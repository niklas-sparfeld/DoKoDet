import Foundation

public enum DeviceCardPlaneGeometryError: Error, Equatable {
  case invalidMatrix
  case invalidPoint
  case pointAtInfinity
  case invalidQuadrilateral
  case invalidCardSize
  case invalidRotation
}

public struct DevicePoint2D: Equatable, Sendable {
  public let x: Double
  public let y: Double

  public init(x: Double, y: Double) throws {
    guard x.isFinite, y.isFinite else { throw DeviceCardPlaneGeometryError.invalidPoint }
    self.x = x
    self.y = y
  }

  fileprivate init(uncheckedX x: Double, y: Double) {
    self.x = x
    self.y = y
  }
}

public struct DeviceHomography: Equatable, Sendable {
  public let rows: [[Double]]

  public init(rows: [[Double]]) throws {
    guard rows.count == 3, rows.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }) else {
      throw DeviceCardPlaneGeometryError.invalidMatrix
    }
    let determinant = Self.determinant(rows)
    guard determinant.isFinite, abs(determinant) >= 1e-12 else {
      throw DeviceCardPlaneGeometryError.invalidMatrix
    }
    self.rows = rows
  }

  public func apply(to points: [DevicePoint2D]) throws -> [DevicePoint2D] {
    try points.map { point in
      let denominator = rows[2][0] * point.x + rows[2][1] * point.y + rows[2][2]
      guard denominator.isFinite, abs(denominator) >= 1e-9 else {
        throw DeviceCardPlaneGeometryError.pointAtInfinity
      }
      return try DevicePoint2D(
        x: (rows[0][0] * point.x + rows[0][1] * point.y + rows[0][2]) / denominator,
        y: (rows[1][0] * point.x + rows[1][1] * point.y + rows[1][2]) / denominator
      )
    }
  }

  public func inverted() throws -> DeviceHomography {
    let a = rows
    let cofactors = [
      [
        a[1][1] * a[2][2] - a[1][2] * a[2][1], a[0][2] * a[2][1] - a[0][1] * a[2][2],
        a[0][1] * a[1][2] - a[0][2] * a[1][1],
      ],
      [
        a[1][2] * a[2][0] - a[1][0] * a[2][2], a[0][0] * a[2][2] - a[0][2] * a[2][0],
        a[0][2] * a[1][0] - a[0][0] * a[1][2],
      ],
      [
        a[1][0] * a[2][1] - a[1][1] * a[2][0], a[0][1] * a[2][0] - a[0][0] * a[2][1],
        a[0][0] * a[1][1] - a[0][1] * a[1][0],
      ],
    ]
    let determinant = Self.determinant(a)
    return try DeviceHomography(rows: cofactors.map { $0.map { $0 / determinant } })
  }

  private static func determinant(_ a: [[Double]]) -> Double {
    a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
      - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
      + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
  }
}

public struct DeviceCardResidual: Equatable, Sendable {
  public let angleDegrees: Double
  public let aspect: Double
  public let parallel: Double
}

public enum DeviceCardPlaneGeometry {
  public static let cardAspectRatio = 91.0 / 59.0
  public static let coordinateSystem = "source-pixel-boundary/table-short-side-unit/v1"
  public static let cornerOrder = "cyclic-short-edge-first/v1"
  public static let angleConvention = "positive-toward-positive-y-degrees/v1"

  public static func cyclicQuadrilateral(_ points: [DevicePoint2D]) throws -> [DevicePoint2D] {
    guard points.count == 4 else { throw DeviceCardPlaneGeometryError.invalidQuadrilateral }
    let center = DevicePoint2D(
      uncheckedX: points.reduce(0) { $0 + $1.x } / 4,
      y: points.reduce(0) { $0 + $1.y } / 4
    )
    guard center.x.isFinite, center.y.isFinite else {
      throw DeviceCardPlaneGeometryError.invalidQuadrilateral
    }
    let ordered = points.enumerated().sorted { left, right in
      let lhs = atan2(left.element.y - center.y, left.element.x - center.x)
      let rhs = atan2(right.element.y - center.y, right.element.x - center.x)
      return lhs == rhs ? left.offset < right.offset : lhs < rhs
    }.map(\.element)
    guard polygonArea(ordered) > 1e-6 else {
      throw DeviceCardPlaneGeometryError.invalidQuadrilateral
    }
    return ordered
  }

  public static func quadrilateralOrientations(_ points: [DevicePoint2D]) throws
    -> [[DevicePoint2D]]
  {
    let cyclic = try cyclicQuadrilateral(points)
    return [cyclic, Array(cyclic.dropFirst()) + [cyclic[0]]]
  }

  public static func cardVectors(_ points: [DevicePoint2D]) throws -> (
    short: DevicePoint2D, long: DevicePoint2D
  ) {
    guard points.count == 4 else { throw DeviceCardPlaneGeometryError.invalidQuadrilateral }
    let short = ((points[1] - points[0]) + (points[2] - points[3])) * 0.5
    let long = ((points[3] - points[0]) + (points[2] - points[1])) * 0.5
    guard [short, long].allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else {
      throw DeviceCardPlaneGeometryError.invalidQuadrilateral
    }
    return (short, long)
  }

  public static func cardResidual(_ points: [DevicePoint2D]) throws -> DeviceCardResidual {
    let vectors = try cardVectors(points)
    let shortLength = hypot(vectors.short.x, vectors.short.y)
    let longLength = hypot(vectors.long.x, vectors.long.y)
    guard shortLength.isFinite, longLength.isFinite, shortLength >= 1e-9, longLength >= 1e-9 else {
      throw DeviceCardPlaneGeometryError.invalidQuadrilateral
    }
    let cosine = abs(
      (vectors.short.x * vectors.long.x + vectors.short.y * vectors.long.y)
        / (shortLength * longLength))
    let angle = asin(min(1, cosine)) * 180 / .pi
    let aspect = abs(log((longLength / shortLength) / cardAspectRatio))
    let oppositeShort = points[2] - points[3]
    let oppositeLong = points[2] - points[1]
    let shortParallel =
      abs(cross(vectors.short, oppositeShort)) / (shortLength * max(length(oppositeShort), 1e-9))
    let longParallel =
      abs(cross(vectors.long, oppositeLong)) / (longLength * max(length(oppositeLong), 1e-9))
    let result = DeviceCardResidual(
      angleDegrees: angle, aspect: aspect, parallel: shortParallel + longParallel)
    guard result.angleDegrees.isFinite, result.aspect.isFinite, result.parallel.isFinite else {
      throw DeviceCardPlaneGeometryError.invalidQuadrilateral
    }
    return result
  }

  public static func cardQuadrilateral(
    center: DevicePoint2D,
    rotationDegrees: Double,
    shortSize: Double,
    longSize: Double
  ) throws -> [DevicePoint2D] {
    guard rotationDegrees.isFinite else { throw DeviceCardPlaneGeometryError.invalidRotation }
    guard shortSize.isFinite, longSize.isFinite, shortSize > 0, longSize > 0 else {
      throw DeviceCardPlaneGeometryError.invalidCardSize
    }
    let angle = rotationDegrees * .pi / 180
    let short = DevicePoint2D(uncheckedX: cos(angle), y: sin(angle)) * (shortSize / 2)
    let long = DevicePoint2D(uncheckedX: -sin(angle), y: cos(angle)) * (longSize / 2)
    let quad = [
      center - short - long, center + short - long, center + short + long, center - short + long,
    ]
    guard quad.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else {
      throw DeviceCardPlaneGeometryError.invalidCardSize
    }
    return quad
  }

  public static func projectFixedCard(
    tableToImage: DeviceHomography,
    center: DevicePoint2D,
    rotationDegrees: Double,
    shortSize: Double,
    longSize: Double
  ) throws -> [DevicePoint2D] {
    try tableToImage.apply(
      to: cardQuadrilateral(
        center: center,
        rotationDegrees: rotationDegrees,
        shortSize: shortSize,
        longSize: longSize
      ))
  }

  private static func polygonArea(_ points: [DevicePoint2D]) -> Double {
    abs(
      points.indices.reduce(0.0) { total, index in
        let next = points[(index + 1) % points.count]
        return total + points[index].x * next.y - next.x * points[index].y
      }) / 2
  }

  private static func cross(_ lhs: DevicePoint2D, _ rhs: DevicePoint2D) -> Double {
    lhs.x * rhs.y - lhs.y * rhs.x
  }

  private static func length(_ point: DevicePoint2D) -> Double { hypot(point.x, point.y) }
}

extension DevicePoint2D {
  fileprivate static func + (lhs: DevicePoint2D, rhs: DevicePoint2D) -> DevicePoint2D {
    DevicePoint2D(uncheckedX: lhs.x + rhs.x, y: lhs.y + rhs.y)
  }

  fileprivate static func - (lhs: DevicePoint2D, rhs: DevicePoint2D) -> DevicePoint2D {
    DevicePoint2D(uncheckedX: lhs.x - rhs.x, y: lhs.y - rhs.y)
  }

  fileprivate static func * (lhs: DevicePoint2D, rhs: Double) -> DevicePoint2D {
    DevicePoint2D(uncheckedX: lhs.x * rhs, y: lhs.y * rhs)
  }
}
