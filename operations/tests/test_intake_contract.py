from __future__ import annotations

import json
from pathlib import Path

import pytest

from doko_operations.intake_contract import (
    IntakeContractError,
    parse_evidence_package_bundle,
    parse_evidence_package_lineage,
    parse_evidence_package_record,
    parse_pending_video,
)

ROOT = Path(__file__).parents[2]
EVIDENCE = ROOT / "fixtures" / "repository-intake" / "v1" / "evidence-package-complete"
PENDING = ROOT / "fixtures" / "repository-intake" / "v1" / "pending-video"


def test_operations_decodes_pending_and_evidence_contracts() -> None:
    pending = parse_pending_video((PENDING / "manifest.json").read_bytes())
    bundle = parse_evidence_package_bundle((EVIDENCE / "manifest.json").read_bytes())
    record = parse_evidence_package_record((EVIDENCE / "package-record.json").read_bytes())
    lineage = parse_evidence_package_lineage((EVIDENCE / "lineage.json").read_bytes())

    assert pending.media_facts.container == "mp4"
    assert bundle.package_id == record.package_id == lineage.package_id
    assert bundle.source_asset_id == record.source_asset_id
    assert len(bundle.files.frames) == 6


def test_operations_contract_is_strict() -> None:
    payload = json.loads((EVIDENCE / "manifest.json").read_bytes())
    payload["legacy_path"] = "data/evidence"

    with pytest.raises(IntakeContractError):
        parse_evidence_package_bundle(json.dumps(payload).encode())
