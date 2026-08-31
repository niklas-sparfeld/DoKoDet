import SwiftUI
import UIKit

struct RootView: View {
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
#if DEBUG
            TabView(selection: $selectedTab) {
                NavigationStack {
                    RecordingWorkspaceView()
                }
                .tabItem {
                    Label("Workspace", systemImage: "camera")
                }
                .tag(Tab.workspace)

                NavigationStack {
                    ReplayView()
                }
                .tabItem {
                    Label("Replay", systemImage: "film")
                }
                .tag(Tab.replay)
            }
#else
            NavigationStack {
                RecordingWorkspaceView()
            }
#endif
        }
        .onAppear {
            updateIdleTimer()
            appState.startBackendDiscovery()
            appState.uploadQueuedEvidence()
            appState.uploadQueuedTrainingRecordings()
            appState.startRecordingWorkspace()
        }
        .onDisappear {
            appState.stopRecordingWorkspace()
            UIApplication.shared.isIdleTimerDisabled = false
        }
        .onChange(of: appState.recordingWorkspaceState) { _, _ in
            updateIdleTimer()
        }
        .onChange(of: appState.replayRunning) { _, _ in
            updateIdleTimer()
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                updateIdleTimer()
            } else {
                UIApplication.shared.isIdleTimerDisabled = false
            }
        }
        .onChange(of: appState.backendDiscovery.state) { _, _ in
            appState.uploadQueuedEvidence()
            appState.uploadQueuedTrainingRecordings()
        }
    }

    private func updateIdleTimer() {
        UIApplication.shared.isIdleTimerDisabled = scenePhase == .active
            && (appState.recordingWorkspaceState.isRecording || appState.replayRunning)
    }

    @EnvironmentObject private var appState: AppState

#if DEBUG
    private enum Tab: Hashable {
        case workspace
        case replay
    }

    @State private var selectedTab: Tab = .workspace
#endif
}
