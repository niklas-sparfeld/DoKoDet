import type {
  Candidate,
  Geometry,
  IgnoreRegion,
  Point,
} from "./PipelineVisibleCardTypes";

const POLYGON_SWITCH_CLEARANCE_RATIO = 0.08;

export function geometryPolygons(geometry: Geometry): Point[][] {
  if (geometry.visible_region !== undefined)
    return geometry.visible_region.polygons.map((polygon) => [...polygon]);
  const box = geometry.box_2d;
  return box === undefined
    ? [[]]
    : [
        [
          { x: box.x_min, y: box.y_min },
          { x: box.x_max, y: box.y_min },
          { x: box.x_max, y: box.y_max },
          { x: box.x_min, y: box.y_max },
        ],
      ];
}

const GEOMETRY_EPSILON = 1e-9;

export function candidateIsWithinIgnoreRegions(
  candidate: Candidate,
  regions: IgnoreRegion[],
): boolean {
  const containers = regions.flatMap((region) => region.geometry.polygons);
  return (
    containers.length > 0 &&
    geometryPolygons(candidate.geometry).every((polygon) =>
      polygonIsWithin(polygon, containers),
    )
  );
}

function polygonIsWithin(candidate: Point[], containers: Point[][]): boolean {
  if (candidate.length < 3) return false;
  if (!candidate.every((point) => pointInPolygonUnion(point, containers)))
    return false;
  return candidate.every((start, index) =>
    segmentIsWithin(
      start,
      candidate[(index + 1) % candidate.length],
      containers,
    ),
  );
}

function segmentIsWithin(
  start: Point,
  end: Point,
  containers: Point[][],
): boolean {
  if (start.x === end.x && start.y === end.y) return true;
  const parameters = [0, 1];
  for (const polygon of containers) {
    for (let index = 0; index < polygon.length; index += 1) {
      parameters.push(
        ...segmentIntersectionParameters(
          start,
          end,
          polygon[index],
          polygon[(index + 1) % polygon.length],
        ),
      );
    }
  }
  const ordered = [
    ...new Set(
      parameters
        .filter(
          (parameter) =>
            parameter >= -GEOMETRY_EPSILON && parameter <= 1 + GEOMETRY_EPSILON,
        )
        .map((parameter) =>
          Math.max(0, Math.min(1, Math.round(parameter * 1e12) / 1e12)),
        ),
    ),
  ].sort((left, right) => left - right);
  return ordered.slice(0, -1).every((left, index) => {
    const right = ordered[index + 1];
    if (right - left <= GEOMETRY_EPSILON) return true;
    const parameter = (left + right) / 2;
    return pointInPolygonUnion(
      {
        x: start.x + (end.x - start.x) * parameter,
        y: start.y + (end.y - start.y) * parameter,
      },
      containers,
    );
  });
}

function segmentIntersectionParameters(
  start: Point,
  end: Point,
  otherStart: Point,
  otherEnd: Point,
): number[] {
  const rayX = end.x - start.x;
  const rayY = end.y - start.y;
  const edgeX = otherEnd.x - otherStart.x;
  const edgeY = otherEnd.y - otherStart.y;
  const denominator = rayX * edgeY - rayY * edgeX;
  const offsetX = otherStart.x - start.x;
  const offsetY = otherStart.y - start.y;
  if (denominator === 0) {
    if (offsetX * rayY - offsetY * rayX !== 0) return [];
    const lengthSquared = rayX * rayX + rayY * rayY;
    if (lengthSquared === 0) return [];
    return [
      (offsetX * rayX + offsetY * rayY) / lengthSquared,
      ((otherEnd.x - start.x) * rayX + (otherEnd.y - start.y) * rayY) /
        lengthSquared,
    ];
  }
  const parameter = (offsetX * edgeY - offsetY * edgeX) / denominator;
  const otherParameter = (offsetX * rayY - offsetY * rayX) / denominator;
  return parameter >= -GEOMETRY_EPSILON &&
    parameter <= 1 + GEOMETRY_EPSILON &&
    otherParameter >= -GEOMETRY_EPSILON &&
    otherParameter <= 1 + GEOMETRY_EPSILON
    ? [parameter]
    : [];
}

function pointInPolygonUnion(point: Point, polygons: Point[][]): boolean {
  return polygons.some((polygon) => pointInPolygon(point.x, point.y, polygon));
}

export function findClearlySelectedCandidate(
  candidates: Candidate[],
  currentCardId: string | null,
  currentPolygons: Point[][],
  point: Point,
): { candidate: Candidate; polygonIndex: number } | null {
  if (!isClearlyOutsidePolygons(currentPolygons, point)) return null;
  let selected: {
    candidate: Candidate;
    polygonIndex: number;
    clearance: number;
  } | null = null;
  for (const candidate of candidates) {
    if (candidate.card_id === currentCardId) continue;
    const polygons = geometryPolygons(candidate.geometry);
    for (const [polygonIndex, polygon] of polygons.entries()) {
      if (polygon.length < 3 || !pointInPolygon(point.x, point.y, polygon)) {
        continue;
      }
      const clearance = polygonClearanceRatio(point, polygon);
      if (clearance <= POLYGON_SWITCH_CLEARANCE_RATIO) continue;
      if (selected === null || clearance > selected.clearance) {
        selected = { candidate, polygonIndex, clearance };
      }
    }
  }
  return selected === null
    ? null
    : {
        candidate: selected.candidate,
        polygonIndex: selected.polygonIndex,
      };
}

export function findClearlySelectedPolygon(
  polygons: Point[][],
  currentPolygonIndex: number,
  point: Point,
): number | null {
  const currentPolygon = polygons[currentPolygonIndex];
  if (currentPolygon === undefined || currentPolygon.length < 3) return null;
  if (!isClearlyOutsidePolygons([currentPolygon], point)) {
    return null;
  }
  let selected: { index: number; clearance: number } | null = null;
  for (const [polygonIndex, polygon] of polygons.entries()) {
    if (
      polygonIndex === currentPolygonIndex ||
      polygon.length < 3 ||
      !pointInPolygon(point.x, point.y, polygon)
    ) {
      continue;
    }
    const clearance = polygonClearanceRatio(point, polygon);
    if (clearance <= POLYGON_SWITCH_CLEARANCE_RATIO) continue;
    if (selected === null || clearance > selected.clearance) {
      selected = { index: polygonIndex, clearance };
    }
  }
  return selected?.index ?? null;
}

function isClearlyOutsidePolygons(polygons: Point[][], point: Point): boolean {
  const completePolygons = polygons.filter((polygon) => polygon.length >= 3);
  if (completePolygons.length === 0) return true;
  if (pointInPolygonUnion(point, completePolygons)) return false;
  return completePolygons.every(
    (polygon) =>
      polygonClearanceRatio(point, polygon) > POLYGON_SWITCH_CLEARANCE_RATIO,
  );
}

function polygonClearanceRatio(point: Point, polygon: Point[]): number {
  const scale = polygonScale(polygon);
  let nearestDistanceSquared = Number.POSITIVE_INFINITY;
  for (let index = 0; index < polygon.length; index += 1) {
    nearestDistanceSquared = Math.min(
      nearestDistanceSquared,
      squaredDistanceToSegment(
        point,
        polygon[index],
        polygon[(index + 1) % polygon.length],
      ),
    );
  }
  return Math.sqrt(nearestDistanceSquared) / scale;
}

function polygonScale(polygon: Point[]): number {
  const xValues = polygon.map((point) => point.x);
  const yValues = polygon.map((point) => point.y);
  return Math.max(
    1,
    Math.hypot(
      Math.max(...xValues) - Math.min(...xValues),
      Math.max(...yValues) - Math.min(...yValues),
    ),
  );
}

function pointInPolygon(x: number, y: number, polygon: Point[]): boolean {
  let inside = false;
  for (let index = 0; index < polygon.length; index += 1) {
    const first = polygon[index];
    const second = polygon[(index + 1) % polygon.length];
    if (pointOnSegment(x, y, first, second)) return true;
    if (first.y > y === second.y > y) continue;
    const intersectionX =
      first.x + ((y - first.y) * (second.x - first.x)) / (second.y - first.y);
    if (x < intersectionX) inside = !inside;
  }
  return inside;
}

function pointOnSegment(
  x: number,
  y: number,
  start: Point,
  end: Point,
): boolean {
  const cross =
    (x - start.x) * (end.y - start.y) - (y - start.y) * (end.x - start.x);
  if (Math.abs(cross) > GEOMETRY_EPSILON) return false;
  return (
    Math.min(start.x, end.x) - GEOMETRY_EPSILON <= x &&
    x <= Math.max(start.x, end.x) + GEOMETRY_EPSILON &&
    Math.min(start.y, end.y) - GEOMETRY_EPSILON <= y &&
    y <= Math.max(start.y, end.y) + GEOMETRY_EPSILON
  );
}

export function reviewedGeometry(polygons: Point[][]): Geometry {
  return {
    kind: "reviewed-visible-region/v1",
    visible_region: {
      polygons: polygons.map((polygon) =>
        polygon.map((point) => ({
          x: Math.round(point.x),
          y: Math.round(point.y),
        })),
      ),
    },
  };
}

export function validatePolygons(polygons: Point[][]): string | null {
  if (polygons.length === 0 || polygons.some((polygon) => polygon.length < 3))
    return "Each visible region needs at least three points.";
  if (
    polygons.some((polygon) =>
      polygon.some(
        (point) =>
          point.x < 0 || point.x > 1000 || point.y < 0 || point.y > 1000,
      ),
    )
  )
    return "Polygon points must stay inside the frame.";
  if (polygons.some((polygon) => Math.abs(polygonArea(polygon)) === 0))
    return "Each polygon must have positive area.";
  return null;
}

function polygonArea(polygon: Point[]): number {
  return polygon.reduce((area, point, index) => {
    const next = polygon[(index + 1) % polygon.length];
    return area + point.x * next.y - next.x * point.y;
  }, 0);
}

export function insertPointOnNearestEdge(
  polygon: Point[],
  point: Point,
): Point[] {
  let nearestEdgeIndex = 0;
  let nearestDistanceSquared = Number.POSITIVE_INFINITY;
  for (let index = 0; index < polygon.length; index += 1) {
    const distanceSquared = squaredDistanceToSegment(
      point,
      polygon[index],
      polygon[(index + 1) % polygon.length],
    );
    if (distanceSquared < nearestDistanceSquared) {
      nearestDistanceSquared = distanceSquared;
      nearestEdgeIndex = index;
    }
  }
  return [
    ...polygon.slice(0, nearestEdgeIndex + 1),
    point,
    ...polygon.slice(nearestEdgeIndex + 1),
  ];
}

function squaredDistanceToSegment(
  point: Point,
  start: Point,
  end: Point,
): number {
  const horizontal = end.x - start.x;
  const vertical = end.y - start.y;
  const lengthSquared = horizontal ** 2 + vertical ** 2;
  if (lengthSquared === 0)
    return (point.x - start.x) ** 2 + (point.y - start.y) ** 2;
  const position = Math.min(
    Math.max(
      ((point.x - start.x) * horizontal + (point.y - start.y) * vertical) /
        lengthSquared,
      0,
    ),
    1,
  );
  const nearestX = start.x + position * horizontal;
  const nearestY = start.y + position * vertical;
  return (point.x - nearestX) ** 2 + (point.y - nearestY) ** 2;
}

export function pointFromEvent(
  event: {
    clientX: number;
    clientY: number;
    currentTarget: {
      getBoundingClientRect: () => {
        left: number;
        top: number;
        width: number;
        height: number;
      };
    };
  },
  providedPoint?: Point | null,
): Point | null {
  if (providedPoint !== undefined) return providedPoint;
  const rect = event.currentTarget.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  return {
    x: clamp(((event.clientX - rect.left) / rect.width) * 1000, 1000),
    y: clamp(((event.clientY - rect.top) / rect.height) * 1000, 1000),
  };
}

export function clamp(value: number, maximum: number): number {
  return Math.min(
    Math.max(0, Math.round(value)),
    Math.max(0, Math.round(maximum)),
  );
}
