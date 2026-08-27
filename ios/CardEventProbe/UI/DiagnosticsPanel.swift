import Foundation
import SwiftUI

struct DiagnosticsPanel: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            CaptureStatusView(appState: appState)
            EvidenceQueueStatusView(appState: appState)
            BackendStatusView(discovery: appState.backendDiscovery)

            HStack {
                Text("Model")
                Spacer()
                Text(appState.modelState.title)
            }

#if DEBUG
            DeveloperDiagnosticsView(appState: appState)
#endif

            if let packageError = appState.evidencePackageError {
                OperatorErrorView(title: "Package", message: packageError)
            }

            if let uploadError = appState.evidenceUploadError {
                OperatorErrorView(title: "Upload", message: uploadError)
            }

            if let inferenceError = appState.inferenceError {
                OperatorErrorView(title: "Capture", message: inferenceError)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

}

private struct CaptureStatusView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Capture")
                Spacer()
                Text(appState.captureActivity.title)
                    .fontWeight(.medium)
            }
            HStack {
                Text("Session")
                Spacer()
                Text(sessionIDText)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
            }
            HStack {
                Text("Latest event sequence")
                Spacer()
                Text(appState.latestEventSequence.map(String.init) ?? "—")
                    .monospacedDigit()
            }
        }
        .padding(.bottom, 4)
    }

    private var sessionIDText: String {
        guard let sessionID = appState.captureSessionID else { return "—" }
        return sessionID.uuidString.lowercased()
    }
}

private struct EvidenceQueueStatusView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Evidence queue")
                    .fontWeight(.medium)
                Spacer()
                if appState.evidenceUploadRunning {
                    ProgressView()
                        .controlSize(.small)
                    Text("Uploading")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let diagnostics = appState.evidenceQueueDiagnostics {
                LazyVGrid(
                    columns: [GridItem(.flexible()), GridItem(.flexible())],
                    alignment: .leading,
                    spacing: 4
                ) {
                    QueueCountView(title: "Queued", count: diagnostics.queuedCount)
                    QueueCountView(title: "Acknowledged", count: diagnostics.acknowledgedCount)
                    QueueCountView(title: "Retryable failures", count: diagnostics.retryableFailureCount)
                    QueueCountView(title: "Permanent failures", count: diagnostics.permanentFailureCount)
                }

                if diagnostics.stagingCount > 0 || diagnostics.corruptCount > 0 {
                    Text(
                        "Staging \(diagnostics.stagingCount) · corrupt \(diagnostics.corruptCount)"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                if diagnostics.retryableFailureCount > 0 {
                    Button("Retry retryable packages") {
                        appState.retryFailedEvidence()
                    }
                    .buttonStyle(.bordered)
                    .disabled(appState.evidenceUploadRunning)
                }
            } else {
                Text("Queue status is not available.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.bottom, 4)
    }
}

private struct QueueCountView: View {
    let title: String
    let count: Int

    var body: some View {
        HStack {
            Text(title)
                .font(.caption)
            Spacer()
            Text("\(count)")
                .font(.caption.monospacedDigit())
        }
    }
}

private struct OperatorErrorView: View {
    let title: String
    let message: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(title) error")
                .font(.caption.weight(.semibold))
            Text(message)
                .font(.caption)
                .textSelection(.enabled)
        }
        .foregroundStyle(.red)
    }
}

#if DEBUG
private struct DeveloperDiagnosticsView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            switch appState.modelState {
            case let .ready(contract):
                Text(contract.summary)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            case let .failed(message):
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.red)
            case .loading:
                ProgressView()
            }

            HStack {
                Text("Events")
                Spacer()
                Text("\(appState.eventCount)")
            }

            HStack {
                Text("Score")
                Spacer()
                Text(appState.latestPrediction.map { String(format: "%.3f", $0.cardEventProbability) } ?? "—")
            }

            HStack {
                Text("Inference")
                Spacer()
                Text(appState.latestPrediction.map { String(format: "%.1f ms", $0.inferenceDurationMs) } ?? "—")
            }

            HStack {
                Text("Frames")
                Spacer()
                Text("\(appState.inferenceMetrics.cameraFramesReceived)")
            }

            HStack {
                Text("Skipped / busy")
                Spacer()
                Text("\(appState.inferenceMetrics.framesSkippedForSampling) / \(appState.inferenceMetrics.framesDroppedWhileBusy)")
            }

            HStack {
                Text("Rate / avg")
                Spacer()
                Text(rateAndLatency)
            }

            HStack {
                Text("Thermal")
                Spacer()
                Text(appState.thermalStateDescription)
            }

            if let packageID = appState.latestEvidencePackageID {
                DisclosureGroup("Vision result (developer)") {
                    Button("Read backend result") {
                        appState.loadEvidenceResults(for: packageID)
                    }
                    if appState.latestEvidenceResults.isEmpty {
                        Text("No stored result loaded.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(appState.latestEvidenceResults, id: \.resultID) { result in
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Status: \(result.status)")
                                Text("Detector: \(result.detector.name) \(result.detector.version)")
                                ForEach(result.candidates, id: \.card) { candidate in
                                    Text(String(format: "%@ %.3f", candidate.card, candidate.probability))
                                }
                            }
                            .font(.caption.monospaced())
                        }
                    }
                    if let error = appState.evidenceResultError {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
            }

            if let timestamp = appState.lastEventTimestampSeconds {
                Text(String(format: "Card event at %.3f s", timestamp))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.green)
            }

            ScoreHistoryView(
                samples: appState.scoreHistory,
                threshold: appState.eventDecoder.configuration.threshold
            )

            DisclosureGroup("Settings") {
                VStack(alignment: .leading, spacing: 8) {
                    thresholdSlider(
                        title: "Threshold",
                        value: appState.eventDecoder.configuration.threshold,
                        onChange: appState.setThreshold
                    )
                    Button("Reset events and history") {
                        appState.resetEvents()
                    }
                }
                .padding(.top, 4)
            }

            DisclosureGroup("Diagnostics recording") {
                VStack(alignment: .leading, spacing: 8) {
                    Toggle(
                        "Record session log and event frames",
                        isOn: Binding(
                            get: { appState.diagnosticsRecording },
                            set: appState.setDiagnosticsRecording
                        )
                    )
                    Text("Logs and images stay on this device until you export them.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack {
                        Button("Missed event") {
                            appState.recordAnnotation(.missedEvent)
                        }
                        Button("False event") {
                            appState.recordAnnotation(.falseEvent)
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(!appState.diagnosticsRecording)
                    if let url = appState.diagnosticsLogURL {
                        ShareLink(item: url) {
                            Label("Export session log", systemImage: "square.and.arrow.up")
                        }
                    }
                    if let diagnosticsError = appState.diagnosticsError {
                        Text(diagnosticsError)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
                .padding(.top, 4)
            }
        }
    }

    private var rateAndLatency: String {
        let rate = appState.actualPredictionRateHz.map { String(format: "%.1f Hz", $0) } ?? "—"
        let latency = appState.inferenceMetrics.averageInferenceDurationMs
            .map { String(format: "%.1f ms", $0) } ?? "—"
        return "\(rate) / \(latency)"
    }

    private func thresholdSlider(
        title: String,
        value: Double,
        onChange: @escaping (Double) -> Void
    ) -> some View {
        VStack(alignment: .leading) {
            HStack {
                Text(title)
                Spacer()
                Text(String(format: "%.2f", value))
                    .monospacedDigit()
            }
            Slider(value: Binding(get: { value }, set: onChange), in: 0.0...1.0)
        }
    }
}
#endif

private struct BackendStatusView: View {
    @ObservedObject var discovery: BackendDiscovery

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Backend")
                Spacer()
                Text(discovery.state.title)
            }
            if let detail = discovery.state.detail ?? discovery.diagnosticMessage {
                Text(detail)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
    }
}

private struct ScoreHistoryView: View {
    let samples: [ScoreSample]
    let threshold: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Score history")
                .font(.caption.weight(.medium))
            Canvas { context, size in
                drawThreshold(threshold, in: &context, size: size, color: .orange)

                guard samples.count > 1 else { return }
                var path = Path()
                for (index, sample) in samples.enumerated() {
                    let x = CGFloat(index) / CGFloat(samples.count - 1) * size.width
                    let y = CGFloat(1.0 - sample.probability) * size.height
                    let point = CGPoint(x: x, y: y)
                    if index == 0 {
                        path.move(to: point)
                    } else {
                        path.addLine(to: point)
                    }
                }
                context.stroke(path, with: .color(.green), lineWidth: 2)
            }
            .frame(height: 90)
            .background(.black.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        }
    }

    private func drawThreshold(
        _ threshold: Double,
        in context: inout GraphicsContext,
        size: CGSize,
        color: Color
    ) {
        let y = CGFloat(1.0 - threshold) * size.height
        var path = Path()
        path.move(to: CGPoint(x: 0, y: y))
        path.addLine(to: CGPoint(x: size.width, y: y))
        context.stroke(path, with: .color(color.opacity(0.7)), style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
    }
}
