# Epic 0114 M11: full-corpus baseline and qualification gates

Date: 2026-11-08
Status: Complete

## Result

The complete retained corpus passed on the declared MacBook Pro M2 Pro profile. Warm endpoint families use three independent batches. M6–M10 single-run and browser families were repeated in three sequential sessions. The full raw collection contains 6,456 response or action samples, 179 case/profile/cache budgets, and 70 UI route budget keys. No request timed out, no response check failed, and all three independent M6-M10 sessions passed.

The [machine-readable baseline](0114-M11_Performance_Baseline.json) records every case ceiling, noise allowance, route key, input hash, and source hash. The [raw results](0114-M11_Baseline_Raw/) retain per-request data, CSV exports, startup logs, browser waterfalls, and discarded attempts. The accepted raw tree is 40 MB; its provenance map contains 68 file hashes.

## Machine and fixtures

- Machine: MacBook Pro M2 Pro, model `Mac14,10`, macOS 27.2, arm64, 12 CPUs, Python 3.13.18.
- Hard fixture: `~/.cache/doko-detector/interactive-performance`. The hard-snapshot validator checked all 57 content-addressed assets before timing. The manifest SHA-256 is `e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`.
- The hard recording video is 127 MB. M2 measured a real 65,536-byte range response. Startup, catalog, pipeline, and write families used exact hard snapshots where declared.
- M9 derived-media cases use the compact generated 55-byte video fixture and a deterministic thumbnail renderer. Route and cache handlers are real. The hard video transfer budget comes from M2.
- M10 uses the documented compact generated browser fixture (106 files, 173,838 bytes, 64×64 local video) against a real Uvicorn process and Vite browser app. It is browser workflow evidence, not hard-data browser timing.
- No run flushed the OS file cache. Cold refers to a new process/app and declared application-cache state.

## Session coverage

| Family | Retained samples | Coverage and protocol |
| --- | ---: | --- |
| M2 startup | 150 | Empty, hard-populated, and interrupted-recovery profiles; 10 fresh processes/profile. Every startup and first-use response passed.
| M2 controlled HTTP | 210 | Hard `/api/jobs` and bounded real video range; 5 warmups + 30 measured requests in 3 isolated batches/case.
| M3 catalog/evidence | 1,890 | 18 case/profile groups across generated-empty and hard profiles; 5 warmups + 30 measured requests in 3 batches/group.
| M4-M5 pipeline reads | 3,780 | 35 hard-data cases; one process-cold request and 5 warmups + 30 warm requests in each of 3 batches/case.
| M6 job reads | 45 | 15 samples/session in three fresh runs; history sizes 12 and 300, exact cursor pages and boundary cases.
| M7 interactive writes | 108 | 36 named write/control cases/session in three sequential runs; each durable effect checked.
| M8 residual writes | 24 | Eight real-handler writes/session in three fresh-storage runs; lineage and durable readback checked.
| M9 media/cache | 39 | Thirteen route and cold/warm/restart cases/session in three sequential runs.
| M10 browser/load | 210 | Seven scenarios/session, 10 fresh contexts/scenario, across three sequential real-process browser runs. The controlled-load scenario remains a separate case.

The measured collection envelope ran from the first startup trial log at 19:59 local on Nov 7 through the final residual-write sample at 01:14 on Nov 8: 5 hours 15 minutes. The protocol has fixed sample counts. M2 controlled requests use a 30-second timeout; M3–M5 requests use 180 seconds. Startup cleanup waits at most 30 seconds, and the Playwright suite has a 1,800-second watchdog. The synchronous M6–M9 fixtures use finite named case lists and completed within the measured run envelope. The qualification CLI then validated the complete evidence and hard fixture in 24.5 seconds.

## Capture commands

Run these commands sequentially. Each session writes to `docs/reports/0114-M11_Baseline_Raw/session-01/`, `session-02/`, or `session-03/`; the catalog and pipeline runners use three independent batches inside one result file.

```sh
# Startup profile, once for each profile: empty, hard_populated, interrupted_recovery.
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode startup --profile hard_populated --startup-processes 10 --timeout 180 --output docs/reports/0114-M11_Baseline_Raw/session-01/startup-hard.json

# Hard controlled HTTP, catalog/evidence, and pipeline workspace/result reads.
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_performance.py --mode http --profile hard_populated --warmups 5 --repeats 30 --batches 3 --timeout 30 --output docs/reports/0114-M11_Baseline_Raw/session-01/controlled-hard.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_catalog_read_performance.py --profile both --warmups 5 --repeats 30 --batches 3 --timeout 180 --output docs/reports/0114-M11_Baseline_Raw/catalog-reads.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_pipeline_read_performance.py --warmups 5 --repeats 30 --batches 3 --timeout 180 --output docs/reports/0114-M11_Baseline_Raw/pipeline-reads.json

# Run once in each of the three session directories, in order.
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_job_read_performance.py --output docs/reports/0114-M11_Baseline_Raw/session-01/job-reads.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_write_performance.py --output docs/reports/0114-M11_Baseline_Raw/session-01/interactive-writes.json
DOKODETECTOR_M8_SAMPLE_OUTPUT=docs/reports/0114-M11_Baseline_Raw/session-01/residual-writes.json mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_residual_write_performance.py -q
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_media_performance.py --output docs/reports/0114-M11_Baseline_Raw/session-01/media.json
mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_browser_performance.py --contexts 10 --timeout 180 --output docs/reports/0114-M11_Baseline_Raw/session-01/browser.json
```

Repeat the last five commands for `session-02/` and `session-03/`. Run all measurement commands without another benchmark process on the machine. Use the exact machine and frozen hard fixture above.

## Budget policy

Each case uses p95 when it has at least 30 measured samples; otherwise it uses the median. Noise is `max(category floor, 3 × 1.4826 × MAD)` over retained measurements. The ceiling is `reference + 20% relative tolerance + absolute noise allowance`. The JSON/control floor is 2 ms, media floor 5 ms, browser floor 10 ms, and startup floor 25 ms. Route ceilings link to their measured case groups. The source timing and fixture hashes are recorded in the baseline; the comparator never rewrites the baseline.

| Family | Case groups | Samples/group | Slowest reference | Ceiling | Measured absolute noise allowance range |
| --- | ---: | ---: | ---: | ---: | ---: |
| M2 controlled HTTP | 2 | 90 | 0.479 s (`controlled/video_range`) | 0.580 s | 2.0–5.0 ms |
| M3 catalog/evidence | 18 | 90 | 17.992 s (`catalog/catalog_hard/hard`) | 21.746 s | 2.0–155.7 ms |
| M4-M5 pipeline reads | 70 | 3–90 | 29.569 s (`pipeline/lineage_hard/warm`) | 35.966 s | 2.0–1259.4 ms |
| M2 startup/first use | 15 | 10 | 4.451 s (`startup/hard/workspace_first_use`) | 5.366 s | 25.0–27.1 ms |
| M6 job reads | 10 | 3–6 | 0.037 s (`jobs/history_page_300`) | 0.046 s | 2.0–2.0 ms |
| M7 durable writes | 36 | 3 | 2.009 s (`writes/calibration_draft_discard`) | 2.459 s | 2.0–57.0 ms |
| M8 residual writes | 8 | 3 | 24.853 s (`residual/calibration_apply`) | 29.867 s | 2.0–42.7 ms |
| M9 media/cache | 13 | 3 | 0.089 s (`media/identity_crop_after_restart`) | 0.112 s | 5.0–5.0 ms |
| M10 browser/load | 7 | 30 | 2.206 s (`browser/job_submission_visible_status`) | 2.685 s | 13.0–113.1 ms |

There are 32 slow-debt case groups above one second. For planning, each has a target of 80% of its measured reference; the gap is 20% of that reference. These targets are not the regression ceilings. M12 must ratify a target after profiling and before implementation.

| Slow case | Measured reference | Planning target | Gap | Profile candidate |
| --- | ---: | ---: | ---: | --- |
| `pipeline/lineage_hard/warm` | 29.569 s (p95, n=90) | 23.655 s | 5.914 s | Profile hard node enumeration, lineage validation, and workspace serialization. |
| `pipeline/lineage_hard/cold` | 29.422 s (median, n=3) | 23.538 s | 5.884 s | Profile hard node enumeration, lineage validation, and workspace serialization. |
| `residual/calibration_apply` | 24.853 s (median, n=3) | 19.883 s | 4.971 s | Profile frame-scene reads, fit work, lineage validation, and publication. |
| `pipeline/comparison_exact_runs/warm` | 21.080 s (p95, n=90) | 16.864 s | 4.216 s | Profile exact input loads, matching, and comparison result serialization. |
| `pipeline/workspace_full_hard/warm` | 21.059 s (p95, n=90) | 16.847 s | 4.212 s | Profile hard node enumeration, lineage validation, and workspace serialization. |
| `pipeline/workspace_full_hard/cold` | 20.788 s (median, n=3) | 16.631 s | 4.158 s | Profile hard node enumeration, lineage validation, and workspace serialization. |
| `pipeline/comparison_exact_runs/cold` | 20.785 s (median, n=3) | 16.628 s | 4.157 s | Profile exact input loads, matching, and comparison result serialization. |
| `catalog/catalog_hard/hard` | 17.992 s (p95, n=90) | 14.394 s | 3.598 s | Profile repository enumeration, manifest parsing, and JSON serialization. |
| `pipeline/workspace_stage_visual_identities_hard/warm` | 14.859 s (p95, n=90) | 11.887 s | 2.972 s | Profile hard node enumeration, lineage validation, and workspace serialization. |
| `pipeline/workspace_stage_visual_identities_hard/cold` | 14.714 s (median, n=3) | 11.771 s | 2.943 s | Profile hard node enumeration, lineage validation, and workspace serialization. |
| `pipeline/revision_max_identity_payload/warm` | 5.224 s (p95, n=90) | 4.179 s | 1.045 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/revision_max_identity_payload/cold` | 5.114 s (median, n=3) | 4.091 s | 1.023 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/reviews_exact_revision/warm` | 4.968 s (p95, n=90) | 3.974 s | 0.994 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/reviews_stale_revision/warm` | 4.964 s (p95, n=90) | 3.972 s | 0.993 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/revision_missing_stale/warm` | 4.958 s (p95, n=90) | 3.966 s | 0.992 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/reviews_exact_revision/cold` | 4.928 s (median, n=3) | 3.943 s | 0.986 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/reviews_stale_revision/cold` | 4.902 s (median, n=3) | 3.922 s | 0.980 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/revision_missing_stale/cold` | 4.815 s (median, n=3) | 3.852 s | 0.963 s | Profile immutable revision reads and large payload validation/serialization. |
| `startup/hard/workspace_first_use` | 4.451 s (median, n=10) | 3.561 s | 0.890 s | Profile startup discovery and first-use bundle/workspace loading. |
| `pipeline/revision_max_polygon_payload/warm` | 3.676 s (p95, n=90) | 2.941 s | 0.735 s | Profile immutable revision reads and large payload validation/serialization. |
| `pipeline/revision_max_polygon_payload/cold` | 3.601 s (median, n=3) | 2.881 s | 0.720 s | Profile immutable revision reads and large payload validation/serialization. |
| `startup/hard/recordings_first_use` | 3.010 s (median, n=10) | 2.408 s | 0.602 s | Profile startup discovery and first-use bundle/workspace loading. |
| `browser/job_submission_visible_status` | 2.206 s (p95, n=30) | 1.765 s | 0.441 s | Split API wait, media decode, and view render in a Playwright trace. |
| `pipeline/calibration_draft_snapshot/warm` | 2.195 s (p95, n=90) | 1.756 s | 0.439 s | Profile draft snapshot reads, repeated validation, and serialization. |
| `browser/controlled_load` | 2.172 s (p95, n=30) | 1.737 s | 0.434 s | Split API wait, media decode, and view render in a Playwright trace. |
| `pipeline/calibration_draft_snapshot/cold` | 2.124 s (median, n=3) | 1.699 s | 0.425 s | Profile draft snapshot reads, repeated validation, and serialization. |
| `writes/calibration_draft_discard` | 2.009 s (median, n=3) | 1.607 s | 0.402 s | Profile draft snapshot reads, repeated validation, and serialization. |
| `writes/calibration_draft_start` | 1.998 s (median, n=3) | 1.598 s | 0.400 s | Profile draft snapshot reads, repeated validation, and serialization. |
| `writes/calibration_draft_update` | 1.964 s (median, n=3) | 1.571 s | 0.393 s | Profile draft snapshot reads, repeated validation, and serialization. |
| `writes/calibration_draft_readback_after_update` | 1.951 s (median, n=3) | 1.561 s | 0.390 s | Profile draft snapshot reads, repeated validation, and serialization. |
| `pipeline/calibration_draft_invalid_lineage/warm` | 1.778 s (p95, n=90) | 1.422 s | 0.356 s | Profile draft snapshot reads, repeated validation, and serialization. |
| `pipeline/calibration_draft_invalid_lineage/cold` | 1.749 s (median, n=3) | 1.399 s | 0.350 s | Profile draft snapshot reads, repeated validation, and serialization. |

## Qualification and failure gates

`backend/scripts/qualify_interactive_ui_performance.py` is the machine-readable qualification command. The capture commands run each suite family in the order shown by the raw session files; every runner has a fixed sample count and finite request/process watchdogs. It verifies the 57 hard assets, machine and hard-manifest profile, ten startup logs/profile, exact named case and sample counts, response status, size, and available body hashes, browser scenario/context counts, and the 70 route-to-case links. It fails on missing files or cases, invalid responses, timeouts, wrong profile, extra/missing route keys, or any case reference above its ceiling.

```sh
mise exec -- uv run --project backend python backend/scripts/materialize_interactive_ui_performance_fixtures.py --require-hard
mise exec -- uv run --project backend python backend/scripts/check_interactive_ui_performance_inventory.py
mise exec -- uv run --project backend python backend/scripts/qualify_interactive_ui_performance.py
```

The baseline is explicit and immutable during qualification. A reviewed baseline refresh uses `--write-baseline` only after a complete passing capture and before/after review. The comparator’s injected-slowdown check changed all 90 warm `workspace_full_hard` samples to 10× their measured time and ran the actual qualification command. It failed that case with p95 210.590 s above the 25.671 s ceiling (exit 1).

## Discarded attempts and limits

- The first M4 run overlapped a separate 0115 benchmark. It was stopped; it wrote no result file and does not enter the baseline. The accepted M4 run completed uncontended with 3,780 samples and zero failures.
- M7 exposed a stale fake-participant registration and an old pipeline-run request fixture. The runner now uses the current fake participant and required round facts. The output-bearing contract failure is retained under `discarded/`; three overlapping launches were stopped before export and discarded. The final three sequential runs passed 36/36 each.
- M8 sample rows now include response digests. The earlier rows without digests are retained under `discarded/`; three fresh runs with the complete evidence passed.
- The compact M9/M10 fixtures limit conclusions for hard-data browser behavior and large derived media. The hard source video range itself is covered by M2; the remaining limitation is recorded for future profiles.

## Checks

- Hard fixture validation with `--require-hard`: passed, 57 assets.
- M2 runner regression tests: passed, 8 tests.
- M7 interactive-write runner test: passed.
- M8 residual-write test: passed in all three sequential sessions.
- Qualification-gate unit tests: passed, 3 tests.
- Ruff check and format check: passed for changed Python files.
- Inventory gate: passed, 76 registered API operations, one documented unregistered UI URL, 70 UI cases.
- Full retained-corpus qualification: passed, 179 case budgets and 70 UI route budgets.
- Injected 10× slowdown: rejected by the actual qualification CLI.

## Next work

M12 may profile the 32 slow-debt groups and select candidate cycle one. The machine, fixture, baseline, and route-key map stay fixed for before/after comparisons. The run handoff remains 7 of 9 requested milestones complete, with M12 and M13 remaining.
