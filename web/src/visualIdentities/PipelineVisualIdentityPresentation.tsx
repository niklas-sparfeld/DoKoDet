import {
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
} from "../api/client";
import styles from "../App.module.css";
import identityStyles from "./PipelineVisualIdentityEditor.module.css";
import {
  IDENTITY_SUIT_ROWS,
  type EditableIdentity,
} from "./PipelineVisualIdentityTypes";
import {
  formatCardIdentity,
  formatIdentityReviewStatus,
  identityReviewStatus,
} from "./PipelineVisualIdentityFormatting";

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
      className={identityStyles.framePanel}
      aria-label="Selected visual identity"
    >
      <div className={identityStyles.detailGrid}>
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
        <figure className={identityStyles.imagePanel}>
          {cropUrl !== null ? (
            <img
              className={identityStyles.cropImage}
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

export function IdentitySourceSurface({
  item,
  items,
  loading,
  recordingId,
  sourceRevisionId,
  onSelectIdentity,
}: {
  item: EditableIdentity | null;
  items: EditableIdentity[];
  loading: boolean;
  recordingId: string;
  sourceRevisionId: string | null;
  onSelectIdentity?: (identity: string) => void;
}) {
  return (
    <section
      className={identityStyles.workbenchSurface}
      aria-label="Visual identity source and crop"
    >
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
          <polygon
            key={`${candidate.itemId}-${index}`}
            points={polygon.map((point) => `${point.x},${point.y}`).join(" ")}
            data-card-id={candidate.itemId}
            data-current={candidate.itemId === selectedItemId}
          />
        )),
      )}
    </svg>
  );
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
              <CardRailIdentity
                identity={item.outcome.candidates[0]?.identity}
              />
              <small>
                {formatIdentityReviewStatus(identityReviewStatus(item))}
              </small>
            </button>
          </li>
        ))}
      </ol>
      <section
        className={identityStyles.keyboardShortcuts}
        aria-label="Keyboard shortcuts"
      >
        <p className={styles.statusLabel}>Keyboard shortcuts</p>
        <dl>
          <div>
            <dt>← / →</dt>
            <dd>Previous / next card</dd>
          </div>
          <div>
            <dt>A</dt>
            <dd>Toggle accepted</dd>
          </div>
          <div>
            <dt>U</dt>
            <dd>Toggle unusable</dd>
          </div>
        </dl>
      </section>
    </section>
  );
}

function CardRailIdentity({ identity }: { identity?: string }) {
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
