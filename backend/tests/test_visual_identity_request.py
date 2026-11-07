from __future__ import annotations

from types import SimpleNamespace

from dokodetector_backend.visual_identity_request import VisualIdentityRequestBuilder


def test_duplicate_source_card_ids_get_stable_frame_scoped_identity_ids() -> None:
    items = (
        SimpleNamespace(
            card_id="manual-card-1",
            frame_identity=SimpleNamespace(frame_index=2671),
        ),
        SimpleNamespace(
            card_id="manual-card-1",
            frame_identity=SimpleNamespace(frame_index=3285),
        ),
        SimpleNamespace(
            card_id="pose-card-1",
            frame_identity=SimpleNamespace(frame_index=3285),
        ),
    )

    item_ids = VisualIdentityRequestBuilder._identity_item_ids(items)

    assert item_ids == VisualIdentityRequestBuilder._identity_item_ids(items)
    assert len(item_ids) == len(set(item_ids))
    assert item_ids[0].startswith("manual-card-1-frame-2671-")
    assert item_ids[1].startswith("manual-card-1-frame-3285-")
    assert item_ids[2] == "pose-card-1"
