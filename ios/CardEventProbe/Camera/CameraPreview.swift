import AVFoundation
import SwiftUI
import UIKit

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewView {
        PreviewView(session: session)
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        uiView.previewLayer.session = session
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

    init(session: AVCaptureSession) {
        super.init(frame: .zero)
        previewLayer.session = session
        previewLayer.videoGravity = .resizeAspectFill
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        let portraitAngle: CGFloat = 90.0
        if let connection = previewLayer.connection,
           connection.isVideoRotationAngleSupported(portraitAngle) {
            connection.videoRotationAngle = portraitAngle
        }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("PreviewView does not support storyboards")
    }
}
