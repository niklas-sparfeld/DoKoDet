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

public struct AppRunContext: Codable, Equatable, Sendable {
    public let sessionID: UUID

    public init(sessionID: UUID = UUID()) {
        self.sessionID = sessionID
    }

    public var appRunSessionID: UUID { sessionID }

    public var sessionIDString: String {
        sessionID.uuidString.lowercased()
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case sessionID = "session_id"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try recordingProfileRequireExactKeys(container, CodingKeys.self)
        sessionID = try container.decode(UUID.self, forKey: .sessionID)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(sessionID.uuidString.lowercased(), forKey: .sessionID)
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
        if tags.contains(where: { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
            issues.append(
                RecordingProfileValidationIssue(field: .tags, message: "Tags must not contain blank entries.")
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

public struct FixedRecordingMetadata: Codable, Equatable, Sendable {
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

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case tableSetup = "table_setup"
        case cardDeck = "card_deck"
        case cameraView = "camera_view"
        case cameraMotion = "camera_motion"
        case cameraFraming = "camera_framing"
        case lighting
        case background
        case sourcePermission = "source_permission"
        case knownLimitations = "known_limitations"
        case notes
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try recordingProfileRequireExactKeys(container, CodingKeys.self)
        self.init(
            tableSetup: try container.decode(String.self, forKey: .tableSetup),
            cardDeck: try container.decode(String.self, forKey: .cardDeck),
            cameraView: try container.decode(String.self, forKey: .cameraView),
            cameraMotion: try container.decode(String.self, forKey: .cameraMotion),
            cameraFraming: try container.decode(String.self, forKey: .cameraFraming),
            lighting: try container.decode([String].self, forKey: .lighting),
            background: try container.decode(String.self, forKey: .background),
            sourcePermission: try container.decode(String.self, forKey: .sourcePermission),
            knownLimitations: try container.decode([String].self, forKey: .knownLimitations),
            notes: try container.decodeIfPresent(String.self, forKey: .notes)
        )
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(tableSetup, forKey: .tableSetup)
        try container.encode(cardDeck, forKey: .cardDeck)
        try container.encode(cameraView, forKey: .cameraView)
        try container.encode(cameraMotion, forKey: .cameraMotion)
        try container.encode(cameraFraming, forKey: .cameraFraming)
        try container.encode(lighting, forKey: .lighting)
        try container.encode(background, forKey: .background)
        try container.encode(sourcePermission, forKey: .sourcePermission)
        try container.encode(knownLimitations, forKey: .knownLimitations)
        try container.encode(notes, forKey: .notes)
    }
}

public struct TrainingRecordingCollectionMetadata: Codable, Equatable, Sendable {
    public let collectionProfileID: String
    public let operatorName: String
    public let contentType: String
    public let gameID: String?
    public let tableSetup: String
    public let cardDeck: String
    public let cameraView: String
    public let cameraMotion: String
    public let cameraFraming: String
    public let lighting: [String]
    public let background: String
    public let scenarioTags: [String]
    public let knownLimitations: [String]
    public let sourcePermission: String
    public let notes: String?

    public var validationIssues: [String] {
        var issues: [String] = []
        if collectionProfileID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append("collection profile id is empty")
        }
        if operatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append("operator is empty")
        }
        if !["real_game", "staged_scenario"].contains(contentType) {
            issues.append("content type is invalid")
        }
        if contentType == "real_game" {
            if gameID?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false {
                issues.append("real game id is empty")
            }
        } else if gameID != nil {
            issues.append("staged source must not have a game id")
        }
        if tableSetup.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || cardDeck.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || cameraView.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || cameraMotion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || cameraFraming.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || lighting.isEmpty
            || background.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || scenarioTags.isEmpty
            || sourcePermission.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append("metadata contains an empty value")
        }
        return issues
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case collectionProfileID = "collection_profile_id"
        case operatorName = "operator"
        case contentType = "content_type"
        case gameID = "game_id"
        case tableSetup = "table_setup"
        case cardDeck = "card_deck"
        case cameraView = "camera_view"
        case cameraMotion = "camera_motion"
        case cameraFraming = "camera_framing"
        case lighting
        case background
        case scenarioTags = "scenario_tags"
        case knownLimitations = "known_limitations"
        case sourcePermission = "source_permission"
        case notes
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try recordingProfileRequireExactKeys(container, CodingKeys.self)
        collectionProfileID = try container.decode(String.self, forKey: .collectionProfileID)
        operatorName = try container.decode(String.self, forKey: .operatorName)
        contentType = try container.decode(String.self, forKey: .contentType)
        gameID = try container.decodeIfPresent(String.self, forKey: .gameID)
        tableSetup = try container.decode(String.self, forKey: .tableSetup)
        cardDeck = try container.decode(String.self, forKey: .cardDeck)
        cameraView = try container.decode(String.self, forKey: .cameraView)
        cameraMotion = try container.decode(String.self, forKey: .cameraMotion)
        cameraFraming = try container.decode(String.self, forKey: .cameraFraming)
        lighting = try container.decode([String].self, forKey: .lighting)
        background = try container.decode(String.self, forKey: .background)
        scenarioTags = try container.decode([String].self, forKey: .scenarioTags)
        knownLimitations = try container.decode([String].self, forKey: .knownLimitations)
        sourcePermission = try container.decode(String.self, forKey: .sourcePermission)
        notes = try container.decodeIfPresent(String.self, forKey: .notes)
        guard validationIssues.isEmpty else { throw RecordingProfileError.invalidSnapshot }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(collectionProfileID, forKey: .collectionProfileID)
        try container.encode(operatorName, forKey: .operatorName)
        try container.encode(contentType, forKey: .contentType)
        try container.encode(gameID, forKey: .gameID)
        try container.encode(tableSetup, forKey: .tableSetup)
        try container.encode(cardDeck, forKey: .cardDeck)
        try container.encode(cameraView, forKey: .cameraView)
        try container.encode(cameraMotion, forKey: .cameraMotion)
        try container.encode(cameraFraming, forKey: .cameraFraming)
        try container.encode(lighting, forKey: .lighting)
        try container.encode(background, forKey: .background)
        try container.encode(scenarioTags, forKey: .scenarioTags)
        try container.encode(knownLimitations, forKey: .knownLimitations)
        try container.encode(sourcePermission, forKey: .sourcePermission)
        try container.encode(notes, forKey: .notes)
    }
}

public struct RecordingProfileLoadResult: Equatable, Sendable {
    public let profiles: [RecordingProfile]
    public let obsoleteFileCount: Int

    public init(profiles: [RecordingProfile], obsoleteFileCount: Int = 0) {
        self.profiles = profiles
        self.obsoleteFileCount = obsoleteFileCount
    }

    public var obsoleteFileNotice: String? {
        guard obsoleteFileCount > 0 else { return nil }
        return obsoleteFileCount == 1
            ? "An obsolete collection profile was found. Recreate it as a recording profile."
            : "Obsolete collection profiles were found. Recreate them as recording profiles."
    }
}

public final class RecordingProfileStore: @unchecked Sendable {
    public let directory: URL
    public let obsoleteDirectories: [URL]
    public private(set) var obsoleteFileNotice: String?

    private let fileManager = FileManager.default
    private let lock = NSLock()

    public init(directory: URL, obsoleteDirectories: [URL] = []) {
        self.directory = directory
        self.obsoleteDirectories = obsoleteDirectories.filter { $0 != directory }
    }

    public func save(_ profile: RecordingProfile) throws {
        lock.lock()
        defer { lock.unlock() }
        guard profile.schemaVersion == recordingProfileSchemaVersion,
              recordingProfileIsIdentifier(profile.profileID) else {
            throw RecordingProfileError.invalidProfile
        }
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            throw RecordingProfileError.cannotCreateDirectory(directory, error.localizedDescription)
        }

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let profileURL = url(for: profile.profileID)
        do {
            try encoder.encode(profile).write(to: profileURL, options: .atomic)
        } catch {
            throw RecordingProfileError.cannotWrite(profileURL, error.localizedDescription)
        }
    }

    public func load(profileID: String) throws -> RecordingProfile {
        lock.lock()
        defer { lock.unlock() }
        guard recordingProfileIsIdentifier(profileID) else {
            throw RecordingProfileError.invalidProfile
        }
        let profileURL = url(for: profileID)
        do {
            return try JSONDecoder().decode(
                RecordingProfile.self,
                from: Data(contentsOf: profileURL)
            )
        } catch {
            throw RecordingProfileError.cannotRead(profileURL, error.localizedDescription)
        }
    }

    public func loadAll() throws -> [RecordingProfile] {
        try loadAllResult().profiles
    }

    public func loadAllResult() throws -> RecordingProfileLoadResult {
        lock.lock()
        defer { lock.unlock() }

        let urls: [URL]
        do {
            let directories = [directory] + obsoleteDirectories
            guard directories.contains(where: { fileManager.fileExists(atPath: $0.path) }) else {
                obsoleteFileNotice = nil
                return RecordingProfileLoadResult(profiles: [])
            }
            urls = try directories.flatMap { directory -> [URL] in
                guard fileManager.fileExists(atPath: directory.path) else { return [] }
                return try fileManager.contentsOfDirectory(
                    at: directory,
                    includingPropertiesForKeys: [.isRegularFileKey],
                    options: [.skipsHiddenFiles]
                )
                .filter { $0.pathExtension == "json" }
            }
            .sorted { $0.path < $1.path }
        } catch {
            throw RecordingProfileError.cannotRead(directory, error.localizedDescription)
        }

        var profiles: [RecordingProfile] = []
        var obsoleteFileCount = 0
        for profileURL in urls {
            guard let data = try? Data(contentsOf: profileURL) else { continue }
            if Self.isObsoleteCollectionProfile(data) {
                obsoleteFileCount += 1
                continue
            }
            guard let profile = try? JSONDecoder().decode(RecordingProfile.self, from: data) else {
                continue
            }
            profiles.append(profile)
        }

        let result = RecordingProfileLoadResult(
            profiles: profiles,
            obsoleteFileCount: obsoleteFileCount
        )
        obsoleteFileNotice = result.obsoleteFileNotice
        return result
    }

    private func url(for profileID: String) -> URL {
        directory.appendingPathComponent("\(profileID).json", isDirectory: false)
    }

    private static func isObsoleteCollectionProfile(_ data: Data) -> Bool {
        guard let object = try? JSONSerialization.jsonObject(with: data),
              let dictionary = object as? [String: Any] else {
            return false
        }
        return dictionary["schema_version"] as? String == "collection-profile/v1"
    }
}

public enum OperatorSettingsStoreError: LocalizedError, Equatable, Sendable {
    case cannotCreateDirectory(URL, String)
    case cannotRead(URL, String)
    case cannotWrite(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .cannotCreateDirectory(url, message):
            return "The settings directory could not be created at \(url.path): \(message)"
        case let .cannotRead(url, message):
            return "The operator settings could not be read at \(url.path): \(message)"
        case let .cannotWrite(url, message):
            return "The operator settings could not be written at \(url.path): \(message)"
        }
    }
}

public final class OperatorSettingsStore: @unchecked Sendable {
    public let fileURL: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()

    public init(directory: URL, fileName: String = "operator-settings.json") {
        fileURL = directory.appendingPathComponent(fileName, isDirectory: false)
    }

    public func load() throws -> OperatorSettings? {
        lock.lock()
        defer { lock.unlock() }
        guard fileManager.fileExists(atPath: fileURL.path) else { return nil }
        do {
            return try JSONDecoder().decode(OperatorSettings.self, from: Data(contentsOf: fileURL))
        } catch {
            throw OperatorSettingsStoreError.cannotRead(fileURL, error.localizedDescription)
        }
    }

    public func save(_ settings: OperatorSettings) throws {
        lock.lock()
        defer { lock.unlock() }
        do {
            try fileManager.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        } catch {
            throw OperatorSettingsStoreError.cannotCreateDirectory(
                fileURL.deletingLastPathComponent(),
                error.localizedDescription
            )
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        do {
            try encoder.encode(settings).write(to: fileURL, options: .atomic)
        } catch {
            throw OperatorSettingsStoreError.cannotWrite(fileURL, error.localizedDescription)
        }
    }
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

/// The immutable inputs captured when one recording starts.
public struct RecordingStartSnapshot: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let recordingID: String
    public let startedAtUTC: String
    public let profile: RecordingProfile
    public let operatorSettings: OperatorSettings
    public let appRunContext: AppRunContext
    public let fixedMetadata: FixedRecordingMetadata
    public let collectionMetadata: TrainingRecordingCollectionMetadata
    public let taskEnrollments: [RepositoryTaskEnrollment]

    public init(
        recordingID: String,
        startedAtUTC: String,
        profile: RecordingProfile,
        operatorSettings: OperatorSettings,
        appRunContext: AppRunContext,
        fixedMetadata: FixedRecordingMetadata = .current
    ) throws {
        guard recordingProfileIsIdentifier(recordingID), recordingProfileIsUTCTimestamp(startedAtUTC) else {
            throw RecordingProfileError.invalidRecordingIdentity
        }
        guard profile.isComplete else {
            throw RecordingProfileError.incomplete(profile.validationIssues)
        }
        guard operatorSettings.isComplete else {
            throw RecordingProfileError.operatorNameMissing
        }

        let adapter = RecordingMetadataAdapter(fixedMetadata: fixedMetadata)
        collectionMetadata = try adapter.makeCollectionMetadata(
            profile: profile,
            operatorSettings: operatorSettings,
            appRunContext: appRunContext
        )
        taskEnrollments = try profile.makeTaskEnrollments(
            recordingID: recordingID,
            createdAtUTC: startedAtUTC,
            operatorSettings: operatorSettings
        )
        schemaVersion = recordingStartSnapshotSchemaVersion
        self.recordingID = recordingID
        self.startedAtUTC = startedAtUTC
        self.profile = profile
        self.operatorSettings = operatorSettings
        self.appRunContext = appRunContext
        self.fixedMetadata = fixedMetadata
    }

    public func makeRoundSetup() throws -> RoundRecordingSetup {
        try DefaultRoundAnalysisSetup().makeRoundSetup(
            recordingID: recordingID,
            purpose: profile.purpose,
            appRunContext: appRunContext
        )
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case startedAtUTC = "started_at_utc"
        case profile
        case operatorSettings = "operator_settings"
        case appRunContext = "app_run_context"
        case fixedMetadata = "fixed_metadata"
        case collectionMetadata = "collection_metadata"
        case taskEnrollments = "task_enrollments"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try recordingProfileRequireExactKeys(container, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        recordingID = try container.decode(String.self, forKey: .recordingID)
        startedAtUTC = try container.decode(String.self, forKey: .startedAtUTC)
        profile = try container.decode(RecordingProfile.self, forKey: .profile)
        operatorSettings = try container.decode(OperatorSettings.self, forKey: .operatorSettings)
        appRunContext = try container.decode(AppRunContext.self, forKey: .appRunContext)
        fixedMetadata = try container.decode(FixedRecordingMetadata.self, forKey: .fixedMetadata)
        collectionMetadata = try container.decode(
            TrainingRecordingCollectionMetadata.self,
            forKey: .collectionMetadata
        )
        taskEnrollments = try container.decode([RepositoryTaskEnrollment].self, forKey: .taskEnrollments)

        let expectedMetadata = try? RecordingMetadataAdapter(
            fixedMetadata: fixedMetadata
        ).makeCollectionMetadata(
            profile: profile,
            operatorSettings: operatorSettings,
            appRunContext: appRunContext
        )
        let expectedTaskEnrollments = try? profile.makeTaskEnrollments(
            recordingID: recordingID,
            createdAtUTC: startedAtUTC,
            operatorSettings: operatorSettings
        )

        guard schemaVersion == recordingStartSnapshotSchemaVersion,
              recordingProfileIsIdentifier(recordingID),
              recordingProfileIsUTCTimestamp(startedAtUTC),
              profile.isComplete,
              operatorSettings.isComplete,
              taskEnrollments.count == RepositoryDataTask.allCases.count,
              Set(taskEnrollments.map(\.task)) == Set(RepositoryDataTask.allCases),
              taskEnrollments.allSatisfy({ $0.operator == operatorSettings.operatorName }),
              taskEnrollments.allSatisfy({ $0.taskEnrollmentID.hasPrefix("\(recordingID)-") }),
              expectedMetadata == collectionMetadata,
              expectedTaskEnrollments == taskEnrollments else {
            throw RecordingProfileError.invalidSnapshot
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(recordingID, forKey: .recordingID)
        try container.encode(startedAtUTC, forKey: .startedAtUTC)
        try container.encode(profile, forKey: .profile)
        try container.encode(operatorSettings, forKey: .operatorSettings)
        try container.encode(appRunContext, forKey: .appRunContext)
        try container.encode(fixedMetadata, forKey: .fixedMetadata)
        try container.encode(collectionMetadata, forKey: .collectionMetadata)
        try container.encode(taskEnrollments, forKey: .taskEnrollments)
    }
}

public let recordingStartSnapshotSchemaVersion = "recording-start-snapshot/v1"

public enum RecordingStartSnapshotStoreError: LocalizedError, Equatable, Sendable {
    case cannotCreateDirectory(URL, String)
    case cannotRead(URL, String)
    case cannotWrite(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .cannotCreateDirectory(url, message):
            return "The recording snapshot directory could not be created at \(url.path): \(message)"
        case let .cannotRead(url, message):
            return "The recording snapshot could not be read at \(url.path): \(message)"
        case let .cannotWrite(url, message):
            return "The recording snapshot could not be written at \(url.path): \(message)"
        }
    }
}

public final class RecordingStartSnapshotStore: @unchecked Sendable {
    public let directory: URL
    public let snapshotURL: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()

    public init(directory: URL, fileName: String = "recording-start-snapshot.json") {
        self.directory = directory
        snapshotURL = directory.appendingPathComponent(fileName, isDirectory: false)
    }

    public func load() throws -> RecordingStartSnapshot? {
        lock.lock()
        defer { lock.unlock() }
        guard fileManager.fileExists(atPath: snapshotURL.path) else { return nil }
        do {
            return try JSONDecoder().decode(
                RecordingStartSnapshot.self,
                from: Data(contentsOf: snapshotURL)
            )
        } catch {
            throw RecordingStartSnapshotStoreError.cannotRead(snapshotURL, error.localizedDescription)
        }
    }

    public func save(_ snapshot: RecordingStartSnapshot) throws {
        lock.lock()
        defer { lock.unlock() }
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            throw RecordingStartSnapshotStoreError.cannotCreateDirectory(
                directory,
                error.localizedDescription
            )
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        do {
            try encoder.encode(snapshot).write(to: snapshotURL, options: .atomic)
        } catch {
            throw RecordingStartSnapshotStoreError.cannotWrite(snapshotURL, error.localizedDescription)
        }
    }

    public func remove() throws {
        lock.lock()
        defer { lock.unlock() }
        guard fileManager.fileExists(atPath: snapshotURL.path) else { return }
        do {
            try fileManager.removeItem(at: snapshotURL)
        } catch {
            throw RecordingStartSnapshotStoreError.cannotWrite(snapshotURL, error.localizedDescription)
        }
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
            recordingID: recordingID,
            defaults: RoundRecordingSetupDefaults(
                gameID: purpose.mapping(for: appRunContext).analysisGameID
            )
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
    case invalidSnapshot
    case invalidRecordingIdentity
    case operatorNameMissing
    case cannotCreateDirectory(URL, String)
    case cannotRead(URL, String)
    case cannotWrite(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .incomplete(issues):
            return issues.map { "\($0.field.rawValue): \($0.message)" }.joined(separator: " ")
        case .invalidProfile:
            return "The recording profile is invalid."
        case .invalidSnapshot:
            return "The recording start snapshot is invalid."
        case .invalidRecordingIdentity:
            return "The recording identity or enrollment timestamp is invalid."
        case .operatorNameMissing:
            return "Enter the operator name."
        case let .cannotCreateDirectory(url, message):
            return "The recording-profile directory could not be created at \(url.path): \(message)"
        case let .cannotRead(url, message):
            return "The recording profile could not be read at \(url.path): \(message)"
        case let .cannotWrite(url, message):
            return "The recording profile could not be written at \(url.path): \(message)"
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
