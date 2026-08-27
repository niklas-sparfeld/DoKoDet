import Foundation

public enum TrainingRecordingWorkflowState: Equatable, Sendable {
    case idle
    case recording
    case finalizing
    case queued
    case uploading
    case acknowledged
    case failed(String)

    public var title: String {
        switch self {
        case .idle:
            return "Idle"
        case .recording:
            return "Recording"
        case .finalizing:
            return "Finalizing"
        case .queued:
            return "Queued"
        case .uploading:
            return "Uploading"
        case .acknowledged:
            return "Acknowledged"
        case .failed:
            return "Failed"
        }
    }
}

public enum TrainingRecordingQueueState: String, CaseIterable, Codable, Sendable {
    case queued
    case acknowledged
    case failed
    case corrupt
}

public enum TrainingRecordingFailureKind: String, Codable, Sendable {
    case retryable
    case permanent
}

public struct TrainingRecordingFailure: Codable, Equatable, Sendable {
    public let kind: TrainingRecordingFailureKind
    public let statusCode: Int?
    public let message: String
    public let recordedAt: Date

    public init(
        kind: TrainingRecordingFailureKind,
        statusCode: Int? = nil,
        message: String,
        recordedAt: Date = Date()
    ) {
        self.kind = kind
        self.statusCode = statusCode
        self.message = message
        self.recordedAt = recordedAt
    }
}

public struct TrainingRecordingQueueDiagnostics: Equatable, Sendable {
    public let stagingCount: Int
    public let queuedCount: Int
    public let acknowledgedCount: Int
    public let failedCount: Int
    public let corruptCount: Int
    public let retryableFailureCount: Int
    public let permanentFailureCount: Int
    public let recoveredRecordingIDs: [String]
    public let corruptPaths: [String]
    public let errors: [String]

    public init(
        stagingCount: Int,
        queuedCount: Int,
        acknowledgedCount: Int,
        failedCount: Int,
        corruptCount: Int,
        retryableFailureCount: Int = 0,
        permanentFailureCount: Int = 0,
        recoveredRecordingIDs: [String] = [],
        corruptPaths: [String] = [],
        errors: [String] = []
    ) {
        self.stagingCount = stagingCount
        self.queuedCount = queuedCount
        self.acknowledgedCount = acknowledgedCount
        self.failedCount = failedCount
        self.corruptCount = corruptCount
        self.retryableFailureCount = retryableFailureCount
        self.permanentFailureCount = permanentFailureCount
        self.recoveredRecordingIDs = recoveredRecordingIDs
        self.corruptPaths = corruptPaths
        self.errors = errors
    }
}

public enum TrainingRecordingStoreError: LocalizedError, Equatable {
    case invalidTransition(TrainingRecordingQueueState, TrainingRecordingQueueState)
    case recordingNotFound(URL)
    case recordingAlreadyExists(URL)
    case invalidRecording(URL, String)
    case writeFailed(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .invalidTransition(source, destination):
            return "The training recording cannot move from \(source.rawValue) to \(destination.rawValue)."
        case let .recordingNotFound(url):
            return "The training recording was not found at \(url.path)."
        case let .recordingAlreadyExists(url):
            return "The training recording already exists at \(url.path)."
        case let .invalidRecording(url, message):
            return "The training recording at \(url.path) is invalid: \(message)."
        case let .writeFailed(url, message):
            return "The training recording queue could not write \(url.path): \(message)"
        }
    }
}

/// Stores immutable finalized bundles in durable queue state directories.
public final class TrainingRecordingStore: @unchecked Sendable {
    public let root: URL

    private let fileManager = FileManager.default
    private let lock = NSLock()
    private var storedDiagnostics = TrainingRecordingQueueDiagnostics(
        stagingCount: 0,
        queuedCount: 0,
        acknowledgedCount: 0,
        failedCount: 0,
        corruptCount: 0
    )

    public init(root: URL) {
        self.root = root
    }

    public var diagnostics: TrainingRecordingQueueDiagnostics {
        lock.lock()
        defer { lock.unlock() }
        return storedDiagnostics
    }

    public func directoryURL(for state: TrainingRecordingQueueState) -> URL {
        root.appendingPathComponent(state.rawValue, isDirectory: true)
    }

    public func recordingURL(
        for recordingID: String,
        in state: TrainingRecordingQueueState = .queued
    ) -> URL {
        directoryURL(for: state).appendingPathComponent(recordingID, isDirectory: true)
    }

    public func recordingURLs(in state: TrainingRecordingQueueState) throws -> [URL] {
        lock.lock()
        defer { lock.unlock() }
        try ensureLayoutLocked()
        return try entriesLocked(in: state)
            .filter { isDirectory($0) && $0.lastPathComponent != ".staging" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    public func failure(for recordingID: String) -> TrainingRecordingFailure? {
        lock.lock()
        defer { lock.unlock() }
        return failureLocked(for: recordingID)
    }

    public func acknowledgementData(for recordingID: String) -> Data? {
        lock.lock()
        defer { lock.unlock() }
        return try? Data(contentsOf: acknowledgementURL(for: recordingID))
    }

    @discardableResult
    public func moveRecording(
        for recordingID: String,
        from sourceState: TrainingRecordingQueueState,
        to destinationState: TrainingRecordingQueueState,
        failure: TrainingRecordingFailure? = nil,
        acknowledgementData: Data? = nil
    ) throws -> URL {
        lock.lock()
        defer { lock.unlock() }

        guard sourceState != destinationState else {
            throw TrainingRecordingStoreError.invalidTransition(sourceState, destinationState)
        }
        try ensureLayoutLocked()

        let sourceURL = recordingURL(for: recordingID, in: sourceState)
        let destinationURL = recordingURL(for: recordingID, in: destinationState)
        guard isDirectory(sourceURL) else {
            throw TrainingRecordingStoreError.recordingNotFound(sourceURL)
        }
        guard !fileManager.fileExists(atPath: destinationURL.path) else {
            throw TrainingRecordingStoreError.recordingAlreadyExists(destinationURL)
        }

        let failureURL = failureURL(for: recordingID)
        let acknowledgementURL = acknowledgementURL(for: recordingID)
        do {
            switch destinationState {
            case .failed:
                guard let failure else {
                    throw TrainingRecordingStoreError.invalidTransition(sourceState, destinationState)
                }
                try encodeFailure(failure, to: failureURL)
            case .acknowledged:
                if let acknowledgementData {
                    try acknowledgementData.write(to: acknowledgementURL, options: .atomic)
                }
            case .queued, .corrupt:
                break
            }

            try fileManager.moveItem(at: sourceURL, to: destinationURL)
            if destinationState != .failed {
                try? fileManager.removeItem(at: failureURL)
            }
            if destinationState != .acknowledged {
                try? fileManager.removeItem(at: acknowledgementURL)
            }
            storedDiagnostics = makeDiagnosticsLocked()
            return destinationURL
        } catch let error as TrainingRecordingStoreError {
            throw error
        } catch {
            if destinationState == .failed {
                try? fileManager.removeItem(at: failureURL)
            }
            if destinationState == .acknowledged {
                try? fileManager.removeItem(at: acknowledgementURL)
            }
            throw TrainingRecordingStoreError.writeFailed(
                destinationURL,
                error.localizedDescription
            )
        }
    }

    public func retryableFailedRecordingURLs() throws -> [URL] {
        try recordingURLs(in: .failed).filter { url in
            failure(for: url.lastPathComponent)?.kind == .retryable
        }
    }

    @discardableResult
    public func requeueFailedRecording(for recordingID: String) throws -> URL {
        lock.lock()
        defer { lock.unlock() }

        guard failureLocked(for: recordingID)?.kind == .retryable else {
            throw TrainingRecordingStoreError.invalidTransition(.failed, .queued)
        }
        let sourceURL = recordingURL(for: recordingID, in: .failed)
        let destinationURL = recordingURL(for: recordingID, in: .queued)
        guard isDirectory(sourceURL) else {
            throw TrainingRecordingStoreError.recordingNotFound(sourceURL)
        }
        guard !fileManager.fileExists(atPath: destinationURL.path) else {
            throw TrainingRecordingStoreError.recordingAlreadyExists(destinationURL)
        }
        do {
            try fileManager.moveItem(at: sourceURL, to: destinationURL)
            try? fileManager.removeItem(at: failureURL(for: recordingID))
            storedDiagnostics = makeDiagnosticsLocked()
            return destinationURL
        } catch {
            throw TrainingRecordingStoreError.writeFailed(
                destinationURL,
                error.localizedDescription
            )
        }
    }

    /// Rebuilds durable state on launch and retains invalid queued bundles for inspection.
    @discardableResult
    public func recover() throws -> TrainingRecordingQueueDiagnostics {
        lock.lock()
        defer { lock.unlock() }

        try ensureLayoutLocked()
        var recoveredIDs: [String] = []
        var corruptPaths: [String] = []
        var errors: [String] = []

        for recordingURL in try entriesLocked(in: .queued)
            where isDirectory(recordingURL) && recordingURL.lastPathComponent != ".staging" {
            do {
                let manifest = try validateRecordingLocked(at: recordingURL)
                let expectedURL = self.recordingURL(for: manifest.recordingID)
                guard expectedURL.standardizedFileURL == recordingURL.standardizedFileURL else {
                    throw TrainingRecordingStoreError.invalidRecording(
                        recordingURL,
                        "directory name does not match manifest.recording_id"
                    )
                }
                recoveredIDs.append(manifest.recordingID)
            } catch {
                retainCorruptLocked(
                    recordingURL,
                    error: error,
                    paths: &corruptPaths,
                    errors: &errors
                )
            }
        }

        storedDiagnostics = makeDiagnosticsLocked(
            recoveredRecordingIDs: recoveredIDs,
            corruptPaths: corruptPaths,
            errors: errors
        )
        return storedDiagnostics
    }

    public func validateRecording(at recordingURL: URL) throws -> TrainingRecordingManifest {
        lock.lock()
        defer { lock.unlock() }
        return try validateRecordingLocked(at: recordingURL)
    }

    private func ensureLayoutLocked() throws {
        do {
            for state in TrainingRecordingQueueState.allCases {
                try fileManager.createDirectory(
                    at: directoryURL(for: state),
                    withIntermediateDirectories: true
                )
            }
            try fileManager.createDirectory(
                at: root.appendingPathComponent("failures", isDirectory: true),
                withIntermediateDirectories: true
            )
            try fileManager.createDirectory(
                at: root.appendingPathComponent("acknowledgements", isDirectory: true),
                withIntermediateDirectories: true
            )
            try fileManager.createDirectory(
                at: directoryURL(for: .queued).appendingPathComponent(".staging", isDirectory: true),
                withIntermediateDirectories: true
            )
        } catch {
            throw TrainingRecordingStoreError.writeFailed(root, error.localizedDescription)
        }
    }

    private func entriesLocked(in state: TrainingRecordingQueueState) throws -> [URL] {
        do {
            return try fileManager.contentsOfDirectory(
                at: directoryURL(for: state),
                includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
                options: []
            )
        } catch {
            throw TrainingRecordingStoreError.writeFailed(
                directoryURL(for: state),
                error.localizedDescription
            )
        }
    }

    private func validateRecordingLocked(at recordingURL: URL) throws -> TrainingRecordingManifest {
        guard isDirectory(recordingURL) else {
            throw TrainingRecordingStoreError.invalidRecording(recordingURL, "entry is not a directory")
        }
        let manifestURL = recordingURL.appendingPathComponent("manifest.json")
        guard isRegularFile(manifestURL) else {
            throw TrainingRecordingStoreError.invalidRecording(recordingURL, "manifest.json is missing")
        }
        let manifestData: Data
        do {
            manifestData = try Data(contentsOf: manifestURL)
        } catch {
            throw TrainingRecordingStoreError.invalidRecording(recordingURL, error.localizedDescription)
        }
        let entries: [URL]
        do {
            entries = try fileManager.contentsOfDirectory(
                at: recordingURL,
                includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
                options: []
            )
        } catch {
            throw TrainingRecordingStoreError.invalidRecording(recordingURL, error.localizedDescription)
        }
        let manifest: TrainingRecordingManifest
        do {
            manifest = try JSONDecoder().decode(TrainingRecordingManifest.self, from: manifestData)
        } catch {
            throw TrainingRecordingStoreError.invalidRecording(recordingURL, error.localizedDescription)
        }
        let videoURL = recordingURL.appendingPathComponent(manifest.video.name)
        let predictionsURL = recordingURL.appendingPathComponent(manifest.predictions.name)
        guard Set(entries.map(\.lastPathComponent)) == Set([
            "manifest.json",
            manifest.video.name,
            manifest.predictions.name,
        ]) else {
            throw TrainingRecordingStoreError.invalidRecording(
                recordingURL,
                "bundle contains an unexpected top-level entry"
            )
        }
        guard isRegularFile(videoURL), isRegularFile(predictionsURL) else {
            throw TrainingRecordingStoreError.invalidRecording(
                recordingURL,
                "the manifest files are missing"
            )
        }
        do {
            _ = try validateTrainingRecordingBundle(
                manifestData: manifestData,
                predictionsData: Data(contentsOf: predictionsURL),
                videoURL: videoURL
            )
        } catch {
            throw TrainingRecordingStoreError.invalidRecording(recordingURL, error.localizedDescription)
        }
        return manifest
    }

    private func retainCorruptLocked(
        _ sourceURL: URL,
        error: Error,
        paths: inout [String],
        errors: inout [String]
    ) {
        let destinationURL = directoryURL(for: .corrupt)
            .appendingPathComponent(
                "\(sourceURL.lastPathComponent)-\(UUID().uuidString.lowercased())",
                isDirectory: true
            )
        do {
            try fileManager.moveItem(at: sourceURL, to: destinationURL)
            paths.append(destinationURL.path)
        } catch {
            paths.append(sourceURL.path)
            errors.append("The invalid recording at \(sourceURL.path) could not be retained: \(error.localizedDescription)")
        }
        errors.append(error.localizedDescription)
    }

    private func makeDiagnosticsLocked(
        recoveredRecordingIDs: [String] = [],
        corruptPaths: [String] = [],
        errors: [String] = []
    ) -> TrainingRecordingQueueDiagnostics {
        let stagingCount = (try? entriesLocked(in: .queued).filter {
            $0.lastPathComponent == ".staging" && isDirectory($0)
        }.flatMap { (try? fileManager.contentsOfDirectory(at: $0, includingPropertiesForKeys: [.isDirectoryKey], options: [])) ?? [] }.filter(isDirectory).count) ?? 0
        let failedURLs = (try? entriesLocked(in: .failed).filter(isDirectory)) ?? []
        let retryable = failedURLs.filter {
            failureLocked(for: $0.lastPathComponent)?.kind == .retryable
        }.count
        return TrainingRecordingQueueDiagnostics(
            stagingCount: stagingCount,
            queuedCount: ((try? entriesLocked(in: .queued).filter { isDirectory($0) && $0.lastPathComponent != ".staging" }.count) ?? 0),
            acknowledgedCount: ((try? entriesLocked(in: .acknowledged).filter(isDirectory).count) ?? 0),
            failedCount: failedURLs.count,
            corruptCount: ((try? entriesLocked(in: .corrupt).filter(isDirectory).count) ?? 0),
            retryableFailureCount: retryable,
            permanentFailureCount: failedURLs.count - retryable,
            recoveredRecordingIDs: recoveredRecordingIDs,
            corruptPaths: corruptPaths,
            errors: errors
        )
    }

    private func failureLocked(for recordingID: String) -> TrainingRecordingFailure? {
        guard let data = try? Data(contentsOf: failureURL(for: recordingID)) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(TrainingRecordingFailure.self, from: data)
    }

    private func encodeFailure(_ failure: TrainingRecordingFailure, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(failure).write(to: url, options: .atomic)
    }

    private func failureURL(for recordingID: String) -> URL {
        root.appendingPathComponent("failures", isDirectory: true)
            .appendingPathComponent("\(recordingID).json")
    }

    private func acknowledgementURL(for recordingID: String) -> URL {
        root.appendingPathComponent("acknowledgements", isDirectory: true)
            .appendingPathComponent("\(recordingID).json")
    }

    private func isDirectory(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
    }

    private func isRegularFile(_ url: URL) -> Bool {
        (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
    }
}
