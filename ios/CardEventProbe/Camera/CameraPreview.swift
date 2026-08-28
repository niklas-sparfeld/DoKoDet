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
    let previewLayer: AVCaptureVideoPreviewLayer

    var onOrientationChange: (UIInterfaceOrientation) -> Void
    private var lastInterfaceOrientation: UIInterfaceOrientation?
    private var portraitPreviewSize: CGSize?

    init(
        session: AVCaptureSession,
        onOrientationChange: @escaping (UIInterfaceOrientation) -> Void
    ) {
        previewLayer = AVCaptureVideoPreviewLayer(session: session)
        self.onOrientationChange = onOrientationChange
        super.init(frame: .zero)
        backgroundColor = .black
        layer.addSublayer(previewLayer)
        previewLayer.videoGravity = .resizeAspectFill
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        layoutPreviewLayer()
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

    private func layoutPreviewLayer() {
        guard let interfaceOrientation = window?.windowScene?.interfaceOrientation else {
            previewLayer.frame = bounds
            return
        }

        if interfaceOrientation.isPortrait {
            portraitPreviewSize = bounds.size
            previewLayer.frame = bounds
            return
        }

        let size = portraitPreviewSize ?? bounds.size
        previewLayer.frame = CGRect(
            x: (bounds.width - size.width) / 2,
            y: (bounds.height - size.height) / 2,
            width: size.width,
            height: size.height
        )
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("PreviewView does not support storyboards")
    }
}
