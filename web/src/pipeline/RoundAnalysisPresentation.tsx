import type { RoundAnalysisStatus } from "../api/client";
import styles from "../App.module.css";
import { analysisStatusMessage } from "./RoundAnalysisFormatting";
import { analysisPath } from "./roundAnalysisUrl";
import { PipelineControlStatusBadge } from "./PipelineControlStatusBadge";

export function RoundAnalysisStatusPanel({
  recordingId,
  observationRevisionId,
  liveStatus,
  onSelectAnalysis,
}: {
  recordingId: string;
  observationRevisionId: string;
  liveStatus: RoundAnalysisStatus;
  onSelectAnalysis: (analysisId: string | null) => void;
}) {
  return (
    <div className={styles.pipelineRunStatus} role="status">
      <p>{analysisStatusMessage(liveStatus.state)}</p>
      <p>Exact observation input: {observationRevisionId || "Unavailable"}</p>
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
  );
}

export function RoundAnalysisHistory({
  recordingId,
  analyses,
  activeAnalysisId,
  completedAnalysis,
  onSelectAnalysis,
}: {
  recordingId: string;
  analyses: Array<{
    analysis_id: string;
    state: string;
    round_id: string;
    input_revision_ids: string[];
  }>;
  activeAnalysisId: string | null;
  completedAnalysis: boolean;
  onSelectAnalysis: (analysisId: string) => void;
}) {
  return (
    <details className={styles.pipelineRunHistory} open={completedAnalysis}>
      <summary>Retained analyses and actual inputs</summary>
      <ul className={styles.pipelineRunList}>
        {analyses.map((analysis) => (
          <li key={analysis.analysis_id}>
            <button
              className={styles.pipelineRunSelectButton}
              type="button"
              aria-pressed={analysis.analysis_id === activeAnalysisId}
              onClick={() => onSelectAnalysis(analysis.analysis_id)}
            >
              <span>{analysis.analysis_id}</span>
              <PipelineControlStatusBadge value={analysis.state} />
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
              {analysis.state === "complete" ? "Open timeline" : "Open status"}
            </a>
          </li>
        ))}
      </ul>
    </details>
  );
}
