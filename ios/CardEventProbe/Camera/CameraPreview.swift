import AVFoundation
import SwiftUI
import UIKit

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    let onOrientationChange: (UIInterfaceOrientation) -> Void

    func makeUIView(context: Context) -> PreviewView {
        PreviewView(session: session, onOrientationChange: onOrientationChange)
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        uiView.previewLayer.session = session
        uiView.onOrientationChange = onOrientationChange
    }
}

final class PreviewView: UIView {
    override class var layerClass: AnyClass {
        AVCaptureVideoPreviewLayer.self
    }

    var previewLayer: AVCaptureVideoPreviewLayer {
        guard let layer = layer as? AVCaptureVideoPreviewLayer else {
            preconditionFailure("PreviewView must use AVCaptureVideoPreviewLayer")
        }
        return layer
    }

    var onOrientationChange: (UIInterfaceOrientation) -> Void
    private var lastInterfaceOrientation: UIInterfaceOrientation?

    init(
        session: AVCaptureSession,
        onOrientationChange: @escaping (UIInterfaceOrientation) -> Void
    ) {
        self.onOrientationChange = onOrientationChange
        super.init(frame: .zero)
        previewLayer.session = session
        previewLayer.videoGravity = .resizeAspectFill
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        updateVideoOrientation()
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        updateVideoOrientation()
    }

    private func updateVideoOrientation() {
        guard let interfaceOrientation = window?.windowScene?.interfaceOrientation,
              let rotationAngle = CameraOrientation.rotationAngle(for: interfaceOrientation),
              let connection = previewLayer.connection,
              connection.isVideoRotationAngleSupported(rotationAngle) else { return }

        connection.videoRotationAngle = rotationAngle
        guard lastInterfaceOrientation != interfaceOrientation else { return }
        lastInterfaceOrientation = interfaceOrientation
        onOrientationChange(interfaceOrientation)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("PreviewView does not support storyboards")
    }
}
