# Epic 0095 M1 observation result

## Decision

Allowing candidate sums below one let all three retained inputs pass observation assembly. Each run
completed and published an observation revision. The 24 card candidates retain the original values
from the 25-class identity distribution. The contract still rejects a candidate sum above one plus
the `1e-6` tolerance. No score was normalized.

This confirms the contract was the blocker. It does not measure identity quality or validate
gameplay reconstruction.

## Results

| Recording | Observations | Cards | Zero-card observations | Classified cards | Candidate sums below 1 | Lowest sum | Run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `cardeventnet-IMG_0657` | 52 | 113 | 9 | 112 | 66 | 0.999877 | `coord-b485f149f77e43989fb8` |
| `cardeventnet-IMG_0662` | 52 | 104 | 8 | 104 | 61 | 0.888767 | `coord-67f6dcd018dd429bbada` |
| `game-2026-08-20-01-001` | 43 | 105 | 2 | 100 | 60 | 0.914684 | `coord-c80008c595664dc9b773` |
| **Total** | **147** | **322** | **19** | **316** | **187** | — | — |

All observation statuses are `observed`. The 19 zero-card observations preserve the 19 no-card frames
from M4. Both byte-identical decoded JPEG pairs in `IMG_0662` remain in the exact retained event and
detector inputs (frames 300 and 375); no event, detector, scene, or identity stage ran again.

## Scope and limits

The only new processor executions were three observation assemblies. They took 32.7 seconds from
the first run start to the last run completion. The API used local providers, made zero cloud
requests, and made no annotation or sealed-data access. Reconstruction did not run because the real
round lacks explicit active-player, dealer, and first-trick-leader context. The other two sources
are staged trick sequences.

The backend process was not sampled for RSS during this short batch, so this report gives no peak
memory value. The M4 diagnostic's 1.03 GiB sample applies only to the earlier M4 batch.

The source identity model remains unqualified. M4 found no exact predicted-to-reviewed crop hash
matches for `IMG_0662` and no reviewed identity revision for the real round. All identity
predictions still need human review. This experiment selects no model and makes no quality claim.

## Stored evidence

The three processor requests, states, per-observation items, and output revisions are retained under
`data/operations/pipeline/`. Their paths and digests, exact input revision digests, output counts,
and run timing are in the [machine-readable result](0095-M1_Partial_Identity_Observation_Result.json).
The existing `table_observations.json` selection pointers were absent before execution and were
removed after the runs. No upstream selection changed.
