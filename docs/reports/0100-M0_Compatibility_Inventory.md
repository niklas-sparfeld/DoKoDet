# 0100 M0 compatibility inventory

Checked on 2026-10-30 in the current local checkout. This inventory records current code and local
data. It does not treat older handoffs as current failures without a fresh check.

## Summary

M0 found four code and configuration repairs for M1–M4. The live editor check for M5 remains
unavailable because the local backend is not running. The backend revision store itself accepts all
frozen review targets and verifies their content. No source evidence is missing for those targets.

All checks were read-only. They did not change selections, review targets, drafts, queue progress,
source bytes, or revision content. No model inference or cloud request ran. The unrelated local edit
to `0096-M3_Exact_Reference_Evaluation.json` was left unchanged.

## Findings

| Boundary | Current evidence | Repair path | Preservation requirement |
| --- | --- | --- | --- |
| Installed game engine | `operations/pyproject.toml` declares `doko-game-engine` as a local, non-editable path dependency. Both `operations/.venv` and `backend/.venv` import `game_engine` from their `site-packages`. The installed package lacks `pile_regions_seen` and `pile_search_status`, which exist in `game_engine/src/game_engine/reconstruction.py`. | M1: make local package installs use current source; refresh both environments through normal setup. | Keep package versions and engine output semantics unchanged. |
| Recording session IDs | Recording metadata and pipeline data use string session IDs. Round analysis contracts still type `session_id` as UUID in `backend/src/dokodetector_backend/contract.py` and `round_analysis_timeline.py` converts observation session IDs to UUID. Existing session IDs such as `session-2026-08-20` cannot pass this contract. | M2: use the canonical recording session identifier through analysis, storage, status, and browser paths. | Keep recording metadata, source digests, and exact recording equality checks unchanged. |
| Round context | `RoundAnalysisControls.tsx` initializes dealer and trick leader as `seat-1`. `round_analysis_service.py` also creates requests with seat defaults. These values are not operator-confirmed facts. | M3: request missing context before analysis and persist the explicit values in the analysis request. | Keep unknown real-round facts unknown until the operator supplies them. |
| Local model recipe | The local `backend/.env` selects `local-rfdetr-fine-frame`, points to 0043 identity artifacts, and sets MPS. Epic 0100 requires full-frame 0092 M4 detection and 0088 M6 local classification for its first-trial recipe. The 0092 detector checkpoint and manifest, 0088 M6 bundle files, and 0063 M14 event checkpoint are present in this checkout. | M4: provide one explicit recipe with the selected provider, bundles, crop policy, device, and digests at each entry point. Keep fine-frame as an alternate. | Do not change defaults or promote a model. Keep M6 output review-required. Treat ignored `.runtime` assets as local-only. |
| Revision catalog | The current operations parser accepted 644 of 722 revision manifests. It rejected 78: 75 `card_scene_proposals` with `proposed-card-scene-data/v1` and 3 `visual_identities` with `visual-identity-data/v1`. All 180 non-null pointers in the 129 current selection files point to accepted manifests. | M5: identify which rejected historical revisions are still needed by active views; replace only an active generated revision if a required reader cannot consume it. | Do not edit immutable revisions, source data, review decisions, or sealed reports. Create replacement revisions with lineage and receipts if active repair is needed. |
| 0096 review targets | The current `PipelineRevisionStore` loaded all 165 frozen target revisions. All 165 have the expected recording ID and canonical content digest. The queue still has one unreviewable recording because its corrected detector output is absent; this is a recorded dependency failure, not a catalog failure. | No revision repair is needed for these 165 target artifacts. M5 must still verify editor navigation when the backend is running. | Keep the queue digest, exact revision/frame links, and unreviewable item unchanged. |
| 0098 review targets | The current store loaded all 114 exact target revisions with matching recording IDs and content digests. The queue pins targets across 26 recordings. All 26 current generated selection pointers differ from the frozen target. Ten recordings have conflicting drafts; 13 have completed drafts and 3 have no saved reference state. The queue report records all ten conflicts. | M5: check each exact target through the editor; preserve conflicting drafts and do not move selection pointers to the frozen targets. | Keep the frozen queue and all saved drafts unchanged. Opening a target must not rebase or mark another draft reviewed. |
| Live editor access | The current backend is not running, so HTTP editor navigation and current draft state could not be checked in this M0 run. The 0098 frozen queue records its prior live-backend check as unavailable. | M5: repeat the exact-target editor check when the local service is available. | A failed connection is not evidence that retained source data is missing. |

## Frozen review-target accounting

| Queue | Frozen items | Revision and content check | Active target result |
| --- | ---: | --- | --- |
| [0096 M4 detector review](0096-M4_Human_Review_Queue.json) | 165 | 165 loaded; all recording IDs and content digests matched | All target artifacts are available through the current revision store. One separate recording remains unreviewable because its corrected M1 output does not exist. |
| [0098 M3 identity review](0098-M3_Identity_Review_Queue.json) | 114 | 114 loaded; all recording IDs and content digests matched | All target artifacts are available through the current revision store. The queue retains 26 pointer differences and 10 conflicting drafts. |

The older 0097 handoff said all 165 items were unavailable in that checkout because of manifest
schema rejection. The current direct store check did not reproduce that result for the exact frozen
targets. The live editor check remains open, so this does not establish that browser navigation
currently works.

## M0 disposition

- M1 owns the stale installed engine.
- M2 owns recording session identifiers that are incorrectly constrained to UUIDs.
- M3 owns the invented round-context defaults.
- M4 owns the mismatch between current local settings and the explicit first-trial model recipe.
- M5 owns the 78 rejected historical manifests and live editor verification. No frozen review target
  needs replacement based on the current store check.
- M6 can use the current fixture coverage and repeat unchanged local model probes. No full-recording
  inference or real-round accuracy claim is authorized by this milestone.

The queue targets have repair paths or a concrete missing-input reason. The 78 rejected manifests
are not referenced by current non-null selection pointers. Their historical disposition is limited
to M5 review; this inventory does not authorize data conversion or regeneration.
