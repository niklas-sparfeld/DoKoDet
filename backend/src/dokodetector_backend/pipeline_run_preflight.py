"""Resolve local processor providers and freeze their request identities."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from dokodetector_backend.event_pipeline_service import CardEventFileProvider


def validate_local_stage_providers(
    recording_id: str,
    stage_requests: Mapping[str, Any],
    *,
    event_service: Any,
    visible_card_service: Any,
    visual_identity_service: Any,
) -> dict[str, Any]:
    """Check local model availability and freeze provider identities into stage settings."""

    frozen = {name: dict(value) for name, value in stage_requests.items()}
    providers: dict[str, Any] = {}

    event_provider = event_service.event_provider
    if not isinstance(event_provider, CardEventFileProvider):
        raise ValueError("The event stage does not have the configured local file provider.")
    event_config = _configuration(frozen["event_proposals"], "event_proposals")
    event_request = event_service._build_request(
        recording_id,
        {
            "request": {
                "run_id": f"preflight-{uuid4().hex}",
                "configuration": event_config,
            }
        },
    )
    event_request = event_service._freeze_provider_defaults(event_request)
    checkpoint = event_provider.resolve_checkpoint_path(event_request.configuration)
    if checkpoint is None or not checkpoint.is_file():
        raise ValueError("The configured CardEventNet checkpoint is not available.")
    event_config = dict(event_request.configuration)
    with checkpoint.open("rb") as checkpoint_file:
        event_config["checkpoint_sha256"] = hashlib.file_digest(
            checkpoint_file, "sha256"
        ).hexdigest()
    frozen["event_proposals"]["configuration"] = event_config
    providers["event_proposals"] = {
        "name": "cardeventnet",
        "version": event_request.implementation.version,
        "checkpoint_sha256": event_config["checkpoint_sha256"],
    }

    visible_config = _configuration(
        frozen["visible_card_and_pile_proposals"], "visible_card_and_pile_proposals"
    )
    visible_name = visible_config.get("provider")
    if not isinstance(visible_name, str) or not visible_name.startswith("local"):
        raise ValueError("Select an explicit local visible-card provider.")
    visible_provider = visible_card_service._provider_for_selection(visible_name)
    if visible_provider is None:
        raise ValueError(f"The local visible-card provider is not available: {visible_name}.")
    visible_base = getattr(visible_provider, "provider", visible_provider)
    visible_facts = _provider_facts(visible_base)
    visible_config.update(visible_facts)
    frozen["visible_card_and_pile_proposals"]["configuration"] = visible_config
    providers["visible_card_and_pile_proposals"] = visible_facts

    scene_config = _configuration(
        frozen["card_scene_and_calibration"], "card_scene_and_calibration"
    )
    frozen["card_scene_and_calibration"]["configuration"] = scene_config
    providers["card_scene_and_calibration"] = {
        "name": "automatic-card-scene",
        "version": "configured-backend",
    }

    identity_config = _configuration(
        frozen["visual_identity_proposals"], "visual_identity_proposals"
    )
    identity_name = identity_config.get("provider")
    if not isinstance(identity_name, str) or not identity_name.startswith("local"):
        raise ValueError("Select an explicit local visual-identity provider.")
    identity_classifier = visual_identity_service._classifier_for_selection(identity_name)
    if identity_classifier is None:
        raise ValueError(f"The local visual-identity provider is not available: {identity_name}.")
    classifier = getattr(identity_classifier, "classifier", identity_classifier)
    identity_facts = {
        "provider": str(getattr(identity_classifier, "name", identity_name)),
        "version": str(getattr(identity_classifier, "version", "unknown")),
        "crop_policy": "predicted_visible_region",
    }
    identity_config.update(identity_facts)
    frozen["visual_identity_proposals"]["configuration"] = identity_config
    frozen["visual_identity_proposals"]["crop_policy"] = {
        "policy_id": "predicted_visible_region",
        "output_encoding": "ppm",
    }
    identity_bundle = getattr(classifier, "bundle_identity", None)
    providers["visual_identity_proposals"] = {
        **identity_facts,
        "model": str(getattr(classifier, "model", identity_facts["provider"])),
        "bundle_identity": dict(identity_bundle) if isinstance(identity_bundle, Mapping) else None,
    }

    observation_config = _configuration(frozen["table_observations"], "table_observations")
    frozen["table_observations"]["configuration"] = observation_config
    providers["table_observations"] = {
        "name": "observation-assembly",
        "version": "configured-backend",
    }
    return {"stage_requests": frozen, "providers": providers}


def _configuration(stage_request: dict[str, Any], stage_name: str) -> dict[str, Any]:
    value = stage_request.get("configuration")
    if not isinstance(value, Mapping):
        raise ValueError(f"Provide configuration for {stage_name}.")
    return dict(value)


def _provider_facts(provider: Any) -> dict[str, Any]:
    facts = {
        "provider": str(getattr(provider, "name", "unknown")),
        "version": str(getattr(provider, "version", "unknown")),
    }
    bundle_identity = getattr(provider, "bundle_identity", None)
    if isinstance(bundle_identity, Mapping):
        facts["bundle_identity"] = dict(bundle_identity)
    return facts


__all__ = ["validate_local_stage_providers"]
