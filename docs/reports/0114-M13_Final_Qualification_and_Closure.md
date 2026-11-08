# Epic 0114 M13: final qualification and closure

Date: 2026-11-08
Status: Complete
Code revision measured: `132987095cc7d5921ed9f7a6edd005574e81c442`

## Result and cycle-two decision

Cycle two stopped after profiling. No numeric target was frozen and no speculative code change was
made. The hard `workspace_full_hard` request returned HTTP 200, the expected 49,286 bytes, and
SHA-256 `845cacbc15db27837ee9ac0587ad8c0eac7ea64d11db0c7cc39a696759ae7ce1` in 20.246 s. The
profile counted 63 read opens, 38 unique JSON paths, 586 `json.loads` calls, and 14 domain parser
calls (8 visible-card and 6 visual-identity). M12 had already attributed 14.325 s of a 20.351 s
request to five `node_store.history` traversals.

Each history read validates the persisted node revisions and their content. The profile did not
identify a separate duplicate parse or a bounded operation that could be removed while preserving
that validation and the complete workspace response. Skipping validation or reducing returned
history content would weaken the contract. This is the measured stop reason for cycle two.

## Before and after

| Case | M11 reference | After cycle one | M13 current evidence | Result |
| --- | ---: | ---: | ---: | --- |
| `pipeline/lineage_hard/cold` | 29.422 s median | 14.451 s median | M13: 14.387 s median, 3 samples | 51.1% faster; frozen target passed |
| `pipeline/lineage_hard/warm` | 29.569 s p95 | 14.520 s maximum of 9 | M13: 14.427 s maximum, 9 samples | 51.2% faster than M11 p95; frozen target passed |
| `pipeline/workspace_full_hard/cold` | 20.788 s median | 20.387 s median | M13: 20.219 s median, 3 samples | Below M11 gate; no cycle-two gain claim |
| `pipeline/workspace_full_hard/warm` | 21.059 s p95 | 20.469 s maximum of 9 | M13: 20.293 s maximum, 9 samples | Below M11 gate; no cycle-two gain claim |
| Hard startup to useful response | 8.040 s median | 8.077 s median | M13: 8.041 s median, 10 fresh processes | Within the M11 gate; no startup gain |
| Hard recordings first use | 3.010 s median | 3.015 s median | M13: 3.008 s median, 10 fresh processes | Within the M11 gate |
| Hard workspace first use | 4.451 s median | 4.464 s median | M13: 4.447 s median, 10 fresh processes | Within the M11 gate |

M11's retained corpus has 32 groups above its planning target. Cycle one brought the two hard
lineage groups below their targets. About 30 groups remain above target; workspace and startup
remain visible debt. The M11 baseline was not changed. M11 slow-debt targets are planning targets,
not qualification ceilings.

## Current qualification

- The frozen hard fixture validator passed all 57 assets. Its external full-tier requirement is
  `~/.cache/doko-detector/interactive-performance`, with manifest digest
  `e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`; the exact asset manifest
  and source requirements are in the [M1 fixture freeze](0114-M1_Hard_Data_and_Fixture_Freeze.md).
- The route inventory passed: 76 registered API operations, 70 UI route budget keys, and the one
  documented unregistered `/api/recordings/{recording_id}/video` 404 boundary.
- The M11 qualification command passed all 179 case budgets and 70 UI route budgets. Its unchanged
  M11 endpoint, write, media, and contention captures remain applicable because M12 changed only
  lineage history lookup. M13's fresh 24-sample hard pipeline run covers the changed lineage path
  and reserved full workspace route. This reuses unchanged M11 suite families; qualification alone
  over old samples is not used as current-code evidence.
- M13 reran all startup profiles on current code: 10 empty, 10 hard-populated, and 10 interrupted-
  recovery processes. All 30 process trials and 150 recorded endpoint/startup checks passed.
- The full real-process browser and controlled-load suite passed 70 samples in 10 fresh contexts
  for each of seven scenarios. It recorded zero errors. This fresh run includes workspace,
  revision-switch, media, review-save, Jobs drawer, submission, and controlled-load flows.
- Raw outputs: [hard pipeline samples](0114-M13_Pipeline_Qualification.json),
  [workspace profile](0114-M13_Workspace_Profile.json),
  [browser and load samples](0114-M13_Browser_Qualification.json), and the three startup files
  ([empty](0114-M13_Startup_Empty.json), [hard](0114-M13_Startup_Hard.json),
  [recovery](0114-M13_Startup_Recovery.json)). Their `.artifacts/` folders retain browser
  waterfalls, logs, startup CSVs, and trial logs.
- A seeded `representative` generated tier materialized and validated in `/tmp` with seed `11401`
  and 901 hashed assets. It requires no developer corpus. The hard tier still requires the 57
  external assets listed in the frozen manifest.
- Backend tests passed: 33 tests across lineage, pipeline API, and qualification gates. Ruff check
  and format checks passed for the changed lineage files.
- `npm run check` passed typecheck, lint, formatting, and generated API verification. Vitest had
  241 passing and two failing tests. Both failures also exist at the M11 base revision: the two
  tests in `web/src/App.test.tsx` return a workspace object for the `/v1/recordings/{id}` request,
  so `round_id` is absent when `AutomatedPipelineControls` reads it. `git diff
  3d9dfbd42..HEAD -- web/src/App.test.tsx web/src/pipeline/AutomatedPipelineControls.tsx` is empty;
  blame ties the assumption to launch-modal commit `26e3a02a1`. Follow-up belongs to that launch
  modal UI test path. The real-process Playwright suite passed and is recorded separately above.
- The hard-fixture validator and route scanner emit existing legacy run-state warnings from the
  normal checkout data tree. They did not modify it. The temporary disposable profile emitted
  expected missing-resource warnings for optional empty stores.

## Suite cost and reproduction

M11 captured 6,456 raw response/action samples over about 5 hours 15 minutes. Its full qualification
then took about 24.5 seconds. M13 reused unchanged M11 endpoint families, captured 24 fresh hard
pipeline samples, ran 30 fresh startup processes, profiled one hard workspace request, and ran a
fresh 70-sample browser/load suite (about 1.3 minutes). No benchmark processes overlapped. Raw M13
outputs are retained beside this report.

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard
mise exec -- uv run --project backend python backend/scripts/check_interactive_ui_performance_inventory.py
mise exec -- uv run --project backend python backend/scripts/qualify_interactive_ui_performance.py
mise exec -- uv run --project backend python backend/scripts/profile_0115_application_io.py --case workspace_full_hard --output /tmp/0114-m13-workspace-profile.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_pipeline_read_performance.py --warmups 0 --repeats 3 --batches 3 --timeout 180 --case lineage_hard --case workspace_full_hard --output docs/reports/0114-M13_Pipeline_Qualification.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile empty --startup-processes 10 --timeout 180 --output docs/reports/0114-M13_Startup_Empty.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile hard_populated --startup-processes 10 --timeout 180 --output docs/reports/0114-M13_Startup_Hard.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile interrupted_recovery --startup-processes 10 --timeout 180 --output docs/reports/0114-M13_Startup_Recovery.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_browser_performance.py --contexts 10 --timeout 180 --output docs/reports/0114-M13_Browser_Qualification.json
```

The qualification command checks the frozen baseline but does not rewrite it. Refresh the baseline
only after a separate complete capture and review. M13 did not change the case set or gates.

## Remaining follow-ups and closure

- Profile a new workspace candidate only when it has a validation-preserving operation boundary and
  a numeric target can be frozen before implementation.
- Keep the two malformed App test fixtures in the launch-modal UI test follow-up; they predate M13.
- Address the remaining slow-debt cases in a separately scoped performance plan. Do not claim that
  every latency target was met.

M0–M13 are complete. The epic closes because the endpoint inventory, hard and generated fixture
tiers, startup profiles, regression gates, and current browser qualification are available and
verified. Cycle two produced an evidence-based stop because it found no safe bounded reduction.
Performance debt remains documented above.
