import pytest

from doko_operations.source_exclusion import (
    NONPLANAR_RECORDING_ID,
    NONPLANAR_SOURCE_ASSET_ID,
    NONPLANAR_SOURCE_SHA256,
    SourceExclusionError,
    ensure_source_allowed,
)


@pytest.mark.parametrize(
    "identity",
    [
        {"recording_id": NONPLANAR_RECORDING_ID},
        {"source_asset_id": NONPLANAR_SOURCE_ASSET_ID},
        {"source_sha256": NONPLANAR_SOURCE_SHA256, "recording_id": "renamed"},
    ],
)
def test_nonplanar_source_remains_excluded_by_each_identity(identity: dict[str, str]) -> None:
    with pytest.raises(SourceExclusionError, match="permanently excluded.*non-flat surface"):
        ensure_source_allowed(**identity)


def test_failed_calibration_is_not_a_permanent_exclusion() -> None:
    ensure_source_allowed(recording_id="cardeventnet-IMG_0096")
