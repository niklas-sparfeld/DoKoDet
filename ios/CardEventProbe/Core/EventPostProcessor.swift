import CoreMedia

/// Converts a burst of model predictions into one event per physical card play.
public final class EventPostProcessor {
    public struct Configuration {
        public var highThreshold: Double
        public var lowThreshold: Double
        public var minimumConsecutiveHighPredictions: Int
        public var cooldown: CMTime

        public init(
            highThreshold: Double = 0.75,
            lowThreshold: Double = 0.35,
            minimumConsecutiveHighPredictions: Int = 2,
            cooldown: CMTime = CMTime(seconds: 0.6, preferredTimescale: 600)
        ) {
            precondition(highThreshold > lowThreshold, "highThreshold must exceed lowThreshold")
            precondition(lowThreshold >= 0.0 && highThreshold <= 1.0, "thresholds must be in [0, 1]")
            precondition(minimumConsecutiveHighPredictions > 0, "minimum hit count must be positive")
            precondition(cooldown >= .zero, "cooldown must not be negative")

            self.highThreshold = highThreshold
            self.lowThreshold = lowThreshold
            self.minimumConsecutiveHighPredictions = minimumConsecutiveHighPredictions
            self.cooldown = cooldown
        }
    }

    private struct Candidate {
        var hits: Int
        var peakTimestamp: CMTime
        var peakProbability: Double
    }

    private enum State {
        case idle
        case candidate(Candidate)
        case active
        case cooldown(until: CMTime)
    }

    public private(set) var configuration: Configuration
    private var state: State = .idle
    private var lastTimestamp: CMTime?

    public init(configuration: Configuration = Configuration()) {
        self.configuration = configuration
    }

    public func reset() {
        state = .idle
        lastTimestamp = nil
    }

    public func updateConfiguration(_ configuration: Configuration) {
        self.configuration = configuration
        reset()
    }

    /// Consume one prediction. The return value is non-nil only when a new event is emitted.
    public func consume(_ prediction: ModelPrediction) -> DetectionEvent? {
        if let lastTimestamp, CMTimeCompare(prediction.timestamp, lastTimestamp) < 0 {
            reset()
        }
        lastTimestamp = prediction.timestamp

        switch state {
        case .idle:
            guard isHigh(prediction) else { return nil }
            return beginCandidate(with: prediction)

        case let .candidate(candidate):
            guard isHigh(prediction) else {
                state = .idle
                return nil
            }

            let updated = Candidate(
                hits: candidate.hits + 1,
                peakTimestamp: peakProbability(candidate, prediction).timestamp,
                peakProbability: peakProbability(candidate, prediction).probability
            )
            guard updated.hits >= configuration.minimumConsecutiveHighPredictions else {
                state = .candidate(updated)
                return nil
            }

            state = .active
            return DetectionEvent(
                timestamp: updated.peakTimestamp,
                peakProbability: updated.peakProbability
            )

        case .active:
            if isAtLeastLow(prediction) {
                return nil
            }

            state = .cooldown(until: prediction.timestamp + configuration.cooldown)
            return nil

        case let .cooldown(until):
            if CMTimeCompare(prediction.timestamp, until) < 0 {
                // A return above the low threshold during cooldown belongs to the
                // current burst. It must not create a second event.
                if isAtLeastLow(prediction) {
                    state = .active
                }
                return nil
            }

            state = .idle
            return consume(prediction)
        }
    }

    private func beginCandidate(with prediction: ModelPrediction) -> DetectionEvent? {
        let candidate = Candidate(
            hits: 1,
            peakTimestamp: prediction.timestamp,
            peakProbability: prediction.cardEventProbability
        )
        guard configuration.minimumConsecutiveHighPredictions == 1 else {
            state = .candidate(candidate)
            return nil
        }

        state = .active
        return DetectionEvent(
            timestamp: prediction.timestamp,
            peakProbability: prediction.cardEventProbability
        )
    }

    private func isHigh(_ prediction: ModelPrediction) -> Bool {
        prediction.cardEventProbability >= configuration.highThreshold
    }

    private func isAtLeastLow(_ prediction: ModelPrediction) -> Bool {
        prediction.cardEventProbability >= configuration.lowThreshold
    }

    private func peakProbability(
        _ candidate: Candidate,
        _ prediction: ModelPrediction
    ) -> (timestamp: CMTime, probability: Double) {
        if prediction.cardEventProbability > candidate.peakProbability {
            return (prediction.timestamp, prediction.cardEventProbability)
        }
        return (candidate.peakTimestamp, candidate.peakProbability)
    }
}
