import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  WheelEvent as ReactWheelEvent,
} from "react";
import {
  candidatePolygons,
  candidatePosePolygon,
  cameraViewBox,
  editorPoint,
  isSelected,
  mappingCornerRadius,
  mappingStrokeWidth,
  pathAttribute,
  pointsAttribute,
  rectifiedBackgroundPatches,
  renderOrder,
  rotationHandle,
  strokeWidth,
  tableViewBox,
  transformSourcePolygon,
} from "./VisibleCardWorkbenchSurfaceGeometry";
import type { CalibrationRefinementResponse } from "../api/client";
import type { CalibrationFitDiagnosticOutline } from "./CalibrationFitDiagnostics";
import styles from "./PipelineVisibleCardEditor.module.css";
import type { WorkbenchCalibrationAnchor } from "./VisibleCardWorkbenchControls";
import { clamp, posePolygon } from "./VisibleCardWorkbenchGeometry";
import {
  ANCHOR_STATES,
  projectImagePointToTable,
  projectTablePoint,
  type AnchorState,
  type CardSceneProjection,
  type PoseCard,
  type PoseSceneEnvelope,
  type TablePoint,
} from "./PoseBasedVisibleCardScene";
import type {
  Candidate,
  EditableFrame,
  EditorState,
  Point,
} from "./PipelineVisibleCardTypes";
import type {
  WorkbenchLayer,
  WorkbenchPreferences,
  WorkbenchSelection,
  WorkbenchViewpoint,
} from "./VisibleCardReviewWorkbenchState";

type WorkbenchPointHandler = (
  event: ReactPointerEvent<SVGSVGElement>,
  point: Point | null,
) => void;

export function WorkbenchSurface({
  frame,
  candidates,
  scene,
  sourceUrl,
  width,
  height,
  viewpoint,
  activeTool,
  enabledLayers,
  selection,
  viewport,
  gestureViewBox,
  candidateProjection,
  calibrationFitOutlines,
  mappingAnchors,
  editor,
  includeIgnoreRegionCount,
  onSelect,
  onKeyDown,
  onPointPointerDown,
  onCanvasPointerDown,
  onPointerMove,
  onPointerLeave,
  onPointerUp,
  onPointerCancel,
  onWheel,
  onDeleteSelectedPoint,
  onVirtualCardPointerDown,
  onVirtualCardKeyDown,
  onMappingAnchorPointerDown,
  onMappingAnchorCornerSelect,
}: {
  frame: EditableFrame;
  candidates: Candidate[];
  scene: PoseSceneEnvelope | null;
  sourceUrl: string | null;
  width: number;
  height: number;
  viewpoint: WorkbenchViewpoint;
  activeTool: WorkbenchPreferences["activeTool"];
  enabledLayers: WorkbenchLayer[];
  selection: WorkbenchSelection | null;
  viewport: { zoom: number; pan: { x: number; y: number } };
  gestureViewBox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  candidateProjection: CardSceneProjection | null;
  calibrationFitOutlines: CalibrationFitDiagnosticOutline[];
  mappingAnchors: WorkbenchCalibrationAnchor[];
  editor: EditorState | null;
  includeIgnoreRegionCount: boolean;
  onSelect: (selection: WorkbenchSelection) => void;
  onKeyDown: (event: ReactKeyboardEvent<SVGSVGElement>) => void;
  onPointPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
  onCanvasPointerDown?: WorkbenchPointHandler;
  onPointerMove?: WorkbenchPointHandler;
  onPointerLeave?: WorkbenchPointHandler;
  onPointerUp?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointerCancel?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onWheel?: (event: ReactWheelEvent<SVGSVGElement>) => void;
  onDeleteSelectedPoint?: (event: ReactKeyboardEvent<SVGSVGElement>) => void;
  onVirtualCardPointerDown?: (
    event: ReactPointerEvent<SVGElement>,
    cardId: string,
    kind: "move" | "rotate",
  ) => void;
  onVirtualCardKeyDown?: (
    event: ReactKeyboardEvent<SVGPolygonElement>,
    cardId: string,
  ) => void;
  onMappingAnchorPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    cornerIndex: number,
  ) => void;
  onMappingAnchorCornerSelect: (cornerIndex: number) => void;
}) {
  const count = frame.outcome.candidates.length;
  const proposalLabel = `${count} visible-card proposal${count === 1 ? "" : "s"}${includeIgnoreRegionCount && frame.outcome.ignored_regions.length > 0 ? ` and ${frame.outcome.ignored_regions.length} ignore region${frame.outcome.ignored_regions.length === 1 ? "" : "s"}` : ""}`;
  if (viewpoint === "rectified" && scene !== null) {
    const viewBox =
      gestureViewBox ?? tableViewBox(scene.scene, scene.projection, viewport);
    return (
      <svg
        className={styles.workbenchRectifiedSurface}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
        role="img"
        aria-label={`Rectified visible-card workbench with ${proposalLabel}`}
        tabIndex={0}
        onKeyDown={(event) => {
          onKeyDown(event);
          onDeleteSelectedPoint?.(event);
        }}
        onPointerDown={(event) =>
          onCanvasPointerDown?.(
            event,
            sourcePointFromEvent(
              event,
              "rectified",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerMove={(event) =>
          onPointerMove?.(
            event,
            sourcePointFromEvent(
              event,
              "rectified",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerLeave={(event) =>
          onPointerLeave?.(
            event,
            sourcePointFromEvent(
              event,
              "rectified",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onWheel={onWheel}
      >
        {sourceUrl !== null ? (
          <RectifiedSourceFrame
            sourceUrl={sourceUrl}
            width={width}
            height={height}
            homography={scene.projection.table_to_image_homography}
            clipPrefix={`workbench-${frame.itemId}-background`}
          />
        ) : null}
        {renderLayers({
          frame,
          candidates,
          scene,
          viewpoint,
          width,
          height,
          zoom: viewport.zoom,
          activeTool,
          enabledLayers,
          selection,
          candidateProjection,
          mappingAnchors,
          onSelect,
          onVirtualCardPointerDown,
          onVirtualCardKeyDown,
          onMappingAnchorPointerDown,
          onMappingAnchorCornerSelect,
        })}
        {renderCalibrationFitOutlines(
          calibrationFitOutlines,
          viewpoint,
          width,
          height,
          scene,
          candidates,
        )}
        {renderEditorOverlay({
          editor,
          activeTool,
          viewpoint,
          width,
          height,
          scene,
          onPointPointerDown,
        })}
      </svg>
    );
  }
  const viewBox = cameraViewBox(width, height, viewport);
  return (
    <div
      className={styles.workbenchCameraViewport}
      style={
        {
          "--workbench-frame-aspect-ratio": `${width} / ${height}`,
        } as CSSProperties
      }
    >
      <svg
        className={styles.workbenchCameraSurface}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={proposalLabel}
        tabIndex={0}
        onKeyDown={(event) => {
          onKeyDown(event);
          onDeleteSelectedPoint?.(event);
        }}
        onPointerDown={(event) =>
          onCanvasPointerDown?.(
            event,
            sourcePointFromEvent(
              event,
              "camera",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerMove={(event) =>
          onPointerMove?.(
            event,
            sourcePointFromEvent(
              event,
              "camera",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerLeave={(event) =>
          onPointerLeave?.(
            event,
            sourcePointFromEvent(
              event,
              "camera",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onWheel={onWheel}
      >
        {sourceUrl !== null ? (
          <image
            href={sourceUrl}
            x={0}
            y={0}
            width={width}
            height={height}
            preserveAspectRatio="none"
            pointerEvents="none"
            data-workbench-background="camera"
            aria-hidden="true"
          />
        ) : null}
        {renderLayers({
          frame,
          candidates,
          scene,
          viewpoint: "camera",
          width,
          height,
          zoom: viewport.zoom,
          activeTool,
          enabledLayers,
          selection,
          candidateProjection,
          mappingAnchors,
          onSelect,
          onVirtualCardPointerDown,
          onVirtualCardKeyDown,
          onMappingAnchorPointerDown,
          onMappingAnchorCornerSelect,
        })}
        {renderCalibrationFitOutlines(
          calibrationFitOutlines,
          "camera",
          width,
          height,
          scene,
          candidates,
        )}
        {renderEditorOverlay({
          editor,
          activeTool,
          viewpoint: "camera",
          width,
          height,
          scene,
          onPointPointerDown,
        })}
      </svg>
    </div>
  );
}

function renderCalibrationFitOutlines(
  outlines: CalibrationFitDiagnosticOutline[],
  viewpoint: WorkbenchViewpoint,
  width: number,
  height: number,
  scene: PoseSceneEnvelope | null,
  candidates: Candidate[],
) {
  return outlines.map((outline) => {
    const projectedPoints = outline.points
      .map((point): [number, number] | null => {
        if (viewpoint === "camera" || scene === null) return [point.x, point.y];
        return projectImagePointToTable(
          [point.x, point.y],
          scene.projection.table_to_image_homography,
        );
      })
      .filter((point): point is [number, number] => point !== null);
    const candidate = candidates.find(
      (item) => item.card_id === outline.candidateId,
    );
    const points =
      projectedPoints.length >= 4
        ? projectedPoints
        : candidate === undefined
          ? []
          : (candidatePolygons(candidate, width, height, viewpoint, scene)[0] ??
            []);
    if (points.length < 3) return null;
    const minX = Math.min(...points.map(([x]) => x));
    const minY = Math.min(...points.map(([, y]) => y));
    const fontSize = viewpoint === "camera" ? Math.max(13, width / 110) : 0.14;
    const labelX = Math.max(0, minX);
    const labelY = Math.max(fontSize * 2, minY);
    const statusLabel =
      outline.status === "fit"
        ? "FIT"
        : outline.status === "held_out"
          ? "HELD OUT"
          : "DISCARDED";
    const metricLabel =
      outline.medianDistancePx === null
        ? "boundary metric unavailable"
        : `M/P90/MAX ${outline.medianDistancePx.toFixed(1)}/${outline.p90DistancePx?.toFixed(1) ?? "–"}/${outline.maximumDistancePx?.toFixed(1) ?? "–"} px`;
    const detailLabel =
      outline.status === "discarded" && outline.reason !== null
        ? outline.reason.replaceAll("_", " ")
        : `confidence ${outline.confidence?.toFixed(2) ?? "–"} · quality ${outline.qualityScore?.toFixed(2) ?? "–"}`;
    const title = [
      outline.candidateId,
      statusLabel,
      outline.reason === null
        ? null
        : `Reason: ${outline.reason.replaceAll("_", " ")}`,
      outline.confidence === null
        ? null
        : `Confidence: ${outline.confidence.toFixed(3)}`,
      outline.qualityScore === null
        ? null
        : `Quality score: ${outline.qualityScore.toFixed(3)}`,
      outline.medianDistancePx === null
        ? null
        : `Boundary distance: median ${outline.medianDistancePx.toFixed(2)} px, P90 ${outline.p90DistancePx?.toFixed(2) ?? "unavailable"} px, max ${outline.maximumDistancePx?.toFixed(2) ?? "unavailable"} px`,
    ]
      .filter((item) => item !== null)
      .join("\n");
    return (
      <g
        key={outline.candidateId}
        data-calibration-fit-outline="true"
        data-candidate-id={outline.candidateId}
        data-calibration-status={outline.status}
        role="img"
        aria-label={`${statusLabel.toLowerCase()} calibration card ${outline.candidateId}: ${metricLabel}`}
      >
        <title>{title}</title>
        <polygon
          className={styles.calibrationFitOutline}
          points={pointsAttribute(points)}
          strokeWidth={strokeWidth(viewpoint, width)}
          data-status={outline.status}
          data-geometry={projectedPoints.length >= 4 ? "fitted" : "detected"}
        />
        <text
          className={styles.calibrationFitLabel}
          x={labelX}
          y={labelY}
          fontSize={fontSize}
          data-status={outline.status}
        >
          <tspan x={labelX}>{statusLabel}</tspan>
          <tspan x={labelX} dy="1.15em">
            {metricLabel}
          </tspan>
          <tspan x={labelX} dy="1.15em">
            {detailLabel}
          </tspan>
        </text>
      </g>
    );
  });
}

type LayerRenderContext = {
  frame: EditableFrame;
  candidates: Candidate[];
  scene: PoseSceneEnvelope | null;
  viewpoint: WorkbenchViewpoint;
  width: number;
  height: number;
  zoom: number;
  activeTool: WorkbenchPreferences["activeTool"];
  enabledLayers: WorkbenchLayer[];
  selection: WorkbenchSelection | null;
  candidateProjection: CardSceneProjection | null;
  mappingAnchors: WorkbenchCalibrationAnchor[];
  onSelect: (selection: WorkbenchSelection) => void;
  onVirtualCardPointerDown?: (
    event: ReactPointerEvent<SVGElement>,
    cardId: string,
    kind: "move" | "rotate",
  ) => void;
  onVirtualCardKeyDown?: (
    event: ReactKeyboardEvent<SVGPolygonElement>,
    cardId: string,
  ) => void;
  onMappingAnchorPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    cornerIndex: number,
  ) => void;
  onMappingAnchorCornerSelect: (cornerIndex: number) => void;
};

function renderEditorOverlay({
  editor,
  activeTool,
  viewpoint,
  width,
  height,
  scene,
  onPointPointerDown,
}: {
  editor: EditorState | null;
  activeTool: WorkbenchPreferences["activeTool"];
  viewpoint: WorkbenchViewpoint;
  width: number;
  height: number;
  scene: PoseSceneEnvelope | null;
  onPointPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
}) {
  if (editor === null) return null;
  return (
    <g
      data-workbench-editor="visible-regions"
      pointerEvents={activeTool === "mapping" ? "none" : undefined}
    >
      {editor.polygons.map((polygon, polygonIndex) => {
        const points = polygon
          .map((point) => editorPoint(point, viewpoint, width, height, scene))
          .filter((point): point is [number, number] => point !== null);
        return (
          <g key={`editor-${polygonIndex}`}>
            {points.length >= 2 ? (
              <polygon
                points={pointsAttribute(points)}
                fill={
                  editor.polygonIndex === polygonIndex
                    ? "rgba(255, 210, 79, 0.25)"
                    : "rgba(255, 210, 79, 0.12)"
                }
                stroke={
                  editor.polygonIndex === polygonIndex ? "#ffd24f" : "#c79f34"
                }
                strokeDasharray="4 3"
                strokeWidth={strokeWidth(viewpoint, width)}
                pointerEvents="none"
              />
            ) : null}
            {polygon.map((point, pointIndex) => {
              const displayPoint = editorPoint(
                point,
                viewpoint,
                width,
                height,
                scene,
              );
              if (displayPoint === null) return null;
              const [x, y] = displayPoint;
              return (
                <circle
                  key={`${point.x}:${point.y}:${pointIndex}`}
                  cx={x}
                  cy={y}
                  r={viewpoint === "camera" ? Math.max(1, width / 160) : 0.1}
                  fill={
                    editor.polygonIndex === polygonIndex &&
                    editor.selectedPointIndex === pointIndex
                      ? "#ffffff"
                      : "#ffd24f"
                  }
                  stroke="#ffd24f"
                  strokeWidth={strokeWidth(viewpoint, width) / 2}
                  tabIndex={0}
                  role="button"
                  aria-label={`Polygon ${polygonIndex + 1}, point ${pointIndex + 1} at ${point.x}, ${point.y}`}
                  onPointerDown={(event) =>
                    onPointPointerDown?.(event, polygonIndex, pointIndex)
                  }
                  onClick={(event) => event.stopPropagation()}
                />
              );
            })}
          </g>
        );
      })}
    </g>
  );
}

function sourcePointFromEvent(
  event: ReactPointerEvent<SVGSVGElement>,
  viewpoint: WorkbenchViewpoint,
  viewBox: { x: number; y: number; width: number; height: number },
  width: number,
  height: number,
  scene: PoseSceneEnvelope | null,
): Point | null {
  const rect = event.currentTarget.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  const scale = Math.min(
    rect.width / viewBox.width,
    rect.height / viewBox.height,
  );
  if (!Number.isFinite(scale) || scale <= 0) return null;
  const contentWidth = viewBox.width * scale;
  const contentHeight = viewBox.height * scale;
  const offsetX = (rect.width - contentWidth) / 2;
  const offsetY = (rect.height - contentHeight) / 2;
  const displayX = viewBox.x + (event.clientX - rect.left - offsetX) / scale;
  const displayY = viewBox.y + (event.clientY - rect.top - offsetY) / scale;
  if (viewpoint === "camera" || scene === null) {
    return {
      x: clamp((displayX / width) * 1000, 1000),
      y: clamp((displayY / height) * 1000, 1000),
    };
  }
  const source = projectTablePoint(
    [displayX, displayY],
    scene.projection.table_to_image_homography,
  );
  return source === null
    ? null
    : {
        x: clamp((source[0] / width) * 1000, 1000),
        y: clamp((source[1] / height) * 1000, 1000),
      };
}

export function readCalibrationAnchors(
  refinement: CalibrationRefinementResponse | null,
  frameId: string,
  eventId: string,
  sceneFrameId: string | null,
): WorkbenchCalibrationAnchor[] {
  if (refinement === null || !Array.isArray(refinement.draft.anchors))
    return [];
  const frameIds = new Set([frameId, eventId, sceneFrameId].filter(Boolean));
  return refinement.draft.anchors.flatMap((raw) => {
    if (!isRecord(raw)) return [];
    const anchorId = readString(raw.anchor_id);
    const cardId = readString(raw.card_id);
    const sourceFrameId = readString(raw.source_frame_id);
    const state = readAnchorState(raw.state);
    const corners = readTablePoints(raw.quadrilateral);
    if (
      anchorId === null ||
      cardId === null ||
      sourceFrameId === null ||
      state === null ||
      corners === null ||
      !frameIds.has(sourceFrameId)
    )
      return [];
    return [
      {
        anchorId,
        cardId,
        sourceFrameId,
        eligible: raw.eligible === true,
        state,
        corners,
      },
    ];
  });
}

export function calibrationDraftRevision(
  refinement: CalibrationRefinementResponse | null,
): number {
  const revision = refinement?.draft.revision;
  return typeof revision === "number" &&
    Number.isInteger(revision) &&
    revision >= 0
    ? revision
    : 0;
}

export function calibrationCommandCount(
  refinement: CalibrationRefinementResponse | null,
): number {
  return Array.isArray(refinement?.draft.commands)
    ? refinement.draft.commands.length
    : 0;
}

function readAnchorState(value: unknown): AnchorState | null {
  return typeof value === "string" &&
    (ANCHOR_STATES as readonly string[]).includes(value)
    ? (value as AnchorState)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readTablePoints(value: unknown): TablePoint[] | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const points = value.map((raw) => {
    if (!Array.isArray(raw) || raw.length !== 2) return null;
    const x = raw[0];
    const y = raw[1];
    return typeof x === "number" &&
      Number.isFinite(x) &&
      typeof y === "number" &&
      Number.isFinite(y)
      ? ([x, y] as TablePoint)
      : null;
  });
  return points.every((point): point is TablePoint => point !== null)
    ? points
    : null;
}

export function cloneTablePoints(points: TablePoint[]): TablePoint[] {
  return points.map(([x, y]) => [x, y]);
}

type LayerRenderer = {
  layer: WorkbenchLayer;
  render: (context: LayerRenderContext) => ReactNode;
};

export const WORKBENCH_LAYER_REGISTRY: readonly LayerRenderer[] = [
  { layer: "mapping", render: renderMappingLayer },
  { layer: "ignore_regions", render: renderIgnoreLayer },
  { layer: "suggestions", render: renderSuggestionLayer },
  { layer: "virtual_cards", render: renderVirtualCardLayer },
  { layer: "visible_regions", render: renderVisibleRegionLayer },
];

function renderLayers(context: LayerRenderContext) {
  const layers =
    context.activeTool === "mapping"
      ? [
          ...WORKBENCH_LAYER_REGISTRY.filter(
            (entry) => entry.layer !== "mapping",
          ),
          ...WORKBENCH_LAYER_REGISTRY.filter(
            (entry) => entry.layer === "mapping",
          ),
        ]
      : WORKBENCH_LAYER_REGISTRY;
  return layers
    .filter((entry) => context.enabledLayers.includes(entry.layer))
    .map((entry) => {
      const { layer } = entry;
      return (
        <g
          key={layer}
          data-workbench-layer={layer}
          pointerEvents={
            context.activeTool === "mapping" && layer !== "mapping"
              ? "none"
              : undefined
          }
        >
          {entry.render(context)}
        </g>
      );
    });
}

function renderVisibleRegionLayer({
  candidates,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return candidates.flatMap((candidate) =>
    candidatePolygons(candidate, width, height, viewpoint, scene).map(
      (polygon, polygonIndex) => (
        <polygon
          key={`${candidate.card_id}-visible-${polygonIndex}`}
          points={pointsAttribute(polygon)}
          fill="rgba(59, 205, 180, 0.2)"
          stroke={
            isSelected(selection, {
              type: "visible_card",
              id: candidate.card_id,
            })
              ? "#ffd24f"
              : "#30c9ac"
          }
          strokeWidth={strokeWidth(viewpoint, width)}
          data-card-id={candidate.card_id}
          data-polygon-index={polygonIndex}
          role="button"
          tabIndex={0}
          aria-label={`Edit ${candidate.card_id}, polygon ${polygonIndex + 1}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({
              type: "polygon",
              id: candidate.card_id,
              polygonIndex,
            });
          }}
        />
      ),
    ),
  );
}

function renderSuggestionLayer({
  candidates,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return candidates.flatMap((candidate) =>
    candidatePolygons(candidate, width, height, viewpoint, scene).map(
      (polygon, polygonIndex) => (
        <path
          key={`${candidate.card_id}-suggestion-${polygonIndex}`}
          d={pathAttribute(polygon)}
          fill="none"
          stroke={
            isSelected(selection, {
              type: "visible_card",
              id: candidate.card_id,
            })
              ? "#ffffff"
              : "#a7aebc"
          }
          strokeDasharray="5 5"
          strokeWidth={strokeWidth(viewpoint, width)}
          data-card-id={candidate.card_id}
          data-suggestion="true"
          role="button"
          tabIndex={0}
          aria-label={`Select detector suggestion ${candidate.card_id}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "visible_card", id: candidate.card_id });
          }}
        />
      ),
    ),
  );
}

function renderIgnoreLayer({
  frame,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return frame.outcome.ignored_regions.flatMap((region) =>
    region.geometry.polygons.map((polygon, polygonIndex) => {
      const points = transformSourcePolygon(
        polygon,
        width,
        height,
        viewpoint,
        scene,
      );
      return (
        <polygon
          key={`${region.region_id}-${polygonIndex}`}
          points={pointsAttribute(points)}
          fill="rgba(255, 170, 96, 0.22)"
          stroke={
            isSelected(selection, {
              type: "ignore_region",
              id: region.region_id,
            })
              ? "#ffffff"
              : "#f0a35b"
          }
          strokeDasharray="3 3"
          strokeWidth={strokeWidth(viewpoint, width)}
          data-ignore-region-id={region.region_id}
          role="button"
          tabIndex={0}
          aria-label={`Select ignore region ${region.region_id}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "ignore_region", id: region.region_id });
          }}
        />
      );
    }),
  );
}

function renderVirtualCardLayer({
  scene,
  viewpoint,
  width,
  zoom,
  selection,
  onSelect,
  onVirtualCardPointerDown,
  onVirtualCardKeyDown,
}: LayerRenderContext) {
  if (scene === null) return null;
  const orderedPoses = renderOrder(scene.scene, selection);
  const badges = orderedPoses.map((pose) => {
    const index = scene.scene.stacking_order.card_ids.indexOf(pose.card_id);
    const polygon = posePolygon(pose, scene.projection, viewpoint);
    if (index < 0 || polygon.length === 0) return null;
    const [start, edgeEnd, inwardEnd] = polygon;
    const edge = [edgeEnd[0] - start[0], edgeEnd[1] - start[1]];
    const inward = [inwardEnd[0] - edgeEnd[0], inwardEnd[1] - edgeEnd[1]];
    const x = start[0] + edge[0] * 0.12 + inward[0] * 0.1;
    const y = start[1] + edge[1] * 0.12 + inward[1] * 0.1;
    const radius =
      viewpoint === "camera"
        ? Math.max(12, width / 55) / Math.max(zoom, 0.01)
        : Math.max(0.08, scene.projection.card_short_size * 0.12) /
          Math.max(zoom, 0.01);
    return { cardId: pose.card_id, index, x, y, radius };
  });
  return (
    <>
      {orderedPoses.map((pose) => {
        const polygon = posePolygon(pose, scene.projection, viewpoint);
        const selected = isSelected(selection, {
          type: "virtual_card",
          id: pose.card_id,
        });
        const handle = rotationHandle(pose, scene.projection, viewpoint);
        return (
          <g key={pose.card_id}>
            <polygon
              points={pointsAttribute(polygon)}
              fill="rgba(55, 96, 106, 0.55)"
              stroke={selected ? "#d9fff7" : "#80b6b7"}
              strokeWidth={strokeWidth(viewpoint, width, selected)}
              data-card-id={pose.card_id}
              data-stacking-index={scene.scene.stacking_order.card_ids.indexOf(
                pose.card_id,
              )}
              role="button"
              tabIndex={0}
              aria-label={`Select virtual card ${pose.card_id}`}
              onKeyDown={(event) => onVirtualCardKeyDown?.(event, pose.card_id)}
              onPointerDown={(event) =>
                onVirtualCardPointerDown?.(event, pose.card_id, "move")
              }
              onClick={(event) => {
                event.stopPropagation();
                onSelect({ type: "virtual_card", id: pose.card_id });
              }}
            />
            {selected ? (
              <circle
                cx={handle[0]}
                cy={handle[1]}
                r={viewpoint === "camera" ? Math.max(3, width / 120) : 0.11}
                fill="#ffd24f"
                stroke="#18242f"
                strokeWidth={strokeWidth(viewpoint, width) / 2}
                role="button"
                tabIndex={0}
                aria-label={`Rotate card ${pose.card_id}`}
                onPointerDown={(event) =>
                  onVirtualCardPointerDown?.(event, pose.card_id, "rotate")
                }
                onClick={(event) => event.stopPropagation()}
              />
            ) : null}
          </g>
        );
      })}
      <g
        data-card-stacking-badges="true"
        pointerEvents="none"
        aria-hidden="true"
      >
        {badges.map((badge) =>
          badge === null ? null : (
            <g
              key={badge.cardId}
              data-stacking-badge-id={badge.cardId}
              data-stacking-index={badge.index}
            >
              <circle
                cx={badge.x}
                cy={badge.y}
                r={badge.radius}
                fill="#14252b"
                stroke="#ffffff"
                strokeWidth={
                  (viewpoint === "camera" ? Math.max(1, width / 500) : 0.08) /
                  Math.max(zoom, 0.01)
                }
              />
              <text
                x={badge.x}
                y={badge.y}
                fill="#ffffff"
                fontSize={badge.radius * 1.15}
                fontWeight="800"
                textAnchor="middle"
                dominantBaseline="central"
              >
                {badge.index + 1}
              </text>
            </g>
          ),
        )}
      </g>
    </>
  );
}

function renderMappingLayer({
  scene,
  viewpoint,
  candidateProjection,
  width,
  zoom,
  mappingAnchors,
  selection,
  onSelect,
  onMappingAnchorPointerDown,
  onMappingAnchorCornerSelect,
}: LayerRenderContext) {
  if (scene === null && mappingAnchors.length === 0) return null;
  const orderedAnchors = [
    ...mappingAnchors.filter(
      (anchor) =>
        !isSelected(selection, {
          type: "calibration_anchor",
          id: anchor.anchorId,
        }),
    ),
    ...mappingAnchors.filter((anchor) =>
      isSelected(selection, {
        type: "calibration_anchor",
        id: anchor.anchorId,
      }),
    ),
  ];
  if (scene === null) {
    return orderedAnchors.map((anchor) => (
      <MappingAnchorOverlay
        key={anchor.anchorId}
        anchor={anchor}
        viewpoint={viewpoint}
        projection={null}
        width={width}
        zoom={zoom}
        selected={isSelected(selection, {
          type: "calibration_anchor",
          id: anchor.anchorId,
        })}
        onSelect={onSelect}
        onPointerDown={onMappingAnchorPointerDown}
        onSelectCorner={onMappingAnchorCornerSelect}
      />
    ));
  }
  const currentProjection = scene.projection;
  const candidate =
    candidateProjection === null
      ? null
      : scene.scene.poses.map((pose) => (
          <CandidateMappingProjection
            key={`${pose.card_id}-candidate`}
            polygon={candidatePosePolygon(
              pose,
              currentProjection,
              candidateProjection,
              viewpoint,
            )}
            viewpoint={viewpoint}
            width={width}
            zoom={zoom}
          />
        ));
  return (
    <>
      {candidate}
      {orderedAnchors.map((anchor) => (
        <MappingAnchorOverlay
          key={anchor.anchorId}
          anchor={anchor}
          viewpoint={viewpoint}
          projection={currentProjection}
          width={width}
          zoom={zoom}
          selected={isSelected(selection, {
            type: "calibration_anchor",
            id: anchor.anchorId,
          })}
          onSelect={onSelect}
          onPointerDown={onMappingAnchorPointerDown}
          onSelectCorner={onMappingAnchorCornerSelect}
        />
      ))}
    </>
  );
}

function MappingAnchorOverlay({
  anchor,
  viewpoint,
  projection,
  width,
  zoom,
  selected,
  onSelect,
  onSelectCorner,
  onPointerDown,
}: {
  anchor: WorkbenchCalibrationAnchor;
  viewpoint: WorkbenchViewpoint;
  projection: CardSceneProjection | null;
  width: number;
  zoom: number;
  selected: boolean;
  onSelect: (selection: WorkbenchSelection) => void;
  onSelectCorner: (cornerIndex: number) => void;
  onPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    cornerIndex: number,
  ) => void;
}) {
  const corners =
    projection === null || viewpoint === "camera"
      ? anchor.corners
      : anchor.corners
          .map((point) =>
            projectImagePointToTable(
              point,
              projection.table_to_image_homography,
            ),
          )
          .filter((point): point is TablePoint => point !== null);
  return (
    <g data-anchor-id={anchor.anchorId} data-anchor-state={anchor.state}>
      {corners.length === 4 ? (
        <polygon
          points={pointsAttribute(corners)}
          fill="none"
          stroke={selected ? "#ffffff" : "#ff8a65"}
          strokeDasharray={selected ? undefined : "4 3"}
          strokeWidth={mappingStrokeWidth(viewpoint, width, zoom)}
          opacity={0.5}
          pointerEvents="stroke"
          role="button"
          tabIndex={0}
          aria-label={`Select calibration anchor ${anchor.anchorId}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "calibration_anchor", id: anchor.anchorId });
          }}
        />
      ) : null}
      {corners.map(([x, y], index) => (
        <circle
          key={`${anchor.anchorId}-${index}`}
          cx={x}
          cy={y}
          r={mappingCornerRadius(
            viewpoint,
            width,
            zoom,
            Math.max(0.05, (projection?.card_short_size ?? 1) * 0.08),
          )}
          fill={selected ? "#ffffff" : "#ff8a65"}
          stroke="#18242f"
          strokeWidth={mappingStrokeWidth(viewpoint, width, zoom) / 2}
          opacity={0.5}
          data-mapping-anchor={index}
          role="button"
          tabIndex={0}
          aria-label={`Adjust calibration anchor ${index + 1} for ${anchor.anchorId}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "calibration_anchor", id: anchor.anchorId });
            onSelectCorner(index);
          }}
          onPointerDown={(event) => onPointerDown?.(event, anchor, index)}
        />
      ))}
    </g>
  );
}

function CandidateMappingProjection({
  polygon,
  viewpoint,
  width,
  zoom,
}: {
  polygon: TablePoint[];
  viewpoint: WorkbenchViewpoint;
  width: number;
  zoom: number;
}) {
  return (
    <g data-projection="candidate">
      <polygon
        points={pointsAttribute(polygon)}
        fill="none"
        stroke="#ffd166"
        strokeDasharray="8 5"
        strokeWidth={mappingStrokeWidth(viewpoint, width, zoom)}
        opacity={0.5}
        pointerEvents="none"
      />
    </g>
  );
}

function RectifiedSourceFrame({
  sourceUrl,
  width,
  height,
  homography,
  clipPrefix,
}: {
  sourceUrl: string;
  width: number;
  height: number;
  homography: number[][];
  clipPrefix: string;
}) {
  const patches = rectifiedBackgroundPatches(
    width,
    height,
    homography,
    clipPrefix,
  );
  return (
    <g data-workbench-background="rectified" pointerEvents="none">
      <defs>
        {patches.map((patch) => (
          <clipPath
            key={patch.clipId}
            id={patch.clipId}
            clipPathUnits="userSpaceOnUse"
          >
            <polygon points={pointsAttribute(patch.sourceTriangle)} />
          </clipPath>
        ))}
      </defs>
      {patches.map((patch) => (
        <g key={patch.clipId} transform={patch.transform}>
          <image
            href={sourceUrl}
            x={0}
            y={0}
            width={width}
            height={height}
            preserveAspectRatio="none"
            clipPath={`url(#${patch.clipId})`}
            aria-hidden="true"
          />
        </g>
      ))}
    </g>
  );
}
