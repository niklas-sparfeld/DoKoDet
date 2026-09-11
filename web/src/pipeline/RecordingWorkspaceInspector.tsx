import type {
  PipelineComparisonResponse,
  PipelineStageKey,
  PipelineWorkspace,
  PipelineWorkspaceStage,
} from "../api/client";
import styles from "../App.module.css";
import {
  ObservationRunControls,
  RoundAnalysisControls,
} from "./ObservationAndAnalysisControls";
import { ComparisonInspectorControls } from "./ComparisonView";
import { RunControls } from "./RunControls";
import type { PipelineUrlState, PipelineView } from "./recordingPipelineUrl";
import { actionHref, isModifiedClick } from "./recordingWorkspaceNavigation";
import {
  formatByteLength,
  formatDuration,
  formatIdentifier,
  formatMicroseconds,
} from "./recordingWorkspaceFormatting";
import type { RecordingWorkspacePresentation } from "./recordingWorkspacePresentation";
import { RecordingWorkspaceStatusBadge } from "./RecordingWorkspaceStatusBadge";
import inspectorStyles from "./RecordingWorkspaceInspector.module.css";

export type RecordingWorkspaceInspectorProps = {
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
  comparison: PipelineComparisonResponse | null;
  selectionBusy: boolean;
  onNavigate: (path: string) => void;
  onReplaceUrlState: (state: PipelineUrlState) => void;
  onSelectGeneratedRevision: (revisionId: string | null) => Promise<void>;
  onRefresh: () => Promise<void>;
};

export function RecordingWorkspaceInspector({
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
  comparison,
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
      className={`${styles.pipelineInspectorSlot} ${inspectorStyles.slot}`}
      aria-label="Workspace inspector"
      data-slot="inspector"
    >
      <section
        className={`${styles.pipelineInspectorSection} ${inspectorStyles.section}`}
        data-inspector-section="progress"
        aria-labelledby="pipeline-inspector-progress"
      >
        <div className={inspectorStyles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Progress</p>
            <h2 id="pipeline-inspector-progress">{progress.label}</h2>
          </div>
          <RecordingWorkspaceStatusBadge value={stage.state} />
        </div>
        {progress.completed !== null && progress.total !== null ? (
          <>
            <div className={inspectorStyles.progressHeading}>
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
          <p className={inspectorStyles.empty}>
            No execution progress recorded.
          </p>
        )}
      </section>

      <section
        className={`${styles.pipelineInspectorSection} ${inspectorStyles.section}`}
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
        className={`${styles.pipelineInspectorSection} ${inspectorStyles.section}`}
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
            <div className={inspectorStyles.sectionHeading}>
              <div>
                <p className={styles.statusLabel}>Save or execution state</p>
                <h2 id="pipeline-inspector-save-state">
                  {formatIdentifier(presentation.inspector.saveState)}
                </h2>
              </div>
              <RecordingWorkspaceStatusBadge
                value={presentation.inspector.saveState}
              />
            </div>
            {!actionOwnsExecution ? executionControls : null}
          </>
        )}
      </section>

      <section
        className={`${styles.pipelineInspectorSection} ${inspectorStyles.section}`}
        data-inspector-section="selection"
        aria-labelledby="pipeline-inspector-selection"
      >
        <p className={styles.statusLabel}>Current selection</p>
        <h2 id="pipeline-inspector-selection">
          {compare ? "Comparison inputs" : formatIdentifier(activeView)}
        </h2>
        <div className={inspectorStyles.selectionFacts}>
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
        {compare ? (
          <ComparisonInspectorControls
            recordingId={recordingId}
            stage={stage}
            urlState={urlState}
            onNavigate={onNavigate}
            comparison={comparison}
          />
        ) : (
          <div className={inspectorStyles.fields}>
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
                      <option
                        key={option.revision_id}
                        value={option.revision_id}
                      >
                        {option.display_label} · {option.revision_id}
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
                    {option.display_label} · {option.revision_id}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
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
          className={`${styles.pipelineInspectorSection} ${inspectorStyles.section}`}
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
        className={inspectorStyles.details}
        data-inspector-section="details"
        open={presentation.diagnostics.length > 0}
      >
        <summary>Lineage, diagnostics, and history</summary>
        <div className={inspectorStyles.detailsContent}>
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
    <div className={inspectorStyles.historyContent}>
      {stage.runs.length > 0 ? (
        <ul
          className={inspectorStyles.historyList}
          aria-label="Processor history"
        >
          {stage.runs.map((run) => (
            <li key={run.run_id}>
              <div>
                <strong>{run.run_id}</strong>
                <RecordingWorkspaceStatusBadge value={run.status} />
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
          className={inspectorStyles.historyList}
          aria-label="Analysis history"
        >
          {stage.analyses.map((analysis) => (
            <li key={analysis.analysis_id}>
              <div>
                <strong>{analysis.analysis_id}</strong>
                <RecordingWorkspaceStatusBadge value={analysis.state} />
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
