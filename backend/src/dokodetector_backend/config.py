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
    max_package_bytes: int = 100_000_000
    server_host: str = "0.0.0.0"
    server_port: int = 8_000
    bonjour_enabled: bool = True
    bonjour_name: str = "DokoDetector"
    bonjour_hostname: str | None = None
