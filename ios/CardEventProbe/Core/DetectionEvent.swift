import CoreMedia
import Foundation

public struct DetectionEvent: Identifiable {
    public let id: UUID
    public let timestamp: CMTime
    public let emittedAt: CMTime
    public let peakProbability: Double

    public init(
        id: UUID = UUID(),
        timestamp: CMTime,
        emittedAt: CMTime? = nil,
        peakProbability: Double
    ) {
        self.id = id
        self.timestamp = timestamp
        self.emittedAt = emittedAt ?? timestamp
        self.peakProbability = peakProbability
    }
}
