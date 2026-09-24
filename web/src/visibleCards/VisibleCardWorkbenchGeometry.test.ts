import { describe, expect, it } from "vitest";

import type { Candidate, IgnoreRegion } from "./PipelineVisibleCardTypes";
import type { PoseCard } from "./PoseBasedVisibleCardScene";
import {
  candidateIsCoveredByIgnoreRegions,
  clamp,
  posePolygon,
} from "./VisibleCardWorkbenchGeometry";
import { surfaceViewBox } from "./VisibleCardWorkbenchSurfaceGeometry";

const candidate: Candidate = {
  card_id: "card-1",
  geometry: {
    kind: "visible-region/v1",
    visible_region: {
      polygons: [
        [
          { x: 0.2, y: 0.2 },
          { x: 0.4, y: 0.2 },
          { x: 0.4, y: 0.4 },
          { x: 0.2, y: 0.4 },
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
        { x: 0.1, y: 0.1 },
        { x: 0.5, y: 0.1 },
        { x: 0.5, y: 0.5 },
        { x: 0.1, y: 0.5 },
      ],
    ],
  },
  normalization: { width: 100, height: 100, policy_id: "test" },
  reason: "untidy_stack",
  source_candidates: [],
};

const pose: PoseCard = {
  schema_version: "card-pose/v1",
  card_id: "card-1",
  center: [10, 20],
  rotation_degrees: 0,
  source_suggestion_id: null,
  fit_diagnostics_digest: null,
};

describe("visible-card workbench geometry", () => {
  it("detects overlap with an ignore region without mounting React", () => {
    expect(candidateIsCoveredByIgnoreRegions(candidate, [ignoreRegion])).toBe(
      true,
    );
    expect(candidateIsCoveredByIgnoreRegions(candidate, [])).toBe(false);
  });

  it("projects a pose into camera coordinates", () => {
    expect(
      posePolygon(
        pose,
        {
          table_to_image_homography: [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
          ],
          card_short_size: 2,
          card_long_size: 4,
        },
        "camera",
      ),
    ).toEqual([
      [9, 18],
      [11, 18],
      [11, 22],
      [9, 22],
    ]);
  });

  it("clamps values at both viewport bounds", () => {
    expect(clamp(-3, 10)).toBe(0);
    expect(clamp(4, 10)).toBe(4);
    expect(clamp(13, 10)).toBe(10);
  });

  it("maps camera zoom and pan to the visible source rectangle", () => {
    expect(
      surfaceViewBox("camera", 100, 50, null, {
        zoom: 2,
        pan: { x: 10, y: -5 },
      }),
    ).toEqual({ x: 35, y: 7.5, width: 50, height: 25 });
  });

  it("keeps a zoomed camera crop inside the source frame", () => {
    expect(
      surfaceViewBox("camera", 100, 50, null, {
        zoom: 2,
        pan: { x: 100, y: 100 },
      }),
    ).toEqual({ x: 50, y: 25, width: 50, height: 25 });
  });
});
