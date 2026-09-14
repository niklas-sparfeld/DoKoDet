# CardEventNet card-state change interval data policy

## Purpose

This policy defines how reviewed card-state change intervals are stored and measured. It applies
to the recording pipeline event contract and to CardEventNet data views. It does not create a new
event type.

## Event range

Every reviewed `card_state_changed` event has `start_us` and `end_us` source times.

- A point event has `start_us == end_us`.
- An interval has `start_us < end_us`.
- The start is the first visible action that begins the persistent table-state change. Do not use
  hand motion, first contact, or a blurred frame unless that frame is the first visible action that
  changes the persistent state.
- The end is the first source frame where the new table state is stable after the change.
- A trick clear is one interval when cards move, disappear, reappear, or remain partly visible
  before the new table state is stable. Its intermediate frames are not separate events.
- Use a point event when the change is clear at one source frame or when no nonzero range can be
  reviewed with confidence. Do not invent an end time.

The event remains `card_state_changed` for both forms. The range describes the observed change. It
does not assert a card play, card side, trick winner, or another gameplay meaning.

## CardEventNet anchor

The CardEventNet target for an interval is its stable end, `end_us`. A point event uses its equal
start and end value. A training or evaluation task can declare another anchor only when that task
documents the reason and uses it consistently.

The interval interior is part of the reviewed change. It is not ordinary negative evidence and it
is not a confirmed hard negative.

## Diagnostic outcomes

Use these outcomes for a reviewed source range and a detector proposal. Apply them only inside the
declared review coverage.

| Outcome | Rule |
| --- | --- |
| `point_match` | A proposal is within the declared matching tolerance of a point event. |
| `stable_end_match` | A proposal is within the declared tolerance of an interval's `end_us` stable-state anchor. |
| `in_progress_detection` | A proposal is inside an interval before its stable end: `start_us <= proposal_us < end_us`. It is not a false trigger only because it is early. |
| `confirmed_false_trigger` | A reviewed proposal is outside every matching point and interval range, and review confirms that no card-state change occurred at that time. |
| `miss` | A reviewed point or interval has no matching proposal at its declared anchor. |

Check `stable_end_match` before `in_progress_detection`. A proposal at the interval end is an
anchor match, not an in-progress detection. A proposal can be reported as in progress even when it
is not close enough to the stable end for a match.

Do not count an `in_progress_detection` as a hard negative or as a confirmed false trigger. Keep
the source range, the proposal time, the selected anchor, and the outcome in the diagnostic row so
that a later data view can reproduce the decision.

## Review rule

Review one continuous card-state change as one event. Mark the first visible action that starts the
persistent change, then mark the first stable frame after it. If the start or stable end is not
clear, keep a point event or mark the review uncertain. Do not split intermediate card movement
into several generic events.
