# Epic 0114 M4: pipeline workspace and revision reads

Date: 2026-11-07

## Scope and cases

The runner `backend/scripts/run_interactive_ui_pipeline_read_performance.py` covers six UI GET
routes with 15 named speed and correctness cases. It uses the hard fixture in disposable storage,
then calls the real application services, filesystem stores, validation models, and JSON response
serialization. It reads reviews only; it does not write a review or request derived media.

| Route family | Speed and correctness cases |
| --- | --- |
| Workspace | Full workspace; `visual_identities` stage filter; missing recording |
| Lineage | Exact graph with expected nodes, revisions, and copied parent revisions; missing recording |
| Node revisions | Maximum identity payload; maximum polygon payload; stale revision |
| Reviews | Exact revision; stale revision |
| Calibration refinement | Current-schema draft snapshot; historical draft with invalid lineage; missing draft |
| Published calibration | Exact snapshot; missing revision |

The M0 inventory now includes `GET /api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}`.
It is a UI read route. The runner checks this route's exact calibration and recording identities and
its missing-revision response. The node revision GET routes now map unknown revision keys to their
404 contract. A focused regression test covers both revision and review reads.

The hard lineage case exposed missing copy ancestors in the frozen node set. M4 added exact hashed
node, head, and revision files for those parents. The content-addressed hard cache now contains 57
assets. The lineage reader returns exact identity and polygon revisions and their parent revision
IDs. The fixture validator passes.

The frozen calibration draft is a historical revision without current `input_revision_ids`
provenance. Its read returns the expected HTTP 422 `invalid_calibration_refinement` response. M4
keeps this as a named correctness and speed case. A second case seeds a current-schema proposal and
detector input in disposable storage through `PipelineNodeStore.create`, using the frozen proposal
and detector content. It preserves the original assets and creates no review record. The
calibration-refinement route then returns the exact stored draft. The published calibration
snapshot also has a successful exact-identity case.

## Preliminary samples

Command:

```sh
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_pipeline_read_performance.py \
  --warmups 1 --repeats 1 --batches 1 --timeout 180 \
  --output docs/reports/0114-M4_Pipeline_Read_Samples.json
```

The runner retained 45 samples: one cold request, one warmup, and one warm measured request for
each of 15 cases. Each case used a fresh isolated app. Cold means the first request before that
app's route cache was warmed. Warm means the request after one warmup. The OS filesystem cache was
not flushed. The response body was fully consumed and hashed. All 45 responses matched their
correctness oracle. These samples are preliminary and are not a baseline.

| Case | Cold median | Warm median |
| --- | ---: | ---: |
| Full workspace | 20.30 s | 20.29 s |
| Stage-filtered workspace | 15.13 s | 14.64 s |
| Lineage | 29.48 s | 29.44 s |
| Maximum identity revision | 5.11 s | 5.14 s |
| Maximum polygon revision | 3.59 s | 3.67 s |
| Exact review list | 4.87 s | 4.87 s |
| Calibration-refinement draft snapshot | 2.03 s | 1.99 s |
| Published calibration snapshot | 254 ms | 233 ms |
| Missing recordings, drafts, and calibrations | 7.9–18.6 ms | 0.49–0.54 ms |
| Stale node and review revisions | 4.81–4.88 s | 4.86–4.87 s |
| Historical calibration draft validation | 1.69 s | 1.64 s |

The 29.2-second lineage sample is close to the earlier 30-second exploratory timeout and merits
review with the later performance profile. The final runner uses a finite 180-second timeout. Do not
treat these one-sample medians as stable tail estimates.

Measurement profile: macOS 27.2, Apple M2 Pro (Mac14,10), arm64; source checkout based on
`6d0dd7a0a`; hard fixture manifest SHA-256
`e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`; local in-process ASGI
transport; no controlled background load. No baseline or budget gate is set.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_pipeline_read_performance.py backend/tests/test_pipeline_node_edit_api.py` — PASS, 9 tests.
- Ruff check and format check for the runner, focused tests, and node API — PASS.
- `mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard` — PASS, 57 assets validated.
- `mise exec -- uv run --project backend python backend/scripts/check_interactive_ui_performance_inventory.py` — PASS, 76 registered routes classified.
- Preliminary runner command above — PASS, 45/45 samples correct.

Raw samples: [pipeline read samples](0114-M4_Pipeline_Read_Samples.json).
