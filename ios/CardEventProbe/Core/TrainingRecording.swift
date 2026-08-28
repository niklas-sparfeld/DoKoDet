import CryptoKit
import Foundation

public let trainingRecordingSchemaVersion = "cardevent-recording/v1"
public let devicePredictionsSchemaVersion = "cardevent-device-predictions/v1"

public struct TrainingRecordingFile: Codable, Equatable, Sendable {
    public let name: String
    public let type: String
    public let byteLength: Int
    public let sha256: String

    public init(name: String, type: String, byteLength: Int, sha256: String) {
        self.name = name
        self.type = type
        self.byteLength = byteLength
        self.sha256 = sha256
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        type = try container.decode(String.self, forKey: .type)
        byteLength = try container.decode(Int.self, forKey: .byteLength)
        sha256 = try container.decode(String.self, forKey: .sha256)
        guard Self.isSafeFilename(name), byteLength > 0, Self.isLowercaseSHA256(sha256) else {
            throw contractError("file metadata contains an invalid name, length, or hash")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case name
        case type
        case byteLength = "byte_length"
        case sha256
    }

    fileprivate static func isLowercaseSHA256(_ value: String) -> Bool {
        value.count == 64 && value.unicodeScalars.allSatisfy { scalar in
            (0x30...0x39).contains(scalar.value) || (0x61...0x66).contains(scalar.value)
        }
    }

    fileprivate static func isSafeFilename(_ value: String) -> Bool {
        guard value.isEmpty == false,
              let first = value.unicodeScalars.first,
              isASCII(first),
              isLetterOrNumber(first) else { return false }
        return value.unicodeScalars.dropFirst().allSatisfy { scalar in
            isASCII(scalar)
                && (isLetterOrNumber(scalar)
                    || scalar.value == 0x2E
                    || scalar.value == 0x5F
                    || scalar.value == 0x2D)
        }
    }

    private static func isASCII(_ scalar: Unicode.Scalar) -> Bool { scalar.value <= 0x7F }

    private static func isLetterOrNumber(_ scalar: Unicode.Scalar) -> Bool {
        (0x30...0x39).contains(scalar.value)
            || (0x41...0x5A).contains(scalar.value)
            || (0x61...0x7A).contains(scalar.value)
    }
}

public struct TrainingRecordingVideo: Codable, Equatable, Sendable {
    public let name: String
    public let type: String
    public let byteLength: Int
    public let sha256: String
    public let codec: String
    public let width: Int
    public let height: Int
    public let frameRate: Double

    public init(
        name: String,
        type: String,
        byteLength: Int,
        sha256: String,
        codec: String,
        width: Int,
        height: Int,
        frameRate: Double
    ) {
        self.name = name
        self.type = type
        self.byteLength = byteLength
        self.sha256 = sha256
        self.codec = codec
        self.width = width
        self.height = height
        self.frameRate = frameRate
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        type = try container.decode(String.self, forKey: .type)
        byteLength = try container.decode(Int.self, forKey: .byteLength)
        sha256 = try container.decode(String.self, forKey: .sha256)
        codec = try container.decode(String.self, forKey: .codec)
        width = try container.decode(Int.self, forKey: .width)
        height = try container.decode(Int.self, forKey: .height)
        frameRate = try container.decode(Double.self, forKey: .frameRate)
        guard TrainingRecordingFile.isSafeFilename(name), type == "video/quicktime",
              byteLength > 0, TrainingRecordingFile.isLowercaseSHA256(sha256), codec == "h264",
              width > 0, height > 0, frameRate.isFinite, frameRate > 0 else {
            throw contractError("video metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case name
        case type
        case byteLength = "byte_length"
        case sha256
        case codec
        case width
        case height
        case frameRate = "frame_rate"
    }
}

public struct TrainingRecordingPredictionsFile: Codable, Equatable, Sendable {
    public let name: String
    public let type: String
    public let byteLength: Int
    public let sha256: String
    public let sampleCount: Int
    public let eventProposalCount: Int

    public init(
        name: String,
        type: String,
        byteLength: Int,
        sha256: String,
        sampleCount: Int,
        eventProposalCount: Int
    ) {
        self.name = name
        self.type = type
        self.byteLength = byteLength
        self.sha256 = sha256
        self.sampleCount = sampleCount
        self.eventProposalCount = eventProposalCount
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        type = try container.decode(String.self, forKey: .type)
        byteLength = try container.decode(Int.self, forKey: .byteLength)
        sha256 = try container.decode(String.self, forKey: .sha256)
        sampleCount = try container.decode(Int.self, forKey: .sampleCount)
        eventProposalCount = try container.decode(Int.self, forKey: .eventProposalCount)
        guard TrainingRecordingFile.isSafeFilename(name), type == "application/json",
              byteLength > 0, TrainingRecordingFile.isLowercaseSHA256(sha256),
              sampleCount >= 0, eventProposalCount >= 0 else {
            throw contractError("prediction file metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case name
        case type
        case byteLength = "byte_length"
        case sha256
        case sampleCount = "sample_count"
        case eventProposalCount = "event_proposal_count"
    }
}

public struct TrainingRecordingModel: Codable, Equatable, Sendable {
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

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        version = try container.decode(String.self, forKey: .version)
        weightsSHA256 = try container.decode(String.self, forKey: .weightsSHA256)
        preprocessing = try container.decode(String.self, forKey: .preprocessing)
        guard name.isEmpty == false, version.isEmpty == false, preprocessing.isEmpty == false,
              TrainingRecordingFile.isLowercaseSHA256(weightsSHA256) else {
            throw contractError("model metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case name
        case version
        case weightsSHA256 = "weights_sha256"
        case preprocessing
    }
}

public struct TrainingRecordingDecoder: Codable, Equatable, Sendable {
    public let algorithm: String
    public let threshold: Double
    public let peakConfirmationS: Double
    public let minimumEventGapS: Double

    public init(
        algorithm: String,
        threshold: Double,
        peakConfirmationS: Double,
        minimumEventGapS: Double
    ) {
        self.algorithm = algorithm
        self.threshold = threshold
        self.peakConfirmationS = peakConfirmationS
        self.minimumEventGapS = minimumEventGapS
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        algorithm = try container.decode(String.self, forKey: .algorithm)
        threshold = try container.decode(Double.self, forKey: .threshold)
        peakConfirmationS = try container.decode(Double.self, forKey: .peakConfirmationS)
        minimumEventGapS = try container.decode(Double.self, forKey: .minimumEventGapS)
        guard algorithm.isEmpty == false, threshold.isFinite, (0.0...1.0).contains(threshold),
              peakConfirmationS.isFinite, peakConfirmationS >= 0,
              minimumEventGapS.isFinite, minimumEventGapS >= 0 else {
            throw contractError("decoder metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case algorithm
        case threshold
        case peakConfirmationS = "peak_confirmation_s"
        case minimumEventGapS = "minimum_event_gap_s"
    }
}

public struct TrainingRecordingCamera: Codable, Equatable, Sendable {
    public let position: String
    public let orientation: String
    public let sourceWidth: Int
    public let sourceHeight: Int

    public init(position: String, orientation: String, sourceWidth: Int, sourceHeight: Int) {
        self.position = position
        self.orientation = orientation
        self.sourceWidth = sourceWidth
        self.sourceHeight = sourceHeight
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        position = try container.decode(String.self, forKey: .position)
        orientation = try container.decode(String.self, forKey: .orientation)
        sourceWidth = try container.decode(Int.self, forKey: .sourceWidth)
        sourceHeight = try container.decode(Int.self, forKey: .sourceHeight)
        guard position == "back" || position == "front", orientation.isEmpty == false,
              sourceWidth > 0, sourceHeight > 0 else {
            throw contractError("camera metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case position
        case orientation
        case sourceWidth = "source_width"
        case sourceHeight = "source_height"
    }
}

public struct TrainingRecordingClient: Codable, Equatable, Sendable {
    public let appVersion: String
    public let build: String
    public let deviceModel: String
    public let osVersion: String

    public init(appVersion: String, build: String, deviceModel: String, osVersion: String) {
        self.appVersion = appVersion
        self.build = build
        self.deviceModel = deviceModel
        self.osVersion = osVersion
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        appVersion = try container.decode(String.self, forKey: .appVersion)
        build = try container.decode(String.self, forKey: .build)
        deviceModel = try container.decode(String.self, forKey: .deviceModel)
        osVersion = try container.decode(String.self, forKey: .osVersion)
        guard appVersion.isEmpty == false, build.isEmpty == false, deviceModel.isEmpty == false,
              osVersion.isEmpty == false else {
            throw contractError("client metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case appVersion = "app_version"
        case build
        case deviceModel = "device_model"
        case osVersion = "os_version"
    }
}

public struct TrainingRecordingCaptureMetrics: Codable, Equatable, Sendable {
    public let receivedFrameCount: Int
    public let writtenFrameCount: Int
    public let droppedFrameCount: Int

    public init(
        receivedFrameCount: Int,
        writtenFrameCount: Int,
        droppedFrameCount: Int
    ) {
        self.receivedFrameCount = receivedFrameCount
        self.writtenFrameCount = writtenFrameCount
        self.droppedFrameCount = droppedFrameCount
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        receivedFrameCount = try container.decode(Int.self, forKey: .receivedFrameCount)
        writtenFrameCount = try container.decode(Int.self, forKey: .writtenFrameCount)
        droppedFrameCount = try container.decode(Int.self, forKey: .droppedFrameCount)
        guard receivedFrameCount >= 0, writtenFrameCount >= 0, droppedFrameCount >= 0,
              writtenFrameCount + droppedFrameCount == receivedFrameCount else {
            throw contractError("capture metrics must balance received, written, and dropped frames")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case receivedFrameCount = "received_frame_count"
        case writtenFrameCount = "written_frame_count"
        case droppedFrameCount = "dropped_frame_count"
    }
}

public struct TrainingRecordingManifest: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let recordingID: String
    public let sessionID: String
    public let videoID: String
    public let startedAtUTC: String
    public let endedAtUTC: String
    public let durationS: Double
    public let state: String
    public let video: TrainingRecordingVideo
    public let predictions: TrainingRecordingPredictionsFile
    public let model: TrainingRecordingModel
    public let decoder: TrainingRecordingDecoder
    public let camera: TrainingRecordingCamera
    public let client: TrainingRecordingClient
    public let captureMetrics: TrainingRecordingCaptureMetrics
    public let source: String
    public let sourcePermission: String
    public let collectionMetadata: TrainingRecordingCollectionMetadata
    public let taskEnrollments: [RepositoryTaskEnrollment]

    public init(
        schemaVersion: String = trainingRecordingSchemaVersion,
        recordingID: String,
        sessionID: String,
        videoID: String,
        startedAtUTC: String,
        endedAtUTC: String,
        durationS: Double,
        state: String = "complete",
        video: TrainingRecordingVideo,
        predictions: TrainingRecordingPredictionsFile,
        model: TrainingRecordingModel,
        decoder: TrainingRecordingDecoder,
        camera: TrainingRecordingCamera,
        client: TrainingRecordingClient,
        captureMetrics: TrainingRecordingCaptureMetrics,
        source: String = "self_recorded",
        sourcePermission: String,
        collectionMetadata: TrainingRecordingCollectionMetadata,
        taskEnrollments: [RepositoryTaskEnrollment]
    ) throws {
        self.schemaVersion = schemaVersion
        self.recordingID = recordingID
        self.sessionID = sessionID
        self.videoID = videoID
        self.startedAtUTC = startedAtUTC
        self.endedAtUTC = endedAtUTC
        self.durationS = durationS
        self.state = state
        self.video = video
        self.predictions = predictions
        self.model = model
        self.decoder = decoder
        self.camera = camera
        self.client = client
        self.captureMetrics = captureMetrics
        self.source = source
        self.sourcePermission = sourcePermission
        self.collectionMetadata = collectionMetadata
        self.taskEnrollments = taskEnrollments
        try validate()
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        recordingID = try container.decode(String.self, forKey: .recordingID)
        sessionID = try container.decode(String.self, forKey: .sessionID)
        videoID = try container.decode(String.self, forKey: .videoID)
        startedAtUTC = try container.decode(String.self, forKey: .startedAtUTC)
        endedAtUTC = try container.decode(String.self, forKey: .endedAtUTC)
        durationS = try container.decode(Double.self, forKey: .durationS)
        state = try container.decode(String.self, forKey: .state)
        video = try container.decode(TrainingRecordingVideo.self, forKey: .video)
        predictions = try container.decode(TrainingRecordingPredictionsFile.self, forKey: .predictions)
        model = try container.decode(TrainingRecordingModel.self, forKey: .model)
        self.decoder = try container.decode(TrainingRecordingDecoder.self, forKey: .decoder)
        camera = try container.decode(TrainingRecordingCamera.self, forKey: .camera)
        client = try container.decode(TrainingRecordingClient.self, forKey: .client)
        captureMetrics = try container.decode(TrainingRecordingCaptureMetrics.self, forKey: .captureMetrics)
        source = try container.decode(String.self, forKey: .source)
        sourcePermission = try container.decode(String.self, forKey: .sourcePermission)
        collectionMetadata = try container.decode(
            TrainingRecordingCollectionMetadata.self,
            forKey: .collectionMetadata
        )
        taskEnrollments = try container.decode([RepositoryTaskEnrollment].self, forKey: .taskEnrollments)
        try validate()
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case sessionID = "session_id"
        case videoID = "video_id"
        case startedAtUTC = "started_at_utc"
        case endedAtUTC = "ended_at_utc"
        case durationS = "duration_s"
        case state
        case video
        case predictions
        case model
        case decoder
        case camera
        case client
        case captureMetrics = "capture_metrics"
        case source
        case sourcePermission = "source_permission"
        case collectionMetadata = "collection_metadata"
        case taskEnrollments = "task_enrollments"
    }

    private func validate() throws {
        guard schemaVersion == trainingRecordingSchemaVersion, state == "complete",
              source == "self_recorded", durationS.isFinite, durationS > 0,
              Self.isSafeIdentifier(recordingID), Self.isSafeIdentifier(sessionID),
              Self.isSafeIdentifier(videoID),
              sourcePermission == "training_only"
                || sourcePermission == "training_and_evaluation"
                || sourcePermission == "project_use"
                || sourcePermission == "unrestricted" else {
            throw contractError("recording manifest contains an invalid version, identity, or state")
        }
        guard let started = Self.parseUTC(startedAtUTC),
              let ended = Self.parseUTC(endedAtUTC),
              ended > started,
              abs(ended.timeIntervalSince(started) - durationS) <= 0.001 else {
            throw contractError("recording duration does not match its UTC times")
        }
        guard video.name == "\(videoID).mov", predictions.name == "\(videoID).json",
              video.width == camera.sourceWidth, video.height == camera.sourceHeight else {
            throw contractError("recording file names and camera dimensions must match video_id")
        }
        guard collectionMetadata.sourcePermission == sourcePermission,
              collectionMetadata.validationIssues.isEmpty,
              taskEnrollments.count == RepositoryDataTask.allCases.count,
              Set(taskEnrollments.map(\.task)) == Set(RepositoryDataTask.allCases),
              Set(taskEnrollments.map(\.taskEnrollmentID)).count == taskEnrollments.count,
              taskEnrollments.allSatisfy({ $0.operator == collectionMetadata.operatorName }) else {
            throw contractError("recording collection metadata or task enrollments are incomplete")
        }
    }

    private static func isSafeIdentifier(_ value: String) -> Bool {
        guard let first = value.unicodeScalars.first,
              isLetterOrNumber(first) else { return false }
        return value.unicodeScalars.dropFirst().allSatisfy { scalar in
            isLetterOrNumber(scalar) || scalar.value == 0x2E || scalar.value == 0x3A || scalar.value == 0x5F || scalar.value == 0x2D
        }
    }

    private static func isLetterOrNumber(_ scalar: Unicode.Scalar) -> Bool {
        (0x30...0x39).contains(scalar.value)
            || (0x41...0x5A).contains(scalar.value)
            || (0x61...0x7A).contains(scalar.value)
    }

    private static func parseUTC(_ value: String) -> Date? {
        guard value.hasSuffix("Z") else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value) ?? {
            formatter.formatOptions = [.withInternetDateTime]
            return formatter.date(from: value)
        }()
    }
}

public struct TrainingRecordingProbability: Codable, Equatable, Sendable {
    public let timeS: Double
    public let probability: Double
    public let inferenceMs: Double

    public init(timeS: Double, probability: Double, inferenceMs: Double) {
        self.timeS = timeS
        self.probability = probability
        self.inferenceMs = inferenceMs
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        timeS = try container.decode(Double.self, forKey: .timeS)
        probability = try container.decode(Double.self, forKey: .probability)
        inferenceMs = try container.decode(Double.self, forKey: .inferenceMs)
        guard timeS.isFinite, timeS >= 0, probability.isFinite, (0.0...1.0).contains(probability),
              inferenceMs.isFinite, inferenceMs >= 0 else {
            throw contractError("prediction sample contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case timeS = "time_s"
        case probability
        case inferenceMs = "inference_ms"
    }
}

public struct TrainingRecordingEventProposal: Codable, Equatable, Sendable {
    public let timeS: Double
    public let emittedAtS: Double
    public let probability: Double

    public init(timeS: Double, emittedAtS: Double, probability: Double) {
        self.timeS = timeS
        self.emittedAtS = emittedAtS
        self.probability = probability
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        timeS = try container.decode(Double.self, forKey: .timeS)
        emittedAtS = try container.decode(Double.self, forKey: .emittedAtS)
        probability = try container.decode(Double.self, forKey: .probability)
        guard timeS.isFinite, timeS >= 0, emittedAtS.isFinite, emittedAtS >= timeS,
              probability.isFinite, (0.0...1.0).contains(probability) else {
            throw contractError("event proposal contains an invalid or non-causal value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case timeS = "time_s"
        case emittedAtS = "emitted_at_s"
        case probability
    }
}

public struct DevicePredictions: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let sourceVideo: String
    public let model: TrainingRecordingModel
    public let decoder: TrainingRecordingDecoder
    public let probabilities: [TrainingRecordingProbability]
    public let eventProposals: [TrainingRecordingEventProposal]

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        sourceVideo = try container.decode(String.self, forKey: .sourceVideo)
        model = try container.decode(TrainingRecordingModel.self, forKey: .model)
        self.decoder = try container.decode(TrainingRecordingDecoder.self, forKey: .decoder)
        probabilities = try container.decode([TrainingRecordingProbability].self, forKey: .probabilities)
        eventProposals = try container.decode([TrainingRecordingEventProposal].self, forKey: .eventProposals)
        guard schemaVersion == devicePredictionsSchemaVersion,
              TrainingRecordingFile.isSafeFilename(sourceVideo) else {
            throw contractError("device predictions contain an invalid version or source video")
        }
        guard probabilities.indices.dropFirst().allSatisfy({ index in
            probabilities[index - 1].timeS <= probabilities[index].timeS
        }), eventProposals.indices.dropFirst().allSatisfy({ index in
            eventProposals[index - 1].timeS <= eventProposals[index].timeS
        }) else {
            throw contractError("prediction times must be ordered on the recording timeline")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case sourceVideo = "source_video"
        case model
        case decoder
        case probabilities
        case eventProposals = "event_proposals"
    }
}

public enum TrainingRecordingContractError: LocalizedError, Equatable {
    case invalid(String)
    case identityMismatch
    case provenanceMismatch
    case countMismatch
    case timeMismatch
    case hashMismatch(String)

    public var errorDescription: String? {
        switch self {
        case let .invalid(message): return "Invalid training recording: \(message)."
        case .identityMismatch: return "The prediction source video does not match the manifest."
        case .provenanceMismatch: return "Prediction provenance does not match the manifest."
        case .countMismatch: return "Prediction counts do not match the manifest."
        case .timeMismatch: return "A prediction time is outside the recording duration."
        case let .hashMismatch(name): return "The \(name) bytes do not match the manifest."
        }
    }
}

public func validateTrainingRecordingBundle(
    manifestData: Data,
    predictionsData: Data,
    videoData: Data
) throws -> (TrainingRecordingManifest, DevicePredictions) {
    return try validateTrainingRecordingBundle(
        manifestData: manifestData,
        predictionsData: predictionsData,
        videoByteLength: videoData.count,
        videoSHA256: videoData.sha256Hex
    )
}

/// Validates a bundle while streaming the video hash from disk.
public func validateTrainingRecordingBundle(
    manifestData: Data,
    predictionsData: Data,
    videoURL: URL
) throws -> (TrainingRecordingManifest, DevicePredictions) {
    let attributes: [FileAttributeKey: Any]
    do {
        attributes = try FileManager.default.attributesOfItem(atPath: videoURL.path)
    } catch {
        throw TrainingRecordingContractError.hashMismatch("video")
    }
    guard let byteLength = attributes[.size] as? NSNumber else {
        throw TrainingRecordingContractError.hashMismatch("video")
    }
    return try validateTrainingRecordingBundle(
        manifestData: manifestData,
        predictionsData: predictionsData,
        videoByteLength: byteLength.intValue,
        videoSHA256: try sha256Hex(of: videoURL)
    )
}

private func validateTrainingRecordingBundle(
    manifestData: Data,
    predictionsData: Data,
    videoByteLength: Int,
    videoSHA256: String
) throws -> (TrainingRecordingManifest, DevicePredictions) {
    let decoder = JSONDecoder()
    let manifest = try decoder.decode(TrainingRecordingManifest.self, from: manifestData)
    let predictions = try decoder.decode(DevicePredictions.self, from: predictionsData)
    guard manifest.video.name == predictions.sourceVideo else {
        throw TrainingRecordingContractError.identityMismatch
    }
    guard manifest.model == predictions.model, manifest.decoder == predictions.decoder else {
        throw TrainingRecordingContractError.provenanceMismatch
    }
    guard manifest.predictions.sampleCount == predictions.probabilities.count,
          manifest.predictions.eventProposalCount == predictions.eventProposals.count else {
        throw TrainingRecordingContractError.countMismatch
    }
    guard predictions.probabilities.allSatisfy({ $0.timeS <= manifest.durationS }),
          predictions.eventProposals.allSatisfy({ $0.emittedAtS <= manifest.durationS }) else {
        throw TrainingRecordingContractError.timeMismatch
    }
    guard videoByteLength == manifest.video.byteLength,
          videoSHA256 == manifest.video.sha256 else {
        throw TrainingRecordingContractError.hashMismatch("video")
    }
    guard predictionsData.count == manifest.predictions.byteLength,
          predictionsData.sha256Hex == manifest.predictions.sha256 else {
        throw TrainingRecordingContractError.hashMismatch("predictions")
    }
    return (manifest, predictions)
}

private func sha256Hex(of url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }

    var hasher = SHA256()
    while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
        hasher.update(data: chunk)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

private func contractError(_ message: String) -> TrainingRecordingContractError {
    .invalid(message)
}

private func requireExactKeys<Key: CodingKey & CaseIterable>(
    _ container: KeyedDecodingContainer<Key>,
    _ keyType: Key.Type
) throws {
    let expected = Set(keyType.allCases.map(\.stringValue))
    let actual = Set(container.allKeys.map(\.stringValue))
    guard actual == expected else {
        throw contractError("unexpected or missing fields")
    }
}

private extension Data {
    var sha256Hex: String {
        SHA256.hash(data: self).map { String(format: "%02x", $0) }.joined()
    }
}
