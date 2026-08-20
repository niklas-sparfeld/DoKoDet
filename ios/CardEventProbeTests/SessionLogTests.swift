import Foundation
import XCTest
@testable import CardEventProbeCore

final class SessionLogTests: XCTestCase {
    func testWritesSessionPredictionAndAnnotationAsJSONLines() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let log = try SessionLog(
            directory: directory,
            metadata: SessionLogMetadata(
                source: .live,
                appVersion: "1",
                device: "Test device",
                osVersion: "Test OS",
                modelName: "CardEventNet",
                modelVersion: "test",
                targetInferenceHz: 8.0,
                highThreshold: 0.75,
                lowThreshold: 0.35
            )
        )
        try log.appendPrediction(
            SessionLogPrediction(
                source: .live,
                timestampSeconds: 12.375,
                rawProbability: 0.83,
                smoothedProbability: 0.83,
                eventEmitted: true,
                inferenceMs: 14.2
            )
        )
        try log.appendAnnotation(
            SessionLogAnnotation(source: .live, timestampSeconds: 12.375, kind: .missedEvent)
        )
        log.close()

        let lines = try String(contentsOf: log.url, encoding: .utf8)
            .split(separator: "\n")
            .map(String.init)
        XCTAssertEqual(lines.count, 3)

        let first = try json(lines[0])
        XCTAssertEqual(first["type"] as? String, "session")
        XCTAssertEqual(first["source"] as? String, "live")
        XCTAssertEqual(first["targetInferenceHz"] as? Double, 8.0)

        let second = try json(lines[1])
        XCTAssertEqual(second["type"] as? String, "prediction")
        XCTAssertEqual(second["eventEmitted"] as? Bool, true)
        XCTAssertEqual(second["inferenceMs"] as? Double, 14.2)

        let third = try json(lines[2])
        XCTAssertEqual(third["type"] as? String, "annotation")
        XCTAssertEqual(third["kind"] as? String, "missed_event")
    }

    private func json(_ line: String) throws -> [String: Any] {
        try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
        )
    }
}
