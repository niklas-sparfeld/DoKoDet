import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type RecordingDetail,
  type RecordingSummary,
} from "./api/client";
import { RecordingAnalysisView } from "./analysis/AnalysisView";
import styles from "./App.module.css";

export function RecordingListView() {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [recordings, setRecordings] = useState<RecordingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [triggeringRecordingId, setTriggeringRecordingId] = useState<
    string | null
  >(null);

  const loadRecordings = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await client.listRecordings({ signal });
        if (!signal?.aborted) {
          setRecordings(response.recordings);
          setError(null);
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          setError(describeError(reason));
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
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
    ) {
      return;
    }
    const timer = window.setInterval(() => void loadRecordings(), 2000);
    return () => window.clearInterval(timer);
  }, [loadRecordings, recordings]);

  async function startAnalysis(recording: RecordingSummary) {
    setTriggeringRecordingId(recording.recording_id);
    setNotice(null);
    try {
      const status = await client.startRecordingAnalysis(
        recording.recording_id,
      );
      setNotice(`Analysis ${status.analysis_id} was queued.`);
      await loadRecordings();
    } catch (reason: unknown) {
      setError(describeError(reason));
    } finally {
      setTriggeringRecordingId(null);
    }
  }

  return (
    <main className={`${styles.shell} ${styles.recordingsPage}`}>
      <header className={styles.recordingsHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector</p>
          <h1>Recordings</h1>
          <p className={styles.description}>
            Start a new round analysis for an accepted recording, or open one
            that already exists.
          </p>
        </div>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => {
            setLoading(true);
            void loadRecordings();
          }}
          disabled={loading}
        >
          Refresh
        </button>
      </header>

      {notice !== null ? (
        <p className={styles.recordingNotice} role="status">
          {notice}
        </p>
      ) : null}
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
            <RecordingCard
              key={recording.recording_id}
              recording={recording}
              isTriggering={triggeringRecordingId === recording.recording_id}
              onStart={() => void startAnalysis(recording)}
            />
          ))}
        </div>
      )}
    </main>
  );
}

function RecordingCard({
  recording,
  isTriggering,
  onStart,
}: {
  recording: RecordingSummary;
  isTriggering: boolean;
  onStart: () => void;
}) {
  return (
    <article className={styles.recordingCard}>
      <header className={styles.recordingCardHeader}>
        <a
          className={styles.recordingCardLink}
          href={recordingPagePath(recording.recording_id)}
        >
          <p className={styles.eyebrow}>Round</p>
          <h2>{recording.round_id}</h2>
          <p className={styles.recordingId} title={recording.recording_id}>
            Recording {recording.recording_id}
          </p>
        </a>
        <div className={styles.recordingAction}>
          <a
            className={styles.recordingLink}
            href={recordingPagePath(recording.recording_id)}
          >
            Open recording
          </a>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={onStart}
            disabled={!recording.can_start_analysis || isTriggering}
          >
            {isTriggering ? "Starting…" : "Start new analysis"}
          </button>
          {!recording.can_start_analysis ? (
            <p className={styles.recordingBlocker}>
              {recording.analysis_blocker}
            </p>
          ) : null}
        </div>
      </header>

      <dl className={styles.recordingStats}>
        <div>
          <dt>Received</dt>
          <dd>{formatTimestamp(recording.received_at)}</dd>
        </div>
        <div>
          <dt>Session</dt>
          <dd title={recording.session_id}>{recording.session_id}</dd>
        </div>
        <div>
          <dt>Evidence packages</dt>
          <dd>{recording.evidence_package_ids.length}</dd>
        </div>
      </dl>

      <section className={styles.recordingAnalyses}>
        <div className={styles.sectionHeading}>
          <h3>Analyses</h3>
          <span className={styles.countLabel}>{recording.analyses.length}</span>
        </div>
        {recording.analyses.length === 0 ? (
          <p className={styles.emptyInline}>No analyses have been started.</p>
        ) : (
          <ul className={styles.analysisList}>
            {recording.analyses.map((analysis) => (
              <li
                key={analysis.analysis_id}
                className={styles.analysisListItem}
              >
                <div>
                  <StatusBadge value={analysis.state} />
                  <span className={styles.analysisTimestamp}>
                    {formatTimestamp(analysis.created_at)}
                  </span>
                  <p className={styles.analysisId} title={analysis.analysis_id}>
                    {analysis.analysis_id}
                  </p>
                  {analysis.state === "complete" &&
                  analysis.result_status !== null ? (
                    <p className={styles.analysisResult}>
                      Result: <StatusBadge value={analysis.result_status} />
                    </p>
                  ) : null}
                  {analysis.state === "failed" && analysis.error !== null ? (
                    <p className={styles.analysisError}>{analysis.error}</p>
                  ) : null}
                </div>
                {analysis.state === "complete" ? (
                  <a
                    className={styles.recordingLink}
                    href={analysisSelectionPath(
                      recording.recording_id,
                      analysis.analysis_id,
                    )}
                  >
                    Open timeline
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}

export function RecordingDetailView({
  recordingId,
  selectedAnalysisId,
}: {
  recordingId: string;
  selectedAnalysisId: string | null;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);

  const loadRecording = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await client.getRecording(recordingId, { signal });
        if (!signal?.aborted) {
          setRecording(response);
          setError(null);
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          setError(describeError(reason));
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [client, recordingId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => void loadRecording(controller.signal),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadRecording]);

  async function startAnalysis() {
    setTriggering(true);
    setNotice(null);
    setError(null);
    try {
      const status = await client.startRecordingAnalysis(recordingId);
      setNotice(`Analysis ${status.analysis_id} was queued.`);
      await loadRecording();
    } catch (reason: unknown) {
      setError(describeError(reason));
    } finally {
      setTriggering(false);
    }
  }

  return (
    <main className={`${styles.shell} ${styles.recordingsPage}`}>
      <a className={styles.backLink} href="/">
        ← Recordings
      </a>
      {error !== null && recording === null ? (
        <section className={styles.panel} aria-live="polite">
          <p className={styles.statusLabel}>Unable to load recording</p>
          <p>{error}</p>
        </section>
      ) : loading && recording === null ? (
        <p className={styles.loading} aria-live="polite">
          Loading recording…
        </p>
      ) : recording === null ? null : (
        <>
          <header className={styles.detailHeader}>
            <div>
              <p className={styles.eyebrow}>
                DokoDetector · Recording workspace
              </p>
              <h1>Recording details</h1>
              <p className={styles.detailContext}>
                {recording.round_id} · {formatTimestamp(recording.received_at)}
              </p>
            </div>
            <div className={styles.nextAction}>
              <span className={styles.statusLabel}>Next action</span>
              <strong>{recording.next_action}</strong>
            </div>
          </header>

          {notice !== null ? (
            <p className={styles.recordingNotice} role="status">
              {notice}
            </p>
          ) : null}
          {error !== null ? (
            <p className={styles.errorMessage} role="alert">
              {error}
            </p>
          ) : null}

          <nav aria-label="Recording workspace sections">
            <ol className={styles.detailProgress}>
              <DetailProgressLink
                href="#recording"
                label="Recording"
                state={recording.state}
              />
              <DetailProgressLink
                href="#card-events"
                label="Card events"
                state={formatIdentifier(recording.card_event_review.state)}
              />
              <DetailProgressLink
                href="#training-use"
                label="Training use"
                state={recording.training_use.eligibility}
              />
              <DetailProgressLink
                href="#round-analyses"
                label="Round analyses"
                state={formatAnalysisCount(recording.analyses.length)}
              />
            </ol>
          </nav>

          <RecordingSection recording={recording} />
          <CardEventSection review={recording.card_event_review} />
          <TrainingUseSection trainingUse={recording.training_use} />
          <RoundAnalysesSection
            recording={recording}
            selectedAnalysisId={selectedAnalysisId}
            isTriggering={triggering}
            onStart={() => void startAnalysis()}
          />
        </>
      )}
    </main>
  );
}

function DetailProgressLink({
  href,
  label,
  state,
}: {
  href: string;
  label: string;
  state: string;
}) {
  return (
    <li className={styles.detailProgressItem}>
      <a href={href}>{label}</a>
      <span>{state}</span>
    </li>
  );
}

function RecordingSection({ recording }: { recording: RecordingDetail }) {
  const mediaFacts = recording.video.media_facts;
  return (
    <section id="recording" className={styles.detailPanel}>
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Source</p>
          <h2>Recording</h2>
        </div>
        <StatusBadge value={recording.state} />
      </div>
      <div className={styles.detailRecordingLayout}>
        <video
          className={styles.detailSourceVideo}
          controls
          preload="metadata"
          src={recording.video.url}
          aria-label={`Source recording ${recording.recording_id}`}
        />
        <dl className={styles.detailStats}>
          <Stat label="Session" value={recording.session_id} />
          <Stat label="Round" value={recording.round_id} />
          <Stat
            label="Received"
            value={formatTimestamp(recording.received_at)}
          />
          <Stat
            label="Duration"
            value={
              mediaFacts === null
                ? "Not measured"
                : formatDuration(mediaFacts.duration_ms)
            }
          />
          <Stat
            label="Frame rate"
            value={
              mediaFacts === null
                ? "Not measured"
                : `${mediaFacts.nominal_frame_rate.toFixed(2)} fps`
            }
          />
          <Stat
            label="Evidence packages"
            value={String(recording.evidence_package_ids.length)}
          />
        </dl>
      </div>
      <details className={styles.sourceDetails}>
        <summary>Source identifiers and intake metadata</summary>
        <dl className={styles.detailMetadata}>
          <Stat label="Recording ID" value={recording.recording_id} />
          <Stat label="Source asset" value={recording.source_asset_id} />
          <Stat label="Video ID" value={recording.video_id} />
          <Stat
            label="Original file"
            value={recording.source.original_filename}
          />
          <Stat
            label="Acquisition"
            value={recording.source.acquisition_method}
          />
          <Stat label="Permission" value={recording.source.source_permission} />
          <Stat label="Retention" value={recording.source.retention_state} />
        </dl>
      </details>
    </section>
  );
}

function CardEventSection({
  review,
}: {
  review: RecordingDetail["card_event_review"];
}) {
  return (
    <section id="card-events" className={styles.detailPanel}>
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Annotation</p>
          <h2>Card events</h2>
        </div>
        <span className={styles.countLabel}>{review.event_count} events</span>
      </div>
      <p className={styles.detailLead}>
        Review the full recording and save the CardEvent timeline here. The
        editor will be available in the next workspace milestone.
      </p>
      <p className={styles.detailEmptyState}>
        {review.state === "not_started"
          ? "No CardEvent review has been started."
          : `Review state: ${formatIdentifier(review.state)}.`}
      </p>
    </section>
  );
}

function TrainingUseSection({
  trainingUse,
}: {
  trainingUse: RecordingDetail["training_use"];
}) {
  const task = trainingUse.card_event_task;
  return (
    <section id="training-use" className={styles.detailPanel}>
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Dataset workflow</p>
          <h2>Training use</h2>
        </div>
        <span className={styles.countLabel}>
          {trainingUse.development_partition === null
            ? "Unassigned"
            : formatIdentifier(trainingUse.development_partition)}
        </span>
      </div>
      <dl className={styles.detailStats}>
        <Stat
          label="Eligibility"
          value={formatIdentifier(trainingUse.eligibility)}
        />
        <Stat
          label="Development partition"
          value={
            trainingUse.development_partition === null
              ? "Unassigned"
              : formatIdentifier(trainingUse.development_partition)
          }
        />
        <Stat
          label="CardEvent task"
          value={
            task === null
              ? "Not enrolled"
              : formatIdentifier(task.lifecycle_state)
          }
        />
      </dl>
      {task !== null ? (
        <p className={styles.detailMetaLine}>
          {formatIdentifier(task.disposition)} · {task.operator}
        </p>
      ) : null}
      {trainingUse.blocker !== null ? (
        <p className={styles.detailBlocker}>{trainingUse.blocker}</p>
      ) : (
        <p className={styles.detailEmptyState}>
          No current training-use blocker.
        </p>
      )}
    </section>
  );
}

function RoundAnalysesSection({
  recording,
  selectedAnalysisId,
  isTriggering,
  onStart,
}: {
  recording: RecordingDetail;
  selectedAnalysisId: string | null;
  isTriggering: boolean;
  onStart: () => void;
}) {
  const selectedAnalysis = recording.analyses.find(
    (analysis) => analysis.analysis_id === selectedAnalysisId,
  );
  return (
    <section id="round-analyses" className={styles.detailPanel}>
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Optional derived artifact</p>
          <h2>Round analyses</h2>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={onStart}
          disabled={!recording.can_start_analysis || isTriggering}
        >
          {isTriggering ? "Starting…" : "Start new analysis"}
        </button>
      </div>
      {!recording.can_start_analysis && recording.analysis_blocker !== null ? (
        <p className={styles.detailBlocker}>{recording.analysis_blocker}</p>
      ) : null}
      {recording.analyses.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No analyses have been started. This does not block CardEvent review.
        </p>
      ) : (
        <ul className={styles.detailAnalysisList}>
          {recording.analyses.map((analysis) => (
            <li
              key={analysis.analysis_id}
              className={styles.detailAnalysisItem}
            >
              <div>
                <StatusBadge value={analysis.state} />
                <span className={styles.analysisTimestamp}>
                  {formatTimestamp(analysis.created_at)}
                </span>
                <p className={styles.analysisId} title={analysis.analysis_id}>
                  {analysis.analysis_id}
                </p>
                {analysis.state !== "complete" &&
                analysis.state !== "failed" ? (
                  <p className={styles.detailMetaLine}>
                    Evidence packages: {analysis.completed_evidence_packages}/
                    {analysis.total_evidence_packages}
                  </p>
                ) : null}
                {analysis.state === "failed" && analysis.error !== null ? (
                  <p className={styles.analysisError}>{analysis.error}</p>
                ) : null}
              </div>
              <a
                className={styles.recordingLink}
                href={analysisSelectionPath(
                  recording.recording_id,
                  analysis.analysis_id,
                )}
              >
                {analysis.state === "complete"
                  ? "Open timeline"
                  : "View status"}
              </a>
            </li>
          ))}
        </ul>
      )}
      {selectedAnalysisId !== null && selectedAnalysis === undefined ? (
        <p className={styles.detailBlocker}>
          This analysis is not linked to the recording detail.
        </p>
      ) : selectedAnalysis !== undefined ? (
        <RecordingAnalysisView
          key={selectedAnalysis.analysis_id}
          analysisId={selectedAnalysis.analysis_id}
          recordingId={recording.recording_id}
        />
      ) : null}
    </section>
  );
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
function isActiveAnalysis(
  analysis: RecordingSummary["analyses"][number],
): boolean {
  return analysis.state !== "complete" && analysis.state !== "failed";
}
function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
function recordingPagePath(recordingId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}`;
}
function analysisSelectionPath(
  recordingId: string,
  analysisId: string,
): string {
  return `${recordingPagePath(recordingId)}?analysis=${encodeURIComponent(analysisId)}`;
}
function formatAnalysisCount(count: number): string {
  return count === 0 ? "Not started" : `${count} available`;
}
function formatDuration(durationMs: number): string {
  const totalSeconds = Math.round(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}
function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}
