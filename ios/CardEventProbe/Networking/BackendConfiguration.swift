import Foundation

public enum BackendConfigurationError: LocalizedError, Equatable {
    case invalidBaseURL(URL)
    case invalidPort(Int)

    public var errorDescription: String? {
        switch self {
        case let .invalidBaseURL(url):
            return "The backend base URL is invalid: \(url.absoluteString)."
        case let .invalidPort(port):
            return "The backend port is invalid: \(port)."
        }
    }
}

/// The local HTTP endpoint used by the evidence and result clients.
public struct BackendConfiguration: Equatable, Sendable {
    public let baseURL: URL

    public init(baseURL: URL) throws {
        guard Self.isValidBaseURL(baseURL) else {
            throw BackendConfigurationError.invalidBaseURL(baseURL)
        }
        self.baseURL = baseURL
    }

    /// The address used when the simulator talks to a backend on the development Mac.
    public static func simulatorLocalhost(port: Int = 8000) throws -> Self {
        guard (1...65_535).contains(port) else {
            throw BackendConfigurationError.invalidPort(port)
        }
        return try Self(baseURL: URL(string: "http://127.0.0.1:\(port)")!)
    }

    public func evidencePackageURL(for packageID: UUID) -> URL {
        baseURL
            .appendingPathComponent("v1", isDirectory: true)
            .appendingPathComponent("evidence-packages", isDirectory: true)
            .appendingPathComponent(packageID.uuidString.lowercased())
    }

    public func visionResultsURL(for packageID: UUID) -> URL {
        evidencePackageURL(for: packageID)
            .appendingPathComponent("vision-results", isDirectory: true)
    }

    public func visionResultURL(for resultID: UUID) -> URL {
        baseURL
            .appendingPathComponent("v1", isDirectory: true)
            .appendingPathComponent("vision-results", isDirectory: true)
            .appendingPathComponent(resultID.uuidString.lowercased())
    }

    public func trainingRecordingURL(for recordingID: String) -> URL {
        baseURL
            .appendingPathComponent("v1", isDirectory: true)
            .appendingPathComponent("training-recordings", isDirectory: true)
            .appendingPathComponent(recordingID)
    }

    private static func isValidBaseURL(_ url: URL) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.scheme == "http" || components.scheme == "https",
              let hostname = components.host,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil,
              components.path.isEmpty || components.path == "/" else {
            return false
        }

        if components.scheme == "https" {
            return true
        }
        return isPermittedLocalHost(hostname)
    }

    private static func isPermittedLocalHost(_ hostname: String) -> Bool {
        let normalized = hostname.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        if normalized == "localhost"
            || normalized == "ip6-localhost"
            || normalized == "::1"
            || normalized.hasSuffix(".local") {
            return true
        }

        let parts = normalized.split(separator: ".")
        guard parts.count == 4,
              let first = UInt8(parts[0]),
              let second = UInt8(parts[1]),
              parts.dropFirst(2).allSatisfy({ UInt8($0) != nil }) else {
            return false
        }

        return first == 10
            || first == 172 && (16...31).contains(second)
            || first == 192 && second == 168
            || first == 169 && second == 254
            || first == 127
    }
}
