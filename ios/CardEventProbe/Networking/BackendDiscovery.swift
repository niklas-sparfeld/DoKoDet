import Foundation
import Network
import os
import SwiftUI

@MainActor
final class BackendDiscovery: ObservableObject {
    static let serviceType = "_dokodetector._tcp"
    private static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.dokodetector.CardEventProbe",
        category: "BackendDiscovery"
    )

    enum State: Equatable {
        case stopped
        case searching
        case checking
        case connected(BackendService)
        case failed(String)

        var title: String {
            switch self {
            case .stopped:
                return "Stopped"
            case .searching:
                return "Searching"
            case .checking:
                return "Checking"
            case .connected:
                return "Connected"
            case .failed:
                return "Unavailable"
            }
        }

        var detail: String? {
            switch self {
            case let .connected(service):
                return service.baseURL.absoluteString
            case let .failed(message):
                return message
            case .stopped, .searching, .checking:
                return nil
            }
        }
    }

    @Published private(set) var state: State = .stopped
    @Published private(set) var diagnosticMessage: String?

    private let browserQueue = DispatchQueue(label: "com.dokodetector.backend-discovery")
    private let session: URLSession
    private var browser: NWBrowser?
    private var validationTask: Task<Void, Never>?

    init(session: URLSession? = nil) {
        self.session = session ?? Self.makeSession()
    }

    func start() {
        guard browser == nil else { return }

        state = .searching
        record("Browsing for Bonjour services of type \(Self.serviceType).")
        let browser = NWBrowser(
            for: .bonjourWithTXTRecord(type: Self.serviceType, domain: nil),
            using: NWParameters.tcp
        )
        self.browser = browser

        browser.stateUpdateHandler = { [weak self] browserState in
            Task { @MainActor [weak self] in
                self?.apply(browserState)
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor [weak self] in
                self?.updateServices(from: results)
            }
        }
        browser.start(queue: browserQueue)
    }

    func stop() {
        validationTask?.cancel()
        validationTask = nil
        browser?.cancel()
        browser = nil
        state = .stopped
        record("Stopped Bonjour browsing.")
    }

    private func apply(_ browserState: NWBrowser.State) {
        Self.logger.debug("Browser state changed: \(String(describing: browserState), privacy: .public)")
        switch browserState {
        case .ready:
            if case .failed = state {
                state = .searching
            }
            record("Bonjour browser is ready.")
        case let .waiting(error), let .failed(error):
            state = .failed(error.localizedDescription)
            record("Bonjour browser failed: \(error.localizedDescription)")
        case .cancelled:
            if browser != nil {
                state = .stopped
            }
        case .setup:
            break
        @unknown default:
            break
        }
    }

    private func updateServices(from results: Set<NWBrowser.Result>) {
        let services = results.compactMap(Self.service(from:)).sorted {
            $0.name.localizedStandardCompare($1.name) == .orderedAscending
        }
        let rejectedCount = results.count - services.count
        record(
            "Bonjour returned \(results.count) service(s); \(services.count) compatible, \(rejectedCount) rejected."
        )

        if case let .connected(current) = state, services.contains(current) {
            return
        }

        validationTask?.cancel()
        guard !services.isEmpty else {
            state = .searching
            record("No compatible DokoDetector backend is advertised.")
            return
        }

        state = .checking
        validationTask = Task { [weak self] in
            guard let self else { return }
            for service in services {
                guard !Task.isCancelled else { return }
                self.record("Checking backend \(service.name) at \(service.baseURL.absoluteString).")
                if await self.isReady(service) {
                    guard !Task.isCancelled else { return }
                    self.state = .connected(service)
                    self.record("Connected to backend \(service.name) at \(service.baseURL.absoluteString).")
                    return
                }
            }
            guard !Task.isCancelled else { return }
            self.state = .searching
            self.record("No advertised backend passed the readiness check.")
        }
    }

    private func isReady(_ service: BackendService) async -> Bool {
        var request = URLRequest(
            url: service.baseURL.appendingPathComponent("health/ready")
        )
        request.timeoutInterval = 3

        do {
            let (data, response) = try await session.data(for: request)
            guard let response = response as? HTTPURLResponse,
                  response.statusCode == 200 else {
                let status = (response as? HTTPURLResponse)?.statusCode.description ?? "no HTTP response"
                record("Readiness check failed for \(service.baseURL.absoluteString): \(status).")
                return false
            }
            let health = try JSONDecoder().decode(HealthResponse.self, from: data)
            guard health.status == "ok" else {
                record("Readiness check returned status \(health.status) for \(service.baseURL.absoluteString).")
                return false
            }
            return true
        } catch {
            record("Readiness check failed for \(service.baseURL.absoluteString): \(error.localizedDescription)")
            return false
        }
    }

    private static func service(from result: NWBrowser.Result) -> BackendService? {
        guard case let .service(name, _, _, _) = result.endpoint,
              case let .bonjour(txtRecord) = result.metadata else {
            return nil
        }
        return BackendService(name: name, txtRecord: txtRecord.dictionary)
    }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForResource = 5
        return URLSession(configuration: configuration)
    }

    private func record(_ message: String) {
        diagnosticMessage = message
        Self.logger.info("\(message, privacy: .public)")
    }
}

private struct HealthResponse: Decodable {
    let status: String
}
