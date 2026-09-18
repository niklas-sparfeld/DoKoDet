from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from doko_operations.pipeline_data import (
    CARD_STATE_CHANGED_EVENT_TYPE,
    EVENT_DATA_SCHEMA_VERSION,
    PIPELINE_SELECTION_SCHEMA_VERSION,
    PROCESSOR_RUN_REQUEST_SCHEMA_VERSION,
    PROCESSOR_RUN_STATE_SCHEMA_VERSION,
    PipelineDataContractError,
    PipelineSelection,
    RecordingVideoSource,
    RunProgress,
    SyntheticFixtureSource,
    canonical_data_revision_bytes,
    canonical_event_data_bytes,
    canonical_json_bytes,
    canonical_pipeline_selection_bytes,
    canonical_processor_run_request_bytes,
    canonical_processor_run_state_bytes,
    parse_data_revision_bytes,
    parse_event_data_bytes,
    parse_event_data_revision_bytes,
    parse_pipeline_selection_bytes,
    parse_processor_run_request_bytes,
    parse_processor_run_state_bytes,
    sha256_bytes,
)

DIGEST = "a" * 64
PIPELINE_EVENT_FIXTURES = Path(__file__).parents[2] / "fixtures" / "pipeline-data" / "v1"
SOURCE = {
    "schema_version": "recording-video/v1",
    "recording_id": "recording-01",
    "relative_path": "data/intake/recordings/recording-01/video.mov",
    "video_sha256": DIGEST,
    "byte_length": 100,
    "duration_us": 10_000_000,
}


def _event_content() -> dict[str, object]:
    return {
        "schema_version": EVENT_DATA_SCHEMA_VERSION,
        "events": [
            {
                "event_id": "event-01",
                "event_type": CARD_STATE_CHANGED_EVENT_TYPE,
                "start_us": 1_000_000,
                "end_us": 1_250_000,
                "model_scores": [{"producer_id": "card-event-net.v1", "score": 0.75}],
            }
        ],
    }


def _processor_producer() -> dict[str, object]:
    return {
        "kind": "processor",
        "processor_type": "event-detection",
        "run_id": "run-01",
        "implementation_id": "event-worker.v1",
        "model_id": "card-event-net/v2",
    }


def _manifest(*, source: object = SOURCE, origin: str = "processor") -> dict[str, object]:
    source = json.loads(json.dumps(source))
    value: dict[str, object] = {
        "schema_version": "data-revision/v1",
        "revision_id": "revision-01",
        "content_type": "events",
        "content_schema": EVENT_DATA_SCHEMA_VERSION,
        "source": source,
        "content_sha256": sha256_bytes(canonical_json_bytes(_event_content())),
        "input_revision_ids": [],
        "origin": origin,
        "producer": _processor_producer(),
        "coverage": {"kind": "processed", "intervals": []},
        "created_at": "2026-09-05T10:00:00Z",
    }
    if isinstance(source, dict) and source["schema_version"] == "recording-video/v1":
        value["recording_id"] = source["recording_id"]
    return value


def test_event_revision_variants_round_trip_to_canonical_bytes() -> None:
    content = _event_content()
    parsed_content = parse_event_data_bytes(canonical_event_data_bytes(content))
    assert canonical_event_data_bytes(parsed_content) == canonical_event_data_bytes(content)

    generated = _manifest()
    parsed_generated = parse_data_revision_bytes(canonical_data_revision_bytes(generated))
    assert parsed_generated.recording_id == "recording-01"

    manual = _manifest(origin="manual")
    manual["producer"] = {
        "kind": "human",
        "review_id": "review-01",
        "operator_id": "operator-01",
    }
    corrected = _manifest(origin="corrected")
    corrected["producer"] = {
        "kind": "human",
        "review_id": "review-02",
        "operator_id": "operator-01",
        "base_revision_id": "revision-01",
    }
    synthetic_source = {
        "schema_version": "synthetic-fixture/v1",
        "fixture_id": "fixture-01",
        "fixture_digest": DIGEST,
    }
    synthetic = _manifest(source=synthetic_source)

    for fixture in (generated, manual, corrected, synthetic):
        parsed = parse_data_revision_bytes(canonical_data_revision_bytes(fixture))
        assert canonical_data_revision_bytes(parsed) == canonical_data_revision_bytes(fixture)

    human_content = _event_content()
    human_content["events"][0].pop("model_scores")
    for fixture in (manual, corrected):
        fixture["content_sha256"] = sha256_bytes(canonical_json_bytes(human_content))
        parsed = parse_data_revision_bytes(
            canonical_data_revision_bytes(fixture), canonical_event_data_bytes(human_content)
        )
        assert parsed.origin in {"manual", "corrected"}

    assert isinstance(
        parse_data_revision_bytes(canonical_data_revision_bytes(synthetic)).source,
        SyntheticFixtureSource,
    )


@pytest.mark.parametrize(
    ("fixture_name", "expected_bounds"),
    [
        ("event-data-point.json", (2_000_000, 2_000_000)),
        ("event-data-interval.json", (3_000_000, 4_250_000)),
    ],
)
def test_event_contract_fixtures_preserve_point_and_interval_bounds(
    fixture_name: str, expected_bounds: tuple[int, int]
) -> None:
    fixture = json.loads(
        (PIPELINE_EVENT_FIXTURES / fixture_name).read_text(encoding="utf-8")
    )

    parsed = parse_event_data_bytes(
        canonical_event_data_bytes(fixture), duration_us=10_000_000
    )

    event = parsed.events[0]
    assert (event.start_us, event.end_us) == expected_bounds
    assert canonical_event_data_bytes(parsed) == canonical_event_data_bytes(fixture)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value["source"].update(video_sha256="A" * 64), "source"),
        (lambda value: value["source"].update(duration_us=1), "time"),
        (lambda value: value["events"].append({"event_id": "event-01"}), "event"),
    ],
)
def test_event_revision_rejects_invalid_content_or_source(change, message: str) -> None:
    content = _event_content()
    manifest = _manifest()
    if message == "event":
        change(content)
        manifest["content_sha256"] = sha256_bytes(canonical_json_bytes(content))
        with pytest.raises(PipelineDataContractError):
            parse_event_data_bytes(canonical_event_data_bytes(content))
    else:
        if message == "time":
            manifest["source"]["duration_us"] = 0
        else:
            change(manifest)
        with pytest.raises(PipelineDataContractError):
            parse_data_revision_bytes(canonical_data_revision_bytes(manifest))


def test_event_data_rejects_unordered_events_and_non_finite_scores() -> None:
    content = _event_content()
    content["events"] = [
        {
            "event_id": "event-02",
            "event_type": CARD_STATE_CHANGED_EVENT_TYPE,
            "start_us": 2,
            "end_us": 3,
        },
        {
            "event_id": "event-01",
            "event_type": CARD_STATE_CHANGED_EVENT_TYPE,
            "start_us": 1,
            "end_us": 2,
        },
    ]
    with pytest.raises(PipelineDataContractError):
        parse_event_data_bytes(canonical_event_data_bytes(content))

    content = _event_content()
    content["events"][0]["model_scores"][0]["score"] = float("nan")
    with pytest.raises(ValueError):
        canonical_event_data_bytes(content)


def test_active_event_contract_rejects_retired_types_but_history_can_be_read() -> None:
    content = _event_content()
    content["events"][0]["event_type"] = "card_played"

    with pytest.raises(PipelineDataContractError, match="card_state_changed"):
        canonical_event_data_bytes(content)
    with pytest.raises(PipelineDataContractError, match="card_state_changed"):
        parse_event_data_bytes(canonical_json_bytes(content))

    historical = parse_event_data_bytes(canonical_json_bytes(content), allow_legacy=True)
    assert historical.events[0].event_type == "card_played"


def test_origin_lineage_rejects_fabricated_review_or_model_metadata() -> None:
    manual = _manifest(origin="manual")
    manual["producer"] = {
        "kind": "human",
        "review_id": "review-01",
        "operator_id": "operator-01",
        "model_id": "fabricated-model",
    }
    with pytest.raises(PipelineDataContractError):
        parse_data_revision_bytes(canonical_data_revision_bytes(manual))

    corrected = _manifest(origin="corrected")
    corrected["producer"] = {
        "kind": "human",
        "review_id": "review-01",
        "operator_id": "operator-01",
        "base_revision_id": "revision-01",
    }
    with pytest.raises(PipelineDataContractError):
        parse_event_data_revision_bytes(
            canonical_json_bytes({"manifest": corrected, "content": _event_content()})
        )


def test_run_request_freezes_exact_inputs_and_complete_policy_values() -> None:
    request = {
        "schema_version": PROCESSOR_RUN_REQUEST_SCHEMA_VERSION,
        "run_id": "run-01",
        "processor_type": "event-detection",
        "source": SOURCE,
        "input_revision_ids": ["revision-01", "revision-02"],
        "implementation": {"name": "event-worker", "version": "1"},
        "model": {"name": "CardEventNet", "version": "v2", "weights_sha256": DIGEST},
        "configuration": {"threshold": 0.5},
        "extraction_policy": {"policy_id": "exact-event/v1", "boundary": "source-duration"},
        "crop_policy": None,
    }
    parsed = parse_processor_run_request_bytes(canonical_processor_run_request_bytes(request))
    assert parsed.input_revision_ids == ("revision-01", "revision-02")
    assert parsed.extraction_policy["policy_id"] == "exact-event/v1"

    duplicate = dict(request, input_revision_ids=["revision-01", "revision-01"])
    with pytest.raises(PipelineDataContractError):
        parse_processor_run_request_bytes(canonical_processor_run_request_bytes(duplicate))


def test_selection_requires_integer_revision_and_distinct_pointer_roles() -> None:
    selection = {
        "schema_version": PIPELINE_SELECTION_SCHEMA_VERSION,
        "revision": 0,
        "recording_id": "recording-01",
        "content_type": "events",
        "selected_generated_revision_id": "revision-01",
        "selected_completed_reference_revision_id": None,
        "updated_at": "2026-09-05T10:00:00Z",
    }
    parsed = parse_pipeline_selection_bytes(canonical_pipeline_selection_bytes(selection))
    assert isinstance(parsed, PipelineSelection)
    assert parsed.revision == 0

    invalid = dict(selection, revision=True)
    with pytest.raises(PipelineDataContractError):
        parse_pipeline_selection_bytes(canonical_pipeline_selection_bytes(invalid))


def test_canonical_json_is_sorted_ascii_and_hashes_exact_bytes() -> None:
    value = {"z": "ä", "a": 1}
    assert canonical_json_bytes(value) == b'{"a":1,"z":"\\u00e4"}'
    assert hashlib.sha256(canonical_json_bytes(value)).hexdigest() == sha256_bytes(
        canonical_json_bytes(value)
    )


def test_source_objects_reject_boolean_integer_substitutions() -> None:
    source = dict(SOURCE, byte_length=True)
    with pytest.raises(PipelineDataContractError):
        RecordingVideoSource.from_mapping(source)


def test_run_state_keeps_execution_state_separate_from_review_state() -> None:
    state = {
        "schema_version": PROCESSOR_RUN_STATE_SCHEMA_VERSION,
        "run_id": "run-01",
        "status": "complete",
        "attempt": 1,
        "created_at": "2026-09-05T10:00:00Z",
        "started_at": "2026-09-05T10:00:01Z",
        "completed_at": "2026-09-05T10:00:02Z",
        "updated_at": "2026-09-05T10:00:02Z",
        "progress": {"completed": 1, "total": 1},
        "items": [
            {
                "item_id": "event-01",
                "status": "succeeded",
                "result": {"event_id": "event-01"},
                "failure": None,
            }
        ],
        "terminal_failure": None,
        "output_revision_ids": ["revision-01"],
        "metrics": {
            "schema_version": "cardeventnet-metrics/v1",
            "probabilities": [],
        },
    }
    parsed = parse_processor_run_state_bytes(canonical_processor_run_state_bytes(state))
    assert parsed.progress == RunProgress(completed=1, total=1)
    assert parsed.metrics["schema_version"] == "cardeventnet-metrics/v1"

    partial = dict(state, status="partial", progress={"completed": 0, "total": 1})
    parsed_partial = parse_processor_run_state_bytes(canonical_processor_run_state_bytes(partial))
    assert parsed_partial.status == "partial"
    assert parsed_partial.output_revision_ids == ("revision-01",)
