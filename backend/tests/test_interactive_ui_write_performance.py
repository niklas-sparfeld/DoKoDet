from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_interactive_ui_write_performance import run  # noqa: E402


def test_write_samples_check_durable_effects_in_isolated_storage() -> None:
    result = run()

    assert result["all_pass"]
    assert result["controlled_load"] is None
    assert len(result["samples"]) == 36
    assert {sample["case"] for sample in result["samples"]} >= {
        "submit_first",
        "submit_second",
        "queue_move",
        "cancel_queued_job",
        "retry_cancelled_job",
        "retry_detail_after_write",
        "frame_review_defer",
        "unregistered_ui_video_url",
        "pipeline_node_edit",
        "pipeline_node_copy",
        "pipeline_node_restore",
        "pipeline_item_review",
        "pipeline_coverage_review",
        "pipeline_overall_review",
        "events_selection_clear",
        "observations_selection_clear",
        "visible-cards_selection_clear",
        "visual-identities_selection_clear",
        "calibration_draft_start",
        "calibration_draft_update",
        "calibration_draft_discard",
        "pipeline_run_submit",
    }
    assert [effect["actual"] for effect in result["durable_effects"]] == [
        effect["expected"] for effect in result["durable_effects"]
    ]
