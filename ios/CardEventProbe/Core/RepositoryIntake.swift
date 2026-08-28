import CryptoKit
import Foundation

public let repositoryBundleSchemaVersion = "repository-bundle/v1"
public let repositoryTaskEnrollmentSchemaVersion = "task-enrollment/v1"
public let proposalGeneratorRunSchemaVersion = "proposal-generator-run/v1"
public let repositorySourceRecordSchemaVersion = "source-record/v1"

public enum RepositoryDataTask: String, Codable, CaseIterable, Hashable, Sendable {
    case cardEventDetection = "cardevent_event_detection"
    case tableEvidenceAnalysis = "table_evidence_analysis"
}

public enum RepositoryTaskDisposition: String, Codable, CaseIterable, Hashable, Sendable {
    case selected
    case deferred
    case excluded
}

public struct RepositorySourceRecord: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let sourceAssetID: String
    public let sha256: String
    public let byteLength: Int
    public let mediaType: String
    public let originalFilename: String
    public let acquisitionMethod: String
    public let sourcePermission: String
    public let allowedUses: [String]
    public let sessionID: String?
    public let recordingID: String?
    public let videoID: String?
    public let gameID: String?
    public let roundID: String?
    public let tableSetup: String?
    public let contentType: String?
    public let retentionState: String
    public let notes: String?

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        sourceAssetID = try container.decode(String.self, forKey: .sourceAssetID)
        sha256 = try container.decode(String.self, forKey: .sha256)
        byteLength = try container.decode(Int.self, forKey: .byteLength)
        mediaType = try container.decode(String.self, forKey: .mediaType)
        originalFilename = try container.decode(String.self, forKey: .originalFilename)
        acquisitionMethod = try container.decode(String.self, forKey: .acquisitionMethod)
        sourcePermission = try container.decode(String.self, forKey: .sourcePermission)
        allowedUses = try container.decode([String].self, forKey: .allowedUses)
        sessionID = try container.decodeIfPresent(String.self, forKey: .sessionID)
        recordingID = try container.decodeIfPresent(String.self, forKey: .recordingID)
        videoID = try container.decodeIfPresent(String.self, forKey: .videoID)
        gameID = try container.decodeIfPresent(String.self, forKey: .gameID)
        roundID = try container.decodeIfPresent(String.self, forKey: .roundID)
        tableSetup = try container.decodeIfPresent(String.self, forKey: .tableSetup)
        contentType = try container.decodeIfPresent(String.self, forKey: .contentType)
        retentionState = try container.decode(String.self, forKey: .retentionState)
        notes = try container.decodeIfPresent(String.self, forKey: .notes)
        guard schemaVersion == repositorySourceRecordSchemaVersion,
              RepositoryIntakeContract.isIdentifier(sourceAssetID),
              RepositoryIntakeContract.isSHA256(sha256), byteLength > 0,
              mediaType.isEmpty == false, RepositoryIntakeContract.isFilename(originalFilename),
              acquisitionMethod.isEmpty == false,
              ["training_only", "training_and_evaluation", "project_use", "unrestricted"].contains(sourcePermission),
              allowedUses.isEmpty == false,
              Set(allowedUses).isSubset(of: ["train", "validation", "test", "evaluation"]),
              allowedUses.count == Set(allowedUses).count,
              ["active", "deletion_requested", "deleted", "retired"].contains(retentionState),
              [sessionID, recordingID, videoID, gameID, roundID, tableSetup].allSatisfy({ value in
                  value == nil || RepositoryIntakeContract.isIdentifier(value!)
              }) else {
            throw repositoryContractError("source record contains an invalid value")
        }
        if let contentType, !["real_game", "staged_trick_sequence", "staged_scenario", "synthetic_render", "other"].contains(contentType) {
            throw repositoryContractError("source record contains an unknown content type")
        }
        if ["staged_scenario", "staged_trick_sequence"].contains(contentType), gameID != nil || roundID != nil {
            throw repositoryContractError("staged activity must not have a game or round")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case sourceAssetID = "source_asset_id"
        case sha256
        case byteLength = "byte_length"
        case mediaType = "media_type"
        case originalFilename = "original_filename"
        case acquisitionMethod = "acquisition_method"
        case sourcePermission = "source_permission"
        case allowedUses = "allowed_uses"
        case sessionID = "session_id"
        case recordingID = "recording_id"
        case videoID = "video_id"
        case gameID = "game_id"
        case roundID = "round_id"
        case tableSetup = "table_setup"
        case contentType = "content_type"
        case retentionState = "retention_state"
        case notes
    }
}

public struct RepositoryTaskEnrollment: Codable, Equatable, Sendable {
    public let taskEnrollmentID: String
    public let task: RepositoryDataTask
    public let disposition: RepositoryTaskDisposition
    public let lifecycleState: String
    public let `operator`: String
    public let createdAtUTC: String
    public let reason: String?

    public init(
        taskEnrollmentID: String,
        task: RepositoryDataTask,
        disposition: RepositoryTaskDisposition,
        operatorName: String,
        createdAtUTC: String,
        reason: String? = nil
    ) throws {
        guard RepositoryIntakeContract.isIdentifier(taskEnrollmentID) else {
            throw repositoryContractError("task enrollment id is invalid: \(taskEnrollmentID)")
        }
        guard !operatorName.isEmpty else {
            throw repositoryContractError("task enrollment operator is invalid")
        }
        guard RepositoryIntakeContract.isUTCTimestamp(createdAtUTC) else {
            throw repositoryContractError("task enrollment timestamp is invalid: \(createdAtUTC)")
        }
        if disposition == .excluded {
            guard reason?.isEmpty == false else {
                throw repositoryContractError("excluded enrollment needs a reason")
            }
        } else if reason != nil {
            throw repositoryContractError("selected or deferred enrollment must not have a reason")
        }
        self.taskEnrollmentID = taskEnrollmentID
        self.task = task
        self.disposition = disposition
        self.lifecycleState = disposition == .excluded ? "excluded" : "intake"
        self.operator = operatorName
        self.createdAtUTC = createdAtUTC
        self.reason = reason
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        taskEnrollmentID = try container.decode(String.self, forKey: .taskEnrollmentID)
        task = try container.decode(RepositoryDataTask.self, forKey: .task)
        disposition = try container.decode(RepositoryTaskDisposition.self, forKey: .disposition)
        lifecycleState = try container.decode(String.self, forKey: .lifecycleState)
        `operator` = try container.decode(String.self, forKey: .operator)
        createdAtUTC = try container.decode(String.self, forKey: .createdAtUTC)
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
        guard RepositoryIntakeContract.isIdentifier(taskEnrollmentID),
              ["intake", "annotating", "review_required", "reviewed", "eligible", "excluded", "retired"].contains(lifecycleState),
              `operator`.isEmpty == false, RepositoryIntakeContract.isUTCTimestamp(createdAtUTC) else {
            throw repositoryContractError("task enrollment contains an invalid value")
        }
        if disposition == .excluded {
            guard lifecycleState == "excluded", reason?.isEmpty == false else {
                throw repositoryContractError("excluded enrollment needs state and reason")
            }
        } else {
            guard lifecycleState == "intake", reason == nil else {
                throw repositoryContractError("selected or deferred enrollment must start in intake")
            }
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case taskEnrollmentID = "task_enrollment_id"
        case task
        case disposition
        case lifecycleState = "lifecycle_state"
        case `operator`
        case createdAtUTC = "created_at_utc"
        case reason
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(taskEnrollmentID, forKey: .taskEnrollmentID)
        try container.encode(task, forKey: .task)
        try container.encode(disposition, forKey: .disposition)
        try container.encode(lifecycleState, forKey: .lifecycleState)
        try container.encode(`operator`, forKey: .operator)
        try container.encode(createdAtUTC, forKey: .createdAtUTC)
        try container.encode(reason, forKey: .reason)
    }
}

public struct RepositoryTaskEnrollmentDocument: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let sourceAssetID: String
    public let enrollments: [RepositoryTaskEnrollment]

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        sourceAssetID = try container.decode(String.self, forKey: .sourceAssetID)
        enrollments = try container.decode([RepositoryTaskEnrollment].self, forKey: .enrollments)
        guard schemaVersion == repositoryTaskEnrollmentSchemaVersion,
              RepositoryIntakeContract.isIdentifier(sourceAssetID), enrollments.count == 2,
              Set(enrollments.map(\.task)) == Set(RepositoryDataTask.allCases),
              Set(enrollments.map(\.taskEnrollmentID)).count == 2 else {
            throw repositoryContractError("task enrollment document must contain one entry for each task")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case sourceAssetID = "source_asset_id"
        case enrollments
    }
}

public struct RepositoryBundleFile: Codable, Equatable, Sendable {
    public let relativePath: String
    public let type: String
    public let byteLength: Int
    public let sha256: String

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        relativePath = try container.decode(String.self, forKey: .relativePath)
        type = try container.decode(String.self, forKey: .type)
        byteLength = try container.decode(Int.self, forKey: .byteLength)
        sha256 = try container.decode(String.self, forKey: .sha256)
        let path = relativePath.split(separator: "/", omittingEmptySubsequences: false)
        guard relativePath.isEmpty == false, relativePath.first != "/", !path.contains(".."),
              type.isEmpty == false, byteLength > 0, RepositoryIntakeContract.isSHA256(sha256) else {
            throw repositoryContractError("bundle file contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case relativePath = "relative_path"
        case type
        case byteLength = "byte_length"
        case sha256
    }
}

public struct RepositoryProposalFile: Codable, Equatable, Sendable {
    public let proposalGeneratorRunID: String
    public let relativePath: String
    public let type: String
    public let byteLength: Int
    public let sha256: String

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        proposalGeneratorRunID = try container.decode(String.self, forKey: .proposalGeneratorRunID)
        relativePath = try container.decode(String.self, forKey: .relativePath)
        type = try container.decode(String.self, forKey: .type)
        byteLength = try container.decode(Int.self, forKey: .byteLength)
        sha256 = try container.decode(String.self, forKey: .sha256)
        let path = relativePath.split(separator: "/", omittingEmptySubsequences: false)
        guard RepositoryIntakeContract.isIdentifier(proposalGeneratorRunID), relativePath.isEmpty == false,
              relativePath.first != "/", !path.contains(".."), type == "application/json", byteLength > 0,
              RepositoryIntakeContract.isSHA256(sha256) else {
            throw repositoryContractError("proposal file contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case proposalGeneratorRunID = "proposal_generator_run_id"
        case relativePath = "relative_path"
        case type
        case byteLength = "byte_length"
        case sha256
    }
}

public struct RepositoryBundleFiles: Codable, Equatable, Sendable {
    public let video: RepositoryBundleFile
    public let sourceRecord: RepositoryBundleFile
    public let taskEnrollment: RepositoryBundleFile
    public let proposalGeneratorRuns: [RepositoryProposalFile]

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        video = try container.decode(RepositoryBundleFile.self, forKey: .video)
        sourceRecord = try container.decode(RepositoryBundleFile.self, forKey: .sourceRecord)
        taskEnrollment = try container.decode(RepositoryBundleFile.self, forKey: .taskEnrollment)
        proposalGeneratorRuns = try container.decode([RepositoryProposalFile].self, forKey: .proposalGeneratorRuns)
        guard video.type == "video/quicktime", sourceRecord.type == "application/json",
              taskEnrollment.type == "application/json",
              Set(proposalGeneratorRuns.map(\.proposalGeneratorRunID)).count == proposalGeneratorRuns.count else {
            throw repositoryContractError("bundle file types or proposal identities are invalid")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case video
        case sourceRecord = "source_record"
        case taskEnrollment = "task_enrollment"
        case proposalGeneratorRuns = "proposal_generator_runs"
    }
}

public struct RepositoryBundle: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let sourceAssetID: String
    public let recordingID: String
    public let videoID: String
    public let sessionID: String
    public let state: String
    public let sourceSHA256: String
    public let files: RepositoryBundleFiles

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        sourceAssetID = try container.decode(String.self, forKey: .sourceAssetID)
        recordingID = try container.decode(String.self, forKey: .recordingID)
        videoID = try container.decode(String.self, forKey: .videoID)
        sessionID = try container.decode(String.self, forKey: .sessionID)
        state = try container.decode(String.self, forKey: .state)
        sourceSHA256 = try container.decode(String.self, forKey: .sourceSHA256)
        files = try container.decode(RepositoryBundleFiles.self, forKey: .files)
        guard schemaVersion == repositoryBundleSchemaVersion, state == "complete",
              RepositoryIntakeContract.isIdentifier(sourceAssetID),
              RepositoryIntakeContract.isIdentifier(recordingID), RepositoryIntakeContract.isIdentifier(videoID),
              RepositoryIntakeContract.isIdentifier(sessionID), RepositoryIntakeContract.isSHA256(sourceSHA256),
              files.video.sha256 == sourceSHA256 else {
            throw repositoryContractError("repository bundle contains an invalid identity or state")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case sourceAssetID = "source_asset_id"
        case recordingID = "recording_id"
        case videoID = "video_id"
        case sessionID = "session_id"
        case state
        case sourceSHA256 = "source_sha256"
        case files
    }
}

public struct RepositoryProposalDecoder: Codable, Equatable, Sendable {
    public let algorithm: String
    public let threshold: Double
    public let peakConfirmationS: Double
    public let minimumEventGapS: Double

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        algorithm = try container.decode(String.self, forKey: .algorithm)
        threshold = try container.decode(Double.self, forKey: .threshold)
        peakConfirmationS = try container.decode(Double.self, forKey: .peakConfirmationS)
        minimumEventGapS = try container.decode(Double.self, forKey: .minimumEventGapS)
        guard algorithm.isEmpty == false, threshold.isFinite, (0...1).contains(threshold),
              peakConfirmationS.isFinite, peakConfirmationS >= 0,
              minimumEventGapS.isFinite, minimumEventGapS >= 0 else {
            throw repositoryContractError("proposal decoder contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case algorithm
        case threshold
        case peakConfirmationS = "peak_confirmation_s"
        case minimumEventGapS = "minimum_event_gap_s"
    }
}

public struct RepositoryProposalSampling: Codable, Equatable, Sendable {
    public let strategy: String
    public let targetHz: Double

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        strategy = try container.decode(String.self, forKey: .strategy)
        targetHz = try container.decode(Double.self, forKey: .targetHz)
        guard strategy.isEmpty == false, targetHz.isFinite, targetHz > 0 else {
            throw repositoryContractError("proposal sampling contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case strategy
        case targetHz = "target_hz"
    }
}

public struct RepositoryExecutionEnvironment: Codable, Equatable, Sendable {
    public let platform: String
    public let device: String
    public let osVersion: String
    public let runtimeVersion: String

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        platform = try container.decode(String.self, forKey: .platform)
        device = try container.decode(String.self, forKey: .device)
        osVersion = try container.decode(String.self, forKey: .osVersion)
        runtimeVersion = try container.decode(String.self, forKey: .runtimeVersion)
        guard ["ios", "macos", "linux"].contains(platform), device.isEmpty == false,
              osVersion.isEmpty == false, runtimeVersion.isEmpty == false else {
            throw repositoryContractError("proposal execution environment contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case platform
        case device
        case osVersion = "os_version"
        case runtimeVersion = "runtime_version"
    }
}

public struct RepositoryProbability: Codable, Equatable, Sendable {
    public let timeS: Double
    public let probability: Double
    public let inferenceMs: Double

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        timeS = try container.decode(Double.self, forKey: .timeS)
        probability = try container.decode(Double.self, forKey: .probability)
        inferenceMs = try container.decode(Double.self, forKey: .inferenceMs)
        guard timeS.isFinite, timeS >= 0, probability.isFinite, (0...1).contains(probability),
              inferenceMs.isFinite, inferenceMs >= 0 else {
            throw repositoryContractError("proposal probability contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case timeS = "time_s"
        case probability
        case inferenceMs = "inference_ms"
    }
}

public struct RepositoryEventProposal: Codable, Equatable, Sendable {
    public let timeS: Double
    public let emittedAtS: Double
    public let probability: Double

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        timeS = try container.decode(Double.self, forKey: .timeS)
        emittedAtS = try container.decode(Double.self, forKey: .emittedAtS)
        probability = try container.decode(Double.self, forKey: .probability)
        guard timeS.isFinite, timeS >= 0, emittedAtS.isFinite, emittedAtS >= timeS,
              probability.isFinite, (0...1).contains(probability) else {
            throw repositoryContractError("event proposal contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case timeS = "time_s"
        case emittedAtS = "emitted_at_s"
        case probability
    }
}

public struct RepositoryProposalGeneratorRun: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let proposalGeneratorRunID: String
    public let purpose: String
    public let sourceAssetID: String
    public let recordingID: String
    public let videoID: String
    public let sourceSHA256: String
    public let modelBundleID: String
    public let weightsSHA256: String
    public let decoder: RepositoryProposalDecoder
    public let preprocessing: String
    public let sampling: RepositoryProposalSampling
    public let executionEnvironment: RepositoryExecutionEnvironment
    public let probabilities: [RepositoryProbability]
    public let eventProposals: [RepositoryEventProposal]
    public let outputSHA256: String

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try repositoryRequireExactKeys(decoder, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        proposalGeneratorRunID = try container.decode(String.self, forKey: .proposalGeneratorRunID)
        purpose = try container.decode(String.self, forKey: .purpose)
        sourceAssetID = try container.decode(String.self, forKey: .sourceAssetID)
        recordingID = try container.decode(String.self, forKey: .recordingID)
        videoID = try container.decode(String.self, forKey: .videoID)
        sourceSHA256 = try container.decode(String.self, forKey: .sourceSHA256)
        modelBundleID = try container.decode(String.self, forKey: .modelBundleID)
        weightsSHA256 = try container.decode(String.self, forKey: .weightsSHA256)
        self.decoder = try container.decode(RepositoryProposalDecoder.self, forKey: .decoder)
        preprocessing = try container.decode(String.self, forKey: .preprocessing)
        sampling = try container.decode(RepositoryProposalSampling.self, forKey: .sampling)
        executionEnvironment = try container.decode(RepositoryExecutionEnvironment.self, forKey: .executionEnvironment)
        probabilities = try container.decode([RepositoryProbability].self, forKey: .probabilities)
        eventProposals = try container.decode([RepositoryEventProposal].self, forKey: .eventProposals)
        outputSHA256 = try container.decode(String.self, forKey: .outputSHA256)
        guard schemaVersion == proposalGeneratorRunSchemaVersion, purpose == "proposal_only",
              RepositoryIntakeContract.isIdentifier(proposalGeneratorRunID),
              RepositoryIntakeContract.isIdentifier(sourceAssetID), RepositoryIntakeContract.isIdentifier(recordingID),
              RepositoryIntakeContract.isIdentifier(videoID), RepositoryIntakeContract.isSHA256(sourceSHA256),
              RepositoryIntakeContract.isIdentifier(modelBundleID), RepositoryIntakeContract.isSHA256(weightsSHA256),
              preprocessing.isEmpty == false, RepositoryIntakeContract.isSHA256(outputSHA256),
              probabilities.indices.dropFirst().allSatisfy({ index in probabilities[index - 1].timeS <= probabilities[index].timeS }),
              eventProposals.indices.dropFirst().allSatisfy({ index in eventProposals[index - 1].timeS <= eventProposals[index].timeS }) else {
            throw repositoryContractError("proposal generator run contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case proposalGeneratorRunID = "proposal_generator_run_id"
        case purpose
        case sourceAssetID = "source_asset_id"
        case recordingID = "recording_id"
        case videoID = "video_id"
        case sourceSHA256 = "source_sha256"
        case modelBundleID = "model_bundle_id"
        case weightsSHA256 = "weights_sha256"
        case decoder
        case preprocessing
        case sampling
        case executionEnvironment = "execution_environment"
        case probabilities
        case eventProposals = "event_proposals"
        case outputSHA256 = "output_sha256"
    }
}

public enum RepositoryIntakeContract {
    public static func validate(
        bundle: RepositoryBundle,
        source: RepositorySourceRecord,
        enrollments: RepositoryTaskEnrollmentDocument,
        proposalRuns: [RepositoryProposalGeneratorRun]
    ) throws {
        guard bundle.sourceAssetID == source.sourceAssetID, bundle.sourceSHA256 == source.sha256,
              bundle.recordingID == source.recordingID, bundle.videoID == source.videoID,
              bundle.sessionID == source.sessionID, enrollments.sourceAssetID == bundle.sourceAssetID else {
            throw repositoryContractError("repository bundle documents have different identities")
        }
        let expected = Set(bundle.files.proposalGeneratorRuns.map(\.proposalGeneratorRunID))
        guard expected == Set(proposalRuns.map(\.proposalGeneratorRunID)) else {
            throw repositoryContractError("bundle proposal files do not match proposal runs")
        }
        for run in proposalRuns {
            guard run.sourceAssetID == bundle.sourceAssetID, run.recordingID == bundle.recordingID,
                  run.videoID == bundle.videoID, run.sourceSHA256 == bundle.sourceSHA256 else {
                throw repositoryContractError("proposal run lineage does not match source bundle")
            }
        }
    }

    fileprivate static func isIdentifier(_ value: String) -> Bool {
        guard let first = value.unicodeScalars.first, isASCIIAlphaNumeric(first) else { return false }
        return value.unicodeScalars.dropFirst().allSatisfy { scalar in
            isASCIIAlphaNumeric(scalar) || [0x2E, 0x3A, 0x5F, 0x2D].contains(scalar.value)
        }
    }

    fileprivate static func isFilename(_ value: String) -> Bool {
        guard let first = value.unicodeScalars.first, isASCIIAlphaNumeric(first) else { return false }
        return value.unicodeScalars.dropFirst().allSatisfy { scalar in
            isASCIIAlphaNumeric(scalar) || [0x2E, 0x5F, 0x2D].contains(scalar.value)
        }
    }

    fileprivate static func isSHA256(_ value: String) -> Bool {
        value.count == 64 && value.unicodeScalars.allSatisfy { scalar in
            (0x30...0x39).contains(scalar.value) || (0x61...0x66).contains(scalar.value)
        }
    }

    fileprivate static func isUTCTimestamp(_ value: String) -> Bool {
        guard value.hasSuffix("Z") else { return false }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value) != nil || {
            formatter.formatOptions = [.withInternetDateTime]
            return formatter.date(from: value) != nil
        }()
    }

    private static func isASCIIAlphaNumeric(_ scalar: Unicode.Scalar) -> Bool {
        (0x30...0x39).contains(scalar.value) || (0x41...0x5A).contains(scalar.value)
            || (0x61...0x7A).contains(scalar.value)
    }
}

public enum RepositoryIntakeContractError: LocalizedError, Equatable {
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case let .invalid(message): return "Invalid repository intake: \(message)."
        }
    }
}

private func repositoryContractError(_ message: String) -> RepositoryIntakeContractError {
    .invalid(message)
}

private struct RepositoryAnyCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil

    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}

private func repositoryRequireExactKeys<Key: CodingKey & CaseIterable>(
    _ decoder: Decoder,
    _ keyType: Key.Type
) throws {
    let container = try decoder.container(keyedBy: RepositoryAnyCodingKey.self)
    let expected = Set(keyType.allCases.map(\.stringValue))
    let actual = Set(container.allKeys.map(\.stringValue))
    guard actual == expected else { throw repositoryContractError("unexpected or missing fields") }
}

public func decodeRepositoryJSON<T: Decodable>(_ type: T.Type, data: Data) throws -> T {
    try JSONDecoder().decode(type, from: data)
}

public func verifyRepositoryBytes(_ data: Data, descriptor: RepositoryBundleFile) throws {
    guard data.count == descriptor.byteLength,
          data.sha256Hex == descriptor.sha256 else {
        throw repositoryContractError("bundle file bytes do not match their descriptor")
    }
}

private extension Data {
    var sha256Hex: String {
        SHA256.hash(data: self).map { String(format: "%02x", $0) }.joined()
    }
}
