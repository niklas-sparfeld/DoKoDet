import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createDokoDetectorClient,
  type PipelineRunResponse,
  type PipelineWorkspaceStage,
} from "../api/client";
import styles from "../App.module.css";
import {
  buildObservationRequest,
  describePipelineError,
  TERMINAL_RUN_STATES,
  toRunFacts,
} from "./ObservationRunFormatting";
import { PipelineRunStatus, RunHistory } from "./ObservationRunPresentation";
import { PipelineControlStatusBadge } from "./PipelineControlStatusBadge";
import { usePageVisibility } from "./usePageVisibility";

export type ObservationRunControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  stages: PipelineWorkspaceStage[];
  onRefresh: () => Promise<void>;
  compact?: boolean;
};

export function ObservationRunControls({
  recordingId,
  stage,
  stages,
  onRefresh,
  compact = false,
}: ObservationRunControlsProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const pageVisible = usePageVisibility();
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
    if (trackedRunId === null || !pageVisible) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    let controller: AbortController | null = null;
    const poll = async () => {
      if (cancelled) return;
      controller = new AbortController();
      try {
        const response = await getRun(trackedRunId, {
          signal: controller.signal,
        });
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
  }, [getRun, onRefresh, pageVisible, trackedRunId]);

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
            <PipelineControlStatusBadge value={selectedRun.status} />
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

function createUuid(): string {
  return typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-0000-4000-8000-${Math.random().toString(16).slice(2, 14)}`;
}

function createId(prefix: string): string {
  return `${prefix}-run-${createUuid().slice(0, 12)}`;
}
