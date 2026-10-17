# Epic 0098 M3 identity review queue

Status: complete. Human identity review remains pending.

## Frozen queue

- Queue ID: `epic-0098-identity-review-v1`
- Queue digest: `5d54e04850f391ea33e96583de5df81dee93162bc46364290c7fcdcd6847df67`
- Selected frames: 114 of at most 145.
- Recordings with reviewable identity outcomes: 26 of 26.
- Recordings with no reviewable identity outcomes: 0.
- Human review decisions created: 0.
- Selection reasons: `{"deterministic_control": 26, "face_down_prediction": 25, "low_top1_confidence": 61, "low_top1_top2_margin": 42}`.

Each queue item selects one card result from one frame. The URL pins the exact generated revision, card item, and source time in the maintained-reference editor. Selection reasons include low confidence, low top-1/top-2 margin, face-down predictions, diagnostics when present, and one deterministic control when available. The proposal only routes review. It does not establish identity correctness.

## Coverage

| Recording | M6 training overlap | Identity-bearing frames | Queue frames | No reviewable identities |
| --- | ---: | ---: | ---: | --- |
| `5a1f4037-d8ad-48da-9950-2ed2272811a5` | no | 81 | 5 | no |
| `cardeventnet-IMG_0091` | no | 41 | 5 | no |
| `cardeventnet-IMG_0095` | no | 43 | 5 | no |
| `cardeventnet-IMG_0096` | no | 49 | 5 | no |
| `cardeventnet-IMG_0097` | yes | 40 | 5 | no |
| `cardeventnet-IMG_0636` | yes | 40 | 5 | no |
| `cardeventnet-IMG_0637` | yes | 40 | 2 | no |
| `cardeventnet-IMG_0638` | yes | 41 | 5 | no |
| `cardeventnet-IMG_0639` | yes | 40 | 5 | no |
| `cardeventnet-IMG_0640` | yes | 40 | 2 | no |
| `cardeventnet-IMG_0642` | no | 40 | 5 | no |
| `cardeventnet-IMG_0643` | yes | 42 | 3 | no |
| `cardeventnet-IMG_0644` | no | 54 | 5 | no |
| `cardeventnet-IMG_0645` | no | 45 | 5 | no |
| `cardeventnet-IMG_0650` | yes | 29 | 1 | no |
| `cardeventnet-IMG_0651` | yes | 41 | 4 | no |
| `cardeventnet-IMG_0652` | no | 41 | 5 | no |
| `cardeventnet-IMG_0653` | yes | 40 | 5 | no |
| `cardeventnet-IMG_0655` | yes | 43 | 5 | no |
| `cardeventnet-IMG_0657` | no | 42 | 4 | no |
| `cardeventnet-IMG_0658` | yes | 41 | 3 | no |
| `cardeventnet-IMG_0661` | no | 44 | 5 | no |
| `cardeventnet-IMG_0662` | no | 40 | 5 | no |
| `game-2026-09-18-01-001` | no | 55 | 5 | no |
| `game-2026-09-18-01-002` | no | 52 | 5 | no |
| `game-2026-09-18-01-003` | no | 55 | 5 | no |

## Target and draft status

- Current selection pointers: `{"different_from_queue_target": 26}`. The queue URL pins its frozen result revision even when the current pointer names another run.
- Saved draft states: `{"completed": 13, "conflict_preserved": 10, "no_saved_reference_state": 3}`. A draft with a different source revision is marked `conflict_preserved`; inspect it before any edit.
- Live editor backend status: `unavailable` (connection refused at http://127.0.0.1:8001). The builder verified local immutable result artifacts and recorded saved selection and draft state. Confirm editor access before review starts.
- The 0097 queue API is unavailable in this checkout. This report is the documented file-based adapter input. It does not add queue UI.

## Reproduction

```sh
mise exec -- uv run --project operations python operations/scripts/build_0098_m3_identity_review_queue.py --pipeline-store /Users/niklas.sparfeld/Developer/doko_detector/data/operations/pipeline --operations-root /Users/niklas.sparfeld/Developer/doko_detector/data/operations --live-backend-status unavailable --live-backend-reason 'connection refused at http://127.0.0.1:8001'
```

## Frozen inputs

- M0 manifest SHA-256: `38ead572914fc3b5628dad2da2e6bcab8414a44701657b12d6a7428d75a50c0f`
- M1 report SHA-256: `2669f0d439f73448fa126749cacafa0414618dada11a05622a35384c39824586`
- M2 report SHA-256: `1d5ce2f48eff0ec4232c90e94821d9dbee89c2fab5a24358af8ebf7f89d31b42`
- Each `queue_item_id` covers frozen frame selection and result lineage. The `queue_digest` covers the ordered item IDs. Runtime editor and draft status is a separate snapshot.
