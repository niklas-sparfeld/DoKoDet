import CoreMedia
import CoreVideo
import ImageIO
import XCTest
@testable import CardEventProbeCore

final class EvidenceFrameRingTests: XCTestCase {
    func testRingEvictsFramesOutsideHistoryAndCountBounds() {
        let ring = EvidenceFrameRing(
            historyDuration: time(3.0),
            maximumFrameCount: 3
        )
        for seconds in 0...4 {
            ring.append(frame(at: Double(seconds), value: UInt8(seconds)))
        }

        XCTAssertEqual(ring.count, 3)
        XCTAssertTrue(
            ring.select(
                eventTimestamp: time(0.0),
                targetOffsetsMs: [0],
                maximumLookupDistanceMs: 0
            )[0].isMissing
        )
        let newest = ring.select(
            eventTimestamp: time(4.0),
            targetOffsetsMs: [0],
            maximumLookupDistanceMs: 0
        )[0]
        XCTAssertEqual(newest.actualOffsetMs, 0)
        XCTAssertEqual(newest.frame?.jpegData, Data([4]))
    }

    func testSelectionUsesEarlierFrameForAnExactTieAndRecordsOffsets() {
        let ring = EvidenceFrameRing(historyDuration: time(3.0), maximumFrameCount: 10)
        ring.append(frame(at: 0.4, value: 4))
        ring.append(frame(at: 0.6, value: 6))

        let selections = ring.select(
            eventTimestamp: time(0.5),
            targetOffsetsMs: [0, 100, 500],
            maximumLookupDistanceMs: 100
        )

        XCTAssertEqual(selections[0].actualOffsetMs, -100)
        XCTAssertEqual(selections[0].frame?.jpegData, Data([4]))
        XCTAssertEqual(selections[1].actualOffsetMs, 100)
        XCTAssertEqual(selections[1].frame?.jpegData, Data([6]))
        XCTAssertTrue(selections[2].isMissing)
        XCTAssertNil(selections[2].actualOffsetMs)
    }

    func testJPEGEncoderWritesTheCompleteFrameDimensions() throws {
        let pixelBuffer = try makePixelBuffer(width: 4, height: 2)
        let frame = VideoFrame(
            pixelBuffer: pixelBuffer,
            timestamp: time(1.0),
            orientation: .up
        )

        let encoded = try JPEGEvidenceFrameEncoder(quality: 0.85).encode(frame)
        guard let source = CGImageSourceCreateWithData(encoded.jpegData as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            return XCTFail("The encoded evidence is not a readable JPEG.")
        }

        XCTAssertEqual(encoded.width, 4)
        XCTAssertEqual(encoded.height, 2)
        XCTAssertEqual(image.width, 4)
        XCTAssertEqual(image.height, 2)
    }

    func testSamplerRecordsAFrameDroppedWhileEncoderIsBusy() throws {
        let encoder = BlockingEvidenceFrameEncoder()
        let sampler = EvidenceFrameSampler(
            configuration: EvidenceCaptureConfiguration(
                targetHz: 8.0,
                targetOffsetsMs: [0],
                maximumLookupDistanceMs: 0,
                finalizationDelayMs: 0
            ),
            encoder: encoder
        )

        let pixelBuffer = try makePixelBuffer(width: 2, height: 2)
        sampler.consume(
            VideoFrame(
                pixelBuffer: pixelBuffer,
                timestamp: time(0.0),
                orientation: .up
            )
        )
        XCTAssertEqual(encoder.started.wait(timeout: .now() + 1.0), .success)

        sampler.consume(
            VideoFrame(
                pixelBuffer: pixelBuffer,
                timestamp: time(0.25),
                orientation: .up
            )
        )
        XCTAssertEqual(sampler.metrics.framesDroppedWhileBusy, 1)

        encoder.release.signal()
        XCTAssertEqual(encoder.finished.wait(timeout: .now() + 1.0), .success)
        let deadline = Date().addingTimeInterval(1.0)
        while sampler.metrics.framesEncoded < 1, Date() < deadline {
            Thread.sleep(forTimeInterval: 0.001)
        }
        XCTAssertEqual(sampler.metrics.framesEncoded, 1)
        XCTAssertEqual(sampler.ring.count, 1)
    }

    private func time(_ seconds: Double) -> CMTime {
        CMTime(seconds: seconds, preferredTimescale: 1_000)
    }

    private func frame(at seconds: Double, value: UInt8) -> EncodedEvidenceFrame {
        EncodedEvidenceFrame(
            timestamp: time(seconds),
            jpegData: Data([value]),
            width: 1,
            height: 1
        )
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

private final class BlockingEvidenceFrameEncoder: EvidenceFrameEncoding {
    let started = DispatchSemaphore(value: 0)
    let release = DispatchSemaphore(value: 0)
    let finished = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var callCount = 0

    func encode(_ frame: VideoFrame) throws -> EncodedEvidenceFrame {
        lock.lock()
        callCount += 1
        let isFirstCall = callCount == 1
        lock.unlock()

        if isFirstCall {
            started.signal()
            release.wait()
        }

        finished.signal()
        return EncodedEvidenceFrame(
            timestamp: frame.timestamp,
            jpegData: Data([1]),
            width: CVPixelBufferGetWidth(frame.pixelBuffer),
            height: CVPixelBufferGetHeight(frame.pixelBuffer)
        )
    }
}
