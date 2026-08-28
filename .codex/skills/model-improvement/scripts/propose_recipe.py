#!/usr/bin/env python3
"""Create one validated model-recipe proposal without mutating campaign state."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from doko_operations.model_improvement import ModelImprovementError, load_model_recipe

_RESERVED_NAMES = frozenset(
    {
        "campaign.json",
        "comparison.json",
        "lock.json",
        "promotion-receipt.json",
        "resolved-recipe.yaml",
        "model-registry.json",
        "registry.json",
    }
)
_RESERVED_PARTS = frozenset({"campaign", "campaigns", "model-campaigns", "registry"})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _proposal_id(recipe_digest: str, rationale: str) -> str:
    identity = _canonical_json({"recipe_digest": recipe_digest, "rationale": rationale})
    return f"proposal-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _validate_output_path(path: Path, source: Path) -> None:
    if path.name in _RESERVED_NAMES or any(
        part in _RESERVED_PARTS for part in path.parts
    ):
        raise ValueError("proposal output must not target a campaign or registry path")
    if not path.name.startswith("proposed-") or path.suffix.lower() != ".json":
        raise ValueError("proposal output must use a new proposed-*.json filename")
    if path.resolve() == source.resolve():
        raise ValueError("proposal output must differ from the source recipe")
    if path.exists():
        raise ValueError(f"proposal output already exists: {path}")


def create_proposal(
    source: Path, output: Path, rationale: str
) -> tuple[dict[str, Any], str, str]:
    """Validate a source recipe and write a new doko-compatible proposal artifact."""

    rationale = rationale.strip()
    if not rationale:
        raise ValueError("rationale must not be empty")
    _validate_output_path(output, source)
    recipe = load_model_recipe(source)
    proposal_id = _proposal_id(recipe.digest, rationale)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(recipe.to_mapping(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    return recipe.to_mapping(), proposal_id, recipe.digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a validated proposed recipe; do not mutate a model campaign."
    )
    parser.add_argument(
        "--recipe", type=Path, required=True, help="Checked-in source recipe."
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New proposed-*.json path."
    )
    parser.add_argument(
        "--reason", required=True, help="Short operator-facing rationale."
    )
    args = parser.parse_args(argv)
    try:
        _proposal, proposal_id, recipe_digest = create_proposal(
            args.recipe, args.output, args.reason
        )
    except (ModelImprovementError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"proposal: {proposal_id}")
    print(f"recipe digest: {recipe_digest}")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
