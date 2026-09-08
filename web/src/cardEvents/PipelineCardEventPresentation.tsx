import type { ChangeEvent, RefObject } from "react";

import type {
  EditableEvent,
  PipelineCardEventType,
  PipelineEvent,
} from "./PipelineCardEventTypes";
import { PIPELINE_CARD_EVENT_TYPES } from "./PipelineCardEventTypes";
import {
  formatDuration,
  formatIdentifier,
  formatMicroseconds,
} from "./PipelineCardEventFormatting";
import styles from "../App.module.css";
import eventStyles from "./PipelineCardEventEditor.module.css";

export function EventSourceSurface({
  videoRef,
  videoUrl,
  recordingId,
  watchedPercent,
  watchedThroughUs,
  coverageComplete,
  durationUs,
  onAddEvent,
  onMarkCoverage,
  showCoverageControls,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  videoUrl: string;
  recordingId: string;
  watchedPercent: number;
  watchedThroughUs: number;
  coverageComplete: boolean;
  durationUs: number;
  onAddEvent: () => void;
  onMarkCoverage: () => void;
  showCoverageControls: boolean;
}) {
  return (
    <div className={eventStyles.sourceSurface}>
      <video
        ref={videoRef}
        className={eventStyles.sourceVideo}
        data-recording-source-video={recordingId}
        src={videoUrl}
        controls
        preload="metadata"
        aria-label={`CardEvent source video ${recordingId}`}
      />
      {showCoverageControls ? (
        <div className={eventStyles.coverage}>
          <span>Full-recording coverage</span>
          <strong>{Math.round(watchedPercent)}% watched</strong>
          <progress
            max={100}
            value={watchedPercent}
            aria-label="Full-recording coverage"
          />
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onAddEvent}
          >
            Add event at playhead
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            disabled={durationUs <= 0 || watchedThroughUs < durationUs}
            onClick={onMarkCoverage}
          >
            {coverageComplete
              ? "Full recording covered"
              : "Mark full recording covered"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function GeneratedEventView({
  events,
  loading,
  revisionId,
  videoUrl,
  durationUs,
  selectedEvent,
  videoRef,
  recordingId,
}: {
  events: PipelineEvent[];
  loading: boolean;
  revisionId: string | null;
  videoUrl: string;
  durationUs: number;
  selectedEvent: PipelineEvent | undefined;
  videoRef: RefObject<HTMLVideoElement | null>;
  recordingId: string;
}) {
  return (
    <section
      className={eventStyles.reviewPanel}
      aria-label="Generated event result"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Generated result</p>
          <h3>Event suggestions</h3>
        </div>
        <span className={styles.countLabel}>
          {events.length} event{events.length === 1 ? "" : "s"}
        </span>
      </div>
      <p className={styles.detailLead}>
        Generated events are immutable suggestions. Choose Review to copy this
        exact result into the maintained reference.
      </p>
      {revisionId !== null ? (
        <p className={styles.pipelineUrlState}>Source revision {revisionId}</p>
      ) : null}
      {loading ? (
        <p className={styles.detailEmptyState}>Loading generated events…</p>
      ) : events.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No generated event result is selected.
        </p>
      ) : (
        <div className={eventStyles.generatedSurface}>
          <video
            ref={videoRef}
            className={eventStyles.sourceVideo}
            data-recording-source-video={recordingId}
            src={videoUrl}
            controls
            preload="metadata"
            aria-label="CardEvent generated result source video"
          />
          {selectedEvent === undefined ? (
            <p className={styles.detailEmptyState}>
              Select a proposal from the Timeline Rail.
            </p>
          ) : (
            <dl className={styles.pipelineInspectorFacts}>
              <div>
                <dt>Selected proposal</dt>
                <dd>{formatIdentifier(selectedEvent.event_type)}</dd>
              </div>
              <div>
                <dt>Time</dt>
                <dd>
                  <span>{formatMicroseconds(selectedEvent.start_us)}</span>–
                  <span>{formatMicroseconds(selectedEvent.end_us)}</span>
                </dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{formatDuration(durationUs)} accepted video</dd>
              </div>
            </dl>
          )}
        </div>
      )}
    </section>
  );
}

export function EventDetails({
  event,
  durationUs,
  editable,
  onChange,
  onAccept,
  onReject,
  onUndo,
  onNudge,
}: {
  event: EditableEvent;
  durationUs: number;
  editable: boolean;
  onChange: (changes: Partial<PipelineEvent>) => void;
  onAccept: () => void;
  onReject: () => void;
  onUndo: () => void;
  onNudge: (delta: -1 | 1) => void;
}) {
  const duration = Math.max(0, durationUs) / 1_000_000;
  const updateNumber = (field: "start_us" | "end_us", value: string) => {
    const seconds = Number(value);
    if (Number.isFinite(seconds))
      onChange({ [field]: Math.round(seconds * 1_000_000) });
  };
  return (
    <section
      className={eventStyles.formPanel}
      aria-label="Selected event details"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Selected event</p>
          <h3>Event details</h3>
        </div>
        <ReviewStateBadge value={event.reviewState} />
      </div>
      <div className={eventStyles.formGrid}>
        <label>
          Start time (seconds)
          <input
            type="number"
            min="0"
            max={duration}
            step="0.000001"
            value={event.event.start_us / 1_000_000}
            disabled={!editable}
            onChange={(input) => updateNumber("start_us", input.target.value)}
            aria-label="Start time for selected event"
          />
        </label>
        <label>
          End time (seconds)
          <input
            type="number"
            min="0"
            max={duration}
            step="0.000001"
            value={event.event.end_us / 1_000_000}
            disabled={!editable}
            onChange={(input) => updateNumber("end_us", input.target.value)}
            aria-label="End time for selected event"
          />
        </label>
        <label>
          Event type
          <select
            value={event.event.event_type}
            disabled={!editable}
            onChange={(input: ChangeEvent<HTMLSelectElement>) =>
              onChange({
                event_type: input.target.value as PipelineCardEventType,
              })
            }
            aria-label="Event type for selected event"
          >
            {PIPELINE_CARD_EVENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {formatIdentifier(type)}
              </option>
            ))}
          </select>
        </label>
        <div className={eventStyles.frameReadout}>
          <span>Start frame</span>
          <strong>{Math.round((event.event.start_us / 1_000_000) * 30)}</strong>
        </div>
      </div>
      <div
        className={eventStyles.videoActions}
        aria-label="Selected event actions"
      >
        {event.reviewState === "pending" || event.reviewState === "affected" ? (
          <>
            <button
              className={`${styles.primaryButton} ${eventStyles.videoActionButton}`}
              type="button"
              onClick={onAccept}
            >
              Accept suggestion
            </button>
            <button
              className={`${styles.secondaryButton} ${eventStyles.videoActionButton}`}
              type="button"
              onClick={onReject}
            >
              Reject suggestion
            </button>
          </>
        ) : event.reviewState === "rejected" ? (
          <button
            className={`${styles.secondaryButton} ${eventStyles.videoActionButton}`}
            type="button"
            onClick={onUndo}
          >
            Undo rejection
          </button>
        ) : (
          <button
            className={`${styles.secondaryButton} ${eventStyles.videoActionButton}`}
            type="button"
            onClick={onReject}
          >
            Remove event
          </button>
        )}
        <button
          className={`${styles.secondaryButton} ${eventStyles.videoActionButton}`}
          type="button"
          onClick={() => onNudge(-1)}
          disabled={!editable}
        >
          Nudge -1 frame
        </button>
        <button
          className={`${styles.secondaryButton} ${eventStyles.videoActionButton}`}
          type="button"
          onClick={() => onNudge(1)}
          disabled={!editable}
        >
          Nudge +1 frame
        </button>
      </div>
    </section>
  );
}

export function ReviewCount({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className={eventStyles.reviewCount}>
      <span className={styles.statusLabel}>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function ReviewStateBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}
