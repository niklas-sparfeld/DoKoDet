import AVFoundation
import CoreMedia
import CoreVideo
import Foundation

final class VideoReplayRunner {
    private let queue = DispatchQueue(label: "com.dokodetector.CardEventProbe.replay")
    private let lock = NSLock()
    private var cancelled = false

    func start(
        url: URL,
        modelRunner: CardEventModelRunner,
        eventDecoder: CausalEventDecoder,
        evidenceSampler: EvidenceFrameSampler,
        onUpdate: @escaping (ReplayProgress) -> Void
    ) {
        lock.lock()
        cancelled = false
        lock.unlock()

        let hasSecurityScope = url.startAccessingSecurityScopedResource()

        queue.async { [weak self] in
            guard let self else { return }
            defer {
                if hasSecurityScope {
                    url.stopAccessingSecurityScopedResource()
                }
            }

            do {
                try self.run(
                    url: url,
                    modelRunner: modelRunner,
                    eventDecoder: eventDecoder,
                    evidenceSampler: evidenceSampler,
                    onUpdate: onUpdate
                )
            } catch {
                self.publish(
                    ReplayProgress(
                        fileName: url.lastPathComponent,
                        durationSeconds: 0.0,
                        currentTimeSeconds: 0.0,
                        framesRead: 0,
                        predictionsProduced: 0,
                        eventCount: 0,
                        lastEventTimestampSeconds: nil,
                        averageInferenceDurationMs: nil,
                        frame: nil,
                        prediction: nil,
                        event: nil,
                        isComplete: true,
                        isCancelled: false,
                        errorMessage: error.localizedDescription
                    ),
                    onUpdate: onUpdate
                )
            }
        }
    }

    func cancel() {
        lock.lock()
        cancelled = true
        lock.unlock()
    }

    private func run(
        url: URL,
        modelRunner: CardEventModelRunner,
        eventDecoder: CausalEventDecoder,
        evidenceSampler: EvidenceFrameSampler,
        onUpdate: @escaping (ReplayProgress) -> Void
    ) throws {
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first else {
            throw ReplayError.videoTrackMissing
        }
        let duration = max(0.0, asset.duration.seconds)
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(
            track: track,
            outputSettings: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            ]
        )
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { throw ReplayError.cannotAddOutput }
        reader.add(output)
        guard reader.startReading() else {
            throw reader.error ?? ReplayError.readerStartFailed
        }

        modelRunner.reset()
        eventDecoder.reset()
        var samplingPolicy = InferenceSamplingPolicy()
        var framesRead = 0
        var predictionsProduced = 0
        var eventCount = 0
        var lastEventTimestampSeconds: Double?
        var totalInferenceDurationMs = 0.0
        var latestPrediction: ModelPrediction?

        while let sampleBuffer = output.copyNextSampleBuffer() {
            if isCancelled() {
                reader.cancelReading()
                publish(
                    ReplayProgress(
                        fileName: url.lastPathComponent,
                        durationSeconds: duration,
                        currentTimeSeconds: latestPrediction.map { CMTimeGetSeconds($0.timestamp) } ?? 0.0,
                        framesRead: framesRead,
                        predictionsProduced: predictionsProduced,
                        eventCount: eventCount,
                        lastEventTimestampSeconds: lastEventTimestampSeconds,
                        averageInferenceDurationMs: averageInferenceDurationMs(
                            total: totalInferenceDurationMs,
                            count: predictionsProduced
                        ),
                        frame: nil,
                        prediction: latestPrediction,
                        event: nil,
                        isComplete: true,
                        isCancelled: true,
                        errorMessage: nil
                    ),
                    onUpdate: onUpdate
                )
                return
            }

            framesRead += 1
            let timestamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
                continue
            }

            let frame = VideoFrame(
                pixelBuffer: pixelBuffer,
                timestamp: timestamp,
                orientation: .up
            )
            evidenceSampler.consume(frame)
            guard samplingPolicy.accept(timestamp: timestamp, inferenceInFlight: false) == .accepted else {
                continue
            }
            guard let prediction = try modelRunner.consume(frame) else { continue }
            latestPrediction = prediction
            predictionsProduced += 1
            totalInferenceDurationMs += prediction.inferenceDurationMs
            let event = eventDecoder.consume(prediction)
            if let event {
                eventCount += 1
                lastEventTimestampSeconds = CMTimeGetSeconds(event.timestamp)
            }

            publish(
                ReplayProgress(
                    fileName: url.lastPathComponent,
                    durationSeconds: duration,
                    currentTimeSeconds: CMTimeGetSeconds(prediction.timestamp),
                    framesRead: framesRead,
                    predictionsProduced: predictionsProduced,
                    eventCount: eventCount,
                    lastEventTimestampSeconds: lastEventTimestampSeconds,
                    averageInferenceDurationMs: averageInferenceDurationMs(
                        total: totalInferenceDurationMs,
                        count: predictionsProduced
                    ),
                    frame: frame,
                    prediction: prediction,
                    event: event,
                    isComplete: false,
                    isCancelled: false,
                    errorMessage: nil
                ),
                onUpdate: onUpdate
            )
        }

        if reader.status == .failed {
            throw reader.error ?? ReplayError.readerFailed
        }
        let flushedEvent = eventDecoder.flush()
        if let flushedEvent {
            eventCount += 1
            lastEventTimestampSeconds = CMTimeGetSeconds(flushedEvent.timestamp)
        }
        publish(
            ReplayProgress(
                fileName: url.lastPathComponent,
                durationSeconds: duration,
                currentTimeSeconds: latestPrediction.map { CMTimeGetSeconds($0.timestamp) } ?? duration,
                framesRead: framesRead,
                predictionsProduced: predictionsProduced,
                eventCount: eventCount,
                lastEventTimestampSeconds: lastEventTimestampSeconds,
                averageInferenceDurationMs: averageInferenceDurationMs(
                    total: totalInferenceDurationMs,
                    count: predictionsProduced
                ),
                frame: nil,
                prediction: latestPrediction,
                event: flushedEvent,
                isComplete: true,
                isCancelled: false,
                errorMessage: nil
            ),
            onUpdate: onUpdate
        )
    }

    private func isCancelled() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancelled
    }

    private func averageInferenceDurationMs(total: Double, count: Int) -> Double? {
        count == 0 ? nil : total / Double(count)
    }

    private func publish(
        _ progress: ReplayProgress,
        onUpdate: @escaping (ReplayProgress) -> Void
    ) {
        DispatchQueue.main.async {
            onUpdate(progress)
        }
    }
}

private enum ReplayError: LocalizedError {
    case videoTrackMissing
    case cannotAddOutput
    case readerStartFailed
    case readerFailed

    var errorDescription: String? {
        switch self {
        case .videoTrackMissing:
            return "The selected file has no video track."
        case .cannotAddOutput:
            return "The replay video output could not be added."
        case .readerStartFailed:
            return "The replay reader could not start."
        case .readerFailed:
            return "The replay reader failed while decoding the video."
        }
    }
}
