import type { PipelineCardEventRailItem } from "../cardEvents/PipelineCardEventEditor";
import type { PipelineVisibleCardRailItem } from "../visibleCards/PipelineVisibleCardEditor";
import type { PipelineVisualIdentityRailItem } from "../visualIdentities/PipelineVisualIdentityEditor";
import {
  buildEventRailItems,
  buildVisibleCardRailItems,
  buildVisualIdentityRailItems,
} from "./RecordingWorkspaceRail";

describe("recording workspace rail coordination", () => {
  it("adds event review lanes and full-recording coverage", () => {
    const items = [
      {
        itemId: "event-1",
        label: "card_played",
        state: "accepted",
        startUs: 2_000_000,
        endUs: 3_000_000,
      },
    ] satisfies PipelineCardEventRailItem[];

    expect(buildEventRailItems(items, 90_000_000)).toMatchObject([
      {
        id: "event:event-1",
        laneId: "events",
        timeRange: { startUs: 2_000_000, endUs: 3_000_000 },
      },
      {
        id: "event:event-1:state",
        laneId: "review-state",
        label: "card_played · accepted",
      },
      {
        id: "events:coverage",
        laneId: "coverage",
        timeRange: { startUs: 0, endUs: 90_000_000 },
      },
    ]);
  });

  it("maps visible-card decisions and proposals to one frame time", () => {
    const items = [
      {
        itemId: "frame-1",
        label: "Frame 1",
        state: "detected",
        timeUs: 4_000_000,
        proposalCount: 2,
        decision: "cards",
      },
    ] satisfies PipelineVisibleCardRailItem[];

    expect(buildVisibleCardRailItems(items, 4_000_000)).toMatchObject([
      {
        id: "visible-card:frame-1",
        laneId: "resolved-frames",
        timeRange: { startUs: 4_000_000, endUs: 4_000_000 },
      },
      {
        id: "visible-card:frame-1:decision",
        laneId: "frame-decision",
        state: "cards",
      },
      {
        id: "visible-card:frame-1:proposals",
        laneId: "proposals",
        label: "Frame 1 · 2 proposals",
      },
    ]);
  });

  it("maps visual identity review and outcome lanes", () => {
    const items = [
      {
        itemId: "identity-1",
        label: "HEARTS_QUEEN",
        state: "classified",
        timeUs: 5_000_000,
        cropPolicy: "visible-region/v1",
      },
    ] satisfies PipelineVisualIdentityRailItem[];

    expect(buildVisualIdentityRailItems(items, 90_000_000)).toMatchObject([
      {
        id: "identity:identity-1",
        laneId: "identity-cards",
        timeRange: { startUs: 5_000_000, endUs: 5_000_001 },
      },
      {
        id: "identity:identity-1:review",
        laneId: "review-state",
        label: "HEARTS_QUEEN · classified",
      },
    ]);
  });
});
