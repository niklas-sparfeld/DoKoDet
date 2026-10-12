# 0091 pile-region capability handoff

## Readiness states

| State | Status | Evidence |
| --- | --- | --- |
| Annotation-ready | Ready | `visible-card-data/v2` maintains pile regions separately from cards. The operator workflow, reversible grouping, pile-only coverage, immutable publication, and reload are available. Continue reviewed pile annotation in 0086. |
| Software-ready | Ready | Two-class materialization and fixture training support `visible_card` (category 1) and `card_pile` (category 2). `rfdetr-segmentation-bundle/v1` validates the two-class map and `card_pile` capability receipt. The explicit `local-rfdetr-segmentation` provider retains predictions and lineage. Identity work filters piles. `table-observation/v2` and `round-reconstruction-result/v3` retain pile evidence without gameplay inference. |
| Trained-model-ready | Unavailable | 0087 remains Blocked and has no selected pile-capable bundle. Fixture training proves software compatibility only. It does not establish detector quality or model readiness. |

## Capability handoff

- **0086 — reviewed corpus:** Use the operator flow in
  [`Pile Region Annotation`](../guides/Pile_Region_Annotation.md). Maintain pile geometry in
  `visible-card-data/v2`; do not treat missing pile review in older v1 references as a negative.
  Annotation remains a human decision.
- **0087 — RF-DETR campaign:** The software accepts the fixed two-class categories and
  `rfdetr-pile-segmentation-manifest/v1`. It supports deterministic materialization, trainer
  smoke, bundle reload, evaluation, and explicit provider output. Run the real campaign only
  after 0086 freezes eligible references and 0087 freezes its inputs, budgets, and gates. No
  candidate is selected by this handoff.
- **0088 — DINO campaign:** Piles remain outside identity crops, suggestion outcomes, and
  training targets. Mixed observations carry pile evidence in `table-observation/v2`; do not
  create DINO work for pile regions or grouped members.
- **0089 — algorithm edge cases:** The engine retains pile polygons and lineage, reports
  `pile_search_status=retained_not_used`, and does not derive plays, identity, winners, or counts
  from piles. Temporal or gameplay use requires its own evidence and scope.
- **0090 — local pipeline:** Declare pile support from the selected provider and bundle receipt.
  Preserve pile evidence through observation assembly and engine input. Until 0087 selects a
  validated real bundle, report model support as unavailable; an empty pile list from a card-only
  provider is not a reviewed negative.

## Reproducible fixture verification

Run from the repository root. The Python command covers reference editing/publication and restart,
two-class materialization and stale-input rejection, fixture trainer and bundle reload, provider
predictions, identity filtering, observation assembly, engine input, and reconstruction behavior.
The Web command covers pile review and engine timeline inspection. Both commands use local fixtures
and do not read evaluation images or change annotation references.

```sh
PYTHONPATH=backend/src:operations/src:table_evidence_analyzer/src:game_engine/src \
  mise exec -- uv run --project backend --group dev \
  --with opencv-python==4.11.0.86 python -m pytest \
  backend/tests/test_pipeline_reference.py::test_pile_grouping_is_reversible_and_pile_only_coverage_completes \
  backend/tests/test_pipeline_reference.py::test_pile_grouping_removes_and_restores_proposal_card_review_state \
  backend/tests/test_pipeline_reference.py::test_pile_create_replace_and_ignore_conversion_commands \
  backend/tests/test_visible_card_pipeline_api.py::test_visible_card_pipeline_uses_selected_event_revisions_and_retains_outcomes \
  backend/tests/test_visual_identity_pipeline_api.py::test_visual_identity_pipeline_uses_generated_geometry_and_restarts \
  operations/tests/test_rfdetr_segmentation_campaign.py::test_m2_materializes_pile_targets_as_a_separate_rle_category \
  operations/tests/test_rfdetr_segmentation_campaign.py::test_m1_rejects_a_changed_extracted_frame_digest \
  operations/tests/test_rfdetr_pile_targets.py \
  operations/tests/test_pile_observation_boundary.py \
  table_evidence_analyzer/tests/test_rfdetr_pile_training.py \
  table_evidence_analyzer/tests/test_observation_assembly.py::test_assembler_preserves_piles_separately_for_mixed_and_pile_only_frames \
  game_engine/tests

(cd web && npm test -- --run src/visibleCards/PipelineVisibleCardEditor.piles.test.tsx src/analysis/AnalysisTimelinePresentation.test.tsx)
```

Materialization tests assert deterministic digests and exact category/RLE output. Trainer tests
reload the written bundle and assert class-map and mask-policy parity. Provider fixtures retain
bundle identity and class lineage. Observation and engine fixtures verify source geometry parity;
the engine test asserts unchanged plays and replay actions. Test-generated outputs live in temporary
directories, so their manifest and bundle digests are checked at runtime and do not refer to a
mutable checked-in artifact. The exact source revision is the commit containing this handoff.

M7 verification on the implementation at commit
`8d7c52cef5f12c5cf4656c0c7f96ab9f7351b0a6` passed 94 Python tests, 9 focused Web tests,
and `npm run typecheck`. The fixture trainer output recorded run ID
`rfdetr-pile-0091-m3-smoke-1791810666`, materialization digest
`8ff79d1a16f19b35690ac3aed3882cfbd160f28d64df9ad9354d9318c85387c0`, bundle digest
`6166d8412571c2e4f7d676ef314c6b251682054f06fbf300284511adb96dfe38`, checkpoint SHA-256
`4bffa8bb54263bf682a2c60fa4ab702721cae7b4fb41b3e6db5ff010b01a1536`, materialization file
SHA-256 `4f1c35d0c7c497bcd1e40eb1091798c04d91e0469821b02a5e0120e5ac96b8db`, and bundle manifest
SHA-256 `1f4e89baf0d941794b081b98720a056cf3f969d4d5f4197d30fc439cec682b27`. These are fixture
artifacts, not a real candidate or model-quality result.

## Bounded real-bundle smoke procedure

Run only after 0087 records a selected candidate and exact bundle path. First verify that the bundle
loads as `rfdetr-segmentation-bundle/v1`, declares categories 1=`visible_card` and 2=`card_pile`,
and includes the 0091 capability receipt. Record the bundle and checkpoint SHA-256 values from its
manifest. Then set `VISIBLE_CARD_PROVIDER=local-rfdetr-segmentation` and
`VISIBLE_CARD_SEGMENTATION_BUNDLE_PATH` to that exact bundle. Run the provider on one eligible,
reviewed development frame that contains a visible card touching a pile footprint. Record the exact
input revision and frame digest, bundle/checkpoint digests, run ID, both class outputs, and result
revision. Confirm that the card and pile remain separate after reload and that the pile retains its
model lineage. Stop after this frame; do not use the smoke to tune thresholds or claim model quality.

If 0087 has no accepted two-class candidate, do not run this procedure. Record trained-model
readiness as unavailable and keep the fixture-backed software and annotation capabilities active.
