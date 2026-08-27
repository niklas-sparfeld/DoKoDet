"""Application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables with local defaults."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: str = "sqlite:///./.runtime/dokodetector.db"
    evidence_root: Path = Path(".runtime")
    max_manifest_bytes: int = 1_000_000
    max_frame_bytes: int = 10_000_000
    max_video_bytes: int = 750_000
    max_package_bytes: int = 100_000_000
    max_recording_manifest_bytes: int = 1_000_000
    max_recording_predictions_bytes: int = 10_000_000
    max_recording_video_bytes: int = 1_000_000_000
    max_recording_bytes: int = 1_100_000_000
    vision_detector_name: str = "scripted"
    vision_detector_version: str = "scripted-v1"
    vision_detector_mapping_path: Path | None = None
    server_host: str = "0.0.0.0"
    server_port: int = 8_000
    bonjour_enabled: bool = True
    bonjour_name: str = "DokoDetector"
    bonjour_hostname: str | None = None
    bonjour_address: str | None = None
