import type { PipelineReferenceOperation } from "../api/client";

export const CARD_STATE_CHANGED_EVENT_TYPE = "card_state_changed" as const;
export type PipelineCardEventType = typeof CARD_STATE_CHANGED_EVENT_TYPE;
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
  optimistic: (current: EditableEvent[]) => EditableEvent[];
  coalesceKey?: string;
};
