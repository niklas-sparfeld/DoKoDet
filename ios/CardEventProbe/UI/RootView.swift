import SwiftUI

struct RootView: View {
    @State private var selectedTab: AppTab = .live

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
            appState.startBackendDiscovery()
            appState.uploadQueuedEvidence()
            appState.uploadQueuedTrainingRecordings()
        }
        .onChange(of: appState.backendDiscovery.state) { _, _ in
            appState.uploadQueuedEvidence()
            appState.uploadQueuedTrainingRecordings()
        }
    }

    @EnvironmentObject private var appState: AppState
}
