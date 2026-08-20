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
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
