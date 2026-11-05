import type { PipelineCardEventRailItem } from "../cardEvents/PipelineCardEventRailItem";
import { buildEventRailItems } from "./RecordingWorkspaceRail";

describe("recording workspace event rail", () => {
  it("shows exact event positions and recording coverage", () => {
    const items = [
      {
        itemId: "event-1",
        label: "Card-state change",
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
        label: "Card-state change · accepted",
      },
      {
        id: "events:coverage",
        laneId: "coverage",
        timeRange: { startUs: 0, endUs: 90_000_000 },
      },
    ]);
  });
});
