import CoreMedia
import CoreVideo
import ImageIO

public struct VideoFrame: @unchecked Sendable {
    public let pixelBuffer: CVPixelBuffer
    public let timestamp: CMTime
    public let orientation: CGImagePropertyOrientation

    public init(
        pixelBuffer: CVPixelBuffer,
        timestamp: CMTime,
        orientation: CGImagePropertyOrientation
    ) {
        self.pixelBuffer = pixelBuffer
        self.timestamp = timestamp
        self.orientation = orientation
    }
}
