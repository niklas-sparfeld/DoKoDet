import Foundation

struct BackendService: Equatable, Sendable {
    static let supportedAPIVersion = "v1"

    let name: String
    let baseURL: URL

    init?(name: String, txtRecord: [String: String]) {
        guard txtRecord["api"] == Self.supportedAPIVersion,
              let urlValue = txtRecord["url"],
              let components = URLComponents(string: urlValue),
              components.scheme == "http",
              let hostname = components.host,
              hostname.lowercased().hasSuffix(".local"),
              components.port != nil,
              components.user == nil,
              components.password == nil,
              components.query == nil,
              components.fragment == nil,
              components.path.isEmpty || components.path == "/",
              let baseURL = components.url else {
            return nil
        }

        self.name = name
        self.baseURL = baseURL
    }
}
