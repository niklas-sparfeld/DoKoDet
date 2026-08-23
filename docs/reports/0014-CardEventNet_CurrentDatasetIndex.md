# CardEventNet current dataset index

## Status

This index records all 38 local raw videos with matching annotation files. It is the V1 metadata
baseline, not final annotation review.

## Evidence

Technical fields come from `ffprobe` QuickTime metadata. The index groups captures by contiguous
capture time and does not split a group across the development split. The groups are:

- 2018-01-24: 1 video;
- 2018-01-28: 4 videos;
- 2020-06-11 at 18:48: 3 videos;
- 2020-06-11 at 19:21: 1 video;
- 2020-06-12: 2 videos;
- 2026-08-20: 12 videos;
- 2026-08-21: 15 videos.

Each annotation has 28 to 44 `card_played` events. This and a contact-sheet review support the
provisional `staged_trick_sequence` classification. It does not prove every visual scenario tag.

## Split use

[`full-frame-development.yaml`](../../card_event_net/data/splits/full-frame-development.yaml)
is session-isolated. It reserves no test partition because the only clearly independent legacy
test session, `IMG_2781`, has already been evaluated for the ROI pipeline. Do not use it as a new
full-frame final test. Collect and reserve a new independently captured session for that purpose.

## Required human review

- Confirm source and use permission for every capture group.
- Confirm the capture-time groups match real recording sessions and table setups.
- Confirm the provisional staging, camera, lighting, and framing descriptions.
- Review annotations for non-play state changes before training on them as negatives.
