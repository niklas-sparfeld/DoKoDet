import CoreMedia
import Foundation

/// Builds one package from an event and the compressed evidence ring.
public struct EvidencePackageAssembler: Sendable {
    private let configuration: EvidenceCaptureConfiguration
    private let sessionClock: EvidenceSessionClock
    private let sessionID: UUID
    private let model: EvidencePackageModelMetadata
    private let decoderConfiguration: CausalEventDecoder.Configuration
    private let targetInferenceHz: Double
    private let client: EvidencePackageClientMetadata

    public init(
        configuration: EvidenceCaptureConfiguration,
        sessionClock: EvidenceSessionClock,
        sessionID: UUID,
        model: EvidencePackageModelMetadata,
        decoderConfiguration: CausalEventDecoder.Configuration,
        client: EvidencePackageClientMetadata,
        targetInferenceHz: Double = 8.0
    ) {
        self.configuration = configuration
        self.sessionClock = sessionClock
        self.sessionID = sessionID
        self.model = model
        self.decoderConfiguration = decoderConfiguration
        precondition(targetInferenceHz > 0.0, "target inference rate must be positive")
        self.targetInferenceHz = targetInferenceHz
        self.client = client
    }

    public func assemble(
        event: DetectionEvent,
        eventSequence: Int,
        packageID: UUID = UUID(),
        ring: EvidenceFrameRing,
        camera: EvidencePackageCameraMetadata,
        scoreTrace: [ModelPrediction] = [],
        videoSnippet: PackagedEvidenceVideo? = nil,
        videoSnippetFailureReason: String? = nil,
        parentRecordingID: String? = nil
    ) throws -> EvidencePackage {
        guard videoSnippet == nil || videoSnippetFailureReason == nil else {
            throw EvidencePackageError.videoDataMismatch("multiple video results")
        }
        if sessionClock.elapsedTime(for: event.timestamp) == nil {
            sessionClock.observe(event.timestamp)
        }
        guard eventSequence > 0,
              let eventTimeMs = sessionClock.elapsedMilliseconds(for: event.timestamp),
              let emittedAtMs = sessionClock.elapsedMilliseconds(for: event.emittedAt),
              emittedAtMs >= eventTimeMs else {
            throw EvidencePackageError.invalidSessionTime
        }

        let selections = ring.select(
            eventTimestamp: event.timestamp,
            targetOffsetsMs: configuration.targetOffsetsMs,
            maximumLookupDistanceMs: configuration.maximumLookupDistanceMs
        )
        var packagedFrames: [PackagedEvidenceFrame] = []
        var missingTargets: [Int] = []

        for (index, selection) in selections.enumerated() {
            guard let frame = selection.frame,
                  let sessionElapsedMs = sessionClock.elapsedMilliseconds(for: frame.timestamp),
                  let capturedAtUTC = sessionClock.utcDate(for: frame.timestamp) else {
                missingTargets.append(selection.targetOffsetMs)
                continue
            }

            let partName = String(format: "frame_%02d", index)
            let manifest = EvidenceFrameManifest(
                partName: partName,
                targetOffsetMs: selection.targetOffsetMs,
                actualOffsetMs: selection.actualOffsetMs ?? 0,
                sessionElapsedMs: sessionElapsedMs,
                capturedAtUTC: capturedAtUTC,
                width: frame.width,
                height: frame.height,
                byteLength: frame.jpegData.count,
                contentType: "image/jpeg",
                sha256: evidencePackageSHA256Hex(frame.jpegData)
            )
            packagedFrames.append(
                PackagedEvidenceFrame(manifest: manifest, jpegData: frame.jpegData)
            )
        }

        let trace = scoreTrace.compactMap { prediction -> EvidenceScoreTraceEntry? in
            guard let sessionElapsedMs = sessionClock.elapsedMilliseconds(for: prediction.timestamp) else {
                return nil
            }
            return EvidenceScoreTraceEntry(
                sessionElapsedMs: sessionElapsedMs,
                score: prediction.cardEventProbability
            )
        }
        let manifest = EvidencePackageManifest(
            packageID: packageID,
            session: EvidenceSessionMetadata(sessionID: sessionID, eventSequence: eventSequence),
            event: EvidenceEventMetadata(
                eventTimeMs: eventTimeMs,
                emittedAtMs: emittedAtMs,
                evidenceComplete: missingTargets.isEmpty
            ),
            model: model,
            eventDecoder: EvidenceEventDecoderMetadata(
                algorithm: "causal_peak_v1",
                threshold: decoderConfiguration.threshold,
                peakConfirmationMs: milliseconds(decoderConfiguration.peakConfirmation),
                minimumEventGapMs: milliseconds(decoderConfiguration.minimumEventGap),
                targetInferenceHz: targetInferenceHz
            ),
            evidenceCapture: EvidenceCaptureMetadata(configuration: configuration),
            camera: camera,
            frames: packagedFrames.map(\.manifest),
            videoSnippet: videoSnippet?.manifest
                ?? videoSnippetFailureReason.map(EvidenceVideoSnippetManifest.init(failureReason:)),
            missingFrameTargetsMs: missingTargets,
            scoreTrace: trace.sorted { $0.sessionElapsedMs < $1.sessionElapsedMs },
            client: client
        )
        let repositoryMetadata: EvidencePackageRepositoryMetadata?
        if let parentRecordingID {
            let standardMetadata = try EvidencePackageRepositoryMetadata.standard(for: manifest)
            let lineage = try RepositoryEvidencePackageLineage(
                packageID: standardMetadata.lineage.packageID,
                parentSourceAssetID: standardMetadata.lineage.parentSourceAssetID,
                parentRecordingID: parentRecordingID,
                parentVideoID: standardMetadata.lineage.parentVideoID,
                sessionID: standardMetadata.lineage.sessionID
            )
            repositoryMetadata = try EvidencePackageRepositoryMetadata(
                packageRecord: standardMetadata.packageRecord,
                taskEnrollment: standardMetadata.taskEnrollment,
                lineage: lineage
            )
        } else {
            repositoryMetadata = nil
        }
        return try EvidencePackage(
            manifest: manifest,
            frames: packagedFrames,
            videoSnippet: videoSnippet,
            repositoryMetadata: repositoryMetadata
        )
    }

    private func milliseconds(_ time: CMTime) -> Int {
        max(0, Int((CMTimeGetSeconds(time) * 1_000.0).rounded()))
    }
}
