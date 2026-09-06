import {
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type PipelineSelectionUpdateRequest,
  type PipelineSelectableContentType,
  type PipelineStageKey,
  type PipelineWorkspace,
  type PipelineWorkspaceStage,
} from "../api/client";
import {
  PipelineCardEventEditor,
  type PipelineCardEventRailItem,
} from "../cardEvents/PipelineCardEventEditor";
import { PipelineVisibleCardEditor } from "../visibleCards/PipelineVisibleCardEditor";
import type { PipelineVisibleCardRailItem } from "../visibleCards/PipelineVisibleCardEditor";
import {
  PipelineVisualIdentityEditor,
  type PipelineVisualIdentityRailItem,
} from "../visualIdentities/PipelineVisualIdentityEditor";
import styles from "../App.module.css";
import {
  ObservationRunControls,
  RoundAnalysisControls,
} from "./ObservationAndAnalysisControls";
import { RunControls } from "./RunControls";
import { RecordingTimelineRail } from "./RecordingTimelineRail";
import { ComparisonView } from "./ComparisonView";
import { PipelineObservationWorkbench } from "./PipelineObservationWorkbench";
import { PipelineRoundAnalysisWorkbench } from "./PipelineRoundAnalysisWorkbench";
import {
  buildRecordingWorkspacePresentation,
  PIPELINE_STAGE_KEYS,
  STAGE_LABELS,
  isPipelineStageKey,
  primaryActionForStage,
  type RecordingWorkspacePresentation,
  type RecordingTimelineRailItem,
  type PipelinePrimaryActionKind,
  type PipelineUrlState,
  type PipelineView,
} from "./recordingWorkspacePresentation";

export type { PipelineStageKey } from "../api/client";
export {
  PIPELINE_STAGE_KEYS,
  STAGE_LABELS,
  getPrimaryAction,
  isPipelineStageKey,
  primaryActionForStage,
} from "./recordingWorkspacePresentation";
export type {
  PipelinePrimaryAction,
  PipelinePrimaryActionKind,
  PipelineUrlState,
  PipelineView,
} from "./recordingWorkspacePresentation";

const STAGE_CONTENT_TYPES: Record<
  Exclude<PipelineStageKey, "round_analyses">,
  PipelineSelectableContentType
> = {
  events: "events",
  visible_cards: "visible_cards",
  visual_identities: "visual_identities",
  table_observations: "table_observations",
};

export function readRecordingPipelineRoute(pathname: string): {
  recordingId: string;
  stage: PipelineStageKey | null;
  compare: boolean;
} | null {
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
  const [eventRail, setEventRail] = useState<{
    key: string;
    items: RecordingTimelineRailItem[];
  } | null>(null);
  const [visibleCardRail, setVisibleCardRail] = useState<{
    key: string;
    items: RecordingTimelineRailItem[];
  } | null>(null);
  const [visualIdentityRail, setVisualIdentityRail] = useState<{
    key: string;
    items: RecordingTimelineRailItem[];
  } | null>(null);
  const workspaceDurationUsRef = useRef(0);
  workspaceDurationUsRef.current = workspace?.video.duration_us ?? 0;
  const eventRailKeyRef = useRef("");
  const visibleCardRailKeyRef = useRef("");
  const visualIdentityRailKeyRef = useRef("");
  const handleEventRailItemsChange = useCallback(
    (items: PipelineCardEventRailItem[]) => {
      setEventRail({
        key: eventRailKeyRef.current,
        items: items
          .flatMap<RecordingTimelineRailItem>((item) => [
            {
              id: `event:${item.itemId}`,
              itemId: item.itemId,
              selectionParam: "item" as const,
              laneId:
                item.state === "pending" || item.state === "affected"
                  ? "review-state"
                  : "events",
              label: item.label,
              state: item.state,
              timeRange: {
                startUs: item.startUs,
                endUs: item.endUs,
              },
              runId: null,
            },
            {
              id: `event:${item.itemId}:state`,
              itemId: item.itemId,
              selectionParam: "item" as const,
              laneId: "review-state",
              label: `${item.label} · ${item.state}`,
              state: item.state,
              timeRange: {
                startUs: item.startUs,
                endUs: item.endUs,
              },
              runId: null,
            },
          ])
          .concat({
            id: "events:coverage",
            itemId: "events:coverage",
            selectionParam: "none" as const,
            laneId: "coverage",
            label: "Full recording",
            state: "reviewed",
            timeRange: {
              startUs: 0,
              endUs: workspaceDurationUsRef.current,
            },
            runId: null,
          }),
      });
    },
    [],
  );
  const handleVisibleCardRailItemsChange = useCallback(
    (items: PipelineVisibleCardRailItem[]) => {
      setVisibleCardRail({
        key: visibleCardRailKeyRef.current,
        items: items.flatMap<RecordingTimelineRailItem>((item) => {
          const timeRange =
            item.timeUs === null
              ? null
              : {
                  startUs: item.timeUs,
                  endUs: Math.min(
                    workspaceDurationUsRef.current,
                    item.timeUs + 1,
                  ),
                };
          return [
            {
              id: `visible-card:${item.itemId}`,
              itemId: item.itemId,
              selectionParam: "item" as const,
              laneId: "resolved-frames",
              label: item.label,
              state: item.state,
              timeRange,
              runId: null,
            },
            {
              id: `visible-card:${item.itemId}:decision`,
              itemId: item.itemId,
              selectionParam: "item" as const,
              laneId: "frame-decision",
              label: `${item.label} · ${item.decision ?? "pending decision"}`,
              state: item.decision ?? item.state,
              timeRange,
              runId: null,
            },
            {
              id: `visible-card:${item.itemId}:proposals`,
              itemId: item.itemId,
              selectionParam: "item" as const,
              laneId: "proposals",
              label: `${item.label} · ${item.proposalCount} proposal${item.proposalCount === 1 ? "" : "s"}`,
              state: item.state,
              timeRange,
              runId: null,
            },
          ];
        }),
      });
    },
    [],
  );
  const handleVisualIdentityRailItemsChange = useCallback(
    (items: PipelineVisualIdentityRailItem[]) => {
      setVisualIdentityRail({
        key: visualIdentityRailKeyRef.current,
        items: items.flatMap((item) => {
          const timeRange = {
            startUs: item.timeUs,
            endUs: Math.min(workspaceDurationUsRef.current, item.timeUs + 1),
          };
          return [
            {
              id: `identity:${item.itemId}`,
              itemId: item.itemId,
              selectionParam: "item" as const,
              laneId: "identity-cards",
              label: item.label,
              state: item.state,
              timeRange,
              runId: null,
            },
            {
              id: `identity:${item.itemId}:review`,
              itemId: item.itemId,
              selectionParam: "item" as const,
              laneId: "review-state",
              label: `${item.label} · ${item.state}`,
              state: item.state,
              timeRange,
              runId: null,
            },
          ];
        }),
      });
    },
    [],
  );

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

  function navigateTo(path: string, replace = false): void {
    if (replace) {
      window.history.replaceState({}, "", path);
    } else {
      window.history.pushState({}, "", path);
    }
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  function replaceUrlState(nextState: PipelineUrlState): void {
    const nextPath = compare
      ? recordingPipelineComparePath(
          recordingId,
          stageKey ?? "events",
          nextState,
        )
      : recordingPipelinePath(recordingId, stageKey ?? "events", nextState);
    window.history.replaceState({}, "", nextPath);
    setUrlState(nextState);
  }

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
  if (stage === undefined) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.errorMessage} role="alert">
          {error ?? "The recording pipeline stage could not be loaded."}
        </p>
      </main>
    );
  }

  const presentation = buildRecordingWorkspacePresentation({
    workspace,
    stageKey,
    compare,
    urlState,
    error,
  });
  const activeView = presentation.topBar.view ?? defaultViewForStage(stage);
  const action =
    presentation.inspector.primaryAction ?? primaryActionForStage(stage);
  const actionState = actionStateForStage(stage, urlState, action.kind);
  const displayedRevision = presentation.stage?.displayedRevisionId ?? null;
  const rail = presentation.rail;
  const eventRailKey = `${recordingId}:${stage.key}:${activeView}:${compare ? "compare" : "task"}`;
  eventRailKeyRef.current = eventRailKey;
  const visibleCardRailKey = `${recordingId}:${stage.key}:${activeView}:${compare ? "compare" : "task"}`;
  visibleCardRailKeyRef.current = visibleCardRailKey;
  const visualIdentityRailKey = `${recordingId}:${stage.key}:${activeView}:${compare ? "compare" : "task"}`;
  visualIdentityRailKeyRef.current = visualIdentityRailKey;
  const visibleRail =
    stage.key === "events" && activeView === "reviewed" && !compare
      ? eventRail?.key === eventRailKey && rail !== null
        ? {
            ...rail,
            items: eventRail.items,
            selectedItemId:
              eventRail.items.find((item) => item.itemId === urlState.item)
                ?.id ?? null,
            lanes: rail.lanes.map((lane) => ({
              ...lane,
              itemCount: eventRail.items.filter(
                (item) => item.laneId === lane.id,
              ).length,
            })),
          }
        : rail === null
          ? null
          : {
              ...rail,
              items: [],
              lanes: rail.lanes.map((lane) => ({ ...lane, itemCount: 0 })),
            }
      : stage.key === "visible_cards" && !compare
        ? visibleCardRail?.key === visibleCardRailKey && rail !== null
          ? {
              ...rail,
              items: visibleCardRail.items,
              selectedItemId:
                visibleCardRail.items.find(
                  (item) => item.itemId === urlState.item,
                )?.id ?? null,
              lanes: rail.lanes.map((lane) => ({
                ...lane,
                itemCount: visibleCardRail.items.filter(
                  (item) => item.laneId === lane.id,
                ).length,
              })),
            }
          : rail === null
            ? null
            : {
                ...rail,
                items: [],
                lanes: rail.lanes.map((lane) => ({ ...lane, itemCount: 0 })),
              }
        : rail;
  const identityRail =
    stage.key === "visual_identities" && !compare
      ? visualIdentityRail?.key === visualIdentityRailKey && rail !== null
        ? {
            ...rail,
            items: visualIdentityRail.items,
            selectedItemId:
              visualIdentityRail.items.find(
                (item) => item.itemId === urlState.item,
              )?.id ?? null,
            lanes: rail.lanes.map((lane) => ({
              ...lane,
              itemCount: visualIdentityRail.items.filter(
                (item) => item.laneId === lane.id,
              ).length,
            })),
          }
        : rail === null
          ? null
          : {
              ...rail,
              items: [],
              lanes: rail.lanes.map((lane) => ({ ...lane, itemCount: 0 })),
            }
      : visibleRail;
  const selectedEventRunId =
    stage.key === "events" && displayedRevision !== null
      ? (stage.runs.find((run) =>
          run.output_revision_ids.includes(displayedRevision),
        )?.run_id ?? null)
      : null;
  const selectedVisibleCardRunId =
    stage.key === "visible_cards" && displayedRevision !== null
      ? (stage.runs.find((run) =>
          run.output_revision_ids.includes(displayedRevision),
        )?.run_id ?? null)
      : null;
  const selectedVisualIdentityRunId =
    stage.key === "visual_identities" && displayedRevision !== null
      ? (stage.runs.find((run) =>
          run.output_revision_ids.includes(displayedRevision),
        )?.run_id ?? null)
      : null;

  function handleRailTimeChange(timeUs: number): void {
    replaceUrlState({ ...urlState, tUs: timeUs });
  }

  function handleRailItemSelect(
    item: NonNullable<RecordingWorkspacePresentation["rail"]>["items"][number],
  ): void {
    if (item.selectionParam === "none") {
      if (item.timeRange !== null) {
        replaceUrlState({ ...urlState, tUs: item.timeRange.startUs });
      }
      return;
    }
    replaceUrlState({
      ...urlState,
      item: item.selectionParam === "item" ? item.itemId : null,
      analysis: item.selectionParam === "analysis" ? item.itemId : null,
      tUs: item.timeRange?.startUs ?? urlState.tUs,
    });
  }

  return (
    <main
      className={`${styles.shell} ${styles.recordingsPage} ${styles.pipelinePage} ${styles.pipelineViewport}`}
    >
      <div className={styles.pipelineTopSlot} data-slot="top">
        <header className={styles.pipelineTopBar} role="banner">
          <h1 className={styles.visuallyHidden}>Recording pipeline</h1>
          <a className={styles.pipelineBackLink} href="/recordings">
            <span aria-hidden="true">←</span> Back to recordings
          </a>
          <div className={styles.pipelineRecordingContext}>
            <span className={styles.statusLabel}>Recording</span>
            <strong title={recordingId}>{recordingId}</strong>
            <span>{formatDuration(workspace.video.duration_us)}</span>
          </div>
          <nav aria-label="Recording pipeline stages">
            <ol className={styles.pipelineStageNavigation}>
              {workspace.stages.map((candidate) => (
                <li key={candidate.key}>
                  <a
                    aria-current={
                      candidate.key === stage.key ? "page" : undefined
                    }
                    className={
                      candidate.key === stage.key
                        ? styles.pipelineStageLinkActive
                        : styles.pipelineStageLink
                    }
                    href={recordingPipelinePath(recordingId, candidate.key, {
                      ...urlState,
                      left: null,
                      right: null,
                      reference: null,
                      analysis: null,
                    })}
                    onClick={(event) => {
                      if (isModifiedClick(event)) {
                        return;
                      }
                      event.preventDefault();
                      navigateTo(
                        recordingPipelinePath(recordingId, candidate.key, {
                          ...urlState,
                          left: null,
                          right: null,
                          reference: null,
                          analysis: null,
                        }),
                      );
                    }}
                  >
                    <span>{STAGE_LABELS[candidate.key]}</span>
                    <StatusBadge value={candidate.state} />
                  </a>
                </li>
              ))}
            </ol>
          </nav>
          {stage.has_maintained_reference ? (
            <fieldset className={styles.pipelineViewSwitch}>
              <legend className={styles.visuallyHidden}>Pipeline view</legend>
              <div className={styles.pipelineToggleGroup}>
                {(["generated", "reviewed"] as const).map((view) => (
                  <button
                    key={view}
                    className={
                      activeView === view
                        ? styles.pipelineToggleActive
                        : styles.pipelineToggle
                    }
                    type="button"
                    aria-pressed={activeView === view}
                    disabled={
                      view === "reviewed" && !stage.has_maintained_reference
                    }
                    onClick={() =>
                      navigateTo(
                        recordingPipelinePath(recordingId, stage.key, {
                          ...urlState,
                          view,
                          revision: null,
                          left: compare ? urlState.left : null,
                          right: compare ? urlState.right : null,
                          reference: compare ? urlState.reference : null,
                        }),
                      )
                    }
                  >
                    {formatIdentifier(view)}
                  </button>
                ))}
              </div>
            </fieldset>
          ) : null}
        </header>

        {notice !== null ? (
          <p className={styles.recordingNotice} role="status">
            {notice}
          </p>
        ) : null}
        {error !== null ? (
          <p className={styles.errorMessage} role="alert">
            {error}
          </p>
        ) : null}
      </div>

      <div className={styles.pipelineWorkspaceGrid} data-slot="workspace">
        <section
          className={styles.pipelineTaskSurface}
          aria-label={`${STAGE_LABELS[stage.key]} task surface`}
          data-slot="center"
        >
          <div className={styles.pipelineTaskSurfaceContent}>
            {compare ? (
              <ComparisonView
                recordingId={recordingId}
                stage={stage}
                durationUs={workspace.video.duration_us}
                urlState={urlState}
                onNavigate={navigateTo}
              />
            ) : null}
            {stage.key === "round_analyses" && !compare ? (
              <PipelineRoundAnalysisWorkbench
                recordingId={recordingId}
                stage={stage}
                selectedAnalysisId={
                  presentation.inspector.selection?.analysisId ?? null
                }
                selectedTimeUs={
                  presentation.inspector.selection?.timeUs ?? null
                }
                onTimeChange={handleRailTimeChange}
              />
            ) : null}
            {stage.key === "events" && !compare ? (
              <PipelineCardEventEditor
                recordingId={recordingId}
                durationUs={workspace.video.duration_us}
                selectionItemId={presentation.surface.selectedItemId}
                selectionTimeUs={
                  presentation.inspector.selection?.timeUs ?? null
                }
                generatedRevisionId={
                  stage.selected_generated_revision_id ?? null
                }
                generatedRunId={selectedEventRunId}
                view={activeView}
                inspectorEnabled={action.kind !== "blocked"}
                onRailItemsChange={handleEventRailItemsChange}
                onReviewRequested={() =>
                  navigateTo(
                    actionHref(recordingId, stage.key, "review", urlState),
                  )
                }
              />
            ) : null}
            {stage.key === "visible_cards" && !compare ? (
              <PipelineVisibleCardEditor
                recordingId={recordingId}
                durationUs={workspace.video.duration_us}
                selectionItemId={presentation.surface.selectedItemId}
                selectionTimeUs={
                  presentation.inspector.selection?.timeUs ?? null
                }
                generatedRevisionId={
                  stage.selected_generated_revision_id ?? null
                }
                displayedRevisionId={
                  activeView === "generated" ? displayedRevision : null
                }
                generatedRunId={selectedVisibleCardRunId}
                view={activeView}
                inspectorEnabled={action.kind !== "blocked"}
                onRailItemsChange={handleVisibleCardRailItemsChange}
                onReviewRequested={() =>
                  navigateTo(
                    actionHref(recordingId, stage.key, "review", urlState),
                  )
                }
              />
            ) : null}
            {stage.key === "visual_identities" && !compare ? (
              <PipelineVisualIdentityEditor
                recordingId={recordingId}
                durationUs={workspace.video.duration_us}
                selectionItemId={presentation.surface.selectedItemId}
                selectionTimeUs={
                  presentation.inspector.selection?.timeUs ?? null
                }
                generatedRevisionId={
                  stage.selected_generated_revision_id ?? null
                }
                displayedRevisionId={
                  activeView === "generated" ? displayedRevision : null
                }
                generatedRunId={selectedVisualIdentityRunId}
                view={activeView}
                inspectorEnabled={action.kind !== "blocked"}
                onRailItemsChange={handleVisualIdentityRailItemsChange}
              />
            ) : null}
            {stage.key === "table_observations" && !compare ? (
              <PipelineObservationWorkbench
                recordingId={recordingId}
                stage={stage}
                selectedItemId={presentation.surface.selectedItemId}
              />
            ) : null}
          </div>
        </section>

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
          selectionBusy={selectionBusy}
          onNavigate={navigateTo}
          onReplaceUrlState={replaceUrlState}
          onSelectGeneratedRevision={selectGeneratedRevision}
          onRefresh={() => loadWorkspace()}
        />
      </div>

      <section
        className={styles.pipelineRailSlot}
        aria-label="Timeline Rail"
        data-slot="bottom"
      >
        {identityRail !== null ? (
          <RecordingTimelineRail
            key={`${stage.key}:${activeView}:${compare ? "compare" : "task"}`}
            recordingId={recordingId}
            durationUs={identityRail.durationUs}
            currentTimeUs={identityRail.currentTimeUs}
            selectedItemId={identityRail.selectedItemId}
            lanes={identityRail.lanes}
            items={identityRail.items}
            onTimeChange={handleRailTimeChange}
            onItemSelect={handleRailItemSelect}
          />
        ) : (
          <p className={styles.pipelineRailHint}>Timeline unavailable.</p>
        )}
      </section>
    </main>
  );
}

type RecordingWorkspaceInspectorProps = {
  recordingId: string;
  workspace: PipelineWorkspace;
  stage: PipelineWorkspaceStage;
  compare: boolean;
  urlState: PipelineUrlState;
  activeView: PipelineView;
  displayedRevision: string | null;
  action: NonNullable<
    RecordingWorkspacePresentation["inspector"]["primaryAction"]
  >;
  actionState: PipelineUrlState;
  presentation: RecordingWorkspacePresentation;
  selectionBusy: boolean;
  onNavigate: (path: string) => void;
  onReplaceUrlState: (state: PipelineUrlState) => void;
  onSelectGeneratedRevision: (revisionId: string | null) => Promise<void>;
  onRefresh: () => Promise<void>;
};

function RecordingWorkspaceInspector({
  recordingId,
  workspace,
  stage,
  compare,
  urlState,
  activeView,
  displayedRevision,
  action,
  actionState,
  presentation,
  selectionBusy,
  onNavigate,
  onReplaceUrlState,
  onSelectGeneratedRevision,
  onRefresh,
}: RecordingWorkspaceInspectorProps) {
  const recording = presentation.recording;
  const selection = presentation.inspector.selection;
  const progress = presentation.inspector.progress;
  const executionControls = compare ? null : (
    <>
      {stage.key === "table_observations" ? (
        <ObservationRunControls
          compact
          recordingId={recordingId}
          stage={stage}
          stages={workspace.stages}
          onRefresh={onRefresh}
        />
      ) : null}
      {stage.key === "round_analyses" ? (
        <RoundAnalysisControls
          compact
          recordingId={recordingId}
          stage={stage}
          selectedAnalysisId={urlState.analysis}
          onRefresh={onRefresh}
          onSelectAnalysis={(analysisId) =>
            onReplaceUrlState({ ...urlState, analysis: analysisId })
          }
        />
      ) : null}
      {isProcessorStage(stage.key) ? (
        <RunControls
          compact
          recordingId={recordingId}
          stage={stage}
          stages={workspace.stages}
          onRefresh={onRefresh}
        />
      ) : null}
    </>
  );
  const actionOwnsExecution =
    action.kind === "run" || action.kind === "run_again";
  const usesEditorInspector =
    !compare &&
    action.kind !== "blocked" &&
    (stage.key === "events" ||
      stage.key === "visible_cards" ||
      stage.key === "visual_identities");

  return (
    <aside
      className={styles.pipelineInspectorSlot}
      aria-label="Workspace inspector"
      data-slot="inspector"
    >
      <section
        className={styles.pipelineInspectorSection}
        data-inspector-section="progress"
        aria-labelledby="pipeline-inspector-progress"
      >
        <div className={styles.pipelineInspectorSectionHeading}>
          <div>
            <p className={styles.statusLabel}>Progress</p>
            <h2 id="pipeline-inspector-progress">{progress.label}</h2>
          </div>
          <StatusBadge value={stage.state} />
        </div>
        {progress.completed !== null && progress.total !== null ? (
          <>
            <div className={styles.pipelineInspectorProgressHeading}>
              <span>
                {progress.completed} of {progress.total} complete
              </span>
              <strong>{progress.percent ?? 0}%</strong>
            </div>
            <progress
              max={progress.total}
              value={progress.completed}
              aria-label={progress.label}
            />
          </>
        ) : (
          <p className={styles.pipelineInspectorEmpty}>
            No execution progress recorded.
          </p>
        )}
      </section>

      <section
        className={styles.pipelineInspectorSection}
        data-inspector-section="action"
        aria-labelledby="pipeline-inspector-action"
      >
        {usesEditorInspector ? (
          <div
            data-event-inspector-slot="action"
            data-visible-card-inspector-slot="action"
            data-identity-inspector-slot="action"
          />
        ) : (
          <>
            <p className={styles.statusLabel}>Primary action</p>
            <h2 id="pipeline-inspector-action">{action.label}</h2>
            {action.kind === "blocked" ? (
              <p className={styles.detailBlocker}>{action.blocker}</p>
            ) : actionOwnsExecution ? (
              executionControls
            ) : (
              <a
                className={styles.primaryButton}
                href={actionHref(
                  recordingId,
                  stage.key,
                  action.kind,
                  actionState,
                )}
                onClick={(event) => {
                  if (isModifiedClick(event)) {
                    return;
                  }
                  event.preventDefault();
                  onNavigate(
                    actionHref(
                      recordingId,
                      stage.key,
                      action.kind,
                      actionState,
                    ),
                  );
                }}
                data-action={action.kind}
              >
                {action.label}
              </a>
            )}
            {presentation.inspector.activeBlocker !== null &&
            action.kind !== "blocked" ? (
              <p className={styles.detailBlocker} role="alert">
                {presentation.inspector.activeBlocker}
              </p>
            ) : null}
          </>
        )}
      </section>

      <section
        className={styles.pipelineInspectorSection}
        data-inspector-section="save-state"
        aria-labelledby="pipeline-inspector-save-state"
      >
        {usesEditorInspector ? (
          <>
            <div
              data-event-inspector-slot="save"
              data-visible-card-inspector-slot="save"
              data-identity-inspector-slot="save"
            />
            {executionControls}
          </>
        ) : (
          <>
            <div className={styles.pipelineInspectorSectionHeading}>
              <div>
                <p className={styles.statusLabel}>Save or execution state</p>
                <h2 id="pipeline-inspector-save-state">
                  {formatIdentifier(presentation.inspector.saveState)}
                </h2>
              </div>
              <StatusBadge value={presentation.inspector.saveState} />
            </div>
            {!actionOwnsExecution ? executionControls : null}
          </>
        )}
      </section>

      <section
        className={styles.pipelineInspectorSection}
        data-inspector-section="selection"
        aria-labelledby="pipeline-inspector-selection"
      >
        <p className={styles.statusLabel}>Current selection</p>
        <h2 id="pipeline-inspector-selection">
          {formatIdentifier(activeView)}
        </h2>
        <div className={styles.pipelineInspectorSelectionFacts}>
          <span>Displayed revision</span>
          <strong>{displayedRevision ?? "None"}</strong>
          <span>Item</span>
          <strong>{selection?.itemId ?? "None"}</strong>
          <span>Position</span>
          <strong>
            {selection?.timeUs === null || selection?.timeUs === undefined
              ? "None"
              : formatMicroseconds(selection.timeUs)}
          </strong>
          {selection?.analysisId !== null &&
          selection?.analysisId !== undefined ? (
            <>
              <span>Analysis</span>
              <strong>{selection.analysisId}</strong>
            </>
          ) : null}
        </div>
        <div className={styles.pipelineInspectorFields}>
          {stage.key !== "round_analyses" ? (
            <label className={styles.pipelineSelector}>
              <span>Default generated revision</span>
              <select
                aria-label="Default generated revision"
                value={stage.selected_generated_revision_id ?? ""}
                disabled={selectionBusy}
                onChange={(event) =>
                  void onSelectGeneratedRevision(event.target.value || null)
                }
              >
                <option value="">No generated revision selected</option>
                {stage.input_options
                  .filter((option) => option.origin === "processor")
                  .map((option) => (
                    <option key={option.revision_id} value={option.revision_id}>
                      {option.display_label}
                    </option>
                  ))}
              </select>
            </label>
          ) : null}
          <label className={styles.pipelineSelector}>
            <span>Displayed revision</span>
            <select
              aria-label="Displayed revision"
              value={displayedRevision ?? ""}
              disabled={stage.input_options.length === 0}
              onChange={(event) => {
                const nextRevision = event.target.value || null;
                const defaultRevision =
                  activeView === "generated"
                    ? stage.selected_generated_revision_id
                    : stage.selected_completed_reference_revision_id;
                onReplaceUrlState({
                  ...urlState,
                  revision:
                    nextRevision === defaultRevision ? null : nextRevision,
                });
              }}
            >
              <option value="">No revision selected</option>
              {stage.input_options.map((option) => (
                <option key={option.revision_id} value={option.revision_id}>
                  {option.display_label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {usesEditorInspector ? (
          <div
            data-event-inspector-slot="selection"
            data-visible-card-inspector-slot="selection"
            data-identity-inspector-slot="selection"
          />
        ) : null}
      </section>

      {recording !== null ? (
        <section
          className={styles.pipelineInspectorSection}
          data-inspector-section="metadata"
          aria-labelledby="pipeline-inspector-metadata"
        >
          <p className={styles.statusLabel}>Recording metadata</p>
          <h2 id="pipeline-inspector-metadata">Accepted video</h2>
          <dl className={styles.pipelineInspectorFacts}>
            <div>
              <dt>Recording</dt>
              <dd>{recording.recordingId}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{formatDuration(recording.durationUs)}</dd>
            </div>
            <div>
              <dt>Video SHA-256</dt>
              <dd>{recording.videoSha256.slice(0, 12)}…</dd>
            </div>
            <div>
              <dt>Bytes</dt>
              <dd>{formatByteLength(recording.byteLength)}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <details
        className={styles.pipelineInspectorDetails}
        data-inspector-section="details"
        open={presentation.diagnostics.length > 0}
      >
        <summary>Lineage, diagnostics, and history</summary>
        <div className={styles.pipelineInspectorDetailsContent}>
          <dl className={styles.pipelineInspectorFacts}>
            <div>
              <dt>Stage</dt>
              <dd>{stage.key}</dd>
            </div>
            <div>
              <dt>Processor</dt>
              <dd>{stage.processor_type}</dd>
            </div>
            <div>
              <dt>Generated revision</dt>
              <dd>{stage.selected_generated_revision_id ?? "None"}</dd>
            </div>
            <div>
              <dt>Reference revision</dt>
              <dd>
                {stage.selected_completed_reference_revision_id ?? "None"}
              </dd>
            </div>
            <div>
              <dt>Reference source</dt>
              <dd>{stage.reference?.source_revision_id ?? "None"}</dd>
            </div>
            <div>
              <dt>Selection revision</dt>
              <dd>{stage.selection_revision ?? "None"}</dd>
            </div>
          </dl>
          {presentation.diagnostics.length > 0 ? (
            <ul
              className={styles.pipelineDiagnostics}
              aria-label="Pipeline diagnostics"
            >
              {presentation.diagnostics.map((diagnostic) => (
                <li key={`${diagnostic.code}:${diagnostic.revision_id ?? ""}`}>
                  <strong>{formatIdentifier(diagnostic.code)}</strong>
                  <span>{diagnostic.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <PipelineHistory stage={stage} />
        </div>
      </details>
    </aside>
  );
}

function isProcessorStage(
  stageKey: PipelineStageKey,
): stageKey is "events" | "visible_cards" | "visual_identities" {
  return (
    stageKey === "events" ||
    stageKey === "visible_cards" ||
    stageKey === "visual_identities"
  );
}

function PipelineHistory({ stage }: { stage: PipelineWorkspaceStage }) {
  if (stage.runs.length === 0 && stage.analyses.length === 0) {
    return <p className={styles.detailEmptyState}>No retained history.</p>;
  }
  return (
    <div className={styles.pipelineHistoryContent}>
      {stage.runs.length > 0 ? (
        <ul
          className={styles.pipelineHistoryList}
          aria-label="Processor history"
        >
          {stage.runs.map((run) => (
            <li key={run.run_id}>
              <div>
                <strong>{run.run_id}</strong>
                <StatusBadge value={run.status} />
              </div>
              <span>
                {run.implementation.name} {run.implementation.version} · inputs{" "}
                {run.input_revision_ids.join(", ") || "none"}
              </span>
              {run.failure !== null && run.failure !== undefined ? (
                <span>{run.failure.message}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {stage.analyses.length > 0 ? (
        <ul
          className={styles.pipelineHistoryList}
          aria-label="Analysis history"
        >
          {stage.analyses.map((analysis) => (
            <li key={analysis.analysis_id}>
              <div>
                <strong>{analysis.analysis_id}</strong>
                <StatusBadge value={analysis.state} />
              </div>
              <span>
                {analysis.round_id} · inputs{" "}
                {analysis.input_revision_ids.join(", ") || "none"}
              </span>
              {analysis.failure !== null ? (
                <span>{analysis.failure}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function actionHref(
  recordingId: string,
  stage: PipelineStageKey,
  action: PipelinePrimaryActionKind,
  state: PipelineUrlState,
): string {
  if (action === "compare") {
    return recordingPipelineComparePath(recordingId, stage, state);
  }
  return recordingPipelinePath(recordingId, stage, {
    ...state,
    view:
      action === "review" || action === "continue_review"
        ? "reviewed"
        : state.view,
  });
}

function actionStateForStage(
  stage: PipelineWorkspaceStage,
  state: PipelineUrlState,
  action: PipelinePrimaryActionKind,
): PipelineUrlState {
  if (action !== "open_analysis") {
    return state;
  }
  return {
    ...state,
    analysis:
      stage.analyses.find((analysis) => analysis.state === "complete")
        ?.analysis_id ?? null,
  };
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

function defaultViewForStage(stage: PipelineWorkspaceStage): PipelineView {
  return stage.selected_generated_revision_id !== null ||
    !stage.has_maintained_reference
    ? "generated"
    : "reviewed";
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

function isModifiedClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function formatDuration(durationUs: number): string {
  const totalSeconds = Math.floor(durationUs / 1_000_000);
  const minutes = Math.floor(totalSeconds / 60);
  return `${minutes}:${String(totalSeconds % 60).padStart(2, "0")}`;
}

function formatByteLength(value: number): string {
  if (value < 1_000) return `${value} B`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(1)} kB`;
  if (value < 1_000_000_000) return `${(value / 1_000_000).toFixed(1)} MB`;
  return `${(value / 1_000_000_000).toFixed(1)} GB`;
}

function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)}s`;
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

function recordingPagePath(recordingId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}`;
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}
