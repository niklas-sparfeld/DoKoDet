import Foundation

public enum EvidenceUploadDisposition: String, Codable, Sendable {
    case acknowledged
    case retryableFailure
    case permanentFailure
}

public struct EvidenceUploadAttempt: Equatable, Sendable {
    public let packageID: UUID
    public let disposition: EvidenceUploadDisposition
    public let response: EvidenceUploadResponse?
    public let failure: EvidencePackageFailure?

    public init(
        packageID: UUID,
        disposition: EvidenceUploadDisposition,
        response: EvidenceUploadResponse? = nil,
        failure: EvidencePackageFailure? = nil
    ) {
        self.packageID = packageID
        self.disposition = disposition
        self.response = response
        self.failure = failure
    }
}

/// Owns package state transitions for foreground uploads.
public actor EvidenceUploadQueue {
    private let store: EvidencePackageStore
    private let client: EvidenceUploadClient
    private var isRunning = false

    public init(
        store: EvidencePackageStore,
        client: EvidenceUploadClient
    ) {
        self.store = store
        self.client = client
    }

    public func uploadQueued(
        using configuration: BackendConfiguration
    ) async -> [EvidenceUploadAttempt] {
        guard !isRunning else { return [] }
        isRunning = true
        defer { isRunning = false }

        _ = try? store.recover()
        guard let packageURLs = try? store.packageURLs(in: .queued) else { return [] }
        return await upload(packageURLs, using: configuration)
    }

    public func retryFailed(
        using configuration: BackendConfiguration
    ) async -> [EvidenceUploadAttempt] {
        guard !isRunning else { return [] }
        isRunning = true
        defer { isRunning = false }

        do {
            for packageURL in try store.retryableFailedPackageURLs() {
                guard let packageID = UUID(uuidString: packageURL.lastPathComponent) else { continue }
                _ = try store.requeueFailedPackage(for: packageID)
            }
        } catch {
            return []
        }

        guard let packageURLs = try? store.packageURLs(in: .queued) else { return [] }
        return await upload(packageURLs, using: configuration)
    }

    private func upload(
        _ packageURLs: [URL],
        using configuration: BackendConfiguration
    ) async -> [EvidenceUploadAttempt] {
        var attempts: [EvidenceUploadAttempt] = []
        attempts.reserveCapacity(packageURLs.count)

        for packageURL in packageURLs {
            guard let packageID = UUID(uuidString: packageURL.lastPathComponent) else { continue }
            do {
                let response = try await client.upload(
                    packageAt: packageURL,
                    using: configuration
                )
                _ = try store.movePackage(
                    for: packageID,
                    from: .queued,
                    to: .acknowledged,
                    acknowledgementData: try Self.encode(response)
                )
                attempts.append(
                    EvidenceUploadAttempt(
                        packageID: packageID,
                        disposition: .acknowledged,
                        response: response
                    )
                )
            } catch {
                let uploadError = error
                let kind = EvidenceUploadClient.failureKind(for: uploadError)
                let failure = EvidencePackageFailure(
                    kind: kind,
                    statusCode: EvidenceUploadClient.statusCode(for: uploadError),
                    message: uploadError.localizedDescription
                )
                do {
                    _ = try store.movePackage(
                        for: packageID,
                        from: .queued,
                        to: .failed,
                        failure: failure
                    )
                } catch {
                    attempts.append(
                        EvidenceUploadAttempt(
                            packageID: packageID,
                            disposition: kind == .retryable ? .retryableFailure : .permanentFailure,
                            failure: EvidencePackageFailure(
                                kind: kind,
                                statusCode: EvidenceUploadClient.statusCode(for: uploadError),
                                message: "The package state could not be updated: \(error.localizedDescription)"
                            )
                        )
                    )
                    continue
                }
                attempts.append(
                    EvidenceUploadAttempt(
                        packageID: packageID,
                        disposition: kind == .retryable ? .retryableFailure : .permanentFailure,
                        failure: failure
                    )
                )
            }
        }
        return attempts
    }

    private static func encode(_ response: EvidenceUploadResponse) throws -> Data {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return try encoder.encode(response)
    }
}
