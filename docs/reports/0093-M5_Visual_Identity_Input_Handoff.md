# Epic 0093 M5 visual identity input handoff

Date: 2026-10-14. This handoff verifies annotation and crop capability. It does not claim that
the current reviewed corpus is ready for training.

## Input contract

The materializer accepts one exact completed visible-card revision and one exact completed
visual-identity revision for each recording. It requires current schemas. The visible-card content uses
`visible-card-data/v2`. The identity content uses `visual-identity-data/v2`. Each revision binds
its immutable ID and canonical content digest. The recording also supplies its source-lineage
group.

A positive identity row must match the same `card_id`, exact `frame_identity`, and exact reviewed
geometry in both revisions. Its identity outcome must carry `visual-identity-annotation-provenance/v1`
with the visible-card revision ID and digest, card ID, frame identity, and geometry digest. An
annotation-only outcome has `classifier: null`. Its crop receipt must be usable, match the reviewed
frame and geometry, use `oracle_visible_region`, and match the resolved native crop bytes.

The materializer writes native PPM crops and PGM visible-support masks. It writes a
`reviewed-visual-identity-materialization/v1` manifest. The manifest contains the 24 canonical face-up
classes and `FACE_DOWN`, sample rows, class and recording support, back-design support, duplicate
crop groups, and reason-coded exclusions. Missing back-design metadata remains unspecified. A class
listed in the manifest has no evidence until its sample count is non-zero.

Pile regions are not identity targets. The reviewed visible-card revision removes grouped pile
members from its candidate list. The materializer also excludes IDs listed as grouped pile members,
even if a malformed input still lists one as an individual candidate. A stale identity item for a
removed member is excluded. A pile region alone does not create a card identity target.

## Reproduction commands

Run the materialization contract and the annotation API persistence regressions from the repository
root:

```sh
mise exec -- uv run --project operations pytest operations/tests/test_visual_identity_materialization.py
mise exec -- uv run --project backend pytest backend/tests/test_pipeline_reference.py -k annotation_reference
```

Consumers use the same operations entry point with completed reference envelopes and their exact
source-frame resolver:

```python
from doko_operations.visual_identity_materialization import (
    materialize_reviewed_visual_identity_crops,
)

manifest = materialize_reviewed_visual_identity_crops(
    recordings=completed_reference_envelopes,
    output_dir=".runtime/reviewed-visual-identity-inputs",
    frame_resolver=resolve_exact_source_frame,
)
```

The resolver must return the exact `frame_identity` requested by the revision. A different frame,
geometry, source digest, or crop digest produces an exclusion. Do not convert generated classifier
output to annotation provenance. Do not replace `oracle_visible_region` with a predicted crop kind.

## Replay and current data limit

The fixture replay covers all 25 targets, stable manifest and crop digests, exact mask bytes, current
schema checks, stale frame and geometry rejection, unreadable evidence, pile-member isolation, and a
face-down-to-face-up correction. The correction updates the reviewed side and annotation-source
digest. It keeps the same frame and geometry, so it keeps the same native crop bytes and card item.

The live development snapshot was checked for IMG_0095, IMG_0097, and IMG_0654 only. These are the
eligible 0086 M2 development recordings. No other source entered the replay or materialization.
The current snapshot has no eligible positive annotation crop:

| Recording | Current identity evidence                                                                                                                                                               | Handoff result    |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| IMG_0095  | 105 generated Gemini outcomes in an uncompleted identity draft; no annotation provenance                                                                                                | Not eligible      |
| IMG_0097  | 231 older outcomes; the completed identity reference uses prediction-backed crop lineage and has no annotation provenance. Its card IDs do not match the current visible-card revision. | Not eligible      |
| IMG_0654  | No visual-identity reference                                                                                                                                                            | No identity input |

A read-only eligibility replay over these current reference files produced zero samples. The
materializer excluded old identity outcomes without matching visible-card items and did not invoke
the frame resolver for them. It did not write to the maintained references. A few exact visible-card
frames from these recordings were inspected in M4, but they do not supply human identity labels.

Therefore the handoff proves capability with fixtures and proves that current incompatible evidence
does not enter the input set. Current corpus support for all 25 classes is zero. Back-design support
is unspecified. 0086 can continue annotation without classifier predictions. 0094 and 0088 can use
the published contract when eligible reviewed annotations exist; this report does not make the
corpus ready to train, freeze a training dataset, or change a model or provider default.

## Verification

- Materialization regressions: 5 passed.
- Annotation reference/API regressions: 2 passed.
- The existing FastAPI test dependency emits a Starlette deprecation warning; the tests pass.
