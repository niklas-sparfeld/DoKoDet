# CardEventNet M11 reference reconciliation and decoder replay

- Campaign: `cardeventnet-0063-m9-hard-negative-ablation`
- M10 packet: `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m10-timing-review.json`
- Operator artifact: `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m10-operator-review.json`
- Sealed test read: `false`
- System holdout read: `false`

## Operator decision reconciliation

The M10 artifact keeps region fields blank, so M11 uses the six recording decisions and their prose notes as the completion evidence. The mapping is deterministic: adjusted recordings map missed or in-progress items to `reference_corrected`; unchanged or prediction-okay recordings map them to `reference_confirmed`; confirmed false triggers map to `no_event_confirmed` unless the current reference now contains an event at that time. Any explicit canonical region decision takes precedence.

| Decision | Items |
| --- | ---: |
| `reference_corrected` | 27 |
| `reference_confirmed` | 25 |
| `no_event_confirmed` | 18 |

## Successor development dataset

- Dataset: `cardeventnet-interval-dataset-00a59b5fcd210d23c569`
- Dataset path: `data/operations/cardevent-datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569`
- Dataset digest: `00a59b5fcd210d23c569727f98453c77237bb2c2ae71ebfc0a69e9abf8e807ee`
- Split: `cardeventnet-interval-split-939ecbcfa22d3658c966`
- Reviewed recordings: `cardeventnet-IMG_0090, cardeventnet-IMG_0091, cardeventnet-IMG_0635, cardeventnet-IMG_0644, cardeventnet-IMG_0652, cardeventnet-IMG_0661`
- Revision-changed recordings: `cardeventnet-IMG_0090, cardeventnet-IMG_0635, cardeventnet-IMG_0644, cardeventnet-IMG_0661`
- Source groups and sealed-test membership are preserved from M7.
- The saved checkpoint is evaluated against the successor validation references; no training is run.

## Decoder replay

- Grid artifact: `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m11-decoder-grid.json`
- Grid digest: `836e44601ec841016161cb6e0af1c86de8aeb217f5669af5f11d2d322c8dae51`
- Threshold is fixed from M9. The decoder grid is validation-only.
- No decoder is selected in M11. Sealed-test output is not read.

| Decoder | Point | Stable-end | Inside interval | Duplicate detections | No-event triggers | Signed error median (s) | Emission delay median (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `current_causal` | 228 | 49 | 24 | 32 | 25 | 0.111182 | 0.236182 |
| `longer_peak_confirmation` | 228 | 51 | 19 | 31 | 25 | 0.112339 | 0.487339 |
| `bounded_quiet_window` | 68 | 9 | 8 | 3 | 12 | 0.087235 | 0.212235 |

M11 stops after deterministic reference validation and offline decoder replay. It does not train, export, promote, read sealed test, or read the system holdout.
