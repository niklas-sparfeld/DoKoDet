"""Application settings and repository-root path resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when the backend cannot resolve its repository root."""


def discover_repository_root(start: str | Path | None = None) -> Path:
    """Find the nearest repository root containing the shared toolchain and model package."""

    location = Path.cwd() if start is None else Path(start)
    location = location.expanduser().resolve()
    if location.is_file():
        location = location.parent
    for candidate in (location, *location.parents):
        if (candidate / "mise.toml").is_file() and (candidate / "card_event_net").is_dir():
            return candidate

    # This fallback keeps the installed local backend usable when its process starts outside the
    # checkout.  It is only accepted when the package was installed from this repository.
    package_root = Path(__file__).resolve().parents[3]
    if (package_root / "mise.toml").is_file() and (package_root / "card_event_net").is_dir():
        return package_root
    raise ConfigurationError(
        "Could not find the repository root. Run the backend from a checkout containing "
        "mise.toml or set REPOSITORY_ROOT."
    )


def _resolve_path(value: Path, root: Path) -> Path:
    path = value.expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def _resolve_frontend_dist(value: Path, root: Path) -> Path:
    """Resolve the source-checkout frontend when the backend has its own mise root."""

    resolved = _resolve_path(value, root)
    if value == Path("web/dist") and not resolved.exists():
        checkout_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
        if checkout_dist.is_dir():
            return checkout_dist
    return resolved


class Settings(BaseSettings):
    """Settings loaded from environment variables with local defaults."""

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
    )

    repository_root: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("REPOSITORY_ROOT", "DOKO_REPOSITORY_ROOT"),
    )
    evidence_root: Path = Path(".runtime")
    operations_root: Path = Path("data/operations")
    frontend_dist: Path = Path("web/dist")
    repository_intake_root: Path = Path("data/intake/recordings")
    evidence_package_intake_root: Path = Path("data/intake/evidence-packages")
    pending_video_root: Path = Path("data/incoming/videos")
    card_event_checkpoint_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CARD_EVENT_CHECKPOINT_PATH",
            "CARDEVENT_CHECKPOINT_PATH",
            "CARDEVENTNET_CHECKPOINT_PATH",
        ),
    )
    max_manifest_bytes: int = 1_000_000
    max_frame_bytes: int = 10_000_000
    max_video_bytes: int = 750_000
    max_package_bytes: int = 100_000_000
    max_recording_manifest_bytes: int = 1_000_000
    max_recording_predictions_bytes: int = 10_000_000
    max_recording_video_bytes: int = 1_000_000_000
    max_recording_bytes: int = 1_100_000_000
    max_pending_video_bytes: int = 1_000_000_000
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: float = 120.0
    gemini_max_retries: int = 2
    gemini_max_concurrent_requests: int = Field(default=4, ge=1)
    visible_card_provider: Literal[
        "gemini",
        "local",
        "local-rfdetr-segmentation",
        "local-rfdetr-fine-frame",
    ] = Field(
        default="gemini",
        validation_alias=AliasChoices("VISIBLE_CARD_PROVIDER"),
    )
    visible_card_bundle_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VISIBLE_CARD_BUNDLE_PATH",
            "LOCAL_VISIBLE_CARD_BUNDLE_PATH",
            "LOCAL_VISIBLE_CARD_BUNDLE",
        ),
    )
    visible_card_segmentation_bundle_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VISIBLE_CARD_SEGMENTATION_BUNDLE_PATH",
            "LOCAL_VISIBLE_CARD_SEGMENTATION_BUNDLE_PATH",
        ),
    )
    visible_card_device: Literal["cpu", "mps"] | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VISIBLE_CARD_DEVICE",
            "LOCAL_VISIBLE_CARD_DEVICE",
            "LOCAL_DEVICE",
        ),
    )
    visible_card_identity_classifier: Literal["gemini", "local"] = Field(
        default="gemini",
        validation_alias=AliasChoices(
            "VISIBLE_CARD_IDENTITY_CLASSIFIER",
            "VISIBLE_CARD_IDENTITY_PROVIDER",
        ),
    )
    visible_card_identity_bundle_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VISIBLE_CARD_IDENTITY_BUNDLE_PATH",
            "LOCAL_VISIBLE_CARD_IDENTITY_BUNDLE_PATH",
            "LOCAL_IDENTITY_BUNDLE_PATH",
        ),
    )
    visible_card_identity_device: Literal["cpu", "mps"] | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VISIBLE_CARD_IDENTITY_DEVICE",
            "LOCAL_VISIBLE_CARD_IDENTITY_DEVICE",
            "LOCAL_IDENTITY_DEVICE",
        ),
    )
    visible_card_identity_max_concurrent_requests: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices(
            "VISIBLE_CARD_IDENTITY_MAX_CONCURRENT_REQUESTS",
            "LOCAL_IDENTITY_MAX_CONCURRENT_REQUESTS",
        ),
    )
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
        self.evidence_root = _resolve_path(self.evidence_root, root)
        # Keep an explicitly relocated runtime beside its matching data root. This also gives
        # local test and operator sandboxes isolated durable state without extra configuration.
        self.operations_root = (
            self.evidence_root.parent / "data" / "operations"
            if self.operations_root == Path("data/operations")
            else _resolve_path(self.operations_root, root)
        )
        self.frontend_dist = _resolve_frontend_dist(self.frontend_dist, root)
        self.repository_intake_root = _resolve_path(self.repository_intake_root, root)
        self.evidence_package_intake_root = _resolve_path(self.evidence_package_intake_root, root)
        self.pending_video_root = _resolve_path(self.pending_video_root, root)
        if self.card_event_checkpoint_path is not None:
            self.card_event_checkpoint_path = _resolve_path(self.card_event_checkpoint_path, root)
        if self.visible_card_bundle_path is not None:
            self.visible_card_bundle_path = _resolve_path(self.visible_card_bundle_path, root)
        if self.visible_card_segmentation_bundle_path is not None:
            self.visible_card_segmentation_bundle_path = _resolve_path(
                self.visible_card_segmentation_bundle_path, root
            )
        if self.visible_card_identity_bundle_path is not None:
            self.visible_card_identity_bundle_path = _resolve_path(
                self.visible_card_identity_bundle_path, root
            )
        return self

    @property
    def pipeline_root(self) -> Path:
        """Return the durable root for pipeline records."""

        return self.operations_root / "pipeline"

    @property
    def table_observations_root(self) -> Path:
        """Return the durable root for analyzer observations."""

        return self.operations_root / "table-observations"

    @property
    def round_analyses_root(self) -> Path:
        """Return the durable root for round-analysis artifacts."""

        return self.operations_root / "round-analyses"


__all__ = ["ConfigurationError", "Settings", "discover_repository_root"]
