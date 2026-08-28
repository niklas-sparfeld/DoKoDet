import Foundation
import XCTest
@testable import CardEventProbeCore

final class RepositoryIntakeContractTests: XCTestCase {
    private let fixtureNames = ["cardevent-only", "table-evidence-only", "both"]

    func testReplacementFixturesDecodeInSwiftAndPreserveIndependentSelection() throws {
        for fixtureName in fixtureNames {
            let root = try fixtureRoot(named: fixtureName)
            let bundle = try decode(RepositoryBundle.self, at: root.appendingPathComponent("manifest.json"))
            let source = try decode(RepositorySourceRecord.self, at: root.appendingPathComponent("source-record.json"))
            let enrollments = try decode(
                RepositoryTaskEnrollmentDocument.self,
                at: root.appendingPathComponent("initial-task-enrollment.json")
            )
            let runs = try bundle.files.proposalGeneratorRuns.map { proposalFile in
                try decode(RepositoryProposalGeneratorRun.self, at: root.appendingPathComponent(proposalFile.relativePath))
            }
            try RepositoryIntakeContract.validate(
                bundle: bundle,
                source: source,
                enrollments: enrollments,
                proposalRuns: runs
            )
            let videoData = try Data(contentsOf: root.appendingPathComponent(bundle.files.video.relativePath))
            try verifyRepositoryBytes(videoData, descriptor: bundle.files.video)
            XCTAssertEqual(source.sha256, bundle.sourceSHA256)
            XCTAssertEqual(runs.first?.purpose, "proposal_only")

            let selected = enrollments.enrollments
                .filter { $0.disposition == .selected }
                .map(\.task)
            let expected: [RepositoryDataTask]
            switch fixtureName {
            case "cardevent-only": expected = [.cardEventDetection]
            case "table-evidence-only": expected = [.tableEvidenceAnalysis]
            default: expected = RepositoryDataTask.allCases
            }
            XCTAssertEqual(Set(selected), Set(expected))
        }
    }

    func testReplacementFixtureDirectoryHasOnlyDeclaredMembersAndValidHashes() throws {
        let root = try fixtureRoot(named: "both")
        let bundle = try validateRepositoryBundleDirectory(at: root)

        XCTAssertEqual(bundle.recordingID, "recording-both")
        XCTAssertEqual(
            bundle.files.proposalGeneratorRuns.map(\.relativePath),
            ["predictions/proposal-both.json"]
        )
    }

    func testReplacementContractRejectsUnknownFieldsAndLegacyAliases() throws {
        let root = try fixtureRoot(named: "both")
        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(
                with: Data(contentsOf: root.appendingPathComponent("manifest.json"))
            ) as? [String: Any]
        )
        object["recording"] = object.removeValue(forKey: "recording_id")
        let malformed = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        XCTAssertThrowsError(try JSONDecoder().decode(RepositoryBundle.self, from: malformed))

        var enrollment = try XCTUnwrap(
            JSONSerialization.jsonObject(
                with: Data(contentsOf: root.appendingPathComponent("initial-task-enrollment.json"))
            ) as? [String: Any]
        )
        var values = try XCTUnwrap(enrollment["enrollments"] as? [[String: Any]])
        values[0]["legacy_disposition"] = "selected"
        enrollment["enrollments"] = values
        let malformedEnrollment = try JSONSerialization.data(withJSONObject: enrollment, options: [.sortedKeys])
        XCTAssertThrowsError(
            try JSONDecoder().decode(RepositoryTaskEnrollmentDocument.self, from: malformedEnrollment)
        )
    }

    private func decode<T: Decodable>(_ type: T.Type, at url: URL) throws -> T {
        try JSONDecoder().decode(type, from: Data(contentsOf: url))
    }

    private func fixtureRoot(named name: String) throws -> URL {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // CardEventProbeTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
        let root = repositoryRoot
            .appendingPathComponent("fixtures/repository-bundle/v1")
            .appendingPathComponent(name)
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.path))
        return root
    }
}
