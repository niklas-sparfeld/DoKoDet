import Foundation

public enum ModelPreprocessingError: LocalizedError, Equatable {
    case invalidROI
    case invalidFrameSize
    case invalidTargetSize

    public var errorDescription: String? {
        switch self {
        case .invalidROI:
            return "The table ROI must be finite, positive, and inside the frame."
        case .invalidFrameSize:
            return "The source frame size must be positive."
        case .invalidTargetSize:
            return "The model target size must be positive."
        }
    }
}

/// A table ROI in the oriented video-frame coordinate space.
public struct NormalizedROI: Equatable, Sendable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) throws {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        guard isValid else {
            throw ModelPreprocessingError.invalidROI
        }
    }

    public var isValid: Bool {
        let values = [x, y, width, height]
        return values.allSatisfy { $0.isFinite }
            && x >= 0.0
            && y >= 0.0
            && width > 0.0
            && height > 0.0
            && x + width <= 1.0
            && y + height <= 1.0
    }

    public func pixelCrop(frameWidth: Int, frameHeight: Int) throws -> PixelCrop {
        guard frameWidth > 0, frameHeight > 0 else {
            throw ModelPreprocessingError.invalidFrameSize
        }
        guard isValid else {
            throw ModelPreprocessingError.invalidROI
        }

        let x1 = max(0, min(Int(floor(x * Double(frameWidth))), frameWidth - 1))
        let y1 = max(0, min(Int(floor(y * Double(frameHeight))), frameHeight - 1))
        let x2 = max(x1 + 1, min(Int(ceil((x + width) * Double(frameWidth))), frameWidth))
        let y2 = max(y1 + 1, min(Int(ceil((y + height) * Double(frameHeight))), frameHeight))
        return PixelCrop(x: x1, y: y1, width: x2 - x1, height: y2 - y1)
    }
}

public struct PixelCrop: Equatable, Sendable {
    public let x: Int
    public let y: Int
    public let width: Int
    public let height: Int

    public init(x: Int, y: Int, width: Int, height: Int) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }
}

public struct LetterboxGeometry: Equatable, Sendable {
    public let targetSize: Int
    public let resizedWidth: Int
    public let resizedHeight: Int
    public let xOffset: Int
    public let yOffset: Int

    public init(crop: PixelCrop, targetSize: Int) throws {
        guard crop.width > 0, crop.height > 0 else {
            throw ModelPreprocessingError.invalidFrameSize
        }
        guard targetSize > 0 else {
            throw ModelPreprocessingError.invalidTargetSize
        }

        let scale = min(
            Double(targetSize) / Double(crop.width),
            Double(targetSize) / Double(crop.height)
        )
        resizedWidth = max(1, Int((Double(crop.width) * scale).rounded()))
        resizedHeight = max(1, Int((Double(crop.height) * scale).rounded()))
        self.targetSize = targetSize
        xOffset = (targetSize - resizedWidth) / 2
        yOffset = (targetSize - resizedHeight) / 2
    }
}
