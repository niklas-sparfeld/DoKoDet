from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from table_evidence_analyzer.visible_card_dataset import (
    VisibleCardDatasetConfig,
    VisibleCardDatasetError,
    load_visible_card_dataset_manifest,
    load_visible_card_recipe,
    materialize_visible_card_dataset,
)
from table_evidence_analyzer.visible_cards import (
    NormalizedBox,
    NormalizedPoint,
    ProviderResult,
    VisibleCardProposal,
    VisibleCardRequest,
    write_run_artifact,
)


def _write_source_and_results(root: Path, *, malformed: bool = False) -> tuple[Path, Path]:
    evidence_root = root / "evidence"
    results_root = root / "results"
    evidence_root.mkdir(parents=True)
    results_root.mkdir(parents=True)
    packages: list[dict[str, object]] = []
    proposal = VisibleCardProposal(
        box_2d=NormalizedBox(y_min=100, x_min=200, y_max=500, x_max=700),
        polygon=(
            NormalizedPoint(x=200, y=100),
            NormalizedPoint(x=700, y=100),
            NormalizedPoint(x=700, y=500),
            NormalizedPoint(x=200, y=500),
        ),
        side="face_up",
        label="not an identity target",
    )
    for index in range(25):
        group = "group-a" if index < 12 else "group-b" if index < 20 else "group-c"
        package_id = f"package-{index:02d}"
        package_root = evidence_root / package_id
        frames_root = package_root / "frames"
        frames_root.mkdir(parents=True)
        image = f"frame bytes {package_id}".encode()
        frame_path = frames_root / "frame_00.jpg"
        frame_path.write_bytes(image)
        frame_digest = hashlib.sha256(image).hexdigest()
        (package_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "cardevent-evidence/v2",
                    "event": {
                        "event_time_ms": 1000 + index,
                        "evidence_complete": True,
                    },
                    "session": {"session_id": f"session-{group}"},
                    "frames": [
                        {
                            "part_name": "frame_00",
                            "target_offset_ms": 0,
                            "actual_offset_ms": 0,
                            "width": 1000,
                            "height": 1000,
                            "sha256": frame_digest,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        request = VisibleCardRequest(
            package_id=package_id,
            frame_part_name="frame_00",
            target_offset_ms=0,
            image_bytes=image,
            width=1000,
            height=1000,
        )
        result = ProviderResult(
            status="ok",
            proposals=() if group == "group-c" else (proposal,),
            raw_response={"provider": "gemini"},
        )
        result_path = results_root / f"{package_id}-frame_00.json"
        write_run_artifact(request, result, result_path)
        packages.append(
            {
                "package_id": package_id,
                "relative_path": package_id,
                "event_type": "card_played",
                "evidence_complete": True,
                "session_id": f"session-{group}",
                "source_lineage_group": group,
                "table_setup": "setup-1",
                "card_deck": "deck-1",
            }
        )
    if malformed:
        bad_id = "package-25"
        package_root = evidence_root / bad_id
        (package_root / "frames").mkdir(parents=True)
        image = b"malformed frame"
        (package_root / "frames" / "frame_00.jpg").write_bytes(image)
        (package_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "cardevent-evidence/v2",
                    "event": {"event_time_ms": 2000, "evidence_complete": True},
                    "session": {"session_id": "session-group-a"},
                    "frames": [
                        {
                            "part_name": "frame_00",
                            "target_offset_ms": 0,
                            "width": 1000,
                            "height": 1000,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        packages.append(
            {
                "package_id": bad_id,
                "relative_path": bad_id,
                "event_type": "card_played",
                "evidence_complete": True,
                "source_lineage_group": "group-a",
            }
        )
        (results_root / f"{bad_id}-frame_00.json").write_text("not json", encoding="utf-8")
    (evidence_root / "extraction-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "annotation-evidence-extraction/v1",
                "event_types": ["card_played"],
                "packages": packages,
            }
        ),
        encoding="utf-8",
    )
    return evidence_root, results_root


def test_materializer_selects_bounded_diverse_slice_and_is_reproducible(tmp_path: Path) -> None:
    evidence_root, results_root = _write_source_and_results(tmp_path / "input")
    first = materialize_visible_card_dataset(
        VisibleCardDatasetConfig(
            evidence_root=evidence_root,
            results_root=results_root,
            output_dir=tmp_path / "output-1",
        )
    )
    second = materialize_visible_card_dataset(
        VisibleCardDatasetConfig(
            evidence_root=evidence_root,
            results_root=results_root,
            output_dir=tmp_path / "output-2",
        )
    )

    assert first["selected_frame_count"] == 21
    assert first["dataset_digest"] == second["dataset_digest"]
    assert (tmp_path / "output-1/dataset-manifest.json").read_bytes() == (
        tmp_path / "output-2/dataset-manifest.json"
    ).read_bytes()
    assert not (tmp_path / "output-1/images").exists()

    manifest = load_visible_card_dataset_manifest(tmp_path / "output-1/dataset-manifest.json")
    recipe = load_visible_card_recipe(tmp_path / "output-1/recipe.json")
    assert manifest["label_state"] == "unreviewed_pseudo_label"
    assert manifest["reference_contract"] == "not_reviewed_reference"
    assert all(frame["review_state"] == "unreviewed" for frame in manifest["frames"])
    assert {frame["source_lineage_group"] for frame in manifest["frames"]} == {
        "group-a",
        "group-b",
        "group-c",
    }
    train = {
        frame["source_lineage_group"] for frame in manifest["frames"] if frame["split"] == "train"
    }
    validation = {
        frame["source_lineage_group"]
        for frame in manifest["frames"]
        if frame["split"] == "validation"
    }
    assert train.isdisjoint(validation)
    assert any(frame["targets"] for frame in manifest["frames"] if frame["split"] == "train")
    assert any(frame["targets"] for frame in manifest["frames"] if frame["split"] == "validation")
    assert recipe["model_variant"] == "RFDETRLarge"
    assert recipe["package"] == {"name": "rfdetr", "version": "1.9.4"}
    assert recipe["input_size"] == [704, 704]
    assert recipe["confidence_threshold"] == 0.5

    coco = json.loads((tmp_path / "output-1/annotations.json").read_text(encoding="utf-8"))
    assert len(coco["images"]) == 21
    assert len(coco["annotations"]) == 20
    assert coco["categories"] == [{"id": 1, "name": "visible_card", "supercategory": "card"}]
    assert coco["annotations"][0]["bbox"] == [200, 100, 500, 400]
    assert coco["annotations"][0]["target_state"] == "unreviewed_pseudo_label"


def test_materializer_records_malformed_result_and_rejects_unusable_slice(tmp_path: Path) -> None:
    evidence_root, results_root = _write_source_and_results(tmp_path / "input", malformed=True)
    manifest = materialize_visible_card_dataset(
        VisibleCardDatasetConfig(
            evidence_root=evidence_root,
            results_root=results_root,
            output_dir=tmp_path / "output",
        )
    )
    payload = json.loads(Path(manifest["dataset_manifest"]).read_text(encoding="utf-8"))
    assert any(item["reason"] == "malformed_gemini_result" for item in payload["excluded"])

    with pytest.raises(VisibleCardDatasetError, match="at least three source-lineage groups"):
        materialize_visible_card_dataset(
            VisibleCardDatasetConfig(
                evidence_root=evidence_root,
                results_root=results_root,
                output_dir=tmp_path / "too-small",
                target_frame_count=20,
                max_frames=20,
            )
        )


def test_materializer_accepts_cached_provider_artifacts(tmp_path: Path) -> None:
    evidence_root, results_root = _write_source_and_results(tmp_path / "input")
    result_path = results_root / "package-00-frame_00.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload.pop("image")
    payload.pop("overlay")
    payload["schema_version"] = "visible-card-cache/v1"
    payload["provider"] = {"name": "gemini", "version": "gemini-visible-cards-v1"}
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    report = materialize_visible_card_dataset(
        VisibleCardDatasetConfig(
            evidence_root=evidence_root,
            results_root=results_root,
            output_dir=tmp_path / "output",
        )
    )

    assert report["selected_frame_count"] == 21
