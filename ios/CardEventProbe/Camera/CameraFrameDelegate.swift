import AVFoundation
import ImageIO

final class CameraFrameDelegate: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    var onFrame: ((VideoFrame) -> Void)?
    var orientation: CGImagePropertyOrientation = .up

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let timestamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        onFrame?(
            VideoFrame(
                pixelBuffer: pixelBuffer,
                timestamp: timestamp,
                orientation: orientation
            )
        )
    }
}
