import CoreMedia
import CoreVideo
import CryptoKit
import Foundation
import ImageIO

public let evidencePackageSchemaVersion = "cardevent-evidence/v1"

/// Maps media timestamps to one session-relative timeline and UTC dates.
public final class EvidenceSessionClock: @unchecked Sendable {
    public let startedAtUTC: Date

    private let lock = NSLock()
    private var sourceTimestamp: CMTime?

    public init(startedAtUTC: Date = Date()) {
        self.startedAtUTC = startedAtUTC
    }

    @discardableResult
    public func observe(_ timestamp: CMTime) -> CMTime? {
        guard CMTimeGetSeconds(timestamp).isFinite else { return nil }

        lock.lock()
        defer { lock.unlock() }
        if sourceTimestamp == nil {
            sourceTimestamp = timestamp
        }
        guard let sourceTimestamp else { return nil }
        return CMTimeSubtract(timestamp, sourceTimestamp)
    }

    public func elapsedTime(for timestamp: CMTime) -> CMTime? {
        guard CMTimeGetSeconds(timestamp).isFinite else { return nil }

        lock.lock()
        defer { lock.unlock() }
        guard let sourceTimestamp else { return nil }
        return CMTimeSubtract(timestamp, sourceTimestamp)
    }

    public func elapsedMilliseconds(for timestamp: CMTime) -> Int? {
        guard let elapsedTime = elapsedTime(for: timestamp) else { return nil }
        let seconds = CMTimeGetSeconds(elapsedTime)
        guard seconds.isFinite, seconds >= 0.0 else { return nil }
        return Int((seconds * 1_000.0).rounded())
    }

    public func utcDate(for timestamp: CMTime) -> Date? {
        guard let elapsedTime = elapsedTime(for: timestamp) else { return nil }
        let seconds = CMTimeGetSeconds(elapsedTime)
        guard seconds.isFinite else { return nil }
        return startedAtUTC.addingTimeInterval(seconds)
    }
}

public struct EvidencePackageModelMetadata: Codable, Equatable, Sendable {
    public let name: String
    public let version: String
    public let weightsSHA256: String
    public let preprocessing: String

    public init(name: String, version: String, weightsSHA256: String, preprocessing: String) {
        self.name = name
        self.version = version
        self.weightsSHA256 = weightsSHA256
        self.preprocessing = preprocessing
    }

    private enum CodingKeys: String, CodingKey {
        case name
        case version
        case weightsSHA256 = "weights_sha256"
        case preprocessing
    }
}

public struct EvidencePackageCameraMetadata: Codable, Equatable, Sendable {
    public let position: String
    public let orientation: String
    public let width: Int
    public let height: Int

    public init(position: String, orientation: String, width: Int, height: Int) {
        precondition(width > 0 && height > 0, "camera dimensions must be positive")
        self.position = position
        self.orientation = orientation
        self.width = width
        self.height = height
    }

    private enum CodingKeys: String, CodingKey {
        case position
        case orientation
        case width
        case height
    }
}

public struct EvidencePackageClientMetadata: Codable, Equatable, Sendable {
    public let appVersion: String
    public let build: String
    public let deviceModelIdentifier: String
    public let osVersion: String

    public init(
        appVersion: String,
        build: String,
        deviceModelIdentifier: String,
        osVersion: String
    ) {
        self.appVersion = appVersion
        self.build = build
        self.deviceModelIdentifier = deviceModelIdentifier
        self.osVersion = osVersion
    }

    private enum CodingKeys: String, CodingKey {
        case appVersion = "app_version"
        case build
        case deviceModelIdentifier = "device_model_identifier"
        case osVersion = "os_version"
    }
}

public struct EvidenceSessionMetadata: Codable, Equatable, Sendable {
    public let sessionID: UUID
    public let eventSequence: Int

    public init(sessionID: UUID, eventSequence: Int) {
        precondition(eventSequence > 0, "event sequence must be positive")
        self.sessionID = sessionID
        self.eventSequence = eventSequence
    }

    private enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case eventSequence = "event_sequence"
    }
}

public struct EvidenceEventMetadata: Codable, Equatable, Sendable {
    public let eventTimeMs: Int
    public let emittedAtMs: Int
    public let evidenceComplete: Bool

    public init(
        eventTimeMs: Int,
        emittedAtMs: Int,
        evidenceComplete: Bool
    ) {
        precondition(eventTimeMs >= 0, "event time must not be negative")
        precondition(emittedAtMs >= eventTimeMs, "emitted time must not precede event time")
        self.eventTimeMs = eventTimeMs
        self.emittedAtMs = emittedAtMs
        self.evidenceComplete = evidenceComplete
    }

    private enum CodingKeys: String, CodingKey {
        case eventTimeMs = "event_time_ms"
        case emittedAtMs = "emitted_at_ms"
        case evidenceComplete = "evidence_complete"
    }
}

public struct EvidenceEventDecoderMetadata: Codable, Equatable, Sendable {
    public let algorithm: String
    public let threshold: Double
    public let peakConfirmationMs: Int
    public let minimumEventGapMs: Int
    public let targetInferenceHz: Double

    public init(
        algorithm: String,
        threshold: Double,
        peakConfirmationMs: Int,
        minimumEventGapMs: Int,
        targetInferenceHz: Double
    ) {
        self.algorithm = algorithm
        self.threshold = threshold
        self.peakConfirmationMs = peakConfirmationMs
        self.minimumEventGapMs = minimumEventGapMs
        self.targetInferenceHz = targetInferenceHz
    }

    private enum CodingKeys: String, CodingKey {
        case algorithm
        case threshold
        case peakConfirmationMs = "peak_confirmation_ms"
        case minimumEventGapMs = "minimum_event_gap_ms"
        case targetInferenceHz = "target_inference_hz"
    }
}

public struct EvidenceCaptureMetadata: Codable, Equatable, Sendable {
    public let sampleHz: Double
    public let jpegQuality: Double
    public let ringDurationMs: Int
    public let targetOffsetsMs: [Int]
    public let maximumLookupDistanceMs: Int
    public let finalizationDelayMs: Int

    public init(configuration: EvidenceCaptureConfiguration) {
        sampleHz = configuration.targetHz
        jpegQuality = configuration.jpegQuality
        ringDurationMs = Int((configuration.historySeconds * 1_000.0).rounded())
        targetOffsetsMs = configuration.targetOffsetsMs
        maximumLookupDistanceMs = configuration.maximumLookupDistanceMs
        finalizationDelayMs = configuration.finalizationDelayMs
    }

    private enum CodingKeys: String, CodingKey {
        case sampleHz = "sample_hz"
        case jpegQuality = "jpeg_quality"
        case ringDurationMs = "ring_duration_ms"
        case targetOffsetsMs = "target_offsets_ms"
        case maximumLookupDistanceMs = "maximum_lookup_distance_ms"
        case finalizationDelayMs = "finalization_delay_ms"
    }
}

public struct EvidenceFrameManifest: Codable, Equatable, Sendable {
    public let partName: String
    public let targetOffsetMs: Int
    public let actualOffsetMs: Int
    public let sessionElapsedMs: Int
    public let capturedAtUTC: Date
    public let width: Int
    public let height: Int
    public let byteLength: Int
    public let contentType: String
    public let sha256: String

    public init(
        partName: String,
        targetOffsetMs: Int,
        actualOffsetMs: Int,
        sessionElapsedMs: Int,
        capturedAtUTC: Date,
        width: Int,
        height: Int,
        byteLength: Int,
        contentType: String,
        sha256: String
    ) {
        self.partName = partName
        self.targetOffsetMs = targetOffsetMs
        self.actualOffsetMs = actualOffsetMs
        self.sessionElapsedMs = sessionElapsedMs
        self.capturedAtUTC = capturedAtUTC
        self.width = width
        self.height = height
        self.byteLength = byteLength
        self.contentType = contentType
        self.sha256 = sha256
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let capturedAtString = try container.decode(String.self, forKey: .capturedAtUTC)
        guard let capturedAtUTC = parseISO8601Date(capturedAtString) else {
            throw DecodingError.dataCorruptedError(
                forKey: .capturedAtUTC,
                in: container,
                debugDescription: "captured_at_utc must be an ISO-8601 UTC timestamp."
            )
        }
        self.init(
            partName: try container.decode(String.self, forKey: .partName),
            targetOffsetMs: try container.decode(Int.self, forKey: .targetOffsetMs),
            actualOffsetMs: try container.decode(Int.self, forKey: .actualOffsetMs),
            sessionElapsedMs: try container.decode(Int.self, forKey: .sessionElapsedMs),
            capturedAtUTC: capturedAtUTC,
            width: try container.decode(Int.self, forKey: .width),
            height: try container.decode(Int.self, forKey: .height),
            byteLength: try container.decode(Int.self, forKey: .byteLength),
            contentType: try container.decode(String.self, forKey: .contentType),
            sha256: try container.decode(String.self, forKey: .sha256)
        )
    }

    private enum CodingKeys: String, CodingKey {
        case partName = "part_name"
        case targetOffsetMs = "target_offset_ms"
        case actualOffsetMs = "actual_offset_ms"
        case sessionElapsedMs = "session_elapsed_ms"
        case capturedAtUTC = "captured_at_utc"
        case width
        case height
        case byteLength = "byte_length"
        case contentType = "content_type"
        case sha256
    }
}

public struct EvidenceScoreTraceEntry: Codable, Equatable, Sendable {
    public let sessionElapsedMs: Int
    public let score: Double

    public init(sessionElapsedMs: Int, score: Double) {
        self.sessionElapsedMs = sessionElapsedMs
        self.score = score
    }

    private enum CodingKeys: String, CodingKey {
        case sessionElapsedMs = "session_elapsed_ms"
        case score
    }
}

public struct EvidencePackageManifest: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let packageID: UUID
    public let session: EvidenceSessionMetadata
    public let event: EvidenceEventMetadata
    public let model: EvidencePackageModelMetadata
    public let eventDecoder: EvidenceEventDecoderMetadata
    public let evidenceCapture: EvidenceCaptureMetadata
    public let camera: EvidencePackageCameraMetadata
    public let frames: [EvidenceFrameManifest]
    public let missingFrameTargetsMs: [Int]
    public let scoreTrace: [EvidenceScoreTraceEntry]
    public let client: EvidencePackageClientMetadata

    public init(
        packageID: UUID,
        session: EvidenceSessionMetadata,
        event: EvidenceEventMetadata,
        model: EvidencePackageModelMetadata,
        eventDecoder: EvidenceEventDecoderMetadata,
        evidenceCapture: EvidenceCaptureMetadata,
        camera: EvidencePackageCameraMetadata,
        frames: [EvidenceFrameManifest],
        missingFrameTargetsMs: [Int],
        scoreTrace: [EvidenceScoreTraceEntry],
        client: EvidencePackageClientMetadata,
        schemaVersion: String = evidencePackageSchemaVersion
    ) {
        self.schemaVersion = schemaVersion
        self.packageID = packageID
        self.session = session
        self.event = event
        self.model = model
        self.eventDecoder = eventDecoder
        self.evidenceCapture = evidenceCapture
        self.camera = camera
        self.frames = frames
        self.missingFrameTargetsMs = missingFrameTargetsMs
        self.scoreTrace = scoreTrace
        self.client = client
    }

    public func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(iso8601String(from: date))
        }
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(self)
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case packageID = "package_id"
        case session
        case event
        case model
        case eventDecoder = "event_decoder"
        case evidenceCapture = "evidence_capture"
        case camera
        case frames
        case missingFrameTargetsMs = "missing_frame_targets_ms"
        case scoreTrace = "score_trace"
        case client
    }
}

public struct PackagedEvidenceFrame: Sendable {
    public let manifest: EvidenceFrameManifest
    public let jpegData: Data

    public init(manifest: EvidenceFrameManifest, jpegData: Data) {
        self.manifest = manifest
        self.jpegData = jpegData
    }
}

public enum EvidencePackageError: LocalizedError, Equatable {
    case invalidFrameCount
    case duplicateFrameTarget(Int)
    case duplicateFramePart(String)
    case invalidFramePart(String)
    case frameTargetSetMismatch
    case frameDataMismatch(String)
    case invalidSessionTime

    public var errorDescription: String? {
        switch self {
        case .invalidFrameCount:
            return "The evidence package frame count is invalid."
        case let .duplicateFrameTarget(target):
            return "The evidence package contains target offset \(target) more than once."
        case let .duplicateFramePart(part):
            return "The evidence package contains part \(part) more than once."
        case let .invalidFramePart(part):
            return "The evidence package contains an unsafe part name: \(part)."
        case .frameTargetSetMismatch:
            return "The evidence package present and missing targets do not match its configuration."
        case let .frameDataMismatch(part):
            return "The evidence package data does not match frame \(part)'s manifest."
        case .invalidSessionTime:
            return "The evidence package contains a timestamp outside the session timeline."
        }
    }
}

/// An immutable package. It contains compressed bytes only.
public struct EvidencePackage: Sendable {
    public let manifest: EvidencePackageManifest
    public let frames: [PackagedEvidenceFrame]

    public init(manifest: EvidencePackageManifest, frames: [PackagedEvidenceFrame]) throws {
        guard frames.count == manifest.frames.count else {
            throw EvidencePackageError.invalidFrameCount
        }

        var frameTargets = Set<Int>()
        var frameParts = Set<String>()
        for frame in frames {
            guard Self.isSafePartName(frame.manifest.partName) else {
                throw EvidencePackageError.invalidFramePart(frame.manifest.partName)
            }
            guard manifest.frames.contains(frame.manifest) else {
                throw EvidencePackageError.frameDataMismatch(frame.manifest.partName)
            }
            guard frame.manifest.byteLength == frame.jpegData.count,
                  frame.manifest.contentType == "image/jpeg",
                  frame.manifest.width > 0,
                  frame.manifest.height > 0,
                  frame.manifest.sessionElapsedMs >= 0,
                  sha256Hex(frame.jpegData) == frame.manifest.sha256 else {
                throw EvidencePackageError.frameDataMismatch(frame.manifest.partName)
            }
            guard frameTargets.insert(frame.manifest.targetOffsetMs).inserted else {
                throw EvidencePackageError.duplicateFrameTarget(frame.manifest.targetOffsetMs)
            }
            guard frameParts.insert(frame.manifest.partName).inserted else {
                throw EvidencePackageError.duplicateFramePart(frame.manifest.partName)
            }
        }

        let configuredTargets = Set(manifest.evidenceCapture.targetOffsetsMs)
        let missingTargets = Set(manifest.missingFrameTargetsMs)
        guard frameTargets.isDisjoint(with: missingTargets),
              frameTargets.union(missingTargets) == configuredTargets,
              manifest.event.evidenceComplete == missingTargets.isEmpty else {
            throw EvidencePackageError.frameTargetSetMismatch
        }

        self.manifest = manifest
        self.frames = frames
    }

    private static func isSafePartName(_ partName: String) -> Bool {
        guard partName.count <= 64,
              let first = partName.unicodeScalars.first,
              isASCII(first),
              isLetterOrNumber(first) else {
            return false
        }
        return partName.unicodeScalars.dropFirst().allSatisfy { scalar in
            isASCII(scalar) && (isLetterOrNumber(scalar) || scalar.value == 0x2E || scalar.value == 0x5F || scalar.value == 0x2D)
        }
    }

    private static func isASCII(_ scalar: Unicode.Scalar) -> Bool {
        scalar.value <= 0x7F
    }

    private static func isLetterOrNumber(_ scalar: Unicode.Scalar) -> Bool {
        (0x30...0x39).contains(scalar.value)
            || (0x41...0x5A).contains(scalar.value)
            || (0x61...0x7A).contains(scalar.value)
    }
}

/// Builds one package from an event and the compressed evidence ring.
public struct EvidencePackageAssembler: Sendable {
    private let configuration: EvidenceCaptureConfiguration
    private let sessionClock: EvidenceSessionClock
    private let sessionID: UUID
    private let model: EvidencePackageModelMetadata
    private let decoderConfiguration: CausalEventDecoder.Configuration
    private let targetInferenceHz: Double
    private let client: EvidencePackageClientMetadata

    public init(
        configuration: EvidenceCaptureConfiguration,
        sessionClock: EvidenceSessionClock,
        sessionID: UUID,
        model: EvidencePackageModelMetadata,
        decoderConfiguration: CausalEventDecoder.Configuration,
        client: EvidencePackageClientMetadata,
        targetInferenceHz: Double = 8.0
    ) {
        self.configuration = configuration
        self.sessionClock = sessionClock
        self.sessionID = sessionID
        self.model = model
        self.decoderConfiguration = decoderConfiguration
        precondition(targetInferenceHz > 0.0, "target inference rate must be positive")
        self.targetInferenceHz = targetInferenceHz
        self.client = client
    }

    public func assemble(
        event: DetectionEvent,
        eventSequence: Int,
        packageID: UUID = UUID(),
        ring: EvidenceFrameRing,
        camera: EvidencePackageCameraMetadata,
        scoreTrace: [ModelPrediction] = []
    ) throws -> EvidencePackage {
        if sessionClock.elapsedTime(for: event.timestamp) == nil {
            sessionClock.observe(event.timestamp)
        }
        guard eventSequence > 0,
              let eventTimeMs = sessionClock.elapsedMilliseconds(for: event.timestamp),
              let emittedAtMs = sessionClock.elapsedMilliseconds(for: event.emittedAt),
              emittedAtMs >= eventTimeMs else {
            throw EvidencePackageError.invalidSessionTime
        }

        let selections = ring.select(
            eventTimestamp: event.timestamp,
            targetOffsetsMs: configuration.targetOffsetsMs,
            maximumLookupDistanceMs: configuration.maximumLookupDistanceMs
        )
        var packagedFrames: [PackagedEvidenceFrame] = []
        var missingTargets: [Int] = []

        for (index, selection) in selections.enumerated() {
            guard let frame = selection.frame,
                  let sessionElapsedMs = sessionClock.elapsedMilliseconds(for: frame.timestamp),
                  let capturedAtUTC = sessionClock.utcDate(for: frame.timestamp) else {
                missingTargets.append(selection.targetOffsetMs)
                continue
            }

            let partName = String(format: "frame_%02d", index)
            let manifest = EvidenceFrameManifest(
                partName: partName,
                targetOffsetMs: selection.targetOffsetMs,
                actualOffsetMs: selection.actualOffsetMs ?? 0,
                sessionElapsedMs: sessionElapsedMs,
                capturedAtUTC: capturedAtUTC,
                width: frame.width,
                height: frame.height,
                byteLength: frame.jpegData.count,
                contentType: "image/jpeg",
                sha256: sha256Hex(frame.jpegData)
            )
            packagedFrames.append(
                PackagedEvidenceFrame(manifest: manifest, jpegData: frame.jpegData)
            )
        }

        let trace = scoreTrace.compactMap { prediction -> EvidenceScoreTraceEntry? in
            guard let sessionElapsedMs = sessionClock.elapsedMilliseconds(for: prediction.timestamp) else {
                return nil
            }
            return EvidenceScoreTraceEntry(
                sessionElapsedMs: sessionElapsedMs,
                score: prediction.cardEventProbability
            )
        }
        let manifest = EvidencePackageManifest(
            packageID: packageID,
            session: EvidenceSessionMetadata(sessionID: sessionID, eventSequence: eventSequence),
            event: EvidenceEventMetadata(
                eventTimeMs: eventTimeMs,
                emittedAtMs: emittedAtMs,
                evidenceComplete: missingTargets.isEmpty
            ),
            model: model,
            eventDecoder: EvidenceEventDecoderMetadata(
                algorithm: "causal_peak_v1",
                threshold: decoderConfiguration.threshold,
                peakConfirmationMs: milliseconds(decoderConfiguration.peakConfirmation),
                minimumEventGapMs: milliseconds(decoderConfiguration.minimumEventGap),
                targetInferenceHz: targetInferenceHz
            ),
            evidenceCapture: EvidenceCaptureMetadata(configuration: configuration),
            camera: camera,
            frames: packagedFrames.map(\.manifest),
            missingFrameTargetsMs: missingTargets,
            scoreTrace: trace.sorted { $0.sessionElapsedMs < $1.sessionElapsedMs },
            client: client
        )
        return try EvidencePackage(manifest: manifest, frames: packagedFrames)
    }

    private func milliseconds(_ time: CMTime) -> Int {
        max(0, Int((CMTimeGetSeconds(time) * 1_000.0).rounded()))
    }
}

public final class EvidencePackageStore: @unchecked Sendable {
    public let root: URL

    public init(root: URL) {
        self.root = root
    }

    public func packageURL(for packageID: UUID) -> URL {
        root.appendingPathComponent(packageID.uuidString, isDirectory: true)
    }

    /// Writes a package below a staging directory, then renames it into place.
    @discardableResult
    public func persist(_ package: EvidencePackage) throws -> URL {
        let manifestData: Data
        do {
            manifestData = try package.manifest.encoded()
        } catch {
            throw EvidencePackageStoreError.writeFailed(root, error.localizedDescription)
        }

        let fileManager = FileManager.default
        let finalURL = packageURL(for: package.manifest.packageID)
        if fileManager.fileExists(atPath: finalURL.path) {
            throw EvidencePackageStoreError.packageAlreadyExists(finalURL)
        }

        let stagingURL = root.appendingPathComponent(
            ".staging-\(package.manifest.packageID.uuidString)-\(UUID().uuidString)",
            isDirectory: true
        )
        do {
            try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: stagingURL, withIntermediateDirectories: false)
            try fileManager.createDirectory(
                at: stagingURL.appendingPathComponent("frames", isDirectory: true),
                withIntermediateDirectories: false
            )
            try manifestData.write(
                to: stagingURL.appendingPathComponent("manifest.json"),
                options: .atomic
            )
            for frame in package.frames {
                try frame.jpegData.write(
                    to: stagingURL
                        .appendingPathComponent("frames", isDirectory: true)
                        .appendingPathComponent("\(frame.manifest.partName).jpg"),
                    options: .atomic
                )
            }
            try fileManager.moveItem(at: stagingURL, to: finalURL)
            return finalURL
        } catch let error as EvidencePackageStoreError {
            try? fileManager.removeItem(at: stagingURL)
            throw error
        } catch {
            try? fileManager.removeItem(at: stagingURL)
            if fileManager.fileExists(atPath: finalURL.path) {
                throw EvidencePackageStoreError.packageAlreadyExists(finalURL)
            }
            throw EvidencePackageStoreError.writeFailed(finalURL, error.localizedDescription)
        }
    }
}

public enum EvidencePackageStoreError: LocalizedError, Equatable {
    case packageAlreadyExists(URL)
    case writeFailed(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .packageAlreadyExists(url):
            return "The evidence package already exists at \(url.path)."
        case let .writeFailed(url, message):
            return "The evidence package could not be written at \(url.path): \(message)"
        }
    }
}

private func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

private func iso8601String(from date: Date) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [
        .withInternetDateTime,
        .withDashSeparatorInDate,
        .withColonSeparatorInTime,
        .withFractionalSeconds,
    ]
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    return formatter.string(from: date)
}

private func parseISO8601Date(_ value: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.formatOptions = [
        .withInternetDateTime,
        .withDashSeparatorInDate,
        .withColonSeparatorInTime,
        .withFractionalSeconds,
    ]
    if let date = formatter.date(from: value) {
        return date
    }
    formatter.formatOptions.remove(.withFractionalSeconds)
    return formatter.date(from: value)
}
