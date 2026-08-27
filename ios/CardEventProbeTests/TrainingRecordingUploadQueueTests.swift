import Foundation
import XCTest
@testable import CardEventProbeCore

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class TrainingRecordingUploadQueueTests: XCTestCase {
    func testRecoverFindsQueuedBundleAfterLaunch() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = TrainingRecordingStore(root: root)
        try installFixture(in: store, state: .queued)

        let diagnostics = try store.recover()

        XCTAssertEqual(diagnostics.queuedCount, 1)
        XCTAssertEqual(diagnostics.recoveredRecordingIDs, ["recording-fixture-001"])
        XCTAssertTrue(diagnostics.errors.isEmpty)
    }

    func testMultipartUploadUsesThreeFileBackedParts() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = TrainingRecordingStore(root: root)
        let recordingURL = try installFixture(in: store, state: .queued)
        let bodyDirectory = root.appendingPathComponent("request-bodies", isDirectory: true)
        let builder = try TrainingRecordingMultipartRequestBuilder(bodyDirectory: bodyDirectory)

        let prepared = try builder.prepare(
            recordingAt: recordingURL,
            baseURL: URL(string: "http://127.0.0.1:8000")!
        )
        defer { prepared.removeBodyFile() }
        let body = try Data(contentsOf: prepared.bodyFileURL)
        let bodyText = String(decoding: body, as: UTF8.self)

        XCTAssertEqual(
            prepared.request.url?.path,
            "/v1/training-recordings/recording-fixture-001"
        )
        XCTAssertTrue(bodyText.contains("name=\"manifest\""))
        XCTAssertTrue(bodyText.contains("name=\"video\"; filename=\"video-fixture-001.mov\""))
        XCTAssertTrue(bodyText.contains("name=\"predictions\"; filename=\"video-fixture-001.json\""))
        XCTAssertGreaterThan(prepared.contentLength, 0)
    }

    func testUploadFailurePreservesBundleAndRetryAcknowledgesOnce() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = TrainingRecordingStore(root: root)
        _ = try installFixture(in: store, state: .queued)

        RecordingUploadURLProtocol.statusCode = 503
        let queue = TrainingRecordingUploadQueue(
            store: store,
            client: try makeClient(bodyDirectory: root)
        )
        let configuration = try BackendConfiguration.simulatorLocalhost()
        let failed = await queue.uploadQueued(using: configuration)

        XCTAssertEqual(failed.first?.disposition, .retryableFailure)
        XCTAssertEqual(store.diagnostics.failedCount, 1)
        XCTAssertNotNil(store.failure(for: "recording-fixture-001"))
        XCTAssertNil(store.failure(for: "recording-fixture-002"))
        XCTAssertTrue(FileManager.default.fileExists(
            atPath: store.recordingURL(for: "recording-fixture-001", in: .failed).path
        ))

        RecordingUploadURLProtocol.statusCode = 201
        let acknowledged = await queue.retryFailed(using: configuration)

        XCTAssertEqual(acknowledged.first?.disposition, .acknowledged)
        XCTAssertEqual(store.diagnostics.acknowledgedCount, 1)
        let repeated = await queue.uploadQueued(using: configuration)
        XCTAssertEqual(repeated, [], "acknowledged bundles must not be uploaded again")
        XCTAssertEqual(RecordingUploadURLProtocol.requestCount, 2)
    }

    private func makeClient(bodyDirectory: URL) throws -> TrainingRecordingUploadClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RecordingUploadURLProtocol.self]
        return try TrainingRecordingUploadClient(
            session: URLSession(configuration: configuration),
            bodyDirectory: bodyDirectory
        )
    }

    @discardableResult
    private func installFixture(
        in store: TrainingRecordingStore,
        state: TrainingRecordingQueueState
    ) throws -> URL {
        let destination = store.recordingURL(for: "recording-fixture-001", in: state)
        try FileManager.default.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try FileManager.default.copyItem(at: fixtureURL(), to: destination)
        return destination
    }

    private func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("fixtures/training-recording/v1/recording-fixture-001")
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}

private final class RecordingUploadURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var storedStatusCode = 201
    private static var storedRequestCount = 0

    static var statusCode: Int {
        get {
            lock.lock()
            defer { lock.unlock() }
            return storedStatusCode
        }
        set {
            lock.lock()
            storedStatusCode = newValue
            lock.unlock()
        }
    }

    static var requestCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return storedRequestCount
    }

    override class func canInit(with request: URLRequest) -> Bool {
        request.httpMethod == "PUT"
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        let statusCode: Int
        Self.lock.lock()
        statusCode = Self.storedStatusCode
        Self.storedRequestCount += 1
        Self.lock.unlock()

        guard let url = request.url,
              let client = client else {
            return
        }
        let body = Data(
            "{\"recording_id\":\"recording-fixture-001\",\"state\":\"acknowledged\",\"created\":\(statusCode == 201 ? "true" : "false"),\"received_at\":\"2026-08-27T00:00:00Z\"}"
                .utf8
        )
        let response = HTTPURLResponse(
            url: url,
            statusCode: statusCode,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client.urlProtocol(self, didLoad: body)
        client.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
