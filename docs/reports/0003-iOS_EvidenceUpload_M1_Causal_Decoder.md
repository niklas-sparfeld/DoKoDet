# iOS Evidence Upload M1 — Causal Decoder Report

## Status

Frozen for the pipeline PoC. The decoder matches between Python and Swift on the shared fixture.

## Frozen live configuration

| Setting | Value |
| --- | ---: |
| threshold | `0.4996626377105713` |
| peak confirmation | `125 ms` |
| minimum event gap | `625 ms` |

The run started with the threshold from report 0015, `0.3442875146865845`. The causal decoder
changed the validation event set. A validation-only threshold selection then chose
`0.4996626377105713` by maximum F1 fallback. The 98% recall target was not met by the causal
event set.

## State rules

- A score at or above the threshold starts one pending peak when the decoder is armed.
- A higher score replaces the pending peak.
- A peak is confirmed when no higher score arrives for `125 ms`.
- The event time is the pending peak time. The emission time is the timestamp of the sample that
  confirms it.
- The minimum gap suppresses events at or below `625 ms` from the last accepted peak.
- A timestamp gap greater than the minimum event gap starts a new probability segment.
- `flush()` emits one pending peak at the last sample timestamp. A second flush emits nothing.
- The decoder stores one pending peak, the last accepted event, and the last sample timestamp.

## Validation replay

Source stream:
`card_event_net/data/outputs/run-20260825-235429/validation-streams/evaluation.json.gz`

The source is the saved V2 validation stream. The test partition was not used for threshold
selection or decoder tuning.

| Metric | Causal result |
| --- | ---: |
| videos | 5 |
| real events | 255 |
| detected true events | 241 |
| missed events | 14 |
| false events | 30 |
| recall | 94.51% |
| precision | 88.93% |
| F1 | 91.63% |
| false events/hour | 228.03 |
| emission latency median | 235 ms |
| emission latency p95 | 431 ms |

## Parity evidence

Python and Swift consume
`ios/CardEventProbeTests/Fixtures/causal_decoder_v1.json`. Both implementations assert event
time, peak score, emission time, minimum-gap suppression, irregular gaps, and end-of-stream
flush behavior.
