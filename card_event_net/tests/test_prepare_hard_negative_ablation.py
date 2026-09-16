from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import yaml


def _module():
    path = Path(__file__).parents[1] / "prepare_hard_negative_ablation.py"
    spec = importlib.util.spec_from_file_location("prepare_hard_negative_ablation", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_reviewed_manifest_keeps_only_no_event_items(tmp_path: Path) -> None:
    module = _module()
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(
        json.dumps(
            {
                "format": "cardevent-hard-negative-candidates-v1",
                "partition": "train",
                "training_input": False,
                "videos": [
                    {
                        "video": "cardeventnet-game",
                        "duration_s": 20.0,
                        "candidates": [
                            {
                                "id": "candidate-a",
                                "time_s": 4.0,
                                "probability": 0.9,
                            },
                            {
                                "id": "candidate-b",
                                "time_s": 8.0,
                                "probability": 0.8,
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "format": "cardevent-hard-negative-review-v1",
                "source_manifest_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "items": [
                    {
                        "id": "cardeventnet-game@4.000000",
                        "video": "cardeventnet-game",
                        "time_s": 4.0,
                        "probability": 0.9,
                        "decision": "no_event",
                    },
                    {
                        "id": "cardeventnet-game@8.000000",
                        "video": "cardeventnet-game",
                        "time_s": 8.0,
                        "probability": 0.8,
                        "decision": "missed_event",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    split_path = tmp_path / "split.yaml"
    split_path.write_text(yaml.safe_dump({"train": ["cardeventnet-game"]}), encoding="utf-8")
    output_path = tmp_path / "reviewed.json"

    payload = module.build_reviewed_manifest(
        candidate_path,
        review_path,
        split_path,
        output_path=output_path,
        campaign_id="cardeventnet-test-ablation",
    )

    assert payload["training_input"] is True
    assert payload["hard_negative_count"] == 1
    assert payload["review_decision_counts"] == {"missed_event": 1, "no_event": 1}
    assert payload["videos"][0]["hard_negatives"][0]["time_s"] == 4.0


def test_build_ablation_handoff_contains_only_manual_commands(tmp_path: Path) -> None:
    module = _module()
    manifest = tmp_path / "reviewed.json"
    manifest.write_text(json.dumps({"training_input": True}), encoding="utf-8")
    handoff_path = tmp_path / "handoff.json"

    payload = module.build_ablation_handoff(
        manifest,
        handoff_path=handoff_path,
        dataset_view=Path(".runtime/cardevent/datasets/interval"),
        config_path=Path("card_event_net/configs/transition-label-v2.yaml"),
        campaign_id="cardeventnet-test-ablation",
    )

    assert "--hard-negative-manifest" in payload["commands"]["train"]
    assert "--partition val" in payload["commands"]["evaluate"]
    assert "--partition test" not in payload["commands"]["train"]
    assert handoff_path.is_file()
