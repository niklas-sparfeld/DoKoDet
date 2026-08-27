@preconcurrency import AVFoundation
import CoreImage
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation

public enum EvidenceVideoCadenceDecision: Equatable, Sendable {
    case accepted(missedTargetCount: Int, didReset: Bool)
    case rateLimited
    case invalidTimestamp
}

/// Selects camera frames against fixed target times without accumulating timestamp drift.
public struct EvidenceVideoCadenceSampler: Sendable {
    public let targetFrameRate: Double

    private let frameInterval: CMTime
    private var nextTargetTimestamp: CMTime?
    private var lastTimestamp: CMTime?

    public init(targetFrameRate: Double) {
        precondition(
            targetFrameRate.isFinite && targetFrameRate > 0.0,
            "video target frame rate must be positive"
        )
        self.targetFrameRate = targetFrameRate
        frameInterval = CMTime(
            seconds: 1.0 / targetFrameRate,
            preferredTimescale: 60_000
        )
    }

    public mutating func reset() {
        nextTargetTimestamp = nil
        lastTimestamp = nil
    }

    public mutating func sample(timestamp: CMTime) -> EvidenceVideoCadenceDecision {
        guard CMTimeGetSeconds(timestamp).isFinite else {
            return .invalidTimestamp
        }

        var didReset = false
        if let lastTimestamp,
           CMTimeCompare(timestamp, lastTimestamp) < 0 {
            nextTargetTimestamp = nil
            didReset = true
        }
        lastTimestamp = timestamp

        guard let nextTargetTimestamp else {
            self.nextTargetTimestamp = CMTimeAdd(timestamp, frameInterval)
            return .accepted(missedTargetCount: 0, didReset: didReset)
        }
        guard CMTimeCompare(timestamp, nextTargetTimestamp) >= 0 else {
            return .rateLimited
        }

        var missedTargetCount = 0
        var nextTarget = nextTargetTimestamp
        while CMTimeCompare(timestamp, nextTarget) >= 0 {
            nextTarget = CMTimeAdd(nextTarget, frameInterval)
            missedTargetCount += 1
        }
        self.nextTargetTimestamp = nextTarget
        return .accepted(
            missedTargetCount: max(0, missedTargetCount - 1),
            didReset: didReset
        )
    }
}

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
    public let acceptedFrameCount: Int
    public let rateLimitedFrameCount: Int
    public let missedTargetTimeCount: Int
    public let framesReplacedBeforeConversion: Int
    public let conversionFailureCount: Int
    public let rollingFrameRate: Double?
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
        acceptedFrameCount: Int = 0,
        rateLimitedFrameCount: Int = 0,
        missedTargetTimeCount: Int = 0,
        framesReplacedBeforeConversion: Int = 0,
        conversionFailureCount: Int = 0,
        rollingFrameRate: Double? = nil,
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
        self.acceptedFrameCount = acceptedFrameCount
        self.rateLimitedFrameCount = rateLimitedFrameCount
        self.missedTargetTimeCount = missedTargetTimeCount
        self.framesReplacedBeforeConversion = framesReplacedBeforeConversion
        self.conversionFailureCount = conversionFailureCount
        self.rollingFrameRate = rollingFrameRate
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
    private var cadenceSampler: EvidenceVideoCadenceSampler
    private let temporaryByteCapacity: Int
    private let maximumBufferedFrameCount: Int
    private let maximumPendingConversionCount: Int
    private let outputPixelBufferPool: CVPixelBufferPool?
    private let conversionQueue = DispatchQueue(
        label: "com.dokodetector.CardEventProbe.live-video-conversion",
        qos: .userInitiated
    )
    private let condition = NSCondition()
    private let context = CIContext()
    private var frames: [BufferedFrame] = []
    private var pendingConversions: [VideoFrame] = []
    private var conversionWorkerRunning = false
    private var latestTimestamp: CMTime?
    private var activeEventTimestamps: [CMTime] = []
    private var encodingInFlight = 0
    private var stopped = false
    private var completedCaptureCount = 0
    private var failedCaptureCount = 0
    private var acceptedFrameCount = 0
    private var rateLimitedFrameCount = 0
    private var missedTargetCount = 0
    private var framesReplacedBeforeConversion = 0
    private var conversionFailureCount = 0
    private var lastFailureReason: String?

    public init(
        configuration: EvidenceVideoCaptureMetadata = .standard,
        minimumCoverageStartOffsetMs: Int = -800,
        maximumCoverageEndOffsetMs: Int = 700,
        temporaryByteCapacity: Int = 40 * 1024 * 1024,
        maximumPendingConversionCount: Int = 4
    ) {
        precondition(
            minimumCoverageStartOffsetMs < maximumCoverageEndOffsetMs,
            "live video coverage must be an ordered range"
        )
        precondition(temporaryByteCapacity > 0, "temporary video capacity must be positive")
        precondition(maximumPendingConversionCount > 0, "pending conversion capacity must be positive")
        self.configuration = configuration
        self.minimumCoverageStartOffsetMs = minimumCoverageStartOffsetMs
        self.maximumCoverageEndOffsetMs = maximumCoverageEndOffsetMs
        cadenceSampler = EvidenceVideoCadenceSampler(
            targetFrameRate: configuration.maxNominalFrameRate
        )
        self.temporaryByteCapacity = temporaryByteCapacity
        self.maximumPendingConversionCount = maximumPendingConversionCount
        let bytesPerFrame = max(1, configuration.maxWidth * configuration.maxHeight * 4)
        maximumBufferedFrameCount = min(
            max(1, Int(ceil(Double(configuration.maxDurationMs) / 1_000.0 * configuration.maxNominalFrameRate)) + 1),
            max(1, temporaryByteCapacity / bytesPerFrame - maximumPendingConversionCount)
        )
        outputPixelBufferPool = Self.makePixelBufferPool(
            width: configuration.maxWidth,
            height: configuration.maxHeight
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
            condition.unlock()
            return
        }
        let decision = cadenceSampler.sample(timestamp: timestamp)
        guard case let .accepted(missedTargetCount, _) = decision else {
            if case .rateLimited = decision {
                rateLimitedFrameCount += 1
            }
            condition.unlock()
            return
        }
        self.missedTargetCount += missedTargetCount
        if pendingConversions.count >= maximumPendingConversionCount {
            pendingConversions.removeFirst()
            framesReplacedBeforeConversion += 1
        }
        pendingConversions.append(frame)
        let shouldStartWorker = !conversionWorkerRunning
        conversionWorkerRunning = true
        condition.unlock()

        if shouldStartWorker {
            conversionQueue.async { [weak self] in
                self?.drainConversionQueue()
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
            let encodedMedia = try encode(selectedFrames)
            guard encodedMedia.data.count <= configuration.maxByteLength else {
                throw EvidenceVideoSnippetCaptureError.outputTooLarge
            }
            let startOffsetMs = Int(
                (CMTimeGetSeconds(CMTimeSubtract(first.timestamp, eventTimestamp)) * 1_000.0).rounded()
            )
            let durationMs = encodedMedia.durationMs
            let manifest = EvidenceVideoSnippetManifest(
                partName: "snippet_00",
                startOffsetMs: startOffsetMs,
                endOffsetMs: startOffsetMs + durationMs,
                durationMs: durationMs,
                width: encodedMedia.width,
                height: encodedMedia.height,
                nominalFrameRate: encodedMedia.frameRate,
                byteLength: encodedMedia.data.count,
                sha256: Self.sha256Hex(encodedMedia.data)
            )
            didComplete = true
            return PackagedEvidenceVideo(manifest: manifest, mp4Data: encodedMedia.data)
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
        pendingConversions.removeAll(keepingCapacity: false)
        frames.removeAll(keepingCapacity: false)
        condition.broadcast()
        condition.unlock()
    }

    private func append(pixelBuffer: CVPixelBuffer, timestamp: CMTime) {
        condition.lock()
        guard !stopped else {
            condition.broadcast()
            condition.unlock()
            return
        }
        if let previous = frames.last, CMTimeCompare(timestamp, previous.timestamp) < 0 {
            frames.removeAll(keepingCapacity: true)
        }
        frames.append(BufferedFrame(timestamp: timestamp, pixelBuffer: pixelBuffer))
        acceptedFrameCount += 1
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

    private func drainConversionQueue() {
        while true {
            condition.lock()
            guard !stopped, !pendingConversions.isEmpty else {
                conversionWorkerRunning = false
                condition.broadcast()
                condition.unlock()
                return
            }
            let frame = pendingConversions.removeFirst()
            condition.unlock()

            do {
                let pixelBuffer = try makeOutputPixelBuffer(from: frame.pixelBuffer)
                append(pixelBuffer: pixelBuffer, timestamp: frame.timestamp)
            } catch {
                condition.lock()
                conversionFailureCount += 1
                lastFailureReason = error.localizedDescription
                condition.broadcast()
                condition.unlock()
            }
        }
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
        let rollingFrameRate: Double?
        if let first = frames.first,
           let last = frames.last,
           frames.count > 1 {
            let duration = CMTimeGetSeconds(CMTimeSubtract(last.timestamp, first.timestamp))
            rollingFrameRate = duration > 0.0 ? Double(frames.count - 1) / duration : nil
        } else {
            rollingFrameRate = nil
        }
        let framesDropped = rateLimitedFrameCount
            + framesReplacedBeforeConversion
            + conversionFailureCount
        return EvidenceVideoCaptureStatus(
            state: state,
            bufferedFrameCount: frames.count,
            bufferedDurationMs: durationMs,
            temporaryBytes: (frames.count + pendingConversions.count) * bytesPerFrame,
            temporaryByteCapacity: temporaryByteCapacity,
            activeCaptureCount: activeEventTimestamps.count,
            completedCaptureCount: completedCaptureCount,
            failedCaptureCount: failedCaptureCount,
            framesDropped: framesDropped,
            acceptedFrameCount: acceptedFrameCount,
            rateLimitedFrameCount: rateLimitedFrameCount,
            missedTargetTimeCount: missedTargetCount,
            framesReplacedBeforeConversion: framesReplacedBeforeConversion,
            conversionFailureCount: conversionFailureCount,
            rollingFrameRate: rollingFrameRate,
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
        guard let outputPixelBufferPool,
              CVPixelBufferPoolCreatePixelBuffer(nil, outputPixelBufferPool, &output) == kCVReturnSuccess,
              let output else {
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

    private static func makePixelBufferPool(width: Int, height: Int) -> CVPixelBufferPool? {
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:],
        ]
        var pool: CVPixelBufferPool?
        guard CVPixelBufferPoolCreate(nil, nil, attributes as CFDictionary, &pool) == kCVReturnSuccess else {
            return nil
        }
        return pool
    }

    private struct EncodedMedia {
        let data: Data
        let width: Int
        let height: Int
        let frameRate: Double
        let durationMs: Int
    }

    private func encode(_ frames: [BufferedFrame]) throws -> EncodedMedia {
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
        let asset = AVURLAsset(url: outputURL)
        guard let track = asset.tracks(withMediaType: .video).first else {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        let duration = asset.duration.seconds
        guard duration.isFinite, duration > 0.0 else {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        let frameRate = track.nominalFrameRate > 0.0
            ? Double(track.nominalFrameRate)
            : Double(frames.count) / duration
        guard frameRate.isFinite, frameRate > 0.0 else {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
        do {
            return EncodedMedia(
                data: try Data(contentsOf: outputURL),
                width: max(1, Int(abs(track.naturalSize.width.rounded()))),
                height: max(1, Int(abs(track.naturalSize.height.rounded()))),
                frameRate: frameRate,
                durationMs: max(1, Int((duration * 1_000.0).rounded()))
            )
        } catch {
            throw EvidenceVideoSnippetCaptureError.writerFailed
        }
    }

    private static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
