# Table Observation and Game Reconstruction

## Status

This document defines the target architecture and the order in which to build it. The active epics
own implementation details. Update this document when an active epic changes the shared boundary.

## 1. Decision summary

DokoDetector does not require the TableEvidenceAnalyzer to produce an authoritative sequence of card
plays. The analyzer turns supplied evidence packages into an ordered stream of uncertain table
observations. Game reconstruction uses those observations, round rules, deck limits, and human
correction constraints to infer card plays and tricks.

CardEventNet remains an event-proposal model. An event proposal can trigger evidence capture. It is
not proof that a card play occurred. False proposals can produce repeated observations. A missed
proposal can produce a missing observation.

The first useful boundary stays small. Each table observation contains anonymous observed cards and
ranked visual card identity candidates. Later TableEvidenceAnalyzer versions can add soft visual
evidence:

- probability that an observed card exists;
- score that a card became newly visible;
- score that a card is in the active table area;
- possible associations with observed cards from an earlier observation;
- short card tracklets derived from a video snippet.

The reconstruction engine does not consume pixels, boxes, corners, or optical flow. The
TableEvidenceAnalyzer can use all of them internally.

## 2. Target process

```text
camera frames
  -> CardEventNet event proposals
  -> selected frames and a bounded video snippet
  -> immutable evidence package
  -> TableEvidenceAnalyzer inspection and short-term visual analysis
  -> ordered table observations
  -> reconstruction hypotheses constrained by the deterministic rules core
  -> resolved round or focused alternatives
  -> optional human correction constraints
  -> reviewed reconstruction
```

Keep these responsibilities separate.

### CardEventNet

- Reports time-bounded event proposals.
- Optimizes capture attention and cost.
- Does not classify the card or declare a card play.

### Evidence capture and backend

- Preserve selected frames for simple recognition, diagnostics, and fallback.
- Add a bounded video snippet for movement and occlusion analysis.
- Preserve immutable bytes, timing, hashes, and capture configuration.
- Allow an evidence package without a usable snippet.

### TableEvidenceAnalyzer

- Detect visible card proposals in the supplied visual evidence.
- Rank visual card identities for each observed card.
- Compare pre-event and post-event evidence.
- Add optional visual scores and card tracklets.
- Remain free of players, turns, legal moves, deck counts, and round rules.

The TableEvidenceAnalyzer is handed an evidence package. It can combine several models with
classical image processing, matching, geometry, and tracking. It can also use bounded earlier table
observations or overlapping visual evidence. It does not capture evidence and must not use game
state.

### Game reconstruction

- Preserve the ordered raw table observations.
- Infer persistent cards, card plays, trick clearing, and observation errors.
- Apply deck multiplicity, turn order, following rules, and trick rules.
- Rank reconstruction hypotheses without converting visual scores into false calibrated confidence.
- Return focused differences when several hypotheses remain valid.
- Apply immutable human correction constraints and recompute the result.

The deterministic rules core is a dependency of reconstruction. It does not perform visual
tracking or observation deduplication.

## 3. Evidence contract target

A future evidence-package version adds one optional bounded video snippet to the selected frames.
The exact container, codec, duration, frame rate, and resolution come from the measurements in plan
0025.

The snippet metadata must contain:

```text
part name
event-relative start and end
duration
container and codec
width and height
nominal frame rate, when known
byte length and SHA-256
capture completeness
```

The backend verifies the declared bytes and that the supported media can be decoded. It preserves
the original bytes. Tests use a small checked-in media fixture and do not require a phone.

Selected frames remain part of the evidence package. A consumer must not require the optional
snippet unless its declared capability requires it.

## 4. Table-observation contract target

Use a new schema such as `table-observation/v1`. It replaces `vision-detection/v1` in active code and
fixtures. The closed plan 0005 remains the historical record. Do not maintain two runtime paths for
these undeployed local contracts.

An illustrative result is:

```json
{
  "schema_version": "table-observation/v1",
  "observation_id": "...",
  "source": {
    "package_id": "...",
    "snippet_part_name": "event_snippet"
  },
  "session": {
    "session_id": "...",
    "event_sequence": 17
  },
  "observed_at_ms": 42125,
  "status": "observed",
  "capabilities": [
    "identity_candidates",
    "presence_score",
    "newly_visible_score",
    "active_area_score"
  ],
  "cards": [
    {
      "observed_card_id": "observation-17-card-01",
      "identity_candidates": [
        {"card": "HEARTS_10", "probability": 0.8},
        {"card": "HEARTS_KING", "probability": 0.2}
      ],
      "presence_score": 0.97,
      "newly_visible_score": 0.91,
      "active_area_score": 0.86,
      "association_candidates": []
    }
  ],
  "calibration": "uncalibrated",
  "analyzer": {"name": "...", "version": "..."},
  "diagnostics": {}
}
```

The exact schema is frozen in plan 0006. Apply these semantic rules:

- `cards: []` means that the TableEvidenceAnalyzer detected no cards. It does not prove that the table was
  empty.
- `insufficient_evidence` remains distinct from an observed empty card list.
- An observed card is anonymous outside its table observation.
- Identity candidates are conditional on the proposal being a card.
- `presence_score` represents the separate possibility of a false card proposal.
- Optional evidence is absent when it is unavailable. Absence never means a score of zero.
- Association candidates and card tracklets remain uncertain. They never identify a physical copy.
- Scores in the interval from zero to one are not calibrated probabilities unless held-out evidence
  proves calibration.
- Raw evidence and earlier result versions remain unchanged.

Geometry can stay inside the TableEvidenceAnalyzer. The engine-facing `active_area_score` or
normalized distance is sufficient for the first spatial experiment. Do not add game-specific labels
such as `captured_fox` to the visual contract.

## 5. Reconstruction input and result

The round input contains:

```text
ruleset and deck manifest
game and round identifiers
active players, dealer, and first trick leader
ordered table observations
optional correction constraints
reconstruction configuration and evidence-feature weights
```

The engine treats card plays, persistent table state, observation-to-card association, trick
clearing, and missing plays as latent values.

The result contains:

```text
status: resolved | ambiguous | impossible | incomplete
ranked reconstruction hypotheses
selected card plays and tricks for each retained hypothesis
focused decisions that differ between hypotheses
source observation and evidence references
applied correction constraints
rejected alternatives and rule conflicts
search limits and calibration labels
```

One missing card play can become unique when every other card and its missing slot are known. Two
known missing cards in two known slots allow at most two assignments. More hypotheses can exist when
the missing slots or other observations are also uncertain. The engine must merge hypotheses that
produce the same gameplay result.

## 6. Human correction contract

Human review is part of the target design. Do not treat it as a production-only fallback.

The review UI should first ask about the smallest unresolved decision, for example:

```text
Trick 1, Niklas's card play:
HEARTS_10 or HEARTS_KING?
```

It can also offer a complete round editor. Supported corrections include:

- choose a card identity;
- assign or change the active player;
- insert or delete a card play;
- change card-play order;
- mark an observation as irrelevant;
- associate or separate two observed cards;
- set a trick boundary;
- replace the complete card-play sequence.

Store each correction as an immutable constraint with reviewer provenance. Re-run reconstruction
after a correction. Do not overwrite the table observations or the earlier machine result. Show a
clear conflict if a correction violates the selected ruleset or deck manifest.

## 7. Additive implementation order

Implement the smallest end-to-end slice first. Add one evidence family at a time.

### Step 0 — Contracts, rules, and synthetic truth

Freeze deck manifests, the minimal table-observation schema, the reconstruction result, and the
correction-constraint shape. Implement the deterministic rules core. Generate legal synthetic
rounds and exact identity-only table observations.

This step requires no model, video, phone, network, or GPU.

### Step 1 — Identity-only reconstruction

Reconstruct small scenarios from anonymous observed cards with identity candidate distributions.
Cover repeated observations, empty observations, false event proposals, missing plays, and
ambiguous identities. Use exhaustive search as the correctness oracle.

### Step 2 — Presence evidence

Add optional `presence_score`. Test false card proposals and duplicate detections. Compare results
with and without the feature.

### Step 3 — Transition evidence

Add optional `newly_visible_score` and simple predecessor associations from selected frames. Test
reappearance after occlusion and movement of an existing card. Do not require video tracking yet.

### Step 4 — Spatial evidence

Add optional `active_area_score` or normalized active-area distance. Test side piles, cards retained
for scoring, and old tricks shown outside the active area.

### Step 5 — Video snippets and card tracklets

Add bounded snippet capture and storage. Derive short card tracklets inside the
TableEvidenceAnalyzer. Add optional association and movement evidence to the same table-observation
contract.

Plan 0025 can implement snippet transport in parallel with steps 0 through 4. Step 5 controls when
reconstruction begins to depend on derived tracklet evidence, not when transport work can start.

### Step 6 — Scalable reconstruction

Compare beam search, hypothesis merging, and targeted backtracking against the exhaustive oracle.
Scale from bounded scenarios to complete uncertain rounds and games.

### Step 7 — Human review

Measure unresolved decisions. Build focused questions first. Add the complete editor and reviewed
reconstruction lifecycle after the correction contract is proven with fixtures.

## 8. Rules for independent improvements

Each new evidence family must obey these rules:

1. Declare a capability in the observation result.
2. Keep the field optional for consumers that support an earlier capability set.
3. Treat a missing field as unavailable, not negative evidence.
4. Add a synthetic scenario in which the feature helps and one in which it can mislead.
5. Run an ablation that compares reconstruction with and without the feature.
6. Preserve raw visual evidence and all derived outputs.
7. Version feature semantics, preprocessing, and model bundles.
8. Do not multiply correlated visual scores as if they were independent calibrated probabilities.
9. Keep deterministic rule rejection separate from visual ranking.
10. Allow the result to remain ambiguous.

These rules let identity recognition, presence estimation, transition comparison, spatial evidence,
and tracking improve independently.

## 9. Plan ownership

- [Plan 0006](plans/3-in-progress/0006-GameEngine_v1.md) owns the shared observation-to-reconstruction
  contract, rules core, synthetic generator, and exhaustive oracle.
- [Plan 0020](plans/5-closed/0020-Data_Foundation.md) owns source lineage and reviewed annotation
  data for observed cards, snippets, and tracklets.
- [Plan 0021](plans/2-ready/0021-Table_Evidence_Analyzer_Training_Pipeline.md) owns reusable model
  training, evaluation, export, and capability metadata.
- [Plan 0025](plans/2-ready/0025-Video_Snippet_Evidence.md) owns iOS and backend video-snippet
  evidence transport.
- [Plan 0022](plans/0-to-specify/0022-Table_Evidence_Analyzer_Development.md) will select measured
  visible-card, transition, spatial, and tracking methods for the TableEvidenceAnalyzer.
- [Plan 0023](plans/0-to-specify/0023-Game_Reconstruction_Development.md) will scale reconstruction
  from the oracle to complete rounds and games.
- [Plan 0026](plans/0-to-specify/0026-Reconstruction_Review_Workflow.md) will define the human
  reconstruction-review workflow after ambiguity measurements exist.
- [Plan 0024](plans/0-to-specify/0024-System_Production_Readiness.md) will select production work from
  measured end-to-end requirements.
