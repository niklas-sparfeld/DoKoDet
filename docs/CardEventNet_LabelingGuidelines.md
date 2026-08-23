# CardEventNet labeling guidelines

## Purpose

CardEventNet is a candidate detector. A positive event tells the system to run table-state
detection again. Label visible card-state changes, not only valid game actions.

Use these rules for training, validation, and test annotations. Do not change a rule for one split
or to match a model prediction.

## Core rule

Label a positive event when a visible card-state change can make table-state detection return a
different useful result.

Apply this rule to the complete camera frame. Do not define a geometric active area. Use game
context to distinguish:

- the current trick;
- collected tricks;
- scoring cards left on the table;
- cards held by players;
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
- the time when a hand leaves;
- the time when the complete table becomes empty.

For a card placement or move, use the first frame where the card has substantially reached its new
pose and its new role is visible. If motion blur hides the result, advance to the first clear
frame.

For a removal, use the first frame where the card is no longer part of the relevant table state.
For a trick clear, use the first frame where the cards from the completed trick have been gathered
or transferred to the collector. The cards can remain visible in the full frame.

The format uses point events. It does not store movement intervals. This avoids false conflicts
when two physical actions overlap.

## Event classes

### `card_played`

One card is placed as part of the current trick. Label valid, invalid, accidental, face-up, and
face-down plays. Use the time when the card's role in the trick becomes observable.

Do not use this class when an old collected card falls back onto the table. Use `card_returned`.

### `trick_cleared`

The completed trick stops being the active trick. Label one event for the complete clear action.
The collector can place the cards in a visible stack next to the current trick.

Do not wait until the table is empty. A card from the next trick can already be on the table. The
label time depends only on the cards from the completed trick.

### `card_moved`

A card that is already on the table reaches a meaningfully different pose or role and remains on
the table. This includes turning a face-down card face up, moving a scoring card aside, and a
correction that changes overlap or readability.

Use the movement thresholds below. Do not label small jitter.

### `card_removed`

One relevant table card is removed without clearing the complete trick. Examples are a withdrawn
play, removal of an incorrectly played card, or removal of a stray card.

Do not use this class for the normal collection of a complete trick. Use `trick_cleared`.

### `card_returned`

A card that was previously removed or collected comes back onto the table as a loose relevant
card, but it is not a new play. An old trick card that falls from a collection stack is a
`card_returned` event.

If a player deliberately plays that card as the next legal play, use `card_played`.

### `multiple_cards_dropped`

Two or more cards enter or change the table state in one inseparable action. Use one event when
reliable per-card timestamps do not exist, such as a packet of cards falling together.

Do not use this class for two players who play separate cards at nearly the same time. Label two
`card_played` events when the two state changes are visible separately.

### `anomalous_state_change`

A meaningful visible card-state change has no more specific class. Add a note that states what
changed. This is a last-resort class. Do not use it as a shortcut for uncertain review.

## Meaningful movement

Compare the stable state before the action with the new observable state. Label `card_moved` when
at least one of these conditions is true:

- the card center moves by at least one quarter of the card's visible short edge;
- the card rotates by at least 15 degrees;
- the card flips between face and back;
- overlap changes enough to expose or hide card identity;
- the card changes role between the current trick, a collected trick, and a score display;
- table-state detection could reasonably change card count, identity, position, role, or
  ownership.

The last rule overrides the numeric guides. The fractions make the rule independent of video
resolution. They also suppress camera noise and harmless taps after the full frame is reduced to
the model input size.

Do not label a tap, vibration, or slide below both numeric guides when identity, overlap, and card
role stay unchanged.

Treat one continuous manipulation as one event at its final meaningful state. Label a second event
only when a distinct intermediate state becomes observable before a new action changes it again.

## Overlapping actions

Annotate each observable semantic event, even when timestamps are close. Do not move or remove a
ground-truth event to satisfy the current decoder's minimum event gap.

When a player collects a trick immediately while the fourth card is played:

1. Label `card_played` when the fourth card becomes observable as part of the trick.
2. Label `trick_cleared` when the completed trick is no longer active.

The events can be less than the decoder gap apart. If the fourth card never becomes visually
distinguishable as part of the trick, mark the `card_played` event `uncertain`. Confirm the clear
event if its state change is visible.

When the next trick starts before the old trick is clear, label the new `card_played` event at its
normal time. Then label `trick_cleared` when the old cards have been gathered by the collector.
The new card does not prevent a clear label.

## Frequent real-game situations

### A card lands on its back and is turned over

Label the landing as `card_played`. Label the later turn as `card_moved`. Add a short note if the
sequence is hard to recognize. Add both `face_down_card_played` and `face_down_card_turned` to the
video metadata.

### Collected tricks remain visible

Label `trick_cleared` when the old trick becomes a collection stack. Do not label the stationary
stack again. Treat hands moving over it, card backs, and small stack compression as negatives.

If a card falls from the stack back onto the table as a loose card, label `card_returned`.

### A scoring card remains visible

For a scoring card such as a Fuchs, the card can remain next to the collected tricks. If the card
is deliberately separated as a score display before the rest of the trick is collected, label
`card_moved` when that new role becomes clear. Label `trick_cleared` when the remaining completed
trick has been gathered.

If separation and collection are one continuous action with no distinct intermediate state, label
only `trick_cleared` at the final observable state. The visible scoring card does not mean that the
old trick is still active.

### A play is withdrawn and replayed

Label the original `card_played`, then `card_removed`, then the later `card_played`. If the same
card returns only to restore the prior table state and is not played, use `card_returned` for the
return.

## Negatives and hard negatives

Do not add a positive event for:

- a hand that hovers, points, or touches without meaningful card movement;
- temporary occlusion by a hand, sleeve, drink, or other object;
- shadows or lighting changes;
- camera shake, autofocus, or exposure changes;
- cards handled only in a player's hand;
- a stationary collected trick or score card;
- unrelated full-frame motion that cannot change the game-relevant table state.

Ordinary background needs no point annotation. A hard negative is a reviewed model trigger that
contains no positive event under this guide. Store it in the separate hard-negative manifest. Do
not convert a suspected missing event into a hard negative without human review.

## Confidence and notes

Use `confirmed` when the event class is clear and the timestamp is accurate to the first
observable frame. A missing confidence value in an old annotation has the same meaning.

Use `uncertain` when an event probably exists but its class or time cannot be set reliably. Use
`ignore` for a review point where the video does not support a decision. These entries are excluded
from training and event metrics.

`proposed` is reserved for model output. A model proposal is not ground truth. The annotation tool
must not save it as confirmed without a human decision.

Add a note for `anomalous_state_change`, for uncommon interpretations, and whenever another
reviewer will need context.

## Annotation format

The current machine-readable contract is
[`annotation-v1.schema.json`](../card_event_net/schemas/annotation-v1.schema.json). Each source
video has one JSON file:

```json
{
  "video": "game-001.mov",
  "roi": {"x": 0.05, "y": 0.12, "width": 0.8, "height": 0.75},
  "events": [
    {
      "time_s": 12.4,
      "type": "card_played",
      "confidence": "confirmed"
    },
    {
      "time_s": 12.82,
      "type": "trick_cleared",
      "confidence": "confirmed",
      "notes": "Fourth card and clear overlap."
    }
  ]
}
```

The V1 `roi` field is a legacy preprocessing field. Do not use it to decide event meaning. The
[full-frame input plan](plans/0013-CardEventNet_FullFrameInput.md) will remove it from new
annotations and retain read compatibility for existing files.

Keep events in time order. Close events are valid when they represent separate visible changes.
The current validator rejects only effective duplicates within 10 ms and warns about events less
than 100 ms apart.

## Review procedure

For the first quality check:

1. Label a small sample without model proposals.
2. Review it again on a separate pass without relying on the first decision.
3. Compare event count, class, and timestamp.
4. Resolve each disagreement by updating this guide or correcting the annotation.
5. Repeat until the two passes apply the rules consistently.

Check especially for missing trick clears. A complete 40-card game normally has about ten
`trick_cleared` events in addition to its card plays and anomalies.
