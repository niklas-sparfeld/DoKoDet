@preconcurrency import AVFoundation
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation
import ImageIO

public struct TrainingRecordingConfiguration: Sendable {
    public let outputRoot: URL
    public let recordingID: String
    public let sessionID: String
    public let videoID: String
    public let startedAtUTC: Date
    public let model: TrainingRecordingModel
    public let decoder: TrainingRecordingDecoder
    public let cameraPosition: String
    public let client: TrainingRecordingClient
    public let sourcePermission: String
    public let frameRate: Double
    public let maximumDurationSeconds: Double?
    public let maximumSizeBytes: Int64?

    public init(
        outputRoot: URL,
        recordingID: String,
        sessionID: String,
        videoID: String,
        startedAtUTC: Date = Date(),
        model: TrainingRecordingModel,
        decoder: TrainingRecordingDecoder,
        cameraPosition: String = "back",
        client: TrainingRecordingClient,
        sourcePermission: String,
        frameRate: Double = 30.0,
        maximumDurationSeconds: Double? = nil,
        maximumSizeBytes: Int64? = nil
    ) {
        precondition(startedAtUTC.timeIntervalSinceReferenceDate.isFinite, "start time must be finite")
        precondition(frameRate.isFinite && frameRate > 0.0, "frame rate must be positive")
        precondition(
            maximumDurationSeconds.map { $0.isFinite && $0 > 0.0 } ?? true,
            "maximum duration must be positive"
        )
        precondition(
            maximumSizeBytes.map { $0 > 0 } ?? true,
            "maximum size must be positive"
        )
        self.outputRoot = outputRoot
        self.recordingID = recordingID
        self.sessionID = sessionID
        self.videoID = videoID
        self.startedAtUTC = startedAtUTC
        self.model = model
        self.decoder = decoder
        self.cameraPosition = cameraPosition
        self.client = client
        self.sourcePermission = sourcePermission
        self.frameRate = frameRate
        self.maximumDurationSeconds = maximumDurationSeconds
        self.maximumSizeBytes = maximumSizeBytes
    }
}

public struct TrainingRecordingMetrics: Equatable, Sendable {
    public let receivedFrameCount: Int
    public let writtenFrameCount: Int
    public let droppedFrameCount: Int
    public let predictionSampleCount: Int
    public let eventProposalCount: Int

    public init(
        receivedFrameCount: Int = 0,
        writtenFrameCount: Int = 0,
        droppedFrameCount: Int = 0,
        predictionSampleCount: Int = 0,
        eventProposalCount: Int = 0
    ) {
        self.receivedFrameCount = receivedFrameCount
        self.writtenFrameCount = writtenFrameCount
        self.droppedFrameCount = droppedFrameCount
        self.predictionSampleCount = predictionSampleCount
        self.eventProposalCount = eventProposalCount
    }
}

public enum TrainingRecordingState: Equatable, Sendable {
    case idle
    case recording
    case finalizing
    case completed(URL)
    case failed(String)
}

public enum TrainingRecordingError: LocalizedError, Equatable {
    case invalidState(String)
    case outputAlreadyExists(URL)
    case cannotCreateDirectory(URL, String)
    case cannotCreatePredictionFile(URL, String)
    case noFramesWritten
    case writerFailed(String)
    case predictionWriteFailed(String)
    case validationFailed(String)
    case finalizationFailed(String)

    public var errorDescription: String? {
        switch self {
        case let .invalidState(message):
            return "The training recording is in an invalid state: \(message)."
        case let .outputAlreadyExists(url):
            return "The training recording output already exists at \(url.path)."
        case let .cannotCreateDirectory(url, message):
            return "The training recording directory could not be created at \(url.path): \(message)"
        case let .cannotCreatePredictionFile(url, message):
            return "The prediction file could not be created at \(url.path): \(message)"
        case .noFramesWritten:
            return "The training recording contains no video frames."
        case let .writerFailed(message):
            return "The training video writer failed: \(message)"
        case let .predictionWriteFailed(message):
            return "The prediction file could not be written: \(message)"
        case let .validationFailed(message):
            return "The training recording did not pass validation: \(message)"
        case let .finalizationFailed(message):
            return "The training recording could not be finalized: \(message)"
        }
    }
}

public struct TrainingRecordingVideoWriterOutput: Sendable {
    public let width: Int
    public let height: Int
    public let frameRate: Double

    public init(width: Int, height: Int, frameRate: Double) {
        self.width = width
        self.height = height
        self.frameRate = frameRate
    }
}

/// A video writer used only from the recorder's serial writer queue.
public protocol TrainingRecordingVideoWriter: AnyObject {
    var isReadyForMoreMediaData: Bool { get }

    func append(_ frame: VideoFrame, presentationTime: CMTime) -> Bool

    func finish(completion: @escaping (Result<TrainingRecordingVideoWriterOutput, Error>) -> Void)
}

public protocol TrainingRecordingVideoWriterFactory {
    func makeWriter(
        outputURL: URL,
        width: Int,
        height: Int,
        frameRate: Double
    ) throws -> any TrainingRecordingVideoWriter
}

/// Creates H.264 QuickTime writers for the live app.
public struct AVAssetWriterVideoWriterFactory: TrainingRecordingVideoWriterFactory {
    public init() {}

    public func makeWriter(
        outputURL: URL,
        width: Int,
        height: Int,
        frameRate: Double
    ) throws -> any TrainingRecordingVideoWriter {
        try AVAssetWriterVideoWriter(
            outputURL: outputURL,
            width: width,
            height: height,
            frameRate: frameRate
        )
    }
}

public final class AVAssetWriterVideoWriter: TrainingRecordingVideoWriter {
    private let writer: AVAssetWriter
    private let input: AVAssetWriterInput
    private let adaptor: AVAssetWriterInputPixelBufferAdaptor
    private let output: TrainingRecordingVideoWriterOutput

    public init(outputURL: URL, width: Int, height: Int, frameRate: Double) throws {
        guard width > 0, height > 0, frameRate.isFinite, frameRate > 0 else {
            throw TrainingRecordingError.writerFailed("video dimensions and frame rate must be positive")
        }

        writer = try AVAssetWriter(outputURL: outputURL, fileType: .mov)
        input = AVAssetWriterInput(
            mediaType: .video,
            outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264,
                AVVideoWidthKey: width,
                AVVideoHeightKey: height,
                AVVideoCompressionPropertiesKey: [
                    AVVideoExpectedSourceFrameRateKey: frameRate,
                ],
            ]
        )
        input.expectsMediaDataInRealTime = true
        adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ]
        )
        output = TrainingRecordingVideoWriterOutput(
            width: width,
            height: height,
            frameRate: frameRate
        )

        guard writer.canAdd(input) else {
            throw TrainingRecordingError.writerFailed("the video input could not be added")
        }
        writer.add(input)
        guard writer.startWriting() else {
            throw TrainingRecordingError.writerFailed(
                writer.error?.localizedDescription ?? "the writer could not start"
            )
        }
        writer.startSession(atSourceTime: .zero)
    }

    public var isReadyForMoreMediaData: Bool {
        writer.status == .writing && input.isReadyForMoreMediaData
    }

    public func append(_ frame: VideoFrame, presentationTime: CMTime) -> Bool {
        guard writer.status == .writing else { return false }
        return adaptor.append(frame.pixelBuffer, withPresentationTime: presentationTime)
    }

    public func finish(completion: @escaping (Result<TrainingRecordingVideoWriterOutput, Error>) -> Void) {
        input.markAsFinished()
        let completionBox = VideoWriterFinishCompletion(completion)
        writer.finishWriting { [writer, output, completionBox] in
            if writer.status == .completed {
                completionBox.call(.success(output))
            } else {
                completionBox.call(
                    .failure(
                        TrainingRecordingError.writerFailed(
                            writer.error?.localizedDescription ?? "the writer did not complete"
                        )
                    )
                )
            }
        }
    }
}

private final class VideoWriterFinishCompletion: @unchecked Sendable {
    private let completion: (Result<TrainingRecordingVideoWriterOutput, Error>) -> Void

    init(_ completion: @escaping (Result<TrainingRecordingVideoWriterOutput, Error>) -> Void) {
        self.completion = completion
    }

    func call(_ result: Result<TrainingRecordingVideoWriterOutput, Error>) {
        completion(result)
    }
}

/// Records a complete recording on one bounded serial writer path.
public final class TrainingRecordingCoordinator: @unchecked Sendable {
    private let configuration: TrainingRecordingConfiguration
    private let writerFactory: any TrainingRecordingVideoWriterFactory
    private let writerQueue = DispatchQueue(label: "com.dokodetector.CardEventProbe.training-recording")
    private let lock = NSLock()
    private let fileManager = FileManager.default

    private var stateValue: TrainingRecordingState = .idle
    private var metricsValue = TrainingRecordingMetrics()
    private var stopCompletions: [(Result<URL, Error>) -> Void] = []
    private var recordingError: TrainingRecordingError?
    private var stagingDirectory: URL?
    private var finalDirectory: URL?
    private var videoURL: URL?
    private var predictionsURL: URL?
    private var predictionWriter: StreamingDevicePredictionsWriter?
    private var videoWriter: (any TrainingRecordingVideoWriter)?
    private var sourceTimestamp: CMTime?
    private var latestTimelineTime: CMTime?
    private var lastWrittenFrameTime: CMTime?
    private var firstOrientation: String?
    private var frameWriteInFlight = false

    public init(
        configuration: TrainingRecordingConfiguration,
        writerFactory: any TrainingRecordingVideoWriterFactory = AVAssetWriterVideoWriterFactory()
    ) {
        self.configuration = configuration
        self.writerFactory = writerFactory
    }

    public var state: TrainingRecordingState {
        lock.lock()
        defer { lock.unlock() }
        return stateValue
    }

    public var metrics: TrainingRecordingMetrics {
        lock.lock()
        defer { lock.unlock() }
        return metricsValue
    }

    /// Returns the current on-disk size of the staged video and prediction files.
    public var estimatedStoredSizeBytes: Int64 {
        lock.lock()
        let urls = [videoURL, predictionsURL].compactMap { $0 }
        lock.unlock()
        return urls.reduce(0) { total, url in
            let attributes = try? fileManager.attributesOfItem(atPath: url.path)
            return total + ((attributes?[.size] as? NSNumber)?.int64Value ?? 0)
        }
    }

    /// Waits for writer work submitted before this call. Intended for tests and handoff.
    public func drain() {
        writerQueue.sync {}
    }

    /// Creates a private staging directory and starts the prediction stream.
    public func start() throws {
        lock.lock()
        guard stateValue == .idle else {
            let current = stateValue
            lock.unlock()
            throw TrainingRecordingError.invalidState("cannot start from \(current)")
        }
        lock.unlock()

        let finalDirectory = configuration.outputRoot
            .appendingPathComponent(configuration.recordingID, isDirectory: true)
        guard !fileManager.fileExists(atPath: finalDirectory.path) else {
            throw TrainingRecordingError.outputAlreadyExists(finalDirectory)
        }

        let stagingParent = configuration.outputRoot.appendingPathComponent(".staging", isDirectory: true)
        let stagingDirectory = stagingParent.appendingPathComponent(
            "\(configuration.recordingID)-\(UUID().uuidString.lowercased())",
            isDirectory: true
        )
        do {
            try fileManager.createDirectory(at: stagingDirectory, withIntermediateDirectories: true)
        } catch {
            throw TrainingRecordingError.cannotCreateDirectory(
                stagingDirectory,
                error.localizedDescription
            )
        }

        let videoURL = stagingDirectory.appendingPathComponent(
            "\(configuration.videoID).mov",
            isDirectory: false
        )
        let predictionsURL = stagingDirectory.appendingPathComponent(
            "\(configuration.videoID).json",
            isDirectory: false
        )

        do {
            let predictionWriter = try StreamingDevicePredictionsWriter(
                url: predictionsURL,
                temporaryDirectory: stagingDirectory,
                sourceVideo: videoURL.lastPathComponent,
                model: configuration.model,
                decoder: configuration.decoder
            )
            lock.lock()
            self.stagingDirectory = stagingDirectory
            self.finalDirectory = finalDirectory
            self.videoURL = videoURL
            self.predictionsURL = predictionsURL
            self.predictionWriter = predictionWriter
            stateValue = .recording
            lock.unlock()
        } catch {
            try? fileManager.removeItem(at: stagingDirectory)
            throw TrainingRecordingError.cannotCreatePredictionFile(
                predictionsURL,
                error.localizedDescription
            )
        }
    }

    /// Accepts a frame without waiting for file I/O or an encoder.
    public func consume(_ frame: VideoFrame) {
        let timestamp = frame.timestamp
        let seconds = CMTimeGetSeconds(timestamp)

        lock.lock()
        guard stateValue == .recording else {
            lock.unlock()
            return
        }

        metricsValue = TrainingRecordingMetrics(
            receivedFrameCount: metricsValue.receivedFrameCount + 1,
            writtenFrameCount: metricsValue.writtenFrameCount,
            droppedFrameCount: metricsValue.droppedFrameCount,
            predictionSampleCount: metricsValue.predictionSampleCount,
            eventProposalCount: metricsValue.eventProposalCount
        )
        guard seconds.isFinite else {
            incrementDroppedFrameLocked()
            lock.unlock()
            return
        }

        if sourceTimestamp == nil {
            sourceTimestamp = timestamp
            firstOrientation = Self.orientationName(frame.orientation)
        }
        guard let sourceTimestamp else {
            incrementDroppedFrameLocked()
            lock.unlock()
            return
        }
        let relativeTime = CMTimeSubtract(timestamp, sourceTimestamp)
        guard CMTimeGetSeconds(relativeTime).isFinite,
              CMTimeCompare(relativeTime, .zero) >= 0 else {
            incrementDroppedFrameLocked()
            lock.unlock()
            return
        }
        latestTimelineTime = maxTime(latestTimelineTime, relativeTime)

        guard !frameWriteInFlight else {
            incrementDroppedFrameLocked()
            lock.unlock()
            return
        }
        frameWriteInFlight = true
        lock.unlock()

        writerQueue.async { [weak self] in
            self?.writeFrame(frame, relativeTime: relativeTime)
        }
    }

    /// Appends one device probability and an event proposal, if one was emitted.
    public func consume(_ prediction: ModelPrediction, event: DetectionEvent? = nil) {
        lock.lock()
        guard stateValue == .recording,
              let sourceTimestamp,
              CMTimeGetSeconds(prediction.timestamp).isFinite else {
            lock.unlock()
            return
        }
        let relativeTime = CMTimeSubtract(prediction.timestamp, sourceTimestamp)
        let eventRelativeTime = event.map { CMTimeSubtract($0.timestamp, sourceTimestamp) }
        let emittedRelativeTime = event.map { CMTimeSubtract($0.emittedAt, sourceTimestamp) }
        guard isNonNegativeFinite(relativeTime),
              eventRelativeTime.map(isNonNegativeFinite) ?? true,
              emittedRelativeTime.map(isNonNegativeFinite) ?? true else {
            let error = TrainingRecordingError.predictionWriteFailed(
                "prediction times must be on the recording timeline"
            )
            setFailureLocked(error)
            lock.unlock()
            return
        }
        latestTimelineTime = maxTime(latestTimelineTime, relativeTime)
        if let emittedRelativeTime {
            latestTimelineTime = maxTime(latestTimelineTime, emittedRelativeTime)
        }
        lock.unlock()

        writerQueue.async { [weak self] in
            self?.writePrediction(
                prediction,
                relativeTime: relativeTime,
                event: event,
                eventRelativeTime: eventRelativeTime,
                emittedRelativeTime: emittedRelativeTime
            )
        }
    }

    /// Records an event emitted while the decoder flushes at the end of capture.
    public func record(_ event: DetectionEvent) {
        lock.lock()
        guard stateValue == .recording,
              let sourceTimestamp else {
            lock.unlock()
            return
        }
        let eventRelativeTime = CMTimeSubtract(event.timestamp, sourceTimestamp)
        let emittedRelativeTime = CMTimeSubtract(event.emittedAt, sourceTimestamp)
        guard isNonNegativeFinite(eventRelativeTime), isNonNegativeFinite(emittedRelativeTime) else {
            let error = TrainingRecordingError.predictionWriteFailed(
                "event proposal times must be on the recording timeline"
            )
            setFailureLocked(error)
            lock.unlock()
            return
        }
        latestTimelineTime = maxTime(latestTimelineTime, emittedRelativeTime)
        lock.unlock()

        writerQueue.async { [weak self] in
            self?.writeEvent(
                event,
                eventRelativeTime: eventRelativeTime,
                emittedRelativeTime: emittedRelativeTime
            )
        }
    }

    /// Finalizes the writer and atomically moves the complete bundle out of staging.
    public func stop(completion: @escaping (Result<URL, Error>) -> Void = { _ in }) {
        lock.lock()
        switch stateValue {
        case .recording, .failed:
            stopCompletions.append(completion)
            stateValue = .finalizing
            lock.unlock()
            writerQueue.async { [weak self] in
                self?.finalize()
            }
        case .finalizing:
            stopCompletions.append(completion)
            lock.unlock()
        case let .completed(url):
            lock.unlock()
            completion(.success(url))
        case .idle:
            lock.unlock()
            completion(.failure(TrainingRecordingError.invalidState("recording has not started")))
        }
    }

    private func writeFrame(_ frame: VideoFrame, relativeTime: CMTime) {
        defer {
            lock.lock()
            frameWriteInFlight = false
            lock.unlock()
        }

        lock.lock()
        guard recordingError == nil else {
            incrementDroppedFrameLocked()
            lock.unlock()
            return
        }
        let existingWriter = videoWriter
        let videoURL = self.videoURL
        lock.unlock()

        let writer: any TrainingRecordingVideoWriter
        do {
            if let existingWriter {
                writer = existingWriter
            } else {
                guard let videoURL else {
                    throw TrainingRecordingError.writerFailed("the video output path is missing")
                }
                let width = CVPixelBufferGetWidth(frame.pixelBuffer)
                let height = CVPixelBufferGetHeight(frame.pixelBuffer)
                let createdWriter = try writerFactory.makeWriter(
                    outputURL: videoURL,
                    width: width,
                    height: height,
                    frameRate: configuration.frameRate
                )
                lock.lock()
                if videoWriter == nil {
                    videoWriter = createdWriter
                }
                let selectedWriter = videoWriter ?? createdWriter
                lock.unlock()
                writer = selectedWriter
            }
        } catch let error as TrainingRecordingError {
            setFailureAndDrop(error)
            return
        } catch {
            setFailureAndDrop(.writerFailed(error.localizedDescription))
            return
        }

        guard writer.isReadyForMoreMediaData else {
            lock.lock()
            incrementDroppedFrameLocked()
            lock.unlock()
            return
        }

        let appended = writer.append(frame, presentationTime: relativeTime)
        lock.lock()
        if appended {
            metricsValue = TrainingRecordingMetrics(
                receivedFrameCount: metricsValue.receivedFrameCount,
                writtenFrameCount: metricsValue.writtenFrameCount + 1,
                droppedFrameCount: metricsValue.droppedFrameCount,
                predictionSampleCount: metricsValue.predictionSampleCount,
                eventProposalCount: metricsValue.eventProposalCount
            )
            lastWrittenFrameTime = maxTime(lastWrittenFrameTime, relativeTime)
        } else {
            setFailureLocked(.writerFailed("the writer rejected a ready frame"))
            incrementDroppedFrameLocked()
        }
        lock.unlock()
    }

    private func writePrediction(
        _ prediction: ModelPrediction,
        relativeTime: CMTime,
        event: DetectionEvent?,
        eventRelativeTime: CMTime?,
        emittedRelativeTime: CMTime?
    ) {
        lock.lock()
        guard recordingError == nil, let predictionWriter else {
            lock.unlock()
            return
        }
        lock.unlock()
        do {
            try predictionWriter.append(
                TrainingRecordingProbability(
                    timeS: CMTimeGetSeconds(relativeTime),
                    probability: prediction.cardEventProbability,
                    inferenceMs: prediction.inferenceDurationMs
                )
            )
            if let event, let eventRelativeTime, let emittedRelativeTime {
                try predictionWriter.append(
                    TrainingRecordingEventProposal(
                        timeS: CMTimeGetSeconds(eventRelativeTime),
                        emittedAtS: CMTimeGetSeconds(emittedRelativeTime),
                        probability: event.peakProbability
                    )
                )
            }
            lock.lock()
            metricsValue = TrainingRecordingMetrics(
                receivedFrameCount: metricsValue.receivedFrameCount,
                writtenFrameCount: metricsValue.writtenFrameCount,
                droppedFrameCount: metricsValue.droppedFrameCount,
                predictionSampleCount: metricsValue.predictionSampleCount + 1,
                eventProposalCount: metricsValue.eventProposalCount + (event == nil ? 0 : 1)
            )
            lock.unlock()
        } catch {
            lock.lock()
            setFailureLocked(.predictionWriteFailed(error.localizedDescription))
            lock.unlock()
        }
    }

    private func writeEvent(
        _ event: DetectionEvent,
        eventRelativeTime: CMTime,
        emittedRelativeTime: CMTime
    ) {
        lock.lock()
        guard recordingError == nil, let predictionWriter else {
            lock.unlock()
            return
        }
        lock.unlock()
        do {
            try predictionWriter.append(
                TrainingRecordingEventProposal(
                    timeS: CMTimeGetSeconds(eventRelativeTime),
                    emittedAtS: CMTimeGetSeconds(emittedRelativeTime),
                    probability: event.peakProbability
                )
            )
            lock.lock()
            metricsValue = TrainingRecordingMetrics(
                receivedFrameCount: metricsValue.receivedFrameCount,
                writtenFrameCount: metricsValue.writtenFrameCount,
                droppedFrameCount: metricsValue.droppedFrameCount,
                predictionSampleCount: metricsValue.predictionSampleCount,
                eventProposalCount: metricsValue.eventProposalCount + 1
            )
            lock.unlock()
        } catch {
            lock.lock()
            setFailureLocked(.predictionWriteFailed(error.localizedDescription))
            lock.unlock()
        }
    }

    private func finalize() {
        lock.lock()
        let currentError = recordingError
        let writer = videoWriter
        let predictionWriter = self.predictionWriter
        lock.unlock()

        guard let writer, let predictionWriter else {
            finishWithFailure(currentError ?? .noFramesWritten)
            return
        }

        do {
            try predictionWriter.finish()
        } catch {
            finishWithFailure(.predictionWriteFailed(error.localizedDescription))
            return
        }

        writer.finish { [weak self] result in
            guard let self else { return }
            self.writerQueue.async { [weak self] in
                self?.finishVideo(result, priorError: currentError)
            }
        }
    }

    private func finishVideo(
        _ result: Result<TrainingRecordingVideoWriterOutput, Error>,
        priorError: TrainingRecordingError?
    ) {
        if let priorError {
            finishWithFailure(priorError)
            return
        }

        let writerOutput: TrainingRecordingVideoWriterOutput
        do {
            writerOutput = try result.get()
        } catch {
            finishWithFailure(.writerFailed(error.localizedDescription))
            return
        }

        do {
            let bundleURL = try makeFinalBundle(writerOutput: writerOutput)
            lock.lock()
            stateValue = .completed(bundleURL)
            let completions = stopCompletions
            stopCompletions.removeAll()
            lock.unlock()
            complete(completions, with: .success(bundleURL))
        } catch let error as TrainingRecordingError {
            finishWithFailure(error)
        } catch {
            finishWithFailure(.finalizationFailed(error.localizedDescription))
        }
    }

    private func makeFinalBundle(writerOutput: TrainingRecordingVideoWriterOutput) throws -> URL {
        guard let stagingDirectory, let finalDirectory, let videoURL, let predictionsURL else {
            throw TrainingRecordingError.finalizationFailed("the staging paths are missing")
        }
        guard metricsValue.writtenFrameCount > 0 else {
            throw TrainingRecordingError.noFramesWritten
        }
        guard fileManager.fileExists(atPath: videoURL.path) else {
            throw TrainingRecordingError.finalizationFailed("the video file is missing")
        }

        let videoAttributes = try fileManager.attributesOfItem(atPath: videoURL.path)
        guard let videoByteLength = (videoAttributes[.size] as? NSNumber)?.intValue,
              videoByteLength > 0 else {
            throw TrainingRecordingError.finalizationFailed("the video file is empty")
        }
        let predictionsData = try Data(contentsOf: predictionsURL)
        let duration = max(
            CMTimeGetSeconds(latestTimelineTime ?? lastWrittenFrameTime ?? .zero)
                + (1.0 / configuration.frameRate),
            1.0 / configuration.frameRate
        )
        let manifest = try TrainingRecordingManifest(
            recordingID: configuration.recordingID,
            sessionID: configuration.sessionID,
            videoID: configuration.videoID,
            startedAtUTC: utcString(from: configuration.startedAtUTC),
            endedAtUTC: utcString(from: configuration.startedAtUTC.addingTimeInterval(duration)),
            durationS: duration,
            video: TrainingRecordingVideo(
                name: videoURL.lastPathComponent,
                type: "video/quicktime",
                byteLength: videoByteLength,
                sha256: try sha256Hex(of: videoURL),
                codec: "h264",
                width: writerOutput.width,
                height: writerOutput.height,
                frameRate: writerOutput.frameRate
            ),
            predictions: TrainingRecordingPredictionsFile(
                name: predictionsURL.lastPathComponent,
                type: "application/json",
                byteLength: predictionsData.count,
                sha256: predictionsData.sha256Hex,
                sampleCount: predictionWriter?.sampleCount ?? 0,
                eventProposalCount: predictionWriter?.eventProposalCount ?? 0
            ),
            model: configuration.model,
            decoder: configuration.decoder,
            camera: TrainingRecordingCamera(
                position: configuration.cameraPosition,
                orientation: firstOrientation ?? "up",
                sourceWidth: writerOutput.width,
                sourceHeight: writerOutput.height
            ),
            client: configuration.client,
            captureMetrics: TrainingRecordingCaptureMetrics(
                receivedFrameCount: metricsValue.receivedFrameCount,
                writtenFrameCount: metricsValue.writtenFrameCount,
                droppedFrameCount: metricsValue.droppedFrameCount
            ),
            sourcePermission: configuration.sourcePermission
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let manifestData = try encoder.encode(manifest)
        let manifestURL = stagingDirectory.appendingPathComponent("manifest.json", isDirectory: false)
        try manifestData.write(to: manifestURL, options: .atomic)

        do {
            _ = try validateTrainingRecordingBundle(
                manifestData: manifestData,
                predictionsData: predictionsData,
                videoURL: videoURL
            )
        } catch {
            throw TrainingRecordingError.validationFailed(error.localizedDescription)
        }

        guard !fileManager.fileExists(atPath: finalDirectory.path) else {
            throw TrainingRecordingError.outputAlreadyExists(finalDirectory)
        }
        try fileManager.moveItem(at: stagingDirectory, to: finalDirectory)
        return finalDirectory
    }

    private func finishWithFailure(_ error: TrainingRecordingError) {
        lock.lock()
        stateValue = .failed(error.localizedDescription)
        let completions = stopCompletions
        stopCompletions.removeAll()
        let stagingDirectory = self.stagingDirectory
        let predictionWriter = self.predictionWriter
        lock.unlock()
        predictionWriter?.discard()
        if let stagingDirectory {
            try? fileManager.removeItem(at: stagingDirectory)
        }
        complete(completions, with: .failure(error))
    }

    private func complete(
        _ completions: [(Result<URL, Error>) -> Void],
        with result: Result<URL, Error>
    ) {
        for completion in completions {
            completion(result)
        }
    }

    private func setFailureAndDrop(_ error: TrainingRecordingError) {
        lock.lock()
        setFailureLocked(error)
        incrementDroppedFrameLocked()
        lock.unlock()
    }

    private func setFailureLocked(_ error: TrainingRecordingError) {
        recordingError = error
        stateValue = .failed(error.localizedDescription)
    }

    private func incrementDroppedFrameLocked() {
        metricsValue = TrainingRecordingMetrics(
            receivedFrameCount: metricsValue.receivedFrameCount,
            writtenFrameCount: metricsValue.writtenFrameCount,
            droppedFrameCount: metricsValue.droppedFrameCount + 1,
            predictionSampleCount: metricsValue.predictionSampleCount,
            eventProposalCount: metricsValue.eventProposalCount
        )
    }
}

private final class StreamingDevicePredictionsWriter {
    private let url: URL
    private let temporaryURL: URL
    private let handle: FileHandle
    private let eventHandle: FileHandle
    private let encoder: JSONEncoder
    private var lastProbabilityTime: Double?
    private var lastEventTime: Double?
    private var isClosed = false
    private(set) var sampleCount = 0
    private(set) var eventProposalCount = 0

    init(
        url: URL,
        temporaryDirectory: URL,
        sourceVideo: String,
        model: TrainingRecordingModel,
        decoder: TrainingRecordingDecoder
    ) throws {
        self.url = url
        temporaryURL = temporaryDirectory.appendingPathComponent("event-proposals.tmp", isDirectory: false)
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard FileManager.default.createFile(atPath: url.path, contents: nil),
              FileManager.default.createFile(atPath: temporaryURL.path, contents: nil),
              let handle = try? FileHandle(forWritingTo: url),
              let eventHandle = try? FileHandle(forWritingTo: temporaryURL) else {
            throw TrainingRecordingError.cannotCreatePredictionFile(
                url,
                "the prediction stream could not be opened"
            )
        }
        self.handle = handle
        self.eventHandle = eventHandle

        var prefix = Data(
            "{\"schema_version\":\"\(devicePredictionsSchemaVersion)\",\"source_video\":\"".utf8
        )
        let sourceVideoData = try encoder.encode(sourceVideo)
        prefix.append(sourceVideoData)
        prefix.append(Data(",\"model\":".utf8))
        prefix.append(try encoder.encode(model))
        prefix.append(Data(",\"decoder\":".utf8))
        prefix.append(try encoder.encode(decoder))
        prefix.append(Data(",\"probabilities\":[".utf8))
        try handle.write(contentsOf: prefix)
    }

    deinit {
        try? handle.close()
        try? eventHandle.close()
    }

    func append(_ sample: TrainingRecordingProbability) throws {
        guard !isClosed else {
            throw TrainingRecordingError.predictionWriteFailed("the prediction stream is closed")
        }
        guard lastProbabilityTime.map({ $0 <= sample.timeS }) ?? true else {
            throw TrainingRecordingError.predictionWriteFailed(
                "prediction times must be ordered"
            )
        }
        try writeCommaIfNeeded(sampleCount, to: handle)
        try handle.write(contentsOf: encoder.encode(sample))
        lastProbabilityTime = sample.timeS
        sampleCount += 1
    }

    func append(_ proposal: TrainingRecordingEventProposal) throws {
        guard !isClosed else {
            throw TrainingRecordingError.predictionWriteFailed("the prediction stream is closed")
        }
        guard lastEventTime.map({ $0 <= proposal.timeS }) ?? true else {
            throw TrainingRecordingError.predictionWriteFailed(
                "event proposal times must be ordered"
            )
        }
        try writeCommaIfNeeded(eventProposalCount, to: eventHandle)
        try eventHandle.write(contentsOf: encoder.encode(proposal))
        lastEventTime = proposal.timeS
        eventProposalCount += 1
    }

    func finish() throws {
        guard !isClosed else { return }
        isClosed = true
        try eventHandle.close()
        try handle.write(contentsOf: Data("],\"event_proposals\":[".utf8))
        let reader = try FileHandle(forReadingFrom: temporaryURL)
        defer { try? reader.close() }
        while let chunk = try reader.read(upToCount: 64 * 1024), !chunk.isEmpty {
            try handle.write(contentsOf: chunk)
        }
        try handle.write(contentsOf: Data("]}".utf8))
        try handle.close()
        try? FileManager.default.removeItem(at: temporaryURL)
    }

    func discard() {
        guard !isClosed else {
            try? FileManager.default.removeItem(at: temporaryURL)
            return
        }
        isClosed = true
        try? eventHandle.close()
        try? handle.close()
        try? FileManager.default.removeItem(at: url)
        try? FileManager.default.removeItem(at: temporaryURL)
    }

    private func writeCommaIfNeeded(_ count: Int, to handle: FileHandle) throws {
        if count > 0 {
            try handle.write(contentsOf: Data(",".utf8))
        }
    }
}

private func isNonNegativeFinite(_ time: CMTime) -> Bool {
    let seconds = CMTimeGetSeconds(time)
    return seconds.isFinite && seconds >= 0.0
}

private func maxTime(_ left: CMTime?, _ right: CMTime) -> CMTime {
    guard let left else { return right }
    return CMTimeCompare(left, right) >= 0 ? left : right
}

private func utcString(from date: Date) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [
        .withInternetDateTime,
        .withDashSeparatorInDate,
        .withColonSeparatorInTime,
        .withFractionalSeconds,
    ]
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    return formatter.string(from: date)
}

private func sha256Hex(of url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    var hasher = SHA256()
    while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
        hasher.update(data: chunk)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

private extension Data {
    var sha256Hex: String {
        SHA256.hash(data: self).map { String(format: "%02x", $0) }.joined()
    }
}

private extension TrainingRecordingCoordinator {
    static func orientationName(_ orientation: CGImagePropertyOrientation) -> String {
        switch orientation {
        case .up: return "up"
        case .upMirrored: return "up_mirrored"
        case .down: return "down"
        case .downMirrored: return "down_mirrored"
        case .left: return "left"
        case .leftMirrored: return "left_mirrored"
        case .right: return "right"
        case .rightMirrored: return "right_mirrored"
        @unknown default: return "unknown"
        }
    }
}
