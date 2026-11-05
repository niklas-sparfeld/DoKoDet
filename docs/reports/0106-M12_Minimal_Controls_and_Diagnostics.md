# Epic 0106 M12: Minimal controls and diagnostics

## Result

M12 adds a local processing action to the recording details view. The action runs visible-card
detection, table calibration, proposed card-scene fitting, visual identity, and round reconstruction
in order. It shows the current stage, the final status, and the saved error detail. A failed
required stage stops the run and keeps its result and failure log.

The processing action reads the finalized recording manifest for its recording and session IDs. It
does not require a backend. A local analysis pauses queued recording uploads while it writes to the
recording. The app asks the operator to wait if an upload is already active.

Each round-analysis run saves its request, frozen table observations, result or failure, and a
timestamped log. The export action creates one ZIP file. The archive includes those files, the
recording log, and the JSON results for visible-card detection, calibration, proposed scenes, and
visual identity when available. It excludes the source movie and image and crop files. Those files
remain in the local recording bundle.

The app runs a recording once. It keeps existing stage outputs and asks the operator to start a new
recording for another run. This avoids replacing saved stage results.

The details view shows the size of saved round-analysis diagnostics against the 100 MiB limit. It
does not delete runs automatically. The operator can explicitly delete all saved round analyses.
This action keeps the recording movie and other stage files.
Cleanup frees round-analysis diagnostic storage only. It does not reset the saved stage outputs.

The archive does not include M7 calibration refinement. The workflow has no eligible reviewed
anchors for that immutable preview stage. It also does not include the source movie, so an exported
archive alone cannot replay video inference.

## Verification

- Seven focused round-reconstruction tests passed. They cover a complete fixture, empty and
  impossible card evidence, missing session and observation input, retained failures, reload, and
  diagnostic ZIP creation.
- All 162 iOS package tests passed with zero skips, including frozen RF-DETR reference checks.
- The iPhone 18 Pro Simulator build passed with Xcode 27.2.
- Swift format lint passed for the new post-capture pipeline, round-reconstruction changes, and
  focused tests.
- `git diff --check` and Xcode project plist validation passed.

This result does not establish a successful real-device run or model-quality claim. M13 remains
responsible for the bounded iPhone trial and same-input comparison with the 0105 local workflow.
