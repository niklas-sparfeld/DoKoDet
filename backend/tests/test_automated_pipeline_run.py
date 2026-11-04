from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dokodetector_backend.automated_pipeline_run import (
    AutomatedPipelinePreflightError,
    AutomatedPipelineRunConflict,
    AutomatedPipelineRunService,
    AutomatedPipelineRunStore,
)
from dokodetector_backend.pipeline_run_preflight import validate_local_stage_providers


def _request() -> dict[str, object]:
    return {
        "idempotency_key": str(uuid4()),
        "session_id": "session-1",
        "round_id": "round-1",
        "round_context": {
            "game_id": "game-1",
            "round_id": "round-1",
            "active_players": ["p1", "p2", "p3", "p4"],
            "dealer": "p1",
            "first_trick_leader": "p2",
        },
        "rules_version": "v1",
        "search": {
            "max_missing_plays": 1,
            "max_hypotheses": 16,
            "max_search_nodes": 1000,
        },
        "stage_requests": {
            name: {"configuration": {"stage": name}}
            for name in (
                "event_proposals",
                "visible_card_and_pile_proposals",
                "card_scene_and_calibration",
                "visual_identity_proposals",
                "table_observations",
            )
        },
    }


def _service(tmp_path: Path, *, session_id: str = "session-1") -> AutomatedPipelineRunService:
    return AutomatedPipelineRunService(
        store=AutomatedPipelineRunStore(tmp_path),
        recording_source_provider=lambda recording_id: SimpleNamespace(
            to_mapping=lambda: {
                "schema_version": "recording-video/v1",
                "recording_id": recording_id,
                "video_sha256": "a" * 64,
            }
        ),
        recording_provider_validator=lambda _recording_id, stage_requests: {
            "stage_requests": {
                **stage_requests,
                "event_proposals": {
                    **stage_requests["event_proposals"],
                    "configuration": {"threshold": 0.5, "checkpoint_sha256": "b" * 64},
                },
            },
            "providers": {"event_proposals": {"name": "local-fixture", "version": "1"}},
        },
        round_session_provider=lambda _recording_id: session_id,
    )


def test_start_freezes_inputs_persists_status_and_handles_idempotent_retry(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    request = _request()

    created, idempotent = service.start("recording-1", request)
    read = service.read(created["run_id"])
    retried, was_idempotent = service.start("recording-1", request)

    assert not idempotent
    assert was_idempotent
    assert retried == created == read
    assert created["status"] == "accepted"
    assert created["source"]["video_sha256"] == "a" * 64
    assert created["request"]["stage_requests"]["event_proposals"]["configuration"] == {
        "threshold": 0.5,
        "checkpoint_sha256": "b" * 64,
    }
    assert created["resolved_providers"]["event_proposals"]["name"] == "local-fixture"
    assert [stage["status"] for stage in created["stages"]] == ["pending"] * 6


def test_start_rejects_invalid_preflight_without_persisting_a_run(tmp_path: Path) -> None:
    service = _service(tmp_path, session_id="different-session")
    with pytest.raises(AutomatedPipelinePreflightError, match="session"):
        service.start("recording-1", _request())
    assert list((tmp_path / "runs").glob("*.json")) == []


def test_start_rejects_missing_stage_settings_without_provider_work(tmp_path: Path) -> None:
    called = False

    def validate(_recording_id: str, _stage_requests: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    service = AutomatedPipelineRunService(
        store=AutomatedPipelineRunStore(tmp_path),
        recording_source_provider=lambda _recording_id: SimpleNamespace(to_mapping=lambda: {}),
        recording_provider_validator=validate,  # type: ignore[arg-type]
        round_session_provider=lambda _recording_id: "session-1",
    )
    request = _request()
    del request["stage_requests"]["visual_identity_proposals"]  # type: ignore[index]

    with pytest.raises(AutomatedPipelinePreflightError, match="Missing stage settings"):
        service.start("recording-1", request)
    assert not called


def test_start_prevents_concurrent_run_and_rejects_key_reuse(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = _request()
    created, _ = service.start("recording-1", first)

    second = _request()
    with pytest.raises(AutomatedPipelineRunConflict, match="active pipeline run") as error:
        service.start("recording-1", second)
    assert error.value.active_run_id == created["run_id"]

    changed_retry = dict(first)
    changed_retry["search"] = {
        "max_missing_plays": 2,
        "max_hypotheses": 16,
        "max_search_nodes": 1000,
    }
    with pytest.raises(AutomatedPipelineRunConflict, match="different run"):
        service.start("recording-1", changed_retry)


def test_simultaneous_starts_create_only_one_active_run(tmp_path: Path) -> None:
    service = _service(tmp_path)
    requests = [_request(), _request()]

    def start(request: dict[str, object]) -> str:
        try:
            return service.start("recording-1", request)[0]["run_id"]
        except AutomatedPipelineRunConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(start, requests))

    assert results.count("conflict") == 1
    assert len(list((tmp_path / "runs").glob("*.json"))) == 1


def test_finished_run_releases_recording_for_a_fresh_start(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first, _ = service.start("recording-1", _request())
    service.store.finish(first["run_id"], status="failed")

    second, _ = service.start("recording-1", _request())
    assert second["run_id"] != first["run_id"]


def test_provider_preflight_freezes_local_models_and_automatic_crop(tmp_path: Path) -> None:
    from dokodetector_backend.event_pipeline_service import CardEventFileProvider

    checkpoint = tmp_path / "event-model.pt"
    checkpoint.write_bytes(b"fixture checkpoint")

    class EventService:
        event_provider = CardEventFileProvider(tmp_path)

        def _build_request(self, _recording_id: str, payload: dict[str, object]) -> object:
            configuration = payload["request"]["configuration"]  # type: ignore[index]
            return SimpleNamespace(
                configuration=configuration,
                implementation=SimpleNamespace(version="fixture-v1"),
            )

        @staticmethod
        def _freeze_provider_defaults(request: object) -> object:
            return request

    visible_provider = SimpleNamespace(
        name="local-rfdetr-segmentation",
        version="fixture-v2",
        bundle_identity={"bundle_sha256": "c" * 64},
    )
    identity_classifier = SimpleNamespace(
        name="local-dino",
        version="fixture-v3",
        model="dino-fixture",
        bundle_identity={"bundle_sha256": "d" * 64},
    )
    stage_requests = {
        name: {"configuration": {}}
        for name in (
            "event_proposals",
            "visible_card_and_pile_proposals",
            "card_scene_and_calibration",
            "visual_identity_proposals",
            "table_observations",
        )
    }
    stage_requests["event_proposals"]["configuration"] = {"checkpoint_path": str(checkpoint)}
    stage_requests["visible_card_and_pile_proposals"]["configuration"] = {
        "provider": "local-rfdetr-segmentation"
    }
    stage_requests["visual_identity_proposals"]["configuration"] = {"provider": "local-dino"}

    frozen = validate_local_stage_providers(
        "recording-1",
        stage_requests,
        event_service=EventService(),
        visible_card_service=SimpleNamespace(
            _provider_for_selection=lambda _name: visible_provider
        ),
        visual_identity_service=SimpleNamespace(
            _classifier_for_selection=lambda _name: identity_classifier
        ),
    )

    assert frozen["providers"]["event_proposals"]["checkpoint_sha256"]
    assert frozen["providers"]["visible_card_and_pile_proposals"]["bundle_identity"] == {
        "bundle_sha256": "c" * 64
    }
    assert frozen["stage_requests"]["visual_identity_proposals"]["crop_policy"] == {
        "policy_id": "predicted_visible_region",
        "output_encoding": "ppm",
    }
