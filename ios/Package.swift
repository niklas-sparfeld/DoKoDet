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
            path: "CardEventProbe",
            exclude: [
                "App",
                "Camera",
                "Diagnostics",
                "UI",
                "Replay",
                "Info.plist",
                "CardEventNetTransitionV2.mlpackage",
                "Inference/CardEventModelRunner.swift",
                "Inference/CoreMLCardEventModelRunner.swift",
                "Inference/FrameInferenceCoordinator.swift",
                "Inference/ModelContract.swift",
            ],
            sources: [
                "Core/DetectionEvent.swift",
                "Core/CausalEventDecoder.swift",
                "Core/InferenceSamplingPolicy.swift",
                "Core/ModelPrediction.swift",
                "Core/ModelPreprocessing.swift",
                "Core/SessionLog.swift",
                "Inference/CardEventTensorBuilder.swift",
                "Inference/VideoFrame.swift",
            ]
        ),
        .testTarget(
            name: "CardEventProbeCoreTests",
            dependencies: ["CardEventProbeCore"],
            path: "CardEventProbeTests",
            resources: [
                .copy("Fixtures"),
            ]
        ),
    ]
)
