import CryptoKit
import Foundation
import CardEventProbeCore

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

#if canImport(Glibc)
import Glibc
#else
import Darwin
#endif

@main
struct LocalPipelineClient {
    static func main() async {
        do {
            let options = try Options(arguments: Array(CommandLine.arguments.dropFirst()))
            try await run(options)
        } catch {
            FileHandle.standardError.write(Data("error: \(error.localizedDescription)\n".utf8))
            exit(1)
        }
    }

    private static func run(_ options: Options) async throws {
        switch options.action {
        case .create:
            try createPackages(options)
        case .upload:
            try await uploadPackages(options, retryFailed: false)
        case .retry:
            try await uploadPackages(options, retryFailed: true)
        case .result:
            try await readResult(options)
        }
    }

    private static func createPackages(_ options: Options) throws {
        let root = try options.requiredRoot
        let fixturesRoot = try options.requiredFixturesRoot
        let store = EvidencePackageStore(root: root)
        var packageIDs: [String: String] = [:]

        for variant in options.variants {
            let package = try makePackage(variant: variant, fixturesRoot: fixturesRoot)
            _ = try store.persist(package)
            packageIDs[variant.rawValue] = package.manifest.packageID.uuidString.lowercased()
        }

        try printJSON([
            "action": "create",
            "packages": packageIDs,
            "diagnostics": diagnosticsObject(store.diagnostics),
        ])
    }

    private static func uploadPackages(_ options: Options, retryFailed: Bool) async throws {
        let root = try options.requiredRoot
        let server = try options.requiredServer
        let store = EvidencePackageStore(root: root)
        let client = try EvidenceUploadClient(session: makeSession())
        let queue = EvidenceUploadQueue(store: store, client: client)
        let configuration = try BackendConfiguration(baseURL: server)
        let attempts = retryFailed
            ? await queue.retryFailed(using: configuration)
            : await queue.uploadQueued(using: configuration)

        try printJSON([
            "action": retryFailed ? "retry" : "upload",
            "attempts": attempts.map(attemptObject),
            "diagnostics": diagnosticsObject(store.diagnostics),
        ])
    }

    private static func readResult(_ options: Options) async throws {
        let server = try options.requiredServer
        guard let packageID = options.packageID else {
            throw OptionsError.missingValue("--package-id")
        }
        let configuration = try BackendConfiguration(baseURL: server)
        let client = EvidenceResultClient()
        let results = try await client.results(
            for: packageID,
            using: configuration
        )

        var output: [String: Any] = [
            "action": "result",
            "package_id": packageID.uuidString.lowercased(),
            "results": results.map { result in
                [
                    "result_id": result.resultID.uuidString.lowercased(),
                    "package_id": result.packageID.uuidString.lowercased(),
                    "status": result.status,
                    "candidate_count": result.candidates.count,
                ]
            },
        ]
        if let firstResult = results.first {
            let directResult = try await client.result(
                for: firstResult.resultID,
                using: configuration
            )
            output["direct_result_status"] = directResult.status
        }
        try printJSON(output)
    }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 2
        configuration.timeoutIntervalForResource = 5
        return URLSession(configuration: configuration)
    }

    private static func makePackage(
        variant: PackageVariant,
        fixturesRoot: URL
    ) throws -> EvidencePackage {
        let fixtureName: String = variant == .metadata ? "example-incomplete" :
            variant.baseFixture
        let manifestURL = fixturesRoot
            .appendingPathComponent(fixtureName, isDirectory: true)
            .appendingPathComponent("manifest.json")
        let manifestData = try Data(contentsOf: manifestURL)
        let decoder = JSONDecoder()
        let baseManifest = try decoder.decode(EvidencePackageManifest.self, from: manifestData)
        let frameData = try baseManifest.frames.map { frame in
            try readFrame(
                frame,
                fixtureDirectory: manifestURL.deletingLastPathComponent()
            )
        }

        let packageID = variant.packageID
        let eventSequence = variant.eventSequence
        let packagedFrames: [PackagedEvidenceFrame]
        if variant == .metadata {
            packagedFrames = []
        } else {
            packagedFrames = zip(baseManifest.frames, frameData).map { frame, data in
                let updatedManifest = EvidenceFrameManifest(
                    partName: frame.partName,
                    targetOffsetMs: frame.targetOffsetMs,
                    actualOffsetMs: frame.actualOffsetMs,
                    sessionElapsedMs: frame.sessionElapsedMs,
                    capturedAtUTC: frame.capturedAtUTC,
                    width: frame.width,
                    height: frame.height,
                    byteLength: data.count,
                    contentType: frame.contentType,
                    sha256: sha256Hex(data)
                )
                return PackagedEvidenceFrame(manifest: updatedManifest, jpegData: data)
            }
        }
        let frameManifests = packagedFrames.map(\.manifest)
        let missingTargets = variant == .metadata
            ? baseManifest.evidenceCapture.targetOffsetsMs
            : baseManifest.missingFrameTargetsMs
        let manifest = EvidencePackageManifest(
            packageID: packageID,
            session: EvidenceSessionMetadata(
                sessionID: baseManifest.session.sessionID,
                eventSequence: eventSequence
            ),
            event: EvidenceEventMetadata(
                eventTimeMs: baseManifest.event.eventTimeMs,
                emittedAtMs: baseManifest.event.emittedAtMs,
                evidenceComplete: missingTargets.isEmpty
            ),
            model: baseManifest.model,
            eventDecoder: baseManifest.eventDecoder,
            evidenceCapture: baseManifest.evidenceCapture,
            camera: baseManifest.camera,
            frames: frameManifests,
            missingFrameTargetsMs: missingTargets,
            scoreTrace: baseManifest.scoreTrace,
            client: EvidencePackageClientMetadata(
                appVersion: baseManifest.client.appVersion,
                build: variant.clientBuild ?? baseManifest.client.build,
                deviceModelIdentifier: baseManifest.client.deviceModelIdentifier,
                osVersion: baseManifest.client.osVersion
            ),
            schemaVersion: baseManifest.schemaVersion
        )

        return try EvidencePackage(manifest: manifest, frames: packagedFrames)
    }

    private static func readFrame(
        _ frame: EvidenceFrameManifest,
        fixtureDirectory: URL
    ) throws -> Data {
        let frameURL = fixtureDirectory
            .appendingPathComponent("frames", isDirectory: true)
            .appendingPathComponent("\(frame.partName).jpg")
        if FileManager.default.fileExists(atPath: frameURL.path) {
            return try Data(contentsOf: frameURL)
        }
        return Data("DokoDetector local fixture frame: \(frame.partName)".utf8)
    }

    private static func attemptObject(_ attempt: EvidenceUploadAttempt) -> [String: Any] {
        var object: [String: Any] = [
            "package_id": attempt.packageID.uuidString.lowercased(),
            "disposition": attempt.disposition.rawValue,
        ]
        if let response = attempt.response {
            object["created"] = response.created
            object["state"] = response.state
        }
        if let failure = attempt.failure {
            object["failure_kind"] = failure.kind.rawValue
            if let statusCode = failure.statusCode {
                object["status_code"] = statusCode
            }
        }
        return object
    }

    private static func diagnosticsObject(
        _ diagnostics: EvidencePackageQueueDiagnostics
    ) -> [String: Any] {
        [
            "staging": diagnostics.stagingCount,
            "queued": diagnostics.queuedCount,
            "acknowledged": diagnostics.acknowledgedCount,
            "failed": diagnostics.failedCount,
            "corrupt": diagnostics.corruptCount,
            "retryable_failures": diagnostics.retryableFailureCount,
            "permanent_failures": diagnostics.permanentFailureCount,
        ]
    }

    private static func printJSON(_ object: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
}

private struct Options {
    enum Action: String {
        case create
        case upload
        case retry
        case result
    }

    let action: Action
    let root: URL?
    let fixturesRoot: URL?
    let server: URL?
    let variants: [PackageVariant]
    let packageID: UUID?

    init(arguments: [String]) throws {
        guard let actionValue = arguments.first, let action = Action(rawValue: actionValue) else {
            throw OptionsError.usage
        }

        var root: URL?
        var fixturesRoot: URL?
        var server: URL?
        var variants: [PackageVariant] = []
        var packageID: UUID?
        var index = 1
        while index < arguments.count {
            let argument = arguments[index]
            guard index + 1 < arguments.count else {
                throw OptionsError.missingValue(argument)
            }
            switch argument {
            case "--root":
                root = URL(fileURLWithPath: arguments[index + 1]).standardizedFileURL
            case "--fixtures-root":
                fixturesRoot = URL(fileURLWithPath: arguments[index + 1]).standardizedFileURL
            case "--server":
                guard let url = URL(string: arguments[index + 1]) else {
                    throw OptionsError.invalidValue(argument)
                }
                server = url
            case "--variant":
                let values = arguments[index + 1].split(separator: ",").map(String.init)
                variants = try values.map { value in
                    guard let variant = PackageVariant(rawValue: value) else {
                        throw OptionsError.invalidValue(value)
                    }
                    return variant
                }
            case "--package-id":
                guard let value = UUID(uuidString: arguments[index + 1]) else {
                    throw OptionsError.invalidValue(argument)
                }
                packageID = value
            default:
                throw OptionsError.invalidValue(argument)
            }
            index += 2
        }

        if action == .create, variants.isEmpty {
            throw OptionsError.missingValue("--variant")
        }
        self.action = action
        self.root = root
        self.fixturesRoot = fixturesRoot
        self.server = server
        self.variants = variants
        self.packageID = packageID
    }

    var requiredRoot: URL {
        get throws {
            guard let root else { throw OptionsError.missingValue("--root") }
            return root
        }
    }

    var requiredFixturesRoot: URL {
        get throws {
            guard let fixturesRoot else { throw OptionsError.missingValue("--fixtures-root") }
            return fixturesRoot
        }
    }

    var requiredServer: URL {
        get throws {
            guard let server else { throw OptionsError.missingValue("--server") }
            return server
        }
    }
}

private enum OptionsError: LocalizedError {
    case usage
    case missingValue(String)
    case invalidValue(String)

    var errorDescription: String? {
        switch self {
        case .usage:
            return "Usage: create, upload, retry, or result with the required options."
        case let .missingValue(option):
            return "Missing value for \(option)."
        case let .invalidValue(value):
            return "Invalid command-line value: \(value)."
        }
    }
}

private enum PackageVariant: String {
    case complete
    case incomplete
    case metadata
    case duplicate
    case conflict
    case retry
    case restart

    var baseFixture: String {
        switch self {
        case .complete, .conflict, .retry, .restart:
            return "example-complete"
        case .incomplete, .metadata, .duplicate:
            return "example-incomplete"
        }
    }

    var packageID: UUID {
        let value: String
        switch self {
        case .complete:
            value = "550e8400-e29b-41d4-a716-446655440000"
        case .incomplete, .duplicate:
            value = "550e8400-e29b-41d4-a716-446655440001"
        case .metadata:
            value = "550e8400-e29b-41d4-a716-446655440002"
        case .retry:
            value = "550e8400-e29b-41d4-a716-446655440003"
        case .restart:
            value = "550e8400-e29b-41d4-a716-446655440004"
        case .conflict:
            value = "550e8400-e29b-41d4-a716-446655440000"
        }
        return UUID(uuidString: value)!
    }

    var eventSequence: Int {
        switch self {
        case .complete, .conflict:
            return 1
        case .incomplete, .duplicate:
            return 2
        case .metadata:
            return 3
        case .retry:
            return 4
        case .restart:
            return 5
        }
    }

    var clientBuild: String? {
        self == .conflict ? "m4-conflict" : nil
    }
}

private func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}
