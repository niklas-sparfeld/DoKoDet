# 0088 M1 campaign views

## Result

M1 is complete. Exact source video bytes for all 20 handoff recordings match the intake receipts
and the 0086 handoff. The verification details are in the
[source verification report](0088-M1_Source_Verification.md).

The reviewed materializer produced 913 crops from the frozen training, model-selection, and
confidence-calibration groups. Cold and warm materialization digests and crop bytes match. The DINO
dataset contains 808 reviewed samples: 599 training samples and 209 model-selection samples. The
105 confidence-calibration samples remain outside that dataset. The dataset, split, and frame
artifact index pass the shared data-contract checks. The frozen training manifest and crop cache
load through the DINOv3 trainer contract. The trainer cache contains the exact 0093 PPM crop bytes;
it does not regenerate crops from rectangular frame bounds. The 224-pixel CLS recipe and command
are ready for M3. Their digests are in the
[machine-readable summary](0088-M1_Campaign_Views.json).

FACE_DOWN has one training crop, one model-selection crop, and no calibration crop. This is enough
for exploratory iteration and annotation assistance under the user's decision. It does not support
precision, recall, calibration, or generalization claims.

## Automatic-crop view

The development view uses the frozen two-class RF-DETR bundle from 0087 M5. It processed 130
development frames and produced 495 automatic crops. The one-to-one polygon-IoU association policy
uses a threshold of 0.5. No proposal met that threshold for a reviewed card. The best IoU was
0.255156. All 495 proposal crops are retained without identity targets. The 314 reviewed
model-selection and calibration samples without a matched automatic crop remain in the coverage
receipt. This view is available for annotation assistance, but it does not yet provide paired
automatic-crop identity results.

The provider runtime initially requested one class for a two-class checkpoint, which reinitialized
the trained head. The provider now reads the class count from its validated bundle manifest. The
completed run emitted no class-head reinitialization warning.

One training recording, `cardeventnet-IMG_0639`, has no completed visual-identity revision and no
positive crops. Its frozen source group remains in the M0 split and its missing reference is
recorded. It contributes no positive dataset entry.

The final-test membership is `cardeventnet-IMG_0659` / `source-group-3840f6e17e00e1e4`. M1 did not
resolve its frames, materialize crops, or score it. Unreviewed predictions did not become targets.

Runtime views and crops are in `.runtime/dinov3-identity-0088`. The reproducible builder is
`operations/scripts/build_0088_m1_campaign_views.py`.
