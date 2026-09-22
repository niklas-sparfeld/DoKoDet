import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type {
  CalibrationRefinementResponse,
  PipelineProposalRunResponse,
  PipelineReferenceResource,
} from "../api/client";
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
  selectedGeneratedRevisionId: string | null;
  rebasingReference: boolean;
  rebaseReference: () => Promise<void>;
  rebasingProposal: boolean;
  rebaseReferenceToProposal: () => Promise<void>;
  referenceNeedsSeed: boolean;
  startReference: () => void;
  completionBusy: boolean;
  completionBlocker: string | null;
  proposalRun: PipelineProposalRunResponse | null;
  proposalRevisionId: string | null;
  proposalLoading: boolean;
  proposalError: string | null;
  startProposal: () => void;
  retryProposal: () => void;
  startReviewFromProposal: () => void;
  retryQueuedCommands: () => void;
  reloadWinningDraft: () => Promise<void>;
  completeReference: () => Promise<void>;
  createReference: () => Promise<void>;
  onReviewRequested?: () => void;
  calibrationRefinement: CalibrationRefinementResponse | null;
  calibrationLoading: boolean;
  calibrationError: string | null;
  startCalibrationRefinement: () => void;
  discardCalibrationRefinement: () => void;
  applyCalibrationRefinement: (confirmAffected: boolean) => void;
  onSelectCalibrationFrame: (frameId: string) => void;
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
  selectedGeneratedRevisionId,
  rebasingReference,
  rebaseReference,
  rebasingProposal,
  rebaseReferenceToProposal,
  referenceNeedsSeed,
  startReference,
  saveState,
  queueLength,
  completionBusy,
  completionBlocker,
  proposalRun,
  proposalRevisionId,
  proposalLoading,
  proposalError,
  startProposal,
  retryProposal,
  startReviewFromProposal,
  completeReference,
  createReference,
  onReviewRequested,
  calibrationRefinement,
  calibrationLoading,
  calibrationError,
  startCalibrationRefinement,
  discardCalibrationRefinement,
  applyCalibrationRefinement,
}: VisibleCardInspectorProps) {
  if (view === "generated") {
    return (
      <>
        <p className={styles.statusLabel}>Primary action</p>
        <h2 id="pipeline-inspector-action">Review visible cards</h2>
        <ProposalControls
          generatedRevisionId={generatedRevisionId}
          proposalRun={proposalRun}
          proposalRevisionId={proposalRevisionId}
          proposalLoading={proposalLoading}
          proposalError={proposalError}
          onCreate={startProposal}
          onRetry={retryProposal}
          onStartReview={startReviewFromProposal}
        />
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
          {proposalRevisionId === null
            ? "Seed the existing empty reference from the selected generated result."
            : "Seed review from the preserved proposed card scenes."}
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
        {proposalRevisionId !== null ? (
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={startReviewFromProposal}
            disabled={proposalLoading}
          >
            Start review from proposed scenes
          </button>
        ) : null}
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
        {proposalRevisionId !== null ? (
          <p className={styles.pipelineInspectorEmpty}>
            The next review will retain the immutable proposal and homography.
          </p>
        ) : null}
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
      {selectedGeneratedRevisionId !== null &&
      reference.draft.source_revision_id !== selectedGeneratedRevisionId ? (
        <section
          className={visibleStyles.proposalControls}
          aria-label="Review source"
        >
          <p className={styles.statusLabel}>Review source</p>
          <h3>Different generated result selected</h3>
          <p className={styles.pipelineInspectorEmpty}>
            This review uses a different generated result. Switch it to the
            selected result before continuing.
          </p>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => void rebaseReference()}
            disabled={
              rebasingReference ||
              queueLength > 0 ||
              saveState !== "saved" ||
              operatorId.trim() === ""
            }
          >
            {rebasingReference
              ? "Switching review…"
              : "Switch review to selected result"}
          </button>
        </section>
      ) : null}
      {proposalRun?.status === "complete" &&
      proposalRevisionId !== null &&
      reference.draft.proposal_revision_id !== proposalRevisionId ? (
        <section
          className={visibleStyles.proposalControls}
          aria-label="Proposed card scenes"
        >
          <p className={styles.statusLabel}>Proposed card scenes</p>
          <h3>Proposal ready to inspect</h3>
          <p className={styles.pipelineInspectorEmpty}>
            Load the immutable scene proposal into this review to inspect its
            card poses and homography.
          </p>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => void rebaseReferenceToProposal()}
            disabled={
              rebasingProposal ||
              queueLength > 0 ||
              saveState !== "saved" ||
              operatorId.trim() === ""
            }
          >
            {rebasingProposal
              ? "Loading proposed scenes…"
              : "Inspect proposed card scenes"}
          </button>
        </section>
      ) : null}
      <CalibrationRefinementControls
        proposalRevisionId={proposalRevisionId}
        refinement={calibrationRefinement}
        loading={calibrationLoading}
        error={calibrationError}
        onStart={startCalibrationRefinement}
        onDiscard={discardCalibrationRefinement}
        onApply={applyCalibrationRefinement}
        canApply={saveState === "saved" && queueLength === 0}
      />
    </>
  );
}

function CalibrationRefinementControls({
  proposalRevisionId,
  refinement,
  loading,
  error,
  onStart,
  onDiscard,
  onApply,
  canApply,
}: {
  proposalRevisionId: string | null;
  refinement: CalibrationRefinementResponse | null;
  loading: boolean;
  error: string | null;
  onStart: () => void;
  onDiscard: () => void;
  onApply: (confirmAffected: boolean) => void;
  canApply: boolean;
}) {
  if (proposalRevisionId === null) return null;
  return (
    <section
      className={visibleStyles.proposalControls}
      aria-label="Calibration refinement"
    >
      <p className={styles.statusLabel}>Recording-wide mapping</p>
      <h3>Refine calibration</h3>
      {error !== null ? (
        <p className={visibleStyles.error} role="alert">
          {error}
        </p>
      ) : null}
      {refinement === null ? (
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onStart}
          disabled={loading}
        >
          {loading
            ? "Preparing calibration…"
            : "Prepare calibration refinement"}
        </button>
      ) : (
        <>
          <p className={styles.pipelineInspectorEmpty}>
            Preview: {formatIdentifier(refinement.preview.status)} ·{" "}
            {refinement.preview.accepted_anchor_count} confirmed anchors ·{" "}
            {refinement.preview.changed_frame_ids.length} changed frames
          </p>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onDiscard}
            disabled={loading}
          >
            Discard calibration preview
          </button>
          {refinement.preview.status === "pass" ||
          refinement.preview.failure?.code ===
            "reviewed_displacement_exceeded" ? (
            <button
              className={styles.primaryButton}
              type="button"
              onClick={() =>
                onApply(
                  refinement.preview.failure?.code ===
                    "reviewed_displacement_exceeded",
                )
              }
              disabled={loading || !canApply}
            >
              {loading
                ? "Applying calibration…"
                : refinement.preview.failure?.code ===
                    "reviewed_displacement_exceeded"
                  ? "Apply and mark affected"
                  : "Apply calibration"}
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}

function ProposalControls({
  generatedRevisionId,
  proposalRun,
  proposalRevisionId,
  proposalLoading,
  proposalError,
  onCreate,
  onRetry,
  onStartReview,
}: {
  generatedRevisionId: string | null;
  proposalRun: PipelineProposalRunResponse | null;
  proposalRevisionId: string | null;
  proposalLoading: boolean;
  proposalError: string | null;
  onCreate: () => void;
  onRetry: () => void;
  onStartReview: () => void;
}) {
  const status = proposalRun?.status ?? null;
  return (
    <section
      className={visibleStyles.proposalControls}
      aria-label="Proposed card scene controls"
    >
      <p className={styles.statusLabel}>Proposal processor</p>
      <h3>Create proposed card scenes</h3>
      <p className={styles.pipelineInspectorEmpty}>
        {generatedRevisionId === null
          ? "Select a generated local cascade result first."
          : status === null
            ? "Preserve the virtual cards and table homography for review and failure analysis."
            : `Run status: ${formatIdentifier(status)}${proposalRevisionId === null ? "" : ` · ${proposalRevisionId}`}`}
      </p>
      {proposalError !== null ? (
        <p className={visibleStyles.error} role="alert">
          {proposalError}
        </p>
      ) : null}
      {status === "failed" || status === "partial" ? (
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onRetry}
          disabled={proposalLoading}
        >
          {proposalLoading ? "Retrying proposal…" : "Retry proposal"}
        </button>
      ) : (
        <button
          className={styles.primaryButton}
          type="button"
          onClick={onCreate}
          disabled={proposalLoading || generatedRevisionId === null}
        >
          {proposalLoading
            ? "Creating proposed scenes…"
            : status === "complete"
              ? "Create new proposed scenes"
              : "Create proposed card scenes"}
        </button>
      )}
      {status === "complete" && proposalRevisionId !== null ? (
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onStartReview}
          disabled={proposalLoading}
        >
          Start review from proposed scenes
        </button>
      ) : null}
    </section>
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
  calibrationRefinement,
  onSelectCalibrationFrame,
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
            Use the Timeline Rail to decide this frame as accepted, empty, or
            unusable.
          </p>
        </div>
      ) : null}
      {calibrationRefinement !== null ? (
        <CalibrationPreviewPanel
          refinement={calibrationRefinement}
          onSelectFrame={onSelectCalibrationFrame}
        />
      ) : null}
    </div>
  );
}

function CalibrationPreviewPanel({
  refinement,
  onSelectFrame,
}: {
  refinement: CalibrationRefinementResponse;
  onSelectFrame: (frameId: string) => void;
}) {
  const preview = refinement.preview;
  return (
    <section
      className={visibleStyles.coverageInspector}
      aria-label="Calibration preview"
    >
      <strong>Calibration preview: {formatIdentifier(preview.status)}</strong>
      <dl className={styles.pipelineInspectorFacts}>
        <div>
          <dt>Fit residual</dt>
          <dd>{preview.fit_residual.toFixed(3)} table units</dd>
        </div>
        <div>
          <dt>Held-out alignment change</dt>
          <dd>{preview.held_out_alignment_change_px.toFixed(1)} px</dd>
        </div>
        <div>
          <dt>Maximum displacement</dt>
          <dd>{preview.max_source_pixel_displacement.toFixed(1)} px</dd>
        </div>
      </dl>
      <ul aria-label="Calibration gates">
        {preview.gates.map((gate) => (
          <li key={gate.gate_id}>
            {gate.passed ? "Pass" : "Blocked"}: {formatIdentifier(gate.gate_id)}
          </li>
        ))}
      </ul>
      {preview.failure !== null ? <p>{preview.failure.action}</p> : null}
      {preview.most_affected_frame_ids.length > 0 ? (
        <div
          className={visibleStyles.outcomeButtons}
          aria-label="Most affected frames"
        >
          {preview.most_affected_frame_ids.map((frameId) => (
            <button
              className={styles.inlineAction}
              type="button"
              key={frameId}
              onClick={() => onSelectFrame(frameId)}
            >
              Inspect {frameId}
            </button>
          ))}
        </div>
      ) : null}
    </section>
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
