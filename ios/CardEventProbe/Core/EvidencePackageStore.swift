import Foundation

public enum EvidencePackageQueueState: String, CaseIterable, Codable, Sendable {
    case staging
    case queued
    case acknowledged
    case failed
    case corrupt
}
public enum EvidencePackageFailureKind: String, Codable, Sendable {
    case retryable
    case permanent
}

public struct EvidencePackageFailure: Codable, Equatable, Sendable {
    public let kind: EvidencePackageFailureKind
    public let statusCode: Int?
    public let message: String
    public let recordedAt: Date

    public init(
        kind: EvidencePackageFailureKind,
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

public struct EvidencePackageQueueDiagnostics: Equatable, Sendable {
    public let stagingCount: Int
    public let queuedCount: Int
    public let acknowledgedCount: Int
    public let failedCount: Int
    public let corruptCount: Int
    public let retryableFailureCount: Int
    public let permanentFailureCount: Int
    public let queuedByteCount: Int
    public let queuedByteCapacity: Int
    public let recoveredPackageIDs: [UUID]
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
        queuedByteCount: Int = 0,
        queuedByteCapacity: Int = EvidenceVideoCaptureMetadata.standard.queuedByteCapacity,
        recoveredPackageIDs: [UUID] = [],
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
        self.queuedByteCount = queuedByteCount
        self.queuedByteCapacity = queuedByteCapacity
        self.recoveredPackageIDs = recoveredPackageIDs
        self.corruptPaths = corruptPaths
        self.errors = errors
    }
}

public final class EvidencePackageStore: @unchecked Sendable {
    public let root: URL
    public let queuedByteCapacity: Int

    private let fileManager = FileManager.default
    private let lock = NSLock()
    private var storedDiagnostics = EvidencePackageQueueDiagnostics(
        stagingCount: 0,
        queuedCount: 0,
        acknowledgedCount: 0,
        failedCount: 0,
        corruptCount: 0
    )

    public init(
        root: URL,
        queuedByteCapacity: Int = EvidenceVideoCaptureMetadata.standard.queuedByteCapacity
    ) {
        precondition(queuedByteCapacity > 0, "queued byte capacity must be positive")
        self.root = root
        self.queuedByteCapacity = queuedByteCapacity
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

    /// Returns package directories in a deterministic order.
    public func packageURLs(in state: EvidencePackageQueueState) throws -> [URL] {
        lock.lock()
        defer { lock.unlock() }
        try ensureLayoutLocked()
        return try entriesLocked(in: state)
            .filter { isDirectory($0) }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    public func failure(for packageID: UUID) -> EvidencePackageFailure? {
        lock.lock()
        defer { lock.unlock() }
        return failureLocked(for: packageID)
    }

    public func acknowledgementData(for packageID: UUID) -> Data? {
        lock.lock()
        defer { lock.unlock() }
        return try? Data(contentsOf: acknowledgementMetadataURL(for: packageID))
    }

    /// Moves a package between durable queue states.
    ///
    /// Failure and acknowledgement records are stored beside the package directory. They do not
    /// change the immutable package contents.
    @discardableResult
    public func movePackage(
        for packageID: UUID,
        from sourceState: EvidencePackageQueueState,
        to destinationState: EvidencePackageQueueState,
        failure: EvidencePackageFailure? = nil,
        acknowledgementData: Data? = nil
    ) throws -> URL {
        lock.lock()
        defer { lock.unlock() }

        guard sourceState != destinationState else {
            throw EvidencePackageStoreError.invalidTransition(
                sourceState,
                destinationState
            )
        }
        try ensureLayoutLocked()

        let sourceURL = packageURL(for: packageID, in: sourceState)
        let destinationURL = packageURL(for: packageID, in: destinationState)
        guard fileManager.fileExists(atPath: sourceURL.path) else {
            throw EvidencePackageStoreError.packageNotFound(sourceURL)
        }
        guard !fileManager.fileExists(atPath: destinationURL.path) else {
            throw EvidencePackageStoreError.packageAlreadyExists(destinationURL)
        }
        guard let sourceID = UUID(uuidString: sourceURL.lastPathComponent), sourceID == packageID else {
            throw EvidencePackageStoreError.invalidPackage(
                sourceURL,
                "package directory name is not the requested package_id"
            )
        }

        let failureURL = failureMetadataURL(for: packageID)
        let acknowledgementURL = acknowledgementMetadataURL(for: packageID)
        do {
            switch destinationState {
            case .failed:
                guard let failure else {
                    throw EvidencePackageStoreError.invalidTransition(
                        sourceState,
                        destinationState
                    )
                }
                try encodeFailure(failure, to: failureURL)
            case .acknowledged:
                if let acknowledgementData {
                    try acknowledgementData.write(to: acknowledgementURL, options: .atomic)
                }
            case .staging, .queued, .corrupt:
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
        } catch let error as EvidencePackageStoreError {
            throw error
        } catch {
            if destinationState == .failed {
                try? fileManager.removeItem(at: failureURL)
            }
            if destinationState == .acknowledged {
                try? fileManager.removeItem(at: acknowledgementURL)
            }
            throw EvidencePackageStoreError.writeFailed(
                destinationURL,
                error.localizedDescription
            )
        }
    }

    @discardableResult
    public func retryableFailedPackageURLs() throws -> [URL] {
        try packageURLs(in: .failed).filter { url in
            guard let packageID = UUID(uuidString: url.lastPathComponent) else { return false }
            return failure(for: packageID)?.kind == .retryable
        }
    }

    @discardableResult
    public func requeueFailedPackage(for packageID: UUID) throws -> URL {
        lock.lock()
        defer { lock.unlock() }

        guard failureLocked(for: packageID)?.kind == .retryable else {
            throw EvidencePackageStoreError.invalidTransition(.failed, .queued)
        }
        let sourceURL = packageURL(for: packageID, in: .failed)
        let destinationURL = packageURL(for: packageID, in: .queued)
        guard !fileManager.fileExists(atPath: destinationURL.path) else {
            throw EvidencePackageStoreError.packageAlreadyExists(destinationURL)
        }
        do {
            try fileManager.moveItem(at: sourceURL, to: destinationURL)
            try? fileManager.removeItem(at: failureMetadataURL(for: packageID))
            storedDiagnostics = makeDiagnosticsLocked()
            return destinationURL
        } catch {
            throw EvidencePackageStoreError.writeFailed(
                destinationURL,
                error.localizedDescription
            )
        }
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
        let repositoryMetadata: EvidencePackageRepositoryMetadata
        let repositoryMetadataData: (packageRecord: Data, taskEnrollment: Data, lineage: Data)
        do {
            repositoryMetadata = try package.repositoryMetadata
                ?? EvidencePackageRepositoryMetadata.standard(for: package.manifest)
            repositoryMetadataData = try repositoryMetadata.encodedDocuments()
        } catch {
            throw EvidencePackageStoreError.writeFailed(root, error.localizedDescription)
        }

        try ensureLayoutLocked()
        let finalURL = packageURL(for: package.manifest.packageID)
        if fileManager.fileExists(atPath: finalURL.path) {
            throw EvidencePackageStoreError.packageAlreadyExists(finalURL)
        }
        let packageByteCount = manifestData.count
            + repositoryMetadataData.packageRecord.count
            + repositoryMetadataData.taskEnrollment.count
            + repositoryMetadataData.lineage.count
            + package.frames.reduce(0) { $0 + $1.jpegData.count }
            + (package.videoSnippet?.mp4Data.count ?? 0)
        let queuedByteCount = directoryByteCountLocked(directoryURL(for: .queued))
        guard queuedByteCount <= queuedByteCapacity,
              packageByteCount <= queuedByteCapacity - queuedByteCount else {
            throw EvidencePackageStoreError.queuedByteCapacityExceeded(
                queuedByteCount + packageByteCount,
                queuedByteCapacity
            )
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
            if let videoSnippet = package.videoSnippet {
                guard let partName = videoSnippet.manifest.partName else {
                    throw EvidencePackageStoreError.invalidPackage(
                        stagingURL,
                        "a complete video snippet has no part name"
                    )
                }
                try fileManager.createDirectory(
                    at: stagingURL.appendingPathComponent("video", isDirectory: true),
                    withIntermediateDirectories: false
                )
                try videoSnippet.mp4Data.write(
                    to: stagingURL
                        .appendingPathComponent("video", isDirectory: true)
                        .appendingPathComponent("\(partName).mp4"),
                    options: .atomic
                )
            }
            try manifestData.write(
                to: stagingURL.appendingPathComponent("manifest.json"),
                options: .atomic
            )
            try repositoryMetadataData.packageRecord.write(
                to: stagingURL.appendingPathComponent("package-record.json"),
                options: .atomic
            )
            try repositoryMetadataData.taskEnrollment.write(
                to: stagingURL.appendingPathComponent("initial-task-enrollment.json"),
                options: .atomic
            )
            try repositoryMetadataData.lineage.write(
                to: stagingURL.appendingPathComponent("lineage.json"),
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
        let packageRecordURL = packageURL.appendingPathComponent("package-record.json", isDirectory: false)
        let taskEnrollmentURL = packageURL.appendingPathComponent("initial-task-enrollment.json", isDirectory: false)
        let lineageURL = packageURL.appendingPathComponent("lineage.json", isDirectory: false)
        let framesURL = packageURL.appendingPathComponent("frames", isDirectory: true)
        let videoURL = packageURL.appendingPathComponent("video", isDirectory: true)
        guard isRegularFile(manifestURL), isRegularFile(packageRecordURL),
              isRegularFile(taskEnrollmentURL), isRegularFile(lineageURL), isDirectory(framesURL) else {
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
        let repositoryMetadata: EvidencePackageRepositoryMetadata
        do {
            let decoder = JSONDecoder()
            let packageRecord = try decoder.decode(
                RepositoryEvidencePackageRecord.self,
                from: Data(contentsOf: packageRecordURL)
            )
            let taskEnrollment = try decoder.decode(
                RepositoryTaskEnrollmentDocument.self,
                from: Data(contentsOf: taskEnrollmentURL)
            )
            let lineage = try decoder.decode(
                RepositoryEvidencePackageLineage.self,
                from: Data(contentsOf: lineageURL)
            )
            repositoryMetadata = try EvidencePackageRepositoryMetadata(
                packageRecord: packageRecord,
                taskEnrollment: taskEnrollment,
                lineage: lineage
            )
            guard packageRecord.packageID == manifest.packageID.uuidString.lowercased(),
                  lineage.packageID == packageRecord.packageID else {
                throw EvidencePackageStoreError.invalidPackage(
                    packageURL,
                    "repository metadata does not match manifest.package_id"
                )
            }
        } catch let error as EvidencePackageStoreError {
            throw error
        } catch {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                "repository metadata is invalid: \(error.localizedDescription)"
            )
        }

        let hasCompleteVideo = manifest.videoSnippet?.captureComplete == true
        let expectedEntries = hasCompleteVideo
            ? Set(["manifest.json", "package-record.json", "initial-task-enrollment.json", "lineage.json", "frames", "video"])
            : Set(["manifest.json", "package-record.json", "initial-task-enrollment.json", "lineage.json", "frames"])
        guard Set(packageEntries.map(\.lastPathComponent)) == expectedEntries else {
            throw EvidencePackageStoreError.invalidPackage(
                packageURL,
                "package contains an unexpected top-level entry"
            )
        }
        if hasCompleteVideo {
            guard isDirectory(videoURL) else {
                throw EvidencePackageStoreError.invalidPackage(
                    videoURL,
                    "a complete video snippet requires a video directory"
                )
            }
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
                  evidencePackageSHA256Hex(data) == frameManifest.sha256 else {
                throw EvidencePackageStoreError.invalidPackage(
                    frameURL,
                    "frame byte length or SHA-256 does not match the manifest"
                )
            }
            packagedFrames.append(
                PackagedEvidenceFrame(manifest: frameManifest, jpegData: data)
            )
        }

        var packagedVideo: PackagedEvidenceVideo?
        if let videoManifest = manifest.videoSnippet, videoManifest.captureComplete {
            guard let partName = videoManifest.partName else {
                throw EvidencePackageStoreError.invalidPackage(
                    videoURL,
                    "a complete video snippet has no part name"
                )
            }
            let videoEntries: [URL]
            do {
                videoEntries = try fileManager.contentsOfDirectory(
                    at: videoURL,
                    includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
                    options: []
                )
            } catch {
                throw EvidencePackageStoreError.invalidPackage(videoURL, error.localizedDescription)
            }
            guard videoEntries.allSatisfy({ isRegularFile($0) }),
                  Set(videoEntries.map(\.lastPathComponent)) == Set(["\(partName).mp4"]) else {
                throw EvidencePackageStoreError.invalidPackage(
                    videoURL,
                    "video files do not match manifest.video_snippet"
                )
            }
            let videoFileURL = videoURL.appendingPathComponent("\(partName).mp4", isDirectory: false)
            let data: Data
            do {
                data = try Data(contentsOf: videoFileURL)
            } catch {
                throw EvidencePackageStoreError.invalidPackage(
                    videoFileURL,
                    error.localizedDescription
                )
            }
            guard data.count == videoManifest.byteLength,
                  evidencePackageSHA256Hex(data) == videoManifest.sha256 else {
                throw EvidencePackageStoreError.invalidPackage(
                    videoFileURL,
                    "video byte length or SHA-256 does not match the manifest"
                )
            }
            packagedVideo = PackagedEvidenceVideo(manifest: videoManifest, mp4Data: data)
        }

        do {
            return try EvidencePackage(
                manifest: manifest,
                frames: packagedFrames,
                videoSnippet: packagedVideo,
                repositoryMetadata: repositoryMetadata
            )
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
        let failedPackages = (try? entriesLocked(in: .failed).filter { isDirectory($0) }) ?? []
        let retryableFailureCount = failedPackages.reduce(into: 0) { count, url in
            guard let packageID = UUID(uuidString: url.lastPathComponent),
                  failureLocked(for: packageID)?.kind == .retryable else {
                return
            }
            count += 1
        }
        return EvidencePackageQueueDiagnostics(
            stagingCount: entryCountLocked(in: .staging),
            queuedCount: entryCountLocked(in: .queued),
            acknowledgedCount: entryCountLocked(in: .acknowledged),
            failedCount: failedPackages.count,
            corruptCount: entryCountLocked(in: .corrupt),
            retryableFailureCount: retryableFailureCount,
            permanentFailureCount: failedPackages.count - retryableFailureCount,
            queuedByteCount: directoryByteCountLocked(directoryURL(for: .queued)),
            queuedByteCapacity: queuedByteCapacity,
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
        ).filter { isDirectory($0) }.count) ?? 0
    }

    private func directoryByteCountLocked(_ directory: URL) -> Int {
        guard let enumerator = fileManager.enumerator(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else {
            return 0
        }
        return enumerator.reduce(into: 0) { total, item in
            guard let url = item as? URL,
                  (try? url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true,
                  let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize else {
                return
            }
            total += size
        }
    }

    private func failureMetadataURL(for packageID: UUID) -> URL {
        directoryURL(for: .failed)
            .appendingPathComponent("\(packageID.uuidString.lowercased()).failure.json")
    }

    private func acknowledgementMetadataURL(for packageID: UUID) -> URL {
        directoryURL(for: .acknowledged)
            .appendingPathComponent("\(packageID.uuidString.lowercased()).acknowledgement.json")
    }

    private func failureLocked(for packageID: UUID) -> EvidencePackageFailure? {
        let url = failureMetadataURL(for: packageID)
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(EvidencePackageFailure.self, from: data)
    }

    private func encodeFailure(_ failure: EvidencePackageFailure, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(failure).write(to: url, options: .atomic)
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
    case packageNotFound(URL)
    case invalidTransition(EvidencePackageQueueState, EvidencePackageQueueState)
    case writeFailed(URL, String)
    case invalidPackage(URL, String)
    case queuedByteCapacityExceeded(Int, Int)

    public var errorDescription: String? {
        switch self {
        case let .packageAlreadyExists(url):
            return "The evidence package already exists at \(url.path)."
        case let .packageNotFound(url):
            return "The evidence package was not found at \(url.path)."
        case let .invalidTransition(source, destination):
            return "The evidence package cannot move from \(source.rawValue) to \(destination.rawValue)."
        case let .writeFailed(url, message):
            return "The evidence package could not be written at \(url.path): \(message)"
        case let .invalidPackage(url, message):
            return "The evidence package at \(url.path) is invalid: \(message)"
        case let .queuedByteCapacityExceeded(required, capacity):
            return "The evidence queue needs \(required) bytes, above its \(capacity)-byte limit."
        }
    }
}
