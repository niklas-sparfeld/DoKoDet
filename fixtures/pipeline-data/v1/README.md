# Pipeline event contract fixtures

These fixtures exercise the shared `event-data/v1` contract. They are not training data.

- `event-data-point.json` contains a point `card_state_changed` event.
- `event-data-interval.json` contains a nonzero card-state change interval.

Both forms use the same event type. The interval uses `end_us` as its stable-state anchor for
CardEventNet data tasks.
