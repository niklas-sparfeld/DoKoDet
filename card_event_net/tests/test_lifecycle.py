from __future__ import annotations

from pathlib import Path

import pytest

from cardevent.lifecycle import (
    LifecycleReceipt,
    LifecycleReceiptError,
    load_lifecycle_receipt,
    save_lifecycle_receipt,
)


def test_lifecycle_receipt_round_trip_has_stable_digest(tmp_path: Path) -> None:
    receipt = LifecycleReceipt(
        receipt_id="receipt-001",
        receipt_type="source_import",
        operator="tester",
        occurred_at="2026-08-27T12:00:00Z",
        inputs=({"kind": "source_asset", "id": "source-001", "digest": "a" * 64},),
        outputs=({"kind": "ingestion_index", "id": "index-001", "digest": "b" * 64},),
        metadata={"source_count": 1},
    )
    path = save_lifecycle_receipt(receipt, tmp_path / "receipt.json")

    restored = load_lifecycle_receipt(path)

    assert restored == receipt
    assert restored.to_mapping()["receipt_digest"] == receipt.digest


def test_lifecycle_receipt_rejects_changed_digest() -> None:
    receipt = LifecycleReceipt(
        receipt_id="receipt-001",
        receipt_type="source_import",
        operator="tester",
        occurred_at="2026-08-27T12:00:00Z",
        outputs=({"kind": "ingestion_index", "id": "index-001"},),
    )
    payload = receipt.to_mapping()
    payload["metadata"] = {"changed": True}

    with pytest.raises(LifecycleReceiptError, match="receipt_digest"):
        LifecycleReceipt.from_mapping(payload)
