import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  ApiError,
  createDokoDetectorClient,
  type PipelineReferenceItem,
  type PipelineReferenceOperation,
  type PipelineReferenceResource,
  type PipelineVisualIdentityResult,
} from "../api/client";
import styles from "../App.module.css";
import {
  IdentityInspectorPortals,
  useIdentityInspectorSlots,
} from "./PipelineVisualIdentityInspector";
import {
  readProfileName,
  subscribeToProfileName,
  useProfileName,
} from "../profile/profile";
import {
  IdentityCardList,
  IdentitySourceSurface,
} from "./PipelineVisualIdentityPresentation";
import {
  describeCommand,
  formatCardIdentity,
  identityReviewStatus,
} from "./PipelineVisualIdentityFormatting";
import type {
  CropIdentity,
  EditableIdentity,
  FrameIdentity,
  IdentityCandidate,
  IdentityOutcome,
  IdentityReviewState,
  PendingCommand,
  PipelineVisualIdentityRailItem,
  SaveState,
} from "./PipelineVisualIdentityTypes";
export type { PipelineVisualIdentityRailItem } from "./PipelineVisualIdentityTypes";

const CONTENT_TYPE = "visual_identities" as const;
const RETRY_LIMIT = 3;

export type PipelineVisualIdentityEditorProps = {
  recordingId: string;
  durationUs: number;
  selectionItemId?: string | null;
  selectionTimeUs?: number | null;
  generatedRevisionId: string | null;
  displayedRevisionId?: string | null;
  generatedRunId: string | null;
  view: "generated" | "reviewed";
  onRailItemsChange?: (items: PipelineVisualIdentityRailItem[]) => void;
  inspectorEnabled?: boolean;
};

export function PipelineVisualIdentityEditor({
  recordingId,
  durationUs,
  selectionItemId,
  selectionTimeUs,
  generatedRevisionId,
  displayedRevisionId = generatedRevisionId,
  generatedRunId,
  view,
  onRailItemsChange,
  inspectorEnabled = true,
}: PipelineVisualIdentityEditorProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const profileName = useProfileName();
  const videoRef = useRef<HTMLVideoElement>(null);
  const referenceRef = useRef<PipelineReferenceResource | null>(null);
  const itemsRef = useRef<EditableIdentity[]>([]);
  const navigationItemsRef = useRef<EditableIdentity[]>([]);
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
  const [loading, setLoading] = useState(view === "reviewed");
  const [generatedLoading, setGeneratedLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [queueLength, setQueueLength] = useState(0);
  const [firstUnappliedCommand, setFirstUnappliedCommand] = useState<
    string | null
  >(null);
  const [operatorId, setOperatorId] = useState(profileName);
  const [reviewerId, setReviewerId] = useState(profileName);
  const [inspectedItemIds, setInspectedItemIds] = useState<Set<string>>(
    new Set(),
  );
  const [creatingReference, setCreatingReference] = useState(false);
  const [completionBusy, setCompletionBusy] = useState(false);
  const inspectorSlots = useIdentityInspectorSlots(inspectorEnabled, view);
  const generatedSourceRevisionId = displayedRevisionId ?? generatedRevisionId;
  const usesMaintainedIdentities = view === "reviewed" && reference !== null;
  const [cardListSlot, setCardListSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setCardListSlot(
        document.querySelector<HTMLElement>(
          "[data-identity-card-list-slot='cards']",
        ),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [view]);

  useEffect(
    () =>
      subscribeToProfileName(() => {
        const nextProfileName = readProfileName();
        setOperatorId(nextProfileName);
        setReviewerId(nextProfileName);
      }),
    [],
  );

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
    (
      nextReference: PipelineReferenceResource,
      preserveSelection = true,
      pendingCommands: PendingCommand[] = [],
    ) => {
      const serverItems = nextReference.draft.items
        .map(toEditableIdentity)
        .filter((item): item is EditableIdentity => item !== null);
      const nextItems = pendingCommands.reduce(
        (current, command) => command.applyOptimistic(current),
        serverItems,
      );
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
      if (generatedRunId === null || generatedSourceRevisionId === null) {
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
          setGeneratedItems(
            readItemsFromResult(result, generatedSourceRevisionId),
          );
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) setError(describeError(reason));
      } finally {
        if (!signal?.aborted) setGeneratedLoading(false);
      }
    },
    [client, generatedRunId, generatedSourceRevisionId, recordingId],
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
    const candidates = usesMaintainedIdentities ? items : generatedItems;
    const urlState = new URLSearchParams(window.location.search);
    const itemId =
      selectionItemId === undefined ? urlState.get("item") : selectionItemId;
    const selected =
      candidates.find((item) => item.itemId === itemId) ?? candidates[0];
    const rawTime = urlState.get("t_us");
    const requestedTimeUs =
      selectionTimeUs === undefined
        ? rawTime !== null && /^\d+$/.test(rawTime)
          ? Number(rawTime)
          : null
        : selectionTimeUs;
    const timer = window.setTimeout(() => {
      if (selected !== undefined) selectItem(selected, false);
      if (requestedTimeUs !== null && videoRef.current?.paused !== false) {
        setCurrentTime(requestedTimeUs, false);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    generatedItems,
    items,
    selectionItemId,
    selectionTimeUs,
    selectItem,
    setCurrentTime,
    usesMaintainedIdentities,
  ]);

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
      queueRef.current.shift();
      hydrateReference(nextReference, true, queueRef.current);
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
        applyOptimistic: optimistic,
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
        `Identity selected: ${formatCardIdentity(identity)}.`,
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

  const setUnreviewed = useCallback(
    (item: EditableIdentity) => {
      applyReviewState(
        item,
        { operation: "set_identity_unreviewed", item_id: item.itemId },
        "Identity returned to unreviewed.",
        (outcome) => outcome,
        "pending",
      );
    },
    [applyReviewState],
  );

  const toggleAcceptance = useCallback(
    (item: EditableIdentity) => {
      if (identityReviewStatus(item) === "accepted") {
        setUnreviewed(item);
      } else {
        acceptSuggestion(item);
      }
    },
    [acceptSuggestion, setUnreviewed],
  );

  const toggleUnusable = useCallback(
    (item: EditableIdentity) => {
      if (identityReviewStatus(item) === "unusable") {
        setUnreviewed(item);
      } else {
        markUnusable(item);
      }
    },
    [markUnusable, setUnreviewed],
  );

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
            kind: "visual_identities",
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
          seed:
            generatedSourceRevisionId === null ? "empty" : "selected_generated",
          ...(generatedSourceRevisionId === null
            ? {}
            : { source_revision_id: generatedSourceRevisionId }),
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
    generatedSourceRevisionId,
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
      hydrateReference(winning, true, queueRef.current);
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
      const current = navigationItemsRef.current;
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
        toggleAcceptance(item);
      } else if (
        (event.key === "u" || event.key === "U") &&
        item !== undefined
      ) {
        event.preventDefault();
        toggleUnusable(item);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectItem, toggleAcceptance, toggleUnusable]);

  useEffect(() => {
    navigationItemsRef.current = usesMaintainedIdentities
      ? items
      : generatedItems;
  }, [generatedItems, items, usesMaintainedIdentities]);

  useEffect(() => {
    const source = usesMaintainedIdentities ? items : generatedItems;
    onRailItemsChange?.(
      source.map((item, index) => ({
        itemId: item.itemId,
        label: `Card ${index + 1}`,
        state: identityReviewStatus(item),
        timeUs: item.outcome.frame_identity.requested_time_us,
        cropPolicy: item.outcome.crop_identity?.crop_policy ?? null,
      })),
    );
  }, [generatedItems, items, onRailItemsChange, usesMaintainedIdentities]);

  const activeItems = usesMaintainedIdentities ? items : generatedItems;
  const activeItem =
    activeItems.find((item) => item.itemId === selectedItemId) ??
    activeItems[0] ??
    null;
  const reviewed = view === "reviewed";
  const pendingCount = items.filter(
    (item) => identityReviewStatus(item) === "unreviewed",
  ).length;
  const coveragePercent =
    items.length === 0 ? 0 : (inspectedItemIds.size / items.length) * 100;
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
  const inspector = (
    <IdentityInspectorPortals
      slots={inspectorSlots}
      inspectorEnabled={inspectorEnabled}
      view={view}
      reference={reference}
      item={activeItem}
      itemCount={activeItems.length}
      pendingCount={pendingCount}
      coveragePercent={coveragePercent}
      inspectedCount={inspectedItemIds.size}
      saveState={saveState}
      queueLength={queueLength}
      firstUnappliedCommand={firstUnappliedCommand}
      error={error}
      notice={notice}
      operatorId={operatorId}
      reviewerId={reviewerId}
      setOperatorId={setOperatorId}
      setReviewerId={setReviewerId}
      completionBusy={completionBusy}
      completionBlocker={completionBlocker}
      creatingReference={creatingReference}
      createReference={createReference}
      completeReference={completeReference}
      retryQueuedCommands={retryQueuedCommands}
      reloadWinningDraft={reloadWinningDraft}
      acceptSuggestion={() =>
        activeItem !== null && toggleAcceptance(activeItem)
      }
      markUnusable={() => activeItem !== null && toggleUnusable(activeItem)}
      selectIdentity={(identity) =>
        activeItem !== null && selectIdentity(activeItem, identity)
      }
    />
  );

  const cardList =
    cardListSlot === null
      ? null
      : createPortal(
          <IdentityCardList
            items={activeItems.filter(
              (item) =>
                item.outcome.frame_identity.frame_index ===
                activeItem?.outcome.frame_identity.frame_index,
            )}
            selectedItemId={selectedItemId}
            onSelect={selectItem}
          />,
          cardListSlot,
        );

  if (!reviewed || reference === null) {
    return (
      <>
        {inspector}
        {cardList}
        <IdentitySourceSurface
          recordingId={recordingId}
          item={activeItem}
          items={activeItems}
          loading={generatedLoading}
          sourceRevisionId={generatedSourceRevisionId}
        />
      </>
    );
  }
  if (loading) {
    return (
      <>
        {inspector}
        {cardList}
        <p className={styles.detailEmptyState}>
          Loading maintained visual-identity reference…
        </p>
      </>
    );
  }
  return (
    <>
      {inspector}
      {cardList}
      <IdentitySourceSurface
        recordingId={recordingId}
        item={activeItem}
        items={activeItems}
        loading={false}
        sourceRevisionId={reference.draft.source_revision_id}
        onSelectIdentity={(identity) =>
          activeItem !== null && selectIdentity(activeItem, identity)
        }
      />
    </>
  );

  /* obsolete identity list, stage timeline, and completion bar removed */
  /*
    <section className={styles.cardEventPipelineEditor}>
      <div className={styles.cardEventReviewHeader}>
        <div>
          <p className={styles.statusLabel}>Maintained reference</p>
          <h3>Visual identity review</h3>
          <p className={styles.detailLead}>
            {reference?.draft.source_revision_id === null
              ? "Manual visual-identity reference"
              : `Used visual-identity suggestions ${reference?.draft.source_revision_id ?? ""}`}
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
            data-recording-source-video={recordingId}
            src={videoUrl}
            controls
            preload="none"
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
              sourceRevisionId={reference?.draft.source_revision_id ?? null}
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
  */
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
  window.dispatchEvent(new PopStateEvent("popstate"));
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
