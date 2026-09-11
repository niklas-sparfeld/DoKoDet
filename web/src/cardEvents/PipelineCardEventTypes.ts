import type { PipelineReferenceOperation } from "../api/client";

export const PIPELINE_CARD_EVENT_TYPES = [
  "card_state_changed",
  "card_played",
  "trick_cleared",
  "card_moved",
  "card_removed",
  "card_returned",
  "multiple_cards_dropped",
  "anomalous_state_change",
] as const;

export type PipelineCardEventType = (typeof PIPELINE_CARD_EVENT_TYPES)[number];
export type EventState =
  "pending" | "accepted" | "rejected" | "added" | "corrected" | "affected";

export type PipelineEvent = {
  event_id: string;
  event_type: PipelineCardEventType;
  start_us: number;
  end_us: number;
  model_scores?: Array<Record<string, unknown>>;
};

export type EditableEvent = {
  localId: string;
  itemId: string;
  baseItemId: string | null;
  reviewState: EventState;
  event: PipelineEvent;
};

export type SaveState = "saved" | "saving" | "retrying" | "error" | "conflict";

export type PendingCommand = {
  commandId: string;
  operation: PipelineReferenceOperation;
  notice: string;
  attempts: number;
};
