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
        .executable(
            name: "CardEventProbeLocalPipeline",
            targets: ["CardEventProbeLocalPipeline"]
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
                "Networking/BackendDiscovery.swift",
            ],
            sources: [
                "Core/DetectionEvent.swift",
                "Core/CameraSourceRate.swift",
                "Core/CausalEventDecoder.swift",
                "Core/EvidenceCaptureConfiguration.swift",
                "Core/EvidenceFrameRing.swift",
                "Core/CaptureSession.swift",
                "Core/EvidencePackage.swift",
                "Core/EvidenceVideoSnippet.swift",
                "Core/EvidenceLiveVideoSnippet.swift",
                "Core/RecordingProfile.swift",
                "Core/RecordingWorkspace.swift",
                "Core/RecordingWorkspacePresentation.swift",
                "Core/EvidencePackageCoordinator.swift",
                "Networking/EvidenceMultipartUpload.swift",
                "Core/InferenceSamplingPolicy.swift",
                "Core/ModelPrediction.swift",
                "Core/ModelPreprocessing.swift",
                "Core/SessionLog.swift",
                "Core/TrainingRecording.swift",
                "Core/RepositoryIntake.swift",
                "Core/RoundRecording.swift",
                "Core/TrainingRecordingCoordinator.swift",
                "Core/TrainingRecordingQueue.swift",
                "Inference/CardEventTensorBuilder.swift",
                "Inference/VideoFrame.swift",
                "Networking/BackendService.swift",
                "Networking/BackendConfiguration.swift",
                "Networking/TableObservationClient.swift",
                "Networking/EvidenceUploadQueue.swift",
                "Networking/TrainingRecordingUpload.swift",
                "Networking/RoundAnalysis.swift",
            ]
        ),
        .executableTarget(
            name: "CardEventProbeLocalPipeline",
            dependencies: ["CardEventProbeCore"],
            path: "Integration"
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
