import Foundation

public enum ModelPreprocessingError: LocalizedError, Equatable {
    case invalidFrameSize
    case invalidTargetSize

    public var errorDescription: String? {
        switch self {
        case .invalidFrameSize:
            return "The source frame size must be positive."
        case .invalidTargetSize:
            return "The model target size must be positive."
        }
    }
}

public struct LetterboxGeometry: Equatable, Sendable {
    public let sourceWidth: Int
    public let sourceHeight: Int
    public let targetSize: Int
    public let resizedWidth: Int
    public let resizedHeight: Int
    public let xOffset: Int
    public let yOffset: Int

    public init(sourceWidth: Int, sourceHeight: Int, targetSize: Int) throws {
        guard sourceWidth > 0, sourceHeight > 0 else {
            throw ModelPreprocessingError.invalidFrameSize
        }
        guard targetSize > 0 else {
            throw ModelPreprocessingError.invalidTargetSize
        }

        let scale = min(
            Double(targetSize) / Double(sourceWidth),
            Double(targetSize) / Double(sourceHeight)
        )
        self.sourceWidth = sourceWidth
        self.sourceHeight = sourceHeight
        resizedWidth = max(1, Int((Double(sourceWidth) * scale).rounded(.toNearestOrEven)))
        resizedHeight = max(1, Int((Double(sourceHeight) * scale).rounded(.toNearestOrEven)))
        self.targetSize = targetSize
        xOffset = (targetSize - resizedWidth) / 2
        yOffset = (targetSize - resizedHeight) / 2
    }
}
