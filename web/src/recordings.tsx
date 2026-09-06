import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  repositoryBundleVideoPath,
  type RecordingSummary,
} from "./api/client";
import {
  RecordingPipelineWorkspace,
  type PipelineStageKey,
} from "./pipeline/RecordingPipelineWorkspace";
import styles from "./App.module.css";

export function RecordingListView() {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [recordings, setRecordings] = useState<RecordingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadRecordings = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await client.listRecordings({ signal });
        if (!signal?.aborted) {
          setRecordings(response.recordings);
          setError(null);
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) setError(describeError(reason));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => void loadRecordings(controller.signal),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadRecordings]);

  useEffect(() => {
    if (
      !recordings.some((recording) => recording.analyses.some(isActiveAnalysis))
    )
      return;
    const timer = window.setInterval(() => void loadRecordings(), 2000);
    return () => window.clearInterval(timer);
  }, [loadRecordings, recordings]);

  return (
    <main className={`${styles.shell} ${styles.recordingsPage}`}>
      <header className={styles.recordingsHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector</p>
          <h1>Recordings</h1>
        </div>
      </header>

      {error !== null ? (
        <section className={styles.panel} aria-live="polite">
          <p className={styles.statusLabel}>Unable to load recordings</p>
          <p>{error}</p>
        </section>
      ) : null}
      {loading && recordings.length === 0 ? (
        <p className={styles.loading} aria-live="polite">
          Loading recordings…
        </p>
      ) : recordings.length === 0 ? (
        <section className={styles.panel}>
          <h2>No recordings yet</h2>
          <p>Accepted recording bundles will appear here.</p>
        </section>
      ) : (
        <div className={styles.recordingList} aria-label="Recordings">
          {recordings.map((recording) => (
            <RecordingRow key={recording.recording_id} recording={recording} />
          ))}
        </div>
      )}
    </main>
  );
}

function RecordingRow({ recording }: { recording: RecordingSummary }) {
  return (
    <a
      className={styles.recordingRow}
      href={recordingPagePath(recording.recording_id)}
      aria-label={`Open ${recording.round_id}`}
    >
      <RecordingThumbnail
        recordingId={recording.recording_id}
        roundId={recording.round_id}
      />
      <div className={styles.recordingRowContent}>
        <h2>{recording.round_id}</h2>
      </div>
    </a>
  );
}

function RecordingThumbnail({
  recordingId,
  roundId,
}: {
  recordingId: string;
  roundId: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (video === null) return;

    let disposed = false;

    const captureScreenshot = () => {
      if (disposed || video.videoWidth === 0 || video.videoHeight === 0) return;

      try {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext("2d");
        if (context === null)
          throw new Error("The thumbnail canvas is unavailable.");
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        setScreenshot(canvas.toDataURL("image/jpeg", 0.78));
      } catch {
        setFailed(true);
      }
    };

    const seekToRandomFrame = () => {
      if (!Number.isFinite(video.duration) || video.duration <= 0) {
        setFailed(true);
        return;
      }

      const margin = Math.min(video.duration * 0.15, 2);
      const usableDuration = Math.max(0, video.duration - margin * 2);
      try {
        video.currentTime = margin + Math.random() * usableDuration;
      } catch {
        setFailed(true);
      }
    };

    const handleError = () => setFailed(true);
    video.addEventListener("loadedmetadata", seekToRandomFrame);
    video.addEventListener("seeked", captureScreenshot);
    video.addEventListener("error", handleError);
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seekToRandomFrame();
    }

    return () => {
      disposed = true;
      video.removeEventListener("loadedmetadata", seekToRandomFrame);
      video.removeEventListener("seeked", captureScreenshot);
      video.removeEventListener("error", handleError);
    };
  }, [recordingId]);

  return (
    <div
      className={`${styles.recordingThumbnail} ${failed ? styles.recordingThumbnailFallback : ""}`}
      role="img"
      aria-label={`Random screenshot from ${roundId}`}
    >
      {screenshot !== null ? (
        <img src={screenshot} alt="" />
      ) : (
        <video
          ref={videoRef}
          src={repositoryBundleVideoPath(recordingId)}
          preload="metadata"
          muted
          playsInline
          aria-hidden="true"
        />
      )}
      {failed ? <span>Preview unavailable</span> : null}
    </div>
  );
}

export function RecordingDetailView({
  recordingId,
  pipelineStage = null,
  pipelineCompare = false,
}: {
  recordingId: string;
  pipelineStage?: PipelineStageKey | null;
  pipelineCompare?: boolean;
}) {
  return (
    <RecordingPipelineWorkspace
      recordingId={recordingId}
      stageKey={pipelineStage}
      compare={pipelineCompare}
    />
  );
}

function isActiveAnalysis(
  analysis: RecordingSummary["analyses"][number],
): boolean {
  return analysis.state !== "complete" && analysis.state !== "failed";
}

export function recordingPagePath(recordingId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}`;
}

function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}
