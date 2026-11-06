from types import SimpleNamespace

from dokodetector_backend.event_pipeline_service import EventPipelineService


def test_recovery_reads_compact_statuses_and_only_loads_interrupted_runs(tmp_path):
    service = EventPipelineService.__new__(EventPipelineService)
    failed = []
    started = []
    service.run_store = SimpleNamespace(
        list_statuses=lambda: [
            SimpleNamespace(run_id="done", status="complete"),
            SimpleNamespace(run_id="linked", status="running"),
            SimpleNamespace(run_id="orphan", status="queued"),
        ],
        start=lambda run_id: started.append(run_id),
        fail=lambda run_id, failure: failed.append((run_id, failure.code)),
    )
    (tmp_path / "linked").write_text("{}")
    service._event_use_path = lambda run_id: tmp_path / run_id
    assert service.recover_interrupted_runs() == 1
    assert failed == [("orphan", "backend_restarted")]
    assert started == ["orphan"]


def test_recovery_marks_an_unlinked_queued_run_failed(tmp_path):
    from test_pipeline_lineage_writer import _request

    from dokodetector_backend.pipeline_store import PipelineRuntimeStorage, ProcessorRunStore

    service = EventPipelineService.__new__(EventPipelineService)
    service.run_store = ProcessorRunStore(
        PipelineRuntimeStorage(tmp_path / "runtime", tmp_path / "operations")
    )
    service.run_store.create(_request("queued-event", "event-detection", []))
    service._event_use_path = lambda run_id: tmp_path / "uses" / run_id
    assert service.recover_interrupted_runs() == 1
    assert service.run_store.require("queued-event").state.status == "failed"
