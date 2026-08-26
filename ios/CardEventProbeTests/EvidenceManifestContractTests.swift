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
            "camera",
            "frames",
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

    private func fixtureData(named name: String) throws -> Data {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // CardEventProbeTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
        let url = repositoryRoot
            .appendingPathComponent("fixtures/evidence/v1", isDirectory: true)
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
