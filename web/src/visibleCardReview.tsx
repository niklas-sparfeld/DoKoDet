import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  visibleCardReviewBatchPagePath,
  type VisibleCardReviewBatch,
} from "./api/client";
import styles from "./App.module.css";

type BatchItem = VisibleCardReviewBatch["items"][number];
type Proposal = NonNullable<BatchItem["finder"]>["proposals"][number];
type ReviewedCard = NonNullable<
  NonNullable<BatchItem["review"]>["actions"][number]["reviewed_card"]
>;

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

  const pendingCount =
    batch?.items.filter((item) => item.review?.status !== "reviewed").length ??
    0;
  const reviewedCount = (batch?.items.length ?? 0) - pendingCount;

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
            <div>
              <p className={styles.statusLabel}>Batch progress</p>
              <p className={styles.visibleCardProgressMessage}>
                {batchMessage(batch)}
              </p>
            </div>
            <dl className={styles.detailStats}>
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
          </section>

          {batch.status === "preparing" ? (
            <p className={styles.visibleCardReviewMessage} aria-live="polite">
              The review workspace will open when finder results are complete.
            </p>
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
                />
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </main>
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
}) {
  const source = item.source;
  const proposals = item.finder?.proposals ?? [];
  const reviewedCards = (item.review?.actions ?? [])
    .map((action) => action.reviewed_card)
    .filter((card): card is ReviewedCard => card !== null);
  const imagePath = source?.image_url;
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
          {item.failure.retryable ? (
            <button
              className={styles.inlineAction}
              type="button"
              onClick={onRetry}
            >
              Retry this item
            </button>
          ) : null}
        </div>
      ) : source !== null && imagePath !== undefined ? (
        <>
          <div className={styles.visibleCardCanvasToolbar}>
            <span className={styles.cardEventSaveStatus}>
              Finder proposals are suggestions.
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
          <div className={styles.visibleCardCanvasViewport}>
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
              </svg>
            </div>
          </div>
          <ProposalList
            proposals={proposals}
            activeProposalIndex={activeProposalIndex}
            onProposalSelect={onProposalSelect}
          />
        </>
      ) : (
        <p className={styles.detailEmptyState}>
          The source frame is not available yet.
        </p>
      )}

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
            label="Detector"
            value={`${batch.detector.bundle_id} · ${batch.detector.bundle_digest}`}
          />
        </dl>
      </details>
    </section>
  );
}

function ProposalList({
  proposals,
  activeProposalIndex,
  onProposalSelect,
}: {
  proposals: Proposal[];
  activeProposalIndex: number | null;
  onProposalSelect: (value: number | null) => void;
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
              <button
                className={styles.visibleCardProposalButton}
                type="button"
                aria-pressed={activeProposalIndex === proposal.proposal_index}
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
            </li>
          ))}
        </ol>
      )}
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
