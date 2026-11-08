# Epic 0115 M11: format experiment and decision

Date: 2026-11-08
Base revision: `919b439b44b39b28fb10d7ca8241d640f6af59c7`
Status: Complete; M12 format selected

## Scope and method

The experiment used the M0 rank-2 derived-view cache, narrowed to one concrete resource kind:
`visible-region-crop/v1` entries whose canonical image encoding is PPM. The cache held 8,571
entries, with one manifest and one content file per entry. The source data occupied 1,997,795,952
logical content bytes and 50,023,371 manifest bytes. The selected files used 2,083,942,400
allocated bytes. They are part of the 6.5 GiB derived-view root reported in M0.

The benchmark was read-only against the cache. It materialized the current representation and two
lossless gzip variants in a temporary directory, then removed them. Each candidate stored one
compressed content file and one manifest per entry. The candidate manifest added the codec name,
stored digest, and stored byte length. The existing content digest and byte length remained those
of the uncompressed PPM bytes. The aggregate digest over every cache key and its frame, geometry, and exclusion identity is
`6721e55f6edc3c3d1f9f0602e0c77ffc1fd553e6acee6d15a39397cd2ae70381`. The machine-readable
[benchmark evidence](0115-M11_Format_Experiment.artifacts/format-benchmark.json) records the
128-key random sample digest and the benchmark script digest. It contains no media or item payloads.

Both alternatives compressed and restored all 8,571 entries. Every restored byte sequence matched
its source, content digest, and byte length. The all-entry digest binds each cache key to its frame,
geometry, and exclusion identity. Each entry retained its exact identity object and content digest.
Pixel values and numeric precision stayed exact because the restored bytes matched the source bytes. The cache contains no pipeline review
records or lineage authority; those durable records were not changed. The cache identity retains the
exact source frame and crop geometry on which each view depends.

## Results

Read measurements used 128 random cache keys and two passes. “Cold” means the first application
lookup in the pass; the OS file cache was not flushed. Parse and random lookup included manifest
read and validation, content read, and the candidate decompression and digest checks. Write time
covers reading the source, encoding, writing content, and writing the manifest. Allocated sizes
come from the complete temporary family on the same volume.

| Representation | Content bytes | Manifest bytes | Allocated bytes | Files | Encode / parse (256 manifests) | Complete-family store, encode, and write | Cold random read median / p95 | Warm median / p95 | Peak traced memory: store / random read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current PPM | 1,997,795,952 | 50,023,371 | 2,083,942,400 | 17,142 | n/a / 84.9 ms | 2.91 s | 0.438 / 1.475 ms | 0.411 / 1.445 ms | 2.99 / 3.48 MiB |
| Gzip level 1 | 711,507,194 | 51,336,165 | 798,392,320 | 17,142 | 13.22 s / 86.1 ms | 28.35 s | 0.610 / 2.602 ms | 0.587 / 2.581 ms | 5.72 / 10.72 MiB |
| Gzip level 6 | 687,768,807 | 51,335,998 | 774,754,304 | 17,142 | 24.80 s / 86.2 ms | 39.94 s | 0.603 / 2.520 ms | 0.589 / 2.533 ms | 5.62 / 10.66 MiB |

Peak traced memory reports separate measurements: full-family materialization and storage, then the
128-key random-read sample. The read-phase peak does not replace the write-phase peak.

Gzip level 1 reduces allocated bytes by 1,285,550,080 (61.7%) for this exact family. Its random
lookup p95 stays below 3 ms; its absolute median increase is below 0.2 ms. Gzip level 6 saves a
further 23,638,016 allocated bytes (1.1 percentage points) and takes 1.9 times as long to encode.
Both keep the same file count and require one standard-library gzip decode before content digest
validation. The manifest stays readable JSON. The PPM payload already has a `.bin` filename, so an
operator must consult the manifest to inspect it today; gzip adds one decode step for direct image
inspection.

Level 1 adds about 3.0 ms per entry over current storage in the full-family write. Level 6 adds
about 4.3 ms per entry. Level 1 wrote all entries in 28.35 s, compared with 2.91 s for current
storage. This is a one-time bulk conversion cost plus the ongoing compression cost. It does not
include video decoding. The [format benchmark](0115-M11_Format_Experiment.artifacts/format-benchmark.json)
records all measurements. The sanitized [application counters](0115-M11_Format_Experiment.artifacts/application-io-summary.json)
record one timed read per named hard pipeline scenario, response digests, file reads, and parser
calls. They contain no payload content or path names.

## Hard-fixture read and parse qualification

The 57-asset hard fixture was verified against manifest
`e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`. The four frozen M0
counter cases pass their read and parse ceilings and read no live `data` or `.runtime` paths:

| Case | Read opens | Unique files / JSON files | `json.loads` | Domain parsers | Live reads |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full workspace | 63 | 38 / 38 | 586 | 14 | 0 |
| Lineage | 46 | 35 / 34 | 313 | 7 | 0 |
| Maximum identity revision | 6 | 4 / 4 | 12 | 2 | 0 |
| Maximum polygon revision | 6 | 4 / 4 | 12 | 2 | 0 |

The profiler now applies the same disposable current-schema calibration, event-run, comparison,
and automated-run setup helpers as the existing pipeline read runner. The fixture manifest remains
unchanged. The run records one latency and counter sample for each of its 35 named hard pipeline
scenarios; the full 0114 corpus retains the multi-sample timing qualification. This fills six
formerly missing exact case resources in temporary roots only. The sanitized artifact records the
full 35-case run; setup reads are excluded from each request window.

The hard-fixture inventory passed with 76 registered API operations, the documented single UI URL
gap, and 70 UI cases. The complete retained 0114 performance corpus passed all 179 case budgets
and 70 route budgets. Its checked-in raw report contains absolute log paths from a retired
worktree; the qualification command failed on those stale paths when run unchanged. A temporary
copy of the raw tree rebased only those log paths to the matching checked-in files and passed the
same frozen baseline. No checked-in 0114 evidence changed.

## M12 decision and frozen contract

M12 is justified. It will change only the `visible-region-crop/v1` PPM cache entries selected by
this M11 family. Use a versioned `derived-view-cache/v2` manifest and `content.bin.gz` with
`gzip/level-1/v1`. Keep the cache key, `view_kind`, full identity object, uncompressed
`content_sha256`, and uncompressed `byte_length` unchanged. Add `storage_codec`,
`stored_content_sha256`, and `stored_byte_length`; verify the stored digest, decompress, then verify
the existing content digest and length. Do not change JPEG frames, JPEG previews, sampled frames,
other crop kinds, pipeline revisions, reviews, selections, or lineage.

Freeze these acceptance targets for M12 on the same 8,571-entry snapshot and 128 random keys:

- at least 55% lower allocated bytes, with exactly 17,142 entry files;
- cold and warm random-lookup p95 at or below 3.0 ms;
- average complete-family store/encode/write time at or below 4 ms per entry;
- exact uncompressed bytes, digest, length, manifest identity, frame/item membership, and numeric
  values for every converted entry;
- successful current API crop read, edit/review workflow, and restart with the old selected-family
  path disabled;
- interrupted conversion and corrupt stored-byte checks fail safely and can restore the frozen
  v1 snapshot.

Rehearse conversion in isolated storage. Keep the v1 family snapshot until the v2 verification and
restart checks pass. Do not modify or delete the operator cache during M12 rehearsal. Record the
snapshot and recovery digest before any future activation. The compression alternative is lossless. Its added write CPU and one-step inspection cost are
accepted for the measured reduction in disposable cache storage.

## Checks

- `backend/tests/test_0115_pipeline_cutover.py` — PASS (1 test); exact selected revision, review
  and lineage survive the edit/restart workflow in isolated storage.
- Full exact PPM round-trip across 8,571 entries for gzip levels 1 and 6 — PASS.
- `backend/scripts/profile_0115_application_io.py` across all 35 named hard pipeline scenarios —
  PASS; exact response checks and zero live-root reads. See the sanitized counter artifact.
- `backend/scripts/benchmark_0115_derived_crop_cache_formats.py` — PASS, rerun on the same 8,571
  entries; 8,571 exact round trips for each gzip alternative and separate store/read memory peaks.
- Four M0 hard-case read/parse ceilings — PASS.
- `materialize_interactive_ui_performance_fixtures.py --require-hard` — PASS, 57 assets.
- `check_interactive_ui_performance_inventory.py` — PASS.
- `qualify_interactive_ui_performance.py` — PASS on temporary path-rebased copy of the frozen raw
  evidence; 179 case budgets and 70 UI route budgets. Unmodified invocation reports stale absolute
  log paths from the retired worktree.
- Ruff check and format for both changed backend scripts — PASS. Local Markdown links and
  `git diff --check` — PASS.
