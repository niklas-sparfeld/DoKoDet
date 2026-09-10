import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  repositoryBundleVideoPath,
  type RecordingSummary,
  type PipelineWorkspace,
} from "./api/client";
import {
  RecordingPipelineWorkspace,
  STAGE_LABELS,
  type PipelineStageKey,
} from "./pipeline/RecordingPipelineWorkspace";
import { ProfileControl } from "./profile/ProfileControl";
import styles from "./App.module.css";

export function RecordingListView() {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [recordings, setRecordings] = useState<RecordingSummary[]>([]);
  const [pipelineWorkspaces, setPipelineWorkspaces] = useState<
    Record<string, PipelineWorkspace>
  >({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadRecordings = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await client.listRecordings({ signal });
        if (!signal?.aborted) {
          setRecordings(response.recordings);
          setError(null);

          const workspaceResults = await Promise.all(
            response.recordings.map(async (recording) => {
              try {
                const workspace = await client.getRecordingPipeline(
                  recording.recording_id,
                  { signal },
                );
                return isPipelineWorkspace(workspace)
                  ? ([recording.recording_id, workspace] as const)
                  : null;
              } catch {
                return null;
              }
            }),
          );
          if (!signal?.aborted) {
            const nextWorkspaces: Record<string, PipelineWorkspace> = {};
            for (const result of workspaceResults) {
              if (result !== null) nextWorkspaces[result[0]] = result[1];
            }
            setPipelineWorkspaces(nextWorkspaces);
          }
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
      !recordings.some((recording) =>
        recording.analyses.some(isActiveAnalysis),
      ) &&
      !Object.values(pipelineWorkspaces).some(isActivePipeline)
    )
      return;
    const timer = window.setInterval(() => void loadRecordings(), 2000);
    return () => window.clearInterval(timer);
  }, [loadRecordings, pipelineWorkspaces, recordings]);

  return (
    <main className={`${styles.shell} ${styles.recordingsPage}`}>
      <header className={styles.recordingsHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector</p>
          <h1>Recordings</h1>
        </div>
        <ProfileControl />
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
            <RecordingRow
              key={recording.recording_id}
              recording={recording}
              pipeline={pipelineWorkspaces[recording.recording_id] ?? null}
            />
          ))}
        </div>
      )}
    </main>
  );
}

function RecordingRow({
  recording,
  pipeline,
}: {
  recording: RecordingSummary;
  pipeline: PipelineWorkspace | null;
}) {
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
        <div className={styles.recordingRowHeading}>
          <h2>{recording.round_id}</h2>
          <RecordingStatus recording={recording} pipeline={pipeline} />
        </div>
        <dl className={styles.recordingMetadata}>
          <div>
            <dt>Received</dt>
            <dd>{formatTimestamp(recording.received_at)}</dd>
          </div>
          <div>
            <dt>Session</dt>
            <dd title={recording.session_id}>
              {formatSessionId(recording.session_id)}
            </dd>
          </div>
        </dl>
      </div>
    </a>
  );
}

function RecordingStatus({
  recording,
  pipeline,
}: {
  recording: RecordingSummary;
  pipeline: PipelineWorkspace | null;
}) {
  const status = getRecordingStatus(recording, pipeline);
  return (
    <span
      className={`${styles.status} ${styles.recordingStatus}`}
      data-state={status.state}
    >
      {status.label}
    </span>
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

function isActivePipeline(pipeline: PipelineWorkspace): boolean {
  return pipeline.stages.some((stage) => stage.state === "active-run");
}

export type RecordingStatus = {
  label: string;
  state: "intake" | "analyzing" | "review" | "reviewed" | "complete" | "failed";
};

function getRecordingStatus(
  recording: RecordingSummary,
  pipeline: PipelineWorkspace | null = null,
): RecordingStatus {
  if (pipeline !== null) {
    const pipelineStatus = getPipelineStatus(pipeline);
    if (pipelineStatus !== null) return pipelineStatus;
  }

  return getAnalysisStatus(recording);
}

function getPipelineStatus(
  pipeline: PipelineWorkspace,
): RecordingStatus | null {
  const activeStage = [...pipeline.stages]
    .reverse()
    .find((stage) => stage.state === "active-run");
  if (activeStage !== undefined) {
    return {
      label: `Processing ${STAGE_LABELS[activeStage.key]}`,
      state: "analyzing",
    };
  }

  for (const stage of [...pipeline.stages].reverse()) {
    const label = STAGE_LABELS[stage.key];
    if (stage.key === "round_analyses" && stage.state === "complete") {
      return { label: "Analysis complete", state: "complete" };
    }
    if (stage.state === "failed") {
      return { label: `${label} failed`, state: "failed" };
    }
    if (stage.reference?.state === "complete") {
      return { label: `${label} reviewed`, state: "reviewed" };
    }
    if (
      stage.state === "draft" ||
      stage.state === "affected" ||
      stage.state === "incomplete-coverage"
    ) {
      return { label: `Reviewing ${label}`, state: "review" };
    }
    if (stage.state === "generated-only") {
      return {
        label: stage.has_maintained_reference
          ? `${label} ready for review`
          : `${label} ready`,
        state: "review",
      };
    }
    if (stage.state === "partial") {
      return { label: `${label} incomplete`, state: "review" };
    }
  }

  return null;
}

function getAnalysisStatus(recording: RecordingSummary): RecordingStatus {
  const latestAnalysis = recording.analyses.reduce<
    RecordingSummary["analyses"][number] | null
  >((latest, analysis) => {
    if (latest === null) return analysis;
    return analysis.created_at > latest.created_at ? analysis : latest;
  }, null);

  if (latestAnalysis === null) return { label: "Intake", state: "intake" };
  if (isActiveAnalysis(latestAnalysis)) {
    return { label: "In analysis", state: "analyzing" };
  }
  if (latestAnalysis.state === "failed") {
    return { label: "Failed", state: "failed" };
  }
  return { label: "Complete", state: "complete" };
}

function isPipelineWorkspace(
  value: PipelineWorkspace,
): value is PipelineWorkspace {
  return Array.isArray(value.stages);
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatSessionId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

export function recordingPagePath(recordingId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}`;
}

function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}
