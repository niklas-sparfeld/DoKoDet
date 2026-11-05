# 0107 M0: lineage inventory and contract

Status: complete as the M0 contract. No data migration or runtime change has been performed.
The live checkout contains concurrent changes, so migration requires a consistent snapshot and its identity.

## Existing owners and intended destinations

Paths below are relative to the configured operations root unless stated otherwise. A mapping must
retain the original path, artifact ID, and source-byte digest. It must fail on a missing or ambiguous
reference instead of guessing.

| Existing resource | Owner and consumers | Intended destination or disposition |
| --- | --- | --- |
| `pipeline/revisions/<id>` manifests and content | `PipelineRevisionStore`; pipeline services, coordinator, review and selection services | Exact immutable revision in a named node. Retain old revision ID, bytes, digest, source, producer, coverage, and all input IDs in the mapping. Do not group separate outputs by timestamp. |
| `pipeline/runs/<id>` requests, state and item outcomes | `ProcessorRunStore`; processor services and coordinator | Execution record with exact source, input/output revisions, implementation, model, policies, progress, failures, and empty outcomes. Preserve terminal and nonterminal states. |
| `pipeline/selections/<recording>/<type>.json` | `PipelineSelectionStore`; reference and processor services, workspace | Preserve generated and completed-reference pointers as explicit selection state until 0108 replaces every consumer. Map targets through the old-ID table. Browsing must not change these pointers. |
| `pipeline-references/<recording>/<type>` state, draft, commands and receipts | `PipelineReferenceStore` and `PipelineReferenceService`; operations campaign and readiness tools also read these paths | One separate node for each maintained draft. Map its explicit base revision when available. Preserve state, draft bytes, receipt and command hashes as audit artifacts; command hashes are not replayable edits. Map published revision separately and link only where the stored record proves the relationship. |
| `pipeline-reviews/<recording>/visible_cards/<review>` | `VisibleCardReviewStore`, `VisibleCardReviewService`, visible-card API and editor | One node per independent review, including its exact source, draft, decisions, coverage and completion evidence. Keep review IDs and command hashes. Do not merge reviews that share inputs. The legacy review is a view of the reference, not an additional independent physical draft. |
| Scene proposals in pipeline revisions and edited scenes in visible-card drafts | Proposed-scene and visible-card review services, editor, identity processing | Map each to a virtual-scene node/revision when pose, order, frame and calibration evidence exists. Preserve visible-card, pile and ignore regions separately. Missing scene geometry remains missing; retain original artifact as evidence. |
| Calibration revisions below each recording workspace | `CalibrationRevisionStore`; calibration, scene and identity services | Retain each immutable calibration artifact and exact identity as a dependency. Map to a calibration revision only when its contents and references validate. Preserve failed calibration records where they exist elsewhere; do not invent a published calibration for failures. |
| `round-analyses` inputs, results, state, counterfactuals and evidence packages | `RoundAnalysisArtifactStorage`, analysis store, API and timeline | Retain exact analysis and counterfactual records, source artifacts and paths; map observation inputs, rules, context and settings where recorded. Preserve path-based artifact identities used by timeline and evidence consumers. |
| `pipeline/automated-runs` and coordinator records | Automated run store and pipeline coordinator | Retain orchestration records and stage-to-run/analysis references. They are execution records, not content nodes. Preserve failed and cancelled stages. |
| Derived views under the configured runtime root | Frame/crop materializers and processor consumers | Rebuildable caches are excluded as authoritative nodes. Preserve policies and source identities needed to reproduce them; retain any cache referenced as irreplaceable evidence until verified. Cache creation is not downstream use. |
| Source recordings, retained fixtures and campaign artifacts | Recording and operations tools | Preserve exact artifact identity and bytes. Inventory references without rewriting sealed campaigns or closed epics. If a consumer cannot change, retain an explicit old-artifact mapping. |

`operations` tools that read legacy reference paths include `cardevent_inventory`,
`cardevent_interval_readiness`, `cardevent_readiness`, `cardevent_migration`,
`reviewed_rfdetr_detector_campaign`, `rfdetr_segmentation_campaign`, `dinov3_identity_campaign`,
and `resilience_baseline`. Their retained outputs and active uses need individual classification
before removal. The list is an entry point, not proof that all consumers have been found.

## Contract decisions for subsequent fixtures

- A node ID is stable and independent of its name. A revision ID identifies immutable canonical
  content and its metadata; content digest verifies bytes but is not the node identity. Migration
  IDs must be deterministic from a versioned namespace and the complete old artifact identity.
  Detect collisions and record the complete mapping. Separate review IDs always produce separate
  nodes, even when contents match.
- The working head changes with a compare-and-swap against the expected revision. A no-op creates no
  content revision. A historical edit requires explicit copy or restore. Names and review decisions
  have separate audit records and do not advance content or cause copies.
- An accepted run records all exact input revisions before reading them. Serialize acceptance and
  content edits against the same node lock or transactional boundary. After acceptance, an actual
  content change atomically creates a copy from the exact protected revision. Validate before
  publishing the copy. Use an idempotency key and request digest to resolve retries; reject reuse
  with different content. A failed edit leaves no visible copy. A failed accepted run still protects
  its inputs. Concurrent edits must conflict or resolve to the same idempotent result.
- Record creation and change events with actor, time, operation, exact before/after references, and
  evidence when recorded. Split and merge events carry all source and target item IDs. Unknown
  historical actors and changes are explicitly `not_recorded`; old command hashes cannot fill them.
- Item correspondence is explicit and scoped to exact revisions and evidence. Stable editing IDs
  alone do not prove physical identity or correspondence across frames. Review applicability compares
  the reviewed question, content and evidence, including crop bytes and policy where relevant.
  Preserve inapplicable decisions in history. A changed scene can invalidate another card's review
  when its derived visible evidence changes.
- Graph edges identify exact revisions and their roles: revision within a node, copy from a source,
  and output produced using each input. Reject cycles before commit. Multiple display appearances
  refer to the same node ID. A browse path carries the selected edge and revision at each branch;
  multiple descendants require an explicit choice. It never silently selects a processing input.

## Additional owner and consumer trace

Calibration uses `<recording>/table-plane-calibrations/<revision>/manifest.json`, mutable
`<recording>/table-plane-calibration-drafts/<draft>/{initial,draft}.json`, and immutable
`<recording>/table-plane-calibration-reflows/<receipt>/receipt.json`. `CalibrationRevisionStore`,
`CalibrationDraftStore`, and `CalibrationReflowReceiptStore` own these paths. Calibration refinement,
scene proposals, and identity processing consume their identities. Preserve each initial and current
draft as distinct snapshots; record their known common draft identity without inventing intermediate
edits. Preserve reflow receipts and every recorded source and result reference.

`RecordingBundleStore` and the recording APIs own recording metadata and imported source identity.
Keep those source assets outside the new node store, with exact byte identity and an explicit source
reference from every applicable revision and run. The analysis request stores round context, rules,
search settings and observation input; preserve those exact values in the execution record. Existing
analysis input, result, evidence package and counterfactual paths are externally addressed by the
analysis store and timeline. Map their identities explicitly even when their bytes stay in place.

The current backend selection consumers include `event_pipeline_service`,
`visible_card_pipeline_service`, `proposed_card_scene_pipeline_service`,
`visual_identity_pipeline_service`, `observation_pipeline_service`, `round_analysis_service`,
`pipeline_reference_service`, `visible_card_review_service`, `pipeline_workspace_service`,
`pipeline_stage_api`, `pipeline_workspace_api`, and `cardeventnet_canonicalization`. The last also
opens old reference storage directly. The source search also identifies the operations modules listed
above. Audit indirect callers and retained fixtures again against the actual cutover snapshot; this
list is a removal checklist, not permission to delete any consumer.

## Deterministic migration mapping

The inventory works from a consistent read-only snapshot. Its ID is a digest of the sorted list of
normalized relative paths, file lengths and SHA-256 digests, including referenced files outside the
primary store. Reject symlinks, unstable files, invalid paths, duplicate logical identities with
unequal bytes, and references outside declared roots. Report inaccessible referenced artifacts as
blocking conflicts. Do not inspect sealed sample contents: retain their artifact identity and declared
digest as an external reference and report unavailable verification separately.

Use UUIDv5 with namespace `d1154376-3ab4-5d84-93e1-092dd4ea62d8` and the UTF-8 canonical JSON array
`["0107-migration/v1", resource_kind, old_root_id, relative_identity]`. `old_root_id` identifies the
configured logical root, not an absolute machine path. Normalize relative paths using `/` and reject
`.` and `..` components. Persist the complete key, resulting ID, original ID, and source digests in the
mapping. Encode JSON without insignificant whitespace, with non-ASCII characters preserved. The same snapshot produces the same IDs. A collision between different complete keys is a
blocking conflict, never a suffix or an implicit merge. New interactive nodes and revisions use unique
IDs unrelated to content hashes; content digests are independent integrity checks.

- Each old immutable pipeline revision starts as its own node and one revision. A correction's
  recorded base becomes an exact `copied_from` edge when resolvable; it does not prove that the two
  were revisions within one node. Processor input IDs become typed input edges through the associated
  run when the stored facts establish that association. Preserve unresolved inputs as conflicts.
- Each maintained draft uses its `(recording, content_type)` identity as one node. Its current
  draft is one snapshot revision. A recorded base is a source edge, not inferred ancestry. A separately
  published revision remains its own mapped node; record its relationship only when the stored state
  proves it. An independent review uses `(recording, review_id)` as a separate node, even when it has
  identical content or a common base. The synthetic legacy review resolves to the maintained draft
  mapping, not a second physical node.
- A calibration revision gets a node and revision keyed by `(recording, calibration_revision_id)`.
  A calibration draft gets a separate node keyed by `(recording, draft_id)`; its retained initial and
  current snapshots are revisions only when their relationship is explicitly recorded by the store.
  Equal snapshots share one content revision while retaining both artifact mappings. Reflow receipts
  remain audit artifacts with explicit links, never fabricated content changes.
- Runs, automated runs, analysis records, selection state, receipts and source assets retain their
  own resource kinds and are not converted into editable content nodes. Scene content maps to a
  virtual-scene node only from recorded scene information. Preserve legacy visible-region evidence
  separately when it cannot supply a scene. Derived views remain caches, with explicit evidence
  mappings for any bytes referenced by retained decisions or artifacts.
- Preserve old labels, coverage and review flags as source facts with their original scope. Translate
  only explicit decisions and inspected coverage into review records. Do not turn `complete` into
  per-item decisions or infer negative coverage. If a semantic conversion cannot represent recorded
  facts exactly, block activation and retain the original bytes for diagnosis.

## Review records and applicability

An item decision contains a stable decision ID, reviewer and time if known, exact node and revision,
item reference, question, decision, reviewed content digest, evidence identities and policy identities.
A coverage record identifies the exact revision, question and inspected interval, frame or region,
including explicit empty coverage. An overall decision is separate and revision-bound. Audit records
are append-only; each current applicability result references the earlier decision and states
`applicable`, `inapplicable`, or `unknown`, with a reason. Unknown historical fields remain unknown.

For unchanged copies, retain applicability only if the item content and all evidence used by the
question match. A refreshed identity decision additionally needs explicit one-to-one correspondence,
identical crop bytes and crop policy, and unchanged reviewed content. Ambiguous correspondence,
deleted items, altered evidence or unavailable policy require review. A human-corrected classification
is retained when those conditions hold, even if a new prediction differs. Recompute affected evidence
for all cards after a pose or stacking change; matching an edited ID is insufficient. No upstream
review automatically reviews a derived prediction.

## Atomic publication, migration and cutover

M1–M3 implement a transaction boundary shared by accepted-use registration, head updates and copy
publication. A per-node interprocess lock protects head comparison and acceptance. Acquire multiple
node locks in sorted ID order. Persist accepted input references and a durable transaction commit
before a worker can read them. Publish content and manifests into a private temporary directory,
validate and fsync files, then atomically rename and fsync the parent. Commit the head, copy mapping and
idempotency receipt together through a journaled transaction with recovery; readers expose only
committed transactions. A crash may leave private temporary files but no visible partial copy. Retrying
an accepted command returns its committed result; a different payload under the same key conflicts.
This protocol requires tests on the supported local filesystem; do not claim cross-filesystem atomicity.

M8 only inventories the snapshot and writes a dry-run plan outside the active store. M9 converts
fixtures to a separate staging root and checks counts, canonical content, source-byte digests or
explicit hash mappings, typed references, coverage, review facts, graph acyclicity and all conflicts.
An interrupted conversion or verification leaves the active root untouched. Activation is an atomic
replacement of one application-level root pointer after successful verification, with the old snapshot
retained for recovery. Refuse activation if the source changed after the snapshot. Reapplication of the
same plan is idempotent; a changed snapshot requires a new plan. 0108 owns local activation, rollback,
consumer transition, and deletion after verification; 0107 does not run a real migration.

## Contract fixture matrix

These are small behavioral fixtures for the named milestones, not claims of implemented tests.

| Milestone | Input and action | Required result |
| --- | --- | --- |
| M1 | Node A at revision A1; save changed content, save the same content, restart; two writers both expect A1 | A2 survives restart; no-op adds no revision; A1 remains readable; stale writer conflicts. |
| M2 | Tool inserts item X; human corrects it; tool replaces it; X splits into Y and Z, then Y and Z merge and are deleted | Creation remains attributed to the tool; every recorded operation links exact before/after items and actors; deletion retains history. Copying unchanged X preserves provenance; absent historical actor is `not_recorded`. |
| M3 | Accept run R on A1 while an edit races; R fails; retry a content edit with one idempotency key | Serialization chooses either the committed edit as R's input or protects A1 before the edit. The latter creates exactly one copy B; retries return B; a rejected edit leaves no B. Later B edits remain in B until B is consumed. |
| M4 | Two items have decisions; inspect an empty frame; add an overall decision; change one item | Item decisions, empty coverage and overall decision remain separate; the changed item's old decision is retained but inapplicable; unchanged copied content retains applicability. Item coverage alone does not imply overall review. |
| M5 | Two overlapping scene cards, a corrected identity on one, and exact crop/policy digests; move the other card and rerun | Unchanged exact crops retain their applicable corrections. Changed occlusion or policy invalidates affected decisions, including a different card. Deleted or ambiguously matched items and duplicate identities do not receive guessed decisions. |
| M6 | Scene with fully hidden card, poses and order, exact frame and calibration; separate pile and ignore regions | Round-trip all fields and origin/review facts; derived visible region may be empty. A different calibration is an exact changed dependency; no geometry is invented. |
| M7 | Observation O consumes event E, scene S and identity I; analysis T consumes O and context; A1 has copies B and C | Preserve every typed exact input and run, display A once by identity even in multiple paths, and require branch selection for B/C. Reject a cycle. Preserve failed run and valid empty output distinctly. |
| M8 | Two independent reviews share one base, one draft lacks actor history, one selection is dangling | Two nodes remain distinct, actor is unknown, mapping is byte-for-byte deterministic on repeat, and dangling selection blocks activation. No timestamp-derived ancestry appears. |
| M9 | Fixture snapshot contains the M8 data with the dangling target repaired; interrupt conversion, verification and activation | Counts, semantic fields, source digests and references reconcile; retry does not duplicate nodes. Before pointer swap old store remains active; after verified atomic swap new store is active and recovery snapshot remains usable. |
| M10 | Compose M1–M9 fixtures through edit, use, copy, review, refresh and staged migration | All exact dependencies and applicable decisions survive; run required local checks and document 0108 integration points and remaining old paths. |

## Removal boundary and 0106

0108 removes replaced workspace selectors, reference/review draft lifecycles, pipeline selection
pointers, and old readers/writers only after migrating their data and updating every active consumer
and retained reference. It must update or explicitly retain the operations consumers above, analysis
path identities, fixtures, and any external artifact mapping. It must preserve source assets, sealed
campaign artifacts, immutable historical records and the recovery snapshot. M10 supplies the final
path-by-path removal checklist; this inventory does not authorize deletion.

The local foundations used here are the existing revision, run, review, and coordinator contracts.
0106's remaining M11–M13 concern its device pipeline, comparison and final device evidence; they are
not prerequisites for this foundation. Device artifacts that exist at cutover must still be inventoried
as sources or explicit external references. No device result is assumed or required by M0.
