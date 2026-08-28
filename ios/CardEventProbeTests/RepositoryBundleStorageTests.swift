import Foundation
import XCTest
@testable import CardEventProbeCore

final class RepositoryBundleStorageTests: XCTestCase {
    func testMemberByteMutationIsRejectedBeforeUpload() throws {
        let source = fixtureRoot().appendingPathComponent("both")
        let destination = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: destination) }
        try FileManager.default.copyItem(at: source, to: destination)

        let videoURL = destination.appendingPathComponent("videos/video-both.mov")
        var video = try Data(contentsOf: videoURL)
        video[0] ^= 0xff
        try video.write(to: videoURL)

        XCTAssertThrowsError(try validateRepositoryBundleDirectory(at: destination))
    }

    private func fixtureRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("fixtures/repository-bundle/v1")
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}
