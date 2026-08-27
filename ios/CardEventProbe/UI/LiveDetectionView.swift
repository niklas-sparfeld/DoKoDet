import SwiftUI

struct LiveDetectionView: View {
    @StateObject private var camera = CameraSession()
    @State private var showingTrainingRecordingConsent = false
    @EnvironmentObject private var appState: AppState

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Text("CardEventProbe")
                    .font(.title2.weight(.semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)

                ZStack(alignment: .bottomLeading) {
                    CameraPreview(session: camera.captureSession) { orientation in
                        camera.updateInterfaceOrientation(orientation)
                    }
                        .frame(height: 300)
                        .clipShape(RoundedRectangle(cornerRadius: 16))

                    Text(camera.state.message)
                        .font(.caption.weight(.medium))
                        .padding(8)
                        .background(.black.opacity(0.65), in: Capsule())
                        .foregroundStyle(.white)
                        .padding(12)
                }

                HStack {
                    Label(
                        appState.captureActivity == .live ? "Capture session active" : "Capture session stopped",
                        systemImage: appState.captureActivity == .live ? "record.circle.fill" : "stop.circle"
                    )
                    .foregroundStyle(appState.captureActivity == .live ? .red : .secondary)

                    Spacer()

                    Button(
                        appState.captureActivity == .live ? "End capture" : "Start capture"
                    ) {
                        if appState.captureActivity == .live {
                            endCapture()
                        } else {
                            startCapture()
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(appState.captureActivity == .replay)
                }

                trainingRecordingPanel

                DiagnosticsPanel(cameraSourceRate: camera.sourceRateStatus)
            }
            .padding()
        }
        .navigationTitle("Live")
        .onAppear {
            if appState.captureActivity == .idle {
                startCapture()
            }
        }
        .onDisappear {
            endCapture()
        }
        .onReceive(
            Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()
        ) { now in
            appState.updateTrainingRecordingClock(now: now)
        }
        .alert("Start training recording?", isPresented: $showingTrainingRecordingConsent) {
            Button("Cancel", role: .cancel) {}
            Button("I agree") {
                appState.startTrainingRecording(sourcePermission: "training_and_evaluation")
            }
        } message: {
            Text("The live camera video and model predictions will be saved for training and evaluation.")
        }
    }

    private var trainingRecordingPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label(
                    appState.trainingRecordingState.title,
                    systemImage: appState.trainingRecordingState == .recording
                        ? "record.circle.fill"
                        : "tray.full"
                )
                .foregroundStyle(appState.trainingRecordingState == .recording ? .red : .primary)
                Spacer()
                if appState.trainingRecordingUploadRunning {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            if appState.trainingRecordingState == .recording {
                Text(
                    "\(formattedDuration(appState.trainingRecordingElapsedSeconds)) · \(formattedBytes(appState.trainingRecordingEstimatedSizeBytes))"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            HStack {
                Button(
                    appState.trainingRecordingState == .recording
                        ? "Stop training recording"
                        : "Start training recording"
                ) {
                    if appState.trainingRecordingState == .recording {
                        appState.stopTrainingRecording()
                    } else {
                        showingTrainingRecordingConsent = true
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(appState.trainingRecordingState == .recording ? .red : .accentColor)
                .disabled(
                    appState.trainingRecordingState == .recording
                        ? false
                        : !appState.canStartTrainingRecording
                )

                if case .failed = appState.trainingRecordingState {
                    Button("Retry upload") {
                        appState.retryFailedTrainingRecordings()
                    }
                    .buttonStyle(.bordered)
                    .disabled(appState.trainingRecordingUploadRunning)
                }
            }

            if let error = appState.trainingRecordingError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            } else if let error = appState.trainingRecordingUploadError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            if let diagnostics = appState.trainingRecordingQueueDiagnostics,
               diagnostics.queuedCount > 0 || diagnostics.failedCount > 0 {
                Text(
                    "\(diagnostics.queuedCount) queued · \(diagnostics.failedCount) failed · \(diagnostics.acknowledgedCount) acknowledged"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private func formattedDuration(_ seconds: Double) -> String {
        let totalSeconds = max(0, Int(seconds.rounded(.down)))
        return String(format: "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }

    private func formattedBytes(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }

    private func startCapture() {
        camera.setFrameHandler(appState.startLiveInference())
        camera.start()
    }

    private func endCapture() {
        camera.setFrameHandler(nil)
        camera.stop()
        appState.stopLiveInference()
    }
}
