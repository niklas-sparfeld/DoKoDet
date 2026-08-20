// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "CardEventProbe",
    platforms: [
        .iOS(.v18),
        .macOS(.v15),
    ],
    products: [
        .library(
            name: "CardEventProbeCore",
            targets: ["CardEventProbeCore"]
        ),
    ],
    targets: [
        .target(
            name: "CardEventProbeCore",
            path: "CardEventProbe/Core"
        ),
        .testTarget(
            name: "CardEventProbeCoreTests",
            dependencies: ["CardEventProbeCore"],
            path: "CardEventProbeTests"
        ),
    ]
)
