import type {
  Candidate,
  IgnoreRegion,
  Point,
} from "./PipelineVisibleCardTypes";
import {
  cardPolygon,
  projectTablePoint,
  type CardSceneProjection,
  type PoseCard,
  type PoseSceneEnvelope,
} from "./PoseBasedVisibleCardScene";
import type {
  WorkbenchSelection,
  WorkbenchViewpoint,
} from "./VisibleCardReviewWorkbenchState";
import type { TablePoint } from "./PoseBasedVisibleCardScene";

function candidateNormalizedPolygons(candidate: Candidate): Point[][] {
  if (candidate.geometry.visible_region !== undefined) {
    return candidate.geometry.visible_region.polygons.map((polygon) =>
      polygon.map((point) => ({ x: point.x, y: point.y })),
    );
  }
  const box = candidate.geometry.box_2d;
  return box === undefined
    ? []
    : [
        [
          { x: box.x_min, y: box.y_min },
          { x: box.x_max, y: box.y_min },
          { x: box.x_max, y: box.y_max },
          { x: box.x_min, y: box.y_max },
        ],
      ];
}

export function candidateIsCoveredByIgnoreRegions(
  candidate: Candidate,
  regions: IgnoreRegion[],
): boolean {
  if (regions.length === 0) return false;
  if (
    regions.some((region) =>
      region.source_candidates.some(
        (source) => source.card_id === candidate.card_id,
      ),
    )
  ) {
    return true;
  }
  const containers = regions.flatMap((region) => region.geometry.polygons);
  const polygons = candidateNormalizedPolygons(candidate);
  if (polygons.length === 0 || containers.length === 0) return false;
  return polygons.some((polygon) =>
    containers.some((container) =>
      polygonsOverlapForIgnore(polygon, container),
    ),
  );
}

function polygonsOverlapForIgnore(left: Point[], right: Point[]): boolean {
  if (left.length < 3 || right.length < 3) return false;
  if (polygonsMatch(left, right)) return true;
  const leftCentroid = polygonCentroid(left);
  const rightCentroid = polygonCentroid(right);
  if (
    pointInPolygon(leftCentroid, right) ||
    pointInPolygon(rightCentroid, left)
  ) {
    return true;
  }
  return (
    vertexOverlapRatio(left, right) >= 0.45 ||
    vertexOverlapRatio(right, left) >= 0.45
  );
}

function vertexOverlapRatio(source: Point[], container: Point[]): number {
  if (source.length === 0) return 0;
  const hits = source.filter((point) =>
    pointInPolygon(point, container),
  ).length;
  return hits / source.length;
}

function polygonCentroid(polygon: Point[]): Point {
  const total = polygon.reduce(
    (sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }),
    { x: 0, y: 0 },
  );
  return { x: total.x / polygon.length, y: total.y / polygon.length };
}

function polygonsMatch(left: Point[], right: Point[]): boolean {
  if (left.length !== right.length) return false;
  return left.every(
    (point, index) =>
      Math.abs(point.x - right[index].x) < 1e-6 &&
      Math.abs(point.y - right[index].y) < 1e-6,
  );
}

function pointInPolygon(point: Point, polygon: Point[]): boolean {
  let inside = false;
  for (
    let index = 0, previous = polygon.length - 1;
    index < polygon.length;
    previous = index, index += 1
  ) {
    const current = polygon[index];
    const prior = polygon[previous];
    const crosses =
      current.y > point.y !== prior.y > point.y &&
      point.x <
        ((prior.x - current.x) * (point.y - current.y)) /
          (prior.y - current.y + Number.EPSILON) +
          current.x;
    if (crosses) inside = !inside;
  }
  return inside;
}

export function posePolygon(
  pose: PoseCard,
  projection: CardSceneProjection,
  viewpoint: WorkbenchViewpoint,
): Array<[number, number]> {
  const polygon = cardPolygon(pose, projection);
  if (viewpoint === "rectified") return polygon;
  return polygon
    .map((point) =>
      projectTablePoint(point, projection.table_to_image_homography),
    )
    .filter((point): point is TablePoint => point !== null)
    .map(([x, y]) => [x, y] as [number, number]);
}

export function selectedPoseForSelection(
  scene: PoseSceneEnvelope,
  selection: WorkbenchSelection | null,
): PoseCard | null {
  if (selection?.type !== "virtual_card") return null;
  return (
    scene.scene.poses.find((pose) => pose.card_id === selection.id) ?? null
  );
}

export function clamp(value: number, maximum: number): number {
  return Math.min(Math.max(value, 0), maximum);
}
