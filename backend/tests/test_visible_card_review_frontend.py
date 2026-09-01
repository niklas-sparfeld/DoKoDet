from pathlib import Path

from app_factory import create_test_app
from fastapi.testclient import TestClient

from dokodetector_backend.config import Settings


def test_packaged_frontend_serves_direct_visible_card_batch_route(tmp_path: Path) -> None:
    frontend_dist = tmp_path / "frontend-dist"
    (frontend_dist / "assets").mkdir(parents=True)
    (frontend_dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root">review workspace</div></body></html>',
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'frontend.sqlite'}",
        evidence_root=tmp_path / "runtime",
        frontend_dist=frontend_dist,
        repository_intake_root=tmp_path / "recordings",
        evidence_package_intake_root=tmp_path / "evidence-packages",
        pending_video_root=tmp_path / "pending-videos",
    )

    response = TestClient(create_test_app(settings)).get(
        "/visible-card-reviews/visible-card-batch-0123456789abcdef01234567"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "review workspace" in response.text
