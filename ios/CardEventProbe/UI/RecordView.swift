import SwiftUI

struct RecordView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var camera = CameraSession()
    @State private var profile: RecordingProfile
    @State private var selectedProfileID: String?
    @State private var tagsText = ""
    @State private var operatorNameText = ""

    init() {
        _profile = State(initialValue: RecordingProfile.newDraft())
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                cameraPanel
                profilePanel
                taskPanel
                recordingPanel
                DiagnosticsPanel(cameraSourceRate: camera.sourceRateStatus)
            }
            .padding()
        }
        .navigationTitle("Record")
        .onAppear {
            loadSelectedProfile()
            operatorNameText = appState.operatorSettings.operatorName
            appState.startRoundAnalysisPolling()
            if appState.captureActivity == .idle {
                startCapture()
            }
        }
        .onDisappear {
            if appState.trainingRecordingState == .recording {
                appState.stopTrainingRecording()
            }
            endCapture()
            appState.stopRoundAnalysisPolling()
        }
        .onChange(of: selectedProfileID) { _, newValue in
            guard let newValue else {
                profile = appState.newRecordingProfileDraft()
                syncTextFields()
                appState.selectRecordingProfile(nil)
                return
            }
            guard let selected = appState.recordingProfiles.first(where: { $0.profileID == newValue }) else {
                return
            }
            profile = selected
            syncTextFields()
            appState.selectRecordingProfile(newValue)
        }
        .onChange(of: tagsText) { _, newValue in
            profile.tags = parsedValues(newValue)
        }
        .onReceive(Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()) { now in
            appState.updateTrainingRecordingClock(now: now)
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                appState.startRoundAnalysisPolling()
            } else {
                appState.stopRoundAnalysisPolling()
            }
        }
    }

    private var cameraPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            ZStack(alignment: .bottomLeading) {
                CameraPreview(session: camera.captureSession) { orientation in
                    camera.updateInterfaceOrientation(orientation)
                }
                .frame(height: 240)
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
                Button(appState.captureActivity == .live ? "End capture" : "Start capture") {
                    if appState.captureActivity == .live {
                        endCapture()
                    } else {
                        startCapture()
                    }
                }
                .buttonStyle(.bordered)
                .disabled(appState.captureActivity == .replay)
            }
        }
    }

    private var profilePanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Recording profile")
                    .font(.headline)
                Spacer()
                Button("New") {
                    selectedProfileID = nil
                    profile = appState.newRecordingProfileDraft()
                    syncTextFields()
                }
                .buttonStyle(.bordered)
            }

            Picker("Saved profile", selection: $selectedProfileID) {
                Text("New profile").tag(nil as String?)
                ForEach(appState.recordingProfiles) { savedProfile in
                    Text(savedProfile.name).tag(savedProfile.profileID as String?)
                }
            }

            TextField("Profile name", text: $profile.name)
                .accessibilityLabel("Profile name")
            Picker("Recording purpose", selection: $profile.purpose) {
                ForEach(RecordingPurpose.allCases, id: \.self) { purpose in
                    Text(purpose.title).tag(purpose)
                }
            }
            TextField("Tags, comma separated", text: $tagsText)
                .accessibilityLabel("Recording profile tags")

            Text("Operator settings")
                .font(.subheadline.weight(.medium))
            TextField("Operator name", text: $operatorNameText)
                .accessibilityLabel("Operator name")
            Button("Save operator settings") {
                appState.updateOperatorSettings(OperatorSettings(operatorName: operatorNameText))
            }
            .buttonStyle(.bordered)

            Button("Save profile") {
                applyTextFields()
                appState.saveRecordingProfile(profile)
                selectedProfileID = profile.profileID
            }
            .buttonStyle(.borderedProminent)

            validationMessages(for: profile.validationIssues)
            if let notice = appState.obsoleteRecordingProfileNotice {
                Text(notice)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let error = appState.recordingProfileError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
        .disabled(appState.isRoundRecordingLocked)
    }

    private var taskPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Task enrollments")
                .font(.headline)
            Text("Profile dispositions are captured when recording starts.")
                .font(.caption)
                .foregroundStyle(.secondary)

            ForEach(RepositoryDataTask.allCases, id: \.self) { task in
                VStack(alignment: .leading, spacing: 6) {
                    Text(task.rawValue)
                        .font(.subheadline.weight(.medium))
                    Picker("Task disposition", selection: profileDispositionBinding(for: task)) {
                        ForEach(RepositoryTaskDisposition.allCases, id: \.self) { disposition in
                            Text(disposition.rawValue.capitalized).tag(disposition)
                        }
                    }
                    if profile.taskSetting(for: task)?.disposition == .excluded {
                        TextField("Profile exclusion reason", text: profileReasonBinding(for: task))
                    }
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
        .disabled(appState.isRoundRecordingLocked)
    }

    private var recordingPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label(
                    appState.trainingRecordingState.title,
                    systemImage: appState.trainingRecordingState == .recording
                        ? "record.circle.fill"
                        : "tray.full"
                )
                .foregroundStyle(appState.trainingRecordingState == .recording ? .red : .primary)
                Spacer()
            }

            if appState.trainingRecordingState == .recording {
                Text(
                    "\(formattedDuration(appState.trainingRecordingElapsedSeconds)) · "
                        + "\(formattedBytes(appState.trainingRecordingEstimatedSizeBytes))"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            if appState.trainingRecordingUploadRunning
                || appState.trainingRecordingUploadProgress != nil {
                trainingRecordingUploadProgressView
            }
            roundAnalysisStatusView

            Button(
                appState.trainingRecordingState == .recording
                    ? "Stop round recording"
                    : "Start round recording"
            ) {
                if appState.trainingRecordingState == .recording {
                    appState.stopTrainingRecording()
                } else {
                    appState.updateOperatorSettings(OperatorSettings(operatorName: operatorNameText))
                    appState.startTrainingRecording(profile: profile)
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(appState.trainingRecordingState == .recording ? .red : .accentColor)
            .disabled(
                appState.trainingRecordingState == .recording
                    ? false
                    : !appState.canStartTrainingRecording || !profile.isComplete
            )

            if case .failed = appState.trainingRecordingState {
                Button("Retry upload") {
                    appState.retryFailedTrainingRecordings()
                }
                .buttonStyle(.bordered)
                .disabled(appState.trainingRecordingUploadRunning)
            }
            if let error = appState.trainingRecordingError ?? appState.trainingRecordingUploadError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
            if let diagnostics = appState.trainingRecordingQueueDiagnostics,
               diagnostics.queuedCount > 0 || diagnostics.failedCount > 0 {
                Text(
                    "\(diagnostics.queuedCount) queued · \(diagnostics.failedCount) failed · "
                        + "\(diagnostics.acknowledgedCount) acknowledged"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private var roundAnalysisStatusView: some View {
        if appState.roundAnalysisState != .idle {
            VStack(alignment: .leading, spacing: 4) {
                Label("Round analysis", systemImage: "waveform.path.ecg")
                    .font(.subheadline.weight(.medium))
                Text(appState.roundAnalysisState.title)
                    .font(.subheadline)
                switch appState.roundAnalysisState {
                case let .complete(summary):
                    Text("Result: \(summary.text)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                case let .failed(message):
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.red)
                default:
                    if let detail = appState.roundAnalysisState.detail {
                        Text(detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                appState.roundAnalysisState.isFailure
                    ? Color.red.opacity(0.10)
                    : Color.accentColor.opacity(0.08),
                in: RoundedRectangle(cornerRadius: 10)
            )
            .accessibilityElement(children: .combine)
        }
    }

    @ViewBuilder
    private var trainingRecordingUploadProgressView: some View {
        if let progress = appState.trainingRecordingUploadProgress,
           progress.phase == .uploading {
            uploadTransferProgressView(progress)
        } else {
            HStack(spacing: 8) {
                ProgressView()
                    .controlSize(.small)
                Text("Preparing upload")
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Preparing upload")
        }
    }

    private func uploadTransferProgressView(
        _ progress: TrainingRecordingUploadProgress
    ) -> some View {
        let percentage = progress.percentage
        let sentBytes = formattedBytes(progress.bytesSent)
        let expectedBytes = formattedBytes(progress.expectedBytes)
        return VStack(alignment: .leading, spacing: 4) {
            ProgressView(value: progress.fraction)
                .accessibilityLabel("Uploading training recording")
                .accessibilityValue("\(percentage) percent")
            Text("Uploading \(percentage)% · \(sentBytes) of \(expectedBytes)")
                .font(.caption)
                .foregroundStyle(.secondary)
                .accessibilityLabel(
                    "Uploading \(percentage) percent, \(sentBytes) of \(expectedBytes)"
                )
        }
    }

    private func loadSelectedProfile() {
        selectedProfileID = appState.selectedRecordingProfileID
        if let selectedProfileID,
           let selected = appState.recordingProfiles.first(where: { $0.profileID == selectedProfileID }) {
            profile = selected
        }
        syncTextFields()
    }

    private func syncTextFields() {
        tagsText = profile.tags.joined(separator: ", ")
    }

    private func applyTextFields() {
        profile.tags = parsedValues(tagsText)
    }

    private func parsedValues(_ text: String) -> [String] {
        text.split(separator: ",", omittingEmptySubsequences: true)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func profileDispositionBinding(for task: RepositoryDataTask) -> Binding<RepositoryTaskDisposition> {
        Binding(
            get: { profile.taskSetting(for: task)?.disposition ?? .selected },
            set: { disposition in
                var settings = profile.taskSettings
                if let index = settings.firstIndex(where: { $0.task == task }) {
                    settings[index].disposition = disposition
                    settings[index].reason = nil
                } else {
                    settings.append(RecordingTaskSetting(task: task, disposition: disposition))
                }
                profile.taskSettings = settings
            }
        )
    }

    private func profileReasonBinding(for task: RepositoryDataTask) -> Binding<String> {
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

    @ViewBuilder
    private func validationMessages(for issues: [RecordingProfileValidationIssue]) -> some View {
        if !issues.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(issues.enumerated()), id: \.offset) { _, issue in
                    Text("\(issue.field.rawValue): \(issue.message)")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
        }
    }

    private func formattedDuration(_ seconds: Double) -> String {
        let totalSeconds = max(0, Int(seconds.rounded(.down)))
        return String(format: "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }

    private func formattedBytes(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
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

private extension String {
    var nilIfBlank: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
