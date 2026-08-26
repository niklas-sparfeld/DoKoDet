import CoreMedia
import CoreVideo

public protocol CardEventModelRunner: AnyObject {
    var contract: ModelContract { get }

    func reset()
    func consume(_ frame: VideoFrame) throws -> ModelPrediction?
}

public enum CardEventModelRunnerError: LocalizedError {
    case modelResourceMissing
    case modelContractInvalid(String)
    case inferenceOutputMissing(String)
    case cannotCopyCameraBuffer(CVReturn)

    public var errorDescription: String? {
        switch self {
        case .modelResourceMissing:
            return "CardEventNetTransitionV2.mlpackage is not in the application bundle."
        case let .modelContractInvalid(message):
            return "The CardEventNet model contract is invalid: \(message)"
        case let .inferenceOutputMissing(name):
            return "The CardEventNet prediction did not contain the '\(name)' output."
        case let .cannotCopyCameraBuffer(status):
            return "The camera frame could not be copied for temporal inference (status \(status))."
        }
    }
}
