"""Check the explicit 0100 local model recipe without running inference."""

from __future__ import annotations

import json
import sys
from importlib.util import find_spec
from typing import Any

from table_evidence_analyzer import load_dinov3_identity_bundle, load_rfdetr_segmentation_bundle

from .config import Settings
from .event_pipeline_service import _discover_checkpoint_defaults, _sha256_file


class LocalPreflightError(ValueError):
    """The local trial settings or retained model artifacts are not ready."""


def check_local_recipe(settings: Settings) -> dict[str, Any]:
    """Validate effective settings, frozen identities, bundle bytes, and devices."""
    root = settings.repository_root
    assert root is not None
    freeze_path = root / "docs/reports/0090-M0_Composed_Pilot_Freeze.json"
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))["models"]
        event = freeze["event_detector"]
        detector = freeze["visible_card_detector"]
        identity = freeze["visual_identity"]
        contract = json.loads(
            (
                root / "data/model-campaigns/cardeventnet-0063-m14-development-integration/"
                "integration-contract.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise LocalPreflightError(f"Cannot read the 0090 model freeze: {error}") from error

    expected = {
        "visible_card_provider": "local-rfdetr-segmentation",
        "visible_card_identity_classifier": "local",
        "visible_card_segmentation_bundle_path": root / detector["bundle_path"],
        "visible_card_identity_bundle_path": root / identity["bundle_path"],
    }
    for field, value in expected.items():
        actual = getattr(settings, field)
        if actual != value:
            raise LocalPreflightError(
                f"{field} is {actual!s}; the local trial requires {value!s}. "
                "Export backend/local-pipeline.env.example and check backend/.env."
            )
    defaults = _discover_checkpoint_defaults(root)
    if (
        defaults is None
        or defaults.path != root / event["checkpoint_path"]
        or _sha256_file(defaults.path) != event["checkpoint_sha256"]
        or defaults.threshold != event["threshold"]
        or defaults.merge_window_s != event["decoder"]["min_event_gap_s"]
        or contract.get("decoder") != event["decoder"]
    ):
        raise LocalPreflightError(
            "The 0063 integration contract or checkpoint is missing, invalid, or differs from "
            "the 0090 freeze. Restore the retained contract and checkpoint."
        )
    if settings.card_event_checkpoint_path not in (None, defaults.path):
        raise LocalPreflightError(
            "CARD_EVENT_CHECKPOINT_PATH overrides the frozen checkpoint; remove the stale setting."
        )
    devices = {
        "CardEventNet": settings.card_event_device,
        "visible-card detector": settings.visible_card_device,
        "identity classifier": settings.visible_card_identity_device,
    }
    for component, device in devices.items():
        if device not in {"cpu", "mps"}:
            raise LocalPreflightError(f"Set the {component} device explicitly to cpu or mps.")
    for module in ("torch", "rfdetr", "transformers"):
        if find_spec(module) is None:
            raise LocalPreflightError(
                f"The {module} inference dependency is missing. Run "
                "uv sync --project backend --group inference."
            )
    if "mps" in devices.values():
        try:
            import torch

            available = torch.backends.mps.is_available()
        except (ImportError, AttributeError) as error:
            raise LocalPreflightError("Cannot check MPS availability; install PyTorch.") from error
        if not available:
            raise LocalPreflightError("MPS is unavailable. Select cpu or use a Mac with MPS.")

    try:
        detector_bundle = load_rfdetr_segmentation_bundle(
            expected["visible_card_segmentation_bundle_path"]
        )
        identity_bundle = load_dinov3_identity_bundle(expected["visible_card_identity_bundle_path"])
    except Exception as error:
        raise LocalPreflightError(f"Cannot validate the retained model bundle: {error}") from error
    for label, bundle, frozen in (
        ("detector", detector_bundle, detector),
        ("identity", identity_bundle, identity),
    ):
        if bundle.manifest.get("bundle_digest") != frozen["bundle_digest"]:
            raise LocalPreflightError(f"The {label} bundle differs from the 0090 freeze.")
    return {
        "event_checkpoint_sha256": event["checkpoint_sha256"],
        "event_threshold": defaults.threshold,
        "event_decoder": event["decoder"],
        "detector_bundle_digest": detector["bundle_digest"],
        "identity_bundle_digest": identity["bundle_digest"],
        "crop_policy": identity["crop_policy"],
        "devices": devices,
    }


def main() -> None:
    try:
        report = check_local_recipe(Settings())
    except (LocalPreflightError, ValueError) as error:
        print(f"Local pipeline preflight failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
