import Foundation
import XCTest

@testable import CardEventProbeCore

final class DeviceCardPlaneGeometryTests: XCTestCase {
  func testHomographyMatchesPythonFixtureAndInverts() throws {
    let fixture = try loadFixture()
    let transform = try DeviceHomography(rows: matrix(fixture, "homography"))
    let input = try points(fixture, "points")
    let expected = try points(fixture, "projected_points")
    let actual = try transform.apply(to: input)
    assertPoints(actual, equalTo: expected, accuracy: 1e-10)

    let restored = try transform.inverted().apply(to: actual)
    assertPoints(restored, equalTo: try points(fixture, "inverse_points"), accuracy: 1e-10)
    XCTAssertEqual(try transform.apply(to: []), [])
  }

  func testCardGeometryMatchesPythonFixture() throws {
    let fixture = try loadFixture()
    let inputQuad = try points(fixture, "quad_input")
    assertPoints(
      try DeviceCardPlaneGeometry.cyclicQuadrilateral(inputQuad),
      equalTo: try points(fixture, "cyclic_quad"),
      accuracy: 1e-12
    )

    let center = try DevicePoint2D(x: 2, y: -3)
    let card = try DeviceCardPlaneGeometry.cardQuadrilateral(
      center: center,
      rotationDegrees: 30,
      shortSize: 1,
      longSize: DeviceCardPlaneGeometry.cardAspectRatio
    )
    assertPoints(card, equalTo: try points(fixture, "card_quad"), accuracy: 1e-12)

    let vectors = try DeviceCardPlaneGeometry.cardVectors(card)
    assertPoint(vectors.short, equalTo: try point(fixture, "card_short_vector"), accuracy: 1e-12)
    assertPoint(vectors.long, equalTo: try point(fixture, "card_long_vector"), accuracy: 1e-12)
    let residual = try DeviceCardPlaneGeometry.cardResidual(card)
    let expectedResidual = try numbers(fixture, "card_residual")
    XCTAssertEqual(residual.angleDegrees, expectedResidual[0], accuracy: 1e-12)
    XCTAssertEqual(residual.aspect, expectedResidual[1], accuracy: 1e-12)
    XCTAssertEqual(residual.parallel, expectedResidual[2], accuracy: 1e-12)

    let projected = try DeviceCardPlaneGeometry.projectFixedCard(
      tableToImage: DeviceHomography(rows: matrix(fixture, "homography")),
      center: center,
      rotationDegrees: 30,
      shortSize: 1,
      longSize: DeviceCardPlaneGeometry.cardAspectRatio
    )
    assertPoints(projected, equalTo: try points(fixture, "projected_card"), accuracy: 1e-10)
  }

  func testInvalidGeometryFailsAndInfinityIsNotProjected() throws {
    XCTAssertThrowsError(try DevicePoint2D(x: .infinity, y: 0)) {
      XCTAssertEqual($0 as? DeviceCardPlaneGeometryError, .invalidPoint)
    }
    XCTAssertThrowsError(try DeviceHomography(rows: [[1, 2, 3], [2, 4, 6], [0, 0, 1]])) {
      XCTAssertEqual($0 as? DeviceCardPlaneGeometryError, .invalidMatrix)
    }
    XCTAssertThrowsError(try DeviceCardPlaneGeometry.cyclicQuadrilateral([])) {
      XCTAssertEqual($0 as? DeviceCardPlaneGeometryError, .invalidQuadrilateral)
    }

    let horizon = try DeviceHomography(rows: [[0, 0, 1], [0, 1, 0], [1, 0, 0]])
    XCTAssertThrowsError(try horizon.apply(to: [DevicePoint2D(x: 0, y: 2)])) {
      XCTAssertEqual($0 as? DeviceCardPlaneGeometryError, .pointAtInfinity)
    }
  }

  func testInitialTablePlaneFitSeedMatchesPythonFixture() throws {
    let fixture = try loadFitSeedFixture()
    let input = try XCTUnwrap(fixture["source_quads"] as? [[[Double]]]).map { quad in
      try quad.map { try DevicePoint2D(x: $0[0], y: $0[1]) }
    }
    let seed = try DeviceTablePlaneFit.initialImageToTable(input)
    let expected = try XCTUnwrap(fixture["expected_homography"] as? [[Double]])
    for row in 0..<3 {
      for column in 0..<3 {
        XCTAssertEqual(seed.imageToTable.rows[row][column], expected[row][column], accuracy: 2e-6)
      }
    }
    XCTAssertEqual(seed.seedObservationIndex, try XCTUnwrap(fixture["expected_seed_index"] as? Int))
    XCTAssertEqual(
      seed.seedOrientationIndex, try XCTUnwrap(fixture["expected_orientation_index"] as? Int))
    XCTAssertEqual(
      seed.medianCardResidual,
      try XCTUnwrap(fixture["expected_median_residual"] as? Double),
      accuracy: 2e-6
    )
  }

  func testInitialTablePlaneFitSeedRejectsEmptyAndInvalidInput() throws {
    XCTAssertThrowsError(try DeviceTablePlaneFit.initialImageToTable([])) {
      XCTAssertEqual($0 as? DeviceTablePlaneFitSeedError, .noObservations)
    }
    XCTAssertThrowsError(try DeviceTablePlaneFit.initialImageToTable([[]])) {
      XCTAssertEqual($0 as? DeviceTablePlaneFitSeedError, .invalidQuadrilateral)
    }
  }

  func testRobustTablePlaneFitReturnsFiniteCandidateForSyntheticBoundaries() throws {
    let tableToImage = try DeviceHomography(rows: [
      [720, 80, 900], [24, 560, 250], [0.0003, 0.0006, 1],
    ])
    let positions: [(Double, Double)] = [
      (0, 0), (4, 0), (8, 0), (0, 3), (4, 3), (8, 3), (0, 6), (4, 6), (8, 6),
    ]
    let quads = try positions.enumerated().map { index, center in
      try DeviceCardPlaneGeometry.projectFixedCard(
        tableToImage: tableToImage,
        center: DevicePoint2D(x: center.0, y: center.1),
        rotationDegrees: Double(index % 4) * 9,
        shortSize: 1,
        longSize: DeviceCardPlaneGeometry.cardAspectRatio
      )
    }
    let boundaries = quads.map { quad in
      (0..<64).map { sample -> DevicePoint2D in
        let position = Double(sample) * 4 / 64
        let edge = Int(position)
        let fraction = position - Double(edge)
        let first = quad[edge]
        let second = quad[(edge + 1) % 4]
        return try! DevicePoint2D(
          x: first.x + fraction * (second.x - first.x),
          y: first.y + fraction * (second.y - first.y))
      }
    }

    let fit = try DeviceTablePlaneFit.fitTablePlane(quads, boundarySamples: boundaries)
    XCTAssertTrue(fit.imageToTable.rows.flatMap { $0 }.allSatisfy(\.isFinite))
    XCTAssertEqual(fit.inlierIndices.count, quads.count)
    XCTAssertTrue(fit.medianBoundaryResidual.isFinite)
    XCTAssertFalse(fit.convergenceReason.isEmpty)
    let pythonMatrix = [
      [0.001391, -0.000198, -1.202112],
      [-0.000057, 0.001785, -0.394631],
      [0, -0.000001, 1.000606],
    ]
    for row in 0..<3 {
      for column in 0..<3 {
        XCTAssertEqual(
          fit.imageToTable.rows[row][column], pythonMatrix[row][column], accuracy: 0.00001)
      }
    }
    XCTAssertEqual(fit.medianBoundaryResidual, 0.002054, accuracy: 0.0001)
    XCTAssertTrue(fit.qualityPassed)
  }

  func testRobustTablePlaneFitRejectsOneInconsistentBoundary() throws {
    let tableToImage = try DeviceHomography(rows: [
      [210, 18, 520], [12, 172, 315], [0.0002, 0.0005, 1],
    ])
    let positions: [(Double, Double)] = [
      (0, 0), (4, 0), (8, 0), (0, 3), (4, 3), (8, 3), (0, 6), (4, 6), (8, 6),
    ]
    let quads = try positions.enumerated().map { index, center in
      try DeviceCardPlaneGeometry.projectFixedCard(
        tableToImage: tableToImage,
        center: DevicePoint2D(x: center.0, y: center.1),
        rotationDegrees: Double(index % 4) * 9,
        shortSize: 1,
        longSize: DeviceCardPlaneGeometry.cardAspectRatio
      )
    }
    let boundaries = try quads.enumerated().map { index, quad in
      let center = try DevicePoint2D(
        x: quad.map(\.x).reduce(0, +) / 4, y: quad.map(\.y).reduce(0, +) / 4)
      let observed =
        index == 4
        ? quad.map { point in
          try! DevicePoint2D(
            x: center.x + 0.72 * (point.x - center.x), y: center.y + 0.72 * (point.y - center.y))
        } : quad
      return (0..<64).map { sample -> DevicePoint2D in
        let position = Double(sample) * 4 / 64
        let edge = Int(position)
        let fraction = position - Double(edge)
        let first = observed[edge]
        let second = observed[(edge + 1) % 4]
        return try! DevicePoint2D(
          x: first.x + fraction * (second.x - first.x),
          y: first.y + fraction * (second.y - first.y))
      }
    }

    let fit = try DeviceTablePlaneFit.fitTablePlane(quads, boundarySamples: boundaries)
    XCTAssertEqual(fit.rejectedIndices, [4])
    XCTAssertEqual(fit.inlierIndices.count, 8)
    XCTAssertTrue(fit.qualityPassed)
  }

  func testRobustTablePlaneFitRejectsEmptyAndInvalidWeights() throws {
    XCTAssertThrowsError(try DeviceTablePlaneFit.fitTablePlane([])) {
      XCTAssertEqual($0 as? DeviceTablePlaneBoundaryFitError, .noObservations)
    }
    let quad = try (0..<4).map { index in
      try DevicePoint2D(x: Double(index % 2), y: Double(index / 2))
    }
    XCTAssertThrowsError(try DeviceTablePlaneFit.fitTablePlane([quad], observationWeights: [-1]))
    let degenerate = try (0..<4).map { index in
      try DevicePoint2D(x: Double(index), y: Double(index))
    }
    XCTAssertThrowsError(try DeviceTablePlaneFit.fitTablePlane([degenerate])) {
      XCTAssertEqual($0 as? DeviceTablePlaneBoundaryFitError, .invalidQuadrilateral)
    }
  }

  private func loadFixture() throws -> [String: Any] {
    let url = try XCTUnwrap(
      Bundle.module.url(
        forResource: "table_plane_geometry_v1", withExtension: "json", subdirectory: "Fixtures"))
    return try XCTUnwrap(
      JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
  }

  private func loadFitSeedFixture() throws -> [String: Any] {
    let url = try XCTUnwrap(
      Bundle.module.url(
        forResource: "table_plane_fit_seed_v1", withExtension: "json", subdirectory: "Fixtures"))
    return try XCTUnwrap(
      JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
  }

  private func matrix(_ fixture: [String: Any], _ key: String) throws -> [[Double]] {
    try XCTUnwrap(fixture[key] as? [[Double]])
  }

  private func numbers(_ fixture: [String: Any], _ key: String) throws -> [Double] {
    try XCTUnwrap(fixture[key] as? [Double])
  }

  private func points(_ fixture: [String: Any], _ key: String) throws -> [DevicePoint2D] {
    try numbers2D(fixture, key).map { try DevicePoint2D(x: $0[0], y: $0[1]) }
  }

  private func point(_ fixture: [String: Any], _ key: String) throws -> DevicePoint2D {
    let values = try numbers(fixture, key)
    return try DevicePoint2D(x: values[0], y: values[1])
  }

  private func numbers2D(_ fixture: [String: Any], _ key: String) throws -> [[Double]] {
    try XCTUnwrap(fixture[key] as? [[Double]])
  }

  private func assertPoints(
    _ actual: [DevicePoint2D], equalTo expected: [DevicePoint2D], accuracy: Double,
    file: StaticString = #filePath, line: UInt = #line
  ) {
    XCTAssertEqual(actual.count, expected.count, file: file, line: line)
    for (left, right) in zip(actual, expected) {
      assertPoint(left, equalTo: right, accuracy: accuracy, file: file, line: line)
    }
  }

  private func assertPoint(
    _ actual: DevicePoint2D, equalTo expected: DevicePoint2D, accuracy: Double,
    file: StaticString = #filePath, line: UInt = #line
  ) {
    XCTAssertEqual(actual.x, expected.x, accuracy: accuracy, file: file, line: line)
    XCTAssertEqual(actual.y, expected.y, accuracy: accuracy, file: file, line: line)
  }
}
