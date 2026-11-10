"""Disposable backend for the recording folder browser proof."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from doko_operations.pipeline_data import canonical_event_data_bytes
from table_evidence_analyzer.visible_cards import ProviderResult

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer
from dokodetector_backend.recording_folder_store import RecordingFolderStore

M5_RECORDING_ID = "cardeventnet-IMG_0662"
M5_OUTPUT_NODE_ID = "8bfa825d-94af-5ac6-877d-a1381e662d65"
M5_OUTPUT_REVISION_ID = "d9c461ee-c7f9-5a2c-be60-36da3ea9a169"
M5_PARENT_SET_ID = "1dca5a93-4a87-59f6-ab83-d5c72154916b"
M5_PARENT_VERSION = "d41f92f9-7fd1-52db-a065-7c94f963713a"
M5_LEGACY_EVENT_REVISION_ID = "reference-events-fd5c08dc4f7540053b3ed1c04606b909"


class RestartableBrowserApp:
    """Recreate the backend app against the same disposable recording files."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.app = self._new_app()
        self._lifespan = None

    def _new_app(self):
        app = create_app(
            self.settings,
            analyzer=create_local_poc_analyzer(),
            visible_card_provider=BrowserDetector(),
        )
        _seed_pre_m3_visible_output(app)

        def forbid_recording_catalog(*_args, **_kwargs):
            raise AssertionError("the retired recording catalog was called")

        app.state.recording_bundle_store.list_metadata = forbid_recording_catalog
        app.state.recording_bundle_store.get_metadata = forbid_recording_catalog
        app.state.round_analysis_service.recording_catalog = forbid_recording_catalog
        selection_store = app.state.pipeline_selection_store
        get_exact = selection_store.get_exact
        update_exact = selection_store.update_exact

        def forbid_event_get(recording_id: str, content_type: str):
            if content_type == "events":
                raise AssertionError("legacy event selection read was called")
            return get_exact(recording_id, content_type)

        def forbid_event_update(recording_id: str, content_type: str, **kwargs):
            if content_type == "events":
                raise AssertionError("legacy event selection write was called")
            return update_exact(recording_id, content_type, **kwargs)

        selection_store.get_exact = forbid_event_get
        selection_store.update_exact = forbid_event_update
        return app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    self._lifespan = self.app.router.lifespan_context(self.app)
                    await self._lifespan.__aenter__()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    if self._lifespan is not None:
                        await self._lifespan.__aexit__(None, None, None)
                        self._lifespan = None
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if scope["type"] == "http" and scope["path"] == "/__test/restart":
            if self._lifespan is not None:
                await self._lifespan.__aexit__(None, None, None)
            self.app = self._new_app()
            self._lifespan = self.app.router.lifespan_context(self.app)
            await self._lifespan.__aenter__()
            body = b'{"restarted":true}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        if scope["type"] == "http" and scope["path"] == "/__test/saved-output-sha256":
            node_store = self.app.state.pipeline_selection_store.node_store
            payload = (
                node_store.revision_path(M5_OUTPUT_NODE_ID, M5_OUTPUT_REVISION_ID) / "revision.json"
            )
            body = json.dumps({"sha256": hashlib.sha256(payload.read_bytes()).hexdigest()}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class BrowserDetector:
    """Deterministic provider for the persisted recording-folder browser proof."""

    name = "gemini"
    version = "recording-folder-browser/v1"

    def propose(self, _request) -> ProviderResult:
        return ProviderResult(status="ok")


def main() -> None:
    repository = Path(__file__).parents[2]
    fixture = repository / "fixtures/repository-bundle/v1/both"
    with TemporaryDirectory(prefix="recording-folder-browser-") as directory:
        transport = Path(directory) / "transport" / "recording-both"
        shutil.copytree(fixture, transport)
        _make_playable_transport(transport)
        data_root = Path(directory) / "data" / "recordings"
        recording_store = RecordingFolderStore(data_root)
        recording_store.publish_bundle(transport, recording_id="recording-both")
        event_sets = EventSetStore(recording_store)
        reference = event_sets.save(
            "recording-both",
            set_id="retained-reference",
            version="1",
            content={
                "schema_version": "event-data/v1",
                "events": [
                    {
                        "event_id": "retained-event-1",
                        "event_type": "card_state_changed",
                        "start_us": 500_000,
                        "end_us": 750_000,
                    }
                ],
            },
            origin="corrected",
            provenance={"source": "recording-folder-browser-proof"},
        )
        event_sets.save_review(
            "recording-both",
            reference["set_id"],
            reference["version"],
            review_id="retained-reference-review",
            kind="overall",
            question="Is this event set correct?",
            decision="accepted",
            reviewer={"id": "test-operator"},
            evidence={"policy": "event-review/v1", "source": "browser-proof"},
        )
        generated = event_sets.save(
            "recording-both",
            set_id="retained-generated",
            version="1",
            content={
                "schema_version": "event-data/v1",
                "events": [
                    {
                        "event_id": "retained-event-1",
                        "event_type": "card_state_changed",
                        "start_us": 600_000,
                        "end_us": 800_000,
                    }
                ],
            },
            origin="processor",
            provenance={"source": "recording-folder-browser-proof"},
        )
        retained_transport = Path(directory) / "transport" / M5_RECORDING_ID
        shutil.copytree(fixture, retained_transport)
        _make_playable_transport(retained_transport, recording_id=M5_RECORDING_ID)
        m5_recording_store = RecordingFolderStore(data_root)
        m5_recording_store.publish_bundle(retained_transport, recording_id=M5_RECORDING_ID)
        m5_event_sets = EventSetStore(m5_recording_store)
        parent_content = {
            "schema_version": "event-data/v1",
            "events": [
                {
                    "event_id": "cardeventnet-event-img_0662-000",
                    "event_type": "card_state_changed",
                    "start_us": 2_001_934,
                    "end_us": 2_002_934,
                }
            ],
        }
        parent_digest = hashlib.sha256(canonical_event_data_bytes(parent_content)).hexdigest()
        m5_event_sets.save(
            M5_RECORDING_ID,
            set_id=M5_PARENT_SET_ID,
            version=M5_PARENT_VERSION,
            content=parent_content,
            origin="corrected",
            provenance={
                "source": "retained-corpus-browser-proof",
                "source_metadata": {"legacy_revision_id": M5_LEGACY_EVENT_REVISION_ID},
                "source_content_sha256": parent_digest,
            },
        )
        m5_generated = m5_event_sets.save(
            M5_RECORDING_ID,
            set_id="retained-generated-alternative",
            version="1",
            content={
                "schema_version": "event-data/v1",
                "events": [
                    {
                        "event_id": "cardeventnet-event-img_0662-000",
                        "event_type": "card_state_changed",
                        "start_us": 1_000_000,
                        "end_us": 1_001_000,
                    }
                ],
            },
            origin="processor",
            provenance={"source": "retained-corpus-browser-proof"},
        )
        m5_root = m5_recording_store.get(M5_RECORDING_ID)
        assert m5_root is not None
        m5_event_sets.select(
            M5_RECORDING_ID,
            choice="generated",
            reference={"set_id": m5_generated["set_id"], "version": "1"},
            expected_version=m5_root.version,
        )
        m5_root = m5_recording_store.get(M5_RECORDING_ID)
        assert m5_root is not None
        m5_event_sets.select(
            M5_RECORDING_ID,
            choice="reference",
            reference={"set_id": M5_PARENT_SET_ID, "version": M5_PARENT_VERSION},
            expected_version=m5_root.version,
        )
        root = recording_store.get("recording-both")
        assert root is not None
        event_sets.select(
            "recording-both",
            choice="generated",
            reference={"set_id": generated["set_id"], "version": generated["version"]},
            expected_version=root.version,
        )
        root = recording_store.get("recording-both")
        assert root is not None
        event_sets.select(
            "recording-both",
            choice="reference",
            reference={"set_id": reference["set_id"], "version": reference["version"]},
            expected_version=root.version,
        )
        settings = Settings(
            _env_file=None,
            repository_root=repository,
            recordings_root=data_root,
            evidence_root=Path(directory) / "runtime",
            operations_root=Path(directory) / "operations",
            repository_intake_root=Path(directory) / "transport",
            evidence_package_intake_root=Path(directory) / "packages",
            pending_video_root=Path(directory) / "incoming",
            frontend_dist=repository / "web" / "dist",
        )
        app = RestartableBrowserApp(settings)
        uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")


def _make_playable_transport(bundle: Path, *, recording_id: str | None = None) -> None:
    video_path = bundle / "videos" / "video-both.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=96x64:r=5",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(video_path),
        ],
        check=True,
    )
    video_bytes = video_path.read_bytes()
    video_digest = hashlib.sha256(video_bytes).hexdigest()
    source_path = bundle / "source-record.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source.update(sha256=video_digest, byte_length=len(video_bytes))
    if recording_id is not None:
        source["recording_id"] = recording_id
        source["original_filename"] = "pre-m3-recording.mov"
    source_bytes = _write_json(source_path, source)
    proposal_path = bundle / "predictions" / "proposal-both.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["source_sha256"] = video_digest
    if recording_id is not None:
        proposal["recording_id"] = recording_id
    proposal_bytes = _write_json(proposal_path, proposal)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_sha256"] = video_digest
    if recording_id is not None:
        manifest["recording_id"] = recording_id
    manifest["files"]["video"].update(byte_length=len(video_bytes), sha256=video_digest)
    manifest["files"]["source_record"].update(
        byte_length=len(source_bytes), sha256=hashlib.sha256(source_bytes).hexdigest()
    )
    manifest["files"]["proposal_generator_runs"][0].update(
        byte_length=len(proposal_bytes), sha256=hashlib.sha256(proposal_bytes).hexdigest()
    )
    _write_json(manifest_path, manifest)


def _write_json(path: Path, value: dict) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return raw


def _seed_pre_m3_visible_output(app) -> None:
    node_store = app.state.pipeline_selection_store.node_store
    try:
        node_store.get(M5_OUTPUT_NODE_ID)
        return
    except (FileNotFoundError, KeyError):
        pass
    source = app.state.event_pipeline_service.get_recording_source(M5_RECORDING_ID).to_mapping()
    node_store.create(
        M5_OUTPUT_NODE_ID,
        "Retained pre-M3 visible-card output",
        "visible_cards",
        source,
        {"schema_version": "visible-card-data/v2", "outcomes": []},
        {
            "origin": "processor",
            "coverage": {
                "kind": "requested-event-frames",
                "event_revision_id": M5_LEGACY_EVENT_REVISION_ID,
            },
        },
        revision_id=M5_OUTPUT_REVISION_ID,
    )
    app.state.pipeline_selection_store.update_exact(
        M5_RECORDING_ID,
        "visible_cards",
        expected_revision=0,
        selected_generated=None,
        selected_completed_reference={
            "node_id": M5_OUTPUT_NODE_ID,
            "revision_id": M5_OUTPUT_REVISION_ID,
        },
    )


if __name__ == "__main__":
    main()
