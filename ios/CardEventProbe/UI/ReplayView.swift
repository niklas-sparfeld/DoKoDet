import SwiftUI
import UniformTypeIdentifiers

struct ReplayView: View {
    @EnvironmentObject private var appState: AppState
    @State private var showingImporter = false
    @State private var selectedVideoName: String?
    @State private var selectedURL: URL?

    var body: some View {
        VStack(spacing: 20) {
            Text("Replay")
                .font(.title2.weight(.semibold))
                .frame(maxWidth: .infinity, alignment: .leading)

            Button("Choose Video") {
                showingImporter = true
            }
            .buttonStyle(.borderedProminent)

            if let selectedVideoName {
                Text(selectedVideoName)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if !appState.replayRunning, let selectedURL {
                    Button("Run Replay") {
                        appState.startReplay(url: selectedURL)
                    }
                    .buttonStyle(.bordered)
                }
            } else {
                Text("No replay loaded")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            if let progress = appState.replayProgress {
                VStack(alignment: .leading, spacing: 8) {
                    Text(
                        progress.isCancelled
                            ? "Replay cancelled"
                            : progress.isComplete ? "Replay complete" : "Replay running"
                    )
                    .font(.headline)
                    if progress.durationSeconds > 0.0 {
                        ProgressView(
                            value: min(
                                max(progress.currentTimeSeconds / progress.durationSeconds, 0.0),
                                1.0
                            )
                        )
                    }
                    Text(
                        String(
                            format: "Time %.3f s · %d frames · %d predictions",
                            progress.currentTimeSeconds,
                            progress.framesRead,
                            progress.predictionsProduced
                        )
                    )
                    .font(.caption)
                    Text(
                        String(
                            format: "Events %d · average %.1f ms",
                            progress.eventCount,
                            progress.averageInferenceDurationMs ?? 0.0
                        )
                    )
                    .font(.caption)
                    if let errorMessage = progress.errorMessage {
                        Text(errorMessage)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                    if appState.replayRunning {
                        Button("Cancel Replay") {
                            appState.cancelReplay()
                        }
                        .buttonStyle(.bordered)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
            }

            DiagnosticsPanel()

            Spacer()
        }
        .padding()
        .navigationTitle("Replay")
        .fileImporter(
            isPresented: $showingImporter,
            allowedContentTypes: [.movie],
            allowsMultipleSelection: false
        ) { result in
            if case let .success(urls) = result, let url = urls.first {
                selectedURL = url
                selectedVideoName = url.lastPathComponent
            } else {
                selectedURL = nil
                selectedVideoName = nil
            }
        }
    }
}
