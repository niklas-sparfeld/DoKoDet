import Foundation
import UIKit

struct AnalysisSubmissionGate {
    private(set) var isInFlight = false

    mutating func begin() -> Bool {
        guard !isInFlight else { return false }
        isInFlight = true
        return true
    }

    mutating func finish() {
        isInFlight = false
    }

    mutating func cancel() {
        isInFlight = false
    }
}

/// Owns evidence upload, acknowledgement, and round-analysis coordination.
@MainActor
final class EvidenceAnalysisWorkflow {
    struct State {
        let packageCount: Int
        let packageError: String?
        let queueDiagnostics: EvidencePackageQueueDiagnostics?
        let uploadError: String?
        let uploadRunning: Bool
        let latestPackageID: UUID?
        let roundRecordingState: RoundRecordingState?
        let roundAnalysisState: RoundAnalysisDisplayState
        let roundAnalysisSubmissionState: RoundAnalysisSubmissionState?
    }

    private(set) var evidencePackageCount = 0
    private(set) var evidencePackageError: String?
    private(set) var evidenceQueueDiagnostics: EvidencePackageQueueDiagnostics?
    private(set) var evidenceUploadError: String?
    private(set) var evidenceUploadRunning = false
    private(set) var latestEvidencePackageID: UUID?
    private(set) var roundRecordingState: RoundRecordingState?
    private(set) var roundAnalysisState: RoundAnalysisDisplayState = .idle
    private(set) var roundAnalysisSubmissionState: RoundAnalysisSubmissionState?

    private let evidenceCaptureConfiguration: EvidenceCaptureConfiguration
    private let evidencePackageStore: EvidencePackageStore
    private let evidenceUploadQueue: EvidenceUploadQueue?
    private let roundRecordingStateStore: RoundRecordingStateStore
    private let roundAnalysisSubmissionStore: RoundAnalysisSubmissionStore
    private let roundAnalysisClient: RoundAnalysisClient
    private let backendConfiguration: () -> BackendConfiguration?
    private let onStateChange: (State) -> Void
    private let onEventSequenceReserved: (UUID, Int) -> Void
    private var evidenceUploadTask: Task<Void, Never>?
    private var roundAnalysisRequestGate = AnalysisSubmissionGate()
    private var roundAnalysisRequestTask: Task<Void, Never>?
    private var roundAnalysisPollingTask: Task<Void, Never>?

    init(
        evidenceCaptureConfiguration: EvidenceCaptureConfiguration,
        evidencePackageStore: EvidencePackageStore,
        evidenceUploadQueue: EvidenceUploadQueue?,
        roundRecordingStateStore: RoundRecordingStateStore,
        roundAnalysisSubmissionStore: RoundAnalysisSubmissionStore,
        roundAnalysisClient: RoundAnalysisClient,
        backendConfiguration: @escaping () -> BackendConfiguration?,
        onStateChange: @escaping (State) -> Void,
        onEventSequenceReserved: @escaping (UUID, Int) -> Void
    ) {
        self.evidenceCaptureConfiguration = evidenceCaptureConfiguration
        self.evidencePackageStore = evidencePackageStore
        self.evidenceUploadQueue = evidenceUploadQueue
        self.roundRecordingStateStore = roundRecordingStateStore
        self.roundAnalysisSubmissionStore = roundAnalysisSubmissionStore
        self.roundAnalysisClient = roundAnalysisClient
        self.backendConfiguration = backendConfiguration
        self.onStateChange = onStateChange
        self.onEventSequenceReserved = onEventSequenceReserved
    }

    var state: State {
        State(
            packageCount: evidencePackageCount,
            packageError: evidencePackageError,
            queueDiagnostics: evidenceQueueDiagnostics,
            uploadError: evidenceUploadError,
            uploadRunning: evidenceUploadRunning,
            latestPackageID: latestEvidencePackageID,
            roundRecordingState: roundRecordingState,
            roundAnalysisState: roundAnalysisState,
            roundAnalysisSubmissionState: roundAnalysisSubmissionState
        )
    }

    func recover() {
        do {
            evidenceQueueDiagnostics = try evidencePackageStore.recover()
            evidencePackageError = evidenceQueueDiagnostics?.errors.first
        } catch {
            evidencePackageError = error.localizedDescription
        }
        do {
            roundRecordingState = try roundRecordingStateStore.load()
        } catch {
            evidencePackageError = error.localizedDescription
        }
        recoverRoundAnalysisState()
        publish()
    }

    func setRoundRecordingState(_ state: RoundRecordingState?) {
        roundRecordingState = state
        publish()
    }

    func makeEvidencePackageCoordinator(
        captureSession: CaptureSession,
        ring: EvidenceFrameRing,
        videoSnippetProvider: (any EvidenceVideoSnippetProviding)?,
        recordingID: String? = nil,
        requiresActiveRecording: Bool = false,
        model: EvidencePackageModelMetadata,
        decoderConfiguration: CausalEventDecoder.Configuration,
        client: EvidencePackageClientMetadata,
        onSequenceReserved: @escaping (UUID, Int) -> Void = { _, _ in }
    ) -> EvidencePackageCoordinator {
        EvidencePackageCoordinator(
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
            recordingID: recordingID,
            requiresActiveRecording: requiresActiveRecording,
            videoSnippetProvider: videoSnippetProvider,
            onPackagePersisted: { [weak self] result in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.handlePersistedPackage(
                        result,
                        captureSessionID: captureSession.sessionID,
                        recordingID: recordingID
                    )
                }
            },
            onEventSequenceReserved: { [weak self] sessionID, sequence in
                Task { @MainActor [weak self] in
                    self?.onEventSequenceReserved(sessionID, sequence)
                    onSequenceReserved(sessionID, sequence)
                }
            }
        )
    }

    func uploadQueuedEvidence() {
        guard let configuration = backendConfiguration() else { return }
        guard let evidenceUploadQueue else { return }
        guard evidenceUploadTask == nil else { return }
        evidenceUploadRunning = true
        evidenceUploadTask = Task { [weak self] in
            let attempts = await evidenceUploadQueue.uploadQueued(using: configuration)
            await MainActor.run {
                guard let self else { return }
                self.evidenceUploadTask = nil
                self.evidenceUploadRunning = false
                guard !Task.isCancelled else { return }
                self.applyEvidenceUploadAttempts(attempts)
                if self.evidenceQueueDiagnostics?.queuedCount ?? 0 > 0 {
                    self.uploadQueuedEvidence()
                }
            }
        }
        publish()
    }

    func retryFailedEvidence() {
        guard let configuration = backendConfiguration() else {
            evidenceUploadError = "Connect to a backend before retrying evidence uploads."
            publish()
            return
        }
        guard let evidenceUploadQueue else {
            evidenceUploadError = "The evidence upload queue is not available."
            publish()
            return
        }
        guard evidenceUploadTask == nil else { return }
        evidenceUploadRunning = true
        evidenceUploadTask = Task { [weak self] in
            let attempts = await evidenceUploadQueue.retryFailed(using: configuration)
            await MainActor.run {
                guard let self else { return }
                self.evidenceUploadTask = nil
                self.evidenceUploadRunning = false
                guard !Task.isCancelled else { return }
                self.applyEvidenceUploadAttempts(attempts)
                if self.evidenceQueueDiagnostics?.queuedCount ?? 0 > 0 {
                    self.uploadQueuedEvidence()
                }
            }
        }
        publish()
    }

    func startRoundAnalysisPolling() {
        guard roundAnalysisPollingTask == nil else { return }
        roundAnalysisPollingTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                self.pollRoundAnalysisOnce()
                do {
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                } catch {
                    break
                }
            }
            if self.roundAnalysisPollingTask != nil {
                self.roundAnalysisPollingTask = nil
            }
        }
    }

    func stopRoundAnalysisPolling() {
        roundAnalysisPollingTask?.cancel()
        roundAnalysisPollingTask = nil
        roundAnalysisRequestTask?.cancel()
        roundAnalysisRequestTask = nil
        roundAnalysisRequestGate.cancel()
    }

    func acknowledgeTrainingRecording(_ recordingID: String) {
        if let state = try? roundRecordingStateStore.markRecordingBundleAcknowledged(
            recordingID: recordingID
        ) {
            roundRecordingState = state
        }
        maybeSubmitRoundAnalysis()
        publish()
    }

    func maybeSubmitRoundAnalysis() {
        guard let recordingState = roundRecordingState else { return }
        guard recordingState.recordingPipelineAnalysisSubmissionReadiness == .ready else {
            if trainingRecordingHasFinished {
                roundAnalysisState = .waitingForUploads
            }
            publish()
            return
        }
        guard let configuration = backendConfiguration() else {
            roundAnalysisState = .waitingForUploads
            publish()
            return
        }
        let currentSubmission = try? roundAnalysisSubmissionStore.load()
        let submission: RoundAnalysisSubmissionState
        if let currentSubmission,
           currentSubmission.recordingID == recordingState.recordingID,
           currentSubmission.sessionID == recordingState.sessionID,
           currentSubmission.roundSetup == recordingState.roundSetup,
           currentSubmission.evidencePackageIDs == recordingState.evidencePackageIDs {
            submission = currentSubmission
        } else {
            do {
                submission = try RoundAnalysisSubmissionState(
                    recordingID: recordingState.recordingID,
                    sessionID: recordingState.sessionID,
                    roundSetup: recordingState.roundSetup,
                    evidencePackageIDs: recordingState.evidencePackageIDs,
                    phase: .submitting
                )
                try roundAnalysisSubmissionStore.save(submission)
                roundAnalysisSubmissionState = submission
            } catch {
                roundAnalysisState = .failed(error.localizedDescription)
                publish()
                return
            }
        }

        roundAnalysisSubmissionState = submission
        if let remoteStatus = submission.remoteStatus {
            roundAnalysisState = displayState(for: submission)
            if !remoteStatus.isTerminal {
                publish()
            }
            return
        }
        guard roundAnalysisRequestGate.begin() else { return }
        roundAnalysisState = .queued
        publish()
        roundAnalysisRequestTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let status = try await self.roundAnalysisClient.create(
                    recordingID: submission.recordingID,
                    using: configuration
                )
                let identified = submission.analysisID == nil
                    ? (try? submission.assigningAnalysisID(status.analysisID)) ?? submission
                    : submission
                self.applyRoundAnalysisStatus(status, to: identified)
            } catch {
                guard !Task.isCancelled else {
                    self.roundAnalysisRequestGate.cancel()
                    return
                }
                self.roundAnalysisState = .failed(error.localizedDescription)
                if let failed = try? submission.updating(
                    phase: .failed,
                    error: error.localizedDescription
                ) {
                    self.roundAnalysisSubmissionState = failed
                    try? self.roundAnalysisSubmissionStore.save(failed)
                }
                self.publish()
            }
            self.roundAnalysisRequestGate.finish()
            self.roundAnalysisRequestTask = nil
        }
    }

    func resetRoundAnalysis() throws {
        roundAnalysisRequestTask?.cancel()
        roundAnalysisRequestTask = nil
        roundAnalysisRequestGate.cancel()
        try roundAnalysisSubmissionStore.remove()
        roundAnalysisSubmissionState = nil
        roundAnalysisState = .idle
        publish()
    }

    private var trainingRecordingHasFinished: Bool {
        guard let roundRecordingState else { return false }
        return roundRecordingState.recordingBundleFinalized || roundRecordingState.recordingBundleAcknowledged
    }

    private func handlePersistedPackage(
        _ result: Result<URL, EvidencePackageStoreError>,
        captureSessionID: UUID,
        recordingID: String?
    ) {
        switch result {
        case let .success(url):
            guard let package = try? evidencePackageStore.loadPackage(at: url) else {
                evidencePackageError = "A persisted evidence package could not be read."
                evidenceQueueDiagnostics = evidencePackageStore.diagnostics
                publish()
                return
            }
            if let recordingID {
                guard package.manifest.session.sessionID == captureSessionID,
                      package.repositoryMetadata?.lineage.packageID
                          == package.manifest.packageID.uuidString.lowercased(),
                      package.repositoryMetadata?.lineage.parentRecordingID == recordingID,
                      package.repositoryMetadata?.lineage.sessionID
                          == captureSessionID.uuidString.lowercased(),
                      let state = try? roundRecordingStateStore.appendEvidencePackage(
                          package.manifest.packageID,
                          recordingID: recordingID,
                          sessionID: captureSessionID
                      ) else {
                    evidencePackageError = "A persisted evidence package has invalid recording lineage."
                    evidenceQueueDiagnostics = evidencePackageStore.diagnostics
                    publish()
                    return
                }
                roundRecordingState = state
            }
            evidencePackageCount += 1
            evidencePackageError = nil
            evidenceQueueDiagnostics = evidencePackageStore.diagnostics
            publish()
            uploadQueuedEvidence()
        case let .failure(error):
            evidencePackageError = error.localizedDescription
            evidenceQueueDiagnostics = evidencePackageStore.diagnostics
            publish()
        }
    }

    private func applyEvidenceUploadAttempts(_ attempts: [EvidenceUploadAttempt]) {
        evidenceQueueDiagnostics = evidencePackageStore.diagnostics
        evidenceUploadError = attempts.compactMap { $0.failure?.message }.first
        latestEvidencePackageID = attempts.compactMap { $0.response?.packageID }.last
        guard let recordingID = roundRecordingState?.recordingID else {
            publish()
            return
        }
        for attempt in attempts where attempt.disposition == .acknowledged {
            if let state = try? roundRecordingStateStore.acknowledgeEvidencePackage(
                attempt.packageID,
                recordingID: recordingID
            ) {
                roundRecordingState = state
            }
        }
        maybeSubmitRoundAnalysis()
        publish()
    }

    private func recoverRoundAnalysisState() {
        do {
            guard let state = try roundAnalysisSubmissionStore.load() else { return }
            guard let recordingState = roundRecordingState,
                  recordingState.recordingID == state.recordingID,
                  recordingState.sessionID == state.sessionID else {
                try roundAnalysisSubmissionStore.remove()
                return
            }
            roundAnalysisSubmissionState = state
            roundAnalysisState = displayState(for: state)
        } catch {
            roundAnalysisState = .failed(error.localizedDescription)
        }
    }

    private func pollRoundAnalysisOnce() {
        guard !roundAnalysisRequestGate.isInFlight,
              let submission = try? roundAnalysisSubmissionStore.load(),
              let analysisID = submission.analysisID else { return }
        guard submission.remoteStatus?.isTerminal != true else {
            roundAnalysisState = displayState(for: submission)
            publish()
            return
        }
        guard submission.remoteStatus != nil else {
            maybeSubmitRoundAnalysis()
            return
        }
        guard let configuration = backendConfiguration() else { return }
        guard roundAnalysisRequestGate.begin() else { return }
        roundAnalysisRequestTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let status = try await self.roundAnalysisClient.status(
                    for: analysisID,
                    using: configuration
                )
                self.applyRoundAnalysisStatus(status, to: submission)
            } catch {
                guard !Task.isCancelled else {
                    self.roundAnalysisRequestGate.cancel()
                    return
                }
                self.roundAnalysisState = .failed(error.localizedDescription)
                self.publish()
            }
            self.roundAnalysisRequestGate.finish()
            self.roundAnalysisRequestTask = nil
        }
    }

    private func applyRoundAnalysisStatus(
        _ status: RoundAnalysisStatus,
        to submission: RoundAnalysisSubmissionState
    ) {
        guard let analysisID = submission.analysisID,
              status.analysisID == analysisID,
              status.recordingID == submission.recordingID,
              status.roundID == submission.roundSetup.roundID,
              status.sessionID == submission.sessionID else {
            roundAnalysisState = .failed("The round-analysis response does not match the recording.")
            publish()
            return
        }
        let phase: RoundAnalysisSubmissionPhase
        switch status.state {
        case .queued: phase = .queued
        case .analyzingEvidence: phase = .analyzingEvidence
        case .reconstructing: phase = .reconstructing
        case .complete: phase = .complete
        case .failed: phase = .failed
        }
        do {
            let updated = try submission.updating(
                phase: phase,
                remoteStatus: status,
                error: status.error
            )
            try roundAnalysisSubmissionStore.save(updated)
            roundAnalysisSubmissionState = updated
            roundAnalysisState = displayState(for: updated)
        } catch {
            roundAnalysisState = .failed(error.localizedDescription)
        }
        publish()
    }

    private func displayState(
        for submission: RoundAnalysisSubmissionState
    ) -> RoundAnalysisDisplayState {
        guard let remoteStatus = submission.remoteStatus else {
            switch submission.phase {
            case .waitingForUploads: return .waitingForUploads
            case .submitting, .queued: return .queued
            case .analyzingEvidence:
                return .analyzingEvidence(completed: 0, total: submission.evidencePackageIDs.count)
            case .reconstructing: return .reconstructing
            case .complete: return .failed("The completed round analysis status is missing.")
            case .failed: return .failed(submission.error ?? "The round analysis failed.")
            }
        }
        switch remoteStatus.state {
        case .queued: return .queued
        case .analyzingEvidence:
            return .analyzingEvidence(
                completed: remoteStatus.completedEvidencePackages,
                total: remoteStatus.totalEvidencePackages
            )
        case .reconstructing: return .reconstructing
        case .complete:
            guard let result = remoteStatus.result else {
                return .failed("The completed round analysis status is missing.")
            }
            return .complete(RoundAnalysisResultSummary(result: result))
        case .failed: return .failed(remoteStatus.error ?? "The round analysis failed.")
        }
    }

    private func publish() {
        onStateChange(state)
    }
}
