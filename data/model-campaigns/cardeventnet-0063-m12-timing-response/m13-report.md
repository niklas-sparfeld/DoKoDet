# CardEventNet M13 timing comparison

- Campaign: `cardeventnet-0063-m12-timing-response`
- Decision: `human_review_required`
- Candidate: `interval_endpoint_focus_v1`

M13 validates lineage before reading validation metrics. It reads no sealed test or system-holdout output.

## Strict stable-end and interval-presence metrics

| Metric | M9 baseline | M12 candidate |
| --- | ---: | ---: |
| Stable-end matches | 49 | 54 |
| Point matches | 228 | 215 |
| Interval-presence recall | 89.35% | 86.77% |
| Detections inside intervals | 24 | 24 |
| Confirmed no-event triggers | 25 | 15 |
| Duplicate detections per reviewed change | 32 | 35 |
| Causal emission delay p95 | 0.726 s | 0.719 s |

## Gates

| Gate | Value | Limit | Result |
| --- | ---: | ---: | --- |
| stable_end_matches | 54 | >= 60 | failed |
| confirmed_no_event_triggers | 15 | <= 20 | passed |
| duplicate_detections_per_reviewed_change | 35 | <= 32 | failed |
| causal_emission_delay_p95_s | 0.719497 | <= 0.75 | passed |
| event_presence_recall | 0.867742 | >= 0.98 | failed |

## Failure reasons

- stable_end_matches 54 is below minimum 60
- duplicate_detections_per_reviewed_change 35 exceeds maximum 32
- event_presence_recall 0.867742 is below minimum 0.98

The candidate is not locked until every gate passes. M14 remains blocked.
