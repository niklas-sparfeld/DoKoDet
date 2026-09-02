import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type CardEventReview,
  type CardEventDevelopmentSplitPreview,
  type CardEventDevelopmentSplitPreviewRequest,
  type IdentityReviewReadiness,
  type RecordingDetail,
  type RecordingSummary,
  type VisibleCardReviewPreview,
  type VisibleCardReviewReadiness,
  visibleCardReviewBatchPagePath,
} from "./api/client";
import { RecordingAnalysisView } from "./analysis/AnalysisView";
import { CardEventEditor } from "./cardEvents/CardEventEditor";
import { IdentityReviewSection } from "./identityReview";
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
        <div>
          <dt>CardEvent review</dt>
          <dd>
            {formatIdentifier(recording.card_event_review_state)} ·{" "}
            {recording.card_event_event_count} event
            {recording.card_event_event_count === 1 ? "" : "s"}
          </dd>
        </div>
        <div>
          <dt>Development partition</dt>
          <dd>
            {recording.development_partition === null
              ? "Unassigned"
              : formatIdentifier(recording.development_partition)}
          </dd>
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
  const sourceVideoRef = useRef<HTMLVideoElement>(null);
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [assignmentDestination, setAssignmentDestination] =
    useState<CardEventDevelopmentSplitPreviewRequest["destination"]>("train");
  const [assignmentOperator, setAssignmentOperator] = useState("");
  const [assignmentPreview, setAssignmentPreview] =
    useState<CardEventDevelopmentSplitPreview | null>(null);
  const [assignmentBusy, setAssignmentBusy] = useState(false);
  const [assignmentError, setAssignmentError] = useState<string | null>(null);
  const [visibleCardReview, setVisibleCardReview] =
    useState<VisibleCardReviewReadiness | null>(null);
  const [visibleCardReviewError, setVisibleCardReviewError] = useState<
    string | null
  >(null);
  const [identityReview, setIdentityReview] =
    useState<IdentityReviewReadiness | null>(null);
  const [identityReviewError, setIdentityReviewError] = useState<string | null>(
    null,
  );

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

  const loadVisibleCardReview = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await client.getVisibleCardReview(recordingId, {
          signal,
        });
        if (!signal?.aborted) {
          if (isVisibleCardReviewReadiness(response)) {
            setVisibleCardReview(response);
            setVisibleCardReviewError(null);
          } else {
            setVisibleCardReview(null);
          }
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          setVisibleCardReviewError(describeError(reason));
        }
      }
    },
    [client, recordingId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => void loadVisibleCardReview(controller.signal),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadVisibleCardReview]);

  useEffect(() => {
    if (visibleCardReview?.state !== "preparing") {
      return;
    }
    const timer = window.setInterval(() => void loadVisibleCardReview(), 1000);
    return () => window.clearInterval(timer);
  }, [loadVisibleCardReview, visibleCardReview?.state]);

  const loadIdentityReview = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await client.getIdentityReview(recordingId, {
          signal,
        });
        if (!signal?.aborted && isIdentityReviewReadiness(response)) {
          setIdentityReview(response);
          setIdentityReviewError(null);
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          setIdentityReviewError(describeError(reason));
        }
      }
    },
    [client, recordingId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => void loadIdentityReview(controller.signal),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadIdentityReview]);

  useEffect(() => {
    if (identityReview?.state !== "preparing") {
      return;
    }
    const timer = window.setInterval(() => void loadIdentityReview(), 1000);
    return () => window.clearInterval(timer);
  }, [identityReview?.state, loadIdentityReview]);

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

  async function previewAssignment(
    destination: CardEventDevelopmentSplitPreviewRequest["destination"],
  ) {
    if (
      recording === null ||
      recording.training_use.active_split_digest === null
    ) {
      setAssignmentError("The active development split is not available.");
      return;
    }
    setAssignmentDestination(destination);
    setAssignmentBusy(true);
    setAssignmentError(null);
    setAssignmentPreview(null);
    try {
      const preview = await client.previewCardEventDevelopmentSplit({
        recording_id: recordingId,
        destination,
        expected_active_split_digest:
          recording.training_use.active_split_digest,
      });
      setAssignmentPreview(preview);
    } catch (reason: unknown) {
      setAssignmentError(describeError(reason));
    } finally {
      setAssignmentBusy(false);
    }
  }

  async function applyAssignment() {
    if (
      recording === null ||
      assignmentPreview === null ||
      !assignmentPreview.validation.valid ||
      recording.training_use.active_split_digest === null ||
      assignmentOperator.trim() === ""
    ) {
      return;
    }
    setAssignmentBusy(true);
    setAssignmentError(null);
    try {
      const applied = await client.applyCardEventDevelopmentSplit({
        recording_id: recordingId,
        destination: assignmentPreview.destination,
        expected_active_split_digest:
          recording.training_use.active_split_digest,
        preview_digest: assignmentPreview.preview_digest,
        operator: assignmentOperator.trim(),
      });
      setRecording((current) =>
        current === null
          ? current
          : {
              ...current,
              training_use: {
                ...current.training_use,
                eligibility: "eligible",
                development_partition: applied.destination,
                active_split_version_id: applied.split_version_id,
                active_split_digest: applied.split_version_digest,
                blocker: null,
              },
              next_action:
                applied.destination === "unassigned"
                  ? "Assign a development partition"
                  : `Assigned to ${applied.destination}`,
            },
      );
      setAssignmentPreview(null);
      setNotice(
        `Assigned ${assignmentPreview.affected_recordings.length} connected recording${assignmentPreview.affected_recordings.length === 1 ? "" : "s"} to ${formatIdentifier(applied.destination)}. Receipt ${applied.receipt_id}.`,
      );
    } catch (reason: unknown) {
      setAssignmentError(describeError(reason));
    } finally {
      setAssignmentBusy(false);
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
                href="#visible-cards"
                label="Visible cards"
                state={formatIdentifier(visibleCardReview?.state ?? "loading")}
              />
              <DetailProgressLink
                href="#identity-review"
                label="Identities"
                state={formatIdentifier(identityReview?.state ?? "loading")}
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

          <RecordingSection recording={recording} videoRef={sourceVideoRef} />
          <CardEventSection
            recording={recording}
            videoRef={sourceVideoRef}
            onReviewSaved={(review) =>
              setRecording((current) =>
                current === null
                  ? current
                  : {
                      ...current,
                      card_event_review: {
                        state: review.review_state,
                        event_count: countReviewEvents(review),
                        reviewed_at: review.completed_at,
                      },
                      training_use: {
                        ...current.training_use,
                        eligibility:
                          review.review_state === "completed"
                            ? "eligible"
                            : "review_required",
                        blocker:
                          review.review_state === "completed"
                            ? null
                            : "Complete the full recording CardEvent review before training use.",
                      },
                      next_action:
                        review.review_state === "completed"
                          ? "Assign a development partition"
                          : "Review CardEvent events",
                    },
              )
            }
          />
          <VisibleCardReviewSection
            recordingId={recording.recording_id}
            review={visibleCardReview}
            error={visibleCardReviewError}
            onChanged={setVisibleCardReview}
          />
          <IdentityReviewSection
            recordingId={recording.recording_id}
            review={identityReview}
            error={identityReviewError}
            onChanged={setIdentityReview}
          />
          <TrainingUseSection
            trainingUse={recording.training_use}
            assignmentDestination={assignmentDestination}
            assignmentOperator={assignmentOperator}
            assignmentPreview={assignmentPreview}
            assignmentBusy={assignmentBusy}
            assignmentError={assignmentError}
            onDestinationChange={(destination) => {
              setAssignmentDestination(destination);
              setAssignmentPreview(null);
            }}
            onOperatorChange={setAssignmentOperator}
            onPreview={() => void previewAssignment(assignmentDestination)}
            onApply={() => void applyAssignment()}
          />
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

function RecordingSection({
  recording,
  videoRef,
}: {
  recording: RecordingDetail;
  videoRef: import("react").RefObject<HTMLVideoElement | null>;
}) {
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
          ref={videoRef}
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
  recording,
  videoRef,
  onReviewSaved,
}: {
  recording: RecordingDetail;
  videoRef: import("react").RefObject<HTMLVideoElement | null>;
  onReviewSaved: (review: CardEventReview) => void;
}) {
  const review = recording.card_event_review;
  const taskSelected =
    recording.training_use.card_event_task?.disposition === "selected";
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
        Review the full recording and save the CardEvent timeline here. Use the
        first frame where a card has substantially reached its final position.
      </p>
      {taskSelected ? (
        <CardEventEditor
          recordingId={recording.recording_id}
          videoUrl={recording.video.url}
          mediaFacts={recording.video.media_facts}
          summary={review}
          videoRef={videoRef}
          onSaved={onReviewSaved}
        />
      ) : (
        <p className={styles.detailEmptyState}>
          {review.state === "not_started"
            ? "No CardEvent review has been started."
            : `Review state: ${formatIdentifier(review.state)}.`}
        </p>
      )}
    </section>
  );
}

function VisibleCardReviewSection({
  recordingId,
  review,
  error,
  onChanged,
}: {
  recordingId: string;
  review: VisibleCardReviewReadiness | null;
  error: string | null;
  onChanged: (value: VisibleCardReviewReadiness) => void;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [preview, setPreview] = useState<VisibleCardReviewPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (review === null) {
    return null;
  }
  const currentReview = review;

  async function loadPreview() {
    setBusy(true);
    setActionError(null);
    try {
      setPreview(await client.previewVisibleCardReview(recordingId));
    } catch (reason: unknown) {
      setActionError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createBatch() {
    if (
      preview === null ||
      !preview.validation.valid ||
      preview.request_digest === null
    ) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const batch = await client.createVisibleCardReviewBatch(recordingId, {
        preview_digest: preview.preview_digest,
        request_digest: preview.request_digest,
      });
      onChanged({
        ...currentReview,
        state: "preparing",
        message: "Preparing frames.",
        blocker: null,
        batch,
      });
      setPreview(null);
    } catch (reason: unknown) {
      setActionError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function retryBatch() {
    if (currentReview.batch === null) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const batch = await client.retryVisibleCardReviewBatch(
        currentReview.batch.batch_id,
      );
      onChanged({
        ...currentReview,
        state: "preparing",
        message: "Retrying failed items.",
        blocker: null,
        batch,
      });
    } catch (reason: unknown) {
      setActionError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const batch = review.batch;
  const progress = batch?.progress;
  return (
    <section id="visible-cards" className={styles.detailPanel}>
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Annotation assistant</p>
          <h2>Visible cards</h2>
        </div>
        <StatusBadge value={review.state} />
      </div>
      <p className={styles.detailLead}>
        Prepare exact-event frames and local finder proposals for human review.
        Finder proposals remain suggestions until an operator reviews them.
      </p>
      {error !== null ? (
        <p className={styles.errorMessage} role="alert">
          {error}
        </p>
      ) : null}
      <p className={styles.visibleCardReviewMessage} aria-live="polite">
        {review.message}
      </p>
      {progress !== undefined ? (
        <dl className={styles.detailStats}>
          <Stat
            label="Frames"
            value={`${progress.frames_extracted}/${progress.total_items}`}
          />
          <Stat
            label="Finder results"
            value={`${progress.finder_completed}/${progress.total_items}`}
          />
          <Stat label="Failed items" value={String(progress.failed_items)} />
          <Stat label="Phase" value={formatIdentifier(progress.phase)} />
        </dl>
      ) : null}
      {review.blocker !== null ? (
        <p className={styles.detailBlocker}>{review.blocker.message}</p>
      ) : null}
      {batch?.status === "failed" ? (
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => void retryBatch()}
          disabled={
            busy || !batch.failures.some((failure) => failure.retryable)
          }
        >
          {busy ? "Retrying…" : "Retry failed items"}
        </button>
      ) : null}
      {batch !== null ? (
        <a
          className={styles.recordingLink}
          href={visibleCardReviewBatchPagePath(batch.batch_id)}
        >
          Open review workspace
        </a>
      ) : null}
      {review.state === "ready" && batch === null ? (
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => void loadPreview()}
          disabled={busy}
        >
          {busy ? "Loading preview…" : "Preview visible-card batch"}
        </button>
      ) : null}
      {preview !== null ? (
        <div className={styles.visibleCardPreview} aria-live="polite">
          <p className={styles.statusLabel}>Creation preview</p>
          <dl className={styles.detailStats}>
            <Stat
              label="Reviewed events"
              value={String(preview.selected_event_count)}
            />
            <Stat
              label="Task enrollment"
              value={preview.task_enrollment_id ?? "Not enrolled"}
            />
            <Stat
              label="Permission"
              value={formatIdentifier(preview.source_permission)}
            />
            <Stat
              label="Development partition"
              value={preview.development_partition ?? "Unassigned"}
            />
          </dl>
          {preview.detector !== null ? (
            <p className={styles.detailMetaLine}>
              Detector {preview.detector.bundle_id} ·{" "}
              {preview.detector.provider_version} · digest{" "}
              {preview.detector.bundle_digest.slice(0, 12)}…
            </p>
          ) : null}
          {!preview.validation.valid ? (
            <ul className={styles.detailList}>
              {preview.validation.blockers.map((blocker) => (
                <li key={`${blocker.code}:${blocker.message}`}>
                  {blocker.message}
                </li>
              ))}
            </ul>
          ) : (
            <button
              className={styles.primaryButton}
              type="button"
              onClick={() => void createBatch()}
              disabled={busy}
            >
              {busy ? "Starting…" : "Create visible-card batch"}
            </button>
          )}
        </div>
      ) : null}
      {batch?.status === "ready" ? (
        <p className={styles.detailMetaLine}>
          The batch is ready. Open the review workspace to finish and publish
          it.
        </p>
      ) : null}
      {batch?.status === "completed" ? (
        <div className={styles.visibleCardPublishPanel} role="status">
          <p className={styles.detailMetaLine}>
            Published visible-card review. The completed queue is immutable.
          </p>
          <dl className={styles.detailMetadata}>
            <Stat
              label="Reviewed version"
              value={batch.completed_version_id ?? "Not available"}
            />
            <Stat
              label="Version digest"
              value={batch.completed_version_digest ?? "Not available"}
            />
            <Stat
              label="Lifecycle receipt"
              value={batch.completion_receipt_id ?? "Not available"}
            />
            <Stat
              label="Freeze readiness"
              value={batch.downstream_readiness.message}
            />
          </dl>
        </div>
      ) : null}
      {actionError !== null ? (
        <p className={styles.errorMessage} role="alert">
          {actionError}
        </p>
      ) : null}
    </section>
  );
}

function TrainingUseSection({
  trainingUse,
  assignmentDestination,
  assignmentOperator,
  assignmentPreview,
  assignmentBusy,
  assignmentError,
  onDestinationChange,
  onOperatorChange,
  onPreview,
  onApply,
}: {
  trainingUse: RecordingDetail["training_use"];
  assignmentDestination: CardEventDevelopmentSplitPreviewRequest["destination"];
  assignmentOperator: string;
  assignmentPreview: CardEventDevelopmentSplitPreview | null;
  assignmentBusy: boolean;
  assignmentError: string | null;
  onDestinationChange: (
    value: CardEventDevelopmentSplitPreviewRequest["destination"],
  ) => void;
  onOperatorChange: (value: string) => void;
  onPreview: () => void;
  onApply: () => void;
}) {
  const task = trainingUse.card_event_task;
  const canAssign =
    trainingUse.eligibility === "eligible" &&
    trainingUse.active_split_digest !== null &&
    trainingUse.development_partition !== "test";
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
      {trainingUse.active_split_version_id !== null ? (
        <p className={styles.detailMetaLine}>
          Active split {trainingUse.active_split_version_id} · digest{" "}
          {trainingUse.active_split_digest?.slice(0, 12)}…
        </p>
      ) : null}
      {trainingUse.blocker !== null ? (
        <p className={styles.detailBlocker}>{trainingUse.blocker}</p>
      ) : (
        <p className={styles.detailEmptyState}>
          No current training-use blocker.
        </p>
      )}
      {trainingUse.development_group_keys.length > 0 ? (
        <details className={styles.sourceDetails}>
          <summary>Leakage group keys</summary>
          <ul className={styles.detailList}>
            {trainingUse.development_group_keys.map(([name, value]) => (
              <li key={`${name}:${value}`}>
                <strong>{formatIdentifier(name)}</strong>: {value}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {canAssign ? (
        <div className={styles.assignmentControls}>
          <p className={styles.statusLabel}>Change development partition</p>
          <label className={styles.fieldLabel}>
            Destination
            <select
              aria-label="Development partition destination"
              value={assignmentDestination}
              onChange={(event) =>
                onDestinationChange(
                  event.target
                    .value as CardEventDevelopmentSplitPreviewRequest["destination"],
                )
              }
              disabled={assignmentBusy}
            >
              <option value="train">Train</option>
              <option value="validation">Validation</option>
              <option value="unassigned">Unassigned</option>
            </select>
          </label>
          <label className={styles.fieldLabel}>
            Operator
            <input
              aria-label="Partition operator"
              value={assignmentOperator}
              onChange={(event) => onOperatorChange(event.target.value)}
              disabled={assignmentBusy}
              placeholder="Your name"
            />
          </label>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onPreview}
            disabled={assignmentBusy}
          >
            {assignmentBusy ? "Checking group…" : "Preview assignment"}
          </button>
          {assignmentError !== null ? (
            <p className={styles.errorMessage} role="alert">
              {assignmentError}
            </p>
          ) : null}
          {assignmentPreview !== null ? (
            <div className={styles.assignmentPreview} aria-live="polite">
              <p className={styles.statusLabel}>Affected group</p>
              <p>
                {assignmentPreview.affected_recordings.length} connected
                recording
                {assignmentPreview.affected_recordings.length === 1
                  ? ""
                  : "s"}{" "}
                · {formatIdentifier(assignmentPreview.destination)}
              </p>
              <p className={styles.detailMetaLine}>
                Proposed counts: train {assignmentPreview.proposed_counts.train}
                , validation {assignmentPreview.proposed_counts.validation},
                unassigned {assignmentPreview.proposed_counts.unassigned}
              </p>
              <ul className={styles.detailList}>
                {assignmentPreview.affected_recordings.map((item) => (
                  <li key={item.recording_id}>
                    {item.recording_id} ·{" "}
                    {formatIdentifier(item.current_partition)}
                  </li>
                ))}
              </ul>
              {!assignmentPreview.validation.valid ? (
                <ul className={styles.detailList}>
                  {assignmentPreview.validation.blockers.map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </ul>
              ) : (
                <button
                  className={styles.primaryButton}
                  type="button"
                  onClick={onApply}
                  disabled={assignmentBusy || assignmentOperator.trim() === ""}
                >
                  Confirm assignment to{" "}
                  {formatIdentifier(assignmentPreview.destination)}
                </button>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
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

function countReviewEvents(review: CardEventReview): number {
  const events = review.annotation.events;
  return Array.isArray(events) ? events.length : 0;
}

function isVisibleCardReviewReadiness(
  value: unknown,
): value is VisibleCardReviewReadiness {
  return (
    typeof value === "object" &&
    value !== null &&
    "schema_version" in value &&
    value.schema_version === "visible-card-review-readiness/v1"
  );
}

function isIdentityReviewReadiness(
  value: unknown,
): value is IdentityReviewReadiness {
  return (
    typeof value === "object" &&
    value !== null &&
    "schema_version" in value &&
    value.schema_version === "visual-card-identity-review-readiness/v1"
  );
}

function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}
