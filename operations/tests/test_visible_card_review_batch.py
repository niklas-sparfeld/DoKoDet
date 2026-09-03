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
    CachedVisibleCardProvider,
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


class _RecoveringProvider:
    name = "local"
    version = "local-visible-cards-v1"

    def __init__(self) -> None:
        self.calls = 0

    def propose(self, request: object) -> ProviderResult:
        del request
        self.calls += 1
        if self.calls == 1:
            return ProviderResult(status="unavailable", error="fixture provider error")
        return ProviderResult(status="ok", raw_response={"provider": self.name})


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


def test_batch_loader_normalizes_items_from_before_last_detector_tracking(
    tmp_path: Path,
) -> None:
    request, frames = _request(tmp_path)
    provider = FakeVisibleCardProvider(
        {hashlib.sha256(image).hexdigest(): _prediction() for image in frames.values()}
    )
    store = VisibleCardReviewBatchStore(tmp_path / "operations")
    prepared = store.prepare(request, provider, frame_extractor=_FixtureExtractor(frames))
    batch_root = tmp_path / "operations" / "visible-card-review-batches" / request.batch_id
    batch_path = batch_root / "batch.json"
    legacy = json.loads(batch_path.read_text(encoding="utf-8"))
    for item in legacy["items"]:
        item.pop("last_detector", None)
    batch_path.write_text(json.dumps(legacy), encoding="utf-8")

    loaded = load_visible_card_review_batch(batch_path)

    assert loaded["batch_id"] == prepared["batch_id"]
    assert all(item["last_detector"] == request.detector.to_mapping() for item in loaded["items"])


def test_redetect_updates_one_item_with_its_latest_detector_and_result(tmp_path: Path) -> None:
    request, frames = _request(tmp_path)
    provider = FakeVisibleCardProvider(
        {hashlib.sha256(image).hexdigest(): _prediction() for image in frames.values()}
    )
    store = VisibleCardReviewBatchStore(tmp_path / "operations")
    prepared = store.prepare(request, provider, frame_extractor=_FixtureExtractor(frames))
    item_id = prepared["items"][0]["item_id"]
    detector = replace(
        request.detector,
        bundle_id="fake-gemini-3.7-flash",
        bundle_digest="c" * 64,
        model="gemini-3.7-flash",
        provider="fake",
        provider_version="fake-visible-cards-test-v2",
    )

    updated = store.redetect(
        request.batch_id,
        item_id,
        provider,
        detector=detector,
        expected_revision=0,
    )

    item = updated["items"][0]
    assert updated["status"] == "ready"
    assert item["last_detector"] == detector.to_mapping()
    assert item["finder"]["detector"] == detector.to_mapping()
    assert item["finder"]["request"]["model"] == "gemini-3.7-flash"
    assert item["finder"]["result_path"].endswith("-latest.json")
    queue = load_visible_card_review_queue(updated["queue_path"])
    queued = next(value for value in queue.items if value.item_id == item_id)
    assert queued.teacher.request["model"] == "gemini-3.7-flash"

    second_detector = replace(
        detector,
        model="gemini-3.8-flash",
        bundle_id="fake-gemini-3.8-flash",
    )
    second = store.redetect(
        request.batch_id,
        item_id,
        provider,
        detector=second_detector,
        expected_revision=1,
    )
    assert second["items"][0]["last_detector"] == second_detector.to_mapping()
    assert second["items"][0]["finder"]["result_path"] == item["finder"]["result_path"]
    queue = load_visible_card_review_queue(second["queue_path"])
    queued = next(value for value in queue.items if value.item_id == item_id)
    assert queued.teacher.request["model"] == "gemini-3.8-flash"


def test_redetect_bypasses_the_visible_card_response_cache(tmp_path: Path) -> None:
    class _CountingProvider:
        name = "local"
        version = "local-visible-cards-test-v1"

        def __init__(self) -> None:
            self.calls = 0

        def propose(self, _request: object) -> ProviderResult:
            self.calls += 1
            return ProviderResult(status="ok", raw_response={"call": self.calls})

    request, frames = _request(tmp_path)
    underlying = _CountingProvider()
    provider = CachedVisibleCardProvider(underlying, tmp_path / "cache")
    store = VisibleCardReviewBatchStore(tmp_path / "operations")
    prepared = store.prepare(request, provider, frame_extractor=_FixtureExtractor(frames))
    assert underlying.calls == 2

    store.redetect(
        request.batch_id,
        prepared["items"][0]["item_id"],
        provider,
        detector=request.detector,
        expected_revision=0,
    )

    assert underlying.calls == 3


def test_redetect_can_recover_one_failed_item_without_retrying_the_batch(
    tmp_path: Path,
) -> None:
    request, frames = _request(tmp_path)
    provider = _RecoveringProvider()
    store = VisibleCardReviewBatchStore(tmp_path / "operations")
    prepared = store.prepare(request, provider, frame_extractor=_FixtureExtractor(frames))

    assert prepared["status"] == "failed"
    assert prepared["queue_path"] is None
    failed_item = next(item for item in prepared["items"] if item["failure"] is not None)

    updated = store.redetect(
        request.batch_id,
        failed_item["item_id"],
        provider,
        detector=request.detector,
        expected_revision=0,
    )

    assert updated["status"] == "ready"
    assert updated["failures"] == []
    assert updated["progress"]["finder_completed"] == 2
    assert provider.calls == 3
    queue = load_visible_card_review_queue(updated["queue_path"])
    recovered = next(item for item in queue.items if item.item_id == failed_item["item_id"])
    assert recovered.review.status == "unreviewed"
    assert recovered.teacher.result["status"] == "ok"


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
            replace(request, detector=replace(request.detector, provider="unsupported")),
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


def test_gemini_provider_is_allowed_for_visible_card_review(tmp_path: Path) -> None:
    request, frames = _request(tmp_path)
    request = replace(request, detector=replace(request.detector, provider="gemini"))
    provider = FakeVisibleCardProvider(
        {hashlib.sha256(image).hexdigest(): _prediction() for image in frames.values()}
    )

    result = VisibleCardReviewBatchStore(tmp_path / "operations").prepare(
        request,
        provider,
        frame_extractor=_FixtureExtractor(frames),
    )

    assert result["status"] == "ready"
    assert all(item["finder"]["request"]["provider"] == "gemini" for item in result["items"])


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
