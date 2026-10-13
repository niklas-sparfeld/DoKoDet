from __future__ import annotations

import argparse
from pathlib import Path

from doko_operations.reviewed_visible_card_handoff import (
    build_reviewed_visible_card_handoff,
    validate_reviewed_visible_card_handoff,
    write_reviewed_visible_card_handoff,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the read-only Epic 0086 detection handoff.")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/reports/0086-M2_Detection_Only_Handoff.json"),
    )
    parser.add_argument("--verify-source-bytes", action="store_true")
    args = parser.parse_args()

    handoff = build_reviewed_visible_card_handoff(
        args.repository_root,
        verify_source_bytes=args.verify_source_bytes,
    )
    validate_reviewed_visible_card_handoff(handoff)
    output = args.output if args.output.is_absolute() else args.repository_root / args.output
    write_reviewed_visible_card_handoff(output, handoff)
    print(
        f"{handoff['status']}: {handoff['summary']['eligible_recording_count']} eligible of "
        f"{handoff['summary']['candidate_recording_count']} candidates; "
        f"handoff {handoff['handoff_sha256']} written to {output}"
    )
    return 0 if handoff["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
