import { useEffect, useMemo, useState } from "react";

import {
  createDokoDetectorClient,
  type PipelineWorkspaceStage,
  type RecordingDetail,
  type RoundAnalysisCreateRequest,
  type RoundAnalysisStatus,
} from "../api/client";
import styles from "../App.module.css";
import { describePipelineError } from "./ObservationRunFormatting";
import {
  createUuid,
  DEFAULT_PLAYERS,
  isUuid,
  parseSearchLimits,
  TERMINAL_ANALYSIS_STATES,
} from "./RoundAnalysisFormatting";
import {
  RoundAnalysisHistory,
  RoundAnalysisStatusPanel,
} from "./RoundAnalysisPresentation";
import { PipelineControlStatusBadge } from "./PipelineControlStatusBadge";
import { usePageVisibility } from "./usePageVisibility";

export type RoundAnalysisControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  selectedAnalysisId: string | null;
  onRefresh: () => Promise<void>;
  onSelectAnalysis: (analysisId: string | null) => void;
  compact?: boolean;
};

export function RoundAnalysisControls({
  recordingId,
  stage,
  selectedAnalysisId,
  onRefresh,
  onSelectAnalysis,
  compact = false,
}: RoundAnalysisControlsProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const pageVisible = usePageVisibility();
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
    if (activeAnalysisId === null || !pageVisible) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    let controller: AbortController | null = null;
    const poll = async () => {
      if (cancelled) return;
      controller = new AbortController();
      try {
        const response = await client.getRoundAnalysisStatus(activeAnalysisId, {
          signal: controller.signal,
        });
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
      } finally {
        controller = null;
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
      controller?.abort();
    };
  }, [activeAnalysisId, client, onRefresh, pageVisible]);

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

  const completedAnalysis = stage.analyses.some(
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
            <PipelineControlStatusBadge value={displayedStatus} />
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
        <RoundAnalysisStatusPanel
          recordingId={recordingId}
          observationRevisionId={observationRevisionId}
          liveStatus={liveStatus}
          onSelectAnalysis={onSelectAnalysis}
        />
      ) : null}
      {stage.analyses.length > 0 && !compact ? (
        <RoundAnalysisHistory
          recordingId={recordingId}
          analyses={stage.analyses}
          activeAnalysisId={activeAnalysisId}
          completedAnalysis={completedAnalysis}
          onSelectAnalysis={(analysisId) => {
            setTrackedAnalysisId(analysisId);
            setLiveStatus(null);
            onSelectAnalysis(analysisId);
          }}
        />
      ) : null}
    </section>
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
