import type { PointerEvent as ReactPointerEvent } from "react";

import { pipelineDerivedFramePath } from "../api/client";
import styles from "../App.module.css";
import visibleStyles from "./PipelineVisibleCardEditor.module.css";
import {
  formatFrameTime,
  formatIdentifier,
} from "./PipelineVisibleCardFormatting";
import type {
  Candidate,
  EditableFrame,
  EditorState,
} from "./PipelineVisibleCardTypes";

export function VisibleCardFramePanel({
  recordingId,
  frame,
  editor,
  editorError,
  onOpenEditor,
  onSaveEditor,
  onCancelEditor,
  onRemoveCard,
  onPointerMove,
  onPointerUp,
  onPointPointerDown,
  readOnly,
}: {
  recordingId: string;
  frame: EditableFrame;
  editor: EditorState | null;
  editorError: string | null;
  onOpenEditor?: (candidate: Candidate | null) => void;
  onSaveEditor?: () => void;
  onCancelEditor?: () => void;
  onRemoveCard?: (cardId: string) => void;
  onPointerMove: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointerUp: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointPointerDown: (
    event: ReactPointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
  readOnly: boolean;
}) {
  const identity = frame.outcome.frame_identity;
  const width = identity?.width ?? 1;
  const height = identity?.height ?? 1;
  const sourceUrl =
    identity === null
      ? null
      : pipelineDerivedFramePath(recordingId, identity.requested_time_us);
  return (
    <section
      className={visibleStyles.framePanel}
      aria-label="Selected visible-card frame"
    >
      <header className={visibleStyles.frameHeader}>
        <div>
          <p className={styles.statusLabel}>Source item {frame.itemId}</p>
          <h3>{formatFrameTime(frame)} · resolved frame</h3>
        </div>
        <span className={styles.status} data-state={frame.reviewState}>
          {formatIdentifier(frame.reviewState)}
        </span>
      </header>
      {sourceUrl !== null ? (
        <>
          <div
            className={visibleStyles.canvasViewport}
            style={{ aspectRatio: `${width} / ${height}` }}
          >
            <img
              className={visibleStyles.canvasImage}
              src={sourceUrl}
              width={width}
              height={height}
              alt={`Resolved source frame at ${formatFrameTime(frame)}`}
            />
            <svg
              className={visibleStyles.overlay}
              viewBox={`0 0 ${width} ${height}`}
              role="img"
              aria-label={`${frame.outcome.candidates.length} visible-card proposal${frame.outcome.candidates.length === 1 ? "" : "s"}`}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              style={{ pointerEvents: editor === null ? "none" : "auto" }}
            >
              {frame.outcome.candidates.map((candidate) => (
                <CandidateOverlay
                  key={candidate.card_id}
                  candidate={candidate}
                  width={width}
                  height={height}
                />
              ))}
              {editor?.polygons.map((polygon, polygonIndex) => (
                <g key={`editor-${polygonIndex}`}>
                  {polygon.length >= 2 ? (
                    <polygon
                      points={polygon
                        .map(
                          (point) =>
                            `${(point.x * width) / 1000},${(point.y * height) / 1000}`,
                        )
                        .join(" ")}
                      fill="rgba(255, 210, 79, 0.25)"
                      stroke="#ffd24f"
                      strokeWidth={Math.max(1, width / 250)}
                    />
                  ) : null}
                  {polygon.map((point, pointIndex) => (
                    <circle
                      key={`${point.x}:${point.y}:${pointIndex}`}
                      cx={(point.x * width) / 1000}
                      cy={(point.y * height) / 1000}
                      r={Math.max(3, width / 55)}
                      fill="#ffd24f"
                      tabIndex={0}
                      role="button"
                      aria-label={`Polygon ${polygonIndex + 1}, point ${pointIndex + 1} at ${point.x}, ${point.y}`}
                      onPointerDown={(event) =>
                        onPointPointerDown(event, polygonIndex, pointIndex)
                      }
                      onClick={(event) => event.stopPropagation()}
                    />
                  ))}
                </g>
              ))}
            </svg>
          </div>
          <p className={styles.pipelineUrlState}>
            Derived source frame {sourceUrl}
          </p>
        </>
      ) : (
        <p className={styles.detailBlocker}>
          {frame.outcome.error ??
            "No resolved source frame is available. Mark this frame unusable."}
        </p>
      )}
      {frame.outcome.error !== null ? (
        <p className={styles.detailBlocker}>{frame.outcome.error}</p>
      ) : null}
      <section
        className={visibleStyles.proposalList}
        aria-label="Visible-card proposals"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Detector output</p>
            <h4>Proposal overlays</h4>
          </div>
          <span className={styles.countLabel}>
            {frame.outcome.candidates.length}
          </span>
        </div>
        {frame.outcome.candidates.length === 0 ? (
          <p className={styles.detailEmptyState}>
            No visible-card proposals. Use Add missed card or mark the frame
            reviewed empty.
          </p>
        ) : (
          <ol className={visibleStyles.proposalItems}>
            {frame.outcome.candidates.map((candidate, index) => (
              <li key={candidate.card_id}>
                <div className={visibleStyles.proposalRow}>
                  <span>
                    <strong>Proposal {index + 1}</strong>
                    <small>
                      {candidate.card_id} ·{" "}
                      {formatIdentifier(candidate.geometry.kind)}
                    </small>
                  </span>
                  <div className={visibleStyles.actionButtons}>
                    {!readOnly ? (
                      <>
                        <button
                          className={styles.inlineAction}
                          type="button"
                          onClick={() => onOpenEditor?.(candidate)}
                        >
                          Reshape proposal {index + 1}
                        </button>
                        <button
                          className={styles.inlineAction}
                          type="button"
                          onClick={() => onRemoveCard?.(candidate.card_id)}
                        >
                          Remove card {index + 1}
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
      {!readOnly ? (
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => onOpenEditor?.(null)}
          disabled={identity === null}
        >
          Add missed card
        </button>
      ) : null}
      {!readOnly && editor !== null ? (
        <section
          className={visibleStyles.editor}
          aria-label="Visible region editor"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Geometry editor</p>
              <h4>
                {editor.cardId === null
                  ? "Add missed card"
                  : "Reshape visible region"}
              </h4>
            </div>
          </div>
          <p className={visibleStyles.editorHelp}>
            Drag a polygon point. The complete visible region is saved once when
            the pointer is released.
          </p>
          {editorError !== null ? (
            <p className={visibleStyles.inlineFormError}>{editorError}</p>
          ) : null}
          <div className={visibleStyles.actionButtons}>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={onSaveEditor}
            >
              Save visible region
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={onCancelEditor}
            >
              Cancel
            </button>
          </div>
        </section>
      ) : null}
    </section>
  );
}

function CandidateOverlay({
  candidate,
  width,
  height,
}: {
  candidate: Candidate;
  width: number;
  height: number;
}) {
  const geometry = candidate.geometry;
  if (
    geometry.kind === "reviewed-visible-region/v1" &&
    geometry.visible_region !== undefined
  ) {
    return (
      <g data-card-id={candidate.card_id}>
        <polygon
          points={geometry.visible_region.polygons
            .flat()
            .map(
              (point) =>
                `${(point.x * width) / 1000},${(point.y * height) / 1000}`,
            )
            .join(" ")}
          fill="rgba(59, 209, 154, 0.2)"
          stroke="#3bd19a"
          strokeWidth={Math.max(1, width / 250)}
        />
      </g>
    );
  }
  const box = geometry.box_2d;
  if (box === undefined) return null;
  return (
    <g data-card-id={candidate.card_id}>
      <rect
        x={(box.x_min * width) / 1000}
        y={(box.y_min * height) / 1000}
        width={((box.x_max - box.x_min) * width) / 1000}
        height={((box.y_max - box.y_min) * height) / 1000}
        fill="rgba(234, 160, 220, 0.12)"
        stroke="#eaa0dc"
        strokeDasharray="8 5"
        strokeWidth={Math.max(1, width / 250)}
      />
    </g>
  );
}
