import Foundation
import SwiftUI

struct DiagnosticsPanel: View {
    @EnvironmentObject private var appState: AppState
    @State private var roiX = ""
    @State private var roiY = ""
    @State private var roiWidth = ""
    @State private var roiHeight = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Model")
                Spacer()
                Text(appState.modelState.title)
            }

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
                Text("ROI")
                Spacer()
                Text(appState.roiStatus)
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

            if let timestamp = appState.lastEventTimestampSeconds {
                Text(String(format: "Card event at %.3f s", timestamp))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.green)
            }

            ScoreHistoryView(
                samples: appState.scoreHistory,
                highThreshold: appState.eventPostProcessor.configuration.highThreshold,
                lowThreshold: appState.eventPostProcessor.configuration.lowThreshold
            )

            DisclosureGroup("Settings") {
                VStack(alignment: .leading, spacing: 8) {
                    thresholdSlider(
                        title: "High threshold",
                        value: appState.eventPostProcessor.configuration.highThreshold,
                        onChange: appState.setHighThreshold
                    )
                    thresholdSlider(
                        title: "Low threshold",
                        value: appState.eventPostProcessor.configuration.lowThreshold,
                        onChange: appState.setLowThreshold
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

            DisclosureGroup("Table ROI") {
                Text("Use normalized x, y, width, and height in the oriented camera frame.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    roiField("x", text: $roiX)
                    roiField("y", text: $roiY)
                    roiField("width", text: $roiWidth)
                    roiField("height", text: $roiHeight)
                }
                Button("Apply ROI") {
                    appState.setROI(
                        x: Double(roiX) ?? .nan,
                        y: Double(roiY) ?? .nan,
                        width: Double(roiWidth) ?? .nan,
                        height: Double(roiHeight) ?? .nan
                    )
                }
                if let roiError = appState.roiError {
                    Text(roiError)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            if let inferenceError = appState.inferenceError {
                Text(inferenceError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
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

    private func roiField(_ title: String, text: Binding<String>) -> some View {
        TextField(title, text: text)
            .textFieldStyle(.roundedBorder)
    }
}

private struct ScoreHistoryView: View {
    let samples: [ScoreSample]
    let highThreshold: Double
    let lowThreshold: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Score history")
                .font(.caption.weight(.medium))
            Canvas { context, size in
                drawThreshold(highThreshold, in: &context, size: size, color: .orange)
                drawThreshold(lowThreshold, in: &context, size: size, color: .blue)

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
