from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dokodetector_backend import local_pipeline_preflight as preflight
from dokodetector_backend.config import Settings
from dokodetector_backend.pipeline_coordinator import frozen_pilot_stage_plan


@pytest.fixture
def recipe(tmp_path, monkeypatch):
    root = tmp_path
    freeze = {
        "event_detector": {
            "checkpoint_path": "checkpoint.pt",
            "checkpoint_sha256": "event-digest",
            "threshold": 0.4,
            "decoder": {"min_event_gap_s": 0.625},
        },
        "visible_card_detector": {"bundle_path": "detector", "bundle_digest": "detector-digest"},
        "visual_identity": {
            "bundle_path": "identity",
            "bundle_digest": "identity-digest",
            "crop_policy": "predicted_visible_region",
        },
    }
    path = root / "docs/reports/0090-M0_Composed_Pilot_Freeze.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"models": freeze}), encoding="utf-8")
    contract = root / (
        "data/model-campaigns/cardeventnet-0063-m14-development-integration/"
        "integration-contract.json"
    )
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps({"decoder": freeze["event_detector"]["decoder"]}))
    monkeypatch.setattr(preflight, "find_spec", lambda name: object())
    monkeypatch.setattr(
        preflight,
        "_discover_checkpoint_defaults",
        lambda root: SimpleNamespace(
            path=root / "checkpoint.pt", threshold=0.4, merge_window_s=0.625
        ),
    )
    monkeypatch.setattr(preflight, "_sha256_file", lambda path: "event-digest")
    monkeypatch.setattr(
        preflight,
        "load_rfdetr_segmentation_bundle",
        lambda path: SimpleNamespace(manifest={"bundle_digest": "detector-digest"}),
    )
    monkeypatch.setattr(
        preflight,
        "load_dinov3_identity_bundle",
        lambda path: SimpleNamespace(manifest={"bundle_digest": "identity-digest"}),
    )
    return Settings(
        _env_file=None,
        repository_root=root,
        card_event_device="cpu",
        visible_card_provider="local-rfdetr-segmentation",
        visible_card_segmentation_bundle_path=root / "detector",
        visible_card_device="cpu",
        visible_card_identity_classifier="local",
        visible_card_identity_bundle_path=root / "identity",
        visible_card_identity_device="cpu",
    )


def test_local_recipe_records_exact_model_choices(recipe):
    result = preflight.check_local_recipe(recipe)
    assert result["detector_bundle_digest"] == "detector-digest"
    assert result["identity_bundle_digest"] == "identity-digest"
    assert result["crop_policy"] == "predicted_visible_region"
    assert set(result["devices"].values()) == {"cpu"}


def test_coordinator_example_selects_local_models_and_rfdetr_crops():
    example = Path(__file__).parents[1] / "local-pipeline.requests.example.json"
    requests = json.loads(example.read_text(encoding="utf-8"))
    plan = frozen_pilot_stage_plan(requests)
    assert len(plan) == 6
    assert requests["visible_card_and_pile_proposals"]["configuration"]["provider"] == (
        "local-rfdetr-segmentation"
    )
    identity = requests["visual_identity_proposals"]
    assert identity["configuration"]["provider"] == "local"
    assert identity["crop_input_kind"] == "rfdetr_segment"
    assert identity["crop_policy"] == {
        "policy_id": "predicted_visible_region",
        "output_encoding": "ppm",
    }


def test_local_recipe_rejects_stale_settings(recipe):
    recipe.visible_card_identity_classifier = "gemini"
    with pytest.raises(preflight.LocalPreflightError, match="visible_card_identity_classifier"):
        preflight.check_local_recipe(recipe)


def test_local_recipe_rejects_invalid_or_missing_bundle(recipe, monkeypatch):
    def fail(path):
        raise ValueError("unsupported bundle schema")

    monkeypatch.setattr(preflight, "load_dinov3_identity_bundle", fail)
    with pytest.raises(preflight.LocalPreflightError, match="unsupported bundle schema"):
        preflight.check_local_recipe(recipe)


def test_local_recipe_rejects_wrong_bundle_digest(recipe, monkeypatch):
    monkeypatch.setattr(
        preflight,
        "load_rfdetr_segmentation_bundle",
        lambda path: SimpleNamespace(manifest={"bundle_digest": "wrong"}),
    )
    with pytest.raises(preflight.LocalPreflightError, match="detector bundle differs"):
        preflight.check_local_recipe(recipe)


def test_local_recipe_requires_devices_and_frozen_event_model(recipe):
    recipe.card_event_device = None
    with pytest.raises(preflight.LocalPreflightError, match="CardEventNet device"):
        preflight.check_local_recipe(recipe)
    recipe.card_event_device = "cpu"
    recipe.card_event_checkpoint_path = recipe.repository_root / "other.pt"
    with pytest.raises(preflight.LocalPreflightError, match="overrides the frozen checkpoint"):
        preflight.check_local_recipe(recipe)


def test_local_recipe_rejects_unavailable_mps(recipe, monkeypatch):
    recipe.visible_card_device = "mps"
    fake_torch = SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    with pytest.raises(preflight.LocalPreflightError, match="MPS is unavailable"):
        preflight.check_local_recipe(recipe)


def test_local_recipe_rejects_missing_inference_dependency(recipe, monkeypatch):
    monkeypatch.setattr(preflight, "find_spec", lambda name: None if name == "rfdetr" else object())
    with pytest.raises(
        preflight.LocalPreflightError, match="rfdetr inference dependency is missing"
    ):
        preflight.check_local_recipe(recipe)
