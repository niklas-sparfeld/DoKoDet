import Foundation
import XCTest
@testable import CardEventProbeCore

final class RecordingProfileTests: XCTestCase {
    func testPurposeMappingUsesStableLabelsAndAppRunIDs() {
        let sessionID = UUID(uuidString: "550e8400-e29b-41d4-a716-446655440010")!
        let context = AppRunContext(sessionID: sessionID)

        XCTAssertEqual(RecordingPurpose.allCases.map(\.rawValue), [
            "weird_test_stuff",
            "approximate_forty_card_setup",
            "plausible_staged_round",
            "real_game",
        ])
        XCTAssertEqual(RecordingPurpose.weirdTestStuff.title, "Weird test stuff")
        XCTAssertEqual(
            RecordingPurpose.approximateFortyCardSetup.title,
            "Roughly forty cards in a roughly real-world camera setup"
        )
        XCTAssertEqual(
            RecordingPurpose.plausibleStagedRound.title,
            "Plausible round, but not real"
        )

        let staged = RecordingPurpose.plausibleStagedRound.mapping(for: context)
        XCTAssertEqual(staged.sourceContentType, "staged_scenario")
        XCTAssertNil(staged.sourceGameID)
        XCTAssertEqual(
            staged.analysisGameID,
            "analysis-game-550e8400-e29b-41d4-a716-446655440010"
        )

        let real = RecordingPurpose.realGame.mapping(for: context)
        XCTAssertEqual(real.sourceContentType, "real_game")
        XCTAssertEqual(real.sourceGameID, "game-550e8400-e29b-41d4-a716-446655440010")
        XCTAssertEqual(real.analysisGameID, real.sourceGameID)
    }

    func testRecordingProfileContainsOnlyNewOperatorSelectedValues() throws {
        let profile = validProfile()
        let data = try JSONEncoder().encode(profile)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )

        XCTAssertEqual(
            Set(object.keys),
            Set(["schema_version", "profile_id", "name", "purpose", "tags", "task_settings"])
        )
        XCTAssertEqual(try JSONDecoder().decode(RecordingProfile.self, from: data), profile)
        XCTAssertTrue(profile.isComplete)
    }

    func testRecordingProfileValidatesTagsAndEveryTaskSetting() {
        var profile = RecordingProfile.newDraft()

        XCTAssertFalse(profile.isComplete)
        XCTAssertEqual(
            Set(profile.validationIssues.map(\.field)),
            Set([.name, .tags])
        )

        profile.name = "Kitchen overhead"
        profile.tags = ["staged", "staged"]
        XCTAssertTrue(profile.validationIssues.contains { $0.field == .tags })

        profile.tags = ["staged"]
        profile.taskSettings = [
            RecordingTaskSetting(
                task: .cardEventDetection,
                disposition: .excluded,
                reason: nil
            ),
        ]
        XCTAssertTrue(profile.validationIssues.contains { $0.field == .taskSettings })

        profile.taskSettings = [
            RecordingTaskSetting(
                task: .cardEventDetection,
                disposition: .excluded,
                reason: "not useful for this staged case"
            ),
            RecordingTaskSetting(task: .tableEvidenceAnalysis),
        ]
        XCTAssertTrue(profile.isComplete)
    }

    func testMetadataAdapterAddsPurposeTagAndUsesFixedIntakeMetadata() throws {
        let context = AppRunContext(
            sessionID: UUID(uuidString: "550e8400-e29b-41d4-a716-446655440010")!
        )
        let operatorSettings = OperatorSettings(operatorName: "alice")
        let metadata = try RecordingMetadataAdapter().makeCollectionMetadata(
            profile: validProfile(purpose: .plausibleStagedRound),
            operatorSettings: operatorSettings,
            appRunContext: context
        )

        XCTAssertEqual(metadata.operatorName, "alice")
        XCTAssertEqual(metadata.contentType, "staged_scenario")
        XCTAssertNil(metadata.gameID)
        XCTAssertEqual(metadata.tableSetup, "default_table_setup")
        XCTAssertEqual(metadata.cardDeck, "french_common_back_v1")
        XCTAssertEqual(metadata.cameraView, "overhead")
        XCTAssertEqual(metadata.cameraMotion, "fixed")
        XCTAssertEqual(metadata.cameraFraming, "table_with_context")
        XCTAssertEqual(metadata.lighting, ["not_recorded"])
        XCTAssertEqual(metadata.background, "not_recorded")
        XCTAssertEqual(metadata.scenarioTags, ["kitchen", "plausible_staged_round"])
        XCTAssertEqual(metadata.knownLimitations, [])
        XCTAssertEqual(metadata.sourcePermission, "project_use")
        XCTAssertNil(metadata.notes)
    }

    func testDefaultRoundAnalysisSetupUsesDistinctStagedAndRealGameIDs() throws {
        let context = AppRunContext(
            sessionID: UUID(uuidString: "550e8400-e29b-41d4-a716-446655440010")!
        )
        let adapter = DefaultRoundAnalysisSetup()

        let staged = try adapter.makeRoundSetup(
            recordingID: "recording-001",
            purpose: .weirdTestStuff,
            appRunContext: context
        )
        XCTAssertEqual(staged.gameID, "analysis-game-550e8400-e29b-41d4-a716-446655440010")
        XCTAssertEqual(staged.roundID, "round-recording-001")
        XCTAssertEqual(staged.activePlayers, ["seat-1", "seat-2", "seat-3", "seat-4"])
        XCTAssertEqual(staged.dealer, "seat-1")
        XCTAssertEqual(staged.firstTrickLeader, "seat-1")

        let real = try adapter.makeRoundSetup(
            recordingID: "recording-002",
            purpose: .realGame,
            appRunContext: context
        )
        XCTAssertEqual(real.gameID, "game-550e8400-e29b-41d4-a716-446655440010")
    }

    func testOperatorSettingsAndTaskEnrollmentsUseSnapshotOperatorName() throws {
        let profile = validProfile()
        let enrollments = try profile.makeTaskEnrollments(
            recordingID: "recording-001",
            createdAtUTC: "2026-08-31T10:00:00Z",
            operatorSettings: OperatorSettings(operatorName: "alice")
        )

        XCTAssertEqual(enrollments.count, 2)
        XCTAssertEqual(Set(enrollments.map(\.task)), Set(RepositoryDataTask.allCases))
        XCTAssertTrue(enrollments.allSatisfy { $0.operator == "alice" })
    }

    private func validProfile(
        purpose: RecordingPurpose = .approximateFortyCardSetup
    ) -> RecordingProfile {
        RecordingProfile(
            profileID: "profile-fixture-001",
            name: "Kitchen overhead",
            purpose: purpose,
            tags: ["kitchen"],
            taskSettings: [
                RecordingTaskSetting(task: .cardEventDetection),
                RecordingTaskSetting(task: .tableEvidenceAnalysis),
            ]
        )
    }
}
