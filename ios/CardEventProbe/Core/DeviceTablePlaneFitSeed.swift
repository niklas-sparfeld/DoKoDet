import Foundation

public struct DeviceTablePlaneFitSeed: Equatable, Sendable {
  public let imageToTable: DeviceHomography
  public let seedObservationIndex: Int
  public let seedOrientationIndex: Int
  public let medianCardResidual: Double
}

public enum DeviceTablePlaneFitSeedError: Error, Equatable {
  case noObservations
  case invalidQuadrilateral
  case noFiniteSeed
}

public enum DeviceTablePlaneFit {
  /// Select a deterministic image-to-table homography seed from complete card quadrilaterals.
  /// The seed maps one card to the canonical table-plane card rectangle. It is an initializer,
  /// not a recording calibration or a publication decision.
  public static func initialImageToTable(
    _ cardQuadrilaterals: [[DevicePoint2D]]
  ) throws -> DeviceTablePlaneFitSeed {
    guard !cardQuadrilaterals.isEmpty else {
      throw DeviceTablePlaneFitSeedError.noObservations
    }

    let quads: [[DevicePoint2D]]
    do {
      quads = try cardQuadrilaterals.map { quad in
        guard quad.count == 4 else { throw DeviceTablePlaneFitSeedError.invalidQuadrilateral }
        let ordered = try DeviceCardPlaneGeometry.cyclicQuadrilateral(quad)
        guard area(ordered) > 1e-8 else {
          throw DeviceTablePlaneFitSeedError.invalidQuadrilateral
        }
        return ordered
      }
    } catch let error as DeviceTablePlaneFitSeedError {
      throw error
    } catch {
      throw DeviceTablePlaneFitSeedError.invalidQuadrilateral
    }

    let aspect = DeviceCardPlaneGeometry.cardAspectRatio
    let destination = [
      try DevicePoint2D(x: 0, y: 0),
      try DevicePoint2D(x: 1, y: 0),
      try DevicePoint2D(x: 1, y: aspect),
      try DevicePoint2D(x: 0, y: aspect),
    ]
    var best: DeviceTablePlaneFitSeed?

    for seedIndex in quads.indices {
      let cyclic = quads[seedIndex]
      for orientationIndex in 0..<2 {
        let source = orientationIndex == 0 ? cyclic : Array(cyclic.dropFirst()) + [cyclic[0]]
        guard let homography = try? perspectiveTransform(source, destination) else { continue }
        var residuals: [Double] = []
        var valid = true
        for quad in quads {
          guard let oriented = bestOrientation(quad, through: homography),
            let transformed = try? homography.apply(to: oriented),
            let residual = try? DeviceCardPlaneGeometry.cardResidual(transformed)
          else {
            valid = false
            break
          }
          let score = residual.angleDegrees / 10 + residual.aspect + residual.parallel
          guard score.isFinite else {
            valid = false
            break
          }
          residuals.append(score)
        }
        guard valid, let matrix = try? DeviceHomography(rows: homography.rows) else { continue }
        let score = median(residuals)
        let candidate = DeviceTablePlaneFitSeed(
          imageToTable: matrix,
          seedObservationIndex: seedIndex,
          seedOrientationIndex: orientationIndex,
          medianCardResidual: score
        )
        if best == nil || candidate.medianCardResidual < best!.medianCardResidual {
          best = candidate
        }
      }
    }
    guard let best else { throw DeviceTablePlaneFitSeedError.noFiniteSeed }
    return best
  }

  private static func bestOrientation(
    _ quad: [DevicePoint2D], through homography: DeviceHomography
  ) -> [DevicePoint2D]? {
    let candidates = [quad, Array(quad.dropFirst()) + [quad[0]]]
    return candidates.compactMap { candidate -> (Double, [DevicePoint2D])? in
      guard let transformed = try? homography.apply(to: candidate),
        let residual = try? DeviceCardPlaneGeometry.cardResidual(transformed)
      else { return nil }
      return (residual.angleDegrees / 10 + residual.aspect + residual.parallel, candidate)
    }.min { $0.0 < $1.0 }?.1
  }

  private static func perspectiveTransform(
    _ source: [DevicePoint2D], _ destination: [DevicePoint2D]
  ) throws -> DeviceHomography {
    var system = Array(repeating: Array(repeating: 0.0, count: 9), count: 8)
    for index in 0..<4 {
      let x = source[index].x
      let y = source[index].y
      let u = destination[index].x
      let v = destination[index].y
      system[index * 2] = [x, y, 1, 0, 0, 0, -u * x, -u * y, u]
      system[index * 2 + 1] = [0, 0, 0, x, y, 1, -v * x, -v * y, v]
    }
    for column in 0..<8 {
      let pivot = (column..<8).max { abs(system[$0][column]) < abs(system[$1][column]) }!
      guard abs(system[pivot][column]) > 1e-12 else {
        throw DeviceTablePlaneFitSeedError.noFiniteSeed
      }
      system.swapAt(column, pivot)
      let divisor = system[column][column]
      for entry in column..<9 { system[column][entry] /= divisor }
      for row in 0..<8 where row != column {
        let factor = system[row][column]
        for entry in column..<9 { system[row][entry] -= factor * system[column][entry] }
      }
    }
    let p = system.map { $0[8] }
    return try DeviceHomography(rows: [
      [p[0], p[1], p[2]], [p[3], p[4], p[5]], [p[6], p[7], 1],
    ])
  }

  private static func median(_ values: [Double]) -> Double {
    let sorted = values.sorted()
    guard !sorted.isEmpty else { return .infinity }
    let middle = sorted.count / 2
    return sorted.count.isMultiple(of: 2)
      ? (sorted[middle - 1] + sorted[middle]) / 2
      : sorted[middle]
  }

  private static func area(_ points: [DevicePoint2D]) -> Double {
    abs(
      points.indices.reduce(0.0) { total, index in
        let next = points[(index + 1) % points.count]
        return total + points[index].x * next.y - points[index].y * next.x
      }) / 2
  }
}
