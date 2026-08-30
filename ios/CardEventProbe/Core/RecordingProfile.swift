import Foundation

public let recordingProfileSchemaVersion = "recording-profile/v1"

public enum RecordingPurpose: String, Codable, CaseIterable, Sendable {
    case weirdTestStuff = "weird_test_stuff"
    case approximateFortyCardSetup = "approximate_forty_card_setup"
    case plausibleStagedRound = "plausible_staged_round"
    case realGame = "real_game"

    public var title: String {
        switch self {
        case .weirdTestStuff:
            return "Weird test stuff"
        case .approximateFortyCardSetup:
            return "Roughly forty cards in a roughly real-world camera setup"
        case .plausibleStagedRound:
            return "Plausible round, but not real"
        case .realGame:
            return "Real game"
        }
    }

    public var sourceContentType: String {
        self == .realGame ? "real_game" : "staged_scenario"
    }

    public func mapping(for appRunContext: AppRunContext) -> RecordingPurposeMapping {
        RecordingPurposeMapping(purpose: self, appRunContext: appRunContext)
    }
}

public struct AppRunContext: Equatable, Sendable {
    public let sessionID: UUID

    public init(sessionID: UUID = UUID()) {
        self.sessionID = sessionID
    }

    public var appRunSessionID: UUID { sessionID }

    public var sessionIDString: String {
        sessionID.uuidString.lowercased()
    }

    public func mapping(for purpose: RecordingPurpose) -> RecordingPurposeMapping {
        purpose.mapping(for: self)
    }
}

public struct RecordingPurposeMapping: Equatable, Sendable {
    public let purpose: RecordingPurpose
    public let sourceContentType: String
    public let sourceGameID: String?
    public let analysisGameID: String

    public init(purpose: RecordingPurpose, appRunContext: AppRunContext) {
        self.purpose = purpose
        sourceContentType = purpose.sourceContentType
        if purpose == .realGame {
            let gameID = "game-\(appRunContext.sessionIDString)"
            sourceGameID = gameID
            analysisGameID = gameID
        } else {
            sourceGameID = nil
            analysisGameID = "analysis-game-\(appRunContext.sessionIDString)"
        }
    }
}

public struct RecordingTaskSetting: Codable, Equatable, Sendable {
    public var task: RepositoryDataTask
    public var disposition: RepositoryTaskDisposition
    public var reason: String?

    public init(
        task: RepositoryDataTask,
        disposition: RepositoryTaskDisposition = .selected,
        reason: String? = nil
    ) {
        self.task = task
        self.disposition = disposition
        self.reason = reason
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case task
        case disposition
        case reason
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try recordingProfileRequireExactKeys(container, CodingKeys.self)
        task = try container.decode(RepositoryDataTask.self, forKey: .task)
        disposition = try container.decode(RepositoryTaskDisposition.self, forKey: .disposition)
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(task, forKey: .task)
        try container.encode(disposition, forKey: .disposition)
        try container.encode(reason, forKey: .reason)
    }
}

public typealias RecordingProfileTaskSetting = RecordingTaskSetting

public enum RecordingProfileValidationField: String, Codable, CaseIterable, Sendable {
    case name
    case purpose
    case tags
    case taskSettings = "task_settings"

    public static var profileName: Self { .name }
}

public struct RecordingProfileValidationIssue: Equatable, Sendable {
    public let field: RecordingProfileValidationField
    public let message: String

    public init(field: RecordingProfileValidationField, message: String) {
        self.field = field
        self.message = message
    }
}

public struct RecordingProfile: Codable, Equatable, Identifiable, Sendable {
    public let schemaVersion: String
    public let profileID: String
    public var name: String
    public var purpose: RecordingPurpose
    public var tags: [String]
    public var taskSettings: [RecordingTaskSetting]

    public var id: String { profileID }

    public init(
        profileID: String,
        name: String,
        purpose: RecordingPurpose,
        tags: [String],
        taskSettings: [RecordingTaskSetting] = RecordingProfile.defaultTaskSettings,
        schemaVersion: String = recordingProfileSchemaVersion
    ) {
        self.schemaVersion = schemaVersion
        self.profileID = profileID
        self.name = name
        self.purpose = purpose
        self.tags = tags
        self.taskSettings = taskSettings
    }

    public static func newDraft(
        profileID: String = "profile-\(UUID().uuidString.lowercased())"
    ) -> RecordingProfile {
        RecordingProfile(
            profileID: profileID,
            name: "",
            purpose: .weirdTestStuff,
            tags: []
        )
    }

    public var validationIssues: [RecordingProfileValidationIssue] {
        var issues: [RecordingProfileValidationIssue] = []
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append(
                RecordingProfileValidationIssue(field: .name, message: "Enter a profile name.")
            )
        }
        if tags.isEmpty || tags.contains(where: { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
            issues.append(
                RecordingProfileValidationIssue(field: .tags, message: "Add at least one tag.")
            )
        } else if tags.count != Set(tags).count {
            issues.append(
                RecordingProfileValidationIssue(field: .tags, message: "Tags must not contain duplicates.")
            )
        }

        guard taskSettings.count == RepositoryDataTask.allCases.count,
              Set(taskSettings.map(\.task)) == Set(RepositoryDataTask.allCases) else {
            issues.append(
                RecordingProfileValidationIssue(
                    field: .taskSettings,
                    message: "Set one disposition for each data task."
                )
            )
            return issues
        }
        for setting in taskSettings {
            if setting.disposition == .excluded {
                if setting.reason?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false {
                    issues.append(
                        RecordingProfileValidationIssue(
                            field: .taskSettings,
                            message: "Give an exclusion reason for \(setting.task.rawValue)."
                        )
                    )
                }
            } else if setting.reason != nil {
                issues.append(
                    RecordingProfileValidationIssue(
                        field: .taskSettings,
                        message: "Selected and deferred tasks must not have a reason."
                    )
                )
            }
        }
        return issues
    }

    public var isComplete: Bool { validationIssues.isEmpty }

    public func taskSetting(for task: RepositoryDataTask) -> RecordingTaskSetting? {
        taskSettings.first { $0.task == task }
    }

    public func makeTaskEnrollments(
        recordingID: String,
        createdAtUTC: String,
        operatorSettings: OperatorSettings
    ) throws -> [RepositoryTaskEnrollment] {
        guard isComplete else { throw RecordingProfileError.incomplete(validationIssues) }
        guard recordingProfileIsIdentifier(recordingID), recordingProfileIsUTCTimestamp(createdAtUTC) else {
            throw RecordingProfileError.invalidRecordingIdentity
        }
        guard operatorSettings.isComplete else {
            throw RecordingProfileError.operatorNameMissing
        }

        return try RepositoryDataTask.allCases.map { task in
            let setting = taskSetting(for: task)!
            return try RepositoryTaskEnrollment(
                taskEnrollmentID: "\(recordingID)-\(task.rawValue)",
                task: task,
                disposition: setting.disposition,
                operatorName: operatorSettings.operatorName,
                createdAtUTC: createdAtUTC,
                reason: setting.reason
            )
        }
    }

    public static let defaultTaskSettings = RepositoryDataTask.allCases.map {
        RecordingTaskSetting(task: $0)
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case profileID = "profile_id"
        case name
        case purpose
        case tags
        case taskSettings = "task_settings"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try recordingProfileRequireExactKeys(container, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        profileID = try container.decode(String.self, forKey: .profileID)
        name = try container.decode(String.self, forKey: .name)
        purpose = try container.decode(RecordingPurpose.self, forKey: .purpose)
        tags = try container.decode([String].self, forKey: .tags)
        taskSettings = try container.decode([RecordingTaskSetting].self, forKey: .taskSettings)
        guard schemaVersion == recordingProfileSchemaVersion,
              recordingProfileIsIdentifier(profileID),
              taskSettings.count == RepositoryDataTask.allCases.count,
              Set(taskSettings.map(\.task)) == Set(RepositoryDataTask.allCases) else {
            throw RecordingProfileError.invalidProfile
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(profileID, forKey: .profileID)
        try container.encode(name, forKey: .name)
        try container.encode(purpose, forKey: .purpose)
        try container.encode(tags, forKey: .tags)
        try container.encode(taskSettings, forKey: .taskSettings)
    }
}

public struct OperatorSettings: Codable, Equatable, Sendable {
    public var operatorName: String

    public init(operatorName: String = "") {
        self.operatorName = operatorName
    }

    public var isComplete: Bool {
        !operatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case operatorName = "operator_name"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try recordingProfileRequireExactKeys(container, CodingKeys.self)
        operatorName = try container.decode(String.self, forKey: .operatorName)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(operatorName, forKey: .operatorName)
    }
}

public struct FixedRecordingMetadata: Equatable, Sendable {
    public let tableSetup: String
    public let cardDeck: String
    public let cameraView: String
    public let cameraMotion: String
    public let cameraFraming: String
    public let lighting: [String]
    public let background: String
    public let sourcePermission: String
    public let knownLimitations: [String]
    public let notes: String?

    public init(
        tableSetup: String = "default_table_setup",
        cardDeck: String = "french_common_back_v1",
        cameraView: String = "overhead",
        cameraMotion: String = "fixed",
        cameraFraming: String = "table_with_context",
        lighting: [String] = ["not_recorded"],
        background: String = "not_recorded",
        sourcePermission: String = "project_use",
        knownLimitations: [String] = [],
        notes: String? = nil
    ) {
        self.tableSetup = tableSetup
        self.cardDeck = cardDeck
        self.cameraView = cameraView
        self.cameraMotion = cameraMotion
        self.cameraFraming = cameraFraming
        self.lighting = lighting
        self.background = background
        self.sourcePermission = sourcePermission
        self.knownLimitations = knownLimitations
        self.notes = notes
    }

    public static let current = FixedRecordingMetadata()
    public static let defaultValue = FixedRecordingMetadata()
}

public enum RecordingMetadataAdapterError: LocalizedError, Equatable, Sendable {
    case incompleteProfile([RecordingProfileValidationIssue])
    case operatorNameMissing

    public var errorDescription: String? {
        switch self {
        case let .incompleteProfile(issues):
            return issues.map { "\($0.field.rawValue): \($0.message)" }.joined(separator: " ")
        case .operatorNameMissing:
            return "Enter the operator name."
        }
    }
}

public struct RecordingMetadataAdapter: Sendable {
    public let fixedMetadata: FixedRecordingMetadata

    public init(fixedMetadata: FixedRecordingMetadata = .current) {
        self.fixedMetadata = fixedMetadata
    }

    public func makeCollectionMetadata(
        profile: RecordingProfile,
        operatorSettings: OperatorSettings,
        appRunContext: AppRunContext
    ) throws -> TrainingRecordingCollectionMetadata {
        guard profile.isComplete else {
            throw RecordingMetadataAdapterError.incompleteProfile(profile.validationIssues)
        }
        guard operatorSettings.isComplete else {
            throw RecordingMetadataAdapterError.operatorNameMissing
        }

        let mapping = profile.purpose.mapping(for: appRunContext)
        var scenarioTags = profile.tags
        if !scenarioTags.contains(profile.purpose.rawValue) {
            scenarioTags.append(profile.purpose.rawValue)
        }
        return TrainingRecordingCollectionMetadata(
            collectionProfileID: profile.profileID,
            operatorName: operatorSettings.operatorName,
            contentType: mapping.sourceContentType,
            gameID: mapping.sourceGameID,
            tableSetup: fixedMetadata.tableSetup,
            cardDeck: fixedMetadata.cardDeck,
            cameraView: fixedMetadata.cameraView,
            cameraMotion: fixedMetadata.cameraMotion,
            cameraFraming: fixedMetadata.cameraFraming,
            lighting: fixedMetadata.lighting,
            background: fixedMetadata.background,
            scenarioTags: scenarioTags,
            knownLimitations: fixedMetadata.knownLimitations,
            sourcePermission: fixedMetadata.sourcePermission,
            notes: fixedMetadata.notes
        )
    }

    public static func makeCollectionMetadata(
        profile: RecordingProfile,
        operatorSettings: OperatorSettings,
        appRunContext: AppRunContext
    ) throws -> TrainingRecordingCollectionMetadata {
        try RecordingMetadataAdapter().makeCollectionMetadata(
            profile: profile,
            operatorSettings: operatorSettings,
            appRunContext: appRunContext
        )
    }
}

extension TrainingRecordingCollectionMetadata {
    public init(
        collectionProfileID: String,
        operatorName: String,
        contentType: String,
        gameID: String?,
        tableSetup: String,
        cardDeck: String,
        cameraView: String,
        cameraMotion: String,
        cameraFraming: String,
        lighting: [String],
        background: String,
        scenarioTags: [String],
        knownLimitations: [String],
        sourcePermission: String,
        notes: String?
    ) {
        self.collectionProfileID = collectionProfileID
        self.operatorName = operatorName
        self.contentType = contentType
        self.gameID = gameID
        self.tableSetup = tableSetup
        self.cardDeck = cardDeck
        self.cameraView = cameraView
        self.cameraMotion = cameraMotion
        self.cameraFraming = cameraFraming
        self.lighting = lighting
        self.background = background
        self.scenarioTags = scenarioTags
        self.knownLimitations = knownLimitations
        self.sourcePermission = sourcePermission
        self.notes = notes
    }
}

public struct DefaultRoundAnalysisSetup: Equatable, Sendable {
    public static let fixedSeatIDs = ["seat-1", "seat-2", "seat-3", "seat-4"]

    public init() {}

    public func makeRoundSetup(
        recordingID: String,
        purpose: RecordingPurpose,
        appRunContext: AppRunContext
    ) throws -> RoundRecordingSetup {
        try RoundRecordingSetup(
            gameID: purpose.mapping(for: appRunContext).analysisGameID,
            recordingID: recordingID,
            dealer: Self.fixedSeatIDs[0],
            firstTrickLeader: Self.fixedSeatIDs[0]
        )
    }

    public func roundRecordingSetup(
        recordingID: String,
        purpose: RecordingPurpose,
        appRunContext: AppRunContext
    ) throws -> RoundRecordingSetup {
        try makeRoundSetup(
            recordingID: recordingID,
            purpose: purpose,
            appRunContext: appRunContext
        )
    }
}

public enum RecordingProfileError: LocalizedError, Equatable, Sendable {
    case incomplete([RecordingProfileValidationIssue])
    case invalidProfile
    case invalidRecordingIdentity
    case operatorNameMissing

    public var errorDescription: String? {
        switch self {
        case let .incomplete(issues):
            return issues.map { "\($0.field.rawValue): \($0.message)" }.joined(separator: " ")
        case .invalidProfile:
            return "The recording profile is invalid."
        case .invalidRecordingIdentity:
            return "The recording identity or enrollment timestamp is invalid."
        case .operatorNameMissing:
            return "Enter the operator name."
        }
    }
}

private func recordingProfileIsIdentifier(_ value: String) -> Bool {
    guard let first = value.unicodeScalars.first,
          recordingProfileIsASCIIAlphaNumeric(first) else {
        return false
    }
    return value.unicodeScalars.dropFirst().allSatisfy { scalar in
        recordingProfileIsASCIIAlphaNumeric(scalar)
            || [0x2E, 0x3A, 0x5F, 0x2D].contains(scalar.value)
    }
}

private func recordingProfileIsUTCTimestamp(_ value: String) -> Bool {
    guard value.hasSuffix("Z") else { return false }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: value) != nil || {
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value) != nil
    }()
}

private func recordingProfileIsASCIIAlphaNumeric(_ scalar: Unicode.Scalar) -> Bool {
    (0x30...0x39).contains(scalar.value)
        || (0x41...0x5A).contains(scalar.value)
        || (0x61...0x7A).contains(scalar.value)
}

private func recordingProfileRequireExactKeys<Key: CodingKey & CaseIterable>(
    _ container: KeyedDecodingContainer<Key>,
    _ keyType: Key.Type
) throws {
    let actual = Set(container.allKeys.map(\.stringValue))
    let expected = Set(keyType.allCases.map(\.stringValue))
    guard actual == expected else {
        throw RecordingProfileError.invalidProfile
    }
}
