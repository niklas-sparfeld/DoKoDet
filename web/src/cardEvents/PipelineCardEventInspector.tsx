import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type { PipelineReferenceResource } from "../api/client";
import styles from "../App.module.css";
import eventStyles from "./PipelineCardEventEditor.module.css";
import {
  formatIdentifier,
  formatMicroseconds,
} from "./PipelineCardEventFormatting";
import type {
  EditableEvent,
  PipelineEvent,
  SaveState,
} from "./PipelineCardEventTypes";
import { ReviewCount, ReviewStateBadge } from "./PipelineCardEventPresentation";

export type EventInspectorSlots = {
  action: HTMLElement;
  save: HTMLElement;
  selection: HTMLElement;
};

export type EventInspectorProps = {
  slots: EventInspectorSlots | null;
  inspectorEnabled: boolean;
  view: "generated" | "reviewed";
  reference: PipelineReferenceResource | null;
  generatedEvents: PipelineEvent[];
  generatedRevisionId: string | null;
  generatedLoading: boolean;
  selectedEvent: EditableEvent | undefined;
  selectedGeneratedEvent: PipelineEvent | undefined;
  pendingCount: number;
  acceptedCount: number;
  rejectedCount: number;
  saveState: SaveState;
  queueLength: number;
  firstUnappliedCommand: string | null;
  error: string | null;
  operatorId: string;
  reviewerId: string;
  setOperatorId: (value: string) => void;
  setReviewerId: (value: string) => void;
  creatingReference: boolean;
  completionBusy: boolean;
  completionBlocker: string | null;
  watchedPercent: number;
  watchedThroughUs: number;
  coverageComplete: boolean;
  durationUs: number;
  addEvent: () => void;
  markCoverage: () => void;
  retryQueuedCommands: () => void;
  reloadWinningDraft: () => Promise<void>;
  completeReference: () => Promise<void>;
  createReference: () => Promise<void>;
  onReviewRequested?: () => void;
};

export function useEventInspectorSlots(
  inspectorEnabled: boolean,
  view: "generated" | "reviewed",
): EventInspectorSlots | null {
  const [slots, setSlots] = useState<EventInspectorSlots | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const action = document.querySelector<HTMLElement>(
        '[data-event-inspector-slot="action"]',
      );
      const save = document.querySelector<HTMLElement>(
        '[data-event-inspector-slot="save"]',
      );
      const selection = document.querySelector<HTMLElement>(
        '[data-event-inspector-slot="selection"]',
      );
      if (action !== null && save !== null && selection !== null) {
        setSlots({ action, save, selection });
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [inspectorEnabled, view]);

  return slots;
}

export function EventInspectorPortals(props: EventInspectorProps) {
  const content = (
    <>
      <EventInspectorAction {...props} />
      <EventInspectorSaveState {...props} />
      <EventInspectorSelection {...props} />
    </>
  );
  if (!props.inspectorEnabled) return null;
  if (props.slots === null) {
    return <div className={eventStyles.standaloneInspector}>{content}</div>;
  }
  return (
    <>
      {createPortal(<EventInspectorAction {...props} />, props.slots.action)}
      {createPortal(<EventInspectorSaveState {...props} />, props.slots.save)}
      {createPortal(
        <EventInspectorSelection {...props} />,
        props.slots.selection,
      )}
    </>
  );
}

function EventInspectorAction({
  view,
  reference,
  generatedEvents,
  generatedRevisionId,
  operatorId,
  reviewerId,
  setOperatorId,
  setReviewerId,
  creatingReference,
  completionBusy,
  completionBlocker,
  completeReference,
  createReference,
  onReviewRequested,
}: EventInspectorProps) {
  if (view === "generated") {
    return (
      <>
        <p className={styles.statusLabel}>Primary action</p>
        <h2 id="pipeline-inspector-action">Review generated events</h2>
        <p className={styles.pipelineInspectorEmpty}>
          {generatedLoadingLabel(generatedEvents.length, generatedRevisionId)}
        </p>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={onReviewRequested}
          disabled={onReviewRequested === undefined}
        >
          Review
        </button>
      </>
    );
  }
  if (reference === null) {
    return (
      <>
        <p className={styles.statusLabel}>Primary action</p>
        <h2 id="pipeline-inspector-action">Start event review</h2>
        <p className={styles.pipelineInspectorEmpty}>
          Copy the selected generated result into the maintained reference.
        </p>
        <label className={styles.pipelineSelector}>
          <span>Operator ID</span>
          <input
            value={operatorId}
            onChange={(event) => setOperatorId(event.target.value)}
            placeholder="operator-01"
          />
        </label>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => void createReference()}
          disabled={creatingReference || operatorId.trim() === ""}
        >
          {creatingReference ? "Starting review…" : "Start review"}
        </button>
      </>
    );
  }
  return (
    <>
      <p className={styles.statusLabel}>Primary action</p>
      <h2 id="pipeline-inspector-action">
        {reference.state.draft_state === "completed"
          ? "Publish corrected reference"
          : "Complete event review"}
      </h2>
      {completionBlocker !== null ? (
        <p className={styles.detailBlocker} role="alert">
          {completionBlocker}
        </p>
      ) : null}
      <label className={styles.pipelineSelector}>
        <span>Operator ID</span>
        <input
          value={operatorId}
          onChange={(event) => setOperatorId(event.target.value)}
          placeholder="operator-01"
        />
      </label>
      <label className={styles.pipelineSelector}>
        <span>Reviewer ID</span>
        <input
          value={reviewerId}
          onChange={(event) => setReviewerId(event.target.value)}
          placeholder="reviewer-01"
        />
      </label>
      <button
        className={styles.primaryButton}
        type="button"
        onClick={() => void completeReference()}
        disabled={completionBusy || completionBlocker !== null}
      >
        {completionBusy
          ? "Completing reference…"
          : reference.state.draft_state === "completed"
            ? "Publish corrected reference"
            : "Complete reference"}
      </button>
    </>
  );
}

function EventInspectorSaveState({
  view,
  saveState,
  queueLength,
  firstUnappliedCommand,
  error,
  retryQueuedCommands,
  reloadWinningDraft,
}: EventInspectorProps) {
  return (
    <div className={eventStyles.inspectorState}>
      <div className={styles.pipelineInspectorSectionHeading}>
        <div>
          <p className={styles.statusLabel}>Save or execution state</p>
          <h2 id="pipeline-inspector-save-state">
            {view === "generated"
              ? "Read-only result"
              : formatIdentifier(saveState)}
          </h2>
        </div>
        <ReviewStateBadge value={view === "generated" ? "saved" : saveState} />
      </div>
      {error !== null ? (
        <div className={eventStyles.error} role="alert">
          <p>
            {saveState === "conflict"
              ? `Conflict: the first unapplied command is ${firstUnappliedCommand ?? "unknown"}. ${error}`
              : error}
          </p>
          <div className={eventStyles.errorActions}>
            {saveState === "conflict" ? (
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => void reloadWinningDraft()}
              >
                Reload winning draft and retry
              </button>
            ) : null}
            {queueLength > 0 &&
            (saveState === "error" || saveState === "retrying") ? (
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={retryQueuedCommands}
              >
                Retry queued commands
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EventInspectorSelection({
  slots,
  view,
  reference,
  selectedEvent,
  selectedGeneratedEvent,
  pendingCount,
  acceptedCount,
  rejectedCount,
  watchedPercent,
  watchedThroughUs,
  coverageComplete,
  durationUs,
  addEvent,
  markCoverage,
}: EventInspectorProps) {
  return (
    <div className={eventStyles.inspectorSelection}>
      <p className={styles.statusLabel}>Event selection</p>
      <div className={eventStyles.reviewCounts} aria-label="Event counts">
        <ReviewCount label="Accepted" value={acceptedCount} />
        <ReviewCount label="Pending" value={pendingCount} />
        <ReviewCount label="Rejected" value={rejectedCount} />
      </div>
      <p className={styles.pipelineInspectorEmpty}>
        {view === "reviewed"
          ? selectedEvent === undefined
            ? "Select an event from the Timeline Rail."
            : `Card-state change at ${formatMicroseconds(selectedEvent.event.start_us)}`
          : selectedGeneratedEvent === undefined
            ? "Select a proposal from the Timeline Rail."
            : `Card-state change at ${formatMicroseconds(selectedGeneratedEvent.start_us)}`}
      </p>
      {view === "reviewed" && reference !== null && slots !== null ? (
        <>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={addEvent}
          >
            Add event at playhead
          </button>
          <div className={eventStyles.coverageInspector}>
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
              disabled={durationUs <= 0 || watchedThroughUs < durationUs}
              onClick={markCoverage}
            >
              {coverageComplete
                ? "Full recording covered"
                : "Mark full recording covered"}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}

function generatedLoadingLabel(
  count: number,
  revisionId: string | null,
): string {
  return revisionId === null
    ? "No generated revision is selected."
    : `${count} generated suggestion${count === 1 ? "" : "s"} · immutable source result.`;
}
