import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
  repositoryBundleVideoPath,
  type PipelineReferenceItem,
  type PipelineReferenceOperation,
  type PipelineReferenceResource,
  type PipelineVisualIdentityResult,
} from "../api/client";
import styles from "../App.module.css";

type FrameIdentity = {
  requested_time_us: number;
  frame_index: number;
  presentation_timestamp_us: number;
  width: number;
  height: number;
  image_sha256: string;
  [key: string]: unknown;
};

type CropIdentity = {
  status: "usable" | "unusable";
  crop_policy: string;
  output_encoding: string;
  image_sha256: string | null;
  unusable_reason: string | null;
  [key: string]: unknown;
};

type IdentityCandidate = {
  identity: string;
  score: number | null;
  score_meaning?: string | null;
};

type IdentityOutcome = {
  card_id: string;
  frame_identity: FrameIdentity;
  geometry: Record<string, unknown>;
  crop_identity: CropIdentity | null;
  status: "classified" | "unusable" | "failed";
  candidates: IdentityCandidate[];
  unusable_reason: string | null;
  error: string | null;
};

type IdentityReviewState =
  | "pending"
  | "accepted"
  | "added"
  | "corrected"
  | "unusable"
  | "identity_unusable"
  | "source_problem"
  | "affected";

type EditableIdentity = {
  itemId: string;
  baseItemId: string | null;
  reviewState: IdentityReviewState;
  outcome: IdentityOutcome;
};

type SaveState = "saved" | "saving" | "retrying" | "error" | "conflict";
type PendingCommand = {
  commandId: string;
  operation: PipelineReferenceOperation;
  notice: string;
  attempts: number;
};

const CONTENT_TYPE = "visual_identities" as const;
const RETRY_LIMIT = 3;
const CANONICAL_IDENTITIES = [
  "CLUBS_ACE",
  "CLUBS_NINE",
  "CLUBS_TEN",
  "CLUBS_JACK",
  "CLUBS_QUEEN",
  "CLUBS_KING",
  "DIAMONDS_ACE",
  "DIAMONDS_NINE",
  "DIAMONDS_TEN",
  "DIAMONDS_JACK",
  "DIAMONDS_QUEEN",
  "DIAMONDS_KING",
  "HEARTS_ACE",
  "HEARTS_NINE",
  "HEARTS_TEN",
  "HEARTS_JACK",
  "HEARTS_QUEEN",
  "HEARTS_KING",
  "SPADES_ACE",
  "SPADES_NINE",
  "SPADES_TEN",
  "SPADES_JACK",
  "SPADES_QUEEN",
  "SPADES_KING",
] as const;

export type PipelineVisualIdentityEditorProps = {
  recordingId: string;
  videoUrl?: string;
  durationUs: number;
  generatedRevisionId: string | null;
  displayedRevisionId?: string | null;
  generatedRunId: string | null;
  view: "generated" | "reviewed";
};

export function PipelineVisualIdentityEditor({
  recordingId,
  videoUrl = repositoryBundleVideoPath(recordingId),
  durationUs,
  generatedRevisionId,
  displayedRevisionId = generatedRevisionId,
  generatedRunId,
  view,
}: PipelineVisualIdentityEditorProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const referenceRef = useRef<PipelineReferenceResource | null>(null);
  const itemsRef = useRef<EditableIdentity[]>([]);
  const selectedItemIdRef = useRef<string | null>(null);
  const serverRevisionRef = useRef(0);
  const queueRef = useRef<PendingCommand[]>([]);
  const processingRef = useRef(false);
  const processQueueRef = useRef<(() => void) | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const commandSequenceRef = useRef(0);
  const inspectedItemIdsRef = useRef(new Set<string>());
  const [reference, setReference] = useState<PipelineReferenceResource | null>(
    null,
  );
  const [items, setItems] = useState<EditableIdentity[]>([]);
  const [generatedItems, setGeneratedItems] = useState<EditableIdentity[]>([]);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [playheadUs, setPlayheadUs] = useState(0);
  const [loading, setLoading] = useState(view === "reviewed");
  const [generatedLoading, setGeneratedLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [queueLength, setQueueLength] = useState(0);
  const [firstUnappliedCommand, setFirstUnappliedCommand] = useState<
    string | null
  >(null);
  const [operatorId, setOperatorId] = useState("");
  const [reviewerId, setReviewerId] = useState("");
  const [inspectedItemIds, setInspectedItemIds] = useState<Set<string>>(
    new Set(),
  );
  const [creatingReference, setCreatingReference] = useState(false);
  const [completionBusy, setCompletionBusy] = useState(false);

  const setLocalItems = useCallback((next: EditableIdentity[]) => {
    itemsRef.current = next;
    setItems(next);
  }, []);

  const setSelected = useCallback((itemId: string | null) => {
    selectedItemIdRef.current = itemId;
    setSelectedItemId(itemId);
  }, []);

  const markInspected = useCallback((item: EditableIdentity) => {
    inspectedItemIdsRef.current.add(item.itemId);
    setInspectedItemIds(new Set(inspectedItemIdsRef.current));
  }, []);

  const setCurrentTime = useCallback(
    (nextUs: number, updateUrl = true) => {
      const clamped = clamp(nextUs, durationUs);
      setPlayheadUs(clamped);
      if (videoRef.current !== null) {
        videoRef.current.currentTime = clamped / 1_000_000;
      }
      if (updateUrl) updatePipelineUrl({ t_us: clamped });
    },
    [durationUs],
  );

  const selectItem = useCallback(
    (item: EditableIdentity, seek = true) => {
      setSelected(item.itemId);
      markInspected(item);
      updatePipelineUrl({ item: item.itemId });
      if (seek) setCurrentTime(item.outcome.frame_identity.requested_time_us);
    },
    [markInspected, setCurrentTime, setSelected],
  );

  const hydrateReference = useCallback(
    (nextReference: PipelineReferenceResource, preserveSelection = true) => {
      const nextItems = nextReference.draft.items
        .map(toEditableIdentity)
        .filter((item): item is EditableIdentity => item !== null);
      referenceRef.current = nextReference;
      serverRevisionRef.current = nextReference.draft.revision;
      setReference(nextReference);
      setLocalItems(nextItems);
      if (!preserveSelection) {
        inspectedItemIdsRef.current = new Set();
        setInspectedItemIds(new Set());
      }
      const coverage = readIdentityCoverage(nextReference.draft.coverage);
      for (const card of coverage)
        inspectedItemIdsRef.current.add(card.card_id);
      setInspectedItemIds(new Set(inspectedItemIdsRef.current));
      const current = preserveSelection ? selectedItemIdRef.current : null;
      const selected =
        nextItems.find((item) => item.itemId === current) ?? nextItems[0];
      setSelected(selected?.itemId ?? null);
    },
    [setLocalItems, setSelected],
  );

  const loadGenerated = useCallback(
    async (signal?: AbortSignal) => {
      if (generatedRunId === null || displayedRevisionId === null) {
        setGeneratedItems([]);
        setGeneratedLoading(false);
        return;
      }
      setGeneratedLoading(true);
      try {
        const result = await client.getVisualIdentityResult(
          recordingId,
          generatedRunId,
          { signal },
        );
        if (!signal?.aborted) {
          setGeneratedItems(readItemsFromResult(result, displayedRevisionId));
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) setError(describeError(reason));
      } finally {
        if (!signal?.aborted) setGeneratedLoading(false);
      }
    },
    [client, displayedRevisionId, generatedRunId, recordingId],
  );

  const loadReference = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const loaded = await client.getPipelineReference(
          recordingId,
          CONTENT_TYPE,
          { signal },
        );
        if (!signal?.aborted) {
          hydrateReference(loaded);
          setSaveState("saved");
          setError(null);
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          if (reason instanceof ApiError && reason.status === 404) {
            referenceRef.current = null;
            setReference(null);
            setLocalItems([]);
            setSelected(null);
            setError(null);
          } else {
            setError(describeError(reason));
          }
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [client, hydrateReference, recordingId, setLocalItems, setSelected],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      if (view === "reviewed") void loadReference(controller.signal);
      else setLoading(false);
      void loadGenerated(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (retryTimerRef.current !== null)
        window.clearTimeout(retryTimerRef.current);
    };
  }, [loadGenerated, loadReference, view]);

  useEffect(() => {
    const candidates = view === "reviewed" ? items : generatedItems;
    const itemId = new URLSearchParams(window.location.search).get("item");
    const selected =
      candidates.find((item) => item.itemId === itemId) ?? candidates[0];
    const rawTime = new URLSearchParams(window.location.search).get("t_us");
    const timer = window.setTimeout(() => {
      if (selected !== undefined) selectItem(selected, false);
      if (rawTime !== null && /^\d+$/.test(rawTime)) {
        setCurrentTime(Number(rawTime), false);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generatedItems, items, selectItem, setCurrentTime, view]);

  const nextCommandId = useCallback(() => {
    commandSequenceRef.current += 1;
    return `pipeline-visual-identity-${Date.now()}-${commandSequenceRef.current}`;
  }, []);

  const processQueue = useCallback(async () => {
    if (processingRef.current || queueRef.current.length === 0) {
      if (queueRef.current.length === 0 && saveState !== "conflict") {
        setQueueLength(0);
        setFirstUnappliedCommand(null);
        setSaveState("saved");
      }
      return;
    }
    const command = queueRef.current[0];
    const current = referenceRef.current;
    if (current === null) return;
    processingRef.current = true;
    try {
      const nextReference = await client.updatePipelineReferenceDraft(
        recordingId,
        CONTENT_TYPE,
        {
          expected_revision: serverRevisionRef.current,
          operator_id: operatorId.trim(),
          command_id: command.commandId,
          operations: [command.operation],
        },
      );
      hydrateReference(nextReference);
      queueRef.current.shift();
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(
        queueRef.current.length === 0
          ? null
          : describeCommand(queueRef.current[0]),
      );
      setNotice(command.notice);
      setError(null);
      command.attempts = 0;
    } catch (reason: unknown) {
      command.attempts += 1;
      processingRef.current = false;
      if (reason instanceof ApiError && reason.status === 409) {
        setSaveState("conflict");
        setFirstUnappliedCommand(describeCommand(command));
        setError(describeError(reason));
        return;
      }
      if (isRetryableError(reason) && command.attempts <= RETRY_LIMIT) {
        setSaveState("retrying");
        setError(describeError(reason));
        retryTimerRef.current = window.setTimeout(
          () => {
            retryTimerRef.current = null;
            void processQueueRef.current?.();
          },
          Math.min(500, 100 * command.attempts),
        );
        return;
      }
      setSaveState("error");
      setFirstUnappliedCommand(describeCommand(command));
      setError(describeError(reason));
      return;
    }
    processingRef.current = false;
    if (queueRef.current.length > 0) {
      setSaveState("saving");
      void processQueueRef.current?.();
    } else {
      setSaveState("saved");
    }
  }, [client, hydrateReference, operatorId, recordingId, saveState]);

  useEffect(() => {
    processQueueRef.current = processQueue;
    return () => {
      if (processQueueRef.current === processQueue)
        processQueueRef.current = null;
    };
  }, [processQueue]);

  const enqueue = useCallback(
    (
      operation: PipelineReferenceOperation,
      noticeText: string,
      optimistic: (current: EditableIdentity[]) => EditableIdentity[],
    ) => {
      if (referenceRef.current === null || operatorId.trim() === "") {
        setError("Enter an operator ID before saving an identity decision.");
        return;
      }
      setLocalItems(optimistic(itemsRef.current));
      queueRef.current.push({
        commandId: nextCommandId(),
        operation,
        notice: noticeText,
        attempts: 0,
      });
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(describeCommand(queueRef.current[0]));
      setSaveState("saving");
      setError(null);
      void processQueueRef.current?.();
    },
    [nextCommandId, operatorId, setLocalItems],
  );

  const applyReviewState = useCallback(
    (
      item: EditableIdentity,
      operation: PipelineReferenceOperation,
      noticeText: string,
      next: (outcome: IdentityOutcome) => IdentityOutcome,
      state: IdentityReviewState,
    ) => {
      enqueue(operation, noticeText, (current) =>
        current.map((candidate) =>
          candidate.itemId === item.itemId
            ? {
                ...candidate,
                reviewState: state,
                outcome: next(candidate.outcome),
              }
            : candidate,
        ),
      );
    },
    [enqueue],
  );

  const acceptSuggestion = useCallback(
    (item: EditableIdentity) => {
      if (item.outcome.candidates.length === 0) return;
      applyReviewState(
        item,
        { operation: "accept_identity_suggestion", item_id: item.itemId },
        "Identity suggestion accepted.",
        (outcome) => outcome,
        acceptedState(item),
      );
    },
    [applyReviewState],
  );

  const selectIdentity = useCallback(
    (item: EditableIdentity, identity: string) => {
      if (item.outcome.crop_identity === null) return;
      applyReviewState(
        item,
        { operation: "select_identity", item_id: item.itemId, identity },
        `Identity selected: ${identity}.`,
        (outcome) => ({
          ...outcome,
          status: "classified",
          candidates: [{ identity, score: null, score_meaning: null }],
          unusable_reason: null,
          error: null,
        }),
        acceptedState(item),
      );
    },
    [applyReviewState],
  );

  const markUnusable = useCallback(
    (item: EditableIdentity) => {
      if (item.outcome.crop_identity === null) return;
      applyReviewState(
        item,
        { operation: "set_identity_unusable", item_id: item.itemId },
        "Identity marked unusable.",
        (outcome) => ({
          ...outcome,
          status: "unusable",
          candidates: [],
          unusable_reason: "Reviewed identity unusable.",
          error: null,
        }),
        "identity_unusable",
      );
    },
    [applyReviewState],
  );

  const reportSourceProblem = useCallback(
    (item: EditableIdentity) => {
      applyReviewState(
        item,
        { operation: "report_identity_source_problem", item_id: item.itemId },
        "Identity source problem reported.",
        (outcome) => ({
          ...outcome,
          status: "failed",
          candidates: [],
          unusable_reason: null,
          error: "Reviewed source problem.",
        }),
        "source_problem",
      );
    },
    [applyReviewState],
  );

  const rebaseReference = useCallback(() => {
    if (generatedRevisionId === null) return;
    enqueue(
      { operation: "rebase", source_revision_id: generatedRevisionId },
      "Identity review refreshed from the selected result. Changed cards need review.",
      (current) => current,
    );
  }, [enqueue, generatedRevisionId]);

  const completeReference = useCallback(async () => {
    const current = referenceRef.current;
    const currentItems = itemsRef.current;
    const pending = currentItems.filter(
      (item) =>
        item.reviewState === "pending" || item.reviewState === "affected",
    );
    if (
      current === null ||
      reviewerId.trim() === "" ||
      pending.length > 0 ||
      currentItems.some(
        (item) => !inspectedItemIdsRef.current.has(item.itemId),
      ) ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      saveState !== "saved"
    ) {
      return;
    }
    setCompletionBusy(true);
    setSaveState("saving");
    try {
      const completed = await client.completePipelineReference(
        recordingId,
        CONTENT_TYPE,
        {
          expected_revision: serverRevisionRef.current,
          operator_id: reviewerId.trim(),
          coverage: {
            kind: "identity_cards",
            cards: currentItems.map((item) => ({
              card_id: item.itemId,
              decision:
                item.outcome.status === "classified" ? "identity" : "unusable",
            })),
          },
        },
      );
      hydrateReference(completed, false);
      setSaveState("saved");
      setNotice(
        `Completed identity reference ${completed.state.selected_completed_revision_id ?? "published"}.`,
      );
    } catch (reason: unknown) {
      setSaveState(
        reason instanceof ApiError && reason.status === 409
          ? "conflict"
          : "error",
      );
      setError(describeError(reason));
    } finally {
      setCompletionBusy(false);
    }
  }, [client, hydrateReference, recordingId, reviewerId, saveState]);

  const createReference = useCallback(async () => {
    if (operatorId.trim() === "") return;
    setCreatingReference(true);
    setError(null);
    try {
      const created = await client.createPipelineReference(
        recordingId,
        CONTENT_TYPE,
        {
          operator_id: operatorId.trim(),
          seed: generatedRevisionId === null ? "empty" : "selected_generated",
          ...(generatedRevisionId === null
            ? {}
            : { source_revision_id: generatedRevisionId }),
        },
      );
      hydrateReference(created, false);
      setReviewerId((current) => current || operatorId.trim());
      setNotice(
        "Maintained identity reference created from the selected result.",
      );
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409)
        await loadReference();
      else setError(describeError(reason));
    } finally {
      setCreatingReference(false);
    }
  }, [
    client,
    generatedRevisionId,
    hydrateReference,
    loadReference,
    operatorId,
    recordingId,
  ]);

  const reloadWinningDraft = useCallback(async () => {
    try {
      const winning = await client.getPipelineReference(
        recordingId,
        CONTENT_TYPE,
      );
      hydrateReference(winning);
      setSaveState("saving");
      setError(null);
      setNotice(
        "Winning identity draft loaded. Queued commands will retry in order.",
      );
      window.setTimeout(() => void processQueueRef.current?.(), 0);
    } catch (reason: unknown) {
      setSaveState("error");
      setError(describeError(reason));
    }
  }, [client, hydrateReference, recordingId]);

  const retryQueuedCommands = useCallback(() => {
    if (queueRef.current.length === 0) return;
    queueRef.current[0].attempts = 0;
    setSaveState("saving");
    setError(null);
    void processQueueRef.current?.();
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target !== null &&
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      )
        return;
      const current = itemsRef.current;
      const index = current.findIndex(
        (item) => item.itemId === selectedItemIdRef.current,
      );
      const item = current[index >= 0 ? index : 0];
      if (event.key === " " && videoRef.current !== null) {
        event.preventDefault();
        if (videoRef.current.paused)
          void videoRef.current.play().catch(() => undefined);
        else videoRef.current.pause();
      } else if (event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        selectItem(current[index - 1]);
      } else if (
        event.key === "ArrowRight" &&
        index >= 0 &&
        index < current.length - 1
      ) {
        event.preventDefault();
        selectItem(current[index + 1]);
      } else if (
        (event.key === "a" || event.key === "A") &&
        item !== undefined
      ) {
        event.preventDefault();
        acceptSuggestion(item);
      } else if (
        (event.key === "u" || event.key === "U") &&
        item !== undefined
      ) {
        event.preventDefault();
        markUnusable(item);
      } else if (
        (event.key === "s" || event.key === "S") &&
        item !== undefined
      ) {
        event.preventDefault();
        reportSourceProblem(item);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [acceptSuggestion, markUnusable, reportSourceProblem, selectItem]);

  const activeItems = view === "reviewed" ? items : generatedItems;
  const activeItem =
    activeItems.find((item) => item.itemId === selectedItemId) ?? null;
  const reviewed = view === "reviewed";
  const pendingCount = items.filter(
    (item) => item.reviewState === "pending" || item.reviewState === "affected",
  ).length;
  const coveragePercent =
    items.length === 0 ? 0 : (inspectedItemIds.size / items.length) * 100;
  const sourceMismatch =
    reference !== null &&
    generatedRevisionId !== null &&
    reference.draft.source_revision_id !== generatedRevisionId;
  const completionBlocker =
    !reviewed || reference === null
      ? null
      : pendingCount > 0
        ? `${pendingCount} identity item${pendingCount === 1 ? "" : "s"} still need a decision.`
        : items.some((item) => !inspectedItemIds.has(item.itemId))
          ? "Inspect every identity item before completing the reference."
          : queueLength > 0 ||
              saveState === "saving" ||
              saveState === "retrying"
            ? "Wait for all identity commands to save."
            : saveState !== "saved"
              ? "Resolve the identity save problem before completing the reference."
              : reviewerId.trim() === ""
                ? "Enter the reviewer ID before completing the reference."
                : null;
  const exactCoverage = reference?.draft.coverage;
  const datasetReadiness =
    reference?.state.draft_state === "completed" &&
    readIdentityCoverage(exactCoverage).length === items.length
      ? "Ready"
      : "Blocked until complete identity coverage";

  if (!reviewed) {
    return (
      <GeneratedIdentityView
        items={generatedItems}
        loading={generatedLoading}
        revisionId={displayedRevisionId}
        recordingId={recordingId}
        onSelect={(item) => selectItem(item)}
      />
    );
  }
  if (loading) {
    return (
      <p className={styles.detailEmptyState}>
        Loading maintained visual-identity reference…
      </p>
    );
  }
  if (reference === null) {
    return (
      <section
        className={styles.cardEventReviewPanel}
        aria-label="Start visual identity review"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Maintained reference</p>
            <h3>Start visual identity review</h3>
          </div>
          <span className={styles.countLabel}>
            {generatedItems.length} identity items
          </span>
        </div>
        <p className={styles.detailLead}>
          Classifier output is immutable. Review one recording-owned identity
          reference.
        </p>
        <label className={styles.cardEventReviewer}>
          Operator ID
          <input
            value={operatorId}
            onChange={(event) => setOperatorId(event.target.value)}
            placeholder="operator-01"
          />
        </label>
        {error !== null ? (
          <p className={styles.errorMessage} role="alert">
            {error}
          </p>
        ) : null}
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => void createReference()}
          disabled={creatingReference || operatorId.trim() === ""}
        >
          {creatingReference ? "Starting review…" : "Start review"}
        </button>
      </section>
    );
  }

  return (
    <section
      className={styles.cardEventPipelineEditor}
      aria-label="Visual identity maintained reference editor"
    >
      <div className={styles.cardEventReviewHeader}>
        <div>
          <p className={styles.statusLabel}>Maintained reference</p>
          <h3>Visual identity review</h3>
          <p className={styles.detailLead}>
            {reference.draft.source_revision_id === null
              ? "Manual visual-identity reference"
              : `Used visual-identity suggestions ${reference.draft.source_revision_id}`}
          </p>
        </div>
        <div
          className={styles.cardEventReviewCounts}
          aria-label="Visual identity counts"
        >
          <ReviewCount label="Decided" value={items.length - pendingCount} />
          <ReviewCount label="Pending" value={pendingCount} />
          <ReviewCount
            label="Coverage"
            value={Math.round(coveragePercent)}
            suffix="%"
          />
        </div>
      </div>
      <label className={styles.cardEventReviewer}>
        Operator ID
        <input
          value={operatorId}
          onChange={(event) => setOperatorId(event.target.value)}
          placeholder="operator-01"
        />
      </label>

      {sourceMismatch ? (
        <div className={styles.identityFailure} role="status">
          <strong>Selected identity result changed</strong>
          <p>
            Refresh the draft to mark changed geometry or crop work as affected.
            Unchanged cards keep their review.
          </p>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={rebaseReference}
            disabled={queueLength > 0 || operatorId.trim() === ""}
          >
            Refresh from selected result
          </button>
        </div>
      ) : null}

      <div className={styles.cardEventPipelineVideoGrid}>
        <aside
          className={styles.visibleCardItemRail}
          aria-label="Identity items"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Source items</p>
              <h4>Identity cards</h4>
            </div>
            <span className={styles.countLabel}>{items.length}</span>
          </div>
          <ol className={styles.visibleCardItemList}>
            {items.map((item, index) => (
              <li key={item.itemId}>
                <button
                  className={styles.visibleCardItemButton}
                  type="button"
                  data-selected={item.itemId === selectedItemId}
                  onClick={() => selectItem(item)}
                >
                  <span>Card {index + 1}</span>
                  <strong>{item.itemId}</strong>
                  <small>{formatIdentifier(item.reviewState)}</small>
                </button>
              </li>
            ))}
          </ol>
        </aside>
        <div>
          <video
            ref={videoRef}
            className={styles.cardEventSourceVideo}
            src={videoUrl}
            controls
            preload="metadata"
            aria-label={`Visual identity source video ${recordingId}`}
            onTimeUpdate={(event) => {
              const value = clamp(
                event.currentTarget.currentTime * 1_000_000,
                durationUs,
              );
              setPlayheadUs(value);
              updatePipelineUrl({ t_us: value });
            }}
          />
          <div
            className={styles.cardEventTimeline}
            aria-label="Identity timeline"
          >
            {items.map((item) => (
              <button
                key={item.itemId}
                className={styles.cardEventMarker}
                type="button"
                data-selected={item.itemId === selectedItemId}
                data-state={item.reviewState}
                style={{
                  left: `${(item.outcome.frame_identity.requested_time_us / Math.max(durationUs, 1)) * 100}%`,
                }}
                aria-label={`Select identity ${item.itemId}`}
                onClick={() => selectItem(item)}
              />
            ))}
          </div>
          <p className={styles.pipelineUrlState}>
            Playhead {formatMicroseconds(playheadUs)} · {inspectedItemIds.size}/
            {items.length} identity items inspected
          </p>
          {activeItem === null ? (
            <p className={styles.detailEmptyState}>Select an identity item.</p>
          ) : (
            <IdentityItemPanel
              recordingId={recordingId}
              sourceRevisionId={reference.draft.source_revision_id}
              item={activeItem}
              onAccept={() => acceptSuggestion(activeItem)}
              onSelectIdentity={(identity) =>
                selectIdentity(activeItem, identity)
              }
              onMarkUnusable={() => markUnusable(activeItem)}
              onReportSourceProblem={() => reportSourceProblem(activeItem)}
            />
          )}
        </div>
      </div>

      <section
        className={styles.cardEventCoverage}
        aria-label="Visual identity review coverage"
      >
        <span>Identity coverage</span>
        <strong>{Math.round(coveragePercent)}% inspected</strong>
        <progress
          max={100}
          value={coveragePercent}
          aria-label="Identity coverage"
        />
        <p>
          Each upstream visible card needs an identity or unusable decision.
        </p>
        <p>
          <strong>Dataset readiness:</strong> {datasetReadiness}
        </p>
        <details>
          <summary>Exact backend coverage facts</summary>
          <pre>
            {exactCoverage === null || exactCoverage === undefined
              ? "No completion coverage recorded."
              : JSON.stringify(exactCoverage, null, 2)}
          </pre>
        </details>
      </section>
      <section
        className={styles.cardEventCompletionBar}
        aria-label="Complete maintained visual identity reference"
      >
        <div>
          <p className={styles.statusLabel}>Review completion</p>
          <strong>Complete visual identity review</strong>
          {completionBlocker !== null ? (
            <p className={styles.cardEventCompletionRequirement}>
              {completionBlocker}
            </p>
          ) : null}
        </div>
        <label className={styles.cardEventCompletionReviewer}>
          Reviewer ID
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
          {completionBusy ? "Completing reference…" : "Complete reference"}
        </button>
      </section>
      <details className={styles.cardEventGuidance}>
        <summary>Keyboard shortcuts</summary>
        <p>
          Space play/pause · ←/→ previous/next card · A accept suggestion · U
          identity unusable · S source problem.
        </p>
      </details>
      {notice !== null ? (
        <p className={styles.recordingNotice} role="status">
          {notice}
        </p>
      ) : null}
      {error !== null ? (
        <div className={styles.cardEventError} role="alert">
          <p>
            {saveState === "conflict"
              ? `Conflict: the first unapplied command is ${firstUnappliedCommand ?? "unknown"}. ${error}`
              : error}
          </p>
          <div className={styles.cardEventErrorActions}>
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
    </section>
  );
}

function IdentityItemPanel({
  recordingId,
  sourceRevisionId,
  item,
  onAccept,
  onSelectIdentity,
  onMarkUnusable,
  onReportSourceProblem,
}: {
  recordingId: string;
  sourceRevisionId: string | null;
  item: EditableIdentity;
  onAccept: () => void;
  onSelectIdentity: (identity: string) => void;
  onMarkUnusable: () => void;
  onReportSourceProblem: () => void;
}) {
  const crop = item.outcome.crop_identity;
  const frame = item.outcome.frame_identity;
  const frameUrl = pipelineDerivedFramePath(
    recordingId,
    frame.requested_time_us,
  );
  const cropUrl =
    crop?.status === "usable" && sourceRevisionId !== null
      ? pipelineIdentityCropPath(recordingId, sourceRevisionId, item.itemId)
      : null;
  const selectedIdentity = item.outcome.candidates[0]?.identity ?? null;
  return (
    <section
      className={styles.visibleCardFramePanel}
      aria-label="Selected visual identity"
    >
      <header className={styles.visibleCardFrameHeader}>
        <div>
          <p className={styles.statusLabel}>Source item {item.itemId}</p>
          <h3>
            {formatMicroseconds(frame.requested_time_us)} · resolved frame
          </h3>
        </div>
        <span className={styles.status} data-state={item.reviewState}>
          {formatIdentifier(item.reviewState)}
        </span>
      </header>
      <div className={styles.identityDetailGrid}>
        <section className={styles.identitySourceCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Source frame</p>
              <h4>Read-only geometry</h4>
            </div>
          </div>
          <img
            className={styles.visibleCardCanvasImage}
            src={frameUrl}
            width={frame.width}
            height={frame.height}
            alt={`Resolved source frame for ${item.itemId}`}
          />
          <p className={styles.detailMetaLine}>
            Frame {frame.frame_index} · {frame.width} × {frame.height}
          </p>
          <p className={styles.identityLegend}>
            Geometry belongs to the maintained visible-card reference. Identity
            review cannot edit it.
          </p>
          <a
            className={styles.recordingLink}
            href={visibleCardReviewPath(
              recordingId,
              item.itemId,
              frame.requested_time_us,
            )}
          >
            Open visible-card geometry review
          </a>
        </section>
        <section className={styles.identityCropCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Derived view</p>
              <h4>Identity crop</h4>
            </div>
            <span className={styles.countLabel}>
              {crop?.crop_policy ?? "Unavailable"}
            </span>
          </div>
          {cropUrl !== null ? (
            <img
              className={styles.identityCropImage}
              src={cropUrl}
              alt={`Derived identity crop for ${item.itemId}`}
            />
          ) : (
            <p className={styles.detailEmptyState}>
              {crop?.unusable_reason ??
                item.outcome.error ??
                "No usable crop is available."}
            </p>
          )}
          <p className={styles.detailMetaLine}>
            Crop digest {crop?.image_sha256 ?? "Not available"}
          </p>
        </section>
      </div>
      <section className={styles.identityProposalCard}>
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Classifier proposal</p>
            <h4>Suggestion only</h4>
          </div>
          <span className={styles.countLabel}>
            {item.outcome.candidates.length} candidates
          </span>
        </div>
        {item.outcome.candidates.length === 0 ? (
          <p className={styles.detailEmptyState}>
            No identity prediction is available. Select a canonical identity
            manually.
          </p>
        ) : (
          <ol className={styles.identityCandidateList}>
            {item.outcome.candidates.map((candidate) => (
              <li key={candidate.identity}>
                <strong>{candidate.identity}</strong>
                <span>
                  {candidate.score === null
                    ? "manual"
                    : formatScore(candidate.score)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
      <section className={styles.identityDecisionCard}>
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Human decision</p>
            <h4>{formatIdentifier(item.reviewState)}</h4>
          </div>
        </div>
        <div className={styles.visibleCardOutcomeButtons}>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={onAccept}
            disabled={item.outcome.candidates.length === 0}
          >
            Accept identity suggestion
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onMarkUnusable}
            disabled={crop === null}
          >
            Mark identity unusable
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onReportSourceProblem}
          >
            Report source problem
          </button>
        </div>
        <div
          className={styles.identityChoiceGrid}
          aria-label="Canonical identities"
        >
          {CANONICAL_IDENTITIES.map((identity) => (
            <button
              key={identity}
              className={styles.identityChoiceButton}
              data-selected={selectedIdentity === identity}
              type="button"
              aria-pressed={selectedIdentity === identity}
              onClick={() => onSelectIdentity(identity)}
              disabled={crop === null}
            >
              {identity}
            </button>
          ))}
        </div>
        {item.outcome.error !== null ? (
          <p className={styles.detailBlocker}>{item.outcome.error}</p>
        ) : null}
      </section>
    </section>
  );
}

function GeneratedIdentityView({
  items,
  loading,
  revisionId,
  recordingId,
  onSelect,
}: {
  items: EditableIdentity[];
  loading: boolean;
  revisionId: string | null;
  recordingId: string;
  onSelect: (item: EditableIdentity) => void;
}) {
  return (
    <section
      className={styles.cardEventReviewPanel}
      aria-label="Generated visual identity result"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Generated result</p>
          <h3>Visual identity suggestions</h3>
        </div>
        <span className={styles.countLabel}>{items.length} cards</span>
      </div>
      <p className={styles.detailLead}>
        Generated classifier output is immutable. Choose Review to copy this
        exact result into the maintained reference.
      </p>
      {revisionId !== null ? (
        <p className={styles.pipelineUrlState}>Source revision {revisionId}</p>
      ) : null}
      {loading ? (
        <p className={styles.detailEmptyState}>
          Loading generated visual identities…
        </p>
      ) : items.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No generated visual-identity result is selected.
        </p>
      ) : (
        <div className={styles.tableScroller}>
          <table className={styles.cardEventReviewTable}>
            <caption className={styles.visuallyHidden}>
              Generated visual identity suggestions
            </caption>
            <thead>
              <tr>
                <th scope="col">Card</th>
                <th scope="col">Resolved time</th>
                <th scope="col">Status</th>
                <th scope="col">Suggestion</th>
                <th scope="col">Crop</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.itemId}>
                  <td>
                    <button
                      className={styles.cardEventTableSelect}
                      type="button"
                      onClick={() => onSelect(item)}
                    >
                      {item.itemId}
                    </button>
                  </td>
                  <td>
                    {formatMicroseconds(
                      item.outcome.frame_identity.requested_time_us,
                    )}
                  </td>
                  <td>{formatIdentifier(item.outcome.status)}</td>
                  <td>{item.outcome.candidates[0]?.identity ?? "None"}</td>
                  <td>
                    {item.outcome.crop_identity?.image_sha256 ?? "Unavailable"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items[0] !== undefined ? (
            <p className={styles.detailMetaLine}>
              Source frames use{" "}
              {pipelineDerivedFramePath(
                recordingId,
                items[0].outcome.frame_identity.requested_time_us,
              )}
              .
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

function toEditableIdentity(
  item: PipelineReferenceItem,
): EditableIdentity | null {
  const outcome = readOutcome(item.item);
  if (outcome === null || !isReviewState(item.review_state)) return null;
  return {
    itemId: item.item_id,
    baseItemId: item.base_item_id,
    reviewState: item.review_state,
    outcome,
  };
}

function readItemsFromResult(
  result: PipelineVisualIdentityResult,
  revisionId: string,
): EditableIdentity[] {
  const revision =
    result.revisions.find(
      (candidate) => candidate.manifest.revision_id === revisionId,
    ) ?? result.revisions[0];
  const outcomes = revision?.content.outcomes;
  if (!Array.isArray(outcomes)) return [];
  const items: Array<EditableIdentity | null> = outcomes.map((item) => {
    const outcome = readOutcome(item);
    return outcome === null
      ? null
      : {
          itemId: outcome.card_id,
          baseItemId: null,
          reviewState: "pending" as const,
          outcome,
        };
  });
  return items.filter((item): item is EditableIdentity => item !== null);
}

function readOutcome(value: Record<string, unknown>): IdentityOutcome | null {
  const cardId = value.card_id;
  const frame = readFrameIdentity(value.frame_identity);
  const geometry = isRecord(value.geometry) ? value.geometry : null;
  const status = value.status;
  if (
    typeof cardId !== "string" ||
    frame === null ||
    geometry === null ||
    !["classified", "unusable", "failed"].includes(String(status))
  )
    return null;
  const candidates = Array.isArray(value.candidates)
    ? value.candidates
        .map(readCandidate)
        .filter(
          (candidate): candidate is IdentityCandidate => candidate !== null,
        )
    : [];
  const crop =
    value.crop_identity === null || value.crop_identity === undefined
      ? null
      : readCropIdentity(value.crop_identity);
  if (
    value.crop_identity !== null &&
    value.crop_identity !== undefined &&
    crop === null
  )
    return null;
  return {
    card_id: cardId,
    frame_identity: frame,
    geometry,
    crop_identity: crop,
    status: status as IdentityOutcome["status"],
    candidates,
    unusable_reason:
      typeof value.unusable_reason === "string" ? value.unusable_reason : null,
    error: typeof value.error === "string" ? value.error : null,
  };
}

function readFrameIdentity(value: unknown): FrameIdentity | null {
  if (
    !isRecord(value) ||
    !isInteger(value.requested_time_us) ||
    !isInteger(value.frame_index) ||
    !isInteger(value.presentation_timestamp_us) ||
    !isInteger(value.width) ||
    !isInteger(value.height)
  )
    return null;
  return value as FrameIdentity;
}

function readCropIdentity(value: unknown): CropIdentity | null {
  if (
    !isRecord(value) ||
    (value.status !== "usable" && value.status !== "unusable") ||
    typeof value.crop_policy !== "string" ||
    typeof value.output_encoding !== "string"
  )
    return null;
  return {
    ...(value as Record<string, unknown>),
    status: value.status,
    crop_policy: value.crop_policy,
    output_encoding: value.output_encoding,
    image_sha256:
      typeof value.image_sha256 === "string" ? value.image_sha256 : null,
    unusable_reason:
      typeof value.unusable_reason === "string" ? value.unusable_reason : null,
  } as CropIdentity;
}

function readCandidate(value: unknown): IdentityCandidate | null {
  if (!isRecord(value) || typeof value.identity !== "string") return null;
  return {
    identity: value.identity,
    score: typeof value.score === "number" ? value.score : null,
    score_meaning:
      typeof value.score_meaning === "string" ? value.score_meaning : null,
  };
}

function readIdentityCoverage(
  value: unknown,
): Array<{ card_id: string; decision: string }> {
  if (!isRecord(value) || !Array.isArray(value.cards)) return [];
  return value.cards
    .filter(isRecord)
    .filter(
      (card) =>
        typeof card.card_id === "string" && typeof card.decision === "string",
    )
    .map((card) => ({
      card_id: String(card.card_id),
      decision: String(card.decision),
    }));
}

function acceptedState(item: EditableIdentity): IdentityReviewState {
  return item.baseItemId !== null
    ? "corrected"
    : item.reviewState === "added"
      ? "added"
      : "accepted";
}

function isReviewState(value: string): value is IdentityReviewState {
  return [
    "pending",
    "accepted",
    "added",
    "corrected",
    "unusable",
    "identity_unusable",
    "source_problem",
    "affected",
  ].includes(value);
}

function updatePipelineUrl(values: { item?: string; t_us?: number }): void {
  const url = new URL(window.location.href);
  if (values.item !== undefined) url.searchParams.set("item", values.item);
  if (values.t_us !== undefined)
    url.searchParams.set("t_us", String(Math.round(values.t_us)));
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
}

function visibleCardReviewPath(
  recordingId: string,
  itemId: string,
  timeUs: number,
): string {
  const params = new URLSearchParams({
    view: "reviewed",
    item: itemId,
    t_us: String(Math.round(timeUs)),
  });
  return `/recordings/${encodeURIComponent(recordingId)}/pipeline/visible_cards?${params.toString()}`;
}

function clamp(value: number, durationUs: number): number {
  return Math.min(Math.max(0, Math.round(value)), Math.max(durationUs, 0));
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRetryableError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 408 || error.status === 429 || error.status >= 500)
  );
}

function describeCommand(command: PendingCommand): string {
  return `${command.operation.operation}${command.operation.item_id === undefined ? "" : ` (${command.operation.item_id})`}`;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const body =
      isRecord(error.body) && typeof error.body.message === "string"
        ? error.body.message
        : null;
    return body ?? `The identity request failed with status ${error.status}.`;
  }
  return error instanceof Error
    ? error.message
    : "The identity request failed.";
}

function formatIdentifier(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)} s`;
}

function formatScore(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function ReviewCount({
  label,
  value,
  suffix = "",
}: {
  label: string;
  value: number;
  suffix?: string;
}) {
  return (
    <span>
      <small>{label}</small>
      <strong>
        {value}
        {suffix}
      </strong>
    </span>
  );
}
