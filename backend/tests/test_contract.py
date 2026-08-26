import copy
import json
from pathlib import Path

import pytest

from dokodetector_backend.contract import (
    EvidenceManifest,
    calculate_package_fingerprint,
    parse_manifest_bytes,
    validate_manifest,
    validate_package_id,
)
from dokodetector_backend.errors import ContractError

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "evidence" / "v1"


def load_fixture(name: str) -> tuple[bytes, dict[str, object]]:
    raw = (FIXTURE_ROOT / name / "manifest.json").read_bytes()
    return raw, json.loads(raw)


@pytest.mark.parametrize(
    ("fixture_name", "expected_complete", "expected_frame_count"),
    [("example-complete", True, 6), ("example-incomplete", False, 2)],
)
def test_shared_manifest_fixtures_are_accepted(
    fixture_name: str, expected_complete: bool, expected_frame_count: int
) -> None:
    raw, _ = load_fixture(fixture_name)

    manifest = parse_manifest_bytes(raw)

    assert isinstance(manifest, EvidenceManifest)
    assert manifest.event.evidence_complete is expected_complete
    assert len(manifest.frames) == expected_frame_count


def test_metadata_only_manifest_is_accepted() -> None:
    _, payload = load_fixture("example-incomplete")
    payload["package_id"] = "550e8400-e29b-41d4-a716-446655440002"
    payload["frames"] = []
    payload["missing_frame_targets_ms"] = payload["evidence_capture"]["target_offsets_ms"]
    payload["event"]["evidence_complete"] = False

    manifest = validate_manifest(payload)

    assert manifest.frames == []
    assert manifest.missing_frame_targets_ms == [-800, -400, -100, 150, 400, 700]


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload.update(package_id="not-a-uuid"),
        lambda payload: payload["session"].update(event_sequence=0),
        lambda payload: payload["evidence_capture"].update(target_offsets_ms=[-800, -800]),
        lambda payload: payload.update(missing_frame_targets_ms=[-400, -400, -100, 400, 700]),
        lambda payload: payload["event"].update(evidence_complete=False),
        lambda payload: payload["frames"][0].update(part_name="../frame_00"),
        lambda payload: payload["frames"][1].update(target_offset_ms=-800),
        lambda payload: payload["frames"][0].update(content_type="image/png"),
    ],
)
def test_malformed_manifest_is_rejected(change) -> None:
    _, original = load_fixture("example-complete")
    payload = copy.deepcopy(original)
    change(payload)

    with pytest.raises(ContractError) as error:
        validate_manifest(payload)

    assert error.value.code == "invalid_manifest"


def test_package_id_must_match_the_manifest() -> None:
    raw, _ = load_fixture("example-complete")
    manifest = parse_manifest_bytes(raw)

    with pytest.raises(ContractError) as error:
        validate_package_id("550e8400-e29b-41d4-a716-446655440099", manifest)

    assert error.value.code == "package_id_mismatch"


def test_package_fingerprint_ignores_frame_order() -> None:
    raw, _ = load_fixture("example-complete")
    manifest = parse_manifest_bytes(raw)

    fingerprint = calculate_package_fingerprint(raw, manifest.frames)
    reordered = calculate_package_fingerprint(raw, reversed(manifest.frames))

    assert reordered == fingerprint


def test_package_fingerprint_includes_manifest_bytes_and_frame_content() -> None:
    raw, _ = load_fixture("example-complete")
    manifest = parse_manifest_bytes(raw)
    changed_frame = manifest.frames[0].model_copy(update={"byte_length": 999999})

    original = calculate_package_fingerprint(raw, manifest.frames)
    changed_manifest = calculate_package_fingerprint(raw + b"\n", manifest.frames)
    changed_frame_fingerprint = calculate_package_fingerprint(
        raw, [changed_frame, *manifest.frames[1:]]
    )

    assert changed_manifest != original
    assert changed_frame_fingerprint != original


def test_manifest_parser_returns_stable_error_without_local_details() -> None:
    with pytest.raises(ContractError) as error:
        parse_manifest_bytes(b"not-json")

    assert error.value.code == "invalid_manifest"
    assert "not-json" not in error.value.message
    assert error.value.details == []
