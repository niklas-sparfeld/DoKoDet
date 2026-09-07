import XCTest
@testable import CardEventProbe

final class AppWorkflowTests: XCTestCase {
    @MainActor
    func testEvidenceWorkflowRecoversRoundStateAndRetryReportsMissingBackend() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("app-workflow-recovery-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let roundStore = RoundRecordingStateStore(directory: directory)
        let state = try makeRoundRecordingState()
        try roundStore.save(state)

        let workflow = makeEvidenceWorkflow(
            evidenceRoot: directory.appendingPathComponent("evidence"),
            roundStore: roundStore
        )
        workflow.recover()
        workflow.retryFailedEvidence()

        XCTAssertEqual(workflow.roundRecordingState?.recordingID, state.recordingID)
        XCTAssertEqual(workflow.roundRecordingState?.sessionID, state.sessionID)
        XCTAssertEqual(
            workflow.roundRecordingState?.roundSetup,
            state.roundSetup
        )
        XCTAssertEqual(
            workflow.evidenceUploadError,
            "Connect to a backend before retrying evidence uploads."
        )
    }

    @MainActor
    func testTrainingRecordingAcknowledgementPersistsBeforeAnalysisSubmission() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("app-workflow-ack-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let roundStore = RoundRecordingStateStore(directory: directory)
        let recordingID = "recording-001"
        let packageID = UUID()
        var state = try makeRoundRecordingState(recordingID: recordingID, evidencePackageID: packageID)
        state = try state.closingEvidenceMembership()
        state = state.markingRecordingBundleFinalized()
        try roundStore.save(state)

        let workflow = makeEvidenceWorkflow(
            evidenceRoot: directory.appendingPathComponent("evidence"),
            roundStore: roundStore
        )
        workflow.setRoundRecordingState(state)
        workflow.acknowledgeTrainingRecording(recordingID)

        let reloaded = try XCTUnwrap(try roundStore.load())
        XCTAssertTrue(reloaded.recordingBundleAcknowledged)
        XCTAssertNil(workflow.roundAnalysisSubmissionState)
        XCTAssertEqual(workflow.roundAnalysisState, .waitingForUploads)
    }

    func testAnalysisSubmissionGatePreventsDuplicateSubmission() {
        var gate = AnalysisSubmissionGate()

        XCTAssertTrue(gate.begin())
        XCTAssertFalse(gate.begin())
        XCTAssertTrue(gate.isInFlight)

        gate.finish()

        XCTAssertFalse(gate.isInFlight)
        XCTAssertTrue(gate.begin())
    }

    func testAnalysisSubmissionGateCancellationAllowsRetry() {
        var gate = AnalysisSubmissionGate()

        XCTAssertTrue(gate.begin())
        gate.cancel()

        XCTAssertFalse(gate.isInFlight)
        XCTAssertTrue(gate.begin())
    }

    func testRecordingWorkspaceLifecycleTransitionsRemainIdempotent() {
        var lifecycle = RecordingWorkspaceLifecycle()

        XCTAssertTrue(lifecycle.startPreview())
        XCTAssertTrue(lifecycle.markPreviewReady())
        XCTAssertTrue(lifecycle.startRecording(recordingID: "recording-001"))
        XCTAssertTrue(lifecycle.stopRecording())
        XCTAssertFalse(lifecycle.stopRecording())
        XCTAssertTrue(lifecycle.finishRecording())
        XCTAssertTrue(lifecycle.recoverPostRecording(recordingID: "recording-001"))
        XCTAssertTrue(lifecycle.stopPreview())
        XCTAssertEqual(lifecycle.state, .idle)
    }

    @MainActor
    private func makeEvidenceWorkflow(
        evidenceRoot: URL,
        roundStore: RoundRecordingStateStore
    ) -> EvidenceAnalysisWorkflow {
        EvidenceAnalysisWorkflow(
            evidenceCaptureConfiguration: EvidenceCaptureConfiguration(),
            evidencePackageStore: EvidencePackageStore(root: evidenceRoot),
            evidenceUploadQueue: nil,
            roundRecordingStateStore: roundStore,
            roundAnalysisSubmissionStore: RoundAnalysisSubmissionStore(
                directory: roundStore.directory
            ),
            roundAnalysisClient: RoundAnalysisClient(),
            backendConfiguration: { nil },
            onStateChange: { _ in },
            onEventSequenceReserved: { _, _ in }
        )
    }

    private func makeRoundRecordingState(
        recordingID: String = "recording-001",
        evidencePackageID: UUID? = nil
    ) throws -> RoundRecordingState {
        let setup = try RoundRecordingSetup(
            gameID: "game-001",
            roundID: "round-\(recordingID)",
            ruleset: RoundRecordingRuleset(),
            deckVariant: RoundRecordingSetup.deckVariant,
            activePlayers: RoundRecordingSetup.fixedSeatIDs,
            dealer: "seat-1",
            firstTrickLeader: "seat-1"
        )
        var state = try RoundRecordingState(
            recordingID: recordingID,
            sessionID: UUID(),
            roundSetup: setup
        )
        if let evidencePackageID {
            state = try state.addingEvidencePackage(evidencePackageID)
        }
        return state
    }
}
