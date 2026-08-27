import CoreMedia
import Foundation
import os

struct FrameInferenceMetrics: Equatable {
    let cameraFramesReceived: Int
    let framesSkippedForSampling: Int
    let framesDroppedWhileBusy: Int
    let predictionsProduced: Int
    let averageInferenceDurationMs: Double?
}

struct FrameInferenceUpdate {
    let frame: VideoFrame?
    let prediction: ModelPrediction?
    let event: DetectionEvent?
    let errorMessage: String?
    let metrics: FrameInferenceMetrics
}

/// Connects a camera frame stream to one bounded, serial model execution path.
final class FrameInferenceCoordinator {
    private static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.dokodetector.CardEventProbe",
        category: "LiveInference"
    )
    private let runner: CardEventModelRunner
    private let eventDecoder: CausalEventDecoder
    private let evidenceSampler: EvidenceFrameSampler
    private let videoCapture: (any EvidenceVideoFrameConsumer)?
    private let inferenceQueue = DispatchQueue(label: "com.dokodetector.CardEventProbe.inference")
    private let lock = NSLock()
    private var samplingPolicy: InferenceSamplingPolicy
    private var inferenceInFlight = false
    private var stopped = false
    private var cameraFramesReceived = 0
    private var framesSkippedForSampling = 0
    private var framesDroppedWhileBusy = 0
    private var predictionsProduced = 0
    private var totalInferenceDurationMs = 0.0
    private var trainingRecordingCoordinator: TrainingRecordingCoordinator?
    private let onUpdate: (FrameInferenceUpdate) -> Void

    init(
        runner: CardEventModelRunner,
        eventDecoder: CausalEventDecoder,
        evidenceSampler: EvidenceFrameSampler,
        videoCapture: (any EvidenceVideoFrameConsumer)? = nil,
        targetRateHz: Double = 8.0,
        onUpdate: @escaping (FrameInferenceUpdate) -> Void
    ) {
        precondition(targetRateHz > 0.0, "target inference rate must be positive")
        self.runner = runner
        self.eventDecoder = eventDecoder
        self.evidenceSampler = evidenceSampler
        self.videoCapture = videoCapture
        samplingPolicy = InferenceSamplingPolicy(
            minimumInterval: CMTime(seconds: 1.0 / targetRateHz, preferredTimescale: 600)
        )
        self.onUpdate = onUpdate
        Self.logger.info("Started live inference at \(targetRateHz, format: .fixed(precision: 1)) Hz.")
    }

    func attachTrainingRecording(_ coordinator: TrainingRecordingCoordinator?) {
        lock.lock()
        trainingRecordingCoordinator = coordinator
        lock.unlock()
    }

    func consume(_ frame: VideoFrame) {
        evidenceSampler.consume(frame)
        videoCapture?.consume(frame)

        lock.lock()
        guard !stopped else {
            lock.unlock()
            return
        }

        let trainingRecordingCoordinator = self.trainingRecordingCoordinator
        cameraFramesReceived += 1
        let shouldPublishMetrics = cameraFramesReceived == 1 || cameraFramesReceived.isMultiple(of: 30)
        let decision = samplingPolicy.accept(
            timestamp: frame.timestamp,
            inferenceInFlight: inferenceInFlight
        )
        trainingRecordingCoordinator?.consume(frame)
        switch decision {
        case .sampledTooSoon:
            framesSkippedForSampling += 1
            lock.unlock()
            if shouldPublishMetrics { publishMetrics() }
            return
        case .inferenceBusy:
            framesDroppedWhileBusy += 1
            lock.unlock()
            if shouldPublishMetrics { publishMetrics() }
            return
        case .invalidTimestamp:
            lock.unlock()
            Self.logger.error("Dropped a camera frame with an invalid timestamp.")
            publish(
                prediction: nil,
                event: nil,
                frame: nil,
                errorMessage: "The camera produced a frame with an invalid timestamp."
            )
            return
        case .accepted:
            inferenceInFlight = true
            lock.unlock()
            if shouldPublishMetrics { publishMetrics() }
        }

        inferenceQueue.async { [weak self] in
            self?.runInference(frame)
        }
    }

    func stop() {
        evidenceSampler.stop()
        videoCapture?.stop()
        lock.lock()
        stopped = true
        lock.unlock()
        Self.logger.info("Stopped live inference.")
    }

    private func runInference(_ frame: VideoFrame) {
        var prediction: ModelPrediction?
        var event: DetectionEvent?
        var errorMessage: String?

        do {
            prediction = try runner.consume(frame)
            if let prediction {
                event = eventDecoder.consume(prediction)
            }
        } catch {
            errorMessage = error.localizedDescription
            Self.logger.error("Model inference failed: \(error.localizedDescription, privacy: .public)")
        }

        lock.lock()
        inferenceInFlight = false
        let trainingRecordingCoordinator = self.trainingRecordingCoordinator
        if let prediction {
            predictionsProduced += 1
            totalInferenceDurationMs += prediction.inferenceDurationMs
        }
        lock.unlock()

        if let prediction {
            trainingRecordingCoordinator?.consume(prediction, event: event)
        }
        publish(
            prediction: prediction,
            event: event,
            frame: prediction == nil ? nil : frame,
            errorMessage: errorMessage
        )
    }

    private func publish(
        prediction: ModelPrediction?,
        event: DetectionEvent?,
        frame: VideoFrame?,
        errorMessage: String?
    ) {
        lock.lock()
        let metrics = FrameInferenceMetrics(
            cameraFramesReceived: cameraFramesReceived,
            framesSkippedForSampling: framesSkippedForSampling,
            framesDroppedWhileBusy: framesDroppedWhileBusy,
            predictionsProduced: predictionsProduced,
            averageInferenceDurationMs: predictionsProduced == 0
                ? nil
                : totalInferenceDurationMs / Double(predictionsProduced)
        )
        let shouldPublish = !stopped
        lock.unlock()

        guard shouldPublish else { return }
        DispatchQueue.main.async { [onUpdate] in
            onUpdate(
                FrameInferenceUpdate(
                    frame: frame,
                    prediction: prediction,
                    event: event,
                    errorMessage: errorMessage,
                    metrics: metrics
                )
            )
        }
    }

    private func publishMetrics() {
        lock.lock()
        let metrics = FrameInferenceMetrics(
            cameraFramesReceived: cameraFramesReceived,
            framesSkippedForSampling: framesSkippedForSampling,
            framesDroppedWhileBusy: framesDroppedWhileBusy,
            predictionsProduced: predictionsProduced,
            averageInferenceDurationMs: predictionsProduced == 0
                ? nil
                : totalInferenceDurationMs / Double(predictionsProduced)
        )
        let shouldPublish = !stopped
        lock.unlock()

        guard shouldPublish else { return }
        Self.logger.info(
            "Live inference metrics: camera=\(metrics.cameraFramesReceived), predictions=\(metrics.predictionsProduced), skipped=\(metrics.framesSkippedForSampling), busy=\(metrics.framesDroppedWhileBusy)."
        )
        DispatchQueue.main.async { [onUpdate] in
            onUpdate(
                FrameInferenceUpdate(
                    frame: nil,
                    prediction: nil,
                    event: nil,
                    errorMessage: nil,
                    metrics: metrics
                )
            )
        }
    }
}
