# 0101 M0 cleanup inventory

Date: 2026-10-30. Source baseline: `63bab3b2b8d1c6a0d26a5c0b4c47ee5e62378da3`.
Owner: [epic 0101](../plans/3-in-progress/0101-Repository_Spring_Cleanup.md).

## Scope and current use

The user works entirely through the web UI. Agents sometimes use the CLI. A documented command
is not evidence of a current user. Retain a command for a concrete web dependency, agent workflow,
recovery input, or reproduction need. Documentation and tests explain a contract; they do not by
themselves prove that the interface is needed.

M0 selects one legacy command removal, two small backend/operations boundaries, one editor data
boundary, and one reproduced validation bug. M0 changes no application code. It runs no training,
inference, sealed evaluation, migration, or data repair. Test writes use temporary fixtures.
Source media, revisions, selections, drafts, and frozen queues are outside the change set.

At baseline, 0100 M0 was complete. During discovery, `9504590dc` completed 0100 M1 and refreshed
the installed packages. Before this milestone's commit, `942a56338` completed 0100 M2's session-ID
changes. Those package, analysis-contract, and browser changes belong to 0100. Recheck 0100 and
the worktree before each later milestone.

## Repeatable source size method

Count committed blobs, not the working tree. Include implementation files under component `src/`
and `ios/CardEventProbe/` or `ios/Sources/`. Count comments and blank lines. Exclude generated
`web/src/api/openapi.ts`, tests, dependency trees, caches, build outputs, runtime artifacts, data,
fixtures, lockfiles, reports, and closed history. These are navigation counts, not removal targets.
M0 removes zero implementation lines. Reproduce the table from the repository root:

```bash
python3 - <<'PY'
import pathlib
import subprocess

commit = "63bab3b2b8d1c6a0d26a5c0b4c47ee5e62378da3"
records = []
for line in subprocess.check_output(["git", "ls-tree", "-r", commit], text=True).splitlines():
    meta, path = line.split("\t", 1)
    parts = pathlib.PurePosixPath(path).parts
    if pathlib.PurePosixPath(path).suffix not in {".py", ".ts", ".tsx", ".swift", ".mjs"}:
        continue
    if path == "web/src/api/openapi.ts":
        continue
    if not ("/src/" in path or path.startswith(("ios/CardEventProbe/", "ios/Sources/"))):
        continue
    if set(parts) & {"data", ".runtime", ".venv", "node_modules", "__pycache__", "dist", "build", "5-closed"}:
        continue
    records.append((meta.split()[2], path))
raw = subprocess.check_output(
    ["git", "cat-file", "--batch"],
    input=("\n".join(sha for sha, _ in records) + "\n").encode(),
)
rows = []
position = 0
for _, path in records:
    end = raw.index(b"\n", position)
    size = int(raw[position:end].split()[-1])
    blob = raw[end + 1:end + 1 + size]
    position = end + size + 2
    lines = blob.count(b"\n") + int(bool(blob) and not blob.endswith(b"\n"))
    rows.append((lines, size, path))
for component in sorted({path.split("/")[0] for _, _, path in rows}):
    selected = [row for row in rows if row[2].split("/")[0] == component]
    print(component, len(selected), sum(row[0] for row in selected), sum(row[1] for row in selected))
for lines, size, path in sorted(rows, reverse=True)[:16]:
    print(lines, size, path)
PY
```

| Component | Files | Lines | Bytes |
| --- | ---: | ---: | ---: |
| Backend | 67 | 30,849 | 1,241,752 |
| CardEventNet | 35 | 15,495 | 592,656 |
| Game engine | 9 | 4,047 | 147,912 |
| iOS | 53 | 18,781 | 735,086 |
| Operations | 76 | 74,973 | 3,126,393 |
| TableEvidenceAnalyzer | 45 | 33,204 | 1,386,057 |
| Web | 123 | 49,587 | 1,548,254 |

The operations CLI has 3,801 lines. The reference-handler module has 2,540. The visible-card
editor view has 2,268. The identity editor has 2,000. Size alone establishes no defect.

## Selected work, in delivery order

Priority by evidence and benefit: M1 removes an obsolete interface; M5 fixes a reproduced bug;
M2 isolates an existing command responsibility. M3 and M4 rank last because their smaller
navigation benefit must wait for 0100 M5. Delivery still follows the milestone order below.

### M1: remove old-runtime evidence adoption

- **Paths:** `operations/src/doko_operations/evidence_adoption.py`; adoption import, parser,
  alias, and dispatch in `operations/src/doko_operations/cli.py`; its one command test in
  `operations/tests/test_operations.py`; `README.md`, `operations/README.md`,
  `docs/Repository_Intake_Contract.md`, and `docs/Data_Lifecycle.md`.
- **Consumer evidence:** tracked code references are the CLI import/dispatch, the module's
  `__all__`, and the command test. The package initializer exports no adoption API. The sole
  operations console script is `doko`; this family uses explicit argparse registration. Searches
  of backend, web, iOS, and repository scripts found no adoption caller or dynamic registration.
  Current documentation advertises the command but supplies no active workflow evidence.
- **Recovery evidence:** the configured runtime root resolves to repository `.runtime`.
  `.runtime/evidence`, `backend/.runtime/evidence`, and `backend/data/evidence` are absent.
  The accepted intake root has 98 package directories; this count does not certify their content.
  The current `backend/src/dokodetector_backend/api.py` upload route collects the intake metadata
  and publishes accepted packages through the canonical storage path. It does not invoke adoption.
  The command test constructs the old layout from a canonical fixture. No retained old-runtime
  recovery input or agent script was found in this checkout.
- **Benefit:** remove an obsolete intake interface and its private bundle-construction code.
  Keep canonical package readers, upload, validation, fixtures, and source bytes.
- **Risk / confidence:** low / high for this local web-and-agent scope. External legacy archives
  were not inventoried; preserving their old command is not a requirement. Recheck the configured
  root and callers before deletion. A new concrete recovery dependency changes this selection.
- **Exact verification:** replace the publication test with parser rejection checks for both
  `adopt-evidence` and `adopt-evidence-package`. Run operations `test_operations.py`,
  `test_import_isolation.py`, and `test_intake_contract.py`; backend `test_intake_contract.py` and
  `test_api.py`; Ruff check/format on changed Python paths; check current documentation links.
- **0100 overlap:** none in the selected code or documentation paths. Do not include its package
  declarations, lockfiles, settings, or analysis changes.

### M2: isolate source lifecycle command execution

- **Paths:** impact and source-retirement dispatch plus `_render_impact_human` in
  `operations/src/doko_operations/cli.py`; new
  `operations/src/doko_operations/source_lifecycle_cli.py`; tests in
  `operations/tests/test_operations.py` and a focused `test_source_lifecycle_cli.py`.
- **Consumer evidence:** `cli.py` explicitly registers `data impact` and `data source retire`.
  `impact.py` owns the underlying data operation. Existing tests exercise impact JSON output,
  retirement idempotency, cross-task impact, and preservation of source bundles. They leave CLI
  help, bad arguments, human output, and failure dispatch less directly covered.
- **Change friction / benefit:** source permission operations currently require reading two
  separated dispatch blocks in a CLI whose recent changes concern detector campaigns and batch
  proposals. Move only execution and rendering for this family. Keep parser registration in
  `cli.py` and leave `impact.py` semantics unchanged. Do not create a command framework.
- **Risk / confidence:** medium / high. Retirement writes receipts, so temporary-root tests must
  check output, return codes, source preservation, and idempotency.
- **Exact verification:** add help and missing-subcommand checks; missing required fields and
  invalid retention-state checks; impact preview versus retirement dispatch; human/JSON output;
  domain and filesystem error handling. Run the two command test files and
  `test_import_isolation.py`; Ruff check/format on changed paths.
- **0100 overlap:** none identified. Keep reconstruction, model selection, and pipeline command
  families out of this extraction.

### M3: isolate visible-card frame coverage parsing

- **Paths:** `_frame_coverage_entries`, `_frame_coverage_key`, and `_item_frame_key` in
  `backend/src/dokodetector_backend/pipeline_reference_handlers.py`; new
  `backend/src/dokodetector_backend/visible_card_reference_coverage.py`; new
  `backend/tests/test_visible_card_reference_coverage.py`; existing `test_pipeline_reference.py`.
- **Consumer evidence:** these private methods are called only by
  `VisibleCardReferenceHandler.validate_coverage`. They normalize frame identity and decisions
  and construct lookup keys. They use no store, source loader, selection update, or lifecycle
  state. Keep scene validation, expected decisions, review-state rules, and completion in their
  current owners. Keep the current duplicate behavior until M5 adds its regression.
- **Change friction / benefit:** recent edits in this 2,540-line module cover identity annotation
  and manual-card coverage. A small independent parser lets coverage contract tests avoid the
  full maintained-reference setup. Extract roughly 70 lines, not the whole visible-card handler.
- **Risk / confidence:** medium / high. Errors and normalized serialization must remain exact.
- **Exact verification:** unit cases for valid resolved and unresolved frames, pile combinations,
  malformed fields, invalid decisions, and current duplicate handling. Run
  `test_visible_card_reference_coverage.py`, `test_pipeline_reference.py`, and
  `test_frame_review_api.py`. Existing reference tests cover edits, stale-write conflicts,
  atomic region commands, saved completion, and restart reads. Run backend Ruff check/format.
- **0100 overlap:** wait for 0100 M5 to land, then recheck its handler/store changes. Adapt or
  record no change if that work removes this boundary. Do not change revision access or drafts.

### M4: isolate identity editor data conversion

- **Paths:** `web/src/visualIdentities/PipelineVisualIdentityEditor.tsx`; new
  `PipelineVisualIdentityData.ts` and `PipelineVisualIdentityData.test.ts` in the same directory;
  existing `PipelineVisualIdentityEditor.test.tsx` and `web/tests/e2e/pipeline-cutover.spec.ts`.
- **Consumer evidence:** reference hydration calls `toEditableIdentity`; generated-result loading
  calls `readItemsFromResult`; coverage hydration calls `readIdentityCoverage`; suggestion
  matching calls `canUseGeneratedProposal`. Their outcome, frame, crop, provenance, and candidate
  readers are local pure helpers. Types already belong to `PipelineVisualIdentityTypes.ts`.
- **Change friction / benefit:** recent changes added matched proposals and manual-card draft
  support inside the same component. Move this one conversion/matching responsibility to a data
  module. Leave request effects, queued writes, retries, conflicts, URL navigation, and completion
  in the component. Keep error formatting local; do not export a generic utility collection.
- **Risk / confidence:** medium / high for the boundary, conditional on 0100. Parsing determines
  which items are visible and which proposals can be accepted. Preserve its behavior in this phase.
- **Exact verification:** add direct cases for classified, face-down, unusable, failed, malformed,
  and missing-provenance outcomes; reference/result conversion; crop/frame/geometry mismatches;
  stable key ordering and coverage parsing. Run these tests and the existing editor tests, which
  cover retries, queued batches, delayed responses, navigation, and completion. Run web typecheck,
  boundary check, lint, format, API verification, and `npm run test:e2e` for the existing browser
  suite. Its conflict scenario covers event review; it is not identity-specific conflict evidence.
- **0100 overlap:** wait for M5 and recheck exact-result navigation and draft-preservation changes.
  `readItemsFromResult` currently falls back to the first revision when the requested ID is absent.
  This static concern belongs to 0100 M5; M0 did not reproduce a live navigation failure.

### M5: reject duplicate frame coverage before completion

- **Paths:** the coverage parser selected for M3 and its tests;
  `backend/tests/test_pipeline_reference.py` for the service regression.
- **Reproduction:** create the existing `_vision_source_revision` visible-card fixture, create a
  reference, and accept `event-01`. Submit two coverage entries with the same exact frame identity.
  Use decisions `empty`, then `cards`. Completion succeeds and retains both contradictory entries.
  Repeat with fresh temporary storage and reverse the order: completion raises
  `PipelineReferenceCoverageError`. This ran through the real reference service, not a mocked
  normalization helper.
- **Cause:** `_frame_coverage_entries` tests uniqueness of the complete entry, including decision.
  `validate_coverage` then indexes entries by frame identity. The last entry silently wins.
- **Expected behavior:** reject duplicate frame keys before publication, regardless of order,
  decision, or redundant `item_id`. For unresolved frames use the existing item-based key. Distinct
  frame identities remain valid. This fixes validation only; it does not create review decisions.
- **Benefit / risk / confidence:** deterministic completion validation / low / high. No migration
  or repair of saved coverage is selected.
- **Exact verification:** add a failing service regression for both decision orders and check that
  rejected completion publishes no revision, advances no selection, and preserves the draft.
  Add parser cases for identical duplicates, differing decisions, resolved-frame item labels, and
  distinct unresolved item IDs. Run the same backend tests and Ruff checks as M3.
- **0100 overlap:** this is coverage completion validation, independent of schema/revision access.
  Recheck M5's merged work before changing the shared module. If M3 is skipped, fix the original
  handler method directly instead of forcing an extraction.

Reproduce the service result from the repository root without touching repository data:

```bash
mise exec -- uv run --no-sync --project backend python - <<'PY'
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path("backend/tests").resolve()))
from test_pipeline_reference import _service, _vision_source_revision
from dokodetector_backend.pipeline_reference_errors import PipelineReferenceCoverageError

for decisions in (("empty", "cards"), ("cards", "empty")):
    with TemporaryDirectory(prefix="0101-coverage-") as temp:
        service, store = _service(Path(temp))
        revision = _vision_source_revision(store, "visible_cards")
        reference = service.create_reference("recording-01", "visible_cards", {
            "operator_id": "operator-01", "source_revision_id": revision,
        })
        item = reference.draft.items[0]
        service.update_draft("recording-01", "visible_cards", {
            "operator_id": "operator-01", "expected_revision": 0,
            "operations": [{"operation": "accept", "item_id": item.item_id}],
        })
        try:
            service.complete_reference("recording-01", "visible_cards", {
                "operator_id": "operator-01", "expected_revision": 1,
                "coverage": {"kind": "visible_frames", "frames": [
                    {"frame_identity": item.item["frame_identity"], "decision": decision}
                    for decision in decisions
                ]},
            })
            print(decisions, "ACCEPTED")
        except PipelineReferenceCoverageError as error:
            print(decisions, type(error).__name__, str(error))
PY
```

## Other candidates and dispositions

| Candidate | Consumer and recovery evidence | Decision, risk, confidence, and future verification |
| --- | --- | --- |
| Backend storage consolidation | `backend/pyproject.toml` registers the console script; `storage_consolidation.py` has four temporary-root tests. Current documentation supplies a recovery procedure. The scanned legacy durable roots contain no files. No web caller or active agent invocation was established. | Not selected for M1: one removal is selected, and removing recovery code has lower value than adoption. Documentation alone is not a retention decision. Remaining inventory: recheck roots and any real restore workflow; removal would cover the script declaration, module, tests, and README. Medium risk; low confidence that it is still needed. Coordinate the manifest/README paths with 0100 M1. |
| CardEventNet importer | `cardevent_migration.py` is called by the CLI and migration/readiness tests. Agent scripts `freeze_0087_m0.py` and `freeze_0092_m0.py` import `_allowed_uses`; that is a concrete reproduction dependency even if the importer command is unused. | No whole-module deletion. Separate helper reuse from the external-import interface before a later removal decision. High risk; high confidence in the script dependency, low confidence in current importer use. Relevant checks: `test_cardevent_migration.py`, `test_cardevent_readiness.py`, and `test_import_isolation.py`. Do not run freeze scripts or read sealed test inputs. |
| Visible-card data migration | `backend/pyproject.toml` registers it and `test_visible_card_data_migration.py` imports it. No current web or agent caller was established. It rewrites revision files. | Defer disposition to 0100 M5, which owns retained-contract access and preservation. Test-only use is insufficient to retain it indefinitely. High data risk; low confidence of current need. Do not execute it, including its default mutation path. |
| CardEventNet canonicalization | Registered backend console script and `test_cardeventnet_canonicalization.py`; a local canonicalization receipt exists. No active web or agent invocation was established. | Remaining inventory, not selected for M1. A completed receipt does not prove ongoing use or justify another execution. Medium risk; low confidence of current need. Later removal must trace receipt/reproduction readers and run the focused tests. |
| Historical timing/campaign commands | Explicit CLI families, campaign tests, current handoff commands, and retained campaign evidence exist. Documentation alone does not prove current use. | No broad removal from size or milestone names. Reproduction dependencies need per-command tracing before selection. Medium risk; low confidence for deletion. No campaign, training, or evaluator execution in discovery. |
| Full visible-card handler or editor split | Existing visible-card controller/view, workbench modules, region operations, scene derivation, and many focused tests already divide ownership. | Reject a broad split. M3 takes only frame parsing; M4 uses only one identity-editor boundary. High regression risk for broader work; medium confidence. |
| Commented identity editor UI | Lines 1418–1662 contain a disabled duplicate list/timeline/completion interface. The live component already uses the extracted presentation modules. | Low-risk cleanup opportunity, unselected to keep M4 to one extraction. No active user is inferred from this dead text. |
| Generated API, large geometry/training modules, large tests | Generated OpenAPI types and declared component ownership explain some size. No independent defect was established by the sample. | Reject manual generated-code cleanup and size-driven rewrites. Keep existing ownership and tests. |

## Verification and limits

Baseline commands use the installed environments without dependency synchronization:

```bash
mise exec -- uv run --no-sync --project operations pytest operations/tests/test_operations.py operations/tests/test_import_isolation.py -k 'adopt_evidence or source_retirement or obsolete_data_review or split_rounds or import or removed_review_batch'
mise exec -- uv run --no-sync --project backend pytest backend/tests/test_pipeline_reference.py
# From web/:
mise exec -- npm test -- src/visualIdentities/PipelineVisualIdentityEditor.test.tsx
```

Results: operations 9 passed, 11 deselected; backend 47 passed; web 31 passed. The backend emitted
one existing Starlette/httpx deprecation warning. The initial unfiltered operations run was stopped
after 246 seconds and one passed test: the next test was scanning retained artifacts in
`impact.py`. It was not a completed suite or a test failure. The focused replacement checks cover
the selected command families without that repository-wide scan. This does not change the full
verification requirement for later implementation milestones.

All 138 local Markdown links in the edited board, moved epic, and new report resolve.
`git diff --check` passes. No implementation, dependency, formatting configuration, or API change
belongs to M0; code lint, typecheck, and API generation are therefore not M0 change checks.
The selected source files still match the recorded baseline after 0100 M1 and M2 landed. Unrelated
changes remain outside this milestone's commit.

This inventory does not certify the live web workflow, external legacy archives, model quality,
or absence of other bugs. New test files named above are acceptance work for later milestones,
not files created by M0.
