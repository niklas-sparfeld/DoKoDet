import CoreMedia
import Foundation
import XCTest
@testable import CardEventProbeCore

final class CausalEventDecoderTests: XCTestCase {
    func testMatchesSharedFixture() throws {
        let fixture = try loadFixture()
        let configuration = CausalEventDecoder.Configuration(
            threshold: fixture.configuration.threshold,
            peakConfirmation: time(fixture.configuration.peakConfirmationSeconds),
            minimumEventGap: time(fixture.configuration.minimumEventGapSeconds)
        )

        for stream in fixture.streams {
            let decoder = CausalEventDecoder(configuration: configuration)
            var events: [DetectionEvent] = []
            for sample in stream.samples {
                let prediction = ModelPrediction(
                    timestamp: time(sample.timeSeconds),
                    cardEventProbability: sample.probability,
                    inferenceDurationMs: 1.0
                )
                if let event = decoder.consume(prediction) {
                    events.append(event)
                }
            }
            if let event = decoder.flush() {
                events.append(event)
            }

            XCTAssertEqual(events.count, stream.events.count, stream.name)
            for (actual, expected) in zip(events, stream.events) {
                XCTAssertEqual(CMTimeGetSeconds(actual.timestamp), expected.timeSeconds, accuracy: 0.000001, stream.name)
                XCTAssertEqual(actual.peakProbability, expected.probability, accuracy: 0.000001, stream.name)
                XCTAssertEqual(CMTimeGetSeconds(actual.emittedAt), expected.emittedAtSeconds, accuracy: 0.000001, stream.name)
            }
        }
    }

    func testFlushEmitsPendingPeakOnlyOnce() {
        let decoder = CausalEventDecoder(
            configuration: CausalEventDecoder.Configuration(
                threshold: 0.5,
                peakConfirmation: time(0.125),
                minimumEventGap: time(0.625)
            )
        )

        _ = decoder.consume(prediction(at: 0.0, probability: 0.8))
        XCTAssertNotNil(decoder.flush())
        XCTAssertNil(decoder.flush())
    }

    func testResetClearsTheLastEventGap() {
        let decoder = CausalEventDecoder(
            configuration: CausalEventDecoder.Configuration(
                threshold: 0.5,
                peakConfirmation: time(0.125),
                minimumEventGap: time(0.625)
            )
        )

        _ = decoder.consume(prediction(at: 0.0, probability: 0.8))
        _ = decoder.flush()
        decoder.reset()
        _ = decoder.consume(prediction(at: 0.0, probability: 0.8))
        XCTAssertNotNil(decoder.consume(prediction(at: 0.125, probability: 0.1)))
    }

    private func prediction(at seconds: Double, probability: Double) -> ModelPrediction {
        ModelPrediction(
            timestamp: time(seconds),
            cardEventProbability: probability,
            inferenceDurationMs: 1.0
        )
    }

    private func time(_ seconds: Double) -> CMTime {
        CMTime(seconds: seconds, preferredTimescale: 600)
    }

    private func loadFixture() throws -> Fixture {
        let url = try XCTUnwrap(
            Bundle.module.url(
                forResource: "causal_decoder_v1",
                withExtension: "json",
                subdirectory: "Fixtures"
            )
        )
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
    }
}

private struct Fixture: Decodable {
    let configuration: Configuration
    let streams: [Stream]
}

private struct Configuration: Decodable {
    let threshold: Double
    let peakConfirmationSeconds: Double
    let minimumEventGapSeconds: Double

    private enum CodingKeys: String, CodingKey {
        case threshold
        case peakConfirmationSeconds = "peak_confirmation_s"
        case minimumEventGapSeconds = "min_event_gap_s"
    }
}

private struct Stream: Decodable {
    let name: String
    let samples: [Sample]
    let events: [ExpectedEvent]
}

private struct Sample: Decodable {
    let timeSeconds: Double
    let probability: Double

    private enum CodingKeys: String, CodingKey {
        case timeSeconds = "time_s"
        case probability
    }
}

private struct ExpectedEvent: Decodable {
    let timeSeconds: Double
    let probability: Double
    let emittedAtSeconds: Double

    private enum CodingKeys: String, CodingKey {
        case timeSeconds = "time_s"
        case probability
        case emittedAtSeconds = "emitted_at_s"
    }
}
