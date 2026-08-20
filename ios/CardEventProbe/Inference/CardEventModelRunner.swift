import CoreMedia

public protocol CardEventModelRunner: AnyObject {
    var contract: ModelContract { get }

    func reset()
    func consume(_ frame: VideoFrame) throws -> ModelPrediction?
}

public enum CardEventModelRunnerError: LocalizedError {
    case modelResourceMissing
    case unsupportedPreprocessing(String)

    public var errorDescription: String? {
        switch self {
        case .modelResourceMissing:
            return "CardEventNet.mlpackage is not in the application bundle."
        case let .unsupportedPreprocessing(message):
            return message
        }
    }
}
