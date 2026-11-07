# Epic 0114 M8: Residual write APIs

M8 adds named real-backend request timing and durable readback checks for the eight residual UI
write routes. The cases use temporary storage, exact upstream revisions, and a deterministic local
analysis provider. The retained timings are preliminary single-response samples; they do not set a
baseline or performance budget.

## Coverage and result

The HTTP test covers event, visible-card, proposed-card-scene, visual-identity, and observation
stage submissions; explicit and recording round-analysis intake; and calibration apply. It checks
persisted job/run inputs, exact revision lineage, analysis readback, and published calibration and
visible-card revisions. Calibration apply uses synthetic planar anchors derived from the active
calibration because the frozen detector anchors are noisy and do not prove successful apply.

The integration test exposed two defects in calibration apply: proposal snapshot code treated a
revision as a manifest-bearing proposal object, and published calibration runs omitted the
`calibration_fit_candidate` field required by their schema. The implementation now resolves the
proposal revision and frame scenes by revision ID and writes the nullable field. A focused unit test
covers the snapshot lookup.

## Checks

- Residual-write and calibration snapshot tests pass; the HTTP test records 8 successful named
  responses and verifies durable effects.
- Inventory coverage reports 76 registered operations classified, one documented unregistered UI
  URL, and 70 planned UI cases.
- Ruff check and format checks pass for changed Python files.
- The sample file retains one response per named case. These values are specific to this run and
  are not a baseline.

Samples: [M8 residual-write response samples](0114-M8_Residual_Write_Samples.json).
