import type { PipelineStageKey } from "../api/client";

export function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

export function formatPipelineStageState(
  stageKey: PipelineStageKey,
  state: string,
): string {
  switch (state) {
    case "video-only":
    case "empty":
      return "No processor output";
    case "active-run":
      return "Processor running";
    case "generated-only":
      return "Ready for review";
    case "draft":
      return "Review in progress";
    case "complete":
      return isHumanReviewStage(stageKey) ? "Reviewed" : "Complete";
    case "partial":
      return "Partial output";
    case "failed":
      return "Processor failed";
    case "affected":
      return "Review needs attention";
    case "incomplete-coverage":
      return "Review incomplete";
    default:
      return formatIdentifier(state);
  }
}

function isHumanReviewStage(stageKey: PipelineStageKey): boolean {
  return (
    stageKey === "events" ||
    stageKey === "visible_cards" ||
    stageKey === "visual_identities"
  );
}

export function formatDuration(durationUs: number): string {
  const totalSeconds = Math.floor(durationUs / 1_000_000);
  const minutes = Math.floor(totalSeconds / 60);
  return `${minutes}:${String(totalSeconds % 60).padStart(2, "0")}`;
}

export function formatByteLength(value: number): string {
  if (value < 1_000) return `${value} B`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(1)} kB`;
  if (value < 1_000_000_000) return `${(value / 1_000_000).toFixed(1)} MB`;
  return `${(value / 1_000_000_000).toFixed(1)} GB`;
}

export function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)}s`;
}
