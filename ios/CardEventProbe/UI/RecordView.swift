import SwiftUI

struct RecordView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var camera = CameraSession()
    @State private var profile: CollectionProfile
    @State private var selectedProfileID: String?
    @State private var lightingText = ""
    @State private var scenarioTagsText = ""
    @State private var limitationsText = ""
    @State private var recordingNotes = ""
    @State private var cardEventOverride: RepositoryTaskDisposition?
    @State private var tableEvidenceOverride: RepositoryTaskDisposition?
    @State private var overrideReason = ""
    @State private var dealer = RoundRecordingSetup.fixedSeatIDs[0]
    @State private var firstTrickLeader = RoundRecordingSetup.fixedSeatIDs[0]

    init() {
        _profile = State(initialValue: CollectionProfile.newDraft())
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
            appState.startRoundAnalysisPolling()
            if appState.captureActivity == .idle {
                startCapture()
            }
        }
        .onDisappear {
            if appState.trainingRecordingState == .recording {
                appState.stopTrainingRecording(
                    scenarioTags: parsedValues(scenarioTagsText),
                    notes: recordingNotes.nilIfBlank
                )
            }
            endCapture()
            appState.stopRoundAnalysisPolling()
        }
        .onChange(of: selectedProfileID) { _, newValue in
            guard let newValue else {
                profile = appState.newCollectionProfileDraft()
                syncTextFields()
                resetOverrides()
                appState.selectCollectionProfile(nil)
                return
            }
            guard let selected = appState.collectionProfiles.first(where: { $0.profileID == newValue }) else {
                return
            }
            profile = selected
            syncTextFields()
            resetOverrides()
            appState.selectCollectionProfile(newValue)
        }
        .onChange(of: lightingText) { _, newValue in
            profile.lighting = parsedValues(newValue)
        }
        .onChange(of: scenarioTagsText) { _, newValue in
            profile.scenarioTags = parsedValues(newValue)
        }
        .onChange(of: limitationsText) { _, newValue in
            profile.knownLimitations = parsedValues(newValue)
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
                Text("Collection profile")
                    .font(.headline)
                Spacer()
                Button("New") {
                    selectedProfileID = nil
                    profile = appState.newCollectionProfileDraft()
                    syncTextFields()
                }
                .buttonStyle(.bordered)
            }

            Picker("Saved profile", selection: $selectedProfileID) {
                Text("New profile").tag(nil as String?)
                ForEach(appState.collectionProfiles) { savedProfile in
                    Text(savedProfile.name).tag(savedProfile.profileID as String?)
                }
            }

            TextField("Profile name", text: $profile.name)
            TextField("Operator", text: $profile.operatorName)
            TextField("Session ID", text: $profile.sessionID)
            Picker("Activity", selection: $profile.activity) {
                ForEach(CollectionActivity.allCases, id: \.self) { activity in
                    Text(activity.title).tag(activity)
                }
            }
            if profile.activity == .realGame {
                TextField("Game ID", text: Binding(
                    get: { profile.gameID ?? "" },
                    set: { profile.gameID = $0.nilIfBlank }
                ))
            }
            TextField("Table setup", text: $profile.tableSetup)
            TextField("Deck design", text: $profile.cardDeck)
            Picker("Camera view", selection: $profile.cameraView) {
                option("Choose a view", value: "")
                option("Overhead", value: "overhead")
                option("High oblique", value: "high_oblique")
                option("Low oblique", value: "low_oblique")
                option("Side oblique", value: "side_oblique")
                option("Other", value: "other")
            }
            Picker("Camera motion", selection: $profile.cameraMotion) {
                option("Choose movement", value: "")
                option("Fixed", value: "fixed")
                option("Handheld static", value: "handheld_static")
                option("Handheld moving", value: "handheld_moving")
                option("Other", value: "other")
            }
            Picker("Camera framing", selection: $profile.cameraFraming) {
                option("Choose framing", value: "")
                option("Table fills frame", value: "table_fills_frame")
                option("Table with context", value: "table_with_context")
                option("Wide context", value: "wide_context")
                option("Other", value: "other")
            }
            TextField("Lighting conditions, comma separated", text: $lightingText)
            TextField("Background", text: $profile.background)
            TextField("Scenario tags, comma separated", text: $scenarioTagsText)
            TextField("Known limitations, comma separated", text: $limitationsText)
            Picker("Source permission", selection: $profile.sourcePermission) {
                option("Choose permission", value: "")
                option("Training only", value: "training_only")
                option("Training and evaluation", value: "training_and_evaluation")
                option("Project use", value: "project_use")
                option("Unrestricted", value: "unrestricted")
            }
            TextField("Profile notes", text: Binding(
                get: { profile.notes ?? "" },
                set: { profile.notes = $0.nilIfBlank }
            ), axis: .vertical)
            .lineLimit(2...5)

            Button("Save profile") {
                applyTextFields()
                appState.saveCollectionProfile(profile)
                selectedProfileID = profile.profileID
            }
            .buttonStyle(.borderedProminent)

            validationMessages(for: profile.roundRecordingValidationIssues)
            if let error = appState.collectionProfileError {
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
            Text("Profile dispositions are reused for this session. Set an override only for this recording.")
                .font(.caption)
                .foregroundStyle(.secondary)

            ForEach(RepositoryDataTask.allCases, id: \.self) { task in
                VStack(alignment: .leading, spacing: 6) {
                    Text(task.rawValue)
                        .font(.subheadline.weight(.medium))
                    Picker("Profile disposition", selection: profileDispositionBinding(for: task)) {
                        ForEach(RepositoryTaskDisposition.allCases, id: \.self) { disposition in
                            Text(disposition.rawValue.capitalized).tag(disposition)
                        }
                    }
                    if profile.taskSetting(for: task)?.disposition == .excluded {
                        TextField("Profile exclusion reason", text: profileReasonBinding(for: task))
                    }
                    Picker("Recording override", selection: overrideBinding(for: task)) {
                        Text("Use profile default").tag(nil as RepositoryTaskDisposition?)
                        ForEach(RepositoryTaskDisposition.allCases, id: \.self) { disposition in
                            Text(disposition.rawValue.capitalized).tag(disposition as RepositoryTaskDisposition?)
                        }
                    }
                }
            }

            if cardEventOverride == .excluded || tableEvidenceOverride == .excluded {
                TextField("Override exclusion reason", text: $overrideReason)
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

            Text("Round setup")
                .font(.headline)
            Picker("Dealer", selection: $dealer) {
                ForEach(RoundRecordingSetup.fixedSeatIDs, id: \.self) { seatID in
                    Text(seatID).tag(seatID)
                }
            }
            .disabled(appState.isRoundRecordingLocked)
            Picker("First trick leader", selection: $firstTrickLeader) {
                ForEach(RoundRecordingSetup.fixedSeatIDs, id: \.self) { seatID in
                    Text(seatID).tag(seatID)
                }
            }
            .disabled(appState.isRoundRecordingLocked)

            TextField("Recording notes", text: $recordingNotes, axis: .vertical)
                .lineLimit(2...5)

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
                applyTextFields()
                if appState.trainingRecordingState == .recording {
                    appState.stopTrainingRecording(
                        scenarioTags: profile.scenarioTags,
                        notes: recordingNotes.nilIfBlank
                    )
                } else {
                    appState.startTrainingRecording(
                        profile: profile,
                        dealer: dealer,
                        firstTrickLeader: firstTrickLeader,
                        overrides: recordingOverrides()
                    )
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(appState.trainingRecordingState == .recording ? .red : .accentColor)
            .disabled(
                appState.trainingRecordingState == .recording
                    ? false
                    : !appState.canStartTrainingRecording || !profile.isCompleteRoundRecordingProfile
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
                if let detail = appState.roundAnalysisState.detail {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(
                            appState.roundAnalysisState.title == "Failed" ? .red : .secondary
                        )
                }
            }
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
        selectedProfileID = appState.selectedCollectionProfileID
        if let selectedProfileID,
           let selected = appState.collectionProfiles.first(where: { $0.profileID == selectedProfileID }) {
            profile = selected
        }
        syncTextFields()
    }

    private func syncTextFields() {
        lightingText = profile.lighting.joined(separator: ", ")
        scenarioTagsText = profile.scenarioTags.joined(separator: ", ")
        limitationsText = profile.knownLimitations.joined(separator: ", ")
        recordingNotes = profile.notes ?? ""
    }

    private func resetOverrides() {
        cardEventOverride = nil
        tableEvidenceOverride = nil
        overrideReason = ""
    }

    private func applyTextFields() {
        profile.lighting = parsedValues(lightingText)
        profile.scenarioTags = parsedValues(scenarioTagsText)
        profile.knownLimitations = parsedValues(limitationsText)
    }

    private func parsedValues(_ text: String) -> [String] {
        text.split(separator: ",", omittingEmptySubsequences: true)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func recordingOverrides() -> [CollectionTaskDispositionOverride] {
        [
            cardEventOverride.map {
                CollectionTaskDispositionOverride(
                    task: .cardEventDetection,
                    disposition: $0,
                    reason: $0 == .excluded ? overrideReason.nilIfBlank : nil
                )
            },
            tableEvidenceOverride.map {
                CollectionTaskDispositionOverride(
                    task: .tableEvidenceAnalysis,
                    disposition: $0,
                    reason: $0 == .excluded ? overrideReason.nilIfBlank : nil
                )
            },
        ].compactMap { $0 }
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
                    settings.append(CollectionTaskSetting(task: task, disposition: disposition))
                }
                profile.taskSettings = settings
            }
        )
    }

    private func overrideBinding(for task: RepositoryDataTask) -> Binding<RepositoryTaskDisposition?> {
        Binding(
            get: {
                switch task {
                case .cardEventDetection: return cardEventOverride
                case .tableEvidenceAnalysis: return tableEvidenceOverride
                }
            },
            set: { value in
                switch task {
                case .cardEventDetection: cardEventOverride = value
                case .tableEvidenceAnalysis: tableEvidenceOverride = value
                }
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
    private func option(_ title: String, value: String) -> some View {
        Text(title).tag(value)
    }

    @ViewBuilder
    private func validationMessages(for issues: [CollectionProfileValidationIssue]) -> some View {
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
