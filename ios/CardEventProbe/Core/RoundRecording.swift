import Foundation

public let roundRecordingStateSchemaVersion = "round-recording/v1"

public enum RoundRecordingSetupError: LocalizedError, Equatable, Sendable {
    case invalidGameID
    case invalidRecordingID
    case invalidRoundID
    case invalidDealer
    case invalidFirstTrickLeader

    public var errorDescription: String? {
        switch self {
        case .invalidGameID:
            return "The game ID is invalid."
        case .invalidRecordingID:
            return "The recording ID is invalid."
        case .invalidRoundID:
            return "The round ID is invalid."
        case .invalidDealer:
            return "The dealer must be one of the fixed seat IDs."
        case .invalidFirstTrickLeader:
            return "The first trick leader must be one of the fixed seat IDs."
        }
    }
}

public struct RoundRecordingRuleset: Codable, Equatable, Sendable {
    public let name: String
    public let version: String

    public init(name: String = "doko-normal", version: String = "v1") throws {
        guard name == "doko-normal", version == "v1" else {
            throw RoundRecordingSetupError.invalidRoundID
        }
        self.name = name
        self.version = version
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try roundRecordingRequireExactKeys(container, CodingKeys.self)
        try self.init(
            name: try container.decode(String.self, forKey: .name),
            version: try container.decode(String.self, forKey: .version)
        )
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case name
        case version
    }
}

/// The fixed round setup captured at the start of one round recording.
public struct RoundRecordingSetup: Codable, Equatable, Sendable {
    public static let fixedSeatIDs = ["seat-1", "seat-2", "seat-3", "seat-4"]
    public static let deckVariant = "doko-40-v1"

    public let gameID: String
    public let roundID: String
    public let ruleset: RoundRecordingRuleset
    public let deckVariant: String
    public let activePlayers: [String]
    public let dealer: String
    public let firstTrickLeader: String

    public init(
        gameID: String,
        recordingID: String,
        dealer: String,
        firstTrickLeader: String
    ) throws {
        guard roundRecordingIsIdentifier(gameID) else {
            throw RoundRecordingSetupError.invalidGameID
        }
        guard roundRecordingIsIdentifier(recordingID) else {
            throw RoundRecordingSetupError.invalidRecordingID
        }
        let roundID = "round-\(recordingID)"
        guard roundRecordingIsIdentifier(roundID) else {
            throw RoundRecordingSetupError.invalidRoundID
        }
        guard Self.fixedSeatIDs.contains(dealer) else {
            throw RoundRecordingSetupError.invalidDealer
        }
        guard Self.fixedSeatIDs.contains(firstTrickLeader) else {
            throw RoundRecordingSetupError.invalidFirstTrickLeader
        }
        self.gameID = gameID
        self.roundID = roundID
        self.ruleset = try RoundRecordingRuleset()
        deckVariant = Self.deckVariant
        activePlayers = Self.fixedSeatIDs
        self.dealer = dealer
        self.firstTrickLeader = firstTrickLeader
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try roundRecordingRequireExactKeys(container, CodingKeys.self)
        gameID = try container.decode(String.self, forKey: .gameID)
        roundID = try container.decode(String.self, forKey: .roundID)
        ruleset = try container.decode(RoundRecordingRuleset.self, forKey: .ruleset)
        deckVariant = try container.decode(String.self, forKey: .deckVariant)
        activePlayers = try container.decode([String].self, forKey: .activePlayers)
        dealer = try container.decode(String.self, forKey: .dealer)
        firstTrickLeader = try container.decode(String.self, forKey: .firstTrickLeader)

        guard roundRecordingIsIdentifier(gameID),
              roundRecordingIsIdentifier(roundID),
              ruleset.name == "doko-normal",
              ruleset.version == "v1",
              deckVariant == Self.deckVariant,
              activePlayers == Self.fixedSeatIDs,
              Self.fixedSeatIDs.contains(dealer),
              Self.fixedSeatIDs.contains(firstTrickLeader) else {
            throw RoundRecordingSetupError.invalidRoundID
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case gameID = "game_id"
        case roundID = "round_id"
        case ruleset
        case deckVariant = "deck_variant"
        case activePlayers = "active_players"
        case dealer
        case firstTrickLeader = "first_trick_leader"
    }
}

/// Durable ownership and acknowledgement state for one round recording.
public struct RoundRecordingState: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let recordingID: String
    public let sessionID: UUID
    public let roundSetup: RoundRecordingSetup
    public let startedAtUTC: Date
    public let stoppedAtUTC: Date?
    public let evidencePackageIDs: [UUID]
    public let acknowledgedEvidencePackageIDs: [UUID]
    public let evidenceMembershipClosed: Bool
    public let recordingBundleFinalized: Bool
    public let recordingBundleAcknowledged: Bool

    public init(
        recordingID: String,
        sessionID: UUID,
        roundSetup: RoundRecordingSetup,
        startedAtUTC: Date = Date()
    ) throws {
        guard roundRecordingIsIdentifier(recordingID),
              startedAtUTC.timeIntervalSinceReferenceDate.isFinite,
              roundSetup.roundID == "round-\(recordingID)" else {
            throw RoundRecordingSetupError.invalidRecordingID
        }
        schemaVersion = roundRecordingStateSchemaVersion
        self.recordingID = recordingID
        self.sessionID = sessionID
        self.roundSetup = roundSetup
        self.startedAtUTC = startedAtUTC
        stoppedAtUTC = nil
        evidencePackageIDs = []
        acknowledgedEvidencePackageIDs = []
        evidenceMembershipClosed = false
        recordingBundleFinalized = false
        recordingBundleAcknowledged = false
    }

    public var hasEvidencePackages: Bool {
        !evidencePackageIDs.isEmpty
    }

    public var allEvidencePackagesAcknowledged: Bool {
        hasEvidencePackages
            && Set(acknowledgedEvidencePackageIDs) == Set(evidencePackageIDs)
    }

    public func addingEvidencePackage(_ packageID: UUID) throws -> Self {
        guard !evidencePackageIDs.contains(packageID) else { return self }
        return copy(
            stoppedAtUTC: stoppedAtUTC,
            evidencePackageIDs: evidencePackageIDs + [packageID]
        )
    }

    public func acknowledgingEvidencePackage(_ packageID: UUID) throws -> Self {
        guard evidencePackageIDs.contains(packageID) else {
            throw RoundRecordingStateError.packageNotTracked(packageID)
        }
        guard !acknowledgedEvidencePackageIDs.contains(packageID) else { return self }
        return copy(
            stoppedAtUTC: stoppedAtUTC,
            acknowledgedEvidencePackageIDs: acknowledgedEvidencePackageIDs + [packageID]
        )
    }

    public func closingEvidenceMembership(at date: Date = Date()) throws -> Self {
        guard date.timeIntervalSinceReferenceDate.isFinite else {
            throw RoundRecordingStateError.invalidTimestamp
        }
        return copy(stoppedAtUTC: stoppedAtUTC ?? date, evidenceMembershipClosed: true)
    }

    public func markingRecordingBundleFinalized() -> Self {
        copy(stoppedAtUTC: stoppedAtUTC, recordingBundleFinalized: true)
    }

    public func markingRecordingBundleAcknowledged() -> Self {
        copy(stoppedAtUTC: stoppedAtUTC, recordingBundleAcknowledged: true)
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try roundRecordingRequireExactKeys(container, CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        recordingID = try container.decode(String.self, forKey: .recordingID)
        sessionID = try container.decode(UUID.self, forKey: .sessionID)
        roundSetup = try container.decode(RoundRecordingSetup.self, forKey: .roundSetup)
        startedAtUTC = try Self.decodeDate(container, forKey: .startedAtUTC)
        stoppedAtUTC = try Self.decodeOptionalDate(container, forKey: .stoppedAtUTC)
        evidencePackageIDs = try container.decode([UUID].self, forKey: .evidencePackageIDs)
        acknowledgedEvidencePackageIDs = try container.decode(
            [UUID].self,
            forKey: .acknowledgedEvidencePackageIDs
        )
        evidenceMembershipClosed = try container.decode(Bool.self, forKey: .evidenceMembershipClosed)
        recordingBundleFinalized = try container.decode(Bool.self, forKey: .recordingBundleFinalized)
        recordingBundleAcknowledged = try container.decode(
            Bool.self,
            forKey: .recordingBundleAcknowledged
        )

        guard schemaVersion == roundRecordingStateSchemaVersion,
              roundRecordingIsIdentifier(recordingID),
              roundSetup.roundID == "round-\(recordingID)",
              startedAtUTC.timeIntervalSinceReferenceDate.isFinite,
              stoppedAtUTC.map({ $0.timeIntervalSinceReferenceDate.isFinite }) ?? true,
              Set(evidencePackageIDs).count == evidencePackageIDs.count,
              Set(acknowledgedEvidencePackageIDs).count == acknowledgedEvidencePackageIDs.count,
              Set(acknowledgedEvidencePackageIDs).isSubset(of: Set(evidencePackageIDs)) else {
            throw RoundRecordingStateError.invalidStoredState
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(recordingID, forKey: .recordingID)
        try container.encode(sessionID.uuidString.lowercased(), forKey: .sessionID)
        try container.encode(roundSetup, forKey: .roundSetup)
        try container.encode(Self.encodeDate(startedAtUTC), forKey: .startedAtUTC)
        try container.encode(
            stoppedAtUTC.map { Self.encodeDate($0) },
            forKey: .stoppedAtUTC
        )
        try container.encode(evidencePackageIDs, forKey: .evidencePackageIDs)
        try container.encode(acknowledgedEvidencePackageIDs, forKey: .acknowledgedEvidencePackageIDs)
        try container.encode(evidenceMembershipClosed, forKey: .evidenceMembershipClosed)
        try container.encode(recordingBundleFinalized, forKey: .recordingBundleFinalized)
        try container.encode(recordingBundleAcknowledged, forKey: .recordingBundleAcknowledged)
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case sessionID = "session_id"
        case roundSetup = "round_setup"
        case startedAtUTC = "started_at_utc"
        case stoppedAtUTC = "stopped_at_utc"
        case evidencePackageIDs = "evidence_package_ids"
        case acknowledgedEvidencePackageIDs = "acknowledged_evidence_package_ids"
        case evidenceMembershipClosed = "evidence_membership_closed"
        case recordingBundleFinalized = "recording_bundle_finalized"
        case recordingBundleAcknowledged = "recording_bundle_acknowledged"
    }

    private func copy(
        stoppedAtUTC: Date? = nil,
        evidencePackageIDs: [UUID]? = nil,
        acknowledgedEvidencePackageIDs: [UUID]? = nil,
        evidenceMembershipClosed: Bool? = nil,
        recordingBundleFinalized: Bool? = nil,
        recordingBundleAcknowledged: Bool? = nil
    ) -> Self {
        return Self(
            schemaVersion: schemaVersion,
            recordingID: recordingID,
            sessionID: sessionID,
            roundSetup: roundSetup,
            startedAtUTC: startedAtUTC,
            stoppedAtUTC: stoppedAtUTC,
            evidencePackageIDs: evidencePackageIDs ?? self.evidencePackageIDs,
            acknowledgedEvidencePackageIDs: acknowledgedEvidencePackageIDs
                ?? self.acknowledgedEvidencePackageIDs,
            evidenceMembershipClosed: evidenceMembershipClosed ?? self.evidenceMembershipClosed,
            recordingBundleFinalized: recordingBundleFinalized ?? self.recordingBundleFinalized,
            recordingBundleAcknowledged: recordingBundleAcknowledged
                ?? self.recordingBundleAcknowledged
        )
    }

    private init(
        schemaVersion: String,
        recordingID: String,
        sessionID: UUID,
        roundSetup: RoundRecordingSetup,
        startedAtUTC: Date,
        stoppedAtUTC: Date?,
        evidencePackageIDs: [UUID],
        acknowledgedEvidencePackageIDs: [UUID],
        evidenceMembershipClosed: Bool,
        recordingBundleFinalized: Bool,
        recordingBundleAcknowledged: Bool
    ) {
        self.schemaVersion = schemaVersion
        self.recordingID = recordingID
        self.sessionID = sessionID
        self.roundSetup = roundSetup
        self.startedAtUTC = startedAtUTC
        self.stoppedAtUTC = stoppedAtUTC
        self.evidencePackageIDs = evidencePackageIDs
        self.acknowledgedEvidencePackageIDs = acknowledgedEvidencePackageIDs
        self.evidenceMembershipClosed = evidenceMembershipClosed
        self.recordingBundleFinalized = recordingBundleFinalized
        self.recordingBundleAcknowledged = recordingBundleAcknowledged
    }

    private static func encodeDate(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        return formatter.string(from: date)
    }

    private static func decodeDate<Key: CodingKey>(
        _ container: KeyedDecodingContainer<Key>,
        forKey key: Key
    ) throws -> Date {
        guard let date = decodeISO8601(try container.decode(String.self, forKey: key)) else {
            throw RoundRecordingStateError.invalidStoredState
        }
        return date
    }

    private static func decodeOptionalDate<Key: CodingKey>(
        _ container: KeyedDecodingContainer<Key>,
        forKey key: Key
    ) throws -> Date? {
        guard let value = try container.decodeIfPresent(String.self, forKey: key) else { return nil }
        guard let date = decodeISO8601(value) else {
            throw RoundRecordingStateError.invalidStoredState
        }
        return date
    }
}

public enum RoundRecordingStateError: LocalizedError, Equatable, Sendable {
    case invalidTimestamp
    case invalidStoredState
    case packageNotTracked(UUID)
    case cannotRead(URL, String)
    case cannotWrite(URL, String)

    public var errorDescription: String? {
        switch self {
        case .invalidTimestamp:
            return "The round recording timestamp is invalid."
        case .invalidStoredState:
            return "The stored round recording state is invalid."
        case let .packageNotTracked(packageID):
            return "Evidence package \(packageID.uuidString.lowercased()) is not tracked by the round recording."
        case let .cannotRead(url, message):
            return "The round recording state could not be read at \(url.path): \(message)"
        case let .cannotWrite(url, message):
            return "The round recording state could not be written at \(url.path): \(message)"
        }
    }
}

/// Persists the single active round-recording workflow beside the recording queue.
public final class RoundRecordingStateStore: @unchecked Sendable {
    public let directory: URL
    public let stateURL: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()

    public init(directory: URL, stateFileName: String = "round-recording.json") {
        self.directory = directory
        stateURL = directory.appendingPathComponent(stateFileName, isDirectory: false)
    }

    public func load() throws -> RoundRecordingState? {
        lock.lock()
        defer { lock.unlock() }
        return try loadLocked()
    }

    public func save(_ state: RoundRecordingState) throws {
        lock.lock()
        defer { lock.unlock() }
        try saveLocked(state)
    }

    @discardableResult
    public func appendEvidencePackage(
        _ packageID: UUID,
        recordingID: String,
        sessionID: UUID
    ) throws -> RoundRecordingState? {
        lock.lock()
        defer { lock.unlock() }
        guard let state = try loadLocked(),
              state.recordingID == recordingID,
              state.sessionID == sessionID else {
            return nil
        }
        let updated = try state.addingEvidencePackage(packageID)
        try saveLocked(updated)
        return updated
    }

    @discardableResult
    public func acknowledgeEvidencePackage(
        _ packageID: UUID,
        recordingID: String
    ) throws -> RoundRecordingState? {
        lock.lock()
        defer { lock.unlock() }
        guard let state = try loadLocked(), state.recordingID == recordingID else { return nil }
        let updated = try state.acknowledgingEvidencePackage(packageID)
        try saveLocked(updated)
        return updated
    }

    @discardableResult
    public func closeEvidenceMembership(
        recordingID: String,
        at date: Date = Date()
    ) throws -> RoundRecordingState? {
        lock.lock()
        defer { lock.unlock() }
        guard let state = try loadLocked(), state.recordingID == recordingID else { return nil }
        let updated = try state.closingEvidenceMembership(at: date)
        try saveLocked(updated)
        return updated
    }

    @discardableResult
    public func markRecordingBundleFinalized(
        recordingID: String
    ) throws -> RoundRecordingState? {
        lock.lock()
        defer { lock.unlock() }
        guard let state = try loadLocked(), state.recordingID == recordingID else { return nil }
        let updated = state.markingRecordingBundleFinalized()
        try saveLocked(updated)
        return updated
    }

    @discardableResult
    public func markRecordingBundleAcknowledged(
        recordingID: String
    ) throws -> RoundRecordingState? {
        lock.lock()
        defer { lock.unlock() }
        guard let state = try loadLocked(), state.recordingID == recordingID else { return nil }
        let updated = state.markingRecordingBundleAcknowledged()
        try saveLocked(updated)
        return updated
    }

    public func remove() throws {
        lock.lock()
        defer { lock.unlock() }
        guard fileManager.fileExists(atPath: stateURL.path) else { return }
        do {
            try fileManager.removeItem(at: stateURL)
        } catch {
            throw RoundRecordingStateError.cannotWrite(stateURL, error.localizedDescription)
        }
    }

    private func loadLocked() throws -> RoundRecordingState? {
        guard fileManager.fileExists(atPath: stateURL.path) else { return nil }
        do {
            return try JSONDecoder().decode(
                RoundRecordingState.self,
                from: Data(contentsOf: stateURL)
            )
        } catch {
            throw RoundRecordingStateError.cannotRead(stateURL, error.localizedDescription)
        }
    }

    private func saveLocked(_ state: RoundRecordingState) throws {
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(state).write(to: stateURL, options: .atomic)
        } catch {
            throw RoundRecordingStateError.cannotWrite(stateURL, error.localizedDescription)
        }
    }
}

private func roundRecordingIsIdentifier(_ value: String) -> Bool {
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

private func decodeISO8601(_ value: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = formatter.date(from: value) { return date }
    formatter.formatOptions.remove(.withFractionalSeconds)
    return formatter.date(from: value)
}

private func roundRecordingRequireExactKeys<Key: CodingKey & CaseIterable>(
    _ container: KeyedDecodingContainer<Key>,
    _ keyType: Key.Type
) throws {
    let expected = Set(keyType.allCases.map(\.stringValue))
    let actual = Set(container.allKeys.map(\.stringValue))
    guard actual == expected else {
        throw RoundRecordingStateError.invalidStoredState
    }
}
