import { describe, expect, it } from "vitest";

import {
  candidateIsWithinIgnoreRegions,
  insertPointOnNearestEdge,
  pointFromEvent,
  validatePolygons,
} from "./PipelineVisibleCardGeometry";
import type {
  Candidate,
  IgnoreRegion,
  Point,
} from "./PipelineVisibleCardTypes";

const candidate: Candidate = {
  card_id: "card-1",
  geometry: {
    kind: "reviewed-visible-region/v1",
    visible_region: {
      polygons: [
        [
          { x: 20, y: 20 },
          { x: 40, y: 20 },
          { x: 40, y: 40 },
          { x: 20, y: 40 },
        ],
      ],
    },
  },
  normalization: {},
  side: "face_up",
};

const ignoreRegion: IgnoreRegion = {
  region_id: "ignore-1",
  geometry: {
    kind: "reviewed-ignore-region/v1",
    polygons: [
      [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
        { x: 0, y: 100 },
      ],
    ],
  },
  normalization: { width: 100, height: 100, policy_id: "test" },
  reason: "untidy_stack",
  source_candidates: [],
};

describe("visible-card editor geometry", () => {
  it("checks polygon containment against ignore regions", () => {
    expect(candidateIsWithinIgnoreRegions(candidate, [ignoreRegion])).toBe(
      true,
    );
    expect(candidateIsWithinIgnoreRegions(candidate, [])).toBe(false);
    expect(
      candidateIsWithinIgnoreRegions(
        {
          ...candidate,
          geometry: {
            ...candidate.geometry,
            visible_region: {
              polygons: [
                [
                  { x: 20, y: 20 },
                  { x: 140, y: 20 },
                  { x: 20, y: 40 },
                ],
              ],
            },
          },
        },
        [ignoreRegion],
      ),
    ).toBe(false);
  });

  it("validates normalized polygons and inserts a point on the nearest edge", () => {
    const polygon: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ];
    expect(validatePolygons([polygon])).toBeNull();
    expect(validatePolygons([[...polygon, { x: 1001, y: 20 }]])).toContain(
      "inside the frame",
    );
    expect(insertPointOnNearestEdge(polygon, { x: 50, y: 2 })).toEqual([
      { x: 0, y: 0 },
      { x: 50, y: 2 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ]);
  });

  it("converts pointer coordinates and respects a supplied source point", () => {
    const event = {
      clientX: 25,
      clientY: 60,
      currentTarget: {
        getBoundingClientRect: () => ({
          left: 5,
          top: 10,
          width: 40,
          height: 100,
        }),
      },
    };
    expect(pointFromEvent(event)).toEqual({ x: 500, y: 500 });
    expect(pointFromEvent(event, { x: 12, y: 34 })).toEqual({ x: 12, y: 34 });
    expect(
      pointFromEvent({
        ...event,
        currentTarget: {
          getBoundingClientRect: () => ({
            left: 0,
            top: 0,
            width: 0,
            height: 0,
          }),
        },
      }),
    ).toBeNull();
  });
});
