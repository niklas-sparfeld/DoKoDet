import CoreML
import Foundation

public struct ModelFeatureContract {
    public let name: String
    public let type: String
    public let imageWidth: Int?
    public let imageHeight: Int?
    public let imagePixelFormat: String?
    public let multiArrayShape: [Int]?
    public let multiArrayDataType: String?
    public let isOptional: Bool

    public init(
        name: String,
        type: String,
        imageWidth: Int? = nil,
        imageHeight: Int? = nil,
        imagePixelFormat: String? = nil,
        multiArrayShape: [Int]? = nil,
        multiArrayDataType: String? = nil,
        isOptional: Bool = false
    ) {
        self.name = name
        self.type = type
        self.imageWidth = imageWidth
        self.imageHeight = imageHeight
        self.imagePixelFormat = imagePixelFormat
        self.multiArrayShape = multiArrayShape
        self.multiArrayDataType = multiArrayDataType
        self.isOptional = isOptional
    }

    public var summary: String {
        var parts = ["\(name): \(type)"]
        if let multiArrayShape {
            parts.append("shape \(multiArrayShape)")
        }
        if let multiArrayDataType {
            parts.append("\(multiArrayDataType)")
        }
        if let imageWidth, let imageHeight {
            parts.append("size \(imageWidth)x\(imageHeight)")
        }
        if let imagePixelFormat {
            parts.append("pixel format \(imagePixelFormat)")
        }
        if isOptional {
            parts.append("optional")
        }
        return parts.joined(separator: ", ")
    }
}

public struct ModelContract {
    public let inputFeatures: [ModelFeatureContract]
    public let outputFeatures: [ModelFeatureContract]
    public let metadata: [String: String]
    public let predictedFeatureName: String?
    public let predictedProbabilitiesName: String?

    public init(
        inputFeatures: [ModelFeatureContract],
        outputFeatures: [ModelFeatureContract],
        metadata: [String: String],
        predictedFeatureName: String? = nil,
        predictedProbabilitiesName: String? = nil
    ) {
        self.inputFeatures = inputFeatures
        self.outputFeatures = outputFeatures
        self.metadata = metadata
        self.predictedFeatureName = predictedFeatureName
        self.predictedProbabilitiesName = predictedProbabilitiesName
    }

    public init(model: MLModel) {
        let description = model.modelDescription
        inputFeatures = Self.features(from: description.inputDescriptionsByName)
        outputFeatures = Self.features(from: description.outputDescriptionsByName)
        metadata = description.metadata.reduce(into: [:]) { result, entry in
            result[entry.key.rawValue] = String(describing: entry.value)
        }
        predictedFeatureName = description.predictedFeatureName
        predictedProbabilitiesName = description.predictedProbabilitiesName
    }

    public var imageInput: ModelFeatureContract? {
        inputFeatures.first { $0.imageWidth != nil }
    }

    public var multiArrayInputs: [ModelFeatureContract] {
        inputFeatures.filter { $0.multiArrayShape != nil }
    }

    public var probabilityDictionaryFeature: ModelFeatureContract? {
        outputFeatures.first { $0.type == "dictionary" }
    }

    public var summary: String {
        var lines = ["Inputs:"]
        lines.append(contentsOf: inputFeatures.map { "- \($0.summary)" })
        lines.append("Outputs:")
        lines.append(contentsOf: outputFeatures.map { "- \($0.summary)" })
        if let predictedFeatureName {
            lines.append("Predicted label: \(predictedFeatureName)")
        }
        if let predictedProbabilitiesName {
            lines.append("Predicted probabilities: \(predictedProbabilitiesName)")
        }
        if !metadata.isEmpty {
            lines.append("Metadata:")
            lines.append(contentsOf: metadata.keys.sorted().compactMap { key in
                guard let value = metadata[key] else { return nil }
                return "- \(key): \(value)"
            })
        }
        return lines.joined(separator: "\n")
    }

    private static func features(
        from descriptions: [String: MLFeatureDescription]
    ) -> [ModelFeatureContract] {
        descriptions.keys.sorted().compactMap { name in
            guard let description = descriptions[name] else { return nil }
            let imageConstraint = description.imageConstraint
            let multiArrayConstraint = description.multiArrayConstraint

            return ModelFeatureContract(
                name: name,
                type: featureTypeName(description.type),
                imageWidth: imageConstraint?.pixelsWide,
                imageHeight: imageConstraint?.pixelsHigh,
                imagePixelFormat: imageConstraint.map {
                    String(format: "0x%08X", $0.pixelFormatType)
                },
                multiArrayShape: multiArrayConstraint?.shape.map(\.intValue),
                multiArrayDataType: multiArrayConstraint.map {
                    multiArrayDataTypeName($0.dataType)
                },
                isOptional: description.isOptional
            )
        }
    }

    private static func featureTypeName(_ type: MLFeatureType) -> String {
        switch type {
        case .invalid: return "invalid"
        case .int64: return "int64"
        case .double: return "double"
        case .string: return "string"
        case .image: return "image"
        case .multiArray: return "multiArray"
        case .dictionary: return "dictionary"
        case .sequence: return "sequence"
        case .state: return "state"
        @unknown default: return "unknown(\(type.rawValue))"
        }
    }

    private static func multiArrayDataTypeName(_ type: MLMultiArrayDataType) -> String {
        switch type {
        case .double: return "float64"
        case .float32: return "float32"
        case .float16: return "float16"
        case .int32: return "int32"
        @unknown default: return "unknown(\(type.rawValue))"
        }
    }
}
