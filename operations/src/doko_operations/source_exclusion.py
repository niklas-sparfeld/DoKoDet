"""Repository-wide source exclusions for data selection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SOURCE_EXCLUSION_SCHEMA_VERSION = "source-exclusion/v1"
LEGACY_DEVICE_EXCLUSION_RECEIPT_SCHEMA_VERSION = "legacy-device-exclusion/v1"
LEGACY_DEVICE_DIAGNOSTIC_ROLE = "legacy_device_diagnostic"
LEGACY_DEVICE_EXCLUSION_REASON = (
    "old-phone recordings are retained as diagnostic evidence only; their capture characteristics "
    "are not representative of future training or promotion decisions"
)
LEGACY_DEVICE_RECORDING_IDS = tuple(
    f"cardeventnet-IMG_{number}" for number in (2777, 2778, 2779, 2780, 2781)
)
LEGACY_DEVICE_SOURCE_ASSET_IDS = tuple(
    f"source-cardeventnet-IMG_{number}" for number in (2777, 2778, 2779, 2780, 2781)
)
LEGACY_DEVICE_SOURCE_DIGESTS = {
    "source-cardeventnet-IMG_2777": (
        "ccb1c0ca78558691af4a37c18eaac76a64d782aadc105cd0c779a5296e311e81"
    ),
    "source-cardeventnet-IMG_2778": (
        "9a9ccbdf365bd2addd919617fb28513e9700395b83b0b8b913713cb21da4a029"
    ),
    "source-cardeventnet-IMG_2779": (
        "3c4e2da8d5381aa5648e832ebc31efea09e20008cd7f72fc9b4e33a719660f93"
    ),
    "source-cardeventnet-IMG_2780": (
        "1c801078b400622dd91d43fd57f209ab5f364169dd07b0b6d4487d71dab9f046"
    ),
    "source-cardeventnet-IMG_2781": (
        "d851b5dd347ec9b91adefac2a641b27a3f8c80d308de8e320ad93f927ed458ee"
    ),
}
LEGACY_DEVICE_SOURCE_ASSET_ID_SET = frozenset(LEGACY_DEVICE_SOURCE_ASSET_IDS)
LEGACY_DEVICE_RECORDING_ID_SET = frozenset(LEGACY_DEVICE_RECORDING_IDS)
DEFAULT_SOURCE_EXCLUSION_PATH = Path(
    "data/operations/source-exclusions/legacy-device-diagnostic.json"
)


class SourceExclusionError(ValueError):
    """A source cannot be used by the requested dataset or model gate."""


def legacy_device_exclusion_reason(
    *, source_asset_id: str | None = None, recording_id: str | None = None
) -> str | None:
    """Return the exclusion reason when a source is in the diagnostic-only set."""

    if source_asset_id in LEGACY_DEVICE_SOURCE_ASSET_ID_SET or recording_id in (
        LEGACY_DEVICE_RECORDING_ID_SET
    ):
        return LEGACY_DEVICE_EXCLUSION_REASON
    return None


def ensure_source_allowed(
    *,
    source_asset_id: str | None = None,
    source_sha256: str | None = None,
    recording_id: str | None = None,
    context: str = "dataset source",
) -> None:
    """Reject a legacy-device source in every future dataset partition."""

    reason = legacy_device_exclusion_reason(
        source_asset_id=source_asset_id, recording_id=recording_id
    )
    if reason is None:
        return
    expected = (
        LEGACY_DEVICE_SOURCE_DIGESTS.get(source_asset_id)
        if isinstance(source_asset_id, str)
        else None
    )
    digest_note = ""
    if expected is not None and source_sha256 is not None and source_sha256 != expected:
        digest_note = " (source digest differs from the exclusion receipt)"
    raise SourceExclusionError(
        f"{context} is legacy-device diagnostic-only: "
        f"{source_asset_id or recording_id}{digest_note}; role={LEGACY_DEVICE_DIAGNOSTIC_ROLE}"
    )


def exclusion_path(repository_root: str | Path, path: str | Path | None = None) -> Path:
    """Resolve the repository-wide exclusion receipt path."""

    repository = Path(repository_root).expanduser().resolve()
    candidate = Path(path) if path is not None else DEFAULT_SOURCE_EXCLUSION_PATH
    return (repository / candidate if not candidate.is_absolute() else candidate).resolve()


def read_legacy_device_exclusion(
    repository_root: str | Path, path: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """Read and validate the exclusion receipt, returning its mapping and digest."""

    receipt_path = exclusion_path(repository_root, path)
    if not receipt_path.is_file():
        return None, None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceExclusionError(
            f"could not read source exclusion receipt: {receipt_path}"
        ) from error
    if not isinstance(receipt, Mapping):
        raise SourceExclusionError("source exclusion receipt must be an object")
    validate_legacy_device_exclusion(receipt)
    raw = receipt_path.read_bytes()
    return dict(receipt), hashlib.sha256(raw).hexdigest()


def validate_legacy_device_exclusion(receipt: Mapping[str, Any]) -> None:
    """Validate the complete five-source diagnostic-only exclusion receipt."""

    if receipt.get("schema_version") != LEGACY_DEVICE_EXCLUSION_RECEIPT_SCHEMA_VERSION:
        raise SourceExclusionError("source exclusion receipt schema is unsupported")
    if receipt.get("receipt_type") != LEGACY_DEVICE_DIAGNOSTIC_ROLE:
        raise SourceExclusionError("source exclusion receipt type is invalid")
    if receipt.get("role") != LEGACY_DEVICE_DIAGNOSTIC_ROLE:
        raise SourceExclusionError("source exclusion receipt role is invalid")
    if receipt.get("reason") != LEGACY_DEVICE_EXCLUSION_REASON:
        raise SourceExclusionError("source exclusion receipt reason is invalid")
    sources = receipt.get("sources")
    if not isinstance(sources, list):
        raise SourceExclusionError("source exclusion receipt sources must be a list")
    expected = set(LEGACY_DEVICE_SOURCE_ASSET_IDS)
    observed = {item.get("source_asset_id") for item in sources if isinstance(item, Mapping)}
    if observed != expected or len(sources) != len(expected):
        raise SourceExclusionError("source exclusion receipt must name exactly five source assets")
    for item in sources:
        if not isinstance(item, Mapping):
            raise SourceExclusionError("source exclusion receipt source is invalid")
        asset_id = item.get("source_asset_id")
        digest = item.get("source_sha256")
        recording_id = item.get("recording_id")
        if asset_id not in LEGACY_DEVICE_SOURCE_ASSET_ID_SET:
            raise SourceExclusionError("source exclusion receipt contains an unknown source")
        if digest != LEGACY_DEVICE_SOURCE_DIGESTS[asset_id]:
            raise SourceExclusionError(f"source exclusion digest is invalid for {asset_id}")
        expected_recording = asset_id.replace("source-", "", 1)
        if recording_id != expected_recording:
            raise SourceExclusionError(f"source exclusion recording ID is invalid for {asset_id}")
    receipt_digest = receipt.get("receipt_digest")
    core = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    encoded = json.dumps(
        core,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_digest = hashlib.sha256(encoded).hexdigest()
    if receipt_digest != expected_digest:
        raise SourceExclusionError("source exclusion receipt digest is invalid")


__all__ = [
    "DEFAULT_SOURCE_EXCLUSION_PATH",
    "LEGACY_DEVICE_DIAGNOSTIC_ROLE",
    "LEGACY_DEVICE_EXCLUSION_REASON",
    "LEGACY_DEVICE_EXCLUSION_RECEIPT_SCHEMA_VERSION",
    "LEGACY_DEVICE_RECORDING_IDS",
    "LEGACY_DEVICE_SOURCE_ASSET_IDS",
    "LEGACY_DEVICE_SOURCE_DIGESTS",
    "SourceExclusionError",
    "ensure_source_allowed",
    "exclusion_path",
    "legacy_device_exclusion_reason",
    "read_legacy_device_exclusion",
    "validate_legacy_device_exclusion",
]
