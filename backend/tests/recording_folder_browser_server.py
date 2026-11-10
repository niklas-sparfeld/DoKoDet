"""Disposable backend for the recording folder browser proof."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from table_evidence_analyzer.visible_cards import ProviderResult

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.event_set_store import EventSetStore
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer
from dokodetector_backend.recording_folder_store import RecordingFolderStore


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


def _make_playable_transport(bundle: Path) -> None:
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
    source_bytes = _write_json(source_path, source)
    proposal_path = bundle / "predictions" / "proposal-both.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal["source_sha256"] = video_digest
    proposal_bytes = _write_json(proposal_path, proposal)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_sha256"] = video_digest
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


if __name__ == "__main__":
    main()
