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
        var profile = RecordingProfile.newDraft()
        var state = RecordTabState(profile: profile)

        XCTAssertFalse(state.canFinalize)
        XCTAssertEqual(state.message(for: .name), "Enter a profile name.")

        profile.name = "profile"
        state.update(profile: profile)

        XCTAssertNil(state.message(for: .name))
    }
}
