from __future__ import annotations

import pytest

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
