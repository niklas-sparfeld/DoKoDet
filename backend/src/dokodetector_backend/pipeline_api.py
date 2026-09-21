"""Aggregate router for the recording pipeline HTTP contract."""

from __future__ import annotations

from fastapi import APIRouter

from dokodetector_backend.calibration_refinement_api import router as calibration_refinement_router
from dokodetector_backend.pipeline_comparison_api import router as comparison_router
from dokodetector_backend.pipeline_reference_api import router as reference_router
from dokodetector_backend.pipeline_stage_api import router as stage_router
from dokodetector_backend.pipeline_workspace_api import router as workspace_router

router = APIRouter()
router.include_router(workspace_router)
router.include_router(stage_router)
router.include_router(comparison_router)
router.include_router(calibration_refinement_router)
router.include_router(reference_router)

__all__ = ["router"]
