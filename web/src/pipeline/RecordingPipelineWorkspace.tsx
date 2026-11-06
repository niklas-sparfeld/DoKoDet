import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  recordingPipelineNavigationPath,
  recordingPipelinePath,
  type PipelineNavigationStepKey,
  type PipelineUrlState,
} from "./recordingPipelineUrl";
import {
  decodeLineageSelection,
  validateLineageSelection,
  type PipelineLineageGraph,
} from "./pipelineLineageSelection";
import type { LineageStageKey } from "./pipelineLineageSelection";
import {
  PIPELINE_STAGE_KEYS,
  primaryActionForStage,
  buildRecordingWorkspacePresentation,
} from "./recordingWorkspacePresentation";
import { actionStateForStage } from "./recordingWorkspaceNavigation";
import { PipelineNodeVirtualSceneEditor } from "../visibleCards/PipelineNodeVirtualSceneEditor";
import {
  FrameReviewEditorNavigation,
  FrameReviewPinnedRevisionNotice,
} from "../frameReview/FrameReviewQueueView";

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
export type { PipelineUrlState } from "./recordingPipelineUrl";

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
  stageKey: PipelineNavigationStepKey | null;
  compare: boolean;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [workspace, setWorkspace] = useState<PipelineWorkspace | null>(null);
  const [loadedStageKey, setLoadedStageKey] =
    useState<PipelineNavigationStepKey | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lineageValidation, setLineageValidation] = useState<{
    lineage: string;
    notice: string | null;
  } | null>(null);
  const [lineageGraph, setLineageGraph] = useState<PipelineLineageGraph | null>(
    null,
  );
  const [lineageGraphError, setLineageGraphError] = useState<string | null>(
    null,
  );
  const [lineageRefresh, setLineageRefresh] = useState(0);
  const [urlState, setUrlState] = useState(() =>
    readPipelineUrlState(window.location.search),
  );
  const [selectionBusy, setSelectionBusy] = useState(false);
  const workspaceLoadIdentityRef = useRef<string | null>(null);

  const loadWorkspace = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const backendStageKey = stageKey === "virtual_scenes" ? null : stageKey;
        const response = await client.getRecordingPipeline(
          recordingId,
          {
            signal,
          },
          backendStageKey ?? "events",
        );
        if (!signal?.aborted) {
          if (isPipelineWorkspace(response)) {
            setWorkspace(response);
            setLoadedStageKey(stageKey ?? "events");
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
    if (workspace !== null && loadedStageKey === (stageKey ?? "events")) {
      return;
    }
    const loadIdentity = `${recordingId}:${stageKey ?? "events"}`;
    if (workspaceLoadIdentityRef.current === loadIdentity) {
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      if (workspaceLoadIdentityRef.current === loadIdentity) return;
      workspaceLoadIdentityRef.current = loadIdentity;
      void loadWorkspace(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadWorkspace, loadedStageKey, recordingId, stageKey, workspace]);

  useEffect(() => {
    const updateUrlState = () => {
      setUrlState(readPipelineUrlState(window.location.search));
    };
    window.addEventListener("popstate", updateUrlState);
    return () => window.removeEventListener("popstate", updateUrlState);
  }, []);

  useEffect(() => {
    const selection =
      urlState.lineage === null
        ? null
        : decodeLineageSelection(urlState.lineage);
    const controller = new AbortController();
    void fetch(
      `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/lineage`,
      {
        signal: controller.signal,
      },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error("Lineage data could not be loaded.");
        const graph: unknown = await response.json();
        if (!isPipelineLineageGraph(graph)) {
          throw new Error("The backend returned invalid lineage data.");
        }
        return graph;
      })
      .then((graph) => {
        if (controller.signal.aborted) return;
        setLineageGraph(graph);
        setLineageGraphError(null);
        if (selection === null || urlState.lineage === null) {
          setLineageValidation(null);
          return;
        }
        const missing = validateLineageSelection(selection, graph);
        setLineageValidation({
          lineage: urlState.lineage as string,
          notice:
            missing.length === 0
              ? null
              : "The saved lineage selection is unavailable. No other revision was selected.",
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setLineageGraph(null);
          setLineageGraphError("Lineage data could not be loaded.");
          if (urlState.lineage !== null) {
            setLineageValidation({
              lineage: urlState.lineage,
              notice:
                "Lineage data could not be loaded. The saved selection was not changed.",
            });
          }
        }
      });
    return () => controller.abort();
  }, [lineageRefresh, recordingId, urlState.lineage]);

  useEffect(() => {
    if (urlState.frameReviewQueue !== "0096-M4" || stageKey !== "visible_cards")
      return;
    const saveReview = (event: Event) => {
      const detail = (
        event as CustomEvent<{
          itemId: string;
          nodeId: string;
          revisionId: string;
          reviewId: string;
        }>
      ).detail;
      if (
        detail === undefined ||
        !detail.itemId ||
        !detail.nodeId ||
        !detail.revisionId ||
        !detail.reviewId
      )
        return;
      void (async () => {
        try {
          const page = await client.getFrameReviewPage({ limit: 1, cursor: 0 });
          await client.updateFrameReviewWorkflow(recordingId, detail.itemId, {
            queue_digest: page.queue_digest,
            action: "save_review",
            node_id: detail.nodeId,
            revision_id: detail.revisionId,
            review_id: detail.reviewId,
          });
          await loadWorkspace();
          window.dispatchEvent(new Event("frame-review-progress-updated"));
        } catch (reason) {
          setNotice(
            reason instanceof Error
              ? `Review progress was not recorded: ${reason.message}`
              : "Review progress was not recorded. The frame remains pending.",
          );
        }
      })();
    };
    window.addEventListener("frame-review-node-reviewed", saveReview);
    return () =>
      window.removeEventListener("frame-review-node-reviewed", saveReview);
  }, [client, loadWorkspace, recordingId, stageKey, urlState.frameReviewQueue]);

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

  const workspaceReadyForStage =
    workspace !== null && loadedStageKey === (stageKey ?? "events");
  const activeWorkspace = workspaceReadyForStage ? workspace : null;
  const backendStageKey = stageKey === "virtual_scenes" ? null : stageKey;
  const stage = activeWorkspace?.stages.find(
    (candidate) =>
      candidate.key ===
      (stageKey === "virtual_scenes" ? "visible_cards" : backendStageKey),
  );

  useEffect(() => {
    if (
      activeWorkspace === null ||
      stage === undefined ||
      stageKey === null ||
      stageKey === "virtual_scenes"
    ) {
      return;
    }
    const sanitized = sanitizeUrlState(
      urlState,
      stage,
      activeWorkspace.video.duration_us,
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
  }, [activeWorkspace, compare, recordingId, stage, stageKey, urlState]);

  async function selectGeneratedRevision(
    nextRevisionId: string | null,
  ): Promise<void> {
    if (stage === undefined || stage.key === "round_analyses") return;
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
      setNotice("Processor input revision selected.");
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        await loadWorkspace();
        setNotice(
          "The processor input changed elsewhere. The winning selection is shown.",
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

  const copyLineageNode = useCallback(
    async (
      column: LineageStageKey,
      nodeId: string,
      revisionId: string,
    ): Promise<void> => {
      const response = await fetch(
        `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/copy`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            revision_id: revisionId,
            idempotency_key: crypto.randomUUID(),
            actor: { kind: "human", id: "workspace-operator" },
            reason: "user_requested_copy",
          }),
        },
      );
      if (!response.ok) {
        throw new Error(
          response.status === 409
            ? "This revision changed. Reload lineage and try again."
            : "The copy could not be created.",
        );
      }
      const result: unknown = await response.json();
      if (
        result === null ||
        typeof result !== "object" ||
        !("node_id" in result) ||
        typeof result.node_id !== "string" ||
        !("revision_id" in result) ||
        typeof result.revision_id !== "string" ||
        !("name" in result) ||
        typeof result.name !== "string"
      ) {
        throw new Error("The backend returned invalid copy data.");
      }
      const sourceName =
        lineageGraph?.nodes.find((node) => node.node_id === nodeId)?.name ??
        "selected data";
      const nextSelection = {
        schema_version: "pipeline-lineage-selection/v1" as const,
        selected: {
          ...(urlState.lineage === null
            ? {}
            : (decodeLineageSelection(urlState.lineage)?.selected ?? {})),
          [column]: {
            node_id: result.node_id,
            revision_id: result.revision_id,
          },
        },
      };
      setNotice(
        `Created ${result.name} from ${sourceName}. You can return to the original in lineage.`,
      );
      setLineageRefresh((value) => value + 1);
      navigateTo(
        recordingPipelineNavigationPath(recordingId, stageKey ?? "events", {
          ...urlState,
          lineage: JSON.stringify(nextSelection),
          left: null,
          right: null,
          reference: null,
        }),
      );
    },
    [lineageGraph, navigateTo, recordingId, stageKey, urlState],
  );

  const replaceUrlState = useCallback(
    (nextState: PipelineUrlState): void => {
      const nextPath = compare
        ? recordingPipelineComparePath(
            recordingId,
            backendStageKey ?? "events",
            nextState,
          )
        : recordingPipelineNavigationPath(
            recordingId,
            stageKey ?? "events",
            nextState,
          );
      window.history.replaceState({}, "", nextPath);
      setUrlState(nextState);
    },
    [backendStageKey, compare, recordingId, stageKey],
  );

  const presentation = buildRecordingWorkspacePresentation({
    workspace: activeWorkspace,
    stageKey: backendStageKey,
    compare,
    urlState,
    error,
    loading: loading || !workspaceReadyForStage,
  });
  const action =
    presentation.inspector.primaryAction ??
    (stage === undefined ? null : primaryActionForStage(stage));
  const actionState =
    stage === undefined || action === null
      ? urlState
      : actionStateForStage(stage, urlState, action.kind);
  const pinnedVisibleCardRevision =
    urlState.lineage === null
      ? null
      : (decodeLineageSelection(urlState.lineage)?.selected.visible_cards
          ?.revision_id ?? null);
  const workspaceRail = useRecordingWorkspaceRail({
    recordingId,
    stage,
    stageKey: backendStageKey,
    compare,
    urlState,
    durationUs: activeWorkspace?.video.duration_us ?? 0,
    rail: presentation.rail,
    onReplaceUrlState: replaceUrlState,
  });

  if (!workspaceReadyForStage && error === null) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.loading} role="status">
          Loading recording pipeline…
        </p>
      </main>
    );
  }
  if (activeWorkspace === null) {
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
    stageKey !== "virtual_scenes" &&
    (stage.key === "visible_cards" || stage.key === "visual_identities") &&
    !compare;
  const cardRailLabel =
    stage.key === "visual_identities"
      ? "Visual identity cards"
      : "Visible-card proposals";
  const selectedVirtualScene = (() => {
    if (stageKey !== "virtual_scenes" || urlState.lineage === null) return null;
    const selection = decodeLineageSelection(urlState.lineage);
    const reference = selection?.selected.virtual_scenes;
    if (reference === undefined || lineageGraph === null) return null;
    const node = lineageGraph.nodes.find(
      (candidate) =>
        candidate.node_id === reference.node_id &&
        (candidate.content_type === "card_scene_proposals" ||
          candidate.content_type === "virtual_scenes"),
    );
    const revisionExists = lineageGraph.revisions.some(
      (revision) =>
        revision.node_id === reference.node_id &&
        revision.revision_id === reference.revision_id,
    );
    return node !== undefined && revisionExists
      ? {
          name: node.name,
          nodeId: reference.node_id,
          contentType: node.content_type,
          revisionId: reference.revision_id,
        }
      : null;
  })();
  const currentLineageNotice =
    urlState.lineage !== null &&
    decodeLineageSelection(urlState.lineage) === null
      ? "The saved lineage selection is invalid. No other revision was selected."
      : lineageValidation?.lineage === urlState.lineage
        ? lineageValidation.notice
        : null;

  return (
    <main
      className={`${styles.shell} ${styles.recordingsPage} ${styles.pipelinePage} ${styles.pipelineViewport}`}
    >
      <RecordingWorkspaceShell
        recordingId={recordingId}
        workspace={activeWorkspace}
        navigationStep={stageKey}
        urlState={urlState}
        notice={currentLineageNotice ?? notice}
        error={error}
        lineageGraph={lineageGraph}
        lineageGraphError={lineageGraphError}
        onCopyNode={copyLineageNode}
        onNavigate={navigateTo}
      />
      {urlState.frameReviewQueue === "0096-M4" &&
      stage.key === "visible_cards" ? (
        <FrameReviewEditorNavigation
          recordingId={recordingId}
          itemId={urlState.item}
        />
      ) : null}
      {urlState.frameReviewQueue === "0096-M4" &&
      stage.key === "visible_cards" ? (
        <FrameReviewPinnedRevisionNotice
          pinnedRevision={pinnedVisibleCardRevision}
          selectedRevision={pinnedVisibleCardRevision}
        />
      ) : null}

      {stageKey === "virtual_scenes" ? (
        <section
          className={styles.pipelineWorkspaceGrid}
          aria-label="Virtual scenes"
          data-slot="center"
        >
          <h2>Virtual scenes</h2>
          {selectedVirtualScene === null ? (
            <p>No virtual scene is selected for this lineage.</p>
          ) : selectedVirtualScene.contentType !== "virtual_scenes" ? (
            <p>
              {selectedVirtualScene.name} · revision{" "}
              {selectedVirtualScene.revisionId} is a processor proposal. It is
              read-only here. Select a virtual-scene data set to edit poses or
              stacking order.
            </p>
          ) : (
            <PipelineNodeVirtualSceneEditor
              key={`${selectedVirtualScene.nodeId}:${selectedVirtualScene.revisionId}`}
              recordingId={recordingId}
              nodeId={selectedVirtualScene.nodeId}
              revisionId={selectedVirtualScene.revisionId}
              selectionItemId={urlState.item}
              onPositionChange={(itemId, timeUs) =>
                navigateTo(
                  recordingPipelineNavigationPath(recordingId, stageKey, {
                    ...urlState,
                    item: itemId,
                    ...(timeUs === null ? {} : { t_us: timeUs }),
                  }),
                )
              }
              onRevisionChange={(
                sourceNodeId,
                sourceRevisionId,
                nodeId,
                revisionId,
                frameId,
                timeUs,
              ) => {
                const lineage = decodeLineageSelection(urlState.lineage ?? "");
                const selected = lineage?.selected.virtual_scenes;
                if (
                  lineage === null ||
                  selected?.node_id !== sourceNodeId ||
                  selected.revision_id !== sourceRevisionId
                )
                  return;
                navigateTo(
                  recordingPipelineNavigationPath(recordingId, stageKey, {
                    ...urlState,
                    lineage: JSON.stringify({
                      ...lineage,
                      selected: {
                        ...lineage.selected,
                        virtual_scenes: {
                          node_id: nodeId,
                          revision_id: revisionId,
                        },
                      },
                    }),
                    item: frameId,
                    ...(timeUs === null ? {} : { t_us: timeUs }),
                  }),
                );
              }}
            />
          )}
        </section>
      ) : (
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
            workspace={activeWorkspace}
            stage={stage}
            compare={compare}
            urlState={urlState}
            presentation={presentation}
            onNavigate={navigateTo}
            onEventRailItemsChange={workspaceRail.handleEventRailItemsChange}
            onComparisonRailItemsChange={
              workspaceRail.handleComparisonRailItemsChange
            }
            onComparisonChange={workspaceRail.handleComparisonChange}
            onTimeChange={workspaceRail.handleRailTimeChange}
            onAnalysisChange={(analysisId) =>
              navigateTo(
                recordingPipelineNavigationPath(recordingId, "round_analyses", {
                  ...urlState,
                  analysis: analysisId,
                }),
              )
            }
            lineageGraph={lineageGraph}
          />
          <RecordingWorkspaceInspector
            recordingId={recordingId}
            workspace={activeWorkspace}
            stage={stage}
            compare={compare}
            urlState={urlState}
            action={action}
            actionState={actionState}
            presentation={presentation}
            comparison={workspaceRail.comparison}
            onNavigate={navigateTo}
            onReplaceUrlState={replaceUrlState}
            selectionBusy={selectionBusy}
            onSelectGeneratedRevision={selectGeneratedRevision}
            onRefresh={() => loadWorkspace()}
          />
        </div>
      )}

      {stageKey === "virtual_scenes" ? null : (
        <RecordingWorkspaceTimelineRail
          recordingId={recordingId}
          stage={stage}
          compare={compare}
          rail={workspaceRail.visibleRail}
          onTimeChange={workspaceRail.handleRailTimeChange}
          onItemSelect={workspaceRail.handleRailItemSelect}
        />
      )}
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
  const validRunIds = new Set(stage.runs.map((run) => run.run_id));
  const validReferenceIds = new Set(
    stage.input_options
      .filter(
        (option) => option.origin === "manual" || option.origin === "corrected",
      )
      .map((option) => option.revision_id),
  );
  const selectedReference = stage.selected_completed_reference_revision_id;
  return {
    ...state,
    item:
      state.item !== null &&
      (isKnownItem(stage, state.item) ||
        (stage.key === "table_observations" &&
          state.lineage !== null &&
          decodeLineageSelection(state.lineage)?.selected.table_observations !==
            undefined))
        ? state.item
        : null,
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
      !compare && state.analysis !== null
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

function isPipelineLineageGraph(value: unknown): value is PipelineLineageGraph {
  return (
    typeof value === "object" &&
    value !== null &&
    "schema_version" in value &&
    value.schema_version === "pipeline-lineage-graph/v1" &&
    "nodes" in value &&
    Array.isArray(value.nodes) &&
    "revisions" in value &&
    Array.isArray(value.revisions) &&
    "runs" in value &&
    Array.isArray(value.runs) &&
    "artifacts" in value &&
    Array.isArray(value.artifacts) &&
    "edges" in value &&
    Array.isArray(value.edges)
  );
}
