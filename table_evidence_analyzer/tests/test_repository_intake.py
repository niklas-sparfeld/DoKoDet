from __future__ import annotations

import json
from pathlib import Path

import pytest

from table_evidence_analyzer import (
    parse_evidence_package_bundle,
    parse_evidence_package_lineage,
    parse_evidence_package_record,
    parse_pending_video,
)

ROOT = Path(__file__).parents[2]
EVIDENCE = ROOT / "fixtures" / "repository-intake" / "v1" / "evidence-package-complete"
PENDING = ROOT / "fixtures" / "repository-intake" / "v1" / "pending-video"


def test_analyzer_decodes_shared_intake_contracts() -> None:
    pending = parse_pending_video((PENDING / "manifest.json").read_bytes())
    bundle = parse_evidence_package_bundle((EVIDENCE / "manifest.json").read_bytes())
    record = parse_evidence_package_record((EVIDENCE / "package-record.json").read_bytes())
    lineage = parse_evidence_package_lineage((EVIDENCE / "lineage.json").read_bytes())

    assert pending.state == "pending"
    assert bundle.state == "complete"
    assert bundle.package_id == record.package_id == lineage.package_id


def test_analyzer_rejects_unknown_bundle_fields() -> None:
    payload = json.loads((EVIDENCE / "manifest.json").read_bytes())
    payload["recording_id"] = "legacy-recording"
    with pytest.raises(ValueError):
        parse_evidence_package_bundle(json.dumps(payload).encode())
