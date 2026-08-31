import XCTest
@testable import CardEventProbeCore

final class RecordingWorkspacePresentationTests: XCTestCase {
    func testInformationOrderAndPersistentAccessibilityLabels() {
        let requirements = readyRequirements()
        let state = RecordingWorkspaceSurfaceState(
            workspaceState: .preview,
            trainingState: .idle,
            roundAnalysisState: .idle,
            startRequirements: requirements,
            eventCount: 12,
            elapsedSeconds: 0
        )

        XCTAssertEqual(state.informationOrder, [
            .profileRow,
            .cameraFrame,
            .eventCount,
            .primaryControl,
            .elapsedTime,
            .lifecycleStatus,
            .moreDetails,
        ])
        XCTAssertEqual(state.primaryActionAccessibilityLabel, "Start recording")
        XCTAssertEqual(state.eventCountAccessibilityLabel, "Events detected")
        XCTAssertEqual(state.eventCountAccessibilityValue, "12")
        XCTAssertFalse(state.profileControlsLocked)
        XCTAssertFalse(state.replayEntryLocked)
    }

    func testStartBlockersFollowOperatorFacingGateOrder() {
        XCTAssertEqual(
            RecordingWorkspaceSurfaceState(
                workspaceState: .preview,
                trainingState: .idle,
                roundAnalysisState: .idle,
                startRequirements: readyRequirements(profileSelected: false),
                eventCount: 0,
                elapsedSeconds: 0
            ).startBlocker,
            "Select a recording profile."
        )
        XCTAssertEqual(
            RecordingWorkspaceSurfaceState(
                workspaceState: .preview,
                trainingState: .idle,
                roundAnalysisState: .idle,
                startRequirements: readyRequirements(
                    profileSelected: true,
                    profileComplete: true,
                    operatorConfigured: false,
                    cameraReady: false,
                    modelReady: false,
                    backendConnected: false,
                    diskSpaceAvailable: false,
                    queueReady: false
                ),
                eventCount: 0,
                elapsedSeconds: 0
            ).startBlocker,
            "Add an operator name in Settings."
        )
        XCTAssertEqual(
            RecordingWorkspaceSurfaceState(
                workspaceState: .preview,
                trainingState: .idle,
                roundAnalysisState: .idle,
                startRequirements: readyRequirements(
                    profileSelected: true,
                    profileComplete: true,
                    operatorConfigured: true,
                    cameraReady: false
                ),
                eventCount: 0,
                elapsedSeconds: 0
            ).startBlocker,
            "Camera is not ready."
        )
    }

    func testRecordingLocksSecondaryControlsAndShowsStopWithElapsedTime() {
        let state = RecordingWorkspaceSurfaceState(
            workspaceState: .recording("recording-001"),
            trainingState: .recording,
            roundAnalysisState: .idle,
            startRequirements: readyRequirements(),
            eventCount: 4,
            elapsedSeconds: 65
        )

        XCTAssertEqual(state.primaryActionTitle, "Stop recording")
        XCTAssertTrue(state.primaryActionEnabled)
        XCTAssertEqual(state.primaryActionAccessibilityHint, "Stops the recording and starts finalization.")
        XCTAssertTrue(state.showsElapsedTime)
        XCTAssertTrue(state.profileControlsLocked)
        XCTAssertTrue(state.replayEntryLocked)
        XCTAssertEqual(state.status.title, "Recording in progress")
        XCTAssertEqual(state.status.detail, "01:05 elapsed")
        XCTAssertEqual(state.status.tone, .active)
    }

    func testUploadAnalysisAndFailureStatusesRemainActionable() {
        let uploading = RecordingWorkspaceSurfaceState(
            workspaceState: .postRecording("recording-001"),
            trainingState: .uploading,
            roundAnalysisState: .idle,
            startRequirements: readyRequirements(),
            eventCount: 4,
            elapsedSeconds: 0,
            uploadDetail: "Uploading 50 percent"
        )
        XCTAssertEqual(uploading.status.title, "Uploading recording")
        XCTAssertEqual(uploading.status.detail, "Uploading 50 percent")
        XCTAssertFalse(uploading.profileControlsLocked)

        let complete = RecordingWorkspaceSurfaceState(
            workspaceState: .postRecording("recording-001"),
            trainingState: .acknowledged,
            roundAnalysisState: .complete(
                RoundAnalysisResultSummary(text: "Resolved")
            ),
            startRequirements: readyRequirements(),
            eventCount: 4,
            elapsedSeconds: 0
        )
        XCTAssertEqual(complete.status.title, "Analysis complete")
        XCTAssertEqual(complete.status.tone, RecordingWorkspaceStatusTone.success)

        let failure = RecordingWorkspaceSurfaceState(
            workspaceState: .postRecording("recording-001"),
            trainingState: .failed("Backend rejected the recording."),
            roundAnalysisState: .idle,
            startRequirements: readyRequirements(),
            eventCount: 4,
            elapsedSeconds: 0
        )
        XCTAssertEqual(failure.status.title, "Upload needs attention")
        XCTAssertEqual(failure.status.detail, "Backend rejected the recording.")
        XCTAssertEqual(failure.status.tone, .failure)
    }

    private func readyRequirements(
        workspaceState: RecordingWorkspaceState = .preview,
        profileSelected: Bool = true,
        profileComplete: Bool = true,
        operatorConfigured: Bool = true,
        cameraReady: Bool = true,
        modelReady: Bool = true,
        backendConnected: Bool = true,
        diskSpaceAvailable: Bool = true,
        queueReady: Bool = true,
        replayRunning: Bool = false
    ) -> RecordingWorkspaceStartRequirements {
        RecordingWorkspaceStartRequirements(
            workspaceState: workspaceState,
            profileSelected: profileSelected,
            profileComplete: profileComplete,
            operatorConfigured: operatorConfigured,
            cameraReady: cameraReady,
            modelReady: modelReady,
            backendConnected: backendConnected,
            diskSpaceAvailable: diskSpaceAvailable,
            queueReady: queueReady,
            replayRunning: replayRunning
        )
    }
}
