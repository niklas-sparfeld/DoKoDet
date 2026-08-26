import CoreML
import CoreMedia
import Foundation

public final class CoreMLCardEventModelRunner: CardEventModelRunner {
    public let contract: ModelContract

    private let model: MLModel
    private var frames: [VideoFrame] = []
    private let temporalOffsets: [Double] = [-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0]
    private let historyDuration: Double = 2.0

    public convenience init(
        bundle: Bundle = .main,
        configuration: MLModelConfiguration = MLModelConfiguration()
    ) throws {
        guard let modelURL = bundle.url(
            forResource: "CardEventNetTransitionV2",
            withExtension: "mlmodelc"
        ) else {
            throw CardEventModelRunnerError.modelResourceMissing
        }
        try self.init(modelURL: modelURL, configuration: configuration)
    }

    public init(
        modelURL: URL,
        configuration: MLModelConfiguration = MLModelConfiguration()
    ) throws {
        model = try MLModel(contentsOf: modelURL, configuration: configuration)
        contract = ModelContract(model: model)
        try Self.validateContract(contract)
    }

    public func reset() {
        frames.removeAll(keepingCapacity: true)
    }

    public func consume(_ frame: VideoFrame) throws -> ModelPrediction? {
        let timestamp = CMTimeGetSeconds(frame.timestamp)
        guard timestamp.isFinite else {
            throw CardEventModelRunnerError.modelContractInvalid(
                "Video frame timestamps must be finite."
            )
        }
        if let previous = frames.last,
           CMTimeGetSeconds(previous.timestamp) > timestamp + 1e-9 {
            reset()
        }
        frames.append(frame)
        let cutoff = timestamp - historyDuration
        frames.removeAll { CMTimeGetSeconds($0.timestamp) < cutoff }

        let clip = selectClip(endingAt: timestamp)
        let input = try CardEventTensorBuilder.makeInput(frames: clip)
        let inputName = contract.inputFeatures[0].name
        let outputName = contract.outputFeatures[0].name
        let feature = MLFeatureValue(multiArray: input)
        let provider = try MLDictionaryFeatureProvider(dictionary: [inputName: feature])

        let start = DispatchTime.now().uptimeNanoseconds
        let output = try model.prediction(from: provider)
        let end = DispatchTime.now().uptimeNanoseconds

        guard let logitArray = output.featureValue(for: outputName)?.multiArrayValue,
              logitArray.count == 1 else {
            throw CardEventModelRunnerError.inferenceOutputMissing(outputName)
        }
        let logit = logitArray[0].doubleValue
        let probability = Self.sigmoid(logit)
        let durationMs = Double(end - start) / 1_000_000.0

        return ModelPrediction(
            timestamp: frame.timestamp,
            cardEventProbability: probability,
            rawOutputs: [outputName: logit],
            inferenceDurationMs: durationMs
        )
    }

    private func selectClip(endingAt timestamp: Double) -> [VideoFrame] {
        let eligible = frames.filter { CMTimeGetSeconds($0.timestamp) <= timestamp + 1e-9 }
        guard let first = eligible.first else {
            preconditionFailure("consume(_:) must append a frame before selecting a clip")
        }

        return temporalOffsets.map { offset in
            let target = timestamp + offset
            var selected = first
            var selectedTime = CMTimeGetSeconds(first.timestamp)
            var selectedDistance = abs(selectedTime - target)

            for candidate in eligible.dropFirst() {
                let candidateTime = CMTimeGetSeconds(candidate.timestamp)
                let candidateDistance = abs(candidateTime - target)
                if candidateDistance < selectedDistance {
                    selected = candidate
                    selectedTime = candidateTime
                    selectedDistance = candidateDistance
                }
            }
            return selected
        }
    }

    private static func validateContract(_ contract: ModelContract) throws {
        guard contract.inputFeatures.count == 1,
              let input = contract.inputFeatures.first,
              input.name == "clips",
              input.type == "multiArray",
              input.multiArrayShape == [1, 8, 3, 224, 224],
              input.multiArrayDataType == "float32" else {
            throw CardEventModelRunnerError.modelContractInvalid(
                "expected one float32 multi-array input named clips with shape [1, 8, 3, 224, 224]."
            )
        }

        guard contract.outputFeatures.count == 1,
              let output = contract.outputFeatures.first,
              output.name == "logit",
              output.type == "multiArray",
              output.multiArrayShape == [1],
              output.multiArrayDataType == "float32" else {
            throw CardEventModelRunnerError.modelContractInvalid(
                "expected one float32 multi-array output named logit with shape [1]."
            )
        }
    }

    private static func sigmoid(_ value: Double) -> Double {
        if value >= 0.0 {
            let exponent = exp(-value)
            return 1.0 / (1.0 + exponent)
        }
        let exponent = exp(value)
        return exponent / (1.0 + exponent)
    }
}
