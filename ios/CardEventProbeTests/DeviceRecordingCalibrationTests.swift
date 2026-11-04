import XCTest

@testable import CardEventProbeCore

final class DeviceRecordingCalibrationTests: XCTestCase {
  func testPublishesStableSyntheticRecording() throws {
    let observations = try syntheticObservations()
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: observations)

    XCTAssertEqual(result.status, "published")
    XCTAssertNil(result.failureCode)
    let calibration = try XCTUnwrap(result.calibration)
    XCTAssertEqual(calibration.frameWidth, 1920)
    XCTAssertEqual(calibration.frameHeight, 1080)
    XCTAssertEqual(calibration.visibleCardRevisionID, "visible-cards-r1")
    XCTAssertEqual(calibration.acceptedCandidateIDs.count, 12)
    XCTAssertNotNil(result.fitResult)
    XCTAssertTrue(calibration.imageToTable.rows.flatMap { $0 }.allSatisfy(\.isFinite))
    XCTAssertTrue(calibration.tableToImage.rows.flatMap { $0 }.allSatisfy(\.isFinite))
  }

  func testDoesNotPublishInsufficientInput() throws {
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: [])

    XCTAssertEqual(result.status, "failed")
    XCTAssertEqual(result.failureCode, "insufficient_candidates")
    XCTAssertNil(result.calibration)
  }

  func testDoesNotPublishWhenCandidateCountIsBelowTheGate() throws {
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: Array(try syntheticObservations().prefix(5)))

    XCTAssertEqual(result.status, "failed")
    XCTAssertEqual(result.failureCode, "insufficient_candidates")
    XCTAssertNil(result.calibration)
  }

  func testRejectsChangedRecordingGeometry() throws {
    var observations = try syntheticObservations()
    let source = observations[0]
    observations[1] = DeviceCalibrationObservation(
      candidateID: observations[1].candidateID, frameID: source.frameID, timeS: source.timeS,
      frameWidth: 640, frameHeight: 480, sourceTransformID: source.sourceTransformID,
      confidence: source.confidence, quadrilateral: source.quadrilateral)
    XCTAssertThrowsError(
      try DeviceRecordingCalibrationSelector.calibrate(
        recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
        observations: observations))
  }

  private func syntheticObservations() throws -> [DeviceCalibrationObservation] {
    let locations: [(Double, Double)] = [
      (0, 0), (4, 0), (8, 0), (0, 3), (4, 3), (8, 3),
      (0, 6), (4, 6), (8, 6), (2, 1.5), (6, 4.5), (10, 7),
    ]
    let tableToImage = try DeviceHomography(rows: [
      [120, 20, 420], [15, 100, 240], [0.0002, 0.0004, 1],
    ])
    return try locations.enumerated().map { index, item in
      let center = try DevicePoint2D(x: item.0, y: item.1)
      let tableQuad = try DeviceCardPlaneGeometry.cardQuadrilateral(
        center: center, rotationDegrees: Double(index % 3) * 8,
        shortSize: 1, longSize: DeviceCardPlaneGeometry.cardAspectRatio)
      let quad = try tableToImage.apply(to: tableQuad)
      return DeviceCalibrationObservation(
        candidateID: String(format: "candidate-%02d", index),
        frameID: "frame-\(index)", timeS: Double(index),
        frameWidth: 1920, frameHeight: 1080, sourceTransformID: "camera-transform-1",
        confidence: 0.98, quadrilateral: quad)
    }
  }
}
