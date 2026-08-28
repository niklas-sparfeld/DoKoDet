import Foundation

public struct TrainingRecordingModel: Codable, Equatable, Sendable {
    public let name: String
    public let version: String
    public let weightsSHA256: String
    public let preprocessing: String

    public init(name: String, version: String, weightsSHA256: String, preprocessing: String) {
        self.name = name
        self.version = version
        self.weightsSHA256 = weightsSHA256
        self.preprocessing = preprocessing
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        version = try container.decode(String.self, forKey: .version)
        weightsSHA256 = try container.decode(String.self, forKey: .weightsSHA256)
        preprocessing = try container.decode(String.self, forKey: .preprocessing)
        guard !name.isEmpty, !version.isEmpty, !preprocessing.isEmpty,
              isLowercaseSHA256(weightsSHA256) else {
            throw RepositoryIntakeContractError.invalid("model metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case name
        case version
        case weightsSHA256 = "weights_sha256"
        case preprocessing
    }
}

public struct TrainingRecordingDecoder: Codable, Equatable, Sendable {
    public let algorithm: String
    public let threshold: Double
    public let peakConfirmationS: Double
    public let minimumEventGapS: Double

    public init(
        algorithm: String,
        threshold: Double,
        peakConfirmationS: Double,
        minimumEventGapS: Double
    ) {
        self.algorithm = algorithm
        self.threshold = threshold
        self.peakConfirmationS = peakConfirmationS
        self.minimumEventGapS = minimumEventGapS
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        algorithm = try container.decode(String.self, forKey: .algorithm)
        threshold = try container.decode(Double.self, forKey: .threshold)
        peakConfirmationS = try container.decode(Double.self, forKey: .peakConfirmationS)
        minimumEventGapS = try container.decode(Double.self, forKey: .minimumEventGapS)
        guard !algorithm.isEmpty, threshold.isFinite, (0.0...1.0).contains(threshold),
              peakConfirmationS.isFinite, peakConfirmationS >= 0,
              minimumEventGapS.isFinite, minimumEventGapS >= 0 else {
            throw RepositoryIntakeContractError.invalid("decoder metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case algorithm
        case threshold
        case peakConfirmationS = "peak_confirmation_s"
        case minimumEventGapS = "minimum_event_gap_s"
    }
}

public struct TrainingRecordingClient: Codable, Equatable, Sendable {
    public let appVersion: String
    public let build: String
    public let deviceModel: String
    public let osVersion: String

    public init(appVersion: String, build: String, deviceModel: String, osVersion: String) {
        self.appVersion = appVersion
        self.build = build
        self.deviceModel = deviceModel
        self.osVersion = osVersion
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireExactKeys(container, CodingKeys.self)
        appVersion = try container.decode(String.self, forKey: .appVersion)
        build = try container.decode(String.self, forKey: .build)
        deviceModel = try container.decode(String.self, forKey: .deviceModel)
        osVersion = try container.decode(String.self, forKey: .osVersion)
        guard !appVersion.isEmpty, !build.isEmpty, !deviceModel.isEmpty, !osVersion.isEmpty else {
            throw RepositoryIntakeContractError.invalid("client metadata contains an invalid value")
        }
    }

    private enum CodingKeys: String, CodingKey, CaseIterable {
        case appVersion = "app_version"
        case build
        case deviceModel = "device_model"
        case osVersion = "os_version"
    }
}

private func isLowercaseSHA256(_ value: String) -> Bool {
    value.count == 64 && value.unicodeScalars.allSatisfy { scalar in
        (0x30...0x39).contains(scalar.value) || (0x61...0x66).contains(scalar.value)
    }
}

private func requireExactKeys<Key: CodingKey & CaseIterable>(
    _ container: KeyedDecodingContainer<Key>,
    _ keyType: Key.Type
) throws {
    let expected = Set(keyType.allCases.map(\.stringValue))
    let actual = Set(container.allKeys.map(\.stringValue))
    guard actual == expected else {
        throw RepositoryIntakeContractError.invalid("unexpected or missing fields")
    }
}
