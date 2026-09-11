import type { RefObject } from "react";

import type { EventState, PipelineEvent } from "./PipelineCardEventTypes";
import { CardEventFrameSurface } from "./CardEventFrameSurface";
import {
  formatDuration,
  formatIdentifier,
  formatMicroseconds,
} from "./PipelineCardEventFormatting";
import styles from "../App.module.css";
import { ShortcutButton } from "../pipeline/ShortcutButton";
import eventStyles from "./PipelineCardEventEditor.module.css";

export function EventSourceSurface({
  recordingId,
  requestedTimeUs,
  watchedPercent,
  watchedThroughUs,
  coverageComplete,
  durationUs,
  onAddEvent,
  onMarkCoverage,
  showCoverageControls,
}: {
  recordingId: string;
  requestedTimeUs: number;
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
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={requestedTimeUs}
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
            preload="none"
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
                <dd>Card-state change</dd>
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

export function CardEventReviewControls({
  hasPrevious,
  hasNext,
  selectedState,
  onPrevious,
  onNext,
  onSeek,
  onNudge,
  onAccept,
  onDismiss,
  onAddEvent,
}: {
  hasPrevious: boolean;
  hasNext: boolean;
  selectedState: EventState | null;
  onPrevious: () => void;
  onNext: () => void;
  onSeek: (deltaUs: number) => void;
  onNudge: (delta: -1 | 1) => void;
  onAccept: () => void;
  onDismiss: () => void;
  onAddEvent: () => void;
}) {
  const canDecide = selectedState === "pending" || selectedState === "affected";
  const canNudge = selectedState !== null;
  const dismissLabel =
    selectedState === "rejected" ? "Undo dismiss" : "Dismiss";
  return (
    <aside
      className={eventStyles.controlSidebar}
      aria-label="CardEvent review controls"
    >
      <p className={styles.statusLabel}>Review controls</p>
      <div className={eventStyles.controlGroup}>
        <ShortcutButton
          label="Previous"
          shortcut="Alt+Left"
          ariaShortcut="Alt+ArrowLeft"
          disabled={!hasPrevious}
          disabledReason="There is no previous event."
          onClick={onPrevious}
        />
        <ShortcutButton
          label="Next"
          shortcut="Alt+Right"
          ariaShortcut="Alt+ArrowRight"
          disabled={!hasNext}
          disabledReason="There is no next event."
          onClick={onNext}
        />
      </div>
      <div className={eventStyles.controlGroup}>
        <ShortcutButton
          label="Seek earlier"
          shortcut="Left"
          ariaShortcut="ArrowLeft"
          onClick={() => onSeek(-250_000)}
        />
        <ShortcutButton
          label="Seek later"
          shortcut="Right"
          ariaShortcut="ArrowRight"
          onClick={() => onSeek(250_000)}
        />
        <ShortcutButton
          label="Nudge earlier"
          shortcut=","
          ariaShortcut=","
          disabled={!canNudge}
          disabledReason="Select an event before nudging its time."
          onClick={() => onNudge(-1)}
        />
        <ShortcutButton
          label="Nudge later"
          shortcut="."
          ariaShortcut="."
          disabled={!canNudge}
          disabledReason="Select an event before nudging its time."
          onClick={() => onNudge(1)}
        />
      </div>
      <div className={eventStyles.controlGroup}>
        <ShortcutButton
          label="Accept"
          shortcut="A"
          ariaShortcut="A"
          variant="primary"
          disabled={!canDecide}
          disabledReason="Accept is available for pending events."
          onClick={onAccept}
        />
        <ShortcutButton
          label={dismissLabel}
          shortcut="D"
          ariaShortcut="D"
          disabled={selectedState === null}
          disabledReason="Select an event before dismissing it."
          onClick={onDismiss}
        />
        <ShortcutButton
          label="Add event"
          shortcut="N"
          ariaShortcut="N"
          variant="primary"
          onClick={onAddEvent}
        />
      </div>
    </aside>
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
