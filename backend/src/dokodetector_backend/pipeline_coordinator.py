"""Durable sequential coordination for retained pipeline stages."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx


class StageExecutor(Protocol):
    """Run one retained stage and return its terminal state and revisions."""

    def __call__(
        self,
        *,
        recording_id: str,
        stage: str,
        run_id: str,
        request: Mapping[str, Any],
        input_revision_ids: tuple[str, ...],
    ) -> "StageExecution": ...


@dataclass(frozen=True)
class StageExecution:
    """Terminal result returned by a stage adapter."""

    status: str
    input_revision_ids: tuple[str, ...]
    output_revision_ids: tuple[str, ...] = ()
    failure: Mapping[str, Any] | None = None
    processor_run_id: str | None = None


@dataclass(frozen=True)
class StageDefinition:
    """One stage request and its input revisions in a declared sequence."""

    name: str
    request: Mapping[str, Any]
    input_revision_ids: tuple[str, ...]


class PipelineCoordinatorError(RuntimeError):
    """A coordinator run could not continue safely."""


class PipelineCoordinatorCancelled(PipelineCoordinatorError):
    """The local coordinator was asked to stop waiting and scheduling stages."""


class PipelineCoordinator:
    """Persist a run manifest and execute stages in order.

    The adapter owns each retained processor boundary. This class owns stage ordering,
    exact request and lineage records, terminal-state checks, and safe reuse.
    """

    def __init__(self, root: Path, executor: StageExecutor) -> None:
        self.root = root
        self.executor = executor
        self.on_update = None

    def run(
        self,
        recording_id: str,
        stages: Sequence[StageDefinition],
        *,
        coordinator_id: str,
    ) -> dict[str, Any]:
        if not recording_id or not coordinator_id or not stages:
            raise ValueError("recording_id, coordinator_id, and stages are required")
        path = self.root / f"{coordinator_id}.json"
        document = self._load_or_create(path, recording_id, stages, coordinator_id)
        if document["status"] == "cancelled":
            path.with_suffix(".cancel").unlink(missing_ok=True)
        cancel_path = path.with_suffix(".cancel")
        if hasattr(self.executor, "cancel_path"):
            self.executor.cancel_path = cancel_path
        completed_outputs: dict[str, tuple[str, ...]] = {}
        for index, definition in enumerate(stages):
            row = document["stages"][index]
            if cancel_path.exists():
                document["status"] = "cancelled"
                document["failure"] = {"code": "coordinator_cancelled"}
                self._save(path, document)
                return document
            request_digest = _digest(definition.request)
            input_revision_ids = _resolve_input_references(
                definition.input_revision_ids, completed_outputs
            )
            if row["status"] in {"complete", "skipped"}:
                if (
                    row["request_sha256"] == request_digest
                    and tuple(row["input_revision_ids"]) == input_revision_ids
                    and (row["output_revision_ids"] or row["status"] == "skipped")
                ):
                    if row["output_revision_ids"]:
                        completed_outputs[definition.name] = tuple(row["output_revision_ids"])
                    continue
                row.update(_pending_row(definition, request_digest, input_revision_ids))
                row["run_id"] = _stable_id(
                    coordinator_id, definition.name, request_digest, input_revision_ids
                )
            elif row["status"] in {"running", "accepted"}:
                # The adapter must find and resume the immutable processor request.
                row["status"] = "pending"
            elif row["status"] == "cancelled":
                row["status"] = "pending"

            row.update(
                {
                    "request": dict(definition.request),
                    "request_sha256": request_digest,
                    "input_revision_ids": list(input_revision_ids),
                    "status": "running",
                    "failure": None,
                }
            )
            document["status"] = "running"
            self._save(path, document)
            try:
                execution = self.executor(
                    recording_id=recording_id,
                    stage=definition.name,
                    run_id=row["run_id"],
                    request=definition.request,
                    input_revision_ids=input_revision_ids,
                )
                if execution.status not in {"complete", "partial", "failed", "skipped"}:
                    raise PipelineCoordinatorError(
                        f"Stage {definition.name} returned non-terminal status "
                        f"{execution.status!r}."
                    )
                if execution.input_revision_ids != input_revision_ids:
                    raise PipelineCoordinatorError(
                        f"Stage {definition.name} completed with different input revisions."
                    )
                row["processor_run_id"] = execution.processor_run_id or row["run_id"]
                row["status"] = execution.status
                row["output_revision_ids"] = list(execution.output_revision_ids)
                row["failure"] = execution.failure
                if execution.status in {"partial", "failed"}:
                    document["status"] = "failed"
                    document["failure"] = {
                        "stage": definition.name,
                        "status": execution.status,
                        "details": execution.failure,
                    }
                    self._save(path, document)
                    return document
                if execution.status == "complete" and not execution.output_revision_ids:
                    raise PipelineCoordinatorError(
                        f"Stage {definition.name} completed without output revisions."
                    )
                if execution.output_revision_ids:
                    completed_outputs[definition.name] = execution.output_revision_ids
                document["failure"] = None
                self._save(path, document)
            except PipelineCoordinatorCancelled as error:
                row["status"] = "cancelled"
                row["failure"] = {"code": "coordinator_cancelled", "message": str(error)}
                document["status"] = "cancelled"
                document["failure"] = {"stage": definition.name, **row["failure"]}
                self._save(path, document)
                return document
            except Exception as error:
                row["status"] = "failed"
                row["failure"] = {"code": "coordinator_stage_failed", "message": str(error)}
                document["status"] = "failed"
                document["failure"] = {"stage": definition.name, **row["failure"]}
                self._save(path, document)
                raise

        document["status"] = "complete"
        document["failure"] = None
        self._save(path, document)
        return document

    def read_status(self, coordinator_id: str) -> dict[str, Any]:
        """Read the durable manifest without contacting a stage worker."""
        path = self.root / f"{coordinator_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def request_cancel(self, coordinator_id: str) -> None:
        """Ask a running invocation to stop scheduling and polling stages."""
        status = self.read_status(coordinator_id)
        if status.get("status") != "running":
            raise PipelineCoordinatorError("Only a running coordinator can be cancelled.")
        path = self.root / f"{coordinator_id}.cancel"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("cancel\n", encoding="utf-8")

    def _load_or_create(
        self,
        path: Path,
        recording_id: str,
        stages: Sequence[StageDefinition],
        coordinator_id: str,
    ) -> dict[str, Any]:
        if path.exists():
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("recording_id") != recording_id:
                raise PipelineCoordinatorError("Coordinator ID belongs to another recording.")
            if [row["name"] for row in document["stages"]] != [s.name for s in stages]:
                raise PipelineCoordinatorError("The declared stage order changed for this run.")
            return document
        document = {
            "schema_version": "pipeline-coordinator-run/v1",
            "coordinator_id": coordinator_id,
            "recording_id": recording_id,
            "status": "pending",
            "failure": None,
            "stages": [
                {
                    **_pending_row(stage, _digest(stage.request), stage.input_revision_ids),
                    "name": stage.name,
                    "run_id": _stable_id(
                        coordinator_id,
                        stage.name,
                        _digest(stage.request),
                        stage.input_revision_ids,
                    ),
                    "processor_run_id": None,
                }
                for stage in stages
            ],
        }
        self._save(path, document)
        return document

    def _save(self, path: Path, document: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        if self.on_update is not None:
            self.on_update(dict(document))


class RetainedPipelineStageExecutor:
    """Adapter from coordinator stages to the existing durable processor services."""

    _STAGE_METHODS = {
        "event_proposals": ("event_service", "start_inference"),
        "visible_card_and_pile_proposals": ("visible_card_service", "start_detection"),
        "card_scene_and_calibration": ("proposed_card_scene_service", "start_proposal"),
        "visual_identity_proposals": ("visual_identity_service", "start_classification"),
        "table_observations": ("observation_service", "start_assembly"),
    }

    def __init__(self, composition: Any, *, poll_interval_s: float = 0.25) -> None:
        self.composition = composition
        self.poll_interval_s = poll_interval_s

    def __call__(
        self,
        *,
        recording_id: str,
        stage: str,
        run_id: str,
        request: Mapping[str, Any],
        input_revision_ids: tuple[str, ...],
    ) -> StageExecution:
        if stage == "reconstruction" and request.get("skip") is True:
            return StageExecution(
                status="skipped",
                input_revision_ids=input_revision_ids,
                failure={"reason": request.get("skip_reason", "not configured")},
                processor_run_id=run_id,
            )
        service_name, method_name = self._STAGE_METHODS[stage]
        service = getattr(self.composition, service_name)
        payload = self._request_payload(stage, run_id, request, input_revision_ids)
        existing = self.composition.run_store.get(run_id)
        if existing is not None and existing.state.status in {"queued", "running"}:
            self.composition.run_store.fail(
                run_id,
                {
                    "code": "backend_restarted",
                    "message": "The stage was interrupted by a backend restart.",
                },
            )
            existing = self.composition.run_store.require(run_id)
        if existing is not None and existing.state.status in {"partial", "failed"}:
            run = service.retry(recording_id, run_id)
        else:
            run = getattr(service, method_name)(recording_id, payload)
        while run.state.status in {"queued", "running"}:
            time.sleep(self.poll_interval_s)
            run = self.composition.run_store.require(run_id)
        return StageExecution(
            status=run.state.status,
            input_revision_ids=tuple(run.request.input_revision_ids),
            output_revision_ids=tuple(run.state.output_revision_ids),
            failure=(
                None
                if run.state.terminal_failure is None
                else run.state.terminal_failure.to_mapping()
            ),
            processor_run_id=run.run_id,
        )

    @staticmethod
    def _request_payload(
        stage: str,
        run_id: str,
        request: Mapping[str, Any],
        input_revision_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        values = dict(request)
        values["run_id"] = run_id
        if stage == "event_proposals":
            values.setdefault("input_revision_ids", [])
            return {"request": values}
        if stage == "visible_card_and_pile_proposals":
            if len(input_revision_ids) != 1:
                raise PipelineCoordinatorError("Visible-card detection needs one event revision.")
            values["event_revision_id"] = input_revision_ids[0]
            return {"request": values}
        if stage == "card_scene_and_calibration":
            if len(input_revision_ids) != 1:
                raise PipelineCoordinatorError(
                    "Card-scene proposals need one visible-card revision."
                )
            return {
                "run_id": run_id,
                "visible_card_revision_id": input_revision_ids[0],
                "configuration": values.get("configuration", {}),
            }
        if stage == "visual_identity_proposals":
            if len(input_revision_ids) != 1:
                raise PipelineCoordinatorError(
                    "Identity classification needs one proposed card-scene revision."
                )
            values["card_scene_proposal_revision_id"] = input_revision_ids[0]
            values["crop_input_kind"] = "proposed_virtual_cards"
            return {"request": values}
        if stage == "table_observations":
            if len(input_revision_ids) != 3:
                raise PipelineCoordinatorError(
                    "Observation assembly needs event, visible-card, and identity revisions."
                )
            values["input_revision_ids"] = list(input_revision_ids)
            return {"request": values}
        raise PipelineCoordinatorError(f"Unsupported retained pipeline stage: {stage}")


class HttpPipelineStageExecutor:
    """Execute retained pipeline stages through the local backend HTTP API."""

    _PATHS = {
        "event_proposals": "events",
        "visible_card_and_pile_proposals": "visible-cards",
        "card_scene_and_calibration": "proposed-card-scenes",
        "visual_identity_proposals": "visual-identities",
        "table_observations": "observations",
    }

    def __init__(
        self,
        base_url: str,
        *,
        poll_interval_s: float = 1.0,
        timeout_s: float = 21_600,
    ) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=30)
        self.poll_interval_s = poll_interval_s
        self.deadline = time.monotonic() + timeout_s
        self.cancel_path: Path | None = None

    def __call__(
        self,
        *,
        recording_id: str,
        stage: str,
        run_id: str,
        request: Mapping[str, Any],
        input_revision_ids: tuple[str, ...],
    ) -> StageExecution:
        if stage == "reconstruction" and request.get("skip") is True:
            return StageExecution(
                status="skipped",
                input_revision_ids=input_revision_ids,
                failure={"reason": request.get("skip_reason", "not configured")},
                processor_run_id=run_id,
            )
        recording = quote(recording_id, safe="")
        analysis_id = str(uuid5(NAMESPACE_URL, run_id))
        if stage == "reconstruction":
            required = {"round_id", "session_id", "round_context", "rules_version", "search"}
            missing = required - set(request)
            if missing:
                raise PipelineCoordinatorError(
                    "Reconstruction request is missing explicit game context: "
                    + ", ".join(sorted(missing))
                )
            if len(input_revision_ids) != 1:
                raise PipelineCoordinatorError(
                    "Reconstruction needs one table-observation revision."
                )
            base = "/v1/round-analyses"
            payload = dict(request)
            payload["analysis_id"] = analysis_id
            payload["recording_id"] = recording_id
            payload["table_observation_revision_id"] = input_revision_ids[0]
        else:
            path_name = self._PATHS[stage]
            base = f"/api/recordings/{recording}/pipeline/{path_name}"
            payload = RetainedPipelineStageExecutor._request_payload(
                stage, run_id, request, input_revision_ids
            )
        started = self.client.post(base, json=payload)
        started.raise_for_status()
        run = started.json()
        expected_run_id = analysis_id if stage == "reconstruction" else run_id
        if stage != "reconstruction" and run.get("run_id") != expected_run_id:
            raise PipelineCoordinatorError(f"Backend changed the run ID for {stage}.")
        while (
            run.get("state") in {"queued", "analyzing_evidence", "reconstructing"}
            if stage == "reconstruction"
            else run.get("status") in {"queued", "running"}
        ):
            if self.cancel_path is not None and self.cancel_path.exists():
                raise PipelineCoordinatorCancelled("Cancellation requested.")
            if time.monotonic() >= self.deadline:
                raise PipelineCoordinatorError(f"Timed out while waiting for {stage}.")
            time.sleep(self.poll_interval_s)
            status = self.client.get(f"{base}/{quote(expected_run_id, safe='')}")
            status.raise_for_status()
            run = status.json()
        terminal_status = run.get("state") if stage == "reconstruction" else run.get("status")
        if terminal_status not in {"complete", "partial", "failed"}:
            raise PipelineCoordinatorError(
                f"Backend returned non-terminal status for {stage}: {terminal_status!r}."
            )
        result: Mapping[str, Any] = run
        if stage == "reconstruction" and terminal_status == "complete":
            result = {"revisions": [], "request": {"input_revision_ids": input_revision_ids}}
        elif terminal_status == "complete":
            response = self.client.get(f"{base}/{quote(run_id, safe='')}/result")
            response.raise_for_status()
            result = response.json()
        revision_ids = tuple(
            revision.get("manifest", {}).get("revision_id")
            for revision in result.get("revisions", [])
            if isinstance(revision, Mapping)
            and isinstance(revision.get("manifest"), Mapping)
            and isinstance(revision["manifest"].get("revision_id"), str)
        )
        actual_inputs = tuple(result.get("request", {}).get("input_revision_ids", ()))
        output_revision_ids = revision_ids
        if stage == "reconstruction" and terminal_status == "complete":
            output_revision_ids = (expected_run_id,)
        return StageExecution(
            status=str(terminal_status),
            input_revision_ids=(input_revision_ids if stage == "reconstruction" else actual_inputs),
            output_revision_ids=output_revision_ids,
            failure=(
                {"message": run.get("error")}
                if stage == "reconstruction" and run.get("error")
                else run.get("state", {}).get("failure")
            ),
            processor_run_id=expected_run_id,
        )


def frozen_pilot_stage_plan(
    requests: Mapping[str, Mapping[str, Any]],
) -> tuple[StageDefinition, ...]:
    """Build the five retained processor stages in the M0 pilot order.

    Request settings come from the frozen pilot contract. Revision inputs use stage
    references so the coordinator always forwards the actual outputs from this run.
    Reconstruction is explicit. Use a skip object for staged sequences without game
    context; real rounds need their frozen session and round context.
    """

    sequence = (
        ("event_proposals", ()),
        ("visible_card_and_pile_proposals", ("@stage:event_proposals",)),
        ("card_scene_and_calibration", ("@stage:visible_card_and_pile_proposals",)),
        ("visual_identity_proposals", ("@stage:card_scene_and_calibration",)),
        (
            "table_observations",
            (
                "@stage:event_proposals",
                "@stage:visible_card_and_pile_proposals",
                "@stage:visual_identity_proposals",
            ),
        ),
    )
    missing = [name for name, _ in sequence if name not in requests]
    if "reconstruction" not in requests:
        missing.append("reconstruction (explicit context or skip required)")
    if missing:
        raise ValueError("Missing frozen request settings for: " + ", ".join(missing))
    plan = tuple(StageDefinition(name, requests[name], inputs) for name, inputs in sequence)
    plan += (
        StageDefinition(
            "reconstruction",
            requests["reconstruction"],
            ("@stage:table_observations",),
        ),
    )
    return plan


def _pending_row(
    stage: StageDefinition,
    request_digest: str,
    input_revision_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": stage.name,
        "status": "pending",
        "request": dict(stage.request),
        "request_sha256": request_digest,
        "input_revision_ids": list(input_revision_ids or stage.input_revision_ids),
        "output_revision_ids": [],
        "processor_run_id": None,
        "failure": None,
    }


def _resolve_input_references(
    references: Sequence[str], completed_outputs: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    resolved: list[str] = []
    for reference in references:
        if reference.startswith("@stage:"):
            stage_name = reference.removeprefix("@stage:")
            outputs = completed_outputs.get(stage_name)
            if not outputs:
                raise PipelineCoordinatorError(
                    f"Stage input refers to missing output from {stage_name}."
                )
            resolved.extend(outputs)
        else:
            resolved.append(reference)
    return tuple(resolved)


def _stable_id(
    coordinator_id: str,
    stage_name: str,
    request_digest: str = "",
    input_revision_ids: Sequence[str] = (),
) -> str:
    lineage = json.dumps(list(input_revision_ids), separators=(",", ":"))
    suffix = hashlib.sha256(
        f"{coordinator_id}:{stage_name}:{request_digest}:{lineage}".encode()
    ).hexdigest()[:20]
    return f"coord-{suffix}"


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PipelineCoordinator",
    "PipelineCoordinatorCancelled",
    "PipelineCoordinatorError",
    "HttpPipelineStageExecutor",
    "RetainedPipelineStageExecutor",
    "StageDefinition",
    "StageExecution",
    "StageExecutor",
    "frozen_pilot_stage_plan",
]
