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
    @Published private(set) var roundRecordingState: RoundRecordingState?
    @Published private(set) var roundAnalysisState: RoundAnalysisDisplayState = .idle
    @Published private(set) var roundAnalysisSubmissionState: RoundAnalysisSubmissionState?
    @Published private(set) var recordingProfiles: [RecordingProfile] = []
    @Published private(set) var selectedRecordingProfileID: String?
    @Published private(set) var recordingProfileError: String?
    @Published private(set) var obsoleteRecordingProfileNotice: String?
    @Published private(set) var activeRecordingProfile: RecordingProfile?
    @Published private(set) var operatorSettings = OperatorSettings()
    @Published private(set) var recordingWorkspaceState: RecordingWorkspaceState = .idle
    @Published private(set) var cameraState = CameraSession.State.idle

    let appRunContext: AppRunContext
    let cameraSession = CameraSession()

    let backendDiscovery = BackendDiscovery()
    private(set) var modelRunner: CardEventModelRunner?
    let eventDecoder = CausalEventDecoder()
    private let evidenceCaptureConfiguration = EvidenceCaptureConfiguration()
    private(set) var evidenceSampler: EvidenceFrameSampler?
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
    private var captureSession: CaptureSession?
    private var liveCoordinator: FrameInferenceCoordinator?
    private var liveVideoCapture: LiveEvidenceVideoSnippetProvider?
    private var captureSessionIsPersisted = false
    private lazy var roundRecordingStateStore = RoundRecordingStateStore(
        directory: trainingRecordingRoot()
    )
    private lazy var roundAnalysisSubmissionStore = RoundAnalysisSubmissionStore(
        directory: trainingRecordingRoot()
    )
    private let roundAnalysisClient = RoundAnalysisClient()
    private lazy var recordingStartSnapshotStore = RecordingStartSnapshotStore(
        directory: trainingRecordingRoot()
    )
    private let operatorSettingsStore: OperatorSettingsStore
    private var replayRunner: VideoReplayRunner?
    private var sessionLog: SessionLog?
    private var activeDiagnosticSource: DiagnosticSource?
    private var latestFrame: VideoFrame?

    private lazy var evidenceAnalysisWorkflow: EvidenceAnalysisWorkflow = {
        EvidenceAnalysisWorkflow(
            evidenceCaptureConfiguration: evidenceCaptureConfiguration,
            evidencePackageStore: evidencePackageStore,
            evidenceUploadQueue: evidenceUploadQueue,
            roundRecordingStateStore: roundRecordingStateStore,
            roundAnalysisSubmissionStore: roundAnalysisSubmissionStore,
            roundAnalysisClient: roundAnalysisClient,
            backendConfiguration: { [weak self] in
                guard let self,
                      case let .connected(service) = self.backendDiscovery.state else {
                    return nil
                }
                return try? BackendConfiguration(baseURL: service.baseURL)
            },
            onStateChange: { [weak self] state in
                self?.applyEvidenceAnalysisState(state)
            },
            onEventSequenceReserved: { [weak self] sessionID, sequence in
                guard let self,
                      self.captureSessionID == sessionID || self.captureSessionID == nil else {
                    return
                }
                self.latestEventSequence = sequence
            }
        )
    }()

    private lazy var recordingWorkflow: RecordingWorkflow = {
        RecordingWorkflow(
            appRunContext: appRunContext,
            maximumDurationSeconds: trainingRecordingMaximumDurationSeconds,
            maximumSizeBytes: trainingRecordingMaximumSizeBytes,
            captureSessionIdentityStore: captureSessionIdentityStore,
            trainingRecordingStore: trainingRecordingStore,
            trainingRecordingUploadQueue: trainingRecordingUploadQueue,
            roundRecordingStateStore: roundRecordingStateStore,
            recordingStartSnapshotStore: recordingStartSnapshotStore,
            makeEvidencePackageCoordinator: { [weak self] captureSession, ring, video, recordingID in
                guard let self else {
                    preconditionFailure("AppState must outlive RecordingWorkflow")
                }
                let model = EvidencePackageModelMetadata(
                    name: "CardEventNet",
                    version: self.modelRunner?.contract.metadata["version"]
                        ?? "transition-v2-run-20260825-235429",
                    weightsSHA256: self.modelRunner?.contract.metadata["weights_sha256"]
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
                return self.evidenceAnalysisWorkflow.makeEvidencePackageCoordinator(
                    captureSession: captureSession,
                    ring: ring,
                    videoSnippetProvider: video,
                    recordingID: recordingID,
                    requiresActiveRecording: true,
                    model: model,
                    decoderConfiguration: self.eventDecoder.configuration,
                    client: client
                )
            },
            onStateChange: { [weak self] state in
                self?.applyRecordingWorkflowState(state)
            },
            onCaptureSessionStarted: { [weak self] session in
                self?.captureSession = session
                self?.captureSessionID = session.sessionID
                self?.captureSessionIsPersisted = true
            },
            onCaptureSessionMarkerEnded: { [weak self] in
                self?.captureSessionIsPersisted = false
            },
            onTrainingRecordingAcknowledged: { [weak self] recordingID in
                self?.evidenceAnalysisWorkflow.acknowledgeTrainingRecording(recordingID)
            },
            onRecordingFinalized: { [weak self] in
                self?.evidenceAnalysisWorkflow.maybeSubmitRoundAnalysis()
            },
            attachTrainingRecording: { [weak self] coordinator in
                self?.liveCoordinator?.attachTrainingRecording(coordinator)
            }
        )
    }()

    private let trainingRecordingMaximumDurationSeconds: Double
    private let trainingRecordingMaximumSizeBytes: Int64
    private let trainingRecordingMinimumFreeBytes: Int64
    private let recordingProfileStore: RecordingProfileStore

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
        recordingProfileDirectory: URL? = nil,
        operatorSettingsDirectory: URL? = nil,
        appRunContext: AppRunContext = AppRunContext()
    ) {
        self.appRunContext = appRunContext
        trainingRecordingMaximumDurationSeconds = maximumTrainingRecordingDurationSeconds
        trainingRecordingMaximumSizeBytes = maximumTrainingRecordingSizeBytes
        trainingRecordingMinimumFreeBytes = minimumTrainingRecordingFreeBytes
        recordingProfileStore = RecordingProfileStore(
            directory: recordingProfileDirectory ?? Self.recordingProfileRoot(),
            obsoleteDirectories: recordingProfileDirectory == nil
                ? [Self.legacyCollectionProfileRoot()]
                : []
        )
        operatorSettingsStore = OperatorSettingsStore(
            directory: operatorSettingsDirectory ?? Self.operatorSettingsRoot()
        )
        cameraState = cameraSession.state
        cameraSession.onStateChange = { [weak self] state in
            self?.handleCameraStateChange(state)
        }
        do {
            let result = try recordingProfileStore.loadAllResult()
            recordingProfiles = result.profiles
            selectedRecordingProfileID = recordingProfiles.first?.profileID
            obsoleteRecordingProfileNotice = result.obsoleteFileNotice
        } catch {
            recordingProfileError = error.localizedDescription
        }
        do {
            operatorSettings = try operatorSettingsStore.load() ?? OperatorSettings()
        } catch {
            recordingProfileError = error.localizedDescription
        }
        evidenceAnalysisWorkflow.recover()
        recordingWorkflow.recover()
        loadModel()
    }

    func startBackendDiscovery() {
        backendDiscovery.start()
    }

    func uploadQueuedEvidence() {
        evidenceAnalysisWorkflow.maybeSubmitRoundAnalysis()
        evidenceAnalysisWorkflow.uploadQueuedEvidence()
    }

    func retryFailedEvidence() {
        evidenceAnalysisWorkflow.maybeSubmitRoundAnalysis()
        evidenceAnalysisWorkflow.retryFailedEvidence()
    }

    var recordingStartRequirements: RecordingWorkspaceStartRequirements {
        RecordingWorkspaceStartRequirements(
            workspaceState: recordingWorkspaceState,
            profileSelected: selectedRecordingProfile != nil,
            profileComplete: selectedRecordingProfile?.isComplete == true,
            operatorConfigured: operatorSettings.isComplete,
            cameraReady: cameraState == .running && captureActivity == .live,
            modelReady: {
                if case .ready = modelState { return true }
                return false
            }(),
            backendConnected: {
                if case .connected = backendDiscovery.state { return true }
                return false
            }(),
            diskSpaceAvailable: hasEnoughFreeDiskSpace(),
            queueReady: recordingWorkflow.queueReady,
            replayRunning: replayRunning
        )
    }

    var canStartRecording: Bool {
        recordingStartRequirements.canStart
    }

    var isRecordingLocked: Bool {
        if recordingWorkflow.recordingWorkspaceState.isRecording {
            return true
        }
        switch recordingWorkflow.trainingRecordingState {
        case .recording, .finalizing:
            return true
        case .idle, .queued, .uploading, .acknowledged, .failed:
            return false
        }
    }

    func startRecordingWorkspace() {
        guard !recordingWorkflow.recordingWorkspaceState.isRecording, !replayRunning else { return }

        if liveCoordinator != nil, captureActivity == .live {
            if case .failed = recordingWorkspaceState {
                guard recordingWorkflow.startPreview() else { return }
            }
            if recordingWorkspaceState == .starting {
                _ = recordingWorkflow.markPreviewReady()
            }
            if cameraState != .running {
                cameraSession.start()
            }
            return
        }

        guard recordingWorkflow.startPreview() else { return }
        guard let frameHandler = startLiveInference() else {
            _ = recordingWorkflow.fail("The model is not ready.")
            return
        }
        cameraSession.setFrameHandler(frameHandler)
        cameraSession.start()
    }

    func stopRecordingWorkspace() {
        if recordingWorkflow.trainingRecordingState == .recording {
            stopRecording()
        }
        cameraSession.setFrameHandler(nil)
        cameraSession.stop()
        stopPreviewInference()

        if !recordingWorkflow.recordingWorkspaceState.isRecording {
            _ = recordingWorkflow.stopPreview()
        }
    }

    private func handleCameraStateChange(_ state: CameraSession.State) {
        cameraState = state
        switch state {
        case .running:
            guard recordingWorkflow.recordingWorkspaceState != .idle else {
                cameraSession.stop()
                return
            }
            if recordingWorkflow.recordingWorkspaceState == .starting {
                _ = recordingWorkflow.markPreviewReady()
            }
        case .denied, .failed:
            if recordingWorkflow.recordingWorkspaceState.isRecording {
                stopRecording()
            } else if recordingWorkflow.recordingWorkspaceState == .starting || recordingWorkflow.recordingWorkspaceState == .preview {
                _ = recordingWorkflow.fail(state.message)
                inferenceError = state.message
            }
        case .idle, .requestingPermission:
            break
        }
    }

    func uploadQueuedTrainingRecordings() {
        recordingWorkflow.uploadQueuedTrainingRecordings(using: currentBackendConfiguration())
    }

    func retryFailedTrainingRecordings() {
        recordingWorkflow.retryFailedTrainingRecordings(using: currentBackendConfiguration())
    }

    /// Starts foreground polling while the Record view is visible.
    func startRoundAnalysisPolling() {
        evidenceAnalysisWorkflow.startRoundAnalysisPolling()
    }

    func stopRoundAnalysisPolling() {
        evidenceAnalysisWorkflow.stopRoundAnalysisPolling()
    }

    var selectedRecordingProfile: RecordingProfile? {
        guard let selectedRecordingProfileID else { return nil }
        return recordingProfiles.first { $0.profileID == selectedRecordingProfileID }
    }

    func newRecordingProfileDraft() -> RecordingProfile {
        RecordingProfile.newDraft()
    }

    func selectRecordingProfile(_ profileID: String?) {
        guard profileID == nil || recordingProfiles.contains(where: { $0.profileID == profileID }) else {
            return
        }
        selectedRecordingProfileID = profileID
        recordingProfileError = nil
    }

    func saveRecordingProfile(_ profile: RecordingProfile) {
        do {
            try recordingProfileStore.save(profile)
            let result = try recordingProfileStore.loadAllResult()
            recordingProfiles = result.profiles
            selectedRecordingProfileID = profile.profileID
            obsoleteRecordingProfileNotice = result.obsoleteFileNotice
            recordingProfileError = nil
        } catch {
            recordingProfileError = error.localizedDescription
        }
    }

    func updateOperatorSettings(_ settings: OperatorSettings) {
        do {
            try operatorSettingsStore.save(settings)
            operatorSettings = settings
            recordingProfileError = nil
        } catch {
            recordingProfileError = error.localizedDescription
        }
    }

    func startRecording(profile: RecordingProfile) {
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
            appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown",
            build: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown",
            deviceModel: UIDevice.current.model,
            osVersion: UIDevice.current.systemVersion
        )
        _ = recordingWorkflow.startRecording(
            profile: profile,
            operatorSettings: operatorSettings,
            hasEnoughFreeDiskSpace: hasEnoughFreeDiskSpace(),
            evidenceSampler: evidenceSampler,
            liveVideoCapture: liveVideoCapture,
            model: model,
            decoder: decoder,
            client: client,
            resetRoundAnalysis: { [weak self] in
                try self?.evidenceAnalysisWorkflow.resetRoundAnalysis()
            }
        )
    }

    func stopRecording() {
        recordingWorkflow.stopRecording()
    }

    func updateTrainingRecordingClock(now: Date = Date()) {
        recordingWorkflow.updateClock(now: now)
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
        stopPreviewInference()
        resetEvents()
        evidenceVideoCaptureConfigurationError = nil
        guard let runner = modelRunner else { return nil }
        let captureSession = beginPreviewCaptureSession()
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
        if recordingWorkflow.trainingRecordingState == .recording {
            stopRecording()
        }
        stopPreviewInference()
        if !recordingWorkflow.recordingWorkspaceState.isRecording {
            _ = recordingWorkflow.stopPreview()
        }
    }

    private func stopPreviewInference() {
        guard activeDiagnosticSource == .live || liveCoordinator != nil else { return }
        liveCoordinator?.stop()
        evidenceVideoCaptureStatus = liveVideoCapture?.status ?? .idle
        recordingWorkflow.finishEvidencePackageCoordinator()
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
        guard !recordingWorkflow.recordingWorkspaceState.isRecording else {
            inferenceError = "Stop the recording before starting replay."
            return
        }
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
        recordingWorkflow.setEvidencePackageCoordinator(evidenceAnalysisWorkflow.makeEvidencePackageCoordinator(
            captureSession: captureSession,
            ring: evidenceSampler.ring,
            videoSnippetProvider: AVAssetVideoSnippetProvider(sourceURL: url),
            recordingID: nil,
            requiresActiveRecording: false,
            model: EvidencePackageModelMetadata(
                name: "CardEventNet",
                version: modelRunner?.contract.metadata["version"] ?? "transition-v2-run-20260825-235429",
                weightsSHA256: modelRunner?.contract.metadata["weights_sha256"]
                    ?? "f5eccd8e580d1dccecfa7835b3a0d9d5858cc47fdd0098aa33c3c47f01a38d04",
                preprocessing: "full_frame_letterbox_v1"
            ),
            decoderConfiguration: eventDecoder.configuration,
            client: EvidencePackageClientMetadata(
                appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown",
                build: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown",
                deviceModelIdentifier: UIDevice.current.model,
                osVersion: UIDevice.current.systemVersion
            )
        ))
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
                recordingWorkflow.observeEvidence(frame)
            }
            recordingWorkflow.consumeEvidence(prediction, event: update.event)
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
                recordingWorkflow.observeEvidence(frame)
            }
            recordingWorkflow.consumeEvidence(prediction, event: progress.event)
            latestPrediction = prediction
            latestFrame = progress.frame ?? latestFrame
            if appendScore(prediction) {
                recordPrediction(prediction, event: progress.event)
            }
        }
        if progress.prediction == nil, let event = progress.event {
            recordingWorkflow.recordEvidence(event)
        }
        eventCount = progress.eventCount
        if let timestamp = progress.lastEventTimestampSeconds {
            lastEventTimestampSeconds = timestamp
        }
        if progress.isComplete {
            recordingWorkflow.finishEvidencePackageCoordinator()
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
        recordingWorkflow.finishEvidencePackageCoordinator()
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

    private func beginCaptureSession() -> CaptureSession? {
        do {
            let session = try captureSessionIdentityStore.resumeSession()
                ?? captureSessionIdentityStore.startSession()
            captureSession = session
            captureSessionID = session.sessionID
            captureSessionIsPersisted = true
            latestEventSequence = nil
            return session
        } catch {
            inferenceError = "The capture session could not be started: \(error.localizedDescription)"
            activeDiagnosticSource = nil
            return nil
        }
    }

    private func beginPreviewCaptureSession() -> CaptureSession {
        let session = CaptureSession()
        captureSession = session
        captureSessionID = nil
        captureSessionIsPersisted = false
        latestEventSequence = nil
        return session
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

    private func currentBackendConfiguration() -> BackendConfiguration? {
        guard case let .connected(service) = backendDiscovery.state else { return nil }
        return try? BackendConfiguration(baseURL: service.baseURL)
    }

    private func applyRecordingWorkflowState(_ state: RecordingWorkflow.State) {
        recordingWorkspaceState = state.workspaceState
        trainingRecordingState = state.trainingState
        trainingRecordingMetrics = state.metrics
        trainingRecordingQueueDiagnostics = state.queueDiagnostics
        trainingRecordingError = state.error
        trainingRecordingUploadError = state.uploadError
        trainingRecordingUploadRunning = state.uploadRunning
        trainingRecordingUploadProgress = state.uploadProgress
        latestTrainingRecordingID = state.latestRecordingID
        trainingRecordingStartedAt = state.startedAt
        trainingRecordingElapsedSeconds = state.elapsedSeconds
        trainingRecordingEstimatedSizeBytes = state.estimatedSizeBytes
        activeRecordingProfile = state.activeProfile
        roundRecordingState = state.roundRecordingState
        captureSessionID = state.captureSessionID
        evidenceAnalysisWorkflow.setRoundRecordingState(state.roundRecordingState)
    }

    private func applyEvidenceAnalysisState(_ state: EvidenceAnalysisWorkflow.State) {
        evidencePackageCount = state.packageCount
        evidencePackageError = state.packageError
        evidenceQueueDiagnostics = state.queueDiagnostics
        evidenceUploadError = state.uploadError
        evidenceUploadRunning = state.uploadRunning
        latestEvidencePackageID = state.latestPackageID
        roundRecordingState = state.roundRecordingState
        roundAnalysisState = state.roundAnalysisState
        roundAnalysisSubmissionState = state.roundAnalysisSubmissionState
    }

    private func finishCaptureSession() {
        guard let captureSession else { return }
        if captureSessionIsPersisted {
            do {
                try captureSessionIdentityStore.endSession(sessionID: captureSession.sessionID)
            } catch {
                inferenceError = "The capture session could not be closed: \(error.localizedDescription)"
            }
        }
        captureSessionIsPersisted = false
        self.captureSession = nil
        captureSessionID = nil
        captureActivity = .idle
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

    private static func recordingProfileRoot() -> URL {
        let baseURL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return baseURL
            .appendingPathComponent("DokoDetector", isDirectory: true)
            .appendingPathComponent("recording-profiles", isDirectory: true)
    }

    private static func operatorSettingsRoot() -> URL {
        let baseURL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return baseURL
            .appendingPathComponent("DokoDetector", isDirectory: true)
            .appendingPathComponent("settings", isDirectory: true)
    }

    private static func legacyCollectionProfileRoot() -> URL {
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
