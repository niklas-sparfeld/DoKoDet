import type { PipelineReferenceOperation } from "../api/client";

export type FrameIdentity = {
  requested_time_us: number;
  frame_index: number;
  presentation_timestamp_us: number;
  width: number;
  height: number;
  image_sha256: string;
  [key: string]: unknown;
};

export type CropIdentity = {
  status: "usable" | "unusable";
  crop_policy: string;
  output_encoding: string;
  image_sha256: string | null;
  unusable_reason: string | null;
  [key: string]: unknown;
};

export type IdentityCandidate = {
  identity: string;
  score: number | null;
  score_meaning?: string | null;
};

export type IdentityOutcome = {
  card_id: string;
  frame_identity: FrameIdentity;
  geometry: Record<string, unknown>;
  crop_identity: CropIdentity | null;
  status: "classified" | "face_down" | "unusable" | "failed";
  candidates: IdentityCandidate[];
  unusable_reason: string | null;
  error: string | null;
};

export type IdentityReviewState =
  | "pending"
  | "accepted"
  | "added"
  | "corrected"
  | "unusable"
  | "identity_unusable"
  | "source_problem"
  | "affected";

export type IdentityReviewStatus = "unreviewed" | "accepted" | "unusable";

export type EditableIdentity = {
  itemId: string;
  baseItemId: string | null;
  reviewState: IdentityReviewState;
  outcome: IdentityOutcome;
};

export type SaveState = "saved" | "saving" | "retrying" | "error" | "conflict";

export type PendingCommand = {
  commandId: string;
  operation: PipelineReferenceOperation;
  notice: string;
  attempts: number;
  applyOptimistic: (current: EditableIdentity[]) => EditableIdentity[];
};

export const IDENTITY_SUIT_ROWS = [
  {
    suit: "clubs",
    cards: [
      ["CLUBS_JACK", "♣ Bube"],
      ["CLUBS_QUEEN", "♣ Dame"],
      ["CLUBS_KING", "♣ König"],
      ["CLUBS_TEN", "♣ 10"],
      ["CLUBS_ACE", "♣ Ass"],
    ],
  },
  {
    suit: "spades",
    cards: [
      ["SPADES_JACK", "♠ Bube"],
      ["SPADES_QUEEN", "♠ Dame"],
      ["SPADES_KING", "♠ König"],
      ["SPADES_TEN", "♠ 10"],
      ["SPADES_ACE", "♠ Ass"],
    ],
  },
  {
    suit: "hearts",
    cards: [
      ["HEARTS_JACK", "♥ Bube"],
      ["HEARTS_QUEEN", "♥ Dame"],
      ["HEARTS_KING", "♥ König"],
      ["HEARTS_TEN", "♥ 10"],
      ["HEARTS_ACE", "♥ Ass"],
    ],
  },
  {
    suit: "diamonds",
    cards: [
      ["DIAMONDS_JACK", "♦ Bube"],
      ["DIAMONDS_QUEEN", "♦ Dame"],
      ["DIAMONDS_KING", "♦ König"],
      ["DIAMONDS_TEN", "♦ 10"],
      ["DIAMONDS_ACE", "♦ Ass"],
    ],
  },
] as const;

export type PipelineVisualIdentityRailItem = {
  itemId: string;
  label: string;
  state: IdentityReviewStatus | IdentityOutcome["status"];
  timeUs: number;
  cropPolicy: string | null;
};
