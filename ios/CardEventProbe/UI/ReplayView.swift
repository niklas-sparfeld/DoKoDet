import SwiftUI
import UniformTypeIdentifiers

struct ReplayView: View {
    @State private var showingImporter = false
    @State private var selectedVideoName: String?

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
                Text("Replay processing is the next implementation slice.")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text("No replay loaded")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

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
                selectedVideoName = url.lastPathComponent
            }
        }
    }
}
