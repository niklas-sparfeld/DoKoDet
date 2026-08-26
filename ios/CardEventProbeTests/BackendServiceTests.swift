import XCTest
@testable import CardEventProbeCore

final class BackendServiceTests: XCTestCase {
    func testAcceptsTheSupportedLocalBackend() {
        let service = BackendService(
            name: "Development Mac",
            txtRecord: [
                "api": "v1",
                "url": "http://development-mac.local:8000",
            ]
        )

        XCTAssertEqual(service?.name, "Development Mac")
        XCTAssertEqual(service?.baseURL.absoluteString, "http://development-mac.local:8000")
    }

    func testRejectsAnUnsupportedAPIVersion() {
        XCTAssertNil(
            BackendService(
                name: "Development Mac",
                txtRecord: [
                    "api": "v2",
                    "url": "http://development-mac.local:8000",
                ]
            )
        )
    }

    func testRejectsANonLocalEndpoint() {
        XCTAssertNil(
            BackendService(
                name: "Unexpected server",
                txtRecord: [
                    "api": "v1",
                    "url": "https://example.com:8000",
                ]
            )
        )
    }

    func testAcceptsAPrivateIPAddressEndpoint() {
        let service = BackendService(
            name: "Development Mac",
            txtRecord: [
                "api": "v1",
                "url": "http://192.168.1.42:8000",
            ]
        )

        XCTAssertEqual(service?.baseURL.absoluteString, "http://192.168.1.42:8000")
    }

    func testRejectsAPublicIPAddressEndpoint() {
        XCTAssertNil(
            BackendService(
                name: "Unexpected server",
                txtRecord: [
                    "api": "v1",
                    "url": "http://8.8.8.8:8000",
                ]
            )
        )
    }
}
