import {
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
} from "../api/client";
import styles from "../App.module.css";
import identityStyles from "./PipelineVisualIdentityEditor.module.css";
import {
  CANONICAL_IDENTITIES,
  type EditableIdentity,
} from "./PipelineVisualIdentityTypes";
import {
  formatIdentifier,
  formatMicroseconds,
  formatScore,
} from "./PipelineVisualIdentityFormatting";

export function IdentityItemPanel({
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
  onAccept?: () => void;
  onSelectIdentity?: (identity: string) => void;
  onMarkUnusable?: () => void;
  onReportSourceProblem?: () => void;
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
      <header className={identityStyles.frameHeader}>
        <div>
          <p className={styles.statusLabel}>Source item {item.itemId}</p>
          <h3>{formatMicroseconds(frame.requested_time_us)}</h3>
        </div>
        <span className={styles.status} data-state={item.reviewState}>
          {formatIdentifier(item.reviewState)}
        </span>
      </header>
      <div className={identityStyles.detailGrid}>
        <figure className={identityStyles.imagePanel}>
          <figcaption>Overall</figcaption>
          <img
            className={identityStyles.canvasImage}
            src={frameUrl}
            width={frame.width}
            height={frame.height}
            alt={`Resolved source frame for ${item.itemId}`}
          />
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
        </figure>
        <figure className={identityStyles.imagePanel}>
          <figcaption>Crop</figcaption>
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
          <small>{crop?.crop_policy ?? "No crop policy"}</small>
        </figure>
      </div>
      <section
        className={identityStyles.proposalLine}
        aria-label="Identity proposal"
      >
        <span>Suggestion</span>
        {item.outcome.candidates.length === 0 ? (
          <strong>No prediction</strong>
        ) : (
          <ol className={identityStyles.candidateList}>
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
      {onAccept !== undefined &&
      onSelectIdentity !== undefined &&
      onMarkUnusable !== undefined &&
      onReportSourceProblem !== undefined ? (
        <section className={identityStyles.decisionPanel}>
          <div className={identityStyles.outcomeButtons}>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={onAccept}
              disabled={item.outcome.candidates.length === 0}
            >
              Accept suggestion <kbd>A</kbd>
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={onMarkUnusable}
              disabled={crop === null}
            >
              Unusable <kbd>U</kbd>
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={onReportSourceProblem}
            >
              Correct source <kbd>C</kbd>
            </button>
          </div>
          <div
            className={identityStyles.choiceGrid}
            aria-label="Canonical identities"
          >
            {CANONICAL_IDENTITIES.map((identity) => (
              <button
                key={identity}
                className={identityStyles.choiceButton}
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
      ) : null}
    </section>
  );
}

export function IdentitySourceSurface({
  item,
  loading,
  recordingId,
  sourceRevisionId,
  onAccept,
  onSelectIdentity,
  onMarkUnusable,
  onReportSourceProblem,
}: {
  item: EditableIdentity | null;
  loading: boolean;
  recordingId: string;
  sourceRevisionId: string | null;
  onAccept?: () => void;
  onSelectIdentity?: (identity: string) => void;
  onMarkUnusable?: () => void;
  onReportSourceProblem?: () => void;
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
          onAccept={onAccept}
          onSelectIdentity={onSelectIdentity}
          onMarkUnusable={onMarkUnusable}
          onReportSourceProblem={onReportSourceProblem}
        />
      )}
    </section>
  );
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
      <header>
        <p className={styles.statusLabel}>Cards</p>
        <strong>{items.length}</strong>
      </header>
      <ol>
        {items.map((item, index) => (
          <li key={item.itemId}>
            <button
              type="button"
              data-selected={item.itemId === selectedItemId}
              onClick={() => onSelect(item)}
            >
              <span>{index + 1}</span>
              <strong>
                {item.outcome.candidates[0]?.identity ?? "Needs decision"}
              </strong>
              <small>{formatIdentifier(item.reviewState)}</small>
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
            <dd>Accept suggestion</dd>
          </div>
          <div>
            <dt>U</dt>
            <dd>Mark unusable</dd>
          </div>
          <div>
            <dt>C</dt>
            <dd>Correct visible region</dd>
          </div>
        </dl>
      </section>
    </section>
  );
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
