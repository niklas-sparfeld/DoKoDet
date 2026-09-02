import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  identityReviewBatchPagePath,
  type IdentityReviewBatch,
  type IdentityReviewPreview,
  type IdentityReviewReadiness,
} from "./api/client";
import styles from "./App.module.css";

type IdentityItem = IdentityReviewBatch["items"][number];
type Point = { x: number; y: number };
type Box = { x_min: number; y_min: number; x_max: number; y_max: number };

export function IdentityReviewSection({
  recordingId,
  review,
  error,
  onChanged,
}: {
  recordingId: string;
  review: IdentityReviewReadiness | null;
  error: string | null;
  onChanged: (value: IdentityReviewReadiness) => void;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [preview, setPreview] = useState<IdentityReviewPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function loadPreview() {
    setBusy(true);
    setActionError(null);
    try {
      setPreview(await client.previewIdentityReview(recordingId));
    } catch (reason: unknown) {
      setActionError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createBatch() {
    if (
      review === null ||
      preview === null ||
      !preview.validation.valid ||
      preview.request_digest === null
    ) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const batch = await client.createIdentityReviewBatch(recordingId, {
        preview_digest: preview.preview_digest,
        request_digest: preview.request_digest,
      });
      onChanged({
        ...review,
        state: "preparing",
        message: "Preparing frozen identity crops and proposals.",
        blocker: null,
        selected_card_count: batch.coverage.identity_usable_card_count,
        batch,
        preview_digest: preview.preview_digest,
      });
      setPreview(null);
    } catch (reason: unknown) {
      setActionError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  async function retryBatch() {
    if (review?.batch === null || review?.batch === undefined) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const batch = await client.retryIdentityReviewBatch(
        review.batch.batch_id,
      );
      onChanged({
        ...review,
        state: "preparing",
        message: "Retrying identity crop and proposal preparation.",
        blocker: null,
        batch,
      });
    } catch (reason: unknown) {
      setActionError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  const batch = review?.batch ?? null;
  const canRetry =
    batch !== null && batch.failures.some((failure) => failure.retryable);

  return (
    <section id="identity-review" className={styles.detailPanel}>
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Annotation workspace</p>
          <h2>Visual card identities</h2>
        </div>
        <IdentityStatusBadge value={review?.state ?? "loading"} />
      </div>
      <p className={styles.detailLead}>
        Review the visual card identity in each identity-usable crop. Classifier
        results are proposals only; the human decision is added in the next
        milestone.
      </p>
      {error !== null ? (
        <p className={styles.errorMessage} role="alert">
          {error}
        </p>
      ) : null}
      {review === null ? (
        <p className={styles.detailEmptyState} aria-live="polite">
          Loading identity review readiness…
        </p>
      ) : (
        <>
          <p className={styles.identityReviewMessage} aria-live="polite">
            {review.message}
          </p>
          <dl className={styles.detailStats}>
            <IdentityStat
              label="Identity-usable cards"
              value={String(review.selected_card_count)}
            />
            <IdentityStat
              label="Batch"
              value={batch === null ? "Not created" : batch.status}
            />
            <IdentityStat
              label="Crop policy"
              value={batch?.crop_policy.policy_id ?? "raw rectangular"}
            />
          </dl>
          {review.blocker !== null ? (
            <div className={styles.identityFailure} role="alert">
              <strong>{formatIdentifier(review.blocker.code)}</strong>
              <p>{review.blocker.message}</p>
            </div>
          ) : null}
          {batch !== null ? (
            <div className={styles.identitySummaryActions}>
              <a
                className={styles.recordingLink}
                href={identityReviewBatchPagePath(batch.batch_id)}
              >
                Open identity review workspace
              </a>
              {canRetry ? (
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={() => void retryBatch()}
                  disabled={busy}
                >
                  {busy ? "Retrying…" : "Retry failed preparation"}
                </button>
              ) : null}
            </div>
          ) : null}
          {review.state === "ready" && batch === null ? (
            <button
              className={styles.primaryButton}
              type="button"
              onClick={() => void loadPreview()}
              disabled={busy}
            >
              {busy ? "Loading preview…" : "Preview identity batch"}
            </button>
          ) : null}
          {preview !== null ? (
            <div className={styles.identityPreview} aria-live="polite">
              <p className={styles.statusLabel}>Creation preview</p>
              <p>
                {preview.selected_card_count} identity-usable reviewed card
                {preview.selected_card_count === 1 ? "" : "s"} will be copied
                into frozen crops.
              </p>
              <p className={styles.detailMetaLine}>
                Source {preview.source_asset_id} ·{" "}
                {preview.source_lineage_group}
              </p>
              {!preview.validation.valid ? (
                <IdentityFailureList failures={preview.validation.blockers} />
              ) : (
                <button
                  className={styles.primaryButton}
                  type="button"
                  onClick={() => void createBatch()}
                  disabled={busy}
                >
                  {busy ? "Starting…" : "Create identity batch"}
                </button>
              )}
            </div>
          ) : null}
          {batch?.progress !== undefined ? (
            <dl className={styles.identityProgress}>
              <IdentityStat
                label="Crops"
                value={`${batch.progress.crops_materialized}/${batch.progress.total_items}`}
              />
              <IdentityStat
                label="Proposals"
                value={`${batch.progress.proposals_completed}/${batch.progress.total_items}`}
              />
              <IdentityStat
                label="Failed items"
                value={String(batch.progress.failed_items)}
              />
              <IdentityStat
                label="Phase"
                value={formatIdentifier(batch.progress.phase)}
              />
            </dl>
          ) : null}
        </>
      )}
      {actionError !== null ? (
        <p className={styles.errorMessage} role="alert">
          {actionError}
        </p>
      ) : null}
    </section>
  );
}

export function IdentityReviewPage({
  batchId,
  selectedItemId: initialItemId,
}: {
  batchId: string;
  selectedItemId: string | null;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [batch, setBatch] = useState<IdentityReviewBatch | null>(null);
  const [selectedItemId, setSelectedItemId] = useState(initialItemId);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadBatch = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const loaded = await client.getIdentityReviewBatch(batchId, {
          signal,
        });
        if (!signal?.aborted) {
          setBatch(loaded);
          setError(null);
          setLoading(false);
        }
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

  const effectiveSelectedItemId =
    batch?.items.find((item) => item.item_id === selectedItemId)?.item_id ??
    batch?.items[0]?.item_id ??
    null;
  const selectedIndex =
    batch === null
      ? null
      : batch.items.findIndex(
          (item) => item.item_id === effectiveSelectedItemId,
        );
  const selectedItem =
    batch === null || batch.items.length === 0 || selectedIndex === null
      ? null
      : (batch.items[selectedIndex] ?? null);

  function selectItem(itemId: string) {
    setSelectedItemId(itemId);
    const url = new URL(window.location.href);
    url.searchParams.set("item", itemId);
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
  }

  function moveSelection(direction: -1 | 1, pendingOnly: boolean) {
    if (batch === null || batch.items.length === 0 || selectedIndex === null) {
      return;
    }
    const candidates = batch.items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => !pendingOnly || item.decision.status === "pending");
    const currentPosition = candidates.findIndex(
      ({ index }) => index === selectedIndex,
    );
    if (currentPosition < 0) {
      selectItem(candidates[0].item.item_id);
      return;
    }
    const next = candidates[currentPosition + direction];
    if (next !== undefined) {
      selectItem(next.item.item_id);
    }
  }

  async function retryBatch() {
    setBusy(true);
    setError(null);
    try {
      setBatch(await client.retryIdentityReviewBatch(batchId));
    } catch (reason: unknown) {
      setError(describeError(reason));
    } finally {
      setBusy(false);
    }
  }

  if (loading && batch === null) {
    return (
      <main className={`${styles.shell} ${styles.identityReviewPage}`}>
        <p className={styles.loading} aria-live="polite">
          Loading identity review…
        </p>
      </main>
    );
  }

  return (
    <main className={`${styles.shell} ${styles.identityReviewPage}`}>
      {batch !== null ? (
        <a
          className={styles.backLink}
          href={`/recordings/${encodeURIComponent(batch.recording_id)}#identity-review`}
        >
          ← Recording workspace
        </a>
      ) : null}
      {error !== null && batch === null ? (
        <section className={styles.panel} role="alert">
          <p className={styles.statusLabel}>Unable to load identity review</p>
          <p>{error}</p>
        </section>
      ) : batch === null ? null : (
        <>
          <header className={styles.identityReviewHeader}>
            <div>
              <p className={styles.eyebrow}>
                DokoDetector · Annotation workspace
              </p>
              <h1>Visual card identities</h1>
              <p className={styles.detailContext}>
                Recording {batch.recording_id} · batch {batch.batch_id}
              </p>
            </div>
            <IdentityStatusBadge value={batch.status} />
          </header>

          {error !== null ? (
            <p className={styles.errorMessage} role="alert">
              {error}
            </p>
          ) : null}
          <section className={styles.identityBatchSummary}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.statusLabel}>Batch progress</p>
                <h2>Source-linked identity review</h2>
              </div>
              <span className={styles.countLabel}>
                {batch.progress.total_items} crop
                {batch.progress.total_items === 1 ? "" : "s"}
              </span>
            </div>
            <p className={styles.identityReviewMessage} aria-live="polite">
              {batch.status === "preparing"
                ? `Preparing ${batch.progress.proposals_completed} of ${batch.progress.total_items} proposals.`
                : batch.status === "ready"
                  ? "Every prepared crop is ready for human review."
                  : batch.status === "failed"
                    ? "Preparation has failures. Review the item state or retry the batch."
                    : "Preparation is blocked. Resolve the source or holdout blocker before review."}
            </p>
            <dl className={styles.identityProgress}>
              <IdentityStat
                label="Crops"
                value={`${batch.progress.crops_materialized}/${batch.progress.total_items}`}
              />
              <IdentityStat
                label="Proposals"
                value={`${batch.progress.proposals_completed}/${batch.progress.total_items}`}
              />
              <IdentityStat
                label="Failed items"
                value={String(batch.progress.failed_items)}
              />
              <IdentityStat
                label="Crop policy"
                value={batch.crop_policy.policy_id}
              />
            </dl>
            {batch.failures.length > 0 ? (
              <IdentityFailureList failures={batch.failures} />
            ) : null}
            {batch.failures.some((failure) => failure.retryable) ? (
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => void retryBatch()}
                disabled={busy}
              >
                {busy ? "Retrying…" : "Retry failed preparation"}
              </button>
            ) : null}
          </section>

          {batch.status === "preparing" ? (
            <p className={styles.identityEmptyState} aria-live="polite">
              The review workspace will update when crop and proposal
              preparation completes.
            </p>
          ) : batch.items.length === 0 ? (
            <section className={styles.identityEmptyState} role="status">
              <h2>No identity-usable crops</h2>
              <p>
                This batch contains no reviewed visible cards that are usable
                for visual card identity.
              </p>
            </section>
          ) : selectedItem !== null ? (
            <div className={styles.identityWorkspace}>
              <aside
                className={styles.identityItemRail}
                aria-label="Identity crops"
              >
                <div className={styles.sectionHeading}>
                  <div>
                    <p className={styles.statusLabel}>Queue</p>
                    <h2>Identity crops</h2>
                  </div>
                  <span className={styles.countLabel}>
                    {batch.items.length}
                  </span>
                </div>
                <ol className={styles.identityItemList}>
                  {batch.items.map((item, index) => (
                    <li key={item.item_id}>
                      <button
                        className={styles.identityItemButton}
                        data-selected={item.item_id === selectedItem.item_id}
                        type="button"
                        onClick={() => selectItem(item.item_id)}
                      >
                        <span>Crop {index + 1}</span>
                        <strong>{item.visible_card_review_item_id}</strong>
                        <small>{formatIdentifier(item.status)}</small>
                      </button>
                    </li>
                  ))}
                </ol>
              </aside>
              <IdentityReviewItem
                item={selectedItem}
                itemIndex={selectedIndex ?? 0}
                totalItems={batch.items.length}
                onPrevious={() => moveSelection(-1, false)}
                onPreviousPending={() => moveSelection(-1, true)}
                onNext={() => moveSelection(1, false)}
                onNextPending={() => moveSelection(1, true)}
              />
            </div>
          ) : null}
        </>
      )}
    </main>
  );
}

function IdentityReviewItem({
  item,
  itemIndex,
  totalItems,
  onPrevious,
  onPreviousPending,
  onNext,
  onNextPending,
}: {
  item: IdentityItem;
  itemIndex: number;
  totalItems: number;
  onPrevious: () => void;
  onPreviousPending: () => void;
  onNext: () => void;
  onNextPending: () => void;
}) {
  const polygons = readPolygons(item.visible_card);
  const box = readBox(item.visible_card);
  const hasPrevious = itemIndex > 0;
  const hasNext = itemIndex < totalItems - 1;
  return (
    <section className={styles.identityFramePanel}>
      <header className={styles.identityFrameHeader}>
        <div>
          <p className={styles.statusLabel}>
            Crop {itemIndex + 1} of {totalItems}
          </p>
          <h2>{item.item_id}</h2>
          <p className={styles.detailMetaLine}>
            Source item {item.visible_card_review_item_id}
          </p>
        </div>
        <IdentityStatusBadge value={item.status} />
      </header>

      <nav className={styles.identityNavigation} aria-label="Identity crops">
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onPrevious}
          disabled={!hasPrevious}
        >
          Previous
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onPreviousPending}
          disabled={!hasPrevious}
        >
          Previous pending
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onNextPending}
          disabled={!hasNext}
        >
          Next pending
        </button>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={onNext}
          disabled={!hasNext}
        >
          Next
        </button>
      </nav>

      <div className={styles.identityFrameGrid}>
        <section className={styles.identitySourceCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Source context</p>
              <h2>Reviewed visible region</h2>
            </div>
          </div>
          <div className={styles.identitySourceViewport}>
            <img
              className={styles.identitySourceImage}
              src={item.source.image_url}
              alt={`Source frame ${item.source.frame_part_name}`}
            />
            <svg
              className={styles.identitySourceOverlay}
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              {polygons.map((polygon, index) => (
                <polygon
                  key={`polygon-${index}`}
                  points={polygon
                    .map((point) => `${point.x},${point.y}`)
                    .join(" ")}
                />
              ))}
              {box !== null ? (
                <rect
                  x={box.x_min}
                  y={box.y_min}
                  width={box.x_max - box.x_min}
                  height={box.y_max - box.y_min}
                />
              ) : null}
            </svg>
          </div>
          <p className={styles.identityLegend}>
            Green outline: reviewed visible region. Dashed outline: derived box
            used for the frozen crop.
          </p>
        </section>

        <section className={styles.identityCropCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Frozen input</p>
              <h2>Identity crop</h2>
            </div>
            {item.crop !== null ? (
              <span className={styles.countLabel}>
                {item.crop.width} × {item.crop.height}
              </span>
            ) : null}
          </div>
          {item.crop !== null ? (
            <div className={styles.identityCropViewport}>
              <img
                className={styles.identityCropImage}
                src={item.crop.image_url}
                alt={`Frozen identity crop for ${item.item_id}`}
              />
            </div>
          ) : (
            <p className={styles.identityEmptyState}>
              This crop is unavailable. Review the item failure below.
            </p>
          )}
          <p className={styles.detailMetaLine}>
            Policy {item.crop?.policy_id ?? "not materialized"}
          </p>
        </section>
      </div>

      <div className={styles.identityDetailGrid}>
        <section className={styles.identityProposalCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Classifier proposal</p>
              <h2>Suggestion only</h2>
            </div>
            <span className={styles.countLabel}>
              {item.proposal?.status === "ok" ? "Available" : "Unavailable"}
            </span>
          </div>
          {item.proposal?.status === "ok" ? (
            <>
              <p className={styles.identityProposalLead}>
                {item.proposal.classifier.name}{" "}
                {item.proposal.classifier.version}
                {item.proposal.score === null
                  ? ""
                  : ` · score ${formatScore(item.proposal.score)}`}
              </p>
              <ol className={styles.identityCandidateList}>
                {item.proposal.candidates.map((candidate) => (
                  <li key={candidate.card}>
                    <strong>{candidate.card}</strong>
                    <span>{formatScore(candidate.probability)}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <p className={styles.identityEmptyState}>
              No classifier proposal is available. This item remains reviewable
              without a suggestion.
            </p>
          )}
        </section>

        <section className={styles.identityDecisionCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Human decision</p>
              <h2>Pending</h2>
            </div>
          </div>
          <p className={styles.identityEmptyState}>
            Identity selection and completion controls arrive in M2. Do not use
            this proposal as ground truth.
          </p>
        </section>
      </div>

      {item.failure !== null ? (
        <div className={styles.identityFailure} role="alert">
          <strong>{formatIdentifier(item.failure.code)}</strong>
          <p>{item.failure.message}</p>
        </div>
      ) : null}

      <details className={styles.identityLineage}>
        <summary>Source, crop, and proposal lineage</summary>
        <dl className={styles.detailMetadata}>
          <IdentityStat label="Recording" value={item.source.source_asset_id} />
          <IdentityStat
            label="Source frame"
            value={item.source.frame_part_name}
          />
          <IdentityStat
            label="Source frame digest"
            value={item.source.frame_sha256}
          />
          <IdentityStat
            label="Source asset digest"
            value={item.source.source_asset_sha256}
          />
          <IdentityStat
            label="Visible card digest"
            value={item.visible_card_digest}
          />
          <IdentityStat
            label="Crop digest"
            value={item.crop?.sha256 ?? "Not available"}
          />
          <IdentityStat
            label="Proposal digest"
            value={item.proposal?.result_digest ?? "Not available"}
          />
        </dl>
      </details>
    </section>
  );
}

function IdentityStatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}

function IdentityStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function IdentityFailureList({
  failures,
}: {
  failures: IdentityReviewPreview["validation"]["blockers"];
}) {
  return (
    <ul className={styles.identityFailureList}>
      {failures.map((failure) => (
        <li key={`${failure.code}:${failure.item_id ?? "batch"}`}>
          <strong>{formatIdentifier(failure.code)}</strong>
          <span>{failure.message}</span>
        </li>
      ))}
    </ul>
  );
}

function readPolygons(value: Record<string, unknown>): Point[][] {
  const visibleRegion = asRecord(value.visible_region);
  const polygons = visibleRegion === null ? null : visibleRegion.polygons;
  if (!Array.isArray(polygons)) {
    return [];
  }
  return polygons
    .map((polygon) =>
      Array.isArray(polygon)
        ? polygon
            .map(readPoint)
            .filter((point): point is Point => point !== null)
        : [],
    )
    .filter((polygon) => polygon.length >= 3);
}

function readBox(value: Record<string, unknown>): Box | null {
  const derivedBox = asRecord(value.derived_box);
  const box = derivedBox === null ? null : asRecord(derivedBox.box_2d);
  if (box === null) {
    return null;
  }
  const xMin = readCoordinate(box.x_min);
  const yMin = readCoordinate(box.y_min);
  const xMax = readCoordinate(box.x_max);
  const yMax = readCoordinate(box.y_max);
  return xMin < xMax && yMin < yMax
    ? { x_min: xMin, y_min: yMin, x_max: xMax, y_max: yMax }
    : null;
}

function readPoint(value: unknown): Point | null {
  const point = asRecord(value);
  if (point === null) {
    return null;
  }
  return {
    x: readCoordinate(point.x),
    y: readCoordinate(point.y),
  };
}

function readCoordinate(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(1000, Math.max(0, value))
    : 0;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatScore(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}
