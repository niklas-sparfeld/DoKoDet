"""Replaceable detector boundary for visual evidence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vision_detector.contract import VisionDetectionResult, VisionEvidence


@runtime_checkable
class VisionDetector(Protocol):
    """Detector interface that accepts visual evidence only."""

    def detect(self, evidence: VisionEvidence) -> VisionDetectionResult:
        """Return one validated result for the supplied visual evidence."""


__all__ = ["VisionDetector"]
