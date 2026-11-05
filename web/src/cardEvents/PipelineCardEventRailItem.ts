import type { EventState } from "./PipelineCardEventTypes";

export type PipelineCardEventRailItem = {
  itemId: string;
  label: string;
  state: EventState;
  startUs: number;
  endUs: number;
};
