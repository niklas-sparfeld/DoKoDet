import Foundation

public struct DeviceSceneCandidate: Equatable, Sendable {
  public let candidateID: String
  public let polygons: [[DevicePoint2D]]
  public let confidence: Double

  public init(candidateID: String, polygons: [[DevicePoint2D]], confidence: Double) {
    self.candidateID = candidateID
    self.polygons = polygons
    self.confidence = confidence
  }
}

public struct DeviceSceneFrameInput: Equatable, Sendable {
  public let frameID: String
  public let sourceFrameDigest: String
  public let width: Int
  public let height: Int
  public let status: String
  public let candidates: [DeviceSceneCandidate]

  public init(
    frameID: String, sourceFrameDigest: String, width: Int, height: Int,
    status: String, candidates: [DeviceSceneCandidate]
  ) {
    self.frameID = frameID
    self.sourceFrameDigest = sourceFrameDigest
    self.width = width
    self.height = height
    self.status = status
    self.candidates = candidates
  }
}

public struct DeviceProposedCardPose: Equatable, Sendable {
  public let cardID: String
  public let sourceCandidateID: String
  public let center: DevicePoint2D
  public let rotationDegrees: Double
  public let fitResidual: Double
}

public struct DeviceStackingOrderEvidence: Equatable, Sendable {
  public let leftCardID: String
  public let rightCardID: String
  public let overlapAreaPixels: Double
  public let leftSupport: Double
  public let rightSupport: Double
  public let decision: String
}

public struct DeviceProposedCardSceneFrame: Equatable, Sendable {
  public let frameID: String
  public let sourceFrameDigest: String
  public let status: String
  public let poses: [DeviceProposedCardPose]
  public let orderEvidence: [DeviceStackingOrderEvidence]
  public let uncertainOrderPairs: [[String]]
  public let failureReasons: [String: String]
  public let jointFit: DeviceCardSceneJointFit?
}

public struct DeviceProposedCardSceneRevision: Equatable, Sendable {
  public let detectorRevisionID: String
  public let detectorRevisionDigest: String
  public let calibrationRevisionID: String
  public let calibrationDigest: String
  public let frames: [DeviceProposedCardSceneFrame]
  public let status: String
}

public enum DeviceProposedCardSceneError: Error, Equatable {
  case invalidInput
  case staleDetectorRevision
  case staleCalibration
}

/// Deterministic per-frame card pose initialization from frozen detector and calibration inputs.
/// Poses and order edges remain proposals. Weak or ambiguous overlap evidence stays unresolved.
public enum DeviceProposedCardSceneInitializer {
  public static let maximumAspectLogResidual = 0.24
  public static let minimumOrderOverlapPixels = 4.0
  public static let minimumOrderSupport = 0.08
  public static let weakOrderMargin = 0.12

  public static func initialize(
    frames: [DeviceSceneFrameInput], detectorRevisionID: String,
    detectorRevisionDigest: String, calibration: DeviceRecordingCalibration
  ) throws -> DeviceProposedCardSceneRevision {
    guard !detectorRevisionID.isEmpty, isDigest(detectorRevisionDigest),
      !frames.isEmpty,
      Set(frames.map(\.frameID)).count == frames.count,
      frames.allSatisfy({ !$0.frameID.isEmpty && isDigest($0.sourceFrameDigest) })
    else { throw DeviceProposedCardSceneError.invalidInput }
    guard detectorRevisionID == calibration.visibleCardRevisionID else {
      throw DeviceProposedCardSceneError.staleDetectorRevision
    }
    guard
      frames.allSatisfy({
        $0.width == calibration.frameWidth && $0.height == calibration.frameHeight
      })
    else { throw DeviceProposedCardSceneError.staleCalibration }

    let output = try frames.map { frame in
      try initializeFrame(frame, calibration: calibration)
    }
    let status =
      output.allSatisfy({ ["supported", "no_cards_detected"].contains($0.status) })
      ? "complete" : (output.contains(where: { !$0.poses.isEmpty }) ? "partial" : "failed")
    return DeviceProposedCardSceneRevision(
      detectorRevisionID: detectorRevisionID,
      detectorRevisionDigest: detectorRevisionDigest,
      calibrationRevisionID: calibration.calibrationRevisionID,
      calibrationDigest: calibration.calibrationDigest,
      frames: output, status: status)
  }

  private static func initializeFrame(
    _ frame: DeviceSceneFrameInput, calibration: DeviceRecordingCalibration
  ) throws -> DeviceProposedCardSceneFrame {
    guard ["detected", "empty"].contains(frame.status) else {
      return DeviceProposedCardSceneFrame(
        frameID: frame.frameID, sourceFrameDigest: frame.sourceFrameDigest, status: "failed",
        poses: [], orderEvidence: [], uncertainOrderPairs: [],
        failureReasons: ["frame": "detector_outcome_\(frame.status)"], jointFit: nil)
    }
    guard frame.status != "empty" || frame.candidates.isEmpty,
      frame.candidates.allSatisfy({
        !$0.candidateID.isEmpty && $0.confidence.isFinite && (0...1).contains($0.confidence)
          && !$0.polygons.isEmpty && $0.polygons.allSatisfy({ $0.count >= 3 })
      }),
      Set(frame.candidates.map(\.candidateID)).count == frame.candidates.count
    else { throw DeviceProposedCardSceneError.invalidInput }
    guard !frame.candidates.isEmpty else {
      return DeviceProposedCardSceneFrame(
        frameID: frame.frameID, sourceFrameDigest: frame.sourceFrameDigest,
        status: "no_cards_detected", poses: [], orderEvidence: [], uncertainOrderPairs: [],
        failureReasons: [:], jointFit: nil)
    }

    var poses: [DeviceProposedCardPose] = []
    var failureReasons: [String: String] = [:]
    for candidate in frame.candidates.sorted(by: { $0.candidateID < $1.candidateID }) {
      do {
        poses.append(try fit(candidate, calibration: calibration))
      } catch {
        failureReasons[candidate.candidateID] = "card_geometry_not_supported"
      }
    }
    let order = try stackingEvidence(
      poses: poses, candidates: frame.candidates, calibration: calibration)
    let status = poses.isEmpty ? "failed" : (failureReasons.isEmpty ? "supported" : "partial")
    let initial = DeviceProposedCardSceneFrame(
      frameID: frame.frameID, sourceFrameDigest: frame.sourceFrameDigest, status: status,
      poses: poses, orderEvidence: order.evidence, uncertainOrderPairs: order.uncertain,
      failureReasons: failureReasons, jointFit: nil)
    let fit = DeviceCardSceneJointFitter.fit(
      frame: frame, scene: initial,
      calibration: calibration)
    let updatedPoses = poses.map { fit.poses[$0.cardID] ?? $0 }
    return DeviceProposedCardSceneFrame(
      frameID: frame.frameID, sourceFrameDigest: frame.sourceFrameDigest, status: status,
      poses: updatedPoses, orderEvidence: order.evidence, uncertainOrderPairs: order.uncertain,
      failureReasons: failureReasons, jointFit: fit)
  }

  private static func fit(
    _ candidate: DeviceSceneCandidate, calibration: DeviceRecordingCalibration
  ) throws -> DeviceProposedCardPose {
    let imagePoints = candidate.polygons.flatMap { $0 }
    let tablePoints = try calibration.imageToTable.apply(to: imagePoints)
    guard tablePoints.count >= 4 else { throw DeviceProposedCardSceneError.invalidInput }
    let hull = convexHull(tablePoints)
    guard hull.count >= 4 else { throw DeviceProposedCardSceneError.invalidInput }
    var best: (area: Double, center: DevicePoint2D, angle: Double, short: Double, long: Double)?
    for index in hull.indices {
      let edge = hull[(index + 1) % hull.count] - hull[index]
      let length = hypot(edge.x, edge.y)
      guard length > 1e-9 else { continue }
      let angle = atan2(edge.y, edge.x)
      let axis = try DevicePoint2D(x: cos(angle), y: sin(angle))
      let normal = try DevicePoint2D(x: -sin(angle), y: cos(angle))
      let along = hull.map { dot($0, axis) }
      let across = hull.map { dot($0, normal) }
      let minA = along.min()!
      let maxA = along.max()!
      let minN = across.min()!
      let maxN = across.max()!
      let width = maxA - minA
      let height = maxN - minN
      let area = width * height
      let center = axis * ((minA + maxA) / 2) + normal * ((minN + maxN) / 2)
      let short = min(width, height)
      let long = max(width, height)
      let shortAngle = width <= height ? angle : angle + .pi / 2
      if best == nil || area < best!.area {
        best = (area, center, shortAngle, short, long)
      }
    }
    guard let best, best.short > 0, best.long > 0 else {
      throw DeviceProposedCardSceneError.invalidInput
    }
    let aspectResidual = abs(
      log((best.long / best.short) / DeviceCardPlaneGeometry.cardAspectRatio))
    guard aspectResidual <= maximumAspectLogResidual else {
      throw DeviceProposedCardSceneError.invalidInput
    }
    let rotation = normalizedDegrees(best.angle * 180 / .pi)
    let projected = try DeviceCardPlaneGeometry.projectFixedCard(
      tableToImage: calibration.tableToImage, center: best.center,
      rotationDegrees: rotation, shortSize: calibration.cardShortSize,
      longSize: calibration.cardLongSize)
    let perimeter = zip(projected, projected.dropFirst() + [projected[0]]).reduce(0.0) {
      $0 + hypot($1.1.x - $1.0.x, $1.1.y - $1.0.y)
    }
    let residual = perimeter > 0 ? aspectResidual : 1
    guard residual.isFinite else { throw DeviceProposedCardSceneError.invalidInput }
    return DeviceProposedCardPose(
      cardID: "pose-\(candidate.candidateID)", sourceCandidateID: candidate.candidateID,
      center: best.center, rotationDegrees: rotation, fitResidual: residual)
  }

  private static func stackingEvidence(
    poses: [DeviceProposedCardPose], candidates: [DeviceSceneCandidate],
    calibration: DeviceRecordingCalibration
  ) throws -> (evidence: [DeviceStackingOrderEvidence], uncertain: [[String]]) {
    let byID = Dictionary(uniqueKeysWithValues: candidates.map { ($0.candidateID, $0) })
    var evidence: [DeviceStackingOrderEvidence] = []
    var uncertain: [[String]] = []
    for leftIndex in poses.indices {
      for rightIndex in poses.indices where rightIndex > leftIndex {
        let left = poses[leftIndex]
        let right = poses[rightIndex]
        let leftQuad = try DeviceCardPlaneGeometry.projectFixedCard(
          tableToImage: calibration.tableToImage, center: left.center,
          rotationDegrees: left.rotationDegrees, shortSize: calibration.cardShortSize,
          longSize: calibration.cardLongSize)
        let rightQuad = try DeviceCardPlaneGeometry.projectFixedCard(
          tableToImage: calibration.tableToImage, center: right.center,
          rotationDegrees: right.rotationDegrees, shortSize: calibration.cardShortSize,
          longSize: calibration.cardLongSize)
        let overlap = clip(subject: leftQuad, by: rightQuad)
        let area = polygonArea(overlap)
        guard area >= minimumOrderOverlapPixels else { continue }
        let leftSupport = support(
          byID[left.sourceCandidateID]!, within: overlap)
        let rightSupport = support(
          byID[right.sourceCandidateID]!, within: overlap)
        let difference = leftSupport - rightSupport
        let weak =
          abs(difference) < weakOrderMargin
          || max(leftSupport, rightSupport) < minimumOrderSupport
        if weak {
          uncertain.append([left.cardID, right.cardID].sorted())
        }
        evidence.append(
          DeviceStackingOrderEvidence(
            leftCardID: left.cardID, rightCardID: right.cardID,
            overlapAreaPixels: area, leftSupport: leftSupport, rightSupport: rightSupport,
            decision: weak ? "uncertain" : (difference > 0 ? "left" : "right")))
      }
    }
    return (evidence, uncertain)
  }

  private static func support(
    _ candidate: DeviceSceneCandidate, within clipPolygon: [DevicePoint2D]
  ) -> Double {
    let total = polygonArea(clipPolygon)
    guard total > 0 else { return 0 }
    let covered = candidate.polygons.reduce(0.0) { area, polygon in
      area + polygonArea(clip(subject: polygon, by: clipPolygon))
    }
    return min(1, covered / total)
  }

  private static func convexHull(_ points: [DevicePoint2D]) -> [DevicePoint2D] {
    let sorted = points.sorted { $0.x == $1.x ? $0.y < $1.y : $0.x < $1.x }
      .reduce(into: [DevicePoint2D]()) { result, point in
        if result.last != point { result.append(point) }
      }
    guard sorted.count > 2 else { return sorted }
    func half(_ values: [DevicePoint2D]) -> [DevicePoint2D] {
      var result: [DevicePoint2D] = []
      for point in values {
        while result.count > 1
          && cross(result[result.count - 1] - result[result.count - 2], point - result.last!) <= 0
        {
          result.removeLast()
        }
        result.append(point)
      }
      return result
    }
    return Array(half(sorted).dropLast()) + Array(half(sorted.reversed()).dropLast())
  }

  private static func clip(subject: [DevicePoint2D], by clipper: [DevicePoint2D]) -> [DevicePoint2D]
  {
    guard subject.count >= 3, clipper.count >= 3 else { return [] }
    var output = subject
    let orientation = signedArea(clipper) >= 0 ? 1.0 : -1.0
    for index in clipper.indices {
      let a = clipper[index]
      let b = clipper[(index + 1) % clipper.count]
      let input = output
      output = []
      guard var previous = input.last else { continue }
      for current in input {
        let currentInside = orientation * cross(b - a, current - a) >= -1e-9
        let previousInside = orientation * cross(b - a, previous - a) >= -1e-9
        if currentInside != previousInside, let intersection = intersection(previous, current, a, b)
        {
          output.append(intersection)
        }
        if currentInside { output.append(current) }
        previous = current
      }
    }
    return output
  }

  private static func intersection(
    _ p: DevicePoint2D, _ q: DevicePoint2D, _ a: DevicePoint2D, _ b: DevicePoint2D
  ) -> DevicePoint2D? {
    let r = q - p
    let s = b - a
    let denominator = cross(r, s)
    guard abs(denominator) > 1e-12 else { return nil }
    let t = cross(a - p, s) / denominator
    return try? DevicePoint2D(x: p.x + t * r.x, y: p.y + t * r.y)
  }

  private static func polygonArea(_ points: [DevicePoint2D]) -> Double { abs(signedArea(points)) }
  private static func signedArea(_ points: [DevicePoint2D]) -> Double {
    guard points.count >= 3 else { return 0 }
    return points.indices.reduce(0) { result, index in
      let next = points[(index + 1) % points.count]
      return result + points[index].x * next.y - next.x * points[index].y
    } / 2
  }
  private static func dot(_ lhs: DevicePoint2D, _ rhs: DevicePoint2D) -> Double {
    lhs.x * rhs.x + lhs.y * rhs.y
  }
  private static func cross(_ lhs: DevicePoint2D, _ rhs: DevicePoint2D) -> Double {
    lhs.x * rhs.y - lhs.y * rhs.x
  }
  private static func normalizedDegrees(_ value: Double) -> Double {
    let normalized = value.truncatingRemainder(dividingBy: 180)
    return normalized < 0 ? normalized + 180 : normalized
  }
  private static func isDigest(_ value: String) -> Bool {
    value.count == 64 && value.allSatisfy(\.isHexDigit)
  }
}

extension DevicePoint2D {
  fileprivate static func + (lhs: DevicePoint2D, rhs: DevicePoint2D) -> DevicePoint2D {
    try! DevicePoint2D(x: lhs.x + rhs.x, y: lhs.y + rhs.y)
  }
  fileprivate static func - (lhs: DevicePoint2D, rhs: DevicePoint2D) -> DevicePoint2D {
    try! DevicePoint2D(x: lhs.x - rhs.x, y: lhs.y - rhs.y)
  }
  fileprivate static func * (lhs: DevicePoint2D, rhs: Double) -> DevicePoint2D {
    try! DevicePoint2D(x: lhs.x * rhs, y: lhs.y * rhs)
  }
}
