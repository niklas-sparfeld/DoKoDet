# 0123 M1: local corpus qualification

Date: 2026-11-10
Reader source revision: `7d58eb94a2fa7b9353fc44984f5bb1edd41d7bda`
Local data worktree: `/Users/niklas.sparfeld/Developer/doko_detector` at
`5cc4a0911ab0c9ff43cea5265c1530f7f043faf6`

## Frozen corpus

The corpus digest covers the three root metadata files for each accepted recording and every
existing exact-selection file. It does not cover video or process-history content.

- 58 recordings.
- 310 metadata and selection files, 214,150 bytes.
- Corpus digest: `628211c82ef16f731ba4c061800dfd704cd1265d94ac3b0daf9fe0fef3eca57d`.
- The list response was 80,976 bytes in every sample. It reported 136 selected indicators and no
unavailable metadata rows.

## Latency sessions

Each session used a fresh temporary runtime and copied exact-selection metadata. The production
FastAPI route ran in ten fresh Uvicorn processes, then handled 30 warm HTTP requests. Chromium used
ten fresh browser contexts against the production Vite app and FastAPI app. The browser timer starts
before navigation to `/` and ends only when the DOM contains all 58 recording links and each link
has visible CSS and nonzero bounds. The Playwright test asserts this count on every sample. It
fulfills thumbnail requests with HTTP 204 so thumbnail generation is excluded; this is separate
from the measured visible-row condition.

The earlier `recordings_to_workspace` duration included navigation into the workspace. It is
superseded and is not the browser list result below. The corrected result is reproducible with:

```sh
mise exec -- uv run --project backend python backend/scripts/profile_0123_local_corpus.py \
  --recordings-root /Users/niklas.sparfeld/Developer/doko_detector/data/intake/recordings \
  --selection-root /Users/niklas.sparfeld/Developer/doko_detector/data/operations/pipeline-nodes/.pipeline-node-selections \
  --output docs/reports/0123-M1_Local_Corpus_Browser.json
```

The runner stores raw per-request browser samples and server logs beside the JSON result. Each
browser sample made one `/v1/recordings` request and zero per-recording detail requests. Capture
set 1 used the generated browser fixture during M1 development. Capture set 2 used the frozen
58-recording corpus; this correction reran that same digest. No third capture set was added.

| Session | Fresh-process API median | Warm API median | Browser list median | Browser max |
| --- | ---: | ---: | ---: | ---: |
| 1 | 20.427 ms | 17.238 ms | 331.542 ms | 357.320 ms |
| 2 | 20.694 ms | 17.534 ms | 329.830 ms | 357.838 ms |
| 3 | 20.586 ms | 17.260 ms | 331.348 ms | 347.555 ms |

All medians were below one second. The explicit browser row-count and visibility assertion passed in
all 30 samples. See the [raw local-corpus browser samples](0123-M1_Local_Corpus_Browser.json) and
their accompanying `.artifacts` directory.

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

No new authority or writer contract was added. The profile runner uses the same local recording
and selection roots as the API measurements. Its temporary runtime contains only copied selection
metadata; it does not write to the local recording corpus.
