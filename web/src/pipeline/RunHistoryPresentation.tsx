import type { Dispatch, SetStateAction } from "react";
import type {
  PipelineRun,
  PipelineRunResponse,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import styles from "../App.module.css";
import { RunStatus, StatusBadge } from "./RunStatusPresentation";
import {
  describeCropInputRun,
  type RunStageKey,
} from "./pipelineLaunchRequest";

type Props = {
  selectedRun: PipelineRun | PipelineRunResponse | null;
  stage: PipelineWorkspaceStage;
  runStage: RunStageKey;
  trackedRunId: string | null;
  setTrackedRunId: Dispatch<SetStateAction<string | null>>;
  setLiveRun: Dispatch<SetStateAction<PipelineRunResponse | null>>;
  setMessage: Dispatch<SetStateAction<string | null>>;
};

export function RunHistoryPresentation({
  selectedRun,
  stage,
  runStage,
  trackedRunId,
  setTrackedRunId,
  setLiveRun,
  setMessage,
}: Props) {
  return (
    <>
      {selectedRun !== null ? (
        <>
          {selectedRun.job_id ? (
            <p>
              <a href={`/jobs/${encodeURIComponent(selectedRun.job_id)}`}>
                View job {selectedRun.job_id}
              </a>
            </p>
          ) : null}
          <RunStatus
            run={selectedRun}
            showProbabilities={runStage === "events"}
          />
        </>
      ) : null}

      {stage.runs.length > 0 ? (
        <details className={styles.pipelineRunHistory}>
          <summary>Retained runs and actual inputs</summary>
          <ul className={styles.pipelineRunList}>
            {stage.runs.map((run) => (
              <li key={run.run_id}>
                <button
                  className={styles.pipelineRunSelectButton}
                  type="button"
                  aria-pressed={run.run_id === trackedRunId}
                  onClick={() => {
                    setTrackedRunId(run.run_id);
                    setLiveRun(null);
                    setMessage(null);
                  }}
                >
                  <span>{run.run_id}</span>
                  <StatusBadge value={run.status} />
                </button>
                <span>
                  {run.input_revision_ids.length === 0
                    ? "Accepted recording video"
                    : `Input ${run.input_revision_ids.join(", ")}`}
                </span>
                {runStage === "visual_identities" ? (
                  <span>{describeCropInputRun(run.request)}</span>
                ) : null}
                <span>
                  {run.implementation.name} {run.implementation.version}
                  {run.model === null ? " · no model" : " · model retained"}
                </span>
                {run.failure !== null && run.failure !== undefined ? (
                  <span>{run.failure.message}</span>
                ) : null}
                {run.job_id ? (
                  <a href={`/jobs/${encodeURIComponent(run.job_id)}`}>
                    View job
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}
