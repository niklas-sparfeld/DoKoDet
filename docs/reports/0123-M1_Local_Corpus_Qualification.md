# 0123 M1: local corpus qualification

Date: 2026-11-10  
Reader source revision: `6fa028b6d12e300bdae74cc7fe2645855964d4f0`  
Local data worktree: `/Users/niklas.sparfeld/Developer/doko_detector` at
`5cc4a0911ab0c9ff43cea5265c1530f7f043faf6`

## Frozen corpus

The corpus digest covers the three root metadata files for each accepted recording and every
existing exact-selection file. It does not cover video or process-history content.

- 58 recordings.
- 310 metadata and selection files, 214,150 bytes.
- Corpus digest: `834c532851e12f44087044839ed7ca66c9bd2d6606d9181f7939f55d1e762ed8`.
- The list response was 80,976 bytes in every sample. It reported 136 selected indicators and no
unavailable metadata rows.

## Latency sessions

Each session used a fresh temporary runtime and copied exact-selection metadata. The production
FastAPI route ran in ten fresh Uvicorn processes, then handled 30 warm HTTP requests. Chromium used
ten fresh browser contexts against the production Vite app and FastAPI app. Thumbnail requests were
aborted so the list timing excludes lazy thumbnail work, which the plan measures separately.

| Session | Fresh-process API median | Warm API median | Browser list median | Browser max |
| --- | ---: | ---: | ---: | ---: |
| 1 | 20.887 ms | 17.015 ms | 204.855 ms | 516.168 ms |
| 2 | 21.232 ms | 17.442 ms | 200.728 ms | 540.546 ms |
| 3 | 20.624 ms | 17.341 ms | 211.080 ms | 479.429 ms |

All medians were below one second. The page showed all 58 recording rows in every browser sample.

## Growth and concurrent selection checks

`backend/tests/test_recording_catalog_growth_contract.py` independently grew node versions,
lineage, processor runs, analyses, packages, and proposal files from 10 to 100 entries. For each
family, the route kept its read budget at ten open attempts for one recording (three root metadata
files, one locator, six selection files), read only the three root metadata files, visited one
directory, and returned identical JSON bytes at both history sizes.

The same test runs 20 exact-selection updates concurrently with 30 list requests. It pauses a
writer after the pending locator is published and confirms that the list returns promptly with
all six indicators unavailable. Other rows report the old or new exact pointer, or no selection.
This test is separate from the M0 restart workflow.

No new authority or writer contract was added. The only profile code change records fresh-process
and warm list endpoint samples in the existing real-browser performance runner.
