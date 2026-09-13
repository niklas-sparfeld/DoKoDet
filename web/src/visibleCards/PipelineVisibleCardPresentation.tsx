import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { pipelineDerivedFramePath } from "../api/client";
import styles from "../App.module.css";
import { ShortcutButton } from "../pipeline/ShortcutButton";
import {
  TimelineRailSeekingControls,
  TimelineRailSeekingPortal,
  useTimelineRailSeekingSlot,
} from "../pipeline/TimelineRailSeekingControls";
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
  IgnoreRegion,
} from "./PipelineVisibleCardTypes";

export function visibleCardReviewPrewarmUrls(
  recordingId: string,
  frame: EditableFrame,
): string[] {
  const identity = frame.outcome.frame_identity;
  return identity === null
    ? []
    : [pipelineDerivedFramePath(recordingId, identity.requested_time_us)];
}

export function VisibleCardReviewControls({
  editable,
  hasPrevious,
  hasNext,
  selectedFrame,
  onPrevious,
  onNext,
  onAccept,
  onAddCard,
  selectedCandidateCount,
  onConvertToIgnoreRegion,
  onCreateIgnoreRegion,
  onMarkEmpty,
  onMarkUnusable,
}: {
  editable: boolean;
  hasPrevious: boolean;
  hasNext: boolean;
  selectedFrame: EditableFrame | null;
  onPrevious: () => void;
  onNext: () => void;
  onAccept: () => void;
  onAddCard: () => void;
  selectedCandidateCount: number;
  onConvertToIgnoreRegion: () => void;
  onCreateIgnoreRegion: () => void;
  onMarkEmpty: () => void;
  onMarkUnusable: () => void;
}) {
  const reviewStatus =
    selectedFrame === null ? null : frameReviewStatus(selectedFrame);
  const canAccept =
    editable &&
    selectedFrame !== null &&
    selectedFrame.outcome.status === "detected";
  const canAddCard =
    editable &&
    selectedFrame !== null &&
    selectedFrame.outcome.frame_identity !== null;
  const timelineSeekingSlot = useTimelineRailSeekingSlot();
  const seekingGroups = [
    {
      label: "Frame navigation",
      controls: [
        {
          label: "Previous frame",
          symbol: "⏮",
          shortcut: "ArrowLeft",
          ariaShortcut: "ArrowLeft",
          disabled: !hasPrevious,
          disabledReason: "There is no previous frame.",
          onClick: onPrevious,
        },
        {
          label: "Next frame",
          symbol: "⏭",
          shortcut: "ArrowRight",
          ariaShortcut: "ArrowRight",
          disabled: !hasNext,
          disabledReason: "There is no next frame.",
          onClick: onNext,
        },
      ],
    },
  ] as const;
  const seeking =
    timelineSeekingSlot !== null ? (
      <TimelineRailSeekingPortal
        slot={timelineSeekingSlot}
        groups={seekingGroups}
      />
    ) : null;
  return (
    <>
      {seeking}
      <aside
        className={visibleStyles.controlSidebar}
        aria-label="Visible-card review controls"
      >
        <p className={styles.statusLabel}>Review controls</p>
        {timelineSeekingSlot === null ? (
          <TimelineRailSeekingControls groups={seekingGroups} />
        ) : null}
        {editable ? (
          <div className={visibleStyles.controlGroup}>
            <ShortcutButton
              label={
                reviewStatus === "accepted" ? "Mark unreviewed" : "Accept frame"
              }
              shortcut="A"
              ariaShortcut="A"
              variant="primary"
              disabled={!canAccept}
              disabledReason="Accept is available for detected frames."
              onClick={onAccept}
            />
            <ShortcutButton
              label="Add missed card"
              shortcut="N"
              ariaShortcut="N"
              variant="primary"
              disabled={!canAddCard}
              disabledReason="A resolved source frame is required to add a card."
              onClick={onAddCard}
            />
            <ShortcutButton
              label="Convert selected to ignore region"
              shortcut="I"
              ariaShortcut="I"
              variant="primary"
              disabled={selectedCandidateCount === 0}
              disabledReason="Select one or more proposals to convert them to an ignore region."
              onClick={onConvertToIgnoreRegion}
            />
            <button
              className={styles.inlineAction}
              type="button"
              disabled={!canAddCard}
              onClick={onCreateIgnoreRegion}
            >
              Draw ignore region
            </button>
            <ShortcutButton
              label="Reviewed empty frame"
              shortcut="E"
              ariaShortcut="E"
              disabled={selectedFrame === null}
              disabledReason="Select a frame before marking it empty."
              onClick={onMarkEmpty}
            />
            <ShortcutButton
              label="Unusable frame"
              shortcut="U"
              ariaShortcut="U"
              disabled={selectedFrame === null}
              disabledReason="Select a frame before marking it unusable."
              onClick={onMarkUnusable}
            />
          </div>
        ) : null}
      </aside>
    </>
  );
}

export function VisibleCardFramePanel({
  recordingId,
  frame,
  editor,
  selectedCandidateId,
  editorError,
  selectedCandidateIds,
  onToggleCandidateSelection,
  onOpenIgnoreRegion,
  onRemoveIgnoreRegion,
  onSelectCandidate,
  onSelectCandidatePolygon,
  onOpenEditor,
  onCancelEditor,
  onRemoveCard,
  onPointerMove,
  onCanvasPointerDown,
  onPointerUp,
  onPointPointerDown,
  onDeleteSelectedPoint,
  onSelectEditorPolygon,
  onAddEditorPolygon,
  onRemoveEditorPolygon,
  readOnly,
  proposalSlot,
}: {
  recordingId: string;
  frame: EditableFrame;
  editor: EditorState | null;
  selectedCandidateId: string | null;
  editorError: string | null;
  selectedCandidateIds: string[];
  onToggleCandidateSelection: (cardId: string) => void;
  onOpenIgnoreRegion?: (region: IgnoreRegion) => void;
  onRemoveIgnoreRegion?: (regionId: string) => void;
  onSelectCandidate?: (candidate: Candidate) => void;
  onSelectCandidatePolygon?: (
    candidate: Candidate,
    polygonIndex: number,
  ) => void;
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
  onDeleteSelectedPoint: (event: ReactKeyboardEvent<SVGSVGElement>) => void;
  onSelectEditorPolygon?: (polygonIndex: number) => void;
  onAddEditorPolygon?: () => void;
  onRemoveEditorPolygon?: () => void;
  readOnly: boolean;
  proposalSlot: HTMLElement | null;
}) {
  const identity = frame.outcome.frame_identity;
  const width = identity?.width ?? 1;
  const height = identity?.height ?? 1;
  const sourceUrl = visibleCardReviewPrewarmUrls(recordingId, frame)[0] ?? null;
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
              aria-label={`${frame.outcome.candidates.length} visible-card proposal${frame.outcome.candidates.length === 1 ? "" : "s"}${frame.outcome.ignored_regions.length > 0 ? ` and ${frame.outcome.ignored_regions.length} ignore region${frame.outcome.ignored_regions.length === 1 ? "" : "s"}` : ""}`}
              onPointerMove={onPointerMove}
              onPointerDown={onCanvasPointerDown}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              onKeyDown={onDeleteSelectedPoint}
              style={{
                pointerEvents:
                  editor === null && onSelectCandidatePolygon === undefined
                    ? "none"
                    : "auto",
              }}
            >
              {frame.outcome.ignored_regions.map((region) => (
                <IgnoreRegionOverlay
                  key={region.region_id}
                  region={region}
                  width={width}
                  height={height}
                  selected={editor?.regionId === region.region_id}
                  interactive={!readOnly && onOpenIgnoreRegion !== undefined}
                  onOpen={() => onOpenIgnoreRegion?.(region)}
                />
              ))}
              {frame.outcome.candidates.map((candidate) => (
                <CandidateOverlay
                  key={candidate.card_id}
                  candidate={candidate}
                  width={width}
                  height={height}
                  selected={
                    candidate.card_id === selectedCandidateId ||
                    selectedCandidateIds.includes(candidate.card_id)
                  }
                  reviewStatus={frameReviewStatus(frame)}
                  interactive={
                    editor === null && onSelectCandidatePolygon !== undefined
                  }
                  onSelectPolygon={(polygonIndex) =>
                    onSelectCandidatePolygon?.(candidate, polygonIndex)
                  }
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
                      fill={
                        editor.polygonIndex === polygonIndex
                          ? "rgba(255, 210, 79, 0.25)"
                          : "rgba(255, 210, 79, 0.12)"
                      }
                      stroke={
                        editor.polygonIndex === polygonIndex
                          ? "#ffd24f"
                          : "#c79f34"
                      }
                      strokeDasharray="4 3"
                      strokeWidth={polygonStrokeWidth(width)}
                    />
                  ) : null}
                  {polygon.map((point, pointIndex) => (
                    <circle
                      key={`${point.x}:${point.y}:${pointIndex}`}
                      cx={(point.x * width) / 1000}
                      cy={(point.y * height) / 1000}
                      r={Math.max(1, width / 160)}
                      fill={
                        editor.polygonIndex === polygonIndex &&
                        editor.selectedPointIndex === pointIndex
                          ? "#ffffff"
                          : "#ffd24f"
                      }
                      stroke="#ffd24f"
                      strokeWidth={Math.max(0.5, width / 800)}
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
          selectedCandidateIds={selectedCandidateIds}
          onToggleCandidateSelection={onToggleCandidateSelection}
          selectedCandidateId={selectedCandidateId}
          onSelectCandidate={onSelectCandidate}
          onOpenEditor={onOpenEditor}
          onRemoveCard={onRemoveCard}
          onOpenIgnoreRegion={onOpenIgnoreRegion}
          onRemoveIgnoreRegion={onRemoveIgnoreRegion}
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
            point. Changes are saved automatically and you can keep editing.
            Select a point and press Backspace or Delete to remove it. Select a
            polygon below the frame before you add points. For a missed card,
            click three points on the frame to create its visible region.
          </p>
          <section
            className={visibleStyles.polygonList}
            aria-label="Visible region polygons"
          >
            <p className={styles.statusLabel}>Visible region polygons</p>
            <div className={visibleStyles.polygonActions}>
              {editor.polygons.map((polygon, polygonIndex) => (
                <button
                  className={styles.inlineAction}
                  type="button"
                  key={`polygon-${polygonIndex}`}
                  aria-pressed={editor.polygonIndex === polygonIndex}
                  data-selected={editor.polygonIndex === polygonIndex}
                  onClick={() => onSelectEditorPolygon?.(polygonIndex)}
                >
                  Polygon {polygonIndex + 1} ({polygon.length} point
                  {polygon.length === 1 ? "" : "s"})
                </button>
              ))}
              <button
                className={styles.inlineAction}
                type="button"
                onClick={onAddEditorPolygon}
              >
                Add polygon
              </button>
              <button
                className={styles.inlineAction}
                type="button"
                onClick={onRemoveEditorPolygon}
                disabled={editor.polygons.length <= 1}
              >
                Remove polygon
              </button>
            </div>
          </section>
          {editorError !== null ? (
            <p className={visibleStyles.inlineFormError}>{editorError}</p>
          ) : null}
          <div className={visibleStyles.actionButtons}>
            <ShortcutButton
              label="Close editor"
              shortcut="Esc"
              ariaShortcut="Escape"
              onClick={onCancelEditor ?? (() => undefined)}
            />
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
  selectedCandidateIds,
  onToggleCandidateSelection,
  selectedCandidateId,
  onSelectCandidate,
  onOpenEditor,
  onRemoveCard,
  onOpenIgnoreRegion,
  onRemoveIgnoreRegion,
}: {
  frame: EditableFrame;
  sourceUrl: string | null;
  readOnly: boolean;
  selectedCandidateIds: string[];
  onToggleCandidateSelection: (cardId: string) => void;
  selectedCandidateId: string | null;
  onSelectCandidate?: (candidate: Candidate) => void;
  onOpenEditor?: (candidate: Candidate | null) => void;
  onRemoveCard?: (cardId: string) => void;
  onOpenIgnoreRegion?: (region: IgnoreRegion) => void;
  onRemoveIgnoreRegion?: (regionId: string) => void;
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
                {!readOnly ? (
                  <label className={visibleStyles.proposalCheckbox}>
                    <input
                      type="checkbox"
                      aria-label={`Select proposal ${index + 1} for ignore region`}
                      checked={selectedCandidateIds.includes(candidate.card_id)}
                      onChange={() =>
                        onToggleCandidateSelection(candidate.card_id)
                      }
                    />
                    <span className={styles.visuallyHidden}>
                      Select for ignore region
                    </span>
                  </label>
                ) : null}
                <button
                  className={visibleStyles.proposalSelect}
                  type="button"
                  aria-label={`Select proposal ${index + 1}`}
                  aria-pressed={candidate.card_id === selectedCandidateId}
                  data-selected={candidate.card_id === selectedCandidateId}
                  data-has-selection={!readOnly}
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
                    <small>{formatIdentifier(candidate.side)}</small>
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
      {frame.outcome.ignored_regions.length > 0 ? (
        <section
          className={visibleStyles.ignoreRegionList}
          aria-label="Visible-card ignore regions"
        >
          <p className={styles.statusLabel}>Ignore regions</p>
          <ol className={visibleStyles.proposalItems}>
            {frame.outcome.ignored_regions.map((region, index) => (
              <li key={region.region_id}>
                <div className={visibleStyles.ignoreRegionRow}>
                  <span
                    className={visibleStyles.ignoreRegionSwatch}
                    aria-hidden="true"
                  />
                  <span className={visibleStyles.proposalDetails}>
                    <strong>Ignore region {index + 1}</strong>
                    <span>Untidy stack</span>
                    <small>
                      {region.geometry.polygons.length} polygon
                      {region.geometry.polygons.length === 1 ? "" : "s"}
                    </small>
                  </span>
                  {!readOnly ? (
                    <div className={visibleStyles.actionButtons}>
                      <button
                        className={styles.inlineAction}
                        type="button"
                        onClick={() => onOpenIgnoreRegion?.(region)}
                      >
                        Edit
                      </button>
                      <button
                        className={styles.inlineAction}
                        type="button"
                        onClick={() => onRemoveIgnoreRegion?.(region.region_id)}
                      >
                        Delete
                      </button>
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
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

function IgnoreRegionOverlay({
  region,
  width,
  height,
  selected,
  interactive,
  onOpen,
}: {
  region: IgnoreRegion;
  width: number;
  height: number;
  selected: boolean;
  interactive: boolean;
  onOpen: () => void;
}) {
  return (
    <g
      data-ignore-region-id={region.region_id}
      data-selected={selected}
      data-reason={region.reason}
    >
      {region.geometry.polygons.map((polygon, polygonIndex) => (
        <polygon
          key={`${region.region_id}-polygon-${polygonIndex}`}
          points={polygon
            .map(
              (point) =>
                `${(point.x * width) / 1000},${(point.y * height) / 1000}`,
            )
            .join(" ")}
          fill="rgba(255, 170, 96, 0.22)"
          stroke={selected ? "#ffffff" : "#f0a35b"}
          strokeDasharray="3 3"
          strokeWidth={polygonStrokeWidth(width)}
          role={interactive ? "button" : undefined}
          tabIndex={interactive ? 0 : undefined}
          aria-label={
            interactive
              ? `Edit ignore region ${region.region_id}, polygon ${polygonIndex + 1}`
              : undefined
          }
          onClick={
            interactive
              ? (event) => {
                  event.stopPropagation();
                  onOpen();
                }
              : undefined
          }
          onKeyDown={
            interactive
              ? (event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onOpen();
                  }
                }
              : undefined
          }
        />
      ))}
    </g>
  );
}

function CandidateOverlay({
  candidate,
  width,
  height,
  selected,
  reviewStatus,
  interactive,
  onSelectPolygon,
}: {
  candidate: Candidate;
  width: number;
  height: number;
  selected: boolean;
  reviewStatus: FrameReviewStatus;
  interactive: boolean;
  onSelectPolygon: (polygonIndex: number) => void;
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
            stroke={selected ? "#ffd24f" : palette.stroke}
            strokeWidth={polygonStrokeWidth(width)}
            role={interactive ? "button" : undefined}
            aria-label={
              interactive
                ? `Edit ${candidate.card_id}, polygon ${polygonIndex + 1}`
                : undefined
            }
            tabIndex={interactive ? 0 : undefined}
            onClick={
              interactive
                ? (event) => {
                    event.stopPropagation();
                    onSelectPolygon(polygonIndex);
                  }
                : undefined
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
        stroke={selected ? "#ffd24f" : palette.stroke}
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
  return { fill: "rgba(196, 154, 239, 0.2)", stroke: "#c49aef" };
}

function polygonStrokeWidth(width: number): number {
  return Math.max(1.25, width / 300);
}
