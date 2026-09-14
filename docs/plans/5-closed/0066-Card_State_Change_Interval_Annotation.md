# Card-state change interval annotation

## Plan status

- **Summary:** Let an operator mark the start and stable end of a long card-state change in the
  CardEvent review editor.
- **Status:** Closed
- **Closure reason:** Complete
- **Depends on:** None
- **Builds on:** 0049, 0062, and 0064 complete; 0063 supplies reviewed failure evidence but does
  not block this work.
- **Readiness:** M0–M4 are complete. The interval semantics, stable-end policy, contract
  fixtures, preservation checks, CardEvent viewer editing controls, range-aware Timeline Rail,
  bound navigation, interval-aware targets, negative evidence exclusion, diagnostics, and the
  bounded review pilot are in place.
- **Outcome:** A reviewed event can remain a point or become a nonzero card-state change interval.
  The editor makes both bounds clear. CardEventNet uses the stable end as the event anchor and does
  not treat the interval interior as a hard negative or ordinary negative sample.

## Problem

A trick clear can take several seconds. Cards can move, disappear, reappear, and remain partly
visible before the table becomes stable. A point timestamp cannot describe this activity in a
repeatable way. It makes review uncertain and can turn a valid in-progress state change into a
false trigger or an incorrect negative training sample.

The current pipeline event record already has `start_us` and `end_us`. Current CardEvent review
controls create and keep point events where both values are equal. The editor does not give an
operator a clear way to mark a card-state change interval.

## Scope

This epic includes:

- reviewed `card_state_changed` events with a point or interval time range;
- CardEvent review controls to set, adjust, and inspect the interval start and stable end;
- Timeline Rail presentation of the full reviewed event range;
- point-event compatibility for existing reviewed events and generated proposals;
- CardEventNet materialization, evaluation, and hard-negative rules for reviewed intervals; and
- a bounded human-review pilot using trick-clear examples from the current failure review.

This epic does not include:

- a new event type, gameplay assertion, card-play label, or trick-winner label;
- a model architecture change or model promotion;
- a change to already frozen 0063 data, split, candidate, or sealed test result;
- automatic conversion of an existing point event into an interval; or
- an attempt to label each intermediate pickup or card movement as a separate event.

## Fixed decisions

1. Keep `card_state_changed` as the only generic CardEvent event type. A trick clear is represented
   by its time range, not by another event type.
2. A point event has `start_us == end_us`. A card-state change interval has `start_us < end_us`.
3. For a trick clear, the start is the first visible action that begins the persistent table-state
   change. The end is the first frame where the new table state is stable after the clear.
4. The interval has one reviewed event. Intermediate card movement is not a separate event.
5. The CardEventNet point target for an interval is its `end_us` stable-state anchor. Materializers
   must exclude the interval interior from ordinary negatives and from hard-negative candidates.
6. A detector proposal inside a reviewed interval is not a false positive solely because it is
   earlier than the stable-state anchor. Interval-aware diagnostics must report it separately from
   a true point match and a false trigger.
7. Existing point events, point-event controls, command ordering, source lineage, review coverage,
   and generated proposals remain valid without migration.
8. A new reviewed revision and a new frozen dataset are required before interval-aware training.
   The current 0063 frozen data remains immutable.

## Milestone status

- **M0:** Complete (2026-09-14) — define the card-state change interval in the glossary and
  labeling guide, publish the stable-end and diagnostic policy, add point and interval contract
  fixtures, and verify validation, ordering, comparison, and maintained-reference preservation.
- **M1:** Complete (2026-09-14) — add interval editing to the CardEvent viewer.
- **M2:** Complete (2026-09-14) — make intervals understandable in review.
- **M3:** Complete (2026-09-14) — keep interval interiors out of negative evidence.
- **M4:** Complete (2026-09-14) — run a bounded trick-clear review pilot with source-frame
  evidence, immutable revision lineage, disposable materialization, sampling comparison, and
  interval-aware diagnostic counts.

## Delivery milestones

### M0 — Lock interval review semantics

- Complete — add the card-state change interval definition to the glossary and CardEvent
  annotation guidance.
- Complete — add focused contract fixtures for a point event and a nonzero interval event.
- Complete — define the stable-end anchor and interval-aware diagnostic outcomes in one data-policy
  document.
- Complete — verify that pipeline event validation, ordering, comparison, and reference commands
  preserve a nonzero `start_us` and `end_us` range.

Acceptance:

- an operator can use one concise rule to identify the start and stable end of a trick clear;
- an interval remains `card_state_changed` and validates through the existing event contract; and
- point events retain their current serialized form and behavior.

### M1 — Add interval editing to the CardEvent viewer

- Complete — add visible, accessible actions to mark a selected event start at the playhead and
  mark its stable end at the playhead.
- Complete — keep `N` as the existing point-event action and add `S` and `E` shortcuts for marking
  the start and stable end, with the same actions available as buttons.
- Complete — show both bounds, duration, and the selected bound in the existing CardEvent review
  inspector.
- Complete — reject an end before its start and allow an operator to return an interval to a point
  by setting both bounds to the same source frame.
- Complete — reuse the current ordered command queue, exact source-frame surface, Timeline Rail
  seek, and conflict recovery path.

Acceptance:

- an operator can add a point event, mark its start, seek through the source frames, and mark a
  later stable end without leaving the viewer;
- the persisted review draft has the selected `start_us` and `end_us` values after save and reload;
- existing accept, dismiss, add, nudge, and point-event keyboard workflows remain unchanged; and
- invalid ranges show a clear error and do not change the draft.

### M2 — Make intervals understandable in review

- Complete — render a selected interval as a range in the Timeline Rail and distinguish it from a
  point marker.
- Complete — let the source-frame surface switch directly between the start and stable-end frames.
- Complete — state the selected bound, full range, duration, and stable-end anchor in visible and
  accessible review text.
- Complete — add desktop and narrow browser coverage for point, interval, pending, accepted,
  corrected, save retry, and revision-conflict states.

Acceptance:

- Complete — a reviewer can see the full interval, navigate to either bound, and identify the
  stable-end anchor without calculating times manually;
- Complete — the view remains usable at the existing desktop and narrow breakpoints; and
- Complete — point markers retain their current rail and frame behavior.

### M3 — Keep interval interiors out of negative evidence

- Complete — add an explicit interval policy to CardEventNet materialization and diagnostics.
- Complete — use `end_us` for the point target of a reviewed interval.
- Complete — exclude samples inside the reviewed interval from ordinary negatives, confirmed hard negatives,
  and false-trigger counts that assume a point target.
- Complete — report predictions inside an interval as in-progress detections so review can distinguish them
  from missed events and confirmed no-event triggers.
- Complete — add unit coverage for point events, nonzero intervals, overlapping label windows, and mining
  behavior.

Acceptance:

- Complete — no interval-interior sample enters a hard-negative manifest or ordinary-negative selection;
- Complete — an interval-end target still creates the configured positive label window; and
- Complete — diagnostics separately count point matches, in-progress detections, and confirmed false triggers.

### M4 — Run a bounded trick-clear review pilot

- Complete — review the current uncertain and missed hard-negative candidates that occur during
  trick clears.
- Complete — publish one new reviewed event revision with a small, explicit set of card-state
  change intervals.
- Complete — materialize a new disposable training view and compare its sampling counts with the
  0063 view.
- Complete — record whether interval-aware annotations reduce ambiguous hard-negative candidates
  without using sealed test data.

Acceptance:

- Complete — the pilot records reviewed intervals with source-frame evidence and review coverage;
- Complete — a new training view has immutable lineage to that reviewed revision;
- Complete — the report distinguishes confirmed no-event triggers from in-progress trick-clear
  detections; and
- Complete — no existing frozen dataset or sealed test artifact changes.

## Verification

Run focused backend contract and reference-command tests, CardEventNet materialization and
hard-negative tests, generated API checks, web type and lint checks, CardEvent editor unit tests,
and its desktop and narrow browser tests. For the pilot, verify source revision lineage, review
coverage, stable event ordering, interval exclusion counts, and unchanged 0063 artifact digests.
