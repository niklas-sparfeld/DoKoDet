from __future__ import annotations

from types import SimpleNamespace

from dokodetector_backend.visual_identity_approval import VisualIdentityApprovalPlanner


def test_auto_approval_reason_requires_matching_classified_outcomes() -> None:
    classified = SimpleNamespace(
        status="classified", candidates=(SimpleNamespace(identity="CLUBS_NINE"),)
    )

    assert (
        VisualIdentityApprovalPlanner.auto_approval_reason(
            "pending", classified, ("local-result", classified)
        )
        == "eligible"
    )
    assert (
        VisualIdentityApprovalPlanner.auto_approval_reason(
            "accepted", classified, ("local-result", classified)
        )
        == "already_reviewed"
    )
    assert VisualIdentityApprovalPlanner.auto_approval_reason("pending", classified, None) == (
        "local_unavailable"
    )
