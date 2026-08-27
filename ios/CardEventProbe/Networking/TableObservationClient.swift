import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public struct EvidenceObservationSource: Codable, Equatable, Sendable {
    public let packageID: String
    public let snippetPartName: String?

    private enum CodingKeys: String, CodingKey {
        case packageID = "package_id"
        case snippetPartName = "snippet_part_name"
    }
}

public struct EvidenceObservationSession: Codable, Equatable, Sendable {
    public let sessionID: String
    public let eventSequence: Int

    private enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case eventSequence = "event_sequence"
    }
}

public struct EvidenceIdentityCandidate: Codable, Equatable, Sendable {
    public let card: String
    public let probability: Double
}

public struct EvidenceObservedCard: Codable, Equatable, Sendable {
    public let observedCardID: String
    public let identityCandidates: [EvidenceIdentityCandidate]

    private enum CodingKeys: String, CodingKey {
        case observedCardID = "observed_card_id"
        case identityCandidates = "identity_candidates"
    }
}

public struct EvidenceAnalyzerMetadata: Codable, Equatable, Sendable {
    public let name: String
    public let version: String
}

public struct EvidenceTableObservation: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let observationID: String
    public let source: EvidenceObservationSource
    public let session: EvidenceObservationSession
    public let observedAtMS: Int
    public let status: String
    public let capabilities: [String]
    public let cards: [EvidenceObservedCard]
    public let calibration: String
    public let analyzer: EvidenceAnalyzerMetadata

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case observationID = "observation_id"
        case source
        case session
        case observedAtMS = "observed_at_ms"
        case status
        case capabilities
        case cards
        case calibration
        case analyzer
    }
}

public enum TableObservationClientError: LocalizedError, Equatable, Sendable {
    case nonSuccessResponse(Int, Data)
    case packageIDMismatch(expected: UUID, received: String)
    case invalidResponse
    case invalidResponseBody(String)

    public var errorDescription: String? {
        switch self {
        case let .nonSuccessResponse(status, _):
            return "The table-observation request failed with HTTP status \(status)."
        case let .packageIDMismatch(expected, received):
            return "The table observation belongs to package \(received), expected \(expected)."
        case .invalidResponse:
            return "The table-observation request returned an invalid response."
        case let .invalidResponseBody(message):
            return "The table-observation response is invalid: \(message)"
        }
    }
}

/// Reads table observations without applying game rules.
public final class TableObservationClient: @unchecked Sendable {
    private let session: URLSession

    public init(session: URLSession? = nil) {
        self.session = session ?? Self.makeSession()
    }

    public func observations(
        for packageID: UUID,
        using configuration: BackendConfiguration
    ) async throws -> [EvidenceTableObservation] {
        let (data, response) = try await session.data(
            for: request(configuration.tableObservationsURL(for: packageID))
        )
        try Self.validate(response: response, data: data)
        do {
            let observations = try Self.decoder.decode([EvidenceTableObservation].self, from: data)
            guard observations.allSatisfy({ $0.source.packageID == packageID.uuidString.lowercased() }) else {
                let received = observations.first(where: {
                    $0.source.packageID != packageID.uuidString.lowercased()
                })?.source.packageID ?? "unknown"
                throw TableObservationClientError.packageIDMismatch(
                    expected: packageID,
                    received: received
                )
            }
            return observations
        } catch let error as TableObservationClientError {
            throw error
        } catch {
            throw TableObservationClientError.invalidResponseBody(String(describing: error))
        }
    }

    public func observation(
        for observationID: String,
        using configuration: BackendConfiguration
    ) async throws -> EvidenceTableObservation {
        let (data, response) = try await session.data(
            for: request(configuration.tableObservationURL(for: observationID))
        )
        try Self.validate(response: response, data: data)
        do {
            return try Self.decoder.decode(EvidenceTableObservation.self, from: data)
        } catch {
            throw TableObservationClientError.invalidResponseBody(String(describing: error))
        }
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
            throw TableObservationClientError.invalidResponse
        }
        guard (200..<300).contains(response.statusCode) else {
            throw TableObservationClientError.nonSuccessResponse(response.statusCode, data)
        }
    }

    private static let decoder: JSONDecoder = JSONDecoder()

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 2
        configuration.timeoutIntervalForResource = 5
        return URLSession(configuration: configuration)
    }
}
