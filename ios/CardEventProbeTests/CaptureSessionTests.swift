import CoreMedia
import Foundation
import XCTest
@testable import CardEventProbeCore

final class CaptureSessionTests: XCTestCase {
    func testCameraSourceRateSelectsThirtyFramesPerSecondWhenSupported() throws {
        let status = try XCTUnwrap(
            CameraSourceRateStatus.select(supportedMaximumFrameRate: 60.0)
        )

        XCTAssertEqual(status.requestedFrameRate, 30.0)
        XCTAssertEqual(status.selectedFrameRate, 30.0)
        XCTAssertFalse(status.isFallback)
        XCTAssertTrue(status.summary.contains("selected"))
    }

    func testCameraSourceRateReportsFallbackWhenThirtyFramesPerSecondIsUnavailable() throws {
        let status = try XCTUnwrap(
            CameraSourceRateStatus.select(supportedMaximumFrameRate: 29.97)
        )

        XCTAssertEqual(status.selectedFrameRate, 29.97, accuracy: 0.000001)
        XCTAssertTrue(status.isFallback)
        XCTAssertTrue(status.summary.contains("fallback"))
    }

    func testCameraSourceRateRejectsAnInvalidSupportedRate() {
        XCTAssertNil(CameraSourceRateStatus.select(supportedMaximumFrameRate: 0.0))
    }

    func testIdentityAndNextSequenceSurviveStoreRestart() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }

        let startedAt = Date(timeIntervalSince1970: 1_756_000_000.125)
        let firstStore = CaptureSessionIdentityStore(directory: directory)
        let firstSession = try firstStore.startSession(startedAtUTC: startedAt)

        XCTAssertEqual(try firstSession.reserveEventSequence(), 1)
        XCTAssertEqual(firstSession.nextEventSequence, 2)

        let stateJSON = try XCTUnwrap(
            JSONSerialization.jsonObject(
                with: Data(contentsOf: firstStore.stateURL)
            ) as? [String: Any]
        )
        XCTAssertEqual(
            Set(stateJSON.keys),
            Set(["session_id", "started_at_utc", "next_event_sequence"])
        )
        XCTAssertEqual(stateJSON["session_id"] as? String, firstSession.sessionID.uuidString.lowercased())
        XCTAssertEqual(stateJSON["started_at_utc"] as? String, "2025-08-24T01:46:40.125Z")
        XCTAssertEqual(stateJSON["next_event_sequence"] as? Int, 2)

        let restartedStore = CaptureSessionIdentityStore(directory: directory)
        let resumedSession = try XCTUnwrap(restartedStore.resumeSession())
        XCTAssertEqual(resumedSession.sessionID, firstSession.sessionID)
        XCTAssertEqual(resumedSession.startedAtUTC, startedAt)
        XCTAssertEqual(try resumedSession.reserveEventSequence(), 2)

        let thirdStore = CaptureSessionIdentityStore(directory: directory)
        let resumedAgain = try XCTUnwrap(thirdStore.resumeSession())
        XCTAssertEqual(try resumedAgain.reserveEventSequence(), 3)
    }

    func testNormalEndRemovesOnlyTheMatchingActiveSession() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }

        let store = CaptureSessionIdentityStore(directory: directory)
        let session = try store.startSession()
        try store.endSession(sessionID: UUID())
        XCTAssertNotNil(try store.resumeSession())

        try store.endSession(sessionID: session.sessionID)
        XCTAssertNil(try store.resumeSession())
    }

    func testSessionClockUsesStableMediaTimelineAndUTCAnchor() throws {
        let startedAt = Date(timeIntervalSince1970: 1_756_000_000)
        let session = CaptureSession(startedAtUTC: startedAt)
        session.clock.observe(CMTime(seconds: 100.0, preferredTimescale: 1_000))

        XCTAssertEqual(
            session.clock.elapsedMilliseconds(for: CMTime(seconds: 101.25, preferredTimescale: 1_000)),
            1_250
        )
        XCTAssertEqual(
            session.clock.utcDate(for: CMTime(seconds: 101.25, preferredTimescale: 1_000)),
            startedAt.addingTimeInterval(1.25)
        )
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}
