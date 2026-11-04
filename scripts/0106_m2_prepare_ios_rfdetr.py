"""Copy and verify the frozen 0104 M1 RF-DETR package for the iOS app."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = "425ec4edeaed510743778229c2d03b6ef3fa727e5c182f50b2e8336b63916947"
PACKAGE_NAME = "rfdetr-seg-medium.mlpackage"
TARGET = ROOT / "ios/CardEventProbe/Runtime/RFDETRSegMedium.mlpackage"


def package_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    candidates = [ROOT / ".runtime/0104-m1" / PACKAGE_NAME]
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for line in worktrees.splitlines():
        if line.startswith("worktree "):
            candidates.append(
                Path(line.removeprefix("worktree ")) / ".runtime/0104-m1" / PACKAGE_NAME
            )
    source = next((path for path in candidates if path.is_dir()), None)
    if source is None:
        print(f"Missing frozen input: .runtime/0104-m1/{PACKAGE_NAME}", file=sys.stderr)
        return 2

    actual = package_sha256(source)
    if actual != EXPECTED_SHA256:
        print(f"Frozen RF-DETR digest mismatch: expected {EXPECTED_SHA256}, got {actual}", file=sys.stderr)
        return 2

    if TARGET.exists():
        existing = package_sha256(TARGET)
        if existing != EXPECTED_SHA256:
            print(f"Refusing to replace local model input with digest {existing}: {TARGET}", file=sys.stderr)
            return 2
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, TARGET)

    print(f"Prepared {TARGET.relative_to(ROOT)} ({EXPECTED_SHA256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
