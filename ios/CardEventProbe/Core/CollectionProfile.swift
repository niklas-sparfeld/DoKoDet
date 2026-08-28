import Foundation

public let collectionProfileSchemaVersion = "collection-profile/v1"

public enum CollectionActivity: String, Codable, CaseIterable, Sendable {
    case realGame = "real_game"
    case stagedActivity = "staged_activity"

    public var title: String {
        switch self {
        case .realGame:
            return "Real game"
        case .stagedActivity:
            return "Staged activity"
        }
    }
}

public enum CollectionProfileValidationField: String, Codable, CaseIterable, Sendable {
    case profileName = "profile_name"
    case operatorName = "operator"
    case sessionID = "session_id"
    case activity
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
    case taskEnrollments = "task_enrollments"
}

public struct CollectionProfileValidationIssue: Equatable, Sendable {
    public let field: CollectionProfileValidationField
    public let message: String

    public init(field: CollectionProfileValidationField, message: String) {
        self.field = field
        self.message = message
    }
}

public struct CollectionTaskSetting: Codable, Equatable, Sendable {
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

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try collectionProfileRequireExactKeys(container, CodingKeys.self)
        task = try container.decode(RepositoryDataTask.self, forKey: .task)
        disposition = try container.decode(RepositoryTaskDisposition.self, forKey: .disposition)
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case task
        case disposition
        case reason
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(task, forKey: .task)
        try container.encode(disposition, forKey: .disposition)
        try container.encode(reason, forKey: .reason)
    }
}

public struct CollectionProfile: Codable, Equatable, Identifiable, Sendable {
    public let schemaVersion: String
    public let profileID: String
    public var name: String
    public var operatorName: String
    public var sessionID: String
    public var activity: CollectionActivity
    public var gameID: String?
    public var tableSetup: String
    public var cardDeck: String
    public var cameraView: String
    public var cameraMotion: String
    public var cameraFraming: String
    public var lighting: [String]
    public var background: String
    public var scenarioTags: [String]
    public var knownLimitations: [String]
    public var sourcePermission: String
    public var taskSettings: [CollectionTaskSetting]
    public var notes: String?

    public var id: String { profileID }

    public init(
        profileID: String,
        name: String,
        operatorName: String,
        sessionID: String,
        activity: CollectionActivity,
        gameID: String? = nil,
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
        taskSettings: [CollectionTaskSetting] = CollectionProfile.defaultTaskSettings,
        notes: String? = nil,
        schemaVersion: String = collectionProfileSchemaVersion
    ) {
        self.schemaVersion = schemaVersion
        self.profileID = profileID
        self.name = name
        self.operatorName = operatorName
        self.sessionID = sessionID
        self.activity = activity
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
        self.taskSettings = taskSettings
        self.notes = notes
    }

    public static func newDraft(
        profileID: String = "profile-\(UUID().uuidString.lowercased())",
        sessionID: String = "session-\(UUID().uuidString.lowercased())"
    ) -> CollectionProfile {
        CollectionProfile(
            profileID: profileID,
            name: "New collection profile",
            operatorName: "",
            sessionID: sessionID,
            activity: .stagedActivity,
            tableSetup: "",
            cardDeck: "",
            cameraView: "",
            cameraMotion: "",
            cameraFraming: "",
            lighting: [],
            background: "",
            scenarioTags: [],
            knownLimitations: [],
            sourcePermission: ""
        )
    }

    public var validationIssues: [CollectionProfileValidationIssue] {
        var issues: [CollectionProfileValidationIssue] = []
        requireText(name, field: .profileName, message: "Enter a profile name.", into: &issues)
        requireText(operatorName, field: .operatorName, message: "Enter the operator name.", into: &issues)
        if !collectionProfileIsSafeIdentifier(sessionID) {
            issues.append(
                CollectionProfileValidationIssue(
                    field: .sessionID,
                    message: "Enter a valid session identifier."
                )
            )
        }

        if activity == .realGame {
            requireText(gameID ?? "", field: .gameID, message: "Enter the game ID for a real game.", into: &issues)
        } else if let gameID, !gameID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            issues.append(
                CollectionProfileValidationIssue(
                    field: .gameID,
                    message: "Staged activity must not have a game ID."
                )
            )
        }

        requireText(tableSetup, field: .tableSetup, message: "Enter the table setup.", into: &issues)
        requireText(cardDeck, field: .cardDeck, message: "Enter the deck design.", into: &issues)
        requireText(cameraView, field: .cameraView, message: "Choose the camera view.", into: &issues)
        requireText(cameraMotion, field: .cameraMotion, message: "Choose the camera movement.", into: &issues)
        requireText(cameraFraming, field: .cameraFraming, message: "Choose the camera framing.", into: &issues)
        requireTags(lighting, field: .lighting, message: "Add at least one lighting condition.", into: &issues)
        requireText(background, field: .background, message: "Describe the background.", into: &issues)
        requireTags(scenarioTags, field: .scenarioTags, message: "Add at least one scenario tag.", into: &issues)
        requireText(
            sourcePermission,
            field: .sourcePermission,
            message: "Choose an explicit source permission.",
            into: &issues
        )
        if !["training_only", "training_and_evaluation", "project_use", "unrestricted"].contains(sourcePermission) {
            issues.append(
                CollectionProfileValidationIssue(
                    field: .sourcePermission,
                    message: "Choose a supported source permission."
                )
            )
        }

        guard taskSettings.count == RepositoryDataTask.allCases.count,
              Set(taskSettings.map(\.task)) == Set(RepositoryDataTask.allCases) else {
            issues.append(
                CollectionProfileValidationIssue(
                    field: .taskEnrollments,
                    message: "Set one disposition for each data task."
                )
            )
            return issues
        }
        for setting in taskSettings {
            if setting.disposition == .excluded {
                requireText(
                    setting.reason ?? "",
                    field: .taskEnrollments,
                    message: "Give an exclusion reason for \(setting.task.rawValue).",
                    into: &issues
                )
            } else if setting.reason != nil {
                issues.append(
                    CollectionProfileValidationIssue(
                        field: .taskEnrollments,
                        message: "Selected and deferred tasks must not have a reason."
                    )
                )
            }
        }
        return issues
    }

    public var isComplete: Bool { validationIssues.isEmpty }

    public func taskSetting(for task: RepositoryDataTask) -> CollectionTaskSetting? {
        taskSettings.first { $0.task == task }
    }

    public func recordingMetadata(
        scenarioTags: [String]? = nil,
        notes: String? = nil
    ) throws -> TrainingRecordingCollectionMetadata {
        var copy = self
        if let scenarioTags { copy.scenarioTags = scenarioTags }
        if let notes { copy.notes = notes }
        guard copy.isComplete else {
            throw CollectionProfileError.incomplete(copy.validationIssues)
        }
        return TrainingRecordingCollectionMetadata(profile: copy)
    }

    public func makeTaskEnrollments(
        recordingID: String,
        createdAtUTC: String,
        overrides: [CollectionTaskDispositionOverride] = []
    ) throws -> [RepositoryTaskEnrollment] {
        guard isComplete else {
            throw CollectionProfileError.incomplete(validationIssues)
        }
        guard collectionProfileIsSafeIdentifier(recordingID), collectionProfileIsUTCTimestamp(createdAtUTC) else {
            throw CollectionProfileError.invalidRecordingIdentity
        }
        var overrideByTask: [RepositoryDataTask: CollectionTaskDispositionOverride] = [:]
        for override in overrides {
            guard overrideByTask[override.task] == nil else {
                throw CollectionProfileError.duplicateTaskOverride(override.task)
            }
            overrideByTask[override.task] = override
        }

        return try RepositoryDataTask.allCases.map { task in
            let setting = taskSetting(for: task) ?? CollectionTaskSetting(task: task)
            let selected = overrideByTask[task].map {
                CollectionTaskSetting(task: task, disposition: $0.disposition, reason: $0.reason)
            } ?? setting
            return try RepositoryTaskEnrollment(
                taskEnrollmentID: "\(recordingID)-\(task.rawValue)",
                task: task,
                disposition: selected.disposition,
                operatorName: operatorName,
                createdAtUTC: createdAtUTC,
                reason: selected.reason
            )
        }
    }

    public static let defaultTaskSettings = RepositoryDataTask.allCases.map {
        CollectionTaskSetting(task: $0)
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case profileID = "profile_id"
        case name
        case operatorName = "operator"
        case sessionID = "session_id"
        case activity
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
        case taskSettings = "task_settings"
        case notes
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(profileID, forKey: .profileID)
        try container.encode(name, forKey: .name)
        try container.encode(operatorName, forKey: .operatorName)
        try container.encode(sessionID, forKey: .sessionID)
        try container.encode(activity, forKey: .activity)
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
        try container.encode(taskSettings, forKey: .taskSettings)
        try container.encode(notes, forKey: .notes)
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try collectionProfileRequireExactKeys(container, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        profileID = try container.decode(String.self, forKey: .profileID)
        name = try container.decode(String.self, forKey: .name)
        operatorName = try container.decode(String.self, forKey: .operatorName)
        sessionID = try container.decode(String.self, forKey: .sessionID)
        activity = try container.decode(CollectionActivity.self, forKey: .activity)
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
        taskSettings = try container.decode([CollectionTaskSetting].self, forKey: .taskSettings)
        notes = try container.decodeIfPresent(String.self, forKey: .notes)
        guard schemaVersion == collectionProfileSchemaVersion,
              collectionProfileIsSafeIdentifier(profileID),
              taskSettings.count == RepositoryDataTask.allCases.count,
              Set(taskSettings.map(\.task)) == Set(RepositoryDataTask.allCases) else {
            throw CollectionProfileError.invalidProfile
        }
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

    public init(profile: CollectionProfile) {
        collectionProfileID = profile.profileID
        operatorName = profile.operatorName
        contentType = profile.activity == .realGame ? "real_game" : "staged_scenario"
        gameID = profile.gameID
        tableSetup = profile.tableSetup
        cardDeck = profile.cardDeck
        cameraView = profile.cameraView
        cameraMotion = profile.cameraMotion
        cameraFraming = profile.cameraFraming
        lighting = profile.lighting
        background = profile.background
        scenarioTags = profile.scenarioTags
        knownLimitations = profile.knownLimitations
        sourcePermission = profile.sourcePermission
        notes = profile.notes
    }

    public var validationIssues: [CollectionProfileValidationIssue] {
        var profile = CollectionProfile.newDraft(profileID: collectionProfileID, sessionID: "session-placeholder")
        profile.operatorName = operatorName
        if contentType == "real_game" {
            profile.activity = .realGame
        } else if contentType == "staged_scenario" {
            profile.activity = .stagedActivity
        } else {
            return [
                CollectionProfileValidationIssue(
                    field: .activity,
                    message: "Choose a supported content type."
                )
            ]
        }
        profile.gameID = gameID
        profile.tableSetup = tableSetup
        profile.cardDeck = cardDeck
        profile.cameraView = cameraView
        profile.cameraMotion = cameraMotion
        profile.cameraFraming = cameraFraming
        profile.lighting = lighting
        profile.background = background
        profile.scenarioTags = scenarioTags
        profile.knownLimitations = knownLimitations
        profile.sourcePermission = sourcePermission
        profile.taskSettings = CollectionProfile.defaultTaskSettings
        return profile.validationIssues.filter { issue in
            issue.field != .profileName && issue.field != .sessionID
        }
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

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try collectionProfileRequireExactKeys(container, CodingKeys.self)
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
        guard collectionProfileIsSafeIdentifier(collectionProfileID) else {
            throw CollectionProfileError.invalidProfile
        }
    }
}

public struct CollectionTaskDispositionOverride: Equatable, Sendable {
    public let task: RepositoryDataTask
    public let disposition: RepositoryTaskDisposition
    public let reason: String?

    public init(
        task: RepositoryDataTask,
        disposition: RepositoryTaskDisposition,
        reason: String? = nil
    ) {
        self.task = task
        self.disposition = disposition
        self.reason = reason
    }
}

public enum CollectionProfileError: LocalizedError, Equatable, Sendable {
    case incomplete([CollectionProfileValidationIssue])
    case invalidProfile
    case invalidRecordingIdentity
    case duplicateTaskOverride(RepositoryDataTask)
    case cannotCreateDirectory(URL, String)
    case cannotRead(URL, String)
    case cannotWrite(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .incomplete(issues):
            return issues.map { "\($0.field.rawValue): \($0.message)" }.joined(separator: " ")
        case .invalidProfile:
            return "The collection profile is invalid."
        case .invalidRecordingIdentity:
            return "The recording identity or enrollment timestamp is invalid."
        case let .duplicateTaskOverride(task):
            return "The recording has more than one override for \(task.rawValue)."
        case let .cannotCreateDirectory(url, message):
            return "The collection-profile directory could not be created at \(url.path): \(message)"
        case let .cannotRead(url, message):
            return "The collection profile could not be read at \(url.path): \(message)"
        case let .cannotWrite(url, message):
            return "The collection profile could not be written at \(url.path): \(message)"
        }
    }
}

public final class CollectionProfileStore: @unchecked Sendable {
    public let directory: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()

    public init(directory: URL) {
        self.directory = directory
    }

    public func save(_ profile: CollectionProfile) throws {
        lock.lock()
        defer { lock.unlock() }
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            throw CollectionProfileError.cannotCreateDirectory(directory, error.localizedDescription)
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        do {
            let data = try encoder.encode(profile)
            try data.write(to: url(for: profile.profileID), options: .atomic)
        } catch {
            throw CollectionProfileError.cannotWrite(url(for: profile.profileID), error.localizedDescription)
        }
    }

    public func load(profileID: String) throws -> CollectionProfile {
        lock.lock()
        defer { lock.unlock() }
        let profileURL = url(for: profileID)
        do {
            return try JSONDecoder().decode(CollectionProfile.self, from: Data(contentsOf: profileURL))
        } catch {
            throw CollectionProfileError.cannotRead(profileURL, error.localizedDescription)
        }
    }

    public func loadAll() throws -> [CollectionProfile] {
        lock.lock()
        defer { lock.unlock() }
        let urls: [URL]
        do {
            guard fileManager.fileExists(atPath: directory.path) else { return [] }
            urls = try fileManager.contentsOfDirectory(
                at: directory,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles]
            )
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        } catch {
            throw CollectionProfileError.cannotRead(directory, error.localizedDescription)
        }
        do {
            return try urls.map { try JSONDecoder().decode(CollectionProfile.self, from: Data(contentsOf: $0)) }
        } catch {
            throw CollectionProfileError.cannotRead(directory, error.localizedDescription)
        }
    }

    private func url(for profileID: String) -> URL {
        directory.appendingPathComponent("\(profileID).json", isDirectory: false)
    }
}

private func requireText(
    _ value: String,
    field: CollectionProfileValidationField,
    message: String,
    into issues: inout [CollectionProfileValidationIssue]
) {
    if value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        issues.append(CollectionProfileValidationIssue(field: field, message: message))
    }
}

private func requireTags(
    _ values: [String],
    field: CollectionProfileValidationField,
    message: String,
    into issues: inout [CollectionProfileValidationIssue]
) {
    if values.isEmpty || values.contains(where: { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
        issues.append(CollectionProfileValidationIssue(field: field, message: message))
    }
    if values.count != Set(values).count {
        issues.append(
            CollectionProfileValidationIssue(field: field, message: "Values must not contain duplicates.")
        )
    }
}

private func collectionProfileIsSafeIdentifier(_ value: String) -> Bool {
    guard let first = value.unicodeScalars.first,
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

private func collectionProfileIsUTCTimestamp(_ value: String) -> Bool {
    guard value.hasSuffix("Z") else { return false }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: value) != nil || {
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value) != nil
    }()
}

private struct CollectionProfileAnyCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil

    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}

private func collectionProfileRequireExactKeys<Key: CodingKey & CaseIterable>(
    _ container: KeyedDecodingContainer<Key>,
    _ keyType: Key.Type
) throws {
    let actual = Set(container.allKeys.map(\.stringValue))
    let expected = Set(keyType.allCases.map(\.stringValue))
    guard actual == expected else {
        throw CollectionProfileError.invalidProfile
    }
}
