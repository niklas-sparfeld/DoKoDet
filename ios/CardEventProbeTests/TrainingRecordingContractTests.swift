import Foundation
import XCTest
@testable import CardEventProbeCore

final class TrainingRecordingContractTests: XCTestCase {
    func testSharedFixtureDecodesAndVerifiesFileHashes() throws {
        let manifest = try fixtureData(named: "manifest.json")
        let predictions = try fixtureData(named: "video-fixture-001.json")
        let video = try fixtureData(named: "video-fixture-001.mov")

        let result = try validateTrainingRecordingBundle(
            manifestData: manifest,
            predictionsData: predictions,
            videoData: video
        )

        XCTAssertEqual(result.0.recordingID, "recording-fixture-001")
        XCTAssertEqual(result.0.sessionID, "session-fixture-001")
        XCTAssertEqual(result.1.probabilities.count, result.0.predictions.sampleCount)
        XCTAssertEqual(result.1.eventProposals.count, result.0.predictions.eventProposalCount)
    }

    func testSharedMalformedVariantsAreRejected() throws {
        let manifestData = try fixtureData(named: "manifest.json")
        let predictionsData = try fixtureData(named: "video-fixture-001.json")
        let videoData = try fixtureData(named: "video-fixture-001.mov")

        var wrongHash = try jsonObject(manifestData)
        var wrongHashVideo = try XCTUnwrap(wrongHash["video"] as? [String: Any])
        wrongHashVideo["sha256"] = String(repeating: "0", count: 64)
        wrongHash["video"] = wrongHashVideo
        assertRejects(
            manifest: try jsonData(wrongHash),
            predictions: predictionsData,
            video: videoData
        )

        var wrongFileName = try jsonObject(manifestData)
        var wrongFileVideo = try XCTUnwrap(wrongFileName["video"] as? [String: Any])
        wrongFileVideo["name"] = "other-video.mov"
        wrongFileName["video"] = wrongFileVideo
        assertRejects(
            manifest: try jsonData(wrongFileName),
            predictions: predictionsData,
            video: videoData
        )

        var nonMonotonic = try jsonObject(predictionsData)
        var probabilitySamples = try XCTUnwrap(
            nonMonotonic["probabilities"] as? [[String: Any]]
        )
        probabilitySamples[0]["time_s"] = 0.2
        nonMonotonic["probabilities"] = probabilitySamples
        assertRejects(
            manifest: manifestData,
            predictions: try jsonData(nonMonotonic),
            video: videoData
        )

        var nonCausal = try jsonObject(predictionsData)
        var proposals = try XCTUnwrap(nonCausal["event_proposals"] as? [[String: Any]])
        proposals[0]["time_s"] = 0.2
        proposals[0]["emitted_at_s"] = 0.1
        nonCausal["event_proposals"] = proposals
        assertRejects(
            manifest: manifestData,
            predictions: try jsonData(nonCausal),
            video: videoData
        )

        var wrongIdentity = try jsonObject(predictionsData)
        wrongIdentity["source_video"] = "other-video.mov"
        assertRejects(
            manifest: manifestData,
            predictions: try jsonData(wrongIdentity),
            video: videoData
        )

        var unknownField = try jsonObject(manifestData)
        unknownField["unexpected"] = "not allowed"
        assertRejects(
            manifest: try jsonData(unknownField),
            predictions: predictionsData,
            video: videoData
        )
    }

    private func assertRejects(manifest: Data, predictions: Data, video: Data) {
        XCTAssertThrowsError(
            try validateTrainingRecordingBundle(
                manifestData: manifest,
                predictionsData: predictions,
                videoData: video
            )
        )
    }

    private func fixtureData(named name: String) throws -> Data {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // CardEventProbeTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
        return try Data(
            contentsOf: repositoryRoot
                .appendingPathComponent("fixtures/training-recording/v1/recording-fixture-001")
                .appendingPathComponent(name)
        )
    }

    private func jsonObject(_ data: Data) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func jsonData(_ object: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }
}
