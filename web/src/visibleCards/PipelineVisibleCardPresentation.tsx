import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

import { pipelineDerivedFramePath } from "../api/client";
import styles from "../App.module.css";
import visibleStyles from "./PipelineVisibleCardEditor.module.css";
import {
  formatIdentifier,
  frameReviewStatus,
} from "./PipelineVisibleCardFormatting";
import type {
  Candidate,
  EditableFrame,
  EditorState,
  FrameReviewStatus,
} from "./PipelineVisibleCardTypes";

export function VisibleCardFramePanel({
  recordingId,
  frame,
  editor,
  selectedCandidateId,
  editorError,
  onSelectCandidate,
  onOpenEditor,
  onCancelEditor,
  onRemoveCard,
  onPointerMove,
  onCanvasPointerDown,
  onPointerUp,
  onPointPointerDown,
  readOnly,
  proposalSlot,
}: {
  recordingId: string;
  frame: EditableFrame;
  editor: EditorState | null;
  selectedCandidateId: string | null;
  editorError: string | null;
  onSelectCandidate?: (candidate: Candidate) => void;
  onOpenEditor?: (candidate: Candidate | null) => void;
  onCancelEditor?: () => void;
  onRemoveCard?: (cardId: string) => void;
  onPointerMove: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onCanvasPointerDown: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointerUp: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointPointerDown: (
    event: ReactPointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
  readOnly: boolean;
  proposalSlot: HTMLElement | null;
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
              alt="Selected visible-card source frame"
            />
            <svg
              className={visibleStyles.overlay}
              viewBox={`0 0 ${width} ${height}`}
              role="img"
              aria-label={`${frame.outcome.candidates.length} visible-card proposal${frame.outcome.candidates.length === 1 ? "" : "s"}`}
              onPointerMove={onPointerMove}
              onPointerDown={onCanvasPointerDown}
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
                  selected={candidate.card_id === selectedCandidateId}
                  reviewStatus={frameReviewStatus(frame)}
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
      {renderProposalColumn(
        <ProposalColumn
          frame={frame}
          sourceUrl={sourceUrl}
          readOnly={readOnly}
          selectedCandidateId={selectedCandidateId}
          onSelectCandidate={onSelectCandidate}
          onOpenEditor={onOpenEditor}
          onRemoveCard={onRemoveCard}
          canAddCard={identity !== null}
        />,
        proposalSlot,
      )}
      {!readOnly && editor !== null ? (
        <section
          className={visibleStyles.editor}
          aria-label="Visible region editor"
        >
          <p className={visibleStyles.editorHelp}>
            Drag a point to adjust a visible region, or click an edge to add a
            point. Changes are saved automatically and you can keep editing. For
            a missed card, click three points on the frame to create its visible
            region.
          </p>
          {editorError !== null ? (
            <p className={visibleStyles.inlineFormError}>{editorError}</p>
          ) : null}
          <div className={visibleStyles.actionButtons}>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={onCancelEditor}
            >
              Close editor
            </button>
          </div>
        </section>
      ) : null}
    </section>
  );
}

function renderProposalColumn(
  content: ReactNode,
  proposalSlot: HTMLElement | null,
) {
  return proposalSlot === null ? content : createPortal(content, proposalSlot);
}

function ProposalColumn({
  frame,
  sourceUrl,
  readOnly,
  selectedCandidateId,
  onSelectCandidate,
  onOpenEditor,
  onRemoveCard,
  canAddCard,
}: {
  frame: EditableFrame;
  sourceUrl: string | null;
  readOnly: boolean;
  selectedCandidateId: string | null;
  onSelectCandidate?: (candidate: Candidate) => void;
  onOpenEditor?: (candidate: Candidate | null) => void;
  onRemoveCard?: (cardId: string) => void;
  canAddCard: boolean;
}) {
  return (
    <section
      className={visibleStyles.proposalColumn}
      aria-label="Visible-card proposals"
    >
      {frame.outcome.candidates.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No proposals. Add a missed card or review this frame as empty.
        </p>
      ) : (
        <ol className={visibleStyles.proposalItems}>
          {frame.outcome.candidates.map((candidate, index) => (
            <li key={candidate.card_id}>
              <div className={visibleStyles.proposalRow}>
                <button
                  className={visibleStyles.proposalSelect}
                  type="button"
                  aria-label={`Select proposal ${index + 1}`}
                  aria-pressed={candidate.card_id === selectedCandidateId}
                  data-selected={candidate.card_id === selectedCandidateId}
                  onClick={() => onSelectCandidate?.(candidate)}
                >
                  <CandidatePreview
                    candidate={candidate}
                    sourceUrl={sourceUrl}
                    frameWidth={frame.outcome.frame_identity?.width ?? 1}
                    frameHeight={frame.outcome.frame_identity?.height ?? 1}
                    label={`Proposal ${index + 1} crop preview`}
                  />
                  <span className={visibleStyles.proposalDetails}>
                    <strong>Proposal {index + 1}</strong>
                    <span>Detector suggestion</span>
                    <small>{formatGeometryKind(candidate.geometry)}</small>
                  </span>
                </button>
                {!readOnly ? (
                  <div className={visibleStyles.actionButtons}>
                    <button
                      className={styles.inlineAction}
                      type="button"
                      onClick={() => onOpenEditor?.(candidate)}
                    >
                      Edit
                    </button>
                    <button
                      className={styles.inlineAction}
                      type="button"
                      onClick={() => onRemoveCard?.(candidate.card_id)}
                    >
                      Remove
                    </button>
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
      {!readOnly ? (
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => onOpenEditor?.(null)}
          disabled={!canAddCard}
        >
          Add missed card
        </button>
      ) : null}
      <section
        className={visibleStyles.keyboardShortcuts}
        aria-label="Keyboard shortcuts"
      >
        <p className={styles.statusLabel}>Keyboard shortcuts</p>
        <dl>
          <div>
            <dt>← / →</dt>
            <dd>Previous / next frame</dd>
          </div>
          <div>
            <dt>↑ / ↓</dt>
            <dd>Previous / next proposal</dd>
          </div>
          <div>
            <dt>A</dt>
            <dd>Toggle accepted / unreviewed</dd>
          </div>
          <div>
            <dt>N</dt>
            <dd>Add missed card</dd>
          </div>
          <div>
            <dt>E</dt>
            <dd>Mark frame empty</dd>
          </div>
          <div>
            <dt>U</dt>
            <dd>Mark frame unusable</dd>
          </div>
        </dl>
      </section>
    </section>
  );
}

function CandidatePreview({
  candidate,
  sourceUrl,
  frameWidth,
  frameHeight,
  label,
}: {
  candidate: Candidate;
  sourceUrl: string | null;
  frameWidth: number;
  frameHeight: number;
  label: string;
}) {
  const bounds = candidateBounds(candidate, frameWidth, frameHeight);
  if (sourceUrl === null || bounds === null) {
    return (
      <div
        className={visibleStyles.proposalPreviewPlaceholder}
        aria-hidden="true"
      />
    );
  }
  return (
    <svg
      className={visibleStyles.proposalPreview}
      viewBox={`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`}
      role="img"
      aria-label={label}
      preserveAspectRatio="xMidYMid slice"
    >
      <image
        href={sourceUrl}
        x="0"
        y="0"
        width={frameWidth}
        height={frameHeight}
        preserveAspectRatio="none"
      />
    </svg>
  );
}

function candidateBounds(
  candidate: Candidate,
  frameWidth: number,
  frameHeight: number,
) {
  const geometry = candidate.geometry;
  const points =
    geometry.visible_region?.polygons.flat() ??
    (geometry.box_2d === undefined
      ? []
      : [
          { x: geometry.box_2d.x_min, y: geometry.box_2d.y_min },
          { x: geometry.box_2d.x_max, y: geometry.box_2d.y_max },
        ]);
  if (points.length === 0) return null;
  const xMin = Math.max(0, Math.min(...points.map((point) => point.x)));
  const yMin = Math.max(0, Math.min(...points.map((point) => point.y)));
  const xMax = Math.min(1000, Math.max(...points.map((point) => point.x)));
  const yMax = Math.min(1000, Math.max(...points.map((point) => point.y)));
  const width = Math.max(1, ((xMax - xMin) * frameWidth) / 1000);
  const height = Math.max(1, ((yMax - yMin) * frameHeight) / 1000);
  const x = (xMin * frameWidth) / 1000;
  const y = (yMin * frameHeight) / 1000;
  return { x, y, width, height };
}

function formatGeometryKind(geometry: Candidate["geometry"]): string {
  if (geometry.visible_region !== undefined) {
    return "Polygon";
  }
  const { kind } = geometry;
  if (kind === "detector-box/v1" || kind === "reviewed-box/v1") {
    return "Box";
  }
  return formatIdentifier(kind);
}

function CandidateOverlay({
  candidate,
  width,
  height,
  selected,
  reviewStatus,
}: {
  candidate: Candidate;
  width: number;
  height: number;
  selected: boolean;
  reviewStatus: FrameReviewStatus;
}) {
  const palette = overlayPalette(reviewStatus);
  const geometry = candidate.geometry;
  if (geometry.visible_region !== undefined) {
    return (
      <g
        data-card-id={candidate.card_id}
        data-selected={selected}
        data-review-state={reviewStatus}
      >
        {geometry.visible_region.polygons.map((polygon, polygonIndex) => (
          <polygon
            key={`${candidate.card_id}-polygon-${polygonIndex}`}
            points={polygon
              .map(
                (point) =>
                  `${(point.x * width) / 1000},${(point.y * height) / 1000}`,
              )
              .join(" ")}
            fill={palette.fill}
            stroke={palette.stroke}
            strokeWidth={
              selected ? Math.max(2, width / 180) : Math.max(1, width / 250)
            }
          />
        ))}
      </g>
    );
  }
  const box = geometry.box_2d;
  if (box === undefined) return null;
  return (
    <g
      data-card-id={candidate.card_id}
      data-selected={selected}
      data-review-state={reviewStatus}
    >
      <rect
        x={(box.x_min * width) / 1000}
        y={(box.y_min * height) / 1000}
        width={((box.x_max - box.x_min) * width) / 1000}
        height={((box.y_max - box.y_min) * height) / 1000}
        fill={palette.fill}
        stroke={palette.stroke}
        strokeDasharray="8 5"
        strokeWidth={
          selected ? Math.max(2, width / 180) : Math.max(1, width / 250)
        }
      />
    </g>
  );
}

function overlayPalette(reviewStatus: FrameReviewStatus): {
  fill: string;
  stroke: string;
} {
  if (reviewStatus === "accepted") {
    return { fill: "rgba(85, 213, 137, 0.2)", stroke: "#55d589" };
  }
  if (reviewStatus === "empty" || reviewStatus === "unusable") {
    return { fill: "rgba(255, 125, 114, 0.16)", stroke: "#ff7d72" };
  }
  return { fill: "rgba(242, 193, 95, 0.2)", stroke: "#f2c15f" };
}
