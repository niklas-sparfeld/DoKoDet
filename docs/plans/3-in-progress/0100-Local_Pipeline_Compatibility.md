# Local pipeline compatibility

## Plan status

- **Summary:** Remove current code, configuration, and data-contract blockers before an operator
  tries one recorded round from video to reconstruction with the existing local models.
- **Status:** In Progress
- **Depends on:** Completed 0048/0049 recording pipeline, 0090 coordinator, 0092 M4 detector
  bundle, 0088 M6 identity bundle decision, 0095 observation contract, and 0097 review navigation.
  All implementation prerequisites are available. Pending 0096/0098 human review is not a dependency.
- **Outcome:** A reproducible local setup can read current retained results, run the selected local
  models, assemble observations, accept explicit round context, and publish a reconstruction result.
  Existing review targets open without replacing human work. The next task is a real operator trial.
- **Requested scope:** Code and data compatibility first. Exclude the iOS app.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — froze the current code, environment, revision, and review-target findings in
  the [M0 compatibility inventory](../../reports/0100-M0_Compatibility_Inventory.md).
- **M1:** Complete — made the engine dependency editable in operations, regenerated both lockfiles,
  refreshed both environments, and verified the coordinator, provider, observation, analysis, and
  reconstruction checks.
- **M2:** Complete — use canonical recording session identifiers through observation assembly,
  analysis requests and status, storage, timeline output, browser validation, and generated API
  types. UUID and non-UUID identifiers pass analysis, status, restart, timeline, and counterfactual
  reads. Conflicting observation overrides fail before a run starts.
- **M3:** Not started — require explicit round context without hidden gameplay defaults.
- **M4:** Not started — provide one explicit recipe for the existing local models.
- **M5:** Not started — repair active revision and review-target access.
- **M6:** Not started — verify the combined workflow and publish a short trial guide.

## 1. Purpose and evidence

The next product question is whether the current system helps an operator reconstruct a real round.
This epic removes compatibility failures that prevent that trial. It does not improve model quality
or require a correct real-round reconstruction as its acceptance gate.

The repository review on 2026-10-30 found these issues:

| Boundary | Evidence | Required result |
| --- | --- | --- |
| Local package installation | `operations/pyproject.toml` installs `doko-game-engine` as a non-editable local dependency. The earlier check in this chat loaded a stale installed engine: 14 of 46 focused checks failed on missing pile diagnostic fields. With the current engine source, all 46 passed. | Normal installation and execution use the current source without a `PYTHONPATH` override or manual reinstall after each edit. Recheck after the recent dependency upgrade. |
| Recording session to analysis | Imported real-round bundles use identifiers such as `session-2026-08-20`. Analysis request/status contracts and the browser require a UUID; service validation also requires exact equality with the stored recording. | Existing valid recording session identifiers work unchanged through observations, analysis, persistence, and browser controls. |
| Round context | The retained real-round pilot has no active-player, dealer, or first-trick-leader context. Browser and recording convenience paths currently supply seat defaults. | The operator supplies or explicitly confirms the actual round context. Missing facts produce an actionable input request. |
| Model configuration | Local settings select the older 0068 detector and Gemini identity. The 0092 M4 and 0088 M6 bundles are present. Setting an identity bundle path does not select the local classifier. | One explicit development recipe selects the declared local models at every execution entry point. |
| Retained revisions | A read-only manifest check on 2026-10-30 accepted 644 revisions and rejected 78 with `content_type and content_schema do not match`. Rejected examples use `proposed-card-scene-data/v1`. This check did not validate content bytes or prove queue availability. | Current producers, readers, active selections, and review targets agree on supported contracts. Obsolete generated results have an explicit disposition. |
| Review navigation | The [0097 handoff](../../reports/0097-M3_Frame_Review_Handoff.md) reported 165 unavailable queue items in its checkout. The [0098 handoff](../../reports/0098-M3_Identity_Review_Queue.md) pins 114 review frames and records ten conflicting drafts. | Recheck current access. Fix reproducible compatibility failures without changing review decisions or silently selecting another result. |

Two earlier failures are already resolved. Zero-card detector frames have explicit scene outcomes,
and identity probability sums below one pass observation assembly. The
[0095 result](../../reports/0095-M1_Partial_Identity_Observation_Result.md) contains 147 observations
from three retained inputs. Retain these cases as regression coverage; do not reopen the closed epics.

## 2. Scope and constraints

Use the current contracts as the single normal path. Remove obsolete assumptions instead of adding
permanent compatibility adapters or a general migration framework. A bounded data repair may create
replacement generated revisions when an active input uses an obsolete contract.

Preserve source media, reviewed geometry, identity decisions, saved drafts, frozen campaign inputs,
and historical evaluation artifacts. Do not rewrite immutable revision content or its digest in
place. Record a repair receipt when active data changes. It must identify old and new revisions,
the reason, affected selections or review targets, and verification results. Do not modify closed
epic files or sealed reports to make repaired data appear to be the original evidence.

Keep the implementation small. Reuse the recording workspace, coordinator, model loaders,
maintained references, and existing analysis controls. Do not create another pipeline, review
lifecycle, model registry, or configuration service.

Out of scope:

- iOS code, bundled models, decoder settings, builds, capture, and upload workflows;
- training, model tuning, promotion, new quality gates, or sealed-test access;
- new tracking, player attribution, pile reasoning, or reconstruction search algorithms;
- completing human annotation queues or resolving their gameplay and visual decisions;
- campaign UI, cloud deployment, and production hardening;
- the full real-round operator trial and its accuracy evaluation.

## M0 — Freeze the active compatibility inventory

Recheck the owning source and installed environments after the recent dependency upgrade. Inspect
the current backend and operations environments, recording metadata, selections, revision manifests
and content, model bundles, and the exact 0096/0098 review targets. Separate historical reports from
current failures. Include missing referenced files, unsupported contracts, stale generated API types,
and mismatched lineage only when they affect the current local workflow.

Write a bounded report under `docs/reports/0100-M0_Compatibility_Inventory.md`, with a machine-readable
companion when needed for repair input. For each issue, record the affected paths or IDs, current
failure, owning component, proposed repair milestone, and preservation requirements. Inventory all
active targets in the two queues; do not infer that all currently fail from the old handoff.

Acceptance:

- The inventory contains exact failure categories and counts, including accepted and rejected data.
- Each active target has a repair path or a concrete missing-input reason. No item disappears silently.
- Distinguish unavailable source evidence and unknown round facts from software incompatibility.
- Tests and inventory reads do not change selections, references, queue progress, or source bytes.
- Freeze any required regeneration at one execution per affected input with the declared existing
  models, zero cloud calls, and no tuning. Prefer deterministic repair without inference.

## M1 — Use current local package source

Correct local dependency declarations so backend and operations execution use the current game
engine. Use editable local dependencies where needed and regenerate the affected lockfiles with
the declared toolchain. Check other in-repository package dependencies for the same concrete fault.
Do not change package versions merely to force a cache refresh.

Acceptance:

- A clean normal `uv sync` installs matching local packages for backend and operations.
- The installed engine exposes the current pile diagnostic fields. A source edit is visible without
  a manual package reinstall or environment-variable workaround.
- The coordinator, local provider persistence, observation pipeline, and round-analysis checks pass
  against the installed environment, including reconstruction result serialization.
- Document the normal refresh command after a toolchain change. No application code fills missing
  engine fields with invented defaults.

## M2 — Align recording session identifiers

Treat the canonical session identifier in accepted recording metadata as an identifier, not as an
analysis UUID. Align analysis request/status contracts, service logic, storage, observation assembly,
browser validation, and generated API types with that rule. Keep analysis and evidence-package IDs
as UUIDs where those contracts require them. Do not change the iOS app.

Remove recording-path UUID conversions and session-only UUID form checks. Keep exact equality checks
between a recording, its selected observation revision, and its analysis. Do not generate a substitute
session ID or rewrite source manifests to satisfy the old analysis restriction.

Acceptance:

- UUID-shaped and non-UUID recording session identifiers pass the same complete recording-analysis
  path, including status reads, restart reads, and counterfactual inspection.
- Empty or invalid canonical identifiers and genuine cross-session inputs remain rejected.
- Observation assembly uses the recording's canonical session by default. An explicit conflicting
  override is rejected before execution.
- Existing recording/source bytes, source hashes, reviewed decisions, and frozen queue digests remain
  unchanged. Generated OpenAPI and browser types match the revised contract.

## M3 — Make round context explicit

Use the existing analysis request and browser controls to collect four active players in seat order,
dealer, first-trick leader, round/game identity, and the supported rules version. Keep these facts in
the immutable analysis request. Reuse an existing saved context when valid; otherwise request input.
Do not add a separate gameplay metadata service.

Remove silent seat-one gameplay defaults from browser and recording convenience requests. Seat labels
may remain visible examples, but they are not asserted facts until the operator confirms them. Keep
missing context distinct from a processor failure. Preserve the coordinator's explicit skip behavior
when a caller intentionally omits reconstruction.

Acceptance:

- Missing context shows the exact missing fields before analysis starts; the web app does not submit
  an invented dealer or leader.
- Four distinct players and dealer/leader membership are validated consistently in browser and API.
- Explicit valid context reaches the engine unchanged and remains inspectable after reload.
- Fixture context is sufficient for automated verification. Unknown real-round facts are listed as
  operator input for the next trial, not fabricated or treated as a dependency on annotation work.

## M4 — Select the existing local models explicitly

Provide one documented development recipe through the existing settings and request fields:

- CardEventNet: the 0063 M14 development integration contract and its declared checkpoint/decoder;
- detector: 0092 M4 at `.runtime/rfdetr-segmentation-0092-m4/bundle`, using the full-frame
  `local-rfdetr-segmentation` provider for the first trial;
- identity: 0088 M6 at `.runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle`, with local
  classification explicitly selected;
- the existing declared automatic crop policy, explicit supported device, and recorded model digests.

Use the [0090 freeze](../../reports/0090-M0_Composed_Pilot_Freeze.json) and current bundle manifests to
verify these exact model identities. Do not discover a newest checkpoint. Keep fine-frame refinement
available as an explicit alternate; do not add it to the first-trial recipe.

Fix code that ignores or misreports a chosen provider, bundle, or crop policy. Provide a small
shareable configuration example without credentials. Diagnose missing bundle files and stale local
settings before a run. Do not silently fall back to Gemini. Keep the default configuration distinct
from this explicit local recipe; no quality qualification or promotion occurs here.

Acceptance:

- Browser processor runs and coordinator runs select the same declared models and compatible crop
  inputs. Their saved requests/results identify what actually ran.
- A local configuration works without a Gemini credential and makes zero cloud calls.
- Wrong schemas, missing files, incompatible crop inputs, and unavailable devices fail with an
  actionable message. Startup or preflight does not perform a training run.
- The guide explains which model files must exist locally and how to restore retained bundle
  artifacts. Ignored `.runtime` contents are not described as guaranteed fresh-clone assets.
- M6 predictions remain review-required proposals. Existing model quality limits remain visible.

## M5 — Repair retained revision and review-target access

Use M0's exact inventory to repair active catalog, selection, scene, crop, and editor boundaries.
Check both the manifest contract and content bytes; accepting a manifest alone is not enough.
Current producers and readers must agree on the supported schema for each content type.

Fix a reader when it rejects a valid current contract. For obsolete generated content, create a new
current revision through a bounded deterministic conversion or the frozen regeneration budget.
Record the old-to-new lineage. Update only active targets that require that replacement, with an
explicit receipt. Keep original revisions, frozen queues, and evaluation artifacts unchanged. If a
queue needs replacement targets, publish a separate derived queue with the mapping to the frozen
original; never replace an exact pinned target silently. Do not add permanent obsolete-schema support.

Acceptance:

- Active selections resolve to valid content or a specific genuine missing-input outcome.
- Each available 0096 target opens its exact detector/frame result in the maintained-reference
  editor. Applicable scene/calibration content loads or has a recorded replacement path.
- All 114 frozen 0098 frame targets have checked exact revision/card/crop navigation. No new
  multi-recording identity queue UI is required.
- The ten previously reported conflicting identity drafts are rechecked and preserved. Opening a
  target cannot replace, rebase, or mark a different draft reviewed without an explicit operator edit.
- Queue membership, opening an editor, and data repair create no human review decisions or saved-review
  receipts. Genuine missing evidence remains unavailable; compatibility failures do not.
- After restart, repaired targets still resolve. Checks reject content digest tampering, wrong
  recording/frame lineage, and stale selection updates.

## M6 — Verify readiness for the operator trial

Run a deterministic local fixture through the real service boundaries: events, detection, proposed
scenes, identity, observations, reconstruction, result persistence, and browser inspection. Use
explicit fixture round context. Include zero-card frames, pile evidence, face-down classifications,
and identity candidate sums below one. Verify that piles remain separate and are not invented plays.

Check the declared real bundles with bounded local load/inference probes: one recording frame for
the detector, one usable crop for M6, and one bounded event input. Reuse verified M0 evidence when
unchanged. Report actual inputs, device, digests, and terminal outcomes. No full-recording batch,
sealed evaluator, new model, quality comparison, or real-round accuracy claim belongs here.

Publish `docs/reports/0100-Local_Trial_Readiness.md` with normal setup/start commands, explicit model
settings, a suggested existing complete-round recording, and the browser steps from video to result.
List the remaining operator-supplied round facts. State the engine's current search limits and the
difference between a completed execution and a correct reconstruction.

Acceptance:

- Normal clean setup and an existing refreshed checkout pass the same targeted integration checks.
- API, browser, and coordinator paths reach a stored reconstruction result with compatible inputs.
  Legal unresolved results are allowed; an exception or contract rejection is not a successful gate.
- Results and exact review targets remain readable after restart. Existing coordinator retry and
  stale-input protections still pass; no backend worker durability redesign is required.
- Run relevant Python tests and Ruff checks in changed packages, generated API verification,
  frontend type/lint/format/component checks, and focused browser workflow tests.
- Check local Markdown links after plan/report changes. Record unavailable genuine source inputs
  separately from remaining code failures. No known active compatibility failure is deferred silently.
- The handoff leads directly to one real operator trial with the existing models. Training,
  annotation completion, iOS work, and later reconstruction research are not prerequisites.

## Delivery rule

Implement one milestone at a time. Commit each completed milestone directly to `main`, update this
epic and the board, and report every milestone's current state. This planning change starts no
implementation, data repair, model execution, or human review.
