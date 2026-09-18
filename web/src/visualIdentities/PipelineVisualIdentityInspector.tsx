import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type {
  PipelineReferenceResource,
  VisualIdentityAutoApprovalPlan,
} from "../api/client";
import styles from "../App.module.css";
import identityStyles from "./PipelineVisualIdentityEditor.module.css";
import {
  type EditableIdentity,
  type SaveState,
} from "./PipelineVisualIdentityTypes";
import {
  formatCardIdentity,
  formatIdentityReviewStatus,
  formatIdentityOutcomeStatus,
  formatIdentifier,
  identityReviewStatus,
} from "./PipelineVisualIdentityFormatting";

export type IdentityInspectorSlots = {
  action: HTMLElement;
  save: HTMLElement;
  selection: HTMLElement;
};

export function useIdentityInspectorSlots(
  inspectorEnabled: boolean,
  view: "generated" | "reviewed",
): IdentityInspectorSlots | null {
  const [slots, setSlots] = useState<IdentityInspectorSlots | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const action = document.querySelector<HTMLElement>(
        "[data-identity-inspector-slot='action']",
      );
      const save = document.querySelector<HTMLElement>(
        "[data-identity-inspector-slot='save']",
      );
      const selection = document.querySelector<HTMLElement>(
        "[data-identity-inspector-slot='selection']",
      );
      setSlots(
        action !== null && save !== null && selection !== null
          ? { action, save, selection }
          : null,
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [inspectorEnabled, view]);

  return slots;
}

export type IdentityInspectorProps = {
  slots: IdentityInspectorSlots | null;
  inspectorEnabled: boolean;
  view: "generated" | "reviewed";
  reference: PipelineReferenceResource | null;
  item: EditableIdentity | null;
  itemCount: number;
  pendingCount: number;
  coveragePercent: number;
  inspectedCount: number;
  saveState: SaveState;
  queueLength: number;
  firstUnappliedCommand: string | null;
  error: string | null;
  notice: string | null;
  operatorId: string;
  reviewerId: string;
  setOperatorId: (value: string) => void;
  setReviewerId: (value: string) => void;
  completionBusy: boolean;
  completionBlocker: string | null;
  creatingReference: boolean;
  selectedGeneratedRevisionId: string | null;
  rebasingReference: boolean;
  autoApprovalPlan: VisualIdentityAutoApprovalPlan | null;
  autoApprovalBusy: boolean;
  autoApprovalAvailable: boolean;
  autoApprove: () => Promise<void>;
  createReference: () => Promise<void>;
  rebaseReference: () => Promise<void>;
  completeReference: () => Promise<void>;
  retryQueuedCommands: () => void;
  reloadWinningDraft: () => Promise<void>;
};

export function IdentityInspectorPortals(props: IdentityInspectorProps) {
  if (!props.inspectorEnabled) return null;
  const content = (
    <>
      <IdentityInspectorAction {...props} />
      <IdentityInspectorSave {...props} />
      <IdentityInspectorSelection {...props} />
    </>
  );
  if (props.slots === null)
    return <div className={identityStyles.standaloneInspector}>{content}</div>;
  return (
    <>
      {createPortal(<IdentityInspectorAction {...props} />, props.slots.action)}
      {createPortal(<IdentityInspectorSave {...props} />, props.slots.save)}
      {createPortal(
        <IdentityInspectorSelection {...props} />,
        props.slots.selection,
      )}
    </>
  );
}

function IdentityInspectorAction(props: IdentityInspectorProps) {
  if (props.view === "generated")
    return (
      <>
        <p className={styles.statusLabel}>Generated result</p>
        <h2>Visual identity suggestions</h2>
        <p className={styles.pipelineInspectorEmpty}>
          Generated classifier output is immutable. Choose Review to create a
          maintained reference.
        </p>
      </>
    );
  if (props.reference === null)
    return (
      <>
        <p className={styles.statusLabel}>Maintained reference</p>
        <h2>Start visual identity review</h2>
        <label className={identityStyles.reviewer}>
          Operator ID
          <input
            value={props.operatorId}
            onChange={(event) => props.setOperatorId(event.target.value)}
            placeholder="operator-01"
          />
        </label>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => void props.createReference()}
          disabled={props.creatingReference || props.operatorId.trim() === ""}
        >
          {props.creatingReference ? "Starting review…" : "Start review"}
        </button>
      </>
    );
  return (
    <>
      <p className={styles.statusLabel}>Maintained reference</p>
      <h2>Visual identity review</h2>
      <label className={identityStyles.reviewer}>
        Operator ID
        <input
          value={props.operatorId}
          onChange={(event) => props.setOperatorId(event.target.value)}
          placeholder="operator-01"
        />
      </label>
      <p className={styles.pipelineInspectorEmpty}>
        Choose the canonical identity in the central area. Use the review
        controls below. Changes save automatically.
      </p>
      {props.selectedGeneratedRevisionId !== null &&
      props.reference.draft.source_revision_id !==
        props.selectedGeneratedRevisionId ? (
        <>
          <p className={styles.pipelineInspectorEmpty}>
            A different generated result is selected. Switch this review to its
            crops. Matching decisions stay in place, but inspect the selected
            result before completing the review.
          </p>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => void props.rebaseReference()}
            disabled={
              props.rebasingReference ||
              props.queueLength > 0 ||
              props.saveState !== "saved" ||
              props.operatorId.trim() === ""
            }
          >
            {props.rebasingReference
              ? "Switching review…"
              : "Switch review to selected result"}
          </button>
        </>
      ) : null}
      <button
        className={styles.secondaryButton}
        type="button"
        onClick={() => void props.autoApprove()}
        disabled={!props.autoApprovalAvailable || props.autoApprovalBusy}
      >
        {props.autoApprovalBusy
          ? "Checking identity results…"
          : props.autoApprovalPlan?.local_run?.status === "queued" ||
              props.autoApprovalPlan?.local_run?.status === "running"
            ? "Local identity check running…"
            : "Auto-approve matching identities"}
      </button>
      <AutoApprovalStatus plan={props.autoApprovalPlan} />
    </>
  );
}

function AutoApprovalStatus({
  plan,
}: {
  plan: VisualIdentityAutoApprovalPlan | null;
}) {
  if (plan === null) return null;
  const counts = new Map<string, number>();
  for (const item of plan.items)
    counts.set(item.reason, (counts.get(item.reason) ?? 0) + 1);
  const summary = [...counts.entries()]
    .map(([reason, count]) => `${count} ${reason.replaceAll("_", " ")}`)
    .join(", ");
  return (
    <>
      {plan.local_run !== null &&
      (plan.local_run.status === "queued" ||
        plan.local_run.status === "running") ? (
        <p className={styles.pipelineInspectorEmpty} role="status">
          Local identity check {plan.local_run.status}. This page will refresh
          the comparison when it completes.
        </p>
      ) : null}
      <p className={styles.pipelineInspectorEmpty} role="status">
        Auto-approval: {summary || "no identity items"}.
      </p>
    </>
  );
}

function IdentityInspectorSave(props: IdentityInspectorProps) {
  return (
    <div className={identityStyles.inspectorState}>
      <div className={styles.pipelineInspectorSectionHeading}>
        <div>
          <p className={styles.statusLabel}>Save state</p>
          <h2>{formatIdentifier(props.saveState)}</h2>
        </div>
      </div>
      {props.notice !== null ? (
        <p className={styles.recordingNotice} role="status">
          {props.notice}
        </p>
      ) : null}
      {props.error !== null ? (
        <p className={styles.detailBlocker} role="alert">
          {props.saveState === "conflict"
            ? `Conflict: ${props.firstUnappliedCommand ?? "unknown"}. ${props.error}`
            : props.error}
        </p>
      ) : null}
      {props.queueLength > 0 &&
      (props.saveState === "error" || props.saveState === "retrying") ? (
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={props.retryQueuedCommands}
        >
          Retry queued commands
        </button>
      ) : null}
      {props.saveState === "conflict" ? (
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => void props.reloadWinningDraft()}
        >
          Reload winning draft and retry
        </button>
      ) : null}
    </div>
  );
}

function IdentityInspectorSelection(props: IdentityInspectorProps) {
  const item = props.item;
  const reviewStatus = item === null ? null : identityReviewStatus(item);
  return (
    <div className={identityStyles.inspectorSelection}>
      <p className={styles.statusLabel}>Current identity</p>
      <h2>{item?.itemId ?? "None"}</h2>
      {reviewStatus !== null ? (
        <div className={identityStyles.reviewStatus}>
          <span className={styles.statusLabel}>Review state</span>
          <span className={styles.status} data-state={reviewStatus}>
            {formatIdentityReviewStatus(reviewStatus)}
          </span>
        </div>
      ) : null}
      <dl className={styles.pipelineInspectorFacts}>
        <div>
          <dt>Identity outcome</dt>
          <dd>
            {item === null
              ? "None"
              : formatIdentityOutcomeStatus(item.outcome.status)}
          </dd>
        </div>
        <div>
          <dt>Crop policy</dt>
          <dd>{item?.outcome.crop_identity?.crop_policy ?? "Unavailable"}</dd>
        </div>
        <div>
          <dt>Candidates</dt>
          <dd>
            {item?.outcome.candidates
              .map((candidate) => formatCardIdentity(candidate.identity))
              .join(", ") || "None"}
          </dd>
        </div>
        <div>
          <dt>Review coverage</dt>
          <dd>
            {props.inspectedCount}/{props.itemCount} inspected (
            {Math.round(props.coveragePercent)}%)
          </dd>
        </div>
      </dl>
      <AutoApprovalDiagnostics
        itemId={item?.itemId ?? null}
        plan={props.autoApprovalPlan}
      />
      {props.view === "reviewed" && props.reference !== null ? (
        <>
          <label className={identityStyles.reviewer}>
            Reviewer ID
            <input
              value={props.reviewerId}
              onChange={(event) => props.setReviewerId(event.target.value)}
              placeholder="reviewer-01"
            />
          </label>
          {props.completionBlocker !== null ? (
            <p className={styles.detailBlocker}>{props.completionBlocker}</p>
          ) : null}
          <button
            className={styles.primaryButton}
            type="button"
            onClick={() => void props.completeReference()}
            disabled={props.completionBusy || props.completionBlocker !== null}
          >
            {props.completionBusy
              ? "Completing reference…"
              : "Complete reference"}
          </button>
        </>
      ) : null}
    </div>
  );
}

function AutoApprovalDiagnostics({
  itemId,
  plan,
}: {
  itemId: string | null;
  plan: VisualIdentityAutoApprovalPlan | null;
}) {
  const comparison = plan?.items.find(
    (candidate) => candidate.item_id === itemId,
  );
  if (comparison === undefined) return null;
  return (
    <dl className={styles.pipelineInspectorFacts}>
      <div>
        <dt>Auto-approval</dt>
        <dd>{comparison.reason.replaceAll("_", " ")}</dd>
      </div>
      <div>
        <dt>Gemini result</dt>
        <dd>{comparison.gemini_result?.result_id ?? "Unavailable"}</dd>
      </div>
      <div>
        <dt>Local result</dt>
        <dd>{comparison.local_result?.result_id ?? "Unavailable"}</dd>
      </div>
    </dl>
  );
}
