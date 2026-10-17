# 0090 M3 composed pilot

## Result

The frozen local pilot ran once on all three recordings. Event, visible-card and pile, and
proposed-scene outputs were retained. Each recording stopped after the scene stage reported a
partial result. The coordinator did not run identity or table-observation inference. Reconstruction
did not run because the scenes were partial. The real round also lacks explicit player and dealer
context, so its frozen reconstruction request was a skip.

The pilot produced no composed quality claim. Event quality is measurable against the frozen event
references. Geometry references have no exact frame identities in common with the automatic
detector outputs, so the pilot cannot score visible-card or pile geometry. Identity, table
observation, and reconstruction quality have no execution and no score.

## Frozen inputs and models

The batch and policy are from the [M0 freeze](0090-M0_Composed_Pilot_Freeze.md), source revision
`41532a756`. Preflight returned `ready`. It verified the source hashes, reference revisions and
manifests, model bundles, and local provider settings. The three request files and preflight record
were kept under the ignored `.runtime/0090-m3/` directory.

| Recording | Source SHA-256 | Reviewed event revision | Reviewed geometry revision |
| --- | --- | --- | --- |
| `cardeventnet-IMG_0657` | `23df5b4dbf0d0d80c79161ba32c1f4c4db8473f053fdd9b63508c66e38d3658b` | `reference-events-17e0b4ea8fc84cec099e237467798fdd` | `reference-visible_cards-9825ffb099bab16c735b114ec4c4050a` |
| `cardeventnet-IMG_0662` | `2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7` | `reference-events-fd5c08dc4f7540053b3ed1c04606b909` | `reference-visible_cards-bf287d3bff82dec774f16be1ccc736f0` |
| `game-2026-08-20-01-001` | `2464d0e65547b2db31ea5ca49f4d57cefcb999e34cbacec7e7cca8ee9d549faa` | `reference-events-e22b24bde3ef35a56ab930873b2200cc` | `reference-visible_cards-25c56fb38af9a5604283bbc57789e690` |

The run used the frozen CardEventNet checkpoint `258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4`, at threshold `0.4271905720233917`, with a `0.625 s` merge window. Event matching used the frozen `0.75 s` tolerance and end anchor.

The detector used the 0092 M4 RF-DETR bundle (`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`), with `visible_card` and `card_pile` classes. The 0088 M6 DINO bundle was pinned (`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`) with the frozen predicted-visible-region PPM crop policy. The identity stage did not start, so it made no predictions. M6 remains unqualified and cannot support production use.

The run used local providers only. It made no cloud requests, used no Gemini fallback, and did no
training, tuning, or promotion. No reviewed scene or reference was an execution input.

## Event results

The event comparison used the official pipeline event matching implementation and the frozen
end-anchor tolerance. Precision and recall below count one-to-one event matches.

| Recording | Reviewed | Predicted | Matched | Missed | Extra | Precision | Recall | F1 | Mean / max anchor error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cardeventnet-IMG_0657` | 51 | 52 | 48 | 3 | 4 | 0.923 | 0.941 | 0.932 | 172 / 687 ms |
| `cardeventnet-IMG_0662` | 50 | 52 | 42 | 8 | 10 | 0.808 | 0.840 | 0.824 | 161 / 656 ms |
| `game-2026-08-20-01-001` | 49 | 43 | 39 | 10 | 4 | 0.907 | 0.796 | 0.848 | 241 / 517 ms |

## Stage results and retained artifacts

All run IDs below are processor run IDs. Each run has its request and state under
`data/operations/pipeline/runs/<run-id>/`. Each output revision has a manifest and content under
`data/operations/pipeline/revisions/<revision-id>/`.

| Recording | Coordinator | Event run / revision | Detector run / revision | Scene run / revision | Scene result |
| --- | --- | --- | --- | --- | --- |
| `cardeventnet-IMG_0657` | `0090-cardeventnet-img-0657-a43548b3ea42` | `coord-d991572cdb65618247c1` / `events-coord-d991572cdb65618247c1-attempt-1` | `coord-07d852bb91cfc6b19f7a` / `visible-cards-coord-07d852bb91cfc6b19f7a-attempt-1` | `coord-3c10c8bdaa3a72b0c361` / `card-scene-proposals-coord-3c10c8bdaa3a72b0c361-attempt-1` | Partial: 43 supported, 9 unsupported |
| `cardeventnet-IMG_0662` | `0090-cardeventnet-img-0662-a43548b3ea42` | `coord-08c097cc5f1b4024e867` / `events-coord-08c097cc5f1b4024e867-attempt-1` | `coord-aa2ab2751f97e23f4dd2` / `visible-cards-coord-aa2ab2751f97e23f4dd2-attempt-1` | `coord-20c6e5e069cd8c74a97b` / `card-scene-proposals-coord-20c6e5e069cd8c74a97b-attempt-1` | Partial: 44 supported, 8 unsupported |
| `game-2026-08-20-01-001` | `0090-game-2026-08-20-01-001-6089e48dc8af` | `coord-adf623bae2f082065bba` / `events-coord-adf623bae2f082065bba-attempt-1` | `coord-d7821eb650044d5b3606` / `visible-cards-coord-d7821eb650044d5b3606-attempt-1` | `coord-d0e13247e47284a18828` / `card-scene-proposals-coord-d0e13247e47284a18828-attempt-1` | Partial: 41 supported, 2 unsupported |

The scene stage marked each unsupported frame with `no model polygon produced an initial
fixed-size card pose`. The coordinator stopped dependent work for each recording. It ran no DINO
identity or table-observation stage. The reconstruction request for the real round specified an
explicit skip because the source record has no active players, dealer, or first-trick leader. The
coordinator stopped before that stage and retained no reconstruction result.

| Recording | Event time | Detector time | Scene time | Detector output | Reviewed geometry coverage |
| --- | ---: | ---: | ---: | --- | --- |
| `cardeventnet-IMG_0657` | 25.1 s | 13.0 s | 67.5 s | 113 card candidates; 1 pile region | 52 predicted frames, 51 reviewed frames, 0 exact frame identities; 117 reviewed cards |
| `cardeventnet-IMG_0662` | 26.0 s | 12.7 s | 36.8 s | 104 card candidates; 85 pile regions | 52 predicted frames, 50 reviewed frames, 0 exact frame identities; 109 reviewed cards and 70 pile regions |
| `game-2026-08-20-01-001` | 101.6 s | 31.2 s | 227.9 s | 105 card candidates; 21 pile regions | 43 predicted frames, 49 reviewed frames, 0 exact frame identities; 226 reviewed cards |

Detector counts are raw retained proposals. They are not accuracy measurements. The frozen
polygon-IoU threshold is `0.5`, but no reviewed frame can be paired to a predicted frame by exact
frame identity. The geometry score is therefore unavailable for all recordings, including the
known no-match case. Do not read the candidate counts as matched cards or piles.

## Operations and limits

The first processor run started at `2026-10-17T05:44:26Z`; the last scene run ended at
`2026-10-17T05:55:38Z`. Batch wall time was about 11 minutes 12 seconds, within the frozen
6-hour limit. The backend process used at most 2.33 GiB resident memory in one-second samples,
within the 32 GiB process limit. The pilot used zero cloud requests, within the frozen limit.

There were no manual labels, scene edits, or proposal corrections during execution. Operator work
was limited to preflight, local server setup, three coordinator commands, and result measurement.
No retry or alternate model run occurred.

## Follow-up

Use exact-frame reviewed coverage or add eligible reviewed geometry before making detector quality
claims. Diagnose why the scene initializer rejects detector outputs on the unsupported frames.
Keep identity, observation, and reconstruction measurement behind a complete scene result. Do not
promote M6 or change production defaults from this pilot.
