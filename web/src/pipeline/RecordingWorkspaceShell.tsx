import { useState } from "react";

import type {
  PipelineComparisonResponse,
  PipelineWorkspace,
  PipelineWorkspaceStage,
} from "../api/client";
import type { PipelineCardEventRailItem } from "../cardEvents/PipelineCardEventRailItem";
import { PipelineNodeEventEditor } from "../cardEvents/PipelineNodeEventEditor";
import { PipelineNodeVisibleCardEditor } from "../visibleCards/PipelineNodeVisibleCardEditor";
import { PipelineNodeVisualIdentityEditor } from "../visualIdentities/PipelineNodeVisualIdentityEditor";
import styles from "../App.module.css";
import { Toast } from "../Toast";
import { ComparisonView } from "./ComparisonView";
import { PipelineObservationWorkbench } from "./PipelineObservationWorkbench";
import { PipelineRoundAnalysisWorkbench } from "./PipelineRoundAnalysisWorkbench";
import {
  recordingPipelineNavigationPath,
  type PipelineUrlState,
  type PipelineNavigationStepKey,
} from "./recordingPipelineUrl";
import { readPipelineUrlState } from "./recordingPipelineUrl";
import type { PipelineLineageGraph } from "./pipelineLineageSelection";
import { decodeLineageSelection } from "./pipelineLineageSelection";
import { isModifiedClick } from "./recordingWorkspaceNavigation";
import { formatDuration } from "./recordingWorkspaceFormatting";
import type {
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
  presentation: RecordingWorkspacePresentation;
  onNavigate: (path: string) => void;
  onEventRailItemsChange: (items: PipelineCardEventRailItem[]) => void;
  onComparisonRailItemsChange: (items: RecordingTimelineRailItem[]) => void;
  onComparisonChange: (comparison: PipelineComparisonResponse) => void;
  onTimeChange: (timeUs: number) => void;
  onAnalysisChange?: (analysisId: string) => void;
  onNotice?: (message: string) => void;
  lineageGraph?: PipelineLineageGraph | null;
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
  const contentTypeByStep: Partial<
    Record<PipelineNavigationStepKey, readonly string[]>
  > = {
    events: ["events"],
    visible_cards: ["visible_cards"],
    virtual_scenes: ["card_scene_proposals", "virtual_scenes"],
    visual_identities: ["visual_identities"],
    table_observations: ["table_observations"],
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
                          (item.node_id === reference.node_id &&
                            contentTypeByStep[step.key]?.includes(
                              item.content_type,
                            )) ??
                          false,
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
                  ...(nextSelection.selected.table_observations !==
                  lineageSelection?.selected.table_observations
                    ? { item: null, tUs: null }
                    : {}),
                  left: null,
                  right: null,
                  reference: null,
                },
              );
              onNavigate(path);
            }}
            onCopy={onCopyNode}
            selectedAnalysisId={urlState.analysis}
            onSelectAnalysis={(analysisId) => {
              const path = recordingPipelineNavigationPath(
                recordingId,
                "round_analyses",
                {
                  ...urlState,
                  analysis: analysisId,
                  left: null,
                  right: null,
                  reference: null,
                },
              );
              onNavigate(path);
            }}
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
  presentation,
  onNavigate,
  onEventRailItemsChange,
  onComparisonRailItemsChange,
  onComparisonChange,
  onTimeChange,
  onAnalysisChange,
  onNotice,
  lineageGraph = null,
}: RecordingWorkspaceTaskSurfaceProps) {
  const selectedEventNode =
    urlState.lineage === null
      ? undefined
      : decodeLineageSelection(urlState.lineage)?.selected.events;
  const selectedVisibleCardNode =
    urlState.lineage === null
      ? undefined
      : decodeLineageSelection(urlState.lineage)?.selected.visible_cards;
  const selectedVisualIdentity =
    urlState.lineage === null
      ? undefined
      : decodeLineageSelection(urlState.lineage)?.selected.visual_identities;
  const selectedVisualIdentityNode =
    selectedVisualIdentity === undefined
      ? undefined
      : lineageGraph?.nodes.find(
          (node) =>
            node.node_id === selectedVisualIdentity.node_id &&
            node.content_type === "visual_identities",
        );
  const selectedObservationNode =
    urlState.lineage === null
      ? undefined
      : decodeLineageSelection(urlState.lineage)?.selected.table_observations;
  const selectedObservationDataNode =
    selectedObservationNode === undefined
      ? undefined
      : lineageGraph?.nodes.find(
          (node) =>
            node.node_id === selectedObservationNode.node_id &&
            node.content_type === "table_observations",
        );

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
            onAnalysisChange={onAnalysisChange}
          />
        ) : null}
        {stage.key === "events" &&
        !compare &&
        selectedEventNode !== undefined ? (
          <PipelineNodeEventEditor
            key={`${selectedEventNode.node_id}:${selectedEventNode.revision_id}`}
            recordingId={recordingId}
            nodeId={selectedEventNode.node_id}
            revisionId={selectedEventNode.revision_id}
            durationUs={workspace.video.duration_us}
            sourceSha256={workspace.video.video_sha256}
            portalToInspector
            selectionItemId={presentation.surface.selectedItemId ?? null}
            selectionTimeUs={presentation.inspector.selection?.timeUs ?? null}
            onRailItemsChange={onEventRailItemsChange}
            onNotice={onNotice}
            onPositionChange={(itemId, timeUs) =>
              onNavigate(
                recordingPipelineNavigationPath(recordingId, stage.key, {
                  ...urlState,
                  item: itemId,
                  tUs: timeUs,
                }),
              )
            }
            onRevisionChange={(
              sourceNodeId,
              sourceRevisionId,
              nodeId,
              revisionId,
              itemId,
              timeUs,
            ) => {
              const currentUrlState = readPipelineUrlState(
                window.location.search,
              );
              const currentLineage =
                currentUrlState.lineage === null
                  ? null
                  : decodeLineageSelection(currentUrlState.lineage);
              const currentEventNode = currentLineage?.selected.events;
              if (
                currentEventNode?.node_id !== sourceNodeId ||
                currentEventNode.revision_id !== sourceRevisionId
              )
                return;
              const lineage = decodeLineageSelection(urlState.lineage ?? "");
              if (lineage === null) return;
              onNavigate(
                recordingPipelineNavigationPath(recordingId, stage.key, {
                  ...urlState,
                  lineage: JSON.stringify({
                    ...lineage,
                    selected: {
                      ...lineage.selected,
                      events: { node_id: nodeId, revision_id: revisionId },
                    },
                  }),
                  item: itemId,
                  tUs: timeUs,
                }),
              );
            }}
          />
        ) : null}
        {stage.key === "events" &&
        !compare &&
        selectedEventNode === undefined ? (
          <div aria-hidden="true" />
        ) : null}
        {stage.key === "visible_cards" &&
        !compare &&
        selectedVisibleCardNode !== undefined ? (
          <PipelineNodeVisibleCardEditor
            key={`${selectedVisibleCardNode.node_id}:${selectedVisibleCardNode.revision_id}`}
            recordingId={recordingId}
            nodeId={selectedVisibleCardNode.node_id}
            revisionId={selectedVisibleCardNode.revision_id}
            selectionItemId={presentation.surface.selectedItemId ?? null}
            selectionTimeUs={presentation.inspector.selection?.timeUs ?? null}
            onPositionChange={(itemId, timeUs) =>
              onNavigate(
                recordingPipelineNavigationPath(recordingId, stage.key, {
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
              itemId,
              timeUs,
            ) => {
              const currentUrlState = readPipelineUrlState(
                window.location.search,
              );
              const currentLineage =
                currentUrlState.lineage === null
                  ? null
                  : decodeLineageSelection(currentUrlState.lineage);
              const selected = currentLineage?.selected.visible_cards;
              if (
                selected?.node_id !== sourceNodeId ||
                selected.revision_id !== sourceRevisionId
              )
                return;
              const lineage = decodeLineageSelection(urlState.lineage ?? "");
              if (lineage === null) return;
              onNavigate(
                recordingPipelineNavigationPath(recordingId, stage.key, {
                  ...urlState,
                  lineage: JSON.stringify({
                    ...lineage,
                    selected: {
                      ...lineage.selected,
                      visible_cards: {
                        node_id: nodeId,
                        revision_id: revisionId,
                      },
                    },
                  }),
                  item: itemId,
                  ...(timeUs === null ? {} : { t_us: timeUs }),
                }),
              );
            }}
          />
        ) : null}
        {stage.key === "visible_cards" &&
        !compare &&
        selectedVisibleCardNode === undefined ? (
          <p role="status">
            Select a Visible cards data set in the lineage drawer.
          </p>
        ) : null}
        {stage.key === "visual_identities" &&
        !compare &&
        selectedVisualIdentityNode !== undefined &&
        selectedVisualIdentity !== undefined ? (
          <PipelineNodeVisualIdentityEditor
            key={`${selectedVisualIdentity.node_id}:${selectedVisualIdentity.revision_id}`}
            recordingId={recordingId}
            nodeId={selectedVisualIdentity.node_id}
            revisionId={selectedVisualIdentity.revision_id}
            selectionItemId={presentation.surface.selectedItemId ?? null}
            onPositionChange={(itemId, timeUs) =>
              onNavigate(
                recordingPipelineNavigationPath(recordingId, stage.key, {
                  ...urlState,
                  item: itemId,
                  tUs: timeUs,
                }),
              )
            }
            onRevisionChange={(
              sourceNodeId,
              sourceRevisionId,
              nodeId,
              revisionId,
              itemId,
              timeUs,
            ) => {
              const lineage = decodeLineageSelection(urlState.lineage ?? "");
              if (
                lineage?.selected.visual_identities?.node_id !== sourceNodeId ||
                lineage.selected.visual_identities.revision_id !==
                  sourceRevisionId
              )
                return;
              onNavigate(
                recordingPipelineNavigationPath(recordingId, stage.key, {
                  ...urlState,
                  lineage: JSON.stringify({
                    ...lineage,
                    selected: {
                      ...lineage.selected,
                      visual_identities: {
                        node_id: nodeId,
                        revision_id: revisionId,
                      },
                    },
                  }),
                  item: itemId,
                  tUs: timeUs,
                }),
              );
            }}
          />
        ) : null}
        {stage.key === "visual_identities" &&
        !compare &&
        selectedVisualIdentityNode === undefined ? (
          <p role="status">
            Select a Visual identities data set in the lineage drawer.
          </p>
        ) : null}
        {stage.key === "table_observations" && !compare ? (
          <PipelineObservationWorkbench
            recordingId={recordingId}
            stage={stage}
            selectedItemId={presentation.surface.selectedItemId}
            selectedNode={
              selectedObservationDataNode === undefined ||
              selectedObservationNode === undefined
                ? null
                : {
                    nodeId: selectedObservationNode.node_id,
                    revisionId: selectedObservationNode.revision_id,
                  }
            }
            lineageGraph={lineageGraph}
            onSelectNodeObservation={(itemId, timeUs) =>
              onNavigate(
                recordingPipelineNavigationPath(recordingId, stage.key, {
                  ...urlState,
                  item: itemId,
                  tUs: timeUs,
                }),
              )
            }
          />
        ) : null}
      </div>
    </section>
  );
}
