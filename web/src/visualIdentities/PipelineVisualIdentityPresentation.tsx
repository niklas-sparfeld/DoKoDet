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
  formatIdentifier,
  formatScore,
} from "./PipelineVisualIdentityFormatting";

export function IdentityItemPanel({
  recordingId,
  sourceRevisionId,
  item,
  onAccept,
  onSelectIdentity,
  onMarkUnusable,
}: {
  recordingId: string;
  sourceRevisionId: string | null;
  item: EditableIdentity;
  onAccept?: () => void;
  onSelectIdentity?: (identity: string) => void;
  onMarkUnusable?: () => void;
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
          <img
            className={identityStyles.canvasImage}
            src={frameUrl}
            width={frame.width}
            height={frame.height}
            alt={`Resolved source frame for ${item.itemId}`}
          />
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
      <section
        className={identityStyles.proposalLine}
        aria-label="Identity proposal"
      >
        {item.outcome.candidates.length === 0 ? (
          <strong>No prediction</strong>
        ) : (
          <ol className={identityStyles.candidateList}>
            {item.outcome.candidates.map((candidate) => (
              <li key={candidate.identity}>
                <strong>{formatCardIdentity(candidate.identity)}</strong>
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
      onMarkUnusable !== undefined ? (
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
          </div>
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
                  {label}
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
  loading,
  recordingId,
  sourceRevisionId,
  onAccept,
  onSelectIdentity,
  onMarkUnusable,
}: {
  item: EditableIdentity | null;
  loading: boolean;
  recordingId: string;
  sourceRevisionId: string | null;
  onAccept?: () => void;
  onSelectIdentity?: (identity: string) => void;
  onMarkUnusable?: () => void;
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
                {item.outcome.candidates[0] === undefined
                  ? "Unentschieden"
                  : formatCardIdentity(item.outcome.candidates[0].identity)}
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
        </dl>
      </section>
    </section>
  );
}
