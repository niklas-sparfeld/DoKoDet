"""Durable jobs for calibration previews and counterfactual calculations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from doko_operations.card_plane_calibration_refinement import (
    build_calibration_preview,
    exclude_anchors_in_reviewed_ignore_regions,
)
from doko_operations.card_plane_geometry import TablePlaneCalibration
from doko_operations.counterfactual import (
    canonical_counterfactual_bytes,
    recompute_counterfactual,
    validate_counterfactual_request,
)
from doko_operations.pipeline_data import canonical_json_bytes
from table_evidence_analyzer.card_scene_contract import CalibrationDraft, anchor_fit_contributions

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.job_scheduler import Claims
from dokodetector_backend.job_store import Job, JobManager, JobStorageError
from dokodetector_backend.round_analysis_contract import RoundCounterfactualCreateRequest


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class CalculationJobs:
    """Freeze calculation inputs and publish results through the job manager."""

    def __init__(self, root: Path, calibration: Any, analysis: Any) -> None:
        self.root = root / "calculation-jobs"
        self.calibration = calibration
        self.analysis = analysis

    def _snapshot(self, recording_id: str, body: dict[str, Any]) -> dict[str, Any]:
        proposal_id = body["proposal_revision_id"]
        draft = self.calibration.store.load(recording_id, body["draft_id"])
        proposal, source, data = self.calibration._proposal(recording_id, proposal_id)
        self.calibration._require_current_source(draft, source)
        scenes = self.calibration._frame_scenes(recording_id, data)
        return {
            "proposal_revision_id": proposal_id,
            "proposal_digest": proposal.manifest.content_sha256,
            "draft": draft.to_mapping(),
            "calibration": data.calibration,
            "frame_scenes": list(scenes),
        }

    def normalize(self, request: dict[str, Any]) -> dict[str, Any]:
        if request["type"] == "calibration_preview" and "snapshot" not in request["request"]:
            body, context = request["request"], request["context"]
            if (
                set(context) != {"recording_id"}
                or not isinstance(context["recording_id"], str)
                or set(body) != {"draft_id", "proposal_revision_id"}
                or any(not isinstance(body[key], str) or not body[key] for key in body)
            ):
                raise ValueError("invalid calibration preview request")
            snapshot = self._snapshot(context["recording_id"], body)
            return {
                **request,
                "request": {"snapshot": snapshot, "snapshot_digest": _digest(snapshot)},
            }
        return request

    def validate(self, request: dict[str, Any]) -> None:
        kind = request["type"]
        body = request["request"]
        context = request["context"]
        if kind == "calibration_preview":
            if set(context) != {"recording_id"} or not isinstance(context["recording_id"], str):
                raise ValueError("invalid calibration recording")
            if (
                set(body) != {"snapshot", "snapshot_digest"}
                or _digest(body["snapshot"]) != body["snapshot_digest"]
            ):
                raise ValueError("invalid calibration snapshot")
            snapshot = body["snapshot"]
            draft = CalibrationDraft.from_mapping(snapshot["draft"])
            if draft.recording_id != context["recording_id"]:
                raise ValueError("calibration draft recording does not match")
            TablePlaneCalibration.from_mapping(snapshot["calibration"])
        elif kind == "counterfactual":
            if set(context) != {"analysis_id"}:
                raise ValueError("invalid counterfactual context")
            analysis_id = UUID(context["analysis_id"])
            parsed = RoundCounterfactualCreateRequest.model_validate(body).to_shared()
            if parsed.source_analysis_id != analysis_id:
                raise ValueError("counterfactual source does not match")
            try:
                analysis, verified = self.analysis._load_verified_source(analysis_id)
            except (RuntimeError, OSError) as error:
                raise ValueError("counterfactual source is unavailable or invalid") from error
            if (
                parsed.source_input_sha256 != analysis.input_artifact_sha256
                or parsed.source_result_sha256 != analysis.result_artifact_sha256
            ):
                raise ValueError("counterfactual source hashes do not match")
            validate_counterfactual_request(parsed, verified.input, verified.result)
        else:
            raise ValueError("unknown calculation type")

    def prepare(self, job_id: str, request: dict[str, Any], after_write: Any) -> None:
        self.validate(request)
        path = self.root / job_id / "request.json"
        value = {"job_id": job_id, "request": request}
        if path.exists():
            if json.loads(path.read_text()) != value:
                raise JobStorageError("calculation request conflict")
        else:
            atomic_replace_json(path, value)
            after_write("calculation_request")

    def verify(self, job_id: str, request: dict[str, Any]) -> bool:
        try:
            self.validate(request)
            return json.loads((self.root / job_id / "request.json").read_text()) == {
                "job_id": job_id,
                "request": request,
            }
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def job_fields(self, request: dict[str, Any]) -> dict[str, Any]:
        if request["type"] == "calibration_preview":
            return {
                "label": "Calculate calibration preview",
                "inputs": [
                    {
                        "kind": "calibration_snapshot",
                        "digest": request["request"]["snapshot_digest"],
                    }
                ],
            }
        body = request["request"]
        return {
            "label": "Calculate counterfactual",
            "inputs": [
                {"kind": "analysis_input", "digest": body["source_input_sha256"]},
                {"kind": "analysis_result", "digest": body["source_result_sha256"]},
            ],
        }

    def handle(self, job: Job, _claims: Claims, token: Any, manager: JobManager) -> None:
        token.check()
        manager.report_progress(job.id, phase="Calculate result", completed=None, total=None)
        if job.type == "calibration_preview":
            snapshot = job.request["snapshot"]
            draft = CalibrationDraft.from_mapping(snapshot["draft"])
            scenes = tuple(snapshot["frame_scenes"])
            effective = exclude_anchors_in_reviewed_ignore_regions(draft, scenes)
            preview = build_calibration_preview(
                effective,
                TablePlaneCalibration.from_mapping(snapshot["calibration"]),
                frame_scenes=scenes,
            )
            response = {
                "schema_version": "table-plane-calibration-refinement/v1",
                "recording_id": job.context["recording_id"],
                "proposal_revision_id": snapshot["proposal_revision_id"],
                "draft": effective.to_mapping(),
                "preview": preview.to_mapping(),
                "preview_complete": True,
                "anchor_contributions": [
                    x.to_mapping() for x in anchor_fit_contributions(effective.anchors)
                ],
            }
            result = {
                "kind": "calibration_preview",
                "id": job.id,
                "digest": _digest(response),
                "path": f"/api/jobs/{job.id}/calibration-preview",
            }
            token.check()
            manager.publish(
                job.id,
                [result],
                lambda: atomic_replace_json(self.root / job.id / "result.json", response),
            )
        else:
            parsed = RoundCounterfactualCreateRequest.model_validate(job.request).to_shared()
            analysis_id = UUID(job.context["analysis_id"])
            analysis, verified = self.analysis._load_verified_source(analysis_id)
            if (
                parsed.source_input_sha256 != analysis.input_artifact_sha256
                or parsed.source_result_sha256 != analysis.result_artifact_sha256
            ):
                raise ValueError("counterfactual source hashes changed")
            run = recompute_counterfactual(parsed, verified.input, verified.result)
            token.check()
            result = {
                "kind": "counterfactual",
                "id": str(parsed.counterfactual_id),
                "analysis_id": str(analysis_id),
                "digest": hashlib.sha256(run.result_bytes).hexdigest(),
                "path": (
                    f"/v1/round-analyses/{analysis_id}/counterfactuals/{parsed.counterfactual_id}"
                ),
            }

            def commit() -> None:
                try:
                    self.analysis.artifact_storage.publish_counterfactual(
                        analysis_id,
                        parsed.counterfactual_id,
                        canonical_counterfactual_bytes(parsed),
                        run.input_bytes,
                        run.result_bytes,
                    )
                except FileExistsError:
                    existing = self.analysis.get_counterfactual(
                        analysis_id, parsed.counterfactual_id
                    )
                    if (
                        canonical_counterfactual_bytes(existing.request)
                        != canonical_counterfactual_bytes(parsed)
                        or existing.artifacts.result.sha256 != result["digest"]
                    ):
                        raise ValueError("counterfactual identity conflict") from None

            manager.publish(job.id, [result], commit)

    def verify_publication(self, job: Job, results: list[dict[str, Any]]) -> bool:
        try:
            if len(results) != 1:
                return False
            if job.type == "calibration_preview":
                response = json.loads((self.root / job.id / "result.json").read_text())
                return results[0] == {
                    "kind": "calibration_preview",
                    "id": job.id,
                    "digest": _digest(response),
                    "path": f"/api/jobs/{job.id}/calibration-preview",
                }
            stored = self.analysis.get_counterfactual(
                UUID(job.context["analysis_id"]), UUID(results[0]["id"])
            )
            return (
                results[0]["path"]
                == (
                    f"/v1/round-analyses/{job.context['analysis_id']}/counterfactuals/"
                    f"{job.request['counterfactual_id']}"
                )
                and results[0]["analysis_id"] == job.context["analysis_id"]
                and results[0]["id"] == job.request["counterfactual_id"]
                and results[0]["kind"] == "counterfactual"
                and results[0]["digest"] == stored.artifacts.result.sha256
                and canonical_counterfactual_bytes(stored.request)
                == canonical_counterfactual_bytes(
                    RoundCounterfactualCreateRequest.model_validate(job.request).to_shared()
                )
            )
        except (OSError, ValueError, KeyError, TypeError, LookupError, RuntimeError):
            return False

    def current_preview(self, job: Job) -> dict[str, Any]:
        snapshot = job.request["snapshot"]
        current = self._snapshot(
            job.context["recording_id"],
            {
                "proposal_revision_id": snapshot["proposal_revision_id"],
                "draft_id": snapshot["draft"]["draft_id"],
            },
        )
        if _digest(current) != job.request["snapshot_digest"]:
            raise ValueError("calibration preview is stale")
        if job.state != "succeeded" or not self.verify_publication(job, job.results):
            raise ValueError("calibration preview is not available")
        return json.loads((self.root / job.id / "result.json").read_text())
