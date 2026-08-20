import CoreMedia

public protocol CardEventModelRunner: AnyObject {
    var contract: ModelContract { get }

    func reset()
    func consume(_ frame: VideoFrame) throws -> ModelPrediction?
}

public enum CardEventModelRunnerError: LocalizedError {
    case modelResourceMissing
    case modelContractInvalid(String)
    case roiNotConfigured
    case inferenceOutputMissing(String)

    public var errorDescription: String? {
        switch self {
        case .modelResourceMissing:
            return "CardEventNet.mlpackage is not in the application bundle."
        case let .modelContractInvalid(message):
            return "The CardEventNet model contract is invalid: \(message)"
        case .roiNotConfigured:
            return "The table ROI is not configured. Set an explicit normalized ROI before inference."
        case let .inferenceOutputMissing(name):
            return "The CardEventNet prediction did not contain the '\(name)' output."
        }
    }
}
