import { describe, expect, it } from "vitest";

import type { PipelineVisibleCardResult } from "../api/client";
import {
  coverageEntries,
  frameCoverageKeyFromIdentity,
  frameDecision,
  readFramesFromResult,
} from "./PipelineVisibleCardData";
import type { EditableFrame, FrameIdentity } from "./PipelineVisibleCardTypes";

const identity: FrameIdentity = {
  requested_time_us: 100,
  frame_index: 2,
  presentation_timestamp_us: 90,
  width: 640,
  height: 480,
  image_sha256: "digest",
};

const acceptedEmptyFrame: EditableFrame = {
  itemId: "item-1",
  baseItemId: null,
  reviewState: "empty",
  outcome: {
    event_id: "event-1",
    frame_identity: identity,
    status: "empty",
    candidates: [],
    ignored_regions: [],
    error: null,
  },
};

describe("visible-card editor data helpers", () => {
  it("loads outcomes from the requested revision and skips invalid rows", () => {
    const result = {
      revisions: [
        {
          manifest: { revision_id: "requested" },
          content: {
            outcomes: [
              {
                event_id: "event-1",
                frame_identity: identity,
                status: "empty",
                candidates: [],
                ignored_regions: [],
              },
              { event_id: "invalid" },
            ],
          },
        },
        {
          manifest: { revision_id: "other" },
          content: { outcomes: [] },
        },
      ],
    } as unknown as PipelineVisibleCardResult;

    expect(readFramesFromResult(result, "requested")).toMatchObject([
      {
        itemId: "event-1",
        reviewState: "pending",
        outcome: { status: "empty", frame_identity: identity },
      },
    ]);
  });

  it("keeps accepted frame decisions and stable coverage keys", () => {
    expect(frameDecision(acceptedEmptyFrame)).toBe("empty");
    expect(frameCoverageKeyFromIdentity(identity, null)).toBe(
      frameCoverageKeyFromIdentity({ ...identity }, null),
    );
  });

  it("parses null-identity coverage and ignores malformed entries", () => {
    expect(
      coverageEntries({
        frames: [
          { frame_identity: null, item_id: "item-1" },
          { frame_identity: identity, item_id: 7 },
          { frame_identity: { width: "wide" }, item_id: "bad" },
          null,
        ],
      }),
    ).toEqual([
      { frame_identity: null, item_id: "item-1" },
      { frame_identity: identity, item_id: null },
    ]);
  });
});
