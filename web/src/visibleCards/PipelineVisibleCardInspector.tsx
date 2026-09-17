import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type { PipelineReferenceResource } from "../api/client";
import styles from "../App.module.css";
import visibleStyles from "./PipelineVisibleCardEditor.module.css";
import {
  formatFrameState,
  formatFrameTime,
  formatIdentifier,
} from "./PipelineVisibleCardFormatting";
import type { EditableFrame, SaveState } from "./PipelineVisibleCardTypes";

export type VisibleCardInspectorSlots = {
  action: HTMLElement;
  save: HTMLElement;
  selection: HTMLElement;
};

export function useVisibleCardProposalSlot(): HTMLElement | null {
  const [slot, setSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSlot(
        document.querySelector<HTMLElement>(
          '[data-visible-card-proposal-slot="proposals"]',
        ),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  return slot;
}

export function useVisibleCardInspectorSlots(
  inspectorEnabled: boolean,
  view: "generated" | "reviewed",
): VisibleCardInspectorSlots | null {
  const [slots, setSlots] = useState<VisibleCardInspectorSlots | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const action = document.querySelector<HTMLElement>(
        '[data-visible-card-inspector-slot="action"]',
      );
      const save = document.querySelector<HTMLElement>(
        '[data-visible-card-inspector-slot="save"]',
      );
      const selection = document.querySelector<HTMLElement>(
        '[data-visible-card-inspector-slot="selection"]',
      );
      if (action !== null && save !== null && selection !== null) {
        setSlots({ action, save, selection });
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [inspectorEnabled, view]);

  return slots;
}

export type VisibleCardInspectorProps = {
  slots: VisibleCardInspectorSlots | null;
  inspectorEnabled: boolean;
  view: "generated" | "reviewed";
  reference: PipelineReferenceResource | null;
  frames: EditableFrame[];
  selectedFrame: EditableFrame | null;
  generatedFrames: EditableFrame[];
  generatedRevisionId: string | null;
  generatedLoading: boolean;
  pendingCount: number;
  completedFrameCount: number;
  coveragePercent: number;
  inspectedCount: number;
  saveState: SaveState;
  queueLength: number;
  firstUnappliedCommand: string | null;
  error: string | null;
  operatorId: string;
  reviewerId: string;
  setOperatorId: (value: string) => void;
  setReviewerId: (value: string) => void;
  creatingReference: boolean;
  referenceNeedsSeed: boolean;
  startReference: () => void;
  completionBusy: boolean;
  completionBlocker: string | null;
  restoreGeneratedSuggestions: () => void;
  canRestoreGeneratedSuggestions: boolean;
  retryQueuedCommands: () => void;
  reloadWinningDraft: () => Promise<void>;
  completeReference: () => Promise<void>;
  createReference: () => Promise<void>;
  onReviewRequested?: () => void;
};

export function VisibleCardInspectorPortals(props: VisibleCardInspectorProps) {
  if (!props.inspectorEnabled) return null;
  if (props.slots === null) {
    return (
      <div className={visibleStyles.standaloneInspector}>
        <VisibleCardInspectorAction {...props} />
        <VisibleCardInspectorSaveState {...props} />
        <VisibleCardInspectorSelection {...props} />
      </div>
    );
  }
  return (
    <>
      {createPortal(
        <VisibleCardInspectorAction {...props} />,
        props.slots.action,
      )}
      {createPortal(
        <VisibleCardInspectorSaveState {...props} />,
        props.slots.save,
      )}
      {createPortal(
        <VisibleCardInspectorSelection {...props} />,
        props.slots.selection,
      )}
    </>
  );
}

function VisibleCardInspectorAction({
  view,
  reference,
  generatedFrames,
  generatedRevisionId,
  generatedLoading,
  operatorId,
  reviewerId,
  setOperatorId,
  setReviewerId,
  creatingReference,
  referenceNeedsSeed,
  startReference,
  saveState,
  queueLength,
  completionBusy,
  completionBlocker,
  completeReference,
  createReference,
  onReviewRequested,
}: VisibleCardInspectorProps) {
  if (view === "generated") {
    return (
      <>
        <p className={styles.statusLabel}>Primary action</p>
        <h2 id="pipeline-inspector-action">Review visible cards</h2>
        <p className={styles.pipelineInspectorEmpty}>
          {generatedLoading
            ? "Loading generated visible cards…"
            : generatedRevisionId === null
              ? "No generated revision is selected."
              : `${generatedFrames.length} resolved frame${generatedFrames.length === 1 ? "" : "s"} · immutable source result.`}
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
  if (referenceNeedsSeed) {
    return (
      <>
        <p className={styles.statusLabel}>Primary action</p>
        <h2 id="pipeline-inspector-action">Start visible-card review</h2>
        <p className={styles.pipelineInspectorEmpty}>
          Seed the existing empty reference from the selected generated result.
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
          onClick={startReference}
          disabled={
            operatorId.trim() === "" ||
            saveState === "saving" ||
            queueLength > 0
          }
        >
          {saveState === "saving" || queueLength > 0
            ? "Starting review…"
            : "Start review"}
        </button>
      </>
    );
  }
  if (reference === null) {
    return (
      <>
        <p className={styles.statusLabel}>Primary action</p>
        <h2 id="pipeline-inspector-action">Start visible-card review</h2>
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
  const isCorrectedReference =
    reference.state.selected_completed_revision_id !== null;
  return (
    <>
      <p className={styles.statusLabel}>Primary action</p>
      <h2 id="pipeline-inspector-action">
        {isCorrectedReference
          ? "Publish corrected reference"
          : "Complete visible-card review"}
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
          : isCorrectedReference
            ? "Publish corrected reference"
            : "Complete reference"}
      </button>
    </>
  );
}

function VisibleCardInspectorSaveState({
  view,
  saveState,
  queueLength,
  firstUnappliedCommand,
  error,
  retryQueuedCommands,
  reloadWinningDraft,
}: VisibleCardInspectorProps) {
  return (
    <div className={visibleStyles.inspectorState}>
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
        <div className={visibleStyles.error} role="alert">
          <p>
            {saveState === "conflict"
              ? `Conflict: the first unapplied command is ${firstUnappliedCommand ?? "unknown"}. ${error}`
              : error}
          </p>
          <div className={visibleStyles.errorActions}>
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

function VisibleCardInspectorSelection({
  view,
  reference,
  frames,
  selectedFrame,
  pendingCount,
  completedFrameCount,
  coveragePercent,
  inspectedCount,
  referenceNeedsSeed,
  restoreGeneratedSuggestions,
  canRestoreGeneratedSuggestions,
}: VisibleCardInspectorProps) {
  return (
    <div className={visibleStyles.inspectorSelection}>
      <p className={styles.statusLabel}>Current frame</p>
      <div
        className={visibleStyles.reviewCounts}
        aria-label="Visible-card counts"
      >
        <ReviewCount label="Decided" value={completedFrameCount} />
        <ReviewCount label="Unreviewed" value={pendingCount} />
        <ReviewCount
          label="Proposals"
          value={frames.reduce(
            (count, frame) => count + frame.outcome.candidates.length,
            0,
          )}
        />
        <ReviewCount
          label="Ignore regions"
          value={frames.reduce(
            (count, frame) => count + frame.outcome.ignored_regions.length,
            0,
          )}
        />
      </div>
      <p className={styles.pipelineInspectorEmpty}>
        {selectedFrame === null
          ? view === "generated"
            ? "Select a proposal from the Timeline Rail."
            : "Select a resolved frame from the Timeline Rail."
          : `${formatFrameTime(selectedFrame)} · ${formatFrameState(selectedFrame)}`}
      </p>
      {selectedFrame !== null ? (
        <dl className={styles.pipelineInspectorFacts}>
          <div>
            <dt>Frame item</dt>
            <dd>{selectedFrame.itemId}</dd>
          </div>
          <div>
            <dt>Proposal count</dt>
            <dd>{selectedFrame.outcome.candidates.length}</dd>
          </div>
          <div>
            <dt>Ignore-region count</dt>
            <dd>{selectedFrame.outcome.ignored_regions.length}</dd>
          </div>
        </dl>
      ) : null}
      {view === "reviewed" && reference !== null && !referenceNeedsSeed ? (
        <>
          <div
            className={visibleStyles.outcomeButtons}
            aria-label="Frame outcome"
          >
            <button
              className={styles.inlineAction}
              type="button"
              onClick={restoreGeneratedSuggestions}
              disabled={!canRestoreGeneratedSuggestions}
            >
              Restore generated suggestions
            </button>
          </div>
          <div className={visibleStyles.coverageInspector}>
            <span>Resolved-frame coverage</span>
            <strong>
              {Math.round(coveragePercent)}% inspected ({inspectedCount}/
              {frames.length})
            </strong>
            <progress
              max={100}
              value={coveragePercent}
              aria-label="Resolved-frame coverage"
            />
            <p>
              Each frame must be accepted, empty, or unusable before completion.
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}

function ReviewCount({ label, value }: { label: string; value: number }) {
  return (
    <div className={visibleStyles.reviewCount}>
      <span className={styles.statusLabel}>{label}</span>
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
