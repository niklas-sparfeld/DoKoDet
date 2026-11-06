"""Verify the staged 0100 M5 replacement revisions in an isolated store.

This command is limited to the frozen 0100 M5 inventory. It does not run models.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Any

from doko_operations.derived_view import DerivedViewCache, ExactEventRequest, frame_cache_key
from doko_operations.pipeline_data import (
    DataRevision,
    HumanProducer,
    ImportProducer,
    PipelineSelection,
    ProcessorProducer,
    RecordingVideoSource,
    RunProgress,
    canonical_json_bytes,
    canonical_pipeline_selection_bytes,
    parse_pipeline_selection_bytes,
)
from table_evidence_analyzer.card_scene_contract import CardSceneDraft
from table_evidence_analyzer.pipeline_data import (
    ProposedCardSceneData,
    ProposedCardSceneFrame,
    VisibleCardData,
)

from dokodetector_backend.filesystem import atomic_replace_json
from dokodetector_backend.pipeline_reference_store import PipelineReferenceStore
from dokodetector_backend.pipeline_store import (
    PipelineRevisionStore,
    ProcessorRunStore,
    _process_lock,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_draft_decisions(before: dict[str, Any], after: dict[str, Any]) -> None:
    """Check the copied draft retains its decisions and observed card data."""
    if (
        before["recording_id"] != after["recording_id"]
        or before["content_type"] != after["content_type"]
    ):
        raise ValueError("the draft identity changed")
    if after["revision"] != before["revision"] + 1:
        raise ValueError("the copied draft must advance its revision")
    old_coverage, new_coverage = before["coverage"], after["coverage"]
    if isinstance(old_coverage, dict) and isinstance(new_coverage, dict):
        old_coverage = {k: v for k, v in old_coverage.items() if k != "proposal_revision_id"}
        new_coverage = {k: v for k, v in new_coverage.items() if k != "proposal_revision_id"}
    if old_coverage != new_coverage or before["impact"] != after["impact"]:
        raise ValueError("the draft coverage or impact changed")
    if len(before["items"]) != len(after["items"]):
        raise ValueError("the draft item count changed")
    for original, copied in zip(before["items"], after["items"], strict=True):
        for key in ("item_id", "base_item_id", "review_state"):
            if original[key] != copied[key]:
                raise ValueError(f"the draft item {key} changed")
        old_item, new_item = original["item"], copied["item"]
        if old_item.keys() != new_item.keys():
            raise ValueError("the draft item fields changed")
        for key in old_item:
            if (
                key not in {"card_scene", "crop_input_provenance", "annotation_provenance"}
                and old_item[key] != new_item[key]
            ):
                raise ValueError(f"the draft item {key} changed")
        for key, lineage_fields in (
            (
                "crop_input_provenance",
                {
                    "manifest_digest",
                    "source_revision_id",
                    "source_revision_digest",
                    "source_view_digest",
                },
            ),
            ("annotation_provenance", {"visible_card_revision_id", "visible_card_revision_digest"}),
        ):
            old_provenance, new_provenance = old_item.get(key), new_item.get(key)
            if old_provenance is None or new_provenance is None:
                if old_provenance != new_provenance:
                    raise ValueError(f"the draft item {key} changed")
            elif old_provenance.keys() != new_provenance.keys() or any(
                old_provenance[field] != new_provenance[field]
                for field in old_provenance
                if field not in lineage_fields
            ):
                raise ValueError(f"the draft item {key} changed")
        old_scene, new_scene = old_item.get("card_scene"), new_item.get("card_scene")
        if isinstance(old_scene, dict) and old_scene.get("schema_version") == "card-scene-draft/v1":
            original_scene = CardSceneDraft.from_mapping(old_scene)
            copied_scene = CardSceneDraft.from_mapping(new_scene)
            for key in (
                "proposal",
                "reviewed",
                "card_states",
                "completion",
                "projection",
                "derived_region_receipt",
            ):
                if getattr(original_scene, key) != getattr(copied_scene, key):
                    raise ValueError(f"the reviewed scene {key} changed")
        elif old_scene != new_scene:
            raise ValueError("the legacy reviewed scene changed")


def verify_draft_lineage(
    before: dict[str, Any],
    after: dict[str, Any],
    revision_mapping: dict[str, str],
    crop_mapping: dict[str, dict[str, Any]],
    content_digests: dict[str, str],
    scene_digests: dict[str, str],
) -> None:
    """Require each changed draft lineage field to name its verified replacement."""
    verify_draft_decisions(before, after)
    for key in ("source_revision_id", "proposal_revision_id"):
        old = before.get(key)
        if after.get(key) != revision_mapping.get(old, old):
            raise ValueError(f"the copied draft has incorrect {key}")
    old_coverage = before["coverage"]
    new_coverage = after["coverage"]
    if isinstance(old_coverage, dict) and "proposal_revision_id" in old_coverage:
        old_revision = old_coverage["proposal_revision_id"]
        if not isinstance(new_coverage, dict) or new_coverage.get(
            "proposal_revision_id"
        ) != revision_mapping.get(old_revision, old_revision):
            raise ValueError("the copied draft has incorrect coverage lineage")
    elif isinstance(new_coverage, dict) and "proposal_revision_id" in new_coverage:
        raise ValueError("the copied draft introduced coverage lineage")
    old_annotation = before.get("annotation_source")
    if old_annotation is not None:
        new_annotation = after.get("annotation_source")
        old_revision = old_annotation["visible_card_revision_id"]
        if new_annotation != {
            "visible_card_revision_id": revision_mapping.get(old_revision, old_revision),
            "visible_card_revision_digest": content_digests.get(
                old_revision, old_annotation["visible_card_revision_digest"]
            ),
        }:
            raise ValueError("the copied draft has incorrect annotation source")
    elif after.get("annotation_source") is not None:
        raise ValueError("the copied draft introduced an annotation source")
    for original, copied in zip(before["items"], after["items"], strict=True):
        old_item, new_item = original["item"], copied["item"]
        old_crop = old_item.get("crop_input_provenance")
        if old_crop is not None:
            new_crop = new_item["crop_input_provenance"]
            expected = crop_mapping.get(old_crop["manifest_digest"])
            if expected is not None and any(
                new_crop[key] != expected[key]
                for key in (
                    "manifest_digest",
                    "source_revision_id",
                    "source_revision_digest",
                    "source_view_digest",
                )
            ):
                raise ValueError("the copied draft has incorrect crop lineage")
            if expected is None and old_crop != new_crop:
                raise ValueError("the copied draft changed unknown crop lineage")
        old_annotation = old_item.get("annotation_provenance")
        if old_annotation is not None:
            new_annotation = new_item["annotation_provenance"]
            old_revision = old_annotation["visible_card_revision_id"]
            if new_annotation["visible_card_revision_id"] != revision_mapping.get(
                old_revision, old_revision
            ) or new_annotation["visible_card_revision_digest"] != content_digests.get(
                old_revision, old_annotation["visible_card_revision_digest"]
            ):
                raise ValueError("the copied draft has incorrect annotation lineage")
        old_scene = old_item.get("card_scene")
        if isinstance(old_scene, dict) and old_scene.get("schema_version") == "card-scene-draft/v1":
            new_scene = new_item["card_scene"]
            old_revision = old_scene.get("proposal_revision_id")
            if new_scene.get("proposal_revision_id") != revision_mapping.get(
                old_revision, old_revision
            ) or new_scene.get("proposal_data_digest") != scene_digests.get(
                old_revision, old_scene.get("proposal_data_digest")
            ):
                raise ValueError("the copied draft has incorrect scene lineage")


def verify_revision_content(
    content_type: str, before: dict[str, Any], after: dict[str, Any]
) -> None:
    """Check the replacement preserves source evidence and review outcomes."""
    if content_type == "card_scene_proposals":
        old_core = {key: value for key, value in before.items() if key != "data_digest"}
        if hashlib.sha256(canonical_json_bytes(old_core)).hexdigest() != before["data_digest"]:
            raise ValueError("the original scene data digest does not match")
        expected = ProposedCardSceneData.create(
            detector_revision_id=before["detector_revision_id"],
            detector_revision_digest=before["detector_revision_digest"],
            calibration_revision_id=before["calibration_revision_id"],
            calibration_digest=before["calibration_digest"],
            calibration=before["calibration"],
            calibration_diagnostics=before["calibration_diagnostics"],
            frames=tuple(ProposedCardSceneFrame.from_mapping(frame) for frame in before["frames"]),
        )
        if expected.to_mapping() != after:
            raise ValueError("the copied scene content differs from the source")
        return
    if content_type == "visible_cards":
        old, new = VisibleCardData.from_mapping(before), VisibleCardData.from_mapping(after)
        if len(old.outcomes) != len(new.outcomes):
            raise ValueError("the copied visible-card frame count changed")
        for original, copied in zip(old.outcomes, new.outcomes, strict=True):
            if replace(original, card_scene=None) != replace(copied, card_scene=None):
                raise ValueError("the copied visible-card evidence changed")
            old_scene, new_scene = original.card_scene, copied.card_scene
            if isinstance(old_scene, CardSceneDraft) and isinstance(new_scene, CardSceneDraft):
                if (
                    old_scene.proposal != new_scene.proposal
                    or old_scene.reviewed != new_scene.reviewed
                    or old_scene.card_states != new_scene.card_states
                    or old_scene.completion != new_scene.completion
                    or old_scene.projection != new_scene.projection
                    or old_scene.derived_region_receipt != new_scene.derived_region_receipt
                ):
                    raise ValueError("the copied scene review changed")
            elif old_scene != new_scene:
                raise ValueError("the copied legacy scene review changed")
        return
    if content_type == "visual_identities":
        old, new = before["outcomes"], after["outcomes"]
        if len(old) != len(new):
            raise ValueError("the copied identity outcome count changed")
        for original, copied in zip(old, new, strict=True):
            if original.keys() != copied.keys():
                raise ValueError("the copied identity outcome fields changed")
            for key in original:
                if key not in {"crop_input_provenance", "annotation_provenance"} and original[
                    key
                ] != copied.get(key):
                    raise ValueError(f"the copied identity {key} changed")
        return
    raise ValueError(f"unsupported repair content type: {content_type}")


def verify_missing_legacy_evidence(repository: Path, stage: Path, row: dict[str, Any]) -> None:
    """Check the recorded exact frame differs from the locally resolved bytes."""
    missing = row.get("missing_evidence")
    if not isinstance(missing, dict) or missing.get("reason") != "exact_frame_digest_mismatch":
        raise ValueError("the legacy identity crop checks are incomplete")
    old = "visual-identities-visual_identities-run-debcf221-570-attempt-1"
    old_dir = repository / "data/operations/pipeline/revisions" / old
    manifest = read_json(old_dir / "manifest.json")
    content = read_json(old_dir / "content.json")
    outcomes = [item for item in content["outcomes"] if item["card_id"] == missing.get("card_id")]
    if len(outcomes) != 1 or outcomes[0]["frame_identity"] != missing.get("expected_frame"):
        raise ValueError("the missing frame does not match the retained identity outcome")
    expected = missing["expected_frame"]
    observed = missing["observed_frame"]
    if (
        expected.keys() != observed.keys()
        or any(expected[key] != observed[key] for key in expected if key != "image_sha256")
        or expected["image_sha256"] == observed["image_sha256"]
    ):
        raise ValueError("the missing frame comparison is invalid")
    source = RecordingVideoSource.from_mapping(manifest["source"])
    request = ExactEventRequest(
        source=source,
        requested_time_us=expected["requested_time_us"],
        output_encoding=expected["output_encoding"],
    )
    key = frame_cache_key(
        request,
        decoder_version=expected["decoder_version"],
        transform_version=expected["transform_version"],
    )
    cache_root = stage / "runtime/pipeline/derived-views"
    if key != missing.get("cache_key") or not cache_root.is_dir():
        raise ValueError("the resolved frame cache is unavailable")
    entry = DerivedViewCache(cache_root).read(key)
    if entry is None or entry.manifest["identity"] != observed:
        raise ValueError("the resolved frame bytes do not match the missing-evidence report")


def verify_sources(
    repository: Path,
    geometry: dict[str, Any],
    identities: dict[str, Any],
    drafts: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    """Reject a changed draft, selection, or retained revision before publication."""
    operations = repository / "data/operations"
    stage = Path(geometry["destination"])
    if any(Path(value["destination"]) != stage for value in (identities, drafts, validation)):
        raise ValueError("the staged reports name different stores")
    if len(geometry["records"]) != 28 or len(identities["records"]) != 25:
        raise ValueError("the staged revision count differs from the frozen repair scope")
    if len(drafts["records"]) != 26 or len(validation["references"]) != 26:
        raise ValueError("the staged reference count differs from the frozen repair scope")
    if len(validation["selections"]) != 18:
        raise ValueError("the staged selection count differs from the frozen repair scope")
    if len(validation["crop_checks"]) != 13:
        raise ValueError("the staged identity crop checks are incomplete")
    legacy = [
        row
        for row in validation["crop_checks"]
        if row["old"] == "visual-identities-visual_identities-run-debcf221-570-attempt-1"
    ]
    if len(legacy) != 1:
        raise ValueError("the legacy identity crop checks are incomplete")
    if legacy[0]["crop_count"] != 226:
        verify_missing_legacy_evidence(repository, stage, legacy[0])
    if any(row["crop_count"] < 1 for row in validation["crop_checks"] if row is not legacy[0]):
        raise ValueError("a staged identity result has no verified crop")
    records = geometry["records"] + identities["records"]
    mapping = {row["old"]: row["new"] for row in records}
    if len({row["old"] for row in records}) != len(records) or len(
        {row["new"] for row in records}
    ) != len(records):
        raise ValueError("the staged revision mapping is not one-to-one")
    inventory = read_json(repository / "docs/reports/0100-M5_Lineage_Inventory.json")
    expected_selections = {row["selection"] for row in inventory["items"]}
    if {row["path"] for row in validation["selections"]} != expected_selections:
        raise ValueError("the staged selections differ from the frozen inventory")
    expected_ids = {row["revision_id"] for row in inventory["items"]} | {
        ancestor
        for row in inventory["items"]
        for ancestor, _schema in row["obsolete_or_missing_ancestors"]
    }
    if not expected_ids <= {row["old"] for row in records}:
        raise ValueError("the staged revision mapping misses a frozen target")
    expected_recordings = {Path(row["selection"]).parent.name for row in inventory["items"]}
    receipt_dir = operations / "frame-review-queues/0096-M4/receipts"
    if receipt_dir.exists():
        for path in receipt_dir.glob("*.json"):
            try:
                saved_review = read_json(path)
            except (OSError, ValueError) as error:
                raise ValueError(f"the saved-review receipt is unreadable: {path}") from error
            if not isinstance(saved_review, dict) or not isinstance(
                saved_review.get("recording_id"), str
            ):
                raise ValueError(f"the saved-review receipt is invalid: {path}")
            if saved_review["recording_id"] in expected_recordings:
                raise ValueError(f"a saved-review receipt needs explicit preservation: {path}")
    expected_drafts = {
        (recording, content_type)
        for recording in expected_recordings
        for content_type in ("visible_cards", "visual_identities")
    }
    if {(row["recording_id"], row["stage"]) for row in drafts["records"]} != expected_drafts:
        raise ValueError("the staged drafts differ from the frozen inventory")
    if {tuple(value) for value in validation["references"]} != expected_drafts:
        raise ValueError("the checked references differ from the frozen inventory")
    expected_crop_runs = {
        row["old"] for row in identities["records"] if row.get("origin") == "processor"
    }
    if {row["old"] for row in validation["crop_checks"]} != expected_crop_runs:
        raise ValueError("the checked identity runs differ from the staged outputs")
    for row in records:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", row["old"]):
            raise ValueError("the staged source revision ID is invalid")
        if not re.fullmatch(r"repair-0100-m5-[0-9a-f]{32}", row["new"]):
            raise ValueError("the staged replacement revision ID is invalid")
    old_stored = operations / "pipeline/revisions"
    obsolete = {
        ancestor
        for row in inventory["items"]
        for ancestor, _schema in row["obsolete_or_missing_ancestors"]
    }
    if len(obsolete) != 13 or any(
        schema != "proposed-card-scene-data/v1"
        for row in inventory["items"]
        for _ancestor, schema in row["obsolete_or_missing_ancestors"]
    ):
        raise ValueError("the obsolete scene ancestry differs from the frozen inventory")
    ancestry: dict[str, bool] = {}
    visiting: set[str] = set()

    def affected(revision_id: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", revision_id):
            raise ValueError("the source ancestry contains an invalid revision ID")
        if revision_id in visiting:
            raise ValueError("the source ancestry contains a cycle")
        if revision_id not in ancestry:
            visiting.add(revision_id)
            manifest = read_json(old_stored / revision_id / "manifest.json")
            parent_results = [affected(parent) for parent in manifest["input_revision_ids"]]
            ancestry[revision_id] = revision_id in obsolete or any(parent_results)
            visiting.remove(revision_id)
        return ancestry[revision_id]

    for row in inventory["items"]:
        affected(row["revision_id"])
    if {revision_id for revision_id, value in ancestry.items() if value} != {
        row["old"] for row in records
    }:
        raise ValueError("the staged revision mapping differs from the affected ancestry")
    for record in records:
        path = old_stored / record["old"]
        manifest = read_json(path / "manifest.json")
        if (
            manifest["revision_id"] != record["old"]
            or digest(path / "content.json") != manifest["content_sha256"]
        ):
            raise ValueError(f"source revision changed: {record['old']}")
        candidate = stage / "pipeline/revisions" / record["new"]
        manifest = read_json(candidate / "manifest.json")
        if (
            manifest["revision_id"] != record["new"]
            or manifest["content_sha256"] != record["content_sha256"]
            or manifest["created_at"] != geometry["repair_at"]
            or digest(candidate / "content.json") != record["content_sha256"]
        ):
            raise ValueError(f"staged revision changed: {record['new']}")
        original_manifest = read_json(path / "manifest.json")
        if record.get("origin", original_manifest["origin"]) != original_manifest["origin"]:
            raise ValueError(f"the staged revision origin changed: {record['old']}")
        if any(
            original_manifest[key] != manifest[key]
            for key in ("recording_id", "source", "content_type", "origin")
        ):
            raise ValueError(f"the replacement revision identity changed: {record['old']}")
        if manifest["input_revision_ids"] != [
            mapping.get(value, value) for value in original_manifest["input_revision_ids"]
        ]:
            raise ValueError(f"the replacement revision input changed: {record['old']}")
        original_producer = original_manifest["producer"]
        copied_producer = manifest["producer"]
        if original_manifest["origin"] == "processor":
            if (
                copied_producer.get("kind") != original_producer.get("kind")
                or copied_producer.get("processor_type") != original_producer.get("processor_type")
                or copied_producer.get("model_id") != original_producer.get("model_id")
                or copied_producer.get("implementation_id") != "lineage-repair-copy.0100-m5-v1"
            ):
                raise ValueError(f"the replacement processor facts changed: {record['old']}")
        elif (
            copied_producer.get("kind") != original_producer.get("kind")
            or copied_producer.get("operator_id") != original_producer.get("operator_id")
            or copied_producer.get("review_id") != original_producer.get("review_id")
            or copied_producer.get("base_revision_id")
            != mapping.get(
                original_producer.get("base_revision_id"), original_producer.get("base_revision_id")
            )
        ):
            raise ValueError(f"the replacement reviewer facts changed: {record['old']}")
        expected_coverage = dict(original_manifest["coverage"])
        if original_manifest["content_type"] == "card_scene_proposals":
            expected_coverage["no_card_frame_count"] = 0
        for key in ("proposal_revision_id", "visible_card_revision_id"):
            if key in expected_coverage:
                value = expected_coverage[key]
                expected_coverage[key] = mapping.get(value, value)
        if manifest["coverage"] != expected_coverage:
            raise ValueError(f"the replacement coverage changed: {record['old']}")
        verify_revision_content(
            original_manifest["content_type"],
            read_json(path / "content.json"),
            read_json(candidate / "content.json"),
        )
    for row in drafts["records"]:
        path = operations / "pipeline-references" / row["recording_id"] / row["stage"]
        if (
            digest(path / "state.json") != row["old_state_sha256"]
            or digest(path / "draft.json") != row["old_draft_sha256"]
        ):
            raise ValueError(f"reference changed: {row['recording_id']}/{row['stage']}")
    for row in validation["selections"]:
        selection_path = repository / row["path"]
        if digest(selection_path) != row["old_sha256"]:
            raise ValueError(f"selection changed: {row['path']}")
        old_selection = read_json(selection_path)
        if (
            row["old_revision"] != old_selection["revision"]
            or row["new_revision"] != old_selection["revision"] + 1
            or row["selected_generated_revision_id"]
            != mapping.get(
                old_selection["selected_generated_revision_id"],
                old_selection["selected_generated_revision_id"],
            )
            or row["selected_completed_reference_revision_id"]
            != mapping.get(
                old_selection["selected_completed_reference_revision_id"],
                old_selection["selected_completed_reference_revision_id"],
            )
        ):
            raise ValueError(f"the staged selection changes the selected result: {row['path']}")


def verify_staged_references(
    repository: Path, stage: Path, records: list[dict[str, Any]], drafts: dict[str, Any]
) -> None:
    """Validate each staged draft and its exact replacement lineage."""
    operations = repository / "data/operations"
    revision_mapping = {row["old"]: row["new"] for row in records}
    content_digests: dict[str, str] = {}
    scene_digests: dict[str, str] = {}
    crop_mapping: dict[str, dict[str, Any]] = {}
    for row in records:
        old_manifest = read_json(operations / "pipeline/revisions" / row["old"] / "manifest.json")
        new_dir = stage / "pipeline/revisions" / row["new"]
        new_manifest = read_json(new_dir / "manifest.json")
        content_digests[row["old"]] = new_manifest["content_sha256"]
        if old_manifest["content_type"] == "card_scene_proposals":
            scene_digests[row["old"]] = read_json(new_dir / "content.json")["data_digest"]
            old_run = old_manifest["producer"]["run_id"]
            new_run = new_manifest["producer"]["run_id"]
            old_request = read_json(operations / "pipeline/runs" / old_run / "request.json")
            new_request = read_json(stage / "pipeline/runs" / new_run / "request.json")
            repair = new_request["configuration"].get("lineage_repair", {})
            if (
                repair.get("original_run_id") != old_run
                or repair.get("original_revision_id") != row["old"]
                or repair.get("inference_performed") is not False
                or {k: v for k, v in new_request["configuration"].items() if k != "lineage_repair"}
                != old_request["configuration"]
                or new_request["implementation"]
                != {"name": "lineage-repair-copy", "version": "0100-m5/v1"}
                or any(
                    old_request.get(key) != new_request.get(key)
                    for key in (
                        "source",
                        "model",
                        "processor_type",
                        "input_revision_ids",
                        "extraction_policy",
                        "crop_policy",
                    )
                )
            ):
                raise ValueError(f"the scene copy run has incorrect lineage: {new_run}")
        if (
            old_manifest["content_type"] == "visual_identities"
            and old_manifest["origin"] == "processor"
        ):
            old_run = old_manifest["producer"]["run_id"]
            new_run = new_manifest["producer"]["run_id"]
            old_request = read_json(operations / "pipeline/runs" / old_run / "request.json")
            new_request = read_json(stage / "pipeline/runs" / new_run / "request.json")
            repair = new_request["configuration"].get("lineage_repair", {})
            if (
                repair.get("original_run_id") != old_run
                or repair.get("original_revision_id") != row["old"]
                or repair.get("inference_performed") is not False
                or {k: v for k, v in new_request["configuration"].items() if k != "lineage_repair"}
                != old_request["configuration"]
                or new_request["implementation"]
                != {"name": "lineage-repair-copy", "version": "0100-m5/v1"}
            ):
                raise ValueError(f"the identity copy run has incorrect lineage: {new_run}")
            if new_request["input_revision_ids"] != [
                revision_mapping.get(value, value) for value in old_request["input_revision_ids"]
            ] or any(
                old_request.get(key) != new_request.get(key)
                for key in ("source", "model", "processor_type", "crop_policy", "extraction_policy")
            ):
                raise ValueError(f"the identity copy run changed source or model facts: {new_run}")
            if old_request.get("crop_input") is not None:
                if new_request.get("crop_input") is None:
                    raise ValueError(f"the identity copy lost its crop input: {new_run}")
                if old_request["crop_input"]["items"] != new_request["crop_input"]["items"]:
                    raise ValueError(f"the identity copy changed crop evidence: {new_run}")
                old_digest = old_request["crop_input"]["manifest_digest"]
                crop_mapping[old_digest] = new_request["crop_input"]
            elif new_request.get("crop_input") is not None:
                raise ValueError(f"the identity copy introduced a crop input: {new_run}")
            elif (
                repair.get("crop_input_descriptor_available") is not False
                or repair.get("exact_crop_bytes_verified") is not False
            ):
                raise ValueError(f"the identity copy hides missing crop evidence: {new_run}")
    for row in records:
        old_dir = operations / "pipeline/revisions" / row["old"]
        old_manifest = read_json(old_dir / "manifest.json")
        if old_manifest["content_type"] != "visual_identities":
            continue
        original = read_json(old_dir / "content.json")["outcomes"]
        copied = read_json(stage / "pipeline/revisions" / row["new"] / "content.json")["outcomes"]
        for old_outcome, new_outcome in zip(original, copied, strict=True):
            old_crop = old_outcome.get("crop_input_provenance")
            new_crop = new_outcome.get("crop_input_provenance")
            if old_crop is None:
                expected = None
                if new_crop is not None:
                    raise ValueError("the copied identity introduced unverified crop lineage")
            else:
                expected = crop_mapping.get(old_crop["manifest_digest"])
                if expected is None or new_crop is None:
                    raise ValueError("the copied identity lost crop lineage")
                if (
                    old_crop.keys() != new_crop.keys()
                    or old_crop["schema_version"] != new_crop["schema_version"]
                    or old_crop["input_kind"] != new_crop["input_kind"]
                ):
                    raise ValueError("the copied identity changed crop provenance")
            if new_crop is not None and (
                expected is None
                or any(
                    new_crop[key] != expected[key]
                    for key in (
                        "manifest_digest",
                        "source_revision_id",
                        "source_revision_digest",
                        "source_view_digest",
                    )
                )
            ):
                raise ValueError("the copied identity has incorrect crop lineage")
            old_annotation = old_outcome.get("annotation_provenance")
            new_annotation = new_outcome.get("annotation_provenance")
            if old_annotation is not None:
                old_revision = old_annotation["visible_card_revision_id"]
                if (
                    new_annotation is None
                    or old_annotation.keys() != new_annotation.keys()
                    or any(
                        old_annotation[key] != new_annotation[key]
                        for key in old_annotation
                        if key not in {"visible_card_revision_id", "visible_card_revision_digest"}
                    )
                    or new_annotation["visible_card_revision_id"]
                    != revision_mapping.get(old_revision, old_revision)
                    or new_annotation["visible_card_revision_digest"]
                    != content_digests.get(
                        old_revision, old_annotation["visible_card_revision_digest"]
                    )
                ):
                    raise ValueError("the copied identity has incorrect annotation lineage")
            elif new_annotation is not None:
                raise ValueError("the copied identity introduced annotation lineage")
    for row in drafts["records"]:
        relative = Path("pipeline-references") / row["recording_id"] / row["stage"]
        before = read_json(operations / relative / "draft.json")
        after = read_json(stage / relative / "draft.json")
        old_state = read_json(operations / relative / "state.json")
        new_state = read_json(stage / relative / "state.json")
        verify_draft_lineage(
            before, after, revision_mapping, crop_mapping, content_digests, scene_digests
        )
        if (
            new_state["recording_id"] != old_state["recording_id"]
            or new_state["content_type"] != old_state["content_type"]
            or new_state["draft_revision"] != old_state["draft_revision"] + 1
            or new_state["source_revision_id"] != after["source_revision_id"]
            or new_state["selected_completed_revision_id"]
            != revision_mapping.get(
                old_state["selected_completed_revision_id"],
                old_state["selected_completed_revision_id"],
            )
            or new_state["draft_state"] != old_state["draft_state"]
        ):
            raise ValueError(f"the copied reference state changed: {relative}")


def publish_revisions(operations: Path, stage: Path, records: list[dict[str, Any]]) -> None:
    """Publish the validated copies in dependency order without running a model."""
    source = PipelineRevisionStore(stage)
    target = PipelineRevisionStore(operations)
    source_runs = ProcessorRunStore(stage, revision_store=source)
    target_runs = ProcessorRunStore(operations, revision_store=target)
    cache: dict[str, Any] = {}
    target_cache: dict[str, Any] = {}
    for row in records:
        revision = source.require(row["new"], revision_cache=cache)
        manifest = revision.manifest
        staged_run = None
        if manifest.origin == "processor":
            run_id = manifest.producer.run_id
            staged_run = source_runs.require(run_id, include_items=False)
            if (
                staged_run.request.configuration.get("lineage_repair", {}).get(
                    "inference_performed"
                )
                is not False
            ):
                raise ValueError(f"the copy run does not identify its purpose: {run_id}")
            current, created = target_runs.create(staged_run.request)
            if created:
                target_runs.start(run_id)
            elif current.state.status not in {"running", "complete", "partial"}:
                raise ValueError(f"the copy run cannot be resumed: {run_id}")
        target.publish(
            DataRevision.from_mapping(manifest.to_mapping()),
            revision.content,
            revision_cache=target_cache,
        )
        if (
            staged_run is not None
            and target_runs.require(run_id, revision_cache=target_cache).state.status == "running"
        ):
            state = staged_run.state
            progress = RunProgress(state.progress.completed, state.progress.total)
            if state.status == "complete":
                target_runs.complete(
                    run_id, [manifest.revision_id], progress=progress, metrics=state.metrics
                )
            elif state.status == "partial":
                target_runs.partial(
                    run_id,
                    progress=progress,
                    items=(),
                    output_revision_ids=[manifest.revision_id],
                    metrics=state.metrics,
                )
            else:
                raise ValueError(f"the staged copy run is not terminal: {run_id}")
        print(f"Published verified replacement {manifest.revision_id}", flush=True)


def _write_exact(path: Path, payload: bytes) -> None:
    def validate(actual: bytes) -> None:
        if actual != payload:
            raise ValueError(f"the published bytes differ: {path}")

    atomic_replace_json(path, payload, validate=validate)


def apply_targets(
    repository: Path,
    stage: Path,
    drafts: dict[str, Any],
    validation: dict[str, Any],
    snapshot_path: Path,
    verify: Callable[[], None],
) -> None:
    """Update guarded selections and drafts, and restore them on a write error."""
    operations = repository / "data/operations"
    reference_store = PipelineReferenceStore(operations / "pipeline-references")
    staged_reference_store = PipelineReferenceStore(stage / "pipeline-references")
    selection_revision_store = PipelineRevisionStore(operations)
    selection_runs = ProcessorRunStore(operations, revision_store=selection_revision_store)
    selection_lock = RLock()

    def validate_selection_pointer(
        revision_id: str | None, recording_id: str, content_type: str, role: str
    ) -> None:
        if revision_id is None:
            return
        revision = selection_revision_store.require(revision_id)
        manifest = revision.manifest
        if (
            manifest.recording_id != recording_id
            or manifest.content_type != content_type
            or not isinstance(manifest.source, RecordingVideoSource)
        ):
            raise ValueError(f"{role} selection points to a different recording or content type")
        if role == "generated":
            if manifest.origin != "processor" or not isinstance(
                manifest.producer, (ProcessorProducer, ImportProducer)
            ):
                raise ValueError("generated selection must point to processor output")
            run = selection_runs.get(
                manifest.producer.run_id,
                include_items=False,
                validate_output_revisions=False,
            )
            if (
                run is None
                or run.state.status != "complete"
                or revision_id not in run.state.output_revision_ids
            ):
                raise ValueError("generated selection must point to a complete run output")
        elif manifest.origin not in {"manual", "corrected"} or not isinstance(
            manifest.producer, HumanProducer
        ):
            raise ValueError("completed reference selection must point to human output")

    def validate_selection(raw: bytes, path: Path) -> PipelineSelection:
        selection = parse_pipeline_selection_bytes(raw)
        if canonical_pipeline_selection_bytes(selection) != raw:
            raise ValueError(f"selection is not canonical JSON: {path}")
        if selection.recording_id != path.parent.name or selection.content_type != path.stem:
            raise ValueError(f"selection identity differs from its path: {path}")
        validate_selection_pointer(
            selection.selected_generated_revision_id,
            selection.recording_id,
            selection.content_type,
            "generated",
        )
        validate_selection_pointer(
            selection.selected_completed_reference_revision_id,
            selection.recording_id,
            selection.content_type,
            "completed reference",
        )
        return selection

    references = sorted(drafts["records"], key=lambda row: (row["recording_id"], row["stage"]))
    selections = sorted(validation["selections"], key=lambda row: row["path"])
    original_bytes: dict[Path, bytes] = {}
    with ExitStack() as locks:
        for row in references:
            locks.enter_context(reference_store.locked(row["recording_id"], row["stage"]))
        for row in selections:
            path = repository / row["path"]
            locks.enter_context(_process_lock(path.parent / f".{path.stem}.lock", selection_lock))
        verify()
        for row in references:
            path = operations / "pipeline-references" / row["recording_id"] / row["stage"]
            reference_store.read_locked(row["recording_id"], row["stage"])
            for name, expected in (
                ("state.json", row["old_state_sha256"]),
                ("draft.json", row["old_draft_sha256"]),
            ):
                target = path / name
                raw = target.read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError(f"reference changed: {target}")
                original_bytes[target] = raw
            commands = path / "commands.json"
            if commands.is_file():
                original_bytes[commands] = commands.read_bytes()
        for row in selections:
            path = repository / row["path"]
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["old_sha256"]:
                raise ValueError(f"selection changed: {path}")
            old = validate_selection(raw, path)
            staged_path = stage / Path(row["path"]).relative_to("data/operations")
            staged_raw = staged_path.read_bytes()
            new = validate_selection(staged_raw, staged_path)
            if (
                old.revision != row["old_revision"]
                or new.revision != row["new_revision"]
                or new.revision != old.revision + 1
                or (old.recording_id, old.content_type) != (new.recording_id, new.content_type)
                or new.selected_generated_revision_id != row["selected_generated_revision_id"]
                or new.selected_completed_reference_revision_id
                != row["selected_completed_reference_revision_id"]
            ):
                raise ValueError(f"staged selection changed: {path}")
            original_bytes[path] = raw
        if snapshot_path.exists():
            raise ValueError(f"snapshot already exists: {snapshot_path}")
        with tarfile.open(snapshot_path, "x:gz") as archive:
            for path, payload in sorted(original_bytes.items()):
                info = tarfile.TarInfo(path.relative_to(repository).as_posix())
                info.size = len(payload)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(payload))
        with tarfile.open(snapshot_path, "r:gz") as archive:
            if set(archive.getnames()) != {
                path.relative_to(repository).as_posix() for path in original_bytes
            }:
                raise ValueError("the reference snapshot has an incorrect file list")
            for path, payload in original_bytes.items():
                saved = archive.extractfile(path.relative_to(repository).as_posix())
                if saved is None or saved.read() != payload:
                    raise ValueError(f"the reference snapshot differs: {path}")
        try:
            for row in references:
                staged = staged_reference_store.require(row["recording_id"], row["stage"])
                reference_store.write_locked(staged)
            for row in selections:
                target = repository / row["path"]
                source = stage / Path(row["path"]).relative_to("data/operations")
                _write_exact(target, source.read_bytes())
            for row in references:
                reference_store.read_locked(row["recording_id"], row["stage"])
            for row in selections:
                target = repository / row["path"]
                validate_selection(target.read_bytes(), target)
        except BaseException:
            for path, payload in original_bytes.items():
                if path.name != "commands.json":
                    _write_exact(path, payload)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--identities", type=Path, required=True)
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Publish the verified repair")
    args = parser.parse_args()
    geometry = read_json(args.geometry)
    identities = read_json(args.identities)
    drafts = read_json(args.drafts)
    validation = read_json(args.validation)
    repository = args.repository.resolve()
    stage = Path(geometry["destination"])
    records = geometry["records"] + identities["records"]

    def verify() -> None:
        verify_sources(repository, geometry, identities, drafts, validation)
        verify_staged_references(repository, stage, records, drafts)

    verify()
    if not args.apply:
        print("The staged repair passed its source preflight. No active data was changed.")
        return
    receipt_path = repository / "docs/reports/0100-M5_Repair_Receipt.json"
    snapshot_path = repository / "docs/reports/0100-M5_Original_Reference_Snapshots.tar.gz"
    if receipt_path.exists() or snapshot_path.exists():
        raise ValueError("a repair receipt or snapshot already exists; inspect it before retrying")
    operations = repository / "data/operations"
    target = PipelineRevisionStore(operations)
    runs = ProcessorRunStore(operations, revision_store=target)
    stage_store = PipelineRevisionStore(stage)
    stage_cache: dict[str, Any] = {}
    for row in records:
        if target.revision_path(row["new"]).exists():
            raise ValueError(f"a replacement revision already exists: {row['new']}")
        candidate = stage_store.require(row["new"], revision_cache=stage_cache)
        if (
            candidate.manifest.origin == "processor"
            and runs.run_path(candidate.manifest.producer.run_id).exists()
        ):
            raise ValueError(
                f"a replacement run already exists: {candidate.manifest.producer.run_id}"
            )
    revision_receipts = []
    copy_runs = []
    for row in records:
        old_manifest = operations / "pipeline/revisions" / row["old"] / "manifest.json"
        new_manifest = stage / "pipeline/revisions" / row["new"] / "manifest.json"
        old_facts = read_json(old_manifest)
        new_facts = read_json(new_manifest)
        revision_receipts.append(
            {
                **row,
                "old_manifest_sha256": digest(old_manifest),
                "old_content_sha256": old_facts["content_sha256"],
                "new_manifest_sha256": digest(new_manifest),
            }
        )
        if old_facts["origin"] == "processor":
            copy_runs.append(
                {
                    "old_run_id": old_facts["producer"]["run_id"],
                    "new_run_id": new_facts["producer"]["run_id"],
                    "old_revision_id": row["old"],
                    "new_revision_id": row["new"],
                }
            )
    reference_receipts = []
    for row in drafts["records"]:
        staged = stage / "pipeline-references" / row["recording_id"] / row["stage"]
        reference_receipts.append(
            {
                **row,
                "new_state_sha256": digest(staged / "state.json"),
                "new_draft_sha256": digest(staged / "draft.json"),
            }
        )
    selection_receipts = []
    for row in validation["selections"]:
        original = read_json(repository / row["path"])
        staged = stage / Path(row["path"]).relative_to("data/operations")
        selection_receipts.append(
            {
                **row,
                "old_generated_revision_id": original["selected_generated_revision_id"],
                "old_completed_reference_revision_id": original[
                    "selected_completed_reference_revision_id"
                ],
                "new_sha256": digest(staged),
            }
        )
    receipt = {
        "schema_version": "0100-m5-repair-receipt/v1",
        "status": "prepared",
        "reason": "Replace obsolete scene ancestry without changing review decisions.",
        "inference_performed": False,
        "repair_at": geometry["repair_at"],
        "revisions": revision_receipts,
        "copy_runs": copy_runs,
        "references": reference_receipts,
        "selections": selection_receipts,
        "verification": {
            "copied_card_evidence_and_review_decisions_match": True,
            "reference_service_reads": len(validation["references"]),
            "selection_revision_guards": len(validation["selections"]),
        },
        "crop_checks": validation["crop_checks"],
        "original_reference_snapshot": snapshot_path.relative_to(repository).as_posix(),
    }
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    with receipt_path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        publish_revisions(operations, stage, records)
        apply_targets(repository, stage, drafts, validation, snapshot_path, verify)
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        _write_exact(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
        raise
    receipt["status"] = "applied"
    receipt["snapshot_sha256"] = digest(snapshot_path)
    _write_exact(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    print("The repair was applied. Run the restart and editor checks before closing M5.")


if __name__ == "__main__":
    main()
