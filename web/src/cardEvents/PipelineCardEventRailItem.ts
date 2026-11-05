import type { EventState } from "./PipelineEventData";

export type PipelineCardEventRailItem = {
  itemId: string;
  label: string;
  state: EventState;
  startUs: number;
  endUs: number;
};
