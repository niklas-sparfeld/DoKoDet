import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type RoundAnalysisStatus,
  type RoundAnalysisTimeline,
} from "./api/client";
import styles from "./App.module.css";

export function App() {
  const analysisId = readAnalysisId(window.location.pathname);

  if (analysisId === null) {
    return (
      <main className={styles.shell}>
        <p className={styles.eyebrow}>DokoDetector</p>
        <h1>Round analysis timeline</h1>
        <p className={styles.description}>
          Open an analysis with its ID to inspect the immutable analysis
          timeline.
        </p>
      </main>
    );
  }

  return <AnalysisSmokeView key={analysisId} analysisId={analysisId} />;
}

function AnalysisSmokeView({ analysisId }: { analysisId: string }) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [status, setStatus] = useState<RoundAnalysisStatus | null>(null);
  const [timeline, setTimeline] = useState<RoundAnalysisTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    void client
      .getRoundAnalysisStatus(analysisId, { signal: controller.signal })
      .then((nextStatus) => {
        if (controller.signal.aborted) {
          return;
        }
        setStatus(nextStatus);
        if (nextStatus.state !== "complete") {
          return;
        }
        return client
          .getRoundAnalysisTimeline(analysisId, { signal: controller.signal })
          .then((nextTimeline) => {
            if (!controller.signal.aborted) {
              setTimeline(nextTimeline);
            }
          });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(reason));
        }
      });

    return () => controller.abort();
  }, [analysisId, client]);

  return (
    <main className={styles.shell}>
      <p className={styles.eyebrow}>DokoDetector · Round analysis</p>
      <h1>Analysis smoke view</h1>
      <p className={styles.analysisId}>
        <span>Analysis ID</span> {analysisId}
      </p>
      {error !== null ? (
        <section className={styles.panel} aria-live="polite">
          <p className={styles.statusLabel}>Unable to load analysis</p>
          <p>{error}</p>
        </section>
      ) : status === null ? (
        <p className={styles.loading} aria-live="polite">
          Loading analysis…
        </p>
      ) : (
        <AnalysisStatus status={status} timeline={timeline} />
      )}
    </main>
  );
}

function AnalysisStatus({
  status,
  timeline,
}: {
  status: RoundAnalysisStatus;
  timeline: RoundAnalysisTimeline | null;
}) {
  return (
    <section className={styles.panel} aria-live="polite">
      <div className={styles.statusHeading}>
        <p className={styles.statusLabel}>Analysis status</p>
        <span className={styles.status} data-state={status.state}>
          {status.state}
        </span>
      </div>
      <dl className={styles.stats}>
        <div>
          <dt>Round</dt>
          <dd>{status.round_id}</dd>
        </div>
        <div>
          <dt>Evidence packages</dt>
          <dd>
            {status.completed_evidence_packages}/
            {status.total_evidence_packages}
          </dd>
        </div>
      </dl>
      {timeline === null ? (
        <p className={styles.description}>The timeline is not available yet.</p>
      ) : (
        <div className={styles.connected}>
          <p className={styles.statusLabel}>Timeline API connected</p>
          <p>{timeline.reconstruction_status} reconstruction</p>
          <p>
            {timeline.rows.length} evidence{" "}
            {timeline.rows.length === 1 ? "row" : "rows"} ·{" "}
            {timeline.hypotheses.length} retained{" "}
            {timeline.hypotheses.length === 1 ? "hypothesis" : "hypotheses"}
          </p>
        </div>
      )}
    </section>
  );
}

function readAnalysisId(pathname: string): string | null {
  const match = pathname.match(/^\/round-analyses\/([^/]+)\/?$/);
  return match === null ? null : decodeURIComponent(match[1]);
}

function describeError(reason: unknown): string {
  if (reason instanceof ApiError) {
    return `The backend returned HTTP ${reason.status}.`;
  }
  return "The backend could not be reached.";
}
