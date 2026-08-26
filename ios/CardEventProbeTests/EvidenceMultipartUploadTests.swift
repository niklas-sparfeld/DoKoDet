import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import CryptoKit
import XCTest
@testable import CardEventProbeCore

final class EvidenceMultipartUploadTests: XCTestCase {
    func testValidatesBoundaryAndWritesCompletePartsInManifestOrder() throws {
        XCTAssertTrue(EvidenceMultipartRequestBuilder.isValidBoundary("CardEventProbeEvidenceV1"))
        XCTAssertFalse(EvidenceMultipartRequestBuilder.isValidBoundary("boundary with spaces"))
        XCTAssertThrowsError(try EvidenceMultipartRequestBuilder(boundary: "boundary with spaces"))

        let package = try makePackage(
            targetOffsets: [-100, 100],
            frames: [
                (partName: "frame_00", targetOffset: -100, bytes: Data("jpeg-a".utf8)),
                (partName: "frame_01", targetOffset: 100, bytes: Data("jpeg-b".utf8)),
            ]
        )
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let builder = try EvidenceMultipartRequestBuilder(
            boundary: "TestBoundaryV1",
            bodyDirectory: root
        )

        let prepared = try builder.prepare(
            package: package,
            baseURL: URL(string: "http://backend.local:8000")!
        )
        defer { prepared.removeBodyFile() }

        XCTAssertEqual(prepared.request.httpMethod, "PUT")
        XCTAssertEqual(
            prepared.request.url?.absoluteString,
            "http://backend.local:8000/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440010"
        )
        XCTAssertEqual(
            prepared.request.value(forHTTPHeaderField: "Content-Type"),
            "multipart/form-data; boundary=TestBoundaryV1"
        )
        let body = try Data(contentsOf: prepared.bodyFileURL)
        XCTAssertEqual(prepared.contentLength, Int64(body.count))
        XCTAssertEqual(
            prepared.request.value(forHTTPHeaderField: "Content-Length"),
            String(body.count)
        )
        let closingBoundary = Data("--TestBoundaryV1--\r\n".utf8)
        XCTAssertTrue(body.suffix(closingBoundary.count).elementsEqual(closingBoundary))

        let parts = try parseMultipart(body, boundary: "TestBoundaryV1")
        XCTAssertEqual(parts.map(\.name), ["manifest", "frame_00", "frame_01"])
        XCTAssertEqual(parts.map(\.filename), ["manifest.json", "frame_00.jpg", "frame_01.jpg"])
        XCTAssertEqual(parts.map(\.contentType), ["application/json", "image/jpeg", "image/jpeg"])
        XCTAssertEqual(parts[1].body, Data("jpeg-a".utf8))
        XCTAssertEqual(parts[2].body, Data("jpeg-b".utf8))

        let manifest = try JSONSerialization.jsonObject(with: parts[0].body) as? [String: Any]
        XCTAssertEqual(manifest?["package_id"] as? String, package.manifest.packageID.uuidString.lowercased())
    }

    func testMetadataOnlyPackageContainsOnlyManifestPart() throws {
        let package = try makePackage(targetOffsets: [-100, 100], frames: [])
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let builder = try EvidenceMultipartRequestBuilder(
            boundary: "ZeroFrameBoundary",
            bodyDirectory: root
        )

        let prepared = try builder.prepare(
            package: package,
            baseURL: URL(string: "http://backend.local:8000")!
        )
        defer { prepared.removeBodyFile() }
        let body = try Data(contentsOf: prepared.bodyFileURL)
        let parts = try parseMultipart(body, boundary: "ZeroFrameBoundary")

        XCTAssertEqual(parts.count, 1)
        XCTAssertEqual(parts[0].name, "manifest")
        XCTAssertEqual(parts[0].filename, "manifest.json")
        XCTAssertEqual(parts[0].contentType, "application/json")
    }

    func testIdenticalPreparationDoesNotMutatePackage() throws {
        let package = try makePackage(
            targetOffsets: [0],
            frames: [(partName: "frame_00", targetOffset: 0, bytes: Data([0xFF, 0xD8, 0xFF, 0xD9]))]
        )
        let originalManifest = try package.manifest.encoded()
        let originalFrames = package.frames.map(\.jpegData)
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let builder = try EvidenceMultipartRequestBuilder(
            boundary: "StableBoundary",
            bodyDirectory: root
        )

        let first = try builder.prepare(package: package, baseURL: URL(string: "http://backend.local:8000")!)
        let second = try builder.prepare(package: package, baseURL: URL(string: "http://backend.local:8000")!)
        defer {
            first.removeBodyFile()
            second.removeBodyFile()
        }

        XCTAssertEqual(try Data(contentsOf: first.bodyFileURL), try Data(contentsOf: second.bodyFileURL))
        XCTAssertEqual(try package.manifest.encoded(), originalManifest)
        XCTAssertEqual(package.frames.map(\.jpegData), originalFrames)
    }

    func testPersistedPackageUsesStoredManifestBytes() throws {
        let package = try makePackage(
            targetOffsets: [0],
            frames: [(partName: "frame_00", targetOffset: 0, bytes: Data("jpeg".utf8))]
        )
        let packageRoot = temporaryDirectory()
        let bodyRoot = temporaryDirectory()
        defer {
            try? FileManager.default.removeItem(at: packageRoot)
            try? FileManager.default.removeItem(at: bodyRoot)
        }
        let packageURL = try EvidencePackageStore(root: packageRoot).persist(package)
        let storedManifest = try Data(contentsOf: packageURL.appendingPathComponent("manifest.json"))
        let builder = try EvidenceMultipartRequestBuilder(
            boundary: "StoredPackageBoundary",
            bodyDirectory: bodyRoot
        )
        let prepared = try builder.prepare(
            packageAt: packageURL,
            baseURL: URL(string: "http://backend.local:8000")!
        )
        defer { prepared.removeBodyFile() }

        let parts = try parseMultipart(
            try Data(contentsOf: prepared.bodyFileURL),
            boundary: "StoredPackageBoundary"
        )
        XCTAssertEqual(parts[0].body, storedManifest)
        XCTAssertEqual(parts[1].body, Data("jpeg".utf8))
    }

    func testURLSessionClientSendsFileBackedRequestToContractPath() async throws {
        let package = try makePackage(
            targetOffsets: [0],
            frames: [(partName: "frame_00", targetOffset: 0, bytes: Data("jpeg".utf8))]
        )
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        RecordingURLProtocol.lastBody = nil
        RecordingURLProtocol.handler = { request, body in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(
                request.url?.path,
                "/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440010"
            )
            XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "application/json")
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "Content-Type"),
                "multipart/form-data; boundary=ProtocolBoundary"
            )
            return (
                201,
                Data(
                    ("{"
                        + "\"package_id\":\"550e8400-e29b-41d4-a716-446655440010\",\"state\":\"stored\",\"created\":true,\"received_at\":\"2026-08-26T18:11:29.000Z\""
                        + "}").utf8
                )
            )
        }
        defer { RecordingURLProtocol.handler = nil }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RecordingURLProtocol.self]
        let session = URLSession(configuration: configuration)
        let client = try EvidenceUploadClient(
            session: session,
            boundary: "ProtocolBoundary",
            bodyDirectory: root
        )

        let response = try await client.upload(
            package: package,
            to: URL(string: "http://backend.local:8000")!
        )
        XCTAssertEqual(response.packageID, package.manifest.packageID)
        XCTAssertEqual(response.state, "stored")
        XCTAssertTrue(response.created)
        XCTAssertNotNil(RecordingURLProtocol.lastBody)
        let parts = try parseMultipart(
            try XCTUnwrap(RecordingURLProtocol.lastBody),
            boundary: "ProtocolBoundary"
        )
        XCTAssertEqual(parts.map(\.name), ["manifest", "frame_00"])
        XCTAssertEqual(parts[1].body, Data("jpeg".utf8))
    }

    private struct MultipartPart {
        let name: String
        let filename: String
        let contentType: String
        let body: Data
    }

    private func parseMultipart(_ data: Data, boundary: String) throws -> [MultipartPart] {
        let marker = Data("--\(boundary)".utf8)
        let headerSeparator = Data("\r\n\r\n".utf8)
        let bodySeparator = Data("\r\n--\(boundary)".utf8)
        var offset = 0
        var parts: [MultipartPart] = []

        while true {
            guard data.range(of: marker, in: offset..<data.count)?.lowerBound == offset else {
                throw MultipartParseError.invalidEnvelope
            }
            offset += marker.count
            if data[offset..<data.count].starts(with: Data("--".utf8)) {
                guard data[(offset + 2)..<data.count] == Data("\r\n".utf8) else {
                    throw MultipartParseError.invalidEnvelope
                }
                return parts
            }
            guard data[offset..<data.count].starts(with: Data("\r\n".utf8)) else {
                throw MultipartParseError.invalidEnvelope
            }
            offset += 2
            guard let separator = data.range(of: headerSeparator, in: offset..<data.count),
                  let headerText = String(data: data[offset..<separator.lowerBound], encoding: .ascii) else {
                throw MultipartParseError.invalidEnvelope
            }
            let headers = headerText.split(separator: "\r\n").reduce(into: [String: String]()) { result, line in
                let fields = line.split(separator: ":", maxSplits: 1).map(String.init)
                if fields.count == 2 {
                    result[fields[0].lowercased()] = fields[1].trimmingCharacters(in: .whitespaces)
                }
            }
            offset = separator.upperBound
            guard let next = data.range(of: bodySeparator, in: offset..<data.count) else {
                throw MultipartParseError.invalidEnvelope
            }
            let body = Data(data[offset..<next.lowerBound])
            guard let disposition = headers["content-disposition"],
                  let name = quotedValue("name", in: disposition),
                  let filename = quotedValue("filename", in: disposition),
                  let contentType = headers["content-type"] else {
                throw MultipartParseError.invalidEnvelope
            }
            parts.append(MultipartPart(name: name, filename: filename, contentType: contentType, body: body))
            offset = next.lowerBound + 2
        }
    }

    private func quotedValue(_ key: String, in value: String) -> String? {
        let prefix = "\(key)=\""
        guard let start = value.range(of: prefix)?.upperBound,
              let end = value[start...].firstIndex(of: "\"") else {
            return nil
        }
        return String(value[start..<end])
    }

    private func makePackage(
        targetOffsets: [Int],
        frames: [(partName: String, targetOffset: Int, bytes: Data)]
    ) throws -> EvidencePackage {
        let packageID = UUID(uuid: (0x55, 0x0e, 0x84, 0x00, 0xe2, 0x9b, 0x41, 0xd4, 0xa7, 0x16, 0x44, 0x66, 0x55, 0x44, 0x00, 0x10))
        let capturedAt = Date(timeIntervalSince1970: 1_756_000_000)
        let manifests = frames.map { frame in
            EvidenceFrameManifest(
                partName: frame.partName,
                targetOffsetMs: frame.targetOffset,
                actualOffsetMs: frame.targetOffset,
                sessionElapsedMs: max(0, 10_000 + frame.targetOffset),
                capturedAtUTC: capturedAt.addingTimeInterval(Double(frame.targetOffset) / 1_000.0),
                width: 1920,
                height: 1080,
                byteLength: frame.bytes.count,
                contentType: "image/jpeg",
                sha256: SHA256.hash(data: frame.bytes).map { String(format: "%02x", $0) }.joined()
            )
        }
        let manifest = EvidencePackageManifest(
            packageID: packageID,
            session: EvidenceSessionMetadata(
                sessionID: UUID(uuid: (0x6b, 0xa7, 0xb8, 0x10, 0x9d, 0xad, 0x41, 0xd1, 0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8)),
                eventSequence: 1
            ),
            event: EvidenceEventMetadata(eventTimeMs: 10_000, emittedAtMs: 10_125, evidenceComplete: frames.count == targetOffsets.count),
            model: EvidencePackageModelMetadata(
                name: "CardEventNet",
                version: "test",
                weightsSHA256: String(repeating: "a", count: 64),
                preprocessing: "full_frame_letterbox_v1"
            ),
            eventDecoder: EvidenceEventDecoderMetadata(
                algorithm: "causal_peak_v1",
                threshold: 0.34,
                peakConfirmationMs: 125,
                minimumEventGapMs: 625,
                targetInferenceHz: 8.0
            ),
            evidenceCapture: EvidenceCaptureMetadata(
                configuration: EvidenceCaptureConfiguration(
                    targetHz: 8.0,
                    jpegQuality: 0.85,
                    historySeconds: 3.0,
                    targetOffsetsMs: targetOffsets,
                    maximumLookupDistanceMs: 175,
                    finalizationDelayMs: 900
                )
            ),
            camera: EvidencePackageCameraMetadata(position: "back", orientation: "landscape_right", width: 1920, height: 1080),
            frames: manifests,
            missingFrameTargetsMs: targetOffsets.filter { target in !frames.contains { $0.targetOffset == target } },
            scoreTrace: [],
            client: EvidencePackageClientMetadata(appVersion: "test", build: "1", deviceModelIdentifier: "test-device", osVersion: "18.0")
        )
        return try EvidencePackage(
            manifest: manifest,
            frames: frames.map { frame in
                PackagedEvidenceFrame(
                    manifest: manifests.first { $0.partName == frame.partName }!,
                    jpegData: frame.bytes
                )
            }
        )
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}

private enum MultipartParseError: Error {
    case invalidEnvelope
}

private final class RecordingURLProtocol: URLProtocol {
    typealias Handler = (URLRequest, Data) -> (statusCode: Int, body: Data)

    nonisolated(unsafe) static var handler: Handler?
    nonisolated(unsafe) static var lastBody: Data?

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let body = requestBody()
        Self.lastBody = body
        guard let result = Self.handler?(request, body),
              let response = HTTPURLResponse(
                  url: request.url!,
                  statusCode: result.statusCode,
                  httpVersion: nil,
                  headerFields: ["Content-Type": "application/json"]
              ) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: result.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private func requestBody() -> Data {
        if let body = request.httpBody {
            return body
        }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 16 * 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            body.append(buffer, count: count)
        }
        return body
    }
}
