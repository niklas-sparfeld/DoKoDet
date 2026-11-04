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

  private func loadFixture() throws -> [String: Any] {
    let url = try XCTUnwrap(
      Bundle.module.url(
        forResource: "table_plane_geometry_v1", withExtension: "json", subdirectory: "Fixtures"))
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
