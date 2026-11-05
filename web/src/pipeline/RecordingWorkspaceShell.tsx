import { useState } from "react";

import type {
  PipelineComparisonResponse,
  PipelineWorkspace,
  PipelineWorkspaceStage,
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
import { Toast } from "../Toast";
import { ComparisonView } from "./ComparisonView";
import { PipelineObservationWorkbench } from "./PipelineObservationWorkbench";
import { PipelineRoundAnalysisWorkbench } from "./PipelineRoundAnalysisWorkbench";
import {
  recordingPipelineNavigationPath,
  type PipelineUrlState,
  type PipelineView,
  type PipelineNavigationStepKey,
} from "./recordingPipelineUrl";
import { readPipelineUrlState } from "./recordingPipelineUrl";
import type { PipelineLineageGraph } from "./pipelineLineageSelection";
import { decodeLineageSelection } from "./pipelineLineageSelection";
import { actionHref, isModifiedClick } from "./recordingWorkspaceNavigation";
import { formatDuration } from "./recordingWorkspaceFormatting";
import type {
  PipelinePrimaryAction,
  RecordingTimelineRailItem,
  RecordingWorkspacePresentation,
} from "./recordingWorkspacePresentation";
import { STAGE_LABELS } from "./recordingWorkspacePresentation";
import shellStyles from "./RecordingWorkspaceShell.module.css";
import { ProfileControl } from "../profile/ProfileControl";
import { PipelineLineageDrawer } from "./PipelineLineageDrawer";

export type RecordingWorkspaceShellProps = {
  recordingId: string;
  workspace: PipelineWorkspace;
  navigationStep: PipelineNavigationStepKey;
  urlState: PipelineUrlState;
  notice: string | null;
  error: string | null;
  lineageGraph: PipelineLineageGraph | null;
  lineageGraphError: string | null;
  onCopyNode: (
    column: Exclude<PipelineNavigationStepKey, "round_analyses">,
    nodeId: string,
    revisionId: string,
  ) => Promise<void>;
  onNavigate: (path: string) => void;
};

export type RecordingWorkspaceTaskSurfaceProps = {
  recordingId: string;
  workspace: PipelineWorkspace;
  stage: PipelineWorkspaceStage;
  compare: boolean;
  urlState: PipelineUrlState;
  activeView: PipelineView;
  displayedRevision: string | null;
  action: PipelinePrimaryAction;
  presentation: RecordingWorkspacePresentation;
  selectedEventRunId: string | null;
  selectedVisibleCardRunId: string | null;
  selectedVisualIdentityRunId: string | null;
  onNavigate: (path: string) => void;
  onEventRailItemsChange: (items: PipelineCardEventRailItem[]) => void;
  onVisibleCardRailItemsChange: (items: PipelineVisibleCardRailItem[]) => void;
  onVisualIdentityRailItemsChange: (
    items: PipelineVisualIdentityRailItem[],
  ) => void;
  onComparisonRailItemsChange: (items: RecordingTimelineRailItem[]) => void;
  onComparisonChange: (comparison: PipelineComparisonResponse) => void;
  onTimeChange: (timeUs: number) => void;
};

export function RecordingWorkspaceShell({
  recordingId,
  workspace,
  navigationStep,
  urlState,
  notice,
  error,
  lineageGraph,
  lineageGraphError,
  onCopyNode,
  onNavigate,
}: RecordingWorkspaceShellProps) {
  const [lineageOpen, setLineageOpen] = useState(false);
  const lineageSelection =
    urlState.lineage === null ? null : decodeLineageSelection(urlState.lineage);
  const steps: Array<{ key: PipelineNavigationStepKey; label: string }> = [
    { key: "events", label: "Events" },
    { key: "visible_cards", label: "Visible cards" },
    { key: "virtual_scenes", label: "Virtual scenes" },
    { key: "visual_identities", label: "Visual identities" },
    { key: "table_observations", label: "Table observations" },
    { key: "round_analyses", label: "Round analysis" },
  ];
  const revisionByKey = new Map(
    (lineageGraph?.revisions ?? []).map((revision) => [
      JSON.stringify([revision.node_id, revision.revision_id]),
      revision,
    ]),
  );
  const contentTypeByStep: Partial<Record<PipelineNavigationStepKey, string>> =
    {
      events: "events",
      visible_cards: "visible_cards",
      virtual_scenes: "card_scene_proposals",
      visual_identities: "visual_identities",
      table_observations: "table_observations",
    };
  return (
    <>
      <div className={shellStyles.topSlot} data-slot="top">
        <header className={shellStyles.topBar} role="banner">
          <h1 className={styles.visuallyHidden}>Recording pipeline</h1>
          <a className={shellStyles.backLink} href="/recordings">
            <span aria-hidden="true">←</span> Back to recordings
          </a>
          <div className={shellStyles.recordingContext}>
            <span className={styles.statusLabel}>Recording</span>
            <strong title={recordingId}>{recordingId}</strong>
            <span>{formatDuration(workspace.video.duration_us)}</span>
          </div>
          <nav
            className={shellStyles.stepNavigation}
            aria-label="Recording pipeline steps"
          >
            <ol className={shellStyles.stageNavigation}>
              {steps.map((step) => {
                const reference =
                  step.key === "round_analyses"
                    ? undefined
                    : lineageSelection?.selected[step.key];
                const node =
                  reference === undefined
                    ? undefined
                    : lineageGraph?.nodes.find(
                        (item) =>
                          item.node_id === reference.node_id &&
                          item.content_type === contentTypeByStep[step.key],
                      );
                const revision =
                  reference === undefined
                    ? undefined
                    : revisionByKey.get(
                        JSON.stringify([
                          reference.node_id,
                          reference.revision_id,
                        ]),
                      );
                const selectedNode = node;
                const path = recordingPipelineNavigationPath(
                  recordingId,
                  step.key,
                  {
                    ...urlState,
                    left: null,
                    right: null,
                    reference: null,
                    analysis: null,
                  },
                );
                const isActive = step.key === navigationStep;
                return (
                  <li key={step.key}>
                    <a
                      aria-current={isActive ? "page" : undefined}
                      className={
                        isActive
                          ? shellStyles.stageLinkActive
                          : shellStyles.stageLink
                      }
                      href={path}
                      onClick={(event) => {
                        if (isModifiedClick(event)) {
                          return;
                        }
                        event.preventDefault();
                        onNavigate(path);
                      }}
                    >
                      <span>{step.label}</span>
                    </a>
                    <div
                      className={shellStyles.dataRow}
                      aria-label={`${step.label} data`}
                    >
                      {selectedNode !== undefined && revision !== undefined ? (
                        <>
                          <strong title={selectedNode.name}>
                            {selectedNode.name}
                          </strong>
                          <span>r {reference?.revision_id}</span>
                          <small>Selected</small>
                        </>
                      ) : step.key === "round_analyses" &&
                        urlState.analysis !== null ? (
                        <>
                          <strong>Analysis {urlState.analysis}</strong>
                          <span>Exact analysis</span>
                          <small>Selected</small>
                        </>
                      ) : (
                        <>
                          <strong>No data set selected</strong>
                          <span>—</span>
                          <small>Empty</small>
                        </>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
            <button
              aria-controls="pipeline-lineage-drawer"
              aria-expanded={lineageOpen}
              className={shellStyles.lineageToggle}
              onClick={() => setLineageOpen((open) => !open)}
              type="button"
            >
              {lineageOpen ? "Hide lineage" : "Show lineage"}
            </button>
          </nav>
          <ProfileControl />
        </header>

        {lineageOpen ? (
          <PipelineLineageDrawer
            id="pipeline-lineage-drawer"
            graph={lineageGraph}
            graphError={lineageGraphError}
            selection={lineageSelection}
            onSelect={(nextSelection) => {
              const path = recordingPipelineNavigationPath(
                recordingId,
                navigationStep,
                {
                  ...urlState,
                  lineage: JSON.stringify(nextSelection),
                  left: null,
                  right: null,
                  reference: null,
                },
              );
              onNavigate(path);
            }}
            onCopy={onCopyNode}
          />
        ) : null}

        {notice !== null ? <Toast message={notice} /> : null}
        {error !== null ? (
          <p className={styles.errorMessage} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </>
  );
}

export function RecordingWorkspaceTaskSurface({
  recordingId,
  workspace,
  stage,
  compare,
  urlState,
  activeView,
  displayedRevision,
  action,
  presentation,
  selectedEventRunId,
  selectedVisibleCardRunId,
  selectedVisualIdentityRunId,
  onNavigate,
  onEventRailItemsChange,
  onVisibleCardRailItemsChange,
  onVisualIdentityRailItemsChange,
  onComparisonRailItemsChange,
  onComparisonChange,
  onTimeChange,
}: RecordingWorkspaceTaskSurfaceProps) {
  const visibleCardStage = workspace.stages.find(
    (candidate) => candidate.key === "visible_cards",
  );
  const selectedVisibleCardRevisionId =
    visibleCardStage?.selected_completed_reference_revision_id ?? null;
  const selectedVisibleCardRevisionDigest =
    selectedVisibleCardRevisionId === null
      ? null
      : (visibleCardStage?.input_options.find(
          (option) => option.revision_id === selectedVisibleCardRevisionId,
        )?.content_sha256 ?? null);

  return (
    <section
      className={`${styles.pipelineTaskSurface} ${shellStyles.taskSurface} ${stage.key === "events" && !compare ? styles.pipelineEventTaskSurface : ""} ${(stage.key === "visible_cards" || stage.key === "visual_identities") && !compare ? styles.pipelineVisibleCardTaskSurface : ""} ${stage.key === "visible_cards" && !compare ? shellStyles.squareTaskSurface : ""}`}
      aria-label={`${STAGE_LABELS[stage.key]} task surface`}
      data-slot="center"
    >
      <div
        className={`${shellStyles.taskSurfaceContent} ${(stage.key === "visible_cards" || stage.key === "visual_identities") && !compare ? shellStyles.compactTaskSurfaceContent : ""} ${stage.key === "events" && !compare ? styles.pipelineEventTaskSurfaceContent : ""} ${(stage.key === "visible_cards" || stage.key === "visual_identities") && !compare ? styles.pipelineVisibleCardTaskSurfaceContent : ""} ${stage.key === "visible_cards" && !compare ? styles.pipelineVirtualTableTaskSurfaceContent : ""}`}
      >
        {compare ? (
          <ComparisonView
            recordingId={recordingId}
            stage={stage}
            durationUs={workspace.video.duration_us}
            urlState={urlState}
            onNavigate={onNavigate}
            onRailItemsChange={onComparisonRailItemsChange}
            onTimeChange={onTimeChange}
            onComparisonChange={onComparisonChange}
          />
        ) : null}
        {stage.key === "round_analyses" && !compare ? (
          <PipelineRoundAnalysisWorkbench
            recordingId={recordingId}
            stage={stage}
            selectedAnalysisId={
              presentation.inspector.selection?.analysisId ?? null
            }
            selectedTimeUs={presentation.inspector.selection?.timeUs ?? null}
            onTimeChange={onTimeChange}
          />
        ) : null}
        {stage.key === "events" && !compare ? (
          <PipelineCardEventEditor
            recordingId={recordingId}
            durationUs={workspace.video.duration_us}
            selectionItemId={presentation.surface.selectedItemId}
            selectionTimeUs={presentation.inspector.selection?.timeUs ?? null}
            generatedRevisionId={stage.selected_generated_revision_id ?? null}
            generatedRunId={selectedEventRunId}
            view={activeView}
            inspectorEnabled={action.kind !== "blocked"}
            onRailItemsChange={onEventRailItemsChange}
            onReviewRequested={() =>
              onNavigate(
                actionHref(
                  recordingId,
                  stage.key,
                  "review",
                  readPipelineUrlState(window.location.search),
                ),
              )
            }
          />
        ) : null}
        {stage.key === "visible_cards" && !compare ? (
          <PipelineVisibleCardEditor
            key={urlState.review ?? "maintained-reference"}
            recordingId={recordingId}
            durationUs={workspace.video.duration_us}
            selectionItemId={presentation.surface.selectedItemId}
            selectionTimeUs={presentation.inspector.selection?.timeUs ?? null}
            generatedRevisionId={stage.selected_generated_revision_id ?? null}
            displayedRevisionId={
              displayedRevision ?? stage.selected_generated_revision_id ?? null
            }
            generatedRunId={selectedVisibleCardRunId}
            startReviewRequested={urlState.startReview === "proposal"}
            reviewId={urlState.review}
            view={activeView}
            inspectorEnabled={action.kind !== "blocked"}
            onRailItemsChange={onVisibleCardRailItemsChange}
            onReviewRequested={() =>
              onNavigate(actionHref(recordingId, stage.key, "review", urlState))
            }
          />
        ) : null}
        {stage.key === "visual_identities" && !compare ? (
          <PipelineVisualIdentityEditor
            recordingId={recordingId}
            durationUs={workspace.video.duration_us}
            selectionItemId={presentation.surface.selectedItemId}
            selectionTimeUs={presentation.inspector.selection?.timeUs ?? null}
            generatedRevisionId={stage.selected_generated_revision_id ?? null}
            generatedRevisionIds={stage.input_options
              .filter((option) => option.origin === "processor")
              .map((option) => option.revision_id)}
            displayedRevisionId={
              displayedRevision ?? stage.selected_generated_revision_id ?? null
            }
            generatedRunId={selectedVisualIdentityRunId}
            selectedVisibleCardRevisionId={selectedVisibleCardRevisionId}
            selectedVisibleCardRevisionDigest={
              selectedVisibleCardRevisionDigest
            }
            view={activeView}
            inspectorEnabled={action.kind !== "blocked"}
            onRailItemsChange={onVisualIdentityRailItemsChange}
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
  );
}
