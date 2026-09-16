import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  repositoryBundleThumbnailPath,
  type RecordingSummary,
} from "./api/client";
import {
  RecordingPipelineWorkspace,
  type PipelineStageKey,
} from "./pipeline/RecordingPipelineWorkspace";
import { ProfileControl } from "./profile/ProfileControl";
import { formatPipelineStageState } from "./pipeline/recordingWorkspaceFormatting";
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
      !recordings.some(
        (recording) =>
          recording.analyses.some(isActiveAnalysis) ||
          isActivePipeline(recording),
      )
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
        <div className={styles.recordingRowHeading}>
          <h2>{recording.round_id}</h2>
        </div>
        <RecordingPipelineProgress status={recording.pipeline_status} />
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

const PIPELINE_PROGRESS_LABELS: Record<PipelineStageKey, string> = {
  events: "Events",
  visible_cards: "Visible cards",
  visual_identities: "Identities",
  table_observations: "Observations",
  round_analyses: "Analysis",
};

type PipelineProgressState = "complete" | "active" | "pending" | "failed";

function RecordingPipelineProgress({
  status,
}: {
  status: RecordingSummary["pipeline_status"];
}) {
  return (
    <ol
      className={styles.recordingPipelineProgress}
      aria-label="Pipeline progress"
    >
      {status.stages.map((stage, index) => {
        const progressState = pipelineProgressState(
          stage.state,
          index,
          status.stages,
        );
        const label = PIPELINE_PROGRESS_LABELS[stage.key];
        const stateLabel = formatPipelineStageState(stage.key, stage.state);
        return (
          <li
            key={stage.key}
            className={styles.recordingPipelineStep}
            data-state={progressState}
            data-stage-state={stage.state}
            aria-current={progressState === "active" ? "step" : undefined}
            aria-label={`${label}: ${stateLabel}`}
            title={`${label}: ${stateLabel}`}
          >
            <span className={styles.recordingPipelineMarker} aria-hidden="true">
              {pipelineProgressMarker(progressState, index)}
            </span>
            <span className={styles.recordingPipelineCopy}>
              <span className={styles.recordingPipelineLabel}>{label}</span>
              <span className={styles.recordingPipelineStatus}>
                {stateLabel}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function pipelineProgressState(
  state: RecordingSummary["pipeline_status"]["stages"][number]["state"],
  index: number,
  stages: RecordingSummary["pipeline_status"]["stages"],
): PipelineProgressState {
  if (state === "complete") return "complete";
  if (state === "failed") return "failed";
  if (state === "active-run" || state === "partial" || state === "draft") {
    return "active";
  }
  if (index === stages.findIndex((stage) => stage.state !== "complete")) {
    return "active";
  }
  return "pending";
}

function pipelineProgressMarker(
  state: PipelineProgressState,
  index: number,
): string {
  if (state === "complete") return "✓";
  if (state === "active") return "›";
  if (state === "failed") return "×";
  return String(index + 1);
}

function RecordingThumbnail({
  recordingId,
  roundId,
}: {
  recordingId: string;
  roundId: string;
}) {
  const [failed, setFailed] = useState(false);

  return (
    <div
      className={`${styles.recordingThumbnail} ${failed ? styles.recordingThumbnailFallback : ""}`}
      role="img"
      aria-label={`Cached thumbnail from ${roundId}`}
    >
      {!failed ? (
        <img
          src={repositoryBundleThumbnailPath(recordingId)}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : null}
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

function isActivePipeline(pipeline: RecordingSummary): boolean {
  return pipeline.pipeline_status.stages.some(
    (stage) => stage.state === "active-run",
  );
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
