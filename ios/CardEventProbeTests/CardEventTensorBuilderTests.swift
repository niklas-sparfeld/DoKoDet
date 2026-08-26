import CoreMedia
import CoreML
import CoreVideo
import CryptoKit
import Foundation
import ImageIO
import XCTest
@testable import CardEventProbeCore

final class CardEventTensorBuilderTests: XCTestCase {
    private struct Fixture: Decodable {
        struct PythonReference: Decodable {
            let sha256: String
            let maximumAbsoluteTolerance: Double

            enum CodingKeys: String, CodingKey {
                case sha256
                case maximumAbsoluteTolerance = "maximum_absolute_tolerance"
            }
        }

        let sourceWidth: Int
        let sourceHeight: Int
        let pixelFormat: String
        let orientation: String
        let pixelsBGRA: [UInt8]
        let targetSize: Int
        let frameCount: Int
        let pythonReference: PythonReference

        enum CodingKeys: String, CodingKey {
            case sourceWidth = "source_width"
            case sourceHeight = "source_height"
            case pixelFormat = "pixel_format"
            case orientation
            case pixelsBGRA = "pixels_bgra"
            case targetSize = "target_size"
            case frameCount = "frame_count"
            case pythonReference = "python_reference"
        }
    }

    func testFullFrameTensorMatchesPythonReferenceDigest() throws {
        let fixture = try loadFixture()
        XCTAssertEqual(fixture.pixelFormat, "BGRA")
        XCTAssertEqual(fixture.orientation, "up")
        XCTAssertEqual(
            fixture.pixelsBGRA.count,
            fixture.sourceWidth * fixture.sourceHeight * 4
        )

        let pixelBuffer = try makePixelBuffer(
            width: fixture.sourceWidth,
            height: fixture.sourceHeight,
            pixelsBGRA: fixture.pixelsBGRA
        )
        let frames = (0..<fixture.frameCount).map { index in
            VideoFrame(
                pixelBuffer: pixelBuffer,
                timestamp: CMTime(value: Int64(index), timescale: 8),
                orientation: .up
            )
        }

        let tensor = try CardEventTensorBuilder.makeInput(frames: frames)

        XCTAssertEqual(tensor.shape.map(\.intValue), [1, 8, 3, fixture.targetSize, fixture.targetSize])
        XCTAssertEqual(tensor.dataType, .float32)

        let digest = SHA256.hash(
            data: Data(
                bytes: tensor.dataPointer,
                count: tensor.count * MemoryLayout<Float32>.size
            )
        )
        let digestString = digest.map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(digestString, fixture.pythonReference.sha256)
    }

    private func loadFixture() throws -> Fixture {
        guard let url = Bundle.module.url(
            forResource: "full_frame_letterbox_v1",
            withExtension: "json",
            subdirectory: "Fixtures"
        ) else {
            throw FixtureError.missing
        }
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
    }

    private func makePixelBuffer(
        width: Int,
        height: Int,
        pixelsBGRA: [UInt8]
    ) throws -> CVPixelBuffer {
        var pixelBuffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            nil,
            &pixelBuffer
        )
        guard status == kCVReturnSuccess, let pixelBuffer else {
            throw FixtureError.pixelBufferCreation(status)
        }

        let lockStatus = CVPixelBufferLockBaseAddress(pixelBuffer, [])
        guard lockStatus == kCVReturnSuccess,
              let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            throw FixtureError.pixelBufferLock(lockStatus)
        }
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        pixelsBGRA.withUnsafeBytes { source in
            guard let sourceBaseAddress = source.baseAddress else { return }
            for row in 0..<height {
                let destination = baseAddress.advanced(by: row * bytesPerRow)
                let source = sourceBaseAddress.advanced(by: row * width * 4)
                destination.copyMemory(from: source, byteCount: width * 4)
            }
        }
        return pixelBuffer
    }

    private enum FixtureError: Error {
        case missing
        case pixelBufferCreation(CVReturn)
        case pixelBufferLock(CVReturn)
    }
}
