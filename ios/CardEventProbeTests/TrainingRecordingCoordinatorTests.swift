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
        coordinator.recordInferenceFailure(at: time(100.15), message: "fixture inference failure")

        let result = waitForStop(coordinator)
        let bundleURL = try XCTUnwrap(try result.get())
        let bundle = try validateRepositoryBundleDirectory(at: bundleURL)
        let proposalDescriptor = try XCTUnwrap(bundle.files.proposalGeneratorRuns.first)
        let proposal = try decodeRepositoryJSON(
            RepositoryProposalGeneratorRun.self,
            data: Data(contentsOf: bundleURL.appendingPathComponent(proposalDescriptor.relativePath))
        )
        let source = try decodeRepositoryJSON(
            RepositorySourceRecord.self,
            data: Data(contentsOf: bundleURL.appendingPathComponent(bundle.files.sourceRecord.relativePath))
        )
        let enrollments = try decodeRepositoryJSON(
            RepositoryTaskEnrollmentDocument.self,
            data: Data(contentsOf: bundleURL.appendingPathComponent(bundle.files.taskEnrollment.relativePath))
        )

        XCTAssertEqual(proposal.probabilities.count, 2)
        XCTAssertEqual(proposal.probabilities[0].timeS, 0.0, accuracy: 0.000001)
        XCTAssertEqual(proposal.probabilities[1].timeS, 0.1, accuracy: 0.000001)
        XCTAssertEqual(proposal.eventProposals.count, 1)
        XCTAssertEqual(proposal.eventProposals[0].emittedAtS, 0.1, accuracy: 0.000001)
        let timeline = try DeviceCaptureTimeline.load(from: bundleURL)
        XCTAssertEqual(timeline.recordingID, "recording-fixture-001")
        XCTAssertEqual(timeline.sourceTimeZero.cmTime, time(100.0))
        XCTAssertEqual(timeline.frames.count, 2)
        XCTAssertEqual(timeline.frames[0].frameIndex, 0)
        XCTAssertEqual(timeline.frames[0].movieTime.cmTime, .zero)
        XCTAssertEqual(timeline.frames[1].frameIndex, 1)
        XCTAssertEqual(CMTimeGetSeconds(timeline.frames[1].movieTime.cmTime), 0.1, accuracy: 0.000001)
        XCTAssertEqual(timeline.frames.map(\.orientation), ["up", "up"])
        XCTAssertEqual(timeline.receivedFrameCount, 2)
        XCTAssertEqual(timeline.writtenFrameCount, 2)
        XCTAssertEqual(timeline.droppedFrameCount, 0)
        XCTAssertEqual(timeline.predictionSampleCount, 2)
        XCTAssertEqual(timeline.eventProposalCount, 1)
        XCTAssertEqual(timeline.issues.count, 1)
        XCTAssertEqual(timeline.issues[0].stage, "card_event_inference")
        XCTAssertEqual(timeline.issues[0].message, "fixture inference failure")
        XCTAssertEqual(
            CMTimeGetSeconds(try XCTUnwrap(timeline.issues[0].sourceTime).cmTime),
            0.15,
            accuracy: 0.000001
        )
        XCTAssertEqual(source.gameID, "game-550e8400-e29b-41d4-a716-446655440010")
        XCTAssertEqual(source.tableSetup, "default_table_setup")
        XCTAssertEqual(
            enrollments.enrollments.map(\.task),
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
        let bundle = try decodeRepositoryJSON(RepositoryBundle.self, data: manifestData)
        _ = try validateRepositoryBundleDirectory(at: bundleURL)
        let proposalDescriptor = try XCTUnwrap(bundle.files.proposalGeneratorRuns.first)
        let proposal = try decodeRepositoryJSON(
            RepositoryProposalGeneratorRun.self,
            data: Data(contentsOf: bundleURL.appendingPathComponent(proposalDescriptor.relativePath))
        )

        XCTAssertEqual(proposal.probabilities.count, 1)
        XCTAssertEqual(proposal.probabilities[0].timeS, 0.0, accuracy: 0.000001)
        XCTAssertTrue(proposal.eventProposals.isEmpty)
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

    func testFirstAcceptedVideoFrameDefinesTheSavedTimelineZero() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let writer = FakeVideoWriterFactory(readiness: [false, true])
        let coordinator = TrainingRecordingCoordinator(
            configuration: configuration(root: root),
            writerFactory: writer
        )

        try coordinator.start()
        coordinator.consume(frame(at: 40.0))
        coordinator.drain()
        coordinator.consume(frame(at: 40.2))
        coordinator.drain()
        coordinator.consume(
            ModelPrediction(
                timestamp: time(40.2),
                cardEventProbability: 0.8,
                inferenceDurationMs: 8.0
            ),
            event: DetectionEvent(
                timestamp: time(40.2),
                emittedAt: time(40.3),
                peakProbability: 0.8
            )
        )

        let bundleURL = try XCTUnwrap(try waitForStop(coordinator).get())
        let timeline = try DeviceCaptureTimeline.load(from: bundleURL)
        let proposalURL = bundleURL.appendingPathComponent(
            "predictions/proposal-recording-fixture-001-device.json"
        )
        let proposal = try decodeRepositoryJSON(
            RepositoryProposalGeneratorRun.self,
            data: Data(contentsOf: proposalURL)
        )

        XCTAssertEqual(timeline.sourceTimeZero.cmTime, time(40.2))
        XCTAssertEqual(timeline.frames.count, 1)
        XCTAssertEqual(timeline.frames[0].movieTime.cmTime, .zero)
        XCTAssertEqual(proposal.probabilities[0].timeS, 0.0, accuracy: 0.000001)
        XCTAssertEqual(proposal.eventProposals[0].timeS, 0.0, accuracy: 0.000001)
        XCTAssertEqual(proposal.eventProposals[0].emittedAtS, 0.1, accuracy: 0.000001)
        XCTAssertEqual(coordinator.metrics.droppedFrameCount, 1)
    }

    func testInterruptedCaptureRetainsItsTimelineAndIssue() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let coordinator = TrainingRecordingCoordinator(
            configuration: configuration(root: root),
            writerFactory: FakeVideoWriterFactory()
        )

        try coordinator.start()
        coordinator.consume(frame(at: 50.0))
        coordinator.drain()
        coordinator.markInterrupted()

        let bundleURL = try XCTUnwrap(try waitForStop(coordinator).get())
        let timeline = try DeviceCaptureTimeline.load(from: bundleURL)
        XCTAssertTrue(timeline.interrupted)
        XCTAssertEqual(timeline.frames.count, 1)
        XCTAssertEqual(timeline.issues.last?.stage, "capture")
        XCTAssertEqual(timeline.issues.last?.message, "Capture was interrupted.")
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
        let operatorSettings = OperatorSettings(operatorName: "fixture-operator")
        let context = AppRunContext(
            sessionID: UUID(uuidString: "550e8400-e29b-41d4-a716-446655440010")!
        )
        let fixedMetadata = FixedRecordingMetadata(sourcePermission: "training_and_evaluation")
        let collectionMetadata = try! RecordingMetadataAdapter(
            fixedMetadata: fixedMetadata
        ).makeCollectionMetadata(
            profile: profile,
            operatorSettings: operatorSettings,
            appRunContext: context
        )
        return TrainingRecordingConfiguration(
            outputRoot: root,
            recordingID: "recording-fixture-001",
            sessionID: "550e8400-e29b-41d4-a716-446655440010",
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
            collectionMetadata: collectionMetadata,
            taskEnrollments: try! profile.makeTaskEnrollments(
                recordingID: "recording-fixture-001",
                createdAtUTC: "2026-08-28T08:00:00Z",
                operatorSettings: operatorSettings
            ),
            frameRate: 10.0
        )
    }

    private func validProfile() -> RecordingProfile {
        RecordingProfile(
            profileID: "profile-fixture-001",
            name: "Fixture collection",
            purpose: .realGame,
            tags: ["normal_card_play"]
        )
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
    let readiness: [Bool]
    private(set) var makeCount = 0
    private(set) var writer: FakeVideoWriter?

    init(
        appendResult: Bool = true,
        appendGate: DispatchSemaphore? = nil,
        readiness: [Bool] = []
    ) {
        self.appendResult = appendResult
        self.appendGate = appendGate
        self.readiness = readiness
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
            appendGate: appendGate,
            readiness: readiness
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
    private var readiness: [Bool]
    private(set) var finishCount = 0

    init(
        outputURL: URL,
        width: Int,
        height: Int,
        frameRate: Double,
        appendResult: Bool,
        appendGate: DispatchSemaphore?,
        readiness: [Bool]
    ) {
        self.outputURL = outputURL
        output = TrainingRecordingVideoWriterOutput(width: width, height: height, frameRate: frameRate)
        self.appendResult = appendResult
        self.appendGate = appendGate
        self.readiness = readiness
        try? Data("fake h264 bytes".utf8).write(to: outputURL)
    }

    var isReadyForMoreMediaData: Bool {
        guard !readiness.isEmpty else { return true }
        return readiness.removeFirst()
    }

    func append(_ frame: VideoFrame, presentationTime: CMTime) -> Bool {
        _ = appendGate?.wait(timeout: .now() + 3)
        return appendResult
    }

    func finish(completion: @escaping (Result<TrainingRecordingVideoWriterOutput, Error>) -> Void) {
        finishCount += 1
        completion(.success(output))
    }
}
