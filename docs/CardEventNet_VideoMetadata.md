# CardEventNet video metadata

## Purpose

Use one metadata record for each original video. The record identifies the source, groups related
videos, and describes dataset coverage. Keep the original video unchanged.

The canonical machine-readable contract is
[`video-metadata-v1.schema.json`](../card_event_net/schemas/video-metadata-v1.schema.json). The
repository also contains a complete
[`dataset-manifest.example.yaml`](../card_event_net/data/dataset-manifest.example.yaml).

## Name for the current recordings

Use **staged trick sequence** for a video in which a person deliberately plays repeated groups of
four cards without playing a real game. Use `staged_trick_sequence` as the `content_type` value.

Do not call this footage artificial or synthetic. The images, camera, lighting, hands, cards, and
table are real. The sequence and timing are staged.

The current staged trick sequences provide useful visual diversity:

- realistic phones and cameras;
- different camera views;
- different lighting and backgrounds;
- different card positions.

They do not represent the full game domain:

- the play cadence is regular;
- pauses between tricks are shorter than many game pauses;
- separate plays do not overlap enough;
- mistakes and corrections are rare;
- one actor moves the cards;
- no game decisions occur.

Record these differences in `known_limitations`. Do not infer them later from a file name.

## Identifier rules

`video_id` is the stable dataset identifier. Do not change it when a file moves or is renamed.

`session_id` groups footage that can leak visual or behavioral information across dataset splits.
Give videos the same `session_id` when they come from the same recording period, players, and
physical setup. If uncertain, keep the videos in the same session. Train, validation, and test
splits must not share a session.

`game_id` identifies one real game. Use `null` for staged footage. Every `real_game` record must
have a `game_id`. Several camera files can have the same game ID.

`table_setup` identifies a repeatable physical setup. Create a new value after a material change
to the camera pose, table surface, background, or deck. Lighting remains a separate field because
it can change during one setup.

## Field definitions

| Field | Meaning |
| --- | --- |
| `schema_version` | Contract identifier. V1 is `cardevent-video-metadata/v1`. |
| `video_id` | Stable, unique video identifier without path semantics. |
| `file_name` | Name of the registered original file. |
| `content_type` | `real_game`, `staged_trick_sequence`, `staged_scenario`, `synthetic_render`, or `other`. |
| `session_id` | Leakage group used for dataset splits. |
| `game_id` | Real game identifier, or `null` for footage that is not a real game. |
| `recording_date` | ISO date or timestamp with a UTC offset. Use `null` only when unknown. |
| `device` | Device manufacturer and model, for example `Apple iPhone 14`. |
| `camera` | Physical camera or lens, for example `rear_wide`. |
| `resolution` | Stored source size in `WIDTHxHEIGHT` form. |
| `frame_rate` | Measured average source frame rate. |
| `duration_s` | Measured source duration in seconds. |
| `orientation` | `portrait`, `landscape`, `square`, or `other`. |
| `camera_view` | `overhead`, `high_oblique`, `low_oblique`, `side_oblique`, or `other`. |
| `camera_motion` | `fixed`, `handheld_static`, `handheld_moving`, or `other`. |
| `camera_framing` | `table_fills_frame`, `table_with_context`, `wide_context`, or `other`. |
| `table_setup` | Stable setup identifier. |
| `lighting` | One or more controlled lighting tags. |
| `background` | Short description of the visible surface and nearby objects. |
| `card_deck` | Stable deck or deck-design identifier. |
| `scenario_tags` | Situations that are visibly present in the video. |
| `known_limitations` | Known domain gaps in staged or restricted footage. |
| `source` | How the project obtained the video. |
| `source_permission` | Allowed use: training only, training and evaluation, project use, or unrestricted. |
| `annotation_version` | Annotation release identifier, or `null` before review. |
| `notes` | Optional facts that do not fit a controlled field. |

The technical fields can be `null` before ingestion has measured them. The key must still be
present in a V1 record. Do not guess an unknown value.

## Scenario tags

Tags describe visible evidence. Add a tag only when the video contains the situation. The V1 tags
cover:

- normal and rapid card plays;
- long pauses and overlapping plays;
- a trick collected while a card is played;
- a card played face down and later turned face up;
- collected tricks that stay visible;
- a scoring card that stays next to collected tricks;
- withdrawals, repositioning, dropped cards, and returned old cards.

Use `other_anomaly` only when no specific tag applies. Explain it in `notes`.

## Data collection priority

Do not add only more staged trick sequences. Collect independent real-game sessions and targeted
staged scenarios. Give priority to:

1. irregular and long pauses;
2. plays that overlap each other;
3. the fourth card and trick collection as one continuous action;
4. face-down cards and later corrections;
5. visible collected trick stacks;
6. scoring cards left next to a stack;
7. withdrawals, drops, and other mistakes.

Keep real games and targeted staged scenarios as separate `content_type` values. This makes
per-domain diagnostics possible.

## Full-frame input

CardEventNet's target input is the complete oriented camera frame. Do not use a manually selected
ROI as semantic metadata. Use `camera_framing` to measure how much context is visible.

Most current recordings use `table_fills_frame`. Add `table_with_context` and `wide_context`
footage before claiming general full-frame robustness. Include hands, held cards, drinks, score
sheets, and people at the frame edges. These are important full-frame negatives.
