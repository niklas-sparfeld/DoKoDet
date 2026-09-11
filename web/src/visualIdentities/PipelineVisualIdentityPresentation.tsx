import { useState, type ReactNode } from "react";

import {
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
} from "../api/client";
import styles from "../App.module.css";
import { ShortcutButton } from "../pipeline/ShortcutButton";
import identityStyles from "./PipelineVisualIdentityEditor.module.css";
import {
  IDENTITY_SUIT_ROWS,
  type EditableIdentity,
} from "./PipelineVisualIdentityTypes";
import {
  formatCardIdentity,
  formatIdentityOutcomeStatus,
  formatIdentityReviewStatus,
  identityReviewStatus,
} from "./PipelineVisualIdentityFormatting";

export function visualIdentityReviewPrewarmUrls(
  recordingId: string,
  sourceRevisionId: string | null,
  item: EditableIdentity,
): string[] {
  const frameUrl = pipelineDerivedFramePath(
    recordingId,
    item.outcome.frame_identity.requested_time_us,
  );
  const crop = item.outcome.crop_identity;
  const cropUrl =
    crop?.status === "usable" && sourceRevisionId !== null
      ? pipelineIdentityCropPath(recordingId, sourceRevisionId, item.itemId)
      : null;
  return cropUrl === null ? [frameUrl] : [frameUrl, cropUrl];
}

export function IdentityReviewControls({
  editable,
  hasPrevious,
  hasNext,
  item,
  onPrevious,
  onNext,
  onAccept,
  onMarkUnusable,
  onMarkFaceDown,
  onReportSourceProblem,
}: {
  editable: boolean;
  hasPrevious: boolean;
  hasNext: boolean;
  item: EditableIdentity | null;
  onPrevious: () => void;
  onNext: () => void;
  onAccept: () => void;
  onMarkUnusable: () => void;
  onMarkFaceDown: () => void;
  onReportSourceProblem: () => void;
}) {
  const reviewStatus = item === null ? null : identityReviewStatus(item);
  const canAccept =
    editable &&
    item !== null &&
    (reviewStatus === "accepted" || item.outcome.candidates.length > 0);
  const canMark =
    editable && item !== null && item.outcome.crop_identity !== null;
  return (
    <aside
      className={identityStyles.controlSidebar}
      aria-label="Visual identity review controls"
    >
      <p className={styles.statusLabel}>Review controls</p>
      <div className={identityStyles.controlGroup}>
        <ShortcutButton
          label="Previous card"
          shortcut="Left"
          ariaShortcut="ArrowLeft"
          disabled={!hasPrevious}
          disabledReason="There is no previous card."
          onClick={onPrevious}
        />
        <ShortcutButton
          label="Next card"
          shortcut="Right"
          ariaShortcut="ArrowRight"
          disabled={!hasNext}
          disabledReason="There is no next card."
          onClick={onNext}
        />
      </div>
      {editable ? (
        <div className={identityStyles.controlGroup}>
          <ShortcutButton
            label={reviewStatus === "accepted" ? "Mark unreviewed" : "Accept"}
            shortcut="A"
            ariaShortcut="A"
            variant="primary"
            disabled={!canAccept}
            disabledReason="Accept is available when an identity candidate exists."
            onClick={onAccept}
          />
          <ShortcutButton
            label={
              reviewStatus === "unusable"
                ? "Mark unreviewed"
                : "Identity unusable"
            }
            shortcut="U"
            ariaShortcut="U"
            disabled={!canMark}
            disabledReason="A usable crop is required to mark an identity unusable."
            onClick={onMarkUnusable}
          />
          <ShortcutButton
            label={
              reviewStatus === "face_down" ? "Mark unreviewed" : "Face down"
            }
            shortcut="F"
            ariaShortcut="F"
            disabled={!canMark}
            disabledReason="A usable crop is required to mark a card face down."
            onClick={onMarkFaceDown}
          />
          <ShortcutButton
            label={
              reviewStatus === "source_problem"
                ? "Mark unreviewed"
                : "Source problem"
            }
            shortcut="S"
            ariaShortcut="S"
            disabled={item === null}
            disabledReason="Select a card before reporting a source problem."
            onClick={onReportSourceProblem}
          />
        </div>
      ) : null}
    </aside>
  );
}

export function IdentityItemPanel({
  recordingId,
  sourceRevisionId,
  item,
  items,
  onSelectIdentity,
}: {
  recordingId: string;
  sourceRevisionId: string | null;
  item: EditableIdentity;
  items: EditableIdentity[];
  onSelectIdentity?: (identity: string) => void;
}) {
  const crop = item.outcome.crop_identity;
  const frame = item.outcome.frame_identity;
  const [frameUrl, prewarmedCropUrl] = visualIdentityReviewPrewarmUrls(
    recordingId,
    sourceRevisionId,
    item,
  );
  const cropUrl = prewarmedCropUrl ?? null;
  const selectedIdentity = item.outcome.candidates[0]?.identity ?? null;
  return (
    <section
      className={identityStyles.framePanel}
      aria-label="Selected visual identity"
    >
      <div className={identityStyles.detailGrid}>
        <figure className={identityStyles.imagePanel}>
          <IdentityCropPreview
            cropUrl={cropUrl}
            itemId={item.itemId}
            emptyMessage={
              crop?.unusable_reason ??
              item.outcome.error ??
              "No usable crop is available."
            }
          />
        </figure>
        <figure className={identityStyles.imagePanel}>
          <div className={identityStyles.frameImageContainer}>
            <img
              className={identityStyles.canvasImage}
              src={frameUrl}
              width={frame.width}
              height={frame.height}
              alt={`Resolved source frame for ${item.itemId}`}
            />
            <IdentityGeometryOverlay
              items={items}
              selectedItemId={item.itemId}
              frame={frame}
            />
          </div>
        </figure>
      </div>
      {onSelectIdentity !== undefined ? (
        <section className={identityStyles.decisionPanel}>
          <div
            className={identityStyles.choiceGrid}
            aria-label="Canonical identities"
          >
            {IDENTITY_SUIT_ROWS.flatMap(({ suit, cards }) =>
              cards.map(([identity, label]) => (
                <button
                  key={identity}
                  className={identityStyles.choiceButton}
                  data-selected={selectedIdentity === identity}
                  data-suit={suit}
                  type="button"
                  aria-label={label}
                  aria-pressed={selectedIdentity === identity}
                  onClick={() => onSelectIdentity(identity)}
                  disabled={crop === null}
                >
                  <CardIdentityLabel identity={identity} label={label} />
                </button>
              )),
            )}
          </div>
          {item.outcome.error !== null ? (
            <p className={styles.detailBlocker}>{item.outcome.error}</p>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

function IdentityCropPreview({
  cropUrl,
  itemId,
  emptyMessage,
}: {
  cropUrl: string | null;
  itemId: string;
  emptyMessage: string;
}) {
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);

  if (cropUrl === null) {
    return <p className={styles.detailEmptyState}>{emptyMessage}</p>;
  }

  const loaded = loadedUrl === cropUrl;
  return (
    <div className={identityStyles.cropPreview} data-loaded={loaded}>
      {!loaded ? (
        <div className={identityStyles.cropPlaceholder} role="status">
          Loading crop preview…
        </div>
      ) : null}
      <img
        key={cropUrl}
        className={identityStyles.cropImage}
        data-loaded={loaded}
        src={cropUrl}
        alt={`Derived identity crop for ${itemId}`}
        onLoad={() => setLoadedUrl(cropUrl)}
      />
    </div>
  );
}

export function IdentitySourceSurface({
  item,
  items,
  loading,
  recordingId,
  sourceRevisionId,
  onSelectIdentity,
  controls,
}: {
  item: EditableIdentity | null;
  items: EditableIdentity[];
  loading: boolean;
  recordingId: string;
  sourceRevisionId: string | null;
  onSelectIdentity?: (identity: string) => void;
  controls?: ReactNode;
}) {
  return (
    <section
      className={identityStyles.workbenchSurface}
      aria-label="Visual identity source and crop"
    >
      <div
        className={
          controls === undefined ? undefined : identityStyles.reviewWorkbench
        }
      >
        {controls}
        {loading ? (
          <p className={styles.detailEmptyState}>Loading visual identities…</p>
        ) : item === null ? (
          <p className={styles.detailEmptyState}>
            Select an identity card from the Timeline Rail.
          </p>
        ) : (
          <IdentityItemPanel
            recordingId={recordingId}
            sourceRevisionId={sourceRevisionId}
            item={item}
            items={items}
            onSelectIdentity={onSelectIdentity}
          />
        )}
      </div>
    </section>
  );
}

function IdentityGeometryOverlay({
  items,
  selectedItemId,
  frame,
}: {
  items: EditableIdentity[];
  selectedItemId: string;
  frame: EditableIdentity["outcome"]["frame_identity"];
}) {
  const frameItems = items.filter(
    (candidate) =>
      candidate.outcome.frame_identity.image_sha256 === frame.image_sha256 &&
      candidate.outcome.frame_identity.width === frame.width &&
      candidate.outcome.frame_identity.height === frame.height,
  );
  return (
    <svg
      className={identityStyles.frameGeometryOverlay}
      viewBox="0 0 1000 1000"
      preserveAspectRatio="none"
      aria-label="Visible card geometry"
    >
      {frameItems.flatMap((candidate) =>
        geometryPolygons(candidate.outcome.geometry).map((polygon, index) => (
          <IdentityPolygon
            key={`${candidate.itemId}-${index}`}
            candidate={candidate}
            polygon={polygon}
            selected={candidate.itemId === selectedItemId}
          />
        )),
      )}
    </svg>
  );
}

function IdentityPolygon({
  candidate,
  polygon,
  selected,
}: {
  candidate: EditableIdentity;
  polygon: GeometryPoint[];
  selected: boolean;
}) {
  const palette = identityOverlayPalette(identityReviewStatus(candidate));
  return (
    <polygon
      points={polygon.map((point) => `${point.x},${point.y}`).join(" ")}
      data-card-id={candidate.itemId}
      data-current={selected}
      data-review-state={identityReviewStatus(candidate)}
      fill={palette.fill}
      stroke={selected ? "#ffd24f" : palette.stroke}
    />
  );
}

function identityOverlayPalette(
  reviewStatus: ReturnType<typeof identityReviewStatus>,
): { fill: string; stroke: string } {
  if (reviewStatus === "accepted") {
    return { fill: "rgba(85, 213, 137, 0.2)", stroke: "#55d589" };
  }
  if (reviewStatus === "unusable") {
    return { fill: "rgba(255, 125, 114, 0.16)", stroke: "#ff7d72" };
  }
  return { fill: "rgba(196, 154, 239, 0.2)", stroke: "#c49aef" };
}

type GeometryPoint = { x: number; y: number };

function geometryPolygons(
  geometry: Record<string, unknown>,
): GeometryPoint[][] {
  const region = geometry.visible_region;
  if (isRecord(region) && Array.isArray(region.polygons)) {
    return region.polygons
      .map(readPolygon)
      .filter((polygon): polygon is GeometryPoint[] => polygon !== null);
  }
  const box = geometry.box_2d;
  if (
    !isRecord(box) ||
    !isFiniteNumber(box.x_min) ||
    !isFiniteNumber(box.y_min) ||
    !isFiniteNumber(box.x_max) ||
    !isFiniteNumber(box.y_max)
  )
    return [];
  return [
    [
      { x: box.x_min, y: box.y_min },
      { x: box.x_max, y: box.y_min },
      { x: box.x_max, y: box.y_max },
      { x: box.x_min, y: box.y_max },
    ],
  ];
}

function readPolygon(value: unknown): GeometryPoint[] | null {
  if (!Array.isArray(value)) return null;
  const polygon = value.map((point) =>
    isRecord(point) && isFiniteNumber(point.x) && isFiniteNumber(point.y)
      ? { x: point.x, y: point.y }
      : null,
  );
  return polygon.length >= 3 && polygon.every((point) => point !== null)
    ? polygon
    : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function IdentityCardList({
  items,
  selectedItemId,
  onSelect,
}: {
  items: EditableIdentity[];
  selectedItemId: string | null;
  onSelect: (item: EditableIdentity) => void;
}) {
  return (
    <section className={identityStyles.cardRail} aria-label="Identity cards">
      <ol>
        {items.map((item) => (
          <li key={item.itemId}>
            <button
              type="button"
              data-selected={item.itemId === selectedItemId}
              onClick={() => onSelect(item)}
            >
              <CardRailIdentity item={item} />
              <small>
                {formatIdentityReviewStatus(identityReviewStatus(item))}
              </small>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

function CardRailIdentity({ item }: { item: EditableIdentity }) {
  if (item.outcome.status !== "classified") {
    const label = formatIdentityOutcomeStatus(item.outcome.status);
    const symbol = item.outcome.status === "face_down" ? "▧" : "!";
    return (
      <>
        <span className={identityStyles.cardRailSymbol}>{symbol}</span>
        <strong>{label}</strong>
      </>
    );
  }
  const identity = item.outcome.candidates[0]?.identity;
  if (identity === undefined)
    return (
      <>
        <span className={identityStyles.cardRailSymbol}>?</span>
        <strong>Unentschieden</strong>
      </>
    );
  const [symbol, ...rank] = formatCardIdentity(identity).split(" ");
  return (
    <>
      <span
        className={`${identityStyles.cardSymbol} ${identityStyles.cardRailSymbol}`}
        data-suit={identity.split("_", 1)[0]?.toLowerCase()}
      >
        {symbol}
      </span>
      <strong>{rank.join(" ")}</strong>
    </>
  );
}

function CardIdentityLabel({
  identity,
  label = formatCardIdentity(identity),
}: {
  identity: string;
  label?: string;
}) {
  const [symbol, ...rank] = label.split(" ");
  const suit = identity.split("_", 1)[0]?.toLowerCase();
  if (rank.length === 0 || suit === undefined) return label;
  return (
    <>
      <span className={identityStyles.cardSymbol} data-suit={suit}>
        {symbol}
      </span>{" "}
      {rank.join(" ")}
    </>
  );
}
