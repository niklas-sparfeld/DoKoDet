"""Aggregate router for the recording pipeline HTTP contract."""

from __future__ import annotations

from fastapi import APIRouter

from dokodetector_backend.calibration_refinement_api import router as calibration_refinement_router
from dokodetector_backend.pipeline_comparison_api import router as comparison_router
from dokodetector_backend.pipeline_node_edit_api import router as node_edit_router
from dokodetector_backend.pipeline_run_api import router as run_router
from dokodetector_backend.pipeline_stage_api import router as stage_router
from dokodetector_backend.pipeline_workspace_api import router as workspace_router

router = APIRouter()
router.include_router(workspace_router)
router.include_router(node_edit_router)
router.include_router(run_router)
router.include_router(stage_router)
router.include_router(comparison_router)
router.include_router(calibration_refinement_router)

__all__ = ["router"]
