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
          <h3>
            {formatMicroseconds(frame.requested_time_us)} · resolved frame
          </h3>
        </div>
        <span className={styles.status} data-state={item.reviewState}>
          {formatIdentifier(item.reviewState)}
        </span>
      </header>
      <div className={identityStyles.detailGrid}>
        <section className={identityStyles.sourceCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Source frame</p>
              <h4>Read-only geometry</h4>
            </div>
          </div>
          <img
            className={identityStyles.canvasImage}
            src={frameUrl}
            width={frame.width}
            height={frame.height}
            alt={`Resolved source frame for ${item.itemId}`}
          />
          <p className={styles.detailMetaLine}>
            Frame {frame.frame_index} · {frame.width} × {frame.height}
          </p>
          <p className={identityStyles.legend}>
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
        <section className={identityStyles.cropCard}>
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
          <p className={styles.detailMetaLine}>
            Crop digest {crop?.image_sha256 ?? "Not available"}
          </p>
        </section>
      </div>
      <section className={identityStyles.proposalCard}>
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
        <section className={identityStyles.decisionCard}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Human decision</p>
              <h4>{formatIdentifier(item.reviewState)}</h4>
            </div>
          </div>
          <div className={identityStyles.outcomeButtons}>
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
}: {
  item: EditableIdentity | null;
  loading: boolean;
  recordingId: string;
  sourceRevisionId: string | null;
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
        />
      )}
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
