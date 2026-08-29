from __future__ import annotations

import json
from pathlib import Path

from table_evidence_analyzer.visible_card_batch import (
    VisibleCardBatchConfig,
    run_visible_card_batch,
)


def _evidence_fixture(root: Path) -> Path:
    package_id = "package-001"
    package_root = root / package_id
    frames_root = package_root / "frames"
    frames_root.mkdir(parents=True)
    (frames_root / "frame_00.jpg").write_bytes(b"fixture image bytes")
    (package_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "cardevent-evidence/v2",
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
    (root / "extraction-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "annotation-evidence-extraction/v1",
                "packages": [{"package_id": package_id, "relative_path": package_id}],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_visible_card_batch_is_local_and_resumable(tmp_path: Path) -> None:
    evidence_root = _evidence_fixture(tmp_path / "evidence")
    output_dir = tmp_path / "batch"
    config = VisibleCardBatchConfig(
        evidence_root=evidence_root,
        output_dir=output_dir,
        cache_dir=tmp_path / "cache",
    )

    report = run_visible_card_batch(config)

    assert report["status"] == "completed"
    assert report["package_count"] == 1
    assert report["result_count"] == 1
    assert report["failure_count"] == 0
    assert report["status_counts"] == {"ok": 1, "unavailable": 0}
    result_path = Path(report["results"][0]["result"])
    assert json.loads(result_path.read_text(encoding="utf-8"))["prediction"] == {"cards": []}

    resumed = run_visible_card_batch(
        VisibleCardBatchConfig(
            evidence_root=evidence_root,
            output_dir=output_dir,
            cache_dir=tmp_path / "cache",
            resume=True,
        )
    )

    assert resumed["resumed_result_count"] == 1
    assert resumed["result_count"] == 1
    assert json.loads((output_dir / "batch-state.json").read_text())["status"] == "completed"
