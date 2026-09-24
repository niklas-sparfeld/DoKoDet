import { createPortal } from "react-dom";

import styles from "./PipelineVisibleCardEditor.module.css";
import { formatIdentifier } from "./PipelineVisibleCardFormatting";
import {
  applyPoseSceneAction,
  type PoseSceneEnvelope,
  type PoseCard,
} from "./PoseBasedVisibleCardScene";
import type {
  Candidate,
  EditableFrame,
  IgnoreRegion,
} from "./PipelineVisibleCardTypes";
import type {
  WorkbenchPreferences,
  WorkbenchSelection,
} from "./VisibleCardReviewWorkbenchState";
import {
  candidateIsCoveredByIgnoreRegions,
  clamp,
  posePolygon,
} from "./VisibleCardWorkbenchGeometry";
import type { VisibleCardEditorSummary } from "./VisibleCardWorkbenchControls";

export function WorkbenchProposalColumn({
  frame,
  candidates,
  scene,
  activeTool,
  sourceUrl,
  frameWidth,
  frameHeight,
  readOnly,
  selection,
  editor,
  editorError,
  selectedCandidateIds,
  onToggleCandidateSelection,
  onSelectCandidate,
  onSelectIgnoreRegion,
  onSelectEditorPolygon,
  onSelectVirtualCard,
  onSceneAction,
  proposalSlot,
}: {
  frame: EditableFrame;
  candidates: Candidate[];
  scene: PoseSceneEnvelope | null;
  activeTool: WorkbenchPreferences["activeTool"];
  sourceUrl: string | null;
  frameWidth: number;
  frameHeight: number;
  readOnly: boolean;
  selection: WorkbenchSelection | null;
  editor: VisibleCardEditorSummary | null;
  editorError: string | null;
  selectedCandidateIds: string[];
  onToggleCandidateSelection?: (cardId: string) => void;
  onSelectCandidate: (candidate: Candidate, polygonIndex?: number) => void;
  onSelectIgnoreRegion?: (region: IgnoreRegion) => void;
  onSelectEditorPolygon?: (polygonIndex: number) => void;
  onSelectVirtualCard: (cardId: string) => void;
  onSceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
  proposalSlot: HTMLElement | null;
}) {
  const stackingOrder =
    scene === null
      ? []
      : [
          ...scene.scene.stacking_order.card_ids,
          ...scene.scene.poses
            .map((pose) => pose.card_id)
            .filter(
              (cardId) => !scene.scene.stacking_order.card_ids.includes(cardId),
            ),
        ].filter((cardId) =>
          scene.scene.poses.some((pose) => pose.card_id === cardId),
        );
  const poseById = new Map(
    (scene?.scene.poses ?? []).map((pose) => [pose.card_id, pose]),
  );
  const candidateById = new Map(candidates.map((item) => [item.card_id, item]));
  const isStackOrderMode = activeTool === "virtual_cards" && scene !== null;
  const content = (
    <section
      className={styles.proposalColumn}
      aria-label={
        isStackOrderMode ? "Card stack order" : "Visible-card proposals"
      }
    >
      {editorError !== null ? (
        <p className={styles.inlineFormError} role="alert">
          {editorError}
        </p>
      ) : null}
      {isStackOrderMode ? (
        <section className={styles.stackOrderSection} aria-label="Stack order">
          <ol className={styles.proposalItems}>
            {stackingOrder.map((cardId, index) => {
              const pose = poseById.get(cardId);
              if (pose === undefined) return null;
              const candidate =
                (typeof pose.source_suggestion_id !== "string"
                  ? undefined
                  : candidateById.get(pose.source_suggestion_id)) ??
                candidateById.get(cardId);
              const previewCandidate =
                candidate ??
                (scene === null
                  ? null
                  : virtualCardPreviewCandidate(
                      pose,
                      scene,
                      frameWidth,
                      frameHeight,
                    ));
              const selected =
                selection?.type === "virtual_card" && selection.id === cardId;
              return (
                <li
                  key={cardId}
                  className={styles.stackOrderRow}
                  draggable={!readOnly}
                  data-card-id={cardId}
                  data-stacking-index={index}
                  data-selected={selected ? "true" : undefined}
                  onDragStart={(event) => {
                    event.dataTransfer.setData("text/plain", cardId);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  onDragOver={(event) => {
                    if (!readOnly) {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = "move";
                    }
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    const draggedCardId =
                      event.dataTransfer.getData("text/plain");
                    const currentIndex = stackingOrder.indexOf(draggedCardId);
                    if (
                      readOnly ||
                      currentIndex < 0 ||
                      draggedCardId === cardId ||
                      currentIndex === index
                    ) {
                      return;
                    }
                    onSceneAction(
                      { type: "place", cardId: draggedCardId, index },
                      `Card moved to stack position ${index + 1}.`,
                    );
                  }}
                >
                  <span className={styles.stackOrderRank} aria-hidden="true">
                    {index + 1}
                  </span>
                  <button
                    className={styles.stackOrderSelect}
                    type="button"
                    aria-label={`Select virtual card at stack position ${index + 1}`}
                    aria-pressed={selected}
                    onClick={() => onSelectVirtualCard(cardId)}
                  >
                    {previewCandidate !== null ? (
                      <CandidatePreview
                        candidate={previewCandidate}
                        sourceUrl={sourceUrl}
                        frameWidth={frameWidth}
                        frameHeight={frameHeight}
                        label={`Card at stack position ${index + 1} preview`}
                      />
                    ) : (
                      <span
                        className={styles.stackOrderPlaceholder}
                        aria-hidden="true"
                      >
                        ◇
                      </span>
                    )}
                    <span className={styles.proposalDetails}>
                      <strong>{candidate?.side ?? "Virtual card"}</strong>
                      <span>
                        {index === 0
                          ? "Front"
                          : index === stackingOrder.length - 1
                            ? "Back"
                            : `Layer ${index + 1}`}
                      </span>
                    </span>
                  </button>
                  <span className={styles.stackOrderActions}>
                    <button
                      type="button"
                      aria-label={`Move card at stack position ${index + 1} toward front`}
                      disabled={readOnly || index === 0}
                      onClick={() =>
                        onSceneAction(
                          { type: "place", cardId, index: index - 1 },
                          `Card moved to stack position ${index}.`,
                        )
                      }
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      aria-label={`Move card at stack position ${index + 1} toward back`}
                      disabled={readOnly || index === stackingOrder.length - 1}
                      onClick={() =>
                        onSceneAction(
                          { type: "place", cardId, index: index + 1 },
                          `Card moved to stack position ${index + 2}.`,
                        )
                      }
                    >
                      ↓
                    </button>
                  </span>
                </li>
              );
            })}
          </ol>
          {!readOnly && stackingOrder.length > 1 ? (
            <p className={styles.stackOrderHint}>
              Drag a card to change its stack position.
            </p>
          ) : null}
        </section>
      ) : null}
      {candidates.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No proposals. Add a visible card or review this frame as empty.
        </p>
      ) : (
        <ol className={styles.proposalItems}>
          {candidates.map((candidate, index) => {
            const polygonCount =
              editor?.cardId === candidate.card_id
                ? editor.polygonCount
                : (candidate.geometry.visible_region?.polygons.length ?? 1);
            const hasMultiplePolygons = polygonCount > 1;
            const alreadyIgnored = candidateIsCoveredByIgnoreRegions(
              candidate,
              frame.outcome.ignored_regions,
            );
            const markedForIgnore =
              !alreadyIgnored &&
              selectedCandidateIds.includes(candidate.card_id);
            const isEditorSelection =
              (selection?.id === candidate.card_id &&
                (selection.type === "visible_card" ||
                  selection.type === "polygon")) ||
              editor?.cardId === candidate.card_id;
            const statusLabel = alreadyIgnored
              ? "Already ignored"
              : markedForIgnore
                ? "Marked for ignore"
                : "Detector suggestion";
            return (
              <li key={candidate.card_id}>
                <div
                  className={styles.proposalRow}
                  data-already-ignored={alreadyIgnored ? "true" : undefined}
                  data-marked-for-ignore={markedForIgnore ? "true" : undefined}
                >
                  {!readOnly ? (
                    <label className={styles.proposalCheckbox}>
                      <input
                        type="checkbox"
                        aria-label={`Select proposal ${index + 1} for ignore region`}
                        checked={markedForIgnore || alreadyIgnored}
                        disabled={alreadyIgnored}
                        onChange={() =>
                          onToggleCandidateSelection?.(candidate.card_id)
                        }
                      />
                    </label>
                  ) : null}
                  <button
                    className={styles.proposalSelect}
                    type="button"
                    aria-label={`Select proposal ${index + 1}`}
                    aria-pressed={isEditorSelection}
                    data-has-selection={readOnly ? undefined : "true"}
                    data-selected={isEditorSelection ? "true" : undefined}
                    onClick={() => onSelectCandidate(candidate)}
                  >
                    <CandidatePreview
                      candidate={candidate}
                      sourceUrl={sourceUrl}
                      frameWidth={frameWidth}
                      frameHeight={frameHeight}
                      label={`Proposal ${index + 1} crop preview`}
                    />
                    <span className={styles.proposalDetails}>
                      <strong>Proposal {index + 1}</strong>
                      <span>{statusLabel}</span>
                      <small>{formatIdentifier(candidate.side)}</small>
                      <small>{formatGeometryKind(candidate.geometry)}</small>
                    </span>
                  </button>
                  {hasMultiplePolygons ? (
                    <div
                      className={styles.proposalPolygonSelectors}
                      aria-label={`Polygons for proposal ${index + 1}`}
                    >
                      {Array.from(
                        { length: polygonCount },
                        (_, polygonIndex) => (
                          <button
                            className={styles.proposalPolygonSelector}
                            type="button"
                            key={`polygon-${polygonIndex}`}
                            aria-label={`Select polygon ${polygonIndex + 1} for proposal ${index + 1}`}
                            aria-pressed={
                              editor?.cardId === candidate.card_id
                                ? editor.polygonIndex === polygonIndex
                                : selection?.type === "polygon" &&
                                  selection.id === candidate.card_id &&
                                  selection.polygonIndex === polygonIndex
                            }
                            onClick={(event) => {
                              event.stopPropagation();
                              if (editor?.cardId === candidate.card_id) {
                                onSelectEditorPolygon?.(polygonIndex);
                              } else {
                                onSelectCandidate(candidate, polygonIndex);
                              }
                            }}
                          >
                            {polygonIndex + 1}
                          </button>
                        ),
                      )}
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {frame.outcome.ignored_regions.length > 0 ? (
        <section
          className={styles.ignoreRegionList}
          aria-label="Visible-card ignore regions"
        >
          <p className={styles.statusLabel}>Ignore regions</p>
          <ol className={styles.proposalItems}>
            {frame.outcome.ignored_regions.map((region, index) => (
              <li key={region.region_id}>
                <div className={styles.ignoreRegionRow}>
                  <span
                    className={styles.ignoreRegionSwatch}
                    aria-hidden="true"
                  />
                  <button
                    className={styles.proposalSelect}
                    type="button"
                    aria-label={`Select ignore region ${index + 1}`}
                    aria-pressed={selection?.id === region.region_id}
                    onClick={() => onSelectIgnoreRegion?.(region)}
                  >
                    <span className={styles.proposalDetails}>
                      <strong>Ignore region {index + 1}</strong>
                      <span>Untidy stack</span>
                      <small>
                        {region.geometry.polygons.length} polygon
                        {region.geometry.polygons.length === 1 ? "" : "s"}
                      </small>
                    </span>
                  </button>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </section>
  );
  return proposalSlot === null ? content : createPortal(content, proposalSlot);
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
      <div className={styles.proposalPreviewPlaceholder} aria-hidden="true" />
    );
  }
  return (
    <svg
      className={styles.proposalPreview}
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

function virtualCardPreviewCandidate(
  pose: PoseCard,
  scene: PoseSceneEnvelope,
  frameWidth: number,
  frameHeight: number,
): Candidate | null {
  const polygon = posePolygon(pose, scene.projection, "camera");
  if (polygon.length !== 4 || frameWidth <= 0 || frameHeight <= 0) return null;
  return {
    card_id: pose.card_id,
    geometry: {
      kind: "virtual-card-preview/v1",
      visible_region: {
        polygons: [
          polygon.map(([x, y]) => ({
            x: clamp((x / frameWidth) * 1000, 1000),
            y: clamp((y / frameHeight) * 1000, 1000),
          })),
        ],
      },
    },
    normalization: {},
    side: "unknown",
  };
}

function formatGeometryKind(geometry: Candidate["geometry"]): string {
  if (geometry.visible_region !== undefined) return "Polygon";
  const { kind } = geometry;
  if (kind === "detector-box/v1" || kind === "reviewed-box/v1") return "Box";
  return formatIdentifier(kind);
}
