import AVFoundation
import Combine
import Foundation

@MainActor
final class CameraSession: ObservableObject {
    enum State: Equatable {
        case idle
        case requestingPermission
        case running
        case denied
        case failed(String)

        var message: String {
            switch self {
            case .idle: return "Camera is idle"
            case .requestingPermission: return "Requesting camera access…"
            case .running: return "Camera running"
            case .denied: return "Camera access is denied. Enable it in Settings."
            case let .failed(message): return message
            }
        }
    }

    @Published private(set) var state: State = .idle
    let captureSession = AVCaptureSession()

    private let sessionQueue = DispatchQueue(label: "com.dokodetector.CardEventProbe.camera")
    private var isConfigured = false

    func start() {
        guard state != .running, state != .requestingPermission else { return }

        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureAndStart()
        case .notDetermined:
            state = .requestingPermission
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                Task { @MainActor in
                    guard let self else { return }
                    if granted {
                        self.configureAndStart()
                    } else {
                        self.state = .denied
                    }
                }
            }
        case .denied, .restricted:
            state = .denied
        @unknown default:
            state = .failed("The camera authorization state is unknown.")
        }
    }

    func stop() {
        guard state == .running else { return }
        sessionQueue.async { [weak self] in
            self?.captureSession.stopRunning()
        }
        state = .idle
    }

    private func configureAndStart() {
        sessionQueue.async { [weak self] in
            guard let self else { return }

            do {
                if !self.isConfigured {
                    try self.configureSession()
                    self.isConfigured = true
                }
                self.captureSession.startRunning()
                Task { @MainActor in
                    self.state = .running
                }
            } catch {
                Task { @MainActor in
                    self.state = .failed(error.localizedDescription)
                }
            }
        }
    }

    private func configureSession() throws {
        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            throw CameraError.unavailable
        }

        let input = try AVCaptureDeviceInput(device: camera)

        captureSession.beginConfiguration()
        defer { captureSession.commitConfiguration() }
        captureSession.sessionPreset = captureSession.canSetSessionPreset(.hd1920x1080) ? .hd1920x1080 : .hd1280x720

        guard captureSession.canAddInput(input) else { throw CameraError.cannotAddInput }
        captureSession.addInput(input)
    }
}

private enum CameraError: LocalizedError {
    case unavailable
    case cannotAddInput

    var errorDescription: String? {
        switch self {
        case .unavailable: return "No rear camera is available on this device."
        case .cannotAddInput: return "The camera input could not be added."
        }
    }
}
