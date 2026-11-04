# 0106 M1: Live capture and event retention

Date: 2026-11-04

M1 is complete. The app records the frozen 0103 M3 CardEventNet package during camera capture and
retains its causal event proposals with the recording. The run records the model package digest,
checkpoint digest, preprocessing, and decoder settings. Recording start resets model history and
uses threshold `0.4271905720`, peak confirmation `0.125 s`, and event gap `0.625 s`.

The Xcode build phase copies the package to an ignored local input and checks its directory digest
before it compiles the model. The source package stays out of Git. The run retains a hidden
`.device/capture-timeline.json` sidecar. It records the first accepted movie frame as time zero,
exact rational source and movie times for each written frame, orientation, frame and inference
counts, up to 100 inference errors, and interruption status. The repository intake validator skips
this local diagnostic sidecar. Event proposals remain in the saved proposal run.

The app can record without a connected backend. Stop drains inference and flushes a pending event.
When the app moves out of the active state during recording, it saves the partial capture and marks
the timeline as interrupted. A reopened bundle retains the same event proposal values.

## Verification

- `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test`: 117 tests passed.
- `xcodebuild ... build-for-testing` for the generic iOS target: passed.
- The simulator could not run because the installed CoreSimulator version is older than the
  installed Xcode requires. The app and test targets compiled for iOS.
- The model preparation script verified package digest
  `b3f41726c2029e6047bd9ea04ab742fc55868e815f2601410dc266a8ca736bfd`.

This result does not include an iPhone capture or a model-quality claim. M6 owns the device trial.
