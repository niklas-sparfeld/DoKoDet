import CoreMedia
import Foundation

/// Operating values for the bounded evidence capture path.
public struct EvidenceCaptureConfiguration: Equatable, Sendable {
    public let targetHz: Double
    public let jpegQuality: Double
    public let historySeconds: Double
    public let targetOffsetsMs: [Int]
    public let maximumLookupDistanceMs: Int
    public let finalizationDelayMs: Int

    public init(
        targetHz: Double = 8.0,
        jpegQuality: Double = 0.85,
        historySeconds: Double = 3.0,
        targetOffsetsMs: [Int] = [-800, -400, -100, 150, 400, 700],
        maximumLookupDistanceMs: Int = 175,
        finalizationDelayMs: Int = 900
    ) {
        precondition(targetHz.isFinite && targetHz > 0.0, "evidence target rate must be positive")
        precondition(jpegQuality.isFinite && (0.0...1.0).contains(jpegQuality), "JPEG quality must be in [0, 1]")
        precondition(historySeconds.isFinite && historySeconds > 0.0, "evidence history must be positive")
        precondition(!targetOffsetsMs.isEmpty, "evidence target offsets must not be empty")
        precondition(Set(targetOffsetsMs).count == targetOffsetsMs.count, "evidence target offsets must be unique")
        precondition(maximumLookupDistanceMs >= 0, "maximum lookup distance must not be negative")
        precondition(finalizationDelayMs >= 0, "finalization delay must not be negative")

        self.targetHz = targetHz
        self.jpegQuality = jpegQuality
        self.historySeconds = historySeconds
        self.targetOffsetsMs = targetOffsetsMs
        self.maximumLookupDistanceMs = maximumLookupDistanceMs
        self.finalizationDelayMs = finalizationDelayMs
    }

    public var sampleInterval: CMTime {
        CMTime(seconds: 1.0 / targetHz, preferredTimescale: 600)
    }

    public var historyDuration: CMTime {
        CMTime(seconds: historySeconds, preferredTimescale: 600)
    }

    public var maximumLookupDistance: CMTime {
        CMTime(value: Int64(maximumLookupDistanceMs), timescale: 1_000)
    }

    public var maximumFrameCount: Int {
        max(1, Int(ceil(historySeconds * targetHz)) + 1)
    }
}
