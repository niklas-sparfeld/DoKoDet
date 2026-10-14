# Visual classification annotation and crop inputs

## Plan status

- **Summary:** Complete prediction-independent individual-card annotation and reproducible
  25-class crop preparation, including positively visible card backs.
- **Status:** In Progress
- **Depends on:** Completed 0048/0049 review foundation, 0085 crop-input lineage, and 0091 pile
  isolation. Use fixtures and existing reviewed development examples; no dependency on 0086 M5.
- **Outcome:** A working annotation-to-crop path and versioned input handoff for 0086 M5,
  [0094](../4-blocked/0094-DINO_Training_and_Runtime_Recipes.md), and
  [0088](../4-blocked/0088-Reviewed_Virtual_Card_DINO_Campaign.md).
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-10-14) — froze annotation provenance, positive-class eligibility, and
  contract changes.
- **M1:** Complete (2026-10-14) — seed backend review items from exact reviewed geometry and
  crops, and preserve unchanged labels when annotation sources change.
- **M2:** Complete (2026-10-14) — expose annotation and correction without classifier predictions.
- **M3:** Not started — materialize all 25 reviewed visual classes and readiness receipts.
- **M4:** Not started — audit source fidelity and record the rectification decision.
- **M5:** Not started — verify annotation/crop parity and publish the capability handoff.

## 1. Evidence and scope

Visual Identity already has a Face down action with shortcut F and stores a reviewed face_down
decision. It requires an existing item and crop identity. The campaign analyzer excludes those
outcomes, and its materializer rejects FACE_DOWN targets. A 25-class head and a face-down output
type do not establish a usable annotation-to-training path.

The current adapter also sets identity_usable=false for side=face_down. Keep the glossary's
suit/rank identity-usability meaning; define positive visual-classification eligibility separately.
A valid crop showing the back can be an eligible FACE_DOWN example. UNKNOWN, an unreadable face,
and a coarse pile are not substitutes for positive card-back evidence.

This epic implements data and annotation capabilities. It does not require complete corpus review,
train a model, improve browser-preview appearance, modify detector selection, promote a bundle,
or build a second review lifecycle. 0086 owns human corpus decisions; 0088 owns model quality.

Use the [initial crop investigation](../../reports/0088-Crop_and_Input_Size_Investigation.md)
as a diagnostic starting point; M4 extends it with a fixed small development sample.

## 2. M0 contract freeze — 2026-10-14

The current `visual-identity-data/v1` outcome requires classifier metadata. Classified, face-down,
and unusable outcomes also require a crop identity. The maintained visual-identity draft binds to a
generated identity revision through `source_revision_id`; its items come from that revision. Crop
input v1 binds processor crops to one visible-card revision and accepts generated polygons, RF-DETR
segments, or reviewed virtual cards with card-scene lineage. Therefore, a human label cannot be
seeded from a reviewed visible-card reference when no classifier result exists without adding new
provenance fields. Do not encode a human label as a successful classifier result.

Freeze these contract changes before M1:

1. Advance the strict visual-identity reference draft to v2 and add an `annotation_source` object
   with `visible_card_revision_id` and `visible_card_revision_digest`. It names the exact completed
   reviewed visible-card revision. Keep `source_revision_id` for an optional generated identity
   source. The annotation source is independent of the generated selection and uses the existing
   expected-draft-revision guard for mutations.
2. Advance `visual-identity-data` to v2 and add a versioned `annotation_provenance` object to each
   annotation-only identity outcome. It binds `visible_card_revision_id`, its digest, `card_id`, the
   exact `frame_identity`, and the reviewed geometry digest. Allow `classifier: null` only when this
   provenance is present. Keep crop identity required when a positive label depends on source
   pixels. Generated outcomes retain their current classifier and crop-input provenance
   requirements.
3. Advance the strict crop-input manifest and provenance contracts to v2. Add the
   `reviewed_visible_card` input kind. It resolves native source pixels from exact frame identity
   and reviewed geometry, records source revision/content and geometry digests, and uses the
   `oracle_visible_region` policy for visible-support masking. It must not require a virtual card
   scene or a processor run. Reuse existing crop receipts and derived view validation; do not add a
   silent crop-kind fallback.
4. Define positive eligibility separately from suit/rank identity usability. A usable crop with a
   reviewed canonical face-up identity is an identity target. A usable crop with a positively
   reviewed visible back is a `FACE_DOWN` target. Unknown side, unreadable identity, source problem,
   unavailable pixels, and pile evidence are not positive targets. A calibrated manual individual
   card follows the same rule as a detector-suggested card.

Freeze these M1 fixture outcomes:

| Fixture | Seed or label behavior | Positive target |
| --- | --- | --- |
| Face-up card with known identity | Seed pending; accept or correct the canonical identity | Yes |
| Positively visible card back | Seed pending; set or correct `FACE_DOWN` | Yes, `FACE_DOWN` |
| Unreadable face | Keep actionable for review or source diagnosis | No |
| Missing source pixels | Keep actionable as a source problem; preserve exact lineage | No |
| Changed reviewed geometry | Mark affected work for review; retain unchanged human decisions | No until current geometry is reviewed |
| Calibrated manual individual card | Seed from the exact reviewed reference without a detector proposal | Same rule as a face-up card or back |
| Pile or consumed pile member | Do not create an identity item | No |

M1 must also reject a source revision, frame, card, or geometry mismatch; repeated seeding must be
idempotent; and an unavailable classifier must not block annotation. M0 does not authorize a
full-corpus review gate or change the 0086 corpus decisions.

## 3. Rules

Seed pending review items from an exact eligible completed reviewed geometry reference and exact
source-frame crops, even when no identity processor has run or its predictions are unavailable.
Use explicit annotation-source provenance. Do not fabricate a classifier identity, model score,
or successful machine outcome to satisfy existing schema requirements. Reuse maintained reference
commands, optimistic concurrency, undo/correction behavior, and completion coverage.

Require the exact card/frame/reference and source/geometry/crop lineage. Changed geometry makes
affected items review work; unchanged human labels remain intact. No silent input-kind fallback,
matching by guessed identity, or newest-revision selection is permitted. Preserve calibrated manual
cards where they are eligible independently of detector suggestions. Exclude piles and consumed
member proposals before identity item creation.

Apply current source-exclusion guards and the 0086 recording dispositions, including excluded
source digests under renamed recording IDs. Do not revive an excluded source for the diagnostic
pilot or training inventory. A deferred recording requires its explicit readiness decision.

Offer reviewed visual card identity, FACE_DOWN, identity unusable, and source-problem decisions.
Only resolvable individual-card evidence can become a positive training target. Unavailable pixels
remain actionable source/geometry work, not an invented class. Face-down labels must be correctable
to a face-up identity and back without creating duplicate items or discarding provenance.

Materialize human targets and native source-image crops separately from model preprocessing.
Accept reviewed oracle_visible_region lineage without calling it predicted geometry. Remove the
PoC-specific FACE_DOWN and NINE exclusions. Include all eligible positive classes in reports;
incomplete corpus coverage does not block delivery of software capability proven with fixtures.

## 4. Delivery milestones

### M0 — Freeze data contracts and fixtures

Inspect the existing review commands, source-revision bindings, crop adapter, and campaign analyzer.
Specify the smallest explicit annotation-only source binding and positive-class eligibility rule.
Freeze fixtures for a face-up card, visible back, unreadable face, missing pixels, changed geometry,
manual card, and pile. Record the API and schema fields that must change before implementing them.

Acceptance: exact source authority and conflict behavior; no successful classifier is required
for human annotation; FACE_DOWN remains a visual classification rather than a legal identity.
No human review is automatically completed and no full-corpus gate is introduced.

### M1 — Implement backend annotation seeding

Add the frozen source binding and pending-item creation from reviewed individual-card geometry.
Resolve native crops and reuse existing draft persistence and mutation commands. Handle cold/warm
resolution, repeated seeding, unavailable providers, and stale sources explicitly.

Acceptance: API fixtures create and correct a back label without a classifier run; repeated requests
do not duplicate cards; conflicts are visible; existing human decisions and crop lineage survive;
piles create no items. Run focused backend/operations tests and schema checks.

### M1 implementation evidence — 2026-10-14

- Visual-identity drafts now bind to an exact completed visible-card revision and content digest.
  Seeded items carry frame, card, and reviewed-geometry digests. Native crop resolution can seed
  items without classifier output; missing crops remain actionable source problems.
- Annotation-source rebasing rejects stale or non-current visible-card revisions. It preserves
  decisions and verified crop lineage when frame and geometry remain unchanged, and marks changed
  or removed items as affected.
- The API regression seeds a visible back, corrects it to a face-up identity without classifier
  metadata, reports a missing crop, rejects a stale digest, and verifies source-change behavior.
- Focused backend reference/API tests passed (52 tests). Table-evidence crop/data tests passed
  (20 tests), operations pipeline-data tests passed (14 tests), and the web typecheck plus focused
  review tests passed (32 tests). The full web lint still reports existing errors in
  `CardEventFrameSurface.tsx` and a warning in `VisibleCardReviewWorkbenchView.tsx`.

### M2 — Connect the annotation controls

Expose the reviewed source and pending items in the existing Visual Identity review flow. Reuse
identity choices, Face down/F, unusable, and source-problem controls. Make source problems actionable
and preserve read-only/mutation restrictions. Do not add a preview-quality redesign.

Acceptance: a UI regression covers labeling with no predictions, face-down/face-up correction,
save/reload, source changes and unavailable crops. An operator can start or continue review without
a local or Gemini classifier. Publish this early capability for 0086 M5.

### M2 implementation evidence — 2026-10-14

- The Visual Identity review can start from the selected completed reviewed visible-card reference.
  The request includes its exact revision digest and creates pending items without a classifier run.
- The inspector identifies the annotation source, distinguishes pending annotation from a source
  problem, and offers a guarded refresh when the selected reviewed source changes. Generated-result
  rebasing and auto-approval do not run on annotation drafts.
- Existing identity, FACE_DOWN, unusable, and source-problem controls remain available. A missing
  crop stays actionable as a source problem. The source image and crop stay attached to the exact
  reviewed card item.
- UI regressions cover source seeding, classifier-free FACE_DOWN review, save/reload, correction to
  a face-up identity, changed-source refresh, and missing-crop handling. Web typecheck passed, the
  focused editor suite passed (22 tests), and targeted ESLint passed.

### M3 — Materialize all positive visual classes

Adapt the reusable crop inventory and readiness report to reviewed labels and annotation-only
sources. Export native crops, exact visible-support masks and targets for all 24 identities plus
FACE_DOWN. Do not reconstruct masks from grey RGB values. Keep source grouping,
exact source/frame/card matching, and per-reason exclusions. Do not change human reference content
during preparation. Replace the test that currently requires FACE_DOWN exclusion.

Acceptance: a reviewed back yields a FACE_DOWN target and reproducible crop bytes; wrong frame,
stale geometry, unreadable evidence and piles cannot become targets. Report independent recording,
class/back-design support and duplicates; cold/warm digests match. Publish the 0086 M5 report adapter.

### M4 — Audit crop fidelity and rectification risk

Use at most 24 eligible development crops from at most three recordings, including incomplete
visibility and available/incorrect/unavailable geometry. Compare current JPEG frame extraction with
lossless decode and compare Lanczos, area and bicubic reductions at equal dimensions. Inspect small
rank/suit marks, mask support, neutral fill, and actual pixel occupancy. Use exact timestamps.

Where validated poses exist, produce one offline rectified comparison from a composed transform
of the original frame and visible mask. Preserve physical aspect ratio, hidden-pixel fill, and
180-degree ambiguity. Record failures and the need for antialiasing; do not turn failed geometry
into excluded success cases or infer missing card content.

Acceptance: bounded diagnostic receipts, timings, input digests, and a written decision. Retain
native source-image crops/Lanczos by default. Specify any justified decoder/filter follow-up as a
separate bounded implementation before campaign fitting. No classifier-quality claim follows
from appearance alone, and no runtime rectification policy or mandatory geometry gate is added.

### M5 — Verify and publish the input handoff

Replay the annotation-to-materialization path on fixtures and a few existing reviewed development
items. Verify source/frame/geometry lineage, correction persistence, native crop integrity, and
individual-card/pile isolation. Publish exact contracts, class support limits and executable commands.

Acceptance: 0086 can finish face-down review; 0094 can consume eligible back crops and targets;
0088 can audit and freeze its corpus. Capability readiness is separate from the amount of reviewed
data. No training or default/provider change occurs.

## 5. Verification

Run focused reference command/API/UI tests, crop materialization and lineage checks, and applicable
Python/Web static checks. Use fixtures for missing/failed inference and invalid geometry. Verify
fresh and resumed review commands do not overwrite unrelated human decisions. Keep protected final
test and system-holdout inputs out of the diagnostic pilot.
