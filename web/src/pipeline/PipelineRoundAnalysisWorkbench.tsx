import { createPortal } from "react-dom";
import { useSyncExternalStore } from "react";

import type { PipelineWorkspaceStage } from "../api/client";
import styles from "../App.module.css";
import { RecordingAnalysisView } from "../analysis/AnalysisView";
import { GeometrySurface } from "../workingArea/GeometrySurface";
import { useWorkingAreaFrame } from "../workingArea/workingAreaFrame";

export function PipelineRoundAnalysisWorkbench({
  recordingId,
  sourceSha256,
  stage,
  selectedAnalysisId,
  selectedTimeUs,
}: {
  recordingId: string;
  sourceSha256: string;
  stage: PipelineWorkspaceStage;
  selectedAnalysisId: string | null;
  selectedTimeUs: number | null;
  onTimeChange: (timeUs: number) => void;
  onAnalysisChange?: (analysisId: string) => void;
}) {
  const frameState = useWorkingAreaFrame({
    recordingId,
    sourceId: recordingId,
    sourceSha256,
    requestedTimeUs: selectedTimeUs ?? 0,
    mode: "sampled",
  });
  const analysis =
    stage.analyses.find(
      (candidate) => candidate.analysis_id === selectedAnalysisId,
    ) ?? null;
  const inspector = useSyncExternalStore(
    subscribeInspector,
    getInspector,
    () => null,
  );

  return (
    <div className={styles.analysisWorkbenchSurface} data-analysis-frame>
      {frameState.state === "ready" ? (
        <GeometrySurface
          frame={frameState.frame.identity}
          imageUrl={frameState.frame.imageUrl}
          overlays={[]}
        />
      ) : null}
      {frameState.state !== "ready" && inspector !== null
        ? createPortal(
            <p role={frameState.state === "failed" ? "alert" : "status"}>
              {frameState.state === "failed"
                ? `Source frame unavailable: ${frameState.reason}`
                : "Loading source frame…"}
            </p>,
            inspector,
          )
        : null}
      {analysis === null
        ? inspector === null
          ? null
          : createPortal(
              <p className={styles.detailEmptyState}>
                {stage.analyses.length === 0
                  ? "Choose an exact table-observation revision and rules version in the inspector."
                  : "Select a reconstruction from the Timeline Rail."}
              </p>,
              inspector,
            )
        : analysis.state === "complete" && inspector !== null
          ? createPortal(
              <RecordingAnalysisView
                analysisId={analysis.analysis_id}
                recordingId={recordingId}
              />,
              inspector,
            )
          : inspector === null
            ? null
            : createPortal(
                <section className={styles.analysisWorkbenchSummary}>
                  <p className={styles.statusLabel}>Selected round analysis</p>
                  <h2>{analysis.round_id}</h2>
                  <p>{analysis.state.replaceAll("_", " ")}</p>
                  {analysis.failure !== null ? (
                    <p className={styles.detailBlocker}>{analysis.failure}</p>
                  ) : null}
                </section>,
                inspector,
              )}
    </div>
  );
}

function getInspector(): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    '[data-analysis-inspector-slot="details"]',
  );
}

function subscribeInspector(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.body, { childList: true, subtree: true });
  return () => observer.disconnect();
}
