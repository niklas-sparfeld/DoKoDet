"""Start an isolated backend with a deterministic visible-card detector."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import uvicorn
from table_evidence_analyzer.visible_cards import ProviderResult, normalize_prediction

from dokodetector_backend.app import create_app
from dokodetector_backend.config import Settings
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer
from dokodetector_backend.recording_folder_store import RecordingFolderStore


class DeterministicDetector:
    name = "fixture-detector"
    version = "fixture-detector/v1"

    def propose(self, request: object) -> ProviderResult:
        package_id = request.package_id  # type: ignore[attr-defined]
        if str(package_id).endswith("event-000002"):
            return ProviderResult(status="unavailable", error="fixture detector failed")
        if not str(package_id).endswith("event-000000"):
            return ProviderResult(status="ok")
        prediction = normalize_prediction(
            {
                "cards": [
                    {
                        "box_2d": {"x_min": 100, "y_min": 100, "x_max": 800, "y_max": 800},
                        "polygon": [
                            {"x": 100, "y": 100},
                            {"x": 800, "y": 100},
                            {"x": 800, "y": 800},
                            {"x": 100, "y": 800},
                        ],
                        "side": "unknown",
                        "label": "fixture card",
                    }
                ]
            }
        )
        return ProviderResult(status="ok", proposals=prediction.cards)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    root = args.root.resolve()
    recordings = root / "data" / "recordings"
    if not (recordings / "recording-both").is_dir():
        source_bundle = repo / "fixtures" / "repository-bundle" / "v1" / "both"
        corpus = root / "corpus"
        corpus.mkdir(parents=True, exist_ok=True)
        bundle = corpus / "recording-both"
        shutil.copytree(source_bundle, bundle)
        video = bundle / "videos" / "video-both.mov"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:r=2",
                "-t",
                "1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(video),
            ],
            check=True,
        )
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_sha256"] = digest
        manifest["files"]["video"].update(byte_length=video.stat().st_size, sha256=digest)
        source_path = bundle / "source-record.json"
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source.update(byte_length=video.stat().st_size, sha256=digest)
        source_path.write_text(json.dumps(source, separators=(",", ":")), encoding="utf-8")
        proposal_path = bundle / "predictions" / "proposal-both.json"
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal["source_sha256"] = digest
        proposal_path.write_text(json.dumps(proposal, separators=(",", ":")), encoding="utf-8")
        for field, path in (
            ("source_record", source_path),
            ("proposal_generator_runs", proposal_path),
        ):
            descriptor = manifest["files"][field]
            if isinstance(descriptor, list):
                descriptor = descriptor[0]
            raw = path.read_bytes()
            descriptor.update(byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        manifest_path.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
        RecordingFolderStore(recordings).publish_bundle(bundle, recording_id="recording-both")
    settings = Settings(
        _env_file=None,
        repository_root=repo,
        recordings_root=recordings,
        evidence_root=root / "runtime",
        operations_root=root / "operations",
        repository_intake_root=root / "intake",
        evidence_package_intake_root=root / "evidence-packages",
        pending_video_root=root / "pending-videos",
        frontend_dist=root / "frontend",
        server_host="127.0.0.1",
        server_port=args.port,
    )
    app = create_app(
        settings,
        analyzer=create_local_poc_analyzer(),
        visible_card_provider=DeterministicDetector(),
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
