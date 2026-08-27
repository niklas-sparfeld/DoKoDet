@preconcurrency import AVFoundation
import CoreImage
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation

/// The encoded bytes and manifest for one complete video snippet.
public struct PackagedEvidenceVideo: Sendable {
    public let manifest: EvidenceVideoSnippetManifest
    public let mp4Data: Data

    public init(manifest: EvidenceVideoSnippetManifest, mp4Data: Data) {
        self.manifest = manifest
        self.mp4Data = mp4Data
    }
}

public protocol EvidenceVideoSnippetProviding: Sendable {
    func capture(eventTimestamp: CMTime) throws -> PackagedEvidenceVideo
}

public enum EvidenceVideoSnippetCaptureError: LocalizedError, Equatable {
    case sourceUnavailable
    case videoTrackMissing
    case invalidSourceDuration
    case requestedRangeUnavailable
    case readerFailed
    case writerFailed
    case noFrames
    case outputTooLarge

    public var errorDescription: String? {
        switch self {
        case .sourceUnavailable:
            return "The replay source could not be read."
        case .videoTrackMissing:
            return "The replay source has no video track."
        case .invalidSourceDuration:
            return "The replay source has no valid duration."
        case .requestedRangeUnavailable:
            return "The replay source does not cover the requested evidence range."
        case .readerFailed:
            return "The replay source could not be decoded."
        case .writerFailed:
            return "The evidence video snippet could not be encoded."
        case .noFrames:
            return "The evidence video snippet contains no frames."
        case .outputTooLarge:
            return "The evidence video snippet exceeds its byte limit."
        }
    }
}

/// Encodes a bounded MP4/H.264 range from a replay source on the caller's queue.
public final class AVAssetVideoSnippetProvider: @unchecked Sendable, EvidenceVideoSnippetProviding {
    public let sourceURL: URL
    public let configuration: EvidenceVideoCaptureMetadata

    private let fileManager = FileManager.default

    public init(
        sourceURL: URL,
        configuration: EvidenceVideoCaptureMetadata = .standard
    ) {
        self.sourceURL = sourceURL
        self.configuration = configuration
    }

    public func capture(eventTimestamp: CMTime) throws -> PackagedEvidenceVideo {
        guard fileManager.isReadableFile(atPath: sourceURL.path) else {
            throw EvidenceVideoSnippetCaptureError.sourceUnavailable
        }

        let asset = AVURLAsset(url: sourceURL)
        guard let track = asset.tracks(withMediaType: .video).first else {
            throw EvidenceVideoSnippetCaptureError.videoTrackMissing
        }
        let eventSeconds = eventTimestamp.seconds
        guard eventSeconds.isFinite else {
            throw EvidenceVideoSnippetCaptureError.requestedRangeUnavailable
        }
        let duration = asset.duration.seconds
        guard duration.isFinite, duration > 0.0 else {
            throw EvidenceVideoSnippetCaptureError.invalidSourceDuration
        }

        let requestedStart = CMTimeAdd(
            eventTimestamp,
            CMTime(value: Int64(configuration.requestedStartOffsetMs), timescale: 1_000)
        )
        let requestedEnd = CMTimeAdd(
            eventTimestamp,
            CMTime(value: Int64(configuration.requestedEndOffsetMs), timescale: 1_000)
        )
        let sourceStart = max(0.0, requestedStart.seconds)
        let sourceEnd = min(duration, requestedEnd.seconds)
        guard sourceEnd > sourceStart,
              sourceStart <= eventSeconds,
              sourceEnd >= eventSeconds else {
            throw EvidenceVideoSnippetCaptureError.requestedRangeUnavailable
        }

        let startOffsetMs = Int(((sourceStart - eventSeconds) * 1_000.0).rounded())
        let requestedDurationMs = Int(((sourceEnd - sourceStart) * 1_000.0).rounded())
        guard requestedDurationMs > 0,
              requestedDurationMs <= configuration.maxDurationMs,
              startOffsetMs <= configuration.requestedStartOffsetMs,
              startOffsetMs + requestedDurationMs >= configuration.requestedEndOffsetMs else {
            throw EvidenceVideoSnippetCaptureError.requestedRangeUnavailable
        }

        let sourceWidth = max(1, Int(abs(track.naturalSize.width.rounded())))
        let sourceHeight = max(1, Int(abs(track.naturalSize.height.rounded())))
        let outputSize = Self.outputSize(
            width: sourceWidth,
            height: sourceHeight,
            maxWidth: configuration.maxWidth,
            maxHeight: configuration.maxHeight
        )
        let sourceFrameRate = track.nominalFrameRate > 0.0
            ? Double(track.nominalFrameRate)
            : configuration.maxNominalFrameRate
        let outputFrameRate = min(sourceFrameRate, configuration.maxNominalFrameRate)
        let outputURL = fileManager.temporaryDirectory
            .appendingPathComponent("evidence-snippet-(UUID().uuidString)", isDirectory: true)
            .appendingPathComponent("snippet.mp4", isDirectory: false)
        let outputDirectory = outputURL.deletingLastPathComponent()
        try fileManager.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
        defer { try? fileManager.removeItem(at: outputDirectory) }

        let frameCount = try encode(
            asset: asset,
            track: track,
            sourceStart: CMTime(seconds: sourceStart, preferredTimescale: 6_000),
            sourceDuration: CMTime(seconds: sourceEnd - sourceStart, preferredTimescale: 6_000),
            outputURL: outputURL,
            width: outputSize.width,
            height: outputSize.height,
            frameRate: outputFrameRate
        )
        guard frameCount > 0 else {
            throw EvidenceVideoSnippetCaptureError.noFrames
        }

        let data: Data
        do {
            data = try Data(contentsOf: outputURL)
        } catch {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        guard data.count <= configuration.maxByteLength else {
            throw EvidenceVideoSnippetCaptureError.outputTooLarge
        }

        let durationMs = max(1, Int(((Double(frameCount) / outputFrameRate) * 1_000.0).rounded()))
        let manifest = EvidenceVideoSnippetManifest(
            partName: "snippet_00",
            startOffsetMs: startOffsetMs,
            endOffsetMs: startOffsetMs + durationMs,
            durationMs: durationMs,
            width: outputSize.width,
            height: outputSize.height,
            nominalFrameRate: outputFrameRate,
            byteLength: data.count,
            sha256: Self.sha256Hex(data)
        )
        return PackagedEvidenceVideo(manifest: manifest, mp4Data: data)
    }

    private func encode(
        asset: AVAsset,
        track: AVAssetTrack,
        sourceStart: CMTime,
        sourceDuration: CMTime,
        outputURL: URL,
        width: Int,
        height: Int,
        frameRate: Double
    ) throws -> Int {
        let reader: AVAssetReader
        do {
            reader = try AVAssetReader(asset: asset)
        } catch {
            throw EvidenceVideoSnippetCaptureError.readerFailed
        }
        reader.timeRange = CMTimeRange(start: sourceStart, duration: sourceDuration)
        let output = AVAssetReaderTrackOutput(
            track: track,
            outputSettings: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            ]
        )
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else {
            throw EvidenceVideoSnippetCaptureError.readerFailed
        }
        reader.add(output)

        let writer: AVAssetWriter
        do {
            writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
        } catch {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        let input = AVAssetWriterInput(
            mediaType: .video,
            outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264,
                AVVideoWidthKey: width,
                AVVideoHeightKey: height,
                AVVideoCompressionPropertiesKey: [
                    AVVideoExpectedSourceFrameRateKey: frameRate,
                    AVVideoAverageBitRateKey: 400_000,
                ],
            ]
        )
        input.expectsMediaDataInRealTime = false
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ]
        )
        guard writer.canAdd(input) else {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        writer.add(input)
        writer.shouldOptimizeForNetworkUse = true
        guard writer.startWriting() else {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        writer.startSession(atSourceTime: .zero)
        guard reader.startReading() else {
            writer.cancelWriting()
            throw EvidenceVideoSnippetCaptureError.readerFailed
        }

        let context = CIContext()
        let pool = Self.makePixelBufferPool(width: width, height: height)
        let frameInterval = CMTime(seconds: 1.0 / frameRate, preferredTimescale: 6_000)
        var nextOutputTime = CMTime.zero
        var frameCount = 0

        while let sampleBuffer = output.copyNextSampleBuffer() {
            guard let sourceBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
                continue
            }
            let sourceTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            let presentationTime = CMTimeSubtract(sourceTime, sourceStart)
            guard presentationTime >= .zero else { continue }
            guard CMTimeCompare(presentationTime, nextOutputTime) >= 0 else { continue }

            let pixelBuffer: CVPixelBuffer
            if CVPixelBufferGetWidth(sourceBuffer) == width,
               CVPixelBufferGetHeight(sourceBuffer) == height {
                pixelBuffer = sourceBuffer
            } else {
                guard let pool,
                      let resized = Self.makePixelBuffer(from: sourceBuffer, pool: pool, context: context, width: width, height: height) else {
                    writer.cancelWriting()
                    throw EvidenceVideoSnippetCaptureError.writerFailed
                }
                pixelBuffer = resized
            }

            while !input.isReadyForMoreMediaData {
                guard writer.status == .writing else {
                    throw EvidenceVideoSnippetCaptureError.writerFailed
                }
                Thread.sleep(forTimeInterval: 0.001)
            }
            guard adaptor.append(pixelBuffer, withPresentationTime: nextOutputTime) else {
                writer.cancelWriting()
                throw EvidenceVideoSnippetCaptureError.writerFailed
            }
            frameCount += 1
            nextOutputTime = CMTimeAdd(nextOutputTime, frameInterval)
        }

        guard reader.status == .completed else {
            writer.cancelWriting()
            throw EvidenceVideoSnippetCaptureError.readerFailed
        }
        input.markAsFinished()
        let finished = DispatchSemaphore(value: 0)
        writer.finishWriting {
            finished.signal()
        }
        guard finished.wait(timeout: .now() + 30) == .success,
              writer.status == .completed else {
            writer.cancelWriting()
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        return frameCount
    }

    private static func outputSize(
        width: Int,
        height: Int,
        maxWidth: Int,
        maxHeight: Int
    ) -> (width: Int, height: Int) {
        let scale = min(1.0, min(Double(maxWidth) / Double(width), Double(maxHeight) / Double(height)))
        var outputWidth = max(2, Int((Double(width) * scale).rounded()))
        var outputHeight = max(2, Int((Double(height) * scale).rounded()))
        outputWidth -= outputWidth % 2
        outputHeight -= outputHeight % 2
        return (max(2, outputWidth), max(2, outputHeight))
    }

    private static func makePixelBufferPool(width: Int, height: Int) -> CVPixelBufferPool? {
        var pool: CVPixelBufferPool?
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:],
        ]
        CVPixelBufferPoolCreate(nil, nil, attributes as CFDictionary, &pool)
        return pool
    }

    private static func makePixelBuffer(
        from source: CVPixelBuffer,
        pool: CVPixelBufferPool,
        context: CIContext,
        width: Int,
        height: Int
    ) -> CVPixelBuffer? {
        var output: CVPixelBuffer?
        guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &output) == kCVReturnSuccess,
              let output else {
            return nil
        }
        let scaleX = CGFloat(width) / CGFloat(CVPixelBufferGetWidth(source))
        let scaleY = CGFloat(height) / CGFloat(CVPixelBufferGetHeight(source))
        let image = CIImage(cvPixelBuffer: source).transformed(
            by: CGAffineTransform(scaleX: scaleX, y: scaleY)
        )
        context.render(
            image,
            to: output,
            bounds: CGRect(x: 0, y: 0, width: width, height: height),
            colorSpace: CGColorSpaceCreateDeviceRGB()
        )
        return output
    }

    private static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
