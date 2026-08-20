import CoreML
import Foundation

public final class CoreMLCardEventModelRunner: CardEventModelRunner {
    public let contract: ModelContract

    private let model: MLModel
    private var frames: [VideoFrame] = []

    public init(bundle: Bundle = .main, configuration: MLModelConfiguration = MLModelConfiguration()) throws {
        guard let modelURL = bundle.url(forResource: "CardEventNet", withExtension: "mlmodelc") else {
            throw CardEventModelRunnerError.modelResourceMissing
        }
        try self.init(modelURL: modelURL, configuration: configuration)
    }

    public init(modelURL: URL, configuration: MLModelConfiguration = MLModelConfiguration()) throws {
        model = try MLModel(contentsOf: modelURL, configuration: configuration)
        contract = ModelContract(model: model)
    }

    public func reset() {
        frames.removeAll(keepingCapacity: true)
    }

    public func consume(_ frame: VideoFrame) throws -> ModelPrediction? {
        frames.append(frame)
        if frames.count > 8 {
            frames.removeFirst(frames.count - 8)
        }

        guard frames.count == 8 else { return nil }

        throw CardEventModelRunnerError.unsupportedPreprocessing(
            "CardEventNet needs the annotated table ROI and its exact crop/letterbox preprocessing before inference can run."
        )
    }
}
