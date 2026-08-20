import Foundation

struct ReplayProgress {
    let fileName: String
    let durationSeconds: Double
    let currentTimeSeconds: Double
    let framesRead: Int
    let predictionsProduced: Int
    let eventCount: Int
    let lastEventTimestampSeconds: Double?
    let averageInferenceDurationMs: Double?
    let prediction: ModelPrediction?
    let isComplete: Bool
    let isCancelled: Bool
    let errorMessage: String?
}
