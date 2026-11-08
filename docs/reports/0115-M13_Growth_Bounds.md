# Epic 0115 M13: growth bounds package plan

Date: 2026-11-08
Status: Packages 1, 2, and 3 complete; M13 remains in progress
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
| Sampled-frame cache | `SampledFrameResolver` in `operations/src/doko_operations/derived_view.py`; `.runtime/pipeline/derived-views/sampled-frames` | Independent per-recording manifest/frame writer. It has a separate 2 GiB JPEG-byte budget, 30-day idle expiry, 2,048-frame cap per recording/transform, and shares the parent lifecycle lock. |
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

## Package 2: sampled-frame cache

The backend `VisibleCardPipelineService` enables a separate policy for `SampledFrameResolver` under
`.runtime/pipeline/derived-views/sampled-frames`. The policy keeps at most 2 GiB of JPEG frame bytes
across active cache directories, 2,048 frames per source/transform directory, and expires cache
directories after 30 idle days. Reads and writes refresh frame and directory timestamps. Pruning
runs on sampled-cache access; there is no background worker. The 2 GiB count excludes manifests,
lock files, and filesystem allocation overhead. It does not include package 1 entries or explicit
hard-fixture caches.

The source-video SHA-256 selects the recording directory and the manifest also checks the exact
source byte length. The manifest binds the sample interval, maximum dimension, decoder version,
and transform version. A different video identity or transform therefore regenerates into a new
cache identity. Existing schema entries are cache misses. The accepted source video remains the
only input.

The sampled-frame writer shares `derived-views/.lifecycle.lock` with the package 1 digest-entry
writer. The lock coordinates both policies across threads and processes and protects cold misses,
frame publication, and eviction from concurrent access. Frames are flushed before an atomic manifest
replacement. A later access removes orphan frame files and abandoned temporary manifests. A missing
or invalid frame makes the entry a cache miss and the requested sample is decoded again. Cache
eviction does not touch source media, review work, models, or recovery families.

The focused tests cover per-recording frame limits, root-byte eviction, idle expiry, orphan cleanup,
restart regeneration, full JPEG decode validation, source-identity changes, and same-frame misses.
The corruption regression keeps the JPEG dimensions and scan header readable, truncates the scan
data, and proves that the cached image is rejected and regenerated.
Separate processes verify that eviction waits while a reader holds the shared lock. An interruption
test stops pruning after frame deletion but before manifest replacement, then checks recovery on
the next access. The backend API test checks the sampled preview's cold, warm, and second-frame
behavior. The 0114 media suite passed
13/13 cases; all status, response-byte, and response-digest tuples match the retained M9 sample.
Derived-event cold/warm requests took 3.51/2.62 ms; these exercise the regular derived-view path.
The separate sampled-frame API cold/warm requests on a generated one-second 64x64 video both
returned HTTP 200 and the same 245-byte response digest, with frame time 250,000 us. Their one-run
times were 121.97/2.79 ms. Full JPEG decode validation adds to the sampled-frame cache-hit path;
the recorded warm sample includes that validation. These are local samples, not a new latency
baseline.

See [the sampled cold/warm result](0115-M13_Growth_Bounds.artifacts/sampled-frame-cold-warm.json)
and [the 0114 media result](0115-M13_Growth_Bounds.artifacts/0114-media-package2.json). The 0114
artifact contains all 13 response tuples and timings. The separate sampled-frame artifact records
the generated source-video digest, route, cache policy, response identities, and timings. Both
artifacts bind the implementation files to fingerprint
`9d52392cba5ed1142eb82099cb2564cc872ef69ddcc99e89e06d0716ad226c72`; the checked-in M9 response
corpus remains unchanged.

Limits: size is bounded by JPEG payload bytes, while manifest and filesystem overhead are excluded.
The per-recording limit is frame count, not bytes. A 30-day expiry is enforced only when the
sampled cache is accessed. A cold miss decodes while holding the shared parent lock, so it blocks
other cache lifecycle operations until the frame is published. The performance samples use a tiny
test video and do not qualify large recordings or full 0114 application performance.

Package 2 commit boundary: sampled-frame retention, backend wiring, focused tests, 0114 evidence,
this report, epic, and handoff. M13 remains incomplete until the later writer packages and combined
checks pass.

## Package 3: provider-response cache

The active backend construction in `backend/src/dokodetector_backend/gemini_analyzer.py` writes
visible-card responses (Gemini or selected local provider) under `.runtime/gemini-cache/visible-cards`
and Gemini identity responses under
`.runtime/gemini-cache/card-classification`. Both entries bind the complete request key and
provider or classifier version. They retain raw provider JSON, normalized output, usage, and the
estimated receipt cost. A valid cache hit sets `cache_hit` and skips the provider request. The
backend API is the active writer. The cache-only `operations/scripts/run_0088_m2_reference_comparison.py`
is an exact identity-cache reader; its checked-in report records 209 cache hits, zero new requests,
and USD 0.19358325 in historical estimated receipt costs. It blocks live Gemini calls. The cache is
replay data, not the durable M2 report or saved pipeline/review output.

The runtime cache had 18,655 JSON files and 2,896,399,193 logical bytes (2.697 GiB) at this
package's measurement. Entry ages ranged from 3.21 to 70.02 days, so none exceeded the selected
idle limit. The policy gives this cache root a 180-day idle expiry and a 4 GiB logical-byte budget
for unpinned JSON entries across both subdirectories. The measured unpinned entries use
2,895,766,235 bytes, leaving 1,399,201,061 bytes of headroom. The 632,958 pinned bytes are outside
the budget. When a write pushes unpinned entries over budget, the policy removes least-recently-used
unpinned JSON entries first. A cache hit refreshes its idle timestamp. Expiry runs on access; a
whole-root sweep runs at most hourly, and writes enforce the budget. There is no background task.
Lock and sweep-marker files are outside the byte count.

The lifecycle lock protects entry reads, writes, and pruning across threads and processes. Provider
requests run outside the lock; their request and response remain in memory while in flight. Writes
retain the cache API's atomic file replacement. After a process restart, the next access removes
orphaned atomic-write temporary files. An interrupted prune can be repeated. Files can be protected
by a sibling `.json.pin` marker. Pinned entries are excluded from expiry and budget eviction. The
exact 209 response files used by the 0088 M2 cache-only replay were checked
against the report's request keys, crop digests, classifier version, status, and receipt costs, then
pinned. They total 632,958 bytes. The [pin manifest](0115-M13_Growth_Bounds.artifacts/provider-cache-pins.json)
records each response digest and the source report digest. Other provider cache entries remain
regenerable by the current request path, at the possible cost of another Gemini request.

Focused lifecycle checks cover deterministic idle expiry, oldest-first budget eviction with pin
preservation, and a separate-process reader blocking a writer until the read completes. Tests kill
a writer process after it creates a temporary response file for both the visible-card and
classifier caches. A fresh lifecycle removes each orphan and replays the prior published response.
An interrupted prune also completes on the next access. A classifier version mismatch test
confirms that a fresh result cannot overwrite a pinned exact response and that the old classifier
can still replay it. Backend integration checks confirm the cache wrappers use the configured
runtime root and policy. Tests use fake providers; no paid provider request was made.

Checks: 32 provider and classifier tests passed; 16 backend construction and integration tests
passed; Ruff check, Ruff format check, and `git diff --check` passed. The full
`backend/tests/test_app.py` run had one unrelated failure in
`test_factory_converts_interrupted_round_analysis_to_failed`: it observed `queued` instead of
`failed`. A focused repeat also failed. The test and changed files concern separate round-analysis
state handling; this remains a follow-up for that subsystem. This package did not rerun the 0114
media qualifier.

Limits: the 4 GiB budget excludes pinned responses, lock/sweep files, and filesystem overhead. It
can therefore be exceeded if more evidence is pinned. TTL and budget maintenance occur on access
or write, not in the background. Provider cache eviction can cause a new paid request when a caller
repeats an uncached request. The 0088 M2 output remains the durable result; its exact raw receipts
are separately pinned for cache-only replay.

Package 3 commit boundary: shared cache lifecycle, Gemini backend wiring, focused tests, the exact
M2 replay pin manifest, this report, epic, and handoff form one focused package commit. M13 remains
incomplete until packages 4 and 5 and the combined M13 checks pass.

## Remaining M13 packages

1. Operational logs: select one ranked writer family. Preserve active-job logs and recovery
   evidence; campaign logs need a separate retention decision.
2. Recovery copies and campaign intermediates: select one exact family at a time and prove its
   pins, dependencies, reconstruction or restore path, and expiry condition before cleanup.

These packages remain part of M13 and do not add to the four-milestone run limit. Package 1 bounds
only direct digest entries and package 2 separately bounds sampled-frame JPEG bytes; together they
do not bound lock/state/manifest overhead or other derived-view families. M14 and M15 remain within
the authorized run.

## Run handoff

The active run requested four milestones (M12–M15). M12 is complete. M13 is the current milestone,
so the run has completed 1/4 and has 3/4 remaining. M13 packages 1, 2, and 3 are complete. One
selected operational-log writer and exact recovery or campaign families remain M13 packages. M14
and M15 remain within this run's limit; these packages do not add milestones or authorize work past
M15.
