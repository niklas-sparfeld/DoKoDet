import CoreMedia
import CoreVideo
import CryptoKit
import Foundation
import ImageIO

public let evidencePackageSchemaVersion = "cardevent-evidence/v1"

/// Maps one monotonic media timeline to session-relative times and UTC dates.
///
/// The first valid media timestamp is the immutable zero point. The UTC anchor is only
/// descriptive metadata and never participates in event/frame alignment.
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

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(sessionID.uuidString.lowercased(), forKey: .sessionID)
        try container.encode(eventSequence, forKey: .eventSequence)
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
        guard capturedAtString.hasSuffix("Z")
                || capturedAtString.hasSuffix("+00:00")
                || capturedAtString.hasSuffix("-00:00") else {
            throw DecodingError.dataCorruptedError(
                forKey: .capturedAtUTC,
                in: container,
                debugDescription: "captured_at_utc must use UTC."
            )
        }
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

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        packageID = try container.decode(UUID.self, forKey: .packageID)
        session = try container.decode(EvidenceSessionMetadata.self, forKey: .session)
        event = try container.decode(EvidenceEventMetadata.self, forKey: .event)
        model = try container.decode(EvidencePackageModelMetadata.self, forKey: .model)
        eventDecoder = try container.decode(EvidenceEventDecoderMetadata.self, forKey: .eventDecoder)
        evidenceCapture = try container.decode(EvidenceCaptureMetadata.self, forKey: .evidenceCapture)
        camera = try container.decode(EvidencePackageCameraMetadata.self, forKey: .camera)
        frames = try container.decode([EvidenceFrameManifest].self, forKey: .frames)
        missingFrameTargetsMs = try container.decode([Int].self, forKey: .missingFrameTargetsMs)
        scoreTrace = try container.decode([EvidenceScoreTraceEntry].self, forKey: .scoreTrace)
        client = try container.decode(EvidencePackageClientMetadata.self, forKey: .client)

        try Self.validate(self, codingPath: decoder.codingPath)
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

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(packageID.uuidString.lowercased(), forKey: .packageID)
        try container.encode(session, forKey: .session)
        try container.encode(event, forKey: .event)
        try container.encode(model, forKey: .model)
        try container.encode(eventDecoder, forKey: .eventDecoder)
        try container.encode(evidenceCapture, forKey: .evidenceCapture)
        try container.encode(camera, forKey: .camera)
        try container.encode(frames, forKey: .frames)
        try container.encode(missingFrameTargetsMs, forKey: .missingFrameTargetsMs)
        try container.encode(scoreTrace, forKey: .scoreTrace)
        try container.encode(client, forKey: .client)
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

    private static func validate(
        _ manifest: EvidencePackageManifest,
        codingPath: [CodingKey]
    ) throws {
        func fail(_ message: String) throws -> Never {
            throw DecodingError.dataCorrupted(
                DecodingError.Context(codingPath: codingPath, debugDescription: message)
            )
        }

        guard manifest.schemaVersion == evidencePackageSchemaVersion else {
            try fail("schema_version is not supported.")
        }
        guard manifest.session.eventSequence > 0 else {
            try fail("session.event_sequence must be positive.")
        }
        guard manifest.event.eventTimeMs >= 0,
              manifest.event.emittedAtMs >= manifest.event.eventTimeMs else {
            try fail("event times must be non-negative and causal.")
        }

        guard manifest.model.name.isEmpty == false,
              manifest.model.version.isEmpty == false,
              manifest.model.preprocessing.isEmpty == false,
              Self.isLowercaseSHA256(manifest.model.weightsSHA256),
              manifest.client.appVersion.isEmpty == false,
              manifest.client.build.isEmpty == false,
              manifest.client.deviceModelIdentifier.isEmpty == false,
              manifest.client.osVersion.isEmpty == false else {
            try fail("model and client metadata must contain valid values.")
        }

        let decoder = manifest.eventDecoder
        guard decoder.algorithm.isEmpty == false,
              decoder.threshold.isFinite,
              (0.0...1.0).contains(decoder.threshold),
              decoder.peakConfirmationMs >= 0,
              decoder.minimumEventGapMs >= 0,
              decoder.targetInferenceHz.isFinite,
              decoder.targetInferenceHz > 0.0 else {
            try fail("event_decoder contains an invalid value.")
        }

        let capture = manifest.evidenceCapture
        guard capture.sampleHz.isFinite,
              capture.sampleHz > 0.0,
              capture.jpegQuality.isFinite,
              capture.jpegQuality > 0.0,
              capture.jpegQuality <= 1.0,
              capture.ringDurationMs > 0,
              capture.maximumLookupDistanceMs >= 0,
              capture.finalizationDelayMs >= 0,
              capture.targetOffsetsMs.isEmpty == false,
              Set(capture.targetOffsetsMs).count == capture.targetOffsetsMs.count else {
            try fail("evidence_capture contains an invalid value.")
        }

        guard manifest.camera.position == "back" || manifest.camera.position == "front",
              manifest.camera.orientation.isEmpty == false,
              manifest.camera.width > 0,
              manifest.camera.height > 0 else {
            try fail("camera contains an invalid value.")
        }

        var frameParts = Set<String>()
        var frameTargets = Set<Int>()
        for frame in manifest.frames {
            guard Self.isSafePartName(frame.partName),
                  frameParts.insert(frame.partName).inserted else {
                try fail("frames.part_name values must be safe and unique.")
            }
            guard frameTargets.insert(frame.targetOffsetMs).inserted else {
                try fail("frames target offsets must be unique.")
            }
            guard frame.sessionElapsedMs >= 0,
                  frame.width > 0,
                  frame.height > 0,
                  frame.byteLength > 0,
                  frame.contentType == "image/jpeg",
                  Self.isLowercaseSHA256(frame.sha256) else {
                try fail("frames contains an invalid value.")
            }
        }

        let missingTargets = Set(manifest.missingFrameTargetsMs)
        guard missingTargets.count == manifest.missingFrameTargetsMs.count,
              frameTargets.isDisjoint(with: missingTargets),
              frameTargets.union(missingTargets) == Set(capture.targetOffsetsMs),
              manifest.event.evidenceComplete == missingTargets.isEmpty else {
            try fail("present and missing frame targets must match the configured target set.")
        }

        var previousTraceTime: Int?
        for entry in manifest.scoreTrace {
            guard entry.sessionElapsedMs >= 0,
                  entry.score.isFinite,
                  (0.0...1.0).contains(entry.score),
                  previousTraceTime.map({ entry.sessionElapsedMs >= $0 }) ?? true else {
                try fail("score_trace must contain ordered finite scores.")
            }
            previousTraceTime = entry.sessionElapsedMs
        }
    }

    private static func isLowercaseSHA256(_ value: String) -> Bool {
        value.count == 64 && value.unicodeScalars.allSatisfy { scalar in
            (0x30...0x39).contains(scalar.value) || (0x61...0x66).contains(scalar.value)
        }
    }

    private static func isSafePartName(_ partName: String) -> Bool {
        guard partName.count <= 64,
              let first = partName.unicodeScalars.first,
              isASCII(first),
              isLetterOrNumber(first) else {
            return false
        }
        return partName.unicodeScalars.dropFirst().allSatisfy { scalar in
            isASCII(scalar)
                && (isLetterOrNumber(scalar) || scalar.value == 0x2E || scalar.value == 0x5F || scalar.value == 0x2D)
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

public enum EvidencePackageQueueState: String, CaseIterable, Codable, Sendable {
    case staging
    case queued
    case acknowledged
    case failed
    case corrupt
}

public struct EvidencePackageQueueDiagnostics: Equatable, Sendable {
    public let stagingCount: Int
    public let queuedCount: Int
    public let acknowledgedCount: Int
    public let failedCount: Int
    public let corruptCount: Int
    public let recoveredPackageIDs: [UUID]
    public let corruptPaths: [String]
    public let errors: [String]

    public init(
        stagingCount: Int,
        queuedCount: Int,
        acknowledgedCount: Int,
        failedCount: Int,
        corruptCount: Int,
        recoveredPackageIDs: [UUID] = [],
        corruptPaths: [String] = [],
        errors: [String] = []
    ) {
        self.stagingCount = stagingCount
        self.queuedCount = queuedCount
        self.acknowledgedCount = acknowledgedCount
        self.failedCount = failedCount
        self.corruptCount = corruptCount
        self.recoveredPackageIDs = recoveredPackageIDs
        self.corruptPaths = corruptPaths
        self.errors = errors
    }
}

public final class EvidencePackageStore: @unchecked Sendable {
    public let root: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()
    private var storedDiagnostics = EvidencePackageQueueDiagnostics(
        stagingCount: 0,
        queuedCount: 0,
        acknowledgedCount: 0,
        failedCount: 0,
        corruptCount: 0
    )

    public init(root: URL) {
        self.root = root
    }

    public var diagnostics: EvidencePackageQueueDiagnostics {
        lock.lock()
        defer { lock.unlock() }
        return storedDiagnostics
    }

    public func directoryURL(for state: EvidencePackageQueueState) -> URL {
        root.appendingPathComponent(state.rawValue, isDirectory: true)
    }

    public func packageURL(for packageID: UUID) -> URL {
        packageURL(for: packageID, in: .queued)
    }

    public func packageURL(
        for packageID: UUID,
        in state: EvidencePackageQueueState
    ) -> URL {
        directoryURL(for: state)
            .appendingPathComponent(packageID.uuidString.lowercased(), isDirectory: true)
    }

    /// Writes a package below staging, validates it from disk, then atomically queues it.
    @discardableResult
    public func persist(_ package: EvidencePackage) throws -> URL {
        lock.lock()
        defer { lock.unlock() }

        let manifestData: Data
        do {
            manifestData = try package.manifest.encoded()
        } catch {
            throw EvidencePackageStoreError.writeFailed(root, error.localizedDescription)
        }

        try ensureLayoutLocked()
        let finalURL = packageURL(for: package.manifest.packageID)
        if fileManager.fileExists(atPath: finalURL.path) {
            throw EvidencePackageStoreError.packageAlreadyExists(finalURL)
        }

        let stagingURL = directoryURL(for: .staging).appendingPathComponent(
            "\(package.manifest.packageID.uuidString.lowercased())-\(UUID().uuidString.lowercased())",
            isDirectory: true
        )
        do {
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

            _ = try loadPackageLocked(at: stagingURL)
            try fileManager.moveItem(at: stagingURL, to: finalURL)
            storedDiagnostics = makeDiagnosticsLocked()
            return finalURL
        } catch let error as EvidencePackageStoreError {
            throw error
        } catch {
            if fileManager.fileExists(atPath: finalURL.path) {
                throw EvidencePackageStoreError.packageAlreadyExists(finalURL)
            }
            throw EvidencePackageStoreError.writeFailed(stagingURL, error.localizedDescription)
        }
    }

    /// Rebuilds queue state from package files and retains invalid entries for inspection.
    @discardableResult
    public func recover() throws -> EvidencePackageQueueDiagnostics {
        lock.lock()
        defer { lock.unlock() }

        try ensureLayoutLocked()
        var recoveredPackageIDs: [UUID] = []
        var corruptPaths: [String] = []
        var errors: [String] = []

        for sourceURL in try entriesLocked(in: .staging) {
            do {
                let package = try loadPackageLocked(at: sourceURL)
                let destinationURL = packageURL(for: package.manifest.packageID)
                guard !fileManager.fileExists(atPath: destinationURL.path) else {
                    throw EvidencePackageStoreError.invalidPackage(
                        sourceURL,
                        "a queued package with the same package_id already exists"
                    )
                }
                try fileManager.moveItem(at: sourceURL, to: destinationURL)
                recoveredPackageIDs.append(package.manifest.packageID)
            } catch {
                retainCorruptLocked(
                    sourceURL,
                    error: error,
                    paths: &corruptPaths,
                    errors: &errors
                )
            }
        }

        for sourceURL in try entriesLocked(in: .queued) {
            do {
                _ = try loadQueuedPackageLocked(at: sourceURL)
            } catch {
                retainCorruptLocked(
                    sourceURL,
                    error: error,
                    paths: &corruptPaths,
                    errors: &errors
                )
            }
        }

        storedDiagnostics = makeDiagnosticsLocked(
            recoveredPackageIDs: recoveredPackageIDs,
            corruptPaths: corruptPaths,
            errors: errors
        )
        return storedDiagnostics
    }

    /// Reads and validates one package directory without changing queue state.
    public func loadPackage(at packageURL: URL) throws -> EvidencePackage {
        lock.lock()
        defer { lock.unlock() }
        return try loadPackageLocked(at: packageURL)
    }

    private func ensureLayoutLocked() throws {
        do {
            for state in EvidencePackageQueueState.allCases {
                try fileManager.createDirectory(
                    at: directoryURL(for: state),
                    withIntermediateDirectories: true
                )
            }
        } catch {
            throw EvidencePackageStoreError.writeFailed(root, error.localizedDescription)
        }
    }

    private func entriesLocked(in state: EvidencePackageQueueState) throws -> [URL] {
        do {
            return try fileManager.contentsOfDirectory(
                at: directoryURL(for: state),
                includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
                options: []
            )
        } catch {
            throw EvidencePackageStoreError.writeFailed(
                directoryURL(for: state),
                error.localizedDescription
            )
        }
    }

    private func loadQueuedPackageLocked(at packageURL: URL) throws -> EvidencePackage {
        guard let packageID = UUID(uuidString: packageURL.lastPathComponent) else {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                "queued package directory name is not a UUID"
            )
        }
        let package = try loadPackageLocked(at: packageURL)
        guard package.manifest.packageID == packageID else {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                "package directory name does not match manifest.package_id"
            )
        }
        return package
    }

    private func loadPackageLocked(at packageURL: URL) throws -> EvidencePackage {
        guard isDirectory(packageURL) else {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                "package entry is not a directory"
            )
        }

        let manifestURL = packageURL.appendingPathComponent("manifest.json", isDirectory: false)
        let framesURL = packageURL.appendingPathComponent("frames", isDirectory: true)
        guard isRegularFile(manifestURL), isDirectory(framesURL) else {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                "package must contain manifest.json and a frames directory"
            )
        }

        let packageEntries: [URL]
        do {
            packageEntries = try fileManager.contentsOfDirectory(
                at: packageURL,
                includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
                options: []
            )
        } catch {
            throw EvidencePackageStoreError.invalidPackage(packageURL, error.localizedDescription)
        }
        guard Set(packageEntries.map(\.lastPathComponent)) == Set(["manifest.json", "frames"]) else {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                "package contains an unexpected top-level entry"
            )
        }

        let manifestData: Data
        do {
            manifestData = try Data(contentsOf: manifestURL)
        } catch {
            throw EvidencePackageStoreError.invalidPackage(packageURL, error.localizedDescription)
        }

        let manifest: EvidencePackageManifest
        do {
            manifest = try JSONDecoder().decode(EvidencePackageManifest.self, from: manifestData)
        } catch {
            throw EvidencePackageStoreError.invalidPackage(
                manifestURL,
                error.localizedDescription
            )
        }

        let frameEntries: [URL]
        do {
            frameEntries = try fileManager.contentsOfDirectory(
                at: framesURL,
                includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
                options: []
            )
        } catch {
            throw EvidencePackageStoreError.invalidPackage(framesURL, error.localizedDescription)
        }
        guard frameEntries.allSatisfy({ isRegularFile($0) }) else {
            throw EvidencePackageStoreError.invalidPackage(
                framesURL,
                "frames contains a non-file entry"
            )
        }

        let expectedFrameNames = Set(manifest.frames.map { "\($0.partName).jpg" })
        let actualFrameNames = Set(frameEntries.map(\.lastPathComponent))
        guard expectedFrameNames == actualFrameNames else {
            throw EvidencePackageStoreError.invalidPackage(
                framesURL,
                "frame files do not match manifest.frames"
            )
        }

        var packagedFrames: [PackagedEvidenceFrame] = []
        packagedFrames.reserveCapacity(manifest.frames.count)
        for frameManifest in manifest.frames {
            let frameURL = framesURL.appendingPathComponent(
                "\(frameManifest.partName).jpg",
                isDirectory: false
            )
            let data: Data
            do {
                data = try Data(contentsOf: frameURL)
            } catch {
                throw EvidencePackageStoreError.invalidPackage(
                    frameURL,
                    error.localizedDescription
                )
            }
            guard data.count == frameManifest.byteLength,
                  sha256Hex(data) == frameManifest.sha256 else {
                throw EvidencePackageStoreError.invalidPackage(
                    frameURL,
                    "frame byte length or SHA-256 does not match the manifest"
                )
            }
            packagedFrames.append(
                PackagedEvidenceFrame(manifest: frameManifest, jpegData: data)
            )
        }

        do {
            return try EvidencePackage(manifest: manifest, frames: packagedFrames)
        } catch {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                error.localizedDescription
            )
        }
    }

    private func retainCorruptLocked(
        _ sourceURL: URL,
        error: Error,
        paths: inout [String],
        errors: inout [String]
    ) {
        let message = "\(sourceURL.path): \(error.localizedDescription)"
        errors.append(message)
        let destinationURL = directoryURL(for: .corrupt).appendingPathComponent(
            "\(sourceURL.lastPathComponent)-\(UUID().uuidString.lowercased())",
            isDirectory: isDirectory(sourceURL)
        )
        do {
            try fileManager.moveItem(at: sourceURL, to: destinationURL)
            paths.append(destinationURL.path)
        } catch {
            errors.append(
                "\(sourceURL.path): could not move invalid content to corrupt: \(error.localizedDescription)"
            )
        }
    }

    private func makeDiagnosticsLocked(
        recoveredPackageIDs: [UUID] = [],
        corruptPaths: [String] = [],
        errors: [String] = []
    ) -> EvidencePackageQueueDiagnostics {
        EvidencePackageQueueDiagnostics(
            stagingCount: entryCountLocked(in: .staging),
            queuedCount: entryCountLocked(in: .queued),
            acknowledgedCount: entryCountLocked(in: .acknowledged),
            failedCount: entryCountLocked(in: .failed),
            corruptCount: entryCountLocked(in: .corrupt),
            recoveredPackageIDs: recoveredPackageIDs,
            corruptPaths: corruptPaths,
            errors: errors
        )
    }

    private func entryCountLocked(in state: EvidencePackageQueueState) -> Int {
        (try? fileManager.contentsOfDirectory(
            at: directoryURL(for: state),
            includingPropertiesForKeys: nil,
            options: []
        ).count) ?? 0
    }

    private func isDirectory(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
    }

    private func isRegularFile(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
    }
}

public enum EvidencePackageStoreError: LocalizedError, Equatable {
    case packageAlreadyExists(URL)
    case writeFailed(URL, String)
    case invalidPackage(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .packageAlreadyExists(url):
            return "The evidence package already exists at \(url.path)."
        case let .writeFailed(url, message):
            return "The evidence package could not be written at \(url.path): \(message)"
        case let .invalidPackage(url, message):
            return "The evidence package at \(url.path) is invalid: \(message)"
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
