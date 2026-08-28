import CoreMedia
import CoreVideo
import Foundation
import ImageIO
import XCTest
@testable import CardEventProbeCore

final class TrainingRecordingCoordinatorTests: XCTestCase {
    func testFinalizesValidatedBundleAndWritesOneSharedTimeline() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let writer = FakeVideoWriterFactory()
        let coordinator = TrainingRecordingCoordinator(
            configuration: configuration(root: root),
            writerFactory: writer
        )

        try coordinator.start()
        coordinator.consume(frame(at: 100.0))
        coordinator.drain()
        coordinator.consume(
            ModelPrediction(
                timestamp: time(100.0),
                cardEventProbability: 0.8,
                inferenceDurationMs: 10.0
            ),
            event: DetectionEvent(
                timestamp: time(100.0),
                emittedAt: time(100.1),
                peakProbability: 0.8
            )
        )
        coordinator.consume(frame(at: 100.1))
        coordinator.drain()
        coordinator.consume(
            ModelPrediction(
                timestamp: time(100.1),
                cardEventProbability: 0.2,
                inferenceDurationMs: 11.0
            )
        )

        let result = waitForStop(coordinator)
        let bundleURL = try XCTUnwrap(try result.get())
        let manifestData = try Data(contentsOf: bundleURL.appendingPathComponent("manifest.json"))
        let predictionsURL = bundleURL.appendingPathComponent("video-fixture-001.json")
        let predictionsData = try Data(contentsOf: predictionsURL)
        let videoURL = bundleURL.appendingPathComponent("video-fixture-001.mov")
        let validated = try validateTrainingRecordingBundle(
            manifestData: manifestData,
            predictionsData: predictionsData,
            videoURL: videoURL
        )

        XCTAssertEqual(validated.1.probabilities.count, 2)
        XCTAssertEqual(validated.1.probabilities[0].timeS, 0.0, accuracy: 0.000001)
        XCTAssertEqual(validated.1.probabilities[1].timeS, 0.1, accuracy: 0.000001)
        XCTAssertEqual(validated.1.eventProposals.count, 1)
        XCTAssertEqual(validated.1.eventProposals[0].emittedAtS, 0.1, accuracy: 0.000001)
        XCTAssertEqual(validated.0.collectionMetadata.collectionProfileID, "profile-fixture-001")
        XCTAssertEqual(validated.0.collectionMetadata.tableSetup, "table-fixture-v1")
        XCTAssertEqual(
            validated.0.taskEnrollments.map(\.task),
            RepositoryDataTask.allCases
        )
        XCTAssertEqual(coordinator.metrics.receivedFrameCount, 2)
        XCTAssertEqual(coordinator.metrics.writtenFrameCount, 2)
        XCTAssertEqual(coordinator.metrics.droppedFrameCount, 0)
        XCTAssertEqual(writer.makeCount, 1)
    }

    func testIgnoresResultsCapturedBeforeRecordingStarted() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let writer = FakeVideoWriterFactory()
        let coordinator = TrainingRecordingCoordinator(
            configuration: configuration(root: root),
            writerFactory: writer
        )

        try coordinator.start()
        coordinator.consume(frame(at: 100.0))
        coordinator.drain()

        // A live inference can finish for a frame captured just before recording started.
        coordinator.consume(
            ModelPrediction(
                timestamp: time(99.9),
                cardEventProbability: 0.8,
                inferenceDurationMs: 10.0
            )
        )
        coordinator.consume(
            ModelPrediction(
                timestamp: time(100.0),
                cardEventProbability: 0.2,
                inferenceDurationMs: 11.0
            ),
            event: DetectionEvent(
                timestamp: time(99.9),
                emittedAt: time(100.0),
                peakProbability: 0.8
            )
        )

        let result = waitForStop(coordinator)
        let bundleURL = try XCTUnwrap(try result.get())
        let manifestData = try Data(contentsOf: bundleURL.appendingPathComponent("manifest.json"))
        let predictionsData = try Data(
            contentsOf: bundleURL.appendingPathComponent("video-fixture-001.json")
        )
        let validated = try validateTrainingRecordingBundle(
            manifestData: manifestData,
            predictionsData: predictionsData,
            videoURL: bundleURL.appendingPathComponent("video-fixture-001.mov")
        )

        XCTAssertEqual(validated.1.probabilities.count, 1)
        XCTAssertEqual(validated.1.probabilities[0].timeS, 0.0, accuracy: 0.000001)
        XCTAssertTrue(validated.1.eventProposals.isEmpty)
        XCTAssertEqual(coordinator.metrics.predictionSampleCount, 1)
        XCTAssertEqual(coordinator.metrics.eventProposalCount, 0)
    }

    func testDuplicateStopFinishesWriterOnlyOnce() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let writer = FakeVideoWriterFactory()
        let coordinator = TrainingRecordingCoordinator(
            configuration: configuration(root: root),
            writerFactory: writer
        )

        try coordinator.start()
        coordinator.consume(frame(at: 10.0))

        let first = DispatchSemaphore(value: 0)
        let second = DispatchSemaphore(value: 0)
        var firstResult: Result<URL, Error>?
        var secondResult: Result<URL, Error>?
        coordinator.stop { result in
            firstResult = result
            first.signal()
        }
        coordinator.stop { result in
            secondResult = result
            second.signal()
        }

        XCTAssertEqual(first.wait(timeout: .now() + 3), .success)
        XCTAssertEqual(second.wait(timeout: .now() + 3), .success)
        let firstURL = try XCTUnwrap(try firstResult?.get())
        let secondURL = try XCTUnwrap(try secondResult?.get())
        XCTAssertEqual(firstURL, secondURL)
        XCTAssertEqual(writer.writer?.finishCount, 1)
        XCTAssertEqual(coordinator.state, .completed(firstURL))
    }

    func testSlowWriterDropsFramesWithoutBlockingTheCaller() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let gate = DispatchSemaphore(value: 0)
        let writer = FakeVideoWriterFactory(appendGate: gate)
        let coordinator = TrainingRecordingCoordinator(
            configuration: configuration(root: root),
            writerFactory: writer
        )

        try coordinator.start()
        let start = DispatchTime.now().uptimeNanoseconds
        coordinator.consume(frame(at: 20.0))
        coordinator.consume(frame(at: 20.1))
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000.0

        XCTAssertLessThan(elapsedMs, 100.0)
        XCTAssertEqual(coordinator.metrics.droppedFrameCount, 1)

        gate.signal()
        let result = waitForStop(coordinator)
        XCTAssertNoThrow(try result.get())
        XCTAssertEqual(coordinator.metrics.writtenFrameCount, 1)
    }

    func testWriterFailureIsReportedAndDoesNotProduceACompleteBundle() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let writer = FakeVideoWriterFactory(appendResult: false)
        let coordinator = TrainingRecordingCoordinator(
            configuration: configuration(root: root),
            writerFactory: writer
        )

        try coordinator.start()
        coordinator.consume(frame(at: 30.0))
        XCTAssertTrue(waitUntil { if case .failed = coordinator.state { return true }; return false })

        let result = waitForStop(coordinator)
        XCTAssertThrowsError(try result.get())
        XCTAssertEqual(writer.writer?.finishCount, 1)
        XCTAssertFalse(
            FileManager.default.fileExists(
                atPath: root.appendingPathComponent("recording-fixture-001").path
            )
        )
    }

    private func configuration(root: URL) -> TrainingRecordingConfiguration {
        let profile = validProfile()
        return TrainingRecordingConfiguration(
            outputRoot: root,
            recordingID: "recording-fixture-001",
            sessionID: "session-fixture-001",
            videoID: "video-fixture-001",
            startedAtUTC: Date(timeIntervalSince1970: 1_756_000_000),
            model: TrainingRecordingModel(
                name: "CardEventNet",
                version: "transition-v2",
                weightsSHA256: String(repeating: "a", count: 64),
                preprocessing: "full-frame-letterbox-v1"
            ),
            decoder: TrainingRecordingDecoder(
                algorithm: "causal-peak-v1",
                threshold: 0.5,
                peakConfirmationS: 0.125,
                minimumEventGapS: 0.625
            ),
            client: TrainingRecordingClient(
                appVersion: "0.1.0",
                build: "1",
                deviceModel: "fixture-mac",
                osVersion: "macOS 15"
            ),
            sourcePermission: "training_and_evaluation",
            collectionMetadata: TrainingRecordingCollectionMetadata(profile: profile),
            taskEnrollments: try! profile.makeTaskEnrollments(
                recordingID: "recording-fixture-001",
                createdAtUTC: "2026-08-28T08:00:00Z"
            ),
            frameRate: 10.0
        )
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
        profile.sourcePermission = "training_and_evaluation"
        return profile
    }

    private func frame(at timestamp: Double) -> VideoFrame {
        var pixelBuffer: CVPixelBuffer?
        XCTAssertEqual(
            CVPixelBufferCreate(
                kCFAllocatorDefault,
                640,
                360,
                kCVPixelFormatType_32BGRA,
                nil,
                &pixelBuffer
            ),
            kCVReturnSuccess
        )
        return VideoFrame(
            pixelBuffer: pixelBuffer!,
            timestamp: time(timestamp),
            orientation: .up
        )
    }

    private func time(_ seconds: Double) -> CMTime {
        CMTime(seconds: seconds, preferredTimescale: 600)
    }

    private func waitForStop(_ coordinator: TrainingRecordingCoordinator) -> Result<URL, Error> {
        let semaphore = DispatchSemaphore(value: 0)
        var result: Result<URL, Error>?
        coordinator.stop { received in
            result = received
            semaphore.signal()
        }
        XCTAssertEqual(semaphore.wait(timeout: .now() + 3), .success)
        return result ?? .failure(TrainingRecordingError.finalizationFailed("no result"))
    }

    private func waitUntil(_ predicate: @escaping () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(3)
        while Date() < deadline {
            if predicate() { return true }
            Thread.sleep(forTimeInterval: 0.01)
        }
        return predicate()
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}

private final class FakeVideoWriterFactory: TrainingRecordingVideoWriterFactory {
    let appendResult: Bool
    let appendGate: DispatchSemaphore?
    private(set) var makeCount = 0
    private(set) var writer: FakeVideoWriter?

    init(appendResult: Bool = true, appendGate: DispatchSemaphore? = nil) {
        self.appendResult = appendResult
        self.appendGate = appendGate
    }

    func makeWriter(
        outputURL: URL,
        width: Int,
        height: Int,
        frameRate: Double
    ) throws -> any TrainingRecordingVideoWriter {
        makeCount += 1
        let writer = FakeVideoWriter(
            outputURL: outputURL,
            width: width,
            height: height,
            frameRate: frameRate,
            appendResult: appendResult,
            appendGate: appendGate
        )
        self.writer = writer
        return writer
    }
}

private final class FakeVideoWriter: TrainingRecordingVideoWriter {
    let outputURL: URL
    let output: TrainingRecordingVideoWriterOutput
    let appendResult: Bool
    let appendGate: DispatchSemaphore?
    private(set) var finishCount = 0

    init(
        outputURL: URL,
        width: Int,
        height: Int,
        frameRate: Double,
        appendResult: Bool,
        appendGate: DispatchSemaphore?
    ) {
        self.outputURL = outputURL
        output = TrainingRecordingVideoWriterOutput(width: width, height: height, frameRate: frameRate)
        self.appendResult = appendResult
        self.appendGate = appendGate
        try? Data("fake h264 bytes".utf8).write(to: outputURL)
    }

    var isReadyForMoreMediaData: Bool { true }

    func append(_ frame: VideoFrame, presentationTime: CMTime) -> Bool {
        _ = appendGate?.wait(timeout: .now() + 3)
        return appendResult
    }

    func finish(completion: @escaping (Result<TrainingRecordingVideoWriterOutput, Error>) -> Void) {
        finishCount += 1
        completion(.success(output))
    }
}
