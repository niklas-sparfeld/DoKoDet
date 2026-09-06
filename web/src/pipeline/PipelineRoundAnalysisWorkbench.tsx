import { useEffect, useRef, useState } from "react";

import {
  repositoryBundleVideoPath,
  type PipelineWorkspaceStage,
} from "../api/client";
import { RecordingAnalysisView } from "../analysis/AnalysisView";
import styles from "../App.module.css";

export function PipelineRoundAnalysisWorkbench({
  recordingId,
  stage,
  selectedAnalysisId,
  selectedTimeUs,
  onTimeChange,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  selectedAnalysisId: string | null;
  selectedTimeUs: number | null;
  onTimeChange: (timeUs: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const analysis =
    stage.analyses.find(
      (candidate) => candidate.analysis_id === selectedAnalysisId,
    ) ?? null;

  useEffect(() => {
    const video = videoRef.current;
    if (video === null || selectedTimeUs === null) return;
    const seek = () => {
      video.currentTime = selectedTimeUs / 1_000_000;
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) seek();
    else video.addEventListener("loadedmetadata", seek, { once: true });
    return () => video.removeEventListener("loadedmetadata", seek);
  }, [selectedTimeUs]);

  return (
    <div className={styles.analysisWorkbenchSurface}>
      {showAnalysis && analysis?.state === "complete" ? (
        <section className={styles.analysisWorkbenchDetails}>
          <div className={styles.analysisWorkbenchHeading}>
            <div>
              <p className={styles.statusLabel}>Round reconstruction</p>
              <h2>Evidence and counterfactual workbench</h2>
            </div>
            <button
              className={styles.detailButton}
              type="button"
              onClick={() => setShowAnalysis(false)}
            >
              Return to source
            </button>
          </div>
          <RecordingAnalysisView
            analysisId={analysis.analysis_id}
            recordingId={recordingId}
          />
        </section>
      ) : (
        <>
          <video
            ref={videoRef}
            className={styles.cardEventSourceVideo}
            data-recording-source-video={recordingId}
            src={repositoryBundleVideoPath(recordingId)}
            controls
            preload="metadata"
            aria-label={`Round-analysis source video ${recordingId}`}
            onTimeUpdate={(event) =>
              onTimeChange(
                Math.round(event.currentTarget.currentTime * 1_000_000),
              )
            }
          />
          {analysis === null ? (
            <p className={styles.detailEmptyState}>
              {stage.analyses.length === 0
                ? "Choose an exact table-observation revision and rules version in the inspector."
                : "Select a reconstruction from the Timeline Rail."}
            </p>
          ) : (
            <section className={styles.analysisWorkbenchSummary}>
              <div>
                <p className={styles.statusLabel}>Selected round analysis</p>
                <h2>{analysis.round_id}</h2>
              </div>
              <dl>
                <div>
                  <dt>State</dt>
                  <dd>{analysis.state.replaceAll("_", " ")}</dd>
                </div>
                <div>
                  <dt>Evidence</dt>
                  <dd>
                    {analysis.progress.completed} of {analysis.progress.total}{" "}
                    packages
                  </dd>
                </div>
                <div>
                  <dt>Exact observation input</dt>
                  <dd>
                    {analysis.input_revision_ids.join(", ") || "Unavailable"}
                  </dd>
                </div>
                <div>
                  <dt>Rules version</dt>
                  <dd>{rulesVersion(analysis.request)}</dd>
                </div>
              </dl>
              {analysis.failure !== null ? (
                <p className={styles.detailBlocker}>{analysis.failure}</p>
              ) : null}
              {analysis.state === "complete" ? (
                <button
                  className={styles.primaryButton}
                  type="button"
                  onClick={() => setShowAnalysis(true)}
                >
                  Open evidence and counterfactual workbench
                </button>
              ) : null}
            </section>
          )}
        </>
      )}
    </div>
  );
}

function rulesVersion(request: Record<string, unknown>): string {
  return typeof request.rules_version === "string"
    ? request.rules_version
    : "Unavailable";
}
