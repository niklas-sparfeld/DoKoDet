import CoreML
import CoreMedia
import Foundation
import SwiftUI
import UIKit

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
    @Published private(set) var diagnosticsLogURL: URL?
    @Published private(set) var diagnosticsError: String?
    @Published private(set) var diagnosticsRecording = false

    private(set) var modelRunner: CardEventModelRunner?
    let eventDecoder = CausalEventDecoder()
    private let evidenceCaptureConfiguration = EvidenceCaptureConfiguration()
    private(set) var evidenceSampler: EvidenceFrameSampler?
    private var liveCoordinator: FrameInferenceCoordinator?
    private var replayRunner: VideoReplayRunner?
    private var sessionLog: SessionLog?
    private var activeDiagnosticSource: DiagnosticSource?
    private var latestFrame: VideoFrame?

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
            print("CardEventNetTransitionV2 model contract:\n\(runner.contract.summary)")
#endif
        } catch {
            modelState = .failed(error.localizedDescription)
        }
    }

    func startLiveInference() -> ((VideoFrame) -> Void)? {
        stopReplayForNewSession()
        stopLiveInference()
        guard let runner = modelRunner else { return nil }
        activeDiagnosticSource = .live
        beginDiagnosticsSessionIfNeeded(source: .live)

        let evidenceSampler = EvidenceFrameSampler(configuration: evidenceCaptureConfiguration)
        self.evidenceSampler = evidenceSampler
        let coordinator = FrameInferenceCoordinator(
            runner: runner,
            eventDecoder: eventDecoder,
            evidenceSampler: evidenceSampler,
            targetRateHz: 8.0
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
        if activeDiagnosticSource == .live {
            evidenceSampler?.stop()
        }
        if activeDiagnosticSource == .live {
            finishDiagnosticsSession()
            activeDiagnosticSource = nil
        }
    }

    func startReplay(url: URL) {
        stopLiveInference()
        stopReplayForNewSession()
        guard let runner = modelRunner else {
            inferenceError = "The model is not ready."
            return
        }

        resetEvents()
        replayProgress = nil
        replayRunning = true
        activeDiagnosticSource = .replay
        beginDiagnosticsSessionIfNeeded(source: .replay)
        let replayRunner = VideoReplayRunner()
        let evidenceSampler = EvidenceFrameSampler(configuration: evidenceCaptureConfiguration)
        self.evidenceSampler = evidenceSampler
        self.replayRunner = replayRunner
        replayRunner.start(
            url: url,
            modelRunner: runner,
            eventDecoder: eventDecoder,
            evidenceSampler: evidenceSampler
        ) { [weak self] progress in
            Task { @MainActor in
                guard self?.replayRunner === replayRunner else { return }
                self?.applyReplay(progress)
            }
        }
    }

    func cancelReplay() {
        replayRunner?.cancel()
    }

    func resetEvents() {
        eventDecoder.reset()
        eventCount = 0
        latestPrediction = nil
        inferenceError = nil
        scoreHistory.removeAll(keepingCapacity: true)
        lastEventTimestampSeconds = nil
        latestFrame = nil
    }

    func setDiagnosticsRecording(_ enabled: Bool) {
        diagnosticsRecording = enabled
        diagnosticsError = nil
        if enabled, let activeDiagnosticSource {
            beginDiagnosticsSessionIfNeeded(source: activeDiagnosticSource)
        } else if !enabled {
            finishDiagnosticsSession()
        }
    }

    func recordAnnotation(_ kind: SessionLogAnnotation.Kind) {
        guard let source = activeDiagnosticSource, let sessionLog else {
            diagnosticsError = "Start diagnostics recording before adding an annotation."
            return
        }
        do {
            try sessionLog.appendAnnotation(
                SessionLogAnnotation(
                    source: source,
                    timestampSeconds: latestPrediction.map { CMTimeGetSeconds($0.timestamp) },
                    kind: kind
                )
            )
            saveDiagnosticFrame(kind.rawValue)
        } catch {
            diagnosticsError = error.localizedDescription
        }
    }

    func setThreshold(_ value: Double) {
        guard (0.0...1.0).contains(value) else { return }
        var configuration = eventDecoder.configuration
        configuration.threshold = value
        eventDecoder.updateConfiguration(configuration)
        objectWillChange.send()
    }

    private func apply(_ update: FrameInferenceUpdate) {
        latestPrediction = update.prediction ?? latestPrediction
        inferenceMetrics = update.metrics
        inferenceError = update.errorMessage
        if let prediction = update.prediction {
            latestFrame = update.frame
            if appendScore(prediction) {
                recordPrediction(prediction, event: update.event)
            }
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
            latestFrame = progress.frame ?? latestFrame
            if appendScore(prediction) {
                recordPrediction(prediction, event: progress.event)
            }
        }
        eventCount = progress.eventCount
        if let timestamp = progress.lastEventTimestampSeconds {
            lastEventTimestampSeconds = timestamp
        }
        if progress.isComplete {
            replayRunner = nil
            if activeDiagnosticSource == .replay {
                finishDiagnosticsSession()
                activeDiagnosticSource = nil
            }
        }
    }

    @discardableResult
    private func appendScore(_ prediction: ModelPrediction) -> Bool {
        let timestamp = CMTimeGetSeconds(prediction.timestamp)
        if scoreHistory.last?.timestampSeconds == timestamp {
            return false
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
        return true
    }

    private func beginDiagnosticsSessionIfNeeded(source: DiagnosticSource) {
        guard diagnosticsRecording, sessionLog == nil else { return }
        do {
            let directory = try diagnosticsDirectory()
            let configuration = eventDecoder.configuration
            let metadata = SessionLogMetadata(
                source: source,
                appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown",
                device: UIDevice.current.model,
                osVersion: UIDevice.current.systemVersion,
                modelName: "CardEventNetTransitionV2",
                modelVersion: modelRunner?.contract.metadata["version"] ?? "unknown",
                targetInferenceHz: 8.0,
                threshold: configuration.threshold,
                peakConfirmationMs: Int((CMTimeGetSeconds(configuration.peakConfirmation) * 1_000.0).rounded()),
                minimumEventGapMs: Int((CMTimeGetSeconds(configuration.minimumEventGap) * 1_000.0).rounded())
            )
            let log = try SessionLog(directory: directory, metadata: metadata)
            sessionLog = log
            diagnosticsLogURL = log.url
        } catch {
            diagnosticsRecording = false
            diagnosticsError = error.localizedDescription
        }
    }

    private func finishDiagnosticsSession() {
        sessionLog?.close()
        sessionLog = nil
    }

    private func stopReplayForNewSession() {
        replayRunner?.cancel()
        replayRunner = nil
        if activeDiagnosticSource == .replay {
            evidenceSampler?.stop()
            finishDiagnosticsSession()
            activeDiagnosticSource = nil
        }
    }

    private func recordPrediction(_ prediction: ModelPrediction, event: DetectionEvent?) {
        guard let source = activeDiagnosticSource, let sessionLog else { return }
        do {
            try sessionLog.appendPrediction(
                SessionLogPrediction(
                    source: source,
                    timestampSeconds: CMTimeGetSeconds(prediction.timestamp),
                    rawProbability: prediction.cardEventProbability,
                    smoothedProbability: prediction.cardEventProbability,
                    eventEmitted: event != nil,
                    inferenceMs: prediction.inferenceDurationMs
                )
            )
            if event != nil {
                saveDiagnosticFrame("event")
            }
        } catch {
            diagnosticsError = error.localizedDescription
        }
    }

    private func saveDiagnosticFrame(_ prefix: String) {
        guard let latestFrame, let sessionLog else { return }
        let timestamp = String(format: "%.3f", CMTimeGetSeconds(latestFrame.timestamp))
            .replacingOccurrences(of: ".", with: "_")
        let url = sessionLog.url.deletingLastPathComponent()
            .appendingPathComponent("\(prefix)-\(timestamp)-\(UUID().uuidString).jpg")
        do {
            try DiagnosticFrameWriter.writeJPEG(pixelBuffer: latestFrame.pixelBuffer, to: url)
        } catch {
            diagnosticsError = error.localizedDescription
        }
    }

    private func diagnosticsDirectory() throws -> URL {
        guard let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            throw SessionLogError.cannotCreateDirectory(URL(fileURLWithPath: "Documents"))
        }
        return documents
            .appendingPathComponent("CardEventProbeDiagnostics", isDirectory: true)
            .appendingPathComponent("session-\(UUID().uuidString)", isDirectory: true)
    }
}
