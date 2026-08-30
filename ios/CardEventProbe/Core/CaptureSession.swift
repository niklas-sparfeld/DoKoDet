import Foundation

/// The small amount of capture state needed to keep evidence ordered.
public struct CaptureSessionState: Codable, Equatable, Sendable {
    public let sessionID: UUID
    public let startedAtUTC: Date
    public let nextEventSequence: Int

    public init(
        sessionID: UUID = UUID(),
        startedAtUTC: Date = Date(),
        nextEventSequence: Int = 1
    ) {
        precondition(
            startedAtUTC.timeIntervalSinceReferenceDate.isFinite,
            "session start time must be finite"
        )
        precondition(nextEventSequence > 0, "event sequence must be positive")
        self.sessionID = sessionID
        self.startedAtUTC = startedAtUTC
        self.nextEventSequence = nextEventSequence
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let startedAtString = try container.decode(String.self, forKey: .startedAtUTC)
        guard let startedAtUTC = CaptureSessionState.parseUTCDate(startedAtString) else {
            throw DecodingError.dataCorruptedError(
                forKey: .startedAtUTC,
                in: container,
                debugDescription: "started_at_utc must be an ISO-8601 UTC timestamp."
            )
        }

        let nextEventSequence = try container.decode(Int.self, forKey: .nextEventSequence)
        guard nextEventSequence > 0 else {
            throw DecodingError.dataCorruptedError(
                forKey: .nextEventSequence,
                in: container,
                debugDescription: "next_event_sequence must be positive."
            )
        }

        self.init(
            sessionID: try container.decode(UUID.self, forKey: .sessionID),
            startedAtUTC: startedAtUTC,
            nextEventSequence: nextEventSequence
        )
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(sessionID.uuidString.lowercased(), forKey: .sessionID)
        try container.encode(CaptureSessionState.utcString(from: startedAtUTC), forKey: .startedAtUTC)
        try container.encode(nextEventSequence, forKey: .nextEventSequence)
    }

    private enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case startedAtUTC = "started_at_utc"
        case nextEventSequence = "next_event_sequence"
    }

    private static func utcString(from date: Date) -> String {
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

    private static func parseUTCDate(_ value: String) -> Date? {
        guard value.hasSuffix("Z")
                || value.hasSuffix("+00:00")
                || value.hasSuffix("-00:00") else {
            return nil
        }

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
}

public enum CaptureSessionIdentityStoreError: LocalizedError, Equatable {
    case cannotCreateDirectory(URL, String)
    case cannotRead(URL, String)
    case cannotWrite(URL, String)
    case invalidState(URL, String)
    case noActiveSession
    case sequenceExhausted

    public var errorDescription: String? {
        switch self {
        case let .cannotCreateDirectory(url, message):
            return "The capture-session directory could not be created at \(url.path): \(message)"
        case let .cannotRead(url, message):
            return "The capture-session state could not be read at \(url.path): \(message)"
        case let .cannotWrite(url, message):
            return "The capture-session state could not be written at \(url.path): \(message)"
        case let .invalidState(url, message):
            return "The capture-session state at \(url.path) is invalid: \(message)"
        case .noActiveSession:
            return "There is no active capture session."
        case .sequenceExhausted:
            return "The capture-session event sequence is exhausted."
        }
    }
}

/// Owns the active capture session record and persists sequence reservations atomically.
public final class CaptureSessionIdentityStore: @unchecked Sendable {
    public let directory: URL
    public let stateURL: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()

    public init(directory: URL, stateFileName: String = "active.json") {
        self.directory = directory
        stateURL = directory.appendingPathComponent(stateFileName, isDirectory: false)
    }

    /// Starts a new session and replaces any stale active-session marker.
    public func startSession(
        sessionID: UUID = UUID(),
        startedAtUTC: Date = Date(),
        clock: EvidenceSessionClock? = nil
    ) throws -> CaptureSession {
        lock.lock()
        defer { lock.unlock() }

        let state = CaptureSessionState(sessionID: sessionID, startedAtUTC: startedAtUTC)
        try writeLocked(state)
        return CaptureSession(state: state, store: self, clock: clock)
    }

    /// Reopens the active session left by an interrupted process, if one exists.
    public func resumeSession() throws -> CaptureSession? {
        lock.lock()
        defer { lock.unlock() }

        guard fileManager.fileExists(atPath: stateURL.path) else { return nil }
        return CaptureSession(state: try readLocked(), store: self)
    }

    /// Ends the active session without changing any persisted evidence package.
    public func endSession(sessionID: UUID) throws {
        lock.lock()
        defer { lock.unlock() }

        guard fileManager.fileExists(atPath: stateURL.path) else { return }
        let state = try readLocked()
        guard state.sessionID == sessionID else { return }
        do {
            try fileManager.removeItem(at: stateURL)
        } catch {
            throw CaptureSessionIdentityStoreError.cannotWrite(stateURL, error.localizedDescription)
        }
    }

    fileprivate func reserveEventSequence(for sessionID: UUID) throws -> Int {
        lock.lock()
        defer { lock.unlock() }

        guard fileManager.fileExists(atPath: stateURL.path) else {
            throw CaptureSessionIdentityStoreError.noActiveSession
        }
        let state = try readLocked()
        guard state.sessionID == sessionID else {
            throw CaptureSessionIdentityStoreError.invalidState(
                stateURL,
                "the active session does not match the requested session"
            )
        }
        guard state.nextEventSequence < Int.max else {
            throw CaptureSessionIdentityStoreError.sequenceExhausted
        }

        let sequence = state.nextEventSequence
        try writeLocked(
            CaptureSessionState(
                sessionID: state.sessionID,
                startedAtUTC: state.startedAtUTC,
                nextEventSequence: sequence + 1
            )
        )
        return sequence
    }

    fileprivate func state(for sessionID: UUID) throws -> CaptureSessionState {
        lock.lock()
        defer { lock.unlock() }

        guard fileManager.fileExists(atPath: stateURL.path) else {
            throw CaptureSessionIdentityStoreError.noActiveSession
        }
        let state = try readLocked()
        guard state.sessionID == sessionID else {
            throw CaptureSessionIdentityStoreError.invalidState(
                stateURL,
                "the active session does not match the requested session"
            )
        }
        return state
    }

    private func readLocked() throws -> CaptureSessionState {
        let data: Data
        do {
            data = try Data(contentsOf: stateURL)
        } catch {
            throw CaptureSessionIdentityStoreError.cannotRead(stateURL, error.localizedDescription)
        }

        do {
            return try JSONDecoder().decode(CaptureSessionState.self, from: data)
        } catch {
            throw CaptureSessionIdentityStoreError.invalidState(stateURL, error.localizedDescription)
        }
    }

    private func writeLocked(_ state: CaptureSessionState) throws {
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            throw CaptureSessionIdentityStoreError.cannotCreateDirectory(
                directory,
                error.localizedDescription
            )
        }

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
        let data: Data
        do {
            data = try encoder.encode(state)
            try data.write(to: stateURL, options: .atomic)
        } catch {
            throw CaptureSessionIdentityStoreError.cannotWrite(stateURL, error.localizedDescription)
        }
    }
}

/// A capture-session handle shared by evidence sampling and package assembly.
public final class CaptureSession: @unchecked Sendable {
    public let sessionID: UUID
    public let startedAtUTC: Date
    public let clock: EvidenceSessionClock

    private let store: CaptureSessionIdentityStore?
    private let lock = NSLock()
    private var inMemoryNextEventSequence: Int

    public var nextEventSequence: Int {
        if let store {
            if let nextEventSequence = try? store.state(for: sessionID).nextEventSequence {
                return nextEventSequence
            }
        }
        lock.lock()
        defer { lock.unlock() }
        return inMemoryNextEventSequence
    }

    /// Creates an in-memory session for callers that do not need persistence.
    public convenience init(
        sessionID: UUID = UUID(),
        startedAtUTC: Date = Date(),
        nextEventSequence: Int = 1
    ) {
        self.init(
            sessionID: sessionID,
            startedAtUTC: startedAtUTC,
            nextEventSequence: nextEventSequence,
            clock: EvidenceSessionClock(startedAtUTC: startedAtUTC)
        )
    }

    internal init(
        sessionID: UUID,
        startedAtUTC: Date,
        nextEventSequence: Int = 1,
        clock: EvidenceSessionClock
    ) {
        precondition(
            startedAtUTC.timeIntervalSinceReferenceDate.isFinite,
            "session start time must be finite"
        )
        precondition(nextEventSequence > 0, "event sequence must be positive")
        self.sessionID = sessionID
        self.startedAtUTC = startedAtUTC
        self.clock = clock
        store = nil
        inMemoryNextEventSequence = nextEventSequence
    }

    fileprivate init(
        state: CaptureSessionState,
        store: CaptureSessionIdentityStore,
        clock: EvidenceSessionClock? = nil
    ) {
        sessionID = state.sessionID
        startedAtUTC = state.startedAtUTC
        self.clock = clock ?? EvidenceSessionClock(startedAtUTC: state.startedAtUTC)
        self.store = store
        inMemoryNextEventSequence = state.nextEventSequence
    }

    /// Reserves a sequence before package assembly. A failed write does not consume it.
    public func reserveEventSequence() throws -> Int {
        if let store {
            let sequence = try store.reserveEventSequence(for: sessionID)
            lock.lock()
            inMemoryNextEventSequence = sequence + 1
            lock.unlock()
            return sequence
        }

        lock.lock()
        defer { lock.unlock() }
        guard inMemoryNextEventSequence < Int.max else {
            throw CaptureSessionIdentityStoreError.sequenceExhausted
        }
        let sequence = inMemoryNextEventSequence
        inMemoryNextEventSequence += 1
        return sequence
    }
}
