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

                DiagnosticsPanel()
            }
            .padding()
        }
        .navigationTitle("Live")
        .onAppear {
            camera.setFrameHandler(appState.startLiveInference())
            camera.start()
        }
        .onDisappear {
            camera.setFrameHandler(nil)
            camera.stop()
            appState.stopLiveInference()
        }
    }
}
