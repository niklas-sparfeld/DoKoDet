import { useEffect, useMemo, useRef, useState } from "react";

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
  parseSearchLimits,
  TERMINAL_ANALYSIS_STATES,
} from "./RoundAnalysisFormatting";
import {
  RoundAnalysisHistory,
  RoundAnalysisStatusPanel,
} from "./RoundAnalysisPresentation";
import { PipelineControlStatusBadge } from "./PipelineControlStatusBadge";

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
  const loadedContextAnalysisId = useRef<string | null>(null);
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [observationRevisionId, setObservationRevisionId] = useState(
    () =>
      stage.selected_generated?.revision_id ??
      stage.input_options[0]?.node_revision_id ??
      "",
  );
  const [gameId, setGameId] = useState("");
  const [roundId, setRoundId] = useState(
    () => stage.analyses[0]?.round_id ?? "",
  );
  const [sessionId, setSessionId] = useState("");
  const [players, setPlayers] = useState("");
  const [dealer, setDealer] = useState("");
  const [firstTrickLeader, setFirstTrickLeader] = useState("");
  const [rulesVersion, setRulesVersion] = useState<"v1" | "">("");
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
  const [trackedJobId, setTrackedJobId] = useState<string | null>(null);
  const [trackedJobAnalysisId, setTrackedJobAnalysisId] = useState<
    string | null
  >(null);
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

  useEffect(() => {
    const savedAnalysis = stage.analyses[0];
    if (
      savedAnalysis === undefined ||
      loadedContextAnalysisId.current === savedAnalysis.analysis_id
    )
      return;
    loadedContextAnalysisId.current = savedAnalysis.analysis_id;
    const controller = new AbortController();
    void client
      .getRoundAnalysisStatus(savedAnalysis.analysis_id, {
        signal: controller.signal,
      })
      .then((status) => {
        const context = status.round_context;
        if (controller.signal.aborted || context == null) return;
        setGameId(context.game_id);
        setRoundId(context.round_id);
        setPlayers(context.active_players.join(", "));
        setDealer(context.dealer);
        setFirstTrickLeader(context.first_trick_leader);
        setRulesVersion(status.rules_version || "");
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [client, stage.analyses]);

  const activeAnalysisId = selectedAnalysisId ?? trackedAnalysisId;

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
      ["four active players", activePlayers.length === 4 ? "set" : ""],
    ].filter(([, value]) => value === "");
    if (missing.length > 0) {
      setMessage(
        `Enter explicit ${missing.map(([name]) => name).join(", ")} before starting round analysis.`,
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
      setMessage("Round context needs four distinct active players.");
      return null;
    }
    if (!activePlayers.includes(firstTrickLeader.trim())) {
      setMessage("First-trick leader must be one of the four active players.");
      return null;
    }
    const identifierPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
    if (
      [
        ...activePlayers,
        dealer.trim(),
        firstTrickLeader.trim(),
        gameId.trim(),
        roundId.trim(),
      ].some((value) => !identifierPattern.test(value))
    ) {
      setMessage("Round context values must use valid identifiers.");
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
    const observation = stage.input_options.find(
      (option) => option.node_revision_id === observationRevisionId,
    );
    if (observation === undefined) {
      setMessage(
        "Select a stored table-observation revision before starting analysis.",
      );
      return null;
    }
    return {
      schema_version: "round-analysis/v1",
      analysis_id: createUuid(),
      recording_id: recordingId,
      round_id: roundId.trim(),
      session_id: sessionId.trim(),
      table_observation_node_ref: {
        node_id: observation.node_id,
        revision_id: observation.node_revision_id,
      },
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
      setTrackedJobId(response.job_id ?? null);
      setTrackedJobAnalysisId(response.analysis_id);
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
      {trackedJobId !== null && trackedJobAnalysisId === activeAnalysisId ? (
        <p>
          <a href={`/jobs/${encodeURIComponent(trackedJobId)}`}>
            View job {trackedJobId}
          </a>
        </p>
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
              <option
                key={option.node_revision_id}
                value={option.node_revision_id}
              >
                {option.display_label} · {option.node_revision_id}
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
            placeholder="Enter four player IDs in seat order"
          />
          <ContextField
            label="Dealer"
            value={dealer}
            onChange={setDealer}
            placeholder="Confirm dealer player ID"
          />
          <ContextField
            label="First-trick leader"
            value={firstTrickLeader}
            onChange={setFirstTrickLeader}
            placeholder="Confirm leader player ID"
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
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number";
  placeholder?: string;
}) {
  return (
    <label className={styles.pipelineRunSelector}>
      <span>{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
