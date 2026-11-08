# Epic 0115 M13: growth bounds package plan

Date: 2026-11-08
Status: Package 1 complete; M13 remains in progress
Planning revision: `84a8835c`

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
| Digest-entry derived-view cache | `DerivedViewCache` in `operations/src/doko_operations/derived_view.py`; direct SHA-256-keyed directories in `.runtime/pipeline/derived-views` | Exact cache-key reconstruction, budget and idle expiry, in-flight access protection, crash-safe eviction, and 0114 hot/cold evidence. Keep the separate hard-fixture cache and durable roots outside this writer. |
| Sampled-frame cache | `SampledFrameResolver` in `operations/src/doko_operations/derived_view.py`; `.runtime/pipeline/derived-views/sampled-frames` | Independent per-recording manifest/frame writer. It is excluded from package 1 and requires its own bounds and parent-root coordination. |
| Provider-response cache | `backend/src/dokodetector_backend/gemini_analyzer.py`; `.runtime/gemini-cache` | Identify request replay and provider-cost effects, then define independent expiry, budget, active-request, and restart behavior. |
| Operational logs | `backend/src/dokodetector_backend/job_persistence.py` writes per-job `logs.json`; campaign tools also write command and output logs | Select one bounded writer family after ranking. Keep active-job logs and logs needed for restart/recovery. Campaign logs need a separate owner and retention decision. |
| Recovery copies and campaign intermediates | Migration/recovery tooling and campaign materialization/training writers; exact roots vary by operation | Name one exact family at a time, then record pins, dependencies, reconstructability, expiry condition, and a tested recovery procedure. Cache expiry does not apply. |

These boundaries are based on the M0 ranked inventory and source references. They do not authorize
deletion, provider-cache expiry, job-log truncation, or recovery-copy cleanup. The initial package
owns only the derived-view cache. Any further family selected for a package must have its active
reader/writer and retained dependencies confirmed before implementation.

## Package 1: derived-view cache lifecycle

The backend's direct SHA-256-keyed `DerivedViewCache` entries now use a 30-day idle expiry and an
8 GiB logical-byte limit for unpinned entries. The limit is based on the M0 6.82 GB logical
inventory, with room for ordinary growth. When the limit is exceeded, the cache removes the least
recently used entries first. A `.pin` file excludes an entry from expiry and eviction. The policy
does not cover the separate `SampledFrameResolver` writer under the `sampled-frames` subdirectory;
that writer is the next M13 package. Explicit cache roots for source media, human work, models, and
the 0114 hard-fixture assets do not use this policy.

The policy is enabled only for backend runtime digest-entry cache access. Other `DerivedViewCache`
users keep their current unbounded test or campaign behavior. Reads refresh the cache entry's directory
timestamp. A small retention state avoids a full tree scan per write; the cache rebuilds that state
after an interrupted mutation. New entries use staging and atomic rename. For an unpinned
replacement, the writer moves the prior entry to a temporary backup before publishing the staged
entry. A lifecycle lock protects cache readers and writers across threads and processes. If
interrupted, the next operation restores the backup when the destination is missing, or removes the
backup when the new entry is present. A pinned entry is never replaced. Exact cache keys still bind
the source and view identity, so a changed source or revision misses the prior entry and regenerates
through the existing API path.

Required checks: deterministic budget and idle-expiry behavior; pinned dependency preservation;
missing-entry regeneration; stale source/revision behavior after restart; concurrent readers and
writers; interruption/crash recovery as a separate check; and hot/cold 0114 behavior on the same
fixture corpus. Record source revision, fixture digest, response correctness, and latency against
the M12/M11 baseline. The 28 focused tests cover expiry, hourly-sweep-on-write, pin/unpin,
oldest-first eviction, concurrent readers and writers, interruption before and after replacement
publish, pinned replacement preservation, and pending-write/staging recovery. Existing API tests
cover a new identity revision, review save, and restart.

The 0114 media suite passed 13/13 cases. All 13 status, byte-count, and response-digest tuples match
the retained 0114 M9 sample. Derived-frame cold/warm requests took 3.43/2.14 ms. Identity-crop
cold/warm, new-revision, after-review, and after-restart requests took 70.44/4.27/70.46/3.88/89.85
ms. These are single-run local samples, not a new latency baseline. The full 0114 qualifier was not
rerun in this package.

The [0114 media result](0115-M13_Growth_Bounds.artifacts/0114-media.json) retains all 13 responses
and timings. Their status, byte count, and response digest tuples match the checked-in 0114 M9
sample. The hard-asset validator passed all 57 assets. Inventory validation passed with 76
registered API operations and 70 planned UI cases. The code and test files have the SHA-256
fingerprint `aab188186390e942506702cb0efd50d1ed7ef0ab5b1fa798d864e040045ae1f7` in the media
artifact.

Limits: the 8 GiB limit applies to unpinned cache entry bytes, not lock/state files or explicitly
pinned entries. Pinned cache entries can therefore exceed it. A read expires its selected entry
after 30 idle days. Writes also sweep expired entries when an hour has passed since the prior sweep
or when the size budget is exceeded. An idle cache with no reads or writes is not swept in the
background. The cache root is disposable; if an evicted entry cannot be regenerated, its API
request still fails under the existing source availability rules. The operator cache was not
activated or modified.

Package 1 commit boundary: cache contract and backend wiring, focused tests, 0114 evidence, this
report, epic, and handoff. Later packages have separate boundaries. Completing this package alone
does not complete M13.

## Remaining M13 packages

1. Sampled-frame cache: inspect its per-recording writer and readers, then define a separate bound
   coordinated with the parent derived-view cache root.
2. Provider-response cache: confirm the active request/cache readers and replay/cost behavior before
   setting its own budget and expiry.
3. Operational logs: select one ranked writer family. Preserve active-job logs and recovery
   evidence; campaign logs need a separate retention decision.
4. Recovery copies and campaign intermediates: select one exact family at a time and prove its
   pins, dependencies, reconstruction or restore path, and expiry condition before cleanup.

These packages remain part of M13 and do not add to the four-milestone run limit. Package 1 bounds
only direct digest entries; it does not bound the entire derived-view root. M14 and M15 remain
within the authorized run.

## Run handoff

The active run requested four milestones (M12–M15). M12 is complete. M13 is the current milestone,
so the run has completed 1/4 and has 3/4 remaining. The first M13 package is derived-view cache
lifecycle. The provider-response cache, one selected operational-log writer, and exact recovery or
campaign families remain future M13 packages. M14 and M15 remain within this run's limit; these
packages do not add milestones or authorize work past M15.
