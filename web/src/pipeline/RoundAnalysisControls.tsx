import { useCallback, useMemo, useState } from "react";

import {
  createDokoDetectorClient,
  type EnqueueJobBody,
  type PipelineWorkspaceStage,
  type RoundAnalysisCreateRequest,
} from "../api/client";
import styles from "../App.module.css";
import { JobStartActions } from "../jobs/JobStartActions";
import { AcceptedJobReceipt, useJobSubmission } from "../jobs/useJobSubmission";
import { parseSearchLimits } from "./RoundAnalysisFormatting";
import { RoundAnalysisHistory } from "./RoundAnalysisPresentation";

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
}: RoundAnalysisControlsProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const initialObservation =
    stage.selected_generated?.revision_id ??
    stage.input_options[0]?.node_revision_id ??
    "";
  const [observationRevisionId, setObservationRevisionId] =
    useState(initialObservation);
  const [gameId, setGameId] = useState("");
  const [roundId, setRoundId] = useState("");
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
    () => selectedAnalysisId ?? stage.analyses[0]?.analysis_id ?? null,
  );
  const [pendingRequest, setPendingRequest] = useState<{
    payload: EnqueueJobBody;
    analysisId: string;
  } | null>(null);
  const enqueue = useCallback(
    (payload: EnqueueJobBody, key: string) => client.enqueueJob(payload, key),
    [client],
  );
  const submission = useJobSubmission(enqueue);
  const uncertain =
    submission.error?.startsWith("Acceptance is uncertain") ?? false;
  const activeAnalysisId = selectedAnalysisId ?? trackedAnalysisId;
  const observation =
    stage.input_options.find(
      (option) => option.node_revision_id === observationRevisionId,
    ) ?? null;
  const activePlayers = players
    .split(",")
    .map((player) => player.trim())
    .filter(Boolean);
  const identifierPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  const identifiers = [
    ...activePlayers,
    dealer.trim(),
    firstTrickLeader.trim(),
    gameId.trim(),
    roundId.trim(),
  ];
  const search = parseSearchLimits(
    maxMissingPlays,
    maxHypotheses,
    maxSearchNodes,
  );
  const formErrors = [
    ...stage.run_blockers,
    ...(observation === null
      ? ["Select an exact stored table-observation revision."]
      : []),
    ...(!gameId.trim() ? ["Enter the game ID."] : []),
    ...(!roundId.trim() ? ["Enter the round ID."] : []),
    ...(!sessionId.trim() ? ["Enter the session ID."] : []),
    ...(activePlayers.length !== 4
      ? ["Enter four active player IDs in seat order."]
      : []),
    ...(activePlayers.length === 4 && new Set(activePlayers).size !== 4
      ? ["The four active player IDs must be distinct."]
      : []),
    ...(!dealer.trim() ? ["Enter the dealer player ID."] : []),
    ...(!firstTrickLeader.trim() ? ["Enter the first-trick leader."] : []),
    ...(activePlayers.length === 4 &&
    firstTrickLeader.trim() &&
    !activePlayers.includes(firstTrickLeader.trim())
      ? ["First-trick leader must be one of the four active players."]
      : []),
    ...(identifiers.some((value) => value && !identifierPattern.test(value))
      ? ["Round facts must use valid identifiers."]
      : []),
    ...(!rulesVersion ? ["Select an explicit rules version."] : []),
    ...(search === null
      ? [
          "Search limits must be valid positive numbers, with missing plays at least zero.",
        ]
      : []),
  ];
  const errors = [
    ...(submission.error ? [submission.error] : []),
    ...formErrors,
  ];
  const action = {
    id: "reconstruct-round-analysis",
    label: "Reconstruct one round",
    description:
      "Create a fresh reconstruction hypothesis from one exact table-observation revision and explicit round facts.",
    expectedOutput:
      "A new round-analysis result linked to its exact observation revision, rules, search limits, round facts, and optional correction constraints.",
    sections: [
      {
        title: "Exact observation input",
        content: (
          <label className={styles.pipelineRunSelector}>
            <span>Exact observation revision</span>
            <select
              aria-label="Exact observation revision"
              value={observationRevisionId}
              disabled={uncertain}
              onChange={(event) => setObservationRevisionId(event.target.value)}
            >
              <option value="">Select an observation revision</option>
              {stage.input_options.map((option) => (
                <option
                  key={`${option.node_id}:${option.node_revision_id}`}
                  value={option.node_revision_id}
                >
                  {option.display_label} · {option.node_id}@
                  {option.node_revision_id}
                </option>
              ))}
            </select>
          </label>
        ),
      },
      {
        title: "Required round facts",
        content: (
          <div className={styles.pipelineContextGrid}>
            <ContextField
              label="Game ID"
              value={gameId}
              onChange={setGameId}
              disabled={uncertain}
            />
            <ContextField
              label="Round ID"
              value={roundId}
              onChange={setRoundId}
              disabled={uncertain}
            />
            <ContextField
              label="Session ID"
              value={sessionId}
              onChange={setSessionId}
              disabled={uncertain}
            />
            <ContextField
              label="Four active players in seat order"
              value={players}
              onChange={setPlayers}
              placeholder="north, east, south, west"
              disabled={uncertain}
            />
            <ContextField
              label="Dealer player ID"
              value={dealer}
              onChange={setDealer}
              disabled={uncertain}
            />
            <ContextField
              label="First-trick leader"
              value={firstTrickLeader}
              onChange={setFirstTrickLeader}
              disabled={uncertain}
            />
          </div>
        ),
      },
      {
        title: "Rules and search limits",
        content: (
          <div className={styles.pipelineContextGrid}>
            <label className={styles.pipelineRunSelector}>
              <span>Rules version</span>
              <select
                aria-label="Rules version"
                value={rulesVersion}
                disabled={uncertain}
                onChange={(event) =>
                  setRulesVersion(event.target.value as "v1" | "")
                }
              >
                <option value="">Select rules version</option>
                <option value="v1">doko-normal v1</option>
              </select>
            </label>
            <ContextField
              label="Max missing plays"
              value={maxMissingPlays}
              onChange={setMaxMissingPlays}
              type="number"
              disabled={uncertain}
            />
            <ContextField
              label="Max hypotheses"
              value={maxHypotheses}
              onChange={setMaxHypotheses}
              type="number"
              disabled={uncertain}
            />
            <ContextField
              label="Max search nodes"
              value={maxSearchNodes}
              onChange={setMaxSearchNodes}
              type="number"
              disabled={uncertain}
            />
            <ContextField
              label="Correction constraint revision IDs (optional)"
              value={correctionIds}
              onChange={setCorrectionIds}
              disabled={uncertain}
            />
          </div>
        ),
      },
    ],
  };

  function buildRequest(): RoundAnalysisCreateRequest | null {
    if (
      formErrors.length ||
      observation === null ||
      search === null ||
      !rulesVersion
    )
      return null;
    const analysisId = crypto.randomUUID();
    return {
      schema_version: "round-analysis/v1",
      analysis_id: analysisId,
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

  return (
    <section
      className={styles.pipelineRunControls}
      aria-label="Round analysis actions"
    >
      <JobStartActions
        actions={[action]}
        submitting={submission.submitting}
        validationErrors={errors}
        canSubmit={(formErrors.length === 0 || uncertain) && stage.can_run}
        onStart={async () => {
          let pending = pendingRequest;
          if (!uncertain || pending === null) {
            const request = buildRequest();
            if (request === null) return false;
            pending = {
              analysisId: request.analysis_id,
              payload: {
                type: "round_analysis",
                context: { recording_id: recordingId },
                request: request as unknown as Record<string, unknown>,
              },
            };
            setPendingRequest(pending);
          }
          const accepted = await submission.submit(pending.payload);
          if (!accepted) return false;
          setPendingRequest(null);
          setTrackedAnalysisId(pending.analysisId);
          onSelectAnalysis(pending.analysisId);
          await onRefresh();
          return true;
        }}
      />
      {submission.job ? <AcceptedJobReceipt job={submission.job} /> : null}
      {stage.analyses.length > 0 ? (
        <RoundAnalysisHistory
          recordingId={recordingId}
          analyses={stage.analyses}
          activeAnalysisId={activeAnalysisId}
          completedAnalysis={stage.analyses.some(
            (analysis) =>
              analysis.analysis_id === activeAnalysisId &&
              analysis.state === "complete",
          )}
          onSelectAnalysis={(analysisId) => {
            setTrackedAnalysisId(analysisId);
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
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number";
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <label className={styles.pipelineRunSelector}>
      <span>{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
