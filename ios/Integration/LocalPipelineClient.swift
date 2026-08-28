import AVFoundation
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation
import CardEventProbeCore
import ImageIO

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
        case .simulateRecording:
            try simulateRecording(options)
        case .upload:
            try await uploadPackages(options, retryFailed: false)
        case .retry:
            try await uploadPackages(options, retryFailed: true)
        case .uploadRecording:
            try await uploadRecordings(options, retryFailed: false)
        case .retryRecording:
            try await uploadRecordings(options, retryFailed: true)
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

    private static func simulateRecording(_ options: Options) throws {
        let inputURL = try options.requiredInputVideo
        let root = try options.requiredRoot
        let recordingID = options.recordingID ?? "recording-simulator-001"
        let sessionID = options.sessionID ?? "550e8400-e29b-41d4-a716-446655440010"
        let videoID = options.videoID ?? "video-simulator-001"
        guard UUID(uuidString: sessionID) != nil else {
            throw OptionsError.invalidValue("--session-id")
        }

        let trainingRoot = root.appendingPathComponent("training", isDirectory: true)
        let evidenceRoot = root.appendingPathComponent("evidence", isDirectory: true)
        let asset = AVURLAsset(url: inputURL)
        guard let track = asset.tracks(withMediaType: .video).first else {
            throw SavedVideoSimulationError.videoTrackMissing(inputURL)
        }

        let frameRate = track.nominalFrameRate > 0.0 ? Double(track.nominalFrameRate) : 30.0
        let model = TrainingRecordingModel(
            name: "CardEventNet",
            version: "saved-video-simulator-v1",
            weightsSHA256: String(repeating: "0", count: 64),
            preprocessing: "full_frame_letterbox_v1"
        )
        let decoderConfiguration = CausalEventDecoder.Configuration(
            threshold: 0.5,
            peakConfirmation: CMTime(seconds: 1.0 / frameRate, preferredTimescale: 600),
            minimumEventGap: CMTime(seconds: 0.6, preferredTimescale: 600)
        )
        let decoder = TrainingRecordingDecoder(
            algorithm: "causal_peak_v1",
            threshold: decoderConfiguration.threshold,
            peakConfirmationS: CMTimeGetSeconds(decoderConfiguration.peakConfirmation),
            minimumEventGapS: CMTimeGetSeconds(decoderConfiguration.minimumEventGap)
        )
        let client = TrainingRecordingClient(
            appVersion: "0.1.0",
            build: "saved-video-simulator",
            deviceModel: "macOS-simulator",
            osVersion: ProcessInfo.processInfo.operatingSystemVersionString
        )
        let startedAtUTC = Date(timeIntervalSince1970: 1_756_000_000)
        var collectionProfile = CollectionProfile.newDraft(
            profileID: "profile-saved-video-simulator-v1",
            sessionID: sessionID
        )
        collectionProfile.name = "Saved video simulator"
        collectionProfile.operatorName = "saved-video-simulator"
        collectionProfile.activity = .stagedActivity
        collectionProfile.tableSetup = "saved-video-simulator-table"
        collectionProfile.cardDeck = "doko-48-v1"
        collectionProfile.cameraView = "overhead"
        collectionProfile.cameraMotion = "fixed"
        collectionProfile.cameraFraming = "table_fills_frame"
        collectionProfile.lighting = ["room_light"]
        collectionProfile.background = "saved video fixture"
        collectionProfile.scenarioTags = ["normal_card_play"]
        collectionProfile.sourcePermission = "training_and_evaluation"
        let recordingConfiguration = TrainingRecordingConfiguration(
            outputRoot: trainingRoot.appendingPathComponent("queued", isDirectory: true),
            recordingID: recordingID,
            sessionID: sessionID,
            videoID: videoID,
            startedAtUTC: startedAtUTC,
            model: model,
            decoder: decoder,
            client: client,
            sourcePermission: "training_and_evaluation",
            collectionMetadata: try collectionProfile.recordingMetadata(),
            taskEnrollments: try collectionProfile.makeTaskEnrollments(
                recordingID: recordingID,
                createdAtUTC: utcString(from: startedAtUTC)
            ),
            frameRate: frameRate
        )
        let recordingCoordinator = TrainingRecordingCoordinator(configuration: recordingConfiguration)
        try recordingCoordinator.start()

        let captureSession = CaptureSession(
            sessionID: UUID(uuidString: sessionID)!,
            startedAtUTC: startedAtUTC
        )
        let evidenceConfiguration = EvidenceCaptureConfiguration(
            targetHz: frameRate,
            jpegQuality: 0.8,
            historySeconds: 3.0,
            targetOffsetsMs: [0],
            maximumLookupDistanceMs: Int((500.0 / frameRate).rounded()),
            finalizationDelayMs: 0
        )
        let evidenceStore = EvidencePackageStore(root: evidenceRoot)
        let evidenceSampler = EvidenceFrameSampler(
            configuration: evidenceConfiguration,
            sessionClock: captureSession.clock
        )
        let evidenceCoordinator = EvidencePackageCoordinator(
            configuration: evidenceConfiguration,
            captureSession: captureSession,
            ring: evidenceSampler.ring,
            store: evidenceStore,
            model: EvidencePackageModelMetadata(
                name: model.name,
                version: model.version,
                weightsSHA256: model.weightsSHA256,
                preprocessing: model.preprocessing
            ),
            decoderConfiguration: decoderConfiguration,
            client: EvidencePackageClientMetadata(
                appVersion: client.appVersion,
                build: client.build,
                deviceModelIdentifier: client.deviceModel,
                osVersion: client.osVersion
            ),
            camera: EvidencePackageCameraMetadata(
                position: "back",
                orientation: "up",
                width: 1,
                height: 1
            ),
            recordingID: recordingID,
            videoSnippetProvider: AVAssetVideoSnippetProvider(sourceURL: inputURL)
        )

        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(
            track: track,
            outputSettings: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            ]
        )
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else {
            throw SavedVideoSimulationError.cannotAddReaderOutput
        }
        reader.add(output)
        guard reader.startReading() else {
            throw reader.error ?? SavedVideoSimulationError.readerStartFailed
        }

        var frameCount = 0
        var predictionCount = 0
        var lastTimestamp = CMTime.zero
        let eventDecoder = CausalEventDecoder(configuration: decoderConfiguration)
        let eventCenterFrame = max(1, Int((asset.duration.seconds * frameRate / 2.0).rounded()))
        while let sampleBuffer = output.copyNextSampleBuffer() {
            guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
                continue
            }
            let timestamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            let frame = VideoFrame(
                pixelBuffer: pixelBuffer,
                timestamp: timestamp,
                orientation: .up
            )
            recordingCoordinator.consume(frame)
            evidenceSampler.consume(frame)
            evidenceCoordinator.observe(frame)
            evidenceSampler.drain()

            let probability = simulatedProbability(
                frameIndex: frameCount,
                eventCenterFrame: eventCenterFrame
            )
            let prediction = ModelPrediction(
                timestamp: timestamp,
                cardEventProbability: probability,
                rawOutputs: ["card_event": probability],
                inferenceDurationMs: 1.0
            )
            let event = eventDecoder.consume(prediction)
            recordingCoordinator.consume(prediction, event: event)
            evidenceCoordinator.consume(prediction, event: event)
            recordingCoordinator.drain()
            evidenceCoordinator.drain()
            frameCount += 1
            predictionCount += 1
            lastTimestamp = timestamp
        }

        guard reader.status == .completed else {
            throw reader.error ?? SavedVideoSimulationError.readerFailed
        }
        if let event = eventDecoder.flush() {
            recordingCoordinator.record(event)
            evidenceCoordinator.record(event)
        }
        recordingCoordinator.drain()
        evidenceCoordinator.finish()
        evidenceCoordinator.drain()
        guard frameCount > 0, predictionCount > 0 else {
            throw SavedVideoSimulationError.noFrames
        }
        guard let evidenceRecordingCorrelationID = evidenceCoordinator.legacyCaptureSessionID else {
            throw SavedVideoSimulationError.missingEvidenceRecordingCorrelation
        }

        let bundleURL = try waitForRecordingStop(recordingCoordinator)
        let manifestData = try Data(
            contentsOf: bundleURL.appendingPathComponent("manifest.json")
        )
        let manifest = try decodeRepositoryJSON(RepositoryBundle.self, data: manifestData)
        _ = try validateRepositoryBundleDirectory(at: bundleURL)
        guard let proposalDescriptor = manifest.files.proposalGeneratorRuns.first else {
            throw SavedVideoSimulationError.missingProposalGeneratorRun
        }
        let proposalData = try Data(
            contentsOf: bundleURL.appendingPathComponent(proposalDescriptor.relativePath)
        )
        let proposal = try decodeRepositoryJSON(
            RepositoryProposalGeneratorRun.self,
            data: proposalData
        )
        let evidenceDiagnostics = try evidenceStore.recover()

        try printJSON([
            "action": "simulate-recording",
            "recording_id": recordingID,
            "session_id": sessionID,
            "video_id": videoID,
            "recording_directory": bundleURL.path,
            "evidence_root": evidenceRoot.path,
            "evidence_package_count": evidenceDiagnostics.queuedCount,
            "evidence_recording_correlation_id": evidenceRecordingCorrelationID,
            "evidence_canonical_session_id": captureSession.sessionID.uuidString.lowercased(),
            "input_frame_count": frameCount,
            "prediction_sample_count": proposal.probabilities.count,
            "event_proposal_count": proposal.eventProposals.count,
            "input_duration_s": CMTimeGetSeconds(asset.duration),
            "recording_duration_s": CMTimeGetSeconds(lastTimestamp),
            "last_input_timestamp_s": CMTimeGetSeconds(lastTimestamp),
            "recording_video_sha256": manifest.sourceSHA256,
            "recording_predictions_sha256": proposalDescriptor.sha256,
            "recording_metrics": [
                "received_frame_count": recordingCoordinator.metrics.receivedFrameCount,
                "written_frame_count": recordingCoordinator.metrics.writtenFrameCount,
                "dropped_frame_count": recordingCoordinator.metrics.droppedFrameCount,
            ],
        ])
    }

    private static func uploadRecordings(
        _ options: Options,
        retryFailed: Bool
    ) async throws {
        let root = try options.requiredRoot
        let server = try options.requiredServer
        let store = TrainingRecordingStore(root: root)
        let client = try TrainingRecordingUploadClient(
            session: makeSession(),
            bodyDirectory: root
        )
        let queue = TrainingRecordingUploadQueue(store: store, client: client)
        let configuration = try BackendConfiguration(baseURL: server)
        let attempts = retryFailed
            ? await queue.retryFailed(using: configuration)
            : await queue.uploadQueued(using: configuration)

        try printJSON([
            "action": retryFailed ? "retry-recording" : "upload-recording",
            "attempts": attempts.map(recordingAttemptObject),
            "diagnostics": recordingDiagnosticsObject(store.diagnostics),
        ])
    }

    private static func waitForRecordingStop(
        _ coordinator: TrainingRecordingCoordinator
    ) throws -> URL {
        let semaphore = DispatchSemaphore(value: 0)
        var result: Result<URL, Error>?
        coordinator.stop { received in
            result = received
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 30) == .success else {
            throw SavedVideoSimulationError.finalizationTimedOut
        }
        return try result?.get() ?? {
            throw SavedVideoSimulationError.finalizationMissing
        }()
    }

    private static func simulatedProbability(frameIndex: Int, eventCenterFrame: Int) -> Double {
        // Keep the local replay deterministic and produce one causal peak at the source midpoint.
        abs(frameIndex - eventCenterFrame) <= 1 ? 0.9 : 0.1
    }

    private static func readResult(_ options: Options) async throws {
        let server = try options.requiredServer
        guard let packageID = options.packageID else {
            throw OptionsError.missingValue("--package-id")
        }
        let configuration = try BackendConfiguration(baseURL: server)
        let client = TableObservationClient()
        let observations = try await client.observations(
            for: packageID,
            using: configuration
        )

        var output: [String: Any] = [
            "action": "result",
            "package_id": packageID.uuidString.lowercased(),
            "observations": observations.map { observation in
                [
                    "observation_id": observation.observationID,
                    "package_id": observation.source.packageID,
                    "status": observation.status,
                    "candidate_count": observation.cards.flatMap(\.identityCandidates).count,
                ]
            },
        ]
        if let firstObservation = observations.first {
            let directObservation = try await client.observation(
                for: firstObservation.observationID,
                using: configuration
            )
            output["direct_observation_status"] = directObservation.status
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
        let packagedVideo: PackagedEvidenceVideo?
        if let videoManifest = baseManifest.videoSnippet, videoManifest.captureComplete {
            guard videoManifest.partName != nil else {
                throw OptionsError.invalidValue("video_snippet.part_name")
            }
            let videoURL = manifestURL.deletingLastPathComponent()
                .appendingPathComponent("snippet.mp4")
            packagedVideo = PackagedEvidenceVideo(
                manifest: videoManifest,
                mp4Data: try Data(contentsOf: videoURL)
            )
        } else {
            packagedVideo = nil
        }
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
            videoSnippet: packagedVideo?.manifest,
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

        return try EvidencePackage(
            manifest: manifest,
            frames: packagedFrames,
            videoSnippet: packagedVideo
        )
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

    private static func recordingAttemptObject(
        _ attempt: TrainingRecordingUploadAttempt
    ) -> [String: Any] {
        var object: [String: Any] = [
            "recording_id": attempt.recordingID,
            "disposition": attempt.disposition.rawValue,
        ]
        if let response = attempt.response {
            object["created"] = response.created
            object["state"] = response.state
        }
        if let failure = attempt.failure {
            object["failure_kind"] = failure.kind.rawValue
            object["failure_message"] = failure.message
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

    private static func recordingDiagnosticsObject(
        _ diagnostics: TrainingRecordingQueueDiagnostics
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
        case simulateRecording = "simulate-recording"
        case upload
        case retry
        case uploadRecording = "upload-recording"
        case retryRecording = "retry-recording"
        case result
    }

    let action: Action
    let root: URL?
    let fixturesRoot: URL?
    let server: URL?
    let variants: [PackageVariant]
    let packageID: UUID?
    let inputVideo: URL?
    let recordingID: String?
    let sessionID: String?
    let videoID: String?

    init(arguments: [String]) throws {
        guard let actionValue = arguments.first, let action = Action(rawValue: actionValue) else {
            throw OptionsError.usage
        }

        var root: URL?
        var fixturesRoot: URL?
        var server: URL?
        var variants: [PackageVariant] = []
        var packageID: UUID?
        var inputVideo: URL?
        var recordingID: String?
        var sessionID: String?
        var videoID: String?
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
            case "--input-video":
                inputVideo = URL(fileURLWithPath: arguments[index + 1]).standardizedFileURL
            case "--recording-id":
                recordingID = arguments[index + 1]
            case "--session-id":
                sessionID = arguments[index + 1]
            case "--video-id":
                videoID = arguments[index + 1]
            default:
                throw OptionsError.invalidValue(argument)
            }
            index += 2
        }

        if action == .create, variants.isEmpty {
            throw OptionsError.missingValue("--variant")
        }
        if action == .simulateRecording, inputVideo == nil {
            throw OptionsError.missingValue("--input-video")
        }
        self.action = action
        self.root = root
        self.fixturesRoot = fixturesRoot
        self.server = server
        self.variants = variants
        self.packageID = packageID
        self.inputVideo = inputVideo
        self.recordingID = recordingID
        self.sessionID = sessionID
        self.videoID = videoID
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

    var requiredInputVideo: URL {
        get throws {
            guard let inputVideo else { throw OptionsError.missingValue("--input-video") }
            return inputVideo
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
            return "Usage: create, simulate-recording, upload, retry, upload-recording, retry-recording, or result with the required options."
        case let .missingValue(option):
            return "Missing value for \(option)."
        case let .invalidValue(value):
            return "Invalid command-line value: \(value)."
        }
    }
}

private func utcString(from date: Date) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    return formatter.string(from: date)
}

private enum SavedVideoSimulationError: LocalizedError {
    case videoTrackMissing(URL)
    case cannotAddReaderOutput
    case readerStartFailed
    case readerFailed
    case noFrames
    case missingEvidenceRecordingCorrelation
    case missingProposalGeneratorRun
    case finalizationTimedOut
    case finalizationMissing

    var errorDescription: String? {
        switch self {
        case let .videoTrackMissing(url):
            return "The saved video has no video track: \(url.path)."
        case .cannotAddReaderOutput:
            return "The saved-video reader could not add its pixel-buffer output."
        case .readerStartFailed:
            return "The saved-video reader could not start."
        case .readerFailed:
            return "The saved-video reader failed while reading frames."
        case .noFrames:
            return "The saved video did not produce any frames or predictions."
        case .missingEvidenceRecordingCorrelation:
            return "The simulated evidence package has no recording correlation ID."
        case .missingProposalGeneratorRun:
            return "The simulated recording has no proposal generator run."
        case .finalizationTimedOut:
            return "The saved-video recording did not finish within 30 seconds."
        case .finalizationMissing:
            return "The saved-video recording finished without a result."
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
