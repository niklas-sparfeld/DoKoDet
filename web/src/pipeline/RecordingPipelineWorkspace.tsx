import { useCallback, useEffect, useMemo, useState } from "react";

import { createFrameReviewClient } from "../api/frameReviewClient";
import { createPipelineProcessingClient } from "../api/pipelineProcessingClient";
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
} from "./recordingPipelineUrl";
import { decodeLineageSelection } from "./pipelineLineageSelection";
import type { LineageStageKey } from "./pipelineLineageSelection";
import {
  primaryActionForStage,
  buildRecordingWorkspacePresentation,
} from "./recordingWorkspacePresentation";
import { actionStateForStage } from "./recordingWorkspaceNavigation";
import {
  chooseInitialStage,
  sanitizeUrlState,
} from "./recordingPipelineSelection";
import { useRecordingPipelineData } from "./useRecordingPipelineData";
import {
  useRecordingPipelineSelection,
  useRecordingPipelineUrlState,
} from "./useRecordingPipelineSelection";
import {
  FrameReviewEditorNavigation,
  FrameReviewPinnedRevisionNotice,
} from "../frameReview/FrameReviewQueueView";

export type { PipelineStageKey } from "../api/pipelineContracts";
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

export function RecordingPipelineWorkspace({
  recordingId,
  stageKey,
  compare,
}: {
  recordingId: string;
  stageKey: PipelineNavigationStepKey | null;
  compare: boolean;
}) {
  const client = useMemo(
    () => ({
      ...createFrameReviewClient(),
      ...createPipelineProcessingClient(),
    }),
    [],
  );
  const [notice, setNotice] = useState<string | null>(null);
  const { urlState, setUrlState } = useRecordingPipelineUrlState();
  const data = useRecordingPipelineData(
    recordingId,
    stageKey,
    urlState.lineage,
    client,
  );

  const {
    workspace,
    loadedStageKey,
    loading,
    error,
    loadWorkspace,
    lineageValidation,
    lineageGraph,
    lineageGraphError,
    setWorkspace,
    refreshLineage,
  } = data;

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
    if (
      workspace === null ||
      workspace.recording_id !== recordingId ||
      stageKey !== null ||
      compare
    ) {
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
    workspace !== null &&
    workspace.recording_id === recordingId &&
    loadedStageKey === (stageKey ?? "events");
  const activeWorkspace = workspaceReadyForStage ? workspace : null;
  const backendStageKey = stageKey === "virtual_scenes" ? null : stageKey;
  const stage = activeWorkspace?.stages.find(
    (candidate) =>
      candidate.key ===
      (stageKey === "virtual_scenes" ? "visible_cards" : backendStageKey),
  );

  const selection = useRecordingPipelineSelection({
    recordingId,
    stageKey,
    compare,
    backendStageKey,
    stage,
    setWorkspace,
    loadWorkspace,
    client,
    setNotice,
    urlState,
    setUrlState,
  });
  const {
    selectionBusy,
    navigateTo,
    replaceUrlState,
    selectGeneratedRevision,
  } = selection;

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
      refreshLineage();
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
    [lineageGraph, navigateTo, recordingId, refreshLineage, stageKey, urlState],
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
    stageKey !== "virtual_scenes" && stage.key === "visible_cards" && !compare;
  const cardRailLabel = "Visible-card proposals";
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
        onOpenLineage={refreshLineage}
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
            <div data-visible-card-proposal-slot="proposals" />
          </aside>
        ) : null}
        <RecordingWorkspaceTaskSurface
          recordingId={recordingId}
          navigationStep={stageKey}
          workspace={activeWorkspace}
          stage={stage}
          compare={compare}
          urlState={urlState}
          presentation={presentation}
          onNavigate={navigateTo}
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
          navigationStep={stageKey}
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
      {
        <RecordingWorkspaceTimelineRail
          recordingId={recordingId}
          navigationStep={stageKey}
          stage={stage}
          compare={compare}
          rail={workspaceRail.visibleRail}
          onTimeChange={workspaceRail.handleRailTimeChange}
          onItemSelect={workspaceRail.handleRailItemSelect}
        />
      }
    </main>
  );
}
