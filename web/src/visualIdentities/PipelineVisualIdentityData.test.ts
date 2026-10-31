import { describe, expect, it } from "vitest";

import type {
  PipelineReferenceItem,
  PipelineVisualIdentityResult,
} from "../api/client";
import {
  canUseGeneratedProposal,
  readIdentityCoverage,
  readItemsFromResult,
  readStringList,
  toEditableIdentity,
} from "./PipelineVisualIdentityData";
import type { EditableIdentity } from "./PipelineVisualIdentityTypes";

const FRAME = {
  requested_time_us: 100,
  frame_index: 1,
  presentation_timestamp_us: 100,
  width: 640,
  height: 480,
  image_sha256: "a".repeat(64),
};
const GEOMETRY = { kind: "fixture", box: [1, 2, 3, 4] };

function outcome(overrides: Record<string, unknown> = {}) {
  return {
    card_id: "card-1",
    frame_identity: FRAME,
    geometry: GEOMETRY,
    crop_identity: {
      status: "usable",
      crop_policy: "raw_rectangular",
      output_encoding: "ppm",
      image_sha256: "b".repeat(64),
      unusable_reason: null,
    },
    crop_input_provenance: {
      input_kind: "reviewed_virtual_card",
      source_revision_id: "revision-1",
      manifest_digest: "c".repeat(64),
    },
    annotation_provenance: {
      visible_card_revision_id: "visible-revision-1",
      visible_card_revision_digest: "d".repeat(64),
      card_id: "visible-card-1",
      frame_identity: FRAME,
      geometry_digest: "e".repeat(64),
    },
    status: "classified",
    candidates: [{ identity: "CLUBS_NINE", score: 0.8 }],
    unusable_reason: null,
    error: null,
    ...overrides,
  };
}

function editable(overrides: Partial<EditableIdentity> = {}): EditableIdentity {
  return {
    itemId: "card-1",
    baseItemId: null,
    reviewState: "pending",
    outcome: outcome() as unknown as EditableIdentity["outcome"],
    ...overrides,
  };
}

describe("visual identity data conversion", () => {
  it("converts reference items and rejects invalid review states or outcomes", () => {
    const item: PipelineReferenceItem = {
      item_id: "item-1",
      base_item_id: "base-1",
      review_state: "corrected",
      item: outcome(),
    };

    expect(toEditableIdentity(item)).toMatchObject({
      itemId: "item-1",
      baseItemId: "base-1",
      reviewState: "corrected",
      outcome: { card_id: "card-1" },
    });
    expect(toEditableIdentity({ ...item, review_state: "unknown" })).toBeNull();
    expect(
      toEditableIdentity({ ...item, item: { card_id: "card-1" } }),
    ).toBeNull();
  });

  it("reads outcomes from the requested revision and falls back to the first revision", () => {
    const result = {
      revisions: [
        {
          manifest: { revision_id: "first" },
          content: { outcomes: [outcome()] },
        },
        {
          manifest: { revision_id: "selected" },
          content: { outcomes: [outcome({ card_id: "card-2" })] },
        },
      ],
    } as unknown as PipelineVisualIdentityResult;

    expect(
      readItemsFromResult(result, "selected").map((item) => item.itemId),
    ).toEqual(["card-2"]);
    expect(
      readItemsFromResult(result, "missing").map((item) => item.itemId),
    ).toEqual(["card-1"]);
    expect(
      readItemsFromResult(
        { revisions: [] } as unknown as PipelineVisualIdentityResult,
        "missing",
      ),
    ).toEqual([]);
  });

  it("keeps only string input revision ids and valid coverage entries", () => {
    expect(readStringList(["revision-1", 2, null, "revision-2"])).toEqual([
      "revision-1",
      "revision-2",
    ]);
    expect(readStringList({ ids: [] })).toEqual([]);
    expect(
      readIdentityCoverage({
        cards: [
          { card_id: "card-1", decision: "accepted" },
          { card_id: "card-2", decision: 3 },
          null,
        ],
      }),
    ).toEqual([{ card_id: "card-1", decision: "accepted" }]);
  });

  it("matches generated proposals only when frame, geometry, and usable crop agree", () => {
    const reviewed = editable();
    expect(canUseGeneratedProposal(reviewed, editable())).toBe(true);
    expect(
      canUseGeneratedProposal(
        reviewed,
        editable({
          outcome: outcome({
            geometry: { kind: "different" },
          }) as unknown as EditableIdentity["outcome"],
        }),
      ),
    ).toBe(false);
    expect(canUseGeneratedProposal(reviewed, undefined)).toBe(false);
  });
});
