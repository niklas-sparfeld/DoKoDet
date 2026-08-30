import Foundation
import XCTest
@testable import CardEventProbeCore

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class RoundAnalysisTests: XCTestCase {
    override func setUp() {
        super.setUp()
        RoundAnalysisURLProtocol.reset()
    }

    func testCreateRequestUsesStrictBackendShapeAndFixedSearchLimits() throws {
        let recordingID = "recording-analysis-fixture"
        let setup = try RoundRecordingSetup(
            gameID: "game-analysis-fixture",
            recordingID: recordingID,
            dealer: "seat-2",
            firstTrickLeader: "seat-3"
        )
        let analysisID = UUID(uuidString: "00000000-0000-0000-0000-000000000032")!
        let packageID = UUID(uuidString: "00000000-0000-0000-0000-000000000034")!
        let request = try RoundAnalysisCreateRequest(
            analysisID: analysisID,
            recordingID: recordingID,
            sessionID: UUID(uuidString: "00000000-0000-0000-0000-000000000033")!,
            roundSetup: setup,
            evidencePackageIDs: [packageID]
        )

        let data = try JSONEncoder().encode(request)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(object["schema_version"] as? String, "round-analysis/v1")
        XCTAssertEqual(object["analysis_id"] as? String, analysisID.uuidString.lowercased())
        XCTAssertEqual(object["recording_id"] as? String, recordingID)
        XCTAssertEqual(object["round_id"] as? String, setup.roundID)
        XCTAssertEqual(object["evidence_package_ids"] as? [String], [packageID.uuidString.lowercased()])
        XCTAssertEqual(
            object["search"] as? [String: Int],
            [
                "max_missing_plays": 1,
                "max_hypotheses": 256,
                "max_search_nodes": 250_000,
            ]
        )

        var unknownField = object
        unknownField["unexpected"] = true
        XCTAssertThrowsError(
            try JSONDecoder().decode(
                RoundAnalysisCreateRequest.self,
                from: JSONSerialization.data(withJSONObject: unknownField)
            )
        )
    }

    func testSubmissionStatePersistsAnalysisIDAndCanResumeAfterReload() throws {
        let directory = temporaryDirectory()
        defer {
            if FileManager.default.fileExists(atPath: directory.path) {
                try? FileManager.default.removeItem(at: directory)
            }
        }
        let recordingID = "recording-analysis-fixture"
        let setup = try RoundRecordingSetup(
            gameID: "game-analysis-fixture",
            recordingID: recordingID,
            dealer: "seat-1",
            firstTrickLeader: "seat-1"
        )
        let analysisID = UUID()
        let packageID = UUID()
        let state = try RoundAnalysisSubmissionState(
            recordingID: recordingID,
            sessionID: UUID(),
            roundSetup: setup,
            evidencePackageIDs: [packageID],
            analysisID: analysisID,
            phase: .submitting
        )
        let store = RoundAnalysisSubmissionStore(directory: directory)

        try store.save(state)

        let reloaded = try XCTUnwrap(try RoundAnalysisSubmissionStore(directory: directory).load())
        XCTAssertEqual(reloaded.analysisID, analysisID)
        XCTAssertEqual(reloaded.evidencePackageIDs, [packageID])
        XCTAssertEqual(reloaded.phase, .submitting)
        XCTAssertEqual(reloaded.createRequest?.analysisID, analysisID)
    }

    func testEmptyEvidenceFailureIsDurableWithoutAnAnalysisID() throws {
        let setup = try RoundRecordingSetup(
            gameID: "game-analysis-fixture",
            recordingID: "recording-analysis-fixture",
            dealer: "seat-1",
            firstTrickLeader: "seat-1"
        )
        let state = try RoundAnalysisSubmissionState(
            recordingID: "recording-analysis-fixture",
            sessionID: UUID(),
            roundSetup: setup,
            evidencePackageIDs: [],
            phase: .failed,
            error: "No evidence packages captured"
        )

        XCTAssertNil(state.analysisID)
        XCTAssertNil(state.createRequest)
        XCTAssertEqual(state.error, "No evidence packages captured")
    }

    func testSubmissionReadinessWaitsForEveryAcknowledgement() throws {
        let setup = try RoundRecordingSetup(
            gameID: "game-analysis-fixture",
            recordingID: "recording-analysis-fixture",
            dealer: "seat-1",
            firstTrickLeader: "seat-1"
        )
        let packageID = UUID()
        let sessionID = UUID()
        let initial = try RoundRecordingState(
            recordingID: "recording-analysis-fixture",
            sessionID: sessionID,
            roundSetup: setup
        )
        let withPackage = try initial
            .addingEvidencePackage(packageID)
            .closingEvidenceMembership()
            .markingRecordingBundleFinalized()
            .markingRecordingBundleAcknowledged()

        XCTAssertEqual(withPackage.roundAnalysisSubmissionReadiness, .waitingForUploads)
        let acknowledged = try withPackage.acknowledgingEvidencePackage(packageID)
        XCTAssertEqual(acknowledged.roundAnalysisSubmissionReadiness, .ready)
    }

    func testClientPostsAndPollsCanonicalRoundAnalysisEndpoints() async throws {
        let setup = try RoundRecordingSetup(
            gameID: "game-analysis-fixture",
            recordingID: "recording-analysis-fixture",
            dealer: "seat-1",
            firstTrickLeader: "seat-1"
        )
        let analysisID = UUID(uuidString: "00000000-0000-0000-0000-000000000032")!
        let request = try RoundAnalysisCreateRequest(
            analysisID: analysisID,
            recordingID: "recording-analysis-fixture",
            sessionID: UUID(uuidString: "00000000-0000-0000-0000-000000000033")!,
            roundSetup: setup,
            evidencePackageIDs: [
                UUID(uuidString: "00000000-0000-0000-0000-000000000034")!,
            ]
        )
        let configuration = try BackendConfiguration.simulatorLocalhost()
        let sessionConfiguration = URLSessionConfiguration.ephemeral
        sessionConfiguration.protocolClasses = [RoundAnalysisURLProtocol.self]
        let client = RoundAnalysisClient(session: URLSession(configuration: sessionConfiguration))

        let created = try await client.create(request: request, using: configuration)
        let polled = try await client.status(for: analysisID, using: configuration)

        XCTAssertEqual(created.state, .queued)
        XCTAssertEqual(polled.analysisID, analysisID)
        XCTAssertEqual(RoundAnalysisURLProtocol.methods, ["POST", "GET"])
        XCTAssertEqual(
            RoundAnalysisURLProtocol.paths,
            ["/v1/round-analyses", "/v1/round-analyses/\(analysisID.uuidString.lowercased())"]
        )
        let posted = try XCTUnwrap(
            JSONSerialization.jsonObject(with: RoundAnalysisURLProtocol.postedBody) as? [String: Any]
        )
        XCTAssertEqual(posted["analysis_id"] as? String, analysisID.uuidString.lowercased())
    }

    func testClientRejectsUnknownStatusFields() async throws {
        let analysisID = UUID(uuidString: "00000000-0000-0000-0000-000000000032")!
        RoundAnalysisURLProtocol.statusBody = Self.statusJSON(
            analysisID: analysisID,
            extraField: true
        )
        let configuration = try BackendConfiguration.simulatorLocalhost()
        let sessionConfiguration = URLSessionConfiguration.ephemeral
        sessionConfiguration.protocolClasses = [RoundAnalysisURLProtocol.self]
        let client = RoundAnalysisClient(session: URLSession(configuration: sessionConfiguration))

        do {
            _ = try await client.status(for: analysisID, using: configuration)
            XCTFail("an unknown status field must be rejected")
        } catch {
            XCTAssertNotNil(error as? RoundAnalysisContractError)
        }
    }

    func testTerminalResultSummaryCoversResolvedAndAmbiguousResults() {
        let analysisID = UUID()
        let resolved = RoundAnalysisResult(
            analysisID: analysisID,
            reconstructionStatus: .resolved,
            hypotheses: [[
                "gameplay": .object([
                    "tricks": .array(Array(repeating: .object([:]), count: 10)),
                ]),
            ]],
            focusedDecisions: [],
            diagnostics: [:],
            inputArtifactID: "round-analyses/analysis/input.json",
            inputArtifactSHA256: String(repeating: "a", count: 64),
            resultArtifactID: "round-analyses/analysis/result.json",
            resultArtifactSHA256: String(repeating: "b", count: 64)
        )
        XCTAssertEqual(
            RoundAnalysisResultSummary(result: resolved).text,
            "Resolved hypothesis with 10 tricks"
        )

        let ambiguous = RoundAnalysisResult(
            analysisID: analysisID,
            reconstructionStatus: .ambiguous,
            hypotheses: [[:], [:], [:]],
            focusedDecisions: [[:], [:]],
            diagnostics: [:],
            inputArtifactID: "round-analyses/analysis/input.json",
            inputArtifactSHA256: String(repeating: "a", count: 64),
            resultArtifactID: "round-analyses/analysis/result.json",
            resultArtifactSHA256: String(repeating: "b", count: 64)
        )
        XCTAssertEqual(
            RoundAnalysisResultSummary(result: ambiguous).text,
            "Ambiguous: 3 hypotheses, 2 focused decisions"
        )
    }

    func testTerminalResultSummaryUsesEngineDiagnosticsAndKeepsEmptyEvidenceFailureExplicit() {
        let analysisID = UUID()
        let incomplete = RoundAnalysisResult(
            analysisID: analysisID,
            reconstructionStatus: .incomplete,
            hypotheses: [],
            focusedDecisions: [],
            diagnostics: [
                "incomplete_observations": .array([.string("observation-001")]),
            ],
            inputArtifactID: "round-analyses/analysis/input.json",
            inputArtifactSHA256: String(repeating: "a", count: 64),
            resultArtifactID: "round-analyses/analysis/result.json",
            resultArtifactSHA256: String(repeating: "b", count: 64)
        )
        XCTAssertEqual(
            RoundAnalysisResultSummary(result: incomplete).text,
            "Incomplete: 1 incomplete observation"
        )

        let impossible = RoundAnalysisResult(
            analysisID: analysisID,
            reconstructionStatus: .impossible,
            hypotheses: [],
            focusedDecisions: [],
            diagnostics: [
                "rejected_branches": .array([.string("rejected")]),
            ],
            inputArtifactID: "round-analyses/analysis/input.json",
            inputArtifactSHA256: String(repeating: "a", count: 64),
            resultArtifactID: "round-analyses/analysis/result.json",
            resultArtifactSHA256: String(repeating: "b", count: 64)
        )
        XCTAssertEqual(
            RoundAnalysisResultSummary(result: impossible).text,
            "Impossible: 1 rejected branch"
        )

        let failure = RoundAnalysisDisplayState.failed("No evidence packages captured")
        XCTAssertTrue(failure.isFailure)
        XCTAssertEqual(failure.detail, "No evidence packages captured")
    }

    fileprivate static func statusJSON(analysisID: UUID, extraField: Bool = false) -> Data {
        var object: [String: Any] = [
            "analysis_id": analysisID.uuidString.lowercased(),
            "recording_id": "recording-analysis-fixture",
            "round_id": "round-recording-analysis-fixture",
            "session_id": "00000000-0000-0000-0000-000000000033",
            "state": "queued",
            "total_evidence_packages": 1,
            "completed_evidence_packages": 0,
            "result": NSNull(),
            "error": NSNull(),
            "created_at": "2026-08-30T16:00:00Z",
            "started_at": NSNull(),
            "completed_at": NSNull(),
        ]
        if extraField {
            object["unexpected"] = true
        }
        return try! JSONSerialization.data(withJSONObject: object)
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}

private final class RoundAnalysisURLProtocol: URLProtocol {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var storedMethods: [String] = []
    nonisolated(unsafe) private static var storedPaths: [String] = []
    nonisolated(unsafe) private static var storedPostedBody = Data()
    nonisolated(unsafe) static var statusBody = RoundAnalysisTests.statusJSON(
        analysisID: UUID(uuidString: "00000000-0000-0000-0000-000000000032")!
    )

    static var methods: [String] {
        lock.lock()
        defer { lock.unlock() }
        return storedMethods
    }

    static var paths: [String] {
        lock.lock()
        defer { lock.unlock() }
        return storedPaths
    }

    static var postedBody: Data {
        lock.lock()
        defer { lock.unlock() }
        return storedPostedBody
    }

    static func reset() {
        lock.lock()
        storedMethods = []
        storedPaths = []
        storedPostedBody = Data()
        statusBody = RoundAnalysisTests.statusJSON(
            analysisID: UUID(uuidString: "00000000-0000-0000-0000-000000000032")!
        )
        lock.unlock()
    }

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.path.hasPrefix("/v1/round-analyses") == true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let client else { return }
        let method = request.httpMethod ?? ""
        let path = request.url?.path ?? ""
        Self.lock.lock()
        Self.storedMethods.append(method)
        Self.storedPaths.append(path)
        if method == "POST" {
            Self.storedPostedBody = request.httpBody ?? Self.readBodyStream(request.httpBodyStream)
        }
        let body = Self.statusBody
        Self.lock.unlock()
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: method == "POST" ? 202 : 200,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client.urlProtocol(self, didLoad: body)
        client.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func readBodyStream(_ stream: InputStream?) -> Data {
        guard let stream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let count = stream.read(buffer, maxLength: 4096)
            guard count > 0 else { break }
            data.append(buffer, count: count)
        }
        return data
    }
}
