import CoreMedia
import CoreVideo
import Foundation
import ImageIO

/// Creates and persists event packages after the configured future evidence window.
public final class EvidencePackageCoordinator: @unchecked Sendable {
    private struct PendingEvent {
        let event: DetectionEvent
        let packageID: UUID
        let eventSequence: Int
    }

    private enum VideoSnippetCaptureResult {
        case complete(PackagedEvidenceVideo)
        case failed

        var completeVideo: PackagedEvidenceVideo? {
            guard case let .complete(video) = self else { return nil }
            return video
        }

        var failureReason: String? {
            guard case .failed = self else { return nil }
            return "capture_failed"
        }
    }

    private let configuration: EvidenceCaptureConfiguration
    private let captureSession: CaptureSession
    private let ring: EvidenceFrameRing
    private let store: EvidencePackageStore
    private let assembler: EvidencePackageAssembler
    private let videoSnippetProvider: (any EvidenceVideoSnippetProviding)?
    private let queue = DispatchQueue(
        label: "com.dokodetector.CardEventProbe.package",
        qos: .userInitiated
    )
    private let onPackagePersisted: (Result<URL, EvidencePackageStoreError>) -> Void
    private let onEventSequenceReserved: (UUID, Int) -> Void
    private var pendingEvents: [PendingEvent] = []
    private var processedEventIDs = Set<UUID>()
    private var preparedVideoResults: [UUID: VideoSnippetCaptureResult] = [:]
    private var scoreTrace: [ModelPrediction] = []
    private var camera: EvidencePackageCameraMetadata
    private var recordingID: String?
    private var stopped = false

    public init(
        configuration: EvidenceCaptureConfiguration,
        captureSession: CaptureSession,
        ring: EvidenceFrameRing,
        store: EvidencePackageStore,
        model: EvidencePackageModelMetadata,
        decoderConfiguration: CausalEventDecoder.Configuration,
        client: EvidencePackageClientMetadata,
        camera: EvidencePackageCameraMetadata,
        recordingID: String? = nil,
        videoSnippetProvider: (any EvidenceVideoSnippetProviding)? = nil,
        onPackagePersisted: @escaping (Result<URL, EvidencePackageStoreError>) -> Void = { _ in },
        onEventSequenceReserved: @escaping (UUID, Int) -> Void = { _, _ in }
    ) {
        self.configuration = configuration
        self.captureSession = captureSession
        self.ring = ring
        self.store = store
        assembler = EvidencePackageAssembler(
            configuration: configuration,
            sessionClock: captureSession.clock,
            sessionID: captureSession.sessionID,
            model: model,
            decoderConfiguration: decoderConfiguration,
            client: client
        )
        self.onPackagePersisted = onPackagePersisted
        self.onEventSequenceReserved = onEventSequenceReserved
        self.camera = camera
        self.recordingID = recordingID
        self.videoSnippetProvider = videoSnippetProvider
    }

    /// Compatibility initializer for package-only callers that do not need persistence.
    public convenience init(
        configuration: EvidenceCaptureConfiguration,
        sessionClock: EvidenceSessionClock,
        sessionID: UUID = UUID(),
        ring: EvidenceFrameRing,
        store: EvidencePackageStore,
        model: EvidencePackageModelMetadata,
        decoderConfiguration: CausalEventDecoder.Configuration,
        client: EvidencePackageClientMetadata,
        camera: EvidencePackageCameraMetadata,
        recordingID: String? = nil,
        videoSnippetProvider: (any EvidenceVideoSnippetProviding)? = nil,
        onPackagePersisted: @escaping (Result<URL, EvidencePackageStoreError>) -> Void = { _ in },
        onEventSequenceReserved: @escaping (UUID, Int) -> Void = { _, _ in }
    ) {
        self.init(
            configuration: configuration,
            captureSession: CaptureSession(
                sessionID: sessionID,
                startedAtUTC: sessionClock.startedAtUTC,
                clock: sessionClock
            ),
            ring: ring,
            store: store,
            model: model,
            decoderConfiguration: decoderConfiguration,
            client: client,
            camera: camera,
            recordingID: recordingID,
            videoSnippetProvider: videoSnippetProvider,
            onPackagePersisted: onPackagePersisted,
            onEventSequenceReserved: onEventSequenceReserved
        )
    }

    public var captureSessionID: UUID { captureSession.sessionID }

    public var canonicalSessionID: UUID { captureSession.sessionID }

    public var recordingCorrelationID: String? {
        queue.sync { recordingID }
    }

    /// The canonical session remains the capture session. Until the evidence contract gains
    /// canonical recording fields, this is the value to map to legacy capture_session_id.
    public var legacyCaptureSessionID: String? {
        queue.sync { recordingID }
    }

    public func setRecordingID(_ recordingID: String?) {
        queue.sync {
            guard !stopped else { return }
            self.recordingID = recordingID
        }
    }

    public var pendingEventCount: Int {
        queue.sync { pendingEvents.count }
    }

    /// Record the dimensions and orientation of the complete source frame.
    public func observe(_ frame: VideoFrame) {
        queue.async {
            guard !self.stopped else { return }
            self.captureSession.clock.observe(frame.timestamp)
            self.camera = EvidencePackageCameraMetadata(
                position: self.camera.position,
                orientation: Self.orientationName(frame.orientation),
                width: CVPixelBufferGetWidth(frame.pixelBuffer),
                height: CVPixelBufferGetHeight(frame.pixelBuffer)
            )
        }
    }

    /// Record one model prediction and any event emitted by the decoder.
    public func consume(_ prediction: ModelPrediction, event: DetectionEvent? = nil) {
        queue.async {
            guard !self.stopped else { return }
            self.captureSession.clock.observe(prediction.timestamp)
            self.scoreTrace.append(prediction)
            self.trimScoreTrace(through: prediction.timestamp)
            if let event {
                self.addPending(event)
            }
            self.finalizeEligible(through: prediction.timestamp)
        }
    }

    /// Record an event emitted while the decoder flushes at end of replay.
    public func record(_ event: DetectionEvent) {
        queue.async {
            guard !self.stopped else { return }
            self.captureSession.clock.observe(event.timestamp)
            self.addPending(event)
        }
    }

    /// Finalize all pending events. Use this when a replay or capture session ends.
    public func finish() {
        queue.async {
            guard !self.stopped else { return }
            self.finalizeAll()
            self.stopped = true
        }
    }

    /// Wait for package work submitted before this call to finish. Intended for tests and handoff.
    public func drain() {
        queue.sync {}
    }

    public func reset() {
        queue.sync {
            pendingEvents.removeAll(keepingCapacity: true)
            processedEventIDs.removeAll(keepingCapacity: true)
            preparedVideoResults.removeAll(keepingCapacity: true)
            scoreTrace.removeAll(keepingCapacity: true)
            stopped = false
        }
    }

    private func addPending(_ event: DetectionEvent) {
        guard !processedEventIDs.contains(event.id) else { return }
        let eventSequence: Int
        do {
            eventSequence = try captureSession.reserveEventSequence()
        } catch {
            onPackagePersisted(
                .failure(
                    .writeFailed(
                        store.root,
                        "The event sequence could not be reserved: \(error.localizedDescription)"
                    )
                )
            )
            return
        }
        processedEventIDs.insert(event.id)
        onEventSequenceReserved(captureSession.sessionID, eventSequence)
        let pending = PendingEvent(
            event: event,
            packageID: UUID(),
            eventSequence: eventSequence
        )
        if videoSnippetProvider != nil {
            preparedVideoResults[pending.packageID] = captureVideoSnippet(for: event)
        }
        pendingEvents.append(pending)
        pendingEvents.sort {
            CMTimeCompare($0.event.timestamp, $1.event.timestamp) < 0
        }
    }

    private func finalizeEligible(through timestamp: CMTime) {
        let finalizationDelay = max(
            configuration.finalizationDelayMs,
            configuration.targetOffsetsMs.max() ?? 0
        )
        let eligible = CMTimeSubtract(
            timestamp,
            CMTime(value: Int64(finalizationDelay), timescale: 1_000)
        )
        let events = pendingEvents.filter {
            CMTimeCompare($0.event.timestamp, eligible) <= 0
        }
        pendingEvents.removeAll { pending in
            events.contains { $0.packageID == pending.packageID }
        }
        persist(events)
    }

    private func finalizeAll() {
        let events = pendingEvents
        pendingEvents.removeAll(keepingCapacity: true)
        persist(events)
    }

    private func persist(_ events: [PendingEvent]) {
        for pending in events {
            do {
                let videoResult = preparedVideoResults.removeValue(forKey: pending.packageID)
                let package = try assembler.assemble(
                    event: pending.event,
                    eventSequence: pending.eventSequence,
                    packageID: pending.packageID,
                    ring: ring,
                    camera: camera,
                    scoreTrace: scoreTrace,
                    videoSnippet: videoResult?.completeVideo,
                    videoSnippetFailureReason: videoResult?.failureReason
                )
                let url = try store.persist(package)
                onPackagePersisted(.success(url))
            } catch let error as EvidencePackageStoreError {
                onPackagePersisted(.failure(error))
            } catch {
                onPackagePersisted(
                    .failure(.writeFailed(store.packageURL(for: pending.packageID), error.localizedDescription))
                )
            }
        }
    }

    private func captureVideoSnippet(for event: DetectionEvent) -> VideoSnippetCaptureResult? {
        guard let videoSnippetProvider else { return nil }
        do {
            return .complete(try videoSnippetProvider.capture(eventTimestamp: event.timestamp))
        } catch {
            return .failed
        }
    }

    private func trimScoreTrace(through timestamp: CMTime) {
        let retention = max(configuration.historySeconds, 2.0) + 1.0
        let cutoff = CMTimeSubtract(timestamp, CMTime(seconds: retention, preferredTimescale: 600))
        scoreTrace.removeAll {
            CMTimeCompare($0.timestamp, cutoff) < 0
        }
    }

    private static func orientationName(_ orientation: CGImagePropertyOrientation) -> String {
        switch orientation {
        case .up: return "up"
        case .upMirrored: return "up_mirrored"
        case .down: return "down"
        case .downMirrored: return "down_mirrored"
        case .left: return "left"
        case .leftMirrored: return "left_mirrored"
        case .right: return "right"
        case .rightMirrored: return "right_mirrored"
        @unknown default: return "unknown"
        }
    }
}
