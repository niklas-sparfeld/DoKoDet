export const CARD_STATE_CHANGED_EVENT_TYPE = "card_state_changed" as const;

export type EventState =
  "pending" | "accepted" | "rejected" | "added" | "corrected" | "affected";
