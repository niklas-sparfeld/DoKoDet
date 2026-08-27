"""Deterministic fixture-backed detector for local pipeline tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from vision_detector.contract import (
    VISION_SCHEMA_VERSION,
    VisionDetectionResult,
    VisionDetectorMetadata,
    VisionDiagnostics,
    VisionEvidence,
    VisionSession,
)

SCRIPTED_DETECTOR_NAME = "scripted"
SCRIPTED_DETECTOR_VERSION = "scripted-v1"
SCRIPTED_DEFAULT_CREATED_AT = datetime(2026, 8, 26, 18, 12, tzinfo=timezone.utc)
SCRIPTED_DEFAULT_SESSION_ID = UUID("00000000-0000-0000-0000-000000000000")


class ScriptedDetectorConfigurationError(ValueError):
    """The checked-in scripted detector mapping is invalid."""


class ScriptedVisionDetector:
    """Return deterministic result templates selected by package ID.

    Package-ID selection is intentional test control behavior. This class must not be used as a
    visual recognition implementation.
    """

    def __init__(
        self,
        mapping_path: Path | str | None = None,
        *,
        version: str = SCRIPTED_DETECTOR_VERSION,
    ) -> None:
        detector_metadata = VisionDetectorMetadata(
            name=SCRIPTED_DETECTOR_NAME,
            version=version,
        )
        self.version = detector_metadata.version
        self.name = detector_metadata.name
        self.mapping_path = (
            Path(mapping_path) if mapping_path is not None else default_mapping_path()
        )
        self._templates = _load_templates(self.mapping_path)

    def detect(self, evidence: VisionEvidence) -> VisionDetectionResult:
        """Return the mapped result or a deterministic abstention for an unknown package."""

        if not isinstance(evidence, VisionEvidence):
            raise TypeError("scripted detector input must be VisionEvidence.")

        template = self._templates.get(evidence.package_id)
        if template is None:
            return self._fallback_result(evidence)

        result_id = template.result_id
        if template.detector.version != self.version:
            result_id = uuid5(
                NAMESPACE_URL,
                f"doko-detector/scripted/{self.version}/{evidence.package_id}/{template.result_id}",
            )

        result_payload = template.model_dump(mode="python")
        result_payload.update(
            package_id=evidence.package_id,
            result_id=result_id,
            detector=VisionDetectorMetadata(
                name=SCRIPTED_DETECTOR_NAME,
                version=self.version,
            ),
            diagnostics=VisionDiagnostics(
                frames_received=len(evidence.frames),
                frames_decoded=0,
            ),
        )
        return VisionDetectionResult.model_validate(result_payload)

    def _fallback_result(self, evidence: VisionEvidence) -> VisionDetectionResult:
        result_id = uuid5(
            NAMESPACE_URL,
            f"doko-detector/scripted/{self.version}/{evidence.package_id}",
        )
        return VisionDetectionResult(
            schema_version=VISION_SCHEMA_VERSION,
            result_id=result_id,
            package_id=evidence.package_id,
            session=VisionSession(
                session_id=SCRIPTED_DEFAULT_SESSION_ID,
                event_sequence=1,
            ),
            status="insufficient_evidence",
            selected_card=None,
            candidates=[],
            calibration="fixture",
            detector=VisionDetectorMetadata(
                name=SCRIPTED_DETECTOR_NAME,
                version=self.version,
            ),
            diagnostics=VisionDiagnostics(
                frames_received=len(evidence.frames),
                frames_decoded=0,
            ),
            observations=[],
            created_at=SCRIPTED_DEFAULT_CREATED_AT,
        )


ScriptedDetector = ScriptedVisionDetector


def default_mapping_path() -> Path:
    """Return the checked-in scripted result mapping path."""

    return (
        Path(__file__).resolve().parents[3] / "fixtures" / "vision" / "v1" / "scripted-results.json"
    )


def _load_templates(path: Path) -> dict[UUID, VisionDetectionResult]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ScriptedDetectorConfigurationError(
            f"could not read scripted detector mapping: {path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ScriptedDetectorConfigurationError(
            f"scripted detector mapping is not valid JSON: {path}"
        ) from error

    if not isinstance(payload, dict):
        raise ScriptedDetectorConfigurationError("scripted detector mapping must be a JSON object.")

    templates: dict[UUID, VisionDetectionResult] = {}
    for package_id_text, template_payload in payload.items():
        try:
            package_id = UUID(package_id_text)
        except (AttributeError, TypeError, ValueError) as error:
            raise ScriptedDetectorConfigurationError(
                "scripted detector mapping keys must be UUIDs."
            ) from error
        if not isinstance(template_payload, Mapping):
            raise ScriptedDetectorConfigurationError(
                "scripted detector mapping values must be result objects."
            )
        try:
            template = VisionDetectionResult.model_validate(template_payload)
        except ValidationError as error:
            raise ScriptedDetectorConfigurationError(
                "scripted detector mapping contains an invalid result template."
            ) from error
        if template.package_id != package_id:
            raise ScriptedDetectorConfigurationError(
                "scripted detector mapping key must match the template package_id."
            )
        if template.detector.name != SCRIPTED_DETECTOR_NAME:
            raise ScriptedDetectorConfigurationError(
                "scripted detector templates must use detector name 'scripted'."
            )
        templates[package_id] = template
    return templates


__all__ = [
    "SCRIPTED_DETECTOR_NAME",
    "SCRIPTED_DETECTOR_VERSION",
    "ScriptedDetector",
    "ScriptedDetectorConfigurationError",
    "ScriptedVisionDetector",
    "default_mapping_path",
]
