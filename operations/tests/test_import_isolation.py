from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

UNRELATED_MODULES = (
    "doko_operations.cardevent_campaign",
    "doko_operations.pipeline_comparison",
    "doko_operations.round_reconstruction",
    "doko_operations.table_evidence_campaign",
)

REMOVED_BATCH_MODULES = (
    "doko_operations.visible_card_review_batch",
    "doko_operations.visual_card_identity_dataset",
    "doko_operations.visual_card_identity_review_batch",
)


def test_pipeline_data_import_does_not_load_unrelated_operations_modules() -> None:
    probe = f"""
import json
import sys

import doko_operations.pipeline_data

print(json.dumps({{name: name in sys.modules for name in {UNRELATED_MODULES!r}}}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    loaded = json.loads(result.stdout)
    assert all(not loaded[name] for name in UNRELATED_MODULES)


def test_removed_review_batch_modules_are_not_importable() -> None:
    probe = f"""
import importlib
import json

removed = {{}}
for name in {REMOVED_BATCH_MODULES!r}:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError:
        removed[name] = True
    else:
        removed[name] = False

print(json.dumps(removed))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    removed = json.loads(result.stdout)
    assert all(removed[name] for name in REMOVED_BATCH_MODULES)
