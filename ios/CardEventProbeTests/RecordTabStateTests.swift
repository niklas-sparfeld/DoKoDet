import XCTest
@testable import CardEventProbeCore

final class RecordTabStateTests: XCTestCase {
    func testRecordTabNavigationIsExplicitAndReachable() {
        var state = RecordTabState()

        XCTAssertEqual(state.selectedTab, .live)
        state.select(.record)

        XCTAssertEqual(state.selectedTab, .record)
        XCTAssertTrue(state.isRecordTabSelected)
    }

    func testRecordTabExposesFieldLevelValidationBeforeUpload() {
        var profile = CollectionProfile.newDraft()
        profile.operatorName = ""
        var state = RecordTabState(profile: profile)

        XCTAssertFalse(state.canFinalize)
        XCTAssertEqual(state.message(for: .operatorName), "Enter the operator name.")

        profile.operatorName = "operator"
        state.update(profile: profile)

        XCTAssertNil(state.message(for: .operatorName))
    }
}
