import SwiftUI

struct LiveDetectionView: View {
    @StateObject private var camera = CameraSession()
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
