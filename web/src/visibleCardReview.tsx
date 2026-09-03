import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type SetStateAction,
} from "react";

import {
  ApiError,
  createDokoDetectorClient,
  visibleCardReviewBatchPagePath,
  type VisibleCardReviewItemUpdateRequest,
  type VisibleCardReviewBatch,
} from "./api/client";
import styles from "./App.module.css";

type BatchItem = VisibleCardReviewBatch["items"][number];
type Proposal = NonNullable<BatchItem["finder"]>["proposals"][number];
type ReviewedCard = NonNullable<
  NonNullable<BatchItem["review"]>["actions"][number]["reviewed_card"]
>;
type ReviewUpdate = VisibleCardReviewItemUpdateRequest["review"];
type ReviewAction = ReviewUpdate["actions"][number];
type Point = ReviewedCard["visible_region"]["polygons"][number][number];
type Outcome = "usable" | "empty" | "unusable";
type EditorState = {
  action: "reshaped" | "added";
  cardId: string;
  proposalIndex: number | null;
  polygons: Point[][];
  polygonIndex: number;
  selectedPointIndex: number | null;
  side: ReviewedCard["side"];
  usable: boolean;
  reason: string;
  failureTags: string[];
};

const FAILURE_TAGS = [
  "small_card",
  "occlusion",
  "human_hand",
  "blur",
  "glare",
  "crop_boundary",
  "duplicate",
] as const;

export function VisibleCardReviewPage({
  batchId,
  selectedItemId: initialItemId,
}: {
  batchId: string;
  selectedItemId: string | null;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [batch, setBatch] = useState<VisibleCardReviewBatch | null>(null);
  const [selectedItemId, setSelectedItemId] = useState(initialItemId);
  const [activeProposalIndex, setActiveProposalIndex] = useState<number | null>(
    null,
  );
  const [zoom, setZoom] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState("web-operator");

  const loadBatch = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const loaded = await client.getVisibleCardReviewBatch(batchId, {
          signal,
        });
        if (signal?.aborted) {
          return;
        }
        setBatch(loaded);
        setError(null);
        setLoading(false);
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          setError(describeError(reason));
          setLoading(false);
        }
      }
    },
    [batchId, client],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void loadBatch(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadBatch]);

  useEffect(() => {
    if (batch?.status !== "preparing") {
      return;
    }
    const timer = window.setInterval(() => void loadBatch(), 1000);
    return () => window.clearInterval(timer);
  }, [batch?.status, loadBatch]);

  const effectiveSelectedItemId = effectiveItemId(batch, selectedItemId);
  const selectedIndex = selectedIndexFor(batch, effectiveSelectedItemId);
  const selectedItem =
    selectedIndex === null || batch === null
      ? null
      : (batch.items[selectedIndex] ?? null);

  useEffect(() => {
    if (
      batch !== null &&
      effectiveSelectedItemId !== null &&
      effectiveSelectedItemId !== selectedItemId
    ) {
      replaceSelectedItem(effectiveSelectedItemId, batchId);
    }
  }, [batch, batchId, effectiveSelectedItemId, selectedItemId]);

  function selectItem(itemId: string) {
    setSelectedItemId(itemId);
    setActiveProposalIndex(null);
    setZoom(1);
    replaceSelectedItem(itemId, batchId);
  }

  function moveSelection(offset: number, pendingOnly: boolean) {
    if (batch === null || selectedIndex === null) {
      return;
    }
    const candidates = batch.items
      .map((item, index) => ({ item, index }))
      .filter(
        ({ index }) =>
          (offset < 0 ? index < selectedIndex : index > selectedIndex) &&
          (!pendingOnly || batch.items[index].review?.status !== "reviewed"),
      );
    const next = offset < 0 ? candidates.at(-1) : candidates[0];
    if (next !== undefined) {
      selectItem(next.item.item_id);
    }
  }

  async function retryBatch() {
    setBusy(true);
    setError(null);
    try {
      const retried = await client.retryVisibleCardReviewBatch(batchId);
      setBatch(retried);
    } catch (reason: unknown) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function completeBatch() {
    if (
      batch === null ||
      batch.status !== "ready" ||
      pendingCount > 0 ||
      reviewer.trim() === ""
    ) {
      return;
    }
    if (
      !window.confirm(
        "Publish this complete visible-card review? The published queue will be immutable.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setBatch(
        await client.completeVisibleCardReviewBatch(batchId, {
          reviewer: reviewer.trim(),
          expected_revision: batch.revision,
        }),
      );
    } catch (reason: unknown) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function startRevision() {
    if (
      batch === null ||
      batch.status !== "completed" ||
      batch.completed_version_id === null
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setBatch(
        await client.startVisibleCardReviewRevision(batchId, {
          parent_version_id: batch.completed_version_id,
          expected_revision: batch.revision,
        }),
      );
    } catch (reason: unknown) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function saveReview(itemId: string, review: ReviewUpdate) {
    if (batch === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await client.updateVisibleCardReviewItem(batchId, itemId, {
        expected_revision: batch.revision,
        review,
      });
      setBatch(saved);
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        await loadBatch();
        setError(
          "This review changed in another window. Your action was not applied; the current revision is loaded.",
        );
      } else {
        setError(describeError(reason));
      }
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  async function redetectFrame(itemId: string, model: string | null) {
    if (batch === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setBatch(
        await client.redetectVisibleCardReviewItem(batchId, itemId, {
          expected_revision: batch.revision,
          model,
        }),
      );
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        await loadBatch();
      }
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const pendingCount =
    batch?.items.filter((item) => item.review?.status !== "reviewed").length ??
    0;
  return (
    <main className={`${styles.shell} ${styles.visibleCardReviewPage}`}>
      <header className={styles.visibleCardHeader}>
        <div>
          <a
            className={styles.recordingLink}
            href={recordingPagePath(batch?.recording_id)}
          >
            ← Back to recording
          </a>
          <p className={styles.eyebrow}>DokoDetector · Review workspace</p>
          <h1>Visible-card review</h1>
          <p className={styles.detailContext}>
            Batch {batchId}{" "}
            {batch === null ? "" : `· Recording ${batch.recording_id}`}
          </p>
        </div>
        {batch !== null ? <StatusBadge value={batch.status} /> : null}
      </header>

      {loading && batch === null ? (
        <p className={styles.loading} aria-live="polite">
          Loading review batch…
        </p>
      ) : null}
      {error !== null ? (
        <p className={styles.errorMessage} role="alert">
          {error}
        </p>
      ) : null}
      {batch !== null ? (
        <>
          <section className={styles.visibleCardBatchSummary}>
            <dl
              className={`${styles.detailStats} ${styles.visibleCardSummaryStats}`}
            >
              <Stat
                label="Usable frames"
                value={String(batch.summary.usable_frames)}
              />
              <Stat
                label="Reviewed empty"
                value={String(batch.summary.empty_frames)}
              />
              <Stat
                label="Unusable frames"
                value={String(batch.summary.unusable_frames)}
              />
              <Stat
                label="Retained cards"
                value={String(batch.summary.retained_cards)}
              />
              <Stat
                label="Corrected proposals"
                value={String(batch.summary.corrected_proposals)}
              />
              <Stat
                label="Removed proposals"
                value={String(batch.summary.removed_proposals)}
              />
              <Stat
                label="Added cards"
                value={String(batch.summary.added_cards)}
              />
            </dl>
            {batch.status === "failed" ? (
              <div className={styles.visibleCardFailureBar}>
                <p>
                  {batch.failures[0]?.message ??
                    "One or more review items could not be prepared."}
                </p>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={() => void retryBatch()}
                  disabled={
                    busy || !batch.failures.some((failure) => failure.retryable)
                  }
                >
                  {busy ? "Retrying…" : "Retry failed items"}
                </button>
              </div>
            ) : null}
            {batch.status === "ready" ? (
              <div className={styles.visibleCardPublishPanel}>
                <label>
                  Reviewer
                  <input
                    value={reviewer}
                    onChange={(event) => setReviewer(event.target.value)}
                    disabled={busy}
                  />
                </label>
                <p>
                  {pendingCount === 0
                    ? "Every frame is complete. Review the summary, then publish the immutable queue."
                    : `${pendingCount} frame${pendingCount === 1 ? "" : "s"} remain${pendingCount === 1 ? "s" : ""}.`}
                </p>
                <button
                  className={styles.primaryButton}
                  type="button"
                  onClick={() => void completeBatch()}
                  disabled={busy || pendingCount > 0 || reviewer.trim() === ""}
                >
                  {busy ? "Publishing…" : "Complete review"}
                </button>
              </div>
            ) : null}
            {batch.status === "completed" ? (
              <div className={styles.visibleCardPublishPanel} role="status">
                <p>
                  Published by {batch.reviewer ?? "unknown reviewer"} at{" "}
                  {batch.completed_at_utc ?? "unknown time"}. The completed
                  queue is immutable.
                </p>
                <dl className={styles.detailMetadata}>
                  <Stat
                    label="Reviewed version"
                    value={batch.completed_version_id ?? "Not available"}
                  />
                  <Stat
                    label="Version digest"
                    value={batch.completed_version_digest ?? "Not available"}
                  />
                  <Stat
                    label="Lifecycle receipt"
                    value={batch.completion_receipt_id ?? "Not available"}
                  />
                  <Stat
                    label="Receipt digest"
                    value={batch.completion_receipt_digest ?? "Not available"}
                  />
                  <Stat
                    label="Freeze readiness"
                    value={batch.downstream_readiness.message}
                  />
                </dl>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={() => void startRevision()}
                  disabled={busy}
                >
                  {busy ? "Starting revision…" : "Start a new revision"}
                </button>
              </div>
            ) : null}
          </section>

          {batch.status === "preparing" ? (
            <div className={styles.visibleCardPreparingState}>
              <BatchProgress batch={batch} />
              <p className={styles.visibleCardReviewMessage} aria-live="polite">
                The review workspace will open when finder results are complete.
              </p>
            </div>
          ) : null}

          {batch.items.length > 0 && batch.status !== "preparing" ? (
            <div className={styles.visibleCardWorkspace}>
              <aside
                className={styles.visibleCardItemRail}
                aria-label="Review frames"
              >
                <div className={styles.sectionHeading}>
                  <div>
                    <p className={styles.statusLabel}>Queue</p>
                    <h2>Source frames</h2>
                  </div>
                  <span className={styles.countLabel}>
                    {batch.items.length}
                  </span>
                </div>
                <ol className={styles.visibleCardItemList}>
                  {batch.items.map((item, index) => (
                    <li key={item.item_id}>
                      <button
                        className={styles.visibleCardItemButton}
                        data-selected={item.item_id === selectedItem?.item_id}
                        type="button"
                        onClick={() => selectItem(item.item_id)}
                      >
                        <span>Frame {index + 1}</span>
                        <strong>{formatSeconds(item.event_time_s)}</strong>
                        <small>{formatItemStatus(item)}</small>
                      </button>
                    </li>
                  ))}
                </ol>
              </aside>

              {selectedItem !== null ? (
                <VisibleCardFrame
                  key={`${selectedItem.item_id}:${selectedItem.last_detector?.model ?? batch.detector.model}`}
                  batch={batch}
                  item={selectedItem}
                  itemIndex={selectedIndex ?? 0}
                  totalItems={batch.items.length}
                  activeProposalIndex={activeProposalIndex}
                  zoom={zoom}
                  onZoomChange={setZoom}
                  onProposalSelect={setActiveProposalIndex}
                  onPrevious={() => moveSelection(-1, false)}
                  onPreviousPending={() => moveSelection(-1, true)}
                  onNext={() => moveSelection(1, false)}
                  onNextPending={() => moveSelection(1, true)}
                  onRetry={() => void retryBatch()}
                  onRedetect={redetectFrame}
                  onSaveReview={saveReview}
                  saveBusy={busy}
                  readOnly={batch.status === "completed"}
                />
              ) : null}
              <BatchProgress batch={batch} />
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}

function BatchProgress({ batch }: { batch: VisibleCardReviewBatch }) {
  const pendingCount = batch.items.filter(
    (item) => item.review?.status !== "reviewed",
  ).length;
  const reviewedCount = batch.items.length - pendingCount;

  return (
    <aside
      className={styles.visibleCardBatchProgress}
      aria-label="Batch progress"
    >
      <p className={styles.statusLabel}>Batch progress</p>
      <p className={styles.visibleCardProgressMessage}>{batchMessage(batch)}</p>
      <dl className={`${styles.detailStats} ${styles.visibleCardBatchStats}`}>
        <Stat
          label="Frames"
          value={`${batch.progress.frames_extracted}/${batch.progress.total_items}`}
        />
        <Stat
          label="Reviewed"
          value={`${reviewedCount}/${batch.items.length}`}
        />
        <Stat label="Pending" value={String(pendingCount)} />
        <Stat label="Detector" value={batch.detector.bundle_id} />
      </dl>
    </aside>
  );
}

function VisibleCardFrame({
  batch,
  item,
  itemIndex,
  totalItems,
  activeProposalIndex,
  zoom,
  onZoomChange,
  onProposalSelect,
  onPrevious,
  onPreviousPending,
  onNext,
  onNextPending,
  onRetry,
  onRedetect,
  onSaveReview,
  saveBusy,
  readOnly,
}: {
  batch: VisibleCardReviewBatch;
  item: BatchItem;
  itemIndex: number;
  totalItems: number;
  activeProposalIndex: number | null;
  zoom: number;
  onZoomChange: (value: number) => void;
  onProposalSelect: (value: number | null) => void;
  onPrevious: () => void;
  onPreviousPending: () => void;
  onNext: () => void;
  onNextPending: () => void;
  onRetry: () => void;
  onRedetect: (itemId: string, model: string | null) => Promise<void>;
  onSaveReview: (itemId: string, review: ReviewUpdate) => Promise<void>;
  saveBusy: boolean;
  readOnly: boolean;
}) {
  const source = item.source;
  const finder = item.finder;
  const proposals = finder?.proposals ?? [];
  const actions = (item.review?.actions ?? []) as ReviewAction[];
  const reviewedCards = actions
    .map((action) => action.reviewed_card)
    .filter((card): card is ReviewedCard => card !== null);
  const imagePath = source?.image_url;
  const interactionDisabled = readOnly || item.failure !== null;
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [outcomeMessage, setOutcomeMessage] = useState<string | null>(null);
  const [pendingSave, setPendingSave] = useState<ReviewUpdate | null>(null);
  const dragPoint = useRef<{
    polygonIndex: number;
    pointIndex: number;
    pointerId: number;
  } | null>(null);
  const [detectorModel, setDetectorModel] = useState(
    item.last_detector?.model ?? batch.detector.model,
  );
  const [rawResultOpen, setRawResultOpen] = useState(false);
  const rawResultButtonRef = useRef<HTMLButtonElement>(null);

  function currentReview(changes: {
    status?: ReviewUpdate["status"];
    decision?: ReviewUpdate["decision"];
    emptyFrame?: boolean;
    failureTags?: string[];
    actions?: ReviewAction[];
  }): ReviewUpdate {
    return {
      status: changes.status ?? "in_progress",
      decision: changes.decision ?? item.review?.decision ?? "GOOD",
      empty_frame: changes.emptyFrame ?? item.review?.empty_frame ?? false,
      failure_tags: [
        ...(changes.failureTags ?? item.review?.failure_tags ?? []),
      ],
      actions: changes.actions ?? actions,
      reviewer: item.review?.reviewer ?? "web-operator",
    };
  }

  async function save(next: ReviewUpdate): Promise<boolean> {
    setPendingSave(next);
    try {
      await onSaveReview(item.item_id, next);
      setPendingSave(null);
      setOutcomeMessage(null);
      return true;
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        setPendingSave(null);
      }
      return false;
    }
  }

  function saveProposalAction(
    proposal: Proposal,
    action: "accepted" | "removed",
  ) {
    if (readOnly) {
      return;
    }
    const cardId = cardIdForProposal(proposal.proposal_index);
    const nextActions = actions.filter(
      (existing) => existing.card_id !== cardId,
    );
    nextActions.push({
      card_id: cardId,
      action,
      proposal_index: proposal.proposal_index,
      reviewed_card:
        action === "accepted"
          ? reviewedCardFromProposal(proposal, cardId)
          : null,
    });
    void save(
      currentReview({
        decision: "GOOD",
        emptyFrame: false,
        actions: nextActions,
      }),
    );
  }

  function openCorrection(proposal: Proposal) {
    if (readOnly) {
      return;
    }
    const existing = actions.find(
      (action) => action.proposal_index === proposal.proposal_index,
    );
    const card =
      existing?.reviewed_card ??
      reviewedCardFromProposal(
        proposal,
        cardIdForProposal(proposal.proposal_index),
      );
    setEditorError(null);
    setEditor({
      action: "reshaped",
      cardId: card.card_id,
      proposalIndex: proposal.proposal_index,
      polygons: card.visible_region.polygons.map((polygon) => [...polygon]),
      polygonIndex: 0,
      selectedPointIndex: null,
      side: card.side,
      usable: card.identity_usability.usable,
      reason: card.identity_usability.reason,
      failureTags: [...card.failure_tags],
    });
  }

  function openAddCard() {
    if (readOnly) {
      return;
    }
    setEditorError(null);
    setEditor({
      action: "added",
      cardId: nextAddedCardId(actions),
      proposalIndex: null,
      polygons: [[]],
      polygonIndex: 0,
      selectedPointIndex: null,
      side: "unknown",
      usable: true,
      reason: "sufficient_identity_evidence",
      failureTags: [],
    });
  }

  function handleCanvasClick(event: MouseEvent<SVGSVGElement>) {
    if (editor === null || source === null) {
      return;
    }
    const point = pointFromClientPosition(
      event.clientX,
      event.clientY,
      event.currentTarget,
    );
    if (point === null) {
      return;
    }
    setEditor((current) => {
      if (current === null) {
        return current;
      }
      const polygons = current.polygons.map((polygon) => [...polygon]);
      polygons[current.polygonIndex] = insertPointIntoPolygon(
        polygons[current.polygonIndex],
        point,
      );
      return {
        ...current,
        polygons,
        selectedPointIndex: null,
      };
    });
  }

  function handlePointPointerDown(
    event: PointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) {
    event.preventDefault();
    event.stopPropagation();
    dragPoint.current = {
      polygonIndex,
      pointIndex,
      pointerId: event.pointerId,
    };
    if (typeof event.currentTarget.setPointerCapture === "function") {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    setEditor((current) =>
      current === null
        ? current
        : { ...current, polygonIndex, selectedPointIndex: pointIndex },
    );
  }

  function handleCanvasPointerMove(event: PointerEvent<SVGSVGElement>) {
    const drag = dragPoint.current;
    if (drag === null || drag.pointerId !== event.pointerId) {
      return;
    }
    const point = pointFromClientPosition(
      event.clientX,
      event.clientY,
      event.currentTarget,
    );
    if (point === null) {
      return;
    }
    setEditor((current) => {
      if (
        current === null ||
        current.polygons[drag.polygonIndex] === undefined
      ) {
        return current;
      }
      const polygons = current.polygons.map((polygon) => [...polygon]);
      const polygon = polygons[drag.polygonIndex];
      if (polygon[drag.pointIndex] === undefined) {
        return current;
      }
      polygon[drag.pointIndex] = point;
      return { ...current, polygons };
    });
  }

  function stopPointDrag(event: PointerEvent<SVGSVGElement>) {
    if (dragPoint.current?.pointerId === event.pointerId) {
      dragPoint.current = null;
    }
  }

  function removeEditorPoint(polygonIndex: number, pointIndex: number) {
    setEditor((current) => {
      const polygon = current?.polygons[polygonIndex];
      if (
        current === null ||
        polygon === undefined ||
        polygon[pointIndex] === undefined
      ) {
        return current;
      }
      const polygons = current.polygons.map((value) => [...value]);
      polygons[polygonIndex] = polygon.filter(
        (_, index) => index !== pointIndex,
      );
      return {
        ...current,
        polygons,
        polygonIndex,
        selectedPointIndex: null,
      };
    });
  }

  async function saveEditor() {
    if (editor === null) {
      return;
    }
    const geometryError = validateEditorPolygons(editor.polygons);
    if (geometryError !== null) {
      setEditorError(geometryError);
      return;
    }
    const reviewedCard: ReviewedCard = {
      card_id: editor.cardId,
      visible_region: { polygons: editor.polygons },
      derived_box: deriveBox(editor.polygons),
      identity_usability: {
        usable: editor.usable,
        reason: editor.usable ? "sufficient_identity_evidence" : editor.reason,
      },
      side: editor.side,
      failure_tags: editor.failureTags,
    };
    const nextActions = actions.filter(
      (action) => action.card_id !== editor.cardId,
    );
    nextActions.push({
      card_id: editor.cardId,
      action: editor.action,
      proposal_index: editor.proposalIndex,
      reviewed_card: reviewedCard,
    });
    if (
      await save(
        currentReview({
          decision: "GOOD",
          emptyFrame: false,
          actions: nextActions,
        }),
      )
    ) {
      setEditor(null);
      setEditorError(null);
    }
  }

  function saveOutcome(outcome: Outcome) {
    if (outcome === "usable") {
      const proposalIndices = new Set(
        actions
          .filter((action) => action.proposal_index !== null)
          .map((action) => action.proposal_index),
      );
      if (
        proposalIndices.size !== proposals.length ||
        actions.every((action) => action.reviewed_card === null)
      ) {
        setOutcomeMessage(
          "Act on every finder proposal and keep at least one visible card before marking this frame usable.",
        );
        return;
      }
      void save(
        currentReview({
          status: "reviewed",
          decision: "GOOD",
          emptyFrame: false,
        }),
      );
      return;
    }
    void save(
      currentReview({
        status: "reviewed",
        decision: "BAD",
        emptyFrame: outcome === "empty",
        actions: [],
      }),
    );
  }

  return (
    <section className={styles.visibleCardFramePanel}>
      <header className={styles.visibleCardFrameHeader}>
        <div>
          <p className={styles.statusLabel}>
            Frame {itemIndex + 1} of {totalItems}
          </p>
          <h2>{formatSeconds(item.event_time_s)} · exact event frame</h2>
          <p className={styles.detailMetaLine}>
            Frame index {item.frame_index ?? "not extracted"} · offset{" "}
            {item.target_offset_ms} ms
          </p>
        </div>
        <StatusBadge value={item.review?.status ?? item.status} />
      </header>

      <div
        className={styles.visibleCardNavigation}
        aria-label="Frame navigation"
      >
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onPrevious}
        >
          Previous
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onPreviousPending}
        >
          Previous pending
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onNextPending}
        >
          Next pending
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onNext}
        >
          Next
        </button>
      </div>

      {item.failure !== null ? (
        <div className={styles.detailBlocker}>
          <p>{item.failure.message}</p>
          <div className={styles.visibleCardFailureActions}>
            {item.failure.retryable ? (
              <button
                className={styles.inlineAction}
                type="button"
                onClick={onRetry}
              >
                Retry this item
              </button>
            ) : null}
            {finder?.raw_response !== null &&
            finder?.raw_response !== undefined ? (
              <button
                ref={rawResultButtonRef}
                className={styles.inlineAction}
                type="button"
                aria-haspopup="dialog"
                onClick={() => setRawResultOpen(true)}
              >
                Show raw result
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {source !== null && imagePath !== undefined ? (
        <>
          <section
            className={styles.visibleCardDetectorControls}
            aria-label="Frame detector"
          >
            <div>
              <p className={styles.statusLabel}>Frame detector</p>
              <p className={styles.visibleCardDetectorHelp}>
                Re-detection replaces this frame&apos;s finder result and resets
                its review. Other frames are unchanged.
              </p>
              <p className={styles.visibleCardDetectorLastRun}>
                Last detector:{" "}
                {item.last_detector?.bundle_id ?? "Not available"}
              </p>
            </div>
            <div className={styles.visibleCardDetectorForm}>
              <label>
                Detector model
                <input
                  value={detectorModel}
                  onChange={(event) => setDetectorModel(event.target.value)}
                  disabled={readOnly || saveBusy}
                  list="visible-card-detector-models"
                />
              </label>
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() =>
                  void onRedetect(item.item_id, detectorModel.trim() || null)
                }
                disabled={
                  readOnly ||
                  saveBusy ||
                  detectorModel.trim() === "" ||
                  batch.status !== "ready"
                }
              >
                {saveBusy ? "Re-detecting…" : "Re-detect frame"}
              </button>
            </div>
            <datalist id="visible-card-detector-models">
              <option value={batch.detector.model} />
            </datalist>
          </section>
          <div className={styles.visibleCardCanvasToolbar}>
            <span className={styles.cardEventSaveStatus}>
              {item.failure !== null
                ? "Display-only finder output; retry the failed item to review it."
                : saveBusy
                  ? "Saving review…"
                  : "Finder proposals are suggestions."}
            </span>
            <div className={styles.visibleCardZoomControls}>
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => onZoomChange(1)}
                aria-pressed={zoom === 1}
              >
                Fit
              </button>
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => onZoomChange(Math.max(1, zoom - 0.25))}
                disabled={zoom === 1}
              >
                −
              </button>
              <span aria-label={`Zoom ${Math.round(zoom * 100)} percent`}>
                {Math.round(zoom * 100)}%
              </span>
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => onZoomChange(Math.min(3, zoom + 0.25))}
                disabled={zoom === 3}
              >
                +
              </button>
            </div>
          </div>
          <div
            className={styles.visibleCardCanvasViewport}
            style={{ aspectRatio: `${source.width} / ${source.height}` }}
          >
            <div
              className={styles.visibleCardCanvasInner}
              style={{ width: `${zoom * 100}%` }}
            >
              <img
                className={styles.visibleCardCanvasImage}
                src={imagePath}
                width={source.width}
                height={source.height}
                alt={`Exact event source frame at ${formatSeconds(item.event_time_s)}`}
              />
              <svg
                className={styles.visibleCardOverlay}
                viewBox={`0 0 ${source.width} ${source.height}`}
                role="img"
                aria-label={`${proposals.length} finder proposal${proposals.length === 1 ? "" : "s"}`}
                onClick={handleCanvasClick}
                onPointerMove={handleCanvasPointerMove}
                onPointerUp={stopPointDrag}
                onPointerCancel={stopPointDrag}
                style={{ pointerEvents: editor === null ? "none" : "auto" }}
              >
                {proposals.map((proposal) => (
                  <ProposalOverlay
                    key={proposal.proposal_index}
                    proposal={proposal}
                    width={source.width}
                    height={source.height}
                    active={proposal.proposal_index === activeProposalIndex}
                  />
                ))}
                {reviewedCards.map((card) => (
                  <ReviewedOverlay
                    key={card.card_id}
                    card={card}
                    width={source.width}
                    height={source.height}
                  />
                ))}
                {editor?.polygons.map((polygon, index) => (
                  <EditorOverlay
                    key={`editor:${index}`}
                    polygon={polygon}
                    width={source.width}
                    height={source.height}
                    active={index === editor.polygonIndex}
                    selectedPointIndex={
                      index === editor.polygonIndex
                        ? editor.selectedPointIndex
                        : null
                    }
                    polygonIndex={index}
                    onPointPointerDown={handlePointPointerDown}
                    onPointClick={(pointIndex) =>
                      setEditor((current) =>
                        current === null
                          ? current
                          : {
                              ...current,
                              polygonIndex: index,
                              selectedPointIndex: pointIndex,
                            },
                      )
                    }
                    onPointFocus={(pointIndex) =>
                      setEditor((current) =>
                        current === null
                          ? current
                          : {
                              ...current,
                              polygonIndex: index,
                              selectedPointIndex: pointIndex,
                            },
                      )
                    }
                    onPointKeyDown={(event, pointIndex) => {
                      if (event.key === "Delete" || event.key === "Backspace") {
                        event.preventDefault();
                        removeEditorPoint(index, pointIndex);
                      }
                    }}
                  />
                ))}
              </svg>
            </div>
          </div>
          <FrameOutcomeControls
            review={item.review}
            message={outcomeMessage}
            onOutcome={saveOutcome}
            onFailureTags={(failureTags) =>
              void save(currentReview({ failureTags }))
            }
            disabled={interactionDisabled}
            onRetrySave={
              pendingSave === null ? undefined : () => void save(pendingSave)
            }
          />
          <ProposalList
            proposals={proposals}
            actions={actions}
            activeProposalIndex={activeProposalIndex}
            onProposalSelect={onProposalSelect}
            onAccept={(proposal) => saveProposalAction(proposal, "accepted")}
            onRemove={(proposal) => saveProposalAction(proposal, "removed")}
            onCorrect={openCorrection}
            disabled={interactionDisabled}
          />
          <button
            className={styles.primaryButton}
            type="button"
            onClick={openAddCard}
            disabled={interactionDisabled}
          >
            Add missed card
          </button>
          {editor !== null ? (
            <PolygonEditor
              editor={editor}
              error={editorError}
              onChange={setEditor}
              onCancel={() => setEditor(null)}
              onSave={() => void saveEditor()}
            />
          ) : null}
        </>
      ) : (
        <p className={styles.detailEmptyState}>
          {item.failure !== null
            ? "The source frame is not available for this failed item."
            : "The source frame is not available yet."}
        </p>
      )}
      <FinderDiagnostics finder={finder} />
      {item.failure === null &&
      finder?.raw_response !== null &&
      finder?.raw_response !== undefined ? (
        <button
          ref={rawResultButtonRef}
          className={styles.secondaryButton}
          type="button"
          aria-haspopup="dialog"
          onClick={() => setRawResultOpen(true)}
        >
          Show raw result
        </button>
      ) : null}
      <RawResultDialog
        item={item}
        rawResponse={finder?.raw_response ?? null}
        open={rawResultOpen}
        onClose={() => setRawResultOpen(false)}
        openerRef={rawResultButtonRef}
      />

      <details className={styles.visibleCardDiagnostics}>
        <summary>Source and finder lineage</summary>
        <dl className={styles.detailMetadata}>
          <Stat label="Item ID" value={item.item_id} />
          <Stat label="Event ID" value={item.event_id} />
          <Stat label="Event index" value={String(item.event_index)} />
          <Stat
            label="Source asset"
            value={source?.source_asset_id ?? "Not available"}
          />
          <Stat
            label="Lineage group"
            value={source?.source_lineage_group ?? "Not available"}
          />
          <Stat
            label="Frame digest"
            value={source?.frame_sha256 ?? "Not available"}
          />
          <Stat
            label="Finder request"
            value={item.finder?.request_digest ?? "Not available"}
          />
          <Stat
            label="Finder result"
            value={item.finder?.result_digest ?? "Not available"}
          />
          <Stat
            label="Prediction"
            value={item.finder?.prediction_sha256 ?? "Not available"}
          />
          <Stat
            label="Last detector"
            value={
              item.last_detector == null
                ? "Not available"
                : `${item.last_detector.bundle_id} · ${item.last_detector.bundle_digest}`
            }
          />
        </dl>
      </details>
    </section>
  );
}

function FrameOutcomeControls({
  review,
  message,
  onOutcome,
  onFailureTags,
  onRetrySave,
  disabled,
}: {
  review: BatchItem["review"];
  message: string | null;
  onOutcome: (outcome: Outcome) => void;
  onFailureTags: (failureTags: string[]) => void;
  onRetrySave: (() => void) | undefined;
  disabled: boolean;
}) {
  return (
    <section
      className={styles.visibleCardReviewControls}
      aria-label="Frame outcome"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Frame outcome</p>
          <h2>What does this frame show?</h2>
        </div>
      </div>
      <div className={styles.visibleCardOutcomeButtons}>
        <button
          className={styles.primaryButton}
          type="button"
          aria-pressed={
            review?.decision === "GOOD" && review.empty_frame === false
          }
          onClick={() => onOutcome("usable")}
          disabled={disabled}
        >
          Usable with visible cards
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          aria-pressed={
            review?.decision === "BAD" && review.empty_frame === true
          }
          onClick={() => onOutcome("empty")}
          disabled={disabled}
        >
          Reviewed empty frame
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          aria-pressed={
            review?.decision === "BAD" && review.empty_frame === false
          }
          onClick={() => onOutcome("unusable")}
          disabled={disabled}
        >
          Unusable frame
        </button>
      </div>
      {message !== null ? (
        <p className={styles.inlineFormError}>{message}</p>
      ) : null}
      {onRetrySave !== undefined ? (
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onRetrySave}
          disabled={disabled}
        >
          Retry last save
        </button>
      ) : null}
      <fieldset className={styles.visibleCardFailureTags}>
        <legend>Frame failure tags</legend>
        {FAILURE_TAGS.map((tag) => (
          <label key={tag}>
            <input
              type="checkbox"
              checked={review?.failure_tags.includes(tag) ?? false}
              disabled={disabled}
              onChange={(event) => {
                const failureTags = review?.failure_tags ?? [];
                onFailureTags(
                  event.target.checked
                    ? [...failureTags, tag]
                    : failureTags.filter((value) => value !== tag),
                );
              }}
            />
            {formatIdentifier(tag)}
          </label>
        ))}
      </fieldset>
      <p className={styles.visibleCardEditorHelp}>
        Mark only visible card pixels. Exclude hidden pixels, an occluding card,
        a human hand, and the background.
      </p>
    </section>
  );
}

function ProposalList({
  proposals,
  actions,
  activeProposalIndex,
  onProposalSelect,
  onAccept,
  onCorrect,
  onRemove,
  disabled,
}: {
  proposals: Proposal[];
  actions: ReviewAction[];
  activeProposalIndex: number | null;
  onProposalSelect: (value: number | null) => void;
  onAccept: (proposal: Proposal) => void;
  onCorrect: (proposal: Proposal) => void;
  onRemove: (proposal: Proposal) => void;
  disabled: boolean;
}) {
  return (
    <section
      className={styles.visibleCardProposalList}
      aria-label="Finder proposals"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Finder output</p>
          <h2>Proposal overlays</h2>
        </div>
        <span className={styles.countLabel}>{proposals.length}</span>
      </div>
      {proposals.length === 0 ? (
        <p className={styles.detailEmptyState}>
          The finder returned no proposals. Review this frame as empty or add a
          missed card in the next phase.
        </p>
      ) : (
        <ol className={styles.visibleCardProposalItems}>
          {proposals.map((proposal) => (
            <li key={proposal.proposal_index}>
              <div className={styles.visibleCardProposalRow}>
                <button
                  className={styles.visibleCardProposalButton}
                  type="button"
                  aria-pressed={activeProposalIndex === proposal.proposal_index}
                  disabled={disabled}
                  onClick={() =>
                    onProposalSelect(
                      activeProposalIndex === proposal.proposal_index
                        ? null
                        : proposal.proposal_index,
                    )
                  }
                >
                  <span className={styles.visibleCardProposalSwatch} />
                  <span>
                    <strong>Proposal {proposal.proposal_index + 1}</strong>
                    <small>
                      {proposal.label} · {formatIdentifier(proposal.side)}
                    </small>
                  </span>
                </button>
                <div className={styles.visibleCardActionButtons}>
                  {actions.find(
                    (action) =>
                      action.proposal_index === proposal.proposal_index,
                  )?.action === "removed" ? (
                    <span className={styles.countLabel}>Removed</span>
                  ) : null}
                  <button
                    className={styles.inlineAction}
                    type="button"
                    disabled={disabled}
                    onClick={() => onAccept(proposal)}
                  >
                    Accept proposal {proposal.proposal_index + 1}
                  </button>
                  <button
                    className={styles.inlineAction}
                    type="button"
                    disabled={disabled}
                    onClick={() => onCorrect(proposal)}
                  >
                    Correct proposal {proposal.proposal_index + 1}
                  </button>
                  <button
                    className={styles.inlineAction}
                    type="button"
                    disabled={disabled}
                    onClick={() => onRemove(proposal)}
                  >
                    Remove proposal {proposal.proposal_index + 1}
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function FinderDiagnostics({ finder }: { finder: BatchItem["finder"] }) {
  const rawResponse = finder?.raw_response ?? null;
  const proposalsRecovered = finder?.proposals_recovered === true;
  if (rawResponse === null && !proposalsRecovered) {
    return null;
  }
  return (
    <details className={styles.visibleCardDiagnostics}>
      <summary>Finder diagnostics</summary>
      {proposalsRecovered ? (
        <p className={styles.detailBlocker}>
          The response was malformed, so the polygon was shown with a derived
          tight box for diagnosis. These proposals are display-only. Retry the
          item before using them for review.
        </p>
      ) : null}
      {rawResponse !== null ? (
        <>
          <p className={styles.detailLead}>
            Candidate JSON captured from the finder:
          </p>
          <pre className={styles.rawJson}>
            {formatFinderResponse(rawResponse)}
          </pre>
        </>
      ) : null}
    </details>
  );
}

function RawResultDialog({
  item,
  rawResponse,
  open,
  onClose,
  openerRef,
}: {
  item: BatchItem;
  rawResponse: Record<string, unknown> | null;
  open: boolean;
  onClose: () => void;
  openerRef: import("react").RefObject<HTMLButtonElement | null>;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (!open || rawResponse === null) {
      if (wasOpen.current) {
        wasOpen.current = false;
        openerRef.current?.focus();
      }
      return;
    }
    wasOpen.current = true;
    closeButtonRef.current?.focus();
    const dialog = dialogRef.current;
    if (dialog === null) {
      return;
    }
    const focusableSelector =
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(focusableSelector),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", handleKeyDown);
    return () => dialog.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open, openerRef, rawResponse]);

  if (!open || rawResponse === null) {
    return null;
  }

  return (
    <div
      className={styles.recordingDetailsOverlay}
      onClick={onClose}
      data-testid="raw-result-overlay"
    >
      <div
        ref={dialogRef}
        className={styles.recordingDetailsDialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="raw-result-dialog-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.recordingDetailsHeader}>
          <div>
            <p className={styles.statusLabel}>Finder diagnostics</p>
            <h2 id="raw-result-dialog-title">Gemini raw result</h2>
          </div>
          <button
            ref={closeButtonRef}
            className={styles.recordingDetailsClose}
            type="button"
            onClick={onClose}
            aria-label="Close raw result"
          >
            ×
          </button>
        </div>
        <p className={styles.detailLead}>
          Unmodified response for frame {formatSeconds(item.event_time_s)}.
          Candidate JSON is shown exactly as Gemini returned it.
        </p>
        <pre className={styles.rawJson}>
          {JSON.stringify(rawResponse, null, 2) ?? "null"}
        </pre>
      </div>
    </div>
  );
}

function formatFinderResponse(rawResponse: Record<string, unknown>): string {
  const candidates = rawResponse.candidates;
  const firstCandidate = Array.isArray(candidates) ? candidates[0] : null;
  const content = isRecord(firstCandidate) ? firstCandidate.content : null;
  const parts = isRecord(content) ? content.parts : null;
  const firstText = Array.isArray(parts)
    ? parts.find((part) => isRecord(part) && typeof part.text === "string")
    : undefined;
  if (isRecord(firstText) && typeof firstText.text === "string") {
    try {
      return (
        JSON.stringify(JSON.parse(firstText.text), null, 2) ?? firstText.text
      );
    } catch {
      return firstText.text;
    }
  }
  return JSON.stringify(rawResponse, null, 2) ?? "null";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function PolygonEditor({
  editor,
  error,
  onChange,
  onCancel,
  onSave,
}: {
  editor: EditorState;
  error: string | null;
  onChange: Dispatch<SetStateAction<EditorState | null>>;
  onCancel: () => void;
  onSave: () => void;
}) {
  function updateEditor(changes: Partial<EditorState>) {
    onChange((current) =>
      current === null ? current : { ...current, ...changes },
    );
  }

  function updatePolygon(index: number, polygon: Point[]) {
    onChange((current) => {
      if (current === null) {
        return current;
      }
      const polygons = current.polygons.map((value) => [...value]);
      polygons[index] = polygon;
      return {
        ...current,
        polygons,
        selectedPointIndex:
          current.polygonIndex === index &&
          (polygon.length === 0 ||
            (current.selectedPointIndex !== null &&
              current.selectedPointIndex >= polygon.length))
            ? null
            : current.selectedPointIndex,
      };
    });
  }

  function removePoint(index: number, pointIndex: number) {
    onChange((current) => {
      const polygon = current?.polygons[index];
      if (
        current === null ||
        polygon === undefined ||
        polygon[pointIndex] === undefined
      ) {
        return current;
      }
      const polygons = current.polygons.map((value) => [...value]);
      polygons[index] = polygon.filter((_, value) => value !== pointIndex);
      return {
        ...current,
        polygons,
        polygonIndex: index,
        selectedPointIndex: null,
      };
    });
  }

  function removeSelectedPoint() {
    if (editor.selectedPointIndex !== null) {
      removePoint(editor.polygonIndex, editor.selectedPointIndex);
    }
  }

  return (
    <section
      className={styles.visibleCardEditor}
      aria-label="Visible region editor"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Geometry editor</p>
          <h2>
            {editor.action === "added"
              ? "Add missed card"
              : "Correct visible region"}
          </h2>
        </div>
      </div>
      <p className={styles.visibleCardEditorHelp}>
        Click an empty part of the frame to add a point to the selected polygon.
        New points are inserted between the closest boundary edge. Click a point
        to select it, then drag it to move it. Press Delete or use the delete
        button to remove the selected point. Use at least three points with
        positive area.
      </p>
      <div className={styles.visibleCardEditorGrid}>
        <label>
          Side
          <select
            value={editor.side}
            onChange={(event) =>
              updateEditor({ side: event.target.value as EditorState["side"] })
            }
          >
            <option value="face_up">Face up</option>
            <option value="face_down">Face down</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label>
          Identity usability
          <select
            value={editor.usable ? "usable" : "unusable"}
            onChange={(event) =>
              updateEditor({
                usable: event.target.value === "usable",
                reason:
                  event.target.value === "usable"
                    ? "sufficient_identity_evidence"
                    : editor.reason === "sufficient_identity_evidence"
                      ? "insufficient_identity_evidence"
                      : editor.reason,
              })
            }
          >
            <option value="usable">Usable</option>
            <option value="unusable">Not usable</option>
          </select>
        </label>
        {!editor.usable ? (
          <label>
            Unusable reason
            <select
              value={editor.reason}
              onChange={(event) => updateEditor({ reason: event.target.value })}
            >
              <option value="insufficient_identity_evidence">
                Insufficient identity evidence
              </option>
              <option value="crop_contamination">Crop contamination</option>
              <option value="unknown_side">Unknown side</option>
              <option value="occluded">Occluded</option>
              <option value="other">Other</option>
            </select>
          </label>
        ) : null}
      </div>
      <fieldset className={styles.visibleCardFailureTags}>
        <legend>Failure tags</legend>
        {FAILURE_TAGS.map((tag) => (
          <label key={tag}>
            <input
              type="checkbox"
              checked={editor.failureTags.includes(tag)}
              onChange={(event) =>
                updateEditor({
                  failureTags: event.target.checked
                    ? [...editor.failureTags, tag]
                    : editor.failureTags.filter((value) => value !== tag),
                })
              }
            />
            {formatIdentifier(tag)}
          </label>
        ))}
      </fieldset>
      <ol className={styles.visibleCardPolygonList}>
        {editor.polygons.map((polygon, index) => (
          <li key={index}>
            <button
              className={styles.secondaryButton}
              type="button"
              aria-pressed={index === editor.polygonIndex}
              onClick={() =>
                updateEditor({ polygonIndex: index, selectedPointIndex: null })
              }
            >
              Polygon {index + 1} ({polygon.length} points)
            </button>
            <button
              className={styles.inlineAction}
              type="button"
              onClick={() => updatePolygon(index, [])}
            >
              Clear polygon
            </button>
            <button
              className={styles.inlineAction}
              type="button"
              disabled={polygon.length === 0}
              onClick={() => updatePolygon(index, polygon.slice(0, -1))}
            >
              Remove last point
            </button>
            {polygon.map((point, pointIndex) => (
              <button
                key={`${point.x}:${point.y}:${pointIndex}`}
                className={styles.inlineAction}
                type="button"
                aria-pressed={
                  index === editor.polygonIndex &&
                  pointIndex === editor.selectedPointIndex
                }
                onClick={() => {
                  updateEditor({
                    polygonIndex: index,
                    selectedPointIndex: pointIndex,
                  });
                }}
              >
                Point {pointIndex + 1} ({point.x}, {point.y})
              </button>
            ))}
            {editor.polygons.length > 1 ? (
              <button
                className={styles.inlineAction}
                type="button"
                onClick={() =>
                  onChange((current) => {
                    if (current === null) {
                      return current;
                    }
                    const polygons = current.polygons.filter(
                      (_, value) => value !== index,
                    );
                    return {
                      ...current,
                      polygons,
                      polygonIndex: Math.min(
                        current.polygonIndex,
                        polygons.length - 1,
                      ),
                      selectedPointIndex: null,
                    };
                  })
                }
              >
                Remove polygon
              </button>
            ) : null}
          </li>
        ))}
      </ol>
      <div className={styles.visibleCardEditorButtons}>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={editor.selectedPointIndex === null}
          onClick={removeSelectedPoint}
        >
          Delete selected point
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() =>
            onChange((current) =>
              current === null
                ? current
                : {
                    ...current,
                    polygons: [...current.polygons, []],
                    polygonIndex: current.polygons.length,
                    selectedPointIndex: null,
                  },
            )
          }
        >
          Add polygon
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button className={styles.primaryButton} type="button" onClick={onSave}>
          Save {editor.action === "added" ? "card" : "correction"}
        </button>
      </div>
      {error !== null ? (
        <p className={styles.inlineFormError}>{error}</p>
      ) : null}
    </section>
  );
}

function ProposalOverlay({
  proposal,
  width,
  height,
  active,
}: {
  proposal: Proposal;
  width: number;
  height: number;
  active: boolean;
}) {
  const points = proposal.polygon
    .map((point) => `${(point.x * width) / 1000},${(point.y * height) / 1000}`)
    .join(" ");
  const box = proposal.box_2d;
  return (
    <g data-active={active}>
      <polygon className={styles.visibleCardProposalPolygon} points={points} />
      <rect
        className={styles.visibleCardProposalBox}
        x={(box.x_min * width) / 1000}
        y={(box.y_min * height) / 1000}
        width={((box.x_max - box.x_min) * width) / 1000}
        height={((box.y_max - box.y_min) * height) / 1000}
      />
    </g>
  );
}

function ReviewedOverlay({
  card,
  width,
  height,
}: {
  card: ReviewedCard;
  width: number;
  height: number;
}) {
  const polygons = card.visible_region.polygons.map((polygon) =>
    polygon
      .map(
        (point) => `${(point.x * width) / 1000},${(point.y * height) / 1000}`,
      )
      .join(" "),
  );
  const box = card.derived_box;
  return (
    <g className={styles.visibleCardReviewedGeometry}>
      {polygons.map((points, index) => (
        <polygon key={`${card.card_id}:${index}`} points={points} />
      ))}
      <rect
        x={(box.x_min * width) / 1000}
        y={(box.y_min * height) / 1000}
        width={((box.x_max - box.x_min) * width) / 1000}
        height={((box.y_max - box.y_min) * height) / 1000}
      />
    </g>
  );
}

function EditorOverlay({
  polygon,
  width,
  height,
  active,
  selectedPointIndex,
  polygonIndex,
  onPointPointerDown,
  onPointClick,
  onPointFocus,
  onPointKeyDown,
}: {
  polygon: Point[];
  width: number;
  height: number;
  active: boolean;
  selectedPointIndex: number | null;
  polygonIndex: number;
  onPointPointerDown: (
    event: PointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
  onPointClick: (pointIndex: number) => void;
  onPointFocus: (pointIndex: number) => void;
  onPointKeyDown: (
    event: ReactKeyboardEvent<SVGCircleElement>,
    pointIndex: number,
  ) => void;
}) {
  const points = polygon
    .map((point) => `${(point.x * width) / 1000},${(point.y * height) / 1000}`)
    .join(" ");
  return (
    <g className={styles.visibleCardEditorGeometry} data-active={active}>
      {polygon.length >= 3 ? <polygon points={points} /> : null}
      {polygon.map((point, index) => (
        <circle
          key={`${point.x}:${point.y}:${index}`}
          className={styles.visibleCardEditorPoint}
          cx={(point.x * width) / 1000}
          cy={(point.y * height) / 1000}
          r={Math.max(width, height) / 80}
          data-selected={index === selectedPointIndex}
          role="button"
          tabIndex={0}
          aria-label={`Polygon ${polygonIndex + 1}, point ${index + 1} at ${point.x}, ${point.y}`}
          aria-pressed={index === selectedPointIndex}
          onPointerDown={(event) =>
            onPointPointerDown(event, polygonIndex, index)
          }
          onClick={(event) => {
            event.stopPropagation();
            onPointClick(index);
          }}
          onFocus={() => onPointFocus(index)}
          onKeyDown={(event) => onPointKeyDown(event, index)}
        />
      ))}
    </g>
  );
}

function reviewedCardFromProposal(
  proposal: Proposal,
  cardId: string,
): ReviewedCard {
  return {
    card_id: cardId,
    visible_region: { polygons: [[...proposal.polygon]] },
    derived_box: proposal.box_2d,
    identity_usability: {
      usable: true,
      reason: "sufficient_identity_evidence",
    },
    side: proposal.side,
    failure_tags: [],
  };
}

function cardIdForProposal(proposalIndex: number): string {
  return `card-${proposalIndex + 1}`;
}

function nextAddedCardId(actions: ReviewAction[]): string {
  const used = new Set(actions.map((action) => action.card_id));
  let index = 1;
  while (used.has(`card-added-${index}`)) {
    index += 1;
  }
  return `card-added-${index}`;
}

function deriveBox(polygons: Point[][]): ReviewedCard["derived_box"] {
  const points = polygons.flat();
  return {
    y_min: Math.min(...points.map((point) => point.y)),
    x_min: Math.min(...points.map((point) => point.x)),
    y_max: Math.max(...points.map((point) => point.y)),
    x_max: Math.max(...points.map((point) => point.x)),
  };
}

function validateEditorPolygons(polygons: Point[][]): string | null {
  if (polygons.length === 0 || polygons.some((polygon) => polygon.length < 3)) {
    return "Each visible region polygon needs at least three points.";
  }
  if (
    polygons.some((polygon) =>
      polygon.some(
        (point) =>
          point.x < 0 || point.x > 1000 || point.y < 0 || point.y > 1000,
      ),
    )
  ) {
    return "Polygon points must stay inside the source frame.";
  }
  if (polygons.some((polygon) => polygonArea(polygon) <= 0)) {
    return "Each visible region polygon needs positive area.";
  }
  return null;
}

function pointFromClientPosition(
  clientX: number,
  clientY: number,
  element: SVGSVGElement,
): Point | null {
  const bounds = element.getBoundingClientRect();
  if (bounds.width <= 0 || bounds.height <= 0) {
    return null;
  }
  return {
    x: clampNormalized(
      Math.round(((clientX - bounds.left) / bounds.width) * 1000),
    ),
    y: clampNormalized(
      Math.round(((clientY - bounds.top) / bounds.height) * 1000),
    ),
  };
}

export function insertPointIntoPolygon(
  polygon: Point[],
  point: Point,
): Point[] {
  if (polygon.length < 3) {
    return [...polygon, point];
  }

  let closestEdgeIndex = 0;
  let closestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < polygon.length; index += 1) {
    const next = polygon[(index + 1) % polygon.length];
    const distance = distanceToSegmentSquared(point, polygon[index], next);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestEdgeIndex = index;
    }
  }

  const insertionIndex = closestEdgeIndex + 1;
  return [
    ...polygon.slice(0, insertionIndex),
    point,
    ...polygon.slice(insertionIndex),
  ];
}

function distanceToSegmentSquared(
  point: Point,
  start: Point,
  end: Point,
): number {
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  const lengthSquared = deltaX * deltaX + deltaY * deltaY;
  if (lengthSquared === 0) {
    return distanceSquared(point, start);
  }
  const projection = Math.max(
    0,
    Math.min(
      1,
      ((point.x - start.x) * deltaX + (point.y - start.y) * deltaY) /
        lengthSquared,
    ),
  );
  return distanceSquared(point, {
    x: start.x + projection * deltaX,
    y: start.y + projection * deltaY,
  });
}

function distanceSquared(first: Point, second: Point): number {
  const deltaX = first.x - second.x;
  const deltaY = first.y - second.y;
  return deltaX * deltaX + deltaY * deltaY;
}

function polygonArea(points: Point[]): number {
  return Math.abs(
    points.reduce((area, point, index) => {
      const next = points[(index + 1) % points.length];
      return area + point.x * next.y - next.x * point.y;
    }, 0) / 2,
  );
}

function clampNormalized(value: number): number {
  return Math.max(0, Math.min(1000, value));
}

function selectedIndexFor(
  batch: VisibleCardReviewBatch | null,
  itemId: string | null,
): number | null {
  if (batch === null) {
    return null;
  }
  const index =
    itemId === null
      ? -1
      : batch.items.findIndex((item) => item.item_id === itemId);
  return index >= 0 ? index : null;
}

function effectiveItemId(
  batch: VisibleCardReviewBatch | null,
  itemId: string | null,
): string | null {
  if (batch === null || batch.items.length === 0) {
    return itemId;
  }
  if (itemId !== null && batch.items.some((item) => item.item_id === itemId)) {
    return itemId;
  }
  return (
    batch.items.find((item) => item.review?.status !== "reviewed") ??
    batch.items[0]
  ).item_id;
}

function replaceSelectedItem(itemId: string, batchId: string) {
  const params = new URLSearchParams(window.location.search);
  params.set("item", itemId);
  window.history.replaceState(
    window.history.state,
    "",
    `${visibleCardReviewBatchPagePath(batchId)}?${params.toString()}`,
  );
}

function batchMessage(batch: VisibleCardReviewBatch): string {
  if (batch.status === "completed") {
    return "Review complete — published immutable review is ready for freeze use.";
  }
  if (batch.status === "ready") {
    return `Ready to review — ${batch.progress.finder_completed} of ${batch.progress.total_items} complete.`;
  }
  if (batch.status === "failed") {
    return "Batch failed — retry unavailable items.";
  }
  return `Preparing frames — ${batch.progress.frames_extracted} of ${batch.progress.total_items}.`;
}

function formatItemStatus(item: BatchItem): string {
  if (item.failure !== null) {
    return "Failed · retry available";
  }
  return formatIdentifier(item.review?.status ?? item.status);
}

function formatSeconds(value: number): string {
  return `${value.toFixed(3)} s`;
}

function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function recordingPagePath(recordingId: string | undefined): string {
  return recordingId === undefined
    ? "/"
    : `/recordings/${encodeURIComponent(recordingId)}`;
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd title={value}>{value}</dd>
    </div>
  );
}

function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}
