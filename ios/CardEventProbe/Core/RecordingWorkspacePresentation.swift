import Foundation

public enum RecordingWorkspaceSurfaceItem: String, CaseIterable, Sendable {
    case profileRow
    case cameraFrame
    case eventCount
    case primaryControl
    case elapsedTime
    case lifecycleStatus
    case moreDetails
}

public enum RecordingWorkspaceStatusTone: String, Equatable, Sendable {
    case neutral
    case active
    case success
    case warning
    case failure
}

public struct RecordingWorkspaceStatus: Equatable, Sendable {
    public let title: String
    public let detail: String?
    public let tone: RecordingWorkspaceStatusTone

    public init(
        title: String,
        detail: String? = nil,
        tone: RecordingWorkspaceStatusTone
    ) {
        self.title = title
        self.detail = detail
        self.tone = tone
    }
}

/// The independent checks that must pass before the primary Start control is enabled.
public struct RecordingWorkspaceStartRequirements: Equatable, Sendable {
    public let workspaceState: RecordingWorkspaceState
    public let profileSelected: Bool
    public let profileComplete: Bool
    public let operatorConfigured: Bool
    public let cameraReady: Bool
    public let modelReady: Bool
    public let backendConnected: Bool
    public let diskSpaceAvailable: Bool
    public let queueReady: Bool
    public let replayRunning: Bool

    public init(
        workspaceState: RecordingWorkspaceState,
        profileSelected: Bool,
        profileComplete: Bool,
        operatorConfigured: Bool,
        cameraReady: Bool,
        modelReady: Bool,
        backendConnected: Bool,
        diskSpaceAvailable: Bool,
        queueReady: Bool,
        replayRunning: Bool
    ) {
        self.workspaceState = workspaceState
        self.profileSelected = profileSelected
        self.profileComplete = profileComplete
        self.operatorConfigured = operatorConfigured
        self.cameraReady = cameraReady
        self.modelReady = modelReady
        self.backendConnected = backendConnected
        self.diskSpaceAvailable = diskSpaceAvailable
        self.queueReady = queueReady
        self.replayRunning = replayRunning
    }

    public var blocker: String? {
        guard profileSelected else { return "Select a recording profile." }
        guard profileComplete else { return "Complete the selected recording profile." }
        guard operatorConfigured else { return "Add an operator name in Settings." }
        guard !replayRunning else { return "Stop replay before recording." }

        switch workspaceState {
        case .idle:
            return "Starting the camera preview."
        case .starting:
            return "Camera preview is starting."
        case let .failed(message):
            return message
        case .recording, .stopping:
            return "A recording is already active."
        case .preview, .postRecording:
            break
        }

        guard cameraReady else { return "Camera is not ready." }
        guard modelReady else { return "The detection model is not ready." }
        guard backendConnected else { return "Connect to a backend before recording." }
        guard diskSpaceAvailable else { return "There is not enough free space for a recording." }
        guard queueReady else { return "The previous recording is still finishing." }
        return nil
    }

    public var canStart: Bool { blocker == nil }
}

/// View-facing state for the compact recording workspace.
public struct RecordingWorkspaceSurfaceState: Equatable, Sendable {
    public let informationOrder: [RecordingWorkspaceSurfaceItem]
    public let primaryActionTitle: String
    public let primaryActionEnabled: Bool
    public let primaryActionAccessibilityLabel: String
    public let primaryActionAccessibilityHint: String?
    public let eventCountAccessibilityLabel: String
    public let eventCountAccessibilityValue: String
    public let showsElapsedTime: Bool
    public let profileControlsLocked: Bool
    public let replayEntryLocked: Bool
    public let startBlocker: String?
    public let status: RecordingWorkspaceStatus

    public init(
        workspaceState: RecordingWorkspaceState,
        trainingState: TrainingRecordingWorkflowState,
        roundAnalysisState: RoundAnalysisDisplayState,
        startRequirements: RecordingWorkspaceStartRequirements,
        eventCount: Int,
        elapsedSeconds: Double,
        uploadDetail: String? = nil,
        uploadError: String? = nil
    ) {
        informationOrder = [
            .profileRow,
            .cameraFrame,
            .eventCount,
            .primaryControl,
            .elapsedTime,
            .lifecycleStatus,
            .moreDetails,
        ]
        startBlocker = startRequirements.blocker
        profileControlsLocked = workspaceState.isRecording
            || trainingState == .recording
            || trainingState == .finalizing
        replayEntryLocked = workspaceState.isRecording
        eventCountAccessibilityLabel = "Events detected"
        eventCountAccessibilityValue = "\(max(0, eventCount))"
        showsElapsedTime = workspaceState.isRecording || trainingState == .recording

        switch workspaceState {
        case .recording:
            primaryActionTitle = "Stop recording"
            primaryActionEnabled = true
            primaryActionAccessibilityLabel = "Stop recording"
            primaryActionAccessibilityHint = "Stops the recording and starts finalization."
        case .stopping:
            primaryActionTitle = "Finalizing recording"
            primaryActionEnabled = false
            primaryActionAccessibilityLabel = "Finalizing recording"
            primaryActionAccessibilityHint = nil
        default:
            primaryActionTitle = "Start recording"
            primaryActionEnabled = startRequirements.canStart
            primaryActionAccessibilityLabel = "Start recording"
            primaryActionAccessibilityHint = startRequirements.blocker
                ?? "Starts the recording with the selected profile."
        }

        status = Self.makeStatus(
            workspaceState: workspaceState,
            trainingState: trainingState,
            roundAnalysisState: roundAnalysisState,
            startBlocker: startRequirements.blocker,
            elapsedSeconds: elapsedSeconds,
            uploadDetail: uploadDetail,
            uploadError: uploadError
        )
    }

    private static func makeStatus(
        workspaceState: RecordingWorkspaceState,
        trainingState: TrainingRecordingWorkflowState,
        roundAnalysisState: RoundAnalysisDisplayState,
        startBlocker: String?,
        elapsedSeconds: Double,
        uploadDetail: String?,
        uploadError: String?
    ) -> RecordingWorkspaceStatus {
        switch workspaceState {
        case .idle:
            return RecordingWorkspaceStatus(
                title: "Preparing recording workspace",
                detail: startBlocker,
                tone: .neutral
            )
        case .starting:
            return RecordingWorkspaceStatus(
                title: "Starting camera preview",
                detail: startBlocker,
                tone: .neutral
            )
        case .preview:
            if let startBlocker {
                return RecordingWorkspaceStatus(
                    title: "Not ready to record",
                    detail: startBlocker,
                    tone: .warning
                )
            }
            return RecordingWorkspaceStatus(
                title: "Ready to record",
                detail: "The camera and live detection are ready.",
                tone: .success
            )
        case .recording:
            let elapsed = formattedDuration(elapsedSeconds)
            return RecordingWorkspaceStatus(
                title: "Recording in progress",
                detail: "\(elapsed) elapsed",
                tone: .active
            )
        case .stopping:
            return RecordingWorkspaceStatus(
                title: "Finalizing recording",
                detail: "Closing evidence and saving the complete recording.",
                tone: .active
            )
        case .postRecording:
            return postRecordingStatus(
                trainingState: trainingState,
                roundAnalysisState: roundAnalysisState,
                uploadDetail: uploadDetail,
                uploadError: uploadError
            )
        case let .failed(message):
            return RecordingWorkspaceStatus(
                title: "Recording workspace needs attention",
                detail: message,
                tone: .failure
            )
        }
    }

    private static func postRecordingStatus(
        trainingState: TrainingRecordingWorkflowState,
        roundAnalysisState: RoundAnalysisDisplayState,
        uploadDetail: String?,
        uploadError: String?
    ) -> RecordingWorkspaceStatus {
        if let uploadError {
            return RecordingWorkspaceStatus(
                title: "Upload needs attention",
                detail: uploadError,
                tone: .failure
            )
        }

        switch trainingState {
        case .finalizing:
            return RecordingWorkspaceStatus(
                title: "Finalizing recording",
                detail: "Preparing the upload.",
                tone: .active
            )
        case .queued:
            return RecordingWorkspaceStatus(
                title: "Waiting to upload",
                detail: "The recording is saved locally.",
                tone: .neutral
            )
        case .uploading:
            return RecordingWorkspaceStatus(
                title: "Uploading recording",
                detail: uploadDetail ?? "Sending the recording to the backend.",
                tone: .active
            )
        case let .failed(message):
            return RecordingWorkspaceStatus(
                title: "Upload needs attention",
                detail: message,
                tone: .failure
            )
        case .acknowledged:
            return analysisStatus(roundAnalysisState)
        case .idle, .recording:
            return RecordingWorkspaceStatus(
                title: "Recording complete",
                detail: "The recording is available in the local queue.",
                tone: .success
            )
        }
    }

    private static func analysisStatus(
        _ state: RoundAnalysisDisplayState
    ) -> RecordingWorkspaceStatus {
        switch state {
        case .idle:
            return RecordingWorkspaceStatus(
                title: "Upload complete",
                detail: "Waiting to start analysis.",
                tone: .success
            )
        case .waitingForUploads:
            return RecordingWorkspaceStatus(
                title: "Waiting for evidence uploads",
                detail: "Analysis starts when all evidence is acknowledged.",
                tone: .neutral
            )
        case .queued:
            return RecordingWorkspaceStatus(
                title: "Analysis queued",
                detail: "The backend will analyze the recording.",
                tone: .neutral
            )
        case let .analyzingEvidence(completed, total):
            return RecordingWorkspaceStatus(
                title: "Analyzing evidence",
                detail: "Analyzed \(completed) of \(total) evidence packages.",
                tone: .active
            )
        case .reconstructing:
            return RecordingWorkspaceStatus(
                title: "Reconstructing round",
                detail: "The backend is building the round result.",
                tone: .active
            )
        case let .complete(summary):
            return RecordingWorkspaceStatus(
                title: "Analysis complete",
                detail: summary.text,
                tone: .success
            )
        case let .failed(message):
            return RecordingWorkspaceStatus(
                title: "Analysis needs attention",
                detail: message,
                tone: .failure
            )
        }
    }

    private static func formattedDuration(_ seconds: Double) -> String {
        let totalSeconds = max(0, Int(seconds.rounded(.down)))
        return String(format: "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }
}
