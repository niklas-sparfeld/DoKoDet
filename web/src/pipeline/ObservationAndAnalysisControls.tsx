import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type PipelineRun,
  type PipelineRunResponse,
  type PipelineRunStartRequest,
  type PipelineWorkspaceStage,
  type RecordingDetail,
  type RoundAnalysisCreateRequest,
  type RoundAnalysisStatus,
} from "../api/client";
import { RecordingAnalysisView } from "../analysis/AnalysisView";
import styles from "../App.module.css";

const TERMINAL_RUN_STATES = new Set(["complete", "partial", "failed"]);
const TERMINAL_ANALYSIS_STATES = new Set(["complete", "failed"]);
const DEFAULT_PLAYERS = "seat-1, seat-2, seat-3, seat-4";

type ObservationRunControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  stages: PipelineWorkspaceStage[];
  onRefresh: () => Promise<void>;
  compact?: boolean;
};

type RoundAnalysisControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  selectedAnalysisId: string | null;
  onRefresh: () => Promise<void>;
  onSelectAnalysis: (analysisId: string | null) => void;
  compact?: boolean;
};

type RunFacts = {
  run_id: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
  input_revision_ids: string[];
};

export function ObservationRunControls({
  recordingId,
  stage,
  stages,
  onRefresh,
  compact = false,
}: ObservationRunControlsProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const compatibleSets = useMemo(
    () => stage.compatible_input_sets ?? [],
    [stage.compatible_input_sets],
  );
  const selectedDefaults = useMemo(
    () =>
      ["events", "visible_cards", "visual_identities"].map((key) => {
        const upstream = stages.find((candidate) => candidate.key === key);
        return (
          upstream?.selected_completed_reference_revision_id ??
          upstream?.selected_generated_revision_id ??
          null
        );
      }),
    [stages],
  );
  const defaultSet = useMemo(
    () =>
      compatibleSets.find((candidate) =>
        candidate.input_revision_ids.every(
          (revisionId, index) => revisionId === selectedDefaults[index],
        ),
      ) ??
      compatibleSets[0] ??
      null,
    [compatibleSets, selectedDefaults],
  );
  const [selectedSetKey, setSelectedSetKey] = useState("");
  const [trackedRunId, setTrackedRunId] = useState<string | null>(
    () =>
      stage.runs.find(
        (run) => run.status === "queued" || run.status === "running",
      )?.run_id ?? null,
  );
  const [liveRun, setLiveRun] = useState<PipelineRunResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const selectedSet =
    compatibleSets.find(
      (candidate) => candidate.input_revision_ids.join("|") === selectedSetKey,
    ) ?? defaultSet;
  const selectedRun = useMemo(
    () =>
      liveRun !== null && liveRun.run_id === trackedRunId
        ? toRunFacts(liveRun)
        : trackedRunId === null
          ? null
          : toRunFacts(
              stage.runs.find((run) => run.run_id === trackedRunId) ?? null,
            ),
    [liveRun, stage.runs, trackedRunId],
  );
  const latestRun = stage.runs[0] ?? null;

  const getRun = useCallback(
    (runId: string, init?: RequestInit) =>
      client.getObservationRun(recordingId, runId, init),
    [client, recordingId],
  );

  useEffect(() => {
    if (trackedRunId === null) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    const poll = async () => {
      try {
        const response = await getRun(trackedRunId);
        if (cancelled) {
          return;
        }
        setLiveRun(response);
        if (TERMINAL_RUN_STATES.has(response.status)) {
          await onRefresh();
          return;
        }
        timer = window.setTimeout(() => void poll(), 1000);
      } catch (reason: unknown) {
        if (!cancelled) {
          setMessage(describePipelineError(reason));
          timer = window.setTimeout(() => void poll(), 1000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [getRun, onRefresh, trackedRunId]);

  async function startRun() {
    if (selectedSet === null) {
      setMessage(
        "No compatible event, visible-card, and identity revision set is available.",
      );
      return;
    }
    setBusy(true);
    setMessage(null);
    const runId = createId("observation");
    try {
      const response = await client.startObservationRun(
        recordingId,
        buildObservationRequest(
          runId,
          selectedSet.input_revision_ids,
          latestRun,
        ),
      );
      setLiveRun(response);
      setTrackedRunId(response.run_id);
      await onRefresh();
    } catch (reason: unknown) {
      setMessage(describePipelineError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function retryRun(runId: string) {
    setBusy(true);
    setMessage(null);
    try {
      const response = await client.retryObservationRun(recordingId, runId);
      setLiveRun(response);
      setTrackedRunId(response.run_id);
      await onRefresh();
    } catch (reason: unknown) {
      setMessage(describePipelineError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={`${styles.pipelineRunControls} ${compact ? styles.pipelineRunControlsCompact : ""}`}
      aria-labelledby={compact ? undefined : "observation-controls-heading"}
    >
      {!compact ? (
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Processor controls</p>
            <h3 id="observation-controls-heading">
              Assemble table observations
            </h3>
          </div>
          {selectedRun !== null ? (
            <StatusBadge value={selectedRun.status} />
          ) : null}
        </div>
      ) : null}
      {stage.run_blockers.length > 0 && compatibleSets.length === 0 ? (
        <p className={styles.detailBlocker}>{stage.run_blockers[0]}</p>
      ) : (
        <>
          <div className={styles.pipelineRunForm}>
            <label className={styles.pipelineRunSelector}>
              <span>Compatible revision set</span>
              <select
                aria-label="Compatible revision set"
                value={selectedSet?.input_revision_ids.join("|") ?? ""}
                disabled={busy || compatibleSets.length === 0}
                onChange={(event) => setSelectedSetKey(event.target.value)}
              >
                {compatibleSets.length === 0 ? (
                  <option value="">No compatible revision set</option>
                ) : (
                  compatibleSets.map((candidate) => (
                    <option
                      key={candidate.input_revision_ids.join("|")}
                      value={candidate.input_revision_ids.join("|")}
                    >
                      {candidate.display_label}
                    </option>
                  ))
                )}
              </select>
            </label>
            <button
              className={styles.primaryButton}
              type="button"
              disabled={!stage.can_run || selectedSet === null || busy}
              onClick={() => void startRun()}
            >
              {busy
                ? "Starting…"
                : latestRun === null
                  ? "Assemble observations"
                  : "Run again"}
            </button>
          </div>
          {selectedSet !== null ? (
            <p className={styles.pipelineRunInputValue}>
              Exact inputs: {selectedSet.input_revision_ids.join(", ")}
            </p>
          ) : null}
        </>
      )}
      {message !== null ? (
        <p className={styles.pipelineRunMessage} role="alert">
          {message}
        </p>
      ) : null}
      {selectedRun !== null ? (
        <PipelineRunStatus run={selectedRun} onRetry={retryRun} busy={busy} />
      ) : null}
      {stage.runs.length > 0 ? (
        <details className={styles.pipelineRunHistory}>
          <summary>Retained assembly runs and actual inputs</summary>
          <RunHistory
            runs={stage.runs}
            trackedRunId={trackedRunId}
            onSelect={(runId) => {
              setTrackedRunId(runId);
              setLiveRun(null);
              setMessage(null);
            }}
            onRetry={retryRun}
            busy={busy}
          />
        </details>
      ) : null}
    </section>
  );
}

export function RoundAnalysisControls({
  recordingId,
  stage,
  selectedAnalysisId,
  onRefresh,
  onSelectAnalysis,
  compact = false,
}: RoundAnalysisControlsProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [observationRevisionId, setObservationRevisionId] = useState(
    () =>
      stage.selected_generated_revision_id ??
      stage.input_options[0]?.revision_id ??
      "",
  );
  const [gameId, setGameId] = useState("");
  const [roundId, setRoundId] = useState(
    () => stage.analyses[0]?.round_id ?? "",
  );
  const [sessionId, setSessionId] = useState("");
  const [players, setPlayers] = useState(DEFAULT_PLAYERS);
  const [dealer, setDealer] = useState("seat-1");
  const [firstTrickLeader, setFirstTrickLeader] = useState("seat-1");
  const [rulesVersion, setRulesVersion] = useState<"v1" | "">("v1");
  const [maxMissingPlays, setMaxMissingPlays] = useState("1");
  const [maxHypotheses, setMaxHypotheses] = useState("256");
  const [maxSearchNodes, setMaxSearchNodes] = useState("250000");
  const [correctionIds, setCorrectionIds] = useState("");
  const [trackedAnalysisId, setTrackedAnalysisId] = useState<string | null>(
    () =>
      selectedAnalysisId ??
      stage.analyses.find(
        (analysis) => !TERMINAL_ANALYSIS_STATES.has(analysis.state),
      )?.analysis_id ??
      null,
  );
  const [liveStatus, setLiveStatus] = useState<RoundAnalysisStatus | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void client
      .getRecording(recordingId, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) {
          return;
        }
        setRecording(response);
        setGameId((current) => current || response.source.game_id || "");
        setRoundId(
          (current) => current || response.source.round_id || response.round_id,
        );
        setSessionId((current) => current || response.session_id);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [client, recordingId]);

  const activeAnalysisId = selectedAnalysisId ?? trackedAnalysisId;

  useEffect(() => {
    if (activeAnalysisId === null) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    const poll = async () => {
      try {
        const response = await client.getRoundAnalysisStatus(activeAnalysisId);
        if (cancelled) {
          return;
        }
        setLiveStatus(response);
        if (TERMINAL_ANALYSIS_STATES.has(response.state)) {
          await onRefresh();
          return;
        }
        timer = window.setTimeout(() => void poll(), 1000);
      } catch (reason: unknown) {
        if (!cancelled) {
          setMessage(describePipelineError(reason));
          timer = window.setTimeout(() => void poll(), 1000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [activeAnalysisId, client, onRefresh]);

  function validateContext(): RoundAnalysisCreateRequest | null {
    const activePlayers = players
      .split(",")
      .map((player) => player.trim())
      .filter(Boolean);
    const missing = [
      ["observation revision", observationRevisionId],
      ["game ID", gameId.trim()],
      ["round ID", roundId.trim()],
      ["session ID", sessionId.trim()],
      ["dealer", dealer.trim()],
      ["first-trick leader", firstTrickLeader.trim()],
    ].find(([, value]) => value === "");
    if (missing !== undefined) {
      setMessage(
        `Enter an explicit ${missing[0]} before starting round analysis.`,
      );
      return null;
    }
    if (!rulesVersion) {
      setMessage(
        "Select an explicit rules version before starting round analysis.",
      );
      return null;
    }
    if (activePlayers.length !== 4 || new Set(activePlayers).size !== 4) {
      setMessage("Round context needs four unique active players.");
      return null;
    }
    if (!isUuid(sessionId.trim())) {
      setMessage("Session ID must be a valid UUID.");
      return null;
    }
    const search = parseSearchLimits(
      maxMissingPlays,
      maxHypotheses,
      maxSearchNodes,
    );
    if (search === null) {
      setMessage(
        "Search limits must be positive numbers, with missing plays at least zero.",
      );
      return null;
    }
    return {
      schema_version: "round-analysis/v1",
      analysis_id: createUuid(),
      recording_id: recordingId,
      round_id: roundId.trim(),
      session_id: sessionId.trim(),
      table_observation_revision_id: observationRevisionId,
      round_context: {
        game_id: gameId.trim(),
        round_id: roundId.trim(),
        active_players: activePlayers,
        dealer: dealer.trim(),
        first_trick_leader: firstTrickLeader.trim(),
      },
      rules_version: rulesVersion,
      correction_constraint_revision_ids: correctionIds
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
      search,
    };
  }

  async function startAnalysis() {
    const request = validateContext();
    if (request === null) {
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const response = await client.createRoundAnalysis(request);
      setTrackedAnalysisId(response.analysis_id);
      setLiveStatus(response);
      onSelectAnalysis(response.analysis_id);
      await onRefresh();
    } catch (reason: unknown) {
      setMessage(describePipelineError(reason));
    } finally {
      setBusy(false);
    }
  }

  const completedAnalysis = stage.analyses.find(
    (analysis) =>
      analysis.analysis_id === activeAnalysisId &&
      analysis.state === "complete",
  );
  const displayedStatus =
    (liveStatus?.analysis_id === activeAnalysisId ? liveStatus.state : null) ??
    (activeAnalysisId === null
      ? null
      : (stage.analyses.find(
          (analysis) => analysis.analysis_id === activeAnalysisId,
        )?.state ?? null));

  return (
    <section
      className={`${styles.pipelineRunControls} ${compact ? styles.pipelineRunControlsCompact : ""}`}
      aria-labelledby={compact ? undefined : "round-analysis-controls-heading"}
    >
      {!compact ? (
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Analysis controls</p>
            <h3 id="round-analysis-controls-heading">Reconstruct one round</h3>
          </div>
          {displayedStatus !== null ? (
            <StatusBadge value={displayedStatus} />
          ) : null}
        </div>
      ) : null}
      {stage.run_blockers.length > 0 ? (
        <p className={styles.detailBlocker}>{stage.run_blockers[0]}</p>
      ) : null}
      <div className={styles.pipelineRunForm}>
        <label className={styles.pipelineRunSelector}>
          <span>Exact observation revision</span>
          <select
            aria-label="Exact observation revision"
            value={observationRevisionId}
            disabled={busy || stage.input_options.length === 0}
            onChange={(event) => setObservationRevisionId(event.target.value)}
          >
            <option value="">Select an observation revision</option>
            {stage.input_options.map((option) => (
              <option key={option.revision_id} value={option.revision_id}>
                {option.display_label} · {option.revision_id}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.pipelineRunSelector}>
          <span>Rules version</span>
          <select
            aria-label="Rules version"
            value={rulesVersion}
            disabled={busy}
            onChange={(event) =>
              setRulesVersion(event.target.value as "v1" | "")
            }
          >
            <option value="">Select rules version</option>
            <option value="v1">doko-normal v1</option>
          </select>
        </label>
        <button
          className={styles.primaryButton}
          type="button"
          disabled={!stage.can_run || busy || stage.input_options.length === 0}
          onClick={() => void startAnalysis()}
        >
          {busy ? "Starting…" : "Start reconstruction"}
        </button>
      </div>
      <details className={styles.pipelineRunHistory}>
        <summary>Round context and advanced analysis settings</summary>
        <div className={styles.pipelineContextGrid}>
          <ContextField label="Game ID" value={gameId} onChange={setGameId} />
          <ContextField
            label="Round ID"
            value={roundId}
            onChange={setRoundId}
          />
          <ContextField
            label="Session ID"
            value={sessionId}
            onChange={setSessionId}
          />
          <ContextField
            label="Active players"
            value={players}
            onChange={setPlayers}
          />
          <ContextField label="Dealer" value={dealer} onChange={setDealer} />
          <ContextField
            label="First-trick leader"
            value={firstTrickLeader}
            onChange={setFirstTrickLeader}
          />
          <ContextField
            label="Max missing plays"
            value={maxMissingPlays}
            onChange={setMaxMissingPlays}
            type="number"
          />
          <ContextField
            label="Max hypotheses"
            value={maxHypotheses}
            onChange={setMaxHypotheses}
            type="number"
          />
          <ContextField
            label="Max search nodes"
            value={maxSearchNodes}
            onChange={setMaxSearchNodes}
            type="number"
          />
          <ContextField
            label="Correction revision IDs"
            value={correctionIds}
            onChange={setCorrectionIds}
          />
        </div>
        {recording !== null ? (
          <p className={styles.pipelineRunInputValue}>
            Recording context loaded from {recording.recording_id}.
          </p>
        ) : null}
      </details>
      {message !== null ? (
        <p className={styles.pipelineRunMessage} role="alert">
          {message}
        </p>
      ) : null}
      {liveStatus !== null ? (
        <div className={styles.pipelineRunStatus} role="status">
          <p>{analysisStatusMessage(liveStatus.state)}</p>
          <p>
            Exact observation input: {observationRevisionId || "Unavailable"}
          </p>
          <p>Analysis ID: {liveStatus.analysis_id}</p>
          {liveStatus.error !== null && liveStatus.error !== undefined ? (
            <p>{liveStatus.error}</p>
          ) : null}
          {liveStatus.state === "complete" ? (
            <a
              className={styles.recordingLink}
              href={analysisPath(recordingId, liveStatus.analysis_id)}
              onClick={(event) => {
                event.preventDefault();
                onSelectAnalysis(liveStatus.analysis_id);
              }}
            >
              Open diagnostic timeline and counterfactual workbench
            </a>
          ) : null}
        </div>
      ) : null}
      {stage.analyses.length > 0 ? (
        <details
          className={styles.pipelineRunHistory}
          open={completedAnalysis !== undefined}
        >
          <summary>Retained analyses and actual inputs</summary>
          <ul className={styles.pipelineRunList}>
            {stage.analyses.map((analysis) => (
              <li key={analysis.analysis_id}>
                <button
                  className={styles.pipelineRunSelectButton}
                  type="button"
                  aria-pressed={analysis.analysis_id === activeAnalysisId}
                  onClick={() => {
                    setTrackedAnalysisId(analysis.analysis_id);
                    setLiveStatus(null);
                    onSelectAnalysis(analysis.analysis_id);
                  }}
                >
                  <span>{analysis.analysis_id}</span>
                  <StatusBadge value={analysis.state} />
                </button>
                <span>
                  {analysis.round_id} · observation input{" "}
                  {analysis.input_revision_ids.join(", ") || "none"}
                </span>
                <a
                  className={styles.recordingLink}
                  href={analysisPath(recordingId, analysis.analysis_id)}
                  onClick={(event) => {
                    event.preventDefault();
                    onSelectAnalysis(analysis.analysis_id);
                  }}
                >
                  {analysis.state === "complete"
                    ? "Open timeline"
                    : "Open status"}
                </a>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

export function SelectedAnalysisTimeline({
  analysisId,
  recordingId,
}: {
  analysisId: string | null;
  recordingId: string;
}) {
  return analysisId === null ? null : (
    <RecordingAnalysisView analysisId={analysisId} recordingId={recordingId} />
  );
}

function RunHistory({
  runs,
  trackedRunId,
  onSelect,
  onRetry,
  busy,
}: {
  runs: PipelineRun[];
  trackedRunId: string | null;
  onSelect: (runId: string) => void;
  onRetry: (runId: string) => Promise<void>;
  busy: boolean;
}) {
  return (
    <ul className={styles.pipelineRunList}>
      {runs.map((run) => (
        <li key={run.run_id}>
          <button
            className={styles.pipelineRunSelectButton}
            type="button"
            aria-pressed={run.run_id === trackedRunId}
            onClick={() => onSelect(run.run_id)}
          >
            <span>{run.run_id}</span>
            <StatusBadge value={run.status} />
          </button>
          <span>Inputs {run.input_revision_ids.join(", ") || "none"}</span>
          <span>
            {run.implementation.name} {run.implementation.version}
          </span>
          {run.failure !== null && run.failure !== undefined ? (
            <span>{run.failure.message}</span>
          ) : null}
          {run.status === "failed" || run.status === "partial" ? (
            <button
              className={styles.detailButton}
              type="button"
              disabled={busy}
              onClick={() => void onRetry(run.run_id)}
            >
              Retry same run
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function PipelineRunStatus({
  run,
  onRetry,
  busy,
}: {
  run: RunFacts;
  onRetry: (runId: string) => Promise<void>;
  busy: boolean;
}) {
  const progress = readObject(run.state.progress);
  const completed = readNumber(progress?.completed);
  const total = readNumber(progress?.total);
  const failure = readObject(run.state.terminal_failure);
  return (
    <div className={styles.pipelineRunStatus} role="status">
      <p>{runStatusMessage(run.status)}</p>
      {completed !== null && total !== null ? (
        <p>
          Progress: {completed} / {total} items
        </p>
      ) : null}
      {readString(failure?.message) !== null ? (
        <p>{readString(failure?.message)}</p>
      ) : null}
      <dl className={styles.pipelineRunFacts}>
        <div>
          <dt>Run</dt>
          <dd>{run.run_id}</dd>
        </div>
        <div>
          <dt>Attempt</dt>
          <dd>{run.attempt}</dd>
        </div>
        <div>
          <dt>Actual inputs</dt>
          <dd>
            {run.input_revision_ids.join(", ") || "Accepted recording video"}
          </dd>
        </div>
        <div>
          <dt>Implementation</dt>
          <dd>{formatValue(run.request.implementation)}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>{formatValue(run.request.model)}</dd>
        </div>
        <div>
          <dt>Configuration</dt>
          <dd>{formatValue(run.request.configuration)}</dd>
        </div>
        <div>
          <dt>Extraction policy</dt>
          <dd>{formatValue(run.request.extraction_policy)}</dd>
        </div>
        <div>
          <dt>Crop policy</dt>
          <dd>{formatValue(run.request.crop_policy)}</dd>
        </div>
      </dl>
      {run.status === "failed" || run.status === "partial" ? (
        <button
          className={styles.detailButton}
          type="button"
          disabled={busy}
          onClick={() => void onRetry(run.run_id)}
        >
          Retry same run
        </button>
      ) : null}
    </div>
  );
}

function ContextField({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number";
}) {
  return (
    <label className={styles.pipelineRunSelector}>
      <span>{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function buildObservationRequest(
  runId: string,
  inputRevisionIds: string[],
  latestRun: PipelineRun | null,
): PipelineRunStartRequest {
  return {
    request: {
      run_id: runId,
      input_revision_ids: inputRevisionIds,
      implementation: latestRun?.implementation ?? {
        name: "observation-assembler",
        version: "v1",
      },
      model: latestRun?.model ?? null,
      configuration: latestRun?.configuration ?? {},
      extraction_policy: latestRun?.extraction_policy ?? {
        policy_id: "exact-event/v1",
      },
      crop_policy: latestRun?.crop_policy ?? null,
    },
  };
}

function toRunFacts(
  run: PipelineRun | PipelineRunResponse | null,
): RunFacts | null {
  if (run === null) {
    return null;
  }
  return {
    run_id: run.run_id,
    status: run.status,
    attempt: run.attempt,
    request: run.request,
    state: run.state,
    input_revision_ids:
      "input_revision_ids" in run && Array.isArray(run.input_revision_ids)
        ? run.input_revision_ids
        : readStringArray(run.request.input_revision_ids),
  };
}

function runStatusMessage(status: string): string {
  return status === "complete"
    ? "Observation assembly completed and retained its output revision."
    : status === "partial"
      ? "Observation assembly returned a partial result. Review it or retry the same frozen request."
      : status === "failed"
        ? "Observation assembly failed. Retry keeps the run ID and exact frozen inputs."
        : status === "queued"
          ? "Observation assembly is queued."
          : "Observation assembly is running.";
}

function analysisStatusMessage(status: string): string {
  return status === "complete"
    ? "Round reconstruction completed."
    : status === "failed"
      ? "Round reconstruction failed."
      : status === "queued"
        ? "Round reconstruction is queued."
        : "Round reconstruction is running.";
}

function describePipelineError(reason: unknown): string {
  if (!(reason instanceof ApiError)) {
    return "The pipeline request could not reach the backend.";
  }
  const body = readObject(reason.body);
  const detail = readObject(body?.detail);
  const message = readString(detail?.message) ?? readString(body?.message);
  if (reason.status === 422) {
    return message === null
      ? "The selected pipeline input or round context is incompatible."
      : `The selected pipeline input or round context is incompatible: ${message}`;
  }
  return message ?? `The backend returned HTTP ${reason.status}.`;
}

function parseSearchLimits(
  missing: string,
  hypotheses: string,
  nodes: string,
): RoundAnalysisCreateRequest["search"] | null {
  const maxMissingPlays = Number(missing);
  const maxHypotheses = Number(hypotheses);
  const maxSearchNodes = Number(nodes);
  if (
    !Number.isInteger(maxMissingPlays) ||
    maxMissingPlays < 0 ||
    !Number.isInteger(maxHypotheses) ||
    maxHypotheses <= 0 ||
    !Number.isInteger(maxSearchNodes) ||
    maxSearchNodes <= 0
  ) {
    return null;
  }
  return {
    max_missing_plays: maxMissingPlays,
    max_hypotheses: maxHypotheses,
    max_search_nodes: maxSearchNodes,
  };
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
}

function createUuid(): string {
  return typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-0000-4000-8000-${Math.random().toString(16).slice(2, 14)}`;
}

function createId(prefix: string): string {
  return `${prefix}-run-${createUuid().slice(0, 12)}`;
}

export function analysisPath(recordingId: string, analysisId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}/pipeline/round_analyses?analysis=${encodeURIComponent(analysisId)}`;
}

function readObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : [];
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "Unavailable";
  }
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
