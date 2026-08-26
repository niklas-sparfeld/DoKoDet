import CoreImage
import CoreMedia
import CoreVideo
import Foundation
import ImageIO

/// One complete frame after JPEG compression.
public struct EncodedEvidenceFrame {
    public let timestamp: CMTime
    public let jpegData: Data
    public let width: Int
    public let height: Int

    public init(timestamp: CMTime, jpegData: Data, width: Int, height: Int) {
        precondition(CMTimeGetSeconds(timestamp).isFinite, "frame timestamp must be finite")
        precondition(!jpegData.isEmpty, "JPEG data must not be empty")
        precondition(width > 0 && height > 0, "frame dimensions must be positive")
        self.timestamp = timestamp
        self.jpegData = jpegData
        self.width = width
        self.height = height
    }
}

/// The result of looking up one configured event-relative target.
public struct EvidenceFrameSelection {
    public let targetOffsetMs: Int
    public let actualOffsetMs: Int?
    public let frame: EncodedEvidenceFrame?

    public init(targetOffsetMs: Int, actualOffsetMs: Int?, frame: EncodedEvidenceFrame?) {
        self.targetOffsetMs = targetOffsetMs
        self.actualOffsetMs = actualOffsetMs
        self.frame = frame
    }

    public var isMissing: Bool {
        frame == nil
    }
}

/// A bounded store of compressed evidence frames.
public final class EvidenceFrameRing {
    private let historyDuration: CMTime
    private let maximumFrameCount: Int
    private let lock = NSLock()
    private var storedFrames: [EncodedEvidenceFrame] = []

    public init(historyDuration: CMTime, maximumFrameCount: Int) {
        precondition(
            CMTimeGetSeconds(historyDuration).isFinite && historyDuration > .zero,
            "history duration must be positive"
        )
        precondition(maximumFrameCount > 0, "maximum frame count must be positive")
        self.historyDuration = historyDuration
        self.maximumFrameCount = maximumFrameCount
        storedFrames.reserveCapacity(maximumFrameCount)
    }

    public convenience init(configuration: EvidenceCaptureConfiguration) {
        self.init(
            historyDuration: configuration.historyDuration,
            maximumFrameCount: configuration.maximumFrameCount
        )
    }

    public var count: Int {
        lock.lock()
        defer { lock.unlock() }
        return storedFrames.count
    }

    public func reset() {
        lock.lock()
        storedFrames.removeAll(keepingCapacity: true)
        lock.unlock()
    }

    public func append(_ frame: EncodedEvidenceFrame) {
        lock.lock()
        defer { lock.unlock() }

        if let last = storedFrames.last,
           CMTimeCompare(frame.timestamp, last.timestamp) < 0 {
            storedFrames.removeAll(keepingCapacity: true)
        }

        storedFrames.append(frame)
        evictFrames(through: frame.timestamp)
    }

    /// Select the nearest stored frame for each event-relative target.
    /// Ties select the earlier frame.
    public func select(
        eventTimestamp: CMTime,
        targetOffsetsMs: [Int],
        maximumLookupDistanceMs: Int
    ) -> [EvidenceFrameSelection] {
        precondition(CMTimeGetSeconds(eventTimestamp).isFinite, "event timestamp must be finite")
        precondition(maximumLookupDistanceMs >= 0, "maximum lookup distance must not be negative")

        lock.lock()
        let frames = storedFrames
        lock.unlock()

        let maximumDistance = CMTime(value: Int64(maximumLookupDistanceMs), timescale: 1_000)
        return targetOffsetsMs.map { targetOffsetMs in
            let targetTime = CMTimeAdd(
                eventTimestamp,
                CMTime(value: Int64(targetOffsetMs), timescale: 1_000)
            )
            let selected = frames.min { left, right in
                let leftDistance = absoluteDistance(from: left.timestamp, to: targetTime)
                let rightDistance = absoluteDistance(from: right.timestamp, to: targetTime)
                if CMTimeCompare(leftDistance, rightDistance) == 0 {
                    return CMTimeCompare(left.timestamp, right.timestamp) < 0
                }
                return CMTimeCompare(leftDistance, rightDistance) < 0
            }

            guard let selected else {
                return EvidenceFrameSelection(
                    targetOffsetMs: targetOffsetMs,
                    actualOffsetMs: nil,
                    frame: nil
                )
            }

            let distance = absoluteDistance(from: selected.timestamp, to: targetTime)
            guard CMTimeCompare(distance, maximumDistance) <= 0 else {
                return EvidenceFrameSelection(
                    targetOffsetMs: targetOffsetMs,
                    actualOffsetMs: nil,
                    frame: nil
                )
            }

            let actualOffsetMs = Int(
                CMTimeConvertScale(
                    CMTimeSubtract(selected.timestamp, eventTimestamp),
                    timescale: 1_000,
                    method: .roundHalfAwayFromZero
                ).value
            )
            return EvidenceFrameSelection(
                targetOffsetMs: targetOffsetMs,
                actualOffsetMs: actualOffsetMs,
                frame: selected
            )
        }
    }

    private func evictFrames(through newestTimestamp: CMTime) {
        let oldestAllowed = CMTimeSubtract(newestTimestamp, historyDuration)
        while storedFrames.count > 1,
              CMTimeCompare(storedFrames[0].timestamp, oldestAllowed) < 0 {
            storedFrames.removeFirst()
        }
        if storedFrames.count > maximumFrameCount {
            storedFrames.removeFirst(storedFrames.count - maximumFrameCount)
        }
    }

    private func absoluteDistance(from left: CMTime, to right: CMTime) -> CMTime {
        let difference = CMTimeSubtract(left, right)
        guard CMTimeCompare(difference, .zero) < 0 else { return difference }
        return CMTime(value: -difference.value, timescale: difference.timescale)
    }
}

public protocol EvidenceFrameEncoding {
    func encode(_ frame: VideoFrame) throws -> EncodedEvidenceFrame
}

public enum EvidenceFrameEncodingError: LocalizedError, Equatable {
    case cannotCreateImage
    case cannotCreateDestination
    case cannotFinalizeDestination

    public var errorDescription: String? {
        switch self {
        case .cannotCreateImage:
            return "The evidence frame image could not be created."
        case .cannotCreateDestination:
            return "The JPEG destination could not be created."
        case .cannotFinalizeDestination:
            return "The JPEG destination could not be finalized."
        }
    }
}

/// Encodes the complete oriented pixel buffer as JPEG data.
public final class JPEGEvidenceFrameEncoder: EvidenceFrameEncoding {
    private let quality: Double
    private let context: CIContext

    public init(quality: Double = 0.85, context: CIContext = CIContext()) {
        precondition(quality.isFinite && (0.0...1.0).contains(quality), "JPEG quality must be in [0, 1]")
        self.quality = quality
        self.context = context
    }

    public func encode(_ frame: VideoFrame) throws -> EncodedEvidenceFrame {
        let orientedImage = CIImage(cvPixelBuffer: frame.pixelBuffer).oriented(frame.orientation)
        guard let cgImage = context.createCGImage(orientedImage, from: orientedImage.extent) else {
            throw EvidenceFrameEncodingError.cannotCreateImage
        }

        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            data,
            "public.jpeg" as CFString,
            1,
            nil
        ) else {
            throw EvidenceFrameEncodingError.cannotCreateDestination
        }

        CGImageDestinationAddImage(
            destination,
            cgImage,
            [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary
        )
        guard CGImageDestinationFinalize(destination) else {
            throw EvidenceFrameEncodingError.cannotFinalizeDestination
        }

        return EncodedEvidenceFrame(
            timestamp: frame.timestamp,
            jpegData: data as Data,
            width: cgImage.width,
            height: cgImage.height
        )
    }
}

public struct EvidenceFrameSamplerMetrics: Equatable {
    public let framesReceived: Int
    public let samplesSkippedForRate: Int
    public let framesDroppedWhileBusy: Int
    public let framesEncoded: Int
    public let encodingFailures: Int

    public init(
        framesReceived: Int,
        samplesSkippedForRate: Int,
        framesDroppedWhileBusy: Int,
        framesEncoded: Int,
        encodingFailures: Int
    ) {
        self.framesReceived = framesReceived
        self.samplesSkippedForRate = samplesSkippedForRate
        self.framesDroppedWhileBusy = framesDroppedWhileBusy
        self.framesEncoded = framesEncoded
        self.encodingFailures = encodingFailures
    }
}

/// Samples frames at a fixed rate and permits only one JPEG encode in flight.
public final class EvidenceFrameSampler: @unchecked Sendable {
    private let configuration: EvidenceCaptureConfiguration
    private let encoder: EvidenceFrameEncoding
    private let encoderQueue = DispatchQueue(label: "com.dokodetector.CardEventProbe.evidence-encoder")
    public let ring: EvidenceFrameRing
    private let lock = NSLock()
    private var lastSampleTimestamp: CMTime?
    private var encodingInFlight = false
    private var stopped = false
    private var generation = 0
    private var framesReceived = 0
    private var samplesSkippedForRate = 0
    private var framesDroppedWhileBusy = 0
    private var framesEncoded = 0
    private var encodingFailures = 0

    public init(
        configuration: EvidenceCaptureConfiguration = EvidenceCaptureConfiguration(),
        encoder: EvidenceFrameEncoding? = nil
    ) {
        self.configuration = configuration
        self.encoder = encoder ?? JPEGEvidenceFrameEncoder(quality: configuration.jpegQuality)
        ring = EvidenceFrameRing(configuration: configuration)
    }

    public var metrics: EvidenceFrameSamplerMetrics {
        lock.lock()
        defer { lock.unlock() }
        return EvidenceFrameSamplerMetrics(
            framesReceived: framesReceived,
            samplesSkippedForRate: samplesSkippedForRate,
            framesDroppedWhileBusy: framesDroppedWhileBusy,
            framesEncoded: framesEncoded,
            encodingFailures: encodingFailures
        )
    }

    public func consume(_ frame: VideoFrame) {
        lock.lock()
        guard !stopped else {
            lock.unlock()
            return
        }

        framesReceived += 1
        let timestamp = frame.timestamp
        guard CMTimeGetSeconds(timestamp).isFinite else {
            lock.unlock()
            return
        }

        if let lastSampleTimestamp,
           CMTimeCompare(timestamp, lastSampleTimestamp) < 0 {
            self.lastSampleTimestamp = nil
        }
        if let lastSampleTimestamp,
           CMTimeCompare(
               CMTimeSubtract(timestamp, lastSampleTimestamp),
               configuration.sampleInterval
           ) < 0 {
            samplesSkippedForRate += 1
            lock.unlock()
            return
        }

        self.lastSampleTimestamp = timestamp
        guard !encodingInFlight else {
            framesDroppedWhileBusy += 1
            lock.unlock()
            return
        }

        encodingInFlight = true
        let taskGeneration = generation
        lock.unlock()

        encoderQueue.async { [weak self] in
            guard let self else { return }
            do {
                let encodedFrame = try self.encoder.encode(frame)
                self.lock.lock()
                self.encodingInFlight = false
                let shouldStore = taskGeneration == self.generation
                if shouldStore {
                    self.ring.append(encodedFrame)
                    self.framesEncoded += 1
                }
                self.lock.unlock()
            } catch {
                self.lock.lock()
                self.encodingInFlight = false
                if taskGeneration == self.generation {
                    self.encodingFailures += 1
                }
                self.lock.unlock()
            }
        }
    }

    public func reset() {
        lock.lock()
        generation += 1
        lastSampleTimestamp = nil
        stopped = false
        framesReceived = 0
        samplesSkippedForRate = 0
        framesDroppedWhileBusy = 0
        framesEncoded = 0
        encodingFailures = 0
        ring.reset()
        lock.unlock()
    }

    public func stop() {
        lock.lock()
        stopped = true
        lock.unlock()
    }
}
