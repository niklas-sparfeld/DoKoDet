import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type RecordingSummary,
} from "./api/client";
import {
  RecordingPipelineWorkspace,
  recordingPipelinePath,
  type PipelineStageKey,
} from "./pipeline/RecordingPipelineWorkspace";
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
            Open an accepted recording to run processors, review maintained
            references, and inspect reconstruction results.
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
          <p className={styles.eyebrow}>Recording</p>
          <h2>{recording.round_id}</h2>
          <p className={styles.recordingId} title={recording.recording_id}>
            {recording.recording_id}
          </p>
        </a>
        <div className={styles.recordingAction}>
          <a
            className={styles.recordingLink}
            href={recordingPagePath(recording.recording_id)}
          >
            Open pipeline
          </a>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={onStart}
            disabled={!recording.can_start_analysis || isTriggering}
          >
            {isTriggering ? "Starting…" : "Start reconstruction"}
          </button>
          {!recording.can_start_analysis ? (
            <p className={styles.recordingBlocker}>
              {recording.analysis_blocker}
            </p>
          ) : null}
        </div>
      </header>

      <dl className={styles.recordingStats}>
        <Stat label="Received" value={formatTimestamp(recording.received_at)} />
        <Stat label="Session" value={recording.session_id} />
        <Stat
          label="Evidence packages"
          value={String(recording.evidence_package_ids.length)}
        />
        <Stat
          label="Round analyses"
          value={formatAnalysisCount(recording.analyses.length)}
        />
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
                    Open analysis
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
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

export function recordingPagePath(recordingId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}`;
}

function analysisSelectionPath(
  recordingId: string,
  analysisId: string,
): string {
  return recordingPipelinePath(recordingId, "round_analyses", {
    analysis: analysisId,
  });
}

function formatAnalysisCount(count: number): string {
  return count === 0 ? "Not started" : `${count} available`;
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
