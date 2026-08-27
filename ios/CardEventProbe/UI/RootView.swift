import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            NavigationStack {
                LiveDetectionView()
            }
            .tabItem {
                Label("Live", systemImage: "camera")
            }

            NavigationStack {
                ReplayView()
            }
            .tabItem {
                Label("Replay", systemImage: "film")
            }
        }
        .onAppear {
            appState.startBackendDiscovery()
            appState.uploadQueuedEvidence()
        }
        .onChange(of: appState.backendDiscovery.state) { _, _ in
            appState.uploadQueuedEvidence()
        }
    }

    @EnvironmentObject private var appState: AppState
}
