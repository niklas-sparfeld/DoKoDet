import XCTest
@testable import CardEventProbeCore

final class ModelPreprocessingTests: XCTestCase {
    func testROIUsesFloorForOriginAndCeilForEnd() throws {
        let roi = try NormalizedROI(x: 0.125, y: 0.2, width: 0.5, height: 0.4)

        XCTAssertEqual(
            try roi.pixelCrop(frameWidth: 800, frameHeight: 500),
            PixelCrop(x: 100, y: 100, width: 400, height: 200)
        )
    }

    func testLetterboxPreservesAspectRatioAndCentersOnBlackCanvas() throws {
        let geometry = try LetterboxGeometry(
            crop: PixelCrop(x: 0, y: 0, width: 400, height: 200),
            targetSize: 224
        )

        XCTAssertEqual(geometry.resizedWidth, 224)
        XCTAssertEqual(geometry.resizedHeight, 112)
        XCTAssertEqual(geometry.xOffset, 0)
        XCTAssertEqual(geometry.yOffset, 56)
    }

    func testROIRejectsValuesOutsideNormalizedFrame() {
        XCTAssertThrowsError(try NormalizedROI(x: 0.5, y: 0.0, width: 0.6, height: 0.5))
    }
}
