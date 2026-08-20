import CoreMedia

public enum InferenceFrameDecision: Equatable {
    case accepted
    case sampledTooSoon
    case inferenceBusy
    case invalidTimestamp
}

/// Applies the live inference interval before work enters the model queue.
public struct InferenceSamplingPolicy {
    public let minimumInterval: CMTime
    private var lastAcceptedTimestamp: CMTime?

    public init(minimumInterval: CMTime = CMTime(seconds: 0.125, preferredTimescale: 600)) {
        precondition(minimumInterval >= .zero, "minimum interval must not be negative")
        self.minimumInterval = minimumInterval
    }

    public mutating func reset() {
        lastAcceptedTimestamp = nil
    }

    public mutating func accept(
        timestamp: CMTime,
        inferenceInFlight: Bool
    ) -> InferenceFrameDecision {
        let seconds = CMTimeGetSeconds(timestamp)
        guard seconds.isFinite else { return .invalidTimestamp }

        if let lastAcceptedTimestamp,
           CMTimeCompare(timestamp, lastAcceptedTimestamp) < 0 {
            self.lastAcceptedTimestamp = nil
        }

        if let lastAcceptedTimestamp,
           timestamp - lastAcceptedTimestamp < minimumInterval {
            return .sampledTooSoon
        }
        guard !inferenceInFlight else { return .inferenceBusy }

        lastAcceptedTimestamp = timestamp
        return .accepted
    }
}
