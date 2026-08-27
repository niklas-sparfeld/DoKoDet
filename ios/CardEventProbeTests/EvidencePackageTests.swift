import CoreMedia
import Foundation
import XCTest
@testable import CardEventProbeCore

final class EvidencePackageTests: XCTestCase {
    func testCompletePackageStoresFullFrameBytesAndHashes() throws {
        let configuration = configuration(targetOffsetsMs: [-100, 0, 100])
        let clock = clock()
        let ring = EvidenceFrameRing(configuration: configuration)
        ring.append(encodedFrame(at: 0.9, value: 1))
        ring.append(encodedFrame(at: 1.0, value: 2))
        ring.append(encodedFrame(at: 1.1, value: 3))

        let package = try assembler(
            configuration: configuration,
            clock: clock
        ).assemble(
            event: event(at: 1.0, emittedAt: 1.125),
            eventSequence: 1,
            packageID: packageID(0),
            ring: ring,
            camera: camera(),
            scoreTrace: [prediction(at: 1.0, score: 0.92)]
        )

        XCTAssertEqual(package.manifest.event.eventTimeMs, 1_000)
        XCTAssertEqual(package.manifest.event.emittedAtMs, 1_125)
        XCTAssertTrue(package.manifest.event.evidenceComplete)
        XCTAssertEqual(package.manifest.frames.map(\.targetOffsetMs), [-100, 0, 100])
        XCTAssertEqual(package.manifest.frames.map(\.byteLength), [1, 1, 1])
        XCTAssertEqual(package.frames.map(\.jpegData), [Data([1]), Data([2]), Data([3])])

        let encodedManifest = try package.manifest.encoded()
        let json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encodedManifest) as? [String: Any]
        )
        XCTAssertEqual(json["schema_version"] as? String, "cardevent-evidence/v2")
        XCTAssertNotNil(json["missing_frame_targets_ms"])
        let eventJSON = try XCTUnwrap(json["event"] as? [String: Any])
        XCTAssertEqual(eventJSON["event_time_ms"] as? Int, 1_000)
        XCTAssertNil(eventJSON["peak_probability"])
        let clientJSON = try XCTUnwrap(json["client"] as? [String: Any])
        XCTAssertEqual(clientJSON["device_model_identifier"] as? String, "test-device")
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let decodedManifest = try decoder.decode(EvidencePackageManifest.self, from: encodedManifest)
        XCTAssertEqual(decodedManifest.packageID, package.manifest.packageID)
        XCTAssertEqual(decodedManifest.frames.map(\.sha256), package.manifest.frames.map(\.sha256))
        XCTAssertEqual(
            decodedManifest.frames[0].capturedAtUTC.timeIntervalSince(
                package.manifest.frames[0].capturedAtUTC
            ),
            0.0,
            accuracy: 0.001
        )

        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let packageURL = try EvidencePackageStore(root: root).persist(package)
        XCTAssertEqual(
            try Data(contentsOf: packageURL.appendingPathComponent("frames/frame_00.jpg")),
            Data([1])
        )
        XCTAssertFalse(
            FileManager.default.fileExists(
                atPath: root.appendingPathComponent(".staging-").path
            )
        )
    }

    func testIncompletePackageListsMissingTargetsAndIsPersisted() throws {
        let configuration = configuration(targetOffsetsMs: [-100, 0, 100])
        let clock = clock()
        let ring = EvidenceFrameRing(configuration: configuration)
        ring.append(encodedFrame(at: 1.0, value: 2))

        let package = try assembler(
            configuration: configuration,
            clock: clock
        ).assemble(
            event: event(at: 1.0, emittedAt: 1.125),
            eventSequence: 2,
            packageID: packageID(1),
            ring: ring,
            camera: camera()
        )

        XCTAssertFalse(package.manifest.event.evidenceComplete)
        XCTAssertEqual(package.manifest.missingFrameTargetsMs, [-100, 100])
        XCTAssertEqual(package.frames.count, 1)

        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let packageURL = try EvidencePackageStore(root: root).persist(package)
        XCTAssertTrue(FileManager.default.fileExists(atPath: packageURL.appendingPathComponent("manifest.json").path))
        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(
                at: packageURL.appendingPathComponent("frames"),
                includingPropertiesForKeys: nil
            ).count,
            1
        )
    }

    func testMetadataOnlyPackageIsValid() throws {
        let configuration = configuration(targetOffsetsMs: [-100, 0, 100])
        let clock = clock()
        let package = try assembler(
            configuration: configuration,
            clock: clock
        ).assemble(
            event: event(at: 1.0, emittedAt: 1.125),
            eventSequence: 3,
            packageID: packageID(2),
            ring: EvidenceFrameRing(configuration: configuration),
            camera: camera()
        )

        XCTAssertTrue(package.frames.isEmpty)
        XCTAssertEqual(package.manifest.missingFrameTargetsMs, [-100, 0, 100])
        XCTAssertFalse(package.manifest.event.evidenceComplete)

        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let packageURL = try EvidencePackageStore(root: root).persist(package)
        XCTAssertTrue(FileManager.default.fileExists(atPath: packageURL.appendingPathComponent("manifest.json").path))
        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(
                at: packageURL.appendingPathComponent("frames"),
                includingPropertiesForKeys: nil
            ).count,
            0
        )
    }

    func testStoreCreatesQueueLayoutAndQueuesValidatedPackage() throws {
        let package = try completePackage(packageID: packageID(3))
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }

        let store = EvidencePackageStore(root: root)
        let packageURL = try store.persist(package)

        XCTAssertEqual(packageURL, store.packageURL(for: package.manifest.packageID))
        XCTAssertTrue(packageURL.path.contains("/queued/"))
        XCTAssertEqual(try store.loadPackage(at: packageURL).manifest, package.manifest)
        for state in EvidencePackageQueueState.allCases {
            XCTAssertTrue(FileManager.default.fileExists(atPath: store.directoryURL(for: state).path))
        }
        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(
                at: store.directoryURL(for: .staging),
                includingPropertiesForKeys: nil
            ).count,
            0
        )
    }

    func testStoreRejectsPackagesAboveTheQueuedByteCapacityBeforeStaging() throws {
        let package = try completePackage(packageID: packageID(30))
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }

        let store = EvidencePackageStore(root: root, queuedByteCapacity: 1)
        XCTAssertThrowsError(try store.persist(package)) { error in
            guard case let EvidencePackageStoreError.queuedByteCapacityExceeded(required, capacity) = error else {
                return XCTFail("unexpected error: \(error)")
            }
            XCTAssertGreaterThan(required, capacity)
        }
        XCTAssertEqual(try store.packageURLs(in: .staging).count, 0)
        XCTAssertEqual(try store.packageURLs(in: .queued).count, 0)
    }

    func testRecoveryQueuesCompleteStagingAndRetainsCorruptContent() throws {
        let package = try completePackage(packageID: packageID(4))
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }

        let store = EvidencePackageStore(root: root)
        let queuedURL = try store.persist(package)
        let stagedURL = store.directoryURL(for: .staging)
            .appendingPathComponent("interrupted-package", isDirectory: true)
        try FileManager.default.moveItem(at: queuedURL, to: stagedURL)

        let corruptURL = store.directoryURL(for: .staging)
            .appendingPathComponent("partial-package", isDirectory: true)
        try FileManager.default.createDirectory(at: corruptURL, withIntermediateDirectories: true)
        try Data("not a manifest".utf8).write(
            to: corruptURL.appendingPathComponent("manifest.json")
        )

        let diagnostics = try store.recover()

        XCTAssertEqual(diagnostics.recoveredPackageIDs, [package.manifest.packageID])
        XCTAssertEqual(diagnostics.stagingCount, 0)
        XCTAssertEqual(diagnostics.queuedCount, 1)
        XCTAssertEqual(diagnostics.corruptCount, 1)
        XCTAssertEqual(diagnostics.corruptPaths.count, 1)
        XCTAssertEqual(diagnostics.errors.count, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: store.packageURL(for: package.manifest.packageID).path))

        let retainedURL = URL(fileURLWithPath: try XCTUnwrap(diagnostics.corruptPaths.first))
        XCTAssertTrue(
            FileManager.default.fileExists(
                atPath: retainedURL.appendingPathComponent("manifest.json").path
            )
        )
    }

    func testRecoveryQuarantinesQueuedHashMismatch() throws {
        let package = try completePackage(packageID: packageID(5))
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }

        let store = EvidencePackageStore(root: root)
        let packageURL = try store.persist(package)
        let frameURL = packageURL
            .appendingPathComponent("frames", isDirectory: true)
            .appendingPathComponent("frame_01.jpg", isDirectory: false)
        try Data([0xFF]).write(to: frameURL)

        let diagnostics = try store.recover()

        XCTAssertEqual(diagnostics.queuedCount, 0)
        XCTAssertEqual(diagnostics.corruptCount, 1)
        XCTAssertEqual(diagnostics.corruptPaths.count, 1)
        XCTAssertTrue(diagnostics.errors.first?.contains("SHA-256") == true)
    }

    func testCoordinatorKeepsSessionAndRecordingCorrelationSeparate() throws {
        let sessionID = UUID()
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let coordinator = EvidencePackageCoordinator(
            configuration: configuration(targetOffsetsMs: [0]),
            sessionClock: clock(),
            sessionID: sessionID,
            ring: EvidenceFrameRing(configuration: configuration(targetOffsetsMs: [0])),
            store: EvidencePackageStore(root: root),
            model: model(),
            decoderConfiguration: decoderConfiguration(),
            client: client(),
            camera: camera(),
            recordingID: "recording-fixture-001"
        )

        XCTAssertEqual(coordinator.canonicalSessionID, sessionID)
        XCTAssertEqual(coordinator.recordingCorrelationID, "recording-fixture-001")
        XCTAssertEqual(coordinator.legacyCaptureSessionID, "recording-fixture-001")
        coordinator.setRecordingID("recording-fixture-002")
        XCTAssertEqual(coordinator.legacyCaptureSessionID, "recording-fixture-002")
    }

    func testCoordinatorFinalizesMultipleEventsIndependently() throws {
        let configuration = configuration(targetOffsetsMs: [0], finalizationDelayMs: 100)
        let clock = clock()
        let sessionRoot = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: sessionRoot) }
        let captureSession = try CaptureSessionIdentityStore(directory: sessionRoot)
            .startSession(startedAtUTC: clock.startedAtUTC)
        captureSession.clock.observe(time(0.0))
        let ring = EvidenceFrameRing(configuration: configuration)
        ring.append(encodedFrame(at: 0.0, value: 1))
        ring.append(encodedFrame(at: 0.1, value: 2))
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }

        var packageURLs: [URL] = []
        var reservedSequences: [(UUID, Int)] = []
        let coordinator = EvidencePackageCoordinator(
            configuration: configuration,
            captureSession: captureSession,
            ring: ring,
            store: EvidencePackageStore(root: root),
            model: model(),
            decoderConfiguration: decoderConfiguration(),
            client: client(),
            camera: camera()
        ) { result in
            if case let .success(url) = result {
                packageURLs.append(url)
            }
        } onEventSequenceReserved: { sessionID, sequence in
            reservedSequences.append((sessionID, sequence))
        }

        coordinator.consume(
            prediction(at: 0.0, score: 0.90),
            event: event(at: 0.0, emittedAt: 0.125)
        )
        coordinator.drain()
        XCTAssertEqual(coordinator.pendingEventCount, 1)

        coordinator.consume(
            prediction(at: 0.1, score: 0.20),
            event: event(at: 0.1, emittedAt: 0.225)
        )
        coordinator.drain()
        XCTAssertEqual(packageURLs.count, 1)
        XCTAssertEqual(coordinator.pendingEventCount, 1)

        coordinator.finish()
        coordinator.drain()
        XCTAssertEqual(packageURLs.count, 2)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifests = packageURLs.compactMap { url in
            try? decoder.decode(
                EvidencePackageManifest.self,
                from: (try? Data(contentsOf: url.appendingPathComponent("manifest.json"))) ?? Data()
            )
        }
        XCTAssertEqual(manifests.map(\.session.eventSequence), [1, 2])
        XCTAssertEqual(Set(manifests.map(\.packageID)).count, 2)
        XCTAssertEqual(captureSession.nextEventSequence, 3)
        XCTAssertEqual(reservedSequences.map(\.1), [1, 2])
        XCTAssertEqual(Set(reservedSequences.map(\.0)), Set([captureSession.sessionID]))
    }

    private func completePackage(packageID: UUID) throws -> EvidencePackage {
        let configuration = configuration(targetOffsetsMs: [-100, 0, 100])
        let clock = clock()
        let ring = EvidenceFrameRing(configuration: configuration)
        ring.append(encodedFrame(at: 0.9, value: 1))
        ring.append(encodedFrame(at: 1.0, value: 2))
        ring.append(encodedFrame(at: 1.1, value: 3))
        return try assembler(configuration: configuration, clock: clock).assemble(
            event: event(at: 1.0, emittedAt: 1.125),
            eventSequence: 1,
            packageID: packageID,
            ring: ring,
            camera: camera()
        )
    }

    private func assembler(
        configuration: EvidenceCaptureConfiguration,
        clock: EvidenceSessionClock
    ) -> EvidencePackageAssembler {
        EvidencePackageAssembler(
            configuration: configuration,
            sessionClock: clock,
            sessionID: packageID(20),
            model: model(),
            decoderConfiguration: decoderConfiguration(),
            client: client()
        )
    }

    private func configuration(
        targetOffsetsMs: [Int],
        finalizationDelayMs: Int = 900
    ) -> EvidenceCaptureConfiguration {
        EvidenceCaptureConfiguration(
            targetHz: 8.0,
            jpegQuality: 0.85,
            historySeconds: 3.0,
            targetOffsetsMs: targetOffsetsMs,
            maximumLookupDistanceMs: 10,
            finalizationDelayMs: finalizationDelayMs
        )
    }

    private func clock() -> EvidenceSessionClock {
        let clock = EvidenceSessionClock(startedAtUTC: Date(timeIntervalSince1970: 1_756_000_000))
        clock.observe(time(0.0))
        return clock
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
            threshold: 0.3442875146865845,
            peakConfirmation: time(0.125),
            minimumEventGap: time(0.625)
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

    private func client() -> EvidencePackageClientMetadata {
        EvidencePackageClientMetadata(
            appVersion: "test",
            build: "1",
            deviceModelIdentifier: "test-device",
            osVersion: "test-os"
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

    private func encodedFrame(at timestamp: Double, value: UInt8) -> EncodedEvidenceFrame {
        EncodedEvidenceFrame(
            timestamp: time(timestamp),
            jpegData: Data([value]),
            width: 1920,
            height: 1080
        )
    }

    private func packageID(_ value: UInt8) -> UUID {
        UUID(uuid: (value, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, value))
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
    }

    private func time(_ seconds: Double) -> CMTime {
        CMTime(seconds: seconds, preferredTimescale: 1_000)
    }
}
