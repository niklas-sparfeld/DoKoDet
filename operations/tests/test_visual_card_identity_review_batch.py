from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from table_evidence_analyzer import (
    CardClassificationResult,
    IdentityCandidate,
    ProviderResult,
    build_request_from_image,
    build_visible_card_review_queue,
    update_frame_review,
)

import doko_operations.visual_card_identity_review_batch as identity_batch
from doko_operations import (
    VisualCardIdentityBatchError,
    VisualCardIdentityBatchRequest,
    VisualCardIdentityBatchStore,
    VisualCardIdentityBatchWriteError,
    VisualCardIdentityClassifierIdentity,
    load_visual_card_identity_review_batch,
)


def _image() -> bytes:
    output = BytesIO()
    Image.new("RGB", (40, 30), (20, 50, 80)).save(output, format="JPEG")
    return output.getvalue()


def _queue(root: Path, *, identity_usable: bool = True) -> tuple[Path, str, bytes]:
    frame_path = root / "frame.jpg"
    frame_bytes = _image()
    frame_path.write_bytes(frame_bytes)
    request = build_request_from_image(
        frame_path,
        package_id="package-fixture",
        frame_part_name="frame_00",
        target_offset_ms=0,
        width=40,
        height=30,
        model="fixture-classifier",
        provider="local",
    )
    prediction = {
        "cards": [
            {
                "box_2d": {"y_min": 100, "x_min": 100, "y_max": 900, "x_max": 900},
                "polygon": [
                    {"x": 100, "y": 100},
                    {"x": 900, "y": 100},
                    {"x": 900, "y": 900},
                    {"x": 100, "y": 900},
                ],
                "side": "face_up",
                "label": "visible_card",
            }
        ]
    }
    artifact = {
        "request_key": request.request_key,
        "request": request.to_mapping(),
        "provider": {"name": "local", "model": "fixture-classifier"},
        **ProviderResult.from_mapping(
            {
                "status": "ok",
                "prediction": prediction,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "latency_ms": 1.0,
                "retry_count": 0,
                "estimated_cost_usd": 0.0,
                "error": None,
                "raw_response": {"fixture": True},
            }
        ).to_mapping(),
    }
    queue_path = root / "visible-card-review.json"
    build_visible_card_review_queue(
        [artifact],
        queue_path,
        run_id="visible-card-batch-fixture",
        lineage_by_item={
            "package-fixture:frame_00": {
                "package_id": "package-fixture",
                "frame_part_name": "frame_00",
                "target_offset_ms": 0,
                "image": str(frame_path),
                "frame_sha256": hashlib.sha256(frame_bytes).hexdigest(),
                "source_asset_id": "source-fixture",
                "source_lineage_group": "group-fixture",
                "source_asset_sha256": "a" * 64,
                "width": 40,
                "height": 30,
            }
        },
    )
    card = {
        "card_id": "card-01",
        "visible_region": {"polygons": [prediction["cards"][0]["polygon"]]},
        "derived_box": prediction["cards"][0]["box_2d"],
        "identity_usability": {
            "usable": identity_usable,
            "reason": "sufficient_identity_evidence"
            if identity_usable
            else "insufficient_identity_evidence",
        },
        "side": "face_up",
        "failure_tags": [],
    }
    update_frame_review(
        queue_path,
        "package-fixture:frame_00",
        {
            "status": "reviewed",
            "decision": "GOOD",
            "empty_frame": False,
            "failure_tags": [],
            "actions": [
                {
                    "card_id": "card-01",
                    "action": "accepted",
                    "proposal_index": 0,
                    "reviewed_card": card,
                }
            ],
            "reviewer": "fixture-operator",
        },
        expected_revision=0,
    )
    return queue_path, hashlib.sha256(queue_path.read_bytes()).hexdigest(), frame_bytes


class _Classifier:
    name = "fixture-identity"
    version = "fixture-identity-v1"
    calibration = "uncalibrated"

    def __init__(self) -> None:
        self.calls = 0

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        assert crop_bytes.startswith(b"P6\n")
        self.calls += 1
        return CardClassificationResult(
            status="ok",
            candidates=(
                IdentityCandidate(card="CLUBS_NINE", probability=0.75),
                IdentityCandidate(card="SPADES_NINE", probability=0.25),
            ),
            latency_ms=2.5,
            raw_response={"fixture": True},
        )


def _request(root: Path, queue_path: Path, queue_digest: str) -> VisualCardIdentityBatchRequest:
    return VisualCardIdentityBatchRequest(
        recording_id="recording-fixture",
        source_asset_id="source-fixture",
        source_sha256="a" * 64,
        source_lineage_group="group-fixture",
        visible_card_review_batch_id="visible-card-batch-fixture",
        visible_card_review_version_id="visible-card-reviewed-fixture",
        visible_card_review_version_digest="b" * 64,
        visible_card_review_queue_path=queue_path,
        visible_card_review_queue_digest=queue_digest,
        classifier=VisualCardIdentityClassifierIdentity(
            name="fixture-identity", version="fixture-identity-v1", calibration="uncalibrated"
        ),
    )


def test_identity_batch_freezes_usable_crop_and_proposal_lineage(tmp_path: Path) -> None:
    queue_path, queue_digest, frame_before = _queue(tmp_path)
    request = _request(tmp_path, queue_path, queue_digest)
    classifier = _Classifier()
    store = VisualCardIdentityBatchStore(tmp_path / "operations")

    prepared = store.prepare(request, classifier)

    assert prepared["status"] == "ready"
    assert prepared["batch_id"] == request.batch_id
    assert prepared["progress"] == {
        "phase": "ready",
        "total_items": 1,
        "crops_materialized": 1,
        "proposals_completed": 1,
        "failed_items": 0,
    }
    assert prepared["coverage"]["identity_usable_card_count"] == 1
    item = prepared["items"][0]
    assert item["visible_card"]["card_id"] == "card-01"
    assert item["crop"]["policy_id"] == "raw_rectangular"
    assert item["proposal"]["candidates"][0]["card"] == "CLUBS_NINE"
    assert item["proposal"]["score"] == 0.75
    assert classifier.calls == 1
    assert queue_path.read_bytes() != b""
    assert frame_before == Path(item["source"]["image"]).read_bytes()

    repeated = store.prepare(request, classifier)
    assert repeated["batch_id"] == prepared["batch_id"]
    assert repeated["items"] == prepared["items"]
    assert classifier.calls == 1


def test_identity_batch_excludes_unusable_cards_and_protected_groups(tmp_path: Path) -> None:
    queue_path, queue_digest, _ = _queue(tmp_path, identity_usable=False)
    request = _request(tmp_path, queue_path, queue_digest)
    blocked = VisualCardIdentityBatchStore(tmp_path / "operations").prepare(request, _Classifier())
    assert blocked["status"] == "blocked"
    assert blocked["failures"][0]["code"] == "no_identity_usable_cards"
    assert blocked["coverage"]["excluded_cards"][0]["reason"] == "insufficient_identity_evidence"

    protected_request = replace(
        request,
        protected_source_lineage_groups=("group-fixture",),
    )
    protected = VisualCardIdentityBatchStore(tmp_path / "protected").prepare(
        protected_request, _Classifier()
    )
    assert protected["status"] == "blocked"
    assert protected["failures"][0]["code"] == "protected_source_group"


def test_identity_proposal_failure_is_reviewable_and_retry_reuses_crop(tmp_path: Path) -> None:
    queue_path, queue_digest, _ = _queue(tmp_path)
    request = _request(tmp_path, queue_path, queue_digest)

    class FlakyClassifier(_Classifier):
        def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
            self.calls += 1
            if self.calls == 1:
                return CardClassificationResult(status="unavailable", error="fixture unavailable")
            return super().classify_ppm(crop_bytes)

    classifier = FlakyClassifier()
    store = VisualCardIdentityBatchStore(tmp_path / "operations")
    first = store.prepare(request, classifier)
    assert first["status"] == "ready"
    assert first["items"][0]["proposal"]["status"] == "unavailable"
    crop_path = Path(first["items"][0]["crop"]["path"])
    crop_digest = first["items"][0]["crop"]["sha256"]

    store.begin_retry(request.batch_id)
    second = store.prepare(request, classifier, resume=True)
    assert second["status"] == "ready"
    assert second["items"][0]["proposal"]["status"] == "ok"
    assert second["items"][0]["crop"]["sha256"] == crop_digest
    assert crop_path.read_bytes()


def test_changed_visible_review_bytes_are_blocked(tmp_path: Path) -> None:
    queue_path, queue_digest, _ = _queue(tmp_path)
    request = _request(tmp_path, queue_path, queue_digest)
    queue_path.write_text(
        queue_path.read_text(encoding="utf-8").replace('"revision": 1', '"revision": 2'),
        encoding="utf-8",
    )

    result = VisualCardIdentityBatchStore(tmp_path / "operations").prepare(request, _Classifier())

    assert result["status"] == "blocked"
    assert result["failures"][0]["code"] == "stale_visible_card_review"


def test_changed_frozen_crop_artifact_is_rejected(tmp_path: Path) -> None:
    queue_path, queue_digest, _ = _queue(tmp_path)
    request = _request(tmp_path, queue_path, queue_digest)
    store = VisualCardIdentityBatchStore(tmp_path / "operations")
    prepared = store.prepare(request, _Classifier())
    crop_path = Path(prepared["items"][0]["crop"]["path"])
    crop_path.write_bytes(crop_path.read_bytes() + b"tampered")

    with pytest.raises(VisualCardIdentityBatchError, match="crop artifact digest changed"):
        load_visual_card_identity_review_batch(store.batch_path(request.batch_id))


def test_identity_crop_write_failure_is_explicit(tmp_path: Path, monkeypatch) -> None:
    queue_path, queue_digest, _ = _queue(tmp_path)
    request = _request(tmp_path, queue_path, queue_digest)

    def fail(_path: Path, _value: bytes) -> None:
        raise VisualCardIdentityBatchWriteError("fixture write failure")

    monkeypatch.setattr(identity_batch, "_immutable_write", fail)
    result = VisualCardIdentityBatchStore(tmp_path / "operations").prepare(request, _Classifier())

    assert result["status"] == "failed"
    assert result["items"][0]["failure"]["code"] == "write_error"
