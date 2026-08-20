import CoreMedia

public struct ModelPrediction {
    public let timestamp: CMTime
    public let cardEventProbability: Double
    public let rawOutputs: [String: Double]
    public let inferenceDurationMs: Double

    public init(
        timestamp: CMTime,
        cardEventProbability: Double,
        rawOutputs: [String: Double] = [:],
        inferenceDurationMs: Double
    ) {
        self.timestamp = timestamp
        self.cardEventProbability = cardEventProbability
        self.rawOutputs = rawOutputs
        self.inferenceDurationMs = inferenceDurationMs
    }
}
