import CoreMedia
import Foundation

/// Owns the live recording lifecycle and the durable training-recording queue.
@MainActor
final class RecordingWorkflow {
    struct State {
        let workspaceState: RecordingWorkspaceState
        let trainingState: TrainingRecordingWorkflowState
        let metrics: TrainingRecordingMetrics
        let queueDiagnostics: TrainingRecordingQueueDiagnostics?
        let error: String?
        let uploadError: String?
        let uploadRunning: Bool
        let uploadProgress: TrainingRecordingUploadProgress?
        let latestRecordingID: String?
        let startedAt: Date?
        let elapsedSeconds: Double
        let estimatedSizeBytes: Int64
        let activeProfile: RecordingProfile?
        let roundRecordingState: RoundRecordingState?
        let captureSessionID: UUID?
    }

    private(set) var recordingWorkspaceState: RecordingWorkspaceState = .idle
    private(set) var trainingRecordingState: TrainingRecordingWorkflowState = .idle
    private(set) var trainingRecordingMetrics = TrainingRecordingMetrics()
    private(set) var trainingRecordingQueueDiagnostics: TrainingRecordingQueueDiagnostics?
    private(set) var trainingRecordingError: String?
    private(set) var trainingRecordingUploadError: String?
    private(set) var trainingRecordingUploadRunning = false
    private(set) var trainingRecordingUploadProgress: TrainingRecordingUploadProgress?
    private(set) var latestTrainingRecordingID: String?
    private(set) var trainingRecordingStartedAt: Date?
    private(set) var trainingRecordingElapsedSeconds = 0.0
    private(set) var trainingRecordingEstimatedSizeBytes: Int64 = 0
    private(set) var activeRecordingProfile: RecordingProfile?
    private(set) var roundRecordingState: RoundRecordingState?
    private(set) var captureSessionID: UUID?

    private(set) var trainingRecordingCoordinator: TrainingRecordingCoordinator?
    private(set) var evidencePackageCoordinator: EvidencePackageCoordinator?

    private let appRunContext: AppRunContext
    private let trainingRecordingMaximumDurationSeconds: Double
    private let trainingRecordingMaximumSizeBytes: Int64
    private let captureSessionIdentityStore: CaptureSessionIdentityStore
    private let trainingRecordingStore: TrainingRecordingStore
    private let trainingRecordingUploadQueue: TrainingRecordingUploadQueue?
    private let roundRecordingStateStore: RoundRecordingStateStore
    private let recordingStartSnapshotStore: RecordingStartSnapshotStore
    private let makeEvidencePackageCoordinator: (
        CaptureSession,
        EvidenceFrameRing,
        (any EvidenceVideoSnippetProviding)?,
        String?
    ) -> EvidencePackageCoordinator
    private let onStateChange: (State) -> Void
    private let onCaptureSessionStarted: (CaptureSession) -> Void
    private let onCaptureSessionMarkerEnded: () -> Void
    private let onTrainingRecordingAcknowledged: (String) -> Void
    private let onRecordingFinalized: () -> Void
    private let attachTrainingRecording: (TrainingRecordingCoordinator?) -> Void
    private var recordingWorkspaceLifecycle = RecordingWorkspaceLifecycle()
    private var activeRecordingSnapshot: RecordingStartSnapshot?
    private var captureSessionIsPersisted = false
    private var trainingRecordingUploadTask: Task<Void, Never>?
    private var lastTrainingRecordingUploadProgressUpdateAt: Date?

    init(
        appRunContext: AppRunContext,
        maximumDurationSeconds: Double,
        maximumSizeBytes: Int64,
        captureSessionIdentityStore: CaptureSessionIdentityStore,
        trainingRecordingStore: TrainingRecordingStore,
        trainingRecordingUploadQueue: TrainingRecordingUploadQueue?,
        roundRecordingStateStore: RoundRecordingStateStore,
        recordingStartSnapshotStore: RecordingStartSnapshotStore,
        makeEvidencePackageCoordinator: @escaping (
            CaptureSession,
            EvidenceFrameRing,
            (any EvidenceVideoSnippetProviding)?,
            String?
        ) -> EvidencePackageCoordinator,
        onStateChange: @escaping (State) -> Void,
        onCaptureSessionStarted: @escaping (CaptureSession) -> Void,
        onCaptureSessionMarkerEnded: @escaping () -> Void,
        onTrainingRecordingAcknowledged: @escaping (String) -> Void,
        onRecordingFinalized: @escaping () -> Void,
        attachTrainingRecording: @escaping (TrainingRecordingCoordinator?) -> Void
    ) {
        self.appRunContext = appRunContext
        self.trainingRecordingMaximumDurationSeconds = maximumDurationSeconds
        self.trainingRecordingMaximumSizeBytes = maximumSizeBytes
        self.captureSessionIdentityStore = captureSessionIdentityStore
        self.trainingRecordingStore = trainingRecordingStore
        self.trainingRecordingUploadQueue = trainingRecordingUploadQueue
        self.roundRecordingStateStore = roundRecordingStateStore
        self.recordingStartSnapshotStore = recordingStartSnapshotStore
        self.makeEvidencePackageCoordinator = makeEvidencePackageCoordinator
        self.onStateChange = onStateChange
        self.onCaptureSessionStarted = onCaptureSessionStarted
        self.onCaptureSessionMarkerEnded = onCaptureSessionMarkerEnded
        self.onTrainingRecordingAcknowledged = onTrainingRecordingAcknowledged
        self.onRecordingFinalized = onRecordingFinalized
        self.attachTrainingRecording = attachTrainingRecording
    }

    var state: State {
        State(
            workspaceState: recordingWorkspaceState,
            trainingState: trainingRecordingState,
            metrics: trainingRecordingMetrics,
            queueDiagnostics: trainingRecordingQueueDiagnostics,
            error: trainingRecordingError,
            uploadError: trainingRecordingUploadError,
            uploadRunning: trainingRecordingUploadRunning,
            uploadProgress: trainingRecordingUploadProgress,
            latestRecordingID: latestTrainingRecordingID,
            startedAt: trainingRecordingStartedAt,
            elapsedSeconds: trainingRecordingElapsedSeconds,
            estimatedSizeBytes: trainingRecordingEstimatedSizeBytes,
            activeProfile: activeRecordingProfile,
            roundRecordingState: roundRecordingState,
            captureSessionID: captureSessionID
        )
    }

    var queueReady: Bool {
        guard trainingRecordingCoordinator == nil else { return false }
        switch trainingRecordingState {
        case .idle, .acknowledged, .failed:
            return true
        case .recording, .finalizing, .queued, .uploading:
            return false
        }
    }

    func recover() {
        recoverRoundRecordingState()
        recoverRecordingStartSnapshot()
        recoverTrainingRecordings()
        publish()
    }

    @discardableResult
    func startPreview() -> Bool {
        guard recordingWorkspaceLifecycle.startPreview() else { return false }
        publish()
        return true
    }

    @discardableResult
    func markPreviewReady() -> Bool {
        guard recordingWorkspaceLifecycle.markPreviewReady() else { return false }
        publish()
        return true
    }

    @discardableResult
    func stopPreview() -> Bool {
        guard recordingWorkspaceLifecycle.stopPreview() else { return false }
        publish()
        return true
    }

    @discardableResult
    func fail(_ message: String) -> Bool {
        guard recordingWorkspaceLifecycle.fail(message) else { return false }
        publish()
        return true
    }

    @discardableResult
    func startRecording(
        profile: RecordingProfile,
        operatorSettings: OperatorSettings,
        hasEnoughFreeDiskSpace: Bool,
        evidenceSampler: EvidenceFrameSampler?,
        liveVideoCapture: LiveEvidenceVideoSnippetProvider?,
        model: TrainingRecordingModel,
        decoder: TrainingRecordingDecoder,
        client: TrainingRecordingClient,
        resetRoundAnalysis: () throws -> Void
    ) -> Bool {
        guard profile.isComplete else {
            trainingRecordingError = profile.validationIssues
                .map { "\($0.field.rawValue): \($0.message)" }
                .joined(separator: " ")
            publish()
            return false
        }
        guard operatorSettings.isComplete else {
            trainingRecordingError = "Enter the operator name in settings before recording."
            publish()
            return false
        }
        guard recordingWorkspaceState.acceptsRecordingStart else {
            trainingRecordingError = "Start the recording workspace preview with a ready backend before recording."
            publish()
            return false
        }
        guard hasEnoughFreeDiskSpace else {
            trainingRecordingError = "There is not enough free space for a training recording."
            publish()
            return false
        }

        let recordingID = UUID().uuidString.lowercased()
        let startedAt = Date()
        let snapshot: RecordingStartSnapshot
        do {
            snapshot = try RecordingStartSnapshot(
                recordingID: recordingID,
                startedAtUTC: Self.utcTimestamp(startedAt),
                profile: profile,
                operatorSettings: operatorSettings,
                appRunContext: appRunContext
            )
            try recordingStartSnapshotStore.save(snapshot)
        } catch {
            trainingRecordingError = "The recording start snapshot could not be saved: \(error.localizedDescription)"
            publish()
            return false
        }

        let roundSetup: RoundRecordingSetup
        do {
            roundSetup = try snapshot.makeRoundSetup()
        } catch {
            try? recordingStartSnapshotStore.remove()
            trainingRecordingError = error.localizedDescription
            publish()
            return false
        }
        guard let evidenceSampler else {
            try? recordingStartSnapshotStore.remove()
            trainingRecordingError = "Evidence capture is not ready."
            publish()
            return false
        }
        evidenceSampler.reset()
        liveVideoCapture?.reset()

        let recordingCaptureSession: CaptureSession
        do {
            recordingCaptureSession = try captureSessionIdentityStore.startSession(
                sessionID: appRunContext.sessionID,
                startedAtUTC: startedAt,
                clock: evidenceSampler.sessionClock
            )
        } catch {
            try? recordingStartSnapshotStore.remove()
            trainingRecordingError = "The recording session could not be started: \(error.localizedDescription)"
            publish()
            return false
        }

        let savedRoundRecordingState: RoundRecordingState
        do {
            savedRoundRecordingState = try RoundRecordingState(
                recordingID: recordingID,
                sessionID: appRunContext.sessionID,
                roundSetup: roundSetup,
                startedAtUTC: startedAt
            )
            try roundRecordingStateStore.save(savedRoundRecordingState)
        } catch {
            try? recordingStartSnapshotStore.remove()
            try? captureSessionIdentityStore.endSession(sessionID: appRunContext.sessionID)
            trainingRecordingError = "The round recording state could not be saved: \(error.localizedDescription)"
            publish()
            return false
        }
        do {
            try resetRoundAnalysis()
        } catch {
            try? roundRecordingStateStore.remove()
            try? recordingStartSnapshotStore.remove()
            try? captureSessionIdentityStore.endSession(sessionID: appRunContext.sessionID)
            trainingRecordingError = "The previous round analysis state could not be cleared: \(error.localizedDescription)"
            publish()
            return false
        }

        let configuration = TrainingRecordingConfiguration(
            outputRoot: trainingRecordingStore.directoryURL(for: .queued),
            recordingID: recordingID,
            sessionID: appRunContext.sessionIDString,
            videoID: "video-\(recordingID)",
            startedAtUTC: startedAt,
            model: model,
            decoder: decoder,
            client: client,
            sourcePermission: snapshot.collectionMetadata.sourcePermission,
            collectionMetadata: snapshot.collectionMetadata,
            taskEnrollments: snapshot.taskEnrollments,
            frameRate: 30.0,
            maximumDurationSeconds: trainingRecordingMaximumDurationSeconds,
            maximumSizeBytes: trainingRecordingMaximumSizeBytes
        )
        let coordinator = TrainingRecordingCoordinator(configuration: configuration)
        do {
            try coordinator.start()
        } catch {
            try? roundRecordingStateStore.remove()
            try? recordingStartSnapshotStore.remove()
            try? captureSessionIdentityStore.endSession(sessionID: appRunContext.sessionID)
            trainingRecordingError = error.localizedDescription
            publish()
            return false
        }

        captureSessionID = appRunContext.sessionID
        captureSessionIsPersisted = true
        onCaptureSessionStarted(recordingCaptureSession)
        evidencePackageCoordinator = makeEvidencePackageCoordinator(
            recordingCaptureSession,
            evidenceSampler.ring,
            liveVideoCapture,
            recordingID
        )
        trainingRecordingCoordinator = coordinator
        roundRecordingState = savedRoundRecordingState
        activeRecordingProfile = profile
        activeRecordingSnapshot = snapshot
        attachTrainingRecording(coordinator)
        latestTrainingRecordingID = recordingID
        trainingRecordingStartedAt = startedAt
        trainingRecordingElapsedSeconds = 0.0
        trainingRecordingEstimatedSizeBytes = 0
        trainingRecordingMetrics = coordinator.metrics
        trainingRecordingError = nil
        trainingRecordingUploadError = nil
        trainingRecordingUploadProgress = nil
        lastTrainingRecordingUploadProgressUpdateAt = nil
        guard recordingWorkspaceLifecycle.startRecording(recordingID: recordingID) else {
            coordinator.stop()
            trainingRecordingCoordinator = nil
            try? roundRecordingStateStore.remove()
            try? recordingStartSnapshotStore.remove()
            try? captureSessionIdentityStore.endSession(sessionID: appRunContext.sessionID)
            trainingRecordingError = "The recording workspace is not ready to start recording."
            publish()
            return false
        }
        trainingRecordingState = .recording
        publish()
        return true
    }

    func stopRecording() {
        guard trainingRecordingState == .recording else { return }
        guard recordingWorkspaceLifecycle.stopRecording() else { return }
        publish()
        guard let coordinator = trainingRecordingCoordinator else {
            failRecording("The training recording coordinator is not available.")
            return
        }
        guard let recordingID = latestTrainingRecordingID else {
            failRecording("The round recording ID is not available.")
            return
        }
        guard let activeRecordingSnapshot else {
            failRecording("The recording start snapshot is not available.")
            return
        }
        do {
            _ = try roundRecordingStateStore.closeEvidenceMembership(recordingID: recordingID)
            roundRecordingState = try roundRecordingStateStore.load()
        } catch {
            failRecording("The round recording state could not be closed: \(error.localizedDescription)")
            return
        }
        attachTrainingRecording(nil)
        evidencePackageCoordinator?.closeRecordingMembership()
        finishEvidencePackageCoordinator()
        finishPersistedCaptureSessionMarker()
        trainingRecordingState = .finalizing
        trainingRecordingMetrics = coordinator.metrics
        publish()
        let collectionMetadata = activeRecordingSnapshot.collectionMetadata
        let taskEnrollments = activeRecordingSnapshot.taskEnrollments
        coordinator.stop(
            completion: { [weak self, weak coordinator] result in
                Task { @MainActor in
                    guard let self else { return }
                    self.trainingRecordingMetrics = coordinator?.metrics ?? self.trainingRecordingMetrics
                    self.trainingRecordingStartedAt = nil
                    self.trainingRecordingElapsedSeconds = 0.0
                    self.trainingRecordingEstimatedSizeBytes = coordinator?.estimatedStoredSizeBytes ?? self.trainingRecordingEstimatedSizeBytes
                    self.trainingRecordingCoordinator = nil
                    self.activeRecordingProfile = nil
                    switch result {
                    case .success:
                        try? self.recordingStartSnapshotStore.remove()
                        self.activeRecordingSnapshot = nil
                        self.roundRecordingState = try? self.roundRecordingStateStore.markRecordingBundleFinalized(
                            recordingID: recordingID
                        )
                        self.trainingRecordingError = nil
                        self.trainingRecordingQueueDiagnostics = self.trainingRecordingStore.diagnostics
                        self.trainingRecordingState = .queued
                        _ = self.recordingWorkspaceLifecycle.finishRecording()
                        self.onRecordingFinalized()
                    case let .failure(error):
                        self.trainingRecordingError = error.localizedDescription
                        self.trainingRecordingState = .failed(error.localizedDescription)
                        _ = self.recordingWorkspaceLifecycle.fail(error.localizedDescription)
                        self.trainingRecordingQueueDiagnostics = self.trainingRecordingStore.diagnostics
                    }
                    self.publish()
                }
            },
            collectionMetadata: collectionMetadata,
            taskEnrollments: taskEnrollments
        )
    }

    func updateClock(now: Date = Date()) {
        guard trainingRecordingState == .recording,
              let startedAt = trainingRecordingStartedAt else { return }
        trainingRecordingElapsedSeconds = max(0.0, now.timeIntervalSince(startedAt))
        if let coordinator = trainingRecordingCoordinator {
            trainingRecordingMetrics = coordinator.metrics
            trainingRecordingEstimatedSizeBytes = coordinator.estimatedStoredSizeBytes
        }
        if trainingRecordingElapsedSeconds >= trainingRecordingMaximumDurationSeconds
            || trainingRecordingEstimatedSizeBytes >= trainingRecordingMaximumSizeBytes {
            trainingRecordingError = trainingRecordingElapsedSeconds >= trainingRecordingMaximumDurationSeconds
                ? "The maximum training recording duration was reached."
                : "The maximum training recording size was reached."
            stopRecording()
        } else {
            publish()
        }
    }

    func uploadQueuedTrainingRecordings(using configuration: BackendConfiguration?) {
        guard let configuration else {
            trainingRecordingUploadError = "Connect to a backend before uploading training recordings."
            publish()
            return
        }
        guard let trainingRecordingUploadQueue else {
            trainingRecordingUploadError = "The training recording upload queue is not available."
            publish()
            return
        }
        guard trainingRecordingUploadTask == nil else { return }
        if trainingRecordingState == .queued { trainingRecordingState = .uploading }
        trainingRecordingUploadRunning = true
        trainingRecordingUploadError = nil
        let progressHandler: TrainingRecordingUploadProgressHandler = { [weak self] progress in
            Task { @MainActor [weak self] in
                self?.applyUploadProgress(progress)
            }
        }
        trainingRecordingUploadTask = Task { [weak self] in
            let attempts = await trainingRecordingUploadQueue.uploadQueued(
                using: configuration,
                progress: progressHandler
            )
            await MainActor.run {
                guard let self else { return }
                self.trainingRecordingUploadTask = nil
                self.trainingRecordingUploadRunning = false
                guard !Task.isCancelled else { return }
                self.applyUploadAttempts(attempts)
                if self.trainingRecordingQueueDiagnostics?.queuedCount ?? 0 > 0 {
                    self.uploadQueuedTrainingRecordings(using: configuration)
                }
            }
        }
        publish()
    }

    func retryFailedTrainingRecordings(using configuration: BackendConfiguration?) {
        guard let configuration else {
            trainingRecordingUploadError = "Connect to a backend before retrying training recording uploads."
            publish()
            return
        }
        guard let trainingRecordingUploadQueue else {
            trainingRecordingUploadError = "The training recording upload queue is not available."
            publish()
            return
        }
        guard trainingRecordingUploadTask == nil else { return }
        trainingRecordingState = .uploading
        trainingRecordingUploadRunning = true
        trainingRecordingUploadError = nil
        trainingRecordingUploadProgress = nil
        lastTrainingRecordingUploadProgressUpdateAt = nil
        let progressHandler: TrainingRecordingUploadProgressHandler = { [weak self] progress in
            Task { @MainActor [weak self] in
                self?.applyUploadProgress(progress)
            }
        }
        trainingRecordingUploadTask = Task { [weak self] in
            let attempts = await trainingRecordingUploadQueue.retryFailed(
                using: configuration,
                progress: progressHandler
            )
            await MainActor.run {
                guard let self else { return }
                self.trainingRecordingUploadTask = nil
                self.trainingRecordingUploadRunning = false
                guard !Task.isCancelled else { return }
                self.applyUploadAttempts(attempts)
            }
        }
        publish()
    }

    func finishEvidencePackageCoordinator() {
        guard let evidencePackageCoordinator else { return }
        evidencePackageCoordinator.finish()
        evidencePackageCoordinator.drain()
        self.evidencePackageCoordinator = nil
    }

    func setEvidencePackageCoordinator(_ coordinator: EvidencePackageCoordinator?) {
        evidencePackageCoordinator = coordinator
    }

    func observeEvidence(_ frame: VideoFrame) {
        evidencePackageCoordinator?.observe(frame)
    }

    func consumeEvidence(_ prediction: ModelPrediction, event: DetectionEvent?) {
        evidencePackageCoordinator?.consume(prediction, event: event)
    }

    func recordEvidence(_ event: DetectionEvent) {
        evidencePackageCoordinator?.record(event)
    }

    private func applyUploadAttempts(_ attempts: [TrainingRecordingUploadAttempt]) {
        trainingRecordingQueueDiagnostics = trainingRecordingStore.diagnostics
        trainingRecordingUploadError = attempts.compactMap { $0.failure?.message }.first
            ?? trainingRecordingQueueDiagnostics?.errors.first
        guard let recordingID = latestTrainingRecordingID,
              let attempt = attempts.last(where: { $0.recordingID == recordingID }) else {
            if trainingRecordingState == .uploading,
               let recordingID = latestTrainingRecordingID,
               let failure = trainingRecordingStore.failure(for: recordingID) {
                trainingRecordingState = .failed(failure.message)
                trainingRecordingError = failure.message
            } else if trainingRecordingState == .uploading {
                trainingRecordingState = trainingRecordingQueueDiagnostics?.queuedCount ?? 0 > 0
                    ? .queued
                    : .idle
            }
            publish()
            return
        }
        switch attempt.disposition {
        case .acknowledged:
            if let progress = trainingRecordingUploadProgress,
               progress.recordingID == recordingID,
               progress.phase == .uploading,
               progress.fraction < 1.0 {
                trainingRecordingUploadProgress = TrainingRecordingUploadProgress(
                    recordingID: recordingID,
                    phase: .uploading,
                    bytesSent: progress.expectedBytes,
                    expectedBytes: progress.expectedBytes
                )
            }
            trainingRecordingState = .acknowledged
            trainingRecordingError = nil
            onTrainingRecordingAcknowledged(recordingID)
        case .retryableFailure, .permanentFailure:
            let message = attempt.failure?.message ?? "The training recording upload failed."
            trainingRecordingState = .failed(message)
            trainingRecordingError = message
        }
        publish()
    }

    private func applyUploadProgress(_ progress: TrainingRecordingUploadProgress) {
        latestTrainingRecordingID = progress.recordingID
        if trainingRecordingState != .recording && trainingRecordingState != .finalizing {
            trainingRecordingState = .uploading
        }
        let now = Date()
        let isBoundary = progress.phase == .preparing
            || progress.fraction == 0.0
            || progress.fraction >= 1.0
        if !isBoundary,
           let lastUpdate = lastTrainingRecordingUploadProgressUpdateAt,
           now.timeIntervalSince(lastUpdate) < 0.1 {
            return
        }
        trainingRecordingUploadProgress = progress
        lastTrainingRecordingUploadProgressUpdateAt = now
        publish()
    }

    private func recoverRoundRecordingState() {
        do {
            roundRecordingState = try roundRecordingStateStore.load()
        } catch {
            trainingRecordingError = error.localizedDescription
        }
    }

    private func recoverRecordingStartSnapshot() {
        do {
            guard let snapshot = try recordingStartSnapshotStore.load() else { return }
            guard let roundRecordingState,
                  roundRecordingState.recordingID == snapshot.recordingID,
                  roundRecordingState.sessionID == snapshot.appRunContext.sessionID else {
                try recordingStartSnapshotStore.remove()
                return
            }
            activeRecordingSnapshot = snapshot
            activeRecordingProfile = snapshot.profile
            _ = recordingWorkspaceLifecycle.recoverInterruptedRecording(recordingID: snapshot.recordingID)
            recordingWorkspaceState = recordingWorkspaceLifecycle.state
        } catch {
            trainingRecordingError = error.localizedDescription
        }
    }

    private func recoverTrainingRecordings() {
        do {
            trainingRecordingQueueDiagnostics = try trainingRecordingStore.recover()
            trainingRecordingError = trainingRecordingQueueDiagnostics?.errors.first
            if trainingRecordingQueueDiagnostics?.queuedCount ?? 0 > 0 {
                trainingRecordingState = .queued
                latestTrainingRecordingID = trainingRecordingQueueDiagnostics?.recoveredRecordingIDs.last
                if let recordingID = latestTrainingRecordingID {
                    _ = recordingWorkspaceLifecycle.recoverPostRecording(recordingID: recordingID)
                    recordingWorkspaceState = recordingWorkspaceLifecycle.state
                }
            } else if trainingRecordingQueueDiagnostics?.failedCount ?? 0 > 0 {
                let failedURLs = try? trainingRecordingStore.recordingURLs(in: .failed)
                if let failedURL = failedURLs?.last {
                    latestTrainingRecordingID = failedURL.lastPathComponent
                    let message = trainingRecordingStore.failure(for: failedURL.lastPathComponent)?.message
                        ?? "A training recording upload failed."
                    trainingRecordingState = .failed(message)
                    trainingRecordingError = message
                    _ = recordingWorkspaceLifecycle.fail(message)
                    recordingWorkspaceState = recordingWorkspaceLifecycle.state
                }
            }
        } catch {
            trainingRecordingError = error.localizedDescription
        }
    }

    private func failRecording(_ message: String) {
        trainingRecordingState = .failed(message)
        trainingRecordingError = message
        _ = recordingWorkspaceLifecycle.fail(message)
        publish()
    }

    private func finishPersistedCaptureSessionMarker() {
        guard captureSessionIsPersisted else { return }
        do {
            try captureSessionIdentityStore.endSession(sessionID: appRunContext.sessionID)
            captureSessionIsPersisted = false
            onCaptureSessionMarkerEnded()
        } catch {
            trainingRecordingError = "The recording session could not be closed: \(error.localizedDescription)"
        }
    }

    private func publish() {
        recordingWorkspaceState = recordingWorkspaceLifecycle.state
        onStateChange(state)
    }

    private static func utcTimestamp(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }
}
