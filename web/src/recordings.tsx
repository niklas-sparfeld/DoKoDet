import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "./api/transport";
import { createRecordingsClient } from "./api/recordingsClient";
import { type RecordingSummary } from "./api/recordingContracts";
import { RecordingPipelineWorkspace } from "./pipeline/RecordingPipelineWorkspace";
import type { PipelineNavigationStepKey } from "./pipeline/recordingPipelineUrl";
import { ProfileControl } from "./profile/ProfileControl";
import styles from "./App.module.css";

export function RecordingListView() {
  const client = useMemo(() => createRecordingsClient(), []);
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

  return (
    <main className={`${styles.shell} ${styles.recordingsPage}`}>
      <header className={styles.recordingsHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector</p>
          <h1>Recordings</h1>
        </div>
        <a href="/frame-reviews/0096-M4">Frame review queue</a>
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
      aria-label={`Open ${recording.display_name}`}
    >
      <RecordingThumbnail
        thumbnailUrl={recording.thumbnail_url}
        roundId={recording.display_name}
      />
      <div className={styles.recordingRowContent}>
        <div className={styles.recordingRowHeading}>
          <h2>{recording.display_name}</h2>
        </div>
        <dl className={styles.recordingMetadata} aria-label="Selected data">
          {recording.selections.map((selection) => (
            <div key={selection.content_type} data-state={selection.state}>
              <dt>{selection.content_type.replaceAll("_", " ")}</dt>
              <dd>{selectionLabel(selection)}</dd>
            </div>
          ))}
        </dl>
        {recording.metadata_state === "unavailable" ? (
          <p role="status">Recording metadata unavailable</p>
        ) : null}
        <dl className={styles.recordingMetadata}>
          {recording.received_at ? (
            <div>
              <dt>Received</dt>
              <dd>{formatTimestamp(recording.received_at)}</dd>
            </div>
          ) : null}
          {recording.session_id ? (
            <div>
              <dt>Session</dt>
              <dd title={recording.session_id}>
                {formatSessionId(recording.session_id)}
              </dd>
            </div>
          ) : null}
        </dl>
      </div>
    </a>
  );
}

function RecordingThumbnail({
  thumbnailUrl,
  roundId,
}: {
  thumbnailUrl: string | null;
  roundId: string;
}) {
  const [failed, setFailed] = useState(thumbnailUrl === null);

  return (
    <div
      className={`${styles.recordingThumbnail} ${failed ? styles.recordingThumbnailFallback : ""}`}
      role="img"
      aria-label={`Cached thumbnail from ${roundId}`}
    >
      {!failed && thumbnailUrl ? (
        <img
          src={thumbnailUrl}
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
  pipelineStage?: PipelineNavigationStepKey | null;
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

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatSessionId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function selectionLabel(
  selection: RecordingSummary["selections"][number],
): string {
  if (selection.state === "unavailable") return "Unavailable";
  const generated = selection.selected_generated !== null;
  const reference = selection.selected_completed_reference !== null;
  if (generated && reference) return "Generated and reference selected";
  if (generated) return "Generated selected";
  if (reference) return "Reference selected";
  return "Not selected";
}

export function recordingPagePath(recordingId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}`;
}

function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}
