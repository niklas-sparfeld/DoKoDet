import CoreImage
import CoreVideo
import Foundation
import ImageIO

enum DiagnosticFrameWriter {
    private static let context = CIContext()

    static func writeJPEG(pixelBuffer: CVPixelBuffer, to url: URL) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
        try context.writeJPEGRepresentation(
            of: image,
            to: url,
            colorSpace: colorSpace,
            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.9]
        )
    }
}
