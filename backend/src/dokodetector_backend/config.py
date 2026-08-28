"""Application settings and repository-root path resolution."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when the backend cannot resolve its repository root."""


def discover_repository_root(start: str | Path | None = None) -> Path:
    """Find the nearest repository root containing ``mise.toml``."""

    location = Path.cwd() if start is None else Path(start)
    location = location.expanduser().resolve()
    if location.is_file():
        location = location.parent
    for candidate in (location, *location.parents):
        if (candidate / "mise.toml").is_file():
            return candidate

    # This fallback keeps the installed local backend usable when its process starts outside the
    # checkout.  It is only accepted when the package was installed from this repository.
    package_root = Path(__file__).resolve().parents[3]
    if (package_root / "mise.toml").is_file():
        return package_root
    raise ConfigurationError(
        "Could not find the repository root. Run the backend from a checkout containing "
        "mise.toml or set REPOSITORY_ROOT."
    )


def _resolve_path(value: Path, root: Path) -> Path:
    path = value.expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _resolve_database_url(value: str, root: Path) -> str:
    """Resolve relative SQLite filenames without changing non-local database URLs."""

    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    database = value[len(prefix) :]
    if database in {":memory:", ""} or database.startswith("/"):
        return value
    return f"{prefix}{(root / database).resolve()}"


class Settings(BaseSettings):
    """Settings loaded from environment variables with local defaults."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    repository_root: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("REPOSITORY_ROOT", "DOKO_REPOSITORY_ROOT"),
    )
    database_url: str = "sqlite:///./.runtime/dokodetector.db"
    evidence_root: Path = Path(".runtime")
    repository_intake_root: Path = Path("data/intake/recordings")
    max_manifest_bytes: int = 1_000_000
    max_frame_bytes: int = 10_000_000
    max_video_bytes: int = 750_000
    max_package_bytes: int = 100_000_000
    max_recording_manifest_bytes: int = 1_000_000
    max_recording_predictions_bytes: int = 10_000_000
    max_recording_video_bytes: int = 1_000_000_000
    max_recording_bytes: int = 1_100_000_000
    server_host: str = "0.0.0.0"
    server_port: int = 8_000
    bonjour_enabled: bool = True
    bonjour_name: str = "DokoDetector"
    bonjour_hostname: str | None = None
    bonjour_address: str | None = None

    @model_validator(mode="after")
    def resolve_repository_paths(self) -> Settings:
        root = (
            self.repository_root.expanduser().resolve()
            if self.repository_root is not None
            else discover_repository_root()
        )
        if not root.is_dir():
            raise ConfigurationError(f"Repository root is not a directory: {root}")
        self.repository_root = root
        self.database_url = _resolve_database_url(self.database_url, root)
        self.evidence_root = _resolve_path(self.evidence_root, root)
        self.repository_intake_root = _resolve_path(self.repository_intake_root, root)
        return self


__all__ = ["ConfigurationError", "Settings", "discover_repository_root"]
