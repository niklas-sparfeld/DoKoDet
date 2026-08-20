import Foundation
import SwiftUI

struct DiagnosticsPanel: View {
    @EnvironmentObject private var appState: AppState

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

            if let inferenceError = appState.inferenceError {
                Text(inferenceError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
