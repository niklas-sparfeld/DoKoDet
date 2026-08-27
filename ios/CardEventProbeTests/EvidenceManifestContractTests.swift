import AVFoundation
import CoreVideo
import Foundation
import XCTest
@testable import CardEventProbeCore

final class EvidenceManifestContractTests: XCTestCase {
    func testSharedCompleteAndIncompleteFixturesDecodeAndReencode() throws {
        for fixtureName in ["example-complete", "example-incomplete"] {
            let source = try fixtureData(named: fixtureName)
            let decoder = JSONDecoder()
            let manifest = try decoder.decode(EvidencePackageManifest.self, from: source)
            let encoded = try manifest.encoded()
            let sourceJSON = try jsonObject(source)
            let encodedJSON = try jsonObject(encoded)

            XCTAssertTrue(
                sourceJSON.isEqual(encodedJSON),
                "Swift must preserve the shared fixture manifest contract."
            )
        }
    }

    func testSharedFixturesHaveOnlyTheVersionedTopLevelFields() throws {
        let expectedFields: Set<String> = [
            "schema_version",
            "package_id",
            "session",
            "event",
            "model",
            "event_decoder",
            "evidence_capture",
            "video_capture",
            "camera",
            "frames",
            "video_snippet",
            "missing_frame_targets_ms",
            "score_trace",
            "client",
        ]

        for fixtureName in ["example-complete", "example-incomplete"] {
            let object = try XCTUnwrap(
                try JSONSerialization.jsonObject(with: fixtureData(named: fixtureName))
                    as? [String: Any]
            )
            XCTAssertEqual(Set(object.keys), expectedFields)
            XCTAssertNil(object["player"])
            XCTAssertNil(object["turn"])
        }
    }

    func testManifestDecoderRejectsAnInconsistentTargetSet() throws {
        var object = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: fixtureData(named: "example-complete"))
                as? [String: Any]
        )
        var event = try XCTUnwrap(object["event"] as? [String: Any])
        event["evidence_complete"] = false
        object["event"] = event
        let invalid = try JSONSerialization.data(withJSONObject: object)

        XCTAssertThrowsError(
            try JSONDecoder().decode(EvidencePackageManifest.self, from: invalid)
        )
    }

    func testManifestDecoderRejectsUnknownTopLevelFields() throws {
        var object = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: fixtureData(named: "example-complete"))
                as? [String: Any]
        )
        object["future_field"] = true
        let invalid = try JSONSerialization.data(withJSONObject: object)

        XCTAssertThrowsError(
            try JSONDecoder().decode(EvidencePackageManifest.self, from: invalid)
        )
    }

    func testMissingSnippetAndExplicitCaptureFailureRemainDistinct() throws {
        let complete = try JSONDecoder().decode(
            EvidencePackageManifest.self,
            from: fixtureData(named: "example-complete")
        )
        let incomplete = try JSONDecoder().decode(
            EvidencePackageManifest.self,
            from: fixtureData(named: "example-incomplete")
        )
        XCTAssertNotNil(complete.videoSnippet)
        XCTAssertNil(incomplete.videoSnippet)
        XCTAssertFalse(EvidenceVideoSnippetManifest(failureReason: "encoder unavailable").captureComplete)
    }

    func testCanonicalSnippetDecodesWithAVFoundation() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let url = root
            .appendingPathComponent("fixtures/evidence/v2/example-complete", isDirectory: true)
            .appendingPathComponent("snippet.mp4")
        let asset = AVURLAsset(url: url)
        let tracks = asset.tracks(withMediaType: .video)
        XCTAssertEqual(tracks.count, 1)
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(
            track: try XCTUnwrap(tracks.first),
            outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        )
        XCTAssertTrue(reader.canAdd(output))
        reader.add(output)
        XCTAssertTrue(reader.startReading())

        var frameCount = 0
        while output.copyNextSampleBuffer() != nil {
            frameCount += 1
        }
        XCTAssertEqual(reader.status, .completed)
        XCTAssertEqual(frameCount, 32)
    }

    private func fixtureData(named name: String) throws -> Data {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // CardEventProbeTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
        let url = repositoryRoot
            .appendingPathComponent("fixtures/evidence/v2", isDirectory: true)
            .appendingPathComponent(name, isDirectory: true)
            .appendingPathComponent("manifest.json")
        return try Data(contentsOf: url)
    }

    private func jsonObject(_ data: Data) throws -> NSDictionary {
        try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? NSDictionary
        )
    }
}
