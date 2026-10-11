# Epic 0086 M1 pilot proposal generation

**Date:** 2026-10-11
**Recording:** `cardeventnet-IMG_0095`
**Outcome:** Complete

## Inputs

- Event reference: `reference-events-3e2d3b060f2719da7d4e932825b78370`
- Event frames: `cardeventnet-event-img_0095-000` through
  `cardeventnet-event-img_0095-052` (53 frames)
- Source video SHA-256: `34610c528a17117cf60dafd4137cf3531836c2bfdf422d391060249ce8da7bc7`
- RF-DETR detector revision: `visible-cards-0fcc49e1-9f61-4986-90bf-2f145e325ccd-attempt-1`
- Detector content SHA-256: `cfa3c6b5cfe0eeb6d4fe420bdeabf6d1d07e105e45423e4aa6301b746a6751ff`
- 0068 model bundle digest: `b3deef701e26d91ebfd9d357b4ff69b45ae9360e3722de340f1044214179df29`

## Output

- Processor run: `card-scene-proposal-aea76436-13ec-4bab-8ed1-1f3ab13a3fbe`
- Run status: `complete`; 53 of 53 frames processed
- Proposal revision: `card-scene-proposals-card-scene-proposal-aea76436-13ec-4bab-8ed1-1f3ab13a3fbe-attempt-1`
- Proposal content SHA-256: `1a42956f85eafbc6be4c0de1899b1140aef9fa84dabcb223cca53fd013100712`
- Supported / unsupported frames: 53 / 0
- Pose recipe: `fixed-card-pose-grid-search/v4`
- Calibration revision: `calibration-b76138a469c3f36bfbe816a1`
- Calibration digest: `33148a0ab934dca1e8e82d51a5914da0c835e0dca561217625e21a2631626a7a`
- Geometry: `card-plane-geometry/v5`; measured aspect ratio 1.5328836424957841

## Revision identity fix

The first proposal run, `card-scene-proposal-719c6efe-d8e7-4b8d-9926-c1792cc1bc18`, failed before
publishing proposals. It attempted to publish the v5 calibration at the v4 revision path
`calibration-fcaac5de34bd872e9d45eb8c`. The immutable store rejected the different content with
`immutable_revision_conflict`. Calibration revision identity now includes the geometry algorithm
version. The existing v4 calibration remains unchanged, and the v5 calibration has its own revision.

## Preservation and checks

The source video hash is unchanged. The selected event revision remains the same. The maintained
visible-card reference remains at draft revision 487, selects completed revision
`reference-visible_cards-54e8b7d89787b9d8b8e64745fc3cafbf`, and still points to the original
detector revision. Proposal generation did not change the human-maintained draft.

Focused checks passed: 52 operations tests for calibration, calibration reflow, and proposal
processing; three backend proposed-scene pipeline tests; Ruff; and formatting. The fixtures cover
geometry-versioned calibration IDs, accepted and adjusted card states across reflow, and interrupted
proposal-run recovery. No human review mutation or training started.
