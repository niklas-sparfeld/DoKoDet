# Repository spring cleanup

## Plan status

- **Summary:** Investigate and remove justified code and interface clutter, simplify selected
  component boundaries, and fix reproducible bugs found during the review.
- **Status:** Ready
- **Depends on:** None. Work that overlaps 0100 must wait for its relevant milestone to land.
- **Outcome:** A short evidence-based inventory and a bounded set of verified improvements make
  common changes easier to locate and reduce unnecessary maintenance. Unsupported candidates can
  be rejected without forcing a change.
- **Prior work:** [0053 discovery](../5-closed/0053-Agent_Navigation_Cleanup_Discovery.md) and its
  [report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md); 0055–0060 delivered focused
  follow-ups. Reassess the current tree; do not reopen those closed plans.

## Milestone status

- **M0:** Not started — verify and rank the inventory and select bounded changes.
- **M1:** Not started — remove proven obsolete development interfaces and their private code.
- **M2:** Not started — simplify one operations command boundary.
- **M3:** Not started — simplify one maintained-reference handler boundary.
- **M4:** Not started — simplify one review-editor boundary.
- **M5:** Not started — fix a bounded, reproduced bug or record why none was selected.
- **M6:** Not started — verify the combined result and publish the remaining inventory.

## Purpose and evidence

This is a new cleanup pass, not a mandate to rewrite the system. The planning review on 2026-10-30
used tracked source sizes, current entry points and references, the glossary, 0100, and the earlier
0053/0058 work. It did not establish that a candidate is dead or that a large file is defective.
Counts below are line counts in the reviewed checkout, including comments and blank lines. They are
navigation signals, not targets.

| Priority | Candidate and current evidence | Question for M0 | Risk / confidence |
| --- | --- | --- | --- |
| 1 | `operations/src/doko_operations/cli.py` has 3,801 lines. One parser and dispatch function cover many data and campaign commands, including historical milestone commands. | Trace actual command consumers and tests; identify one cohesive command family whose extraction or removal reduces unrelated reading. | Medium / high for size, low for removal |
| 2 | `backend/src/dokodetector_backend/pipeline_reference_handlers.py` has 2,540 lines; its visible-card handler spans most of the module. 0058 already separated lifecycle and content handling. | Find a specific content responsibility that can move without changing lifecycle, validation, or saved review behavior. | High / medium |
| 3 | `web/src/visibleCards/PipelineVisibleCardEditorView.tsx` has 2,268 lines; `web/src/visualIdentities/PipelineVisualIdentityEditor.tsx` has 2,000. The latter mixes the editor component with parsing and provenance helpers. | Identify one coherent extraction with a clear ownership and test boundary; review save, conflict, and navigation behavior first. | High / medium |
| 4 | One-time tooling includes `evidence_adoption.py`, backend storage consolidation, and migration entry points. `adopt-evidence` is still advertised in the root README and intake contract and has tests; consolidation is in the backend README. | Check active consumers, recovery and retained evidence before declaring any command obsolete. A historical name alone is insufficient. | High / low for removal |
| 5 | The inventory also shows large campaign, geometry, training, and test modules. Generated `web/src/api/openapi.ts` has 6,147 lines. | Sample only when a concrete defect or ownership problem justifies it. Generated API code is not a manual cleanup target. | Variable / low |

The findings are starting points. No dead code or new bug is established by this planning pass.
The implementing model owns deeper tracing, selection, implementation, and regression evidence.
It must avoid broad refactors and must not treat test-only references as proof of a supported runtime
consumer or absence of references as proof that dynamic entry points are unused.

## M0 — Validate and select

Use the current committed tree and check 0100's current state first. Produce
`docs/reports/0101-M0_Cleanup_Inventory.md`. Record the commit and repeatable tracked-file size
method, excluding generated files, dependency trees, caches, runtime artifacts, data, and closed
history from removal counts. Check entry points, imports, dynamic registration, current documentation,
tests, automation, and recovery or reproduction uses for each removal candidate. Inspect component
ownership, neighboring tests, and actual change friction for each architecture candidate.

For each retained candidate record paths, consumer evidence, benefit, risk, confidence, exact
verification, 0100 overlap, and a small proposed change. Record rejected candidates and reasons.
Investigate bugs with a reproducible fixture or test and record expected and actual behavior. Do not
run model training, inference, sealed evaluations, or mutate data during discovery. Select at most
one small change per M1–M5. Update those milestones with exact paths and tests, or explicitly mark a
milestone not applicable when evidence does not justify work. Split a selected change into further
Luna-sized milestones if it cannot fit one phase. Do not create follow-up epics unless an independent
outcome or dependency requires one.

## M1 — Remove proven obsolete interfaces

Implement only the M0-selected removal. Trace and update the command, private implementation,
exports, tests, and current documentation together. Preserve any active recovery, reproduction, or
data access path. Run relevant component tests and Ruff checks. If no candidate meets the evidence
gate, record the decision and complete the milestone without deletion.

## M2 — Operations command boundary

Implement the selected small command-family change in `operations`; keep remaining behavior and
consumer entry points consistent unless M0 proved an interface obsolete. Test representative help,
argument validation, dispatch, failure, and output behavior for the affected family. Run the focused
operations tests and Ruff checks. Do not restructure all commands or change campaign results.

## M3 — Maintained-reference boundary

After the relevant 0100 work lands, implement at most one selected handler extraction. Preserve
reference lifecycle ownership, concurrency and conflict handling, saved drafts, review decisions,
coverage, serialization, and API behavior. Run focused reference and API tests, including edit,
save, conflict, and reload cases, plus backend Ruff checks. If no useful independent boundary exists,
record that result instead.

## M4 — Review-editor boundary

After the relevant 0100 work lands, implement at most one selected extraction in one editor. Keep
review state, queued edits, draft preservation, navigation, and error behavior intact. Run focused
component and browser workflow tests as appropriate, plus web typecheck, lint, formatting and API
verification. Do not change review decisions or frozen queues. Record a no-change decision if the
benefit does not justify the risk.

## M5 — Bounded bug fix

Select at most one independently reproduced bug from M0 or the preceding milestones. Add a failing
regression test when practical, fix its cause, and run the affected tests and checks. Give bugs owned
by 0100 to that epic; do not create a competing implementation. If none meets this gate, record that
no bug was selected. Larger or ambiguous issues remain in the inventory for later planning.

## M6 — Verify and hand off

Run the relevant combined checks for changed components and local Markdown link checks. Confirm
generated API consistency when affected. Summarize changes, rejected candidates, remaining issues,
known limitations, and verification in `docs/reports/0101-Cleanup_Handoff.md`. Check that no
unrelated work or data changed. Close this epic when each milestone has a verified result or an
explicit evidence-based no-change decision; do not claim that the repository is free of dead code
or bugs.

## Boundaries and delivery

0100 owns local pipeline compatibility, model selection, round context, revision and review-target
access, and its trial readiness. Do not edit overlapping paths while another agent is working on them;
recheck the merged result and adapt or skip a candidate. This epic does not delay 0100 or human
review. Preserve source media, reviewed data, drafts, frozen queues, model bundles, campaign inputs,
and historical evidence. No training, promotion, model quality claim, large data migration, new
compatibility layer, or top-level repository reorganization is in scope. Keep closed epics immutable.

Implement one milestone per phase. Commit each completed milestone to `main`, update this epic and
the board, report every milestone's state, and compact the working context before the next phase.
