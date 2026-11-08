# Epic 0115 M13: growth bounds package plan

Date: 2026-11-08
Status: Replanned before implementation
Base revision: `d31b19bda`

## Why M13 has separate packages

M13 combines stores with different writers and retention authority. A single expiry or size policy
would risk removing data that is still needed for active work or recovery. The package boundaries
below keep each change tied to its writer and its recovery checks. The original M13 acceptance is
unchanged. M13 remains incomplete until all packages and the combined checks pass.

The M0 inventory ranks `.runtime/pipeline/derived-views` at 6.5 GiB and 71,804 files. It identifies
`DerivedViewCache` as the active reader/writer and records a provisional 30-day idle expiry only
after exact-key regeneration is proven. M12 changes the PPM representation for that cache family,
but its 8,571-entry conversion ran in a separate destination. The operator cache remains unchanged;
its frozen snapshot is a recovery reference. M0 separately ranks `.runtime/gemini-cache` at 2.7 GiB
and 18,655 JSON files, with provider cost and replay value unresolved. The M0 inventory also
identifies recovery trees and campaign training outputs as separate retention candidates, not
disposable cache entries.

The current implementation has at least these independent writers:

| Package | Writer and owned path | Required boundary |
| --- | --- | --- |
| Derived-view cache | `operations/src/doko_operations/derived_view.py`; `.runtime/pipeline/derived-views` | Exact cache-key reconstruction, budget and idle expiry, in-flight access protection, crash-safe eviction, and 0114 hot/cold evidence. Keep the separate hard-fixture cache and durable roots outside this writer. |
| Provider-response cache | `backend/src/dokodetector_backend/gemini_analyzer.py`; `.runtime/gemini-cache` | Identify request replay and provider-cost effects, then define independent expiry, budget, active-request, and restart behavior. |
| Operational logs | `backend/src/dokodetector_backend/job_persistence.py` writes per-job `logs.json`; campaign tools also write command and output logs | Select one bounded writer family after ranking. Keep active-job logs and logs needed for restart/recovery. Campaign logs need a separate owner and retention decision. |
| Recovery copies and campaign intermediates | Migration/recovery tooling and campaign materialization/training writers; exact roots vary by operation | Name one exact family at a time, then record pins, dependencies, reconstructability, expiry condition, and a tested recovery procedure. Cache expiry does not apply. |

These boundaries are based on the M0 ranked inventory and source references. They do not authorize
deletion, provider-cache expiry, job-log truncation, or recovery-copy cleanup. The initial package
owns only the derived-view cache. Any further family selected for a package must have its active
reader/writer and retained dependencies confirmed before implementation.

## Current package: derived-view cache lifecycle

Observable result: new derived-view cache growth is bounded while an entry still reconstructs from
its exact cache key and source identity. Durable human work and the 0114 hard-fixture cache remain
outside automatic eviction. A missing or evicted entry regenerates through the existing API path.

Required checks: deterministic budget and idle-expiry behavior; pinned dependency preservation;
missing-entry regeneration; stale source/revision behavior after restart; concurrent readers and
writers; interruption/crash recovery as a separate check; and hot/cold 0114 behavior on the same
fixture corpus. Record source revision, fixture digest, response correctness, and latency against
the M12/M11 baseline. If the exact budget or safe pin mechanism cannot be established from the
current contract, revise this package before implementation rather than weakening the acceptance.

Commit boundary: derived-view writer contract, implementation, focused tests, 0114 evidence, this
report, epic/handoff, and any board update required by a status change in one package commit. Later
packages receive their own bounded contract and evidence. Completing this package alone does not
complete M13.

## Run handoff

The active run requested four milestones (M12–M15). M12 is complete. M13 is the current milestone,
so the run has completed 1/4 and has 3/4 remaining. The first M13 package is derived-view cache
lifecycle. The provider-response cache, one selected operational-log writer, and exact recovery or
campaign families remain future M13 packages. M14 and M15 remain within this run's limit; these
packages do not add milestones or authorize work past M15.
