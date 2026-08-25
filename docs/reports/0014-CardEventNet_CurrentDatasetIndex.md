# CardEventNet current dataset index

## Status

This index records all 38 local raw videos with matching annotation files. It is the V1 metadata
baseline, not final annotation review.

## Evidence

Technical fields come from `ffprobe` QuickTime metadata. The content groups are:

- five `.m4v` files contain real-game rounds recorded with an iPhone X;
- the January 24 round and the four January 28 rounds belong to two separate games;
- six lowercase `.mov` files contain older staged trick sequences;
- 27 uppercase `.MOV` files contain recent staged trick sequences recorded with the target
  iPhone 14.

Each staged recording has different lighting, camera angle, or background. The manifest therefore
treats each staged recording as an independent session and table setup.

## Split use

[`full-frame-development.yaml`](../../card_event_net/data/splits/full-frame-development.yaml)
is session- and game-isolated. Training contains the January 24 real-game round and 27 staged
recordings. Validation contains the four January 28 real-game rounds and six staged recordings.
The staged validation data covers both older recording dates and both iPhone 14 recording dates.

The split has no test partition. `IMG_2781` has already been evaluated for the ROI pipeline, so the
development split uses it for training. Do not use it as a new full-frame final test. Collect and
reserve a new independently recorded game for that purpose.

## Required human review

- Confirm source and use permission for every capture group.
- Confirm the camera, lighting, and framing descriptions.
- Review annotations for non-play state changes before training on them as negatives.
