from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from dokodetector_backend.errors import ContractError
from dokodetector_backend.recording_contract import (
    DevicePredictions,
    RecordingManifest,
    parse_device_predictions_bytes,
    parse_recording_manifest_bytes,
    validate_recording_bundle,
)

FIXTURE_ROOT = (
    Path(__file__).parents[2] / "fixtures" / "training-recording" / "v1" / "recording-fixture-001"
)


def load_fixture() -> tuple[bytes, bytes, bytes, dict[str, object], dict[str, object]]:
    manifest_bytes = (FIXTURE_ROOT / "manifest.json").read_bytes()
    predictions_bytes = (FIXTURE_ROOT / "video-fixture-001.json").read_bytes()
    video_bytes = (FIXTURE_ROOT / "video-fixture-001.mov").read_bytes()
    return (
        manifest_bytes,
        predictions_bytes,
        video_bytes,
        json.loads(manifest_bytes),
        json.loads(predictions_bytes),
    )


def test_shared_fixture_is_accepted_and_its_counts_are_checked() -> None:
    manifest_bytes, predictions_bytes, video_bytes, _, _ = load_fixture()

    manifest, predictions = validate_recording_bundle(
        manifest_bytes, predictions_bytes, video_bytes
    )

    assert isinstance(manifest, RecordingManifest)
    assert isinstance(predictions, DevicePredictions)
    assert manifest.video.name == predictions.source_video
    assert len(predictions.probabilities) == manifest.predictions.sample_count
    assert len(predictions.event_proposals) == manifest.predictions.event_proposal_count
    assert manifest.collection_metadata.table_setup == "table-fixture-v1"
    assert {enrollment.task for enrollment in manifest.task_enrollments} == {
        "cardevent_event_detection",
        "table_evidence_analysis",
    }


def test_schema_documents_and_versioned_documents_are_present() -> None:
    schema_root = Path(__file__).parents[2] / "schemas" / "training-recording"
    manifest_schema = json.loads(
        (schema_root / "recording-manifest-v1.schema.json").read_text(encoding="utf-8")
    )
    predictions_schema = json.loads(
        (schema_root / "device-predictions-v1.schema.json").read_text(encoding="utf-8")
    )

    assert manifest_schema["properties"]["schema_version"]["const"] == "cardevent-recording/v1"
    assert (
        predictions_schema["properties"]["schema_version"]["const"]
        == "cardevent-device-predictions/v1"
    )


@pytest.mark.parametrize(
    ("name", "change", "expected_code"),
    [
        (
            "wrong video hash",
            lambda manifest, _: manifest["video"].update(
                sha256="0000000000000000000000000000000000000000000000000000000000000000"
            ),
            "recording_hash_mismatch",
        ),
        (
            "wrong file name",
            lambda manifest, _: manifest["video"].update(name="other-video.mov"),
            "invalid_recording_manifest",
        ),
        (
            "non-monotonic probability time",
            lambda _, predictions: predictions["probabilities"][0].update(time_s=0.2),
            "invalid_device_predictions",
        ),
        (
            "non-causal event proposal",
            lambda _, predictions: predictions["event_proposals"][0].update(
                emitted_at_s=0.1, time_s=0.2
            ),
            "invalid_device_predictions",
        ),
        (
            "wrong source video identity",
            lambda _, predictions: predictions.update(source_video="other-video.mov"),
            "recording_identity_mismatch",
        ),
        (
            "unknown manifest field",
            lambda manifest, _: manifest.update(unexpected="not allowed"),
            "invalid_recording_manifest",
        ),
    ],
)
def test_shared_malformed_variants_are_rejected(name, change, expected_code) -> None:
    manifest_bytes, predictions_bytes, video_bytes, manifest, predictions = load_fixture()
    manifest = copy.deepcopy(manifest)
    predictions = copy.deepcopy(predictions)
    change(manifest, predictions)
    changed_manifest = json.dumps(manifest, separators=(",", ":")).encode()
    changed_predictions = json.dumps(predictions, separators=(",", ":")).encode()

    with pytest.raises(ContractError) as error:
        validate_recording_bundle(changed_manifest, changed_predictions, video_bytes)

    assert error.value.code == expected_code, name


def test_individual_documents_decode_with_the_shared_types() -> None:
    manifest_bytes, predictions_bytes, _, _, _ = load_fixture()

    manifest = parse_recording_manifest_bytes(manifest_bytes)
    predictions = parse_device_predictions_bytes(predictions_bytes)

    assert manifest.recording_id == "recording-fixture-001"
    assert predictions.probabilities[1].time_s == 0.125
