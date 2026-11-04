import CoreMedia
import Foundation

public struct DeviceMediaTime: Codable, Equatable, Sendable {
    public let value: Int64
    public let timescale: Int32
    public let epoch: Int64

    public init(_ time: CMTime) throws {
        guard time.isValid, time.isNumeric, time.timescale > 0 else {
            throw DeviceCaptureTimelineError.invalidTime
        }
        value = time.value
        timescale = time.timescale
        epoch = time.epoch
    }

    public var cmTime: CMTime {
        CMTime(value: value, timescale: timescale, flags: .valid, epoch: epoch)
    }
}

public struct DeviceCaptureFrameTime: Codable, Equatable, Sendable {
    public let frameIndex: Int
    public let sourceTime: DeviceMediaTime
    public let movieTime: DeviceMediaTime
    public let orientation: String

    private enum CodingKeys: String, CodingKey {
        case frameIndex = "frame_index"
        case sourceTime = "source_time"
        case movieTime = "movie_time"
        case orientation
    }
}

public struct DeviceCaptureTimeline: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let recordingID: String
    public let sourceTimeZero: DeviceMediaTime
    public let frames: [DeviceCaptureFrameTime]
    public let issues: [DeviceCaptureIssue]
    public let interrupted: Bool
    public let receivedFrameCount: Int
    public let writtenFrameCount: Int
    public let droppedFrameCount: Int
    public let sampledFrameCount: Int
    public let busyFrameDropCount: Int
    public let predictionSampleCount: Int
    public let eventProposalCount: Int

    public init(
        recordingID: String,
        sourceTimeZero: DeviceMediaTime,
        frames: [DeviceCaptureFrameTime],
        issues: [DeviceCaptureIssue] = [],
        interrupted: Bool = false,
        metrics: TrainingRecordingMetrics = TrainingRecordingMetrics(),
        sampledFrameCount: Int = 0,
        busyFrameDropCount: Int = 0
    ) {
        schemaVersion = "doko-device-capture-timeline/v1"
        self.recordingID = recordingID
        self.sourceTimeZero = sourceTimeZero
        self.frames = frames
        self.issues = issues
        self.interrupted = interrupted
        receivedFrameCount = metrics.receivedFrameCount
        writtenFrameCount = metrics.writtenFrameCount
        droppedFrameCount = metrics.droppedFrameCount
        predictionSampleCount = metrics.predictionSampleCount
        eventProposalCount = metrics.eventProposalCount
        self.sampledFrameCount = sampledFrameCount
        self.busyFrameDropCount = busyFrameDropCount
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case recordingID = "recording_id"
        case sourceTimeZero = "source_time_zero"
        case frames
        case issues
        case interrupted
        case receivedFrameCount = "received_frame_count"
        case writtenFrameCount = "written_frame_count"
        case droppedFrameCount = "dropped_frame_count"
        case sampledFrameCount = "sampled_frame_count"
        case busyFrameDropCount = "busy_frame_drop_count"
        case predictionSampleCount = "prediction_sample_count"
        case eventProposalCount = "event_proposal_count"
    }

    public static func load(from bundleURL: URL) throws -> DeviceCaptureTimeline {
        let url = bundleURL.appendingPathComponent(".device/capture-timeline.json")
        return try JSONDecoder().decode(DeviceCaptureTimeline.self, from: Data(contentsOf: url))
    }
}

public struct DeviceCaptureIssue: Codable, Equatable, Sendable {
    public let stage: String
    public let sourceTime: DeviceMediaTime?
    public let message: String

    public init(stage: String, sourceTime: DeviceMediaTime?, message: String) {
        self.stage = stage
        self.sourceTime = sourceTime
        self.message = message
    }

    private enum CodingKeys: String, CodingKey {
        case stage
        case sourceTime = "source_time"
        case message
    }
}

public enum DeviceCaptureTimelineError: Error {
    case invalidTime
}
