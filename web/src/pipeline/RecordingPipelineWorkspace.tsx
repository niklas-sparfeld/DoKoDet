import {
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
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
import { PipelineCardEventEditor } from "../cardEvents/PipelineCardEventEditor";
import { PipelineVisibleCardEditor } from "../visibleCards/PipelineVisibleCardEditor";
import { PipelineVisualIdentityEditor } from "../visualIdentities/PipelineVisualIdentityEditor";
import styles from "../App.module.css";
import {
  ObservationRunControls,
  RoundAnalysisControls,
  SelectedAnalysisTimeline,
} from "./ObservationAndAnalysisControls";
import { RunControls } from "./RunControls";
import { ComparisonView } from "./ComparisonView";

export type { PipelineStageKey } from "../api/client";

export const PIPELINE_STAGE_KEYS: readonly PipelineStageKey[] = [
  "events",
  "visible_cards",
  "visual_identities",
  "table_observations",
  "round_analyses",
];

const STAGE_LABELS: Record<PipelineStageKey, string> = {
  events: "Events",
  visible_cards: "Visible cards",
  visual_identities: "Visual identities",
  table_observations: "Table observations",
  round_analyses: "Round analyses",
};

const STAGE_CONTENT_TYPES: Record<
  Exclude<PipelineStageKey, "round_analyses">,
  PipelineSelectableContentType
> = {
  events: "events",
  visible_cards: "visible_cards",
  visual_identities: "visual_identities",
  table_observations: "table_observations",
};

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

export function isPipelineStageKey(value: string): value is PipelineStageKey {
  return PIPELINE_STAGE_KEYS.includes(value as PipelineStageKey);
}

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

  if (stageKey === null && workspace === null) {
    return null;
  }
  if (stageKey !== null && loading && workspace === null) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.loading} role="status">
          Loading recording pipeline…
        </p>
      </main>
    );
  }
  if (stageKey !== null && (workspace === null || stage === undefined)) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <p className={styles.errorMessage} role="alert">
          {error ?? "The recording pipeline could not be loaded."}
        </p>
      </main>
    );
  }
  if (workspace === null || stage === undefined) {
    return null;
  }

  const activeView = urlState.view ?? defaultViewForStage(stage);
  const action = primaryActionForStage(stage);
  const actionState = actionStateForStage(stage, urlState, action.kind);
  const generatedOptions = stage.input_options.filter(
    (option) => option.origin === "processor",
  );
  const displayedRevision =
    urlState.revision ??
    (activeView === "generated"
      ? stage.selected_generated_revision_id
      : stage.selected_completed_reference_revision_id) ??
    null;
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

  return (
    <main
      className={`${styles.shell} ${styles.recordingsPage} ${styles.pipelinePage}`}
    >
      <a className={styles.backLink} href={recordingPagePath(recordingId)}>
        ← Recording details
      </a>
      <header className={styles.pipelineHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector · Recording workspace</p>
          <h1>Recording pipeline</h1>
          <p className={styles.detailContext}>
            {recordingId} · {formatDuration(workspace.video.duration_us)}
          </p>
        </div>
        <div className={styles.pipelineVideoIdentity}>
          <span className={styles.statusLabel}>Accepted video</span>
          <strong>{workspace.video.video_sha256.slice(0, 12)}…</strong>
        </div>
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
      {workspace.diagnostics.length > 0 ? (
        <ul
          className={styles.pipelineDiagnostics}
          aria-label="Pipeline diagnostics"
        >
          {workspace.diagnostics.map((diagnostic) => (
            <li key={`${diagnostic.code}:${diagnostic.revision_id ?? ""}`}>
              <strong>{formatIdentifier(diagnostic.code)}</strong>
              <span>{diagnostic.message}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <nav aria-label="Recording pipeline stages">
        <ol className={styles.pipelineStageNavigation}>
          {workspace.stages.map((candidate) => (
            <li key={candidate.key}>
              <a
                aria-current={candidate.key === stage.key ? "page" : undefined}
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

      <section
        className={styles.pipelineSummaryGrid}
        aria-label="Pipeline stage summary"
      >
        {workspace.stages.map((candidate) => (
          <StageSummaryCard
            key={candidate.key}
            recordingId={recordingId}
            stage={candidate}
            current={candidate.key === stage.key}
            state={urlState}
            onNavigate={navigateTo}
          />
        ))}
      </section>

      <section
        className={styles.pipelineStagePanel}
        aria-labelledby="pipeline-stage-heading"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Selected stage</p>
            <h2 id="pipeline-stage-heading">{STAGE_LABELS[stage.key]}</h2>
          </div>
          <StatusBadge value={stage.state} />
        </div>
        <div className={styles.pipelineActionRow}>
          <div>
            <span className={styles.statusLabel}>Next action</span>
            <strong>{action.label}</strong>
          </div>
          {action.kind === "blocked" ? (
            <p className={styles.detailBlocker}>{action.blocker}</p>
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
                navigateTo(
                  actionHref(recordingId, stage.key, action.kind, actionState),
                );
              }}
              data-action={action.kind}
            >
              {action.label}
            </a>
          )}
        </div>
        <div className={styles.pipelineSelectorGrid}>
          <fieldset className={styles.pipelineSelector}>
            <legend>View</legend>
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
          {stage.key !== "round_analyses" ? (
            <label className={styles.pipelineSelector}>
              <span>Default generated revision</span>
              <select
                aria-label="Default generated revision"
                value={stage.selected_generated_revision_id ?? ""}
                disabled={selectionBusy}
                onChange={(event) =>
                  void selectGeneratedRevision(event.target.value || null)
                }
              >
                <option value="">No generated revision selected</option>
                {generatedOptions.map((option) => (
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
                replaceUrlState({
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
        {urlState.item !== null || urlState.tUs !== null ? (
          <p className={styles.pipelineUrlState}>
            {urlState.item === null ? null : `Item ${urlState.item}`}
            {urlState.item !== null && urlState.tUs !== null ? " · " : null}
            {urlState.tUs === null
              ? null
              : `${formatMicroseconds(urlState.tUs)} position`}
          </p>
        ) : null}
        <details className={styles.pipelineHistory}>
          <summary>History and exact inputs</summary>
          <PipelineHistory stage={stage} />
        </details>
        {compare ? (
          <ComparisonView
            recordingId={recordingId}
            stage={stage}
            durationUs={workspace.video.duration_us}
            urlState={urlState}
            onNavigate={navigateTo}
          />
        ) : null}
        {!compare ? (
          <RunControls
            recordingId={recordingId}
            stage={stage}
            stages={workspace.stages}
            onRefresh={() => loadWorkspace()}
          />
        ) : null}
        {stage.key === "table_observations" && !compare ? (
          <ObservationRunControls
            recordingId={recordingId}
            stage={stage}
            stages={workspace.stages}
            onRefresh={() => loadWorkspace()}
          />
        ) : null}
        {stage.key === "round_analyses" && !compare ? (
          <RoundAnalysisControls
            recordingId={recordingId}
            stage={stage}
            selectedAnalysisId={urlState.analysis}
            onRefresh={() => loadWorkspace()}
            onSelectAnalysis={(analysisId) =>
              replaceUrlState({ ...urlState, analysis: analysisId })
            }
          />
        ) : null}
        {stage.key === "round_analyses" && !compare ? (
          <SelectedAnalysisTimeline
            analysisId={urlState.analysis}
            recordingId={recordingId}
          />
        ) : null}
        {stage.key === "events" && !compare ? (
          <PipelineCardEventEditor
            recordingId={recordingId}
            durationUs={workspace.video.duration_us}
            generatedRevisionId={stage.selected_generated_revision_id ?? null}
            generatedRunId={selectedEventRunId}
            view={activeView}
          />
        ) : null}
        {stage.key === "visible_cards" && !compare ? (
          <PipelineVisibleCardEditor
            recordingId={recordingId}
            durationUs={workspace.video.duration_us}
            generatedRevisionId={stage.selected_generated_revision_id ?? null}
            displayedRevisionId={
              activeView === "generated" ? displayedRevision : null
            }
            generatedRunId={selectedVisibleCardRunId}
            view={activeView}
          />
        ) : null}
        {stage.key === "visual_identities" && !compare ? (
          <PipelineVisualIdentityEditor
            recordingId={recordingId}
            durationUs={workspace.video.duration_us}
            generatedRevisionId={stage.selected_generated_revision_id ?? null}
            displayedRevisionId={
              activeView === "generated" ? displayedRevision : null
            }
            generatedRunId={selectedVisualIdentityRunId}
            view={activeView}
          />
        ) : null}
      </section>
    </main>
  );
}

function StageSummaryCard({
  recordingId,
  stage,
  current,
  state,
  onNavigate,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  current: boolean;
  state: PipelineUrlState;
  onNavigate: (path: string) => void;
}) {
  const action = primaryActionForStage(stage);
  const path = recordingPipelinePath(
    recordingId,
    stage.key,
    actionStateForStage(stage, state, action.kind),
  );
  return (
    <article className={styles.pipelineSummaryCard} data-current={current}>
      <div className={styles.pipelineSummaryCardHeading}>
        <h3>{STAGE_LABELS[stage.key]}</h3>
        <StatusBadge value={stage.state} />
      </div>
      <p className={styles.pipelineSummaryText}>
        {stage.input_options.length} revision
        {stage.input_options.length === 1 ? "" : "s"} · {stage.runs.length} run
        {stage.runs.length === 1 ? "" : "s"}
      </p>
      <a
        className={styles.recordingLink}
        href={path}
        onClick={(event) => {
          if (isModifiedClick(event)) {
            return;
          }
          event.preventDefault();
          onNavigate(path);
        }}
      >
        {action.label}
      </a>
    </article>
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
  if (stage.key === "table_observations" || stage.key === "round_analyses") {
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
