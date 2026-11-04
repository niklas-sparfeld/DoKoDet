import Foundation

public struct DeviceTablePlaneFitResult: Equatable, Sendable {
  public let imageToTable: DeviceHomography
  public let tableToImage: DeviceHomography
  public let inlierIndices: [Int]
  public let rejectedIndices: [Int]
  public let observationResiduals: [Double]
  public let medianBoundaryResidual: Double
  public let qualityPassed: Bool
  public let convergenceReason: String
}

public enum DeviceTablePlaneBoundaryFitError: Error, Equatable {
  case noObservations
  case invalidQuadrilateral
  case invalidBoundarySamples
  case invalidWeights
  case noFiniteFit
}

extension DeviceTablePlaneFit {
  /// Fit a robust shared image/table transform from observed card boundaries.
  /// This returns a candidate only. Recording-level publication gates belong to M6.
  public static func fitTablePlane(
    _ cardQuadrilaterals: [[DevicePoint2D]],
    boundarySamples: [[DevicePoint2D]]? = nil,
    observationWeights: [Double]? = nil
  ) throws -> DeviceTablePlaneFitResult {
    guard !cardQuadrilaterals.isEmpty else { throw DeviceTablePlaneBoundaryFitError.noObservations }
    let quads: [[DevicePoint2D]]
    do { quads = try cardQuadrilaterals.map(DeviceCardPlaneGeometry.cyclicQuadrilateral) } catch {
      throw DeviceTablePlaneBoundaryFitError.invalidQuadrilateral
    }
    let samples = boundarySamples ?? quads.map { boundaryOutline($0, count: 128) }
    guard samples.count == quads.count,
      samples.allSatisfy({ $0.count >= 8 && $0.allSatisfy { $0.x.isFinite && $0.y.isFinite } })
    else { throw DeviceTablePlaneBoundaryFitError.invalidBoundarySamples }
    var weights = observationWeights ?? Array(repeating: 1, count: quads.count)
    guard weights.count == quads.count, weights.allSatisfy({ $0.isFinite && $0 >= 0 }),
      let maximum = weights.max(), maximum > 0
    else { throw DeviceTablePlaneBoundaryFitError.invalidWeights }
    weights = weights.map { $0 / maximum }

    let points: [DevicePoint2D] = samples.flatMap { $0 }
    let minX = points.map(\.x).min()!
    let maxX = points.map(\.x).max()!
    let minY = points.map(\.y).min()!
    let maxY = points.map(\.y).max()!
    let center = [(minX + maxX) / 2, (minY + maxY) / 2]
    let scale = max(max(maxX - minX, maxY - minY), 1)
    let normalizedSamples: [[P2]] = samples.map { boundary in
      boundary.map { point in P2((point.x - center[0]) / scale, (point.y - center[1]) / scale) }
    }

    let seed: DeviceTablePlaneFitSeed
    do { seed = try initialImageToTable(quads) } catch {
      throw DeviceTablePlaneBoundaryFitError.noFiniteFit
    }
    let reference = weights.indices.min {
      weights[$0] == weights[$1] ? $0 < $1 : weights[$0] > weights[$1]
    }!
    var imageToTable = seed.imageToTable.rows
    // Fix the gauge to the highest-weight observation, as the Python fitter does.
    let seedMapped = try seed.imageToTable.apply(to: quads[reference])
    let seedVectors = try DeviceCardPlaneGeometry.cardVectors(seedMapped)
    let gaugeAngle = atan2(seedVectors.short.y, seedVectors.short.x)
    let centerX = seedMapped.map { $0.x }.reduce(0.0, +) / 4
    let centerY = seedMapped.map { $0.y }.reduce(0.0, +) / 4
    let gaugeCenter: [Double] = [centerX, centerY]
    let cosine = cos(gaugeAngle)
    let sine = sin(gaugeAngle)
    let gauge: [[Double]] = [
      [cosine, sine, -cosine * gaugeCenter[0] - sine * gaugeCenter[1]],
      [-sine, cosine, sine * gaugeCenter[0] - cosine * gaugeCenter[1]], [0, 0, 1],
    ]
    imageToTable = multiply(gauge, imageToTable)
    guard let initialTableToImage = inverse(imageToTable) else {
      throw DeviceTablePlaneBoundaryFitError.noFiniteFit
    }
    // P maps table coordinates to normalized source-image coordinates.
    let p = multiply(
      [[1 / scale, 0, -center[0] / scale], [0, 1 / scale, -center[1] / scale], [0, 0, 1]],
      initialTableToImage)
    let gaugedTransform = try DeviceHomography(rows: imageToTable)
    let transformedQuads = try quads.map { try gaugedTransform.apply(to: $0) }
    var poses = transformedQuads.map { quad -> [Double] in
      let vectors = try! DeviceCardPlaneGeometry.cardVectors(quad)
      return [
        quad.map(\.x).reduce(0, +) / 4, quad.map(\.y).reduce(0, +) / 4,
        atan2(vectors.short.y, vectors.short.x),
      ]
    }
    poses[reference] = [0, 0, 0]
    var parameters =
      flatten(p) + poses.enumerated().filter { $0.offset != reference }.flatMap(\.element)
    let activeWeights = weights
    var damping = 1e-3
    var reason = "iteration_limit"
    for _ in 0..<8 {
      let residuals = fitResiduals(
        parameters, poses: poses, reference: reference, samples: normalizedSamples)
      let cost = huberCost(residuals, weights: activeWeights)
      if cost <= 1e-12 {
        reason = "converged"
        break
      }
      let rowCount = residuals.reduce(0) { $0 + $1.count }
      let columnCount = parameters.count
      var jacobian = Array(repeating: Array(repeating: 0.0, count: columnCount), count: rowCount)
      var valid = true
      for column in 0..<columnCount {
        var shifted = parameters
        let step = max(1e-7, abs(parameters[column]) * 1e-5)
        shifted[column] += step
        let shiftedResiduals = fitResiduals(
          shifted, poses: poses, reference: reference, samples: normalizedSamples)
        guard shiftedResiduals.count == residuals.count else {
          valid = false
          break
        }
        var row = 0
        for observation in residuals.indices {
          for item in residuals[observation].indices {
            jacobian[row][column] =
              (shiftedResiduals[observation][item] - residuals[observation][item]) / step
            row += 1
          }
        }
      }
      guard valid else {
        reason = "invalid_jacobian"
        break
      }
      var normal = Array(repeating: Array(repeating: 0.0, count: columnCount), count: columnCount)
      var gradient = Array(repeating: 0.0, count: columnCount)
      var row = 0
      for observation in residuals.indices {
        let weight = sqrt(activeWeights[observation])
        for value in residuals[observation] {
          let robust = sqrt(min(1, 0.025 / max(abs(value), 1e-12)))
          let factor = weight * robust
          let r = value * factor
          for left in 0..<columnCount {
            let jl = jacobian[row][left] * factor
            gradient[left] += jl * r
            for right in 0..<columnCount {
              normal[left][right] += jl * jacobian[row][right] * factor
            }
          }
          row += 1
        }
      }
      var accepted = false
      for _ in 0..<5 {
        var damped = normal
        for index in 0..<columnCount {
          damped[index][index] += damping * max(normal[index][index], 1e-8)
        }
        guard let delta = solve(damped, gradient.map { -$0 }) else {
          damping *= 10
          continue
        }
        let bounded = delta.enumerated().map { index, value in
          let limit = index < 6 ? 0.08 : (index < 8 ? 0.015 : (index % 3 == 2 ? 0.35 : 1.0))
          return min(limit, max(-limit, value))
        }
        for fraction in [1.0, 0.5, 0.25, 0.125] {
          let candidate = zip(parameters, bounded).map { $0 + fraction * $1 }
          if huberCost(
            fitResiduals(candidate, poses: poses, reference: reference, samples: normalizedSamples),
            weights: activeWeights) < cost
          {
            parameters = candidate
            damping = max(1e-8, damping / 3)
            accepted = true
            break
          }
        }
        if accepted { break }
        damping *= 10
      }
      if !accepted {
        reason = "no_improving_step"
        break
      }
    }
    let fittedProjection = matrix(parameters)
    let pixelScaleInverse = [[scale, 0, center[0]], [0, scale, center[1]], [0, 0, 1]]
    let tableToImageRows = multiply(pixelScaleInverse, fittedProjection)
    guard let tableToImage = try? DeviceHomography(rows: tableToImageRows),
      let imageToTable = try? tableToImage.inverted()
    else { throw DeviceTablePlaneBoundaryFitError.noFiniteFit }
    let residuals = fitResiduals(
      parameters, poses: poses, reference: reference, samples: normalizedSamples)
    let perObservation = residuals.map { median($0.map(abs)) }
    let active = perObservation.indices.filter { weights[$0] > 0 }
    let centerResidual = median(active.map { perObservation[$0] })
    let mad = median(active.map { abs(perObservation[$0] - centerResidual) })
    let threshold = max(0.055, centerResidual + max(0.025, 3 * mad))
    let inliers = active.filter { perObservation[$0] <= threshold }
    let rejected = perObservation.indices.filter { !inliers.contains($0) }
    let acceptedMedian = median(inliers.map { perObservation[$0] })
    if rejected.count > 0, inliers.count >= 3, weights.allSatisfy({ $0 > 0 }) {
      var refitWeights = weights
      for index in rejected { refitWeights[index] = 0 }
      let refit = try fitTablePlane(
        quads, boundarySamples: samples, observationWeights: refitWeights)
      return DeviceTablePlaneFitResult(
        imageToTable: refit.imageToTable,
        tableToImage: refit.tableToImage,
        inlierIndices: refit.inlierIndices,
        rejectedIndices: Array(Set(rejected + refit.rejectedIndices)).sorted(),
        observationResiduals: refit.observationResiduals,
        medianBoundaryResidual: refit.medianBoundaryResidual,
        qualityPassed: refit.qualityPassed,
        convergenceReason: refit.convergenceReason
      )
    }
    return DeviceTablePlaneFitResult(
      imageToTable: imageToTable,
      tableToImage: tableToImage,
      inlierIndices: inliers,
      rejectedIndices: rejected,
      observationResiduals: perObservation,
      medianBoundaryResidual: acceptedMedian,
      qualityPassed: inliers.count >= 3 && acceptedMedian <= 0.055,
      convergenceReason: reason
    )
  }
}

private struct P2 {
  var x: Double
  var y: Double
  init(_ x: Double, _ y: Double) {
    self.x = x
    self.y = y
  }
}

private func boundaryOutline(_ quad: [DevicePoint2D], count: Int) -> [DevicePoint2D] {
  (0..<count).map { sample in
    let position = Double(sample) * 4 / Double(count)
    let edge = Int(position)
    let fraction = position - Double(edge)
    let first = quad[edge]
    let second = quad[(edge + 1) % 4]
    return try! DevicePoint2D(
      x: first.x + fraction * (second.x - first.x),
      y: first.y + fraction * (second.y - first.y))
  }
}

private func flatten(_ m: [[Double]]) -> [Double] {
  [m[0][0], m[0][1], m[0][2], m[1][0], m[1][1], m[1][2], m[2][0], m[2][1]]
}
private func matrix(_ p: [Double]) -> [[Double]] {
  [[p[0], p[1], p[2]], [p[3], p[4], p[5]], [p[6], p[7], 1]]
}

private func fitResiduals(
  _ parameters: [Double], poses: [[Double]], reference: Int, samples: [[P2]]
) -> [[Double]] {
  let p = matrix(parameters)
  var poseList = Array(repeating: [0.0, 0.0, 0.0], count: samples.count)
  var offset = 8
  for index in samples.indices where index != reference {
    poseList[index] = Array(parameters[offset..<(offset + 3)])
    offset += 3
  }
  return samples.indices.map { index in
    let pose = poseList[index]
    let a = pose[2]
    let outline = roundedTableOutline(center: [pose[0], pose[1]], angle: a, count: 32)
    let projected = outline.compactMap { project(p, $0) }
    guard projected.count == 32 else { return Array(repeating: 1e3, count: 64) }
    let cardShort = [cos(a) * 0.5, sin(a) * 0.5]
    let cardLong = [
      -sin(a) * DeviceCardPlaneGeometry.cardAspectRatio / 2,
      cos(a) * DeviceCardPlaneGeometry.cardAspectRatio / 2,
    ]
    let corners = [
      [pose[0] - cardShort[0] - cardLong[0], pose[1] - cardShort[1] - cardLong[1]],
      [pose[0] + cardShort[0] - cardLong[0], pose[1] + cardShort[1] - cardLong[1]],
      [pose[0] + cardShort[0] + cardLong[0], pose[1] + cardShort[1] + cardLong[1]],
      [pose[0] - cardShort[0] + cardLong[0], pose[1] - cardShort[1] + cardLong[1]],
    ]
    let projectedCorners = corners.compactMap { project(p, P2($0[0], $0[1])) }
    guard projectedCorners.count == 4 else { return Array(repeating: 1e3, count: 64) }
    let shortSize =
      (distance(projectedCorners[0], projectedCorners[1])
        + distance(projectedCorners[3], projectedCorners[2])) / 2
    guard shortSize > 1e-8 else { return Array(repeating: 1e3, count: 64) }
    let observedIndices = (0..<32).map { $0 * samples[index].count / 32 }
    let observed = observedIndices.map { samples[index][$0] }
    let toProjected = observed.map { pointSegmentDistance($0, projected) }
    let toObserved = projected.map { pointSegmentDistance($0, samples[index]) }
    return (toProjected + toObserved).map { $0 / shortSize }
  }
}

private func project(_ h: [[Double]], _ p: P2) -> P2? {
  let d = h[2][0] * p.x + h[2][1] * p.y + h[2][2]
  guard d.isFinite, abs(d) > 1e-8 else { return nil }
  let x = (h[0][0] * p.x + h[0][1] * p.y + h[0][2]) / d
  let y = (h[1][0] * p.x + h[1][1] * p.y + h[1][2]) / d
  return x.isFinite && y.isFinite ? P2(x, y) : nil
}

private func distance(_ a: P2, _ b: P2) -> Double { hypot(a.x - b.x, a.y - b.y) }

private func pointSegmentDistance(_ point: P2, _ vertices: [P2]) -> Double {
  guard vertices.count > 1 else { return .infinity }
  return vertices.indices.map { index in
    let a = vertices[index]
    let b = vertices[(index + 1) % vertices.count]
    let dx = b.x - a.x
    let dy = b.y - a.y
    let t = min(
      1, max(0, ((point.x - a.x) * dx + (point.y - a.y) * dy) / max(dx * dx + dy * dy, 1e-12)))
    return hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy))
  }.min() ?? .infinity
}

private func roundedTableOutline(center: [Double], angle: Double, count: Int) -> [P2] {
  let ratio = DeviceCardPlaneGeometry.cardAspectRatio
  let radiusX = 0.087
  let radiusY = radiusX / ratio
  let centers = [
    (radiusX, radiusY), (1 - radiusX, radiusY), (1 - radiusX, 1 - radiusY), (radiusX, 1 - radiusY),
  ]
  let starts = [Double.pi, 1.5 * Double.pi, 0, 0.5 * Double.pi]
  let contour = centers.indices.flatMap { corner in
    (0...8).map { step -> P2 in
      let theta = starts[corner] + Double(step) * Double.pi / 16
      return P2(
        centers[corner].0 + radiusX * cos(theta) - 0.5,
        (centers[corner].1 + radiusY * sin(theta)) * ratio - ratio / 2)
    }
  }
  // Uniformly sample the polygon perimeter, then map card-local coordinates to table space.
  let closed = contour + [contour[0]]
  let lengths = closed.indices.dropLast().map { distance(closed[$0], closed[$0 + 1]) }
  let total = lengths.reduce(0, +)
  let local = (0..<count).map { sample -> P2 in
    let target = Double(sample) * total / Double(count)
    var edge = 0
    var traversed = 0.0
    while edge < lengths.count - 1 && traversed + lengths[edge] <= target {
      traversed += lengths[edge]
      edge += 1
    }
    let fraction = (target - traversed) / max(lengths[edge], 1e-12)
    let point = P2(
      closed[edge].x + fraction * (closed[edge + 1].x - closed[edge].x),
      closed[edge].y + fraction * (closed[edge + 1].y - closed[edge].y))
    let c = cos(angle)
    let s = sin(angle)
    return P2(center[0] + c * point.x - s * point.y, center[1] + s * point.x + c * point.y)
  }
  return local
}

private func huberCost(_ residuals: [[Double]], weights: [Double]) -> Double {
  var total = 0.0
  var count = 0.0
  for index in residuals.indices {
    for value in residuals[index] {
      let a = abs(value)
      let delta = 0.025
      total += weights[index] * (a <= delta ? 0.5 * a * a : delta * (a - 0.5 * delta))
      count += weights[index]
    }
  }
  return total / max(count, 1e-12)
}

private func median(_ values: [Double]) -> Double {
  guard !values.isEmpty else { return .infinity }
  let sorted = values.sorted()
  let middle = sorted.count / 2
  return sorted.count.isMultiple(of: 2) ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle]
}

private func multiply(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
  (0..<3).map { row in
    (0..<3).map { column in (0..<3).reduce(0) { $0 + a[row][$1] * b[$1][column] } }
  }
}

private func inverse(_ a: [[Double]]) -> [[Double]]? {
  guard let h = try? DeviceHomography(rows: a), let result = try? h.inverted() else { return nil }
  return result.rows
}

private func solve(_ matrix: [[Double]], _ right: [Double]) -> [Double]? {
  let n = right.count
  var a = matrix.enumerated().map { $0.element + [right[$0.offset]] }
  for column in 0..<n {
    guard let pivot = (column..<n).max(by: { abs(a[$0][column]) < abs(a[$1][column]) }),
      abs(a[pivot][column]) > 1e-14
    else { return nil }
    a.swapAt(column, pivot)
    let divisor = a[column][column]
    for j in column...n { a[column][j] /= divisor }
    for row in 0..<n where row != column {
      let factor = a[row][column]
      for j in column...n { a[row][j] -= factor * a[column][j] }
    }
  }
  return a.map { $0[n] }
}
