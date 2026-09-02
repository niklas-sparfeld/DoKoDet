from __future__ import annotations

import math
import shutil
import time
from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient
from test_card_event_review_api import FIXTURE_ROOT

from dokodetector_backend.config import Settings
from dokodetector_backend.repository import upgrade_database

BACKEND_ROOT = Path(__file__).parents[1]


def _backend(tmp_path: Path) -> TestClient:
    intake_root = tmp_path / "data" / "intake" / "recordings"
    (intake_root / "recording-both").parent.mkdir(parents=True)
    shutil.copytree(FIXTURE_ROOT, intake_root / "recording-both")
    database_url = f"sqlite:///{tmp_path / 'review.sqlite'}"
    upgrade_database(BACKEND_ROOT, database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        evidence_root=tmp_path / "runtime",
        operations_root=tmp_path / "data" / "operations",
        repository_intake_root=intake_root,
        evidence_package_intake_root=tmp_path / "data" / "intake" / "evidence-packages",
        pending_video_root=tmp_path / "data" / "incoming" / "videos",
    )
    return TestClient(create_test_app(settings))


def _annotation(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "cardevent-annotation/v2",
        "video": "video-both.mov",
        "events": events,
    }


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def test_card_event_review_latency_budget_has_repeatable_raw_stage_timings(
    tmp_path: Path,
) -> None:
    client = _backend(tmp_path)
    app = client.app

    started = time.perf_counter()
    first_collection = client.get("/v1/recordings/recording-both/card-event-reviews")
    cold_review_load_ms = (time.perf_counter() - started) * 1000.0
    assert first_collection.status_code == 200

    create = client.post(
        "/v1/recordings/recording-both/card-event-reviews",
        json={"operator": "Niklas"},
    )
    assert create.status_code == 201
    review_id = create.json()["review_id"]
    proposal_id = create.json()["proposals"][0]["proposal_id"]

    review_load_ms: list[float] = []
    for _ in range(10):
        started = time.perf_counter()
        response = client.get(f"/v1/card-event-reviews/{review_id}")
        review_load_ms.append((time.perf_counter() - started) * 1000.0)
        assert response.status_code == 200, response.text

    draft_write_ms: list[float] = []
    revision = 0
    for _ in range(5):
        started = time.perf_counter()
        response = client.put(
            f"/v1/card-event-reviews/{review_id}",
            json={
                "annotation": _annotation([]),
                "proposals": [{"proposal_id": proposal_id, "decision": "undecided"}],
                "expected_revision": revision,
                "full_video_acknowledged": True,
            },
        )
        draft_write_ms.append((time.perf_counter() - started) * 1000.0)
        assert response.status_code == 200
        revision = response.json()["draft_revision"]

    event_command_ms: list[float] = []
    started = time.perf_counter()
    response = client.patch(
        f"/v1/card-event-reviews/{review_id}/events/{create.json()['events'][0]['event_id']}",
        json={
            "client_command_id": "performance-dismiss",
            "expected_revision": revision,
            "action": "dismiss",
        },
    )
    event_command_ms.append((time.perf_counter() - started) * 1000.0)
    assert response.status_code == 200
    revision = response.json()["draft_revision"]
    for index in range(30):
        started = time.perf_counter()
        response = client.post(
            f"/v1/card-event-reviews/{review_id}/events",
            json={
                "client_command_id": f"performance-add-{index}",
                "expected_revision": revision,
                "effective_time_s": 1.2 + index * 0.02,
                "type": "card_played",
            },
        )
        event_command_ms.append((time.perf_counter() - started) * 1000.0)
        assert response.status_code == 200, response.text
        assert "review" not in response.json()
        revision = response.json()["draft_revision"]

    started = time.perf_counter()
    completion = client.post(
        f"/v1/card-event-reviews/{review_id}/complete",
        json={
            "reviewer": "Niklas",
            "expected_revision": revision,
            "full_video_acknowledged": True,
        },
    )
    completion_ms = (time.perf_counter() - started) * 1000.0
    assert completion.status_code == 200

    timings = app.state.card_event_review_source_cache.recent_timings()
    assert timings
    assert any(item["cache_hit"] is False for item in timings)
    assert any(item["cache_hit"] is True for item in timings)
    cold_stages = [item for item in timings if item["cache_hit"] is False]
    assert {"bundle_metadata_read_ms", "source_context_validation_ms"} <= set(cold_stages[-1])
    assert cold_stages[-1]["media_probe_ms"] > cold_stages[-1]["source_context_validation_ms"]
    assert all(item["bundle_metadata_read_ms"] == 0.0 for item in timings if item["cache_hit"])
    assert all(item["media_probe_ms"] == 0.0 for item in timings if item["cache_hit"])

    assert _p95(event_command_ms) <= 250.0
    assert _p95(review_load_ms) <= 500.0
    assert _p95(draft_write_ms) <= 500.0
    assert completion_ms <= 500.0
    assert cold_review_load_ms >= 0.0
    print(
        {
            "cold_review_load_ms": cold_review_load_ms,
            "warm_review_load_p95_ms": _p95(review_load_ms),
            "event_command_p95_ms": _p95(event_command_ms),
            "draft_write_p95_ms": _p95(draft_write_ms),
            "completion_ms": completion_ms,
            "command_response_bytes_last": len(response.content),
            "cold_source_stages_ms": cold_stages[-1],
        }
    )
