"""Run the local scripted detector for stored evidence packages."""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from dokodetector_backend.config import Settings


def main(argv: list[str] | None = None) -> int:
    """Parse the one-shot detector command."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process one package")
    parser.add_argument("--all", action="store_true", help="process all pending packages")
    parser.add_argument("--package-id", type=UUID, help="process this package ID")
    args = parser.parse_args(argv)

    if not args.once:
        parser.error("--once is required")
    if args.all and args.package_id is not None:
        parser.error("--all cannot be combined with --package-id")

    try:
        results = run_command(Settings(), package_id=args.package_id, all_pending=args.all)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.all:
        print(json.dumps([json.loads(result.result_json) for result in results], indent=2))
    else:
        result = results[0] if results else None
        print(json.dumps(json.loads(result.result_json) if result else None, indent=2))
    return 0


def run_command(
    settings: Settings,
    *,
    package_id: UUID | None,
    all_pending: bool,
):
    """Run one explicit package or all pending packages."""

    from dokodetector_backend.vision_runner import build_scripted_runner

    runner = build_scripted_runner(settings)
    if all_pending:
        return runner.run_all()
    result = runner.run_once(package_id)
    return (result,) if result is not None else ()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_command"]
