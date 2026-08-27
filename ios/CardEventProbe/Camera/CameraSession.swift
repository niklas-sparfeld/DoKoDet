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
    @Published private(set) var sourceRateStatus: CameraSourceRateStatus?
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
        let existingSourceRateStatus = sourceRateStatus
        sessionQueue.async { [weak self] in
            guard let self else { return }

            do {
                let sourceRateStatus: CameraSourceRateStatus
                if !self.isConfigured {
                    sourceRateStatus = try self.configureSession(rotationAngle: rotationAngle)
                    self.isConfigured = true
                } else if let existingSourceRateStatus {
                    sourceRateStatus = existingSourceRateStatus
                } else {
                    throw CameraError.sourceFrameRateUnavailable
                }
                self.captureSession.startRunning()
                Self.logger.info("Camera session is running.")
                Task { @MainActor in
                    self.state = .running
                    self.sourceRateStatus = sourceRateStatus
                }
            } catch {
                Self.logger.error("Camera setup failed: \(error.localizedDescription, privacy: .public)")
                Task { @MainActor in
                    self.state = .failed(error.localizedDescription)
                }
            }
        }
    }

    private func configureSession(rotationAngle: CGFloat) throws -> CameraSourceRateStatus {
        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            throw CameraError.unavailable
        }

        let input = try AVCaptureDeviceInput(device: camera)

        captureSession.beginConfiguration()
        defer { captureSession.commitConfiguration() }
        captureSession.sessionPreset = captureSession.canSetSessionPreset(.hd1920x1080) ? .hd1920x1080 : .hd1280x720

        guard captureSession.canAddInput(input) else { throw CameraError.cannotAddInput }
        captureSession.addInput(input)

        let sourceRateStatus = try configureSourceRate(for: camera)

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
        return sourceRateStatus
    }

    private func configureSourceRate(for camera: AVCaptureDevice) throws -> CameraSourceRateStatus {
        let ranges = camera.activeFormat.videoSupportedFrameRateRanges
        guard let maximumRange = ranges.max(by: { $0.maxFrameRate < $1.maxFrameRate }),
              let sourceRateStatus = CameraSourceRateStatus.select(
                  supportedMaximumFrameRate: maximumRange.maxFrameRate
              ),
              let selectedRange = ranges.first(where: {
                  $0.minFrameRate <= sourceRateStatus.selectedFrameRate
                      && $0.maxFrameRate >= sourceRateStatus.selectedFrameRate
              }) else {
            throw CameraError.sourceFrameRateUnavailable
        }

        let frameDuration = sourceRateStatus.isFallback
            ? selectedRange.minFrameDuration
            : CMTime(value: 1, timescale: 30)
        guard frameDuration.isValid, CMTimeGetSeconds(frameDuration).isFinite else {
            throw CameraError.sourceFrameRateUnavailable
        }

        do {
            try camera.lockForConfiguration()
            camera.activeVideoMinFrameDuration = frameDuration
            camera.activeVideoMaxFrameDuration = frameDuration
            camera.unlockForConfiguration()
        } catch {
            throw CameraError.sourceRateConfigurationFailed(error.localizedDescription)
        }
        Self.logger.info(
            "Camera source rate configured at \(sourceRateStatus.selectedFrameRate, privacy: .public) fps."
        )
        return sourceRateStatus
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
    case sourceFrameRateUnavailable
    case sourceRateConfigurationFailed(String)

    var errorDescription: String? {
        switch self {
        case .unavailable: return "No rear camera is available on this device."
        case .cannotAddInput: return "The camera input could not be added."
        case .cannotAddOutput: return "The camera video output could not be added."
        case .sourceFrameRateUnavailable:
            return "The camera does not report a supported source frame rate."
        case let .sourceRateConfigurationFailed(message):
            return "The camera source frame rate could not be configured: \(message)"
        }
    }
}
