from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from table_evidence_analyzer.data import (
    build_smoke_fixture,
    load_dataset_manifest,
    load_split_manifest,
)
from table_evidence_analyzer.dinov3_calibration import (
    CALIBRATION_VIEW_SCHEMA,
    DinoV3CalibrationError,
    _probabilities,
    fit_dinov3_confidence_calibration,
    fit_temperature,
)
from table_evidence_analyzer.local_identity import VISUAL_IDENTITY_TARGETS


def _rows() -> list[dict[str, object]]:
    rows = []
    for index in range(8):
        logits = [-2.0] * len(VISUAL_IDENTITY_TARGETS)
        logits[0] = 8.0
        rows.append(
            {
                "sample_id": f"calibration-{index}",
                "source_lineage_group": {"recording": "calibration-only"},
                "target": VISUAL_IDENTITY_TARGETS[1],
                "logits": logits,
            }
        )
    return rows


def test_temperature_is_positive_rank_preserving_and_softens_overconfidence() -> None:
    rows = _rows()
    temperature, before, after = fit_temperature(rows)

    assert temperature > 1.0
    assert before > after
    raw = _probabilities(rows[0]["logits"], 1.0)
    calibrated = _probabilities(rows[0]["logits"], temperature)
    assert max(range(25), key=raw.__getitem__) == max(range(25), key=calibrated.__getitem__)
    assert calibrated[0] < raw[0]
    assert _probabilities(rows[0]["logits"], 1.0) == raw


def test_empty_or_overlapping_calibration_view_fails(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "best.pt").write_bytes(b"checkpoint")
    view = tmp_path / "view.json"
    output = tmp_path / "calibration.json"
    (run / "run.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "run_id": "run-1",
                "checkpoints": {"best": "best.pt"},
            }
        )
    )
    view.write_text(
        json.dumps(
            {
                "schema_version": CALIBRATION_VIEW_SCHEMA,
                "view_id": "empty-view",
                "run_id": "run-1",
                "source_checkpoint_sha256": hashlib.sha256(b"checkpoint").hexdigest(),
                "rows": [],
            }
        )
    )

    with pytest.raises(DinoV3CalibrationError, match="no rows"):
        fit_dinov3_confidence_calibration(run, view, output)


def test_calibration_rejects_training_lineage_and_retains_disjoint_view(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    dataset = load_dataset_manifest(fixture.dataset_path)
    lineage = dict(dataset.entries[0].group_keys)
    campaign = tmp_path / "campaign.json"
    campaign.write_text(
        json.dumps(
            {
                "state": "frozen",
                "items": [
                    {
                        "sample_id": entry.dataset_item_id,
                        "source_lineage_group": dict(entry.group_keys),
                    }
                    for entry in dataset.entries
                ],
            }
        )
    )
    run = tmp_path / "run"
    run.mkdir()
    checkpoint = run / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    (run / "run.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "run_id": "run-1",
                "config": {
                    "campaign_manifest": str(campaign),
                    "dataset": str(fixture.dataset_path),
                    "split": str(fixture.split_path),
                },
                "checkpoints": {"best": "best.pt"},
            }
        )
    )
    rows = _rows()
    view = tmp_path / "view.json"
    output = tmp_path / "calibration.json"

    overlapping = {
        "schema_version": CALIBRATION_VIEW_SCHEMA,
        "view_id": "overlap",
        "run_id": "run-1",
        "source_checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "rows": [{**rows[0], "source_lineage_group": lineage}],
    }
    view.write_text(json.dumps(overlapping))
    with pytest.raises(DinoV3CalibrationError, match="lineage overlaps"):
        fit_dinov3_confidence_calibration(run, view, output)

    split = load_split_manifest(fixture.split_path)
    overlapping_sample = {
        **overlapping,
        "view_id": "sample-overlap",
        "rows": [
            {
                **rows[0],
                "sample_id": split.train[0],
                "source_lineage_group": {"recording": "elsewhere"},
            }
        ],
    }
    view.write_text(json.dumps(overlapping_sample))
    with pytest.raises(DinoV3CalibrationError, match="sample IDs overlap"):
        fit_dinov3_confidence_calibration(run, view, output)

    disjoint = {**overlapping, "view_id": "reserved-calibration", "rows": rows}
    view.write_text(json.dumps(disjoint))
    result_path = fit_dinov3_confidence_calibration(run, view, output, review_precision_target=0.5)
    result = json.loads(result_path.read_text())
    assert result["temperature"] > 1
    assert result["sample_count"] == len(rows)
    assert result["confidence_report"]["review_threshold_selection"]["candidates_preserved"] is True
