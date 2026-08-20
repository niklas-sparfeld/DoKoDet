import CoreMedia
import XCTest
@testable import CardEventProbeCore

final class InferenceSamplingPolicyTests: XCTestCase {
    func testAcceptsFirstFrameAndRejectsFramesBeforeInterval() {
        var policy = InferenceSamplingPolicy()
        let first = CMTime(seconds: 1.0, preferredTimescale: 600)
        let second = CMTime(seconds: 1.1, preferredTimescale: 600)
        let third = CMTime(seconds: 1.125, preferredTimescale: 600)

        XCTAssertEqual(policy.accept(timestamp: first, inferenceInFlight: false), .accepted)
        XCTAssertEqual(policy.accept(timestamp: second, inferenceInFlight: false), .sampledTooSoon)
        XCTAssertEqual(policy.accept(timestamp: third, inferenceInFlight: false), .accepted)
    }

    func testBusyInferenceDoesNotAdvanceSamplingTimestamp() {
        var policy = InferenceSamplingPolicy()
        let first = CMTime(seconds: 1.0, preferredTimescale: 600)
        let second = CMTime(seconds: 1.2, preferredTimescale: 600)

        XCTAssertEqual(policy.accept(timestamp: first, inferenceInFlight: false), .accepted)
        XCTAssertEqual(policy.accept(timestamp: second, inferenceInFlight: true), .inferenceBusy)
        XCTAssertEqual(policy.accept(timestamp: second, inferenceInFlight: false), .accepted)
    }

    func testBackwardsTimestampResetsThePolicy() {
        var policy = InferenceSamplingPolicy()
        let later = CMTime(seconds: 10.0, preferredTimescale: 600)
        let earlier = CMTime(seconds: 1.0, preferredTimescale: 600)

        XCTAssertEqual(policy.accept(timestamp: later, inferenceInFlight: false), .accepted)
        XCTAssertEqual(policy.accept(timestamp: earlier, inferenceInFlight: false), .accepted)
    }
}
