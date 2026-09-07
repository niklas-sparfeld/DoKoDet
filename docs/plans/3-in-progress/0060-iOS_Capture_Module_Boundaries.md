# iOS capture module boundaries

## Plan status

- **Summary:** Split the iOS evidence package contract, repository-intake validation, and recording
  app-state workflows into focused source boundaries without changing behavior.
- **Status:** In Progress
- **Depends on:** 0053 discovery complete
- **Outcome:** A capture, evidence, upload, or analysis-state change uses a focused source and test
  boundary that compiles in both the Swift Package and Xcode app.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Complete — mapped package and app membership, stable seams, concurrency limits, and
  focused verification.
- **M1:** Complete — split evidence-package contract, assembly, and durable-store ownership with
  unchanged Swift Package and Xcode target membership.
- **M2:** Complete — split repository-intake document models from directory and contract validation with unchanged fixture behavior and target membership.
- **M3:** Complete — moved recording lifecycle, durable training upload, evidence upload, and round-analysis coordination into injected main-actor workflow owners while preserving the `AppState` UI facade.

## Problem and target membership

The iOS app has 18,236 Swift source lines and six files over 1,000 lines. `EvidencePackage.swift`
contains 2,089 lines, `AppState.swift` contains 1,792, and `RepositoryIntake.swift` contains
1,486. One evidence package change can require reading manifest Codable rules, package assembly,
durable queue storage, upload preparation, and app presentation state.

The Swift Package target explicitly lists all reusable Core and selected Networking sources. The
Xcode target builds those sources plus `App`, camera, Core ML inference, diagnostics, replay, and
SwiftUI files. A moved reusable source must be listed in `Package.swift` and added to the Xcode
Sources phase. App-only sources must not enter the package target.

## Stable seams and constraints

| Area | Current owner and seam | Delivery constraint |
| --- | --- | --- |
| Evidence package contract | `EvidencePackage.swift` defines manifest metadata, Codable rules, package value types, and errors. `EvidenceManifestContractTests` decodes fixture manifests. | Preserve JSON field names, encoding order where tested, validation failures, evidence bytes, and fixture compatibility. |
| Evidence assembly and storage | `EvidencePackageAssembler` creates packages; `EvidencePackageStore` persists, recovers, moves, and requeues them. `EvidencePackageCoordinator` and upload code consume these types. | Keep queue states, atomic persistence, recovery, callbacks, and package identifiers unchanged. Do not move coordination into the contract module. |
| Repository intake | `RepositoryIntake.swift` combines repository document Codable models with `RepositoryIntakeContract.validate`. Shared fixture tests decode pending-video and evidence-package bundles. | Keep repository file contracts and fixture decoding unchanged. Model types must not import app, camera, UI, or networking code. |
| App workflow | `AppState` is `@MainActor` and supplies the SwiftUI facade. It owns capture start/stop, durable upload tasks, recovery, round-analysis submission and polling, and published presentation values. | Keep UI publication and state mutations on the main actor. Keep background queue and network work in their existing actors or tasks. Preserve recovery order, cancellation, and idempotent submission guards. |

`EvidencePackageCoordinator` is intentionally an `@unchecked Sendable` class with a private serial
dispatch queue. `EvidenceUploadQueue` and `TrainingRecordingUploadQueue` are actors. M3 must not
turn either model into an unchecked cross-actor app-state dependency. The capture session, model
runner, camera delegate, Core ML model bundle, and device showcase stay Xcode-app-only.

## Delivery milestones

### M1 — Evidence package source boundaries

Split `Core/EvidencePackage.swift` by its existing dependency direction:

- Place manifest metadata, manifest Codable validation, package value types, and package errors in
  one contract source.
- Place `EvidencePackageAssembler` and frame or video package construction in one assembly source
  that depends on the contract source.
- Place queue states, durable filesystem persistence, recovery, acknowledgement, and requeue
  behavior in one store source that depends on the contract source.
- Keep `EvidencePackageCoordinator` as the capture-time coordinator. Update only its imports and
  source references that the split requires.
- Add each new Core source to the Swift Package target and the Xcode Sources phase; remove the
  retired monolithic source reference.

Verify with `swift test` in `ios/`, focused evidence package, video snippet, upload-queue, and
round-recording tests, then the `CardEventProbe` Xcode Debug build for an iOS Simulator. Compare
the existing evidence manifest fixtures before and after the move.

### M2 — Repository-intake contract boundary

Split `Core/RepositoryIntake.swift` into repository document models and a validation source:

- Keep all `Repository*` Codable data types and their custom decoding in a package-owned document
  source.
- Put `RepositoryIntakeContract`, its validation helpers, and contract errors in a validator source
  that depends only on the document source and Foundation.
- Do not change validation rules, JSON names, accepted source records, task enrollments, pending
  videos, or evidence-package lineage.
- Update both target memberships. Keep model and validator sources free of app, UI, camera, and
  backend-client imports.

Verify with `swift test` in `ios/`, especially `RepositoryIntakeContractTests` and
`RepositoryBundleStorageTests`, then the `CardEventProbe` Xcode Debug build for an iOS Simulator.

### M3 — App workflow coordination boundary

Extract app-only recording workflow coordination from `AppState` into focused `@MainActor` types:

- A recording workflow owns recording start and stop, persisted start snapshots, capture-session
  markers, training-recording recovery, and its coordinator lifecycle.
- An evidence and analysis workflow owns evidence upload attempts, retry, evidence-package
  acknowledgement, round-analysis submission, polling, and recovery.
- `AppState` stays the SwiftUI-facing facade. It owns view presentation values and delegates
  commands to the workflows. Keep the existing public UI behavior, errors, progress, and command
  availability.
- Inject existing stores, clients, queues, and callbacks. Do not make the workflows global
  singletons or change their persistence directories.
- Add focused app workflow tests for recovery, retry, acknowledgement before analysis submission,
  cancellation, and duplicate-submission prevention. Existing core tests remain the evidence-byte
  and durable-storage proof.

Add the app-only sources only to the Xcode target. Verify focused Swift Package tests, the affected
Xcode test target, and the `CardEventProbe` Xcode Debug build for an iOS Simulator.

## Exclusions and overlap

Do not change evidence bytes, backend contracts, durable retry and recovery behavior, capture
timing, model inference, the checked-in model bundle, or the device showcase. Epic 0055 owns the
iOS documentation first hop. Preserve source and fixture data. Do not use this cleanup to change
the evidence package format or remove compatibility code.

## Completion criteria

- `EvidencePackage.swift`, `RepositoryIntake.swift`, and `AppState.swift` no longer each combine
  the responsibilities described in this epic.
- Each reusable Core source has matching Swift Package and Xcode target membership.
- Core contract, persistence, and queue tests pass; app workflow tests cover the specified
  lifecycle guards; the iOS Simulator Debug build succeeds.
- Capture, upload, retry, recovery, and round-analysis behavior remains unchanged.
