import CoreMedia
import Foundation
import XCTest
@testable import CardEventProbeCore

final class RoundRecordingTests: XCTestCase {
    func testRoundSetupUsesFixedSeatsAndDerivesRoundIDFromRecordingID() throws {
        let setup = try RoundRecordingSetup(
            gameID: "game-fixture-001",
            recordingID: "recording-fixture-001",
            dealer: "seat-2",
            firstTrickLeader: "seat-3"
        )

        XCTAssertEqual(setup.roundID, "round-recording-fixture-001")
        XCTAssertEqual(setup.activePlayers, ["seat-1", "seat-2", "seat-3", "seat-4"])
        XCTAssertEqual(setup.ruleset, try RoundRecordingRuleset())
        XCTAssertEqual(setup.deckVariant, "doko-40-v1")

        XCTAssertThrowsError(
            try RoundRecordingSetup(
                gameID: "game-fixture-001",
                recordingID: "recording-fixture-001",
                dealer: "player-2",
                firstTrickLeader: "seat-3"
            )
        ) { error in
            XCTAssertEqual(error as? RoundRecordingSetupError, .invalidDealer)
        }
    }

    func testRoundStateStorePreservesOrderedMembershipAcrossStopAndRestart() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }

        let setup = try RoundRecordingSetup(
            gameID: "game-fixture-001",
            recordingID: "recording-fixture-001",
            dealer: "seat-1",
            firstTrickLeader: "seat-1"
        )
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

    func testRoundProfileRequiresRealGameAndUUIDSession() {
        var profile = CollectionProfile(
            profileID: "profile-fixture-001",
            name: "Fixture profile",
            operatorName: "fixture-operator",
            sessionID: "session-fixture-001",
            activity: .stagedActivity,
            gameID: nil,
            tableSetup: "table-fixture-v1",
            cardDeck: "doko-40-v1",
            cameraView: "overhead",
            cameraMotion: "fixed",
            cameraFraming: "table_fills_frame",
            lighting: ["room_light"],
            background: "wood table",
            scenarioTags: ["normal_card_play"],
            knownLimitations: ["single_actor"],
            sourcePermission: "training_and_evaluation"
        )

        XCTAssertFalse(profile.isCompleteRoundRecordingProfile)
        XCTAssertTrue(profile.roundRecordingValidationIssues.contains { $0.field == .activity })
        XCTAssertTrue(profile.roundRecordingValidationIssues.contains { $0.field == .sessionID })

        profile.activity = .realGame
        profile.gameID = "game-fixture-001"
        profile.sessionID = UUID().uuidString

        XCTAssertTrue(profile.isCompleteRoundRecordingProfile)
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
