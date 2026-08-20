import CoreMedia
import Foundation

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
    private let runner: CardEventModelRunner
    private let eventPostProcessor: EventPostProcessor
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
    private let onUpdate: (FrameInferenceUpdate) -> Void

    init(
        runner: CardEventModelRunner,
        eventPostProcessor: EventPostProcessor,
        targetRateHz: Double = 8.0,
        onUpdate: @escaping (FrameInferenceUpdate) -> Void
    ) {
        precondition(targetRateHz > 0.0, "target inference rate must be positive")
        self.runner = runner
        self.eventPostProcessor = eventPostProcessor
        samplingPolicy = InferenceSamplingPolicy(
            minimumInterval: CMTime(seconds: 1.0 / targetRateHz, preferredTimescale: 600)
        )
        self.onUpdate = onUpdate
    }

    func consume(_ frame: VideoFrame) {
        lock.lock()
        guard !stopped else {
            lock.unlock()
            return
        }

        cameraFramesReceived += 1
        let decision = samplingPolicy.accept(
            timestamp: frame.timestamp,
            inferenceInFlight: inferenceInFlight
        )
        switch decision {
        case .sampledTooSoon:
            framesSkippedForSampling += 1
            lock.unlock()
            return
        case .inferenceBusy:
            framesDroppedWhileBusy += 1
            lock.unlock()
            return
        case .invalidTimestamp:
            lock.unlock()
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
        }

        inferenceQueue.async { [weak self] in
            self?.runInference(frame)
        }
    }

    func stop() {
        lock.lock()
        stopped = true
        lock.unlock()
    }

    private func runInference(_ frame: VideoFrame) {
        var prediction: ModelPrediction?
        var event: DetectionEvent?
        var errorMessage: String?

        do {
            prediction = try runner.consume(frame)
            if let prediction {
                event = eventPostProcessor.consume(prediction)
            }
        } catch {
            errorMessage = error.localizedDescription
        }

        lock.lock()
        inferenceInFlight = false
        if let prediction {
            predictionsProduced += 1
            totalInferenceDurationMs += prediction.inferenceDurationMs
        }
        lock.unlock()

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
}
