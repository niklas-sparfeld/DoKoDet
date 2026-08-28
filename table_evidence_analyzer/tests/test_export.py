from pathlib import Path

import pytest

from table_evidence_analyzer.data import build_smoke_fixture
from table_evidence_analyzer.export import export_bundle, load_bundle
from table_evidence_analyzer.training import TrainConfig, train


def test_export_bundle_is_hash_checked_and_classifies_crop_without_training_import(
    tmp_path: Path,
) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    run = tmp_path / "run"
    train(
        TrainConfig(
            dataset=fixture.dataset_path,
            split=fixture.split_path,
            artifacts=fixture.artifact_index_path,
            output=run,
        )
    )
    bundle_path = export_bundle(run, tmp_path / "bundle")
    bundle = load_bundle(bundle_path)
    candidates = bundle.classify(fixture.frame_paths[0])
    assert bundle.manifest["capabilities"] == ["identity_candidates"]
    assert bundle.manifest["calibration"] == "uncalibrated"
    assert sum(candidate.probability for candidate in candidates) == pytest.approx(1.0)
    model = bundle_path / "model.json"
    model.write_text(model.read_text().replace("0.0", "1.0"), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_bundle(bundle_path)
