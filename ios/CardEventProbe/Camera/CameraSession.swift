import AVFoundation
import Combine
import Foundation
import os
import UIKit

enum CameraOrientation {
    static func rotationAngle(for interfaceOrientation: UIInterfaceOrientation) -> CGFloat? {
        switch interfaceOrientation {
        case .portrait:
            return 90.0
        case .portraitUpsideDown:
            return 270.0
        case .landscapeLeft:
            return 180.0
        case .landscapeRight:
            return 0.0
        default:
            return nil
        }
    }
}

@MainActor
final class CameraSession: ObservableObject {
    private static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.dokodetector.CardEventProbe",
        category: "Camera"
    )

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
    private let videoOutput = AVCaptureVideoDataOutput()
    private let frameDelegate = CameraFrameDelegate()
    private var requestedRotationAngle: CGFloat = 90.0
    private var isConfigured = false

    func setFrameHandler(_ handler: ((VideoFrame) -> Void)?) {
        frameDelegate.onFrame = handler
    }

    func updateInterfaceOrientation(_ orientation: UIInterfaceOrientation) {
        guard let rotationAngle = CameraOrientation.rotationAngle(for: orientation) else { return }
        requestedRotationAngle = rotationAngle
        sessionQueue.async { [weak self] in
            self?.applyRotationAngle(rotationAngle)
        }
    }

    func start() {
        guard state != .running, state != .requestingPermission else { return }
        Self.logger.info("Camera start requested.")

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
        Self.logger.info("Camera stop requested.")
        sessionQueue.async { [weak self] in
            self?.captureSession.stopRunning()
        }
        state = .idle
    }

    private func configureAndStart() {
        let rotationAngle = requestedRotationAngle
        sessionQueue.async { [weak self] in
            guard let self else { return }

            do {
                if !self.isConfigured {
                    try self.configureSession(rotationAngle: rotationAngle)
                    self.isConfigured = true
                }
                self.captureSession.startRunning()
                Self.logger.info("Camera session is running.")
                Task { @MainActor in
                    self.state = .running
                }
            } catch {
                Self.logger.error("Camera setup failed: \(error.localizedDescription, privacy: .public)")
                Task { @MainActor in
                    self.state = .failed(error.localizedDescription)
                }
            }
        }
    }

    private func configureSession(rotationAngle: CGFloat) throws {
        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            throw CameraError.unavailable
        }

        let input = try AVCaptureDeviceInput(device: camera)

        captureSession.beginConfiguration()
        defer { captureSession.commitConfiguration() }
        captureSession.sessionPreset = captureSession.canSetSessionPreset(.hd1920x1080) ? .hd1920x1080 : .hd1280x720

        guard captureSession.canAddInput(input) else { throw CameraError.cannotAddInput }
        captureSession.addInput(input)

        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        ]
        guard captureSession.canAddOutput(videoOutput) else { throw CameraError.cannotAddOutput }
        captureSession.addOutput(videoOutput)
        videoOutput.setSampleBufferDelegate(frameDelegate, queue: sessionQueue)

        if let connection = videoOutput.connection(with: .video) {
            applyRotationAngle(rotationAngle, to: connection)
        }
    }

    private func applyRotationAngle(_ rotationAngle: CGFloat) {
        guard isConfigured,
              let connection = videoOutput.connection(with: .video) else { return }
        applyRotationAngle(rotationAngle, to: connection)
    }

    private func applyRotationAngle(_ rotationAngle: CGFloat, to connection: AVCaptureConnection) {
        guard connection.isVideoRotationAngleSupported(rotationAngle) else {
            Self.logger.warning("Camera rotation angle is not supported: \(rotationAngle, privacy: .public)")
            return
        }
        connection.videoRotationAngle = rotationAngle
        frameDelegate.orientation = .up
    }
}

private enum CameraError: LocalizedError {
    case unavailable
    case cannotAddInput
    case cannotAddOutput

    var errorDescription: String? {
        switch self {
        case .unavailable: return "No rear camera is available on this device."
        case .cannotAddInput: return "The camera input could not be added."
        case .cannotAddOutput: return "The camera video output could not be added."
        }
    }
}
