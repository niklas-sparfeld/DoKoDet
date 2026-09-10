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
import { ComparisonView } from "./ComparisonView";
import { PipelineObservationWorkbench } from "./PipelineObservationWorkbench";
import { PipelineRoundAnalysisWorkbench } from "./PipelineRoundAnalysisWorkbench";
import {
  recordingPipelinePath,
  type PipelineUrlState,
  type PipelineView,
} from "./recordingPipelineUrl";
import { actionHref, isModifiedClick } from "./recordingWorkspaceNavigation";
import {
  formatDuration,
  formatIdentifier,
} from "./recordingWorkspaceFormatting";
import type {
  PipelinePrimaryAction,
  RecordingTimelineRailItem,
  RecordingWorkspacePresentation,
} from "./recordingWorkspacePresentation";
import { STAGE_LABELS } from "./recordingWorkspacePresentation";
import { RecordingWorkspaceStatusBadge } from "./RecordingWorkspaceStatusBadge";
import shellStyles from "./RecordingWorkspaceShell.module.css";
import { ProfileControl } from "../profile/ProfileControl";

export type RecordingWorkspaceShellProps = {
  recordingId: string;
  workspace: PipelineWorkspace;
  stage: PipelineWorkspaceStage;
  compare: boolean;
  urlState: PipelineUrlState;
  activeView: PipelineView;
  notice: string | null;
  error: string | null;
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
  stage,
  compare,
  urlState,
  activeView,
  notice,
  error,
  onNavigate,
}: RecordingWorkspaceShellProps) {
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
          <nav aria-label="Recording pipeline stages">
            <ol className={shellStyles.stageNavigation}>
              {workspace.stages.map((candidate) => (
                <li key={candidate.key}>
                  <a
                    aria-current={
                      candidate.key === stage.key ? "page" : undefined
                    }
                    className={
                      candidate.key === stage.key
                        ? shellStyles.stageLinkActive
                        : shellStyles.stageLink
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
                      onNavigate(
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
                    <RecordingWorkspaceStatusBadge value={candidate.state} />
                  </a>
                </li>
              ))}
            </ol>
          </nav>
          {stage.has_maintained_reference ? (
            <fieldset className={shellStyles.viewSwitch}>
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
                      onNavigate(
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
          <ProfileControl />
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
  return (
    <section
      className={`${styles.pipelineTaskSurface} ${shellStyles.taskSurface} ${stage.key === "visible_cards" && !compare ? styles.pipelineVisibleCardTaskSurface : ""}`}
      aria-label={`${STAGE_LABELS[stage.key]} task surface`}
      data-slot="center"
    >
      <div
        className={`${styles.pipelineTaskSurfaceContent} ${shellStyles.taskSurfaceContent} ${stage.key === "visible_cards" && !compare ? styles.pipelineVisibleCardTaskSurfaceContent : ""}`}
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
              onNavigate(actionHref(recordingId, stage.key, "review", urlState))
            }
          />
        ) : null}
        {stage.key === "visible_cards" && !compare ? (
          <PipelineVisibleCardEditor
            recordingId={recordingId}
            durationUs={workspace.video.duration_us}
            selectionItemId={presentation.surface.selectedItemId}
            selectionTimeUs={presentation.inspector.selection?.timeUs ?? null}
            generatedRevisionId={stage.selected_generated_revision_id ?? null}
            displayedRevisionId={
              displayedRevision ?? stage.selected_generated_revision_id ?? null
            }
            generatedRunId={selectedVisibleCardRunId}
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
            displayedRevisionId={
              displayedRevision ?? stage.selected_generated_revision_id ?? null
            }
            generatedRunId={selectedVisualIdentityRunId}
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
