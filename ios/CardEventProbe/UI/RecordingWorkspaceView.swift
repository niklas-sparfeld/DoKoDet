import SwiftUI

struct RecordingWorkspaceView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.scenePhase) private var scenePhase
    @State private var showingProfileEditor = false
    @State private var showingOperatorSettings = false
    @State private var showingDetails = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                profileRow
                cameraFrame
                eventCount
                primaryControl
                if surfaceState.showsElapsedTime {
                    elapsedTime
                }
                lifecycleStatus
                moreDetailsButton
            }
            .padding()
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Settings", systemImage: "gear") {
                    showingOperatorSettings = true
                }
                .accessibilityLabel("Operator settings")
                .disabled(surfaceState.profileControlsLocked)
            }
        }
        .onAppear {
            appState.startRoundAnalysisPolling()
        }
        .onDisappear {
            appState.stopRoundAnalysisPolling()
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                appState.startRoundAnalysisPolling()
            } else {
                appState.stopRoundAnalysisPolling()
            }
        }
        .onReceive(Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()) { now in
            appState.updateTrainingRecordingClock(now: now)
        }
        .sheet(isPresented: $showingProfileEditor) {
            NavigationStack {
                RecordingProfileEditorView(
                    profile: appState.selectedRecordingProfile ?? appState.newRecordingProfileDraft()
                )
            }
        }
        .sheet(isPresented: $showingOperatorSettings) {
            NavigationStack {
                OperatorSettingsView(settings: appState.operatorSettings)
            }
        }
        .sheet(isPresented: $showingDetails) {
            NavigationStack {
                RecordingWorkspaceDetailsView()
            }
        }
    }

    private var surfaceState: RecordingWorkspaceSurfaceState {
        RecordingWorkspaceSurfaceState(
            workspaceState: appState.recordingWorkspaceState,
            trainingState: appState.trainingRecordingState,
            roundAnalysisState: appState.roundAnalysisState,
            startRequirements: appState.recordingStartRequirements,
            eventCount: appState.eventCount,
            elapsedSeconds: appState.trainingRecordingElapsedSeconds,
            uploadDetail: uploadDetail,
            uploadError: appState.trainingRecordingUploadError
                ?? appState.trainingRecordingError
                ?? appState.evidenceUploadError
        )
    }

    private var profileRow: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Recording profile")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(appState.selectedRecordingProfile?.name ?? "No profile selected")
                    .font(.headline)
                    .lineLimit(1)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Recording profile")
            .accessibilityValue(appState.selectedRecordingProfile?.name ?? "No profile selected")

            Spacer()

            Button("Change") {
                showingProfileEditor = true
            }
            .buttonStyle(.bordered)
            .accessibilityLabel("Change recording profile")
            .disabled(surfaceState.profileControlsLocked)
        }
    }

    private var cameraFrame: some View {
        ZStack(alignment: .bottomLeading) {
            CameraPreview(session: appState.cameraSession.captureSession) { orientation in
                appState.cameraSession.updateInterfaceOrientation(orientation)
            }
            .frame(height: 260)
            .clipShape(RoundedRectangle(cornerRadius: 16))

            Text(appState.cameraState.message)
                .font(.caption.weight(.medium))
                .padding(8)
                .background(.black.opacity(0.65), in: Capsule())
                .foregroundStyle(.white)
                .padding(12)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Live camera frame")
        .accessibilityValue(appState.cameraState.message)
    }

    private var eventCount: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(appState.eventCount) events detected")
                .font(.title3.weight(.semibold))
            Text("Live detection smoke test")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(surfaceState.eventCountAccessibilityLabel)
        .accessibilityValue(surfaceState.eventCountAccessibilityValue)
    }

    private var primaryControl: some View {
        Button(surfaceState.primaryActionTitle) {
            if case .recording = appState.recordingWorkspaceState {
                appState.stopRecording()
            } else if let profile = appState.selectedRecordingProfile {
                appState.startRecording(profile: profile)
            }
        }
        .buttonStyle(.borderedProminent)
        .tint(appState.recordingWorkspaceState.isRecording ? .red : .accentColor)
        .frame(maxWidth: .infinity, minHeight: 52)
        .disabled(!surfaceState.primaryActionEnabled)
        .accessibilityLabel(surfaceState.primaryActionAccessibilityLabel)
        .accessibilityHint(surfaceState.primaryActionAccessibilityHint ?? "")
    }

    private var elapsedTime: some View {
        Label(
            "Recording \(formattedDuration(appState.trainingRecordingElapsedSeconds))",
            systemImage: "record.circle.fill"
        )
        .foregroundStyle(.red)
        .accessibilityLabel("Recording elapsed time")
        .accessibilityValue(formattedDuration(appState.trainingRecordingElapsedSeconds))
    }

    private var lifecycleStatus: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(surfaceState.status.title)
                .font(.subheadline.weight(.semibold))
            if let detail = surfaceState.status.detail {
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let blocker = surfaceState.startBlocker,
               !surfaceState.primaryActionEnabled,
               surfaceState.status.detail != blocker {
                Text(blocker)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if surfaceState.status.tone == .failure {
                Button("Retry camera preview") {
                    appState.startRecordingWorkspace()
                }
                .buttonStyle(.bordered)
                .disabled(appState.recordingWorkspaceState.isRecording)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(statusBackground, in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Upload and analysis status")
    }

    private var moreDetailsButton: some View {
        Button("More details") {
            showingDetails = true
        }
        .buttonStyle(.bordered)
        .frame(maxWidth: .infinity)
        .accessibilityHint("Shows profile, queue, analysis, and diagnostic details.")
    }

    private var statusBackground: Color {
        switch surfaceState.status.tone {
        case .neutral:
            return Color.secondary.opacity(0.10)
        case .active:
            return Color.accentColor.opacity(0.12)
        case .success:
            return Color.green.opacity(0.12)
        case .warning:
            return Color.orange.opacity(0.12)
        case .failure:
            return Color.red.opacity(0.12)
        }
    }

    private var uploadDetail: String? {
        guard let progress = appState.trainingRecordingUploadProgress else { return nil }
        switch progress.phase {
        case .preparing:
            return "Preparing upload"
        case .uploading:
            return "Uploading \(progress.percentage)%"
        }
    }

    private func formattedDuration(_ seconds: Double) -> String {
        let totalSeconds = max(0, Int(seconds.rounded(.down)))
        return String(format: "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }
}

private struct RecordingProfileEditorView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var profile: RecordingProfile
    @State private var tagsText: String

    init(profile: RecordingProfile) {
        _profile = State(initialValue: profile)
        _tagsText = State(initialValue: profile.tags.joined(separator: ", "))
    }

    var body: some View {
        Form {
            Section("Saved recording profiles") {
                Picker("Saved profile", selection: selectedProfileID) {
                    ForEach(appState.recordingProfiles) { savedProfile in
                        Text(savedProfile.name).tag(savedProfile.profileID)
                    }
                }
                Button("New recording profile") {
                    profile = appState.newRecordingProfileDraft()
                    tagsText = ""
                }
                .disabled(appState.isRecordingLocked)
            }

            Section("Profile") {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Profile name")
                    TextField("Enter a profile name", text: $profile.name)
                }

                Picker("Recording purpose", selection: $profile.purpose) {
                    ForEach(RecordingPurpose.allCases, id: \.self) { purpose in
                        Text(purpose.title).tag(purpose)
                    }
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Tags")
                    TextField("Separate tags with commas", text: $tagsText)
                }
            }

            Section {
                Text("These settings apply each time this profile starts a recording.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ForEach(RepositoryDataTask.allCases, id: \.self) { task in
                    taskSetting(for: task)
                }
            } header: {
                Text("Task enrollment")
            }

            if !profile.validationIssues.isEmpty {
                Section("Profile validation") {
                    ForEach(Array(profile.validationIssues.enumerated()), id: \.offset) { _, issue in
                        Text("\(issue.field.rawValue): \(issue.message)")
                            .foregroundStyle(.red)
                    }
                }
            }

            if let notice = appState.obsoleteRecordingProfileNotice {
                Section("Saved profile notice") {
                    Text(notice)
                        .foregroundStyle(.secondary)
                }
            }

            if let error = appState.recordingProfileError {
                Section("Storage error") {
                    Text(error)
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("Recording profile")
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") {
                    dismiss()
                }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") {
                    profile.tags = parsedTags(tagsText)
                    appState.saveRecordingProfile(profile)
                    appState.selectRecordingProfile(profile.profileID)
                    dismiss()
                }
                .disabled(!profile.isComplete || appState.isRecordingLocked)
            }
        }
        .disabled(appState.isRecordingLocked)
    }

    private var selectedProfileID: Binding<String> {
        Binding(
            get: { profile.profileID },
            set: { profileID in
                guard let selected = appState.recordingProfiles.first(where: {
                    $0.profileID == profileID
                }) else {
                    return
                }
                profile = selected
                tagsText = selected.tags.joined(separator: ", ")
                appState.selectRecordingProfile(profileID)
            }
        )
    }

    @ViewBuilder
    private func taskSetting(for task: RepositoryDataTask) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(task.rawValue)
                .font(.subheadline.weight(.medium))
            Picker("Disposition", selection: dispositionBinding(for: task)) {
                ForEach(RepositoryTaskDisposition.allCases, id: \.self) { disposition in
                    Text(disposition.rawValue.capitalized).tag(disposition)
                }
            }
            if profile.taskSetting(for: task)?.disposition == .excluded {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Exclusion reason")
                    TextField("Explain why this task is excluded", text: reasonBinding(for: task))
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func dispositionBinding(for task: RepositoryDataTask) -> Binding<RepositoryTaskDisposition> {
        Binding(
            get: { profile.taskSetting(for: task)?.disposition ?? .selected },
            set: { disposition in
                var settings = profile.taskSettings
                guard let index = settings.firstIndex(where: { $0.task == task }) else { return }
                settings[index].disposition = disposition
                settings[index].reason = nil
                profile.taskSettings = settings
            }
        )
    }

    private func reasonBinding(for task: RepositoryDataTask) -> Binding<String> {
        Binding(
            get: { profile.taskSetting(for: task)?.reason ?? "" },
            set: { reason in
                var settings = profile.taskSettings
                guard let index = settings.firstIndex(where: { $0.task == task }) else { return }
                settings[index].reason = reason.nilIfBlank
                profile.taskSettings = settings
            }
        )
    }

    private func parsedTags(_ value: String) -> [String] {
        value.split(separator: ",", omittingEmptySubsequences: true)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }
}

private struct OperatorSettingsView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var operatorName: String

    init(settings: OperatorSettings) {
        _operatorName = State(initialValue: settings.operatorName)
    }

    var body: some View {
        Form {
            Section("Operator") {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Operator name")
                    TextField("Enter your name", text: $operatorName)
                }
                Text("The app snapshots this name when a recording starts.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Operator settings")
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") {
                    dismiss()
                }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") {
                    appState.updateOperatorSettings(OperatorSettings(operatorName: operatorName))
                    dismiss()
                }
            }
        }
    }
}

private struct RecordingWorkspaceDetailsView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        List {
            Section("Upload and analysis") {
                LabeledContent("Recording upload", value: appState.trainingRecordingState.title)
                if let progress = appState.trainingRecordingUploadProgress {
                    LabeledContent("Upload progress", value: "\(progress.percentage)%")
                }
                if appState.roundAnalysisState != .idle {
                    LabeledContent("Analysis", value: appState.roundAnalysisState.title)
                    if let detail = appState.roundAnalysisState.detail {
                        Text(detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                if case .failed = appState.trainingRecordingState {
                    Button("Retry recording upload") {
                        appState.retryFailedTrainingRecordings()
                    }
                    .disabled(appState.trainingRecordingUploadRunning)
                }
                if appState.evidenceQueueDiagnostics?.retryableFailureCount ?? 0 > 0 {
                    Button("Retry evidence uploads") {
                        appState.retryFailedEvidence()
                    }
                    .disabled(appState.evidenceUploadRunning)
                }
            }

            Section("Diagnostics") {
                DiagnosticsPanel(cameraSourceRate: appState.cameraSession.sourceRateStatus)
            }
        }
        .navigationTitle("More details")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Done") {
                    dismiss()
                }
            }
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
