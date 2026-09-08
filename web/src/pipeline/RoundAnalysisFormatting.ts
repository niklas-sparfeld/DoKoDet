import type { RoundAnalysisCreateRequest } from "../api/client";

export const TERMINAL_ANALYSIS_STATES = new Set(["complete", "failed"]);
export const DEFAULT_PLAYERS = "seat-1, seat-2, seat-3, seat-4";

export function analysisStatusMessage(status: string): string {
  return status === "complete"
    ? "Round reconstruction completed."
    : status === "failed"
      ? "Round reconstruction failed."
      : status === "queued"
        ? "Round reconstruction is queued."
        : "Round reconstruction is running.";
}

export function parseSearchLimits(
  missing: string,
  hypotheses: string,
  nodes: string,
): RoundAnalysisCreateRequest["search"] | null {
  const maxMissingPlays = Number(missing);
  const maxHypotheses = Number(hypotheses);
  const maxSearchNodes = Number(nodes);
  if (
    !Number.isInteger(maxMissingPlays) ||
    maxMissingPlays < 0 ||
    !Number.isInteger(maxHypotheses) ||
    maxHypotheses <= 0 ||
    !Number.isInteger(maxSearchNodes) ||
    maxSearchNodes <= 0
  ) {
    return null;
  }
  return {
    max_missing_plays: maxMissingPlays,
    max_hypotheses: maxHypotheses,
    max_search_nodes: maxSearchNodes,
  };
}

export function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
}

export function createUuid(): string {
  return typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-0000-4000-8000-${Math.random().toString(16).slice(2, 14)}`;
}
