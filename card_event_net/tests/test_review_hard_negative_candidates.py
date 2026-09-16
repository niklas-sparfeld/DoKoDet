from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _reviewer_module():
    path = Path(__file__).parents[1] / "review_hard_negative_candidates.py"
    spec = importlib.util.spec_from_file_location("review_hard_negative_candidates", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_candidates_accepts_m9_review_only_manifest(tmp_path: Path) -> None:
    module = _reviewer_module()
    manifest = {
        "format": "cardevent-hard-negative-candidates-v1",
        "partition": "train",
        "training_input": False,
        "videos": [
            {
                "video": "cardeventnet-IMG_0092",
                "candidates": [{"time_s": 12.5, "probability": 0.75}],
            }
        ],
    }
    path = tmp_path / "m9-hard-negative-candidates.json"
    source = json.dumps(manifest).encode()
    path.write_bytes(source)

    candidates, digest = module.load_candidates(path)

    assert candidates == [
        {
            "id": "cardeventnet-IMG_0092@12.500000",
            "video": "cardeventnet-IMG_0092",
            "time_s": 12.5,
            "probability": 0.75,
            "decision": None,
        }
    ]
    assert digest == hashlib.sha256(source).hexdigest()


def test_load_candidates_rejects_m9_training_input_manifest(tmp_path: Path) -> None:
    module = _reviewer_module()
    path = tmp_path / "m9-hard-negative-candidates.json"
    path.write_text(
        json.dumps(
            {
                "format": "cardevent-hard-negative-candidates-v1",
                "partition": "train",
                "training_input": True,
                "videos": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="training_input: false"):
        module.load_candidates(path)
