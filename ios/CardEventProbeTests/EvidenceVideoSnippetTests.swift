import AVFoundation
import CoreMedia
import CryptoKit
import Foundation
import XCTest
@testable import CardEventProbeCore

final class EvidenceVideoSnippetTests: XCTestCase {
    func testLiveCaptureKeepsARealTimeBoundedBufferAndCapturesOneSnippet() throws {
        let configuration = EvidenceVideoCaptureMetadata(
            requestedStartOffsetMs: -250,
            requestedEndOffsetMs: 250,
            maxDurationMs: 1_000,
            maxWidth: 320,
            maxHeight: 180,
            maxNominalFrameRate: 10.0,
            maxByteLength: 250_000,
            queuedByteCapacity: 1_000_000
        )
        let provider = LiveEvidenceVideoSnippetProvider(
            configuration: configuration,
            minimumCoverageStartOffsetMs: -100,
            maximumCoverageEndOffsetMs: 100,
            temporaryByteCapacity: 320 * 180 * 4 * 20
        )

        for index in 0...10 {
            provider.consume(
                VideoFrame(
                    pixelBuffer: try makePixelBuffer(width: 640, height: 360),
                    timestamp: time(Double(index) / 10.0),
                    orientation: .up
                )
            )
        }

        let snippet = try provider.capture(eventTimestamp: time(0.5))

        XCTAssertEqual(snippet.manifest.container, "mp4")
        XCTAssertEqual(snippet.manifest.videoCodec, "h264")
        XCTAssertEqual(snippet.manifest.width, 320)
        XCTAssertEqual(snippet.manifest.height, 180)
        XCTAssertLessThanOrEqual(snippet.manifest.byteLength, configuration.maxByteLength)
        XCTAssertLessThanOrEqual(provider.status.bufferedFrameCount, 11)
        XCTAssertEqual(provider.status.completedCaptureCount, 1)
        XCTAssertEqual(provider.status.failedCaptureCount, 0)
    }

    func testLiveCaptureStopReleasesTheRollingBufferAndCancelsPendingCapture() throws {
        let provider = LiveEvidenceVideoSnippetProvider(
            configuration: EvidenceVideoCaptureMetadata(
                requestedStartOffsetMs: -250,
                requestedEndOffsetMs: 1_000,
                maxDurationMs: 1_500,
                maxWidth: 320,
                maxHeight: 180,
                maxNominalFrameRate: 10.0,
                maxByteLength: 250_000,
                queuedByteCapacity: 1_000_000
            ),
            minimumCoverageStartOffsetMs: -100,
            maximumCoverageEndOffsetMs: 100,
            temporaryByteCapacity: 320 * 180 * 4 * 20
        )
        let completed = expectation(description: "pending capture stops")
        DispatchQueue.global().async {
            do {
                _ = try provider.capture(eventTimestamp: self.time(0.5))
                XCTFail("capture should stop before the post-event range is available")
            } catch EvidenceVideoSnippetCaptureError.captureStopped {
                completed.fulfill()
            } catch {
                XCTFail("unexpected capture error: \(error)")
            }
        }

        Thread.sleep(forTimeInterval: 0.05)
        provider.stop()
        wait(for: [completed], timeout: 2.0)
        XCTAssertEqual(provider.status.state, .stopped)
        XCTAssertEqual(provider.status.bufferedFrameCount, 0)
    }

    func testReplaySourceProducesBoundedH264Snippet() throws {
        let provider = AVAssetVideoSnippetProvider(sourceURL: fixtureURL())
        let snippet = try provider.capture(
            eventTimestamp: CMTime(seconds: 1.0, preferredTimescale: 1_000)
        )

        XCTAssertEqual(snippet.manifest.partName, "snippet_00")
        XCTAssertLessThanOrEqual(snippet.manifest.startOffsetMs!, -800)
        XCTAssertGreaterThanOrEqual(snippet.manifest.endOffsetMs!, 700)
        XCTAssertEqual(snippet.manifest.durationMs, snippet.manifest.endOffsetMs! - snippet.manifest.startOffsetMs!)
        XCTAssertEqual(snippet.manifest.container, "mp4")
        XCTAssertEqual(snippet.manifest.videoCodec, "h264")
        XCTAssertEqual(snippet.manifest.width, 640)
        XCTAssertEqual(snippet.manifest.height, 360)
        XCTAssertEqual(snippet.manifest.nominalFrameRate, 15.0)
        XCTAssertEqual(snippet.manifest.byteLength, snippet.mp4Data.count)
        XCTAssertEqual(
            snippet.manifest.sha256,
            SHA256.hash(data: snippet.mp4Data).map { String(format: "%02x", $0) }.joined()
        )

        let asset = AVURLAsset(url: temporaryVideoURL(for: snippet.mp4Data))
        let tracks = asset.tracks(withMediaType: .video)
        XCTAssertEqual(tracks.count, 1)
        XCTAssertEqual(tracks.first?.naturalSize.width, 640.0)
        XCTAssertEqual(tracks.first?.naturalSize.height, 360.0)
    }

    func testCompleteSnippetSurvivesStoreRecoveryAndMultipartPreparation() throws {
        let provider = AVAssetVideoSnippetProvider(sourceURL: fixtureURL())
        let snippet = try provider.capture(
            eventTimestamp: CMTime(seconds: 1.0, preferredTimescale: 1_000)
        )
        let configuration = EvidenceCaptureConfiguration(
            targetOffsetsMs: [-800, 700],
            maximumLookupDistanceMs: 10
        )
        let clock = EvidenceSessionClock(startedAtUTC: Date(timeIntervalSince1970: 1_756_000_000))
        clock.observe(CMTime.zero)
        let ring = EvidenceFrameRing(configuration: configuration)
        ring.append(
            EncodedEvidenceFrame(
                timestamp: CMTime(seconds: 0.2, preferredTimescale: 1_000),
                jpegData: Data([1]),
                width: 640,
                height: 360
            )
        )
        ring.append(
            EncodedEvidenceFrame(
                timestamp: CMTime(seconds: 1.7, preferredTimescale: 1_000),
                jpegData: Data([2]),
                width: 640,
                height: 360
            )
        )
        let assembler = EvidencePackageAssembler(
            configuration: configuration,
            sessionClock: clock,
            sessionID: UUID(),
            model: EvidencePackageModelMetadata(
                name: "CardEventNet",
                version: "test",
                weightsSHA256: String(repeating: "a", count: 64),
                preprocessing: "full_frame_letterbox_v1"
            ),
            decoderConfiguration: CausalEventDecoder.Configuration(
                threshold: 0.5,
                peakConfirmation: CMTime(seconds: 0.125, preferredTimescale: 1_000),
                minimumEventGap: CMTime(seconds: 0.625, preferredTimescale: 1_000)
            ),
            client: EvidencePackageClientMetadata(
                appVersion: "test",
                build: "1",
                deviceModelIdentifier: "test-device",
                osVersion: "test-os"
            )
        )
        let package = try assembler.assemble(
            event: DetectionEvent(
                id: UUID(),
                timestamp: CMTime(seconds: 1.0, preferredTimescale: 1_000),
                emittedAt: CMTime(seconds: 1.125, preferredTimescale: 1_000),
                peakProbability: 0.9
            ),
            eventSequence: 1,
            ring: ring,
            camera: EvidencePackageCameraMetadata(
                position: "back",
                orientation: "up",
                width: 640,
                height: 360
            ),
            videoSnippet: snippet
        )

        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = EvidencePackageStore(root: root)
        let queuedURL = try store.persist(package)
        let stagedURL = store.directoryURL(for: .staging)
            .appendingPathComponent("interrupted-package", isDirectory: true)
        try FileManager.default.moveItem(at: queuedURL, to: stagedURL)

        let diagnostics = try store.recover()
        XCTAssertEqual(diagnostics.recoveredPackageIDs, [package.manifest.packageID])
        let recovered = try store.loadPackage(
            at: store.packageURL(for: package.manifest.packageID)
        )
        XCTAssertEqual(recovered.videoSnippet?.mp4Data, snippet.mp4Data)
        XCTAssertEqual(recovered.manifest.videoSnippet, snippet.manifest)

        let prepared = try EvidenceMultipartRequestBuilder(
            boundary: "SnippetBoundary",
            bodyDirectory: temporaryDirectory()
        ).prepare(
            packageAt: store.packageURL(for: package.manifest.packageID),
            baseURL: URL(string: "http://backend.local:8000")!
        )
        defer {
            prepared.removeBodyFile()
            try? FileManager.default.removeItem(at: prepared.bodyFileURL.deletingLastPathComponent())
        }
        let body = try Data(contentsOf: prepared.bodyFileURL)
        XCTAssertNotNil(body.range(of: Data("name=\"snippet_00\"".utf8)))
        XCTAssertNotNil(body.range(of: snippet.mp4Data))
    }

    func testFailedReplaySnippetProducesExplicitFrameOnlyPackage() throws {
        let configuration = EvidenceCaptureConfiguration(targetOffsetsMs: [0], maximumLookupDistanceMs: 10)
        let clock = EvidenceSessionClock()
        clock.observe(.zero)
        let ring = EvidenceFrameRing(configuration: configuration)
        ring.append(
            EncodedEvidenceFrame(
                timestamp: .zero,
                jpegData: Data([1]),
                width: 640,
                height: 360
            )
        )
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let coordinator = EvidencePackageCoordinator(
            configuration: configuration,
            sessionClock: clock,
            ring: ring,
            store: EvidencePackageStore(root: root),
            model: EvidencePackageModelMetadata(
                name: "CardEventNet",
                version: "test",
                weightsSHA256: String(repeating: "a", count: 64),
                preprocessing: "full_frame_letterbox_v1"
            ),
            decoderConfiguration: CausalEventDecoder.Configuration(
                threshold: 0.5,
                peakConfirmation: CMTime(seconds: 0.125, preferredTimescale: 1_000),
                minimumEventGap: CMTime(seconds: 0.625, preferredTimescale: 1_000)
            ),
            client: EvidencePackageClientMetadata(
                appVersion: "test",
                build: "1",
                deviceModelIdentifier: "test-device",
                osVersion: "test-os"
            ),
            camera: EvidencePackageCameraMetadata(
                position: "back",
                orientation: "up",
                width: 640,
                height: 360
            ),
            videoSnippetProvider: AVAssetVideoSnippetProvider(
                sourceURL: URL(fileURLWithPath: "/definitely-missing-replay-source.mp4")
            )
        )

        coordinator.record(
            DetectionEvent(
                id: UUID(),
                timestamp: .zero,
                emittedAt: CMTime(seconds: 0.125, preferredTimescale: 1_000),
                peakProbability: 0.9
            )
        )
        coordinator.finish()
        coordinator.drain()

        let packageURL = try XCTUnwrap(try EvidencePackageStore(root: root).packageURLs(in: .queued).first)
        let package = try EvidencePackageStore(root: root).loadPackage(at: packageURL)
        XCTAssertEqual(package.manifest.videoSnippet?.captureComplete, false)
        XCTAssertEqual(package.manifest.videoSnippet?.failureReason, "capture_failed")
        XCTAssertNil(package.videoSnippet)
        XCTAssertEqual(package.frames.count, 1)
    }

    private func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("fixtures/evidence/v2/example-complete/snippet.mp4")
    }

    private func temporaryVideoURL(for data: Data) -> URL {
        let url = temporaryDirectory().appendingPathComponent("snippet.mp4")
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try? data.write(to: url)
        return url
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }

    private func makePixelBuffer(width: Int, height: Int) throws -> CVPixelBuffer {
        var pixelBuffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            nil,
            &pixelBuffer
        )
        guard status == kCVReturnSuccess, let pixelBuffer else {
            throw PixelBufferError.creation(status)
        }
        return pixelBuffer
    }

    private enum PixelBufferError: Error {
        case creation(CVReturn)
    }
}
