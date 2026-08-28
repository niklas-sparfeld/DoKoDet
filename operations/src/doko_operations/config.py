"""Repository configuration for the local data-operations commands.

The operations package has no implicit database or service dependency.  All paths are resolved
from one repository root so that status and validation can inspect a checkout without changing it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when a repository configuration cannot be resolved."""


def discover_repository_root(start: str | Path | None = None) -> Path:
    """Find the nearest checkout root containing ``mise.toml``.

    An explicit ``--repository-root`` should be used for scripts and CI.  Discovery is only a
    convenience for an operator running ``doko`` from a repository subdirectory.
    """

    location = Path.cwd() if start is None else Path(start)
    location = location.expanduser().resolve()
    if location.is_file():
        location = location.parent
    for candidate in (location, *location.parents):
        if (candidate / "mise.toml").is_file():
            return candidate
    raise ConfigurationError(
        "Could not find the repository root. Run from a checkout containing mise.toml or pass "
        "--repository-root."
    )


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    """Resolved, read-only paths used by an operations command."""

    repository_root: Path
    intake_root: Path | None = None
    evidence_package_root: Path | None = None
    pending_video_root: Path | None = None
    artifacts_root: Path | None = None

    def __post_init__(self) -> None:
        root = Path(self.repository_root).expanduser().resolve()
        if not root.is_dir():
            raise ConfigurationError(f"Repository root is not a directory: {root}")
        object.__setattr__(self, "repository_root", root)
        for name in (
            "intake_root",
            "evidence_package_root",
            "pending_video_root",
            "artifacts_root",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = root / path
            object.__setattr__(self, name, path.resolve())

    @classmethod
    def from_environment(
        cls,
        repository_root: str | Path | None = None,
        *,
        intake_root: str | Path | None = None,
        evidence_package_root: str | Path | None = None,
        pending_video_root: str | Path | None = None,
        artifacts_root: str | Path | None = None,
    ) -> "RepositoryConfig":
        """Build configuration from arguments, then ``DOKO_REPOSITORY_ROOT``."""

        root_value = repository_root or os.environ.get("DOKO_REPOSITORY_ROOT")
        root = discover_repository_root() if root_value is None else Path(root_value)
        return cls(
            root,
            intake_root=intake_root,
            evidence_package_root=evidence_package_root,
            pending_video_root=pending_video_root,
            artifacts_root=artifacts_root,
        )

    @property
    def bundle_root(self) -> Path:
        """Return the canonical intake root, with fixture fallback for a fresh checkout.

        M1 is useful before M3 creates ``data/intake/recordings``.  The fallback allows the
        checked-in replacement fixtures to be inspected without introducing a second writable
        intake path.  As soon as the canonical root exists, it is the only default source.
        """

        if self.intake_root is not None:
            return self.intake_root
        canonical = self.repository_root / "data" / "intake" / "recordings"
        if canonical.exists():
            return canonical
        fixtures = self.repository_root / "fixtures" / "repository-bundle" / "v1"
        if fixtures.exists():
            return fixtures
        return canonical

    @property
    def derived_artifact_root(self) -> Path:
        """Return the explicit operations artifact area, if it exists or is configured."""

        return self.artifacts_root or (self.repository_root / "data" / "operations")

    @property
    def pending_root(self) -> Path:
        """Return the raw-video area that waits for operator completion."""

        return self.pending_video_root or (self.repository_root / "data" / "incoming" / "videos")

    @property
    def evidence_package_intake_root(self) -> Path:
        """Return the canonical accepted evidence-package root."""

        return self.evidence_package_root or (
            self.repository_root / "data" / "intake" / "evidence-packages"
        )


__all__ = ["ConfigurationError", "RepositoryConfig", "discover_repository_root"]
