import CoreML
import CoreMedia
import Foundation
import SwiftUI

enum ModelLoadState {
    case loading
    case ready(ModelContract)
    case failed(String)

    var title: String {
        switch self {
        case .loading: return "Loading"
        case .ready: return "Ready"
        case .failed: return "Error"
        }
    }
}

struct ScoreSample: Identifiable {
    let id = UUID()
    let timestampSeconds: Double
    let probability: Double
}

@MainActor
final class AppState: ObservableObject {
    @Published private(set) var modelState: ModelLoadState = .loading
    @Published private(set) var eventCount = 0
    @Published private(set) var latestPrediction: ModelPrediction?
    @Published private(set) var inferenceMetrics = FrameInferenceMetrics(
        cameraFramesReceived: 0,
        framesSkippedForSampling: 0,
        framesDroppedWhileBusy: 0,
        predictionsProduced: 0,
        averageInferenceDurationMs: nil
    )
    @Published private(set) var inferenceError: String?
    @Published private(set) var scoreHistory: [ScoreSample] = []
    @Published private(set) var lastEventTimestampSeconds: Double?
    @Published private(set) var replayProgress: ReplayProgress?
    @Published private(set) var replayRunning = false
    @Published private(set) var roiError: String?

    private(set) var modelRunner: CardEventModelRunner?
    let eventPostProcessor = EventPostProcessor()
    private var liveCoordinator: FrameInferenceCoordinator?
    private var replayRunner: VideoReplayRunner?

    var roiStatus: String {
        guard let runner = modelRunner as? CoreMLCardEventModelRunner else {
            return "Unavailable"
        }
        return runner.roi == nil ? "Not configured" : "Configured"
    }

    var actualPredictionRateHz: Double? {
        guard let first = scoreHistory.first,
              let last = scoreHistory.last,
              scoreHistory.count > 1 else {
            return nil
        }
        let duration = last.timestampSeconds - first.timestampSeconds
        guard duration > 0.0 else { return nil }
        return Double(scoreHistory.count - 1) / duration
    }

    var thermalStateDescription: String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "Nominal"
        case .fair: return "Fair"
        case .serious: return "Serious"
        case .critical: return "Critical"
        @unknown default: return "Unknown"
        }
    }

    init() {
        loadModel()
    }

    func loadModel() {
        stopLiveInference()
        modelState = .loading
        modelRunner = nil

        do {
            let configuration = MLModelConfiguration()
            configuration.computeUnits = .all
            let runner = try CoreMLCardEventModelRunner(configuration: configuration)
            modelRunner = runner
            modelState = .ready(runner.contract)
#if DEBUG
            print("CardEventNet model contract:\n\(runner.contract.summary)")
#endif
        } catch {
            modelState = .failed(error.localizedDescription)
        }
    }

    func startLiveInference() -> ((VideoFrame) -> Void)? {
        cancelReplay()
        stopLiveInference()
        guard let runner = modelRunner else { return nil }

        let coordinator = FrameInferenceCoordinator(
            runner: runner,
            eventPostProcessor: eventPostProcessor
        ) { [weak self] update in
            self?.apply(update)
        }
        liveCoordinator = coordinator
        return { [weak coordinator] frame in
            coordinator?.consume(frame)
        }
    }

    func stopLiveInference() {
        liveCoordinator?.stop()
        liveCoordinator = nil
    }

    func setROI(x: Double, y: Double, width: Double, height: Double) {
        do {
            let roi = try NormalizedROI(x: x, y: y, width: width, height: height)
            guard let runner = modelRunner as? CoreMLCardEventModelRunner else {
                roiError = "The model is not ready."
                return
            }
            runner.setROI(roi)
            eventPostProcessor.reset()
            roiError = nil
        } catch {
            roiError = error.localizedDescription
        }
    }

    func startReplay(url: URL) {
        stopLiveInference()
        cancelReplay()
        guard let runner = modelRunner else {
            inferenceError = "The model is not ready."
            return
        }

        resetEvents()
        replayProgress = nil
        replayRunning = true
        let replayRunner = VideoReplayRunner()
        self.replayRunner = replayRunner
        replayRunner.start(
            url: url,
            modelRunner: runner,
            eventPostProcessor: eventPostProcessor
        ) { [weak self] progress in
            Task { @MainActor in
                self?.applyReplay(progress)
            }
        }
    }

    func cancelReplay() {
        replayRunner?.cancel()
    }

    func resetEvents() {
        eventPostProcessor.reset()
        eventCount = 0
        latestPrediction = nil
        inferenceError = nil
        scoreHistory.removeAll(keepingCapacity: true)
        lastEventTimestampSeconds = nil
    }

    func setHighThreshold(_ value: Double) {
        let low = eventPostProcessor.configuration.lowThreshold
        setThresholds(high: max(value, low + 0.01), low: low)
    }

    func setLowThreshold(_ value: Double) {
        let high = eventPostProcessor.configuration.highThreshold
        setThresholds(high: high, low: min(value, high - 0.01))
    }

    private func setThresholds(high: Double, low: Double) {
        guard high > low else { return }
        let current = eventPostProcessor.configuration
        eventPostProcessor.updateConfiguration(
            EventPostProcessor.Configuration(
                highThreshold: high,
                lowThreshold: low,
                minimumConsecutiveHighPredictions: current.minimumConsecutiveHighPredictions,
                cooldown: current.cooldown
            )
        )
        objectWillChange.send()
    }

    private func apply(_ update: FrameInferenceUpdate) {
        latestPrediction = update.prediction ?? latestPrediction
        inferenceMetrics = update.metrics
        inferenceError = update.errorMessage
        if let prediction = update.prediction {
            appendScore(prediction)
        }
        if update.event != nil {
            eventCount += 1
            if let event = update.event {
                lastEventTimestampSeconds = CMTimeGetSeconds(event.timestamp)
            }
        }
    }

    private func applyReplay(_ progress: ReplayProgress) {
        replayProgress = progress
        replayRunning = !progress.isComplete
        inferenceError = progress.errorMessage
        inferenceMetrics = FrameInferenceMetrics(
            cameraFramesReceived: progress.framesRead,
            framesSkippedForSampling: 0,
            framesDroppedWhileBusy: 0,
            predictionsProduced: progress.predictionsProduced,
            averageInferenceDurationMs: progress.averageInferenceDurationMs
        )
        if let prediction = progress.prediction {
            latestPrediction = prediction
            appendScore(prediction)
        }
        eventCount = progress.eventCount
        if let timestamp = progress.lastEventTimestampSeconds {
            lastEventTimestampSeconds = timestamp
        }
        if progress.isComplete {
            replayRunner = nil
        }
    }

    private func appendScore(_ prediction: ModelPrediction) {
        let timestamp = CMTimeGetSeconds(prediction.timestamp)
        if scoreHistory.last?.timestampSeconds == timestamp {
            return
        }
        scoreHistory.append(
            ScoreSample(
                timestampSeconds: timestamp,
                probability: prediction.cardEventProbability
            )
        )
        if scoreHistory.count > 80 {
            scoreHistory.removeFirst(scoreHistory.count - 80)
        }
    }
}
