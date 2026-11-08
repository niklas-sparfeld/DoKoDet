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
CHAIN_RECEIPT = (
    Path(__file__).parents[2]
    / "docs/reports/0115-M9_Pipeline_Cutover.artifacts/selected-chain.json"
)


def test_selected_legacy_chain_runs_from_isolated_root_across_api_restart(
    tmp_path: Path, monkeypatch
) -> None:
    storage_root = tmp_path / "isolated-storage"
    repository_root = tmp_path / "checkout-without-legacy-pipeline"
    repository_root.mkdir()
    operations = storage_root / "data/operations"
    shutil.copytree(FIXTURE_ROOT, operations)
    chain_receipt = json.loads(CHAIN_RECEIPT.read_bytes())
    for item in chain_receipt["fixture_files"]:
        source = FIXTURE_ROOT / Path(item["path"]).relative_to("data/operations")
        content = source.read_bytes()
        assert len(content) == item["byte_length"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
    monkeypatch.setenv("DOKO_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("DOKO_REPOSITORY_ROOT", str(repository_root))
    settings = Settings(
        _env_file=None,
    )
    legacy_checkout_roots = tuple(
        repository_root / "data/operations/pipeline" / name
        for name in ("revisions", "runs", "selections")
    )
    assert all(not root.exists() for root in legacy_checkout_roots)
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
    event_selection_bytes = (selection_root / "events.json").read_bytes()
    visible_selection_bytes = (selection_root / "visible_cards.json").read_bytes()
    event_selection = parse_pipeline_selection_bytes(event_selection_bytes)
    card_selection = parse_pipeline_selection_bytes(visible_selection_bytes)
    assert event_selection.selected_completed_reference_revision_id == (
        "reference-events-c6478cd0fd7a716bf50f81fd6df34dc9"
    )
    assert card_selection.selected_generated_revision_id == (
        "visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1"
    )
    assert storage.operations_root == operations.resolve()
    assert storage.operations_root != Path(__file__).parents[2] / "data/operations"

    selected_revision = revision_store.require(
        "visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1"
    )
    selected_source = selected_revision.manifest.source.to_mapping()
    selected_content = selected_revision.content.to_mapping()
    reviewed_item_id = selected_content["outcomes"][0]["event_id"]
    pointers = {reviewed_item_id: "/outcomes/0"}

    app = create_test_app(settings)
    node = app.state.pipeline_node_edits.store.create(
        "m9-selected-visible-cards",
        "M9 selected visible-card output",
        "visible_cards",
        selected_source,
        selected_content,
        {
            "origin": "processor",
            "source_revision_id": selected_revision.manifest.revision_id,
            "source_run_id": "visible_cards-run-f9b6c6cf-577",
        },
    )
    edited_content = json.loads(json.dumps(selected_content))
    edited_content["outcomes"][0]["candidates"][0]["geometry"]["visible_region"]["polygons"][0][0][
        "x"
    ] += 1

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
                        "before": [reviewed_item_id],
                        "after": [reviewed_item_id],
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
                "item_id": reviewed_item_id,
                "question": "Does this event match the supplied evidence?",
                "decision": "accepted",
                "reviewer": ACTOR,
                "evidence": {
                    "policy": "visible-card-review/v1",
                    "source_revision_id": selected_revision.manifest.revision_id,
                    "source_run_id": "visible_cards-run-f9b6c6cf-577",
                },
            },
        )
        assert review.status_code == 200, review.text
        readback = client.get(f"/api/pipeline/nodes/{node.node_id}/revisions/{saved_revision_id}")
        assert readback.status_code == 200
        assert readback.json()["content"] == edited_content
        assert readback.json()["metadata"]["source_revision_id"] == (
            selected_revision.manifest.revision_id
        )
        assert readback.json()["metadata"]["source_run_id"] == "visible_cards-run-f9b6c6cf-577"

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
        assert readback.json()["content"] == edited_content
        assert all(not root.exists() for root in legacy_checkout_roots)

    restarted_storage = PipelineRuntimeStorage(settings.evidence_root, settings.operations_root)
    restarted_selection_root = (
        restarted_storage.operations_root / "pipeline/selections" / RECORDING_ID
    )
    restarted_event_selection_bytes = (restarted_selection_root / "events.json").read_bytes()
    restarted_visible_selection_bytes = (
        restarted_selection_root / "visible_cards.json"
    ).read_bytes()
    assert restarted_event_selection_bytes == event_selection_bytes
    assert restarted_visible_selection_bytes == visible_selection_bytes
    restarted_event_selection = parse_pipeline_selection_bytes(restarted_event_selection_bytes)
    restarted_visible_selection = parse_pipeline_selection_bytes(restarted_visible_selection_bytes)
    assert restarted_event_selection.selected_completed_reference_revision_id == (
        "reference-events-c6478cd0fd7a716bf50f81fd6df34dc9"
    )
    assert restarted_visible_selection.selected_generated_revision_id == (
        "visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1"
    )
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
