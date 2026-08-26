import CoreMedia

/// Decodes one causal event from each confirmed probability peak.
public final class CausalEventDecoder {
    public struct Configuration: Sendable {
        public var threshold: Double
        public var peakConfirmation: CMTime
        public var minimumEventGap: CMTime

        public init(
            threshold: Double = 0.4996626377105713,
            peakConfirmation: CMTime = CMTime(seconds: 0.125, preferredTimescale: 600),
            minimumEventGap: CMTime = CMTime(seconds: 0.625, preferredTimescale: 600)
        ) {
            precondition(threshold.isFinite && (0.0...1.0).contains(threshold), "threshold must be in [0, 1]")
            precondition(
                CMTimeGetSeconds(peakConfirmation).isFinite && peakConfirmation >= .zero,
                "peak confirmation must be finite and non-negative"
            )
            precondition(
                CMTimeGetSeconds(minimumEventGap).isFinite && minimumEventGap >= .zero,
                "minimum event gap must be finite and non-negative"
            )

            self.threshold = threshold
            self.peakConfirmation = peakConfirmation
            self.minimumEventGap = minimumEventGap
        }
    }

    private struct PendingPeak {
        var timestamp: CMTime
        var probability: Double
    }

    public private(set) var configuration: Configuration
    private var pendingPeak: PendingPeak?
    private var lastEventTimestamp: CMTime?
    private var lastSampleTimestamp: CMTime?
    private var armed = true

    public init(configuration: Configuration = Configuration()) {
        self.configuration = configuration
    }

    public func reset() {
        pendingPeak = nil
        lastEventTimestamp = nil
        lastSampleTimestamp = nil
        armed = true
    }

    public func updateConfiguration(_ configuration: Configuration) {
        self.configuration = configuration
        reset()
    }

    /// Consume one prediction. The event timestamp is the selected peak.
    public func consume(_ prediction: ModelPrediction) -> DetectionEvent? {
        let timestamp = prediction.timestamp
        if let lastSampleTimestamp,
           CMTimeCompare(timestamp, lastSampleTimestamp) < 0 {
            reset()
        }

        if let lastSampleTimestamp,
           CMTimeCompare(
               CMTimeSubtract(timestamp, lastSampleTimestamp),
               configuration.minimumEventGap
           ) > 0 {
            let event = flushPending(emittedAt: timestamp)
            armed = true
            self.lastSampleTimestamp = timestamp
            startPendingIfNeeded(prediction)
            return event
        }

        if let pendingPeak {
            if prediction.cardEventProbability > pendingPeak.probability {
                self.pendingPeak = PendingPeak(
                    timestamp: timestamp,
                    probability: prediction.cardEventProbability
                )
                lastSampleTimestamp = timestamp
                return nil
            }

            lastSampleTimestamp = timestamp
            if CMTimeCompare(
                CMTimeSubtract(timestamp, pendingPeak.timestamp),
                configuration.peakConfirmation
            ) >= 0 {
                let event = acceptPending(emittedAt: timestamp)
                armed = prediction.cardEventProbability < configuration.threshold
                return event
            }
            return nil
        }

        lastSampleTimestamp = timestamp
        startPendingIfNeeded(prediction)
        return nil
    }

    /// Emit a pending peak when a finite replay stream ends.
    public func flush() -> DetectionEvent? {
        guard let lastSampleTimestamp else { return nil }
        return flushPending(emittedAt: lastSampleTimestamp)
    }

    private func startPendingIfNeeded(_ prediction: ModelPrediction) {
        guard prediction.cardEventProbability >= configuration.threshold else {
            armed = true
            return
        }

        if armed,
           lastEventTimestamp == nil ||
            CMTimeCompare(
                CMTimeSubtract(prediction.timestamp, lastEventTimestamp!),
                configuration.minimumEventGap
            ) > 0 {
            pendingPeak = PendingPeak(
                timestamp: prediction.timestamp,
                probability: prediction.cardEventProbability
            )
        }
        armed = false
    }

    private func flushPending(emittedAt: CMTime) -> DetectionEvent? {
        guard pendingPeak != nil else { return nil }
        let event = acceptPending(emittedAt: emittedAt)
        armed = false
        return event
    }

    private func acceptPending(emittedAt: CMTime) -> DetectionEvent? {
        guard let pendingPeak else { return nil }
        self.pendingPeak = nil

        if let lastEventTimestamp,
           CMTimeCompare(
               CMTimeSubtract(pendingPeak.timestamp, lastEventTimestamp),
               configuration.minimumEventGap
           ) <= 0 {
            return nil
        }

        lastEventTimestamp = pendingPeak.timestamp
        return DetectionEvent(
            timestamp: pendingPeak.timestamp,
            emittedAt: emittedAt,
            peakProbability: pendingPeak.probability
        )
    }
}
