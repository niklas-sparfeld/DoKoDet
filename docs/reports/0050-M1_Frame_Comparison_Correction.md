# 0050 M1 frame comparison correction

Date: 2026-10-17

## Result

M1 corrects decoded-image pairing for retained detector results and measures geometry only on paired images. The comparison key now ignores `requested_time_us`; every other frame identity field remains exact. Comparison items preserve the full reference and prediction identities and both event IDs.

The corrected comparison finds two shared decoded images for `cardeventnet-IMG_0662`. It finds none for `cardeventnet-IMG_0657` or the real round. This restores a small, two-image geometry scope. It does not support a detector quality claim across all three recordings.

No processor or model stage ran. The retained source and data revisions remain unchanged. M1 used comparison algorithm `pipeline-comparison/v2`.

## Frozen inputs

The exact requests, states, revision manifests, and hashes are in the [M0 machine-readable freeze](0050-M0_Diagnostic_Freeze.json). This report uses the same retained detector and reference revisions.

| Recording | Source SHA-256 | Detector revision / content SHA-256 | Reviewed geometry revision / content SHA-256 |
| --- | --- | --- | --- |
| `cardeventnet-IMG_0657` | `23df5b4dbf0d0d80c79161ba32c1f4c4db8473f053fdd9b63508c66e38d3658b` | `visible-cards-coord-07d852bb91cfc6b19f7a-attempt-1` / `823a29f443bb013b95c98cf0cfe6f54899cf703c520ba64f3f3e47504d463c59` | `reference-visible_cards-9825ffb099bab16c735b114ec4c4050a` / `cd87d26bddae0677f7646b5084d8832bdf668d7a9277ee144715db236b31b058` |
| `cardeventnet-IMG_0662` | `2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7` | `visible-cards-coord-aa2ab2751f97e23f4dd2-attempt-1` / `b0992370382ecfb0b3fdefe086d503cd0ea17da657a43e4606d5160f903e5474` | `reference-visible_cards-bf287d3bff82dec774f16be1ccc736f0` / `d098847ee1ee68d6a3e9a3977d7b254bfff762008f9ffccf0ad0ae90625f147d` |
| `game-2026-08-20-01-001` | `2464d0e65547b2db31ea5ca49f4d57cefcb999e34cbacec7e7cca8ee9d549faa` | `visible-cards-coord-d7821eb650044d5b3606-attempt-1` / `f9a85c209cc0eaf304fc0e74430caef160939d6ccfa28d7c4cf39d921d229c85` | `reference-visible_cards-25c56fb38af9a5604283bbc57789e690` / `6710ff5ce7758561ea2d1c1c5278cb90974162bbebbd01af37b75e70fd9a4a3a` |

## Frame coverage correction

| Recording | Predicted frames | Reviewed frames | Paired images | Unpaired predictions | Unpaired reviewed frames |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cardeventnet-IMG_0657` | 52 | 51 | 0 | 52 | 51 |
| `cardeventnet-IMG_0662` | 52 | 50 | 2 | 50 | 48 |
| `game-2026-08-20-01-001` | 43 | 49 | 0 | 43 | 49 |

`IMG_0662` pair 1:

```json
{
  "predicted_event_id": "event-000002",
  "reviewed_event_id": "cardeventnet-event-img_0662-002",
  "predicted_frame_identity": {
    "schema_version": "exact-event/v1",
    "source_video_sha256": "2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7",
    "requested_time_us": 5000000,
    "frame_index": 300,
    "presentation_timestamp_us": 5005000,
    "width": 1920,
    "height": 1080,
    "decoder_version": "ffmpeg/8.1.2",
    "transform_version": "ffmpeg-mjpeg/8.1.2",
    "output_encoding": "jpeg",
    "content_type": "image/jpeg",
    "image_sha256": "bfc307c47fcb232270eed4b37b12c926bc1bd68cc192442bc660bdef88fbbcd0",
    "policy": "exact-event/v1"
  },
  "reviewed_frame_identity": {
    "schema_version": "exact-event/v1",
    "source_video_sha256": "2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7",
    "requested_time_us": 5004836,
    "frame_index": 300,
    "presentation_timestamp_us": 5005000,
    "width": 1920,
    "height": 1080,
    "decoder_version": "ffmpeg/8.1.2",
    "transform_version": "ffmpeg-mjpeg/8.1.2",
    "output_encoding": "jpeg",
    "content_type": "image/jpeg",
    "image_sha256": "bfc307c47fcb232270eed4b37b12c926bc1bd68cc192442bc660bdef88fbbcd0",
    "policy": "exact-event/v1"
  }
}
```

`IMG_0662` pair 2:

```json
{
  "predicted_event_id": "event-000003",
  "reviewed_event_id": "cardeventnet-event-img_0662-003",
  "predicted_frame_identity": {
    "schema_version": "exact-event/v1",
    "source_video_sha256": "2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7",
    "requested_time_us": 6250000,
    "frame_index": 375,
    "presentation_timestamp_us": 6256667,
    "width": 1920,
    "height": 1080,
    "decoder_version": "ffmpeg/8.1.2",
    "transform_version": "ffmpeg-mjpeg/8.1.2",
    "output_encoding": "jpeg",
    "content_type": "image/jpeg",
    "image_sha256": "f9a4fc3dc5f4460fa649b73882325db422544d53b739be93572fb7639805565f",
    "policy": "exact-event/v1"
  },
  "reviewed_frame_identity": {
    "schema_version": "exact-event/v1",
    "source_video_sha256": "2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7",
    "requested_time_us": 6256044,
    "frame_index": 375,
    "presentation_timestamp_us": 6256667,
    "width": 1920,
    "height": 1080,
    "decoder_version": "ffmpeg/8.1.2",
    "transform_version": "ffmpeg-mjpeg/8.1.2",
    "output_encoding": "jpeg",
    "content_type": "image/jpeg",
    "image_sha256": "f9a4fc3dc5f4460fa649b73882325db422544d53b739be93572fb7639805565f",
    "policy": "exact-event/v1"
  }
}
```

The source video hash, decoded-image hash, frame index, presentation timestamp, dimensions, decoder, transform, encoding, content type, policy, and schema agree in both pairs. Only `requested_time_us` differs. The remaining 50 predicted and 48 reviewed `IMG_0662` frames are unpaired; every frame from the other two recordings is unpaired.

## Geometry results

The matcher uses polygon-union masks on the normalized 1000 × 1000 grid with the existing pixel-center raster rule. It does not score the outer bounding box. The matching threshold is polygon IoU `0.5`; reviewed ignore regions remain governed by the existing comparison policy. Neither paired reference frame has an ignore region. All compared card geometries are supported; no geometry form was excluded as unsupported.

| Recording | Paired card predictions | Paired reviewed cards | Matches at IoU ≥ 0.5 | Misses | Extras | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cardeventnet-IMG_0657` | 0 | 0 | 0 | 0 | 0 | n/a | n/a |
| `cardeventnet-IMG_0662` | 7 | 7 | 7 | 0 | 0 | 1.000 | 1.000 |
| `game-2026-08-20-01-001` | 0 | 0 | 0 | 0 | 0 | n/a | n/a |

The seven matched card polygon IoUs are `0.934939`, `0.928812`, `0.744758`, `0.959640`, `0.948245`, `0.935125`, and `0.764896`. The first paired image has three reviewed and three predicted cards. The second has four reviewed and four predicted cards.

Pile regions are reported separately. Both paired images contain zero predicted and zero reviewed pile regions, so pile precision and recall are unavailable. All other pile regions are outside the paired-image scope.

The retained full-output totals remain useful context but are not quality scores: `IMG_0657` has 113 predicted and 117 reviewed cards, plus 1 predicted and 0 reviewed piles; `IMG_0662` has 104 predicted and 109 reviewed cards, plus 85 predicted and 70 reviewed piles; the real round has 105 predicted and 226 reviewed cards, plus 21 predicted and 0 reviewed piles. Of the `IMG_0662` totals, 97 predicted and 102 reviewed cards are outside the two paired images. No geometry score applies to those unpaired inputs.

## Implementation and verification

The comparison key is comparison-only. It keeps every frame identity field except `requested_time_us`; run source checks, revision lineage, crop authority, cache keys, and mutation checks remain unchanged. A comparison item carries both full frame identities and both event IDs.

The changed implementation and regression cases are in:

- `operations/src/doko_operations/pipeline_comparison_contract.py`
- `operations/src/doko_operations/pipeline_comparison_execution.py`
- `backend/src/dokodetector_backend/pipeline_comparison_api.py`
- `backend/tests/test_pipeline_vision_comparison_api.py`
- `operations/tests/test_pipeline_vision_comparison.py`

The tests cover both known pairs, request-time-only changes, source and decoded-image changes, frame location, dimensions, decoder, transform, and encoding. Polygon tests cover the inclusive 0.5 boundary and distinguish a polygon union from its outer box.

Verification passed:

- Backend comparison tests: 18 passed.
- Operations comparison tests: 11 passed.
- No model inference or runtime processor run occurred, and no input data revision changed.
