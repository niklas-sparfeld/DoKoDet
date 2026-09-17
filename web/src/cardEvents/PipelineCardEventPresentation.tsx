import type { RefObject } from "react";
import { createPortal } from "react-dom";

import type {
  EditableEvent,
  EventState,
  PipelineEvent,
} from "./PipelineCardEventTypes";
import { CardEventFrameSurface } from "./CardEventFrameSurface";
import {
  formatDuration,
  formatIdentifier,
  formatMicroseconds,
} from "./PipelineCardEventFormatting";
import styles from "../App.module.css";
import {
  TimelineRailSeekingControls,
  TimelineRailSeekingPortal,
  useTimelineRailReviewControlsSlot,
  useTimelineRailSeekingSlot,
} from "../pipeline/TimelineRailSeekingControls";
import eventStyles from "./PipelineCardEventEditor.module.css";
import { ShortcutButton } from "../pipeline/ShortcutButton";

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
  selectedEvent,
  selectedBound,
  onSelectBound,
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
  selectedEvent?: EditableEvent;
  selectedBound?: "start" | "end";
  onSelectBound?: (bound: "start" | "end") => void;
}) {
  return (
    <div className={eventStyles.sourceSurface}>
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={requestedTimeUs}
      />
      {selectedEvent !== undefined && onSelectBound !== undefined ? (
        <div
          className={eventStyles.intervalNavigation}
          aria-label="Selected event frame navigation"
          role="group"
        >
          <div>
            <p className={styles.statusLabel}>Selected event interval</p>
            <p className={eventStyles.intervalSummary}>
              {formatMicroseconds(selectedEvent.event.start_us)}–
              {formatMicroseconds(selectedEvent.event.end_us)} · duration{" "}
              {formatMicroseconds(
                selectedEvent.event.end_us - selectedEvent.event.start_us,
              )}
              . Stable-end anchor:{" "}
              {formatMicroseconds(selectedEvent.event.end_us)}.
            </p>
          </div>
          <div
            className={eventStyles.intervalNavigationButtons}
            role="group"
            aria-label="Selected event bounds"
          >
            <button
              className={
                selectedBound === "start"
                  ? styles.pipelineToggleActive
                  : styles.pipelineToggle
              }
              type="button"
              aria-pressed={selectedBound === "start"}
              onClick={() => onSelectBound("start")}
            >
              Start {formatMicroseconds(selectedEvent.event.start_us)}
            </button>
            <button
              className={
                selectedBound === "end"
                  ? styles.pipelineToggleActive
                  : styles.pipelineToggle
              }
              type="button"
              aria-pressed={selectedBound === "end"}
              onClick={() => onSelectBound("end")}
            >
              Stable end {formatMicroseconds(selectedEvent.event.end_us)}
            </button>
          </div>
        </div>
      ) : null}
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
  referenceNeedsSeed = false,
}: {
  events: PipelineEvent[];
  loading: boolean;
  revisionId: string | null;
  videoUrl: string;
  durationUs: number;
  selectedEvent: PipelineEvent | undefined;
  videoRef: RefObject<HTMLVideoElement | null>;
  recordingId: string;
  referenceNeedsSeed?: boolean;
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
        {referenceNeedsSeed
          ? "Generated events are immutable suggestions. Start review to copy this exact result into the maintained reference."
          : "Generated events are immutable suggestions. Choose Review to copy this exact result into the maintained reference."}
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
  onMarkStart,
  onMarkStableEnd,
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
  onMarkStart: () => void;
  onMarkStableEnd: () => void;
  onAccept: () => void;
  onDismiss: () => void;
  onAddEvent: () => void;
}) {
  const timelineSeekingSlot = useTimelineRailSeekingSlot();
  const timelineReviewControlsSlot = useTimelineRailReviewControlsSlot();
  const canDecide = selectedState === "pending" || selectedState === "affected";
  const canNudge = selectedState !== null;
  const dismissLabel =
    selectedState === "rejected" ? "Undo dismiss" : "Dismiss";
  const seekingGroups = [
    {
      label: "Event navigation",
      controls: [
        {
          label: "Previous event",
          symbol: "⏮",
          shortcut: "ArrowLeft",
          ariaShortcut: "ArrowLeft",
          disabled: !hasPrevious,
          disabledReason: "There is no previous event.",
          onClick: onPrevious,
        },
        {
          label: "Next event",
          symbol: "⏭",
          shortcut: "ArrowRight",
          ariaShortcut: "ArrowRight",
          disabled: !hasNext,
          disabledReason: "There is no next event.",
          onClick: onNext,
        },
      ],
    },
    {
      label: "Frame seek",
      controls: [
        {
          label: "Seek left",
          symbol: "←",
          shortcut: "Alt+ArrowLeft",
          ariaShortcut: "Alt+ArrowLeft",
          onClick: () => onSeek(-250_000),
        },
        {
          label: "Seek right",
          symbol: "→",
          shortcut: "Alt+ArrowRight",
          ariaShortcut: "Alt+ArrowRight",
          onClick: () => onSeek(250_000),
        },
      ],
    },
  ] as const;
  const seeking =
    timelineSeekingSlot !== null ? (
      <TimelineRailSeekingPortal
        slot={timelineSeekingSlot}
        groups={seekingGroups}
      />
    ) : null;
  const controls = (
    <aside
      className={styles.recordingTimelineReviewControls}
      aria-label="CardEvent review controls"
    >
      {timelineSeekingSlot === null ? (
        <TimelineRailSeekingControls groups={seekingGroups} />
      ) : null}
      <div className={eventStyles.controlGroup}>
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
          label="Mark start"
          shortcut="S"
          ariaShortcut="S"
          disabled={!canNudge}
          disabledReason="Select an event before marking its start."
          onClick={onMarkStart}
        />
        <ShortcutButton
          label="Mark stable end"
          shortcut="E"
          ariaShortcut="E"
          disabled={!canNudge}
          disabledReason="Select an event before marking its stable end."
          onClick={onMarkStableEnd}
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
  return (
    <>
      {seeking}
      {timelineReviewControlsSlot === null
        ? controls
        : createPortal(controls, timelineReviewControlsSlot)}
    </>
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
