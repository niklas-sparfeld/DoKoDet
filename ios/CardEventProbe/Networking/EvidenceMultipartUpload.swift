import Foundation
import CryptoKit
import os

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public let evidenceMultipartDefaultBoundary = "CardEventProbeEvidenceV2"

public enum EvidenceMultipartPreparationError: LocalizedError, Equatable {
    case invalidBoundary(String)
    case invalidBaseURL(URL)
    case missingFrame(String)
    case frameDataMismatch(String)
    case missingVideo(String)
    case videoDataMismatch(String)
    case bodyWriteFailed(URL, String)

    public var errorDescription: String? {
        switch self {
        case let .invalidBoundary(boundary):
            return "The multipart boundary is invalid: \(boundary)."
        case let .invalidBaseURL(url):
            return "The upload base URL is invalid: \(url.absoluteString)."
        case let .missingFrame(partName):
            return "The evidence package is missing frame \(partName)."
        case let .frameDataMismatch(partName):
            return "The evidence package data does not match frame \(partName)'s manifest."
        case let .missingVideo(partName):
            return "The evidence package is missing video \(partName)."
        case let .videoDataMismatch(partName):
            return "The evidence package data does not match video \(partName)'s manifest."
        case let .bodyWriteFailed(url, message):
            return "The multipart body could not be written at \(url.path): \(message)"
        }
    }
}

/// A request whose multipart body is stored in a file.
public struct PreparedEvidenceUpload {
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

/// Writes the V2 multipart envelope without constructing the complete body in memory.
public struct EvidenceMultipartRequestBuilder: Sendable {
    private enum FrameSource {
        case data(Data)
        case file(URL)
    }

    public let boundary: String
    public let bodyDirectory: URL

    public init(
        boundary: String = evidenceMultipartDefaultBoundary,
        bodyDirectory: URL = FileManager.default.temporaryDirectory
    ) throws {
        guard Self.isValidBoundary(boundary) else {
            throw EvidenceMultipartPreparationError.invalidBoundary(boundary)
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
        package: EvidencePackage,
        baseURL: URL
    ) throws -> PreparedEvidenceUpload {
        let framesByPart = Dictionary(uniqueKeysWithValues: package.frames.map { ($0.manifest.partName, $0) })
        let sources = Dictionary(uniqueKeysWithValues: package.manifest.frames.compactMap { frame -> (String, FrameSource)? in
            guard let packagedFrame = framesByPart[frame.partName] else { return nil }
            return (frame.partName, .data(packagedFrame.jpegData))
        })
        let videoSource = package.videoSnippet.map { FrameSource.data($0.mp4Data) }
        let repositoryMetadata = try package.repositoryMetadata
            ?? EvidencePackageRepositoryMetadata.standard(for: package.manifest)
        let repositoryMetadataData = try repositoryMetadata.encodedDocuments()
        return try prepare(
            manifest: package.manifest,
            manifestData: try package.manifest.encoded(),
            packageRecordData: repositoryMetadataData.packageRecord,
            taskEnrollmentData: repositoryMetadataData.taskEnrollment,
            lineageData: repositoryMetadataData.lineage,
            frameSources: sources,
            videoSource: videoSource,
            baseURL: baseURL
        )
    }

    public func prepare(
        package: EvidencePackage,
        configuration: BackendConfiguration
    ) throws -> PreparedEvidenceUpload {
        try prepare(package: package, baseURL: configuration.baseURL)
    }

    /// Prepares a request directly from a package written by `EvidencePackageStore`.
    /// The stored manifest bytes are sent without re-encoding them.
    public func prepare(
        packageAt packageURL: URL,
        baseURL: URL
    ) throws -> PreparedEvidenceUpload {
        let manifestURL = packageURL.appendingPathComponent("manifest.json")
        do {
            let manifestData = try Data(contentsOf: manifestURL)
            let manifest = try JSONDecoder().decode(EvidencePackageManifest.self, from: manifestData)
            let packageRecordData = try Data(
                contentsOf: packageURL.appendingPathComponent("package-record.json")
            )
            let taskEnrollmentData = try Data(
                contentsOf: packageURL.appendingPathComponent("initial-task-enrollment.json")
            )
            let lineageData = try Data(
                contentsOf: packageURL.appendingPathComponent("lineage.json")
            )
            let decoder = JSONDecoder()
            let metadata = try EvidencePackageRepositoryMetadata(
                packageRecord: try decoder.decode(
                    RepositoryEvidencePackageRecord.self,
                    from: packageRecordData
                ),
                taskEnrollment: try decoder.decode(
                    RepositoryTaskEnrollmentDocument.self,
                    from: taskEnrollmentData
                ),
                lineage: try decoder.decode(
                    RepositoryEvidencePackageLineage.self,
                    from: lineageData
                )
            )
            _ = metadata
            let frameSources = Dictionary(
                uniqueKeysWithValues: manifest.frames.map { frame in
                    (
                        frame.partName,
                        FrameSource.file(
                            packageURL
                                .appendingPathComponent("frames", isDirectory: true)
                                .appendingPathComponent("\(frame.partName).jpg")
                        )
                    )
                }
            )
            let videoSource: FrameSource?
            if let videoManifest = manifest.videoSnippet, videoManifest.captureComplete {
                guard let partName = videoManifest.partName else {
                    throw EvidenceMultipartPreparationError.missingVideo("unknown")
                }
                videoSource = .file(
                    packageURL
                        .appendingPathComponent("video", isDirectory: true)
                        .appendingPathComponent("\(partName).mp4", isDirectory: false)
                )
            } else {
                videoSource = nil
            }
            return try prepare(
                manifest: manifest,
                manifestData: manifestData,
                packageRecordData: packageRecordData,
                taskEnrollmentData: taskEnrollmentData,
                lineageData: lineageData,
                frameSources: frameSources,
                videoSource: videoSource,
                baseURL: baseURL
            )
        } catch let error as EvidenceMultipartPreparationError {
            throw error
        } catch {
            throw EvidenceMultipartPreparationError.bodyWriteFailed(
                manifestURL,
                error.localizedDescription
            )
        }
    }

    public func prepare(
        packageAt packageURL: URL,
        configuration: BackendConfiguration
    ) throws -> PreparedEvidenceUpload {
        try prepare(packageAt: packageURL, baseURL: configuration.baseURL)
    }

    private func prepare(
        manifest: EvidencePackageManifest,
        manifestData: Data,
        packageRecordData: Data,
        taskEnrollmentData: Data,
        lineageData: Data,
        frameSources: [String: FrameSource],
        videoSource: FrameSource?,
        baseURL: URL
    ) throws -> PreparedEvidenceUpload {
        guard let components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              components.scheme == "http" || components.scheme == "https",
              components.host != nil,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil else {
            throw EvidenceMultipartPreparationError.invalidBaseURL(baseURL)
        }

        let endpoint = baseURL
            .appendingPathComponent("v1", isDirectory: true)
            .appendingPathComponent("evidence-packages", isDirectory: true)
            .appendingPathComponent(manifest.packageID.uuidString.lowercased())
        let bodyURL = bodyDirectory.appendingPathComponent(
            "evidence-\(manifest.packageID.uuidString.lowercased())-\(UUID().uuidString).multipart"
        )

        do {
            try FileManager.default.createDirectory(
                at: bodyDirectory,
                withIntermediateDirectories: true
            )
            try writeBody(
                manifest: manifest,
                manifestData: manifestData,
                packageRecordData: packageRecordData,
                taskEnrollmentData: taskEnrollmentData,
                lineageData: lineageData,
                frameSources: frameSources,
                videoSource: videoSource,
                to: bodyURL
            )
            let contentLength = try fileSize(of: bodyURL)

            var request = URLRequest(url: endpoint)
            request.httpMethod = "PUT"
            request.setValue(
                "multipart/form-data; boundary=\(boundary)",
                forHTTPHeaderField: "Content-Type"
            )
            request.setValue(String(contentLength), forHTTPHeaderField: "Content-Length")
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            request.cachePolicy = URLRequest.CachePolicy.reloadIgnoringLocalCacheData
            return PreparedEvidenceUpload(
                request: request,
                bodyFileURL: bodyURL,
                contentLength: contentLength
            )
        } catch let error as EvidenceMultipartPreparationError {
            try? FileManager.default.removeItem(at: bodyURL)
            throw error
        } catch {
            try? FileManager.default.removeItem(at: bodyURL)
            throw EvidenceMultipartPreparationError.bodyWriteFailed(
                bodyURL,
                error.localizedDescription
            )
        }
    }

    private func writeBody(
        manifest: EvidencePackageManifest,
        manifestData: Data,
        packageRecordData: Data,
        taskEnrollmentData: Data,
        lineageData: Data,
        frameSources: [String: FrameSource],
        videoSource: FrameSource?,
        to bodyURL: URL
    ) throws {
        let fileManager = FileManager.default
        fileManager.createFile(atPath: bodyURL.path, contents: nil)
        let handle = try FileHandle(forWritingTo: bodyURL)
        var closed = false
        defer {
            if !closed {
                try? handle.close()
            }
        }

        try writeASCII("--\(boundary)\r\n", to: handle)
        try writeASCII(
            "Content-Disposition: form-data; name=\"manifest\"; filename=\"manifest.json\"\r\n",
            to: handle
        )
        try writeASCII("Content-Type: application/json\r\n\r\n", to: handle)
        try handle.write(contentsOf: manifestData)
        try writeASCII("\r\n", to: handle)

        try writeJSONPart(
            name: "package_record",
            filename: "package-record.json",
            data: packageRecordData,
            to: handle
        )
        try writeJSONPart(
            name: "task_enrollment",
            filename: "initial-task-enrollment.json",
            data: taskEnrollmentData,
            to: handle
        )
        try writeJSONPart(
            name: "lineage",
            filename: "lineage.json",
            data: lineageData,
            to: handle
        )

        for frameManifest in manifest.frames {
            guard let frameSource = frameSources[frameManifest.partName] else {
                throw EvidenceMultipartPreparationError.missingFrame(frameManifest.partName)
            }
            try writeASCII("--\(boundary)\r\n", to: handle)
            try writeASCII(
                "Content-Disposition: form-data; name=\"\(frameManifest.partName)\"; filename=\"\(frameManifest.partName).jpg\"\r\n",
                to: handle
            )
            try writeASCII("Content-Type: image/jpeg\r\n\r\n", to: handle)
            try writeFrame(
                frameSource,
                expected: frameManifest,
                to: handle
            )
            try writeASCII("\r\n", to: handle)
        }

        if let videoManifest = manifest.videoSnippet, videoManifest.captureComplete {
            guard let videoSource else {
                throw EvidenceMultipartPreparationError.missingVideo(videoManifest.partName ?? "unknown")
            }
            guard let partName = videoManifest.partName else {
                throw EvidenceMultipartPreparationError.missingVideo("unknown")
            }
            try writeASCII("--\(boundary)\r\n", to: handle)
            try writeASCII(
                "Content-Disposition: form-data; name=\"\(partName)\"; filename=\"\(partName).mp4\"\r\n",
                to: handle
            )
            try writeASCII("Content-Type: video/mp4\r\n\r\n", to: handle)
            try writeVideo(videoSource, expected: videoManifest, to: handle)
            try writeASCII("\r\n", to: handle)
        }

        try writeASCII("--\(boundary)--\r\n", to: handle)
        try handle.close()
        closed = true
    }

    private func writeJSONPart(
        name: String,
        filename: String,
        data: Data,
        to handle: FileHandle
    ) throws {
        try writeASCII("--\(boundary)\r\n", to: handle)
        try writeASCII(
            "Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n",
            to: handle
        )
        try writeASCII("Content-Type: application/json\r\n\r\n", to: handle)
        try handle.write(contentsOf: data)
        try writeASCII("\r\n", to: handle)
    }

    private func writeFrame(
        _ source: FrameSource,
        expected: EvidenceFrameManifest,
        to output: FileHandle
    ) throws {
        switch source {
        case let .data(data):
            guard data.count == expected.byteLength,
                  sha256Hex(data) == expected.sha256 else {
                throw EvidenceMultipartPreparationError.frameDataMismatch(expected.partName)
            }
            try output.write(contentsOf: data)
        case let .file(url):
            let input: FileHandle
            do {
                input = try FileHandle(forReadingFrom: url)
            } catch {
                throw EvidenceMultipartPreparationError.frameDataMismatch(expected.partName)
            }
            defer { try? input.close() }

            var hasher = SHA256()
            var byteLength = 0
            while let chunk = try input.read(upToCount: 64 * 1024), !chunk.isEmpty {
                byteLength += chunk.count
                hasher.update(data: chunk)
                try output.write(contentsOf: chunk)
            }
            let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
            guard byteLength == expected.byteLength, digest == expected.sha256 else {
                throw EvidenceMultipartPreparationError.frameDataMismatch(expected.partName)
            }
        }
    }

    private func writeVideo(
        _ source: FrameSource,
        expected: EvidenceVideoSnippetManifest,
        to output: FileHandle
    ) throws {
        switch source {
        case let .data(data):
            guard data.count == expected.byteLength,
                  sha256Hex(data) == expected.sha256 else {
                throw EvidenceMultipartPreparationError.videoDataMismatch(expected.partName ?? "unknown")
            }
            try output.write(contentsOf: data)
        case let .file(url):
            let input: FileHandle
            do {
                input = try FileHandle(forReadingFrom: url)
            } catch {
                throw EvidenceMultipartPreparationError.videoDataMismatch(expected.partName ?? "unknown")
            }
            defer { try? input.close() }

            var hasher = SHA256()
            var byteLength = 0
            while let chunk = try input.read(upToCount: 64 * 1024), !chunk.isEmpty {
                byteLength += chunk.count
                hasher.update(data: chunk)
                try output.write(contentsOf: chunk)
            }
            let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
            guard byteLength == expected.byteLength, digest == expected.sha256 else {
                throw EvidenceMultipartPreparationError.videoDataMismatch(expected.partName ?? "unknown")
            }
        }
    }

    private func writeASCII(_ value: String, to handle: FileHandle) throws {
        guard let data = value.data(using: .ascii) else {
            throw EvidenceMultipartPreparationError.invalidBoundary(boundary)
        }
        try handle.write(contentsOf: data)
    }

    private func fileSize(of url: URL) throws -> Int64 {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let fileSize = values.fileSize else {
            throw EvidenceMultipartPreparationError.bodyWriteFailed(
                url,
                "the body file has no size"
            )
        }
        return Int64(fileSize)
    }
}

private func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

public struct EvidenceUploadResponse: Codable, Equatable, Sendable {
    public let packageID: UUID
    public let state: String
    public let created: Bool
    public let receivedAt: Date

    public init(packageID: UUID, state: String, created: Bool, receivedAt: Date) {
        self.packageID = packageID
        self.state = state
        self.created = created
        self.receivedAt = receivedAt
    }

    private enum CodingKeys: String, CodingKey {
        case packageID = "package_id"
        case state
        case created
        case receivedAt = "received_at"
    }
}

public enum EvidenceUploadError: LocalizedError, Equatable, Sendable {
    case nonSuccessResponse(Int, Data)
    case packageIDMismatch(expected: UUID, received: UUID)
    case invalidResponse
    case invalidResponseBody(String)

    public var errorDescription: String? {
        switch self {
        case let .nonSuccessResponse(status, data):
            if let summary = Self.serverErrorSummary(data) {
                return "The evidence upload failed with HTTP status \(status): \(summary)"
            }
            return "The evidence upload failed with HTTP status \(status)."
        case let .packageIDMismatch(expected, received):
            return "The evidence upload acknowledged package \(received), expected \(expected)."
        case .invalidResponse:
            return "The evidence upload returned an invalid response."
        case let .invalidResponseBody(message):
            return "The evidence upload returned an invalid response: \(message)"
        }
    }

    public var failureKind: EvidencePackageFailureKind {
        switch self {
        case let .nonSuccessResponse(status, _):
            return EvidenceUploadClient.failureKind(forHTTPStatus: status)
        case .packageIDMismatch, .invalidResponse, .invalidResponseBody:
            return .permanent
        }
    }

    public var statusCode: Int? {
        guard case let .nonSuccessResponse(status, _) = self else { return nil }
        return status
    }

    private struct ServerErrorResponse: Decodable {
        let error: ServerError
    }

    private struct ServerError: Decodable {
        let code: String?
        let message: String?
        let details: [ServerErrorDetail]?
    }

    private struct ServerErrorDetail: Decodable {
        let field: String
        let message: String
    }

    private static func serverErrorSummary(_ data: Data) -> String? {
        guard let response = try? JSONDecoder().decode(ServerErrorResponse.self, from: data) else {
            return nil
        }
        let codeAndMessage = [response.error.code, response.error.message]
            .compactMap { $0 }
            .joined(separator: ": ")
        guard !codeAndMessage.isEmpty else { return nil }
        let details = response.error.details ?? []
        guard !details.isEmpty else { return codeAndMessage }
        let detailText = details.map { "\($0.field): \($0.message)" }.joined(separator: "; ")
        return "\(codeAndMessage) [\(detailText)]"
    }
}

/// Sends one prepared package with a foreground URLSession upload task.
public final class EvidenceUploadClient: @unchecked Sendable {
    private static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.dokodetector.CardEventProbe",
        category: "EvidenceUpload"
    )
    private static let uploadIDHeader = "X-DokoDetector-Upload-ID"
    private static let maxLoggedResponseCharacters = 4096

    private let session: URLSession
    private let builder: EvidenceMultipartRequestBuilder

    public init(
        session: URLSession? = nil,
        boundary: String = evidenceMultipartDefaultBoundary,
        bodyDirectory: URL = FileManager.default.temporaryDirectory
    ) throws {
        self.session = session ?? Self.makeSession()
        builder = try EvidenceMultipartRequestBuilder(
            boundary: boundary,
            bodyDirectory: bodyDirectory
        )
    }

    public func prepare(
        package: EvidencePackage,
        baseURL: URL
    ) throws -> PreparedEvidenceUpload {
        try builder.prepare(package: package, baseURL: baseURL)
    }

    public func prepare(
        package: EvidencePackage,
        configuration: BackendConfiguration
    ) throws -> PreparedEvidenceUpload {
        try builder.prepare(package: package, configuration: configuration)
    }

    public func prepare(
        packageAt packageURL: URL,
        baseURL: URL
    ) throws -> PreparedEvidenceUpload {
        try builder.prepare(packageAt: packageURL, baseURL: baseURL)
    }

    public func prepare(
        packageAt packageURL: URL,
        configuration: BackendConfiguration
    ) throws -> PreparedEvidenceUpload {
        try builder.prepare(packageAt: packageURL, configuration: configuration)
    }

    public func upload(
        package: EvidencePackage,
        to baseURL: URL
    ) async throws -> EvidenceUploadResponse {
        let prepared = try prepare(package: package, baseURL: baseURL)
        defer { prepared.removeBodyFile() }
        return try await performUpload(
            prepared: prepared,
            expectedPackageID: package.manifest.packageID,
            source: "in-memory-package"
        )
    }

    public func upload(
        package: EvidencePackage,
        using configuration: BackendConfiguration
    ) async throws -> EvidenceUploadResponse {
        let prepared = try prepare(package: package, configuration: configuration)
        defer { prepared.removeBodyFile() }
        return try await performUpload(
            prepared: prepared,
            expectedPackageID: package.manifest.packageID,
            source: "in-memory-package"
        )
    }

    public func upload(
        packageAt packageURL: URL,
        to baseURL: URL
    ) async throws -> EvidenceUploadResponse {
        let packageID = try Self.packageID(from: packageURL)
        let prepared = try prepare(packageAt: packageURL, baseURL: baseURL)
        defer { prepared.removeBodyFile() }
        return try await performUpload(
            prepared: prepared,
            expectedPackageID: packageID,
            source: "stored-package"
        )
    }

    public func upload(
        packageAt packageURL: URL,
        using configuration: BackendConfiguration
    ) async throws -> EvidenceUploadResponse {
        let packageID = try Self.packageID(from: packageURL)
        let prepared = try prepare(packageAt: packageURL, configuration: configuration)
        defer { prepared.removeBodyFile() }
        return try await performUpload(
            prepared: prepared,
            expectedPackageID: packageID,
            source: "stored-package"
        )
    }

    private func performUpload(
        prepared: PreparedEvidenceUpload,
        expectedPackageID: UUID,
        source: String
    ) async throws -> EvidenceUploadResponse {
        let uploadID = UUID().uuidString.lowercased()
        var request = prepared.request
        request.setValue(uploadID, forHTTPHeaderField: Self.uploadIDHeader)
        Self.logger.info(
            "evidence_upload_started upload_id=\(uploadID, privacy: .public) package_id=\(expectedPackageID.uuidString.lowercased(), privacy: .public)"
        )
        Self.logger.info(
            "evidence_upload_request source=\(source, privacy: .public) url=\(request.url?.absoluteString ?? "-", privacy: .public) content_length=\(prepared.contentLength, privacy: .public)"
        )

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.upload(
                for: request,
                fromFile: prepared.bodyFileURL
            )
        } catch {
            Self.logger.error(
                "evidence_upload_transport_failed upload_id=\(uploadID, privacy: .public) package_id=\(expectedPackageID.uuidString.lowercased(), privacy: .public)"
            )
            Self.logger.error(
                "evidence_upload_transport_error upload_id=\(uploadID, privacy: .public) error=\(error.localizedDescription, privacy: .public)"
            )
            throw error
        }

        guard let response = response as? HTTPURLResponse else {
            Self.logger.error(
                "evidence_upload_invalid_response upload_id=\(uploadID, privacy: .public) package_id=\(expectedPackageID.uuidString.lowercased(), privacy: .public)"
            )
            Self.logger.error(
                "evidence_upload_response_type upload_id=\(uploadID, privacy: .public) response_type=\(String(describing: type(of: response)), privacy: .public)"
            )
            throw EvidenceUploadError.invalidResponse
        }
        guard response.statusCode == 200 || response.statusCode == 201 else {
            let responseBody = Self.responseBodyForLogging(data)
            Self.logger.error(
                "evidence_upload_rejected upload_id=\(uploadID, privacy: .public) package_id=\(expectedPackageID.uuidString.lowercased(), privacy: .public) status_code=\(response.statusCode, privacy: .public)"
            )
            Self.logger.error(
                "evidence_upload_response_body upload_id=\(uploadID, privacy: .public) response_body=\(responseBody, privacy: .public)"
            )
            throw EvidenceUploadError.nonSuccessResponse(response.statusCode, data)
        }

        do {
            let decoded = try Self.decodeResponse(data, expectedPackageID: expectedPackageID)
            Self.logger.info(
                "evidence_upload_acknowledged upload_id=\(uploadID, privacy: .public) package_id=\(expectedPackageID.uuidString.lowercased(), privacy: .public) status_code=\(response.statusCode, privacy: .public)"
            )
            Self.logger.info(
                "evidence_upload_result upload_id=\(uploadID, privacy: .public) created=\(decoded.created, privacy: .public)"
            )
            return decoded
        } catch {
            Self.logger.error(
                "evidence_upload_invalid_success_body upload_id=\(uploadID, privacy: .public) package_id=\(expectedPackageID.uuidString.lowercased(), privacy: .public) status_code=\(response.statusCode, privacy: .public)"
            )
            Self.logger.error(
                "evidence_upload_success_body_error upload_id=\(uploadID, privacy: .public) response_body=\(Self.responseBodyForLogging(data), privacy: .public) error=\(error.localizedDescription, privacy: .public)"
            )
            throw error
        }
    }

    public static func failureKind(for error: Error) -> EvidencePackageFailureKind {
        if let uploadError = error as? EvidenceUploadError {
            return uploadError.failureKind
        }
        if error is EvidenceMultipartPreparationError || error is EvidencePackageStoreError {
            return .permanent
        }
        return .retryable
    }

    public static func statusCode(for error: Error) -> Int? {
        (error as? EvidenceUploadError)?.statusCode
    }

    fileprivate static func failureKind(forHTTPStatus status: Int) -> EvidencePackageFailureKind {
        switch status {
        case 408, 429, 500...599:
            return .retryable
        default:
            return .permanent
        }
    }

    private static func packageID(from packageURL: URL) throws -> UUID {
        guard let packageID = UUID(uuidString: packageURL.lastPathComponent) else {
            throw EvidenceUploadError.invalidResponseBody(
                "the package directory name is not a UUID"
            )
        }
        return packageID
    }

    private static func decodeResponse(
        _ data: Data,
        expectedPackageID: UUID
    ) throws -> EvidenceUploadResponse {
        let response: EvidenceUploadResponse
        do {
            response = try decoder.decode(EvidenceUploadResponse.self, from: data)
        } catch {
            throw EvidenceUploadError.invalidResponseBody(error.localizedDescription)
        }
        guard response.packageID == expectedPackageID else {
            throw EvidenceUploadError.packageIDMismatch(
                expected: expectedPackageID,
                received: response.packageID
            )
        }
        return response
    }

    private static func responseBodyForLogging(_ data: Data) -> String {
        guard !data.isEmpty else { return "<empty>" }
        let text = String(data: data, encoding: .utf8)
            ?? "<non-UTF8 response (\(data.count) bytes)>"
        let singleLine = text
            .replacingOccurrences(of: "\r", with: "\\r")
            .replacingOccurrences(of: "\n", with: "\\n")
        if singleLine.count <= maxLoggedResponseCharacters {
            return singleLine
        }
        return String(singleLine.prefix(maxLoggedResponseCharacters)) + "…<truncated>"
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

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForResource = 30
        return URLSession(configuration: configuration)
    }
}
