import SwiftUI

struct LiveDetectionView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Text("CardEventProbe")
                    .font(.title2.weight(.semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)

                ZStack(alignment: .bottomLeading) {
                    CameraPreview(session: appState.cameraSession.captureSession) { orientation in
                        appState.cameraSession.updateInterfaceOrientation(orientation)
                    }
                        .frame(height: 300)
                        .clipShape(RoundedRectangle(cornerRadius: 16))

                    Text(appState.cameraState.message)
                        .font(.caption.weight(.medium))
                        .padding(8)
                        .background(.black.opacity(0.65), in: Capsule())
                        .foregroundStyle(.white)
                        .padding(12)
                }

                HStack {
                    Label(
                        appState.recordingWorkspaceState.title,
                        systemImage: appState.recordingWorkspaceState.isRecording
                            ? "record.circle.fill"
                            : "camera"
                    )
                    .foregroundStyle(appState.recordingWorkspaceState.isRecording ? .red : .primary)

                    Spacer()
                }

                DiagnosticsPanel(cameraSourceRate: appState.cameraSession.sourceRateStatus)
            }
            .padding()
        }
        .navigationTitle("Live")
    }
}
