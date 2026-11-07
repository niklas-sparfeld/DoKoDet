import { useCallback, useState } from "react";
import styles from "../App.module.css";
import {
  ProbabilityOverlay,
  readProbabilityMetrics,
} from "./ProbabilityOverlay";
import { readRunActivity } from "./ObservationRunFormatting";
import { describeCropInputRun } from "./pipelineLaunchRequest";

export type RunFacts = {
  run_id: string;
  job_id?: string | null;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
};

function readObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
export function RunStatus({
  run,
  showProbabilities,
}: {
  run: RunFacts;
  showProbabilities: boolean;
}) {
  const [probabilitiesOpen, setProbabilitiesOpen] = useState(false);
  const state = run.state;
  const progress = readObject(state.progress);
  const completed = readNumber(progress?.completed);
  const total = readNumber(progress?.total);
  const failure = readObject(state.terminal_failure);
  const failureMessage = readString(failure?.message);
  const activity = readRunActivity(state);
  const probabilityMetrics = showProbabilities
    ? readProbabilityMetrics(state)
    : null;
  const closeProbabilities = useCallback(() => setProbabilitiesOpen(false), []);
  const message =
    run.status === "complete"
      ? "The processor completed and retained its output revision."
      : run.status === "partial"
        ? "The processor returned a partial result. Review the successful items in the job details."
        : run.status === "failed"
          ? "The processor failed. Review the job details to retry with the exact frozen inputs."
          : run.status === "queued"
            ? "The processor request is queued."
            : "The processor is running.";
  return (
    <div className={styles.pipelineRunStatus} role="status">
      <p>{message}</p>
      {completed !== null && total !== null ? (
        <p>
          Progress: {completed} / {total} items
        </p>
      ) : null}
      {activity?.message !== null && activity?.message !== undefined ? (
        <p>
          {activity.message}
          {activity.step !== null && activity.steps !== null
            ? ` (step ${activity.step}/${activity.steps})`
            : ""}
        </p>
      ) : null}
      {failureMessage !== null ? <p>{failureMessage}</p> : null}
      {activity !== null && activity.logs.length > 0 ? (
        <details className={styles.pipelineRunHistory}>
          <summary>Processor log ({activity.logs.length} messages)</summary>
          <ol>
            {activity.logs.slice(-50).map((entry, index) => (
              <li key={`${entry.at ?? "log"}-${index}`}>{entry.message}</li>
            ))}
          </ol>
        </details>
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
          <dt>Input revisions</dt>
          <dd>{formatRequestList(run.request.input_revision_ids)}</dd>
        </div>
        <div>
          <dt>Implementation</dt>
          <dd>{formatIdentity(run.request.implementation)}</dd>
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
        <div>
          <dt>Crop input</dt>
          <dd>{describeCropInputRun(run.request)}</dd>
        </div>
      </dl>
      {run.job_id ? (
        <a href={`/jobs/${encodeURIComponent(run.job_id)}`}>Manage job</a>
      ) : null}
      {probabilityMetrics !== null ? (
        <button
          className={styles.detailButton}
          type="button"
          onClick={() => setProbabilitiesOpen(true)}
        >
          Show probabilities
        </button>
      ) : null}
      {probabilitiesOpen && probabilityMetrics !== null ? (
        <ProbabilityOverlay
          metrics={probabilityMetrics}
          runId={run.run_id}
          onClose={closeProbabilities}
        />
      ) : null}
    </div>
  );
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatRequestList(value: unknown): string {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value.join(", ") || "Accepted recording video"
    : "Unavailable";
}

function formatIdentity(value: unknown): string {
  const record = readObject(value);
  if (record === null) {
    return "Unavailable";
  }
  const name = readString(record.name);
  const version = readString(record.version);
  return name === null
    ? "Unavailable"
    : version === null
      ? name
      : `${name} ${version}`;
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

export function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
