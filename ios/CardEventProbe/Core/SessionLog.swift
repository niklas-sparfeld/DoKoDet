import Foundation

public enum DiagnosticSource: String, Codable {
    case live
    case replay
}

public struct SessionLogMetadata: Codable, Equatable {
    public let source: DiagnosticSource
    public let appVersion: String
    public let device: String
    public let osVersion: String
    public let modelName: String
    public let modelVersion: String
    public let targetInferenceHz: Double
    public let threshold: Double
    public let peakConfirmationMs: Int
    public let minimumEventGapMs: Int

    public init(
        source: DiagnosticSource,
        appVersion: String,
        device: String,
        osVersion: String,
        modelName: String,
        modelVersion: String,
        targetInferenceHz: Double,
        threshold: Double,
        peakConfirmationMs: Int,
        minimumEventGapMs: Int
    ) {
        self.source = source
        self.appVersion = appVersion
        self.device = device
        self.osVersion = osVersion
        self.modelName = modelName
        self.modelVersion = modelVersion
        self.targetInferenceHz = targetInferenceHz
        self.threshold = threshold
        self.peakConfirmationMs = peakConfirmationMs
        self.minimumEventGapMs = minimumEventGapMs
    }
}

public struct SessionLogPrediction: Codable, Equatable {
    public let source: DiagnosticSource
    public let timestampSeconds: Double
    public let rawProbability: Double
    public let smoothedProbability: Double
    public let eventEmitted: Bool
    public let inferenceMs: Double

    public init(
        source: DiagnosticSource,
        timestampSeconds: Double,
        rawProbability: Double,
        smoothedProbability: Double,
        eventEmitted: Bool,
        inferenceMs: Double
    ) {
        self.source = source
        self.timestampSeconds = timestampSeconds
        self.rawProbability = rawProbability
        self.smoothedProbability = smoothedProbability
        self.eventEmitted = eventEmitted
        self.inferenceMs = inferenceMs
    }
}

public struct SessionLogAnnotation: Codable, Equatable {
    public enum Kind: String, Codable {
        case missedEvent = "missed_event"
        case falseEvent = "false_event"
    }

    public let source: DiagnosticSource
    public let timestampSeconds: Double?
    public let kind: Kind

    public init(source: DiagnosticSource, timestampSeconds: Double?, kind: Kind) {
        self.source = source
        self.timestampSeconds = timestampSeconds
        self.kind = kind
    }
}

public enum SessionLogError: LocalizedError {
    case cannotCreateDirectory(URL)
    case cannotCreateFile(URL)

    public var errorDescription: String? {
        switch self {
        case let .cannotCreateDirectory(url):
            return "The diagnostics directory could not be created at \(url.path)."
        case let .cannotCreateFile(url):
            return "The diagnostics log could not be created at \(url.path)."
        }
    }
}

/// Appends field-test diagnostics as newline-delimited JSON records.
public final class SessionLog {
    public let url: URL
    private let handle: FileHandle
    private let encoder: JSONEncoder

    public init(directory: URL, metadata: SessionLogMetadata, fileName: String = "session.jsonl") throws {
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            throw SessionLogError.cannotCreateDirectory(directory)
        }

        url = directory.appendingPathComponent(fileName, isDirectory: false)
        guard FileManager.default.createFile(atPath: url.path, contents: nil),
              let handle = try? FileHandle(forWritingTo: url) else {
            throw SessionLogError.cannotCreateFile(url)
        }
        self.handle = handle
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try append(type: "session", value: metadata)
    }

    deinit {
        close()
    }

    public func appendPrediction(_ prediction: SessionLogPrediction) throws {
        try append(type: "prediction", value: prediction)
    }

    public func appendAnnotation(_ annotation: SessionLogAnnotation) throws {
        try append(type: "annotation", value: annotation)
    }

    public func close() {
        try? handle.close()
    }

    private func append<Value: Encodable>(type: String, value: Value) throws {
        let valueData = try encoder.encode(value)
        guard var payload = try JSONSerialization.jsonObject(with: valueData) as? [String: Any] else {
            throw SessionLogError.cannotCreateFile(url)
        }
        payload["type"] = type
        var data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        data.append(0x0A)
        try handle.write(contentsOf: data)
    }
}
