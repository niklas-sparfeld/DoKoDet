import Foundation

/// One frozen, reviewable card observation used by calibration refinement.
public struct DeviceCalibrationAnchor: Equatable, Sendable {
  public let anchorID: String
  public let cardID: String
  public let frameID: String
  public let frameDigest: String
  public let quadrilateral: [DevicePoint2D]
  public let confidence: Double
  public let temporalBin: String
  public let tableRegionBin: String
  public let scaleBin: String
  public let orientationBin: String
  public let eligible: Bool
  public let eligibilityReason: String?
  public let state: String
  public let weightClass: String

  public init(
    anchorID: String, cardID: String, frameID: String, frameDigest: String,
    quadrilateral: [DevicePoint2D], confidence: Double, temporalBin: String,
    tableRegionBin: String, scaleBin: String, orientationBin: String, eligible: Bool,
    eligibilityReason: String? = nil, state: String = "candidate", weightClass: String = "candidate"
  ) {
    self.anchorID = anchorID
    self.cardID = cardID
    self.frameID = frameID
    self.frameDigest = frameDigest
    self.quadrilateral = quadrilateral
    self.confidence = confidence
    self.temporalBin = temporalBin
    self.tableRegionBin = tableRegionBin
    self.scaleBin = scaleBin
    self.orientationBin = orientationBin
    self.eligible = eligible
    self.eligibilityReason = eligibilityReason
    self.state = state
    self.weightClass = weightClass
  }
}

/// Frozen refinement inputs tied to one calibration and one visible-card revision.
public struct DeviceCalibrationRefinementDraft: Equatable, Sendable {
  public let draftID: String
  public let detectorRevisionID: String
  public let detectorRevisionDigest: String
  public let baseCalibrationRevisionID: String
  public let baseCalibrationDigest: String
  public let sourceFrameDigests: [String: String]
  public let anchors: [DeviceCalibrationAnchor]

  public init(
    draftID: String, detectorRevisionID: String, detectorRevisionDigest: String,
    baseCalibrationRevisionID: String, baseCalibrationDigest: String,
    sourceFrameDigests: [String: String], anchors: [DeviceCalibrationAnchor]
  ) {
    self.draftID = draftID
    self.detectorRevisionID = detectorRevisionID
    self.detectorRevisionDigest = detectorRevisionDigest
    self.baseCalibrationRevisionID = baseCalibrationRevisionID
    self.baseCalibrationDigest = baseCalibrationDigest
    self.sourceFrameDigests = sourceFrameDigests
    self.anchors = anchors
  }
}

public struct DeviceCalibrationRefinementGate: Equatable, Sendable {
  public let id: String
  public let passed: Bool
  public let observed: Double
  public let threshold: Double
}

public struct DeviceCalibrationPreview: Equatable, Sendable {
  public let draftID: String
  public let detectorRevisionID: String
  public let detectorRevisionDigest: String
  public let sourceFrameDigests: [String: String]
  public let status: String
  public let failureCode: String?
  public let baseCalibrationRevisionID: String
  public let baseCalibrationDigest: String
  public let fitResult: DeviceTablePlaneFitResult?
  public let gates: [DeviceCalibrationRefinementGate]
  public let eligibleAnchorIDs: [String]
  public let deduplicatedAnchorIDs: [String]
  public let acceptedAnchorCount: Int
  public let rejectedCandidateCount: Int
  public let fitResidual: Double
  public let heldOutAlignmentChangePixels: Double
  public let maximumSceneDisplacementPixels: Double
  public let changedFrameIDs: [String]
  public let changedCardIDs: [String]
}

public struct DeviceCalibrationFrameScene: Equatable, Sendable {
  public let frameID: String
  public let reviewed: Bool
  public let poses: [DeviceCalibrationScenePose]

  public init(frameID: String, reviewed: Bool, poses: [DeviceCalibrationScenePose]) {
    self.frameID = frameID
    self.reviewed = reviewed
    self.poses = poses
  }
}

public struct DeviceCalibrationScenePose: Equatable, Sendable {
  public let cardID: String
  public let center: DevicePoint2D
  public let rotationDegrees: Double

  public init(cardID: String, center: DevicePoint2D, rotationDegrees: Double) {
    self.cardID = cardID
    self.center = center
    self.rotationDegrees = rotationDegrees
  }
}

/// Calculates a deterministic preview. It does not write or replace the base calibration.
public enum DeviceCalibrationRefinement {
  public static let minimumEligibleAnchors = 3
  public static let maximumFitResidual = 0.08
  public static let maximumHeldOutAlignmentChangePixels = 8.0
  public static let maximumReviewedDisplacementPixels = 12.0
  public static let maximumProposedDisplacementPixels = 24.0

  public static func preview(
    draft: DeviceCalibrationRefinementDraft, base: DeviceRecordingCalibration,
    frameScenes: [DeviceCalibrationFrameScene] = []
  ) throws -> DeviceCalibrationPreview {
    let baseDigest = base.calibrationDigest
    let anchors = draft.anchors
    guard !draft.draftID.isEmpty, !draft.detectorRevisionID.isEmpty,
      !draft.detectorRevisionDigest.isEmpty,
      draft.detectorRevisionID == base.visibleCardRevisionID,
      draft.sourceFrameDigests.allSatisfy({ !$0.key.isEmpty && !$0.value.isEmpty })
    else { throw DeviceRecordingCalibrationError.invalidInput }
    let lineageMatches =
      draft.baseCalibrationRevisionID == base.calibrationRevisionID
      && draft.baseCalibrationDigest == baseDigest
      && anchors.allSatisfy { draft.sourceFrameDigests[$0.frameID] == $0.frameDigest }
    if !lineageMatches {
      return DeviceCalibrationPreview(
        draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
        detectorRevisionDigest: draft.detectorRevisionDigest,
        sourceFrameDigests: draft.sourceFrameDigests,
        status: "blocked", failureCode: "stale_calibration_revision",
        baseCalibrationRevisionID: base.calibrationRevisionID, baseCalibrationDigest: baseDigest,
        fitResult: nil, gates: [], eligibleAnchorIDs: [], deduplicatedAnchorIDs: [],
        acceptedAnchorCount: 0, rejectedCandidateCount: 0, fitResidual: 0,
        heldOutAlignmentChangePixels: 0,
        maximumSceneDisplacementPixels: 0, changedFrameIDs: [], changedCardIDs: [])
    }
    let eligible = anchors.filter { $0.eligible && $0.state != "excluded" }
    guard
      anchors.allSatisfy({
        !$0.anchorID.isEmpty && !$0.frameID.isEmpty && !$0.frameDigest.isEmpty
          && $0.confidence.isFinite && $0.confidence >= 0 && $0.quadrilateral.count == 4
          && ["candidate", "accepted", "adjusted", "pinned", "excluded"].contains($0.state)
          && ["candidate", "accepted", "adjusted"].contains($0.weightClass)
          && ($0.eligible ? $0.eligibilityReason == nil : $0.eligibilityReason != nil)
          && ($0.eligible || !["accepted", "adjusted", "pinned"].contains($0.state))
      }), Set(anchors.map(\.anchorID)).count == anchors.count
    else {
      throw DeviceRecordingCalibrationError.invalidInput
    }
    guard anchors.allSatisfy({ $0.quadrilateral.allSatisfy { $0.x.isFinite && $0.y.isFinite } })
    else { throw DeviceRecordingCalibrationError.invalidInput }

    let pinnedBuckets = Dictionary(grouping: anchors.filter { $0.state == "pinned" }) {
      [$0.temporalBin, $0.tableRegionBin, $0.scaleBin, $0.orientationBin].joined(
        separator: "\u{1f}")
    }
    let hasPinnedConflict = pinnedBuckets.values.contains { values in
      values.indices.contains { left in
        values.indices.contains { right in
          right > left
            && zip(values[left].quadrilateral, values[right].quadrilateral)
              .map(distance).max().map { $0 > 2.0 } == true
        }
      }
    }
    if hasPinnedConflict {
      return DeviceCalibrationPreview(
        draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
        detectorRevisionDigest: draft.detectorRevisionDigest,
        sourceFrameDigests: draft.sourceFrameDigests,
        status: "blocked", failureCode: "conflicting_pinned_anchors",
        baseCalibrationRevisionID: base.calibrationRevisionID, baseCalibrationDigest: baseDigest,
        fitResult: nil, gates: [], eligibleAnchorIDs: eligible.map(\.anchorID).sorted(),
        deduplicatedAnchorIDs: [], acceptedAnchorCount: acceptedCount(anchors),
        rejectedCandidateCount: anchors.filter { $0.state == "excluded" }.count,
        fitResidual: 0, heldOutAlignmentChangePixels: 0, maximumSceneDisplacementPixels: 0,
        changedFrameIDs: [], changedCardIDs: [])
    }

    let rank = ["candidate": 0, "accepted": 1, "adjusted": 2, "pinned": 3, "excluded": -1]
    let buckets = Dictionary(grouping: eligible) {
      [$0.temporalBin, $0.tableRegionBin, $0.scaleBin, $0.orientationBin].joined(
        separator: "\u{1f}")
    }
    let orderedKeys = buckets.keys.sorted()
    let selected = orderedKeys.compactMap { key in
      buckets[key]?.sorted {
        let leftRank = rank[$0.state, default: -1]
        let rightRank = rank[$1.state, default: -1]
        if leftRank != rightRank { return leftRank > rightRank }
        let leftWeight = weight($0)
        let rightWeight = weight($1)
        if leftWeight != rightWeight { return leftWeight > rightWeight }
        if $0.confidence != $1.confidence { return $0.confidence > $1.confidence }
        return $0.anchorID < $1.anchorID
      }.first
    }
    let rejected = eligible.map(\.anchorID).filter { id in
      !selected.contains(where: { $0.anchorID == id })
    }.sorted()
    guard selected.count >= minimumEligibleAnchors else {
      return DeviceCalibrationPreview(
        draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
        detectorRevisionDigest: draft.detectorRevisionDigest,
        sourceFrameDigests: draft.sourceFrameDigests,
        status: "blocked", failureCode: "insufficient_anchors",
        baseCalibrationRevisionID: base.calibrationRevisionID, baseCalibrationDigest: baseDigest,
        fitResult: nil, gates: [], eligibleAnchorIDs: eligible.map(\.anchorID).sorted(),
        deduplicatedAnchorIDs: rejected, acceptedAnchorCount: acceptedCount(anchors),
        rejectedCandidateCount: rejected.count + anchors.filter { $0.state == "excluded" }.count,
        fitResidual: 0, heldOutAlignmentChangePixels: 0, maximumSceneDisplacementPixels: 0,
        changedFrameIDs: [], changedCardIDs: [])
    }

    let frameTotals = Dictionary(grouping: selected, by: \.frameID).mapValues {
      $0.reduce(0) { $0 + weight($1) }
    }
    let regionTotals = Dictionary(grouping: selected, by: \.tableRegionBin).mapValues {
      $0.reduce(0) { $0 + weight($1) }
    }
    let weights = selected.map { anchor -> Double in
      let baseWeight = weight(anchor)
      let frameScale = min(1, 24 / (frameTotals[anchor.frameID] ?? 24))
      let regionScale = min(1, 24 / (regionTotals[anchor.tableRegionBin] ?? 24))
      return baseWeight * min(frameScale, regionScale)
    }
    let fit = try DeviceTablePlaneFit.fitTablePlane(
      selected.map(\.quadrilateral), observationWeights: weights)
    let residuals = eligible.map { residual($0, imageToTable: fit.imageToTable) }
    let fitResidual = median(residuals)
    let pinnedFailures = anchors.filter {
      $0.state == "pinned" && residual($0, imageToTable: fit.imageToTable) > maximumFitResidual
    }
    if !pinnedFailures.isEmpty {
      return DeviceCalibrationPreview(
        draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
        detectorRevisionDigest: draft.detectorRevisionDigest,
        sourceFrameDigests: draft.sourceFrameDigests,
        status: "blocked", failureCode: "conflicting_pinned_anchors",
        baseCalibrationRevisionID: base.calibrationRevisionID, baseCalibrationDigest: baseDigest,
        fitResult: nil, gates: [], eligibleAnchorIDs: eligible.map(\.anchorID).sorted(),
        deduplicatedAnchorIDs: rejected, acceptedAnchorCount: acceptedCount(anchors),
        rejectedCandidateCount: rejected.count + anchors.filter { $0.state == "excluded" }.count,
        fitResidual: fitResidual, heldOutAlignmentChangePixels: 0,
        maximumSceneDisplacementPixels: 0, changedFrameIDs: [], changedCardIDs: [])
    }
    let heldOut =
      eligible.filter { $0.state == "candidate" }.map { anchor -> Double in
        let before =
          (try? DeviceCardPlaneGeometry.quadrilateralOrientations(anchor.quadrilateral).first)
        guard let before else { return .infinity }
        let old = (try? base.imageToTable.apply(to: before)) ?? []
        let new = (try? fit.imageToTable.apply(to: before)) ?? []
        guard old.count == 4, new.count == 4 else { return .infinity }
        let oldPose = pose(old)
        let newPose = pose(new)
        let oldOutline =
          (try? DeviceCardPlaneGeometry.projectFixedCard(
            tableToImage: base.tableToImage, center: oldPose.center, rotationDegrees: oldPose.angle,
            shortSize: base.cardShortSize, longSize: base.cardLongSize)) ?? []
        let newOutline =
          (try? DeviceCardPlaneGeometry.projectFixedCard(
            tableToImage: fit.tableToImage, center: newPose.center, rotationDegrees: newPose.angle,
            shortSize: base.cardShortSize, longSize: base.cardLongSize)) ?? []
        return zip(oldOutline, newOutline).map(distance).max() ?? .infinity
      }.max() ?? 0

    var maxDisplacement = 0.0
    var changedFrames: [String] = []
    var changedCards: [String] = []
    var reviewedMax = 0.0
    var proposedMax = 0.0
    for scene in frameScenes {
      var frameMax = 0.0
      for card in scene.poses {
        guard
          let oldOutline = try? DeviceCardPlaneGeometry.projectFixedCard(
            tableToImage: base.tableToImage, center: card.center,
            rotationDegrees: card.rotationDegrees, shortSize: base.cardShortSize,
            longSize: base.cardLongSize),
          let mapped = try? fit.imageToTable.apply(to: oldOutline)
        else { continue }
        let newPose = pose(mapped)
        guard
          let refit = try? DeviceCardPlaneGeometry.projectFixedCard(
            tableToImage: fit.tableToImage, center: newPose.center,
            rotationDegrees: newPose.angle, shortSize: base.cardShortSize,
            longSize: base.cardLongSize)
        else { continue }
        let displacement = zip(oldOutline, refit).map(distance).max() ?? 0
        frameMax = max(frameMax, displacement)
        if displacement > 0 { changedCards.append(card.cardID) }
      }
      if frameMax > 0 {
        changedFrames.append(scene.frameID)
        maxDisplacement = max(maxDisplacement, frameMax)
        if scene.reviewed {
          reviewedMax = max(reviewedMax, frameMax)
        } else {
          proposedMax = max(proposedMax, frameMax)
        }
      }
    }
    let gates = [
      gate(
        "minimum_eligible_anchors", Double(eligible.count), Double(minimumEligibleAnchors),
        eligible.count >= minimumEligibleAnchors),
      gate("fit_residual", fitResidual, maximumFitResidual, fitResidual <= maximumFitResidual),
      gate(
        "held_out_alignment_change", heldOut, maximumHeldOutAlignmentChangePixels,
        heldOut <= maximumHeldOutAlignmentChangePixels),
      gate(
        "reviewed_displacement", reviewedMax, maximumReviewedDisplacementPixels,
        reviewedMax <= maximumReviewedDisplacementPixels),
      gate(
        "proposed_displacement", proposedMax, maximumProposedDisplacementPixels,
        proposedMax <= maximumProposedDisplacementPixels),
    ]
    let failed = gates.first(where: { !$0.passed })
    let failureCode = failed.map {
      $0.id == "reviewed_displacement"
        ? "reviewed_displacement_exceeded"
        : ($0.id == "held_out_alignment_change" ? "held_out_gate_failed" : "fit_gate_failed")
    }
    return DeviceCalibrationPreview(
      draftID: draft.draftID, detectorRevisionID: draft.detectorRevisionID,
      detectorRevisionDigest: draft.detectorRevisionDigest,
      sourceFrameDigests: draft.sourceFrameDigests,
      status: failed == nil ? "pass" : "blocked", failureCode: failureCode,
      baseCalibrationRevisionID: base.calibrationRevisionID, baseCalibrationDigest: baseDigest,
      fitResult: fit, gates: gates, eligibleAnchorIDs: eligible.map(\.anchorID).sorted(),
      deduplicatedAnchorIDs: rejected, acceptedAnchorCount: acceptedCount(anchors),
      rejectedCandidateCount: rejected.count + anchors.filter { $0.state == "excluded" }.count,
      fitResidual: fitResidual, heldOutAlignmentChangePixels: heldOut,
      maximumSceneDisplacementPixels: maxDisplacement,
      changedFrameIDs: Array(Set(changedFrames)).sorted(),
      changedCardIDs: Array(Set(changedCards)).sorted())
  }

  private static func weight(_ anchor: DeviceCalibrationAnchor) -> Double {
    switch anchor.weightClass {
    case "accepted": 4
    case "adjusted": 12
    default: 1
    }
  }
  private static func acceptedCount(_ anchors: [DeviceCalibrationAnchor]) -> Int {
    anchors.filter { ["accepted", "adjusted", "pinned"].contains($0.state) }.count
  }
  private static func gate(_ id: String, _ observed: Double, _ threshold: Double, _ passed: Bool)
    -> DeviceCalibrationRefinementGate
  {
    DeviceCalibrationRefinementGate(
      id: id, passed: passed, observed: observed, threshold: threshold)
  }
  private static func median(_ values: [Double]) -> Double {
    guard !values.isEmpty else { return .infinity }
    let sorted = values.sorted()
    let middle = sorted.count / 2
    return sorted.count.isMultiple(of: 2)
      ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle]
  }
  private static func residual(_ anchor: DeviceCalibrationAnchor, imageToTable: DeviceHomography)
    -> Double
  {
    let orientations =
      (try? DeviceCardPlaneGeometry.quadrilateralOrientations(anchor.quadrilateral)) ?? []
    return orientations.compactMap { orientation -> Double? in
      guard let quad = try? imageToTable.apply(to: orientation),
        let value = try? DeviceCardPlaneGeometry.cardResidual(quad)
      else { return nil }
      return value.angleDegrees / 10 + value.aspect + value.parallel
    }.min() ?? .infinity
  }
  private static func pose(_ quad: [DevicePoint2D]) -> (center: DevicePoint2D, angle: Double) {
    let center =
      (try? DevicePoint2D(x: quad.map(\.x).reduce(0, +) / 4, y: quad.map(\.y).reduce(0, +) / 4))
      ?? (try! DevicePoint2D(x: 0, y: 0))
    let shortX = (quad[1].x - quad[0].x) + (quad[2].x - quad[3].x)
    let shortY = (quad[1].y - quad[0].y) + (quad[2].y - quad[3].y)
    return (center, atan2(shortY, shortX) * 180 / .pi)
  }
  private static func distance(_ pair: (DevicePoint2D, DevicePoint2D)) -> Double {
    hypot(pair.0.x - pair.1.x, pair.0.y - pair.1.y)
  }
}
