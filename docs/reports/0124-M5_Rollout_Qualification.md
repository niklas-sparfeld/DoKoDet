# 0124 M5 rollout and qualification

## Result

M5 activated the frozen retained event corpus and qualified the exact-parent browser path. M5
preserved human reviews, selected references, saved outputs, and existing recording HEADs. M6 still
owns runtime-path removal and final closure.

## Exact parent lookup

The visible-card inspector uses a direct event-set reference when the saved output has one.
Otherwise, it matches that recording's saved `coverage.event_revision_id` with the existing event
set provenance `source_metadata.legacy_revision_id`. It requires one match and verifies the source
content digest. Missing, ambiguous, or mismatched facts show an explicit error. This uses the
recording-local event-set list and detail APIs. It reads no processor-run or lineage data and adds no
stored mapping or API contract.

On disposable persisted data, the normal browser opened pre-M3 output
`8bfa825d-94af-5ac6-877d-a1381e662d65@d9c461ee-c7f9-5a2c-be60-36da3ea9a169`, followed its exact
parent, changed the event selection, restarted the backend, and reopened the same output and parent.
The parent stayed `1dca5a93-4a87-59f6-ab83-d5c72154916b@d41f92f9-7fd1-52db-a065-7c94f963713a`;
its event start was `2001934` and digest was
`00ce1f56caf862db76601d6e82cd36587d56f2c9fd23de208364559b910832f5`. The output revision file SHA-256 remained
`23d6a61ffa5c362d2e7bbf1f24c708c93a1800d684573a1fe4078961119da45c`. The browser harness blocked
processor-run and lineage routes; neither route was requested. Unit tests cover missing and
duplicate provenance, direct references, digest matching, output switches while lookups are
pending, and late responses after recording/output switches.

The normal browser also opened the saved M3 provider result without a detector run. After restart,
the selected saved result still opened exact parent
`manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1`. Generated, corrected, and reviewed alternatives
opened in the browser; the corrected alternative was edited, saved as a new manual alternative,
and the generated alternative selected. A review version reopened with 52 reviews.

## Frozen corpus and activation

Snapshot `fb60d5fcd6ed62bd55d40c9e84189578d244e7fba179de9ef611ac51f151d0a6` names 58 recording
roots, 234 event nodes, 283 event revisions, 102 selectors, 4,778 review files, and 457 saved
visible-card outputs. Seven recordings have no event nodes and remain explicit exceptions.

The disposable rehearsal converted 51 recordings into 283 immutable versions, retaining all 4,778
reviews (4,602 item, 88 coverage, 88 overall). It preserved existing selection state, including
recording 0662. Across 457 outputs, 254 parents have one exact provenance and matching digest; 203
outputs have no saved parent fact and remain unavailable. No ambiguous parent was assigned. Full
replay preserved all 58 root digests and HEADs, all existing event versions, and the parent report.

Activation used the same verified snapshot. It added 283 versions to 58 recording roots and changed
no HEAD. Recovery data includes the pre-activation root state and prior versions. The post-activation
check matched every frozen source, selector, review, event revision, and output digest; existing
0662 HEAD and saved output bytes remain unchanged. A normal browser against the activated recording
roots reopened the exact old parent before and after backend restart with event-set writes,
processor-run reads, and lineage reads disabled. The M3 saved result also reopened after restart.

## Bounded source correction

The required M0–M4 regression run found a real M2 observation failure: visual identity compared the
selected visible-card source with the old bundle store, while the selected output used the accepted
recording-folder source. `VisualIdentityRecordingAccess` now reads the existing recording-root
authority for folder recordings and retains the bundle path for legacy recordings. The persisted
event-set → visible-card → visual-identity → observation regression passes. A stale round-analysis
test now uses a missing exact event HEAD pointer; its no-resource-validation boundary remains
covered. The pending pipeline-node transaction still makes non-event selections unavailable while
the recording-owned event HEAD remains readable. This adds finite adapter owners only; no new
persistent contract or authority was introduced.

## Evidence and checks

- [Frozen corpus snapshot](0124-M5_Frozen_Corpus_Snapshot.json)
- [Disposable rehearsal](0124-M5_Disposable_Rehearsal.json)
- [Replay check](0124-M5_Replay_Check.json)
- [Durable recovery data](0124-M5_Corpus_Recovery.json)
- [Activation receipt](0124-M5_Activation_Receipt.json)
- [Post-activation input check](0124-M5_PostActivation_Input_Check.json)
- Browser evidence: [pre-M3 output](assets/0124-m5/pre-m3-output.png), [parent after restart](assets/0124-m5/parent-after-restart.png), [reviewed version](assets/0124-m5/reviewed-version.png), [generated version](assets/0124-m5/generated-version.png), [saved M3 result](assets/0124-m5/m3-saved-result.png), [activated parent](assets/0124-m5/activated-parent.png), and [activated M3 result after restart](assets/0124-m5/activated-m3-after-restart.png).
- Backend regression suite: passed (12 focused test files, including rollout, event sets, reviews,
  pipeline APIs, persisted M2 observation, round analysis, and 0123 list growth).
- Ruff check and format check: passed for all changed backend modules and tests.
- `web/npm run check`: passed; 47 test files, 251 tests, type, lint, format, and generated API
  checks.
- Recording-folder Playwright suite: passed, 5 browser tests. It uses a disposable persisted
  backend, including browser restart coverage. The automated pre-M3 proof seeds the named output
  and revision identity plus saved parent provenance into that persisted backend. It opens the
  exact parent through the normal inspector, changes event selection, restarts, reopens the output
  and parent, checks the output revision file SHA-256, and blocks run/lineage routes. The manual
  corpus evidence above separately covers the unchanged activated retained output bytes.
- `web/npm run build`: passed. Vite reported the existing bundle-size warning for a 525 kB chunk.
- Frozen source integrity and activation/recovery checks: passed as recorded above.

## Correction 1/2

Review found a stale-link window: after the recording or selected output changed, the inspector
could keep the prior parent link visible until the new lookup finished. The component now keys its
result to the current recording, exact selected node/revision, and saved parent identity. It renders
no prior link on the first render for a new key. Deferred responses cannot publish into a later
recording/output view. Both the switch and late-response regressions pass, as does the checked-in
real-backend browser proof. The correction adds no storage contract, authority, or owner outside
the existing M5 browser/UI and test harness.

## Limits and next step

The seven recordings with no event nodes and the 203 outputs with no saved parent facts remain
explicit exceptions; the UI does not infer parents for them. M5 does not migrate other resource
formats or jobs. M6 must still remove replaced runtime event paths and pass the epic's remaining
closure checks before the epic can close.
