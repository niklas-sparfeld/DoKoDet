import type { Candidate } from "./PipelineVisibleCardTypes";

export const RECORDING_ID = "visible-pipeline-recording";
export const RUN_ID = "visible-run-1";
export const REVISION_ID = "visible-revision-1";
export const PROPOSAL_REVISION_ID = "card-scene-proposal-revision-1";
export const ITEM_ID = "event-1";
export const SECOND_ITEM_ID = "event-2";
export const FRAME_IDENTITY = {
  schema_version: "exact-event/v1",
  source_video_sha256: "a".repeat(64),
  requested_time_us: 400_000,
  frame_index: 4,
  presentation_timestamp_us: 400_000,
  width: 100,
  height: 100,
  decoder_version: "fixture-decoder/v1",
  transform_version: "fixture-frame/v1",
  output_encoding: "jpeg",
  content_type: "image/jpeg",
  image_sha256: "b".repeat(64),
  policy: "exact-event/v1",
};
export const DETECTOR_CANDIDATE: Candidate = {
  card_id: "run-card-1",
  side: "unknown",
  geometry: {
    kind: "detector-box/v1",
    box_2d: { x_min: 100, y_min: 100, x_max: 800, y_max: 800 },
  },
  normalization: {
    width: 100,
    height: 100,
    policy_id: "full-frame-0-1000/v1",
  },
};
export const SECOND_DETECTOR_CANDIDATE: Candidate = {
  ...DETECTOR_CANDIDATE,
  card_id: "run-card-2",
  geometry: {
    kind: "detector-box/v1",
    box_2d: { x_min: 200, y_min: 200, x_max: 700, y_max: 700 },
  },
};
export const IGNORE_REGION = {
  region_id: "ignore-region-1",
  geometry: {
    kind: "reviewed-ignore-region/v1" as const,
    polygons: [
      [
        { x: 100, y: 100 },
        { x: 800, y: 100 },
        { x: 800, y: 800 },
        { x: 100, y: 800 },
      ],
    ],
  },
  normalization: {
    width: FRAME_IDENTITY.width,
    height: FRAME_IDENTITY.height,
    policy_id: "full-frame-0-1000/v1",
  },
  reason: "untidy_stack" as const,
  source_candidates: [],
};

export const SEGMENTED_GEOMETRY_WITH_DERIVED_BOX: Candidate["geometry"] = {
  kind: "detector-box/v1",
  box_2d: { x_min: 100, y_min: 100, x_max: 820, y_max: 820 },
  visible_region: {
    polygons: [
      [
        { x: 140, y: 180 },
        { x: 760, y: 120 },
        { x: 820, y: 760 },
        { x: 200, y: 820 },
      ],
    ],
  },
};

export const MULTI_POLYGON_GEOMETRY_WITH_DERIVED_BOX: Candidate["geometry"] = {
  ...SEGMENTED_GEOMETRY_WITH_DERIVED_BOX,
  visible_region: {
    polygons: [
      ...SEGMENTED_GEOMETRY_WITH_DERIVED_BOX.visible_region!.polygons,
      [
        { x: 100, y: 100 },
        { x: 200, y: 100 },
        { x: 200, y: 200 },
        { x: 100, y: 200 },
      ],
    ],
  },
};

export function generatedResult() {
  return {
    run_id: RUN_ID,
    recording_id: RECORDING_ID,
    processor_type: "visible-card-detection",
    status: "complete",
    attempt: 1,
    request: {},
    state: {},
    revisions: [
      {
        manifest: { revision_id: REVISION_ID },
        content: {
          outcomes: [
            {
              event_id: ITEM_ID,
              frame_identity: FRAME_IDENTITY,
              status: "detected",
              candidates: [DETECTOR_CANDIDATE],
              ignored_regions: [],
              error: null,
            },
          ],
        },
      },
    ],
  };
}

export function generatedResultWithTwoFrames() {
  const result = generatedResult();
  result.revisions[0].content.outcomes.push({
    event_id: SECOND_ITEM_ID,
    frame_identity: {
      ...FRAME_IDENTITY,
      requested_time_us: 800_000,
      frame_index: 8,
      presentation_timestamp_us: 800_000,
      image_sha256: "c".repeat(64),
    },
    status: "detected",
    candidates: [
      {
        ...DETECTOR_CANDIDATE,
        card_id: "run-card-2",
        side: "face_down",
      },
    ],
    ignored_regions: [],
    error: null,
  });
  return result;
}

export function generatedResultWithFrames(count: number) {
  const result = generatedResult();
  const template = result.revisions[0].content.outcomes[0];
  result.revisions[0].content.outcomes = Array.from(
    { length: count },
    (_, index) => ({
      ...template,
      event_id: `event-${index + 1}`,
      frame_identity: {
        ...FRAME_IDENTITY,
        requested_time_us: (index + 1) * 100_000,
        frame_index: index + 1,
        presentation_timestamp_us: (index + 1) * 100_000,
        image_sha256: String(index).repeat(64),
      },
      candidates: [
        {
          ...DETECTOR_CANDIDATE,
          card_id: `run-card-${index + 1}`,
        },
      ],
    }),
  );
  return result;
}

export function reference(
  state: "pending" | "accepted" | "corrected" = "pending",
) {
  return {
    recording_id: RECORDING_ID,
    content_type: "visible_cards",
    state: {
      recording_id: RECORDING_ID,
      content_type: "visible_cards",
      draft_revision: state === "pending" ? 0 : 1,
      draft_state: "draft",
      source_revision_id: REVISION_ID,
      selected_completed_revision_id: null,
      updated_at: "2026-09-06T00:00:00Z",
    },
    draft: {
      recording_id: RECORDING_ID,
      content_type: "visible_cards",
      revision: state === "pending" ? 0 : 1,
      source_revision_id: REVISION_ID,
      items: [
        {
          item_id: ITEM_ID,
          base_item_id: null,
          review_state: state,
          item: {
            event_id: ITEM_ID,
            frame_identity: FRAME_IDENTITY,
            status: "detected",
            candidates: [
              state === "corrected"
                ? {
                    ...DETECTOR_CANDIDATE,
                    geometry: {
                      kind: "reviewed-visible-region/v1",
                      visible_region: {
                        polygons: [
                          [
                            { x: 100, y: 100 },
                            { x: 820, y: 100 },
                            { x: 820, y: 820 },
                            { x: 100, y: 820 },
                          ],
                        ],
                      },
                    },
                  }
                : DETECTOR_CANDIDATE,
            ],
            ignored_regions: [],
            error: null,
          },
        },
      ],
      coverage: null,
      impact: [],
      updated_at: "2026-09-06T00:00:00Z",
    },
  };
}

export function referenceWithSegmentedGeometry() {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: item.item.candidates.map((candidate) => ({
            ...candidate,
            geometry: SEGMENTED_GEOMETRY_WITH_DERIVED_BOX,
          })),
        },
      })),
    },
  };
}

export function referenceWithEmptyCandidates() {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: [],
        },
      })),
    },
  };
}

export function generatedResultWithTwoCandidates() {
  const result = generatedResult();
  result.revisions[0].content.outcomes[0].candidates = [
    DETECTOR_CANDIDATE,
    SECOND_DETECTOR_CANDIDATE,
  ];
  return result;
}

export function referenceWithTwoCandidates() {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: [DETECTOR_CANDIDATE, SECOND_DETECTOR_CANDIDATE],
        },
      })),
    },
  };
}

export function referenceWithAdjacentCandidates(
  firstPolygon = [
    { x: 100, y: 100 },
    { x: 500, y: 100 },
    { x: 500, y: 500 },
    { x: 100, y: 500 },
  ],
) {
  const current = reference();
  const makeCandidate = (
    cardId: string,
    polygon: { x: number; y: number }[],
  ): Candidate => ({
    ...DETECTOR_CANDIDATE,
    card_id: cardId,
    geometry: {
      kind: "reviewed-visible-region/v1",
      visible_region: { polygons: [polygon] },
    },
  });
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: [
            makeCandidate("left-card", firstPolygon),
            makeCandidate("right-card", [
              { x: 550, y: 150 },
              { x: 900, y: 150 },
              { x: 900, y: 450 },
              { x: 550, y: 450 },
            ]),
          ],
        },
      })),
    },
  };
}

export function referenceWithIgnoreRegion(
  candidates: Candidate[] = [DETECTOR_CANDIDATE],
) {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      revision: current.draft.revision + 1,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates,
          ignored_regions: [IGNORE_REGION],
        },
      })),
    },
  };
}

export function referenceWithMultiPolygonGeometry() {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: item.item.candidates.map((candidate) => ({
            ...candidate,
            geometry: MULTI_POLYGON_GEOMETRY_WITH_DERIVED_BOX,
          })),
        },
      })),
    },
  };
}

export function referenceWithPolygon(polygon: { x: number; y: number }[]) {
  const current = reference();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item) => ({
        ...item,
        item: {
          ...item.item,
          candidates: item.item.candidates.map((candidate) => ({
            ...candidate,
            geometry: {
              kind: "reviewed-visible-region/v1" as const,
              visible_region: { polygons: [polygon] },
            },
          })),
        },
      })),
    },
  };
}

export function referenceWithTwoFrames() {
  const current = reference();
  const secondItem = {
    ...current.draft.items[0],
    item_id: SECOND_ITEM_ID,
    item: {
      ...current.draft.items[0].item,
      event_id: SECOND_ITEM_ID,
      frame_identity: {
        ...FRAME_IDENTITY,
        requested_time_us: 800_000,
        frame_index: 8,
        presentation_timestamp_us: 800_000,
        image_sha256: "c".repeat(64),
      },
    },
  };
  return {
    ...current,
    draft: { ...current.draft, items: [...current.draft.items, secondItem] },
  };
}

export function referenceWithReviewedPreviousIgnoreRegion() {
  const current = referenceWithTwoFrames();
  return {
    ...current,
    draft: {
      ...current.draft,
      items: current.draft.items.map((item, index) =>
        index === 0
          ? {
              ...item,
              review_state: "accepted",
              item: {
                ...item.item,
                ignored_regions: [IGNORE_REGION],
              },
            }
          : item,
      ),
    },
  };
}

export function referenceAfterCopyingPreviousIgnoreRegion() {
  const current = referenceWithReviewedPreviousIgnoreRegion();
  return {
    ...current,
    draft: {
      ...current.draft,
      revision: current.draft.revision + 1,
      items: current.draft.items.map((item, index) =>
        index === 1
          ? {
              ...item,
              item: {
                ...item.item,
                ignored_regions: [
                  {
                    ...IGNORE_REGION,
                    region_id: `ignore-${SECOND_ITEM_ID}-copied-1`,
                  },
                ],
                candidates: [],
              },
            }
          : item,
      ),
    },
  };
}

export function emptyReference() {
  const current = reference();
  return {
    ...current,
    state: {
      ...current.state,
      source_revision_id: null,
    },
    draft: {
      ...current.draft,
      source_revision_id: null,
      items: [],
    },
  };
}

export function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
