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
  status: "classified" | "unusable" | "failed";
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
};

export const CANONICAL_IDENTITIES = [
  "CLUBS_ACE",
  "CLUBS_NINE",
  "CLUBS_TEN",
  "CLUBS_JACK",
  "CLUBS_QUEEN",
  "CLUBS_KING",
  "DIAMONDS_ACE",
  "DIAMONDS_NINE",
  "DIAMONDS_TEN",
  "DIAMONDS_JACK",
  "DIAMONDS_QUEEN",
  "DIAMONDS_KING",
  "HEARTS_ACE",
  "HEARTS_NINE",
  "HEARTS_TEN",
  "HEARTS_JACK",
  "HEARTS_QUEEN",
  "HEARTS_KING",
  "SPADES_ACE",
  "SPADES_NINE",
  "SPADES_TEN",
  "SPADES_JACK",
  "SPADES_QUEEN",
  "SPADES_KING",
] as const;

export type PipelineVisualIdentityRailItem = {
  itemId: string;
  label: string;
  state: IdentityReviewState | IdentityOutcome["status"];
  timeUs: number;
  cropPolicy: string | null;
};
