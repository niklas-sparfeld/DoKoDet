# 0096 M0 preflight

Date: 2026-10-17

## State

M0 is in progress. This is a preflight snapshot, not the frozen execution manifest. No segmentation
or proposed-scene processor run started.

The live catalog contains 52 accepted recordings. The read-only batch preflight checked 42 entries
after applying the protected-source, legacy-device, and non-flat exclusions. It found 39 selected
event revisions. Three game recordings have no selected event revision and are excluded from this
batch because event detection is outside scope.

| Disposition | Count |
| --- | ---: |
| Preflight candidate; remaining M0 checks pending | 39 |
| Missing selected event revision | 3 |
| Protected test source or related protected session | 4 |
| Legacy-device policy | 5 |
| Non-flat surface | 1 |

The protected test entries and related sessions were removed before querying event selections. No
protected media, references, or predictions were read. The 39 candidate entries have source-use
metadata and event and visible-card maintained-reference state snapshots recorded in the JSON
snapshot. Training, evaluation, and execution eligibility are still separate decisions to make.

## Pinned segmentation bundle

The local provider is available and reports the pinned 0092 M4 bundle:

- Bundle digest: `05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`
- Checkpoint SHA-256: `80accf8a7c55ec65fdd346c0cd2bfcdd28b936260c242c30f1c39ced6043179e`
- Bundle manifest SHA-256: `826ccba533531c62a2059be5889b9c48aa44800df5d216997575a238c37f5816`

The exact local paths and backend provider identity are in the JSON snapshot. The backend was stopped
after the read-only preflight.

## Remaining M0 work

- Compare decoded image hashes against maintained references and report exact comparison coverage.
- Check source-group overlap with the 0092 M4 training set. Keep training-only sources out of scores.
- Freeze extraction policies, implementation and tool digests, and deterministic run identifiers.
- Confirm that protected-source filtering happens before all media, reference, and prediction access.
- Complete the manifest and prove that a failed preflight starts no processor runs.

The processing limits are set to at most 39 runs per processor, one active run, 24 active-processing
hours, 32 GiB process memory, and zero cloud requests. M0 must freeze any verified reductions before
M1 starts.
