import type {
  PipelineReferenceItem,
  PipelineVisualIdentityResult,
} from "../api/client";
import type {
  CropIdentity,
  EditableIdentity,
  FrameIdentity,
  IdentityCandidate,
  IdentityOutcome,
  IdentityReviewState,
} from "./PipelineVisualIdentityTypes";

export function toEditableIdentity(
  item: PipelineReferenceItem,
): EditableIdentity | null {
  const outcome = readOutcome(item.item);
  if (outcome === null || !isReviewState(item.review_state)) return null;
  return {
    itemId: item.item_id,
    baseItemId: item.base_item_id,
    reviewState: item.review_state,
    outcome,
  };
}

export function readItemsFromResult(
  result: PipelineVisualIdentityResult,
  revisionId: string,
): EditableIdentity[] {
  const revision =
    result.revisions.find(
      (candidate) => candidate.manifest.revision_id === revisionId,
    ) ?? result.revisions[0];
  const outcomes = revision?.content.outcomes;
  if (!Array.isArray(outcomes)) return [];
  const items: Array<EditableIdentity | null> = outcomes.map((item) => {
    const outcome = readOutcome(item);
    return outcome === null
      ? null
      : {
          itemId: outcome.card_id,
          baseItemId: null,
          reviewState: "pending" as const,
          outcome,
        };
  });
  return items.filter((item): item is EditableIdentity => item !== null);
}

export function canUseGeneratedProposal(
  reviewed: EditableIdentity,
  proposal: EditableIdentity | undefined,
): proposal is EditableIdentity {
  if (
    proposal === undefined ||
    proposal.itemId !== reviewed.itemId ||
    !sameJson(
      proposal.outcome.frame_identity,
      reviewed.outcome.frame_identity,
    ) ||
    !sameJson(proposal.outcome.geometry, reviewed.outcome.geometry)
  ) {
    return false;
  }
  const reviewedCrop = reviewed.outcome.crop_identity;
  const proposalCrop = proposal.outcome.crop_identity;
  if (
    reviewedCrop?.status !== "usable" ||
    proposalCrop?.status !== "usable" ||
    reviewedCrop.image_sha256 === null ||
    reviewedCrop.image_sha256 !== proposalCrop.image_sha256 ||
    reviewedCrop.crop_policy !== proposalCrop.crop_policy ||
    reviewedCrop.output_encoding !== proposalCrop.output_encoding
  ) {
    return false;
  }
  return (
    (proposal.outcome.status === "classified" &&
      proposal.outcome.candidates.length > 0) ||
    proposal.outcome.status === "face_down"
  );
}

export function readStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function readIdentityCoverage(
  value: unknown,
): Array<{ card_id: string; decision: string }> {
  if (!isRecord(value) || !Array.isArray(value.cards)) return [];
  return value.cards
    .filter(isRecord)
    .filter(
      (card) =>
        typeof card.card_id === "string" && typeof card.decision === "string",
    )
    .map((card) => ({
      card_id: String(card.card_id),
      decision: String(card.decision),
    }));
}

function sameJson(left: unknown, right: unknown): boolean {
  return stableJson(left) === stableJson(right);
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "undefined";
}

function readOutcome(value: unknown): IdentityOutcome | null {
  if (!isRecord(value)) return null;
  const cardId = value.card_id;
  const frame = readFrameIdentity(value.frame_identity);
  const geometry = isRecord(value.geometry) ? value.geometry : null;
  const status = value.status;
  if (
    typeof cardId !== "string" ||
    frame === null ||
    geometry === null ||
    !["classified", "face_down", "unusable", "failed"].includes(String(status))
  )
    return null;
  const candidates = Array.isArray(value.candidates)
    ? value.candidates
        .map(readCandidate)
        .filter(
          (candidate): candidate is IdentityCandidate => candidate !== null,
        )
    : [];
  const crop =
    value.crop_identity === null || value.crop_identity === undefined
      ? null
      : readCropIdentity(value.crop_identity);
  if (
    value.crop_identity !== null &&
    value.crop_identity !== undefined &&
    crop === null
  )
    return null;
  const provenance = readCropInputProvenance(value.crop_input_provenance);
  if (
    value.crop_input_provenance !== null &&
    value.crop_input_provenance !== undefined &&
    provenance === null
  )
    return null;
  const annotation = readAnnotationProvenance(value.annotation_provenance);
  if (
    value.annotation_provenance !== null &&
    value.annotation_provenance !== undefined &&
    annotation === null
  )
    return null;
  return {
    card_id: cardId,
    frame_identity: frame,
    geometry,
    crop_identity: crop,
    crop_input_provenance: provenance,
    annotation_provenance: annotation,
    status: status as IdentityOutcome["status"],
    candidates,
    unusable_reason:
      typeof value.unusable_reason === "string" ? value.unusable_reason : null,
    error: typeof value.error === "string" ? value.error : null,
  };
}

function readAnnotationProvenance(value: unknown) {
  if (value === null || value === undefined) return null;
  if (!isRecord(value)) return null;
  const frame = readFrameIdentity(value.frame_identity);
  if (
    typeof value.visible_card_revision_id !== "string" ||
    typeof value.visible_card_revision_digest !== "string" ||
    typeof value.card_id !== "string" ||
    typeof value.geometry_digest !== "string" ||
    frame === null
  )
    return null;
  return {
    visible_card_revision_id: value.visible_card_revision_id,
    visible_card_revision_digest: value.visible_card_revision_digest,
    card_id: value.card_id,
    frame_identity: frame,
    geometry_digest: value.geometry_digest,
  };
}

function readCropInputProvenance(value: unknown) {
  if (value === null || value === undefined) return null;
  if (
    !isRecord(value) ||
    ![
      "gemini_polygon",
      "rfdetr_segment",
      "reviewed_virtual_card",
      "reviewed_visible_card",
    ].includes(String(value.input_kind)) ||
    typeof value.source_revision_id !== "string" ||
    typeof value.manifest_digest !== "string"
  )
    return null;
  return {
    input_kind: value.input_kind as NonNullable<
      IdentityOutcome["crop_input_provenance"]
    >["input_kind"],
    source_revision_id: value.source_revision_id,
    manifest_digest: value.manifest_digest,
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

function readCropIdentity(value: unknown): CropIdentity | null {
  if (
    !isRecord(value) ||
    (value.status !== "usable" && value.status !== "unusable") ||
    typeof value.crop_policy !== "string" ||
    typeof value.output_encoding !== "string"
  )
    return null;
  return {
    ...(value as Record<string, unknown>),
    status: value.status,
    crop_policy: value.crop_policy,
    output_encoding: value.output_encoding,
    image_sha256:
      typeof value.image_sha256 === "string" ? value.image_sha256 : null,
    unusable_reason:
      typeof value.unusable_reason === "string" ? value.unusable_reason : null,
  } as CropIdentity;
}

function readCandidate(value: unknown): IdentityCandidate | null {
  if (!isRecord(value) || typeof value.identity !== "string") return null;
  return {
    identity: value.identity,
    score: typeof value.score === "number" ? value.score : null,
    score_meaning:
      typeof value.score_meaning === "string" ? value.score_meaning : null,
  };
}

function isReviewState(value: string): value is IdentityReviewState {
  return [
    "pending",
    "accepted",
    "added",
    "corrected",
    "face_down",
    "unusable",
    "identity_unusable",
    "source_problem",
    "affected",
  ].includes(value);
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
