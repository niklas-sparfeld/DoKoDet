import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type PipelineSelectionUpdateRequest,
  type PipelineSelectableContentType,
  type PipelineStageKey,
  type PipelineWorkspace,
  type PipelineWorkspaceStage,
} from "../api/client";
import styles from "../App.module.css";
import { RecordingWorkspaceInspector } from "./RecordingWorkspaceInspector";
import {
  RecordingWorkspaceShell,
  RecordingWorkspaceTaskSurface,
} from "./RecordingWorkspaceShell";
import {
  RecordingWorkspaceTimelineRail,
  useRecordingWorkspaceRail,
} from "./RecordingWorkspaceRail";
import {
  readPipelineUrlState,
  recordingPipelineComparePath,
  recordingPipelinePath,
  type PipelineUrlState,
} from "./recordingPipelineUrl";
import {
  PIPELINE_STAGE_KEYS,
  primaryActionForStage,
  buildRecordingWorkspacePresentation,
} from "./recordingWorkspacePresentation";
import { actionStateForStage } from "./recordingWorkspaceNavigation";

export type { PipelineStageKey } from "../api/client";
export {
  PIPELINE_STAGE_KEYS,
  STAGE_LABELS,
  getPrimaryAction,
  primaryActionForStage,
} from "./recordingWorkspacePresentation";
export type {
  PipelinePrimaryAction,
  PipelinePrimaryActionKind,
} from "./recordingWorkspacePresentation";
export type { PipelineUrlState, PipelineView } from "./recordingPipelineUrl";

const STAGE_CONTENT_TYPES: Record<
  Exclude<PipelineStageKey, "round_analyses">,
  PipelineSelectableContentType
> = {
  events: "events",
  visible_cards: "visible_cards",
  visual_identities: "visual_identities",
  table_observations: "table_observations",
};

export function RecordingPipelineWorkspace({
  recordingId,
  stageKey,
  compare,
}: {
  recordingId: string;
  stageKey: PipelineStageKey | null;
  compare: boolean;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [workspace, setWorkspace] = useState<PipelineWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [urlState, setUrlState] = useState(() =>
    readPipelineUrlState(window.location.search),
  );
  const [selectionBusy, setSelectionBusy] = useState(false);

  const loadWorkspace = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await client.getRecordingPipeline(recordingId, {
          signal,
        });
        if (!signal?.aborted) {
          if (isPipelineWorkspace(response)) {
            setWorkspace(response);
            setError(null);
          } else {
            setWorkspace(null);
            if (stageKey !== null) {
              setError(
                "The backend returned an invalid recording pipeline workspace.",
              );
            }
          }
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          setError(describePipelineError(reason));
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [client, recordingId, stageKey],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => void loadWorkspace(controller.signal),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadWorkspace]);

  useEffect(() => {
    const updateUrlState = () => {
      setUrlState(readPipelineUrlState(window.location.search));
    };
    window.addEventListener("popstate", updateUrlState);
    return () => window.removeEventListener("popstate", updateUrlState);
  }, []);

  useEffect(() => {
    if (workspace === null || stageKey !== null || compare) {
      return;
    }
    const selectedStage = chooseInitialStage(workspace);
    const nextPath = recordingPipelinePath(
      recordingId,
      selectedStage.key,
      readPipelineUrlState(window.location.search),
    );
    if (window.location.pathname !== nextPath.split("?")[0]) {
      window.history.replaceState({}, "", nextPath);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  }, [compare, recordingId, stageKey, workspace]);

  const stage = workspace?.stages.find(
    (candidate) => candidate.key === stageKey,
  );

  useEffect(() => {
    if (workspace === null || stage === undefined || stageKey === null) {
      return;
    }
    const sanitized = sanitizeUrlState(
      urlState,
      stage,
      workspace.video.duration_us,
      compare,
    );
    const nextPath = compare
      ? recordingPipelineComparePath(recordingId, stage.key, sanitized)
      : recordingPipelinePath(recordingId, stage.key, sanitized);
    if (`${window.location.pathname}${window.location.search}` === nextPath) {
      return;
    }
    window.history.replaceState({}, "", nextPath);
    window.setTimeout(
      () =>
        setNotice(
          "Some saved pipeline URL state was no longer available and was reset.",
        ),
      0,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, [compare, recordingId, stage, stageKey, urlState, workspace]);

  async function selectGeneratedRevision(
    nextRevisionId: string | null,
  ): Promise<void> {
    if (stage === undefined || stage.key === "round_analyses") {
      return;
    }
    setSelectionBusy(true);
    setNotice(null);
    const contentType = STAGE_CONTENT_TYPES[stage.key];
    const payload: PipelineSelectionUpdateRequest = {
      expected_revision: stage.selection_revision ?? 0,
      selected_generated_revision_id: nextRevisionId,
    };
    try {
      const response = await client.updatePipelineSelection(
        recordingId,
        contentType,
        payload,
      );
      setWorkspace((current) =>
        current === null
          ? current
          : {
              ...current,
              stages: current.stages.map((candidate) =>
                candidate.key === stage.key
                  ? {
                      ...candidate,
                      selection_revision: response.selection.revision,
                      selected_generated_revision_id:
                        response.selection.selected_generated_revision_id,
                      selected_completed_reference_revision_id:
                        response.selection
                          .selected_completed_reference_revision_id,
                    }
                  : candidate,
              ),
            },
      );
      replaceUrlState({ ...urlState, revision: null });
      setNotice("Generated revision selected.");
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        await loadWorkspace();
        setNotice(
          "The generated selection changed elsewhere. The winning selection is shown.",
        );
      } else {
        setNotice(describePipelineError(reason));
      }
    } finally {
      setSelectionBusy(false);
    }
  }

  const navigateTo = useCallback((path: string, replace = false): void => {
    if (replace) {
      window.history.replaceState({}, "", path);
    } else {
      window.history.pushState({}, "", path);
    }
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  const replaceUrlState = useCallback(
    (nextState: PipelineUrlState): void => {
      const nextPath = compare
        ? recordingPipelineComparePath(
            recordingId,
            stageKey ?? "events",
            nextState,
          )
        : recordingPipelinePath(recordingId, stageKey ?? "events", nextState);
      window.history.replaceState({}, "", nextPath);
      setUrlState(nextState);
    },
    [compare, recordingId, stageKey],
  );

  const presentation = buildRecordingWorkspacePresentation({
    workspace,
    stageKey,
    compare,
    urlState,
    error,
    loading: loading && workspace === null,
  });
  const activeView = presentation.topBar.view ?? "generated";
  const action =
    presentation.inspector.primaryAction ??
    (stage === undefined ? null : primaryActionForStage(stage));
  const actionState =
    stage === undefined || action === null
      ? urlState
      : actionStateForStage(stage, urlState, action.kind);
  const displayedRevision = presentation.stage?.displayedRevisionId ?? null;
  const workspaceRail = useRecordingWorkspaceRail({
    recordingId,
    stage,
    stageKey,
    activeView,
    compare,
    urlState,
    displayedRevision,
    durationUs: workspace?.video.duration_us ?? 0,
    rail: presentation.rail,
    onReplaceUrlState: replaceUrlState,
  });

  if (loading && workspace === null) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.loading} role="status">
          Loading recording pipeline…
        </p>
      </main>
    );
  }
  if (workspace === null) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.errorMessage} role="alert">
          {error ?? "The recording pipeline could not be loaded."}
        </p>
      </main>
    );
  }
  if (stageKey === null) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.loading} role="status">
          Opening recording pipeline…
        </p>
      </main>
    );
  }
  if (stage === undefined || action === null) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.errorMessage} role="alert">
          {error ?? "The recording pipeline stage could not be loaded."}
        </p>
      </main>
    );
  }

  const usesReviewCardRail =
    (stage.key === "visible_cards" || stage.key === "visual_identities") &&
    !compare;
  const cardRailLabel =
    stage.key === "visual_identities"
      ? "Visual identity cards"
      : "Visible-card proposals";

  return (
    <main
      className={`${styles.shell} ${styles.recordingsPage} ${styles.pipelinePage} ${styles.pipelineViewport}`}
    >
      <RecordingWorkspaceShell
        recordingId={recordingId}
        workspace={workspace}
        stage={stage}
        compare={compare}
        urlState={urlState}
        activeView={activeView}
        notice={notice}
        error={error}
        onNavigate={navigateTo}
      />

      <div
        className={`${styles.pipelineWorkspaceGrid} ${usesReviewCardRail ? styles.pipelineVisibleCardWorkspaceGrid : ""}`}
        data-slot="workspace"
      >
        {usesReviewCardRail ? (
          <aside
            className={styles.pipelineProposalSlot}
            aria-label={cardRailLabel}
            data-slot="proposals"
          >
            {stage.key === "visual_identities" ? (
              <div data-identity-card-list-slot="cards" />
            ) : (
              <div data-visible-card-proposal-slot="proposals" />
            )}
          </aside>
        ) : null}
        <RecordingWorkspaceTaskSurface
          recordingId={recordingId}
          workspace={workspace}
          stage={stage}
          compare={compare}
          urlState={urlState}
          activeView={activeView}
          displayedRevision={displayedRevision}
          action={action}
          presentation={presentation}
          selectedEventRunId={workspaceRail.selectedEventRunId}
          selectedVisibleCardRunId={workspaceRail.selectedVisibleCardRunId}
          selectedVisualIdentityRunId={
            workspaceRail.selectedVisualIdentityRunId
          }
          onNavigate={navigateTo}
          onEventRailItemsChange={workspaceRail.handleEventRailItemsChange}
          onVisibleCardRailItemsChange={
            workspaceRail.handleVisibleCardRailItemsChange
          }
          onVisualIdentityRailItemsChange={
            workspaceRail.handleVisualIdentityRailItemsChange
          }
          onComparisonRailItemsChange={
            workspaceRail.handleComparisonRailItemsChange
          }
          onComparisonChange={workspaceRail.handleComparisonChange}
          onTimeChange={workspaceRail.handleRailTimeChange}
        />
        <RecordingWorkspaceInspector
          recordingId={recordingId}
          workspace={workspace}
          stage={stage}
          compare={compare}
          urlState={urlState}
          activeView={activeView}
          displayedRevision={displayedRevision}
          action={action}
          actionState={actionState}
          presentation={presentation}
          comparison={workspaceRail.comparison}
          selectionBusy={selectionBusy}
          onNavigate={navigateTo}
          onReplaceUrlState={replaceUrlState}
          onSelectGeneratedRevision={selectGeneratedRevision}
          onRefresh={() => loadWorkspace()}
        />
      </div>

      <RecordingWorkspaceTimelineRail
        recordingId={recordingId}
        stage={stage}
        activeView={activeView}
        compare={compare}
        rail={workspaceRail.visibleRail}
        onTimeChange={workspaceRail.handleRailTimeChange}
        onItemSelect={workspaceRail.handleRailItemSelect}
      />
    </main>
  );
}

function chooseInitialStage(
  workspace: PipelineWorkspace,
): PipelineWorkspaceStage {
  return (
    workspace.stages.find(
      (stage) =>
        stage.state !== "video-only" &&
        stage.state !== "empty" &&
        (stage.input_options.length > 0 ||
          stage.runs.length > 0 ||
          stage.analyses.length > 0),
    ) ?? workspace.stages[0]
  );
}

function sanitizeUrlState(
  state: PipelineUrlState,
  stage: PipelineWorkspaceStage,
  durationUs: number,
  compare: boolean,
): PipelineUrlState {
  const validRevisionIds = new Set(
    stage.input_options.map((option) => option.revision_id),
  );
  const validRunIds = new Set(stage.runs.map((run) => run.run_id));
  const validReferenceIds = new Set(
    stage.input_options
      .filter(
        (option) => option.origin === "manual" || option.origin === "corrected",
      )
      .map((option) => option.revision_id),
  );
  const selectedReference =
    stage.selected_completed_reference_revision_id ??
    stage.reference?.selected_completion ??
    null;
  return {
    ...state,
    revision:
      state.revision !== null && validRevisionIds.has(state.revision)
        ? state.revision
        : state.revision === null
          ? null
          : null,
    item:
      state.item !== null && isKnownItem(stage, state.item) ? state.item : null,
    tUs:
      state.tUs === null
        ? null
        : Math.min(Math.max(state.tUs, 0), Math.max(durationUs, 0)),
    left:
      compare && state.left !== null && validRunIds.has(state.left)
        ? state.left
        : null,
    right:
      compare && state.right !== null && validRunIds.has(state.right)
        ? state.right
        : null,
    reference:
      compare &&
      state.reference !== null &&
      (validReferenceIds.has(state.reference) ||
        state.reference === selectedReference)
        ? state.reference
        : null,
    analysis:
      !compare && stage.key === "round_analyses" && state.analysis !== null
        ? stage.analyses.some(
            (analysis) => analysis.analysis_id === state.analysis,
          )
          ? state.analysis
          : null
        : null,
  };
}

function isKnownItem(stage: PipelineWorkspaceStage, itemId: string): boolean {
  if (stage.key === "round_analyses") {
    return false;
  }
  const knownItemIds = stage.runs.flatMap((run) => {
    const items = run.state.items;
    return Array.isArray(items)
      ? items.flatMap((item) =>
          typeof item === "object" &&
          item !== null &&
          "item_id" in item &&
          typeof item.item_id === "string"
            ? [item.item_id]
            : [],
        )
      : [];
  });
  if (stage.key === "table_observations") {
    return knownItemIds.includes(itemId);
  }
  return knownItemIds.length === 0 || knownItemIds.includes(itemId);
}

function describePipelineError(reason: unknown): string {
  if (!(reason instanceof ApiError)) {
    return "The backend could not be reached.";
  }
  const body =
    typeof reason.body === "object" && reason.body !== null
      ? (reason.body as Record<string, unknown>)
      : null;
  const detail =
    typeof body?.detail === "object" && body.detail !== null
      ? (body.detail as Record<string, unknown>)
      : null;
  const message =
    typeof detail?.message === "string"
      ? detail.message
      : typeof body?.message === "string"
        ? body.message
        : null;
  if (
    message?.toLowerCase().includes("video") ||
    message?.toLowerCase().includes("recording")
  ) {
    return `The accepted recording video is unavailable: ${message}`;
  }
  if (reason.status === 422) {
    return message === null
      ? "The selected pipeline input is incompatible with this stage."
      : `The selected pipeline input is incompatible with this stage: ${message}`;
  }
  return message ?? `The backend returned HTTP ${reason.status}.`;
}

function isPipelineWorkspace(value: unknown): value is PipelineWorkspace {
  return (
    typeof value === "object" &&
    value !== null &&
    "schema_version" in value &&
    value.schema_version === "pipeline-workspace/v1" &&
    "recording_id" in value &&
    typeof value.recording_id === "string" &&
    "video" in value &&
    typeof value.video === "object" &&
    value.video !== null &&
    "stages" in value &&
    Array.isArray(value.stages) &&
    value.stages.length === PIPELINE_STAGE_KEYS.length
  );
}
