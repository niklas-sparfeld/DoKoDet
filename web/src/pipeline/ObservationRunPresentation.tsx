import type { PipelineRun } from "../api/client";
import styles from "../App.module.css";
import {
  formatValue,
  readNumber,
  readObject,
  readString,
  runStatusMessage,
  type RunFacts,
} from "./ObservationRunFormatting";
import { PipelineControlStatusBadge } from "./PipelineControlStatusBadge";

export function RunHistory({
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
            <PipelineControlStatusBadge value={run.status} />
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

export function PipelineRunStatus({
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
