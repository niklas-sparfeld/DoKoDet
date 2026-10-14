from __future__ import annotations

import json
from pathlib import Path

import pytest

import doko_operations.reviewed_visible_card_handoff as handoff_module
from doko_operations.reviewed_visible_card_handoff import (
    HANDOFF_SCHEMA_VERSION,
    sha256_json,
    validate_reviewed_visible_card_handoff,
)


def _handoff() -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "status": "ready",
        "eligible_recordings": [
            {"recording_id": "recording-1", "reference": {"content_schema": "visible-card-data/v2"}}
        ],
    }
    return {**core, "handoff_sha256": sha256_json(core)}


def test_handoff_validator_accepts_digest_backed_v2_references() -> None:
    validate_reviewed_visible_card_handoff(_handoff())


def test_handoff_validator_rejects_content_changed_after_sealing() -> None:
    handoff = _handoff()
    handoff["eligible_recordings"] = []

    with pytest.raises(ValueError, match="digest does not match"):
        validate_reviewed_visible_card_handoff(handoff)


def test_handoff_validator_rejects_legacy_reference_schema() -> None:
    handoff = _handoff()
    eligible = handoff["eligible_recordings"]
    assert isinstance(eligible, list)
    eligible[0]["reference"]["content_schema"] = "visible-card-data/v1"
    core = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    handoff["handoff_sha256"] = sha256_json(core)

    with pytest.raises(ValueError, match="non-v2"):
        validate_reviewed_visible_card_handoff(handoff)


@pytest.mark.parametrize("tamper", [False, True])
def test_operator_dispositions_are_applied_before_reading_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: bool
) -> None:
    reports = tmp_path / "docs/reports"
    reports.mkdir(parents=True)
    ids = ["permanent", "temporary"]
    inventory = {
        "schema_version": "reviewed-virtual-card-corpus-work-manifest/v1",
        "scope": {"candidate_recordings": ids},
        "recordings": [{"recording_id": rid} for rid in ids],
    }
    inventory["manifest_sha256"] = sha256_json(inventory)
    (tmp_path / handoff_module.DEFAULT_INVENTORY).write_text(json.dumps(inventory))
    dispositions = {
        "schema_version": "0086-recording-dispositions/v1",
        "recordings": {
            "permanent": {"disposition": "permanently_excluded", "reason": "non-flat surface"},
            "temporary": {"disposition": "deferred", "reason": "calibration repair"},
        },
    }
    dispositions["receipt_sha256"] = sha256_json(dispositions)
    if tamper:
        dispositions["recordings"]["temporary"]["reason"] = "changed"
    (tmp_path / handoff_module.DEFAULT_DISPOSITIONS).write_text(json.dumps(dispositions))

    def fail_if_read(*args: object, **kwargs: object) -> None:
        pytest.fail("excluded and deferred sources must not be read")

    monkeypatch.setattr(handoff_module, "_bundle_audit", fail_if_read)
    if tamper:
        with pytest.raises(ValueError, match="dispositions schema or digest is invalid"):
            handoff_module.build_reviewed_visible_card_handoff(tmp_path)
    else:
        result = handoff_module.build_reviewed_visible_card_handoff(tmp_path)
        assert result["summary"]["excluded_recording_count"] == 2
        assert [item["disposition"] for item in result["excluded_recordings"]] == [
            "permanently_excluded",
            "deferred",
        ]
