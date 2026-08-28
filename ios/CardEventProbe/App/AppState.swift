import CoreML
import CoreMedia
import Foundation
import SwiftUI
import UIKit

enum ModelLoadState {
    case loading
    case ready(ModelContract)
    case failed(String)

    var title: String {
        switch self {
        case .loading: return "Loading"
        case .ready: return "Ready"
        case .failed: return "Error"
        }
    }
}

struct ScoreSample: Identifiable {
    let id = UUID()
    let timestampSeconds: Double
    let probability: Double
}

enum CaptureActivity: Equatable {
    case idle
    case live
    case replay

    var title: String {
        switch self {
        case .idle:
            return "Idle"
        case .live:
            return "Live capture"
        case .replay:
            return "Replay"
        }
    }
}

@MainActor
final class AppState: ObservableObject {
    @Published private(set) var modelState: ModelLoadState = .loading
    @Published private(set) var eventCount = 0
    @Published private(set) var latestPrediction: ModelPrediction?
    @Published private(set) var inferenceMetrics = FrameInferenceMetrics(
        cameraFramesReceived: 0,
        framesSkippedForSampling: 0,
        framesDroppedWhileBusy: 0,
        predictionsProduced: 0,
        averageInferenceDurationMs: nil
    )
    @Published private(set) var inferenceError: String?
    @Published private(set) var scoreHistory: [ScoreSample] = []
    @Published private(set) var lastEventTimestampSeconds: Double?
    @Published private(set) var replayProgress: ReplayProgress?
    @Published private(set) var replayRunning = false
    @Published private(set) var diagnosticsLogURL: URL?
    @Published private(set) var diagnosticsError: String?
    @Published private(set) var diagnosticsRecording = false
    @Published private(set) var evidencePackageCount = 0
    @Published private(set) var evidencePackageError: String?
    @Published private(set) var evidenceQueueDiagnostics: EvidencePackageQueueDiagnostics?
    @Published private(set) var evidenceVideoCaptureStatus = EvidenceVideoCaptureStatus.idle
    @Published private(set) var evidenceVideoCaptureConfigurationError: String?
    @Published private(set) var evidenceUploadError: String?
    @Published private(set) var evidenceUploadRunning = false
    @Published private(set) var latestEvidencePackageID: UUID?
    @Published private(set) var latestTableObservations: [EvidenceTableObservation] = []
    @Published private(set) var tableObservationError: String?
    @Published private(set) var captureActivity: CaptureActivity = .idle
    @Published private(set) var captureSessionID: UUID?
    @Published private(set) var latestEventSequence: Int?
    @Published private(set) var trainingRecordingState: TrainingRecordingWorkflowState = .idle
    @Published private(set) var trainingRecordingMetrics = TrainingRecordingMetrics()
    @Published private(set) var trainingRecordingQueueDiagnostics: TrainingRecordingQueueDiagnostics?
    @Published private(set) var trainingRecordingError: String?
    @Published private(set) var trainingRecordingUploadError: String?
    @Published private(set) var trainingRecordingUploadRunning = false
    @Published private(set) var trainingRecordingUploadProgress: TrainingRecordingUploadProgress?
    @Published private(set) var latestTrainingRecordingID: String?
    @Published private(set) var trainingRecordingStartedAt: Date?
    @Published private(set) var trainingRecordingElapsedSeconds = 0.0
    @Published private(set) var trainingRecordingEstimatedSizeBytes: Int64 = 0
    @Published private(set) var collectionProfiles: [CollectionProfile] = []
    @Published private(set) var selectedCollectionProfileID: String?
    @Published private(set) var collectionProfileError: String?
    @Published private(set) var activeCollectionProfile: CollectionProfile?

    let backendDiscovery = BackendDiscovery()
    private(set) var modelRunner: CardEventModelRunner?
    let eventDecoder = CausalEventDecoder()
    private let evidenceCaptureConfiguration = EvidenceCaptureConfiguration()
    private(set) var evidenceSampler: EvidenceFrameSampler?
    private var evidencePackageCoordinator: EvidencePackageCoordinator?
    private lazy var captureSessionIdentityStore = CaptureSessionIdentityStore(
        directory: evidenceSessionRoot()
    )
    private lazy var evidencePackageStore = EvidencePackageStore(root: evidencePackageRoot())
    private lazy var evidenceUploadQueue: EvidenceUploadQueue? = {
        guard let client = try? EvidenceUploadClient() else { return nil }
        return EvidenceUploadQueue(store: evidencePackageStore, client: client)
    }()
    private lazy var trainingRecordingStore = TrainingRecordingStore(root: trainingRecordingRoot())
    private lazy var trainingRecordingUploadQueue: TrainingRecordingUploadQueue? = {
        guard let client = try? TrainingRecordingUploadClient() else { return nil }
        return TrainingRecordingUploadQueue(store: trainingRecordingStore, client: client)
    }()
    private let tableObservationClient = TableObservationClient()
    private var evidenceUploadTask: Task<Void, Never>?
    private var trainingRecordingUploadTask: Task<Void, Never>?
    private var captureSession: CaptureSession?
    private var liveCoordinator: FrameInferenceCoordinator?
    private var liveVideoCapture: LiveEvidenceVideoSnippetProvider?
    private var trainingRecordingCoordinator: TrainingRecordingCoordinator?
    private var activeTaskEnrollments: [RepositoryTaskEnrollment] = []
    private var replayRunner: VideoReplayRunner?
    private var sessionLog: SessionLog?
    private var activeDiagnosticSource: DiagnosticSource?
    private var latestFrame: VideoFrame?
    private var lastTrainingRecordingUploadProgressUpdateAt: Date?

    private let trainingRecordingMaximumDurationSeconds: Double
    private let trainingRecordingMaximumSizeBytes: Int64
    private let trainingRecordingMinimumFreeBytes: Int64
    private let collectionProfileStore: CollectionProfileStore

    var actualPredictionRateHz: Double? {
        guard let first = scoreHistory.first,
              let last = scoreHistory.last,
              scoreHistory.count > 1 else {
            return nil
        }
        let duration = last.timestampSeconds - first.timestampSeconds
        guard duration > 0.0 else { return nil }
        return Double(scoreHistory.count - 1) / duration
    }

    var thermalStateDescription: String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "Nominal"
        case .fair: return "Fair"
        case .serious: return "Serious"
        case .critical: return "Critical"
        @unknown default: return "Unknown"
        }
    }

    init(
        maximumTrainingRecordingDurationSeconds: Double = 15.0 * 60.0,
        maximumTrainingRecordingSizeBytes: Int64 = 2 * 1024 * 1024 * 1024,
        minimumTrainingRecordingFreeBytes: Int64 = 256 * 1024 * 1024,
        collectionProfileDirectory: URL? = nil
    ) {
        trainingRecordingMaximumDurationSeconds = maximumTrainingRecordingDurationSeconds
        trainingRecordingMaximumSizeBytes = maximumTrainingRecordingSizeBytes
        trainingRecordingMinimumFreeBytes = minimumTrainingRecordingFreeBytes
        collectionProfileStore = CollectionProfileStore(
            directory: collectionProfileDirectory ?? Self.collectionProfileRoot()
        )
        do {
            collectionProfiles = try collectionProfileStore.loadAll()
            selectedCollectionProfileID = collectionProfiles.first?.profileID
        } catch {
            collectionProfileError = error.localizedDescription
        }
        recoverEvidencePackages()
        recoverTrainingRecordings()
        loadModel()
    }

    func startBackendDiscovery() {
        backendDiscovery.start()
    }

    func uploadQueuedEvidence() {
        guard case let .connected(service) = backendDiscovery.state,
              let configuration = try? BackendConfiguration(baseURL: service.baseURL),
              let evidenceUploadQueue else {
            return
        }
        guard evidenceUploadTask == nil else { return }

        evidenceUploadRunning = true
        evidenceUploadTask = Task { [weak self] in
            let attempts = await evidenceUploadQueue.uploadQueued(using: configuration)
            self?.evidenceUploadTask = nil
            self?.evidenceUploadRunning = false
            guard !Task.isCancelled else { return }
            self?.applyEvidenceUploadAttempts(attempts)
            if self?.evidenceQueueDiagnostics?.queuedCount ?? 0 > 0 {
                self?.uploadQueuedEvidence()
            }
        }
    }

    func retryFailedEvidence() {
        guard case let .connected(service) = backendDiscovery.state else {
            evidenceUploadError = "Connect to a backend before retrying evidence uploads."
            return
        }
        guard let configuration = try? BackendConfiguration(baseURL: service.baseURL),
              let evidenceUploadQueue else {
            evidenceUploadError = "The evidence upload queue is not available."
            return
        }
        guard evidenceUploadTask == nil else { return }

        evidenceUploadRunning = true
        evidenceUploadTask = Task { [weak self] in
            let attempts = await evidenceUploadQueue.retryFailed(using: configuration)
            self?.evidenceUploadTask = nil
            self?.evidenceUploadRunning = false
            guard !Task.isCancelled else { return }
            self?.applyEvidenceUploadAttempts(attempts)
            if self?.evidenceQueueDiagnostics?.queuedCount ?? 0 > 0 {
                self?.uploadQueuedEvidence()
            }
        }
    }

    var canStartTrainingRecording: Bool {
        guard captureActivity == .live,
              captureSessionID != nil,
              case .ready = modelState,
              case .connected = backendDiscovery.state else {
            return false
        }
        switch trainingRecordingState {
        case .idle, .acknowledged, .failed:
            return trainingRecordingCoordinator == nil
        case .recording, .finalizing, .queued, .uploading:
            return false
        }
    }

    func uploadQueuedTrainingRecordings() {
        guard case let .connected(service) = backendDiscovery.state,
              let configuration = try? BackendConfiguration(baseURL: service.baseURL),
              let trainingRecordingUploadQueue else {
            return
        }
        guard trainingRecordingUploadTask == nil else { return }

        if trainingRecordingState == .queued {
            trainingRecordingState = .uploading
        }
        trainingRecordingUploadRunning = true
        trainingRecordingUploadError = nil
        let progressHandler: TrainingRecordingUploadProgressHandler = { [weak self] progress in
            Task { @MainActor [weak self] in
                self?.applyTrainingRecordingUploadProgress(progress)
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
                self.applyTrainingRecordingUploadAttempts(attempts)
                if self.trainingRecordingQueueDiagnostics?.queuedCount ?? 0 > 0 {
                    self.uploadQueuedTrainingRecordings()
                }
            }
        }
    }

    func retryFailedTrainingRecordings() {
        guard case let .connected(service) = backendDiscovery.state else {
            trainingRecordingUploadError = "Connect to a backend before retrying training recording uploads."
            return
        }
        guard let configuration = try? BackendConfiguration(baseURL: service.baseURL),
              let trainingRecordingUploadQueue else {
            trainingRecordingUploadError = "The training recording upload queue is not available."
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
                self?.applyTrainingRecordingUploadProgress(progress)
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
                self.applyTrainingRecordingUploadAttempts(attempts)
            }
        }
    }

    var selectedCollectionProfile: CollectionProfile? {
        guard let selectedCollectionProfileID else { return nil }
        return collectionProfiles.first { $0.profileID == selectedCollectionProfileID }
    }

    func newCollectionProfileDraft() -> CollectionProfile {
        CollectionProfile.newDraft()
    }

    func selectCollectionProfile(_ profileID: String?) {
        guard profileID == nil || collectionProfiles.contains(where: { $0.profileID == profileID }) else {
            return
        }
        selectedCollectionProfileID = profileID
        collectionProfileError = nil
    }

    func saveCollectionProfile(_ profile: CollectionProfile) {
        do {
            try collectionProfileStore.save(profile)
            collectionProfiles = try collectionProfileStore.loadAll()
            selectedCollectionProfileID = profile.profileID
            collectionProfileError = nil
        } catch {
            collectionProfileError = error.localizedDescription
        }
    }

    func startTrainingRecording(
        profile: CollectionProfile,
        overrides: [CollectionTaskDispositionOverride] = []
    ) {
        guard profile.isComplete else {
            trainingRecordingError = profile.validationIssues
                .map { "\($0.field.rawValue): \($0.message)" }
                .joined(separator: " ")
            return
        }
        guard canStartTrainingRecording, captureSessionID != nil else {
            trainingRecordingError = "Start a live capture with a ready backend before recording."
            return
        }
        guard hasEnoughFreeDiskSpace() else {
            trainingRecordingError = "There is not enough free space for a training recording."
            return
        }

        let recordingID = UUID().uuidString.lowercased()
        let startedAt = Date()
        let collectionMetadata: TrainingRecordingCollectionMetadata
        let taskEnrollments: [RepositoryTaskEnrollment]
        do {
            collectionMetadata = try profile.recordingMetadata()
            taskEnrollments = try profile.makeTaskEnrollments(
                recordingID: recordingID,
                createdAtUTC: Self.utcTimestamp(startedAt),
                overrides: overrides
            )
        } catch {
            trainingRecordingError = error.localizedDescription
            return
        }
        let model = TrainingRecordingModel(
            name: "CardEventNet",
            version: modelRunner?.contract.metadata["version"] ?? "transition-v2-run-20260825-235429",
            weightsSHA256: modelRunner?.contract.metadata["weights_sha256"]
                ?? "f5eccd8e580d1dccecfa7835b3a0d9d5858cc47fdd0098aa33c3c47f01a38d04",
            preprocessing: "full_frame_letterbox_v1"
        )
        let decoderConfiguration = eventDecoder.configuration
        let decoder = TrainingRecordingDecoder(
            algorithm: "causal_peak_v1",
            threshold: decoderConfiguration.threshold,
            peakConfirmationS: CMTimeGetSeconds(decoderConfiguration.peakConfirmation),
            minimumEventGapS: CMTimeGetSeconds(decoderConfiguration.minimumEventGap)
        )
        let client = TrainingRecordingClient(
            appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
                ?? "unknown",
            build: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
                ?? "unknown",
            deviceModel: UIDevice.current.model,
            osVersion: UIDevice.current.systemVersion
        )
        let configuration = TrainingRecordingConfiguration(
            outputRoot: trainingRecordingStore.directoryURL(for: .queued),
            recordingID: recordingID,
            sessionID: profile.sessionID,
            videoID: "video-\(recordingID)",
            startedAtUTC: startedAt,
            model: model,
            decoder: decoder,
            client: client,
            sourcePermission: profile.sourcePermission,
            collectionMetadata: collectionMetadata,
            taskEnrollments: taskEnrollments,
            frameRate: 30.0,
            maximumDurationSeconds: trainingRecordingMaximumDurationSeconds,
            maximumSizeBytes: trainingRecordingMaximumSizeBytes
        )
        let coordinator = TrainingRecordingCoordinator(configuration: configuration)
        do {
            try coordinator.start()
        } catch {
            trainingRecordingError = error.localizedDescription
            return
        }

        trainingRecordingCoordinator = coordinator
        activeCollectionProfile = profile
        activeTaskEnrollments = taskEnrollments
        liveCoordinator?.attachTrainingRecording(coordinator)
        latestTrainingRecordingID = recordingID
        trainingRecordingStartedAt = Date()
        trainingRecordingElapsedSeconds = 0.0
        trainingRecordingEstimatedSizeBytes = 0
        trainingRecordingMetrics = coordinator.metrics
        trainingRecordingError = nil
        trainingRecordingUploadError = nil
        trainingRecordingUploadProgress = nil
        lastTrainingRecordingUploadProgressUpdateAt = nil
        trainingRecordingState = .recording
        evidencePackageCoordinator?.setRecordingID(recordingID)
    }

    func stopTrainingRecording(scenarioTags: [String]? = nil, notes: String? = nil) {
        guard trainingRecordingState == .recording else { return }
        guard let coordinator = trainingRecordingCoordinator else {
            trainingRecordingState = .failed("The training recording coordinator is not available.")
            trainingRecordingError = "The training recording coordinator is not available."
            return
        }
        guard let activeCollectionProfile else {
            trainingRecordingError = "The active collection profile is not available."
            return
        }
        let collectionMetadata: TrainingRecordingCollectionMetadata
        do {
            collectionMetadata = try activeCollectionProfile.recordingMetadata(
                scenarioTags: scenarioTags,
                notes: notes
            )
        } catch {
            trainingRecordingError = error.localizedDescription
            return
        }
        liveCoordinator?.attachTrainingRecording(nil)
        trainingRecordingState = .finalizing
        trainingRecordingMetrics = coordinator.metrics
        coordinator.stop(
            completion: { [weak self, weak coordinator] result in
            Task { @MainActor in
                guard let self else { return }
                self.trainingRecordingMetrics = coordinator?.metrics ?? self.trainingRecordingMetrics
                self.trainingRecordingStartedAt = nil
                self.trainingRecordingElapsedSeconds = 0.0
                self.trainingRecordingEstimatedSizeBytes = coordinator?.estimatedStoredSizeBytes ?? 0
                self.trainingRecordingCoordinator = nil
                self.activeCollectionProfile = nil
                self.activeTaskEnrollments = []
                switch result {
                case let .success(url):
                    self.trainingRecordingError = nil
                    self.trainingRecordingQueueDiagnostics = self.trainingRecordingStore.diagnostics
                    self.trainingRecordingState = .queued
                    self.uploadQueuedTrainingRecordings()
                    _ = url
                case let .failure(error):
                    self.trainingRecordingError = error.localizedDescription
                    self.trainingRecordingState = .failed(error.localizedDescription)
                    self.trainingRecordingQueueDiagnostics = self.trainingRecordingStore.diagnostics
                }
            }
            },
            collectionMetadata: collectionMetadata,
            taskEnrollments: activeTaskEnrollments
        )
    }

    func updateTrainingRecordingClock(now: Date = Date()) {
        guard trainingRecordingState == .recording,
              let startedAt = trainingRecordingStartedAt else {
            return
        }
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
            stopTrainingRecording()
        }
    }

    func loadTableObservations(for packageID: UUID) {
        guard case let .connected(service) = backendDiscovery.state,
              let configuration = try? BackendConfiguration(baseURL: service.baseURL) else {
            tableObservationError = "Connect to a backend before reading table observations."
            return
        }

        tableObservationError = nil
        Task { [weak self] in
            do {
                let observations = try await tableObservationClient.observations(
                    for: packageID,
                    using: configuration
                )
                guard !Task.isCancelled else { return }
                self?.latestTableObservations = observations
            } catch {
                guard !Task.isCancelled else { return }
                self?.tableObservationError = error.localizedDescription
            }
        }
    }

    func loadModel() {
        stopLiveInference()
        modelState = .loading
        modelRunner = nil

        do {
            let configuration = MLModelConfiguration()
            configuration.computeUnits = .all
            let runner = try CoreMLCardEventModelRunner(configuration: configuration)
            modelRunner = runner
            modelState = .ready(runner.contract)
#if DEBUG
            print("CardEventNetTransitionV2 model contract:\n\(runner.contract.summary)")
#endif
        } catch {
            modelState = .failed(error.localizedDescription)
        }
    }

    func startLiveInference() -> ((VideoFrame) -> Void)? {
        stopReplayForNewSession()
        stopLiveInference()
        resetEvents()
        evidenceVideoCaptureConfigurationError = nil
        guard let runner = modelRunner else { return nil }
        guard let captureSession = beginCaptureSession() else { return nil }
        activeDiagnosticSource = .live
        captureActivity = .live
        beginDiagnosticsSessionIfNeeded(source: .live)

        let evidenceSampler = EvidenceFrameSampler(
            configuration: evidenceCaptureConfiguration,
            sessionClock: captureSession.clock
        )
        self.evidenceSampler = evidenceSampler
        let liveVideoCapture: LiveEvidenceVideoSnippetProvider?
        do {
            liveVideoCapture = try LiveEvidenceVideoSnippetProvider(
                configuration: EvidenceVideoCaptureMetadata.standard,
                minimumCoverageStartOffsetMs: evidenceCaptureConfiguration.targetOffsetsMs.min() ?? -800,
                maximumCoverageEndOffsetMs: evidenceCaptureConfiguration.targetOffsetsMs.max() ?? 700
            )
        } catch {
            liveVideoCapture = nil
            evidenceVideoCaptureConfigurationError = error.localizedDescription
        }
        self.liveVideoCapture = liveVideoCapture
        evidenceVideoCaptureStatus = liveVideoCapture?.status ?? .idle
        evidencePackageCoordinator = makeEvidencePackageCoordinator(
            captureSession: captureSession,
            ring: evidenceSampler.ring,
            videoSnippetProvider: liveVideoCapture
        )
        let coordinator = FrameInferenceCoordinator(
            runner: runner,
            eventDecoder: eventDecoder,
            evidenceSampler: evidenceSampler,
            videoCapture: liveVideoCapture,
            targetRateHz: 8.0
        ) { [weak self] update in
            self?.apply(update)
        }
        liveCoordinator = coordinator
        return { [weak coordinator] frame in
            coordinator?.consume(frame)
        }
    }

    func stopLiveInference() {
        guard activeDiagnosticSource == .live || liveCoordinator != nil else { return }
        stopTrainingRecordingForSession()
        liveCoordinator?.stop()
        evidenceVideoCaptureStatus = liveVideoCapture?.status ?? .idle
        finishEvidencePackageCoordinator()
        liveCoordinator = nil
        if activeDiagnosticSource == .live {
            evidenceSampler?.stop()
            evidenceVideoCaptureStatus = liveVideoCapture?.status ?? evidenceVideoCaptureStatus
            liveVideoCapture = nil
        }
        if activeDiagnosticSource == .live {
            finishDiagnosticsSession()
            activeDiagnosticSource = nil
        }
        finishCaptureSession()
    }

    func startReplay(url: URL) {
        stopLiveInference()
        stopReplayForNewSession()
        guard let runner = modelRunner else {
            inferenceError = "The model is not ready."
            return
        }

        resetEvents()
        replayProgress = nil
        replayRunning = true
        guard let captureSession = beginCaptureSession() else {
            replayRunning = false
            return
        }
        activeDiagnosticSource = .replay
        captureActivity = .replay
        beginDiagnosticsSessionIfNeeded(source: .replay)
        let replayRunner = VideoReplayRunner()
        let evidenceSampler = EvidenceFrameSampler(
            configuration: evidenceCaptureConfiguration,
            sessionClock: captureSession.clock
        )
        self.evidenceSampler = evidenceSampler
        evidencePackageCoordinator = makeEvidencePackageCoordinator(
            captureSession: captureSession,
            ring: evidenceSampler.ring,
            videoSnippetProvider: AVAssetVideoSnippetProvider(sourceURL: url)
        )
        self.replayRunner = replayRunner
        replayRunner.start(
            url: url,
            modelRunner: runner,
            eventDecoder: eventDecoder,
            evidenceSampler: evidenceSampler
        ) { [weak self] progress in
            Task { @MainActor in
                guard self?.replayRunner === replayRunner else { return }
                self?.applyReplay(progress)
            }
        }
    }

    func cancelReplay() {
        replayRunner?.cancel()
    }

    func resetEvents() {
        eventDecoder.reset()
        eventCount = 0
        latestPrediction = nil
        inferenceError = nil
        scoreHistory.removeAll(keepingCapacity: true)
        lastEventTimestampSeconds = nil
        latestFrame = nil
    }

    func setDiagnosticsRecording(_ enabled: Bool) {
        diagnosticsRecording = enabled
        diagnosticsError = nil
        if enabled, let activeDiagnosticSource {
            beginDiagnosticsSessionIfNeeded(source: activeDiagnosticSource)
        } else if !enabled {
            finishDiagnosticsSession()
        }
    }

    func recordAnnotation(_ kind: SessionLogAnnotation.Kind) {
        guard let source = activeDiagnosticSource, let sessionLog else {
            diagnosticsError = "Start diagnostics recording before adding an annotation."
            return
        }
        do {
            try sessionLog.appendAnnotation(
                SessionLogAnnotation(
                    source: source,
                    timestampSeconds: latestPrediction.map { CMTimeGetSeconds($0.timestamp) },
                    kind: kind
                )
            )
            saveDiagnosticFrame(kind.rawValue)
        } catch {
            diagnosticsError = error.localizedDescription
        }
    }

    func setThreshold(_ value: Double) {
        guard (0.0...1.0).contains(value) else { return }
        var configuration = eventDecoder.configuration
        configuration.threshold = value
        eventDecoder.updateConfiguration(configuration)
        objectWillChange.send()
    }

    private func apply(_ update: FrameInferenceUpdate) {
        latestPrediction = update.prediction ?? latestPrediction
        inferenceMetrics = update.metrics
        if update.prediction != nil || update.errorMessage != nil {
            inferenceError = update.errorMessage
        }
        if let prediction = update.prediction {
            if let frame = update.frame {
                evidencePackageCoordinator?.observe(frame)
            }
            evidencePackageCoordinator?.consume(prediction, event: update.event)
            latestFrame = update.frame
            if appendScore(prediction) {
                recordPrediction(prediction, event: update.event)
            }
        }
        if update.event != nil {
            eventCount += 1
            if let event = update.event {
                lastEventTimestampSeconds = CMTimeGetSeconds(event.timestamp)
            }
        }
        evidenceVideoCaptureStatus = liveVideoCapture?.status ?? evidenceVideoCaptureStatus
    }

    private func applyReplay(_ progress: ReplayProgress) {
        replayProgress = progress
        replayRunning = !progress.isComplete
        inferenceError = progress.errorMessage
        inferenceMetrics = FrameInferenceMetrics(
            cameraFramesReceived: progress.framesRead,
            framesSkippedForSampling: 0,
            framesDroppedWhileBusy: 0,
            predictionsProduced: progress.predictionsProduced,
            averageInferenceDurationMs: progress.averageInferenceDurationMs
        )
        if let prediction = progress.prediction {
            if let frame = progress.frame {
                evidencePackageCoordinator?.observe(frame)
            }
            evidencePackageCoordinator?.consume(prediction, event: progress.event)
            latestPrediction = prediction
            latestFrame = progress.frame ?? latestFrame
            if appendScore(prediction) {
                recordPrediction(prediction, event: progress.event)
            }
        }
        if progress.prediction == nil, let event = progress.event {
            evidencePackageCoordinator?.record(event)
        }
        eventCount = progress.eventCount
        if let timestamp = progress.lastEventTimestampSeconds {
            lastEventTimestampSeconds = timestamp
        }
        if progress.isComplete {
            finishEvidencePackageCoordinator()
            replayRunner = nil
            finishCaptureSession()
            if activeDiagnosticSource == .replay {
                finishDiagnosticsSession()
                activeDiagnosticSource = nil
            }
        }
    }

    @discardableResult
    private func appendScore(_ prediction: ModelPrediction) -> Bool {
        let timestamp = CMTimeGetSeconds(prediction.timestamp)
        if scoreHistory.last?.timestampSeconds == timestamp {
            return false
        }
        scoreHistory.append(
            ScoreSample(
                timestampSeconds: timestamp,
                probability: prediction.cardEventProbability
            )
        )
        if scoreHistory.count > 80 {
            scoreHistory.removeFirst(scoreHistory.count - 80)
        }
        return true
    }

    private func beginDiagnosticsSessionIfNeeded(source: DiagnosticSource) {
        guard diagnosticsRecording, sessionLog == nil else { return }
        do {
            let directory = try diagnosticsDirectory()
            let configuration = eventDecoder.configuration
            let metadata = SessionLogMetadata(
                source: source,
                appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown",
                device: UIDevice.current.model,
                osVersion: UIDevice.current.systemVersion,
                modelName: "CardEventNetTransitionV2",
                modelVersion: modelRunner?.contract.metadata["version"] ?? "unknown",
                targetInferenceHz: 8.0,
                threshold: configuration.threshold,
                peakConfirmationMs: Int((CMTimeGetSeconds(configuration.peakConfirmation) * 1_000.0).rounded()),
                minimumEventGapMs: Int((CMTimeGetSeconds(configuration.minimumEventGap) * 1_000.0).rounded())
            )
            let log = try SessionLog(directory: directory, metadata: metadata)
            sessionLog = log
            diagnosticsLogURL = log.url
        } catch {
            diagnosticsRecording = false
            diagnosticsError = error.localizedDescription
        }
    }

    private func finishDiagnosticsSession() {
        sessionLog?.close()
        sessionLog = nil
    }

    private func stopReplayForNewSession() {
        replayRunner?.cancel()
        replayRunner = nil
        finishEvidencePackageCoordinator()
        finishCaptureSession()
        if activeDiagnosticSource == .replay {
            evidenceSampler?.stop()
            finishDiagnosticsSession()
            activeDiagnosticSource = nil
        }
    }

    private func recordPrediction(_ prediction: ModelPrediction, event: DetectionEvent?) {
        guard let source = activeDiagnosticSource, let sessionLog else { return }
        do {
            try sessionLog.appendPrediction(
                SessionLogPrediction(
                    source: source,
                    timestampSeconds: CMTimeGetSeconds(prediction.timestamp),
                    rawProbability: prediction.cardEventProbability,
                    smoothedProbability: prediction.cardEventProbability,
                    eventEmitted: event != nil,
                    inferenceMs: prediction.inferenceDurationMs
                )
            )
            if event != nil {
                saveDiagnosticFrame("event")
            }
        } catch {
            diagnosticsError = error.localizedDescription
        }
    }

    private func saveDiagnosticFrame(_ prefix: String) {
        guard let latestFrame, let sessionLog else { return }
        let timestamp = String(format: "%.3f", CMTimeGetSeconds(latestFrame.timestamp))
            .replacingOccurrences(of: ".", with: "_")
        let url = sessionLog.url.deletingLastPathComponent()
            .appendingPathComponent("\(prefix)-\(timestamp)-\(UUID().uuidString).jpg")
        do {
            try DiagnosticFrameWriter.writeJPEG(pixelBuffer: latestFrame.pixelBuffer, to: url)
        } catch {
            diagnosticsError = error.localizedDescription
        }
    }

    private func diagnosticsDirectory() throws -> URL {
        guard let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            throw SessionLogError.cannotCreateDirectory(URL(fileURLWithPath: "Documents"))
        }
        return documents
            .appendingPathComponent("CardEventProbeDiagnostics", isDirectory: true)
            .appendingPathComponent("session-\(UUID().uuidString)", isDirectory: true)
    }

    private func makeEvidencePackageCoordinator(
        captureSession: CaptureSession,
        ring: EvidenceFrameRing,
        videoSnippetProvider: (any EvidenceVideoSnippetProviding)? = nil
    ) -> EvidencePackageCoordinator {
        let decoderConfiguration = eventDecoder.configuration
        let model = EvidencePackageModelMetadata(
            name: "CardEventNet",
            version: modelRunner?.contract.metadata["version"]
                ?? "transition-v2-run-20260825-235429",
            weightsSHA256: modelRunner?.contract.metadata["weights_sha256"]
                ?? "f5eccd8e580d1dccecfa7835b3a0d9d5858cc47fdd0098aa33c3c47f01a38d04",
            preprocessing: "full_frame_letterbox_v1"
        )
        let client = EvidencePackageClientMetadata(
            appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
                ?? "unknown",
            build: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
                ?? "unknown",
            deviceModelIdentifier: UIDevice.current.model,
            osVersion: UIDevice.current.systemVersion
        )
        return EvidencePackageCoordinator(
            configuration: evidenceCaptureConfiguration,
            captureSession: captureSession,
            ring: ring,
            store: evidencePackageStore,
            model: model,
            decoderConfiguration: decoderConfiguration,
            client: client,
            camera: EvidencePackageCameraMetadata(
                position: "back",
                orientation: "up",
                width: 1920,
                height: 1080
            ),
            videoSnippetProvider: videoSnippetProvider
        ) { [weak self] result in
            Task { @MainActor in
                guard let self else { return }
                switch result {
                case .success:
                    self.evidencePackageCount += 1
                    self.evidencePackageError = nil
                    self.evidenceQueueDiagnostics = self.evidencePackageStore.diagnostics
                    self.uploadQueuedEvidence()
                case let .failure(error):
                    self.evidencePackageError = error.localizedDescription
                    self.evidenceQueueDiagnostics = self.evidencePackageStore.diagnostics
                }
            }
        } onEventSequenceReserved: { [weak self] sessionID, sequence in
            Task { @MainActor in
                guard let self,
                      self.captureSessionID == sessionID || self.captureSessionID == nil else {
                    return
                }
                self.latestEventSequence = sequence
            }
        }
    }

    private func beginCaptureSession() -> CaptureSession? {
        do {
            let session = try captureSessionIdentityStore.resumeSession()
                ?? captureSessionIdentityStore.startSession()
            captureSession = session
            captureSessionID = session.sessionID
            latestEventSequence = nil
            return session
        } catch {
            inferenceError = "The capture session could not be started: \(error.localizedDescription)"
            activeDiagnosticSource = nil
            return nil
        }
    }

    private func recoverEvidencePackages() {
        do {
            evidenceQueueDiagnostics = try evidencePackageStore.recover()
            evidencePackageError = evidenceQueueDiagnostics?.errors.first
        } catch {
            evidencePackageError = error.localizedDescription
        }
    }

    private func recoverTrainingRecordings() {
        do {
            trainingRecordingQueueDiagnostics = try trainingRecordingStore.recover()
            trainingRecordingError = trainingRecordingQueueDiagnostics?.errors.first
            if trainingRecordingQueueDiagnostics?.queuedCount ?? 0 > 0 {
                trainingRecordingState = .queued
                latestTrainingRecordingID = trainingRecordingQueueDiagnostics?.recoveredRecordingIDs.last
            } else if trainingRecordingQueueDiagnostics?.failedCount ?? 0 > 0 {
                let failedURLs = try? trainingRecordingStore.recordingURLs(in: .failed)
                if let failedURL = failedURLs?.last {
                    latestTrainingRecordingID = failedURL.lastPathComponent
                    let message = trainingRecordingStore.failure(for: failedURL.lastPathComponent)?.message
                        ?? "A training recording upload failed."
                    trainingRecordingState = .failed(message)
                    trainingRecordingError = message
                }
            }
        } catch {
            trainingRecordingError = error.localizedDescription
        }
    }

    private func applyEvidenceUploadAttempts(_ attempts: [EvidenceUploadAttempt]) {
        evidenceQueueDiagnostics = evidencePackageStore.diagnostics
        evidenceUploadError = attempts.compactMap { $0.failure?.message }.first
        latestEvidencePackageID = attempts.compactMap { $0.response?.packageID }.last
    }

    private func applyTrainingRecordingUploadAttempts(
        _ attempts: [TrainingRecordingUploadAttempt]
    ) {
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
        case .retryableFailure, .permanentFailure:
            let message = attempt.failure?.message ?? "The training recording upload failed."
            trainingRecordingState = .failed(message)
            trainingRecordingError = message
        }
    }

    private func applyTrainingRecordingUploadProgress(
        _ progress: TrainingRecordingUploadProgress
    ) {
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
    }

    private func stopTrainingRecordingForSession() {
        guard trainingRecordingState == .recording else { return }
        stopTrainingRecording()
    }

    private func hasEnoughFreeDiskSpace() -> Bool {
        do {
            try FileManager.default.createDirectory(
                at: trainingRecordingStore.root,
                withIntermediateDirectories: true
            )
            let attributes = try FileManager.default.attributesOfFileSystem(
                forPath: trainingRecordingStore.root.path
            )
            guard let freeBytes = attributes[.systemFreeSize] as? NSNumber else {
                return false
            }
            return freeBytes.int64Value >= trainingRecordingMinimumFreeBytes
        } catch {
            return false
        }
    }

    private func finishCaptureSession() {
        guard let captureSession else { return }
        do {
            try captureSessionIdentityStore.endSession(sessionID: captureSession.sessionID)
        } catch {
            inferenceError = "The capture session could not be closed: \(error.localizedDescription)"
        }
        self.captureSession = nil
        captureSessionID = nil
        captureActivity = .idle
    }

    private func finishEvidencePackageCoordinator() {
        guard let evidencePackageCoordinator else { return }
        evidencePackageCoordinator.finish()
        evidencePackageCoordinator.drain()
        self.evidencePackageCoordinator = nil
    }

    private func evidencePackageRoot() -> URL {
        let baseURL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return baseURL
            .appendingPathComponent("DokoDetector", isDirectory: true)
            .appendingPathComponent("packages", isDirectory: true)
    }

    private func evidenceSessionRoot() -> URL {
        let baseURL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return baseURL
            .appendingPathComponent("DokoDetector", isDirectory: true)
            .appendingPathComponent("sessions", isDirectory: true)
    }

    private func trainingRecordingRoot() -> URL {
        let baseURL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return baseURL
            .appendingPathComponent("DokoDetector", isDirectory: true)
            .appendingPathComponent("repository-bundles", isDirectory: true)
    }

    private static func collectionProfileRoot() -> URL {
        let baseURL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return baseURL
            .appendingPathComponent("DokoDetector", isDirectory: true)
            .appendingPathComponent("collection-profiles", isDirectory: true)
    }

    private static func utcTimestamp(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }
}
