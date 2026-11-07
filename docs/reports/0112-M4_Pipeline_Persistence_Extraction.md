# 0112 M4 pipeline persistence extraction

## Result

M4 retires `backend/src/dokodetector_backend/pipeline_store.py`. Current callers import the owner
that matches their responsibility:

| Owner | Responsibility |
| --- | --- |
| `pipeline_revision_store.py` | Immutable revision publication, validation, and reads |
| `processor_run_store.py` | Processor-run create, state transitions, and updates |
| `processor_run_reader.py` | Strict run layout and state reads |
| `processor_run_catalog.py` | Compact status and recording catalog reads |
| `processor_run_codec.py` | Split metadata and item codecs |
| `processor_run_models.py` | Stored run and status records |
| `pipeline_storage.py` | Shared errors, paths, IDs, timestamps, JSON checks, and lock ownership |

`lineage_migration_inventory.py` and the offline `repair_0100_m5.py` tool import
`LegacyProcessorRunStore` from `legacy_processor_run_store.py`. Its old single-file state decoder is
in `legacy_processor_run_codec.py`. No runtime store imports either migration-only module. Runtime
processor-run reads reject the legacy single-file state layout.

## Contract checks

The focused store tests preserve canonical request, state metadata, and item bytes. They cover
compact status reads without walking item files, state/item separation, retries, atomic revision and
run publication, corrupt revisions and item files, concurrent create through independent store
instances, lock ownership, and migration-only decoding. Existing illegal-transition and error tests
remain with the current store owner.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_store.py backend/tests/test_pipeline_node_selection_store.py backend/tests/test_pipeline_lineage.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_pipeline_node_uses.py backend/tests/test_pipeline_node_reviews.py backend/tests/test_lineage_migration_inventory.py backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_pipeline_run_api.py backend/tests/test_pipeline_comparison_api.py backend/tests/test_pipeline_vision_comparison_api.py backend/tests/test_proposed_card_scene_pipeline.py backend/tests/test_event_recovery_catalog.py backend/tests/test_job_store.py backend/tests/test_jobs_api.py backend/tests/test_job_scheduler.py` — passed.
- `mise exec -- uv run --project backend pytest -q backend/tests/test_repair_0100_m5.py` — passed (14 tests).
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend backend/tests backend/scripts/repair_0100_m5.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend backend/tests backend/scripts/repair_0100_m5.py` — passed.
- `python -m compileall -q backend/src/dokodetector_backend backend/tests backend/scripts/repair_0100_m5.py` — passed.
- Local Markdown links in the updated plan, board, and report — passed.

## Limits

The migration inventory and offline `repair_0100_m5.py` tool are the only callers of the legacy
processor-run reader. M5 onward is unchanged. The next milestone is M5. This execution requested
10 milestones; four are complete and six remain.
