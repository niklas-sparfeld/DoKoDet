from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from doko_operations.card_plane_calibration_refinement import CalibrationRefinementError

from dokodetector_backend.calibration_refinement_service import (
    CalibrationRefinementInputError,
    CalibrationRefinementNotFound,
    CalibrationRefinementService,
)


class _DraftStore:
    def __init__(self, drafts: dict[str, SimpleNamespace]) -> None:
        self.drafts = drafts
        self.reset_ids: list[str] = []

    def load(self, recording_id: str, draft_id: str) -> SimpleNamespace:
        assert recording_id == "recording-1"
        try:
            return self.drafts[draft_id]
        except KeyError as error:
            raise CalibrationRefinementError("calibration draft is missing") from error

    def reset(self, recording_id: str, draft_id: str) -> SimpleNamespace:
        self.reset_ids.append(draft_id)
        return self.load(recording_id, draft_id)


def _service(drafts: dict[str, SimpleNamespace]) -> CalibrationRefinementService:
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service.store = _DraftStore(drafts)
    source = SimpleNamespace(
        manifest=SimpleNamespace(revision_id="detector-new", content_sha256="b" * 64)
    )
    service._proposal = lambda recording_id, proposal_revision_id: (None, source, None)
    service._response = lambda recording_id, proposal_revision_id, draft, data, **kwargs: {
        "draft_id": draft.draft_id
    }
    return service


def _draft(draft_id: str, detector_revision_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        draft_id=draft_id,
        detector_revision_id=detector_revision_id,
        detector_revision_digest="b" * 64,
    )


def test_get_does_not_load_another_proposals_draft() -> None:
    old_id = "calibration-draft-proposal-old"
    service = _service({old_id: _draft(old_id, "detector-old")})
    service._proposal = Mock()

    with pytest.raises(CalibrationRefinementNotFound):
        service.get("recording-1", "proposal-new", None)

    service._proposal.assert_not_called()


def test_get_rejects_an_explicit_stale_draft() -> None:
    old_id = "calibration-draft-proposal-old"
    service = _service({old_id: _draft(old_id, "detector-old")})

    with pytest.raises(CalibrationRefinementInputError, match="different detector revision"):
        service.get("recording-1", "proposal-new", old_id)


def test_get_loads_the_current_proposals_draft() -> None:
    current_id = "calibration-draft-proposal-new"
    service = _service({current_id: _draft(current_id, "detector-new")})

    assert service.get("recording-1", "proposal-new", None) == {"draft_id": current_id}


def test_discard_does_not_reset_a_stale_draft() -> None:
    old_id = "calibration-draft-proposal-old"
    service = _service({old_id: _draft(old_id, "detector-old")})

    with pytest.raises(CalibrationRefinementInputError, match="different detector revision"):
        service.discard("recording-1", "proposal-new", old_id)

    assert service.store.reset_ids == []


def test_pending_response_does_not_calculate_calibration_preview() -> None:
    service = CalibrationRefinementService.__new__(CalibrationRefinementService)
    service._frame_scenes = Mock(side_effect=AssertionError("preview was calculated"))
    draft = SimpleNamespace(
        draft_id="draft-1",
        draft_digest="a" * 64,
        base_calibration_revision_id="calibration-1",
        base_calibration_digest="b" * 64,
        anchors=(),
        to_mapping=lambda: {"draft_id": "draft-1"},
    )

    response = service._response(
        "recording-1",
        "proposal-1",
        draft,
        None,
        include_frame_scenes=False,
    )

    assert response["preview_complete"] is False
    assert response["preview"]["candidate_calibration"] is None
    assert response["preview"]["failure"]["code"] == "preview_not_run"
    service._frame_scenes.assert_not_called()
