import CoreMedia
import Foundation
import XCTest
@testable import CardEventProbeCore

final class RoundRecordingTests: XCTestCase {
    func testRoundSetupUsesFixedSeatsAndDerivesRoundIDFromRecordingID() throws {
        let setup = try defaultSetup(recordingID: "recording-fixture-001")

        XCTAssertEqual(setup.roundID, "round-recording-fixture-001")
        XCTAssertEqual(setup.activePlayers, ["seat-1", "seat-2", "seat-3", "seat-4"])
        XCTAssertEqual(setup.ruleset, try RoundRecordingRuleset())
        XCTAssertEqual(setup.deckVariant, "doko-40-v1")

        XCTAssertEqual(setup.dealer, "seat-1")
        XCTAssertEqual(setup.firstTrickLeader, "seat-1")
    }

    func testRoundStateStorePreservesOrderedMembershipAcrossStopAndRestart() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }

        let setup = try defaultSetup(recordingID: "recording-fixture-001")
        let sessionID = UUID()
        let packageOne = UUID()
        let packageTwo = UUID()
        let startedAt = Date(timeIntervalSince1970: 1_756_000_000.125)
        let store = RoundRecordingStateStore(directory: directory)
        try store.save(
            RoundRecordingState(
                recordingID: "recording-fixture-001",
                sessionID: sessionID,
                roundSetup: setup,
                startedAtUTC: startedAt
            )
        )

        XCTAssertNotNil(
            try store.appendEvidencePackage(
                packageOne,
                recordingID: "recording-fixture-001",
                sessionID: sessionID
            )
        )
        XCTAssertNil(
            try store.appendEvidencePackage(
                UUID(),
                recordingID: "recording-fixture-002",
                sessionID: sessionID
            )
        )
        XCTAssertNotNil(
            try store.closeEvidenceMembership(
                recordingID: "recording-fixture-001",
                at: startedAt.addingTimeInterval(4.0)
            )
        )

        // Finalized pending evidence can arrive after the stop boundary.
        XCTAssertNotNil(
            try store.appendEvidencePackage(
                packageTwo,
                recordingID: "recording-fixture-001",
                sessionID: sessionID
            )
        )
        try store.acknowledgeEvidencePackage(
            packageTwo,
            recordingID: "recording-fixture-001"
        )
        try store.acknowledgeEvidencePackage(
            packageOne,
            recordingID: "recording-fixture-001"
        )
        try store.markRecordingBundleFinalized(recordingID: "recording-fixture-001")
        try store.markRecordingBundleAcknowledged(recordingID: "recording-fixture-001")

        let restarted = try XCTUnwrap(
            RoundRecordingStateStore(directory: directory).load()
        )
        XCTAssertEqual(restarted.recordingID, "recording-fixture-001")
        XCTAssertEqual(restarted.sessionID, sessionID)
        XCTAssertEqual(restarted.startedAtUTC, startedAt)
        XCTAssertEqual(restarted.evidencePackageIDs, [packageOne, packageTwo])
        XCTAssertEqual(restarted.acknowledgedEvidencePackageIDs, [packageTwo, packageOne])
        XCTAssertTrue(restarted.evidenceMembershipClosed)
        XCTAssertTrue(restarted.recordingBundleFinalized)
        XCTAssertTrue(restarted.recordingBundleAcknowledged)
        XCTAssertTrue(restarted.allEvidencePackagesAcknowledged)
    }

    func testRecordingProfilePurposeDoesNotRequireRoundSetupInput() {
        let profile = RecordingProfile(
            profileID: "profile-fixture-001",
            name: "Fixture profile",
            purpose: .plausibleStagedRound,
            tags: ["normal_card_play"]
        )

        XCTAssertTrue(profile.isComplete)
    }

    func testUnifiedFlowSnapshotsAdapterInputsAndWaitsForAcknowledgements() throws {
        let context = AppRunContext(
            sessionID: UUID(uuidString: "550e8400-e29b-41d4-a716-446655440010")!
        )
        let packageID = UUID(uuidString: "00000000-0000-0000-0000-000000000044")!

        for (purpose, sourceGameID, analysisGameID) in [
            (.plausibleStagedRound, nil, "analysis-game-550e8400-e29b-41d4-a716-446655440010"),
            (.realGame, "game-550e8400-e29b-41d4-a716-446655440010", "game-550e8400-e29b-41d4-a716-446655440010"),
        ] as [(RecordingPurpose, String?, String)] {
            let profile = RecordingProfile(
                profileID: "profile-\(purpose.rawValue)",
                name: "Fixture profile",
                purpose: purpose,
                tags: ["fixture"]
            )
            let snapshot = try RecordingStartSnapshot(
                recordingID: "recording-\(purpose.rawValue)",
                startedAtUTC: "2026-08-31T10:00:00Z",
                profile: profile,
                operatorSettings: OperatorSettings(operatorName: "fixture-operator"),
                appRunContext: context
            )
            let setup = try snapshot.makeRoundSetup()
            var state = try RoundRecordingState(
                recordingID: snapshot.recordingID,
                sessionID: context.sessionID,
                roundSetup: setup
            )

            XCTAssertEqual(snapshot.collectionMetadata.gameID, sourceGameID)
            XCTAssertEqual(setup.gameID, analysisGameID)
            XCTAssertEqual(state.roundAnalysisSubmissionReadiness, .waitingForUploads)

            state = try state.addingEvidencePackage(packageID)
            state = try state.closingEvidenceMembership()
            state = state.markingRecordingBundleFinalized()
            state = state.markingRecordingBundleAcknowledged()
            XCTAssertEqual(state.roundAnalysisSubmissionReadiness, .waitingForUploads)

            state = try state.acknowledgingEvidencePackage(packageID)
            XCTAssertEqual(state.roundAnalysisSubmissionReadiness, .ready)
            let submission = try RoundAnalysisSubmissionState(
                recordingID: state.recordingID,
                sessionID: state.sessionID,
                roundSetup: state.roundSetup,
                evidencePackageIDs: state.evidencePackageIDs,
                analysisID: UUID(),
                phase: .submitting
            )
            XCTAssertEqual(submission.createRequest?.roundSetup.gameID, analysisGameID)
        }
    }

    func testEvidenceCoordinatorDoesNotReserveOrPersistOutsideActiveRecording() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }

        let sessionID = UUID()
        let captureSession = CaptureSession(
            sessionID: sessionID,
            startedAtUTC: Date(timeIntervalSince1970: 1_756_000_000)
        )
        let configuration = EvidenceCaptureConfiguration(
            targetHz: 8.0,
            jpegQuality: 0.85,
            historySeconds: 3.0,
            targetOffsetsMs: [0],
            maximumLookupDistanceMs: 10,
            finalizationDelayMs: 100
        )
        let store = EvidencePackageStore(root: root)
        var packageURLs: [URL] = []
        let coordinator = EvidencePackageCoordinator(
            configuration: configuration,
            captureSession: captureSession,
            ring: EvidenceFrameRing(configuration: configuration),
            store: store,
            model: model(),
            decoderConfiguration: decoderConfiguration(),
            client: client(),
            camera: camera(),
            requiresActiveRecording: true
        ) { result in
            if case let .success(url) = result {
                packageURLs.append(url)
            }
        }

        coordinator.consume(
            prediction(at: 0.0, score: 0.9),
            event: event(at: 0.0, emittedAt: 0.125)
        )
        coordinator.drain()
        XCTAssertEqual(coordinator.pendingEventCount, 0)
        XCTAssertEqual(captureSession.nextEventSequence, 1)
        XCTAssertTrue(packageURLs.isEmpty)

        coordinator.setRecordingID("recording-fixture-001")
        coordinator.consume(
            prediction(at: 0.2, score: 0.9),
            event: event(at: 0.2, emittedAt: 0.325)
        )
        coordinator.finish()
        coordinator.drain()

        let packageURL = try XCTUnwrap(packageURLs.first)
        let package = try store.loadPackage(at: packageURL)
        XCTAssertEqual(package.manifest.session.sessionID, sessionID)
        XCTAssertEqual(package.manifest.session.eventSequence, 1)
        XCTAssertEqual(
            package.repositoryMetadata?.lineage.parentRecordingID,
            "recording-fixture-001"
        )
        XCTAssertEqual(
            package.repositoryMetadata?.lineage.sessionID,
            sessionID.uuidString.lowercased()
        )
    }

    private func model() -> EvidencePackageModelMetadata {
        EvidencePackageModelMetadata(
            name: "CardEventNet",
            version: "test",
            weightsSHA256: String(repeating: "a", count: 64),
            preprocessing: "full_frame_letterbox_v1"
        )
    }

    private func defaultSetup(recordingID: String) throws -> RoundRecordingSetup {
        try DefaultRoundAnalysisSetup().makeRoundSetup(
            recordingID: recordingID,
            purpose: .realGame,
            appRunContext: AppRunContext(
                sessionID: UUID(uuidString: "550e8400-e29b-41d4-a716-446655440010")!
            )
        )
    }

    private func decoderConfiguration() -> CausalEventDecoder.Configuration {
        CausalEventDecoder.Configuration(
            threshold: 0.34,
            peakConfirmation: time(0.125),
            minimumEventGap: time(0.625)
        )
    }

    private func client() -> EvidencePackageClientMetadata {
        EvidencePackageClientMetadata(
            appVersion: "test",
            build: "1",
            deviceModelIdentifier: "test-device",
            osVersion: "test-os"
        )
    }

    private func camera() -> EvidencePackageCameraMetadata {
        EvidencePackageCameraMetadata(
            position: "back",
            orientation: "up",
            width: 1920,
            height: 1080
        )
    }

    private func event(at timestamp: Double, emittedAt: Double) -> DetectionEvent {
        DetectionEvent(
            id: UUID(),
            timestamp: time(timestamp),
            emittedAt: time(emittedAt),
            peakProbability: 0.9
        )
    }

    private func prediction(at timestamp: Double, score: Double) -> ModelPrediction {
        ModelPrediction(
            timestamp: time(timestamp),
            cardEventProbability: score,
            inferenceDurationMs: 1.0
        )
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }

    private func time(_ seconds: Double) -> CMTime {
        CMTime(seconds: seconds, preferredTimescale: 1_000)
    }
}
