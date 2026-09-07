# iOS capture module boundaries

## Plan status

- **Summary:** Separate clear iOS evidence contract, validation, coordination, and app-state
  responsibilities without changing capture or upload behavior.
- **Status:** To Specify
- **Depends on:** 0053 discovery complete
- **Outcome:** A capture, evidence, upload, or analysis-state change uses a small source and test
  boundary that works in both Swift Package and Xcode builds.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Not started — one `gpt-5.6-terra` agent maps target membership and concurrency boundaries
  and specifies Luna-sized delivery milestones.

## Problem and candidate paths

The iOS app has 18,236 Swift source lines and six files over 1,000 lines. `EvidencePackage.swift`
contains 2,089 lines and `AppState.swift` contains 1,792. Candidate paths include these files,
`Core/RepositoryIntake.swift`, recording coordinators, networking collaborators, `Package.swift`,
the Xcode project, and their tests.

## Exclusions and overlap

Do not change evidence bytes, backend contracts, durable retry and recovery behavior, capture
timing, model inference, the checked-in model bundle, or the device showcase. Epic 0055 owns the
iOS documentation first hop. Preserve source and fixture data.

## M0 specification questions

- Which types belong to the Swift Package target, the Xcode app target, or both?
- Which evidence types, validation, encoding, assembly, coordination, and state seams are stable?
- Which actor, main-thread, persistence, and lifecycle constraints prevent a safe split?
- Which files change together for common capture and upload tasks?
- Which Swift Package tests, Xcode build, and shared fixture tests cover each milestone?

M0 must replace this outline with small delivery milestones. Each delivery milestone must fit one
`gpt-5.6-luna` phase and name focused Swift and Xcode verification. Close this epic without delivery
when the target graph or concurrency constraints do not support a safe context reduction.
