import Foundation

struct CameraSourceRateStatus: Equatable, Sendable {
    static let requestedFrameRate = 30.0

    let requestedFrameRate: Double
    let selectedFrameRate: Double
    let isFallback: Bool

    var summary: String {
        let selected = String(format: "%.2f fps", selectedFrameRate)
        if isFallback {
            return "\(selected) (fallback; requested \(String(format: "%.0f", requestedFrameRate)) fps)"
        }
        return "\(selected) (selected)"
    }

    static func select(
        requestedFrameRate: Double = Self.requestedFrameRate,
        supportedMaximumFrameRate: Double
    ) -> CameraSourceRateStatus? {
        guard requestedFrameRate.isFinite,
              requestedFrameRate > 0.0,
              supportedMaximumFrameRate.isFinite,
              supportedMaximumFrameRate > 0.0 else {
            return nil
        }
        let selectedFrameRate = min(requestedFrameRate, supportedMaximumFrameRate)
        return CameraSourceRateStatus(
            requestedFrameRate: requestedFrameRate,
            selectedFrameRate: selectedFrameRate,
            isFallback: selectedFrameRate < requestedFrameRate
        )
    }
}
