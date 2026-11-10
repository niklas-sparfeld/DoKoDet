# 0120: source-authority list progress

Date: 2026-11-10. Baseline: `7369003f`. This is partial progress toward the first
production list improvement. The original fast-open outcome is not met.

The list API returns package and analysis counts and at most one newest analysis summary.
The existing recording detail API retains complete package IDs and analysis summaries.
The web list renders the same recording and stage fields. The backend reads analyses once
for the list and groups them by recording. It still uses all analysis states to calculate
stage precedence and retains the existing package lineage and selection blocker checks.

The source-authority approach does not yet avoid node revision payloads. The existing node
manifest and head alone do not establish the validity and recording/content identity of
every historic `data_revision` used by the old reader. Skipping that validation would alter
error and availability behavior for invalid or inconsistent retained records. No such
shortcut was made. Runs, analyses, packages, nodes and node histories are still enumerated.

The [capture](0120-Source_List_Capture.json) records source hashes and fixture identity.
In the same disposable 1x/10x fixture used by M0, response sizes were 1,083 and 1,085 bytes
(previously 1,096 and 4,732); stage states and active work stayed fixed. Source rows still
grew: node manifests 2/11, node history 1/10, package metadata 1/10, analyses 2/20, and
run directories 2/11. Each remaining growth assertion is a separate strict expected failure.
The one-scan test also covers multiple returned recordings. This is structural evidence,
not a latency result.

One instrumented hard-corpus list request returned HTTP 200 in 18.482 seconds. M0's one
instrumented capture was 18.070 seconds; neither single sample is a latency qualification.
Both read 14 revision records, 70,117,888 revision bytes, 11 histories and 737 JSON values.
The hard corpus lacks populated analysis, package and run roots. This change therefore does
not demonstrate a hard-corpus speedup and does not satisfy the fast-open outcome. The bounded
response is useful for retained analysis and package histories, but it is not evidence of
history-independent read cost.

Checks: targeted backend API, growth, recording bundle and pipeline status/blocker tests;
Ruff and format; web typecheck, lint, API generation/verification and App tests. A real
Chromium test used a separate Uvicorn process and disposable persisted data, opened the
recordings list and navigated to its workspace in ten contexts. A separate persisted API
check verifies the list summary and full detail after app restart. These tests do not prove
fast opening on the hard corpus or restart of the browser process. The hard-corpus and
browser checks are not formal qualification.

Stop here. The authorized list step delivered a bounded response and removed repeated
analysis scans, but its user-visible speed checkpoint is unproved. Do not mark it complete,
start the proposed summary contract, or reset M3's correction history. Further work must
first specify a bounded, correct node-availability proof and its existing-authority and
retained-data checks; request authorization before implementation.
