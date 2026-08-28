import Foundation
import XCTest
@testable import CardEventProbeCore

final class CollectionProfileTests: XCTestCase {
    func testProfilePersistenceRoundTripsSessionDefaultsAndTaskDispositions() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let profile = validProfile()
        let store = CollectionProfileStore(directory: root)

        try store.save(profile)

        XCTAssertEqual(try store.load(profileID: profile.profileID), profile)
        XCTAssertEqual(try store.loadAll(), [profile])
        XCTAssertEqual(profile.sessionID, "session-fixture-001")
        XCTAssertEqual(profile.taskSettings.count, 2)
    }

    func testPerRecordingOverrideChangesEnrollmentWithoutChangingSavedProfile() throws {
        let profile = validProfile()
        let originalProfile = profile
        let overrides = [
            CollectionTaskDispositionOverride(
                task: .tableEvidenceAnalysis,
                disposition: .deferred
            )
        ]

        let enrollments = try profile.makeTaskEnrollments(
            recordingID: "recording-fixture-001",
            createdAtUTC: "2026-08-28T08:00:00Z",
            overrides: overrides
        )

        let tableEnrollment = try XCTUnwrap(
            enrollments.first { $0.task == .tableEvidenceAnalysis }
        )
        XCTAssertEqual(tableEnrollment.disposition, .deferred)
        XCTAssertEqual(tableEnrollment.lifecycleState, "intake")
        XCTAssertEqual(tableEnrollment.reason, nil)
        XCTAssertEqual(profile, originalProfile)
        XCTAssertEqual(
            profile.taskSetting(for: .tableEvidenceAnalysis)?.disposition,
            .selected
        )
    }

    func testInvalidProfileReportsFieldLevelValidation() {
        var profile = CollectionProfile.newDraft()
        profile.operatorName = ""
        profile.tableSetup = ""
        profile.activity = .realGame
        profile.gameID = nil

        let fields = Set(profile.validationIssues.map(\.field))

        XCTAssertTrue(fields.contains(.operatorName))
        XCTAssertTrue(fields.contains(.tableSetup))
        XCTAssertTrue(fields.contains(.gameID))
        XCTAssertFalse(profile.isComplete)
    }

    private func validProfile() -> CollectionProfile {
        var profile = CollectionProfile.newDraft(
            profileID: "profile-fixture-001",
            sessionID: "session-fixture-001"
        )
        profile.name = "Fixture collection"
        profile.operatorName = "fixture-operator"
        profile.activity = .realGame
        profile.gameID = "game-fixture-001"
        profile.tableSetup = "table-fixture-v1"
        profile.cardDeck = "doko-48-v1"
        profile.cameraView = "overhead"
        profile.cameraMotion = "fixed"
        profile.cameraFraming = "table_fills_frame"
        profile.lighting = ["room_light"]
        profile.background = "wood table"
        profile.scenarioTags = ["normal_card_play"]
        profile.knownLimitations = ["single_actor"]
        profile.sourcePermission = "training_and_evaluation"
        return profile
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}
