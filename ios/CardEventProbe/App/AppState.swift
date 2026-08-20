import CoreML
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

    private(set) var modelRunner: CardEventModelRunner?
    let eventPostProcessor = EventPostProcessor()
    private var liveCoordinator: FrameInferenceCoordinator?

    var roiStatus: String {
        guard let runner = modelRunner as? CoreMLCardEventModelRunner else {
            return "Unavailable"
        }
        return runner.roi == nil ? "Not configured" : "Configured"
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

    func resetEvents() {
        eventPostProcessor.reset()
        eventCount = 0
        latestPrediction = nil
        inferenceError = nil
    }

    private func apply(_ update: FrameInferenceUpdate) {
        latestPrediction = update.prediction ?? latestPrediction
        inferenceMetrics = update.metrics
        inferenceError = update.errorMessage
        if update.event != nil {
            eventCount += 1
        }
    }
}
