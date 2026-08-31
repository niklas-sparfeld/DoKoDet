import XCTest
@testable import CardEventProbeCore

final class RecordingWorkspaceLifecycleTests: XCTestCase {
    func testStartAndStopUseOneIdempotentRecordingLifecycle() {
        var lifecycle = RecordingWorkspaceLifecycle()

        XCTAssertTrue(lifecycle.startPreview())
        XCTAssertEqual(lifecycle.state, .starting)
        XCTAssertFalse(lifecycle.startPreview())

        XCTAssertTrue(lifecycle.markPreviewReady())
        XCTAssertEqual(lifecycle.state, .preview)
        XCTAssertTrue(lifecycle.startRecording(recordingID: "recording-001"))
        XCTAssertEqual(lifecycle.state, .recording("recording-001"))
        XCTAssertTrue(lifecycle.stopRecording())
        XCTAssertEqual(lifecycle.state, .stopping("recording-001"))
        XCTAssertFalse(lifecycle.stopRecording())
    }

    func testFinalizationMovesToPostRecordingAndAllowsNextRecording() {
        var lifecycle = RecordingWorkspaceLifecycle(state: .preview)

        XCTAssertTrue(lifecycle.startRecording(recordingID: "recording-002"))
        XCTAssertTrue(lifecycle.stopRecording())
        XCTAssertTrue(lifecycle.finishRecording())
        XCTAssertEqual(lifecycle.state, .postRecording("recording-002"))
        XCTAssertTrue(lifecycle.startRecording(recordingID: "recording-003"))
        XCTAssertEqual(lifecycle.state, .recording("recording-003"))
    }

    func testPostRecordingCanRestartTheWorkspacePreview() {
        var lifecycle = RecordingWorkspaceLifecycle(state: .postRecording("recording-006"))

        XCTAssertTrue(lifecycle.startPreview())
        XCTAssertEqual(lifecycle.state, .starting)
        XCTAssertTrue(lifecycle.markPreviewReady())
        XCTAssertTrue(lifecycle.startRecording(recordingID: "recording-007"))
    }

    func testRelaunchRecoveryRestoresPostRecordingOrReportsInterruptedRecording() {
        var postRecording = RecordingWorkspaceLifecycle()
        XCTAssertTrue(postRecording.recoverPostRecording(recordingID: "recording-004"))
        XCTAssertEqual(postRecording.state, .postRecording("recording-004"))

        var interrupted = RecordingWorkspaceLifecycle()
        XCTAssertTrue(interrupted.recoverInterruptedRecording(recordingID: "recording-005"))
        XCTAssertEqual(
            interrupted.state,
            .failed("Recording recording-005 was interrupted before finalization.")
        )
    }

    func testFailureCanRetryPreviewAndStopDoesNotChangeRecordingState() {
        var lifecycle = RecordingWorkspaceLifecycle(state: .starting)

        XCTAssertTrue(lifecycle.fail("Camera access is denied."))
        XCTAssertEqual(lifecycle.state, .failed("Camera access is denied."))
        XCTAssertTrue(lifecycle.startPreview())
        XCTAssertEqual(lifecycle.state, .starting)
        XCTAssertTrue(lifecycle.markPreviewReady())
        XCTAssertTrue(lifecycle.stopPreview())
        XCTAssertEqual(lifecycle.state, .idle)
        XCTAssertFalse(lifecycle.stopRecording())
    }
}
