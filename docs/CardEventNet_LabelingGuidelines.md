# CardEventNet labeling guidelines

## Purpose

CardEventNet is a candidate detector. A positive event tells the system to run table-state
detection again. Label visible card-state changes, not only valid game actions.

Use these rules for training, validation, and test annotations. Do not change a rule for one split
or to match a model prediction.

## Core rule

Label a `card_state_changed` event when a persistent card-related table-state change can make
table-state detection return a different useful result. The label does not assert a card play, a
card side, or another gameplay meaning.

Apply this rule to the complete camera frame. Use game context to distinguish:

- the current trick;
- collected tricks;
- scoring cards left on the table;
- cards held by players; and
- unrelated cards or objects.

A **table card** is a card that rests on the table or falls onto it. A card that stays in a
player's hand is not a table card. Location alone does not decide a label.

## Event time

Set `time_s` to the earliest frame where the new state is clear enough for table-state detection
to observe it.

Do not use:

- the start of hand movement;
- first hand contact;
- the first blurred frame;
- the time when a hand leaves; or
- the time when the complete table becomes empty.

For a placement, move, turn, removal, return, collection, or multi-card change, use the first
frame where the new pose and role are visible. If motion blur hides the result, advance to the
first clear frame.

The format uses point events. It does not store movement intervals. This avoids false conflicts
when two physical actions overlap.

## Meaningful change

Compare the stable state before the action with the new observable state. Label a change when at
least one of these conditions is true:

- the card center moves by at least one quarter of the card's visible short edge;
- the card rotates by at least 15 degrees;
- the card flips between face and back;
- overlap changes enough to expose or hide card identity;
- the card changes role between the current trick, a collected trick, and a score display; or
- table-state detection could reasonably change card count, identity, position, role, or ownership.

The last rule overrides the numeric guides. Do not label a tap, vibration, or slide below both
numeric guides when identity, overlap, and card role stay unchanged.

Treat one continuous manipulation as one event at its final meaningful state. Label a second event
only when a distinct intermediate state becomes observable before a new action changes it again.

## Overlapping actions

Annotate each observable card-state change, even when timestamps are close. Do not move or remove
an event to satisfy the current decoder's minimum event gap.

If a card becomes visible and is collected in one continuous action, label each distinct state
that is observable. If the intermediate state is not distinguishable, label only the final
observable change.

## Frequent real-game situations

### A card lands on its back and is turned over

Label the landing and the later turn when each creates a distinct observable table state. Add a
short note if the sequence is hard to recognize. Card side is not part of the event label.

### Collected tricks remain visible

Label the change when the old trick becomes a collection stack. Do not label the stationary stack
again. Treat hands moving over it, card backs, and small stack compression as negatives.

### A scoring card remains visible

Label a change when a scoring card is deliberately separated and its new role becomes clear. If
separation and collection form one continuous action with no distinct intermediate state, label
only the final observable change.

## Negatives and hard negatives

Do not add a positive event for:

- a hand that hovers, points, or touches without meaningful card movement;
- temporary occlusion by a hand, sleeve, drink, or other object;
- shadows or lighting changes;
- camera shake, autofocus, or exposure changes;
- cards handled only in a player's hand;
- a stationary collected trick or score card; or
- unrelated full-frame motion that cannot change the game-relevant table state.

Ordinary background needs no point annotation. A hard negative is a reviewed model trigger that
contains no positive event under this guide. Store it in the separate hard-negative manifest. Do
not convert a suspected missing event into a hard negative without human review.

## Confidence and notes

Use `confirmed` when the event and timestamp are clear. A missing confidence value in an old
annotation has the same meaning.

Use `uncertain` when an event probably exists but its time cannot be set reliably. Use `ignore` for
a review point where the video does not support a decision. These entries are excluded from
training and event metrics.

`proposed` is reserved for model output. A model proposal is not ground truth. The annotation tool
must not save it as confirmed without a human decision.

Add a note when another reviewer will need context.

## Annotation format

The current machine-readable contract is
[`annotation-v2.schema.json`](../card_event_net/schemas/annotation-v2.schema.json). Each source
video has one JSON file:

```json
{
  "schema_version": "cardevent-annotation/v2",
  "video": "game-001.mov",
  "events": [
    {
      "time_s": 12.4,
      "type": "card_state_changed",
      "confidence": "confirmed"
    }
  ]
}
```

The active contract accepts only `card_state_changed`. V2 annotations have no geometry. V1 files
with an `roi` field remain readable only as historical input; the current annotator writes V2 and
uses the full frame.

Keep events in time order. Close events are valid when they represent separate visible changes.
The current validator rejects only effective duplicates within 10 ms and warns about events less
than 100 ms apart.

## Review procedure

For the first quality check:

1. Label a small sample without model proposals.
2. Review it again on a separate pass without relying on the first decision.
3. Compare event count and timestamp.
4. Resolve each disagreement by updating this guide or correcting the annotation.
5. Repeat until the two passes apply the rules consistently.

Check especially for missed state changes during collection and overlapping actions.
