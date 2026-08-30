import Foundation
import XCTest
@testable import CardEventProbeCore

final class RecordingProfileStorageTests: XCTestCase {
    func testOperatorSettingsStoreRoundTripsSettingsOutsideProfile() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = OperatorSettingsStore(directory: directory)

        XCTAssertNil(try store.load())
        try store.save(OperatorSettings(operatorName: "alice"))

        XCTAssertEqual(
            try OperatorSettingsStore(directory: directory).load(),
            OperatorSettings(operatorName: "alice")
        )
    }

    func testRecordingProfileStoreDoesNotFailWhenOneProfileIsCorrupt() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let profile = RecordingProfile(
            profileID: "profile-fixture-001",
            name: "Kitchen overhead",
            purpose: .approximateFortyCardSetup,
            tags: ["kitchen"]
        )
        let store = RecordingProfileStore(directory: directory)
        try store.save(profile)
        try Data("not json".utf8).write(
            to: directory.appendingPathComponent("corrupt.json")
        )

        XCTAssertEqual(try store.loadAll(), [profile])
        XCTAssertNil(store.obsoleteFileNotice)
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}
