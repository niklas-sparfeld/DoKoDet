import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum EvidenceJSONValue: Codable, Equatable, Sendable {
    case null
    case boolean(Bool)
    case number(Double)
    case string(String)
    case array([EvidenceJSONValue])
    case object([String: EvidenceJSONValue])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .boolean(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([EvidenceJSONValue].self) {
            self = .array(value)
        } else if let value = try? container.decode([String: EvidenceJSONValue].self) {
            self = .object(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "The observation contains an unsupported JSON value."
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null:
            try container.encodeNil()
        case let .boolean(value):
            try container.encode(value)
        case let .number(value):
            try container.encode(value)
        case let .string(value):
            try container.encode(value)
        case let .array(value):
            try container.encode(value)
        case let .object(value):
            try container.encode(value)
        }
    }
}

public struct EvidenceVisionSession: Codable, Equatable, Sendable {
    public let sessionID: UUID
    public let eventSequence: Int

    private enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case eventSequence = "event_sequence"
    }
}

public struct EvidenceVisionCandidate: Codable, Equatable, Sendable {
    public let card: String
    public let probability: Double
}

public struct EvidenceVisionDetector: Codable, Equatable, Sendable {
    public let name: String
    public let version: String
}

public struct EvidenceVisionDiagnostics: Codable, Equatable, Sendable {
    public let framesReceived: Int
    public let framesDecoded: Int

    private enum CodingKeys: String, CodingKey {
        case framesReceived = "frames_received"
        case framesDecoded = "frames_decoded"
    }
}

public struct EvidenceVisionResult: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let resultID: UUID
    public let packageID: UUID
    public let session: EvidenceVisionSession
    public let status: String
    public let selectedCard: String?
    public let candidates: [EvidenceVisionCandidate]
    public let calibration: String
    public let detector: EvidenceVisionDetector
    public let diagnostics: EvidenceVisionDiagnostics
    public let observations: [[String: EvidenceJSONValue]]
    public let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case resultID = "result_id"
        case packageID = "package_id"
        case session
        case status
        case selectedCard = "selected_card"
        case candidates
        case calibration
        case detector
        case diagnostics
        case observations
        case createdAt = "created_at"
    }
}

public enum EvidenceResultClientError: LocalizedError, Equatable, Sendable {
    case nonSuccessResponse(Int, Data)
    case packageIDMismatch(expected: UUID, received: UUID)
    case invalidResponse
    case invalidResponseBody(String)

    public var errorDescription: String? {
        switch self {
        case let .nonSuccessResponse(status, _):
            return "The vision result request failed with HTTP status \(status)."
        case let .packageIDMismatch(expected, received):
            return "The vision result belongs to package \(received), expected \(expected)."
        case .invalidResponse:
            return "The vision result request returned an invalid response."
        case let .invalidResponseBody(message):
            return "The vision result response is invalid: \(message)"
        }
    }
}

/// Reads developer-facing detector results without applying game rules.
public final class EvidenceResultClient: @unchecked Sendable {
    private let session: URLSession

    public init(session: URLSession? = nil) {
        self.session = session ?? Self.makeSession()
    }

    public func results(
        for packageID: UUID,
        using configuration: BackendConfiguration
    ) async throws -> [EvidenceVisionResult] {
        let (data, response) = try await session.data(for: request(configuration.visionResultsURL(for: packageID)))
        try Self.validate(response: response, data: data)
        do {
            let results = try Self.decoder.decode([EvidenceVisionResult].self, from: data)
            guard results.allSatisfy({ $0.packageID == packageID }) else {
                let received = results.first(where: { $0.packageID != packageID })?.packageID ?? packageID
                throw EvidenceResultClientError.packageIDMismatch(expected: packageID, received: received)
            }
            return results
        } catch let error as EvidenceResultClientError {
            throw error
        } catch {
            throw EvidenceResultClientError.invalidResponseBody(String(describing: error))
        }
    }

    public func result(
        for resultID: UUID,
        using configuration: BackendConfiguration
    ) async throws -> EvidenceVisionResult {
        let (data, response) = try await session.data(for: request(configuration.visionResultURL(for: resultID)))
        try Self.validate(response: response, data: data)
        do {
            return try Self.decoder.decode(EvidenceVisionResult.self, from: data)
        } catch {
            throw EvidenceResultClientError.invalidResponseBody(String(describing: error))
        }
    }

    public func results(
        for packageID: UUID,
        from baseURL: URL
    ) async throws -> [EvidenceVisionResult] {
        try await results(for: packageID, using: BackendConfiguration(baseURL: baseURL))
    }

    public func result(
        for resultID: UUID,
        from baseURL: URL
    ) async throws -> EvidenceVisionResult {
        try await result(for: resultID, using: BackendConfiguration(baseURL: baseURL))
    }

    private func request(_ url: URL) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.cachePolicy = .reloadIgnoringLocalCacheData
        return request
    }

    private static func validate(response: URLResponse, data: Data) throws {
        guard let response = response as? HTTPURLResponse else {
            throw EvidenceResultClientError.invalidResponse
        }
        guard (200..<300).contains(response.statusCode) else {
            throw EvidenceResultClientError.nonSuccessResponse(response.statusCode, data)
        }
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            let formatter = ISO8601DateFormatter()
            formatter.timeZone = TimeZone(secondsFromGMT: 0)
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: value) {
                return date
            }
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: value) else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "created_at must be an RFC 3339 timestamp."
                )
            }
            return date
        }
        return decoder
    }()

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForResource = 30
        return URLSession(configuration: configuration)
    }
}
