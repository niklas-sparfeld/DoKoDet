from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from table_evidence_analyzer.visible_card_review_workflow import (
    load_visible_card_review_queue,
    update_frame_review,
)
from table_evidence_analyzer.visible_cards import (
    FakeVisibleCardProvider,
    ProviderResult,
    load_run_artifact,
)

from doko_operations.visible_card_review_batch import (
    ExtractedVisibleCardFrame,
    VisibleCardBatchConflict,
    VisibleCardBatchError,
    VisibleCardBatchRequest,
    VisibleCardDetectorIdentity,
    VisibleCardReviewBatchStore,
    load_visible_card_review_batch,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _image(colour: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (20, 20), colour).save(output, format="JPEG", quality=85)
    return output.getvalue()


def _prediction() -> dict[str, object]:
    return {
        "cards": [
            {
                "box_2d": {"y_min": 100, "x_min": 100, "y_max": 800, "x_max": 800},
                "polygon": [
                    {"x": 100, "y": 100},
                    {"x": 800, "y": 100},
                    {"x": 800, "y": 800},
                    {"x": 100, "y": 800},
                ],
                "side": "unknown",
                "label": "visible_card",
            }
        ]
    }


def _review_version(root: Path, video: Path) -> tuple[Path, str, str]:
    annotation = {
        "schema_version": "cardevent-annotation/v2",
        "video": video.name,
        "events": [
            {"time_s": 0.4, "type": "card_played", "confidence": "confirmed"},
            {"time_s": 1.2, "type": "card_played"},
        ],
    }
    annotation_digest = _digest(annotation)
    version_core = {
        "schema_version": "cardevent-reviewed-annotation/v1",
        "recording_id": "recording-fixture",
        "source_asset_id": "source-fixture",
        "source_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "annotation": annotation,
        "proposal_decisions": {},
        "input_draft_revision": 2,
        "input_draft_digest": "a" * 64,
        "source_digest": hashlib.sha256(video.read_bytes()).hexdigest(),
        "reviewed_annotation_digest": annotation_digest,
        "proposal_decision_digest": _digest({}),
        "reviewer": "operator",
        "completed_at": "2026-09-01T10:00:00Z",
        "parent_version_id": None,
        "parent_digest": None,
    }
    version_id = "cardevent-reviewed-fixture"
    version = {**version_core, "version_id": version_id}
    version_digest = _digest(version)
    version["version_digest"] = version_digest
    path = root / f"{version_id}.json"
    path.write_text(json.dumps(version, indent=2), encoding="utf-8")
    return path, version_digest, annotation_digest


class _FixtureExtractor:
    def __init__(self, frames: dict[float, bytes], *, missing: set[float] | None = None) -> None:
        self.frames = frames
        self.missing = missing or set()
        self.calls: list[float] = []

    def extract(
        self, video_path: Path, *, event_time_s: float, target_offset_ms: int
    ) -> ExtractedVisibleCardFrame | None:
        del video_path
        assert target_offset_ms == 0
        self.calls.append(event_time_s)
        if event_time_s in self.missing:
            return None
        return ExtractedVisibleCardFrame(
            frame_index=round(event_time_s * 10),
            actual_offset_ms=0,
            image_bytes=self.frames[event_time_s],
            width=20,
            height=20,
        )


class _UnavailableProvider:
    name = "local"
    version = "local-visible-cards-v1"

    def propose(self, request: object) -> ProviderResult:
        del request
        return ProviderResult(status="unavailable", error="fixture provider error")


def _request(
    root: Path, *, protected: tuple[str, ...] = ()
) -> tuple[VisibleCardBatchRequest, dict[float, bytes]]:
    video = root / "video.mov"
    video.write_bytes(b"fixture-video-bytes")
    version_path, version_digest, annotation_digest = _review_version(root, video)
    frames = {0.4: _image((30, 40, 50)), 1.2: _image((60, 70, 80))}
    request = VisibleCardBatchRequest(
        recording_id="recording-fixture",
        source_asset_id="source-fixture",
        source_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
        source_lineage_group="session-fixture",
        video_path=video,
        card_event_review_version_path=version_path,
        card_event_review_version_id="cardevent-reviewed-fixture",
        card_event_review_version_digest=version_digest,
        card_event_annotation_digest=annotation_digest,
        detector=VisibleCardDetectorIdentity(
            bundle_id="visible-card-fixture-bundle",
            bundle_digest="b" * 64,
            model="local-rfdetr",
            preprocessing="rfdetr_704_v1",
        ),
        protected_source_lineage_groups=protected,
    )
    return request, frames


def test_batch_preparation_builds_stable_two_item_v2_queue(tmp_path: Path) -> None:
    request, frames = _request(tmp_path)
    provider = FakeVisibleCardProvider(
        {hashlib.sha256(image).hexdigest(): _prediction() for image in frames.values()}
    )
    extractor = _FixtureExtractor(frames)
    source_before = request.video_path.read_bytes()
    review_before = request.card_event_review_version_path.read_bytes()

    first = VisibleCardReviewBatchStore(tmp_path / "operations").prepare(
        request,
        provider,
        frame_extractor=extractor,
    )

    assert first["status"] == "ready"
    assert first["batch_id"] == request.batch_id
    assert first["progress"] == {
        "phase": "ready",
        "total_items": 2,
        "frames_extracted": 2,
        "finder_completed": 2,
        "failed_items": 0,
    }
    queue = load_visible_card_review_queue(first["queue_path"])
    assert [item.item_id for item in queue.items] == [item["item_id"] for item in first["items"]]
    assert [item.source.source_lineage_group for item in queue.items] == [
        "session-fixture",
        "session-fixture",
    ]
    assert [item["event"]["event_time_ms"] for item in first["items"]] == [400, 1200]
    assert [item["frame"]["frame_index"] for item in first["items"]] == [4, 12]
    assert all(
        item["frame"]["sha256"] == hashlib.sha256(frames[item["event"]["event_time_s"]]).hexdigest()
        for item in first["items"]
    )
    assert all(item["finder"]["detector"]["bundle_digest"] == "b" * 64 for item in first["items"])
    assert all(item["finder"]["request"]["provider"] == "local" for item in first["items"])
    assert all(item["finder"]["result"]["status"] == "ok" for item in first["items"])
    assert all(
        load_run_artifact(item["finder"]["result_path"])["status"] == "ok"
        for item in first["items"]
    )
    assert request.video_path.read_bytes() == source_before
    assert request.card_event_review_version_path.read_bytes() == review_before

    calls_before = len(extractor.calls)
    second = VisibleCardReviewBatchStore(tmp_path / "operations").prepare(
        request,
        provider,
        frame_extractor=extractor,
    )
    assert second["batch_id"] == first["batch_id"]
    assert [item["item_id"] for item in second["items"]] == [
        item["item_id"] for item in first["items"]
    ]
    assert len(extractor.calls) == calls_before
    assert (
        load_visible_card_review_batch(
            tmp_path
            / "operations"
            / "visible-card-review-batches"
            / request.batch_id
            / "batch.json"
        )["queue_digest"]
        == first["queue_digest"]
    )


def test_stale_annotation_and_protected_group_are_explicit_blocked_states(tmp_path: Path) -> None:
    request, frames = _request(tmp_path, protected=("session-fixture",))
    provider = FakeVisibleCardProvider()
    result = VisibleCardReviewBatchStore(tmp_path / "operations").prepare(
        request,
        provider,
        frame_extractor=_FixtureExtractor(frames),
    )
    assert result["status"] == "blocked"
    assert result["failures"][0]["code"] == "protected_source_group"
    assert result["queue_path"] is None
    assert result["progress"]["total_items"] == 0

    stale_root = tmp_path / "stale"
    stale_root.mkdir()
    stale_request, stale_frames = _request(stale_root)
    stale_request.card_event_review_version_path.write_text(
        stale_request.card_event_review_version_path.read_text(encoding="utf-8").replace(
            "cardevent-reviewed-fixture", "cardevent-reviewed-tampered"
        ),
        encoding="utf-8",
    )
    stale_result = VisibleCardReviewBatchStore(stale_root / "operations").prepare(
        stale_request,
        provider,
        frame_extractor=_FixtureExtractor(stale_frames),
    )
    assert stale_result["status"] == "blocked"
    assert stale_result["failures"][0]["code"] == "stale_annotation"
    assert stale_result["queue_path"] is None


@pytest.mark.parametrize("failure", ["missing", "provider"])
def test_item_failures_do_not_publish_a_partial_queue(tmp_path: Path, failure: str) -> None:
    request, frames = _request(tmp_path)
    extractor = _FixtureExtractor(frames, missing={0.4} if failure == "missing" else set())
    provider = _UnavailableProvider() if failure == "provider" else FakeVisibleCardProvider()

    result = VisibleCardReviewBatchStore(tmp_path / "operations").prepare(
        request,
        provider,
        frame_extractor=extractor,
    )

    assert result["status"] == "failed"
    assert result["queue_path"] is None
    assert not (
        tmp_path
        / "operations"
        / "visible-card-review-batches"
        / request.batch_id
        / "review-queue.json"
    ).exists()
    codes = {entry["code"] for entry in result["failures"]}
    assert codes == {"missing_frame" if failure == "missing" else "provider_error"}
    if failure == "provider":
        failed_item = next(item for item in result["items"] if item["failure"] is not None)
        assert failed_item["finder"]["result"]["status"] == "unavailable"
        assert load_run_artifact(failed_item["finder"]["result_path"])["status"] == "unavailable"


def test_task_source_and_provider_gates_block_before_extraction(tmp_path: Path) -> None:
    request, frames = _request(tmp_path)
    variants = (
        (replace(request, task_enrollment_selected=False), "task_enrollment_not_selected"),
        (replace(request, source_permission="withdrawn"), "disallowed_source_use"),
        (
            replace(request, detector=replace(request.detector, provider="gemini")),
            "non_local_provider",
        ),
    )

    for variant, code in variants:
        extractor = _FixtureExtractor(frames)
        result = VisibleCardReviewBatchStore(tmp_path / f"operations-{code}").prepare(
            variant,
            _UnavailableProvider(),
            frame_extractor=extractor,
        )
        assert result["status"] == "blocked"
        assert result["failures"][0]["code"] == code
        assert extractor.calls == []


def test_complete_publishes_immutable_queue_and_revision_keeps_parent(tmp_path: Path) -> None:
    request, frames = _request(tmp_path)
    provider = FakeVisibleCardProvider(
        {hashlib.sha256(image).hexdigest(): _prediction() for image in frames.values()}
    )
    store = VisibleCardReviewBatchStore(tmp_path / "operations")
    prepared = store.prepare(request, provider, frame_extractor=_FixtureExtractor(frames))
    queue_path = Path(prepared["queue_path"])
    for item in load_visible_card_review_queue(queue_path).items:
        update_frame_review(
            queue_path,
            item.item_id,
            {
                "status": "reviewed",
                "decision": "BAD",
                "empty_frame": True,
                "failure_tags": [],
                "actions": [],
                "reviewer": "fixture-operator",
            },
            expected_revision=load_visible_card_review_queue(queue_path).revision,
        )

    completed = store.complete(
        request.batch_id,
        reviewer="fixture-operator",
        expected_revision=2,
    )
    assert completed["status"] == "completed"
    published_path = Path(completed["completed_queue_path"])
    published_bytes = published_path.read_bytes()
    assert load_visible_card_review_queue(published_path).revision == 2
    receipt = json.loads(
        (
            tmp_path
            / "operations"
            / "visible-card-review-batches"
            / request.batch_id
            / "receipts"
            / f"{completed['completion_receipt_id']}.json"
        ).read_text(encoding="utf-8")
    )
    dependency_kinds = {entry["kind"] for entry in receipt["dependencies"]}
    assert {
        "source_frame",
        "finder_request",
        "finder_result",
        "finder_proposal",
        "review",
    } <= dependency_kinds
    assert receipt["outputs"][0]["digest"] == completed["completed_version_digest"]

    repeated = store.complete(
        request.batch_id,
        reviewer="fixture-operator",
        expected_revision=2,
    )
    assert repeated["completed_version_id"] == completed["completed_version_id"]
    assert published_path.read_bytes() == published_bytes

    revision = store.start_revision(
        request.batch_id,
        parent_version_id=completed["completed_version_id"],
        expected_revision=2,
    )
    assert revision["status"] == "ready"
    assert revision["parent_version_id"] == completed["completed_version_id"]
    assert revision["parent_digest"] == completed["completed_version_digest"]
    assert published_path.read_bytes() == published_bytes

    unchanged_revision = store.complete(
        request.batch_id,
        reviewer="fixture-operator",
        expected_revision=2,
    )
    assert unchanged_revision["completed_version_id"] != completed["completed_version_id"]
    assert unchanged_revision["parent_version_id"] == completed["completed_version_id"]
    assert unchanged_revision["completion_receipt_id"] != completed["completion_receipt_id"]
    assert published_path.read_bytes() == published_bytes
    unchanged_path = Path(unchanged_revision["completed_queue_path"])
    unchanged_bytes = unchanged_path.read_bytes()

    revision = store.start_revision(
        request.batch_id,
        parent_version_id=unchanged_revision["completed_version_id"],
        expected_revision=2,
    )
    assert revision["parent_version_id"] == unchanged_revision["completed_version_id"]

    update_frame_review(
        queue_path,
        load_visible_card_review_queue(queue_path).items[0].item_id,
        {
            "status": "reviewed",
            "decision": "BAD",
            "empty_frame": False,
            "failure_tags": [],
            "actions": [],
            "reviewer": "fixture-operator",
        },
        expected_revision=2,
    )
    next_completed = store.complete(
        request.batch_id,
        reviewer="fixture-operator",
        expected_revision=3,
    )
    assert next_completed["completed_version_id"] != completed["completed_version_id"]
    assert next_completed["parent_version_id"] == unchanged_revision["completed_version_id"]
    assert published_path.read_bytes() == published_bytes
    assert unchanged_path.read_bytes() == unchanged_bytes


def test_completion_names_remaining_items_and_stale_revision(tmp_path: Path) -> None:
    request, frames = _request(tmp_path)
    provider = FakeVisibleCardProvider(
        {hashlib.sha256(image).hexdigest(): _prediction() for image in frames.values()}
    )
    store = VisibleCardReviewBatchStore(tmp_path / "operations")
    prepared = store.prepare(request, provider, frame_extractor=_FixtureExtractor(frames))
    with pytest.raises(VisibleCardBatchError, match="review is incomplete"):
        store.complete(request.batch_id, reviewer="fixture-operator", expected_revision=0)
    queue_path = Path(prepared["queue_path"])
    update_frame_review(
        queue_path,
        load_visible_card_review_queue(queue_path).items[0].item_id,
        {
            "status": "reviewed",
            "decision": "BAD",
            "empty_frame": True,
            "failure_tags": [],
            "actions": [],
            "reviewer": "fixture-operator",
        },
        expected_revision=0,
    )
    with pytest.raises(VisibleCardBatchConflict):
        store.complete(request.batch_id, reviewer="fixture-operator", expected_revision=0)
