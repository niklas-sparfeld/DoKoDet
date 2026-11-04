import CoreMedia
import Foundation

public struct DeviceVisibleCardEvent: Codable, Equatable, Sendable {
    public let eventID: String
    public let timeS: Double
    public let probability: Double

    public init(index: Int, timeS: Double, probability: Double) throws {
        guard index >= 0, timeS.isFinite, timeS >= 0,
              probability.isFinite, (0...1).contains(probability) else {
            throw DeviceVisibleCardStageError.invalidEvent
        }
        eventID = "event-\(index + 1)"
        self.timeS = timeS
        self.probability = probability
    }

    private enum CodingKeys: String, CodingKey {
        case eventID = "event_id"
        case timeS = "time_s"
        case probability
    }
}

public struct DeviceVisibleCardFrameMapping: Codable, Equatable, Sendable {
    public let eventID: String
    public let requestedTimeS: Double
    public let frameIndex: Int?
    public let actualTimeS: Double?
    public let deltaS: Double?
    public let status: String
    public let message: String?

    private enum CodingKeys: String, CodingKey {
        case eventID = "event_id"
        case requestedTimeS = "requested_time_s"
        case frameIndex = "frame_index"
        case actualTimeS = "actual_time_s"
        case deltaS = "delta_s"
        case status
        case message
    }
}

public enum DeviceVisibleCardFrameSelector {
    public static let maximumDelta = CMTime(value: 1, timescale: 8)

    public static func mapping(
        for event: DeviceVisibleCardEvent,
        frames: [DeviceCaptureFrameTime],
        maximumDelta: CMTime = maximumDelta
    ) -> DeviceVisibleCardFrameMapping {
        let request = CMTime(seconds: event.timeS, preferredTimescale: 1_000_000)
        let nearest = frames.compactMap { frame -> (DeviceCaptureFrameTime, CMTime)? in
            let time = frame.movieTime.cmTime
            guard time.isNumeric, time.epoch == request.epoch else { return nil }
            return (frame, CMTimeAbsoluteValue(CMTimeSubtract(time, request)))
        }.min { left, right in
            let comparison = CMTimeCompare(left.1, right.1)
            if comparison == 0 {
                return CMTimeCompare(left.0.movieTime.cmTime, right.0.movieTime.cmTime) < 0
            }
            return comparison < 0
        }

        guard let (frame, delta) = nearest,
              CMTimeCompare(delta, maximumDelta) <= 0 else {
            return DeviceVisibleCardFrameMapping(
                eventID: event.eventID,
                requestedTimeS: event.timeS,
                frameIndex: nil,
                actualTimeS: nil,
                deltaS: nil,
                status: "failed",
                message: "No decodable video frame is within 0.125 seconds of the event."
            )
        }
        return DeviceVisibleCardFrameMapping(
            eventID: event.eventID,
            requestedTimeS: event.timeS,
            frameIndex: frame.frameIndex,
            actualTimeS: CMTimeGetSeconds(frame.movieTime.cmTime),
            deltaS: CMTimeGetSeconds(delta),
            status: "mapped",
            message: nil
        )
    }
}

public enum DeviceVisibleCardStageError: Error, Equatable {
    case invalidEvent
    case invalidRun
    case invalidOutput
    case modelUnavailable
    case recordingUnavailable
    case proposalUnavailable
    case videoUnavailable
}

public struct RfdetrRawOutput: Sendable {
    public let queryCount: Int
    public let classCount: Int
    public let maskWidth: Int
    public let maskHeight: Int
    public let boxesCXCYWH: [Float]
    public let classLogits: [Float]
    public let maskLogits: [Float]

    public init(
        queryCount: Int,
        classCount: Int,
        maskWidth: Int,
        maskHeight: Int,
        boxesCXCYWH: [Float],
        classLogits: [Float],
        maskLogits: [Float]
    ) throws {
        guard queryCount > 0, classCount > 0, maskWidth > 0, maskHeight > 0,
              boxesCXCYWH.count == queryCount * 4,
              classLogits.count == queryCount * classCount,
              maskLogits.count == queryCount * maskWidth * maskHeight,
              boxesCXCYWH.allSatisfy(\.isFinite),
              classLogits.allSatisfy(\.isFinite), maskLogits.allSatisfy(\.isFinite) else {
            throw DeviceVisibleCardStageError.invalidOutput
        }
        self.queryCount = queryCount
        self.classCount = classCount
        self.maskWidth = maskWidth
        self.maskHeight = maskHeight
        self.boxesCXCYWH = boxesCXCYWH
        self.classLogits = classLogits
        self.maskLogits = maskLogits
    }
}

public struct DeviceVisibleCardDetection: Codable, Equatable, Sendable {
    public let classID: Int
    public let className: String
    public let score: Double
    public let boxXYXY: [Double]
    public let normalizedBox1000: [Int]
    public let polygon: [[Int]]?

    public init(
        classID: Int,
        className: String,
        score: Double,
        boxXYXY: [Double],
        polygon: [[Int]]?,
        imageWidth: Int,
        imageHeight: Int
    ) {
        self.classID = classID
        self.className = className
        self.score = score
        self.boxXYXY = boxXYXY
        normalizedBox1000 = [
            Int(floor(boxXYXY[0] * 1_000 / Double(imageWidth))),
            Int(floor(boxXYXY[1] * 1_000 / Double(imageHeight))),
            Int(ceil(boxXYXY[2] * 1_000 / Double(imageWidth))),
            Int(ceil(boxXYXY[3] * 1_000 / Double(imageHeight))),
        ]
        self.polygon = polygon?.map { point in
            [
                Int((Double(point[0]) * 1_000 / Double(imageWidth)).rounded(.toNearestOrEven)),
                Int((Double(point[1]) * 1_000 / Double(imageHeight)).rounded(.toNearestOrEven)),
            ]
        }
    }

    private enum CodingKeys: String, CodingKey {
        case classID = "class_id"
        case className = "class_name"
        case score
        case boxXYXY = "box_xyxy"
        case normalizedBox1000 = "normalized_box_1000"
        case polygon
    }
}

public struct DeviceVisibleCardCandidate: Codable, Equatable, Sendable {
    public let queryIndex: Int
    public let classID: Int
    public let score: Double
    public let boxXYXY: [Double]

    private enum CodingKeys: String, CodingKey {
        case queryIndex = "query_index"
        case classID = "class_id"
        case score
        case boxXYXY = "box_xyxy"
    }
}

public struct DeviceVisibleCardPostprocessingResult: Equatable, Sendable {
    public let candidates: [DeviceVisibleCardCandidate]
    public let detections: [DeviceVisibleCardDetection]
}

public struct DeviceVisibleCardEventResult: Codable, Equatable, Sendable {
    public let event: DeviceVisibleCardEvent
    public let frameMapping: DeviceVisibleCardFrameMapping
    public let imagePath: String?
    public let imageSHA256: String?
    public let imageWidth: Int?
    public let imageHeight: Int?
    public let thresholdFreeCandidates: [DeviceVisibleCardCandidate]
    public let detections: [DeviceVisibleCardDetection]
    public let status: String
    public let elapsedMs: Double
    public let error: String?

    public init(
        event: DeviceVisibleCardEvent,
        frameMapping: DeviceVisibleCardFrameMapping,
        imagePath: String?,
        imageSHA256: String?,
        imageWidth: Int?,
        imageHeight: Int?,
        thresholdFreeCandidates: [DeviceVisibleCardCandidate] = [],
        detections: [DeviceVisibleCardDetection],
        status: String,
        elapsedMs: Double,
        error: String?
    ) {
        self.event = event
        self.frameMapping = frameMapping
        self.imagePath = imagePath
        self.imageSHA256 = imageSHA256
        self.imageWidth = imageWidth
        self.imageHeight = imageHeight
        self.thresholdFreeCandidates = thresholdFreeCandidates
        self.detections = detections
        self.status = status
        self.elapsedMs = elapsedMs
        self.error = error
    }

    private enum CodingKeys: String, CodingKey {
        case event
        case frameMapping = "frame_mapping"
        case imagePath = "image_path"
        case imageSHA256 = "image_sha256"
        case imageWidth = "image_width"
        case imageHeight = "image_height"
        case thresholdFreeCandidates = "threshold_free_candidates"
        case detections
        case status
        case elapsedMs = "elapsed_ms"
        case error
    }
}

public struct DeviceVisibleCardRevision: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let stageID: String
    public let recordingID: String
    public let videoSHA256: String
    public let modelName: String
    public let modelSHA256: String
    public let checkpointSHA256: String
    public let compiledModelSHA256: String?
    public let compiledModelIdentity: String?
    public let preprocessing: String
    public let classMap: [String: String]
    public let confidenceThreshold: Double
    public let maskLogitThreshold: Double
    public let maximumCandidates: Int
    public let extractionPolicy: String
    public let status: String
    public let elapsedMs: Double
    public let events: [DeviceVisibleCardEventResult]

    public init(
        recordingID: String,
        videoSHA256: String,
        compiledModelSHA256: String?,
        events: [DeviceVisibleCardEventResult],
        status: String,
        elapsedMs: Double
    ) throws {
        guard RepositoryIntakeContract.isIdentifier(recordingID),
              RepositoryIntakeContract.isSHA256(videoSHA256),
              elapsedMs.isFinite, elapsedMs >= 0,
              ["complete", "failed", "interrupted"].contains(status) else {
            throw DeviceVisibleCardStageError.invalidRun
        }
        schemaVersion = "doko-device-visible-cards/v1"
        stageID = "visible-cards-\(recordingID)"
        self.recordingID = recordingID
        self.videoSHA256 = videoSHA256
        modelName = RfdetrCoreMLRunner.modelName
        modelSHA256 = RfdetrCoreMLRunner.packageSHA256
        checkpointSHA256 = RfdetrCoreMLRunner.checkpointSHA256
        self.compiledModelSHA256 = compiledModelSHA256
        compiledModelIdentity = compiledModelSHA256.map {
            "coremlc:\(RfdetrCoreMLRunner.modelName):\($0)"
        }
        preprocessing = "rgb-432x432-bilinear-no-antialias-imagenet-v1"
        classMap = ["0": "visible_card", "1": "card_pile"]
        confidenceThreshold = Double(DeviceVisibleCardPostprocessor.scoreThreshold)
        maskLogitThreshold = 0
        maximumCandidates = 200
        extractionPolicy = "event-peak-nearest-presentation-frame-v1"
        self.status = status
        self.elapsedMs = elapsedMs
        self.events = events
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case stageID = "stage_id"
        case recordingID = "recording_id"
        case videoSHA256 = "video_sha256"
        case modelName = "model_name"
        case modelSHA256 = "model_sha256"
        case checkpointSHA256 = "checkpoint_sha256"
        case compiledModelSHA256 = "compiled_model_sha256"
        case compiledModelIdentity = "compiled_model_identity"
        case preprocessing
        case classMap = "class_map"
        case confidenceThreshold = "confidence_threshold"
        case maskLogitThreshold = "mask_logit_threshold"
        case maximumCandidates = "maximum_candidates"
        case extractionPolicy = "extraction_policy"
        case status
        case elapsedMs = "elapsed_ms"
        case events
    }
}

public enum DeviceVisibleCardPostprocessor {
    public static let scoreThreshold: Float = 0.5
    public static let classMap = [0: "visible_card", 1: "card_pile"]

    public static func binaryMask(
        _ raw: RfdetrRawOutput,
        queryIndex: Int,
        width: Int,
        height: Int
    ) throws -> [UInt8] {
        guard queryIndex >= 0, queryIndex < raw.queryCount, width > 0, height > 0 else {
            throw DeviceVisibleCardStageError.invalidOutput
        }
        let sourceWidth = raw.maskWidth
        let sourceHeight = raw.maskHeight
        let offset = queryIndex * sourceWidth * sourceHeight
        let logits = Array(raw.maskLogits[offset..<(offset + sourceWidth * sourceHeight)])
        var result = [UInt8](repeating: 0, count: width * height)
        for y in 0..<height {
            let sourceY = (Float(y) + 0.5) * Float(sourceHeight) / Float(height) - 0.5
            let y0 = max(0, min(sourceHeight - 1, Int(floor(sourceY))))
            let y1 = min(sourceHeight - 1, y0 + 1)
            let fy = max(0, min(1, sourceY - Float(y0)))
            for x in 0..<width {
                let sourceX = (Float(x) + 0.5) * Float(sourceWidth) / Float(width) - 0.5
                let x0 = max(0, min(sourceWidth - 1, Int(floor(sourceX))))
                let x1 = min(sourceWidth - 1, x0 + 1)
                let fx = max(0, min(1, sourceX - Float(x0)))
                let top = logits[y0 * sourceWidth + x0] * (1 - fx)
                    + logits[y0 * sourceWidth + x1] * fx
                let bottom = logits[y1 * sourceWidth + x0] * (1 - fx)
                    + logits[y1 * sourceWidth + x1] * fx
                if top * (1 - fy) + bottom * fy > 0 { result[y * width + x] = 1 }
            }
        }
        return result
    }

    public static func process(
        _ raw: RfdetrRawOutput,
        imageWidth: Int,
        imageHeight: Int,
        maximumDetections: Int = 200
    ) throws -> [DeviceVisibleCardDetection] {
        try processWithCandidates(
            raw,
            imageWidth: imageWidth,
            imageHeight: imageHeight,
            maximumDetections: maximumDetections
        ).detections
    }

    public static func processWithCandidates(
        _ raw: RfdetrRawOutput,
        imageWidth: Int,
        imageHeight: Int,
        maximumDetections: Int = 200
    ) throws -> DeviceVisibleCardPostprocessingResult {
        guard imageWidth > 0, imageHeight > 0, maximumDetections >= 0 else {
            throw DeviceVisibleCardStageError.invalidOutput
        }
        var ranked: [(flatIndex: Int, query: Int, classID: Int, score: Float)] = []
        ranked.reserveCapacity(raw.queryCount * raw.classCount)
        for query in 0..<raw.queryCount {
            for classIndex in 0..<raw.classCount {
                let index = query * raw.classCount + classIndex
                let logit = raw.classLogits[index]
                let score = 1 / (1 + exp(-logit))
                ranked.append((index, query, classIndex, score))
            }
        }
        ranked.sort {
            if $0.score == $1.score { return $0.flatIndex < $1.flatIndex }
            return $0.score > $1.score
        }

        let selected = ranked.prefix(maximumDetections)
        let candidates = selected.map { item in
            DeviceVisibleCardCandidate(
                queryIndex: item.query,
                classID: item.classID,
                score: Double(item.score),
                boxXYXY: box(for: item.query, raw: raw, imageWidth: imageWidth, imageHeight: imageHeight)
            )
        }
        var detections: [DeviceVisibleCardDetection] = []
        for item in selected where item.score > scoreThreshold {
            guard let className = classMap[item.classID] else { continue }
            let mask = try binaryMask(
                raw,
                queryIndex: item.query,
                width: imageWidth,
                height: imageHeight
            )
            let polygon = try largestMaskPolygon(
                mask: mask,
                width: imageWidth,
                height: imageHeight
            )
            detections.append(DeviceVisibleCardDetection(
                classID: item.classID,
                className: className,
                score: Double(item.score),
                boxXYXY: box(for: item.query, raw: raw, imageWidth: imageWidth, imageHeight: imageHeight),
                polygon: polygon,
                imageWidth: imageWidth,
                imageHeight: imageHeight
            ))
        }
        return DeviceVisibleCardPostprocessingResult(candidates: candidates, detections: detections)
    }

    private static func box(
        for query: Int,
        raw: RfdetrRawOutput,
        imageWidth: Int,
        imageHeight: Int
    ) -> [Double] {
        let offset = query * 4
        let cx = Double(raw.boxesCXCYWH[offset])
        let cy = Double(raw.boxesCXCYWH[offset + 1])
        let width = Double(raw.boxesCXCYWH[offset + 2])
        let height = Double(raw.boxesCXCYWH[offset + 3])
        return [
            max(0, min(Double(imageWidth), (cx - width / 2) * Double(imageWidth))),
            max(0, min(Double(imageHeight), (cy - height / 2) * Double(imageHeight))),
            max(0, min(Double(imageWidth), (cx + width / 2) * Double(imageWidth))),
            max(0, min(Double(imageHeight), (cy + height / 2) * Double(imageHeight))),
        ]
    }

    private static func largestMaskPolygon(
        mask: [UInt8],
        width: Int,
        height: Int
    ) throws -> [[Int]]? {
        guard width > 0, height > 0, mask.count == width * height else {
            throw DeviceVisibleCardStageError.invalidOutput
        }
        guard mask.contains(1) else { return nil }
        var edges: [String: [(Int, Int)]] = [:]
        func add(_ start: (Int, Int), _ end: (Int, Int)) {
            edges["\(start.0),\(start.1)", default: []].append(end)
        }
        for index in mask.indices where mask[index] == 1 {
            let x = index % width
            let y = index / width
            if y == 0 || mask[index - width] == 0 { add((x, y), (x + 1, y)) }
            if x == width - 1 || mask[index + 1] == 0 { add((x + 1, y), (x + 1, y + 1)) }
            if y == height - 1 || mask[index + width] == 0 { add((x + 1, y + 1), (x, y + 1)) }
            if x == 0 || mask[index - 1] == 0 { add((x, y + 1), (x, y)) }
        }
        var best: [(Int, Int)] = []
        for first in edges.keys.sorted() where edges[first] != nil {
            let start = first.split(separator: ",").compactMap { Int($0) }
            guard start.count == 2 else { throw DeviceVisibleCardStageError.invalidOutput }
            var point = (start[0], start[1])
            var contour = [point]
            var guardCount = 0
            repeat {
                guardCount += 1
                guard guardCount <= width * height * 4,
                      var next = edges["\(point.0),\(point.1)"], !next.isEmpty else { break }
                let destination = next.removeFirst()
                if next.isEmpty { edges.removeValue(forKey: "\(point.0),\(point.1)") }
                else { edges["\(point.0),\(point.1)"] = next }
                point = destination
                if point != (start[0], start[1]) { contour.append(point) }
            } while point != (start[0], start[1])
            if abs(area(contour)) > abs(area(best)) { best = contour }
        }
        guard best.count >= 3 else { return nil }
        let simplified = best.indices.compactMap { index -> (Int, Int)? in
            let previous = best[(index + best.count - 1) % best.count]
            let current = best[index]
            let next = best[(index + 1) % best.count]
            let cross = (current.0 - previous.0) * (next.1 - current.1)
                - (current.1 - previous.1) * (next.0 - current.0)
            return cross == 0 ? nil : current
        }
        guard simplified.count >= 3 else { return nil }
        return simplified.map { [$0.0, $0.1] }
    }

    private static func area(_ points: [(Int, Int)]) -> Double {
        guard points.count >= 3 else { return 0 }
        return zip(points, points.dropFirst() + [points[0]]).reduce(0) { value, pair in
            value + Double(pair.0.0 * pair.1.1 - pair.1.0 * pair.0.1) / 2
        }
    }
}
