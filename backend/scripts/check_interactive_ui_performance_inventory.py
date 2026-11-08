"""Check that the interactive performance inventory classifies every API operation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dokodetector_backend.app import create_app
from dokodetector_backend.poc_analyzer import create_local_poc_analyzer

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "reports" / "0114-M0_Interactive_UI_Performance_Inventory.json"


def registered_operations() -> set[tuple[str, str]]:
    app = create_app(analyzer=create_local_poc_analyzer())
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    rows = inventory.get("operations")
    if not isinstance(rows, list):
        print("Inventory must contain an operations list.", file=sys.stderr)
        return 1

    registered_rows = [row for row in rows if row.get("registration") == "openapi_registered"]
    ui_url_rows = [row for row in rows if row.get("registration") == "ui_url_unregistered"]
    keys = [(row.get("method", "").upper(), row.get("route", "")) for row in registered_rows]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    invalid = [
        row
        for row in rows
        if row.get("classification") not in {"ui", "non_ui", "infrastructure"}
        or not row.get("caller")
        or not row.get("scenario")
        or row.get("registration") not in {"openapi_registered", "ui_url_unregistered"}
        or (
            row.get("classification") == "ui"
            and row.get("budget_key")
            != f"api:{row.get('method', '').upper()}:{row.get('route', '')}"
        )
    ]
    registered = registered_operations()
    listed = set(keys)
    missing = sorted(registered - listed)
    stale = sorted(listed - registered)
    if duplicates or invalid or missing or stale:
        for label, values in (
            ("Duplicate inventory operations", duplicates),
            ("Rows without a complete classification", invalid),
            ("Registered API operations missing from inventory", missing),
            ("Inventory operations absent from registration", stale),
        ):
            if values:
                print(f"{label}:", file=sys.stderr)
                for value in values:
                    print(f"  {value}", file=sys.stderr)
        return 1

    ui = sum(row["classification"] == "ui" for row in rows)
    ui_budget_keys = [row["budget_key"] for row in rows if row["classification"] == "ui"]
    if len(ui_budget_keys) != len(set(ui_budget_keys)):
        print("UI route budget keys must be unique.", file=sys.stderr)
        return 1
    print(
        f"PASS: {len(registered_rows)} registered API operations classified; "
        f"{len(ui_url_rows)} UI URL registration gap(s) documented; {ui} planned UI cases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
