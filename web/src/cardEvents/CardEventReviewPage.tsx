import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type CardEventReviewResource,
  type RecordingDetail,
} from "../api/client";
import { RecordingSection, recordingPagePath } from "../recordings";
import styles from "../App.module.css";

export function CardEventReviewPage({ reviewId }: { reviewId: string }) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [review, setReview] = useState<CardEventReviewResource | null>(null);
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      try {
        const resource = await client.getCardEventReviewResource(reviewId, {
          signal: controller.signal,
        });
        const recordingDetail = await client.getRecording(
          resource.recording_id,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          setReview(resource);
          setRecording(recordingDetail);
          setError(null);
        }
      } catch (reason: unknown) {
        if (!controller.signal.aborted) {
          setError(describeReviewPageError(reason));
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    };
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [client, reviewId]);

  if (loading && (review === null || recording === null)) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <a className={styles.backLink} href="/">
          ← Recordings
        </a>
        <p className={styles.loading} aria-live="polite">
          Loading CardEvent review…
        </p>
      </main>
    );
  }

  if (error !== null || review === null || recording === null) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <a className={styles.backLink} href="/">
          ← Recordings
        </a>
        <section className={styles.panel} aria-live="polite">
          <p className={styles.statusLabel}>Unable to load CardEvent review</p>
          <p>{error ?? "The CardEvent review is not available."}</p>
        </section>
      </main>
    );
  }

  const counts = countReviewEvents(review.events);
  const isCompleted = review.review_state === "completed";
  return (
    <main
      className={`${styles.shell} ${styles.recordingsPage} ${styles.cardEventReviewPage}`}
    >
      <a
        className={styles.backLink}
        href={recordingPagePath(recording.recording_id)}
      >
        ← Recording
      </a>
      <header className={styles.detailHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector · CardEvent review</p>
          <h1>CardEvent review</h1>
          <p className={styles.detailContext}>
            {recording.round_id} · Recording {recording.recording_id}
          </p>
        </div>
        <div className={styles.nextAction}>
          <span className={styles.statusLabel}>Review status</span>
          <strong>
            <ReviewStateBadge value={review.review_state} />
          </strong>
        </div>
      </header>

      <section
        className={styles.detailPanel}
        aria-label="CardEvent review summary"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Review resource</p>
            <h2>{isCompleted ? "Completed review" : "Draft review"}</h2>
          </div>
          <span className={styles.countLabel}>{formatEventCount(counts)}</span>
        </div>
        <p className={styles.detailLead}>
          {isCompleted
            ? "This completed review is read-only. Its annotation and lineage are immutable."
            : "This draft is owned by the named operator and can be continued from this stable page."}
        </p>
        <dl className={styles.cardEventReviewPageMetadata}>
          <ReviewMetadata label="Operator" value={review.operator} />
          <ReviewMetadata
            label="Created"
            value={formatTimestamp(review.created_at)}
          />
          <ReviewMetadata
            label="Updated"
            value={formatTimestamp(review.updated_at)}
          />
          <ReviewMetadata
            label="Reviewer"
            value={review.reviewer ?? "Not completed"}
          />
          <ReviewMetadata
            label="Completed"
            value={
              review.completed_at === null
                ? "Not completed"
                : formatTimestamp(review.completed_at)
            }
          />
          <ReviewMetadata
            label="Parent review"
            value={review.parent_review_id ?? "Initial review"}
          />
        </dl>
        <details className={styles.sourceDetails}>
          <summary>Technical review details</summary>
          <dl className={styles.cardEventReviewPageMetadata}>
            <ReviewMetadata label="Review ID" value={review.review_id} />
            <ReviewMetadata
              label="Source asset"
              value={review.source_asset_id}
            />
            <ReviewMetadata
              label="Source digest"
              value={review.source_sha256}
            />
            <ReviewMetadata
              label="Draft revision"
              value={String(review.draft_revision)}
            />
            <ReviewMetadata
              label="Parent version"
              value={review.parent_version_id ?? "Not available"}
            />
            <ReviewMetadata
              label="Completed version"
              value={review.completed_version_id ?? "Not available"}
            />
          </dl>
        </details>
      </section>

      <RecordingSection recording={recording} videoRef={videoRef} />

      <section
        className={styles.detailPanel}
        aria-label="CardEvent event collection"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Review history</p>
            <h2>CardEvent events</h2>
          </div>
          <span className={styles.countLabel}>{formatEventCount(counts)}</span>
        </div>
        <div className={styles.cardEventReviewCounts} aria-label="Event counts">
          <ReviewCount label="Reviewed" value={counts.reviewed} />
          <ReviewCount label="Proposed" value={counts.proposed} />
          <ReviewCount label="Dismissed" value={counts.dismissed} />
        </div>
        {review.events.length === 0 ? (
          <p className={styles.detailEmptyState}>No events in this review.</p>
        ) : (
          <div className={styles.tableScroller}>
            <table className={styles.cardEventReviewTable}>
              <caption className={styles.visuallyHidden}>
                CardEvent review events
              </caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Type</th>
                  <th scope="col">State</th>
                  <th scope="col">Origin</th>
                  <th scope="col">Lineage</th>
                </tr>
              </thead>
              <tbody>
                {[...review.events]
                  .sort(
                    (first, second) =>
                      first.effective_time_s - second.effective_time_s,
                  )
                  .map((event) => (
                    <tr key={event.event_id} data-state={event.state}>
                      <td>{formatTime(event.effective_time_s)}</td>
                      <td>{formatIdentifier(event.type)}</td>
                      <td>
                        <ReviewStateBadge value={event.state} />
                      </td>
                      <td>{formatIdentifier(event.origin)}</td>
                      <td>
                        {event.proposal === null
                          ? "Manual"
                          : event.proposal.proposal_id}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

function ReviewMetadata({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function ReviewCount({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ReviewStateBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}

function countReviewEvents(
  events: CardEventReviewResource["events"],
): Record<"reviewed" | "proposed" | "dismissed", number> {
  return {
    reviewed: events.filter((event) => event.state === "reviewed").length,
    proposed: events.filter((event) => event.state === "proposed").length,
    dismissed: events.filter((event) => event.state === "dismissed").length,
  };
}

function formatEventCount(counts: Record<string, number>): string {
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  return `${total} event${total === 1 ? "" : "s"}`;
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatTime(value: number): string {
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  return `${minutes}:${seconds.toFixed(3).padStart(6, "0")}`;
}

function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function describeReviewPageError(reason: unknown): string {
  if (reason instanceof ApiError && reason.body !== null) {
    const body = reason.body as { error?: { message?: string } };
    if (typeof body.error?.message === "string") {
      return body.error.message;
    }
  }
  return reason instanceof Error
    ? reason.message
    : "The CardEvent review could not be loaded.";
}
