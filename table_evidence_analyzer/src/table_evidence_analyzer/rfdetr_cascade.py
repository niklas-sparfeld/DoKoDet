"""Assembly and validation for the epic 0071 production cascade bundle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rfdetr_card_cluster_training import (
    RFDETR_CARD_CLUSTER_BUNDLE_SCHEMA,
    RFDETR_CARD_CLUSTER_INPUT_SIZE,
    RFDETR_CARD_CLUSTER_MODEL_CLASS,
    RfdetrCardClusterBundle,
    load_rfdetr_card_cluster_bundle,
)
from .rfdetr_segmentation_training import (
    RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
    RFDETR_SEGMENTATION_INPUT_SIZE,
    RFDETR_SEGMENTATION_MODEL_CLASS,
    RfdetrSegmentationBundle,
    load_rfdetr_segmentation_bundle,
)
from .visible_card_cascade import frozen_cascade_recipe

RFDETR_CASCADE_BUNDLE_SCHEMA = "rfdetr-cascade-bundle/v1"
RFDETR_CASCADE_CAMPAIGN_ID = "0071-m6-rfdetr-cascade"
RFDETR_CASCADE_PROVIDER_NAME = "local-rfdetr-cascade"
RFDETR_CASCADE_QUALITY_STATE = "unreviewed"


class RfdetrCascadeBundleError(ValueError):
    """The two-stage cascade bundle cannot be trusted."""


@dataclass(frozen=True, slots=True)
class RfdetrCascadeBundle:
    """A digest-checked manifest over one coarse and one fine child bundle."""

    root: Path
    manifest: dict[str, Any]
    coarse_bundle: RfdetrCardClusterBundle
    fine_bundle: RfdetrSegmentationBundle


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RfdetrCascadeBundleError("cascade values must be finite JSON") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise RfdetrCascadeBundleError(f"could not read cascade file: {path}") from error


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RfdetrCascadeBundleError(f"could not read {context}: {path}") from error
    if not isinstance(value, dict):
        raise RfdetrCascadeBundleError(f"{context} must be an object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical(value) + b"\n")
    temporary.replace(path)


def _required_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RfdetrCascadeBundleError(f"{field} must be a lower-case SHA-256 digest")
    return value


def _child_descriptor(
    root: Path,
    child_root: Path,
    *,
    schema_version: str,
    model_class: str,
    input_size: int,
    bundle_digest: str,
    checkpoint_sha256: str,
) -> dict[str, Any]:
    child_root = child_root.expanduser().resolve()
    try:
        path_value = child_root.relative_to(root).as_posix()
    except ValueError:
        path_value = str(child_root)
    return {
        "path": path_value,
        "schema_version": schema_version,
        "model_class": model_class,
        "input_size": [input_size, input_size],
        "bundle_digest": bundle_digest,
        "manifest_sha256": _file_digest(child_root / "manifest.json"),
        "checkpoint_sha256": checkpoint_sha256,
    }


def assemble_rfdetr_cascade_bundle(
    *,
    coarse_bundle: str | Path,
    fine_bundle: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write one M6 manifest over the validated M3 and M5 child bundles."""

    output = Path(output_dir).expanduser().resolve()
    coarse = load_rfdetr_card_cluster_bundle(coarse_bundle)
    fine = load_rfdetr_segmentation_bundle(fine_bundle)
    recipe = frozen_cascade_recipe()
    recipe_with_digest = {**recipe, "recipe_digest": _digest(recipe)}
    manifest_core: dict[str, Any] = {
        "schema_version": RFDETR_CASCADE_BUNDLE_SCHEMA,
        "component": "visible-card-coarse-to-fine-cascade",
        "quality_state": RFDETR_CASCADE_QUALITY_STATE,
        "campaign_id": RFDETR_CASCADE_CAMPAIGN_ID,
        "provider": RFDETR_CASCADE_PROVIDER_NAME,
        "selectable": True,
        "default": False,
        "recipe": recipe_with_digest,
        "children": {
            "coarse": _child_descriptor(
                output,
                coarse.root,
                schema_version=RFDETR_CARD_CLUSTER_BUNDLE_SCHEMA,
                model_class=RFDETR_CARD_CLUSTER_MODEL_CLASS,
                input_size=RFDETR_CARD_CLUSTER_INPUT_SIZE,
                bundle_digest=coarse.manifest["bundle_digest"],
                checkpoint_sha256=coarse.manifest["checkpoint_sha256"],
            ),
            "fine": _child_descriptor(
                output,
                fine.root,
                schema_version=RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
                model_class=RFDETR_SEGMENTATION_MODEL_CLASS,
                input_size=RFDETR_SEGMENTATION_INPUT_SIZE,
                bundle_digest=fine.manifest["bundle_digest"],
                checkpoint_sha256=fine.manifest["checkpoint_sha256"],
            ),
        },
        "thresholds": {
            "coarse": coarse.manifest["confidence_threshold"],
            "fine": fine.manifest["confidence_threshold"],
        },
        "lineage": {
            "coarse_campaign": coarse.manifest.get("campaign_id"),
            "fine_campaign": fine.manifest.get("campaign_id"),
            "coarse_materialization_digest": coarse.manifest.get("materialization_digest"),
            "fine_materialization_digest": fine.manifest.get("materialization_digest"),
            "fine_initializer_bundle_digest": fine.manifest.get("initializer_bundle_digest"),
        },
    }
    manifest = {**manifest_core, "bundle_digest": _digest(manifest_core)}
    _write_json(output / "manifest.json", manifest)
    return manifest


def _resolve_child(root: Path, descriptor: Mapping[str, Any], field: str) -> Path:
    path_value = descriptor.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise RfdetrCascadeBundleError(f"cascade {field} child path is invalid")
    child = Path(path_value)
    if not child.is_absolute():
        child = root / child
    return child.expanduser().resolve()


def _validate_child_descriptor(
    *,
    root: Path,
    descriptor: Mapping[str, Any],
    field: str,
    expected_schema: str,
    expected_model: str,
    expected_input_size: int,
) -> tuple[Path, dict[str, Any]]:
    child = _resolve_child(root, descriptor, field)
    manifest = _read_json(child / "manifest.json", f"cascade {field} child manifest")
    if descriptor.get("schema_version") != expected_schema:
        raise RfdetrCascadeBundleError(f"cascade {field} child schema is invalid")
    if descriptor.get("model_class") != expected_model:
        raise RfdetrCascadeBundleError(f"cascade {field} child model class is invalid")
    if descriptor.get("input_size") != [expected_input_size, expected_input_size]:
        raise RfdetrCascadeBundleError(f"cascade {field} child input size is invalid")
    if descriptor.get("bundle_digest") != manifest.get("bundle_digest"):
        raise RfdetrCascadeBundleError(f"cascade {field} child bundle digest does not match")
    if descriptor.get("manifest_sha256") != _file_digest(child / "manifest.json"):
        raise RfdetrCascadeBundleError(f"cascade {field} child manifest digest does not match")
    if descriptor.get("checkpoint_sha256") != manifest.get("checkpoint_sha256"):
        raise RfdetrCascadeBundleError(f"cascade {field} child checkpoint digest does not match")
    return child, manifest


def load_rfdetr_cascade_bundle(path: str | Path) -> RfdetrCascadeBundle:
    """Validate the M6 manifest, M0 recipe, and both native child bundles."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise RfdetrCascadeBundleError(f"cascade bundle does not exist: {root}")
    manifest = _read_json(root / "manifest.json", "cascade bundle manifest")
    if manifest.get("schema_version") != RFDETR_CASCADE_BUNDLE_SCHEMA:
        raise RfdetrCascadeBundleError("cascade bundle schema is unsupported")
    if manifest.get("component") != "visible-card-coarse-to-fine-cascade":
        raise RfdetrCascadeBundleError("cascade bundle component is invalid")
    if manifest.get("quality_state") != RFDETR_CASCADE_QUALITY_STATE:
        raise RfdetrCascadeBundleError("cascade bundle quality state is invalid")
    if manifest.get("provider") != RFDETR_CASCADE_PROVIDER_NAME:
        raise RfdetrCascadeBundleError("cascade bundle provider is invalid")
    if manifest.get("selectable") is not True or manifest.get("default") is not False:
        raise RfdetrCascadeBundleError("cascade bundle selection flags are invalid")
    recipe = manifest.get("recipe")
    expected_recipe = frozen_cascade_recipe()
    if not isinstance(recipe, Mapping) or dict(recipe) != {
        **expected_recipe,
        "recipe_digest": _digest(expected_recipe),
    }:
        raise RfdetrCascadeBundleError("cascade bundle M0 recipe is stale or changed")
    if manifest.get("bundle_digest") != _digest(
        {key: value for key, value in manifest.items() if key != "bundle_digest"}
    ):
        raise RfdetrCascadeBundleError("cascade bundle digest does not match contents")
    children = manifest.get("children")
    if not isinstance(children, Mapping) or set(children) != {"coarse", "fine"}:
        raise RfdetrCascadeBundleError("cascade bundle children are incomplete")
    coarse_descriptor = children.get("coarse")
    fine_descriptor = children.get("fine")
    if not isinstance(coarse_descriptor, Mapping) or not isinstance(fine_descriptor, Mapping):
        raise RfdetrCascadeBundleError("cascade child descriptors must be objects")
    coarse_path, _ = _validate_child_descriptor(
        root=root,
        descriptor=coarse_descriptor,
        field="coarse",
        expected_schema=RFDETR_CARD_CLUSTER_BUNDLE_SCHEMA,
        expected_model=RFDETR_CARD_CLUSTER_MODEL_CLASS,
        expected_input_size=RFDETR_CARD_CLUSTER_INPUT_SIZE,
    )
    fine_path, _ = _validate_child_descriptor(
        root=root,
        descriptor=fine_descriptor,
        field="fine",
        expected_schema=RFDETR_SEGMENTATION_BUNDLE_SCHEMA,
        expected_model=RFDETR_SEGMENTATION_MODEL_CLASS,
        expected_input_size=RFDETR_SEGMENTATION_INPUT_SIZE,
    )
    coarse = load_rfdetr_card_cluster_bundle(coarse_path)
    fine = load_rfdetr_segmentation_bundle(fine_path)
    if manifest.get("thresholds") != {
        "coarse": coarse.manifest["confidence_threshold"],
        "fine": fine.manifest["confidence_threshold"],
    }:
        raise RfdetrCascadeBundleError("cascade thresholds do not match child bundles")
    return RfdetrCascadeBundle(root, manifest, coarse, fine)


__all__ = [
    "RFDETR_CASCADE_BUNDLE_SCHEMA",
    "RFDETR_CASCADE_CAMPAIGN_ID",
    "RFDETR_CASCADE_PROVIDER_NAME",
    "RfdetrCascadeBundle",
    "RfdetrCascadeBundleError",
    "assemble_rfdetr_cascade_bundle",
    "load_rfdetr_cascade_bundle",
]
