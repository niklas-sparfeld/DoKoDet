import type {
  PipelineStageKey,
  PipelineWorkspace,
  PipelineWorkspaceStage,
} from "../api/client";
import { CARD_STATE_CHANGED_EVENT_TYPE } from "../cardEvents/PipelineCardEventTypes";
import type { PipelineUrlState, PipelineView } from "./recordingPipelineUrl";

export {
  PIPELINE_STAGE_KEYS,
  isPipelineStageKey,
} from "./recordingPipelineUrl";
export type { PipelineUrlState, PipelineView } from "./recordingPipelineUrl";

export const STAGE_LABELS: Record<PipelineStageKey, string> = {
  events: "Events",
  visible_cards: "Visible cards",
  visual_identities: "Visual identities",
  table_observations: "Table observations",
  round_analyses: "Round analyses",
};

export type PipelinePrimaryActionKind =
  | "continue_review"
  | "run"
  | "review"
  | "compare"
  | "open_analysis"
  | "run_again"
  | "blocked";

export type PipelinePrimaryAction = {
  kind: PipelinePrimaryActionKind;
  label: string;
  blocker: string | null;
};

export function primaryActionForStage(
  stage: PipelineWorkspaceStage,
): PipelinePrimaryAction {
  const reference = stage.reference ?? null;
  if (
    stage.has_maintained_reference &&
    (reference?.state === "draft" || (reference?.affected_count ?? 0) > 0)
  ) {
    return { kind: "continue_review", label: "Continue review", blocker: null };
  }
  if (stage.selected_generated_revision_id === null && stage.can_run) {
    return { kind: "run", label: "Run", blocker: null };
  }
  if (
    stage.selected_generated_revision_id !== null &&
    stage.selected_completed_reference_revision_id === null &&
    stage.can_review
  ) {
    return { kind: "review", label: "Review", blocker: null };
  }
  if (
    stage.selected_completed_reference_revision_id !== null &&
    stage.comparable_run_ids.length >= 2
  ) {
    return { kind: "compare", label: "Compare", blocker: null };
  }
  if (
    stage.key === "round_analyses" &&
    stage.analyses.some((analysis) => analysis.state === "complete")
  ) {
    return { kind: "open_analysis", label: "Open analysis", blocker: null };
  }
  if (stage.can_run) {
    return { kind: "run_again", label: "Run again", blocker: null };
  }
  return {
    kind: "blocked",
    label: "Blocked",
    blocker:
      stage.run_blockers[0] ??
      stage.review_blockers[0] ??
      "No action is available.",
  };
}

export const getPrimaryAction = primaryActionForStage;

export type WorkspacePresentationState =
  "loading" | "failed" | PipelineWorkspaceStage["state"];

export type TaskSurfaceMode =
  | "video"
  | "source-frame"
  | "identity-crop"
  | "observation"
  | "analysis"
  | "comparison";

export type InspectorSectionKey =
  "progress" | "action" | "save-state" | "selection" | "metadata" | "details";

export type InspectorSection = {
  key: InspectorSectionKey;
  label: string;
  collapsed: boolean;
};

export type ProgressPresentation = {
  completed: number | null;
  total: number | null;
  percent: number | null;
  label: string;
};

export type RailTimeRange = {
  startUs: number;
  endUs: number;
};

export type RecordingTimelineRailItem = {
  id: string;
  itemId: string;
  selectionParam: "item" | "analysis" | "none";
  laneId: string;
  label: string;
  state: string;
  timeRange: RailTimeRange | null;
  runId: string | null;
};

export type RecordingTimelineRailLane = {
  id: string;
  label: string;
  itemCount: number;
  state: string;
};

export type WorkspaceSelection = {
  view: PipelineView;
  revisionId: string | null;
  itemId: string | null;
  timeUs: number | null;
  analysisId: string | null;
};

export type RecordingWorkspacePresentation = {
  state: WorkspacePresentationState;
  error: string | null;
  recording: {
    recordingId: string;
    durationUs: number;
    relativeVideoPath: string;
    videoSha256: string;
    byteLength: number;
  } | null;
  topBar: {
    recordingLabel: string;
    durationUs: number;
    stageTabs: Array<{
      key: PipelineStageKey;
      label: string;
      state: PipelineWorkspaceStage["state"];
      active: boolean;
    }>;
    view: PipelineView | null;
  };
  stage: {
    key: PipelineStageKey;
    label: string;
    state: PipelineWorkspaceStage["state"];
    viewOptions: Array<{
      value: PipelineView;
      enabled: boolean;
      active: boolean;
    }>;
    displayedRevisionId: string | null;
  } | null;
  surface: {
    mode: TaskSurfaceMode;
    selectedItemId: string | null;
    selectedRevisionId: string | null;
  };
  inspector: {
    sections: InspectorSection[];
    progress: ProgressPresentation;
    primaryAction: PipelinePrimaryAction | null;
    activeBlocker: string | null;
    saveState: "idle" | "draft" | "affected" | "failed" | "complete";
    selection: WorkspaceSelection | null;
  };
  rail: {
    durationUs: number;
    currentTimeUs: number | null;
    selectedItemId: string | null;
    lanes: RecordingTimelineRailLane[];
    items: RecordingTimelineRailItem[];
  } | null;
  diagnostics: PipelineWorkspace["diagnostics"];
};

type RawItem = Record<string, unknown>;
type PipelineRun = PipelineWorkspaceStage["runs"][number];

const EMPTY_URL_STATE: PipelineUrlState = {
  view: null,
  revision: null,
  item: null,
  tUs: null,
  left: null,
  right: null,
  reference: null,
  analysis: null,
};

const RAIL_LANES: Record<
  PipelineStageKey,
  Array<{ id: string; label: string }>
> = {
  events: [
    { id: "events", label: "Events" },
    { id: "proposals", label: "Proposals" },
    { id: "review-state", label: "Review state" },
    { id: "coverage", label: "Coverage" },
  ],
  visible_cards: [
    { id: "resolved-frames", label: "Resolved frames" },
    { id: "frame-decision", label: "Frame decision" },
    { id: "proposals", label: "Proposals" },
    { id: "ignore-regions", label: "Ignore regions" },
  ],
  visual_identities: [
    { id: "identity-cards", label: "Identity cards" },
    { id: "review-state", label: "Review state" },
  ],
  table_observations: [
    { id: "observation-intervals", label: "Observation intervals" },
    { id: "execution", label: "Execution" },
  ],
  round_analyses: [
    { id: "analysis-evidence", label: "Analysis evidence" },
    { id: "reconstruction", label: "Reconstruction" },
  ],
};

export function buildRecordingWorkspacePresentation({
  workspace,
  stageKey = null,
  compare = false,
  urlState,
  loading = false,
  error = null,
}: {
  workspace: PipelineWorkspace | null;
  stageKey?: PipelineStageKey | null;
  compare?: boolean;
  urlState?: Partial<PipelineUrlState>;
  loading?: boolean;
  error?: string | null;
}): RecordingWorkspacePresentation {
  if (workspace === null) {
    return emptyPresentation(loading ? "loading" : "failed", error);
  }

  const stage =
    (stageKey === null
      ? workspace.stages[0]
      : workspace.stages.find((candidate) => candidate.key === stageKey)) ??
    null;
  if (stage === null) {
    return emptyPresentation(
      "failed",
      error ?? "The pipeline stage is unavailable.",
    );
  }

  const selection = normalizeSelection(stage, workspace.video.duration_us, {
    ...EMPTY_URL_STATE,
    ...urlState,
  });
  const displayedRevisionId = selection.revisionId;
  const action = primaryActionForStage(stage);
  const rail = buildRail(
    stage,
    workspace.video.duration_us,
    selection,
    compare,
  );
  const matchedRun = findRunForRevision(stage, displayedRevisionId);
  const selectedAnalysis =
    selection.analysisId === null
      ? null
      : (stage.analyses.find(
          (candidate) => candidate.analysis_id === selection.analysisId,
        ) ?? null);
  const progress = progressForStage(stage, matchedRun, selectedAnalysis);
  const activeBlocker =
    error ?? action.blocker ?? failureMessage(stage) ?? null;

  return {
    state: stage.state,
    error,
    recording: {
      recordingId: workspace.recording_id,
      durationUs: workspace.video.duration_us,
      relativeVideoPath: workspace.video.relative_path,
      videoSha256: workspace.video.video_sha256,
      byteLength: workspace.video.byte_length,
    },
    topBar: {
      recordingLabel: workspace.recording_id,
      durationUs: workspace.video.duration_us,
      stageTabs: workspace.stages.map((candidate) => ({
        key: candidate.key,
        label: STAGE_LABELS[candidate.key],
        state: candidate.state,
        active: candidate.key === stage.key,
      })),
      view: selection.view,
    },
    stage: {
      key: stage.key,
      label: STAGE_LABELS[stage.key],
      state: stage.state,
      viewOptions: [
        {
          value: "generated",
          enabled: true,
          active: selection.view === "generated",
        },
        {
          value: "reviewed",
          enabled: stage.has_maintained_reference,
          active: selection.view === "reviewed",
        },
      ],
      displayedRevisionId,
    },
    surface: {
      mode: taskSurfaceMode(stage.key, compare),
      selectedItemId: selection.itemId,
      selectedRevisionId: displayedRevisionId,
    },
    inspector: {
      sections: inspectorSections(),
      progress,
      primaryAction: action,
      activeBlocker,
      saveState: saveStateForStage(stage),
      selection,
    },
    rail,
    diagnostics: workspace.diagnostics,
  };
}

function emptyPresentation(
  state: "loading" | "failed",
  error: string | null,
): RecordingWorkspacePresentation {
  return {
    state,
    error,
    recording: null,
    topBar: {
      recordingLabel: "",
      durationUs: 0,
      stageTabs: [],
      view: null,
    },
    stage: null,
    surface: {
      mode: "video",
      selectedItemId: null,
      selectedRevisionId: null,
    },
    inspector: {
      sections: [],
      progress: {
        completed: null,
        total: null,
        percent: null,
        label: "Unavailable",
      },
      primaryAction: null,
      activeBlocker: error,
      saveState: state === "failed" ? "failed" : "idle",
      selection: null,
    },
    rail: null,
    diagnostics: [],
  };
}

function inspectorSections(): InspectorSection[] {
  return [
    { key: "progress", label: "Progress", collapsed: false },
    { key: "action", label: "Primary action", collapsed: false },
    { key: "save-state", label: "Save state", collapsed: false },
    { key: "selection", label: "Current selection", collapsed: false },
    { key: "metadata", label: "Recording metadata", collapsed: false },
    { key: "details", label: "Lineage and history", collapsed: true },
  ];
}

function taskSurfaceMode(
  stage: PipelineStageKey,
  compare: boolean,
): TaskSurfaceMode {
  if (compare) return "comparison";
  switch (stage) {
    case "events":
      return "video";
    case "visible_cards":
      return "source-frame";
    case "visual_identities":
      return "identity-crop";
    case "table_observations":
      return "observation";
    case "round_analyses":
      return "analysis";
  }
}

function normalizeSelection(
  stage: PipelineWorkspaceStage,
  durationUs: number,
  urlState: PipelineUrlState,
): WorkspaceSelection {
  const defaultView = defaultViewForStage(stage);
  const view =
    urlState.view === "reviewed" && stage.has_maintained_reference
      ? "reviewed"
      : urlState.view === "generated"
        ? "generated"
        : defaultView;
  const validRevisionIds = new Set(
    stage.input_options.map((option) => option.revision_id),
  );
  const defaultRevisionId =
    view === "generated"
      ? stage.selected_generated_revision_id
      : stage.selected_completed_reference_revision_id;
  const revisionId =
    urlState.revision !== null && validRevisionIds.has(urlState.revision)
      ? urlState.revision
      : (defaultRevisionId ?? null);
  const railItemIds = knownRailItemIds(stage);
  const itemId =
    stage.key === "round_analyses"
      ? null
      : stage.key === "table_observations"
        ? urlState.item !== null && railItemIds.includes(urlState.item)
          ? urlState.item
          : null
        : urlState.item === null || railItemIds.length === 0
          ? urlState.item
          : railItemIds.includes(urlState.item)
            ? urlState.item
            : null;
  const timeUs =
    urlState.tUs === null
      ? null
      : Math.min(Math.max(urlState.tUs, 0), Math.max(durationUs, 0));
  const analysisId =
    stage.key === "round_analyses" &&
    urlState.analysis !== null &&
    stage.analyses.some(
      (analysis) => analysis.analysis_id === urlState.analysis,
    )
      ? urlState.analysis
      : null;
  return { view, revisionId, itemId, timeUs, analysisId };
}

function defaultViewForStage(stage: PipelineWorkspaceStage): PipelineView {
  return stage.selected_generated_revision_id !== null ||
    stage.reference == null ||
    stage.reference.state === "empty" ||
    !stage.has_maintained_reference
    ? "generated"
    : "reviewed";
}

function buildRail(
  stage: PipelineWorkspaceStage,
  durationUs: number,
  selection: WorkspaceSelection,
  compare: boolean,
): RecordingWorkspacePresentation["rail"] {
  const lanes = compare
    ? [
        { id: "differences", label: "Differences" },
        { id: "matches", label: "Matches" },
      ]
    : RAIL_LANES[stage.key];
  const items = compare
    ? []
    : stage.key === "round_analyses"
      ? analysisRailItems(stage, durationUs)
      : runRailItems(stage, durationUs);
  const normalizedLanes = lanes.map((lane) => ({
    ...lane,
    itemCount: items.filter((item) => item.laneId === lane.id).length,
    state: stage.state,
  }));
  const selectedItemKey = selection.itemId ?? selection.analysisId;
  const selected =
    items.find((item) => item.itemId === selectedItemKey)?.id ?? null;
  return {
    durationUs,
    currentTimeUs: selection.timeUs,
    selectedItemId: selected,
    lanes: normalizedLanes,
    items,
  };
}

function runRailItems(
  stage: PipelineWorkspaceStage,
  durationUs: number,
): RecordingTimelineRailItem[] {
  return stage.runs.flatMap((run) => {
    const rawItems = Array.isArray(run.state.items)
      ? run.state.items.filter(isRecord)
      : [];
    return rawItems.flatMap((item) => {
      const itemId =
        typeof item.item_id === "string" ? item.item_id : "unknown";
      const observationItem = {
        id: `${run.run_id}:${itemId}`,
        itemId,
        selectionParam: "item" as const,
        laneId: railLaneForStage(stage.key),
        label: railItemLabel(item, itemId),
        state: typeof item.status === "string" ? item.status : run.status,
        timeRange: readTimeRange(item, durationUs),
        runId: run.run_id,
      };
      return stage.key === "table_observations"
        ? [
            observationItem,
            {
              ...observationItem,
              id: `${run.run_id}:${itemId}:execution`,
              laneId: "execution",
              label: `${observationItem.label} · ${observationItem.state}`,
            },
          ]
        : [observationItem];
    });
  });
}

function analysisRailItems(
  stage: PipelineWorkspaceStage,
  durationUs: number,
): RecordingTimelineRailItem[] {
  return stage.analyses.flatMap((analysis) => {
    const item = {
      id: `analysis:${analysis.analysis_id}`,
      itemId: analysis.analysis_id,
      selectionParam: "analysis" as const,
      laneId: "analysis-evidence",
      label: analysis.round_id,
      state: analysis.state,
      timeRange: readTimeRange(analysis.request, durationUs),
      runId: null,
    };
    return [
      item,
      {
        ...item,
        id: `${item.id}:reconstruction`,
        laneId: "reconstruction",
        label: `${item.label} · ${item.state}`,
      },
    ];
  });
}

function railLaneForStage(stage: PipelineStageKey): string {
  switch (stage) {
    case "events":
      return "proposals";
    case "visible_cards":
      return "resolved-frames";
    case "visual_identities":
      return "identity-cards";
    case "table_observations":
      return "observation-intervals";
    case "round_analyses":
      return "analysis-evidence";
  }
}

function knownRailItemIds(stage: PipelineWorkspaceStage): string[] {
  if (stage.key === "round_analyses") return [];
  return stage.runs.flatMap((run) => {
    const items = Array.isArray(run.state.items)
      ? run.state.items.filter(isRecord)
      : [];
    return items.flatMap((item) =>
      typeof item.item_id === "string" ? [item.item_id] : [],
    );
  });
}

function findRunForRevision(
  stage: PipelineWorkspaceStage,
  revisionId: string | null,
): PipelineRun | null {
  return (
    stage.runs.find(
      (run) =>
        revisionId !== null && run.output_revision_ids.includes(revisionId),
    ) ??
    stage.runs[stage.runs.length - 1] ??
    null
  );
}

function progressForStage(
  stage: PipelineWorkspaceStage,
  run: PipelineRun | null,
  analysis: PipelineWorkspaceStage["analyses"][number] | null,
): ProgressPresentation {
  if (analysis !== null) {
    return progressValue(
      analysis.progress.completed,
      analysis.progress.total,
      "Analysis progress",
    );
  }
  if (run !== null) {
    return progressValue(
      run.progress.completed,
      run.progress.total,
      "Run progress",
    );
  }
  return {
    completed: null,
    total: null,
    percent: null,
    label: `${STAGE_LABELS[stage.key]} is ${stage.state}`,
  };
}

function progressValue(
  completed: number,
  total: number,
  label: string,
): ProgressPresentation {
  return {
    completed,
    total,
    percent: total > 0 ? Math.round((completed / total) * 100) : null,
    label,
  };
}

function saveStateForStage(
  stage: PipelineWorkspaceStage,
): RecordingWorkspacePresentation["inspector"]["saveState"] {
  if (stage.state === "failed") return "failed";
  if (stage.state === "complete") return "complete";
  if (
    stage.state === "affected" ||
    (stage.reference?.affected_count ?? 0) > 0
  ) {
    return "affected";
  }
  if (stage.state === "draft" || stage.reference?.state === "draft")
    return "draft";
  return "idle";
}

function failureMessage(stage: PipelineWorkspaceStage): string | null {
  return (
    stage.runs.find((run) => run.failure !== null)?.failure?.message ??
    stage.runs
      .map((run) => readFailureMessage(run.state))
      .find((message): message is string => message !== null) ??
    null
  );
}

function readFailureMessage(value: unknown): string | null {
  const record = asRecord(value);
  const failure = asRecord(record?.terminal_failure);
  return typeof failure?.message === "string" ? failure.message : null;
}

function railItemLabel(item: RawItem, fallback: string): string {
  const result = asRecord(item.result);
  if (result?.event_type === CARD_STATE_CHANGED_EVENT_TYPE) {
    return "Card-state change";
  }
  for (const value of [
    result?.event_type,
    result?.card_id,
    result?.observation_id,
    result?.status,
  ]) {
    if (typeof value === "string" && value.length > 0) return value;
  }
  return fallback;
}

function readTimeRange(
  value: unknown,
  durationUs: number,
): RailTimeRange | null {
  const record = asRecord(value);
  if (record === null) return null;
  const result = asRecord(record.result);
  const candidates: Array<RawItem | null> = [record, result];
  for (const candidate of candidates) {
    const range = rangeFromRecord(candidate, durationUs);
    if (range !== null) return range;
  }
  return null;
}

function rangeFromRecord(
  value: Record<string, unknown> | null,
  durationUs: number,
): RailTimeRange | null {
  if (value === null) return null;
  const event = asRecord(value.event);
  const frameIdentity = asRecord(value.frame_identity);
  const observation = asRecord(value.observation);
  const ranges: Array<[unknown, unknown, number]> = [
    [value.start_us, value.end_us, 1],
    [event?.start_us, event?.end_us, 1],
    [value.requested_time_us, value.requested_time_us, 1],
    [frameIdentity?.requested_time_us, frameIdentity?.requested_time_us, 1],
    [value.observed_at_ms, value.observed_at_ms, 1_000],
    [observation?.observed_at_ms, observation?.observed_at_ms, 1_000],
  ];
  for (const [rawStart, rawEnd, multiplier] of ranges) {
    if (typeof rawStart !== "number" || !Number.isFinite(rawStart)) continue;
    const startUs = rawStart * multiplier;
    const endUs =
      typeof rawEnd === "number" && Number.isFinite(rawEnd)
        ? rawEnd * multiplier
        : startUs;
    return {
      startUs: Math.min(Math.max(startUs, 0), Math.max(durationUs, 0)),
      endUs: Math.min(
        Math.max(Math.max(startUs, endUs), 0),
        Math.max(durationUs, 0),
      ),
    };
  }
  return null;
}

function isRecord(value: unknown): value is RawItem {
  return asRecord(value) !== null;
}

function asRecord(value: unknown): RawItem | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as RawItem)
    : null;
}
