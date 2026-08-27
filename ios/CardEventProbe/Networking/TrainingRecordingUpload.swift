import CryptoKit
import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public let trainingRecordingMultipartDefaultBoundary = "CardEventProbeTrainingRecordingV1"

public enum TrainingRecordingMultipartPreparationError: LocalizedError, Equatable {
    case invalidBoundary(String)
    case invalidBaseURL(URL)
    case invalidBundle(URL, String)
    case bodyWriteFailed(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .invalidBoundary(boundary):
            return "The training recording multipart boundary is invalid: \(boundary)."
        case let .invalidBaseURL(url):
            return "The training recording upload URL is invalid: \(url.absoluteString)."
        case let .invalidBundle(url, message):
            return "The training recording at \(url.path) cannot be uploaded: \(message)."
        case let .bodyWriteFailed(url, message):
            return "The training recording multipart body could not be written at \(url.path): \(message)"
        }
    }
}

public struct PreparedTrainingRecordingUpload: Sendable {
    public let request: URLRequest
    public let bodyFileURL: URL
    public let contentLength: Int64

    public init(request: URLRequest, bodyFileURL: URL, contentLength: Int64) {
        self.request = request
        self.bodyFileURL = bodyFileURL
        self.contentLength = contentLength
    }

    public func removeBodyFile() {
        try? FileManager.default.removeItem(at: bodyFileURL)
    }
}

/// Builds the file-backed multipart request for one immutable recording bundle.
public struct TrainingRecordingMultipartRequestBuilder: Sendable {
    public let boundary: String
    public let bodyDirectory: URL

    public init(
        boundary: String = trainingRecordingMultipartDefaultBoundary,
        bodyDirectory: URL = FileManager.default.temporaryDirectory
    ) throws {
        guard Self.isValidBoundary(boundary) else {
            throw TrainingRecordingMultipartPreparationError.invalidBoundary(boundary)
        }
        self.boundary = boundary
        self.bodyDirectory = bodyDirectory
    }

    public static func isValidBoundary(_ boundary: String) -> Bool {
        let bytes = Array(boundary.utf8)
        guard !bytes.isEmpty, bytes.count <= 70 else { return false }
        return bytes.allSatisfy { byte in
            (0x30...0x39).contains(byte)
                || (0x41...0x5A).contains(byte)
                || (0x61...0x7A).contains(byte)
                || [0x27, 0x28, 0x29, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x3A, 0x3D, 0x3F].contains(byte)
        }
    }

    public func prepare(
        recordingAt recordingURL: URL,
        baseURL: URL
    ) throws -> PreparedTrainingRecordingUpload {
        guard let components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              components.scheme == "http" || components.scheme == "https",
              components.host != nil,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil else {
            throw TrainingRecordingMultipartPreparationError.invalidBaseURL(baseURL)
        }

        let manifestURL = recordingURL.appendingPathComponent("manifest.json")
        let manifestData: Data
        let manifest: TrainingRecordingManifest
        do {
            manifestData = try Data(contentsOf: manifestURL)
            manifest = try JSONDecoder().decode(TrainingRecordingManifest.self, from: manifestData)
        } catch {
            throw TrainingRecordingMultipartPreparationError.invalidBundle(
                recordingURL,
                error.localizedDescription
            )
        }
        guard recordingURL.lastPathComponent == manifest.recordingID else {
            throw TrainingRecordingMultipartPreparationError.invalidBundle(
                recordingURL,
                "directory name does not match manifest.recording_id"
            )
        }

        let videoURL = recordingURL.appendingPathComponent(manifest.video.name)
        let predictionsURL = recordingURL.appendingPathComponent(manifest.predictions.name)
        let bundleEntries = (try? FileManager.default.contentsOfDirectory(
            at: recordingURL,
            includingPropertiesForKeys: [.isDirectoryKey, .isRegularFileKey],
            options: []
        )) ?? []
        guard Set(bundleEntries.map(\.lastPathComponent)) == Set([
            "manifest.json",
            manifest.video.name,
            manifest.predictions.name,
        ]) else {
            throw TrainingRecordingMultipartPreparationError.invalidBundle(
                recordingURL,
                "bundle contains an unexpected top-level entry"
            )
        }
        let predictionsData: Data
        do {
            predictionsData = try Data(contentsOf: predictionsURL)
            _ = try validateTrainingRecordingBundle(
                manifestData: manifestData,
                predictionsData: predictionsData,
                videoURL: videoURL
            )
        } catch {
            throw TrainingRecordingMultipartPreparationError.invalidBundle(
                recordingURL,
                error.localizedDescription
            )
        }

        let bodyURL = bodyDirectory.appendingPathComponent(
            "training-recording-\(manifest.recordingID)-\(UUID().uuidString.lowercased()).multipart"
        )
        do {
            try FileManager.default.createDirectory(
                at: bodyDirectory,
                withIntermediateDirectories: true
            )
            try writeBody(
                manifestData: manifestData,
                videoURL: videoURL,
                predictionsURL: predictionsURL,
                to: bodyURL
            )
            let contentLength = try fileSize(of: bodyURL)
            var request = URLRequest(
                url: baseURL
                    .appendingPathComponent("v1", isDirectory: true)
                    .appendingPathComponent("training-recordings", isDirectory: true)
                    .appendingPathComponent(manifest.recordingID)
            )
            request.httpMethod = "PUT"
            request.setValue(
                "multipart/form-data; boundary=\(boundary)",
                forHTTPHeaderField: "Content-Type"
            )
            request.setValue(String(contentLength), forHTTPHeaderField: "Content-Length")
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            request.cachePolicy = .reloadIgnoringLocalCacheData
            return PreparedTrainingRecordingUpload(
                request: request,
                bodyFileURL: bodyURL,
                contentLength: contentLength
            )
        } catch let error as TrainingRecordingMultipartPreparationError {
            try? FileManager.default.removeItem(at: bodyURL)
            throw error
        } catch {
            try? FileManager.default.removeItem(at: bodyURL)
            throw TrainingRecordingMultipartPreparationError.bodyWriteFailed(
                bodyURL,
                error.localizedDescription
            )
        }
    }

    private func writeBody(
        manifestData: Data,
        videoURL: URL,
        predictionsURL: URL,
        to bodyURL: URL
    ) throws {
        FileManager.default.createFile(atPath: bodyURL.path, contents: nil)
        let handle = try FileHandle(forWritingTo: bodyURL)
        var closed = false
        defer {
            if !closed { try? handle.close() }
        }

        try writeASCII("--\(boundary)\r\n", to: handle)
        try writeASCII(
            "Content-Disposition: form-data; name=\"manifest\"; filename=\"manifest.json\"\r\n",
            to: handle
        )
        try writeASCII("Content-Type: application/json\r\n\r\n", to: handle)
        try handle.write(contentsOf: manifestData)
        try writeASCII("\r\n", to: handle)

        try writeASCII("--\(boundary)\r\n", to: handle)
        try writeASCII(
            "Content-Disposition: form-data; name=\"video\"; filename=\"\(videoURL.lastPathComponent)\"\r\n",
            to: handle
        )
        try writeASCII("Content-Type: video/quicktime\r\n\r\n", to: handle)
        try copyFile(videoURL, to: handle)
        try writeASCII("\r\n", to: handle)

        try writeASCII("--\(boundary)\r\n", to: handle)
        try writeASCII(
            "Content-Disposition: form-data; name=\"predictions\"; filename=\"\(predictionsURL.lastPathComponent)\"\r\n",
            to: handle
        )
        try writeASCII("Content-Type: application/json\r\n\r\n", to: handle)
        try copyFile(predictionsURL, to: handle)
        try writeASCII("\r\n", to: handle)

        try writeASCII("--\(boundary)--\r\n", to: handle)
        try handle.close()
        closed = true
    }

    private func copyFile(_ url: URL, to output: FileHandle) throws {
        let input: FileHandle
        do {
            input = try FileHandle(forReadingFrom: url)
        } catch {
            throw TrainingRecordingMultipartPreparationError.bodyWriteFailed(
                url,
                error.localizedDescription
            )
        }
        defer { try? input.close() }
        while let chunk = try input.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            try output.write(contentsOf: chunk)
        }
    }

    private func writeASCII(_ value: String, to handle: FileHandle) throws {
        guard let data = value.data(using: .ascii) else {
            throw TrainingRecordingMultipartPreparationError.invalidBoundary(boundary)
        }
        try handle.write(contentsOf: data)
    }

    private func fileSize(of url: URL) throws -> Int64 {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let size = values.fileSize else {
            throw TrainingRecordingMultipartPreparationError.bodyWriteFailed(
                url,
                "the body file has no size"
            )
        }
        return Int64(size)
    }
}

public struct TrainingRecordingUploadResponse: Codable, Equatable, Sendable {
    public let recordingID: String
    public let state: String
    public let created: Bool
    public let receivedAt: Date

    public init(recordingID: String, state: String, created: Bool, receivedAt: Date) {
        self.recordingID = recordingID
        self.state = state
        self.created = created
        self.receivedAt = receivedAt
    }

    private enum CodingKeys: String, CodingKey {
        case recordingID = "recording_id"
        case state
        case created
        case receivedAt = "received_at"
    }
}

public enum TrainingRecordingUploadError: LocalizedError, Sendable {
    case nonSuccessResponse(Int, Data)
    case recordingIDMismatch(expected: String, received: String)
    case invalidResponse
    case invalidResponseBody(String)

    public var errorDescription: String? {
        switch self {
        case let .nonSuccessResponse(status, _):
            return "The training recording upload failed with HTTP status \(status)."
        case let .recordingIDMismatch(expected, received):
            return "The training recording upload acknowledged \(received), expected \(expected)."
        case .invalidResponse:
            return "The training recording upload returned an invalid response."
        case let .invalidResponseBody(message):
            return "The training recording upload returned an invalid response: \(message)"
        }
    }

    public var failureKind: TrainingRecordingFailureKind {
        switch self {
        case let .nonSuccessResponse(status, _):
            return Self.failureKind(forHTTPStatus: status)
        case .recordingIDMismatch, .invalidResponse, .invalidResponseBody:
            return .permanent
        }
    }

    public var statusCode: Int? {
        guard case let .nonSuccessResponse(status, _) = self else { return nil }
        return status
    }

    fileprivate static func failureKind(forHTTPStatus status: Int) -> TrainingRecordingFailureKind {
        switch status {
        case 408, 429, 500...599:
            return .retryable
        default:
            return .permanent
        }
    }
}

/// Sends one recording with a foreground, file-backed URLSession upload task.
public final class TrainingRecordingUploadClient: @unchecked Sendable {
    private let session: URLSession
    private let builder: TrainingRecordingMultipartRequestBuilder

    public init(
        session: URLSession? = nil,
        boundary: String = trainingRecordingMultipartDefaultBoundary,
        bodyDirectory: URL = FileManager.default.temporaryDirectory
    ) throws {
        self.session = session ?? Self.makeSession()
        builder = try TrainingRecordingMultipartRequestBuilder(
            boundary: boundary,
            bodyDirectory: bodyDirectory
        )
    }

    public func prepare(
        recordingAt recordingURL: URL,
        baseURL: URL
    ) throws -> PreparedTrainingRecordingUpload {
        try builder.prepare(recordingAt: recordingURL, baseURL: baseURL)
    }

    public func upload(
        recordingAt recordingURL: URL,
        using configuration: BackendConfiguration
    ) async throws -> TrainingRecordingUploadResponse {
        let prepared = try prepare(recordingAt: recordingURL, baseURL: configuration.baseURL)
        defer { prepared.removeBodyFile() }
        let (data, response) = try await session.upload(
            for: prepared.request,
            fromFile: prepared.bodyFileURL
        )
        guard let response = response as? HTTPURLResponse else {
            throw TrainingRecordingUploadError.invalidResponse
        }
        guard response.statusCode == 200 || response.statusCode == 201 else {
            throw TrainingRecordingUploadError.nonSuccessResponse(response.statusCode, data)
        }
        let expectedID = recordingURL.lastPathComponent
        let decoded: TrainingRecordingUploadResponse
        do {
            decoded = try Self.decoder.decode(TrainingRecordingUploadResponse.self, from: data)
        } catch {
            throw TrainingRecordingUploadError.invalidResponseBody(error.localizedDescription)
        }
        guard decoded.recordingID == expectedID else {
            throw TrainingRecordingUploadError.recordingIDMismatch(
                expected: expectedID,
                received: decoded.recordingID
            )
        }
        return decoded
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            let formatter = ISO8601DateFormatter()
            formatter.timeZone = TimeZone(secondsFromGMT: 0)
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: value) {
                return date
            }
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: value) else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "received_at must be an RFC 3339 timestamp."
                )
            }
            return date
        }
        return decoder
    }()

    public static func failureKind(for error: Error) -> TrainingRecordingFailureKind {
        if let uploadError = error as? TrainingRecordingUploadError {
            return uploadError.failureKind
        }
        if error is TrainingRecordingMultipartPreparationError
            || error is TrainingRecordingStoreError
            || error is TrainingRecordingContractError {
            return .permanent
        }
        return .retryable
    }

    public static func statusCode(for error: Error) -> Int? {
        (error as? TrainingRecordingUploadError)?.statusCode
    }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.default
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 120
        return URLSession(configuration: configuration)
    }
}

public enum TrainingRecordingUploadDisposition: String, Codable, Sendable {
    case acknowledged
    case retryableFailure
    case permanentFailure
}

public struct TrainingRecordingUploadAttempt: Equatable, Sendable {
    public let recordingID: String
    public let disposition: TrainingRecordingUploadDisposition
    public let response: TrainingRecordingUploadResponse?
    public let failure: TrainingRecordingFailure?

    public init(
        recordingID: String,
        disposition: TrainingRecordingUploadDisposition,
        response: TrainingRecordingUploadResponse? = nil,
        failure: TrainingRecordingFailure? = nil
    ) {
        self.recordingID = recordingID
        self.disposition = disposition
        self.response = response
        self.failure = failure
    }
}

/// Owns durable recording state transitions for foreground uploads.
public actor TrainingRecordingUploadQueue {
    private let store: TrainingRecordingStore
    private let client: TrainingRecordingUploadClient
    private var isRunning = false

    public init(store: TrainingRecordingStore, client: TrainingRecordingUploadClient) {
        self.store = store
        self.client = client
    }

    public func uploadQueued(
        using configuration: BackendConfiguration
    ) async -> [TrainingRecordingUploadAttempt] {
        guard !isRunning else { return [] }
        isRunning = true
        defer { isRunning = false }
        _ = try? store.recover()
        guard let recordingURLs = try? store.recordingURLs(in: .queued) else { return [] }
        return await upload(recordingURLs, using: configuration)
    }

    public func retryFailed(
        using configuration: BackendConfiguration
    ) async -> [TrainingRecordingUploadAttempt] {
        guard !isRunning else { return [] }
        isRunning = true
        defer { isRunning = false }
        do {
            for recordingURL in try store.retryableFailedRecordingURLs() {
                _ = try store.requeueFailedRecording(for: recordingURL.lastPathComponent)
            }
        } catch {
            return []
        }
        guard let recordingURLs = try? store.recordingURLs(in: .queued) else { return [] }
        return await upload(recordingURLs, using: configuration)
    }

    private func upload(
        _ recordingURLs: [URL],
        using configuration: BackendConfiguration
    ) async -> [TrainingRecordingUploadAttempt] {
        var attempts: [TrainingRecordingUploadAttempt] = []
        attempts.reserveCapacity(recordingURLs.count)

        for recordingURL in recordingURLs {
            let recordingID = recordingURL.lastPathComponent
            do {
                let response = try await client.upload(
                    recordingAt: recordingURL,
                    using: configuration
                )
                let encoder = JSONEncoder()
                encoder.dateEncodingStrategy = .iso8601
                _ = try store.moveRecording(
                    for: recordingID,
                    from: .queued,
                    to: .acknowledged,
                    acknowledgementData: try encoder.encode(response)
                )
                attempts.append(
                    TrainingRecordingUploadAttempt(
                        recordingID: recordingID,
                        disposition: .acknowledged,
                        response: response
                    )
                )
            } catch {
                let kind = TrainingRecordingUploadClient.failureKind(for: error)
                let failure = TrainingRecordingFailure(
                    kind: kind,
                    statusCode: TrainingRecordingUploadClient.statusCode(for: error),
                    message: error.localizedDescription
                )
                do {
                    _ = try store.moveRecording(
                        for: recordingID,
                        from: .queued,
                        to: .failed,
                        failure: failure
                    )
                } catch {
                    attempts.append(
                        TrainingRecordingUploadAttempt(
                            recordingID: recordingID,
                            disposition: kind == .retryable ? .retryableFailure : .permanentFailure,
                            failure: TrainingRecordingFailure(
                                kind: kind,
                                statusCode: TrainingRecordingUploadClient.statusCode(for: error),
                                message: "The recording state could not be updated: (error.localizedDescription)"
                            )
                        )
                    )
                    continue
                }
                attempts.append(
                    TrainingRecordingUploadAttempt(
                        recordingID: recordingID,
                        disposition: kind == .retryable ? .retryableFailure : .permanentFailure,
                        failure: failure
                    )
                )
            }
        }
        return attempts
    }
}
