import type { PipelineReferenceOperation } from "../api/client";
import type { PoseSceneEnvelope } from "./PoseBasedVisibleCardScene";

export type Point = { x: number; y: number };

export type FrameIdentity = {
  requested_time_us: number;
  frame_index: number;
  presentation_timestamp_us: number;
  width: number;
  height: number;
  image_sha256: string;
  [key: string]: unknown;
};

export type Geometry = {
  kind: string;
  box_2d?: { x_min: number; y_min: number; x_max: number; y_max: number };
  visible_region?: { polygons: Point[][] };
};

export type VisibleCardSide = "face_up" | "face_down" | "unknown";

export type Candidate = {
  card_id: string;
  geometry: Geometry;
  normalization: Record<string, unknown>;
  side: VisibleCardSide;
  model_scores?: Array<Record<string, unknown>>;
};

export type IgnoreRegionSourceCandidate = {
  revision_id: string;
  card_id: string;
};

export type IgnoreRegion = {
  region_id: string;
  geometry: {
    kind: "reviewed-ignore-region/v1";
    polygons: Point[][];
  };
  normalization: {
    width: number;
    height: number;
    policy_id: string;
  };
  reason: "untidy_stack";
  source_candidates: IgnoreRegionSourceCandidate[];
};

export type Outcome = {
  event_id: string;
  frame_identity: FrameIdentity | null;
  status: "detected" | "empty" | "failed";
  candidates: Candidate[];
  ignored_regions: IgnoreRegion[];
  card_scene?: PoseSceneEnvelope;
  error: string | null;
};

export type FrameReviewState =
  | "pending"
  | "accepted"
  | "rejected"
  | "added"
  | "corrected"
  | "empty"
  | "unusable"
  | "affected";

export type FrameReviewStatus =
  "unreviewed" | "accepted" | "empty" | "unusable";

export type EditableFrame = {
  itemId: string;
  baseItemId: string | null;
  reviewState: FrameReviewState;
  outcome: Outcome;
};

export type SaveState = "saved" | "saving" | "retrying" | "error" | "conflict";

export type PendingCommand = {
  commandId: string;
  operations: PipelineReferenceOperation[];
  notice: string;
  attempts: number;
};

export type EditorState = {
  frameItemId: string;
  cardId: string | null;
  regionId: string | null;
  ignoreRegion: IgnoreRegion | null;
  polygons: Point[][];
  polygonIndex: number;
  selectedPointIndex: number | null;
};

export type PipelineVisibleCardRailItem = {
  itemId: string;
  label: string;
  state: FrameReviewStatus | Outcome["status"];
  timeUs: number | null;
  proposalCount: number;
  ignoredRegionCount?: number;
  decision:
    "cards" | "ignored" | "cards_and_ignored" | "empty" | "unusable" | null;
};
