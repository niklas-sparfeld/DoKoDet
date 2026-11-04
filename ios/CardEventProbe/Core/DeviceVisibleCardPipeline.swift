@preconcurrency import AVFoundation
import CoreImage
import CoreVideo
import CryptoKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

public final class DeviceVisibleCardPipeline {
    private let fileManager = FileManager.default
    private let imageContext = CIContext(options: [.useSoftwareRenderer: false])

    public init() {}

    public func run(recordingBundleURL: URL) throws -> DeviceVisibleCardRevision {
        let started = ProcessInfo.processInfo.systemUptime
        let manifestURL = recordingBundleURL.appendingPathComponent("manifest.json")
        guard fileManager.fileExists(atPath: manifestURL.path) else {
            throw DeviceVisibleCardStageError.recordingUnavailable
        }
        let manifest = try JSONDecoder().decode(
            RepositoryBundle.self,
            from: Data(contentsOf: manifestURL)
        )
        let timeline = try DeviceCaptureTimeline.load(from: recordingBundleURL)
        guard timeline.recordingID == manifest.recordingID else {
            throw DeviceVisibleCardStageError.invalidRun
        }
        guard let proposalFile = manifest.files.proposalGeneratorRuns.first else {
            throw DeviceVisibleCardStageError.proposalUnavailable
        }
        let proposalURL = recordingBundleURL.appendingPathComponent(proposalFile.relativePath)
        let proposal = try JSONDecoder().decode(
            RepositoryProposalGeneratorRun.self,
            from: Data(contentsOf: proposalURL)
        )
        guard proposal.recordingID == manifest.recordingID,
              proposal.videoID == manifest.videoID else {
            throw DeviceVisibleCardStageError.invalidRun
        }
        let events = try proposal.eventProposals.enumerated().map { index, value in
            try DeviceVisibleCardEvent(index: index, timeS: value.timeS, probability: value.probability)
        }
        let mappings = events.map {
            DeviceVisibleCardFrameSelector.mapping(for: $0, frames: timeline.frames)
        }
        let outputRoot = recordingBundleURL
            .appendingPathComponent(".device/stages/visible-cards", isDirectory: true)
        let imageRoot = outputRoot.appendingPathComponent("frames", isDirectory: true)
        try fileManager.createDirectory(at: imageRoot, withIntermediateDirectories: true)

        var results: [DeviceVisibleCardEventResult] = []
        if timeline.interrupted {
            results = zip(events, mappings).map { event, mapping in
                DeviceVisibleCardEventResult(
                    event: event,
                    frameMapping: mapping,
                    imagePath: nil,
                    imageSHA256: nil,
                    imageWidth: nil,
                    imageHeight: nil,
                    detections: [],
                    status: "interrupted",
                    elapsedMs: 0,
                    error: "The capture timeline is interrupted."
                )
            }
            return try saveRevision(
                recordingID: manifest.recordingID,
                videoSHA256: manifest.files.video.sha256,
                compiledModelSHA256: nil,
                results: results,
                status: "interrupted",
                started: started,
                outputRoot: outputRoot
            )
        }

        var resultsByIndex: [Int: DeviceVisibleCardEventResult] = [:]
        var eventsByFrame: [Int: [Int]] = [:]
        var compiledModelSHA256: String?
        for index in events.indices {
            let mapping = mappings[index]
            guard mapping.status == "mapped", let frameIndex = mapping.frameIndex else {
                resultsByIndex[index] = failedResult(events[index], mapping, mapping.message ?? "Frame mapping failed.")
                continue
            }
            eventsByFrame[frameIndex, default: []].append(index)
        }

        if !eventsByFrame.isEmpty {
            do {
                let model = try RfdetrCoreMLRunner.loadBundled()
                compiledModelSHA256 = model.compiledModelSHA256
            let videoURL = recordingBundleURL.appendingPathComponent(manifest.files.video.relativePath)
            guard fileManager.fileExists(atPath: videoURL.path) else {
                throw DeviceVisibleCardStageError.videoUnavailable
            }
            let asset = AVURLAsset(url: videoURL)
            guard let track = asset.tracks(withMediaType: .video).first else {
                throw DeviceVisibleCardStageError.videoUnavailable
            }
            let reader = try AVAssetReader(asset: asset)
            let output = AVAssetReaderTrackOutput(
                track: track,
                outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
            )
            output.alwaysCopiesSampleData = false
            guard reader.canAdd(output) else { throw DeviceVisibleCardStageError.videoUnavailable }
            reader.add(output)
            guard reader.startReading() else { throw reader.error ?? DeviceVisibleCardStageError.videoUnavailable }

            var frameIndex = 0
            while let sample = output.copyNextSampleBuffer() {
                defer { frameIndex += 1 }
                guard let targetEvents = eventsByFrame[frameIndex],
                      let pixelBuffer = CMSampleBufferGetImageBuffer(sample) else { continue }
                let actualTime = CMSampleBufferGetPresentationTimeStamp(sample)
                for eventIndex in targetEvents {
                    let event = events[eventIndex]
                    let mapping = mappings[eventIndex]
                    let elapsedStart = ProcessInfo.processInfo.systemUptime
                    let expectedTime = CMTime(seconds: mapping.actualTimeS ?? -1, preferredTimescale: 1_000_000)
                    let delta = abs(CMTimeGetSeconds(CMTimeSubtract(actualTime, expectedTime)))
                    guard delta <= CMTimeGetSeconds(DeviceVisibleCardFrameSelector.maximumDelta) else {
                        resultsByIndex[eventIndex] = failedResult(
                            event,
                            mapping,
                            "The selected frame could not be decoded at its recorded presentation time."
                        )
                        continue
                    }
                    do {
                        let image = try transformedImage(pixelBuffer, transform: track.preferredTransform)
                        let tensor = try RfdetrImageTensor(cgImage: image)
                        let raw = try model.predict(tensor)
                        let stageOutput = try DeviceVisibleCardPostprocessor.processWithCandidates(
                            raw,
                            imageWidth: image.width,
                            imageHeight: image.height
                        )
                        let png = try pngData(image)
                        let relativePath = ".device/stages/visible-cards/frames/\(event.eventID).png"
                        try png.write(
                            to: recordingBundleURL.appendingPathComponent(relativePath),
                            options: .atomic
                        )
                        resultsByIndex[eventIndex] = DeviceVisibleCardEventResult(
                            event: event,
                            frameMapping: mapping,
                            imagePath: relativePath,
                            imageSHA256: SHA256.hash(data: png).hexString,
                            imageWidth: image.width,
                            imageHeight: image.height,
                            thresholdFreeCandidates: stageOutput.candidates,
                            detections: stageOutput.detections,
                            status: "complete",
                            elapsedMs: (ProcessInfo.processInfo.systemUptime - elapsedStart) * 1_000,
                            error: nil
                        )
                    } catch {
                        resultsByIndex[eventIndex] = failedResult(
                            event,
                            mapping,
                            error.localizedDescription,
                            elapsedMs: (ProcessInfo.processInfo.systemUptime - elapsedStart) * 1_000
                        )
                    }
                }
            }
            if reader.status == .failed {
                let message = reader.error?.localizedDescription ?? "Video decoding failed."
                for index in events.indices where resultsByIndex[index] == nil {
                    resultsByIndex[index] = failedResult(events[index], mappings[index], message)
                }
            }
            } catch {
                for index in events.indices where resultsByIndex[index] == nil {
                    resultsByIndex[index] = failedResult(events[index], mappings[index], error.localizedDescription)
                }
            }
        }

        for index in events.indices where resultsByIndex[index] == nil {
            resultsByIndex[index] = failedResult(events[index], mappings[index], "The selected frame was not present in the recording.")
        }
        results = events.indices.compactMap { resultsByIndex[$0] }
        let status = results.allSatisfy { $0.status == "complete" } ? "complete" : "failed"
        return try saveRevision(
            recordingID: manifest.recordingID,
            videoSHA256: manifest.files.video.sha256,
            compiledModelSHA256: compiledModelSHA256,
            results: results,
            status: status,
            started: started,
            outputRoot: outputRoot
        )
    }

    private func transformedImage(_ pixelBuffer: CVPixelBuffer, transform: CGAffineTransform) throws -> CGImage {
        let transformed = CIImage(cvPixelBuffer: pixelBuffer).transformed(by: transform)
        let extent = transformed.extent.integral
        guard !extent.isEmpty else { throw DeviceVisibleCardStageError.invalidOutput }
        let normalized = transformed.transformed(
            by: CGAffineTransform(translationX: -extent.minX, y: -extent.minY)
        )
        guard let image = imageContext.createCGImage(
            normalized,
            from: CGRect(origin: .zero, size: extent.size)
        ) else { throw DeviceVisibleCardStageError.invalidOutput }
        return image
    }

    private func pngData(_ image: CGImage) throws -> Data {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            data,
            UTType.png.identifier as CFString,
            1,
            nil
        ) else { throw DeviceVisibleCardStageError.invalidOutput }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { throw DeviceVisibleCardStageError.invalidOutput }
        return data as Data
    }

    private func failedResult(
        _ event: DeviceVisibleCardEvent,
        _ mapping: DeviceVisibleCardFrameMapping,
        _ message: String,
        elapsedMs: Double = 0
    ) -> DeviceVisibleCardEventResult {
        DeviceVisibleCardEventResult(
            event: event,
            frameMapping: mapping,
            imagePath: nil,
            imageSHA256: nil,
            imageWidth: nil,
            imageHeight: nil,
            detections: [],
            status: "failed",
            elapsedMs: elapsedMs,
            error: message
        )
    }

    private func saveRevision(
        recordingID: String,
        videoSHA256: String,
        compiledModelSHA256: String?,
        results: [DeviceVisibleCardEventResult],
        status: String,
        started: TimeInterval,
        outputRoot: URL
    ) throws -> DeviceVisibleCardRevision {
        let revision = try DeviceVisibleCardRevision(
            recordingID: recordingID,
            videoSHA256: videoSHA256,
            compiledModelSHA256: compiledModelSHA256,
            events: results,
            status: status,
            elapsedMs: (ProcessInfo.processInfo.systemUptime - started) * 1_000
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(revision).write(
            to: outputRoot.appendingPathComponent("revision.json"),
            options: .atomic
        )
        return revision
    }
}

private extension Digest {
    var hexString: String { map { String(format: "%02x", $0) }.joined() }
}
