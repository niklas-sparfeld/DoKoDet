# Epic 0115 M7: isolated development setup

Date: 2026-11-08
Result: **M7 complete. No tracked data or authority changed.**

## Setup contract

Development and test processes set `DOKO_STORAGE_ROOT` to a distinct absolute path per checkout.
The backend resolves operations, repository intake, evidence-package intake, pending videos, and
runtime data below that root. The CardEventNet inference cache now uses the configured runtime
root too, overriding any request cache path. The repository-relative model and integration-contract
paths remain immutable inputs.

The backend README documents the clean setup, explicit operator-recording import, and normal run
commands. The backend does not rewrite `backend/.env`, copy operator data, or infer a corpus path.
Unset `DOKO_STORAGE_ROOT` still selects the existing repository-relative defaults. Thus an existing
operator process is not silently redirected. Missing model bundles remain unavailable; an explicit
operator import reports a missing or invalid selected recording bundle.

## Mutable-root reader and writer disposition

| Root or resource | Reader/writer | M7 path and check |
| --- | --- | --- |
| Operations, current pipeline nodes, reviews, jobs, and durable state | Pipeline and domain stores and APIs | `DOKO_STORAGE_ROOT/data/operations`; API edit/save/readback/restart in each isolated checkout |
| Repository intake, evidence-package intake, pending videos | Bundle, evidence, upload, and recording APIs | `DOKO_STORAGE_ROOT/data/intake` and `data/incoming`; existing root-resolution test and API workflow |
| Runtime views, thumbnails, provider caches | Runtime storage, thumbnail, Gemini, and CardEventNet | `DOKO_STORAGE_ROOT/runtime`; regression test confirms CardEventNet uses its configured runtime root |
| Operator recording source | Explicit corpus importer and read-only source access | Source stays in place; import requires the corpus path and exact IDs and copies validated bytes |
| Model bundles and tracked model-campaign integration contract | Providers and preflight | Remain at declared immutable checkout/external paths; missing assets fail clearly; M7 does not relocate them |

## Qualification

The M5 fixture workflow uses `fixtures/repository-bundle/v1/both` and
`fixtures/pipeline-data/v1/event-data-interval.json`. Its source-video SHA-256 is
`7184fd89dd78b265e8f617989e8a9659897e060bde2d4f8d47dc05708771f8a8`; the event fixture SHA-256 is
`7e9415663949314206228ee99dc5dd3d69ebbb6e8be28f6f51bd34730c423007`. The tests import a temporary
copy, edit a pipeline node through the API, read it back, restart the app, and read it again. Each
worktree receives a different storage root. The tests assert no node is written under the old
checkout path and that source fixture bytes remain unchanged.

## Exact qualification record

Code revision: `12bd999eca41688d8b6cc19a0f4481a9f501cb76`.

Two disposable detached worktrees used this revision:

| Worktree | Storage root | Root files / bytes | Canonical root manifest SHA-256 |
| --- | --- | ---: | --- |
| `/private/tmp/doko-0115-m7-final-a` | `/private/tmp/doko-0115-m7-final-state-a` | 13 / 6,560 | `104b039e76d4cf5a625b2158777cfe6cba14b77fadcbe9edee940d590598f699` |
| `/private/tmp/doko-0115-m7-final-b` | `/private/tmp/doko-0115-m7-final-state-b` | 13 / 6,560 | `8ffd74f0f83d0623368d6ab73381f7bbc316089a383367608b42f8d2e1b1096b` |

Each manifest hashes sorted relative paths, byte counts, and file SHA-256 values in canonical JSON.
Both roots had `fixture-events` and the imported recording bundle. The distinct state roots were
never shared. Re-running the workflow in worktree A against a third root produced manifest
`21712d024441a91bbbf93ba6da4578072d9213ddf4312eaf2a01dc5aa2e4cddd`; worktree B's manifest
stayed `8ffd74f0f83d0623368d6ab73381f7bbc316089a383367608b42f8d2e1b1096b`. This checks cross-
worktree write isolation. Both worktrees had no `data/operations/pipeline-nodes/fixture-events`
path, so the old mutable path remained unused. The fixture video and event digests are the exact
values above and match their checked-in sources.

The M6 frozen setup sequence passed in both worktrees:

```sh
git worktree add --detach "$WORKTREE" 12bd999eca41688d8b6cc19a0f4481a9f501cb76
cd "$WORKTREE" && mise install
cd "$WORKTREE" && mise exec -- uv sync --project backend
cd "$WORKTREE/web" && mise exec -- npm ci
cd "$WORKTREE/web" && mise exec -- npm run build
cd "$WORKTREE" && DOKO_STORAGE_ROOT="$STATE_ROOT" mise exec -- uv run --project backend \
  python -c 'from dokodetector_backend.app import create_app; create_app()'
cd "$WORKTREE" && DOKO_STORAGE_ROOT="$STATE_ROOT" mise exec -- uv run --project backend \
  pytest backend/tests/test_worktree_storage_contract.py \
  backend/tests/test_operator_corpus_import.py -q
```

`mise install`, backend sync, frontend install/build, app initialization, and both API fixture
tests passed in A and B. The test selector passed 3 tests per checkout. A third isolated API run
passed the same 3 tests to compare manifests. The missing-source importer test and missing
checkpoint provider test passed in the main checkout's focused backend run. The web build reports
the existing 500 kB chunk warning; `npm ci` reports 10 moderate audit findings. Neither stopped
setup. These checks did not use operator assets or mutate the old mutable paths.

## Checks and limits

- Focused backend storage, importer, app, and provider tests: passed except for the M6-recorded
  `test_factory_converts_interrupted_round_analysis_to_failed` failure (`queued` vs `failed`).
- Ruff check, Ruff format check, and `git diff --check`: passed.
- The full clean-worktree checks use the exact M6 setup sequence and the M5 fixture selectors.
- M7 changes cache placement and setup instructions only. It does not untrack or move intake,
  legacy pipeline data, model bundles, or current human work. M8 and M9 retain their separate gates.
