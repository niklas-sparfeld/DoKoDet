import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public let roundAnalysisSchemaVersion = "round-analysis/v1"
public let roundAnalysisSubmissionStateSchemaVersion = "round-analysis-submission/v1"

/// The explicit Plan 0031 search bounds used by the round-recording PoC.
public struct RoundAnalysisSearchLimits: Codable, Equatable, Sendable {
    public let maxMissingPlays: Int
    public let maxHypotheses: Int
    public let maxSearchNodes: Int

    public init(
        maxMissingPlays: Int = 1,
        maxHypotheses: Int = 256,
        maxSearchNodes: Int = 250_000
    ) {
        precondition(maxMissingPlays >= 0, "max missing plays must not be negative")
        precondition(maxHypotheses > 0, "max hypotheses must be positive")
        precondition(maxSearchNodes > 0, "max search nodes must be positive")
        self.maxMissingPlays = maxMissingPlays
        self.maxHypotheses = maxHypotheses
        self.maxSearchNodes = maxSearchNodes
    }

    public init(from decoder: Decoder) throws {
        try roundAnalysisRequireExactKeys(decoder, CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let maxMissingPlays = try container.decode(Int.self, forKey: .maxMissingPlays)
        let maxHypotheses = try container.decode(Int.self, forKey: .maxHypotheses)
        let maxSearchNodes = try container.decode(Int.self, forKey: .maxSearchNodes)
        guard maxMissingPlays >= 0, maxHypotheses > 0, maxSearchNodes > 0 else {
            throw RoundAnalysisContractError.invalidStoredState
        }
        self.maxMissingPlays = maxMissingPlays
        self.maxHypotheses = maxHypotheses
        self.maxSearchNodes = maxSearchNodes
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case maxMissingPlays = "max_missing_plays"
        case maxHypotheses = "max_hypotheses"
        case maxSearchNodes = "max_search_nodes"
    }
}

public enum RoundAnalysisRemoteState: String, Codable, Equatable, Sendable {
    case queued
    case analyzingEvidence = "analyzing_evidence"
    case reconstructing
    case complete
    case failed

    var isTerminal: Bool {
        self == .complete || self == .failed
    }
}

public enum RoundAnalysisReconstructionStatus: String, Codable, Equatable, Sendable {
    case resolved
    case ambiguous
    case incomplete
    case impossible
}

/// A JSON value retained only for the compact result fields returned by the backend.
public indirect enum RoundAnalysisJSONValue: Codable, Equatable, Sendable {
    case null
    case boolean(Bool)
    case number(Double)
    case string(String)
    case array([RoundAnalysisJSONValue])
    case object([String: RoundAnalysisJSONValue])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .boolean(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([RoundAnalysisJSONValue].self) {
            self = .array(value)
        } else if let value = try? container.decode([String: RoundAnalysisJSONValue].self) {
            self = .object(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "the value is not valid JSON"
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null:
            try container.encodeNil()
        case let .boolean(value):
            try container.encode(value)
        case let .number(value):
            guard value.isFinite else {
                throw EncodingError.invalidValue(
                    value,
                    EncodingError.Context(codingPath: encoder.codingPath, debugDescription: "number must be finite")
                )
            }
            try container.encode(value)
        case let .string(value):
            try container.encode(value)
        case let .array(value):
            try container.encode(value)
        case let .object(value):
            try container.encode(value)
        }
    }
}

public struct RoundAnalysisResult: Codable, Equatable, Sendable {
    public let analysisID: UUID
    public let terminalStatus: String
    public let reconstructionStatus: RoundAnalysisReconstructionStatus
    public let hypotheses: [[String: RoundAnalysisJSONValue]]
    public let focusedDecisions: [[String: RoundAnalysisJSONValue]]
    public let diagnostics: [String: RoundAnalysisJSONValue]
    public let inputArtifactID: String
    public let inputArtifactSHA256: String
    public let resultArtifactID: String
    public let resultArtifactSHA256: String

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case analysisID = "analysis_id"
        case terminalStatus = "terminal_status"
        case reconstructionStatus = "reconstruction_status"
        case hypotheses
        case focusedDecisions = "focused_decisions"
        case diagnostics
        case inputArtifactID = "input_artifact_id"
        case inputArtifactSHA256 = "input_artifact_sha256"
        case resultArtifactID = "result_artifact_id"
        case resultArtifactSHA256 = "result_artifact_sha256"
    }

    public init(
        analysisID: UUID,
        terminalStatus: String = "complete",
        reconstructionStatus: RoundAnalysisReconstructionStatus,
        hypotheses: [[String: RoundAnalysisJSONValue]],
        focusedDecisions: [[String: RoundAnalysisJSONValue]],
        diagnostics: [String: RoundAnalysisJSONValue],
        inputArtifactID: String,
        inputArtifactSHA256: String,
        resultArtifactID: String,
        resultArtifactSHA256: String
    ) {
        self.analysisID = analysisID
        self.terminalStatus = terminalStatus
        self.reconstructionStatus = reconstructionStatus
        self.hypotheses = hypotheses
        self.focusedDecisions = focusedDecisions
        self.diagnostics = diagnostics
        self.inputArtifactID = inputArtifactID
        self.inputArtifactSHA256 = inputArtifactSHA256
        self.resultArtifactID = resultArtifactID
        self.resultArtifactSHA256 = resultArtifactSHA256
    }

    public init(from decoder: Decoder) throws {
        try roundAnalysisRequireExactKeys(decoder, CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        analysisID = try container.decode(UUID.self, forKey: .analysisID)
        terminalStatus = try container.decode(String.self, forKey: .terminalStatus)
        reconstructionStatus = try container.decode(
            RoundAnalysisReconstructionStatus.self,
            forKey: .reconstructionStatus
        )
        hypotheses = try container.decode([[String: RoundAnalysisJSONValue]].self, forKey: .hypotheses)
        focusedDecisions = try container.decode(
            [[String: RoundAnalysisJSONValue]].self,
            forKey: .focusedDecisions
        )
        diagnostics = try container.decode([String: RoundAnalysisJSONValue].self, forKey: .diagnostics)
        inputArtifactID = try container.decode(String.self, forKey: .inputArtifactID)
        inputArtifactSHA256 = try container.decode(String.self, forKey: .inputArtifactSHA256)
        resultArtifactID = try container.decode(String.self, forKey: .resultArtifactID)
        resultArtifactSHA256 = try container.decode(String.self, forKey: .resultArtifactSHA256)
        guard terminalStatus == "complete",
              !inputArtifactID.isEmpty,
              !resultArtifactID.isEmpty,
              roundAnalysisIsSHA256(inputArtifactSHA256),
              roundAnalysisIsSHA256(resultArtifactSHA256) else {
            throw RoundAnalysisContractError.invalidResponse
        }
    }
}

/// The exact request accepted by `POST /v1/round-analyses`.
public struct RoundAnalysisCreateRequest: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let analysisID: UUID
    public let recordingID: String
    public let roundID: String
    public let sessionID: UUID
    public let roundSetup: RoundRecordingSetup
    public let evidencePackageIDs: [UUID]
    public let search: RoundAnalysisSearchLimits

    public init(
        analysisID: UUID,
        recordingID: String,
        sessionID: UUID,
        roundSetup: RoundRecordingSetup,
        evidencePackageIDs: [UUID],
        search: RoundAnalysisSearchLimits = RoundAnalysisSearchLimits()
    ) throws {
        guard roundAnalysisIsIdentifier(recordingID),
              roundAnalysisIsIdentifier(roundSetup.gameID),
              roundAnalysisIsIdentifier(roundSetup.roundID),
              roundSetup.roundID == "round-\(recordingID)",
              !evidencePackageIDs.isEmpty,
              Set(evidencePackageIDs).count == evidencePackageIDs.count else {
            throw RoundAnalysisContractError.invalidRequest
        }
        schemaVersion = roundAnalysisSchemaVersion
        self.analysisID = analysisID
        self.recordingID = recordingID
        roundID = roundSetup.roundID
        self.sessionID = sessionID
        self.roundSetup = roundSetup
        self.evidencePackageIDs = evidencePackageIDs
        self.search = search
    }

    public init(from decoder: Decoder) throws {
        try roundAnalysisRequireExactKeys(decoder, CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        analysisID = try container.decode(UUID.self, forKey: .analysisID)
        recordingID = try container.decode(String.self, forKey: .recordingID)
        roundID = try container.decode(String.self, forKey: .roundID)
        sessionID = try container.decode(UUID.self, forKey: .sessionID)
        roundSetup = try container.decode(RoundRecordingSetup.self, forKey: .roundSetup)
        evidencePackageIDs = try container.decode([UUID].self, forKey: .evidencePackageIDs)
        search = try container.decode(RoundAnalysisSearchLimits.self, forKey: .search)
        guard schemaVersion == roundAnalysisSchemaVersion,
              roundAnalysisIsIdentifier(recordingID),
              roundAnalysisIsIdentifier(roundSetup.gameID),
              roundAnalysisIsIdentifier(roundSetup.roundID),
              roundSetup.roundID == roundID,
              roundID == "round-\(recordingID)",
              !evidencePackageIDs.isEmpty,
              Set(evidencePackageIDs).count == evidencePackageIDs.count else {
            throw RoundAnalysisContractError.invalidRequest
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case analysisID = "analysis_id"
        case recordingID = "recording_id"
        case roundID = "round_id"
        case sessionID = "session_id"
        case roundSetup = "round_setup"
        case evidencePackageIDs = "evidence_package_ids"
        case search
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(analysisID.uuidString.lowercased(), forKey: .analysisID)
        try container.encode(recordingID, forKey: .recordingID)
        try container.encode(roundID, forKey: .roundID)
        try container.encode(sessionID.uuidString.lowercased(), forKey: .sessionID)
        try container.encode(roundSetup, forKey: .roundSetup)
        try container.encode(
            evidencePackageIDs.map { $0.uuidString.lowercased() },
            forKey: .evidencePackageIDs
        )
        try container.encode(search, forKey: .search)
    }
}

/// The durable status document returned by the create and polling APIs.
public struct RoundAnalysisStatus: Codable, Equatable, Sendable {
    public let analysisID: UUID
    public let recordingID: String
    public let roundID: String
    public let sessionID: UUID
    public let state: RoundAnalysisRemoteState
    public let totalEvidencePackages: Int
    public let completedEvidencePackages: Int
    public let result: RoundAnalysisResult?
    public let error: String?
    public let createdAt: Date
    public let startedAt: Date?
    public let completedAt: Date?

    public var isTerminal: Bool { state.isTerminal }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case analysisID = "analysis_id"
        case recordingID = "recording_id"
        case roundID = "round_id"
        case sessionID = "session_id"
        case state
        case totalEvidencePackages = "total_evidence_packages"
        case completedEvidencePackages = "completed_evidence_packages"
        case result
        case error
        case createdAt = "created_at"
        case startedAt = "started_at"
        case completedAt = "completed_at"
    }

    public init(from decoder: Decoder) throws {
        try roundAnalysisRequireExactKeys(decoder, CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        analysisID = try container.decode(UUID.self, forKey: .analysisID)
        recordingID = try container.decode(String.self, forKey: .recordingID)
        roundID = try container.decode(String.self, forKey: .roundID)
        sessionID = try container.decode(UUID.self, forKey: .sessionID)
        state = try container.decode(RoundAnalysisRemoteState.self, forKey: .state)
        totalEvidencePackages = try container.decode(Int.self, forKey: .totalEvidencePackages)
        completedEvidencePackages = try container.decode(Int.self, forKey: .completedEvidencePackages)
        result = try container.decodeIfPresent(RoundAnalysisResult.self, forKey: .result)
        error = try container.decodeIfPresent(String.self, forKey: .error)
        createdAt = try roundAnalysisDecodeDate(container, forKey: .createdAt)
        startedAt = try roundAnalysisDecodeOptionalDate(container, forKey: .startedAt)
        completedAt = try roundAnalysisDecodeOptionalDate(container, forKey: .completedAt)
        guard totalEvidencePackages >= 0,
              completedEvidencePackages >= 0,
              completedEvidencePackages <= totalEvidencePackages,
              lifecycleIsValid else {
            throw RoundAnalysisContractError.invalidResponse
        }
    }

    private var lifecycleIsValid: Bool {
        switch state {
        case .complete:
            return result != nil
                && error == nil
                && completedAt != nil
                && completedEvidencePackages == totalEvidencePackages
                && result?.analysisID == analysisID
        case .failed:
            return result == nil && error?.isEmpty == false && completedAt != nil
        case .queued, .analyzingEvidence, .reconstructing:
            return result == nil && error == nil && completedAt == nil
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(analysisID.uuidString.lowercased(), forKey: .analysisID)
        try container.encode(recordingID, forKey: .recordingID)
        try container.encode(roundID, forKey: .roundID)
        try container.encode(sessionID.uuidString.lowercased(), forKey: .sessionID)
        try container.encode(state, forKey: .state)
        try container.encode(totalEvidencePackages, forKey: .totalEvidencePackages)
        try container.encode(completedEvidencePackages, forKey: .completedEvidencePackages)
        try container.encode(result, forKey: .result)
        try container.encode(error, forKey: .error)
        try container.encode(roundAnalysisEncodeDate(createdAt), forKey: .createdAt)
        try container.encode(startedAt.map(roundAnalysisEncodeDate), forKey: .startedAt)
        try container.encode(completedAt.map(roundAnalysisEncodeDate), forKey: .completedAt)
    }
}

public enum RoundAnalysisSubmissionPhase: String, Codable, Equatable, Sendable {
    case waitingForUploads = "waiting_for_uploads"
    case submitting
    case queued
    case analyzingEvidence = "analyzing_evidence"
    case reconstructing
    case complete
    case failed
}

public enum RoundAnalysisSubmissionReadiness: Equatable, Sendable {
    case waitingForUploads
    case noEvidence
    case ready
}

/// A short, user-facing explanation of a completed reconstruction result.
public struct RoundAnalysisResultSummary: Equatable, Sendable {
    public let reconstructionStatus: RoundAnalysisReconstructionStatus
    public let text: String

    public init(result: RoundAnalysisResult) {
        reconstructionStatus = result.reconstructionStatus
        text = Self.makeText(for: result)
    }

    private static func makeText(for result: RoundAnalysisResult) -> String {
        switch result.reconstructionStatus {
        case .resolved:
            var trickCount: Int?
            if let hypothesis = result.hypotheses.first,
               case let .object(gameplay)? = hypothesis["gameplay"],
               case let .array(tricks)? = gameplay["tricks"] {
                trickCount = tricks.count
            }
            if let trickCount {
                return "Resolved hypothesis with \(trickCount) tricks"
            }
            return "Resolved hypothesis"
        case .ambiguous:
            let hypothesisCount = result.hypotheses.count
            let decisionCount = result.focusedDecisions.count
            return "Ambiguous: \(hypothesisCount) hypotheses, \(decisionCount) focused decisions"
        case .incomplete:
            if let count = arrayCount(in: result.diagnostics, forKey: "incomplete_observations") {
                return "Incomplete: \(count) incomplete observation\(count == 1 ? "" : "s")"
            }
            return "Incomplete: inspect engine diagnostics"
        case .impossible:
            if let count = arrayCount(in: result.diagnostics, forKey: "rejected_branches") {
                return "Impossible: \(count) rejected branch\(count == 1 ? "" : "es")"
            }
            return "Impossible: inspect engine diagnostics"
        }
    }

    private static func arrayCount(
        in values: [String: RoundAnalysisJSONValue],
        forKey key: String
    ) -> Int? {
        guard case let .array(values)? = values[key] else { return nil }
        return values.count
    }
}

public extension RoundRecordingState {
    var roundAnalysisSubmissionReadiness: RoundAnalysisSubmissionReadiness {
        guard evidenceMembershipClosed,
              recordingBundleFinalized,
              recordingBundleAcknowledged else {
            return .waitingForUploads
        }
        guard hasEvidencePackages else {
            return .noEvidence
        }
        return allEvidencePackagesAcknowledged ? .ready : .waitingForUploads
    }
}

/// Durable request identity and the latest remote status for one recording.
public struct RoundAnalysisSubmissionState: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let analysisID: UUID?
    public let recordingID: String
    public let sessionID: UUID
    public let roundSetup: RoundRecordingSetup
    public let evidencePackageIDs: [UUID]
    public let search: RoundAnalysisSearchLimits
    public let phase: RoundAnalysisSubmissionPhase
    public let remoteStatus: RoundAnalysisStatus?
    public let error: String?
    public let createdAtUTC: Date
    public let updatedAtUTC: Date

    public init(
        recordingID: String,
        sessionID: UUID,
        roundSetup: RoundRecordingSetup,
        evidencePackageIDs: [UUID],
        search: RoundAnalysisSearchLimits = RoundAnalysisSearchLimits(),
        analysisID: UUID? = nil,
        phase: RoundAnalysisSubmissionPhase = .waitingForUploads,
        remoteStatus: RoundAnalysisStatus? = nil,
        error: String? = nil,
        createdAtUTC: Date = Date(),
        updatedAtUTC: Date = Date()
    ) throws {
        guard roundAnalysisIsIdentifier(recordingID),
              roundAnalysisIsIdentifier(roundSetup.gameID),
              roundAnalysisIsIdentifier(roundSetup.roundID),
              roundSetup.roundID == "round-\(recordingID)",
              Set(evidencePackageIDs).count == evidencePackageIDs.count,
              createdAtUTC.timeIntervalSinceReferenceDate.isFinite,
              updatedAtUTC.timeIntervalSinceReferenceDate.isFinite,
              remoteStatus.map({ $0.analysisID == analysisID }) ?? true else {
            throw RoundAnalysisContractError.invalidStoredState
        }
        if phase == .failed, error?.isEmpty != false {
            throw RoundAnalysisContractError.invalidStoredState
        }
        if phase == .complete, remoteStatus?.state != .complete {
            throw RoundAnalysisContractError.invalidStoredState
        }
        schemaVersion = roundAnalysisSubmissionStateSchemaVersion
        self.analysisID = analysisID
        self.recordingID = recordingID
        self.sessionID = sessionID
        self.roundSetup = roundSetup
        self.evidencePackageIDs = evidencePackageIDs
        self.search = search
        self.phase = phase
        self.remoteStatus = remoteStatus
        self.error = error
        self.createdAtUTC = createdAtUTC
        self.updatedAtUTC = updatedAtUTC
    }

    public func updating(
        phase: RoundAnalysisSubmissionPhase,
        remoteStatus: RoundAnalysisStatus? = nil,
        error: String? = nil,
        updatedAtUTC: Date = Date()
    ) throws -> Self {
        try Self(
            recordingID: recordingID,
            sessionID: sessionID,
            roundSetup: roundSetup,
            evidencePackageIDs: evidencePackageIDs,
            search: search,
            analysisID: analysisID,
            phase: phase,
            remoteStatus: remoteStatus,
            error: error,
            createdAtUTC: createdAtUTC,
            updatedAtUTC: updatedAtUTC
        )
    }

    public var createRequest: RoundAnalysisCreateRequest? {
        guard let analysisID, !evidencePackageIDs.isEmpty else { return nil }
        return try? RoundAnalysisCreateRequest(
            analysisID: analysisID,
            recordingID: recordingID,
            sessionID: sessionID,
            roundSetup: roundSetup,
            evidencePackageIDs: evidencePackageIDs,
            search: search
        )
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case analysisID = "analysis_id"
        case recordingID = "recording_id"
        case sessionID = "session_id"
        case roundSetup = "round_setup"
        case evidencePackageIDs = "evidence_package_ids"
        case search
        case phase
        case remoteStatus = "remote_status"
        case error
        case createdAtUTC = "created_at_utc"
        case updatedAtUTC = "updated_at_utc"
    }

    public init(from decoder: Decoder) throws {
        try roundAnalysisRequireExactKeys(decoder, CodingKeys.self)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        let analysisID = try container.decodeIfPresent(UUID.self, forKey: .analysisID)
        let recordingID = try container.decode(String.self, forKey: .recordingID)
        let sessionID = try container.decode(UUID.self, forKey: .sessionID)
        let roundSetup = try container.decode(RoundRecordingSetup.self, forKey: .roundSetup)
        let evidencePackageIDs = try container.decode([UUID].self, forKey: .evidencePackageIDs)
        let search = try container.decode(RoundAnalysisSearchLimits.self, forKey: .search)
        let phase = try container.decode(RoundAnalysisSubmissionPhase.self, forKey: .phase)
        let remoteStatus = try container.decodeIfPresent(RoundAnalysisStatus.self, forKey: .remoteStatus)
        let error = try container.decodeIfPresent(String.self, forKey: .error)
        let createdAtUTC = try roundAnalysisDecodeDate(container, forKey: .createdAtUTC)
        let updatedAtUTC = try roundAnalysisDecodeDate(container, forKey: .updatedAtUTC)
        guard schemaVersion == roundAnalysisSubmissionStateSchemaVersion else {
            throw RoundAnalysisContractError.invalidStoredState
        }
        if let remoteStatus {
            let expectedPhase: RoundAnalysisSubmissionPhase
            switch remoteStatus.state {
            case .queued:
                expectedPhase = .queued
            case .analyzingEvidence:
                expectedPhase = .analyzingEvidence
            case .reconstructing:
                expectedPhase = .reconstructing
            case .complete:
                expectedPhase = .complete
            case .failed:
                expectedPhase = .failed
            }
            guard phase == expectedPhase else {
                throw RoundAnalysisContractError.invalidStoredState
            }
        }
        self = try Self(
            recordingID: recordingID,
            sessionID: sessionID,
            roundSetup: roundSetup,
            evidencePackageIDs: evidencePackageIDs,
            search: search,
            analysisID: analysisID,
            phase: phase,
            remoteStatus: remoteStatus,
            error: error,
            createdAtUTC: createdAtUTC,
            updatedAtUTC: updatedAtUTC
        )
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(analysisID?.uuidString.lowercased(), forKey: .analysisID)
        try container.encode(recordingID, forKey: .recordingID)
        try container.encode(sessionID.uuidString.lowercased(), forKey: .sessionID)
        try container.encode(roundSetup, forKey: .roundSetup)
        try container.encode(
            evidencePackageIDs.map { $0.uuidString.lowercased() },
            forKey: .evidencePackageIDs
        )
        try container.encode(search, forKey: .search)
        try container.encode(phase, forKey: .phase)
        try container.encode(remoteStatus, forKey: .remoteStatus)
        try container.encode(error, forKey: .error)
        try container.encode(roundAnalysisEncodeDate(createdAtUTC), forKey: .createdAtUTC)
        try container.encode(roundAnalysisEncodeDate(updatedAtUTC), forKey: .updatedAtUTC)
    }
}

public enum RoundAnalysisDisplayState: Equatable, Sendable {
    case idle
    case waitingForUploads
    case queued
    case analyzingEvidence(completed: Int, total: Int)
    case reconstructing
    case complete(RoundAnalysisResultSummary)
    case failed(String)

    public var isFailure: Bool {
        if case .failed = self { return true }
        return false
    }

    public var title: String {
        switch self {
        case .idle: return ""
        case .waitingForUploads: return "Waiting for uploads"
        case .queued: return "Queued"
        case .analyzingEvidence: return "Analyzing evidence"
        case .reconstructing: return "Reconstructing"
        case .complete: return "Complete"
        case .failed: return "Failed"
        }
    }

    public var detail: String? {
        switch self {
        case .idle, .waitingForUploads, .queued, .reconstructing:
            return nil
        case let .analyzingEvidence(completed, total):
            return "Analyzing evidence \(completed) of \(total)"
        case let .complete(summary):
            return summary.text
        case let .failed(message):
            return message
        }
    }
}

public enum RoundAnalysisContractError: LocalizedError, Equatable, Sendable {
    case invalidRequest
    case invalidResponse
    case invalidStoredState
    case nonSuccessResponse(Int, Data)
    case analysisIDMismatch(expected: UUID, received: UUID)
    case recordingIDMismatch(expected: String, received: String)
    case invalidResponseBody(String)
    case cannotRead(URL, String)
    case cannotWrite(URL, String)

    public var errorDescription: String? {
        switch self {
        case .invalidRequest:
            return "The round-analysis request is invalid."
        case .invalidResponse:
            return "The round-analysis request returned an invalid response."
        case .invalidStoredState:
            return "The stored round-analysis submission is invalid."
        case let .nonSuccessResponse(status, _):
            return "The round-analysis request failed with HTTP status \(status)."
        case let .analysisIDMismatch(expected, received):
            return "The round analysis belongs to \(received.uuidString.lowercased()), expected \(expected.uuidString.lowercased())."
        case let .recordingIDMismatch(expected, received):
            return "The round analysis belongs to recording \(received), expected \(expected)."
        case let .invalidResponseBody(message):
            return "The round-analysis response is invalid: \(message)"
        case let .cannotRead(url, message):
            return "The round-analysis submission could not be read at \(url.path): \(message)"
        case let .cannotWrite(url, message):
            return "The round-analysis submission could not be written at \(url.path): \(message)"
        }
    }
}

/// Persists the analysis request identity beside the recording queue.
public final class RoundAnalysisSubmissionStore: @unchecked Sendable {
    public let directory: URL
    public let stateURL: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()

    public init(directory: URL, stateFileName: String = "round-analysis.json") {
        self.directory = directory
        stateURL = directory.appendingPathComponent(stateFileName, isDirectory: false)
    }

    public func load() throws -> RoundAnalysisSubmissionState? {
        lock.lock()
        defer { lock.unlock() }
        guard fileManager.fileExists(atPath: stateURL.path) else { return nil }
        do {
            return try JSONDecoder().decode(
                RoundAnalysisSubmissionState.self,
                from: Data(contentsOf: stateURL)
            )
        } catch {
            throw RoundAnalysisContractError.cannotRead(stateURL, error.localizedDescription)
        }
    }

    public func save(_ state: RoundAnalysisSubmissionState) throws {
        lock.lock()
        defer { lock.unlock() }
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(state).write(to: stateURL, options: .atomic)
        } catch {
            throw RoundAnalysisContractError.cannotWrite(stateURL, error.localizedDescription)
        }
    }

    public func remove() throws {
        lock.lock()
        defer { lock.unlock() }
        guard fileManager.fileExists(atPath: stateURL.path) else { return }
        do {
            try fileManager.removeItem(at: stateURL)
        } catch {
            throw RoundAnalysisContractError.cannotWrite(stateURL, error.localizedDescription)
        }
    }
}

/// Sends create and status requests for the durable round-analysis contract.
public final class RoundAnalysisClient: @unchecked Sendable {
    private let session: URLSession

    public init(session: URLSession? = nil) {
        self.session = session ?? Self.makeSession()
    }

    public func create(
        request payload: RoundAnalysisCreateRequest,
        using configuration: BackendConfiguration
    ) async throws -> RoundAnalysisStatus {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let body: Data
        do {
            body = try encoder.encode(payload)
        } catch {
            throw RoundAnalysisContractError.invalidRequest
        }
        var request = URLRequest(url: configuration.roundAnalysesURL())
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw RoundAnalysisContractError.invalidResponse
        }
        guard response.statusCode == 202 else {
            throw RoundAnalysisContractError.nonSuccessResponse(response.statusCode, data)
        }
        let status = try Self.decodeStatus(data)
        try Self.validate(status, for: payload)
        return status
    }

    public func status(
        for analysisID: UUID,
        using configuration: BackendConfiguration
    ) async throws -> RoundAnalysisStatus {
        var request = URLRequest(url: configuration.roundAnalysisURL(for: analysisID))
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw RoundAnalysisContractError.invalidResponse
        }
        guard response.statusCode == 200 else {
            throw RoundAnalysisContractError.nonSuccessResponse(response.statusCode, data)
        }
        let status = try Self.decodeStatus(data)
        guard status.analysisID == analysisID else {
            throw RoundAnalysisContractError.analysisIDMismatch(
                expected: analysisID,
                received: status.analysisID
            )
        }
        return status
    }

    private static func decodeStatus(_ data: Data) throws -> RoundAnalysisStatus {
        do {
            return try JSONDecoder().decode(RoundAnalysisStatus.self, from: data)
        } catch let error as RoundAnalysisContractError {
            throw error
        } catch {
            throw RoundAnalysisContractError.invalidResponseBody(error.localizedDescription)
        }
    }

    private static func validate(
        _ status: RoundAnalysisStatus,
        for request: RoundAnalysisCreateRequest
    ) throws {
        guard status.analysisID == request.analysisID else {
            throw RoundAnalysisContractError.analysisIDMismatch(
                expected: request.analysisID,
                received: status.analysisID
            )
        }
        guard status.recordingID == request.recordingID else {
            throw RoundAnalysisContractError.recordingIDMismatch(
                expected: request.recordingID,
                received: status.recordingID
            )
        }
        guard status.roundID == request.roundID, status.sessionID == request.sessionID else {
            throw RoundAnalysisContractError.invalidResponse
        }
    }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 2
        configuration.timeoutIntervalForResource = 5
        return URLSession(configuration: configuration)
    }
}

public extension BackendConfiguration {
    func roundAnalysesURL() -> URL {
        baseURL
            .appendingPathComponent("v1", isDirectory: true)
            .appendingPathComponent("round-analyses", isDirectory: false)
    }

    func roundAnalysisURL(for analysisID: UUID) -> URL {
        roundAnalysesURL().appendingPathComponent(analysisID.uuidString.lowercased())
    }
}

private func roundAnalysisIsIdentifier(_ value: String) -> Bool {
    guard value.utf8.count <= 128,
          let first = value.unicodeScalars.first,
          (0x30...0x39).contains(first.value)
            || (0x41...0x5A).contains(first.value)
            || (0x61...0x7A).contains(first.value) else {
        return false
    }
    return value.unicodeScalars.dropFirst().allSatisfy { scalar in
        (0x30...0x39).contains(scalar.value)
            || (0x41...0x5A).contains(scalar.value)
            || (0x61...0x7A).contains(scalar.value)
            || [0x2E, 0x3A, 0x5F, 0x2D].contains(scalar.value)
    }
}

private func roundAnalysisIsSHA256(_ value: String) -> Bool {
    value.utf8.count == 64
        && value.utf8.allSatisfy { byte in
            (0x30...0x39).contains(byte)
                || (0x41...0x46).contains(byte)
                || (0x61...0x66).contains(byte)
        }
}

private struct RoundAnalysisAnyCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil

    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}

private func roundAnalysisRequireExactKeys<Key: CodingKey & CaseIterable>(
    _ decoder: Decoder,
    _ keyType: Key.Type
) throws {
    let container = try decoder.container(keyedBy: RoundAnalysisAnyCodingKey.self)
    let expected = Set(keyType.allCases.map(\.stringValue))
    let actual = Set(container.allKeys.map(\.stringValue))
    guard actual == expected else {
        throw RoundAnalysisContractError.invalidStoredState
    }
}

private func roundAnalysisEncodeDate(_ date: Date) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.string(from: date)
}

private func roundAnalysisDecodeDate<Key: CodingKey>(
    _ container: KeyedDecodingContainer<Key>,
    forKey key: Key
) throws -> Date {
    guard let date = roundAnalysisDecodeISO8601(try container.decode(String.self, forKey: key)) else {
        throw RoundAnalysisContractError.invalidResponse
    }
    return date
}

private func roundAnalysisDecodeOptionalDate<Key: CodingKey>(
    _ container: KeyedDecodingContainer<Key>,
    forKey key: Key
) throws -> Date? {
    guard let value = try container.decodeIfPresent(String.self, forKey: key) else { return nil }
    guard let date = roundAnalysisDecodeISO8601(value) else {
        throw RoundAnalysisContractError.invalidResponse
    }
    return date
}

private func roundAnalysisDecodeISO8601(_ value: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = formatter.date(from: value) { return date }
    formatter.formatOptions = [.withInternetDateTime]
    return formatter.date(from: value)
}
