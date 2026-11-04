import Foundation

public struct DeviceCalibrationObservation: Equatable, Sendable {
  public let candidateID: String
  public let frameID: String
  public let timeS: Double
  public let frameWidth: Int
  public let frameHeight: Int
  public let sourceTransformID: String
  public let confidence: Double
  public let quadrilateral: [DevicePoint2D]
  public let boundarySamples: [DevicePoint2D]?

  public init(
    candidateID: String, frameID: String, timeS: Double, frameWidth: Int, frameHeight: Int,
    sourceTransformID: String, confidence: Double, quadrilateral: [DevicePoint2D],
    boundarySamples: [DevicePoint2D]? = nil
  ) {
    self.candidateID = candidateID
    self.frameID = frameID
    self.timeS = timeS
    self.frameWidth = frameWidth
    self.frameHeight = frameHeight
    self.sourceTransformID = sourceTransformID
    self.confidence = confidence
    self.quadrilateral = quadrilateral
    self.boundarySamples = boundarySamples
  }
}

public struct DeviceRecordingCalibration: Equatable, Sendable {
  public let recordingID: String
  public let visibleCardRevisionID: String
  public let frameWidth: Int
  public let frameHeight: Int
  public let imageToTable: DeviceHomography
  public let tableToImage: DeviceHomography
  public let cardShortSize: Double
  public let cardLongSize: Double
  public let acceptedCandidateIDs: [String]
}

public struct DeviceRecordingCalibrationResult: Equatable, Sendable {
  public let status: String
  public let failureCode: String?
  public let failureMessage: String?
  public let candidateDecisions: [String: String]
  public let fitResult: DeviceTablePlaneFitResult?
  public let calibration: DeviceRecordingCalibration?
}

public enum DeviceRecordingCalibrationError: Error, Equatable {
  case invalidInput
  case inconsistentRecording
}

public enum DeviceRecordingCalibrationSelector {
  public static let confidenceThreshold = 0.90
  public static let minimumCandidates = 6
  public static let minimumTemporalBins = 3
  public static let minimumPositionBins = 3
  public static let minimumOrientationBins = 2
  public static let minimumHeldOutCandidates = 2
  public static let holdoutModulus = 4

  /// Select and validate one recording calibration from a frozen visible-card revision.
  /// Candidate mask-quality filtering must be completed by the visible-card adapter before this call.
  public static func calibrate(
    recordingID: String, visibleCardRevisionID: String,
    observations: [DeviceCalibrationObservation]
  ) throws -> DeviceRecordingCalibrationResult {
    guard !recordingID.isEmpty, !visibleCardRevisionID.isEmpty,
      observations.allSatisfy({
        !$0.candidateID.isEmpty && !$0.frameID.isEmpty && !$0.sourceTransformID.isEmpty
          && $0.timeS.isFinite && $0.timeS >= 0 && $0.confidence.isFinite
          && (0...1).contains($0.confidence) && $0.frameWidth > 0 && $0.frameHeight > 0
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
    let confident = observations.filter { item in
      let accepted = item.confidence >= confidenceThreshold && item.quadrilateral.count == 4
      if !accepted { decisions[item.candidateID] = "rejected:confidence_or_geometry" }
      return accepted
    }.sorted { $0.candidateID < $1.candidateID }
    guard confident.count >= minimumCandidates else {
      return failure(
        "insufficient_candidates", "Too few high-confidence card candidates.", decisions)
    }

    let heldOut = confident.enumerated().filter { $0.offset % holdoutModulus == 0 }.map(\.element)
    let fitting = confident.enumerated().filter { $0.offset % holdoutModulus != 0 }.map(\.element)
    guard heldOut.count >= minimumHeldOutCandidates, !fitting.isEmpty else {
      return failure(
        "insufficient_validation_population", "Too few independent held-out candidates.", decisions)
    }
    let trainingFit = try? DeviceTablePlaneFit.fitTablePlane(
      fitting.map(\.quadrilateral),
      boundarySamples: fitting.map { $0.boundarySamples ?? [] }.enumerated().allSatisfy {
        $0.element.isEmpty
      }
        ? nil : fitting.map { $0.boundarySamples ?? [] },
      observationWeights: fitting.map(\.confidence))
    guard let trainingFit else {
      return failure(
        "calibration_fit_failed", "The table-plane fit did not produce a finite candidate.",
        decisions)
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
        trainingFit)
    }

    let heldOutPasses = heldOut.filter { item in
      guard let mapped = try? trainingFit.imageToTable.apply(to: item.quadrilateral),
        let residual = try? DeviceCardPlaneGeometry.cardResidual(mapped)
      else { return false }
      return residual.angleDegrees <= 10 && residual.aspect <= 0.10 && residual.parallel <= 0.10
    }
    for item in heldOut where !heldOutPasses.contains(item) {
      decisions[item.candidateID] = "rejected:held_out_geometry"
    }
    let selected = (fitAccepted + heldOutPasses).sorted { $0.candidateID < $1.candidateID }
    let temporalBins = Set(selected.map { Int($0.timeS) })
    let positionBins = Set(
      selected.map { item -> String in
        let centerX = item.quadrilateral.map(\.x).reduce(0, +) / 4 / Double(item.frameWidth)
        let centerY = item.quadrilateral.map(\.y).reduce(0, +) / 4 / Double(item.frameHeight)
        return "\(Int(centerX * 8)):\(Int(centerY * 8))"
      })
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
        trainingFit)
    }
    guard trainingFit.qualityPassed, heldOut.count >= minimumHeldOutCandidates,
      Double(heldOutPasses.count) / Double(heldOut.count) >= 0.60
    else {
      return failure(
        "inconsistent_card_geometry", "Fit quality or held-out validation did not pass.", decisions,
        trainingFit)
    }

    return DeviceRecordingCalibrationResult(
      status: "published", failureCode: nil, failureMessage: nil, candidateDecisions: decisions,
      fitResult: trainingFit,
      calibration: DeviceRecordingCalibration(
        recordingID: recordingID, visibleCardRevisionID: visibleCardRevisionID,
        frameWidth: first.frameWidth, frameHeight: first.frameHeight,
        imageToTable: trainingFit.imageToTable, tableToImage: trainingFit.tableToImage,
        cardShortSize: 1, cardLongSize: DeviceCardPlaneGeometry.cardAspectRatio,
        acceptedCandidateIDs: selected.map(\.candidateID)))
  }

  private static func failure(
    _ code: String, _ message: String, _ decisions: [String: String],
    _ fit: DeviceTablePlaneFitResult? = nil
  ) -> DeviceRecordingCalibrationResult {
    DeviceRecordingCalibrationResult(
      status: "failed", failureCode: code, failureMessage: message,
      candidateDecisions: decisions, fitResult: fit, calibration: nil)
  }
}
