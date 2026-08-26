import CoreMedia

public protocol CardEventModelRunner: AnyObject {
    var contract: ModelContract { get }

    func reset()
    func consume(_ frame: VideoFrame) throws -> ModelPrediction?
}

public enum CardEventModelRunnerError: LocalizedError {
    case modelResourceMissing
    case modelContractInvalid(String)
    case inferenceOutputMissing(String)

    public var errorDescription: String? {
        switch self {
        case .modelResourceMissing:
            return "CardEventNetTransitionV2.mlpackage is not in the application bundle."
        case let .modelContractInvalid(message):
            return "The CardEventNet model contract is invalid: \(message)"
        case let .inferenceOutputMissing(name):
            return "The CardEventNet prediction did not contain the '\(name)' output."
        }
    }
}
