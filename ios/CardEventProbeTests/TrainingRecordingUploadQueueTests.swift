import Foundation
import XCTest
@testable import CardEventProbeCore

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class TrainingRecordingUploadQueueTests: XCTestCase {
    override func setUp() {
        super.setUp()
        RecordingUploadURLProtocol.reset()
    }

    func testRecoverFindsQueuedBundleAfterLaunch() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = TrainingRecordingStore(root: root)
        try installFixture(in: store, state: .queued)

        let diagnostics = try store.recover()

        XCTAssertEqual(diagnostics.queuedCount, 1)
        XCTAssertEqual(diagnostics.recoveredRecordingIDs, ["recording-both"])
        XCTAssertTrue(diagnostics.errors.isEmpty)
    }

    func testMultipartUploadUsesRepositoryBundleFileBackedParts() throws {
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
            "/v1/repository-bundles/recording-both"
        )
        XCTAssertTrue(bodyText.contains("name=\"manifest\""))
        XCTAssertTrue(bodyText.contains("name=\"source_record\"; filename=\"source-record.json\""))
        XCTAssertTrue(bodyText.contains("name=\"task_enrollment\"; filename=\"initial-task-enrollment.json\""))
        XCTAssertTrue(bodyText.contains("name=\"video\"; filename=\"video-both.mov\""))
        XCTAssertTrue(bodyText.contains("name=\"proposal\"; filename=\"proposal-both.json\""))
        XCTAssertGreaterThan(prepared.contentLength, 0)
    }

    func testUploadReportsPreparationAndByteAccurateTransferProgress() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = TrainingRecordingStore(root: root)
        let recordingURL = try installFixture(in: store, state: .queued)
        let client = try makeClient(bodyDirectory: root)
        let configuration = try BackendConfiguration.simulatorLocalhost()
        let recorder = UploadProgressRecorder()

        _ = try await client.upload(
            recordingAt: recordingURL,
            using: configuration,
            progress: { recorder.append($0) }
        )

        let progress = recorder.values
        XCTAssertEqual(progress.first?.recordingID, "recording-both")
        XCTAssertEqual(progress.first?.phase, .preparing)
        let transferProgress = progress.filter { $0.phase == .uploading }
        XCTAssertGreaterThanOrEqual(transferProgress.count, 2)
        XCTAssertEqual(transferProgress.first?.bytesSent, 0)
        XCTAssertEqual(transferProgress.last?.bytesSent, transferProgress.last?.expectedBytes)
        XCTAssertTrue(transferProgress.allSatisfy { (0...1).contains($0.fraction) })
        XCTAssertEqual(
            transferProgress.map(\.bytesSent),
            transferProgress.map(\.bytesSent).sorted()
        )
        XCTAssertTrue(transferProgress.allSatisfy { $0.recordingID == "recording-both" })
    }

    func testQueueForwardsProgressAndRetryStartsAtZero() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = TrainingRecordingStore(root: root)
        _ = try installFixture(in: store, state: .queued)
        let queue = TrainingRecordingUploadQueue(
            store: store,
            client: try makeClient(bodyDirectory: root)
        )
        let configuration = try BackendConfiguration.simulatorLocalhost()
        let recorder = UploadProgressRecorder()

        RecordingUploadURLProtocol.statusCode = 503
        let failed = await queue.uploadQueued(
            using: configuration,
            progress: { recorder.append($0) }
        )

        XCTAssertEqual(failed.map(\.disposition), [.retryableFailure])
        XCTAssertEqual(recorder.values.first?.phase, .preparing)
        XCTAssertEqual(recorder.values.first?.recordingID, "recording-both")
        XCTAssertEqual(recorder.values.last?.phase, .uploading)
        XCTAssertEqual(recorder.values.last?.fraction, 1.0)

        recorder.removeAll()
        RecordingUploadURLProtocol.statusCode = 201
        let acknowledged = await queue.retryFailed(
            using: configuration,
            progress: { recorder.append($0) }
        )

        XCTAssertEqual(acknowledged.map(\.disposition), [.acknowledged])
        XCTAssertEqual(recorder.values.first?.phase, .preparing)
        XCTAssertEqual(recorder.values.first?.bytesSent, 0)
        XCTAssertEqual(recorder.values.last?.bytesSent, recorder.values.last?.expectedBytes)
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
        XCTAssertNotNil(store.failure(for: "recording-both"))
        XCTAssertTrue(FileManager.default.fileExists(
            atPath: store.recordingURL(for: "recording-both", in: .failed).path
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
        let destination = store.recordingURL(for: "recording-both", in: state)
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
            .appendingPathComponent("fixtures/repository-bundle/v1/both")
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}

private final class RecordingUploadURLProtocol: URLProtocol {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var storedStatusCode = 201
    nonisolated(unsafe) private static var storedRequestCount = 0

    static func reset() {
        lock.lock()
        storedStatusCode = 201
        storedRequestCount = 0
        lock.unlock()
    }

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
            "{\"recording_id\":\"recording-both\",\"state\":\"acknowledged\",\"created\":\(statusCode == 201 ? "true" : "false"),\"received_at\":\"2026-08-27T00:00:00Z\"}"
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

private final class UploadProgressRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storedValues: [TrainingRecordingUploadProgress] = []

    var values: [TrainingRecordingUploadProgress] {
        lock.lock()
        defer { lock.unlock() }
        return storedValues
    }

    func append(_ value: TrainingRecordingUploadProgress) {
        lock.lock()
        storedValues.append(value)
        lock.unlock()
    }

    func removeAll() {
        lock.lock()
        storedValues.removeAll()
        lock.unlock()
    }
}
