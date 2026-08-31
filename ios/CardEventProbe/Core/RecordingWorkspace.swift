import Foundation

/// The operator-facing lifecycle for the single recording workspace.
public enum RecordingWorkspaceState: Equatable, Sendable {
    case idle
    case starting
    case preview
    case recording(String)
    case stopping(String)
    case postRecording(String)
    case failed(String)

    public var title: String {
        switch self {
        case .idle:
            return "Idle"
        case .starting:
            return "Starting preview"
        case .preview:
            return "Preview"
        case .recording:
            return "Recording"
        case .stopping:
            return "Stopping"
        case .postRecording:
            return "Post-recording"
        case .failed:
            return "Failed"
        }
    }

    public var recordingID: String? {
        switch self {
        case let .recording(recordingID), let .stopping(recordingID), let .postRecording(recordingID):
            return recordingID
        case .idle, .starting, .preview, .failed:
            return nil
        }
    }

    public var isRecording: Bool {
        switch self {
        case .recording, .stopping:
            return true
        case .idle, .starting, .preview, .postRecording, .failed:
            return false
        }
    }

    public var acceptsRecordingStart: Bool {
        switch self {
        case .preview, .postRecording:
            return true
        case .idle, .starting, .recording, .stopping, .failed:
            return false
        }
    }
}

/// A small, side-effect-free state machine for the workspace lifecycle.
///
/// Services such as the camera, inference coordinator, and recorder are owned by the app layer.
/// This type keeps their externally visible transitions consistent and makes repeated Start or
/// Stop requests safe.
public struct RecordingWorkspaceLifecycle: Equatable, Sendable {
    public private(set) var state: RecordingWorkspaceState

    public init(state: RecordingWorkspaceState = .idle) {
        self.state = state
    }

    @discardableResult
    public mutating func startPreview() -> Bool {
        switch state {
        case .idle, .postRecording, .failed:
            state = .starting
            return true
        case .starting, .preview:
            return false
        case .recording, .stopping:
            return false
        }
    }

    @discardableResult
    public mutating func markPreviewReady() -> Bool {
        guard state == .starting else { return false }
        state = .preview
        return true
    }

    @discardableResult
    public mutating func startRecording(recordingID: String) -> Bool {
        guard !recordingID.isEmpty, state.acceptsRecordingStart else { return false }
        state = .recording(recordingID)
        return true
    }

    /// Begins Stop once. A repeated Stop is an idempotent no-op.
    @discardableResult
    public mutating func stopRecording() -> Bool {
        switch state {
        case let .recording(recordingID):
            state = .stopping(recordingID)
            return true
        case .stopping:
            return false
        case .idle, .starting, .preview, .postRecording, .failed:
            return false
        }
    }

    @discardableResult
    public mutating func finishRecording() -> Bool {
        guard let recordingID = state.recordingID else { return false }
        guard case .stopping = state else { return false }
        state = .postRecording(recordingID)
        return true
    }

    @discardableResult
    public mutating func fail(_ message: String) -> Bool {
        guard !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return false
        }
        state = .failed(message)
        return true
    }

    /// Restores a finalized or queued recording after relaunch.
    @discardableResult
    public mutating func recoverPostRecording(recordingID: String) -> Bool {
        guard !recordingID.isEmpty else { return false }
        state = .postRecording(recordingID)
        return true
    }

    /// Marks an interrupted active recording as recoverable failure after relaunch.
    @discardableResult
    public mutating func recoverInterruptedRecording(recordingID: String) -> Bool {
        guard !recordingID.isEmpty else { return false }
        state = .failed("Recording \(recordingID) was interrupted before finalization.")
        return true
    }

    @discardableResult
    public mutating func stopPreview() -> Bool {
        switch state {
        case .starting, .preview, .postRecording, .failed:
            state = .idle
            return true
        case .idle, .recording, .stopping:
            return false
        }
    }
}
