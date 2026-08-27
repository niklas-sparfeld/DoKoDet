import CoreMedia
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import CryptoKit
import XCTest
@testable import CardEventProbeCore

final class EvidenceUploadQueueTests: XCTestCase {
    func testBackendConfigurationProtectsHTTPFromPublicHosts() throws {
        let local = try BackendConfiguration.simulatorLocalhost()
        XCTAssertEqual(local.baseURL.absoluteString, "http://127.0.0.1:8000")
        XCTAssertNoThrow(try BackendConfiguration(baseURL: URL(string: "http://backend.local:8000")!))
        XCTAssertNoThrow(try BackendConfiguration(baseURL: URL(string: "https://example.com:8000")!))
        XCTAssertThrowsError(try BackendConfiguration(baseURL: URL(string: "http://example.com:8000")!))
        XCTAssertThrowsError(try BackendConfiguration(baseURL: URL(string: "http://user:pass@backend.local:8000")!))
    }

    func testUploadQueueAcknowledgesA201AndStoresBackendReceipt() async throws {
        let package = try makePackage(packageID: makePackageID(1))
        let root = temporaryDirectory()
        let bodyRoot = temporaryDirectory()
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: bodyRoot)
        }
        let store = EvidencePackageStore(root: root)
        _ = try store.persist(package)
        M2URLProtocol.handler = { request, _ in
            XCTAssertEqual(request.httpMethod, "PUT")
            return (
                201,
                Data(
                    ("{\"package_id\":\"\(package.manifest.packageID.uuidString.lowercased())\","
                        + "\"state\":\"stored\",\"created\":true,"
                        + "\"received_at\":\"2026-08-27T10:00:00.000Z\"}").utf8
                )
            )
        }
        defer { M2URLProtocol.handler = nil }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [M2URLProtocol.self]
        let client = try EvidenceUploadClient(
            session: URLSession(configuration: configuration),
            bodyDirectory: bodyRoot
        )
        let queue = EvidenceUploadQueue(store: store, client: client)
        let backend = try BackendConfiguration(baseURL: URL(string: "http://backend.local:8000")!)

        let attempts = await queue.uploadQueued(using: backend)

        XCTAssertEqual(attempts.map(\.disposition), [.acknowledged])
        XCTAssertEqual(store.diagnostics.queuedCount, 0)
        XCTAssertEqual(store.diagnostics.acknowledgedCount, 1)
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: store.packageURL(for: package.manifest.packageID, in: .acknowledged).path
            )
        )
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: root
                    .appendingPathComponent("acknowledged")
                    .appendingPathComponent("\(package.manifest.packageID.uuidString.lowercased()).acknowledgement.json")
                    .path
            )
        )
        let receipt = try XCTUnwrap(store.acknowledgementData(for: package.manifest.packageID))
        let receiptDecoder = JSONDecoder()
        receiptDecoder.dateDecodingStrategy = .iso8601
        let decodedReceipt = try receiptDecoder.decode(EvidenceUploadResponse.self, from: receipt)
        XCTAssertEqual(decodedReceipt.state, "stored")
        XCTAssertTrue(decodedReceipt.created)
    }

    func testConflictIsPermanentAndRetainsThePackage() async throws {
        let package = try makePackage(packageID: makePackageID(2))
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = EvidencePackageStore(root: root)
        _ = try store.persist(package)
        M2URLProtocol.handler = { _, _ in
            (409, Data("{\"error\":{\"code\":\"package_conflict\"}}".utf8))
        }
        defer { M2URLProtocol.handler = nil }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [M2URLProtocol.self]
        let client = try EvidenceUploadClient(session: URLSession(configuration: configuration))
        let queue = EvidenceUploadQueue(store: store, client: client)
        let backend = try BackendConfiguration(baseURL: URL(string: "http://backend.local:8000")!)

        let attempts = await queue.uploadQueued(using: backend)

        XCTAssertEqual(attempts.map(\.disposition), [.permanentFailure])
        XCTAssertEqual(store.diagnostics.queuedCount, 0)
        XCTAssertEqual(store.diagnostics.permanentFailureCount, 1)
        XCTAssertEqual(store.failure(for: package.manifest.packageID)?.statusCode, 409)
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: store.packageURL(for: package.manifest.packageID, in: .failed).path
            )
        )
    }

    func testTemporaryFailureCanBeRetried() async throws {
        let package = try makePackage(packageID: makePackageID(3))
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = EvidencePackageStore(root: root)
        _ = try store.persist(package)
        M2URLProtocol.handler = { _, _ in
            (
                M2URLProtocol.statusCode,
                Data(
                    ("{\"package_id\":\"\(package.manifest.packageID.uuidString.lowercased())\","
                        + "\"state\":\"stored\",\"created\":false,"
                        + "\"received_at\":\"2026-08-27T10:00:00.000Z\"}").utf8
                )
            )
        }
        defer { M2URLProtocol.handler = nil }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [M2URLProtocol.self]
        let client = try EvidenceUploadClient(session: URLSession(configuration: configuration))
        let queue = EvidenceUploadQueue(store: store, client: client)
        let backend = try BackendConfiguration(baseURL: URL(string: "http://backend.local:8000")!)

        M2URLProtocol.statusCode = 503
        let first = await queue.uploadQueued(using: backend)
        XCTAssertEqual(first.map(\.disposition), [.retryableFailure])
        XCTAssertEqual(store.diagnostics.retryableFailureCount, 1)

        M2URLProtocol.statusCode = 200
        let second = await queue.retryFailed(using: backend)
        XCTAssertEqual(second.map(\.disposition), [.acknowledged])
        XCTAssertEqual(store.diagnostics.acknowledgedCount, 1)
    }

    func testResultClientReadsTheDeveloperResultContract() async throws {
        M2URLProtocol.handler = { request, _ in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertTrue(request.url?.path.hasSuffix("/vision-results") == true)
            return (200, Data("[\(Self.resultJSON)]".utf8))
        }
        defer { M2URLProtocol.handler = nil }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [M2URLProtocol.self]
        let client = EvidenceResultClient(session: URLSession(configuration: configuration))
        let backend = try BackendConfiguration(baseURL: URL(string: "http://backend.local:8000")!)
        let packageID = UUID(uuidString: "550e8400-e29b-41d4-a716-446655440000")!

        let results = try await client.results(for: packageID, using: backend)

        XCTAssertEqual(results.count, 1)
        XCTAssertEqual(results[0].status, "uncertain")
        XCTAssertEqual(results[0].candidates.map(\.card), ["HEARTS_QUEEN", "DIAMONDS_QUEEN"])
        XCTAssertEqual(results[0].packageID, packageID)
    }

    func testResponseStatusMappingMatchesTheM2Contract() {
        for status in [408, 429, 500, 503, 599] {
            XCTAssertEqual(
                EvidenceUploadClient.failureKind(
                    for: EvidenceUploadError.nonSuccessResponse(status, Data())
                ),
                .retryable
            )
        }
        for status in [400, 409, 415, 422, 499] {
            XCTAssertEqual(
                EvidenceUploadClient.failureKind(
                    for: EvidenceUploadError.nonSuccessResponse(status, Data())
                ),
                .permanent
            )
        }
        XCTAssertEqual(EvidenceUploadClient.failureKind(for: URLError(.timedOut)), .retryable)
    }

    private static let resultJSON = """
    {
      "schema_version": "vision-detection/v1",
      "result_id": "c648d0b8-f82f-4c50-9505-970907ea1f24",
      "package_id": "550e8400-e29b-41d4-a716-446655440000",
      "session": {"session_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8", "event_sequence": 1},
      "status": "uncertain",
      "selected_card": null,
      "candidates": [
        {"card": "HEARTS_QUEEN", "probability": 0.58},
        {"card": "DIAMONDS_QUEEN", "probability": 0.42}
      ],
      "calibration": "fixture",
      "detector": {"name": "scripted", "version": "scripted-v1"},
      "diagnostics": {"frames_received": 6, "frames_decoded": 0},
      "observations": [],
      "created_at": "2026-08-26T18:12:00.000Z"
    }
    """

    private func makePackage(packageID: UUID) throws -> EvidencePackage {
        let bytes = Data("jpeg bytes".utf8)
        let capturedAt = Date(timeIntervalSince1970: 1_756_000_000)
        let frame = EvidenceFrameManifest(
            partName: "frame_00",
            targetOffsetMs: 0,
            actualOffsetMs: 0,
            sessionElapsedMs: 10_000,
            capturedAtUTC: capturedAt,
            width: 1920,
            height: 1080,
            byteLength: bytes.count,
            contentType: "image/jpeg",
            sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        )
        let manifest = EvidencePackageManifest(
            packageID: packageID,
            session: EvidenceSessionMetadata(sessionID: makePackageID(20), eventSequence: 1),
            event: EvidenceEventMetadata(eventTimeMs: 10_000, emittedAtMs: 10_125, evidenceComplete: true),
            model: EvidencePackageModelMetadata(
                name: "CardEventNet",
                version: "test",
                weightsSHA256: String(repeating: "a", count: 64),
                preprocessing: "full_frame_letterbox_v1"
            ),
            eventDecoder: EvidenceEventDecoderMetadata(
                algorithm: "causal_peak_v1",
                threshold: 0.34,
                peakConfirmationMs: 125,
                minimumEventGapMs: 625,
                targetInferenceHz: 8.0
            ),
            evidenceCapture: EvidenceCaptureMetadata(
                configuration: EvidenceCaptureConfiguration(
                    targetHz: 8.0,
                    jpegQuality: 0.85,
                    historySeconds: 3.0,
                    targetOffsetsMs: [0],
                    maximumLookupDistanceMs: 10,
                    finalizationDelayMs: 900
                )
            ),
            camera: EvidencePackageCameraMetadata(position: "back", orientation: "up", width: 1920, height: 1080),
            frames: [frame],
            missingFrameTargetsMs: [],
            scoreTrace: [],
            client: EvidencePackageClientMetadata(
                appVersion: "test",
                build: "1",
                deviceModelIdentifier: "test-device",
                osVersion: "18.0"
            )
        )
        return try EvidencePackage(
            manifest: manifest,
            frames: [PackagedEvidenceFrame(manifest: frame, jpegData: bytes)]
        )
    }

    private func makePackageID(_ value: UInt8) -> UUID {
        UUID(uuid: (value, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, value))
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}

private final class M2URLProtocol: URLProtocol {
    typealias Handler = (URLRequest, Data) -> (statusCode: Int, body: Data)

    nonisolated(unsafe) static var handler: Handler?
    nonisolated(unsafe) static var statusCode = 200

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let result = Self.handler?(request, requestBody()) ?? (500, Data())
        guard let response = HTTPURLResponse(
            url: request.url!,
            statusCode: result.statusCode,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        ) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: result.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private func requestBody() -> Data {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 16 * 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            body.append(buffer, count: count)
        }
        return body
    }
}
