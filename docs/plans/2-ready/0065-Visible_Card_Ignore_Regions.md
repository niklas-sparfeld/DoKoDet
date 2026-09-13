# Visible-card ignore regions

## Plan status

- **Summary:** Let a reviewer mark an ambiguous untidy card stack as one ignore region without
  asserting a card instance, and keep those pixels out of detector and segmenter supervision.
- **Status:** Ready
- **Depends on:** 0048, 0049, and 0062 complete
- **Readiness:** The maintained visible-card reference, polygon editor, immutable generated
  revisions, and dataset consumer boundary exist. `IMG_0661` supplies the first real case.
- **Outcome:** A reviewer can convert one or more Gemini card proposals into one reviewed
  `untidy_stack` ignore region. Normal visible-card instances in the same frame remain usable.
  Dataset consumers must mask the ignored pixels or exclude the frame. They must never use those
  pixels as card targets or ordinary background.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — define the ignore-region contract and its boundaries.
- **M1:** Not started — persist ignore-region review operations and complete references safely.
- **M2:** Not started — add the low-effort region workflow to the visible-card editor.
- **M3:** Not started — project ignore regions into datasets and verify loss and metric behavior.

## 1. Problem

Some frames contain untidy stacks of face-down cards. Several card edges can be visible, but the
frame does not support a reliable instance count or one reviewed visible region for each physical
card. Gemini can return several overlapping or partial polygons for the stack. Correcting all of
them by hand is costly and would still create uncertain instance targets.

The current visible-card contract has only card candidates. Each candidate has a `card_id`, a side,
and geometry. It asserts one card instance. Marking a stack candidate as `face_down` or identity
unusable does not solve the localization problem:

- `face_down` describes the observed side of one card;
- identity usability controls visual identity processing, not detector supervision; and
- removing uncertain candidates while keeping the frame would turn the stack pixels into false
  background during training.

Whole-frame exclusion is safe but wastes clear cards elsewhere in the frame. The reviewed data
needs a region-level ignore concept.

## 2. Decisions

### 2.1 An ignore region is not a card

Add a **visible-card ignore region** as a sibling of `candidates` in each reviewed visible-card
outcome. It is a reviewed annotation region with this minimum content:

```json
{
  "region_id": "ignore-region-001",
  "geometry": {
    "kind": "reviewed-ignore-region/v1",
    "polygons": []
  },
  "normalization": {
    "width": 1920,
    "height": 1080,
    "policy_id": "full-frame-0-1000/v1"
  },
  "reason": "untidy_stack",
  "source_candidates": [
    {
      "revision_id": "visible-cards-run-001",
      "card_id": "generated-card-003"
    }
  ]
}
```

The exact field layout is frozen in M0. The contract must preserve these semantics:

- an ignore region has a `region_id`, not a `card_id`;
- it has no card side, visual identity, model score, or physical-card count;
- it is not an observed card and never reaches identity classification, table observations, or
  reconstruction;
- `untidy_stack` is an ignore reason, not a model class; and
- `source_candidates` records the generated revision and candidate ID for each proposal that the
  reviewer replaced. An empty list is valid for a region drawn without proposals.

Generated provider output remains immutable. A generated result does not change when a reviewer
uses its polygons to create an ignore region. New generated outcomes contain no reviewed ignore
regions.

Revise the active visible-card data contract directly. Do not add a second parallel review
resource or hide ignore-region state in notes. Current selected references that need ignore regions
must be reviewed and published under the new contract before dataset use.

### 2.2 One region represents one ambiguous stack area

Create one reviewed ignore region for each spatially connected untidy stack. Merge the selected
Gemini proposal geometry into that region. Do not retain several reviewed regions merely because
Gemini returned several candidates.

One ignore region can contain more than one polygon only when one physical stack area has
disconnected visible parts. Separate stack areas use separate region IDs. The reviewer needs only a
conservative boundary around the ambiguous card pixels. The reviewer does not trace, count, order,
or infer hidden cards.

Effective supervision must not assign the same pixel to a card target and an ignore mask. When a
clear card is kept as a normal candidate near a stack, its reviewed visible pixels take precedence.
Dataset materialization subtracts normal target pixels from the effective ignore mask. This permits
a conservative, low-effort ignore boundary without discarding a clear neighboring target. Contract
validation rejects duplicate identifiers and invalid or empty geometry. The materializer rejects
an ignore region whose effective mask becomes empty.

### 2.3 Mixed frames remain useful

A reviewed frame can contain:

- card candidates only;
- ignore regions only;
- both card candidates and ignore regions; or
- neither, when it is a reviewed empty frame.

An ignore-only frame is not empty and not failed. Review coverage records that the frame contains
ignored visible-card evidence. Completion requires a decision for every generated candidate: keep
it as a card, correct it as a card, remove it as false, or consume it into an ignore region.

Changing an ignore region does not create visual-identity review work. Changing or removing a real
card candidate keeps the existing downstream impact behavior.

### 2.4 Dataset use is explicit

The visible-card dataset projection carries normal card targets and ignore regions separately. An
ignore region is never emitted as a `visible_card` target or as an `untidy_stack` target.

Each dataset consumer declares one frozen ignore policy:

```text
mask_pixels   -> retain the frame and omit ignored pixels from loss
exclude_frame -> omit the complete frame and record the exclusion
```

There is no implicit fallback. A consumer that supports neither policy must reject a dataset that
contains ignore regions. The materialized dataset records the source region, raster policy, output
mask digest, and effective ignored-pixel count. Normal target pixels take precedence, and the
materializer verifies that the final target and ignore masks do not overlap.

For evaluation, predictions that overlap an ignore region by the frozen threshold are neither true
positives nor false positives. Metrics still evaluate normal reviewed card targets in the same
frame. Reports count ignored frames, regions, pixels, and neutralized predictions so that ignored
data cannot silently improve a score.

This epic supplies the reviewed contract and safe dataset projection. It does not implement or
train a new segmenter. A later provider experiment can consume the masks through epic 0050.

## 3. Operator workflow

Extend the existing visible-card review workspace. The main path is:

1. Select the Gemini candidates that refer to one untidy stack.
2. Choose **Convert to ignore region**.
3. Confirm `untidy_stack` as the reason.
4. Adjust the combined boundary only when necessary.
5. Save and continue reviewing the remaining cards in the frame.

The conversion removes the selected candidates from the maintained reference and adds one ignore
region. It does not modify the generated revision. The command is one atomic review operation, so a
reload, conflict, or retry cannot leave both forms active.

The editor also supports drawing an ignore region without selecting a proposal, adding or removing
polygons within the same region, deleting the region, and restoring the generated suggestions for
the frame. Use a distinct neutral overlay and label. Do not present ignore regions in card counts or
identity actions.

## 4. Scope

In scope:

- the canonical glossary term and active visible-card pipeline data contract;
- strict ignore-region geometry, normalization, reason, and source-lineage validation;
- maintained-reference commands, drafts, coverage, completion, and impact rules;
- web review editing, conversion, rendering, retry, conflict, and accessibility behavior;
- visible-card dataset manifests, materialized ignore masks, frame exclusion, and comparison
  handling; and
- focused fixtures plus an `IMG_0661` workflow exercise.

Out of scope:

- a model class for `untidy_stack` or another kind of clutter;
- estimation of card count, stacking order, hidden geometry, or physical-card identity;
- changes to Gemini prompting or generated proposal semantics;
- visual-identity classification, observation assembly, game rules, or reconstruction;
- training, selecting, or promoting a detector or segmenter; and
- general-purpose semantic segmentation annotation.

## 5. Delivery milestones

### M0 — Define the reviewed ignore-region contract

- Freeze the canonical visible-card ignore-region glossary term in the active contract.
- Add the sibling `ignored_regions` collection, the distinct `reviewed-ignore-region/v1` geometry,
  and the strict `untidy_stack` region contract.
- Define mixed, ignore-only, and empty frame invariants.
- Define deterministic polygon rasterization and target-overlap validation.
- Define source-revision and source-candidate lineage plus canonical serialization.
- Replace active fixtures and API schemas with the new contract. Do not add a compatibility write
  path.

Acceptance:

- a card candidate and an ignore region cannot be confused by identifiers or fields;
- `untidy_stack` cannot enter the card class map, card counts, or identity inputs;
- malformed, duplicate, empty, and out-of-range regions are rejected;
- canonical bytes include ignore geometry and source lineage; and
- TableEvidenceAnalyzer, operations, backend, and generated-client contract tests pass.

### M1 — Add durable reference operations

- Add atomic create, replace, and delete operations for ignore regions.
- Add one atomic operation that consumes selected card candidates into one ignore region.
- Preserve the generated source revision and record every consumed candidate reference.
- Permit mixed and ignore-only reviewed frames without calling them empty or failed.
- Require every generated candidate to have a resolved review disposition before completion.
- Keep card-candidate downstream impact checks and exclude ignore regions from visual-identity
  impact.

Acceptance:

- conversion cannot leave a selected candidate both active and ignored;
- command retry is idempotent and ordered-command conflict recovery remains safe;
- completed coverage distinguishes cards, ignored evidence, empty frames, and unusable frames;
- reopen, revise, complete, and reload preserve every ignore region; and
- focused backend and operations reference tests pass.

### M2 — Add the visible-card review workflow

- Add multi-select for card candidates in one frame.
- Add **Convert to ignore region** with the fixed `untidy_stack` reason.
- Reuse the polygon editor for create, reshape, multi-polygon edit, and delete operations.
- Render ignore regions separately from card candidates in the video surface, inspector, and
  Timeline Rail state.
- Exclude ignore regions from proposal counts, card side controls, and identity actions.
- Preserve optimistic saves, retry, conflict recovery, keyboard access, and narrow layouts.

Acceptance:

- the operator can convert several Gemini polygons into one region with one action;
- the generated revision remains visible and unchanged in history;
- normal cards in the same frame remain editable and countable;
- reload and browser recovery show the saved region exactly once; and
- web unit, type, lint, format, generated-client, and focused browser checks pass.

### M3 — Make dataset and evaluation behavior safe

- Project normal targets and ignore regions separately from completed maintained references.
- Require each visible-card dataset request to select `mask_pixels` or `exclude_frame`.
- Materialize deterministic loss masks for `mask_pixels` and explicit exclusion receipts for
  `exclude_frame`.
- Reject unsupported consumers instead of treating ignored pixels as background.
- Neutralize predictions over ignored regions in visible-card comparison while reporting their
  counts.
- Exercise the complete review and dataset path with fixtures and at least one untidy stack from
  `IMG_0661`.

Acceptance:

- ignored pixels are absent from positive and background loss under `mask_pixels`;
- `exclude_frame` produces no sample and records the exact source-frame reason;
- clear card targets in a mixed frame remain in the materialized dataset;
- ignored predictions cannot improve or reduce instance metrics silently;
- the `IMG_0661` exercise preserves the generated proposals and produces one reviewed ignore
  region with complete lineage; and
- relevant automated tests, static checks, reproducibility checks, and local Markdown link checks
  pass.

## 6. Delivery handoff

After M3, resume epic 0051 only with visible-card references that use the ignore-region contract.
Its identity baseline excludes ignore regions because they have no card identity target. Epic 0050
can later use the frozen masks in a bounded detector or segmenter comparison. Neither epic may
reinterpret an ignore region as a card instance or as ordinary background.
