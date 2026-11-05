"""Conservative transfer of identity decisions across explicit processor refreshes."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from table_evidence_analyzer.cards import CARD_IDENTITIES

from dokodetector_backend.pipeline_item_provenance import _resolve
from dokodetector_backend.pipeline_node_reviews import PipelineNodeReviews
from dokodetector_backend.pipeline_node_store import NodeRevision, PipelineNodeStore

IDENTITY_QUESTION = "visual-card-identity/v1"


def crop_evidence(outcome: dict[str, Any]) -> dict[str, Any] | None:
    """Identify exact crop bytes and the complete crop production policy."""
    crop = outcome.get("crop_identity")
    if not isinstance(crop, dict) or crop.get("status") != "usable" or not crop.get("image_sha256"):
        return None
    return {
        "crop_sha256": crop["image_sha256"],
        "policy": {
            key: crop[key]
            for key in (
                "crop_policy",
                "output_encoding",
                "content_type",
                "decoder_version",
                "transform_version",
            )
        },
    }


class IdentityReviewRefresh:
    """Resolve retained human classifications without modifying processor output.

    Correspondences are explicit pairs of item IDs scoped to the two exact revisions. They are
    supplied by a caller that has established correspondence; IDs or matching labels alone are not
    evidence of correspondence. Results are overlays, not new review records or content revisions.
    """

    def __init__(self, store: PipelineNodeStore) -> None:
        self.store = store
        self.reviews = PipelineNodeReviews(store)

    def refresh(
        self,
        source_node: str,
        source_revision: str,
        target_node: str,
        target_revision: str,
        correspondences: Sequence[tuple[str, str]],
        review_ids: Sequence[str],
    ) -> dict[str, dict[str, Any]]:
        source = self._identity_revision(source_node, source_revision)
        target = self._identity_revision(target_node, target_revision)
        source_items = self._outcome_items(source)
        target_items = self._outcome_items(target)
        pairs = list(correspondences)
        if any(not isinstance(pair, (list, tuple)) or len(pair) != 2 for pair in pairs):
            raise ValueError("correspondence must contain item ID pairs")
        if any(a not in source_items or b not in target_items for a, b in pairs):
            raise ValueError("correspondence references an absent item")
        source_counts = Counter(a for a, _ in pairs)
        target_counts = Counter(b for _, b in pairs)
        decisions: dict[str, list[dict[str, Any]]] = {}
        for review_id in set(review_ids):
            review = self.reviews.get(review_id)
            if (review["node_id"], review["revision_id"]) != (source_node, source_revision):
                raise ValueError("review does not refer to the source revision")
            if review["kind"] != "item" or review["question"] != IDENTITY_QUESTION:
                raise ValueError("review is not a visual identity decision")
            if review["reviewer"]["kind"] != "human":
                raise ValueError("identity decision must be human")
            if review["decision"] not in {*CARD_IDENTITIES, "FACE_DOWN"}:
                raise ValueError("invalid reviewed visual identity")
            item = source_items.get(review["item_id"])
            if (
                item is None
                or item["sha256"] != review["item_sha256"]
                or source.content_sha256 != review["content_sha256"]
            ):
                raise ValueError("review does not match source content")
            decisions.setdefault(review["item_id"], []).append(review)

        result = {key: {"status": "unknown", "reason": "no correspondence"} for key in target_items}
        for old_id, new_id in pairs:
            if source_counts[old_id] != 1 or target_counts[new_id] != 1:
                result[new_id] = {"status": "unknown", "reason": "ambiguous correspondence"}
                continue
            records = decisions.get(old_id, [])
            if len(records) != 1:
                result[new_id] = {
                    "status": "unknown",
                    "reason": "missing or ambiguous decision",
                }
                continue
            record = records[0]
            old = _resolve(source.content, source_items[old_id]["pointer"])
            new = _resolve(target.content, target_items[new_id]["pointer"])
            old_evidence = crop_evidence(old)
            new_evidence = crop_evidence(new)
            if old_evidence is None or new_evidence is None:
                result[new_id] = {
                    "status": "unknown",
                    "reason": "crop evidence is missing",
                    "review_id": record["review_id"],
                }
                continue
            if record["evidence"] != old_evidence or old_evidence != new_evidence:
                result[new_id] = {
                    "status": "inapplicable",
                    "reason": "crop evidence or policy changed",
                    "review_id": record["review_id"],
                }
                continue
            result[new_id] = {
                "status": "applicable",
                "decision": record["decision"],
                "review_id": record["review_id"],
            }
        return result

    def _identity_revision(self, node_id: str, revision_id: str) -> NodeRevision:
        if self.store.get(node_id).content_type != "visual_identities":
            raise ValueError("identity refresh requires visual identity nodes")
        return self.store.read_revision(node_id, revision_id)

    def _outcome_items(self, revision: NodeRevision) -> dict[str, Any]:
        items = self.reviews._revision_items(revision)
        expected = {f"/outcomes/{index}" for index in range(len(revision.content["outcomes"]))}
        if {item["pointer"] for item in items.values()} != expected:
            raise ValueError("item provenance must cover each identity outcome")
        return items
