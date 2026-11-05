import CoreGraphics
import CryptoKit
import XCTest

@testable import CardEventProbeCore

final class DeviceVisualIdentityTests: XCTestCase {
  func testFrozenFaceUpLogitsKeepReferenceIdentityAndCandidateOrder() throws {
    let logits: [Double] = [
      -8.410652160644531, -3.5688371658325195, -1.461574912071228, -2.475015640258789,
      -5.949587345123291, -5.7548651695251465, -8.66942310333252, -0.5868893265724182,
      2.296703338623047, -2.522869110107422, -5.3996782302856445, -5.814253807067871,
      -8.74496078491211, -4.071630477905273, -1.3275680541992188, -3.5831103324890137,
      -5.977299690246582, -4.9218597412109375, -8.902750968933105, -1.7615383863449097,
      -1.429769515991211, -2.2125940322875977, -6.1220598220825195, -6.941694259643555,
      -6.03010892868042,
    ]
    let result = try DeviceVisualIdentityPostprocessor.process(logits)
    XCTAssertEqual(result.rankedTargets.first, "SPADES_QUEEN")
    XCTAssertEqual(result.status, "classified")
    XCTAssertEqual(result.candidates.first?.card, "SPADES_QUEEN")
    XCTAssertEqual(result.candidates.count, 24)
    XCTAssertEqual(result.probabilities.reduce(0, +), 1, accuracy: 1e-12)
    XCTAssertLessThan(result.candidates.reduce(0) { $0 + $1.probability }, 1)
    XCTAssertEqual(result.candidates[0].probability, 0.9744869470596313, accuracy: 1e-6)
  }

  func testFrozenFaceDownLogitsRetainPositiveFaceDownAndNoIdentityCandidates() throws {
    var logits = Array(repeating: -10.0, count: 25)
    logits[24] = 0.44620656967163086
    let result = try DeviceVisualIdentityPostprocessor.process(logits)
    XCTAssertEqual(result.rankedTargets.first, "FACE_DOWN")
    XCTAssertEqual(result.status, "face_down")
    XCTAssertTrue(result.candidates.isEmpty)
  }

  func testRejectsWrongClassCountAndNonFiniteLogits() {
    XCTAssertThrowsError(try DeviceVisualIdentityPostprocessor.process([0]))
    XCTAssertThrowsError(
      try DeviceVisualIdentityPostprocessor.process(Array(repeating: .infinity, count: 25)))
  }

  func testPredictedVisibleRegionCropUsesNormalizedBoundsAndRejectsSmallInput() throws {
    var bytes = [UInt8](repeating: 255, count: 100 * 100 * 4)
    let context = CGContext(
      data: &bytes, width: 100, height: 100, bitsPerComponent: 8,
      bytesPerRow: 400, space: CGColorSpaceCreateDeviceRGB(),
      bitmapInfo: CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue
    )
    let image = try XCTUnwrap(context?.makeImage())
    let crop = try XCTUnwrap(
      DeviceVisibleRegionCropper.crop(
        image: image, normalizedPolygon: [[100, 100], [900, 100], [900, 900], [100, 900]]))
    XCTAssertEqual(crop.width, 80)
    XCTAssertEqual(crop.height, 80)
    XCTAssertNil(
      try DeviceVisibleRegionCropper.crop(
        image: image, normalizedPolygon: [[100, 100], [120, 100], [120, 120], [100, 120]]))
    XCTAssertNil(
      try DeviceVisibleRegionCropper.crop(image: image, normalizedPolygon: [[0, 0], [1, 1]]))
  }

  func testObservationHandoffKeepsLineageEmptyEventsAndUnusableItems() throws {
    let firstEvent = try DeviceVisibleCardEvent(index: 0, timeS: 1.25, probability: 0.9)
    let secondEvent = try DeviceVisibleCardEvent(index: 1, timeS: 2.5, probability: 0.8)
    let mapping1 = DeviceVisibleCardFrameMapping(
      eventID: firstEvent.eventID, requestedTimeS: 1.25, frameIndex: 1,
      actualTimeS: 1.25, deltaS: 0, status: "mapped", message: nil)
    let mapping2 = DeviceVisibleCardFrameMapping(
      eventID: secondEvent.eventID, requestedTimeS: 2.5, frameIndex: 2,
      actualTimeS: 2.5, deltaS: 0, status: "mapped", message: nil)
    let detection = DeviceVisibleCardDetection(
      classID: 0, className: "visible_card", score: 0.9,
      boxXYXY: [10, 10, 90, 90], polygon: [[10, 10], [90, 10], [90, 90], [10, 90]],
      imageWidth: 100, imageHeight: 100)
    let first = DeviceVisibleCardEventResult(
      event: firstEvent, frameMapping: mapping1, imagePath: "frame.png",
      imageSHA256: String(repeating: "a", count: 64), imageWidth: 100, imageHeight: 100,
      detections: [detection, detection], status: "complete", elapsedMs: 10, error: nil)
    let second = DeviceVisibleCardEventResult(
      event: secondEvent, frameMapping: mapping2, imagePath: "empty.png",
      imageSHA256: String(repeating: "b", count: 64), imageWidth: 100, imageHeight: 100,
      detections: [], status: "complete", elapsedMs: 4, error: nil)
    let classified = try DeviceVisualIdentityPostprocessor.process(
      [
        -8.410652160644531, -3.5688371658325195, -1.461574912071228, -2.475015640258789,
        -5.949587345123291, -5.7548651695251465, -8.66942310333252, -0.5868893265724182,
        2.296703338623047, -2.522869110107422, -5.3996782302856445, -5.814253807067871,
        -8.74496078491211, -4.071630477905273, -1.3275680541992188, -3.5831103324890137,
        -5.977299690246582, -4.921859741210938, -8.902750968933105, -1.7615383863449097,
        -1.429769515991211, -2.2125940322875977, -6.1220598220825195, -6.941694259643555,
        -6.03010892868042,
      ])
    let partial = DeviceVisualIdentityResult(
      status: classified.status, classification: classified.classification,
      candidates: Array(classified.candidates.prefix(3)), logits: classified.logits,
      rawProbabilities: classified.rawProbabilities, probabilities: classified.probabilities,
      rankedTargets: classified.rankedTargets, reviewThreshold: classified.reviewThreshold,
      reviewThresholdPassed: classified.reviewThresholdPassed)
    let good = DeviceVisualIdentityOutcome(
      eventID: "event-1", cardID: "event-1-card-1", status: "classified",
      cropPolicy: "predicted_visible_region", frameSHA256: String(repeating: "a", count: 64),
      cropSHA256: String(repeating: "c", count: 64),
      inputTensorSHA256: String(repeating: "d", count: 64),
      result: partial, elapsedMs: 3, error: nil)
    let unusable = DeviceVisualIdentityOutcome(
      eventID: "event-1", cardID: "event-1-card-2", status: "unusable",
      cropPolicy: "predicted_visible_region", frameSHA256: String(repeating: "a", count: 64),
      cropSHA256: nil, inputTensorSHA256: nil, result: nil, elapsedMs: 0,
      error: "missing crop")
    let observations = try DeviceTableObservationAssembler.assemble(
      events: [first, second],
      outcomesByEvent: ["event-1": [good.cardID: good, unusable.cardID: unusable]],
      recordingID: "recording-001", videoSHA256: String(repeating: "e", count: 64),
      assemblyRunID: "assembly-001", sessionID: "session-001",
      eventRevisionID: "events-001", visibleCardRevisionID: "visible-001",
      visualIdentityRevisionID: "identity-001")
    XCTAssertEqual(observations.count, 2)
    XCTAssertEqual(observations[0].cards[0].identityStatus, "classified")
    XCTAssertEqual(observations[0].cards[0].identityCandidates.count, 3)
    XCTAssertEqual(
      observations[0].cards[0].identityCandidates[0].probability,
      partial.candidates[0].probability)
    XCTAssertEqual(observations[0].cards[1].identityStatus, "unusable")
    XCTAssertEqual(observations[0].cards[1].side, "unknown")
    XCTAssertEqual(observations[1].status, "observed")
    XCTAssertTrue(observations[1].cards.isEmpty)
    XCTAssertEqual(
      observations[0].source.inputRevisionIDs,
      ["events-001", "visible-001", "identity-001"])
  }

  func testFrozenDinoCropsMatch0104CoreMLOutputsWhenReferenceRootIsAvailable() throws {
    guard let rootValue = ProcessInfo.processInfo.environment["DEVICE_VISIBLE_CARD_REFERENCE_ROOT"]
    else { throw XCTSkip("DEVICE_VISIBLE_CARD_REFERENCE_ROOT is unset") }
    let root = URL(fileURLWithPath: rootValue)
    let package = root.appendingPathComponent(".runtime/0104-m2/dinov3-identity.mlpackage")
    let inputRoot = root.appendingPathComponent(".runtime/0103-m0/inputs/identity-crops")
    let parityURL = root.appendingPathComponent("docs/reports/0104-M2_DINOv3_Core_ML_Parity.json")
    let parity = try XCTUnwrap(
      JSONSerialization.jsonObject(with: Data(contentsOf: parityURL)) as? [String: Any])
    let crops = try XCTUnwrap(parity["crops"] as? [String: [String: Any]])
    let targets = try XCTUnwrap(parity["targets"] as? [String])
    let threshold = try XCTUnwrap(parity["review_threshold"] as? Double)
    let runner = try DinoV3CoreMLRunner(modelURL: package)
    for name in ["face-up-card-frame-08s.ppm", "face-down-card-frame-40s.ppm"] {
      let cropURL = inputRoot.appendingPathComponent(name)
      let cropData = try Data(contentsOf: cropURL)
      let tensor = try DinoV3ImageTensor(ppmData: cropData).values
      let tensorBytes = tensor.withUnsafeBytes { Data($0) }
      let tensorDigest = SHA256.hash(data: tensorBytes).map { String(format: "%02x", $0) }.joined()
      let actual = try runner.predict(tensor)
      let expected = try XCTUnwrap(crops[name])
      let referenceTensorDigest = try XCTUnwrap(expected["input_tensor_digest"] as? String)
      print("DINO tensor \(name): actual=\(tensorDigest), 0104=\(referenceTensorDigest)")
      let expectedLogits = try XCTUnwrap(expected["coreml_logits"] as? [Double])
      let expectedRaw = try XCTUnwrap(expected["coreml_raw_probabilities"] as? [Double])
      let expectedCalibrated = try XCTUnwrap(expected["coreml_probabilities"] as? [Double])
      let expectedRank = try XCTUnwrap(expected["coreml_top_target"] as? String)
      let comparison = try XCTUnwrap(expected["logits_comparison"] as? [String: Any])
      let referenceRank = try XCTUnwrap(comparison["reference_rank"] as? [Int]).map { targets[$0] }
      XCTAssertEqual(actual.logits.count, 25)
      XCTAssertEqual(actual.rankedTargets.first, expectedRank, name)
      XCTAssertEqual(actual.rankedTargets, referenceRank, name)
      let logitDifference =
        zip(actual.logits, expectedLogits).map { abs($0 - $1) }.max() ?? .infinity
      let rawDifference =
        zip(actual.rawProbabilities, expectedRaw).map { abs($0 - $1) }.max() ?? .infinity
      let calibratedDifference =
        zip(actual.probabilities, expectedCalibrated).map { abs($0 - $1) }.max() ?? .infinity
      print(
        "DINO parity \(name): max logit=\(logitDifference), raw probability=\(rawDifference), calibrated probability=\(calibratedDifference)"
      )
      XCTAssertLessThanOrEqual(logitDifference, 0.01, name)
      XCTAssertLessThanOrEqual(rawDifference, 0.001, name)
      XCTAssertLessThanOrEqual(calibratedDifference, 0.001, name)
      XCTAssertEqual(actual.reviewThresholdPassed, (expectedCalibrated.max() ?? 0) >= threshold)
    }
  }
}
