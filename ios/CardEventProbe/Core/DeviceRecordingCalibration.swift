import CoreFoundation
import CryptoKit
import Foundation

public struct DeviceCalibrationObservation: Equatable, Sendable {
  public let candidateID: String
  public let sourceRevision: String?
  public let frameID: String
  public let timeS: Double
  public let frameWidth: Int
  public let frameHeight: Int
  public let sourceTransformID: String
  public let confidence: Double
  public let qualityScore: Double?
  public let qualityMetrics: [String: Double]
  public let temporalBin: String?
  public let tablePositionBin: String?
  public let scaleBin: String?
  public let orientationBin: String?
  public let quadrilateral: [DevicePoint2D]
  public let boundarySamples: [DevicePoint2D]?

  public init(
    candidateID: String, frameID: String, timeS: Double, frameWidth: Int, frameHeight: Int,
    sourceTransformID: String, confidence: Double, quadrilateral: [DevicePoint2D],
    boundarySamples: [DevicePoint2D]? = nil, qualityScore: Double? = nil,
    qualityMetrics: [String: Double] = [:], temporalBin: String? = nil,
    tablePositionBin: String? = nil, scaleBin: String? = nil, orientationBin: String? = nil,
    sourceRevision: String? = nil
  ) {
    self.candidateID = candidateID
    self.sourceRevision = sourceRevision
    self.frameID = frameID
    self.timeS = timeS
    self.frameWidth = frameWidth
    self.frameHeight = frameHeight
    self.sourceTransformID = sourceTransformID
    self.confidence = confidence
    self.qualityScore = qualityScore
    self.qualityMetrics = qualityMetrics
    self.temporalBin = temporalBin
    self.tablePositionBin = tablePositionBin
    self.scaleBin = scaleBin
    self.orientationBin = orientationBin
    self.quadrilateral = quadrilateral
    self.boundarySamples = boundarySamples
  }
}

public struct DeviceRecordingCalibration: Equatable, Sendable {
  public let calibrationRevisionID: String
  public let recordingID: String
  public let visibleCardRevisionID: String
  public let frameWidth: Int
  public let frameHeight: Int
  public let imageToTable: DeviceHomography
  public let tableToImage: DeviceHomography
  public let cardShortSize: Double
  public let cardLongSize: Double
  public let acceptedCandidateIDs: [String]
  public let schemaVersion: String
  public let geometryAlgorithmVersion: String
  public let coordinateSystem: String
  public let cornerOrder: String
  public let angleConvention: String
  public let recipeDigest: String
  public let candidateReceiptDigests: [String]

  public var calibrationDigest: String {
    let mapping = toMapping()
    return mapping["calibration_digest"] as? String ?? ""
  }

  public func toMapping() -> [String: Any] {
    let core: [String: Any] = [
      "schema_version": schemaVersion,
      "calibration_revision_id": calibrationRevisionID,
      "recording_id": recordingID,
      "source_revision": visibleCardRevisionID,
      "frame_width": frameWidth,
      "frame_height": frameHeight,
      "image_to_table": imageToTable.rows.map { $0.map(DeviceRecordingCalibrationSelector.round6) },
      "table_to_image": tableToImage.rows.map { $0.map(DeviceRecordingCalibrationSelector.round6) },
      "card_short_size": DeviceRecordingCalibrationSelector.round6(cardShortSize),
      "card_long_size": DeviceRecordingCalibrationSelector.round6(cardLongSize),
      "card_aspect_ratio": cardLongSize / cardShortSize,
      "candidate_receipt_digests": candidateReceiptDigests,
      "algorithm_version": geometryAlgorithmVersion,
      "coordinate_system": coordinateSystem,
      "corner_order": cornerOrder,
      "angle_convention": angleConvention,
      "diagnostics": ["recipe_digest": recipeDigest],
    ]
    return core.merging(["calibration_digest": DeviceRecordingCalibrationSelector.digest(core)]) {
      _, new in new
    }
  }
}

public struct DeviceCalibrationCandidateEvidence: Equatable, Sendable {
  public let candidateID: String
  public let sourceRevision: String
  public let sourceFrameID: String
  public let confidence: Double
  public let quadrilateral: [DevicePoint2D]
  public let boundarySamples: [DevicePoint2D]
  public let qualityMetrics: [String: Double]
  public let qualityScore: Double
  public let decision: String
  public let temporalBin: String
  public let tablePositionBin: String
  public let scaleBin: String
  public let orientationBin: String
  public let accepted: Bool
  public let rejectionReason: String?
  public let receiptDigest: String
}

public struct DeviceRecordingCalibrationResult: Equatable, Sendable {
  public let status: String
  public let failureCode: String?
  public let failureMessage: String?
  public let candidateDecisions: [String: String]
  public let candidateEvidence: [DeviceCalibrationCandidateEvidence]
  public var candidateReceiptDigests: [String] { candidateEvidence.map(\.receiptDigest) }
  public let gates: [String: Bool]
  public let fitCandidateIDs: [String]
  public let heldOutCandidateIDs: [String]
  public let fitResult: DeviceTablePlaneFitResult?
  public let calibration: DeviceRecordingCalibration?
}

public enum DeviceRecordingCalibrationError: Error, Equatable {
  case invalidInput
  case inconsistentRecording
}

public enum DeviceRecordingCalibrationSelector {
  public static let recipeDigest =
    "e316b212f9882c808800fd5969a35e01d2a6f764004f375cecd81050e6e43a0b"
  public static let confidenceThreshold = 0.90
  public static let minimumCandidates = 6
  public static let minimumTemporalBins = 3
  public static let minimumPositionBins = 3
  public static let minimumOrientationBins = 2
  public static let minimumHeldOutCandidates = 2
  public static let holdoutModulus = 4

  /// Select a calibration from the exact frozen visible-card revision produced by M2.
  public static func calibrate(
    revision: DeviceVisibleCardRevision
  ) throws -> DeviceRecordingCalibrationResult {
    guard revision.status == "complete" else {
      return failure(
        "visible_card_revision_incomplete",
        "The visible-card revision is not complete.", [:],
        sourceRevision: revision.stageID)
    }
    let observations = try observations(from: revision)
    return try calibrate(
      recordingID: revision.recordingID, visibleCardRevisionID: revision.stageID,
      observations: observations)
  }

  /// Select and validate one recording calibration from a frozen visible-card revision.
  /// Candidate mask-quality filtering must be completed by the visible-card adapter before this call.
  public static func calibrate(
    recordingID: String, visibleCardRevisionID: String,
    observations: [DeviceCalibrationObservation], sizeReferenceInputDigest: String? = nil
  ) throws -> DeviceRecordingCalibrationResult {
    guard !recordingID.isEmpty, !visibleCardRevisionID.isEmpty,
      observations.allSatisfy({
        !$0.candidateID.isEmpty && !$0.frameID.isEmpty && !$0.sourceTransformID.isEmpty
          && ($0.sourceRevision == nil || $0.sourceRevision == visibleCardRevisionID)
          && $0.timeS.isFinite && $0.timeS >= 0 && $0.confidence.isFinite
          && (0...1).contains($0.confidence) && $0.frameWidth > 0 && $0.frameHeight > 0
          && ($0.qualityScore == nil
            || ($0.qualityScore!.isFinite && (0...1).contains($0.qualityScore!)))
          && $0.qualityMetrics.values.allSatisfy(\.isFinite)
      }), Set(observations.map(\.candidateID)).count == observations.count
    else { throw DeviceRecordingCalibrationError.invalidInput }

    guard !observations.isEmpty else {
      return failure("insufficient_candidates", "No card candidates were provided.", [:])
    }

    guard let first = observations.first,
      observations.allSatisfy({
        $0.frameWidth == first.frameWidth && $0.frameHeight == first.frameHeight
          && $0.sourceTransformID == first.sourceTransformID
      })
    else { throw DeviceRecordingCalibrationError.inconsistentRecording }

    var decisions = Dictionary(
      uniqueKeysWithValues: observations.map { ($0.candidateID, "accepted") })
    let qualityPassed = observations.filter { item in
      let reason: String?
      if item.quadrilateral.count != 4 {
        reason = "invalid_geometry"
      } else if (item.boundarySamples ?? item.quadrilateral).contains(where: {
        $0.x <= 2 || $0.y <= 2 || $0.x >= Double(item.frameWidth - 2)
          || $0.y >= Double(item.frameHeight - 2)
      }) {
        reason = "frame_boundary"
      } else if item.confidence < confidenceThreshold {
        reason = "confidence_below_threshold"
      } else if (item.qualityMetrics["boundary_straightness"] ?? 1) < 0.55 {
        reason = "unstable_boundary"
      } else if (item.qualityMetrics["corner_support"] ?? 1) < 0.50 {
        reason = "weak_corner_support"
      } else if (item.qualityMetrics["maximum_inward_defect_over_short_side"] ?? 0) > 0.12
        && 1 - (item.qualityMetrics["convexity"] ?? 1) > 0.06
      {
        reason = "localized_inward_notch"
      } else {
        reason = nil
      }
      if let reason { decisions[item.candidateID] = "rejected:\(reason)" }
      return reason == nil
    }
    var confident: [DeviceCalibrationObservation] = []
    for item in qualityPassed.sorted(by: qualityRank) {
      let peers = confident.filter { $0.frameID == item.frameID }
      if peers.contains(where: { overlapFraction(item.quadrilateral, $0.quadrilateral) > 0.12 }) {
        decisions[item.candidateID] = "rejected:overlaps_prediction"
      } else {
        confident.append(item)
      }
    }
    for item in confident {
      let itemCenter = center(item.quadrilateral)
      var nearby: [(distance: Double, item: DeviceCalibrationObservation)] = []
      for other in confident where other.candidateID != item.candidateID {
        let otherCenter = center(other.quadrilateral)
        let normalizedX = (itemCenter.x - otherCenter.x) / Double(item.frameWidth)
        let normalizedY = (itemCenter.y - otherCenter.y) / Double(item.frameHeight)
        let neighborDistance = hypot(normalizedX, normalizedY)
        if neighborDistance <= 0.30 {
          nearby.append((neighborDistance, other))
        }
      }
      nearby.sort {
        $0.distance == $1.distance
          ? $0.item.candidateID < $1.item.candidateID : $0.distance < $1.distance
      }
      nearby = Array(nearby.prefix(5))
      if nearby.count >= 3 {
        let scales = nearby.map { log(max(polygonArea($0.item.quadrilateral), 1)) / 2 }.sorted()
        let medianScale = scales[scales.count / 2]
        let deviation = log(max(polygonArea(item.quadrilateral), 1)) / 2 - medianScale
        if abs(deviation) > 0.30 {
          decisions[item.candidateID] = "rejected:inconsistent_apparent_card_scale"
        }
      }
    }
    confident.removeAll { decisions[$0.candidateID] != "accepted" }
    confident = cap(
      confident, key: \.frameID, limit: 4, reason: "frame_observation_cap", decisions: &decisions)
    confident = cap(
      confident, key: { bin($0, temporal: true) }, limit: 8,
      reason: "temporal_bin_observation_cap", decisions: &decisions)
    var seenBins = Set<String>()
    confident = confident.sorted(by: qualityRank).filter { item in
      let key = [
        bin(item, temporal: true), bin(item, temporal: false),
        item.scaleBin ?? "s-0", item.orientationBin ?? "o-0",
      ].joined(separator: "|")
      guard seenBins.insert(key).inserted else {
        decisions[item.candidateID] = "rejected:duplicate_bin_lower_quality"
        return false
      }
      return true
    }
    var positionCounts: [String: Int] = [:]
    confident = confident.filter { item in
      let position = bin(item, temporal: false)
      guard positionCounts[position, default: 0] < 8 else {
        decisions[item.candidateID] = "rejected:position_bin_observation_cap"
        return false
      }
      positionCounts[position, default: 0] += 1
      return true
    }
    confident.sort { $0.candidateID < $1.candidateID }
    guard confident.count >= minimumCandidates else {
      return failure(
        "insufficient_candidates", "Too few high-confidence card candidates.", decisions,
        observations: observations, sourceRevision: visibleCardRevisionID)
    }

    let ordered = confident.sorted {
      (bin($0, temporal: true), bin($0, temporal: false), $0.candidateID)
        < (bin($1, temporal: true), bin($1, temporal: false), $1.candidateID)
    }
    let heldOut = ordered.enumerated().filter { $0.offset % holdoutModulus == 0 }.map(\.element)
    let fitting = ordered.enumerated().filter { $0.offset % holdoutModulus != 0 }.map(\.element)
    guard heldOut.count >= minimumHeldOutCandidates, !fitting.isEmpty else {
      return failure(
        "insufficient_validation_population", "Too few independent held-out candidates.", decisions,
        observations: observations, sourceRevision: visibleCardRevisionID)
    }
    let trainingFit = try? DeviceTablePlaneFit.fitTablePlane(
      fitting.map(\.quadrilateral),
      boundarySamples: fitting.map { $0.boundarySamples ?? [] }.enumerated().allSatisfy {
        $0.element.isEmpty
      }
        ? nil : fitting.map { $0.boundarySamples ?? [] },
      observationWeights: fitting.map { max($0.qualityScore ?? $0.confidence, 0.01) })
    guard let trainingFit else {
      return failure(
        "calibration_fit_failed", "The table-plane fit did not produce a finite candidate.",
        decisions, observations: observations, sourceRevision: visibleCardRevisionID)
    }

    let inlierIDs = Set(
      trainingFit.inlierIndices.compactMap {
        fitting.indices.contains($0) ? fitting[$0].candidateID : nil
      })
    for item in fitting where !inlierIDs.contains(item.candidateID) {
      decisions[item.candidateID] = "rejected:fit_outlier"
    }
    let fitAccepted = fitting.filter { inlierIDs.contains($0.candidateID) }
    guard fitAccepted.count >= minimumCandidates else {
      return failure(
        "insufficient_candidates", "Too few candidates remain after outlier rejection.", decisions,
        trainingFit, observations: observations, sourceRevision: visibleCardRevisionID)
    }

    let heldOutMeasurements = heldOut.compactMap {
      item -> (DeviceCalibrationObservation, BoundaryMetrics)? in
      guard
        let metrics = boundaryMetrics(
          item, imageToTable: trainingFit.imageToTable,
          tableToImage: trainingFit.tableToImage)
      else { return nil }
      return (item, metrics)
    }
    let heldOutPasses = heldOutMeasurements.filter {
      $0.1.medianDistance <= 2 && $0.1.p90OverShortSide <= 0.08
    }
    for item in heldOut
    where !heldOutPasses.contains(where: { $0.0.candidateID == item.candidateID }) {
      decisions[item.candidateID] = "rejected:held_out_boundary"
    }
    let selected = (fitAccepted + heldOutPasses.map(\.0)).sorted {
      $0.candidateID < $1.candidateID
    }
    let temporalBins = Set(selected.map { bin($0, temporal: true) })
    let positionBins = Set(selected.map { bin($0, temporal: false) })
    let orientationBins = Set(
      selected.compactMap { item -> Int? in
        guard let q = try? DeviceCardPlaneGeometry.cyclicQuadrilateral(item.quadrilateral),
          let vectors = try? DeviceCardPlaneGeometry.cardVectors(q)
        else { return nil }
        let angle = atan2(vectors.short.y, vectors.short.x) * 180 / .pi
        return Int(floor((angle + 180) / 15))
      })
    guard temporalBins.count >= minimumTemporalBins,
      positionBins.count >= minimumPositionBins,
      orientationBins.count >= minimumOrientationBins
    else {
      return failure(
        "insufficient_diversity",
        "Candidates do not cover enough time, table position, and orientation.", decisions,
        trainingFit, observations: observations, sourceRevision: visibleCardRevisionID)
    }
    let centers = selected.map {
      (
        $0.quadrilateral.map(\.x).reduce(0, +) / 4,
        $0.quadrilateral.map(\.y).reduce(0, +) / 4
      )
    }
    let coverageX = centers.map(\.0).max()! - centers.map(\.0).min()!
    let coverageY = centers.map(\.1).max()! - centers.map(\.1).min()!
    let gates: [String: Bool] = [
      "fit_quality": trainingFit.qualityPassed,
      "candidate_count": selected.count >= minimumCandidates,
      "temporal_diversity": temporalBins.count >= minimumTemporalBins,
      "table_position_diversity": positionBins.count >= minimumPositionBins,
      "orientation_diversity": orientationBins.count >= minimumOrientationBins,
      "spatial_coverage": coverageX / Double(first.frameWidth) >= 0.25
        && coverageY / Double(first.frameHeight) >= 0.25,
      "held_out_population": heldOut.count >= minimumHeldOutCandidates,
      "held_out_boundary": !heldOut.isEmpty
        && Double(heldOutPasses.count) / Double(heldOut.count) >= 0.60,
    ]
    let advisoryGates: Set<String> = ["spatial_coverage", "held_out_boundary"]
    let failedGates = gates.filter { !$0.value && !advisoryGates.contains($0.key) }
    guard failedGates.isEmpty else {
      return failure(
        "inconsistent_card_geometry", "Fit quality or held-out validation did not pass.", decisions,
        trainingFit, gates, observations: observations, sourceRevision: visibleCardRevisionID)
    }

    let candidateEvidence = evidence(
      observations, decisions: decisions,
      fitIDs: Set(fitAccepted.map(\.candidateID)),
      heldOutIDs: Set(heldOut.map(\.candidateID)), sourceRevision: visibleCardRevisionID)
    let acceptedReceiptDigests = candidateEvidence.filter(\.accepted).map(\.receiptDigest)
    let calibrationRevisionID =
      "calibration-"
      + String(
        digest([
          "recording_id": recordingID,
          "source_revision": visibleCardRevisionID,
          "geometry_algorithm_version": "card-plane-geometry/v6",
          "transform_serialization": "float64/v1",
          "recipe_digest": recipeDigest,
          "candidate_receipt_digests": acceptedReceiptDigests,
          "size_reference_input_digest": sizeReferenceInputDigest as Any? ?? NSNull(),
        ]).prefix(24))
    return DeviceRecordingCalibrationResult(
      status: "published", failureCode: nil, failureMessage: nil, candidateDecisions: decisions,
      candidateEvidence: candidateEvidence,
      gates: gates,
      fitCandidateIDs: fitting.filter { inlierIDs.contains($0.candidateID) }.map(\.candidateID),
      heldOutCandidateIDs: heldOut.map(\.candidateID),
      fitResult: trainingFit,
      calibration: DeviceRecordingCalibration(
        calibrationRevisionID: calibrationRevisionID,
        recordingID: recordingID, visibleCardRevisionID: visibleCardRevisionID,
        frameWidth: first.frameWidth, frameHeight: first.frameHeight,
        imageToTable: trainingFit.imageToTable, tableToImage: trainingFit.tableToImage,
        cardShortSize: 1, cardLongSize: DeviceCardPlaneGeometry.cardAspectRatio,
        acceptedCandidateIDs: selected.map(\.candidateID),
        schemaVersion: "table-plane-calibration/v1",
        geometryAlgorithmVersion: "card-plane-geometry/v6",
        coordinateSystem: DeviceCardPlaneGeometry.coordinateSystem,
        cornerOrder: DeviceCardPlaneGeometry.cornerOrder,
        angleConvention: DeviceCardPlaneGeometry.angleConvention,
        recipeDigest: recipeDigest,
        candidateReceiptDigests: acceptedReceiptDigests))
  }

  private static func failure(
    _ code: String, _ message: String, _ decisions: [String: String],
    _ fit: DeviceTablePlaneFitResult? = nil, _ gates: [String: Bool] = [:],
    observations: [DeviceCalibrationObservation] = [], sourceRevision: String = ""
  ) -> DeviceRecordingCalibrationResult {
    DeviceRecordingCalibrationResult(
      status: "failed", failureCode: code, failureMessage: message,
      candidateDecisions: decisions,
      candidateEvidence: evidence(
        observations, decisions: decisions, fitIDs: [], heldOutIDs: [],
        sourceRevision: sourceRevision),
      gates: gates,
      fitCandidateIDs: [], heldOutCandidateIDs: [],
      fitResult: fit, calibration: nil)
  }

  private static func observations(from revision: DeviceVisibleCardRevision) throws
    -> [DeviceCalibrationObservation]
  {
    var result: [DeviceCalibrationObservation] = []
    for eventResult in revision.events where eventResult.status == "complete" {
      guard eventResult.frameMapping.status == "mapped",
        let frameID = eventResult.frameMapping.frameIndex.map({ "frame-\($0)" }),
        let timeS = eventResult.frameMapping.actualTimeS,
        let width = eventResult.imageWidth, let height = eventResult.imageHeight
      else { continue }
      let transformID = "oriented-video-frame-v1-\(width)x\(height)"
      for (index, detection) in eventResult.detections.enumerated()
      where detection.className == "visible_card" {
        guard let polygon = detection.polygon, polygon.count >= 4 else { continue }
        let boundary = try polygon.map { point -> DevicePoint2D in
          guard point.count == 2 else { throw DeviceRecordingCalibrationError.invalidInput }
          return try DevicePoint2D(
            x: Double(point[0]) * Double(width) / 1_000,
            y: Double(point[1]) * Double(height) / 1_000)
        }
        let quad = try fitQuadrilateral(boundary)
        let samples = try uniformSamples(boundary, count: 64)
        let centerX = quad.map(\.x).reduce(0, +) / 4
        let centerY = quad.map(\.y).reduce(0, +) / 4
        let vectors = try DeviceCardPlaneGeometry.cardVectors(quad)
        let angle = atan2(vectors.short.y, vectors.short.x) * 180 / .pi
        let area = polygonArea(quad)
        let scale = Int(floor(log2(max(sqrt(area), 1)) / 0.25))
        let orientation = Int(floor((angle + 180) / 15))
        let metrics = polygonQuality(boundary, quad: quad)
        let geometryScore =
          0.30 * (metrics["mask_quad_iou"] ?? 0)
          + 0.15 * (metrics["quad_mask_coverage"] ?? 0)
          + 0.15 * (metrics["convexity"] ?? 0)
          + 0.20 * (metrics["boundary_straightness"] ?? 0)
          + 0.10 * (metrics["corner_support"] ?? 0)
          + 0.10 * (metrics["component_dominance"] ?? 0)
        result.append(
          DeviceCalibrationObservation(
            candidateID: "\(eventResult.event.eventID)-card-\(index)",
            frameID: frameID, timeS: timeS, frameWidth: width, frameHeight: height,
            sourceTransformID: transformID, confidence: detection.score,
            quadrilateral: quad, boundarySamples: samples,
            qualityScore: 0.85 * geometryScore + 0.15 * detection.score,
            qualityMetrics: metrics,
            temporalBin: "t-\(Int(floor(timeS)))",
            tablePositionBin:
              "p-\(Int(centerX / Double(width) * 8))-\(Int(centerY / Double(height) * 8))",
            scaleBin: "s-\(scale)", orientationBin: "o-\(orientation)",
            sourceRevision: revision.stageID))
      }
    }
    return result
  }

  private static func fitQuadrilateral(_ points: [DevicePoint2D]) throws -> [DevicePoint2D] {
    guard points.count >= 4 else { throw DeviceRecordingCalibrationError.invalidInput }
    let hull = convexHull(points)
    guard hull.count >= 3 else { throw DeviceRecordingCalibrationError.invalidInput }
    let closedPerimeter = zip(hull, hull.dropFirst() + [hull[0]]).reduce(0.0) {
      $0 + distance($1.0, $1.1)
    }
    let approximations: [[DevicePoint2D]] =
      [0.005, 0.01, 0.02, 0.04, 0.08, 0.12].compactMap { fraction in
        let approximation = approximateClosedPolygon(hull, tolerance: fraction * closedPerimeter)
        guard approximation.count == 4, polygonArea(approximation) > 0 else { return nil }
        return approximation
      }
    if let quadrilateral = approximations.max(by: { polygonArea($0) < polygonArea($1) }) {
      return try DeviceCardPlaneGeometry.cyclicQuadrilateral(quadrilateral)
    }

    var best: (area: Double, points: [DevicePoint2D])?
    for index in hull.indices {
      let first = hull[index]
      let second = hull[(index + 1) % hull.count]
      let angle = atan2(second.y - first.y, second.x - first.x)
      let cosine = cos(angle)
      let sine = sin(angle)
      let rotated = try hull.map { point in
        try DevicePoint2D(
          x: point.x * cosine + point.y * sine,
          y: -point.x * sine + point.y * cosine)
      }
      let minimumX = rotated.map(\.x).min()!
      let maximumX = rotated.map(\.x).max()!
      let minimumY = rotated.map(\.y).min()!
      let maximumY = rotated.map(\.y).max()!
      let area = (maximumX - minimumX) * (maximumY - minimumY)
      if best == nil || area < best!.area {
        let corners = try [
          DevicePoint2D(x: minimumX, y: minimumY),
          DevicePoint2D(x: maximumX, y: minimumY),
          DevicePoint2D(x: maximumX, y: maximumY),
          DevicePoint2D(x: minimumX, y: maximumY),
        ].map { point in
          try DevicePoint2D(
            x: point.x * cosine - point.y * sine,
            y: point.x * sine + point.y * cosine)
        }
        best = (area, corners)
      }
    }
    guard let best, best.area > 0 else { throw DeviceRecordingCalibrationError.invalidInput }
    return try DeviceCardPlaneGeometry.cyclicQuadrilateral(best.points)
  }

  private static func approximateClosedPolygon(
    _ points: [DevicePoint2D], tolerance: Double
  ) -> [DevicePoint2D] {
    guard points.count > 4 else { return points }
    let firstFarthest =
      points.indices.max { distance(points[0], points[$0]) < distance(points[0], points[$1]) } ?? 0
    let secondFarthest =
      points.indices.max {
        distance(points[firstFarthest], points[$0]) < distance(points[firstFarthest], points[$1])
      } ?? firstFarthest
    func arc(_ start: Int, _ end: Int) -> [DevicePoint2D] {
      var result = [points[start]]
      var index = start
      while index != end {
        index = (index + 1) % points.count
        result.append(points[index])
      }
      return result
    }
    func simplify(_ line: [DevicePoint2D]) -> [DevicePoint2D] {
      guard line.count > 2 else { return line }
      let start = line[0]
      let end = line[line.count - 1]
      func distanceToLine(_ point: DevicePoint2D) -> Double {
        let dx = end.x - start.x
        let dy = end.y - start.y
        let fraction = min(
          1,
          max(
            0,
            ((point.x - start.x) * dx + (point.y - start.y) * dy)
              / max(dx * dx + dy * dy, 1e-12)))
        return hypot(point.x - (start.x + fraction * dx), point.y - (start.y + fraction * dy))
      }
      let split = line.indices.dropFirst().dropLast().max {
        distanceToLine(line[$0]) < distanceToLine(line[$1])
      }
      guard let split, distanceToLine(line[split]) > tolerance else {
        return [start, end]
      }
      let left = simplify(Array(line[...split]))
      let right = simplify(Array(line[split...]))
      return Array(left.dropLast()) + right
    }
    let firstArc = simplify(arc(firstFarthest, secondFarthest))
    let secondArc = simplify(arc(secondFarthest, firstFarthest))
    return firstArc + secondArc.dropFirst().dropLast()
  }

  private static func polygonQuality(_ boundary: [DevicePoint2D], quad: [DevicePoint2D])
    -> [String: Double]
  {
    let quadArea = polygonArea(quad)
    let boundaryArea = polygonArea(boundary)
    let coverage = min(1, boundaryArea / max(quadArea, 1))
    let straightnessDistances = boundary.map { distanceToSegments($0, quad) }
    let shortSide = min(distance(quad[0], quad[1]), distance(quad[1], quad[2]))
    let straightness =
      Double(straightnessDistances.filter { $0 <= max(1.5, 0.025 * shortSide) }.count)
      / Double(max(boundary.count, 1))
    let cornerSupport =
      quad.map { corner in
        exp(-boundary.map { distance(corner, $0) }.min()! / max(0.05 * shortSide, 1))
      }.reduce(0, +) / 4
    let convexity = min(1, boundaryArea / max(polygonArea(convexHull(boundary)), 1))
    return [
      "mask_quad_iou": coverage,
      "quad_mask_coverage": coverage,
      "convexity": convexity,
      "maximum_inward_defect_over_short_side": 1 - convexity,
      "boundary_straightness": straightness,
      "corner_support": cornerSupport,
      "component_dominance": 1,
      "overlap_fraction": 0,
      "nearest_card_center_distance_over_size": 0,
      "separation_reference_available": 0,
      "local_scale_log_deviation": 0,
      "local_scale_reference_available": 0,
    ]
  }

  private static func convexHull(_ points: [DevicePoint2D]) -> [DevicePoint2D] {
    let sorted = points.sorted { ($0.x, $0.y) < ($1.x, $1.y) }
    func cross(_ origin: DevicePoint2D, _ a: DevicePoint2D, _ b: DevicePoint2D) -> Double {
      (a.x - origin.x) * (b.y - origin.y) - (a.y - origin.y) * (b.x - origin.x)
    }
    var lower: [DevicePoint2D] = []
    for point in sorted {
      while lower.count >= 2 && cross(lower[lower.count - 2], lower[lower.count - 1], point) <= 0 {
        lower.removeLast()
      }
      lower.append(point)
    }
    var upper: [DevicePoint2D] = []
    for point in sorted.reversed() {
      while upper.count >= 2 && cross(upper[upper.count - 2], upper[upper.count - 1], point) <= 0 {
        upper.removeLast()
      }
      upper.append(point)
    }
    return Array(lower.dropLast()) + Array(upper.dropLast())
  }

  private static func polygonArea(_ points: [DevicePoint2D]) -> Double {
    guard points.count >= 3 else { return 0 }
    return abs(
      zip(points, points.dropFirst() + [points[0]]).reduce(0) { sum, pair in
        sum + pair.0.x * pair.1.y - pair.1.x * pair.0.y
      }) / 2
  }

  private static func center(_ quad: [DevicePoint2D]) -> DevicePoint2D {
    let count = Double(quad.count)
    return try! DevicePoint2D(
      x: quad.map(\.x).reduce(0, +) / count,
      y: quad.map(\.y).reduce(0, +) / count)
  }

  private static func qualityRank(
    _ left: DeviceCalibrationObservation, _ right: DeviceCalibrationObservation
  ) -> Bool {
    let leftScore = left.qualityScore ?? left.confidence
    let rightScore = right.qualityScore ?? right.confidence
    if leftScore != rightScore { return leftScore > rightScore }
    if left.confidence != right.confidence { return left.confidence > right.confidence }
    return left.candidateID < right.candidateID
  }

  private static func cap(
    _ observations: [DeviceCalibrationObservation], key: (DeviceCalibrationObservation) -> String,
    limit: Int, reason: String, decisions: inout [String: String]
  ) -> [DeviceCalibrationObservation] {
    var counts: [String: Int] = [:]
    var kept: [DeviceCalibrationObservation] = []
    for item in observations.sorted(by: qualityRank) {
      let value = key(item)
      if counts[value, default: 0] >= limit {
        decisions[item.candidateID] = "rejected:\(reason)"
      } else {
        counts[value, default: 0] += 1
        kept.append(item)
      }
    }
    return kept.sorted { $0.candidateID < $1.candidateID }
  }

  private static func overlapFraction(_ left: [DevicePoint2D], _ right: [DevicePoint2D]) -> Double {
    let leftArea = polygonArea(left)
    let rightArea = polygonArea(right)
    guard min(leftArea, rightArea) > 0 else { return 0 }
    let clipper = signedArea(right) >= 0 ? right : Array(right.reversed())
    var clipped = left
    for index in clipper.indices where !clipped.isEmpty {
      let start = clipper[index]
      let end = clipper[(index + 1) % clipper.count]
      let input = clipped
      clipped = []
      var previous = input[input.count - 1]
      for current in input {
        let currentInside = cross(start, end, current) >= -1e-9
        let previousInside = cross(start, end, previous) >= -1e-9
        if currentInside != previousInside,
          let intersection = lineIntersection(
            previous, current, start, end)
        {
          clipped.append(intersection)
        }
        if currentInside { clipped.append(current) }
        previous = current
      }
    }
    return polygonArea(clipped) / min(leftArea, rightArea)
  }

  private static func cross(
    _ start: DevicePoint2D, _ end: DevicePoint2D, _ point: DevicePoint2D
  ) -> Double {
    (end.x - start.x) * (point.y - start.y) - (end.y - start.y) * (point.x - start.x)
  }

  private static func signedArea(_ points: [DevicePoint2D]) -> Double {
    guard points.count >= 3 else { return 0 }
    return zip(points, points.dropFirst() + [points[0]]).reduce(0) { sum, pair in
      sum + pair.0.x * pair.1.y - pair.1.x * pair.0.y
    } / 2
  }

  private static func lineIntersection(
    _ start: DevicePoint2D, _ end: DevicePoint2D,
    _ clipStart: DevicePoint2D, _ clipEnd: DevicePoint2D
  ) -> DevicePoint2D? {
    let dx = end.x - start.x
    let dy = end.y - start.y
    let cx = clipEnd.x - clipStart.x
    let cy = clipEnd.y - clipStart.y
    let denominator = dx * cy - dy * cx
    guard abs(denominator) > 1e-12 else { return nil }
    let fraction = ((clipStart.x - start.x) * cy - (clipStart.y - start.y) * cx) / denominator
    return try? DevicePoint2D(x: start.x + fraction * dx, y: start.y + fraction * dy)
  }

  private static func uniformSamples(_ points: [DevicePoint2D], count: Int) throws
    -> [DevicePoint2D]
  {
    let closed = points + [points[0]]
    let lengths = zip(closed, closed.dropFirst()).map { distance($0, $1) }
    let total = lengths.reduce(0, +)
    guard total > 0 else { throw DeviceRecordingCalibrationError.invalidInput }
    return try (0..<count).map { sample in
      var target = Double(sample) * total / Double(count)
      for index in lengths.indices {
        if target <= lengths[index] || index == lengths.index(before: lengths.endIndex) {
          let fraction = min(1, target / max(lengths[index], 1e-9))
          return try DevicePoint2D(
            x: closed[index].x + (closed[index + 1].x - closed[index].x) * fraction,
            y: closed[index].y + (closed[index + 1].y - closed[index].y) * fraction)
        }
        target -= lengths[index]
      }
      throw DeviceRecordingCalibrationError.invalidInput
    }
  }

  private static func bin(_ item: DeviceCalibrationObservation, temporal: Bool) -> String {
    if temporal, let value = item.temporalBin { return value }
    if !temporal, let value = item.tablePositionBin { return value }
    if temporal { return "t-\(Int(item.timeS))" }
    let centerX = item.quadrilateral.map(\.x).reduce(0, +) / 4
    let centerY = item.quadrilateral.map(\.y).reduce(0, +) / 4
    return
      "p-\(Int(centerX / Double(item.frameWidth) * 8))-\(Int(centerY / Double(item.frameHeight) * 8))"
  }

  private struct BoundaryMetrics {
    let medianDistance: Double
    let p90OverShortSide: Double
  }

  private static func boundaryMetrics(
    _ item: DeviceCalibrationObservation, imageToTable: DeviceHomography,
    tableToImage: DeviceHomography
  ) -> BoundaryMetrics? {
    let observed = item.boundarySamples ?? item.quadrilateral
    guard observed.count >= 4,
      let cyclic = try? DeviceCardPlaneGeometry.cyclicQuadrilateral(item.quadrilateral)
    else { return nil }
    let orientations = [cyclic, Array(cyclic.dropFirst()) + [cyclic[0]]]
    let mapped = orientations.compactMap { quad -> ([DevicePoint2D], Double)? in
      guard let table = try? imageToTable.apply(to: quad),
        let residual = try? DeviceCardPlaneGeometry.cardResidual(table)
      else { return nil }
      return (table, residual.angleDegrees / 10 + residual.aspect + residual.parallel)
    }.min { $0.1 < $1.1 }?.0
    guard let mapped, let vectors = try? DeviceCardPlaneGeometry.cardVectors(mapped),
      let center = try? DevicePoint2D(
        x: mapped.map(\.x).reduce(0, +) / 4, y: mapped.map(\.y).reduce(0, +) / 4),
      let projected = try? DeviceCardPlaneGeometry.projectFixedCard(
        tableToImage: tableToImage, center: center,
        rotationDegrees: atan2(vectors.short.y, vectors.short.x) * 180 / .pi,
        shortSize: 1, longSize: DeviceCardPlaneGeometry.cardAspectRatio)
    else { return nil }
    let projectedBoundary = projected.indices.flatMap { edge in
      let start = projected[edge]
      let end = projected[(edge + 1) % projected.count]
      return (0..<16).compactMap { step in
        let fraction = Double(step) / 16
        return try? DevicePoint2D(
          x: start.x + (end.x - start.x) * fraction,
          y: start.y + (end.y - start.y) * fraction)
      }
    }
    guard projectedBoundary.count == 64 else { return nil }
    let distances =
      observed.map { distanceToSegments($0, projected) }
      + projectedBoundary.map { distanceToSegments($0, observed) }
    guard distances.allSatisfy(\.isFinite) else { return nil }
    let shortSide =
      (distance(projected[0], projected[1]) + distance(projected[3], projected[2])) / 2
    guard shortSide > 0 else { return nil }
    return BoundaryMetrics(
      medianDistance: percentile(distances, 0.5),
      p90OverShortSide: percentile(distances, 0.9) / shortSide)
  }

  private static func distanceToSegments(_ point: DevicePoint2D, _ vertices: [DevicePoint2D])
    -> Double
  {
    vertices.indices.map { index in
      let start = vertices[index]
      let end = vertices[(index + 1) % vertices.count]
      let dx = end.x - start.x
      let dy = end.y - start.y
      let t = min(
        1,
        max(
          0,
          ((point.x - start.x) * dx + (point.y - start.y) * dy)
            / max(dx * dx + dy * dy, 1e-12)))
      return hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy))
    }.min() ?? .infinity
  }

  private static func distance(_ lhs: DevicePoint2D, _ rhs: DevicePoint2D) -> Double {
    hypot(lhs.x - rhs.x, lhs.y - rhs.y)
  }

  private static func percentile(_ values: [Double], _ fraction: Double) -> Double {
    let sorted = values.sorted()
    guard sorted.count > 1 else { return sorted.first ?? .infinity }
    let position = Double(sorted.count - 1) * fraction
    let lower = Int(position)
    let upper = min(lower + 1, sorted.count - 1)
    let weight = position - Double(lower)
    return sorted[lower] * (1 - weight) + sorted[upper] * weight
  }

  private static func evidence(
    _ observations: [DeviceCalibrationObservation], decisions: [String: String],
    fitIDs: Set<String>, heldOutIDs: Set<String>, sourceRevision: String
  ) -> [DeviceCalibrationCandidateEvidence] {
    observations.sorted { $0.candidateID < $1.candidateID }.map { item in
      let decision = decisions[item.candidateID] ?? "rejected:unknown"
      let fitDecision =
        fitIDs.contains(item.candidateID)
        ? "fit_inlier"
        : heldOutIDs.contains(item.candidateID) && decision == "accepted"
          ? "held_out_pass"
          : decision == "accepted" ? "selector_rejected:not_selected" : decision
      let accepted =
        fitIDs.contains(item.candidateID)
        || (heldOutIDs.contains(item.candidateID) && decision == "accepted")
      let rejectionReason =
        accepted
        ? nil
        : fitDecision.hasPrefix("rejected:")
          ? String(fitDecision.dropFirst("rejected:".count)) : "not_selected"
      var metrics = item.qualityMetrics
      metrics["quality_score"] = item.qualityScore ?? item.confidence
      let temporal = item.temporalBin ?? bin(item, temporal: true)
      let position = item.tablePositionBin ?? bin(item, temporal: false)
      let scale = item.scaleBin ?? "s-0"
      let orientation = item.orientationBin ?? "o-0"
      let revision = item.sourceRevision ?? sourceRevision
      let roundedMetrics = metrics.mapValues(round6)
      let roundedQuad = item.quadrilateral.map { [round6($0.x), round6($0.y)] }
      let roundedBoundary = (item.boundarySamples ?? []).map { [round6($0.x), round6($0.y)] }
      let receiptCore: [String: Any] = [
        "schema_version": "table-plane-calibration-candidate/v2",
        "candidate_id": item.candidateID,
        "source_revision": revision,
        "source_frame_id": item.frameID,
        "confidence": round6(item.confidence),
        "quadrilateral": roundedQuad,
        "boundary_samples": roundedBoundary,
        "quality_metrics": roundedMetrics,
        "temporal_bin": temporal,
        "table_position_bin": position,
        "scale_bin": scale,
        "orientation_bin": orientation,
        "accepted": accepted,
        "rejection_reason": rejectionReason as Any? ?? NSNull(),
      ]
      return DeviceCalibrationCandidateEvidence(
        candidateID: item.candidateID,
        sourceRevision: revision,
        sourceFrameID: item.frameID,
        confidence: item.confidence,
        quadrilateral: item.quadrilateral,
        boundarySamples: item.boundarySamples ?? [],
        qualityMetrics: metrics,
        qualityScore: item.qualityScore ?? item.confidence,
        decision: fitDecision,
        temporalBin: temporal,
        tablePositionBin: position,
        scaleBin: scale,
        orientationBin: orientation,
        accepted: accepted,
        rejectionReason: rejectionReason,
        receiptDigest: sha256(canonicalJSON(receiptCore)))
    }
  }

  fileprivate static func round6(_ value: Double) -> Double {
    (value * 1_000_000).rounded(.toNearestOrEven) / 1_000_000
  }

  private static func sha256(_ text: String) -> String {
    SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
  }

  fileprivate static func digest(_ value: Any) -> String {
    sha256(canonicalJSON(value))
  }

  private static func canonicalJSON(_ value: Any) -> String {
    if value is NSNull { return "null" }
    if let string = value as? String { return jsonString(string) }
    if let number = value as? NSNumber {
      if CFGetTypeID(number) == CFBooleanGetTypeID() { return number.boolValue ? "true" : "false" }
      let type = String(cString: number.objCType)
      return type == "d" || type == "f" ? String(number.doubleValue) : number.stringValue
    }
    if let array = value as? [Any] {
      return "[" + array.map(canonicalJSON).joined(separator: ",") + "]"
    }
    if let object = value as? [String: Any] {
      return "{"
        + object.keys.sorted().map {
          jsonString($0) + ":" + canonicalJSON(object[$0]!)
        }.joined(separator: ",") + "}"
    }
    return "null"
  }

  private static func jsonString(_ value: String) -> String {
    let data = try! JSONSerialization.data(
      withJSONObject: [value], options: [.fragmentsAllowed, .withoutEscapingSlashes])
    let encoded = String(data: data, encoding: .utf8)!
    return String(encoded.dropFirst().dropLast())
  }

}
