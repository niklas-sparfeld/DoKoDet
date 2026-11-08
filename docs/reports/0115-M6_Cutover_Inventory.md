# Epic 0115 M6: cutover inventory and qualification plan

Date: 2026-11-08
Inventory revision: `b294ffac4b37acc233a212e079ae094b44610888`
Result: **M6 complete. No data was removed and no tracking changed.**

## Frozen tracked families

The bounded inventory covers only the tracked intake and legacy pipeline roots. The machine
inventory records each tracked path, Git blob ID, current file size, and family in
[`inventory.json`](0115-M6_Cutover_Inventory.artifacts/inventory.json). Its embedded canonical
manifest SHA-256 is
`5a1ebcc06b73707697bce76e29a095b9f1cf3107ee766536114628a4b361c653`.

| Candidate | Exact tracked paths | Files | Current bytes | Authority and M8/M9 disposition |
| --- | --- | ---: | ---: | --- |
| Intake | `data/intake/recordings/**` | 239 | 15,633,971,412 | Original recording bundles: source assets and operator corpus. M8 may untrack this exact family only after proving each original remains usable through an independent restore path and after the operator corpus remains available. |
| Pipeline revisions, runs, selections | `data/operations/pipeline/revisions/**`, `runs/**`, `selections/**` | 31,521 | 1,701,015,169 | Legacy pipeline representation. M9 owns this exact candidate only after all readers and writers use the M5 worktree root and the current node/revision workflow. Preserve every revision, run, selection, review decision, and dependency. |
| Automated-run idempotency records | `data/operations/pipeline/automated-runs/**` | 15 | 88,395 | Separate owner and contract. Keep tracked; M6 does not include it in M9. |

The pipeline total is 31,536 files and 1,701,103,564 bytes. Intake totals 239 files and
15,633,971,412 bytes. The 58 tracked `.mov` intake files use Git LFS. Current worktree sizes are
measurements, not unique allocation or reclaimable-space claims. Git blob IDs freeze the exact
tracked entries at the inventory revision. The full LFS object check passed, but it does not prove
that a remote or off-volume restore works. M8 must verify a usable independent restore for each
selected original and keep any unresolved path tracked.

Current ignored authority stays outside these candidates. It includes original operator data, the
active `data/operations/pipeline-nodes` node store, review and calibration drafts, source media,
model bundles, runtime caches, and the protected recovery stage. M1 verified 1,006 node manifests,
27,654 files, and a 1,700,808,685-byte node-store clone against its source; the selected API edit,
review, lineage, and run chain survived restart. M5 then proved explicit operator-bundle import and
API edit/save/readback/restart in two isolated roots. Neither result authorizes moving or deleting
the main operator corpus. Existing fixture corpora, model bundles, and performance inputs remain
protected under their owning plans. Active Epic 0096 still awaits human review of its 165-frame
queue and depends on `.runtime/rfdetr-segmentation-0092-m4/bundle`; both stay outside the
candidates. The local DINOv3 bundle under `data/models` also stays outside this cutover. The M5
operator-copy fixture `fixtures/repository-bundle/v1/both` remains in Git. Epic 0114's hard fixture
requires `~/.cache/doko-detector/interactive-performance`, manifest digest
`e3d19c1295535c22e547b72f3d6a9bef1cdbc40deb8a2f93f9be3e03d1973294`; it remains protected.
Epic 0106 has M13 remaining; M6 found no 0106-owned reference in the two candidate families, but
M8/M9 must repeat dependency checks. No pending human decision or active review draft can be
treated as disposable by this inventory.

The worktree inspection included all four registered worktrees:

| Worktree | Revision | State at inspection |
| --- | --- | --- |
| Main checkout | `b294ffac4` | Unrelated edits only in `AGENTS.md` and `docs/workflows/epic-execution.md` |
| `ios-081e0695-1310-4cd1-99f7-3b0ad27ad408` | `0f46b9ad2` | Clean detached worktree |
| `ios-ea2238c1-eaa1-46e6-a9bc-ebd15fdbb3d4` | `80e755c0b` | Clean detached worktree; Git marks it `locked initializing` |
| `.codex/worktrees/6203` | `b7ebf2390` | Repository-wide staged deletion and untracked checkout state |

Do not integrate a cutover until M8/M9 inspect and protect the actual retained files in the last
worktree. The unrelated main-worktree paths do not overlap this milestone.

## Resource schemas, readers, and writers

| Resource | Representative persisted schema | Active readers and writers | Replacement owner and exact check |
| --- | --- | --- | --- |
| Intake bundle | `repository-bundle/v1`; members have recorded hashes and byte lengths | `RepositoryBundleStorage`, `RecordingBundleStore`, recording APIs, event/visible-card/identity/round-analysis source readers; API upload and explicit operator import write to the configured intake root | M7 applies `DOKO_STORAGE_ROOT`; M8 proves exact bundle identity and real service reads after old checkout paths are disabled, verifies source restoration, and restarts. `operator_corpus_import.py` is an explicit byte copy; it does not replace or delete the source. |
| Legacy revisions | Sample: `visible-card-data/v1`; other recorded content schemas remain mixed | `PipelineRuntimeStorage`, `PipelineRevisionStore`, event/visible-card/identity/observation services, comparison and workspace APIs; migration inventory reads legacy revisions | M9 replaces every active consumer with the current node/revision services under the worktree root; verify exact selected revision content, source references, and restart. |
| Legacy runs | `processor-run-request/v1` plus state and item files | `ProcessorRunStore`, `LegacyProcessorRunStore`, event and visual-identity services, run list/detail/result and comparison APIs; migration inventory reads input/output lineage | M9 checks exact run membership, input/output dependencies, result bytes, API readback, and restart before untracking. |
| Legacy selections | `pipeline-selection/v1` | `PipelineReferenceStore` and workspace selection/read APIs; workspace writes selected references | M9 preserves the selected generated and completed-reference IDs and proves the same API-visible selection after restart. |
| Automated-run idempotency | JSON idempotency entries (sample has no top-level `schema_version`) | `AutomatedPipelineRunStore` and automated-pipeline launch routes | Remains tracked and outside M9 until its separate owner, dependencies, and replacement are verified. |
| Current node data and human work | `pipeline-node/v1` and node/revision content schemas; independent review records | `PipelineNodeStore`, node edit/review APIs, workspace APIs, review stores, calibration stores | Keep in the worktree-owned mutable root. M1 and M5 restore checks are evidence; they do not permit altering current human work in M6. |

The source audit covered `backend/src/dokodetector_backend` and `backend/scripts`. The exact
current paths and contracts are `config.py`, `repository_bundle_storage.py`,
`recording_bundle_store.py`, `operator_corpus_import.py`, `pipeline_storage.py`,
`pipeline_revision_store.py`, `processor_run_store.py`, `legacy_processor_run_store.py`,
`pipeline_reference_store.py`, `pipeline_composition.py`, and the current node-store modules.
The `storage_consolidation.py` migration reads legacy paths. Any remaining direct writer or reader
found by the M8/M9 path-disabled rehearsal blocks that affected paths from untracking.

## Restore and dependency evidence

- `git lfs fsck --objects` passed for the current Git LFS object store. This checks local objects;
  no off-volume or remote restore was tested.
- M1 streamed SHA-256 checks for all 51 recovery videos against both the accepted recovery stage
  and protected intake copies. All 51 paths, byte lengths, and hashes matched. M1 also restored the
  exact `IMG_0097` run/review dependency chain through real APIs across restart.
- M1 verified the accepted-loss migration package: 2,086 resources, 34,414 file records, snapshot
  digest `c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`. This is a same-volume
  recovery source, not off-volume disaster recovery. Three declared lost detector revision IDs and
  unresolved histories remain recorded.
- M5 imported the checked-in `IMG_0097` fixture and matched all five file hashes. It also verified
  the edit/save/readback/restart workflow in two disposable worktrees. The M5 report records the
  fixture video SHA-256 and exact API checks.
- M8/M9 must capture a fresh activation snapshot, repeat current path/dependency lookup, verify all
  selected hashes and exact memberships, rehearse checkout and merge effects in disposable
  storage, and prove restore/readback before changing tracking. A selected path with an unknown
  dependency or restore source stays tracked.

## M5 failure disposition

I ran `backend/tests/test_app.py::test_factory_converts_interrupted_round_analysis_to_failed`
from M5 baseline `9f523c3eeb2b42bd11becf39c970c45cf8922c04` and current revision
`b294ffac4b37acc233a212e079ae094b44610888`. Both runs fail in the same way: the test creates an
app and reads `queued` where it expects startup recovery to set `failed`. This is not an M5 storage
regression. The baseline test and relevant backend files are byte-identical to current.

The origin is concrete: commit `12bef8a6b` removed the `round_analysis_store.fail_non_terminal()`
call from `app.py`; the current factory still has no replacement call. The 0108 retrospective
also records this removal and says the required recovery behavior needs a decision. The test does
not enter the FastAPI lifespan, but restoring only a lifespan hook would not fix this factory
contract unless startup recovery is intentionally moved there and the test is updated. The captured
warning also reports the absent `pipeline/runs` resource root.

Owner: the round-analysis startup recovery contract in `backend/src/dokodetector_backend/app.py`,
`round_analysis_store.py`, and `backend/tests/test_app.py`. Follow-up: decide whether app creation
must fail all non-terminal analyses (restore the removed behavior) or whether managed-job recovery
now owns this state. Then implement the selected behavior and test it at the same lifecycle boundary.
Do not suppress this failure or count it as a passing M5 suite result. It is outside M6; resolve or
explicitly track it before any later acceptance gate that runs this test.

## 0112 and 0114 boundaries

Epic 0112 is closed. Its work split pipeline code responsibilities and preserved current request,
revision, review, job, and recovery behavior. It does not own storage cutover or legacy data
retirement. Epic 0108 owns lineage migration and removal of replaced adapters; Epic 0115 owns
worktree isolation and tracked-data cutover. Do not reopen 0112 or treat its module splits as
proof that all stored legacy data has no readers.

Epic 0114 closed at code revision `132987095cc7d5921ed9f7a6edd005574e81c442`. Its final
qualification passed all 179 case budgets and 70 UI route budgets; 30 startup trials and 70 browser
samples passed. It verified the 57-asset hard fixture and the generated representative tier. M13
recorded remaining slow-debt groups and two old malformed `App.test.tsx` fixtures. The fresh M13
startup and browser evidence remains applicable to its measured code revision; M8/M9 must run the
affected current checks after their changes. 0114 fixtures and their external assets stay protected
until their own plans release them.

## Frozen M7–M9 steps

| Milestone | Exact scope | Required gates before any tracking change | Commit boundary |
| --- | --- | --- | --- |
| M7 | Make M5's root contract the normal isolated development path; configure setup without silently redirecting operator data. Do not alter tracking. | Two clean worktrees with separate roots and old mutable path disabled; real API edit/save/readback/restart; cross-worktree and source-write isolation; fixture materialization; clear missing-asset behavior; affected setup and backend checks. | Setup/configuration, tests, report, epic, board, and current handoff. |
| M8 | Only the 239-file tracked `data/intake/recordings/**` candidate above. No pipeline paths. | Freeze activation snapshot; verify each original's exact identity and independent restore source; path-disabled API source read; importer copy and hash check; clean checkout and two-worktree rehearsal; protect retained files in every registered checkout, including the staged deletion state recorded above; prove main operator corpus remains usable. Unresolved path stays tracked. | Selected intake tracking and setup changes, tests, evidence receipt, epic, board, and handoff. No deletion, history rewrite, or Git/LFS maintenance. |
| M9 | Only the 31,521 tracked revision/run/selection files above. Keep all 15 automated-run idempotency files tracked. | Old paths disabled; all active readers/writers use M5 storage root; exact revisions, run dependencies, selections and reviews preserved; real API edit/save/readback/review/dependency workflow across restart; recovery drill and frozen snapshot digest; clean checkout and affected checks; two-worktree isolation and allocation/time measurement. Unresolved path stays tracked. | This selected pipeline family, its tests and evidence, epic, board, and handoff. No intake tracking change. |

Each later milestone repeats inventory and restore checks against its activation snapshot. M6 does
not authorize tracking changes. The source and active human corpus remain available until those
gates pass.

## Frozen setup commands for M7–M9

Use the exact clean-checkout setup sequence in the [M5 disposable checkout command block](0115-M5_Worktree_Storage_Contract.md#disposable-checkout-to-ready-measurements).
For each milestone, replace its example revision and root with that milestone's committed revision
and two distinct temporary worktree/state roots. Run setup once in each checkout:

```sh
/usr/bin/time -p git worktree add --detach "$WORKTREE" "$REVISION"
(cd "$WORKTREE" && /usr/bin/time -p mise install)
(cd "$WORKTREE" && /usr/bin/time -p mise exec -- uv sync --project backend)
(cd "$WORKTREE/web" && /usr/bin/time -p mise exec -- npm ci)
(cd "$WORKTREE/web" && /usr/bin/time -p mise exec -- npm run build)
(cd "$WORKTREE" && DOKO_STORAGE_ROOT="$STATE_ROOT" mise exec -- uv run --project backend python -c \
  'from dokodetector_backend.app import create_app; create_app()')
```

This is the same measured sequence as M5: checkout, tool install, backend sync, frontend install
and build, then backend app initialization. It creates no second package or app setup contract.

### M7 setup and API checks

Run the M5 fixture workflow selectors in both checkouts, with separate `STATE_ROOT` values:

```sh
(cd "$WORKTREE" && DOKO_STORAGE_ROOT="$STATE_ROOT" mise exec -- uv run --project backend pytest \
  backend/tests/test_worktree_storage_contract.py backend/tests/test_operator_corpus_import.py)
```

Keep `data/operations/pipeline-nodes` and the old mutable paths outside each new state root. The
test checks API edit, saved revision and source readback after restart. Compare source fixture hashes
and both state roots after each run.

### M8 intake-specific checks

Before rehearsal, freeze the tracked index entries for the M8 candidate and run the local LFS check:

```sh
git ls-files -s -- data/intake/recordings > "$SNAPSHOT_DIR/intake-index.txt"
git lfs fsck --objects
```

Use the already validated explicit importer from the [M5 contract](0115-M5_Worktree_Storage_Contract.md#contract)
for each recording ID selected by the activation snapshot. The importer takes one or more IDs, and
must leave the source root unchanged:

```sh
DOKO_STORAGE_ROOT="$STATE_ROOT" mise exec -- uv run --project backend \
  dokodetector-import-operator-recordings \
  --operator-corpus-root "$OPERATOR_CORPUS/data/intake/recordings" \
  --recording-id "$RECORDING_ID"
```

Then run the M5 test command above and the current service checks for `GET
/v1/recordings/{recording_id}` and `GET /v1/repository-bundles/{recording_id}` through the real
backend. Add `backend/tests/test_0115_intake_cutover.py` to bind the selected IDs to those API reads,
exact source and imported bundle fingerprints, file hashes, readback and restart results. Run it
with the M5 selectors. A failed or missing independent restore keeps that recording tracked.

### M9 pipeline-specific checks

Freeze the exact candidate entries before a disposable rehearsal. Run the M1 dependency/recovery
verifier against the selected source and state roots:

```sh
git ls-files -s -- data/operations/pipeline/revisions data/operations/pipeline/runs \
  data/operations/pipeline/selections > "$SNAPSHOT_DIR/pipeline-index.txt"
mise exec -- uv run --project backend python scripts/verify_0115_recovery.py \
  --data-root "$SOURCE_ROOT/data" --runtime-root "$STATE_ROOT/runtime" \
  --output "$RECEIPT_DIR/recovery-validation.json"
```

Run the existing pipeline contract and lineage suites, plus the new exact cutover API/restart test
added by M9:

```sh
DOKO_STORAGE_ROOT="$STATE_ROOT" mise exec -- uv run --project backend pytest \
  backend/tests/test_pipeline_api.py backend/tests/test_pipeline_reference.py \
  backend/tests/test_pipeline_lineage_writer.py backend/tests/test_pipeline_node_store.py \
  backend/tests/test_0115_pipeline_cutover.py
```

The new test must read exact old input revisions, dependencies and selected references through
services, edit/save a node, preserve applicable review decisions, restart, then compare exact
content and dependency IDs with the frozen snapshot. The M9 recovery receipt binds those results to
the snapshot digest. Keep `automated-runs/**` tracked and verify it remains unchanged.

## Checks

- Bounded Git inventory of the two candidate roots — 239 intake paths and 31,536 pipeline paths;
  the committed artifact freezes each path, Git blob ID, file size, and exact subfamily.
- `git lfs fsck --objects` — passed.
- Representative schema and ownership lookups for repository bundle, revision, processor run,
  selection, and automated-run idempotency records — passed.
- Named M5 test on baseline and current — both reproduced the recorded `queued` vs `failed`
  failure; owner and follow-up are above.
- Local Markdown path links — checked for the changed plan, board, and report files before commit.
