"""Read-only hash and state-reader audit for declared M3 reference roots."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore

RECOVERY = Path("data/operations-recovery/0108-m10-20261105")
CAMPAIGN_MANIFEST = Path(
    "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_inventory(repository: Path) -> list[dict[str, Any]]:
    base = repository / RECOVERY
    paths = (
        Path("inventory-config.json"),
        Path("inventory-plan.json"),
        Path("inventory-plan-final.json"),
        Path("inventory-plan-accepted-loss.json"),
        Path("migration-stage/migration.json"),
        Path("migration-stage-accepted-loss/migration.json"),
    )
    result = []
    for relative in paths:
        value = read_json(base / relative)
        file_entries = value.get("files", [])
        reference_entries = [
            entry
            for entry in file_entries
            if "pipeline-references/" in entry.get("path", "")
        ]
        result.append(
            {
                "path": (RECOVERY / relative).as_posix(),
                "sha256": sha256_file(base / relative),
                "declared_operations_root": value.get("roots", {}).get("operations"),
                "pipeline_reference_file_entries": len(reference_entries),
                "root_ids": sorted(
                    {
                        entry["root_id"]
                        for entry in reference_entries
                        if entry.get("root_id") is not None
                    }
                ),
            }
        )
    return result


def audit(repository: Path) -> dict[str, Any]:
    campaign_path = repository / CAMPAIGN_MANIFEST
    campaign = read_json(campaign_path)
    active_node_root = repository / "data/operations/pipeline-nodes"
    active_device = (
        active_node_root.stat().st_dev if active_node_root.exists() else None
    )
    roots = {
        "canonical": repository / "data/operations/pipeline-references",
        "migration-source-operations": (
            repository / RECOVERY / "migration-source/operations/pipeline-references"
        ),
        "migration-stage-evidence-operations": (
            repository
            / RECOVERY
            / "migration-stage/evidence/operations/pipeline-references"
        ),
        "accepted-loss-evidence-operations": (
            repository
            / RECOVERY
            / "migration-stage-accepted-loss/evidence/operations/pipeline-references"
        ),
        "recovery-operations-copy": repository
        / RECOVERY
        / "operations/pipeline-references",
    }
    results = []
    for name, root in roots.items():
        root_stat = root.stat() if root.exists() else None
        store = PipelineReferenceStore(root)
        records = []
        for reference in campaign["references"]:
            recording_id = reference["recording_id"]
            reference_root = root / recording_id / "visible_cards"
            state_path = reference_root / "state.json"
            draft_path = reference_root / "draft.json"
            entries = []
            for kind, path in (("state", state_path), ("draft", draft_path)):
                expected = reference[f"reference_{kind}_sha256"]
                observed = sha256_file(path) if path.is_file() else None
                file_stat = path.stat() if path.is_file() else None
                entries.append(
                    {
                        "kind": kind,
                        "expected_sha256": expected,
                        "observed_sha256": observed,
                        "matches": observed == expected,
                        "file_uid": None if file_stat is None else file_stat.st_uid,
                        "file_gid": None if file_stat is None else file_stat.st_gid,
                    }
                )
            state = store.get_state(recording_id, "visible_cards")
            state_match = entries[0]["matches"]
            records.append(
                {
                    "recording_id": recording_id,
                    "expected_revision_id": reference["reference_revision_id"],
                    "files": entries,
                    "state_reader": (
                        None
                        if not state_match
                        else {
                            "read_succeeded": state is not None,
                            "selected_revision_id": (
                                None
                                if state is None
                                else state.selected_completed_revision_id
                            ),
                            "selected_revision_matches": (
                                state is not None
                                and state.selected_completed_revision_id
                                == reference["reference_revision_id"]
                            ),
                            "draft_revision": None
                            if state is None
                            else state.draft_revision,
                            "draft_state": None if state is None else state.draft_state,
                        }
                    ),
                }
            )
        results.append(
            {
                "name": name,
                "path": root.as_posix(),
                "exists": root_stat is not None,
                "uid": None if root_stat is None else root_stat.st_uid,
                "gid": None if root_stat is None else root_stat.st_gid,
                "same_device_as_active_node_store": (
                    None
                    if root_stat is None or active_device is None
                    else root_stat.st_dev == active_device
                ),
                "records": records,
                "matching_state_count": sum(
                    record["files"][0]["matches"] for record in records
                ),
                "matching_draft_count": sum(
                    record["files"][1]["matches"] for record in records
                ),
                "state_reader_success_count": sum(
                    bool(
                        record["state_reader"]
                        and record["state_reader"]["read_succeeded"]
                    )
                    for record in records
                ),
                "selected_revision_match_count": sum(
                    bool(
                        record["state_reader"]
                        and record["state_reader"]["selected_revision_matches"]
                    )
                    for record in records
                ),
            }
        )
    return {
        "campaign_manifest": CAMPAIGN_MANIFEST.as_posix(),
        "campaign_manifest_sha256": sha256_file(campaign_path),
        "reference_count": len(campaign["references"]),
        "recovery_manifests": manifest_inventory(repository),
        "roots": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.repository.expanduser().resolve())
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": output.as_posix(), "root_count": len(result["roots"])}))


if __name__ == "__main__":
    main()
