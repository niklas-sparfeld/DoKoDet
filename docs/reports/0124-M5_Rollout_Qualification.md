# 0124 M5 rollout and qualification

## Status

M5 is incomplete. No retained corpus activation occurred. This work did not change a recording,
event version, selection, review, saved output, or source bundle.

## Implemented

The visible-card workspace inspector prefers a direct saved event-set reference. Otherwise, it
matches the selected output's `coverage.event_revision_id` against `legacy_revision_id` in event-set
provenance for this recording. The legacy match must be unique and its saved content digest must
match the preserved source content digest. Missing or ambiguous provenance and digest mismatch fail
closed. The link opens the exact event-set version. The event-set workspace accepts the exact set
and version in its URL and opens that version on load.

The lookup uses the existing recording event-set list and detail APIs. It adds no persistent field,
mapping store, or API contract. The lookup component does not call processor-run or lineage APIs.

## Checks

- `web/npm run check`: passed, 47 test files and 248 tests; type, lint, format, and generated API
  checks passed.
- `web/npx playwright test --config=playwright.recording-folder.config.ts`: passed, 4 browser
  tests. The new test opened one exact event-set version from a link and reopened it after a real
  backend restart against the same disposable persisted files.
- Focused backend tests for event-set storage, recording folders, and visible-card pipeline API:
  passed, 25 tests.
- Ruff on the existing recording/event stores, API, and workspace service: passed.
- The existing M4 frozen input manifest remains at
  `/var/folders/gv/yr_91p3x2_vctbq99586hjm80000gn/T/0124-m4-final-39juxq3w/frozen-input-manifest.json`
  with digest `a806ca35d95f2424adfa9c14a063f0d33aeadaff2dcc41af25b9ef32b014f03f`. Its three-recording
  corpus and offline parent mapping are M4 evidence, not an M5 activation snapshot.

## Acceptance gaps

The new browser check does not yet start from pre-M3 output
`8bfa825d-94af-5ac6-877d-a1381e662d65@d9c461ee-c7f9-5a2c-be60-36da3ea9a169`. The combined
output-to-parent action has not been checked with processor-run and lineage reads disabled, after
changing event selection and restarting. Generated, corrected, and reviewed alternatives have not
been qualified through that path. The 58 retained bundles have not been frozen, inventoried,
rehearsed, or activated. The M3 real-provider result has not been requalified in this attempt.

Next, run the output-to-parent browser proof on disposable persisted copies. If it passes, freeze the
current corpus and recovery snapshot, rehearse all usable inputs and explicit exceptions, then
activate only after the source snapshot still matches. Keep current activation and qualification
limits in the M5 handoff. M6 remains responsible for runtime path removal and closure.
