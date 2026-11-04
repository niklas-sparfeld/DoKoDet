import { useEffect, useMemo, useState } from "react";

import {
  createDokoDetectorClient,
  type AutomatedPipelineRun,
  type AutomatedPipelineStartRequest,
  type RecordingDetail,
  type PipelineWorkspace,
  type PipelineWorkspaceStage,
} from "../api/client";
import styles from "../App.module.css";
import { recordingPipelinePath } from "./recordingPipelineUrl";

const STORAGE_PREFIX = "automated-pipeline-run:";
const RUNNING = new Set(["accepted", "queued", "running"]);
const STAGES = [
  ["event_proposals", "events", "Event proposals"],
  [
    "visible_card_and_pile_proposals",
    "visible_cards",
    "Visible cards and piles",
  ],
  [
    "card_scene_and_calibration",
    "visible_cards",
    "Card scenes and calibration",
  ],
  ["visual_identity_proposals", "visual_identities", "Visual identities"],
  ["table_observations", "table_observations", "Table observations"],
  ["reconstruction", "round_analyses", "Round analysis"],
] as const;

export function AutomatedPipelineControls({
  recordingId,
  workspace,
  onRefresh,
}: {
  recordingId: string;
  workspace: PipelineWorkspace;
  onRefresh: () => Promise<void>;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const storageKey = `${STORAGE_PREFIX}${recordingId}`;
  const [run, setRun] = useState<AutomatedPipelineRun | null>(null);
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [gameId, setGameId] = useState("");
  const [roundId, setRoundId] = useState("");
  const [players, setPlayers] = useState("");
  const [dealer, setDealer] = useState("");
  const [leader, setLeader] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void client
      .getRecording(recordingId)
      .then((recording) => {
        if (!cancelled) {
          setRecording(recording);
          setSessionId(recording.session_id);
          setGameId(recording.source.game_id ?? "");
          setRoundId(recording.source.round_id ?? recording.round_id);
        }
      })
      .catch(() => undefined);
    const runId = window.localStorage.getItem(storageKey);
    if (runId !== null)
      void client
        .getAutomatedPipelineRun(recordingId, runId)
        .then((value) => {
          if (!cancelled) setRun(value);
        })
        .catch(() => {
          if (!cancelled) window.localStorage.removeItem(storageKey);
        });
    return () => {
      cancelled = true;
    };
  }, [client, recordingId, storageKey]);

  const activeRunId = run?.run_id;
  const activeRunStatus = run?.status;
  useEffect(() => {
    if (
      activeRunId === undefined ||
      activeRunStatus === undefined ||
      !RUNNING.has(activeRunStatus)
    )
      return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await client.getAutomatedPipelineRun(
          recordingId,
          activeRunId,
        );
        if (cancelled) return;
        setRun(next);
        if (!RUNNING.has(next.status)) {
          await onRefresh();
          return;
        }
      } catch (reason) {
        if (!cancelled)
          setMessage(
            reason instanceof Error
              ? reason.message
              : "Unable to refresh pipeline status.",
          );
      }
      if (!cancelled) timer = window.setTimeout(() => void poll(), 1200);
    };
    timer = window.setTimeout(() => void poll(), 0);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeRunId, activeRunStatus, client, onRefresh, recordingId]);

  async function start() {
    const activePlayers = players
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const missing = [
      ["session ID", sessionId],
      ["game ID", gameId.trim()],
      ["round ID", roundId.trim()],
      ["four player IDs", activePlayers.length === 4 ? "set" : ""],
      ["dealer", dealer.trim()],
      ["first-trick leader", leader.trim()],
    ].filter(([, value]) => !value);
    if (
      missing.length ||
      new Set(activePlayers).size !== 4 ||
      !activePlayers.includes(dealer.trim()) ||
      !activePlayers.includes(leader.trim())
    ) {
      setMessage(
        `Fix round prerequisites before starting: ${missing.map(([name]) => name).join(", ") || "use four distinct players and select dealer and leader from them"}.`,
      );
      return;
    }
    setBusy(true);
    setMessage(null);
    const config = (stageKey: string, fallback: Record<string, unknown>) => {
      const stage = workspace.stages.find((item) => item.key === stageKey);
      const latest = stage?.runs[0] as
        | (PipelineWorkspaceStage["runs"][number] & {
            configuration?: Record<string, unknown>;
          })
        | undefined;
      const previous = latest?.configuration ?? latest?.request.configuration;
      const result = {
        ...fallback,
        ...(previous && typeof previous === "object" ? previous : {}),
      };
      if (
        typeof result.provider === "string" &&
        !result.provider.startsWith("local")
      ) {
        result.provider =
          typeof fallback.provider === "string" ? fallback.provider : "local";
      }
      return result;
    };
    const payload: AutomatedPipelineStartRequest = {
      idempotency_key: crypto.randomUUID(),
      session_id: sessionId.trim(),
      round_id: roundId.trim(),
      round_context: {
        game_id: gameId.trim(),
        round_id: roundId.trim(),
        active_players: activePlayers,
        dealer: dealer.trim(),
        first_trick_leader: leader.trim(),
      },
      rules_version: "v1",
      search: {
        max_missing_plays: 1,
        max_hypotheses: 256,
        max_search_nodes: 250000,
      },
      stage_requests: {
        event_proposals: { configuration: config("events", {}) },
        visible_card_and_pile_proposals: {
          configuration: config("visible_cards", {
            provider: "local-rfdetr-segmentation",
          }),
        },
        card_scene_and_calibration: { configuration: {} },
        visual_identity_proposals: {
          configuration: config("visual_identities", { provider: "local" }),
        },
        table_observations: { configuration: {} },
      },
    };
    try {
      const accepted = await client.startAutomatedPipelineRun(
        recordingId,
        payload,
      );
      window.localStorage.setItem(storageKey, accepted.run_id);
      setRun(accepted);
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Pipeline preflight failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  const blocked = recording !== null && recording.video === null;
  return (
    <section
      className={styles.pipelineRunControls}
      aria-labelledby="automated-pipeline-heading"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Complete pipeline</p>
          <h3 id="automated-pipeline-heading">Run all stages</h3>
        </div>
      </div>
      <div className={styles.pipelineContextGrid}>
        <Field label="Game ID" value={gameId} onChange={setGameId} />
        <Field label="Round ID" value={roundId} onChange={setRoundId} />
        <Field label="Session ID" value={sessionId} onChange={setSessionId} />
        <Field
          label="Four player IDs"
          value={players}
          onChange={setPlayers}
          placeholder="Player IDs in seat order, separated by commas"
        />
        <Field label="Dealer" value={dealer} onChange={setDealer} />
        <Field label="First-trick leader" value={leader} onChange={setLeader} />
      </div>
      <p className={styles.pipelineRunInputValue}>
        Rules: doko-normal v1. Search limits: 1 missing play, 256 hypotheses,
        250000 search nodes.
      </p>
      {blocked ? (
        <p className={styles.detailBlocker}>
          An accepted recording video is required.
        </p>
      ) : null}
      <button
        className={styles.primaryButton}
        type="button"
        disabled={busy || blocked || (run !== null && RUNNING.has(run.status))}
        onClick={() => void start()}
      >
        {busy ? "Checking prerequisites…" : "Start complete pipeline"}
      </button>
      {message !== null ? (
        <p role="alert" className={styles.pipelineRunMessage}>
          {message}
        </p>
      ) : null}
      {run !== null ? (
        <div aria-live="polite">
          <p>
            Run {run.run_id} · {run.status}
          </p>
          {run.failure ? (
            <p role="alert">
              {String(run.failure.message ?? JSON.stringify(run.failure))}
            </p>
          ) : null}
          <ol>
            {run.stages.map((stage) => {
              const definition = STAGES.find(([name]) => name === stage.name);
              if (!definition) return null;
              const [, routeStage, label] = definition;
              const analysisId =
                stage.name === "reconstruction"
                  ? stage.output_revision_ids[0]
                  : null;
              const href = recordingPipelinePath(
                recordingId,
                routeStage,
                analysisId ? { analysis: analysisId } : {},
              );
              return (
                <li key={stage.name}>
                  <a href={href}>{label}</a>: {stage.status}
                  {stage.failure
                    ? ` — ${String(stage.failure.message ?? JSON.stringify(stage.failure))}`
                    : ""}
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className={styles.pipelineRunSelector}>
      <span>{label}</span>
      <input
        aria-label={label}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
