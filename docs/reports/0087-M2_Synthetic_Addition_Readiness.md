# 0087 M2 synthetic addition readiness

Date: 2026-10-14

## Decision

M2 is complete with a declared gap. Do not add synthetic frames to the 0087 training view. The
frozen M0 rule permits omission when no compatible two-class pool is available. The existing
synthetic assets do not meet the frozen source-group and current-geometry rules.

## Eligible source scope

The frozen M0 manifest is
[`0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json`](0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json),
with digest `a14ae7c3b96408c652ee7e1d78fc1bc209c9771bf5a70ef26432114a2acd2114`. It assigns only
`cardeventnet-IMG_0095` to training. The M1 materialization contains 42 reviewed training frames
and has digest
`cc0891f04f8e9e4a59790e9f3eac52d91bdaeaf85b43a5a84a7aa563de119e29`.

The 0070 reviewed empty-table approvals contain no `IMG_0095` background. The 0070 planar
production pool uses nine other recordings: `IMG_0096`, `IMG_0097`, `IMG_0636`, `IMG_0637`,
`IMG_0638`, `IMG_0640`, `IMG_0641`, `IMG_0643`, and `IMG_0655`. Its manifest digest is
`96cbcf303127a8ec88b50b618e1d1988d33e412a0d7e984c8296867cc3e6e998`; the source file SHA-256 is
`171b20427fba4543fcf2c969d6777c49564745fb0d4b8e995b898240cad306a1`.

The older all-recordings manifest has digest
`b31c1483c007591451b58bca48e44889bba0dee430ff5426f6f0d2cb661b24f4` and 38 scenes. One scene
uses `IMG_0095`, with the superseded inpainting strategy. Its file SHA-256 is
`df7827d40ca0d7bb31c1b9d05624ccb1467a28efedb9cc3b3ae89dbdf7ab03c9`.

These assets may be usable under source permission, but they are not part of the frozen 0087
training group. The other 0086 development candidates cannot contribute until their references are
eligible and a reviewed split is frozen. Historical `allowed_uses` values do not change this
source-group rule.

## Compatibility gaps

- The older all-recordings pool has one scene from `IMG_0095`, but it uses a card-bearing frame and
  deterministic inpainting as its background. This is not an approved empty background and does
  not establish safe pile-negative supervision.
- The reviewed planar pool uses only explicit reviewed empty backgrounds, but it has no background
  from `IMG_0095`. It freezes card aspect ratio `1.5`, while current card-plane geometry uses
  `91/59` (`1.542373`). The old images cannot satisfy the current-geometry requirement.
- The existing 0070 pool uses one visible-card class. It has no pile annotations. Reusing it as a
  two-class training view would need a reviewed policy for pile negatives, which the current
  sources do not provide.

No images were regenerated or added. No merged view was written, and no training or inference ran.
M0 validation and sealed-test materializations remain unchanged. M4 is not applicable because M2
omitted its synthetic candidate. M3 can proceed with the fixed real-only candidate.

## Reproduce the audit

From the repository root, inspect these frozen inputs:

```sh
python - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
m0 = json.loads((root / "docs/reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json").read_text())
approvals = json.loads((root / "data/operations/synthetic-visible-region-0070-empty-table-approvals.json").read_text())
planar = json.loads((root / "data/operations/synthetic-visible-region-0070-planar-geometry-production.json").read_text())
train_ids = [item["recording_id"] for item in m0["partitions"]["train"]["recordings"]]
approved_ids = sorted({item["recording_id"] for item in approvals["inputs"]})
print("0087 train recordings:", train_ids)
print("0070 approved backgrounds:", approved_ids)
print("0070 planar aspect ratio:", planar["policy"]["card_aspect_ratio"])
print("0070 planar manifest digest:", planar["manifest_digest"])
PY
```

The current card-plane contract is `CARD_ASPECT_RATIO = 91.0 / 59.0` in
`operations/src/doko_operations/card_plane_geometry.py`.
