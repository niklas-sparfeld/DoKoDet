import Foundation
import Network
import SwiftUI

@MainActor
final class BackendDiscovery: ObservableObject {
    static let serviceType = "_dokodetector._tcp"

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
    }

    private func apply(_ browserState: NWBrowser.State) {
        switch browserState {
        case .ready:
            if case .failed = state {
                state = .searching
            }
        case let .waiting(error), let .failed(error):
            state = .failed(error.localizedDescription)
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

        if case let .connected(current) = state, services.contains(current) {
            return
        }

        validationTask?.cancel()
        guard !services.isEmpty else {
            state = .searching
            return
        }

        state = .checking
        validationTask = Task { [weak self] in
            guard let self else { return }
            for service in services {
                guard !Task.isCancelled else { return }
                if await self.isReady(service) {
                    guard !Task.isCancelled else { return }
                    self.state = .connected(service)
                    return
                }
            }
            guard !Task.isCancelled else { return }
            self.state = .searching
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
                return false
            }
            let health = try JSONDecoder().decode(HealthResponse.self, from: data)
            return health.status == "ok"
        } catch {
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
}

private struct HealthResponse: Decodable {
    let status: String
}
