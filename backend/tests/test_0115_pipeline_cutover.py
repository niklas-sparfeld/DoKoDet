from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from app_factory import create_test_app
from doko_operations.pipeline_data import parse_pipeline_selection_bytes
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings
from dokodetector_backend.legacy_processor_run_store import LegacyProcessorRunStore
from dokodetector_backend.pipeline_revision_store import PipelineRevisionStore
from dokodetector_backend.pipeline_storage import PipelineRuntimeStorage

FIXTURE_ROOT = Path(__file__).parent / "fixtures/0115-pipeline-cutover/operations"
REVISION_IDS = (
    "canonical-card-state-reference-events-570e225c1762370434597c1804347e5d",
    "card-scene-proposals-card-scene-proposal-1793787913577-attempt-1",
    "cardeventnet-events-img_0097",
    "reference-events-c6478cd0fd7a716bf50f81fd6df34dc9",
    "visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1",
)
RUN_EDGES = {
    "visible_cards-run-f9b6c6cf-577": (
        ("reference-events-c6478cd0fd7a716bf50f81fd6df34dc9",),
        ("visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1",),
    ),
    "card-scene-proposal-1793787913577": (
        ("visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1",),
        ("card-scene-proposals-card-scene-proposal-1793787913577-attempt-1",),
    ),
}
RECORDING_ID = "cardeventnet-IMG_0097"
ACTOR = {"kind": "human", "id": "0115-m9-cutover-test"}
EDIT_FIXTURE = Path(__file__).parents[2] / "fixtures/pipeline-data/v1/event-data-interval.json"
CHAIN_RECEIPT = (
    Path(__file__).parents[2]
    / "docs/reports/0115-M9_Pipeline_Cutover.artifacts/selected-chain.json"
)


def test_selected_legacy_chain_runs_from_isolated_root_across_api_restart(
    tmp_path: Path, monkeypatch
) -> None:
    storage_root = tmp_path / "isolated-storage"
    operations = storage_root / "data/operations"
    shutil.copytree(FIXTURE_ROOT, operations)
    chain_receipt = json.loads(CHAIN_RECEIPT.read_bytes())
    for item in chain_receipt["fixture_files"]:
        source = FIXTURE_ROOT / Path(item["path"]).relative_to("data/operations")
        content = source.read_bytes()
        assert len(content) == item["byte_length"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
    monkeypatch.setenv("DOKO_STORAGE_ROOT", str(storage_root))
    settings = Settings(
        _env_file=None,
        repository_root=Path(__file__).parents[2],
    )
    storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
    revision_store = PipelineRevisionStore(storage)
    run_store = LegacyProcessorRunStore(storage, revision_store=revision_store)

    revision_fingerprints: dict[str, str] = {}
    for revision_id in REVISION_IDS:
        revision = revision_store.require(revision_id)
        revision_fingerprints[revision_id] = hashlib.sha256(
            json.dumps(
                revision.content.to_mapping(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    assert len(revision_fingerprints) == len(REVISION_IDS)

    run_fingerprints: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for run_id, expected_edges in RUN_EDGES.items():
        run = run_store.require(run_id)
        edges = (
            tuple(run.request.input_revision_ids),
            tuple(run.state.output_revision_ids),
        )
        assert edges == expected_edges
        run_fingerprints[run_id] = edges

    selection_root = operations / "pipeline/selections" / RECORDING_ID
    event_selection = parse_pipeline_selection_bytes((selection_root / "events.json").read_bytes())
    card_selection = parse_pipeline_selection_bytes(
        (selection_root / "visible_cards.json").read_bytes()
    )
    assert event_selection.selected_completed_reference_revision_id == (
        "reference-events-c6478cd0fd7a716bf50f81fd6df34dc9"
    )
    assert card_selection.selected_generated_revision_id == (
        "visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1"
    )
    assert storage.operations_root == operations.resolve()
    assert storage.operations_root != Path(__file__).parents[2] / "data/operations"

    app = create_test_app(settings)
    edited_source = json.loads(EDIT_FIXTURE.read_bytes())
    source = {
        "schema_version": "recording-video/v1",
        "recording_id": "m9-fixture-recording",
        "relative_path": "fixtures/pipeline-data/v1/event-data-interval.json",
        "video_sha256": "a" * 64,
        "byte_length": 100,
        "duration_us": 10_000_000,
    }
    pointers = {
        event["event_id"]: f"/events/{index}" for index, event in enumerate(edited_source["events"])
    }
    node = app.state.pipeline_node_edits.store.create(
        "m9-cutover-events",
        "M9 cutover events",
        "events",
        source,
        edited_source,
        pointers,
    )
    edited_content = json.loads(json.dumps(edited_source))
    edited_content["events"][0]["end_us"] += 1

    with TestClient(app) as client:
        response = client.post(
            f"/api/pipeline/nodes/{node.node_id}/edit",
            json={
                "expected_revision_id": node.revision_id,
                "idempotency_key": "m9-cutover-edit-1",
                "actor": ACTOR,
                "content": edited_content,
                "pointers": pointers,
                "base_pointers": pointers,
                "operations": [
                    {
                        "kind": "replace",
                        "before": [edited_content["events"][0]["event_id"]],
                        "after": [edited_content["events"][0]["event_id"]],
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        saved_revision_id = response.json()["revision_id"]
        review = client.post(
            f"/api/pipeline/nodes/{node.node_id}/reviews/item",
            json={
                "review_id": "m9-cutover-review",
                "revision_id": saved_revision_id,
                "item_id": edited_content["events"][0]["event_id"],
                "question": "Does this event match the supplied evidence?",
                "decision": "accepted",
                "reviewer": ACTOR,
                "evidence": {"policy": "pipeline-event-review/v1", "source": "0115-M9 fixture"},
            },
        )
        assert review.status_code == 200, review.text
        readback = client.get(f"/api/pipeline/nodes/{node.node_id}/revisions/{saved_revision_id}")
        assert readback.status_code == 200
        assert readback.json()["content"] == edited_content

    restarted = create_test_app(settings)
    with TestClient(restarted) as client:
        readback = client.get(f"/api/pipeline/nodes/{node.node_id}/revisions/{saved_revision_id}")
        assert readback.status_code == 200
        assert readback.json()["content"] == edited_content
        reviews = client.get(
            f"/api/pipeline/nodes/{node.node_id}/revisions/{saved_revision_id}/reviews"
        )
        assert reviews.status_code == 200
        assert [item["decision"] for item in reviews.json()] == ["accepted"]

    restarted_storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
    restarted_revision_store = PipelineRevisionStore(restarted_storage)
    restarted_run_store = LegacyProcessorRunStore(
        restarted_storage, revision_store=restarted_revision_store
    )
    assert {
        revision_id: hashlib.sha256(
            json.dumps(
                restarted_revision_store.require(revision_id).content.to_mapping(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        for revision_id in REVISION_IDS
    } == revision_fingerprints
    assert {
        run_id: (
            tuple(restarted_run_store.require(run_id).request.input_revision_ids),
            tuple(restarted_run_store.require(run_id).state.output_revision_ids),
        )
        for run_id in RUN_EDGES
    } == run_fingerprints
