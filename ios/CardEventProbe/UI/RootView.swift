import SwiftUI
import UIKit

struct RootView: View {
    @State private var selectedTab: AppTab = .live
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationStack {
                LiveDetectionView()
            }
            .tabItem {
                Label("Live", systemImage: "camera")
            }
            .tag(AppTab.live)

            NavigationStack {
                RecordView()
            }
            .tabItem {
                Label("Record", systemImage: "record.circle")
            }
            .tag(AppTab.record)

#if DEBUG
            NavigationStack {
                ReplayView()
            }
            .tabItem {
                Label("Replay", systemImage: "film")
            }
            .tag(AppTab.replay)
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
}
