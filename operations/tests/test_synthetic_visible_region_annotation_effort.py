from __future__ import annotations

import json
from pathlib import Path

import pytest

from doko_operations.synthetic_visible_region_annotation_effort import (
    SyntheticVisibleRegionAnnotationEffortError,
    build_synthetic_visible_region_m6_report,
    write_synthetic_visible_region_m6_report,
)


def test_m6_publishes_the_no_development_group_gap_and_keeps_the_positive_metrics(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).parents[2]

    report = build_synthetic_visible_region_m6_report(repository)
    assert report["status"] == "complete_with_declared_gap"
    assert report["development_batch"]["source_group_count"] == 0
    assert report["proposal_pilot"]["status"] == "not_run"
    assert report["proposal_pilot"]["timing"]["active_correction_seconds"] is None
    assert report["model_metrics"]["synthetic_minus_control"]["mask_ap_50_95"] == pytest.approx(
        0.016534
    )
    assert report["decision"]["outcome"] == "retain_as_experiment"
    assert report["decision"]["provider_promoted"] is False
    assert report["decision"]["runtime_default_changed"] is False

    output = write_synthetic_visible_region_m6_report(tmp_path / "m6.json", report)
    assert json.loads(output.read_text()) == report


def test_m6_rejects_a_stale_source_manifest(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    source = repository / "data/operations/rfdetr-visible-card-detector-0068-m0-manifest.json"
    changed = json.loads(source.read_text())
    changed["recordings"] = list(changed["recordings"])
    changed["recordings"][0] = dict(changed["recordings"][0], recording_id="changed")
    changed_source = tmp_path / "stale-source.json"
    changed_source.write_text(json.dumps(changed))

    with pytest.raises(SyntheticVisibleRegionAnnotationEffortError, match="digest is stale"):
        build_synthetic_visible_region_m6_report(repository, source_manifest_path=changed_source)
