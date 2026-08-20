import CoreMedia
import XCTest
@testable import CardEventProbeCore

final class EventPostProcessorTests: XCTestCase {
    private let configuration = EventPostProcessor.Configuration(
        highThreshold: 0.75,
        lowThreshold: 0.35,
        minimumConsecutiveHighPredictions: 2,
        cooldown: CMTime(seconds: 0.6, preferredTimescale: 600)
    )

    func testAllLowScoresProduceNoEvents() {
        let processor = EventPostProcessor(configuration: configuration)

        let events = feed(processor, probabilities: [0.1, 0.2, 0.34, 0.0])

        XCTAssertTrue(events.isEmpty)
    }

    func testOneIsolatedHighScoreDoesNotProduceAnEvent() {
        let processor = EventPostProcessor(configuration: configuration)

        let events = feed(processor, probabilities: [0.1, 0.9, 0.1])

        XCTAssertTrue(events.isEmpty)
    }

    func testSustainedHighScoresProduceExactlyOneEvent() {
        let processor = EventPostProcessor(configuration: configuration)

        let events = feed(processor, probabilities: [0.8, 0.9, 0.95, 0.88, 0.2])

        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].peakProbability, 0.9, accuracy: 0.0001)
    }

    func testHighLowHighAfterCooldownProducesTwoEvents() {
        let processor = EventPostProcessor(configuration: configuration)

        let events = feed(
            processor,
            times: [0.0, 0.125, 0.25, 0.95, 1.075, 1.2],
            probabilities: [0.8, 0.9, 0.1, 0.8, 0.9, 0.1]
        )

        XCTAssertEqual(events.count, 2)
    }

    func testBriefDipWithinLowThresholdKeepsOneEventActive() {
        let processor = EventPostProcessor(configuration: configuration)

        let events = feed(
            processor,
            probabilities: [0.8, 0.9, 0.5, 0.8, 0.9, 0.1]
        )

        XCTAssertEqual(events.count, 1)
    }

    func testResetReturnsToCleanState() {
        let processor = EventPostProcessor(configuration: configuration)

        _ = feed(processor, probabilities: [0.8])
        processor.reset()
        let events = feed(processor, probabilities: [0.8, 0.9])

        XCTAssertEqual(events.count, 1)
    }

    private func feed(
        _ processor: EventPostProcessor,
        times: [Double]? = nil,
        probabilities: [Double]
    ) -> [DetectionEvent] {
        let sampleTimes = times ?? probabilities.indices.map { Double($0) * 0.125 }
        precondition(sampleTimes.count == probabilities.count)

        return zip(sampleTimes, probabilities).compactMap { time, probability in
            processor.consume(
                ModelPrediction(
                    timestamp: CMTime(seconds: time, preferredTimescale: 600),
                    cardEventProbability: probability,
                    inferenceDurationMs: 1.0
                )
            )
        }
    }
}
