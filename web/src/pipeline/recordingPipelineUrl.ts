import type { PipelineStageKey } from "../api/client";

export const PIPELINE_STAGE_KEYS: readonly PipelineStageKey[] = [
  "events",
  "visible_cards",
  "visual_identities",
  "table_observations",
  "round_analyses",
];

export type PipelineView = "generated" | "reviewed";

export type PipelineUrlState = {
  view: PipelineView | null;
  revision: string | null;
  item: string | null;
  tUs: number | null;
  left: string | null;
  right: string | null;
  reference: string | null;
  analysis: string | null;
};

export type RecordingPipelineRoute = {
  recordingId: string;
  stage: PipelineStageKey | null;
  compare: boolean;
};

export function isPipelineStageKey(value: string): value is PipelineStageKey {
  return PIPELINE_STAGE_KEYS.includes(value as PipelineStageKey);
}

export function readRecordingPipelineRoute(
  pathname: string,
): RecordingPipelineRoute | null {
  const match = pathname.match(
    /^\/recordings\/([^/]+)(?:\/pipeline(?:\/([^/]+)(?:\/(compare))?)?)?\/?$/,
  );
  if (match === null) {
    return null;
  }
  const recordingId = decodePathPart(match[1]);
  const rawStage = match[2];
  if (recordingId === null) {
    return null;
  }
  if (rawStage === undefined) {
    return { recordingId, stage: null, compare: false };
  }
  const stage = decodePathPart(rawStage);
  return {
    recordingId,
    stage: stage !== null && isPipelineStageKey(stage) ? stage : null,
    compare:
      match[3] === "compare" && stage !== null && isPipelineStageKey(stage),
  };
}

export function readPipelineUrlState(search: string): PipelineUrlState {
  const params = new URLSearchParams(search);
  const rawTime = params.get("t_us");
  return {
    view: readView(params.get("view")),
    revision: readOptionalParameter(params.get("revision")),
    item: readOptionalParameter(params.get("item")),
    tUs: rawTime !== null && /^-?\d+$/.test(rawTime) ? Number(rawTime) : null,
    left: readOptionalParameter(params.get("left")),
    right: readOptionalParameter(params.get("right")),
    reference: readOptionalParameter(params.get("reference")),
    analysis: readOptionalParameter(params.get("analysis")),
  };
}

export function recordingPipelinePath(
  recordingId: string,
  stage: PipelineStageKey,
  state: PipelineUrlState | Partial<PipelineUrlState> = {},
): string {
  return `${recordingPipelineBasePath(recordingId, stage)}${pipelineSearch(state, false)}`;
}

export function recordingPipelineComparePath(
  recordingId: string,
  stage: PipelineStageKey,
  state: PipelineUrlState | Partial<PipelineUrlState> = {},
): string {
  return `${recordingPipelineBasePath(recordingId, stage)}/compare${pipelineSearch(state, true)}`;
}

function pipelineSearch(
  state: PipelineUrlState | Partial<PipelineUrlState>,
  includeCompare: boolean,
): string {
  const params = new URLSearchParams();
  if (state.view !== null && state.view !== undefined)
    params.set("view", state.view);
  if (state.revision !== null && state.revision !== undefined)
    params.set("revision", state.revision);
  if (state.item !== null && state.item !== undefined)
    params.set("item", state.item);
  if (state.tUs !== null && state.tUs !== undefined)
    params.set("t_us", String(state.tUs));
  if (includeCompare) {
    if (state.left !== null && state.left !== undefined)
      params.set("left", state.left);
    if (state.right !== null && state.right !== undefined)
      params.set("right", state.right);
    if (state.reference !== null && state.reference !== undefined)
      params.set("reference", state.reference);
  }
  if (
    !includeCompare &&
    state.analysis !== null &&
    state.analysis !== undefined
  ) {
    params.set("analysis", state.analysis);
  }
  const query = params.toString();
  return query === "" ? "" : `?${query}`;
}

function recordingPipelineBasePath(
  recordingId: string,
  stage: PipelineStageKey,
): string {
  return `${recordingPagePath(recordingId)}/pipeline/${stage}`;
}

function recordingPagePath(recordingId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}`;
}

function readView(value: string | null): PipelineView | null {
  return value === "generated" || value === "reviewed" ? value : null;
}

function readOptionalParameter(value: string | null): string | null {
  return value === null || value === "" ? null : value;
}

function decodePathPart(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}
