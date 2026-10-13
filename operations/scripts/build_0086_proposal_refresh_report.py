#!/usr/bin/env python3
"""Audit and write the durable Epic 0086 M3 proposal-refresh report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from doko_operations.reviewed_virtual_card_proposal_refresh import (
    DEFAULT_OUTPUT,
    build_0086_proposal_refresh_report,
    validate_0086_proposal_refresh_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    options = {"inventory_path": args.inventory} if args.inventory is not None else {}
    report = build_0086_proposal_refresh_report(args.root, **options)
    validate_0086_proposal_refresh_report(report)
    output = args.output.expanduser()
    if not output.is_absolute():
        output = args.root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Report SHA-256: {report['report_sha256']}")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
