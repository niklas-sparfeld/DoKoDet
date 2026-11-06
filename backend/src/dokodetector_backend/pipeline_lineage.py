"""Exact revision and run lineage for the node-store foundation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from dokodetector_backend.filesystem import atomic_write_json, contained_path
from dokodetector_backend.pipeline_node_store import (
    NodeConflict,
    PipelineNodeStore,
    _object,
    _read_json,
)
from dokodetector_backend.pipeline_store import _canonical_timestamp, _process_lock, _safe_id


def _reference(raw: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ValueError("reference must be an object")
    role = _safe_id(raw.get("role"), "role")
    if raw.get("kind") == "revision" and set(raw) == {"kind", "role", "node_id", "revision_id"}:
        return {
            "kind": "revision",
            "role": role,
            "node_id": _safe_id(raw["node_id"], "node_id"),
            "revision_id": _safe_id(raw["revision_id"], "revision_id"),
        }
    if raw.get("kind") == "artifact" and set(raw) == {"kind", "role", "artifact_id", "sha256"}:
        artifact = raw["artifact_id"]
        digest = raw["sha256"]
        if (
            not isinstance(artifact, str)
            or not artifact.strip()
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("artifact needs an exact identity and SHA-256 digest")
        return {"kind": "artifact", "role": role, "artifact_id": artifact, "sha256": digest}
    raise ValueError("invalid lineage reference")


def _key(ref: Mapping[str, str]) -> tuple[str, ...]:
    if ref["kind"] == "revision":
        return ("revision", ref["node_id"], ref["revision_id"])
    return ("artifact", ref["artifact_id"], ref["sha256"])


def _acyclic(edges: list[tuple[tuple[str, ...], tuple[str, ...]]]) -> None:
    successors: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)
    incoming: dict[tuple[str, ...], int] = {}
    for source, target in edges:
        incoming.setdefault(source, 0)
        incoming.setdefault(target, 0)
        if target not in successors[source]:
            successors[source].add(target)
            incoming[target] += 1
    ready = [key for key, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        source = ready.pop()
        visited += 1
        for target in successors[source]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(incoming):
        raise ValueError("lineage graph contains a cycle")


class PipelineLineage:
    """Publish immutable terminal run records and query a deterministic lineage graph."""

    def __init__(self, store: PipelineNodeStore) -> None:
        self.store = store
        self.root = store.root / ".lineage-runs"
        self.requests = store.root / ".lineage-requests"

    def start(
        self,
        run_id: str,
        *,
        inputs: Sequence[Mapping[str, Any]],
        run_kind: str,
        processor: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Freeze typed inputs and execution context before a worker reads them."""
        _safe_id(run_id, "run_id")
        processor_data = _object(processor, "processor")
        if (
            set(processor_data) != {"implementation", "model", "configuration", "policies"}
            or not isinstance(processor_data["implementation"], dict)
            or not processor_data["implementation"]
            or not isinstance(processor_data["configuration"], dict)
            or not isinstance(processor_data["policies"], dict)
            or not (processor_data["model"] is None or isinstance(processor_data["model"], dict))
        ):
            raise ValueError(
                "processor must identify implementation, model, configuration and policies"
            )
        context_data = _object(context, "context")
        if run_kind not in {"processor", "analysis"}:
            raise ValueError("invalid run kind")
        if (
            run_kind == "analysis"
            and not {"round_context", "rules", "search_settings"} <= context_data.keys()
        ):
            raise ValueError("analysis needs exact round context, rules and search settings")
        refs = sorted((_reference(ref) for ref in inputs), key=lambda x: (_key(x), x["role"]))
        if not refs or len({(_key(ref), ref["role"]) for ref in refs}) != len(refs):
            raise ValueError("run references must be nonempty and unique")
        fields = {
            "schema_version": "pipeline-lineage-request/v1",
            "run_id": run_id,
            "inputs": refs,
            "run_kind": run_kind,
            "processor": processor_data,
            "context": context_data,
        }
        path = contained_path(self.requests, f"{run_id}.json")
        with _process_lock(self.store.root / ".transactions.lock", self.store._lock):
            if path.exists():
                previous = _read_json(path)
                if {k: v for k, v in previous.items() if k != "started_at"} != fields:
                    raise NodeConflict("run ID is already bound to a different request")
                return previous
            accepted = _read_json(
                contained_path(self.store.root / ".accepted-uses", f"{run_id}.json")
            )
            if (
                accepted.get("run_id") != run_id
                or accepted.get("schema_version") != "pipeline-accepted-use/v1"
            ):
                raise ValueError("invalid accepted-use record")
            accepted_refs = {(r["node_id"], r["revision_id"]) for r in accepted["inputs"]}
            actual_refs = {
                (r["node_id"], r["revision_id"]) for r in refs if r["kind"] == "revision"
            }
            if accepted_refs != actual_refs:
                raise ValueError("run inputs do not match accepted exact revisions")
            for ref in refs:
                if ref["kind"] == "revision":
                    self.store.read_revision(ref["node_id"], ref["revision_id"])
            request = {**fields, "started_at": _canonical_timestamp(None)}
            atomic_write_json(path, request)
            return request

    def finish(
        self,
        run_id: str,
        *,
        inputs: Sequence[Mapping[str, Any]],
        outputs: Sequence[Mapping[str, Any]],
        status: str,
        run_kind: str,
        result: str | None,
        processor: Mapping[str, Any],
        context: Mapping[str, Any],
        failure: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Commit a terminal run after accepted-use registration and cycle validation."""
        _safe_id(run_id, "run_id")
        if status not in {"succeeded", "partial", "failed", "cancelled"}:
            raise ValueError("invalid run status")
        if status in {"succeeded", "partial"}:
            if status == "succeeded" and (result not in {"empty", "nonempty"} or not outputs):
                raise ValueError("successful runs need outputs and an explicit result")
            if status == "partial" and (
                result not in {None, "empty", "nonempty"} or (result is not None and not outputs)
            ):
                raise ValueError("partial runs need outputs when they claim a result")
            if status == "succeeded" and failure is not None:
                raise ValueError("successful runs cannot include failure details")
        if status in {"failed", "cancelled"} and (
            result is not None or outputs or (status == "failed" and not failure)
        ):
            raise ValueError("failed or cancelled runs cannot claim a result or output")
        processor_data = _object(processor, "processor")
        if (
            set(processor_data) != {"implementation", "model", "configuration", "policies"}
            or not isinstance(processor_data["implementation"], dict)
            or not processor_data["implementation"]
            or not isinstance(processor_data["configuration"], dict)
            or not isinstance(processor_data["policies"], dict)
            or not (processor_data["model"] is None or isinstance(processor_data["model"], dict))
        ):
            raise ValueError(
                "processor must identify implementation, model, configuration and policies"
            )
        context_data = _object(context, "context")
        if run_kind not in {"processor", "analysis"}:
            raise ValueError("invalid run kind")
        if (
            run_kind == "analysis"
            and not {"round_context", "rules", "search_settings"} <= context_data.keys()
        ):
            raise ValueError("analysis needs exact round context, rules and search settings")
        failure_data = None if failure is None else _object(failure, "failure")
        in_refs = sorted((_reference(ref) for ref in inputs), key=lambda x: (_key(x), x["role"]))
        out_refs = sorted((_reference(ref) for ref in outputs), key=lambda x: (_key(x), x["role"]))
        if (
            not in_refs
            or len({(_key(ref), ref["role"]) for ref in in_refs}) != len(in_refs)
            or len({_key(ref) for ref in out_refs}) != len(out_refs)
        ):
            raise ValueError("run references must be nonempty and unique")
        fields = {
            "schema_version": "pipeline-lineage-run/v1",
            "run_id": run_id,
            "inputs": in_refs,
            "outputs": out_refs,
            "status": status,
            "run_kind": run_kind,
            "result": result,
            "processor": processor_data,
            "context": context_data,
            "failure": failure_data,
        }
        path = contained_path(self.root, f"{run_id}.json")
        with _process_lock(self.store.root / ".transactions.lock", self.store._lock):
            if path.exists():
                previous = _read_json(path)
                if {k: v for k, v in previous.items() if k != "finished_at"} != fields:
                    raise NodeConflict("run ID is already bound to different lineage")
                return previous
            request = _read_json(contained_path(self.requests, f"{run_id}.json"))
            if (
                request.get("schema_version") != "pipeline-lineage-request/v1"
                or request.get("run_id") != run_id
                or any(
                    request.get(k) != fields[k]
                    for k in ("inputs", "run_kind", "processor", "context")
                )
            ):
                raise NodeConflict("terminal record does not match the frozen run request")
            accepted = _read_json(
                contained_path(self.store.root / ".accepted-uses", f"{run_id}.json")
            )
            if (
                accepted.get("run_id") != run_id
                or accepted.get("schema_version") != "pipeline-accepted-use/v1"
            ):
                raise ValueError("invalid accepted-use record")
            accepted_refs = {(r["node_id"], r["revision_id"]) for r in accepted["inputs"]}
            actual_refs = {
                (r["node_id"], r["revision_id"]) for r in in_refs if r["kind"] == "revision"
            }
            if accepted_refs != actual_refs:
                raise ValueError("run inputs do not match accepted exact revisions")
            for ref in in_refs + out_refs:
                if ref["kind"] == "revision":
                    self.store.read_revision(ref["node_id"], ref["revision_id"])
            record = {**fields, "finished_at": _canonical_timestamp(None)}
            self._snapshot(extra=record)
            atomic_write_json(path, record)
            return record

    def snapshot(self, recording_id: str | None = None) -> dict[str, Any]:
        """Return exact lineage, optionally limited to one recording."""
        with _process_lock(self.store.root / ".transactions.lock", self.store._lock):
            result = self._snapshot(recording_id=recording_id)
        return result if recording_id is None else self._recording_snapshot(result, recording_id)

    @staticmethod
    def _recording_snapshot(graph: dict[str, Any], recording_id: str) -> dict[str, Any]:
        """Keep the selected recording's nodes and their complete run relationships."""
        node_ids = {
            node["node_id"]
            for node in graph["nodes"]
            if node["source"].get("recording_id") == recording_id
        }
        revision_ids = {
            (revision["node_id"], revision["revision_id"])
            for revision in graph["revisions"]
            if revision["node_id"] in node_ids
        }
        runs = [
            run
            for run in graph["runs"]
            if (
                isinstance(run.get("context"), Mapping)
                and run["context"].get("recording_id") == recording_id
            )
            or any(
                ref.get("kind") == "revision" and ref.get("node_id") in node_ids
                for ref in run.get("inputs", []) + run.get("outputs", [])
            )
        ]
        run_ids = {run["run_id"] for run in runs}
        artifact_keys = {
            (ref["artifact_id"], ref["sha256"])
            for run in runs
            for ref in run.get("inputs", []) + run.get("outputs", [])
            if ref.get("kind") == "artifact"
        }
        keep_keys = {("revision", *revision) for revision in revision_ids}
        keep_keys.update(("run", run_id) for run_id in run_ids)
        keep_keys.update(("artifact", *artifact) for artifact in artifact_keys)
        edges = [
            edge
            for edge in graph["edges"]
            if tuple(edge["from"]) in keep_keys and tuple(edge["to"]) in keep_keys
        ]
        return {
            **graph,
            "nodes": [node for node in graph["nodes"] if node["node_id"] in node_ids],
            "revisions": [
                revision for revision in graph["revisions"] if revision["node_id"] in node_ids
            ],
            "runs": runs,
            "artifacts": [
                artifact
                for artifact in graph["artifacts"]
                if (artifact["artifact_id"], artifact["sha256"]) in artifact_keys
            ],
            "edges": edges,
        }

    def _snapshot(
        self, extra: dict[str, Any] | None = None, *, recording_id: str | None = None
    ) -> dict[str, Any]:
        nodes, revisions, edges = [], [], []
        known: set[tuple[str, ...]] = set()
        for node in self.store.list_nodes():
            if recording_id is not None and node.source.get("recording_id") != recording_id:
                continue
            nodes.append(
                {
                    "node_id": node.node_id,
                    "name": node.name,
                    "content_type": node.content_type,
                    "source": node.source,
                    "head_revision_id": node.head_revision_id,
                }
            )
            for rev in self.store.history(node.node_id):
                key = ("revision", node.node_id, rev.revision_id)
                known.add(key)
                revisions.append(
                    {
                        "node_id": node.node_id,
                        "revision_id": rev.revision_id,
                        "content_sha256": rev.content_sha256,
                        "created_at": rev.created_at,
                    }
                )
                if rev.parent_revision_id is not None:
                    edges.append(
                        {
                            "kind": "revised",
                            "from": ["revision", node.node_id, rev.parent_revision_id],
                            "to": list(key),
                        }
                    )
                elif (copy := rev.metadata.get("copied_from")) is not None:
                    edges.append(
                        {
                            "kind": "copied",
                            "from": ["revision", copy["node_id"], copy["revision_id"]],
                            "to": list(key),
                            "copy": copy,
                        }
                    )
                restored = rev.metadata.get("restored_from")
                previous_metadata = {}
                if rev.parent_revision_id is not None:
                    previous_metadata = self.store.read_revision(
                        node.node_id, rev.parent_revision_id
                    ).metadata
                elif isinstance(rev.metadata.get("copied_from"), dict):
                    source = rev.metadata["copied_from"]
                    previous_metadata = self.store.read_revision(
                        source["node_id"], source["revision_id"]
                    ).metadata
                if restored is not None and restored != previous_metadata.get("restored_from"):
                    edges.append(
                        {
                            "kind": "restored",
                            "from": ["revision", restored["node_id"], restored["revision_id"]],
                            "to": list(key),
                            "restore": restored,
                        }
                    )
        records = (
            [_read_json(p) for p in sorted(self.root.glob("*.json"))] if self.root.exists() else []
        )
        if extra is not None:
            records.append(extra)
        terminal_ids = {record["run_id"] for record in records}
        accepted_root = self.store.root / ".accepted-uses"
        if accepted_root.exists():
            for path in sorted(accepted_root.glob("*.json")):
                accepted = _read_json(path)
                if (
                    accepted.get("schema_version") != "pipeline-accepted-use/v1"
                    or accepted.get("run_id") != path.stem
                ):
                    raise ValueError("invalid accepted-use record")
                if accepted["run_id"] not in terminal_ids:
                    request_path = contained_path(self.requests, f"{accepted['run_id']}.json")
                    request = _read_json(request_path) if request_path.exists() else None
                    if request is not None:
                        if (
                            request.get("schema_version") != "pipeline-lineage-request/v1"
                            or request.get("run_id") != accepted["run_id"]
                        ):
                            raise ValueError("invalid lineage request")
                        refs = request["inputs"]
                        if {
                            (r["node_id"], r["revision_id"])
                            for r in refs
                            if r["kind"] == "revision"
                        } != {(r["node_id"], r["revision_id"]) for r in accepted["inputs"]}:
                            raise ValueError("request does not match accepted use")
                        records.append(
                            {
                                **request,
                                "schema_version": "pipeline-lineage-run/v1",
                                "status": "accepted",
                                "outputs": [],
                                "accepted_at": accepted["accepted_at"],
                                "result": None,
                                "failure": None,
                            }
                        )
                        continue
                    records.append(
                        {
                            "schema_version": "pipeline-lineage-run/v1",
                            "run_id": accepted["run_id"],
                            "status": "accepted",
                            "run_kind": None,
                            "inputs": [
                                {"kind": "revision", "role": "input", **ref}
                                for ref in accepted["inputs"]
                            ],
                            "outputs": [],
                            "accepted_at": accepted["accepted_at"],
                            "result": None,
                            "processor": None,
                            "context": None,
                            "failure": None,
                        }
                    )
        if recording_id is not None:
            selected_nodes = {node["node_id"] for node in nodes}
            records = [
                record
                for record in records
                if (
                    isinstance(record.get("context"), Mapping)
                    and record["context"].get("recording_id") == recording_id
                )
                or any(
                    ref.get("kind") == "revision" and ref.get("node_id") in selected_nodes
                    for ref in record["inputs"] + record["outputs"]
                )
            ]
        records.sort(key=lambda x: x["run_id"])
        producers = set()
        artifacts: dict[tuple[str, ...], dict[str, str]] = {}
        for record in records:
            if record.get("schema_version") != "pipeline-lineage-run/v1":
                raise ValueError("invalid lineage run")
            run_key = ("run", record["run_id"])
            for direction in ("inputs", "outputs"):
                for raw in record[direction]:
                    ref = _reference(raw)
                    ref_key = _key(ref)
                    if ref["kind"] == "revision" and ref_key not in known:
                        if recording_id is None:
                            raise ValueError("lineage references a missing revision")
                        try:
                            self.store.read_revision(ref["node_id"], ref["revision_id"])
                        except (OSError, KeyError, ValueError) as error:
                            raise ValueError("lineage references a missing revision") from error
                        known.add(ref_key)
                    if ref["kind"] == "artifact":
                        artifacts[ref_key] = {
                            "artifact_id": ref["artifact_id"],
                            "sha256": ref["sha256"],
                        }
                    if direction == "outputs":
                        if ref_key in producers:
                            raise ValueError("exact output has multiple producer runs")
                        producers.add(ref_key)
                    edges.append(
                        {
                            "kind": "used" if direction == "inputs" else "produced",
                            "role": ref["role"],
                            "from": list(ref_key if direction == "inputs" else run_key),
                            "to": list(run_key if direction == "inputs" else ref_key),
                        }
                    )
        for edge in edges:
            if (
                edge["kind"] in {"revised", "copied", "restored"}
                and tuple(edge["from"]) not in known
            ):
                ref = edge["from"]
                if recording_id is None:
                    raise ValueError("lineage references a missing revision")
                try:
                    self.store.read_revision(ref[1], ref[2])
                except (OSError, KeyError, ValueError) as error:
                    raise ValueError("lineage references a missing revision") from error
                known.add(tuple(ref))
        _acyclic([(tuple(edge["from"]), tuple(edge["to"])) for edge in edges])
        nodes.sort(key=lambda n: n["node_id"])
        revisions.sort(key=lambda r: (r["node_id"], r["revision_id"]))
        edges.sort(key=lambda e: (e["from"], e["to"], e["kind"], e.get("role", "")))
        return {
            "schema_version": "pipeline-lineage-graph/v1",
            "nodes": nodes,
            "revisions": revisions,
            "runs": records,
            "artifacts": [artifacts[k] for k in sorted(artifacts)],
            "edges": edges,
        }
