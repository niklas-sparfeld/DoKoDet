import type {
  PipelineProposalRunResponse,
  PipelineReferenceItem,
  PipelineVisibleCardResult,
} from "../api/client";
import { readPoseScene } from "./PoseBasedVisibleCardScene";
import type {
  Candidate,
  EditableFrame,
  FrameIdentity,
  FrameReviewState,
  Geometry,
  IgnoreRegion,
  IgnoreRegionSourceCandidate,
  Outcome,
  Point,
} from "./PipelineVisibleCardTypes";
import { validatePolygons } from "./PipelineVisibleCardGeometry";

export function readProposalInputRevisionId(
  run: PipelineProposalRunResponse,
): string | null {
  const direct = run.request.visible_card_revision_id;
  if (typeof direct === "string") return direct;
  const inputs = run.request.input_revision_ids;
  return Array.isArray(inputs) && typeof inputs[0] === "string"
    ? inputs[0]
    : null;
}

export function readProposalRevisionId(
  run: PipelineProposalRunResponse,
): string | null {
  const outputRevisionIds = run.state.output_revision_ids;
  return Array.isArray(outputRevisionIds) &&
    typeof outputRevisionIds[0] === "string"
    ? outputRevisionIds[0]
    : null;
}

export function toEditableFrame(
  item: PipelineReferenceItem,
): EditableFrame | null {
  const outcome = readOutcome(item.item);
  if (outcome === null || !isFrameReviewState(item.review_state)) return null;
  return {
    itemId: item.item_id,
    baseItemId: item.base_item_id,
    reviewState: item.review_state,
    outcome,
  };
}

export function readFramesFromResult(
  result: PipelineVisibleCardResult,
  revisionId: string,
): EditableFrame[] {
  if (!Array.isArray(result.revisions)) return [];
  const revision =
    result.revisions.find(
      (candidate) => candidate.manifest.revision_id === revisionId,
    ) ?? result.revisions[0];
  const outcomes = revision?.content.outcomes;
  if (!Array.isArray(outcomes)) return [];
  const frames: Array<EditableFrame | null> = outcomes.map((item) => {
    const outcome = readOutcome(item);
    return outcome === null
      ? null
      : {
          itemId: outcome.event_id,
          baseItemId: null,
          reviewState: "pending" as const,
          outcome,
        };
  });
  return frames.filter((frame): frame is EditableFrame => frame !== null);
}

function readOutcome(value: Record<string, unknown>): Outcome | null {
  const eventId = value.event_id;
  const status = value.status;
  const rawFrame = value.frame_identity;
  const rawCandidates = value.candidates;
  const rawIgnoredRegions = value.ignored_regions;
  if (
    typeof eventId !== "string" ||
    !["detected", "empty", "failed"].includes(String(status)) ||
    !Array.isArray(rawCandidates) ||
    (rawIgnoredRegions !== undefined && !Array.isArray(rawIgnoredRegions))
  )
    return null;
  const frame = rawFrame === null ? null : readFrameIdentity(rawFrame);
  if (rawFrame !== null && frame === null) return null;
  const candidates = rawCandidates
    .map(readCandidate)
    .filter((candidate): candidate is Candidate => candidate !== null);
  const ignoredRegions = (rawIgnoredRegions ?? [])
    .map(readIgnoreRegion)
    .filter((region): region is IgnoreRegion => region !== null);
  const cardScene = readPoseScene(value.card_scene);
  return {
    event_id: eventId,
    frame_identity: frame,
    status: status as Outcome["status"],
    candidates,
    ignored_regions: ignoredRegions,
    ...(cardScene === null ? {} : { card_scene: cardScene }),
    error: typeof value.error === "string" ? value.error : null,
  };
}

function readFrameIdentity(value: unknown): FrameIdentity | null {
  if (
    !isRecord(value) ||
    !isInteger(value.requested_time_us) ||
    !isInteger(value.frame_index) ||
    !isInteger(value.presentation_timestamp_us) ||
    !isInteger(value.width) ||
    !isInteger(value.height)
  )
    return null;
  return value as FrameIdentity;
}

function readCandidate(value: unknown): Candidate | null {
  if (
    !isRecord(value) ||
    typeof value.card_id !== "string" ||
    !isVisibleCardSide(value.side) ||
    !isRecord(value.geometry) ||
    !isRecord(value.normalization)
  )
    return null;
  const geometry = readGeometry(value.geometry);
  if (geometry === null) return null;
  return {
    card_id: value.card_id,
    geometry,
    normalization: value.normalization,
    side: value.side,
    ...(Array.isArray(value.model_scores)
      ? { model_scores: value.model_scores.filter(isRecord) }
      : {}),
  };
}

function readIgnoreRegion(value: unknown): IgnoreRegion | null {
  if (!isRecord(value)) return null;
  const geometry = value.geometry;
  const normalization = value.normalization;
  const sourceCandidates = value.source_candidates;
  if (
    typeof value.region_id !== "string" ||
    value.reason !== "untidy_stack" ||
    !isRecord(geometry) ||
    geometry.kind !== "reviewed-ignore-region/v1" ||
    !Array.isArray(geometry.polygons) ||
    !isRecord(normalization) ||
    !isInteger(normalization.width) ||
    !isInteger(normalization.height) ||
    typeof normalization.policy_id !== "string" ||
    !Array.isArray(sourceCandidates)
  )
    return null;
  const polygons = geometry.polygons.map((polygon) => {
    if (
      !Array.isArray(polygon) ||
      polygon.some(
        (point) =>
          !isRecord(point) || !isInteger(point.x) || !isInteger(point.y),
      )
    )
      return null;
    return polygon as Point[];
  });
  if (
    polygons.some((polygon): polygon is null => polygon === null) ||
    validatePolygons(polygons as Point[][]) !== null
  )
    return null;
  const sources = sourceCandidates
    .filter(isRecord)
    .filter(
      (source): source is Record<string, unknown> =>
        typeof source.revision_id === "string" &&
        typeof source.card_id === "string",
    ) as IgnoreRegionSourceCandidate[];
  if (sources.length !== sourceCandidates.length) return null;
  return {
    region_id: value.region_id,
    geometry: {
      kind: "reviewed-ignore-region/v1",
      polygons: polygons as Point[][],
    },
    normalization: {
      width: normalization.width,
      height: normalization.height,
      policy_id: normalization.policy_id,
    },
    reason: "untidy_stack",
    source_candidates: sources,
  };
}

function isVisibleCardSide(value: unknown): value is Candidate["side"] {
  return value === "face_up" || value === "face_down" || value === "unknown";
}

function readGeometry(value: Record<string, unknown>): Geometry | null {
  const box = isRecord(value.box_2d) ? value.box_2d : null;
  const region = isRecord(value.visible_region) ? value.visible_region : null;
  const boxGeometry =
    box !== null &&
    ["x_min", "y_min", "x_max", "y_max"].every((key) => isInteger(box[key]))
      ? (box as Geometry["box_2d"])
      : undefined;
  if (region !== null && Array.isArray(region.polygons)) {
    const polygons = region.polygons
      .filter(Array.isArray)
      .map(
        (polygon) =>
          polygon
            .filter(isRecord)
            .filter(
              (point) => isInteger(point.x) && isInteger(point.y),
            ) as Point[],
      );
    if (
      polygons.length > 0 &&
      polygons.every((polygon) => polygon.length >= 3)
    ) {
      return {
        kind: String(value.kind),
        ...(boxGeometry === undefined ? {} : { box_2d: boxGeometry }),
        visible_region: { polygons },
      };
    }
  }
  if (value.kind === "detector-box/v1" && boxGeometry !== undefined)
    return {
      kind: String(value.kind),
      box_2d: boxGeometry,
    };
  return null;
}

export function frameCoverageKey(frame: EditableFrame): string {
  return frameCoverageKeyFromIdentity(
    frame.outcome.frame_identity,
    frame.itemId,
  );
}

export function frameCoverageKeyFromIdentity(
  identity: FrameIdentity | null,
  itemId: string | null,
): string {
  return identity === null
    ? `item:${itemId ?? "unknown"}`
    : JSON.stringify(identity, Object.keys(identity).sort());
}

export function coverageEntries(
  value: Record<string, unknown> | null,
): Array<{ frame_identity: FrameIdentity | null; item_id: string | null }> {
  if (!isRecord(value) || !Array.isArray(value.frames)) return [];
  return value.frames.flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const identity =
      entry.frame_identity === null
        ? null
        : readFrameIdentity(entry.frame_identity);
    return identity !== null || entry.frame_identity === null
      ? [
          {
            frame_identity: identity,
            item_id: typeof entry.item_id === "string" ? entry.item_id : null,
          },
        ]
      : [];
  });
}

export function frameDecision(
  frame: EditableFrame,
): "cards" | "ignored" | "cards_and_ignored" | "empty" | "unusable" | null {
  if (frame.outcome.status === "detected" && frame.reviewState === "accepted") {
    const hasCards = frame.outcome.candidates.length > 0;
    const hasIgnoredRegions = frame.outcome.ignored_regions.length > 0;
    const hasAcceptedScene =
      frame.outcome.card_scene?.completion_state === "complete" &&
      (frame.outcome.card_scene.scene.poses.length > 0 ||
        (frame.outcome.card_scene.card_review_states?.some(
          (state) => state.state === "accepted" || state.state === "adjusted",
        ) ??
          false));
    if ((hasCards || hasAcceptedScene) && hasIgnoredRegions)
      return "cards_and_ignored";
    if (hasCards || hasAcceptedScene) return "cards";
    if (hasIgnoredRegions) return "ignored";
  }
  if (frame.outcome.status === "empty" && frame.reviewState === "empty")
    return "empty";
  if (frame.outcome.status === "failed" && frame.reviewState === "unusable")
    return "unusable";
  return null;
}

export function nextManualCardId(frame: EditableFrame): string {
  return `manual-${frame.itemId}-${Date.now()}`;
}

export function nextManualRegionId(frame: EditableFrame): string {
  return `ignore-${frame.itemId}-${Date.now()}`;
}

export function copiedIgnoreRegionId(
  frame: EditableFrame,
  index: number,
): string {
  return `ignore-${frame.itemId}-copied-${index + 1}`;
}

export function newIgnoreRegion(
  frame: EditableFrame,
  regionId: string,
): IgnoreRegion {
  const identity = frame.outcome.frame_identity;
  return {
    region_id: regionId,
    geometry: {
      kind: "reviewed-ignore-region/v1",
      polygons: [],
    },
    normalization: {
      width: identity?.width ?? 1,
      height: identity?.height ?? 1,
      policy_id: "full-frame-0-1000/v1",
    },
    reason: "untidy_stack",
    source_candidates: [],
  };
}

export function ignoreRegionMapping(
  region: IgnoreRegion,
): Record<string, unknown> {
  return {
    region_id: region.region_id,
    geometry: {
      kind: region.geometry.kind,
      polygons: region.geometry.polygons.map((polygon) =>
        polygon.map((point) => ({ x: point.x, y: point.y })),
      ),
    },
    normalization: { ...region.normalization },
    reason: region.reason,
    source_candidates: region.source_candidates.map((source) => ({
      ...source,
    })),
  };
}

function isFrameReviewState(value: string): value is FrameReviewState {
  return [
    "pending",
    "accepted",
    "rejected",
    "added",
    "corrected",
    "empty",
    "unusable",
    "affected",
  ].includes(value);
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}
