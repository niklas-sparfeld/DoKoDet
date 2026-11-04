import CoreMedia
import XCTest
@testable import CardEventProbeCore

final class VisibleCardStageTests: XCTestCase {
    func testNearestFrameUsesMoviePresentationTimeAndKeepsEarlierTie() throws {
        let frames = try [
            frame(index: 0, movie: CMTime(value: 0, timescale: 30)),
            frame(index: 1, movie: CMTime(value: 6, timescale: 30)),
        ]
        let event = try DeviceVisibleCardEvent(index: 0, timeS: 0.1, probability: 0.9)

        let result = DeviceVisibleCardFrameSelector.mapping(for: event, frames: frames)

        XCTAssertEqual(result.status, "mapped")
        XCTAssertEqual(result.frameIndex, 0)
        XCTAssertEqual(result.actualTimeS ?? -1, 0, accuracy: 0.000_001)
        XCTAssertEqual(result.deltaS ?? -1, 0.1, accuracy: 0.000_001)
    }

    func testFrameOutsideToleranceFailsWithoutSubstitution() throws {
        let frames = try [frame(index: 3, movie: CMTime(value: 1, timescale: 2))]
        let event = try DeviceVisibleCardEvent(index: 1, timeS: 0.1, probability: 0.7)

        let result = DeviceVisibleCardFrameSelector.mapping(for: event, frames: frames)

        XCTAssertEqual(result.status, "failed")
        XCTAssertNil(result.frameIndex)
        XCTAssertNil(result.actualTimeS)
        XCTAssertNotNil(result.message)
    }

    func testEventIdentityIsStableByOrder() throws {
        let first = try DeviceVisibleCardEvent(index: 4, timeS: 1.25, probability: 0.8)
        let reopened = try DeviceVisibleCardEvent(index: 4, timeS: 1.25, probability: 0.8)

        XCTAssertEqual(first.eventID, "event-5")
        XCTAssertEqual(first, reopened)
    }

    func testPostprocessorSelectsTopClassAndBuildsMaskPolygon() throws {
        let raw = try RfdetrRawOutput(
            queryCount: 2,
            classCount: 3,
            maskWidth: 2,
            maskHeight: 2,
            boxesCXCYWH: [0.5, 0.5, 1, 1, 0.5, 0.5, 0.5, 0.5],
            classLogits: [-4, 3, -3, 4, -4, -4],
            maskLogits: [-1, -1, -1, -1, 1, 1, 1, 1]
        )

        let detections = try DeviceVisibleCardPostprocessor.process(
            raw,
            imageWidth: 2,
            imageHeight: 2,
            maximumDetections: 2
        )

        XCTAssertEqual(detections.count, 2)
        XCTAssertEqual(detections[0].className, "visible_card")
        XCTAssertEqual(detections[0].boxXYXY, [0.5, 0.5, 1.5, 1.5])
        XCTAssertEqual(detections[0].normalizedBox1000, [250, 250, 750, 750])
        XCTAssertEqual(detections[0].polygon, [[0, 0], [1_000, 0], [1_000, 1_000], [0, 1_000]])
        XCTAssertEqual(detections[1].className, "card_pile")
    }

    func testPostprocessorReturnsACompleteEmptyDetectionList() throws {
        let raw = try RfdetrRawOutput(
            queryCount: 1,
            classCount: 3,
            maskWidth: 2,
            maskHeight: 2,
            boxesCXCYWH: [0.5, 0.5, 1, 1],
            classLogits: [-4, -4, -4],
            maskLogits: [-1, -1, -1, -1]
        )

        XCTAssertEqual(
            try DeviceVisibleCardPostprocessor.process(raw, imageWidth: 10, imageHeight: 10),
            []
        )
    }

    private func frame(index: Int, movie: CMTime) throws -> DeviceCaptureFrameTime {
        DeviceCaptureFrameTime(
            frameIndex: index,
            sourceTime: try DeviceMediaTime(movie),
            movieTime: try DeviceMediaTime(movie),
            orientation: "up"
        )
    }
}
