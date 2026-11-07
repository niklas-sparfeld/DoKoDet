from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from support.job_participants import FakeParticipant

from dokodetector_backend.job_store import JobManager


def enqueue(manager: JobManager, name: str) -> str:
    return manager.accept(
        str(uuid4()),
        {"type": "fake", "context": {"recording_id": "r"}, "request": {"input": name}},
    ).id


def test_publication_wins_cancel_race_and_is_recovered_after_crash(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    artifact_root = tmp_path / "published"
    artifact_root.mkdir()
    crashed = False

    def after_write(point: str) -> None:
        nonlocal crashed
        if point == "publication_domain_commit" and not crashed:
            crashed = True
            raise RuntimeError("simulated process loss")

    def verify(job: object, results: list[dict[str, object]]) -> bool:
        return (artifact_root / f"{job.id}.json").exists()  # type: ignore[attr-defined]

    with (
        pytest.raises(RuntimeError, match="simulated process loss"),
        JobManager(
            tmp_path,
            participant,
            after_write=after_write,
            verify_publication=verify,
        ) as manager,
    ):
        job_id = enqueue(manager, "publish-me")
        manager.transition(job_id, "running")
        manager.publish(
            job_id,
            [{"kind": "fake_result", "id": "result-1", "digest": "abc"}],
            lambda: (artifact_root / f"{job_id}.json").write_text("committed"),
        )

    with JobManager(tmp_path, participant, verify_publication=verify) as manager:
        recovered = manager.get(job_id)
        assert recovered.state == "succeeded"
        assert recovered.results[0]["id"] == "result-1"
        assert manager.cancel(job_id).state == "succeeded"


def test_cancel_before_publication_prevents_output_commit(tmp_path: Path) -> None:
    participant = FakeParticipant(tmp_path / "domain")
    with JobManager(tmp_path, participant) as manager:
        job_id = enqueue(manager, "cancel-before-publish")
        manager.transition(job_id, "running")
        assert manager.cancel(job_id).state == "cancelling"
        committed = False

        def commit() -> None:
            nonlocal committed
            committed = True

        assert not manager.publish(job_id, [], commit)
        assert not committed
        assert manager.get(job_id).state == "cancelling"
