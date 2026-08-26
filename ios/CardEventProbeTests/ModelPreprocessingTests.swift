import XCTest
@testable import CardEventProbeCore

final class ModelPreprocessingTests: XCTestCase {
    func testLandscapeLetterboxPreservesAspectRatioAndCentersOnBlackCanvas() throws {
        let geometry = try LetterboxGeometry(
            sourceWidth: 400,
            sourceHeight: 200,
            targetSize: 224
        )

        XCTAssertEqual(geometry.sourceWidth, 400)
        XCTAssertEqual(geometry.sourceHeight, 200)
        XCTAssertEqual(geometry.resizedWidth, 224)
        XCTAssertEqual(geometry.resizedHeight, 112)
        XCTAssertEqual(geometry.xOffset, 0)
        XCTAssertEqual(geometry.yOffset, 56)
    }

    func testPortraitLetterboxPreservesAspectRatioAndCentersOnBlackCanvas() throws {
        let geometry = try LetterboxGeometry(
            sourceWidth: 200,
            sourceHeight: 400,
            targetSize: 224
        )

        XCTAssertEqual(geometry.resizedWidth, 112)
        XCTAssertEqual(geometry.resizedHeight, 224)
        XCTAssertEqual(geometry.xOffset, 56)
        XCTAssertEqual(geometry.yOffset, 0)
    }

    func testLetterboxRejectsInvalidFrameSize() {
        XCTAssertThrowsError(
            try LetterboxGeometry(sourceWidth: 0, sourceHeight: 200, targetSize: 224)
        ) { error in
            XCTAssertEqual(error as? ModelPreprocessingError, .invalidFrameSize)
        }
    }
}
