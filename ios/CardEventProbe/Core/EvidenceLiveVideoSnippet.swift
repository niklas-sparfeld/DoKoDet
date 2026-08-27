@preconcurrency import AVFoundation
import CoreImage
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation

public enum EvidenceVideoCaptureState: String, Sendable {
    case idle
    case rolling
    case waitingForPostEvent
    case encoding
    case stopped
}

public struct EvidenceVideoCaptureStatus: Equatable, Sendable {
    public let state: EvidenceVideoCaptureState
    public let bufferedFrameCount: Int
    public let bufferedDurationMs: Int
    public let temporaryBytes: Int
    public let temporaryByteCapacity: Int
    public let activeCaptureCount: Int
    public let completedCaptureCount: Int
    public let failedCaptureCount: Int
    public let framesDropped: Int
    public let lastFailureReason: String?

    public init(
        state: EvidenceVideoCaptureState,
        bufferedFrameCount: Int,
        bufferedDurationMs: Int,
        temporaryBytes: Int,
        temporaryByteCapacity: Int,
        activeCaptureCount: Int,
        completedCaptureCount: Int,
        failedCaptureCount: Int,
        framesDropped: Int,
        lastFailureReason: String? = nil
    ) {
        self.state = state
        self.bufferedFrameCount = bufferedFrameCount
        self.bufferedDurationMs = bufferedDurationMs
        self.temporaryBytes = temporaryBytes
        self.temporaryByteCapacity = temporaryByteCapacity
        self.activeCaptureCount = activeCaptureCount
        self.completedCaptureCount = completedCaptureCount
        self.failedCaptureCount = failedCaptureCount
        self.framesDropped = framesDropped
        self.lastFailureReason = lastFailureReason
    }

    public static let idle = EvidenceVideoCaptureStatus(
        state: .idle,
        bufferedFrameCount: 0,
        bufferedDurationMs: 0,
        temporaryBytes: 0,
        temporaryByteCapacity: EvidenceVideoCaptureMetadata.standard.maxByteLength * 160,
        activeCaptureCount: 0,
        completedCaptureCount: 0,
        failedCaptureCount: 0,
        framesDropped: 0
    )
}

public protocol EvidenceVideoFrameConsumer: AnyObject, Sendable {
    func consume(_ frame: VideoFrame)
    func stop()
}

/// Keeps a bounded, resized rolling buffer and encodes one event-relative snippet on request.
/// Frame conversion and MP4 encoding run away from the main thread.
public final class LiveEvidenceVideoSnippetProvider: @unchecked Sendable,
    EvidenceVideoSnippetProviding,
    EvidenceVideoFrameConsumer {
    private struct BufferedFrame {
        let timestamp: CMTime
        let pixelBuffer: CVPixelBuffer
    }

    private let configuration: EvidenceVideoCaptureMetadata
    private let minimumCoverageStartOffsetMs: Int
    private let maximumCoverageEndOffsetMs: Int
    private let frameInterval: CMTime
    private let temporaryByteCapacity: Int
    private let maximumBufferedFrameCount: Int
    private let conversionQueue = DispatchQueue(
        label: "com.dokodetector.CardEventProbe.live-video-conversion"
    )
    private let condition = NSCondition()
    private let context = CIContext()
    private var frames: [BufferedFrame] = []
    private var lastAcceptedTimestamp: CMTime?
    private var latestTimestamp: CMTime?
    private var conversionInFlight = false
    private var activeEventTimestamps: [CMTime] = []
    private var encodingInFlight = 0
    private var stopped = false
    private var completedCaptureCount = 0
    private var failedCaptureCount = 0
    private var framesDropped = 0
    private var lastFailureReason: String?

    public init(
        configuration: EvidenceVideoCaptureMetadata = .standard,
        minimumCoverageStartOffsetMs: Int = -800,
        maximumCoverageEndOffsetMs: Int = 700,
        temporaryByteCapacity: Int = 40 * 1024 * 1024
    ) {
        precondition(
            minimumCoverageStartOffsetMs < maximumCoverageEndOffsetMs,
            "live video coverage must be an ordered range"
        )
        precondition(temporaryByteCapacity > 0, "temporary video capacity must be positive")
        self.configuration = configuration
        self.minimumCoverageStartOffsetMs = minimumCoverageStartOffsetMs
        self.maximumCoverageEndOffsetMs = maximumCoverageEndOffsetMs
        frameInterval = CMTime(
            seconds: 1.0 / configuration.maxNominalFrameRate,
            preferredTimescale: 6_000
        )
        self.temporaryByteCapacity = temporaryByteCapacity
        let bytesPerFrame = max(1, configuration.maxWidth * configuration.maxHeight * 4)
        maximumBufferedFrameCount = min(
            max(1, Int(ceil(Double(configuration.maxDurationMs) / 1_000.0 * configuration.maxNominalFrameRate)) + 1),
            max(1, temporaryByteCapacity / bytesPerFrame)
        )
    }

    public var status: EvidenceVideoCaptureStatus {
        condition.lock()
        defer { condition.unlock() }
        return statusLocked()
    }

    public func consume(_ frame: VideoFrame) {
        let timestamp = frame.timestamp
        condition.lock()
        guard !stopped else {
            condition.unlock()
            return
        }
        guard CMTimeGetSeconds(timestamp).isFinite else {
            framesDropped += 1
            condition.unlock()
            return
        }
        if let lastAcceptedTimestamp,
           CMTimeCompare(CMTimeSubtract(timestamp, lastAcceptedTimestamp), frameInterval) < 0 {
            condition.unlock()
            return
        }
        guard !conversionInFlight else {
            framesDropped += 1
            condition.unlock()
            return
        }
        self.lastAcceptedTimestamp = timestamp
        conversionInFlight = true
        condition.unlock()

        conversionQueue.async { [weak self] in
            guard let self else { return }
            do {
                let pixelBuffer = try self.makeOutputPixelBuffer(from: frame.pixelBuffer)
                self.append(pixelBuffer: pixelBuffer, timestamp: timestamp)
            } catch {
                self.condition.lock()
                self.conversionInFlight = false
                self.framesDropped += 1
                self.lastFailureReason = error.localizedDescription
                self.condition.broadcast()
                self.condition.unlock()
            }
        }
    }

    public func capture(eventTimestamp: CMTime) throws -> PackagedEvidenceVideo {
        guard CMTimeGetSeconds(eventTimestamp).isFinite else {
            throw EvidenceVideoSnippetCaptureError.requestedRangeUnavailable
        }
        let requestedStart = CMTimeAdd(
            eventTimestamp,
            CMTime(value: Int64(configuration.requestedStartOffsetMs), timescale: 1_000)
        )
        let requestedEnd = CMTimeAdd(
            eventTimestamp,
            CMTime(value: Int64(configuration.requestedEndOffsetMs), timescale: 1_000)
        )
        let requiredFrameCount = max(
            1,
            Int(
                ceil(
                    CMTimeGetSeconds(CMTimeSubtract(requestedEnd, requestedStart))
                        * configuration.maxNominalFrameRate
                )
            ) + 1
        )
        guard maximumBufferedFrameCount >= requiredFrameCount else {
            recordFailure(EvidenceVideoSnippetCaptureError.temporaryStorageUnavailable)
            throw EvidenceVideoSnippetCaptureError.temporaryStorageUnavailable
        }

        condition.lock()
        guard !stopped else {
            condition.unlock()
            throw EvidenceVideoSnippetCaptureError.captureStopped
        }
        activeEventTimestamps.append(eventTimestamp)
        condition.broadcast()
        let deadline = Date().addingTimeInterval(3.0)
        while !stopped && !hasFrameThrough(requestedEnd) {
            guard condition.wait(until: deadline) else { break }
        }
        if stopped {
            removeActiveEvent(eventTimestamp)
            condition.unlock()
            recordFailure(EvidenceVideoSnippetCaptureError.captureStopped)
            throw EvidenceVideoSnippetCaptureError.captureStopped
        }
        let selectedFrames = frames.filter { frame in
            CMTimeCompare(frame.timestamp, requestedStart) >= 0
                && CMTimeCompare(frame.timestamp, requestedEnd) <= 0
        }
        removeActiveEvent(eventTimestamp)
        guard let first = selectedFrames.first,
              let last = selectedFrames.last,
              CMTimeCompare(
                  first.timestamp,
                  CMTimeAdd(eventTimestamp, CMTime(value: Int64(minimumCoverageStartOffsetMs), timescale: 1_000))
              ) <= 0,
              CMTimeCompare(
                  last.timestamp,
                  CMTimeAdd(eventTimestamp, CMTime(value: Int64(maximumCoverageEndOffsetMs), timescale: 1_000))
              ) >= 0 else {
            condition.unlock()
            recordFailure(EvidenceVideoSnippetCaptureError.requestedRangeUnavailable)
            throw EvidenceVideoSnippetCaptureError.requestedRangeUnavailable
        }
        encodingInFlight += 1
        condition.unlock()

        var didComplete = false
        defer {
            condition.lock()
            encodingInFlight -= 1
            if didComplete {
                completedCaptureCount += 1
            }
            condition.broadcast()
            condition.unlock()
        }

        do {
            let data = try encode(selectedFrames)
            guard data.count <= configuration.maxByteLength else {
                throw EvidenceVideoSnippetCaptureError.outputTooLarge
            }
            let durationMs = max(
                1,
                Int(
                    ((CMTimeGetSeconds(CMTimeSubtract(last.timestamp, first.timestamp))
                        + CMTimeGetSeconds(frameInterval)) * 1_000.0).rounded()
                )
            )
            let startOffsetMs = Int(
                (CMTimeGetSeconds(CMTimeSubtract(first.timestamp, eventTimestamp)) * 1_000.0).rounded()
            )
            let manifest = EvidenceVideoSnippetManifest(
                partName: "snippet_00",
                startOffsetMs: startOffsetMs,
                endOffsetMs: startOffsetMs + durationMs,
                durationMs: durationMs,
                width: configuration.maxWidth,
                height: configuration.maxHeight,
                nominalFrameRate: configuration.maxNominalFrameRate,
                byteLength: data.count,
                sha256: Self.sha256Hex(data)
            )
            didComplete = true
            return PackagedEvidenceVideo(manifest: manifest, mp4Data: data)
        } catch let error as EvidenceVideoSnippetCaptureError {
            recordFailure(error)
            throw error
        } catch {
            let captureError = EvidenceVideoSnippetCaptureError.writerFailed
            recordFailure(captureError)
            throw captureError
        }
    }

    public func stop() {
        condition.lock()
        stopped = true
        frames.removeAll(keepingCapacity: false)
        condition.broadcast()
        condition.unlock()
    }

    private func append(pixelBuffer: CVPixelBuffer, timestamp: CMTime) {
        condition.lock()
        conversionInFlight = false
        guard !stopped else {
            condition.broadcast()
            condition.unlock()
            return
        }
        if let previous = frames.last, CMTimeCompare(timestamp, previous.timestamp) < 0 {
            frames.removeAll(keepingCapacity: true)
        }
        frames.append(BufferedFrame(timestamp: timestamp, pixelBuffer: pixelBuffer))
        latestTimestamp = timestamp
        let retentionStart = activeEventTimestamps.map {
            CMTimeAdd($0, CMTime(value: Int64(configuration.requestedStartOffsetMs), timescale: 1_000))
        }.min() ?? CMTimeSubtract(timestamp, CMTime(seconds: Double(configuration.maxDurationMs) / 1_000.0, preferredTimescale: 6_000))
        frames.removeAll { CMTimeCompare($0.timestamp, retentionStart) < 0 }
        if frames.count > maximumBufferedFrameCount {
            frames.removeFirst(frames.count - maximumBufferedFrameCount)
        }
        condition.broadcast()
        condition.unlock()
    }

    private func hasFrameThrough(_ timestamp: CMTime) -> Bool {
        guard let latestTimestamp else { return false }
        return CMTimeCompare(latestTimestamp, timestamp) >= 0
    }

    private func removeActiveEvent(_ timestamp: CMTime) {
        if let index = activeEventTimestamps.firstIndex(where: {
            CMTimeCompare($0, timestamp) == 0
        }) {
            activeEventTimestamps.remove(at: index)
        }
    }

    private func statusLocked() -> EvidenceVideoCaptureStatus {
        let state: EvidenceVideoCaptureState
        if stopped {
            state = .stopped
        } else if encodingInFlight > 0 {
            state = .encoding
        } else if !activeEventTimestamps.isEmpty {
            state = .waitingForPostEvent
        } else if !frames.isEmpty {
            state = .rolling
        } else {
            state = .idle
        }
        let durationMs: Int
        if let first = frames.first, let last = frames.last {
            durationMs = max(0, Int((CMTimeGetSeconds(CMTimeSubtract(last.timestamp, first.timestamp)) * 1_000.0).rounded()))
        } else {
            durationMs = 0
        }
        let bytesPerFrame = configuration.maxWidth * configuration.maxHeight * 4
        return EvidenceVideoCaptureStatus(
            state: state,
            bufferedFrameCount: frames.count,
            bufferedDurationMs: durationMs,
            temporaryBytes: frames.count * bytesPerFrame,
            temporaryByteCapacity: temporaryByteCapacity,
            activeCaptureCount: activeEventTimestamps.count,
            completedCaptureCount: completedCaptureCount,
            failedCaptureCount: failedCaptureCount,
            framesDropped: framesDropped,
            lastFailureReason: lastFailureReason
        )
    }

    private func recordFailure(_ error: Error) {
        condition.lock()
        failedCaptureCount += 1
        lastFailureReason = error.localizedDescription
        condition.broadcast()
        condition.unlock()
    }

    private func makeOutputPixelBuffer(from source: CVPixelBuffer) throws -> CVPixelBuffer {
        var output: CVPixelBuffer?
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            configuration.maxWidth,
            configuration.maxHeight,
            kCVPixelFormatType_32BGRA,
            nil,
            &output
        )
        guard status == kCVReturnSuccess, let output else {
            throw EvidenceVideoSnippetCaptureError.temporaryStorageUnavailable
        }
        let image = CIImage(cvPixelBuffer: source)
        let scaleX = CGFloat(configuration.maxWidth) / max(1.0, image.extent.width)
        let scaleY = CGFloat(configuration.maxHeight) / max(1.0, image.extent.height)
        let resized = image.transformed(by: CGAffineTransform(scaleX: scaleX, y: scaleY))
        context.render(
            resized,
            to: output,
            bounds: CGRect(x: 0, y: 0, width: configuration.maxWidth, height: configuration.maxHeight),
            colorSpace: CGColorSpaceCreateDeviceRGB()
        )
        return output
    }

    private func encode(_ frames: [BufferedFrame]) throws -> Data {
        let outputDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("live-evidence-\(UUID().uuidString)", isDirectory: true)
        let outputURL = outputDirectory.appendingPathComponent("snippet.mp4", isDirectory: false)
        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: outputDirectory) }

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
                AVVideoWidthKey: configuration.maxWidth,
                AVVideoHeightKey: configuration.maxHeight,
                AVVideoCompressionPropertiesKey: [
                    AVVideoExpectedSourceFrameRateKey: configuration.maxNominalFrameRate,
                    AVVideoAverageBitRateKey: 400_000,
                ],
            ]
        )
        input.expectsMediaDataInRealTime = false
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
                kCVPixelBufferWidthKey as String: configuration.maxWidth,
                kCVPixelBufferHeightKey as String: configuration.maxHeight,
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
        let firstTimestamp = frames[0].timestamp
        for frame in frames {
            while !input.isReadyForMoreMediaData {
                guard writer.status == .writing else {
                    throw EvidenceVideoSnippetCaptureError.writerFailed
                }
                Thread.sleep(forTimeInterval: 0.001)
            }
            let presentationTime = CMTimeSubtract(frame.timestamp, firstTimestamp)
            guard adaptor.append(frame.pixelBuffer, withPresentationTime: presentationTime) else {
                throw EvidenceVideoSnippetCaptureError.writerFailed
            }
        }
        input.markAsFinished()
        let finished = DispatchSemaphore(value: 0)
        writer.finishWriting { finished.signal() }
        guard finished.wait(timeout: .now() + 30) == .success,
              writer.status == .completed else {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        do {
            return try Data(contentsOf: outputURL)
        } catch {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
    }

    private static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
