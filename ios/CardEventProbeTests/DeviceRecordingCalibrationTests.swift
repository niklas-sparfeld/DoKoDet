import XCTest

@testable import CardEventProbeCore

final class DeviceRecordingCalibrationTests: XCTestCase {
  func testMatchesPythonCalibrationFixture() throws {
    let url = try XCTUnwrap(
      Bundle.module.url(
        forResource: "device_recording_calibration_python_v1", withExtension: "json",
        subdirectory: "Fixtures"))
    let root = try XCTUnwrap(
      JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    let values = try XCTUnwrap(root["observations"] as? [[String: Any]])
    let observations = try values.map { item -> DeviceCalibrationObservation in
      let metrics = item["quality_metrics"] as? [String: Double] ?? [:]
      return DeviceCalibrationObservation(
        candidateID: try XCTUnwrap(item["candidate_id"] as? String),
        frameID: try XCTUnwrap(item["frame_id"] as? String),
        timeS: try XCTUnwrap(item["time_s"] as? Double),
        frameWidth: try XCTUnwrap(item["frame_width"] as? Int),
        frameHeight: try XCTUnwrap(item["frame_height"] as? Int),
        sourceTransformID: try XCTUnwrap(item["source_transform_id"] as? String),
        confidence: try XCTUnwrap(item["confidence"] as? Double),
        quadrilateral: try points(item["quadrilateral"]),
        boundarySamples: try points(item["boundary_samples"]),
        qualityScore: item["quality_score"] as? Double,
        qualityMetrics: metrics,
        temporalBin: item["temporal_bin"] as? String,
        tablePositionBin: item["table_position_bin"] as? String,
        scaleBin: item["scale_bin"] as? String,
        orientationBin: item["orientation_bin"] as? String,
        sourceRevision: item["source_revision"] as? String)
    }
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: try XCTUnwrap(root["recording_id"] as? String),
      visibleCardRevisionID: try XCTUnwrap(root["visible_card_revision_id"] as? String),
      observations: observations,
      sizeReferenceInputDigest: root["size_reference_input_digest"] as? String)
    let expected = try XCTUnwrap(root["expected"] as? [String: Any])
    let calibration = try XCTUnwrap(result.calibration)

    XCTAssertEqual(result.status, expected["status"] as? String)
    XCTAssertEqual(result.candidateDecisions["candidate-011"], "rejected:frame_boundary")
    XCTAssertEqual(result.calibration?.acceptedCandidateIDs.count, 11)
    XCTAssertEqual(result.fitCandidateIDs, expected["fit_candidate_ids"] as? [String])
    XCTAssertEqual(result.heldOutCandidateIDs, expected["held_out_candidate_ids"] as? [String])
    XCTAssertEqual(result.gates, expected["gates"] as? [String: Bool])
    XCTAssertEqual(
      result.candidateReceiptDigests, expected["candidate_receipt_digests"] as? [String])
    XCTAssertEqual(
      calibration.calibrationRevisionID, expected["calibration_revision_id"] as? String)
    let serializedCalibration = calibration.toMapping()
    XCTAssertEqual(serializedCalibration["schema_version"] as? String, "table-plane-calibration/v1")
    XCTAssertEqual(
      serializedCalibration["calibration_digest"] as? String, calibration.calibrationDigest)
    let expectedImageToTable = try DeviceHomography(rows: matrix(expected["image_to_table"]))
    let expectedTableToImage = try DeviceHomography(rows: matrix(expected["table_to_image"]))
    let imageLandmarks = try [
      DevicePoint2D(x: 0, y: 0), DevicePoint2D(x: 1920, y: 0),
      DevicePoint2D(x: 1920, y: 1080), DevicePoint2D(x: 0, y: 1080),
      DevicePoint2D(x: 960, y: 540),
    ]
    let expectedTableLandmarks = try expectedImageToTable.apply(to: imageLandmarks)
    let actualTableLandmarks = try calibration.imageToTable.apply(to: imageLandmarks)
    XCTAssertLessThan(
      zip(expectedTableLandmarks, actualTableLandmarks).map(distance).max() ?? .infinity, 0.002)
    let tableLandmarks = try [
      DevicePoint2D(x: -1, y: -1), DevicePoint2D(x: 11, y: -1),
      DevicePoint2D(x: 11, y: 8.5), DevicePoint2D(x: -1, y: 8.5),
    ]
    let expectedImageLandmarks = try expectedTableToImage.apply(to: tableLandmarks)
    let actualImageLandmarks = try calibration.tableToImage.apply(to: tableLandmarks)
    XCTAssertLessThan(
      zip(expectedImageLandmarks, actualImageLandmarks).map(distance).max() ?? .infinity, 0.2)
  }

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
    XCTAssertEqual(calibration.acceptedCandidateIDs.count, 11)
    XCTAssertNotNil(result.fitResult)
    XCTAssertTrue(calibration.imageToTable.rows.flatMap { $0 }.allSatisfy(\.isFinite))
    XCTAssertTrue(calibration.tableToImage.rows.flatMap { $0 }.allSatisfy(\.isFinite))
  }

  func testCalibrationRefinementReturnsImmutablePreviewAndDeduplicatesAnchors() throws {
    let observations = try syntheticObservations()
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: observations)
    let base = try XCTUnwrap(result.calibration)
    let anchors = observations.prefix(9).enumerated().map { index, item in
      DeviceCalibrationAnchor(
        anchorID: "anchor-\(index)", cardID: "card-\(index)", frameID: item.frameID,
        frameDigest: String(repeating: "a", count: 64), quadrilateral: item.quadrilateral,
        confidence: item.confidence, temporalBin: "t-\(index)",
        tableRegionBin: "r-\(index)", scaleBin: "s", orientationBin: "o-\(index % 2)",
        eligible: true)
    }
    var duplicated = anchors
    duplicated.append(
      DeviceCalibrationAnchor(
        anchorID: "anchor-duplicate", cardID: "card-duplicate", frameID: anchors[1].frameID,
        frameDigest: anchors[1].frameDigest, quadrilateral: anchors[1].quadrilateral,
        confidence: 0.5, temporalBin: anchors[1].temporalBin,
        tableRegionBin: anchors[1].tableRegionBin, scaleBin: anchors[1].scaleBin,
        orientationBin: anchors[1].orientationBin, eligible: true))

    let draft = refinementDraft(anchors: duplicated, base: base)
    let preview = try DeviceCalibrationRefinement.preview(draft: draft, base: base)

    XCTAssertEqual(preview.status, "pass")
    XCTAssertEqual(preview.deduplicatedAnchorIDs, ["anchor-duplicate"])
    XCTAssertNotNil(preview.fitResult)
    XCTAssertEqual(base.calibrationDigest, result.calibration?.calibrationDigest)
    XCTAssertEqual(preview.baseCalibrationDigest, base.calibrationDigest)
    XCTAssertEqual(preview.gates.count, 5)
  }

  func testCalibrationRefinementBlocksInsufficientAnchorsWithoutChangingBase() throws {
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: try syntheticObservations())
    let base = try XCTUnwrap(result.calibration)
    let preview = try DeviceCalibrationRefinement.preview(
      draft: refinementDraft(anchors: [], base: base), base: base)

    XCTAssertEqual(preview.status, "blocked")
    XCTAssertEqual(preview.failureCode, "insufficient_anchors")
    XCTAssertNil(preview.fitResult)
    XCTAssertEqual(preview.baseCalibrationDigest, base.calibrationDigest)
  }

  func testCalibrationRefinementMatchesPythonPreviewFixture() throws {
    let url = try XCTUnwrap(
      Bundle.module.url(
        forResource: "device_calibration_refinement_python_v1", withExtension: "json",
        subdirectory: "Fixtures"))
    let root = try XCTUnwrap(
      JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    let base = try calibration(root["base_calibration"])
    let rawAnchors = try XCTUnwrap(root["anchors"] as? [[String: Any]])
    let anchors = try rawAnchors.map { raw in
      DeviceCalibrationAnchor(
        anchorID: try XCTUnwrap(raw["anchor_id"] as? String),
        cardID: try XCTUnwrap(raw["card_id"] as? String),
        frameID: try XCTUnwrap(raw["source_frame_id"] as? String),
        frameDigest: try XCTUnwrap(raw["source_frame_digest"] as? String),
        quadrilateral: try points(raw["quadrilateral"]),
        confidence: try XCTUnwrap(raw["confidence"] as? Double),
        temporalBin: try XCTUnwrap(raw["temporal_bin"] as? String),
        tableRegionBin: try XCTUnwrap(raw["table_region_bin"] as? String),
        scaleBin: try XCTUnwrap(raw["scale_bin"] as? String),
        orientationBin: try XCTUnwrap(raw["orientation_bin"] as? String),
        eligible: try XCTUnwrap(raw["eligible"] as? Bool),
        eligibilityReason: raw["eligibility_reason"] as? String,
        state: try XCTUnwrap(raw["state"] as? String),
        weightClass: try XCTUnwrap(raw["weight_class"] as? String))
    }
    let sourceDigests = try XCTUnwrap(root["source_frame_digests"] as? [String: String])
    let draft = DeviceCalibrationRefinementDraft(
      draftID: try XCTUnwrap(root["draft_id"] as? String),
      detectorRevisionID: try XCTUnwrap(root["detector_revision_id"] as? String),
      detectorRevisionDigest: try XCTUnwrap(root["detector_revision_digest"] as? String),
      baseCalibrationRevisionID: base.calibrationRevisionID,
      baseCalibrationDigest: base.calibrationDigest,
      sourceFrameDigests: sourceDigests, anchors: anchors)
    let preview = try DeviceCalibrationRefinement.preview(draft: draft, base: base)
    let expected = try XCTUnwrap(root["expected"] as? [String: Any])

    XCTAssertEqual(preview.status, expected["status"] as? String)
    XCTAssertEqual(preview.failureCode, expected["failure_code"] as? String)
    XCTAssertEqual(preview.eligibleAnchorIDs, expected["eligible_anchor_ids"] as? [String])
    XCTAssertEqual(preview.acceptedAnchorCount, expected["accepted_anchor_count"] as? Int)
    XCTAssertEqual(preview.deduplicatedAnchorIDs.count, 0)
    XCTAssertEqual(
      preview.fitResidual, try XCTUnwrap(expected["fit_residual"] as? Double), accuracy: 0.01)
    XCTAssertEqual(
      preview.heldOutAlignmentChangePixels,
      try XCTUnwrap(expected["held_out_alignment_change_px"] as? Double), accuracy: 3.0)
    let fit = try XCTUnwrap(preview.fitResult)
    let imagePoints = try [
      DevicePoint2D(x: 0, y: 0), DevicePoint2D(x: 1920, y: 0),
      DevicePoint2D(x: 1920, y: 1080), DevicePoint2D(x: 0, y: 1080),
      DevicePoint2D(x: 960, y: 540),
    ]
    let expectedLandmarks = try points(expected["image_landmarks"])
    let actualLandmarks = try fit.imageToTable.apply(to: imagePoints)
    XCTAssertLessThan(zip(expectedLandmarks, actualLandmarks).map(distance).max() ?? .infinity, 0.1)
    let expectedGates = try XCTUnwrap(expected["gates"] as? [[String: Any]])
    XCTAssertEqual(preview.gates.map(\.id), expectedGates.compactMap { $0["gate_id"] as? String })
    XCTAssertEqual(
      preview.gates.map(\.passed), expectedGates.compactMap { $0["passed"] as? Bool })

    let firstAnchor = try XCTUnwrap(anchors.first)
    let duplicate = DeviceCalibrationAnchor(
      anchorID: "anchor-duplicate", cardID: "card-duplicate", frameID: firstAnchor.frameID,
      frameDigest: firstAnchor.frameDigest, quadrilateral: firstAnchor.quadrilateral,
      confidence: 0.1, temporalBin: firstAnchor.temporalBin,
      tableRegionBin: firstAnchor.tableRegionBin, scaleBin: firstAnchor.scaleBin,
      orientationBin: firstAnchor.orientationBin, eligible: true)
    let duplicateDraft = DeviceCalibrationRefinementDraft(
      draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
      detectorRevisionDigest: draft.detectorRevisionDigest,
      baseCalibrationRevisionID: base.calibrationRevisionID,
      baseCalibrationDigest: base.calibrationDigest,
      sourceFrameDigests: sourceDigests, anchors: anchors + [duplicate])
    let deduplicated = try DeviceCalibrationRefinement.preview(draft: duplicateDraft, base: base)
    XCTAssertEqual(
      deduplicated.deduplicatedAnchorIDs,
      try XCTUnwrap(root["expected_deduplicated_anchor_ids"] as? [String]))

    let emptyDraft = DeviceCalibrationRefinementDraft(
      draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
      detectorRevisionDigest: draft.detectorRevisionDigest,
      baseCalibrationRevisionID: base.calibrationRevisionID,
      baseCalibrationDigest: base.calibrationDigest,
      sourceFrameDigests: sourceDigests, anchors: [])
    let insufficient = try DeviceCalibrationRefinement.preview(draft: emptyDraft, base: base)
    let expectedInsufficient = try XCTUnwrap(
      root["expected_insufficient_anchors"] as? [String: Any])
    XCTAssertEqual(insufficient.status, expectedInsufficient["status"] as? String)
    XCTAssertEqual(insufficient.failureCode, expectedInsufficient["failure_code"] as? String)
    XCTAssertNil(insufficient.fitResult)
  }

  func testCalibrationRefinementRejectsStaleCalibrationLineage() throws {
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: try syntheticObservations())
    let base = try XCTUnwrap(result.calibration)
    let draft = refinementDraft(anchors: [], base: base)
    let staleDraft = DeviceCalibrationRefinementDraft(
      draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
      detectorRevisionDigest: draft.detectorRevisionDigest,
      baseCalibrationRevisionID: "old-calibration",
      baseCalibrationDigest: draft.baseCalibrationDigest,
      sourceFrameDigests: draft.sourceFrameDigests, anchors: draft.anchors)

    let preview = try DeviceCalibrationRefinement.preview(draft: staleDraft, base: base)

    XCTAssertEqual(preview.status, "blocked")
    XCTAssertEqual(preview.failureCode, "stale_calibration_revision")
    XCTAssertNil(preview.fitResult)
    XCTAssertEqual(preview.detectorRevisionDigest, draft.detectorRevisionDigest)
  }

  func testCalibrationRefinementBlocksConflictingPinnedAnchors() throws {
    let observations = try syntheticObservations()
    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: observations)
    let base = try XCTUnwrap(result.calibration)
    let first = observations[0]
    let second = observations[1]
    let pinned = [first, second].enumerated().map { index, item in
      DeviceCalibrationAnchor(
        anchorID: "pin-\(index)", cardID: "card-\(index)", frameID: item.frameID,
        frameDigest: String(repeating: "a", count: 64), quadrilateral: item.quadrilateral,
        confidence: 0.99, temporalBin: "same-time", tableRegionBin: "same-region",
        scaleBin: "same-scale", orientationBin: "same-orientation", eligible: true,
        state: "pinned")
    }
    let draft = refinementDraft(anchors: pinned, base: base)

    let preview = try DeviceCalibrationRefinement.preview(draft: draft, base: base)

    XCTAssertEqual(preview.status, "blocked")
    XCTAssertEqual(preview.failureCode, "conflicting_pinned_anchors")
    XCTAssertNil(preview.fitResult)
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

  func testRejectsAnOutlierCandidateAndRetainsItsDecision() throws {
    var observations = try syntheticObservations()
    let source = observations[6]
    var shifted = source.quadrilateral
    shifted[0] = try DevicePoint2D(x: shifted[0].x + 160, y: shifted[0].y - 40)
    observations[6] = DeviceCalibrationObservation(
      candidateID: source.candidateID, frameID: source.frameID, timeS: source.timeS,
      frameWidth: source.frameWidth, frameHeight: source.frameHeight,
      sourceTransformID: source.sourceTransformID, confidence: source.confidence,
      quadrilateral: shifted)

    let result = try DeviceRecordingCalibrationSelector.calibrate(
      recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
      observations: observations)

    XCTAssertEqual(result.status, "published", "\(result.failureCode ?? "") \(result.gates)")
    XCTAssertEqual(
      result.candidateDecisions[source.candidateID], "rejected:inconsistent_apparent_card_scale")
    XCTAssertTrue(
      result.candidateEvidence.contains {
        $0.candidateID == source.candidateID
          && $0.rejectionReason == "inconsistent_apparent_card_scale"
      })
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

  func testRejectsCandidatesFromAnotherVisibleCardRevision() throws {
    let observations = try syntheticObservations()
    let foreign = DeviceCalibrationObservation(
      candidateID: "foreign-candidate", frameID: "foreign-frame", timeS: 0,
      frameWidth: 1920, frameHeight: 1080, sourceTransformID: "camera-transform-1",
      confidence: 0.98, quadrilateral: observations[0].quadrilateral,
      sourceRevision: "visible-cards-r0")
    XCTAssertThrowsError(
      try DeviceRecordingCalibrationSelector.calibrate(
        recordingID: "recording-1", visibleCardRevisionID: "visible-cards-r1",
        observations: [foreign]))
  }

  func testCalibratesFromExactVisibleCardRevision() throws {
    let locations: [(Double, Double)] = [
      (250, 200), (700, 200), (1150, 200), (250, 500), (700, 500), (1150, 500),
      (250, 800), (700, 800), (1150, 800), (450, 350), (900, 650), (1400, 850),
    ]
    let events = try locations.enumerated().map { index, location in
      let event = try DeviceVisibleCardEvent(index: index, timeS: Double(index), probability: 0.99)
      let mapping = DeviceVisibleCardFrameMapping(
        eventID: event.eventID, requestedTimeS: Double(index), frameIndex: index,
        actualTimeS: Double(index), deltaS: 0, status: "mapped", message: nil)
      let center = try DevicePoint2D(x: location.0, y: location.1)
      let quad = try DeviceCardPlaneGeometry.cardQuadrilateral(
        center: center, rotationDegrees: Double(index % 3) * 20,
        shortSize: 80, longSize: 120)
      let polygon = quad.map { [Int($0.x.rounded()), Int($0.y.rounded())] }
      let detection = DeviceVisibleCardDetection(
        classID: 0, className: "visible_card", score: 0.98,
        boxXYXY: [location.0 - 100, location.1 - 100, location.0 + 100, location.1 + 100],
        polygon: polygon, imageWidth: 1920, imageHeight: 1080)
      return DeviceVisibleCardEventResult(
        event: event, frameMapping: mapping, imagePath: nil,
        imageSHA256: String(repeating: "a", count: 64), imageWidth: 1920, imageHeight: 1080,
        detections: [detection], status: "complete", elapsedMs: 1, error: nil)
    }
    let revision = try DeviceVisibleCardRevision(
      recordingID: "recording-1", videoSHA256: String(repeating: "b", count: 64),
      compiledModelSHA256: nil, events: events, status: "complete", elapsedMs: 12)

    let result = try DeviceRecordingCalibrationSelector.calibrate(revision: revision)

    XCTAssertEqual(result.candidateEvidence.count, locations.count)
    XCTAssertTrue(result.candidateEvidence.allSatisfy { $0.sourceRevision == revision.stageID })
    XCTAssertEqual(result.status, "published", "\(result.failureCode ?? "") \(result.gates)")
    XCTAssertEqual(result.calibration?.visibleCardRevisionID, revision.stageID)
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

  private func refinementDraft(
    anchors: [DeviceCalibrationAnchor], base: DeviceRecordingCalibration
  ) -> DeviceCalibrationRefinementDraft {
    DeviceCalibrationRefinementDraft(
      draftID: "draft-1", detectorRevisionID: base.visibleCardRevisionID,
      detectorRevisionDigest: String(repeating: "d", count: 64),
      baseCalibrationRevisionID: base.calibrationRevisionID,
      baseCalibrationDigest: base.calibrationDigest,
      sourceFrameDigests: Dictionary(
        anchors.map { ($0.frameID, $0.frameDigest) }, uniquingKeysWith: { first, _ in first }),
      anchors: anchors)
  }

  private func calibration(_ raw: Any?) throws -> DeviceRecordingCalibration {
    let value = try XCTUnwrap(raw as? [String: Any])
    let diagnostics = try XCTUnwrap(value["diagnostics"] as? [String: Any])
    let evidence = try XCTUnwrap(diagnostics["candidate_evidence"] as? [[String: Any]])
    let accepted = evidence.filter { $0["accepted"] as? Bool == true }.compactMap {
      $0["candidate_id"] as? String
    }
    return DeviceRecordingCalibration(
      calibrationRevisionID: try XCTUnwrap(value["calibration_revision_id"] as? String),
      recordingID: try XCTUnwrap(value["recording_id"] as? String),
      visibleCardRevisionID: try XCTUnwrap(value["source_revision"] as? String),
      frameWidth: try XCTUnwrap(value["frame_width"] as? Int),
      frameHeight: try XCTUnwrap(value["frame_height"] as? Int),
      imageToTable: try DeviceHomography(rows: matrix(value["image_to_table"])),
      tableToImage: try DeviceHomography(rows: matrix(value["table_to_image"])),
      cardShortSize: try XCTUnwrap(value["card_short_size"] as? Double),
      cardLongSize: try XCTUnwrap(value["card_long_size"] as? Double),
      acceptedCandidateIDs: accepted,
      schemaVersion: try XCTUnwrap(value["schema_version"] as? String),
      geometryAlgorithmVersion: try XCTUnwrap(value["algorithm_version"] as? String),
      coordinateSystem: try XCTUnwrap(value["coordinate_system"] as? String),
      cornerOrder: try XCTUnwrap(value["corner_order"] as? String),
      angleConvention: try XCTUnwrap(value["angle_convention"] as? String),
      recipeDigest: (diagnostics["recipe_digest"] as? String) ?? String(repeating: "e", count: 64),
      candidateReceiptDigests: try XCTUnwrap(value["candidate_receipt_digests"] as? [String]))
  }

  private func points(_ raw: Any?) throws -> [DevicePoint2D] {
    try XCTUnwrap(raw as? [[Double]]).map { point in
      guard point.count == 2 else { throw DeviceRecordingCalibrationError.invalidInput }
      return try DevicePoint2D(x: point[0], y: point[1])
    }
  }

  private func matrix(_ raw: Any?) throws -> [[Double]] {
    let rows = try XCTUnwrap(raw as? [[Double]])
    guard rows.count == 3, rows.allSatisfy({ $0.count == 3 }) else {
      throw DeviceRecordingCalibrationError.invalidInput
    }
    return rows
  }

  private func distance(_ pair: (DevicePoint2D, DevicePoint2D)) -> Double {
    hypot(pair.0.x - pair.1.x, pair.0.y - pair.1.y)
  }
}
