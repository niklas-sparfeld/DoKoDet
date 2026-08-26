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
              Self.isPermittedLocalHost(hostname),
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

    private static func isPermittedLocalHost(_ hostname: String) -> Bool {
        if hostname.lowercased().hasSuffix(".local") {
            return true
        }

        let parts = hostname.split(separator: ".")
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
    }
}
