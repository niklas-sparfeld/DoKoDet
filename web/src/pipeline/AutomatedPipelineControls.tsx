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
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void client
      .getRecording(recordingId)
      .then((recording) => {
        if (!cancelled) {
          setRecording(recording);
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

  async function start() {
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
      await onRefresh();
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
            Run {run.run_id} · {run.status} ·{" "}
            <a href={`/jobs/${encodeURIComponent(run.job_id ?? run.run_id)}`}>
              View job
            </a>
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
