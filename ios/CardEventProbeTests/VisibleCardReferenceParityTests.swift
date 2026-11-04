import Foundation
import CoreML
import CryptoKit
import ImageIO
import XCTest
@testable import CardEventProbeCore

@_silgen_name("uncompress")
private func zlibUncompress(
    _ destination: UnsafeMutablePointer<UInt8>,
    _ destinationLength: UnsafeMutablePointer<UInt>,
    _ source: UnsafePointer<UInt8>,
    _ sourceLength: UInt
) -> Int32

final class VisibleCardReferenceParityTests: XCTestCase {
    func testAllFrozenRfdetrFramesAgainstPythonReference() throws {
        guard let rootPath = ProcessInfo.processInfo.environment["DEVICE_VISIBLE_CARD_REFERENCE_ROOT"] else {
            throw XCTSkip("Set DEVICE_VISIBLE_CARD_REFERENCE_ROOT to the primary checkout to run frozen model parity.")
        }
        let root = URL(fileURLWithPath: rootPath, isDirectory: true)
        let modelURL = root.appendingPathComponent(".runtime/0104-m1/rfdetr-seg-medium.mlpackage")
        let framesURL = root.appendingPathComponent(".runtime/0103-m0/inputs/frames")
        let referenceURL = root.appendingPathComponent("docs/reports/0103-M0_Python_References.json")
        let manifestURL = root.appendingPathComponent("docs/reports/0103-M0_Input_Manifest.json")
        let referenceData = try Data(contentsOf: referenceURL)
        let referenceRoot = try XCTUnwrap(JSONSerialization.jsonObject(with: referenceData) as? [String: Any])
        let rfdetr = try XCTUnwrap(referenceRoot["rfdetr"] as? [String: Any])
        let frames = try XCTUnwrap(rfdetr["frames"] as? [String: Any])
        let manifest = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any])
        let inputFrames = try XCTUnwrap(manifest["frames"] as? [[String: Any]])
        let compiledModelURL = try MLModel.compileModel(at: modelURL)
        let runner = try RfdetrCoreMLRunner(modelURL: compiledModelURL)
        let names = ["frame-02s.png", "frame-08s.png", "frame-12s.png", "frame-20s.png", "frame-40s.png", "frame-70s.png"]
        var report: [[String: Any]] = []

        for name in names {
            let frameURL = framesURL.appendingPathComponent(name)
            let frameBytes = try Data(contentsOf: frameURL)
            let inputRecord = try XCTUnwrap(inputFrames.first { ($0["path"] as? String)?.hasSuffix(name) == true })
            XCTAssertEqual(sha256(frameBytes), inputRecord["sha256"] as? String, "\(name) frozen input digest")
            XCTAssertEqual(inputRecord["width"] as? Int, 1_920)
            XCTAssertEqual(inputRecord["height"] as? Int, 1_080)
            let source = try XCTUnwrap(CGImageSourceCreateWithURL(frameURL as CFURL, nil))
            let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
            let raw = try runner.predict(RfdetrImageTensor(cgImage: image))
            let actual = try DeviceVisibleCardPostprocessor.processWithCandidates(
                raw,
                imageWidth: image.width,
                imageHeight: image.height
            ).candidates
            let frameReference = try XCTUnwrap(frames[name] as? [String: Any])
            let expected = try XCTUnwrap(frameReference["threshold_free_candidates"] as? [[String: Any]])
            XCTAssertEqual(actual.count, expected.count, "\(name) candidate count")

            var thresholdFreeDifferences = 0
            let pairCount = min(actual.count, expected.count)
            for index in 0..<pairCount {
                guard let classID = expected[index]["class_id"] as? Int,
                      let score = expected[index]["score"] as? Double,
                      let box = expected[index]["box_xyxy"] as? [Double], box.count == 4 else {
                    XCTFail("Malformed frozen RF-DETR candidate for \(name) at \(index)")
                    continue
                }
                let normalizedExpected = [box[0] / Double(image.width), box[1] / Double(image.height),
                                          box[2] / Double(image.width), box[3] / Double(image.height)]
                let normalizedActual = [
                    actual[index].boxXYXY[0] / Double(image.width),
                    actual[index].boxXYXY[1] / Double(image.height),
                    actual[index].boxXYXY[2] / Double(image.width),
                    actual[index].boxXYXY[3] / Double(image.height),
                ]
                let differs = classID != actual[index].classID
                    || !withinTolerance(score, actual[index].score)
                    || zip(normalizedExpected, normalizedActual).contains { pair in abs(pair.0 - pair.1) > 1e-4 }
                if differs { thresholdFreeDifferences += 1 }
            }

            let expectedAccepted = expected.filter { ($0["score"] as? Double ?? 0) > 0.5 }
            let actualAccepted = actual.filter { $0.score > 0.5 }
            XCTAssertEqual(actualAccepted.count, expectedAccepted.count, "\(name) above-threshold count")
            var acceptedDifferences = 0
            var acceptedMismatchDetails: [[String: Any]] = []
            for index in 0..<min(actualAccepted.count, expectedAccepted.count) {
                let expectedItem = expectedAccepted[index]
                let classID = expectedItem["class_id"] as? Int ?? -1
                let score = expectedItem["score"] as? Double ?? -1
                let box = expectedItem["box_xyxy"] as? [Double] ?? []
                let normalizedExpected = box.count == 4
                    ? [box[0] / Double(image.width), box[1] / Double(image.height), box[2] / Double(image.width), box[3] / Double(image.height)]
                    : []
                let normalizedActual = [
                    actualAccepted[index].boxXYXY[0] / Double(image.width),
                    actualAccepted[index].boxXYXY[1] / Double(image.height),
                    actualAccepted[index].boxXYXY[2] / Double(image.width),
                    actualAccepted[index].boxXYXY[3] / Double(image.height),
                ]
                let differs = classID != actualAccepted[index].classID
                    || !withinTolerance(score, actualAccepted[index].score)
                    || normalizedExpected.count != 4
                    || zip(normalizedExpected, normalizedActual).contains(where: { abs($0 - $1) > 1e-4 })
                if differs {
                    acceptedDifferences += 1
                    acceptedMismatchDetails.append([
                        "rank": index,
                        "expected_class_id": classID,
                        "actual_class_id": actualAccepted[index].classID,
                        "expected_score": score,
                        "actual_score": actualAccepted[index].score,
                        "expected_box_normalized": normalizedExpected,
                        "actual_box_normalized": normalizedActual,
                    ])
                }
            }
            var maskPairs: [(iou: Double, reference: Int, candidate: Int)] = []
            let expectedMasks = try expectedAccepted.map { try binaryMask($0, width: image.width, height: image.height) }
            let actualMasks = try actualAccepted.map {
                try DeviceVisibleCardPostprocessor.binaryMask(
                    raw,
                    queryIndex: $0.queryIndex,
                    width: image.width,
                    height: image.height
                )
            }
            for referenceIndex in expectedAccepted.indices {
                let referenceClass = expectedAccepted[referenceIndex]["class_id"] as? Int ?? -1
                for candidateIndex in actualAccepted.indices where actualAccepted[candidateIndex].classID == referenceClass {
                    let intersection = zip(expectedMasks[referenceIndex], actualMasks[candidateIndex])
                        .reduce(0) { $0 + ($1.0 == 1 && $1.1 == 1 ? 1 : 0) }
                    let union = zip(expectedMasks[referenceIndex], actualMasks[candidateIndex])
                        .reduce(0) { $0 + ($1.0 == 1 || $1.1 == 1 ? 1 : 0) }
                    let iou = union == 0 ? 1 : Double(intersection) / Double(union)
                    maskPairs.append((iou, referenceIndex, candidateIndex))
                }
            }
            maskPairs.sort { $0.iou > $1.iou }
            var usedReferenceMasks = Set<Int>()
            var usedCandidateMasks = Set<Int>()
            var matchedMaskIoUs: [Double] = []
            for pair in maskPairs where pair.iou >= 0.5 {
                guard usedReferenceMasks.insert(pair.reference).inserted else { continue }
                guard usedCandidateMasks.insert(pair.candidate).inserted else {
                    usedReferenceMasks.remove(pair.reference)
                    continue
                }
                matchedMaskIoUs.append(pair.iou)
            }
            report.append([
                "frame": name,
                "candidate_count": actual.count,
                "threshold_free_differences": thresholdFreeDifferences,
                "accepted_count": actualAccepted.count,
                "accepted_score_or_box_differences": acceptedDifferences,
                "accepted_mismatches": acceptedMismatchDetails,
                "matched_above_threshold_masks": matchedMaskIoUs.count,
                "unmatched_reference_masks": expectedAccepted.count - matchedMaskIoUs.count,
                "unmatched_candidate_masks": actualAccepted.count - matchedMaskIoUs.count,
                "minimum_matched_mask_iou": matchedMaskIoUs.min() ?? NSNull(),
            ])
            XCTAssertEqual(matchedMaskIoUs.count, expectedAccepted.count, "\(name) above-threshold mask matching")
        }
        print("DEVICE_VISIBLE_CARD_PARITY \(String(data: try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), encoding: .utf8) ?? "[]")")
    }

    private func withinTolerance(_ expected: Double, _ actual: Double) -> Bool {
        abs(expected - actual) <= 1e-4 + 1e-4 * abs(expected)
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func binaryMask(_ item: [String: Any], width: Int, height: Int) throws -> [UInt8] {
        let base64 = try XCTUnwrap(item["mask_packbits_little_zlib_base64"] as? String)
        let compressed = try XCTUnwrap(Data(base64Encoded: base64))
        var packed: [UInt8] = []
        let packedCount = (width * height + 7) / 8
        packed = [UInt8](repeating: 0, count: packedCount)
        var destinationLength = UInt(packedCount)
        let status = compressed.withUnsafeBytes { source in
            packed.withUnsafeMutableBufferPointer { destination in
                zlibUncompress(
                    destination.baseAddress!,
                    &destinationLength,
                    source.bindMemory(to: UInt8.self).baseAddress!,
                    UInt(compressed.count)
                )
            }
        }
        XCTAssertEqual(status, 0)
        XCTAssertEqual(destinationLength, UInt(packedCount))
        guard status == 0, destinationLength == UInt(packedCount), packed.count == packedCount else {
            throw NSError(domain: "VisibleCardReferenceParity", code: 2)
        }
        return (0..<(width * height)).map { index in
            (packed[index / 8] >> UInt8(index % 8)) & 1
        }
    }
}
