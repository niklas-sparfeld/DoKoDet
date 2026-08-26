import CoreML
import CoreVideo
import Foundation
import ImageIO

enum CardEventTensorBuilderError: LocalizedError {
    case wrongFrameCount(expected: Int, actual: Int)
    case unsupportedPixelFormat(OSType)
    case pixelBufferLockFailed(CVReturn)
    case missingPixelBufferBaseAddress
    case invalidOrientation

    var errorDescription: String? {
        switch self {
        case let .wrongFrameCount(expected, actual):
            return "CardEventNet needs exactly \(expected) frames, but received \(actual)."
        case let .unsupportedPixelFormat(format):
            return String(format: "The camera pixel format 0x%08X is not supported. Use BGRA.", format)
        case let .pixelBufferLockFailed(status):
            return "The camera frame could not be locked (status \(status))."
        case .missingPixelBufferBaseAddress:
            return "The camera frame has no readable pixel buffer address."
        case .invalidOrientation:
            return "The camera frame has an unsupported orientation."
        }
    }
}

struct CardEventTensorBuilder {
    static let frameCount = 8
    static let targetSize = 224

    private static let means = (red: 0.485, green: 0.456, blue: 0.406)
    private static let standardDeviations = (red: 0.229, green: 0.224, blue: 0.225)

    static func makeInput(
        frames: [VideoFrame]
    ) throws -> MLMultiArray {
        guard frames.count == frameCount else {
            throw CardEventTensorBuilderError.wrongFrameCount(
                expected: frameCount,
                actual: frames.count
            )
        }

        let input = try MLMultiArray(
            shape: [1, frameCount, 3, targetSize, targetSize] as [NSNumber],
            dataType: .float32
        )
        let strides = input.strides.map(\.intValue)
        let output = input.dataPointer.assumingMemoryBound(to: Float32.self)

        for (time, frame) in frames.enumerated() {
            try fill(
                output: output,
                strides: strides,
                time: time,
                frame: frame
            )
        }
        return input
    }

    private static func fill(
        output: UnsafeMutablePointer<Float32>,
        strides: [Int],
        time: Int,
        frame: VideoFrame
    ) throws {
        let pixelBuffer = frame.pixelBuffer
        let pixelFormat = CVPixelBufferGetPixelFormatType(pixelBuffer)
        guard pixelFormat == kCVPixelFormatType_32BGRA else {
            throw CardEventTensorBuilderError.unsupportedPixelFormat(pixelFormat)
        }

        let lockStatus = CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        guard lockStatus == kCVReturnSuccess else {
            throw CardEventTensorBuilderError.pixelBufferLockFailed(lockStatus)
        }
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            throw CardEventTensorBuilderError.missingPixelBufferBaseAddress
        }

        let rawWidth = CVPixelBufferGetWidth(pixelBuffer)
        let rawHeight = CVPixelBufferGetHeight(pixelBuffer)
        let orientedSize = try OrientedSize(
            rawWidth: rawWidth,
            rawHeight: rawHeight,
            orientation: frame.orientation
        )
        let geometry = try LetterboxGeometry(
            sourceWidth: orientedSize.width,
            sourceHeight: orientedSize.height,
            targetSize: targetSize
        )
        let xWeights = AxisWeights(
            sourceCount: orientedSize.width,
            targetCount: geometry.resizedWidth
        )
        let yWeights = AxisWeights(
            sourceCount: orientedSize.height,
            targetCount: geometry.resizedHeight
        )
        let reader = BGRAReader(
            baseAddress: baseAddress.assumingMemoryBound(to: UInt8.self),
            bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
            rawWidth: rawWidth,
            rawHeight: rawHeight,
            orientation: frame.orientation
        )

        for y in 0..<targetSize {
            for x in 0..<targetSize {
                let arrayIndex = time * strides[1] + y * strides[3] + x * strides[4]
                guard x >= geometry.xOffset,
                      x < geometry.xOffset + geometry.resizedWidth,
                      y >= geometry.yOffset,
                      y < geometry.yOffset + geometry.resizedHeight else {
                    writeBlack(output, index: arrayIndex, channelStride: strides[2])
                    continue
                }

                let sourceX = xWeights.values[x - geometry.xOffset]
                let sourceY = yWeights.values[y - geometry.yOffset]
                var red = 0.0
                var green = 0.0
                var blue = 0.0

                for yWeight in sourceY {
                    for xWeight in sourceX {
                        let pixel = reader.rgb(
                            x: xWeight.index,
                            y: yWeight.index
                        )
                        let weight = xWeight.weight * yWeight.weight
                        red += pixel.red * weight
                        green += pixel.green * weight
                        blue += pixel.blue * weight
                    }
                }

                output[arrayIndex] = normalize(
                    red.rounded(.toNearestOrEven),
                    mean: means.red,
                    standardDeviation: standardDeviations.red
                )
                output[arrayIndex + strides[2]] = normalize(
                    green.rounded(.toNearestOrEven),
                    mean: means.green,
                    standardDeviation: standardDeviations.green
                )
                output[arrayIndex + 2 * strides[2]] = normalize(
                    blue.rounded(.toNearestOrEven),
                    mean: means.blue,
                    standardDeviation: standardDeviations.blue
                )
            }
        }
    }

    private static func writeBlack(
        _ output: UnsafeMutablePointer<Float32>,
        index: Int,
        channelStride: Int
    ) {
        output[index] = normalize(0.0, mean: means.red, standardDeviation: standardDeviations.red)
        output[index + channelStride] = normalize(
            0.0,
            mean: means.green,
            standardDeviation: standardDeviations.green
        )
        output[index + 2 * channelStride] = normalize(
            0.0,
            mean: means.blue,
            standardDeviation: standardDeviations.blue
        )
    }

    private static func normalize(
        _ value: Double,
        mean: Double,
        standardDeviation: Double
    ) -> Float32 {
        let value = Float32(value) / 255.0
        return (value - Float32(mean)) / Float32(standardDeviation)
    }
}

private struct RGB {
    let red: Double
    let green: Double
    let blue: Double
}

private struct OrientedSize {
    let width: Int
    let height: Int

    init(
        rawWidth: Int,
        rawHeight: Int,
        orientation: CGImagePropertyOrientation
    ) throws {
        guard rawWidth > 0, rawHeight > 0 else {
            throw ModelPreprocessingError.invalidFrameSize
        }

        switch orientation {
        case .left, .leftMirrored, .right, .rightMirrored:
            width = rawHeight
            height = rawWidth
        case .up, .upMirrored, .down, .downMirrored:
            width = rawWidth
            height = rawHeight
        @unknown default:
            throw CardEventTensorBuilderError.invalidOrientation
        }
    }
}

private struct BGRAReader {
    let baseAddress: UnsafePointer<UInt8>
    let bytesPerRow: Int
    let rawWidth: Int
    let rawHeight: Int
    let orientation: CGImagePropertyOrientation

    func rgb(x: Int, y: Int) -> RGB {
        let raw = rawCoordinate(orientedX: x, orientedY: y)
        let offset = raw.y * bytesPerRow + raw.x * 4
        return RGB(
            red: Double(baseAddress[offset + 2]),
            green: Double(baseAddress[offset + 1]),
            blue: Double(baseAddress[offset])
        )
    }

    private func rawCoordinate(orientedX: Int, orientedY: Int) -> (x: Int, y: Int) {
        switch orientation {
        case .up:
            return (orientedX, orientedY)
        case .upMirrored:
            return (rawWidth - 1 - orientedX, orientedY)
        case .down:
            return (rawWidth - 1 - orientedX, rawHeight - 1 - orientedY)
        case .downMirrored:
            return (orientedX, rawHeight - 1 - orientedY)
        case .leftMirrored:
            return (rawWidth - 1 - orientedY, rawHeight - 1 - orientedX)
        case .right:
            return (orientedY, rawHeight - 1 - orientedX)
        case .rightMirrored:
            return (orientedY, orientedX)
        case .left:
            return (rawWidth - 1 - orientedY, orientedX)
        @unknown default:
            return (orientedX, orientedY)
        }
    }
}

private struct WeightedIndex {
    let index: Int
    let weight: Double
}

private struct AxisWeights {
    let values: [[WeightedIndex]]

    init(sourceCount: Int, targetCount: Int) {
        values = (0..<targetCount).map { targetIndex in
            if targetCount >= sourceCount {
                let sourceIndex = min(
                    sourceCount - 1,
                    Int(Double(targetIndex) * Double(sourceCount) / Double(targetCount))
                )
                return [WeightedIndex(index: sourceIndex, weight: 1.0)]
            }

            let start = Double(targetIndex) * Double(sourceCount) / Double(targetCount)
            let end = Double(targetIndex + 1) * Double(sourceCount) / Double(targetCount)
            let first = max(0, Int(floor(start)))
            let last = min(sourceCount - 1, Int(ceil(end)) - 1)
            let width = end - start
            return (first...last).map { sourceIndex in
                let overlap = min(end, Double(sourceIndex + 1))
                    - max(start, Double(sourceIndex))
                return WeightedIndex(index: sourceIndex, weight: overlap / width)
            }
        }
    }
}
