import userEvent from "@testing-library/user-event";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";
import type { Candidate } from "./PipelineVisibleCardTypes";

const RECORDING_ID = "visible-pipeline-recording";
const RUN_ID = "visible-run-1";
const REVISION_ID = "visible-revision-1";
const PROPOSAL_REVISION_ID = "card-scene-proposal-revision-1";
const ITEM_ID = "event-1";
const SECOND_ITEM_ID = "event-2";
const FRAME_IDENTITY = {
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
const DETECTOR_CANDIDATE: Candidate = {
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
const SECOND_DETECTOR_CANDIDATE: Candidate = {
  ...DETECTOR_CANDIDATE,
  card_id: "run-card-2",
  geometry: {
    kind: "detector-box/v1",
    box_2d: { x_min: 200, y_min: 200, x_max: 700, y_max: 700 },
  },
};
const IGNORE_REGION = {
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

const SEGMENTED_GEOMETRY_WITH_DERIVED_BOX: Candidate["geometry"] = {
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

const MULTI_POLYGON_GEOMETRY_WITH_DERIVED_BOX: Candidate["geometry"] = {
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

function generatedResult() {
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

function generatedResultWithTwoFrames() {
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

function generatedResultWithFrames(count: number) {
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

function reference(state: "pending" | "accepted" | "corrected" = "pending") {
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

function referenceWithSegmentedGeometry() {
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

function referenceWithEmptyCandidates() {
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

function generatedResultWithTwoCandidates() {
  const result = generatedResult();
  result.revisions[0].content.outcomes[0].candidates = [
    DETECTOR_CANDIDATE,
    SECOND_DETECTOR_CANDIDATE,
  ];
  return result;
}

function referenceWithTwoCandidates() {
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

function referenceWithAdjacentCandidates(
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

function referenceWithIgnoreRegion(
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

function referenceWithMultiPolygonGeometry() {
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

function referenceWithPolygon(polygon: { x: number; y: number }[]) {
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

function referenceWithTwoFrames() {
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

function referenceWithReviewedPreviousIgnoreRegion() {
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

function referenceAfterCopyingPreviousIgnoreRegion() {
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

function emptyReference() {
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

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PipelineVisibleCardEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("keeps generated detector output read-only and uses the derived frame URL", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(generatedResult())),
    );
    vi.stubGlobal("fetch", fetchImplementation);
    const railItems = vi.fn();

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
        onRailItemsChange={railItems}
      />,
    );

    expect(
      await screen.findByRole("img", { name: /visible-card proposal/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("video")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Visible-card suggestions" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Generated detector output is immutable/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Source revision/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Resolved-frame timeline"),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(railItems).toHaveBeenLastCalledWith([
        expect.objectContaining({
          itemId: ITEM_ID,
          proposalCount: 1,
          timeUs: FRAME_IDENTITY.requested_time_us,
        }),
      ]),
    );
    expect(
      fetchImplementation.mock.calls.filter(([input]) =>
        String(input).includes("/pipeline/visible-cards/visible-run-1/result"),
      ),
    ).toHaveLength(1);
  });

  it("shows failed fit diagnostics and opens the worst held-out frame", async () => {
    const diagnosticsRun = {
      run_id: "proposal-run-failed",
      recording_id: RECORDING_ID,
      processor_type: "visible-card-scene-proposal",
      status: "failed",
      attempt: 1,
      request: { visible_card_revision_id: REVISION_ID },
      state: {
        metrics: {
          schema_version: "proposed-card-scene-failure-diagnostics/v1",
          calibration_run: {
            failure: {
              code: "held_out_boundary_failed",
              message: "Held-out card boundaries exceed the limit.",
              action: "Inspect the worst-fit frames.",
            },
            calibration_fit_candidate: {
              candidate_digest: "candidate-digest",
              source_revision: REVISION_ID,
              fit_observation_ids: ["candidate-1"],
              held_out_observation_ids: ["candidate-2"],
            },
            diagnostics: {
              candidate_yield: {
                raw_count: 3,
                accepted_count: 2,
                geometry_count: 2,
                quality_count: 2,
              },
              failed_gates: ["held_out_boundary"],
              unavailable_gates: [],
              candidate_evidence: [
                {
                  candidate_id: "candidate-1",
                  source_frame_id: ITEM_ID,
                  fit_decision: "held_out",
                  projected_full_card_outline: [
                    [10, 10],
                    [60, 10],
                    [60, 70],
                    [10, 70],
                  ],
                  residual: {
                    median_boundary_distance_px: 2,
                    p90_boundary_distance_px: 4,
                    maximum_boundary_distance_px: 5,
                    p90_boundary_distance_over_short_side: 0.08,
                  },
                },
                {
                  candidate_id: "candidate-2",
                  source_frame_id: SECOND_ITEM_ID,
                  fit_decision: "held_out",
                  projected_full_card_outline: [
                    [20, 20],
                    [80, 20],
                    [80, 75],
                    [20, 75],
                  ],
                  residual: {
                    median_boundary_distance_px: 6,
                    p90_boundary_distance_px: 11,
                    maximum_boundary_distance_px: 14,
                    p90_boundary_distance_over_short_side: 0.22,
                  },
                },
                {
                  candidate_id: "run-card-2",
                  source_frame_id: SECOND_ITEM_ID,
                  fit_decision: "selector_rejected:frame_boundary",
                  rejection_reason: "frame_boundary",
                  confidence: 0.94,
                  quality_metrics: { quality_score: 0.81 },
                  projected_full_card_outline: null,
                  residual: null,
                },
              ],
              validation: {
                held_out_summary: {
                  count: 2,
                  median_boundary_distance_px: 4,
                  p90_boundary_distance_px: 10,
                  worst_boundary_distance_px: 14,
                  p90_boundary_distance_over_short_side: 0.22,
                },
                absolute_size: {
                  status: "unavailable",
                  short_side_bias: null,
                  area_bias: null,
                },
              },
            },
          },
        },
      },
    };
    const fetchImplementation = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      if (url.includes("/pipeline/proposed-card-scenes")) {
        return Promise.resolve(
          jsonResponse({ recording_id: RECORDING_ID, runs: [diagnosticsRun] }),
        );
      }
      return Promise.resolve(
        jsonResponse(
          url.includes("/result")
            ? generatedResultWithTwoFrames()
            : { recording_id: RECORDING_ID, runs: [] },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchImplementation);

    const user = userEvent.setup();
    const { container } = render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    const diagnostic = await screen.findByRole("region", {
      name: "Calibration fit diagnostic",
    });
    expect(diagnostic).toHaveAttribute("data-diagnostic-only", "true");
    expect(diagnostic).toHaveTextContent(
      "Failed calibration · diagnostic only",
    );
    expect(diagnostic).toHaveTextContent("2 accepted of 3 predictions");
    expect(within(diagnostic).getByLabelText(/Used for fit/)).toBeChecked();
    expect(within(diagnostic).getByLabelText(/Held out/)).toBeChecked();
    expect(within(diagnostic).getByLabelText(/Discarded/)).toBeChecked();
    expect(diagnostic).toHaveTextContent("Optional size comparison");
    expect(diagnostic).toHaveTextContent(
      "Held-out card boundaries exceed the limit.",
    );
    expect(
      container.querySelector(
        '[data-candidate-id="candidate-1"][data-calibration-status="fit"]',
      ),
    ).toHaveTextContent("M/P90/MAX 2.0/4.0/5.0 px");

    await user.click(
      screen.getByRole("button", {
        name: /Open worst fit 1 · event-2 · 14\.00 px max/,
      }),
    );
    expect(
      container.querySelector(
        '[data-calibration-fit-outline="true"][data-candidate-id="candidate-2"]',
      ),
    ).toBeInTheDocument();
    expect(
      container.querySelector(
        '[data-candidate-id="candidate-2"][data-calibration-status="held_out"]',
      ),
    ).toHaveTextContent("M/P90/MAX 6.0/11.0/14.0 px");
    expect(
      container.querySelector(
        '[data-candidate-id="run-card-2"][data-calibration-status="discarded"]',
      ),
    ).toHaveTextContent("frame boundary");
    expect(
      container.querySelector(
        '[data-candidate-id="run-card-2"] [data-geometry="detected"]',
      ),
    ).toBeInTheDocument();
    await user.click(within(diagnostic).getByLabelText(/Discarded/));
    expect(
      container.querySelector('[data-calibration-status="discarded"]'),
    ).not.toBeInTheDocument();
    await user.click(within(diagnostic).getByLabelText(/Held out/));
    expect(
      container.querySelector('[data-calibration-status="held_out"]'),
    ).not.toBeInTheDocument();
    await user.click(within(diagnostic).getByLabelText(/Used for fit/));
    expect(
      container.querySelector('[data-calibration-status="fit"]'),
    ).not.toBeInTheDocument();
  });

  it("keeps a portrait frame aspect ratio before the fullscreen surface layout", async () => {
    const result = generatedResult();
    result.revisions[0].content.outcomes[0].frame_identity = {
      ...FRAME_IDENTITY,
      width: 1080,
      height: 1920,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(result))),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    const surface = await screen.findByRole("img", {
      name: /visible-card proposal/,
    });
    expect(surface.parentElement).toHaveStyle({
      "--workbench-frame-aspect-ratio": "1080 / 1920",
    });
    expect(surface).toHaveAttribute("preserveAspectRatio", "xMidYMid meet");
    const background = surface.querySelector(
      '[data-workbench-background="camera"]',
    );
    expect(background).not.toBeNull();
    expect(background).toHaveAttribute("width", "1080");
    expect(background).toHaveAttribute("height", "1920");
    expect(background).toHaveAttribute("preserveAspectRatio", "none");
  });

  it("keeps frame navigation and selection actions in separate Timeline Rail slots", async () => {
    const controlsSlot = document.createElement("div");
    controlsSlot.dataset.timelineSeekingSlot = "true";
    const reviewControlsSlot = document.createElement("div");
    reviewControlsSlot.dataset.timelineReviewControlsSlot = "true";
    document.body.append(controlsSlot);
    document.body.append(reviewControlsSlot);
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>(() =>
          Promise.resolve(jsonResponse(generatedResult())),
        ),
      );

      render(
        <PipelineVisibleCardEditor
          recordingId={RECORDING_ID}
          durationUs={1_000_000}
          generatedRevisionId={REVISION_ID}
          generatedRunId={RUN_ID}
          view="generated"
        />,
      );

      await waitFor(() =>
        expect(
          controlsSlot.querySelector('[data-timeline-seeking-controls="true"]'),
        ).not.toBeNull(),
      );
      await waitFor(() =>
        expect(
          reviewControlsSlot.querySelector(
            '[data-timeline-seeking-controls="true"]',
          ),
        ).not.toBeNull(),
      );
      expect(controlsSlot.textContent).not.toContain("Add visible card");
      expect(reviewControlsSlot.textContent).toContain("＋");
      expect(
        reviewControlsSlot.querySelector(
          'button[title="Generated visible-card results are read-only. · N"]',
        ),
      ).not.toBeNull();
      expect(reviewControlsSlot.textContent).not.toContain("Accept frame");
    } finally {
      controlsSlot.remove();
      reviewControlsSlot.remove();
    }
  });

  it("prewarms the next neighboring frames in order", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input) =>
      String(input).includes("/pipeline/visible-cards/") &&
      String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResultWithFrames(10)))
        : Promise.resolve(new Response("warm")),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={2_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        selectionItemId="event-6"
        view="generated"
      />,
    );

    await screen.findByRole("img", { name: /visible-card proposal/ });
    await waitFor(() =>
      expect(
        screen
          .getByRole("img", { name: /visible-card proposal/ })
          .querySelector('[data-workbench-background="camera"]'),
      ).toHaveAttribute("href", expect.stringContaining("exact-event/600000")),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(([input]) =>
          String(input).includes("/derived-views/exact-event/"),
        ),
      ).toHaveLength(4),
    );
    expect(
      fetchImplementation.mock.calls
        .filter(([input]) =>
          String(input).includes("/derived-views/exact-event/"),
        )
        .map(([input]) => String(input).split("/").at(-1)),
    ).toEqual(["700000", "800000", "900000", "1000000"]);
  });

  it("does not let failed frame prewarming affect selection or review errors", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input) =>
      String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResultWithTwoFrames()))
        : Promise.reject(new Error("derived frame failed")),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={2_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    expect(
      await screen.findByRole("img", { name: /visible-card proposal/ }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(window.location.search).toContain(`item=${ITEM_ID}`),
    );
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() =>
      expect(window.location.search).toContain(`item=${SECOND_ITEM_ID}`),
    );
    expect(
      screen
        .getByRole("img", { name: /visible-card proposal/ })
        .querySelector('[data-workbench-background="camera"]'),
    ).toHaveAttribute("href", expect.stringContaining("exact-event/800000"));
    expect(screen.queryByText("derived frame failed")).not.toBeInTheDocument();
  });

  it("keeps active frame prewarming deduplicated across selection changes", async () => {
    const resolvers = new Map<string, () => void>();
    const fetchImplementation = vi.fn<typeof fetch>((input) => {
      if (String(input).includes("/result"))
        return Promise.resolve(jsonResponse(generatedResultWithTwoFrames()));
      const url = String(input);
      return new Promise<Response>((resolve) => {
        resolvers.set(url, () => resolve(new Response("warm")));
      });
    });
    vi.stubGlobal("fetch", fetchImplementation);

    const { unmount } = render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={2_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    await screen.findByRole("img", { name: /visible-card proposal/ });
    await waitFor(() =>
      expect(window.location.search).toContain(`item=${ITEM_ID}`),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(([input]) =>
          String(input).includes("/derived-views/exact-event/"),
        ),
      ).toHaveLength(1),
    );
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() =>
      expect(window.location.search).toContain(`item=${SECOND_ITEM_ID}`),
    );
    expect(
      fetchImplementation.mock.calls.filter(([input]) =>
        String(input).includes("exact-event/800000"),
      ),
    ).toHaveLength(1);
    for (const resolve of resolvers.values()) resolve();
    unmount();
  });

  it("renders each segmented visible-region polygon as its own overlay", async () => {
    const result = generatedResult();
    result.revisions[0].content.outcomes[0].candidates = [
      {
        ...DETECTOR_CANDIDATE,
        geometry: {
          kind: "visible-region/v1",
          visible_region: {
            polygons: [
              [
                { x: 100, y: 100 },
                { x: 400, y: 100 },
                { x: 400, y: 800 },
                { x: 100, y: 800 },
              ],
              [
                { x: 600, y: 200 },
                { x: 900, y: 200 },
                { x: 900, y: 700 },
                { x: 600, y: 700 },
              ],
            ],
          },
        },
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(result))),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    const canvas = await screen.findByRole("img", {
      name: "1 visible-card proposal",
    });
    expect(canvas.querySelectorAll("polygon")).toHaveLength(2);
  });

  it("keeps the generated frame and proposals visible after entering review before start", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input) =>
      String(input).includes("/pipeline/visible-cards/") &&
      String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse({ message: "not found" }, 404)),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        displayedRevisionId={null}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    expect(
      await screen.findByRole("img", { name: /visible-card proposal/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Start visible-card review" }),
    ).toBeInTheDocument();
    const proposal = screen.getByRole("button", {
      name: "Select proposal 1",
    });
    expect(proposal).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(proposal);
    expect(proposal).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Box")).toBeInTheDocument();
  });

  it("shows generated proposals when an existing maintained reference is empty", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(reference()));
      }
      return String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(emptyReference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    expect(
      await screen.findByRole("img", { name: /visible-card proposal/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Start visible-card review" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select proposal 1" }),
    ).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("operator-01"), "operator-01");
    await user.click(screen.getByRole("button", { name: "Start review" }));

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      { operation: "rebase", source_revision_id: REVISION_ID },
    ]);
    expect(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    ).toBeInTheDocument();
  });

  it("switches an existing review to the selected generated result", async () => {
    const staleReference = reference();
    staleReference.state.source_revision_id = "older-visible-revision";
    staleReference.draft.source_revision_id = "older-visible-revision";
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(reference()));
      }
      return String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(staleReference));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const switchButton = await screen.findByRole("button", {
      name: "Switch review to selected result",
    });
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("operator-01"), "operator-01");
    await user.click(switchButton);

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      { operation: "rebase", source_revision_id: REVISION_ID },
    ]);
    expect(
      await screen.findByText(
        /Review switched to the selected generated result/,
      ),
    ).toBeInTheDocument();
  });

  it("loads ready proposed scenes into an existing review", async () => {
    const currentReference = reference();
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      const url = String(input);
      if (url.includes("/pipeline/proposed-card-scenes")) {
        return Promise.resolve(
          jsonResponse({
            recording_id: RECORDING_ID,
            runs: [
              {
                run_id: "proposal-run-1",
                recording_id: RECORDING_ID,
                processor_type: "visible-card-scene-proposal",
                status: "complete",
                attempt: 1,
                request: { input_revision_ids: [REVISION_ID] },
                state: { output_revision_ids: [PROPOSAL_REVISION_ID] },
              },
            ],
          }),
        );
      }
      if (url.includes("/pipeline/calibration-refinement")) {
        return Promise.resolve(new Response(null, { status: 404 }));
      }
      if (init?.method === "PUT") {
        return Promise.resolve(
          jsonResponse({
            ...currentReference,
            draft: {
              ...currentReference.draft,
              proposal_revision_id: PROPOSAL_REVISION_ID,
            },
          }),
        );
      }
      return url.includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(currentReference));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const inspectButton = await screen.findByRole("button", {
      name: "Inspect proposed card scenes",
    });
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("operator-01"), "operator-01");
    await user.click(inspectButton);

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      {
        operation: "rebase",
        source_revision_id: REVISION_ID,
        proposal_revision_id: PROPOSAL_REVISION_ID,
      },
    ]);
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent(/Proposed card scenes loaded/);
    expect(toast.parentElement).toBe(document.body);
  });

  it("loads mapping anchors from the proposal used by the reviewed reference", async () => {
    const baseReference = reference();
    const currentReference = {
      ...baseReference,
      draft: {
        ...baseReference.draft,
        proposal_revision_id: PROPOSAL_REVISION_ID,
      },
    };
    const fetchImplementation = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      if (url.includes("/pipeline/proposed-card-scenes")) {
        return Promise.resolve(
          jsonResponse({ recording_id: RECORDING_ID, runs: [] }),
        );
      }
      if (url.includes("/pipeline/calibration-refinement")) {
        return Promise.resolve(new Response(null, { status: 404 }));
      }
      return Promise.resolve(jsonResponse(currentReference));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId="different-visible-revision"
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(([input]) =>
          String(input).includes(
            `/pipeline/calibration-refinement?proposal_revision_id=${PROPOSAL_REVISION_ID}`,
          ),
        ),
      ).toBe(true),
    );
  });

  it("loads maintained frames when an older reference omits ignore regions", async () => {
    const legacyReference = structuredClone(reference()) as unknown as {
      draft: { items: Array<{ item: Record<string, unknown> }> };
    };
    legacyReference.draft.items = legacyReference.draft.items.map((item) => {
      const legacyItem = Object.fromEntries(
        Object.entries(item.item).filter(([key]) => key !== "ignored_regions"),
      );
      return { ...item, item: legacyItem };
    });
    const railItems = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(legacyReference))),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
        onRailItemsChange={railItems}
      />,
    );

    expect(
      await screen.findByRole("img", { name: /visible-card proposal/ }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(railItems).toHaveBeenLastCalledWith([
        expect.objectContaining({
          itemId: ITEM_ID,
          proposalCount: 1,
          timeUs: FRAME_IDENTITY.requested_time_us,
        }),
      ]),
    );
  });

  it("edits stored polygons after starting review when derived box data is also present", async () => {
    const segmentedReference = referenceWithSegmentedGeometry();
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(segmentedReference));
      }
      return String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(emptyReference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: "Start visible-card review" });
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("operator-01"), "operator-01");
    await user.click(screen.getByRole("button", { name: "Start review" }));
    await screen.findByRole("button", { name: "Select proposal 1" });
    await user.click(screen.getByRole("button", { name: "Select proposal 1" }));

    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 140, 180",
      }),
    ).toBeInTheDocument();
    const polygons = screen
      .getByRole("img", { name: "1 visible-card proposal" })
      .querySelectorAll("polygon");
    expect(polygons).toHaveLength(2);
    expect(polygons[0]).toHaveAttribute("stroke-width", "1.25");
    expect(polygons[1]).toHaveAttribute("stroke-width", "1.25");
    expect(polygons[1]).toHaveAttribute("stroke-dasharray", "4 3");
    expect(
      screen.queryByRole("button", { name: /Select polygon/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Drag a point to adjust a region/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Visible region editor" }),
    ).not.toBeInTheDocument();
  });

  it("opens the selected card and polygon when a canvas polygon is clicked", async () => {
    const segmentedReference = referenceWithMultiPolygonGeometry();
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(jsonResponse(segmentedReference)),
      ),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Edit run-card-1, polygon 2",
      }),
    );

    expect(
      screen.getByRole("button", { name: "Select proposal 1" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", {
        name: "Polygon 2, point 1 at 100, 100",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Select polygon 1 for proposal 1",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Select polygon 2 for proposal 1",
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("switches to another clearly separated card polygon from the editor canvas", async () => {
    const adjacentReference = referenceWithAdjacentCandidates();
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(jsonResponse(adjacentReference)),
      ),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      (await screen.findAllByRole("button", { name: "Select proposal 1" }))[0],
    );
    const canvas = screen.getByRole("img", {
      name: "2 visible-card proposals",
    });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(canvas, { clientX: 75, clientY: 30 });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Select proposal 2" }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
    expect(
      screen.getByRole("button", { name: "Polygon 1, point 1 at 550, 150" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Select polygon 1 for proposal 1",
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps a near-boundary click on the active polygon", async () => {
    const insertedPoint = { x: 505, y: 300 };
    const adjacentReference = referenceWithAdjacentCandidates([
      { x: 100, y: 100 },
      { x: 500, y: 100 },
      { x: 500, y: 500 },
      { x: 100, y: 500 },
    ]);
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(
          init?.method === "PUT"
            ? referenceWithAdjacentCandidates([
                { x: 100, y: 100 },
                { x: 500, y: 100 },
                insertedPoint,
                { x: 500, y: 500 },
                { x: 100, y: 500 },
              ])
            : adjacentReference,
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      (await screen.findAllByRole("button", { name: "Select proposal 1" }))[0],
    );
    const canvas = screen.getByRole("img", {
      name: "2 visible-card proposals",
    });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(canvas, { clientX: 50.5, clientY: 30 });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Polygon 1, point 3 at 505, 300" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Select proposal 1" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("converts multiple selected proposals into one untidy-stack ignore region", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(
          init?.method === "PUT"
            ? referenceWithIgnoreRegion([])
            : referenceWithTwoCandidates(),
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select proposal 1 for ignore region",
      }),
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select proposal 2 for ignore region",
      }),
    );
    await user.click(
      screen.getByRole("button", {
        name: /Convert selection to ignore region/,
      }),
    );

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      expect.objectContaining({
        operation: "convert_to_ignore_region",
        item_id: ITEM_ID,
        candidate_ids: ["run-card-1", "run-card-2"],
        region: expect.objectContaining({
          reason: "untidy_stack",
          geometry: expect.objectContaining({
            kind: "reviewed-ignore-region/v1",
            polygons: expect.any(Array),
          }),
        }),
      }),
    ]);
    expect(
      await screen.findByRole("region", {
        name: "Visible-card ignore regions",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Ignore region 1")).toBeInTheDocument();
    expect(screen.getAllByText("Ignore regions")).not.toHaveLength(0);
  });

  it("creates an ignore region from detector proposals when the draft frame has no candidates", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      const url = String(input);
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(referenceWithIgnoreRegion([])));
      }
      if (url.includes("/result")) {
        return Promise.resolve(jsonResponse(generatedResultWithTwoCandidates()));
      }
      return Promise.resolve(jsonResponse(referenceWithEmptyCandidates()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await screen.findByRole("checkbox", {
      name: "Select proposal 1 for ignore region",
    });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select proposal 1 for ignore region",
      }),
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select proposal 2 for ignore region",
      }),
    );
    await user.click(
      screen.getByRole("button", {
        name: /Convert selection to ignore region/,
      }),
    );

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      expect.objectContaining({
        operation: "create_ignore_region",
        item_id: ITEM_ID,
        region: expect.objectContaining({
          reason: "untidy_stack",
          geometry: expect.objectContaining({
            kind: "reviewed-ignore-region/v1",
            polygons: expect.any(Array),
          }),
        }),
      }),
    ]);
    expect(requestBody.operations[0].candidate_ids).toBeUndefined();
    expect(
      await screen.findByRole("region", {
        name: "Visible-card ignore regions",
      }),
    ).toBeInTheDocument();
  });

  it("copies ignore regions from the previous reviewed frame", async () => {
    const previous = referenceWithReviewedPreviousIgnoreRegion();
    const copied = referenceAfterCopyingPreviousIgnoreRegion();
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(jsonResponse(init?.method === "PUT" ? copied : previous)),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    const frameNavigation = await screen.findByRole("group", {
      name: "Frame navigation",
    });
    const copyButton = screen.getByRole("button", {
      name: "Copy ignore regions",
    });
    expect(copyButton).toBeDisabled();

    await user.click(
      within(frameNavigation).getByRole("button", { name: "Next frame" }),
    );
    expect(copyButton).toBeEnabled();
    await user.click(copyButton);

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(1),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      {
        operation: "create_ignore_region",
        item_id: SECOND_ITEM_ID,
        region: {
          ...IGNORE_REGION,
          region_id: `ignore-${SECOND_ITEM_ID}-copied-1`,
        },
      },
    ]);
    expect(
      await screen.findByRole("region", {
        name: "Visible-card ignore regions",
      }),
    ).toBeInTheDocument();
  });

  it("draws, reshapes, and deletes an ignore region with dedicated operations", async () => {
    const responses = [
      referenceWithTwoCandidates(),
      referenceWithIgnoreRegion([]),
      referenceWithIgnoreRegion([]),
      reference(),
    ];
    let putCount = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        const response =
          responses[Math.min(putCount + 1, responses.length - 1)];
        putCount += 1;
        return Promise.resolve(jsonResponse(response));
      }
      return Promise.resolve(jsonResponse(responses[0]));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(
      screen.getByRole("button", {
        name: "Draw ignore region in shared workbench",
      }),
    );
    const canvas = screen.getByRole("img", {
      name: "2 visible-card proposals",
    });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 80 });
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const createBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(createBody.operations[0]).toMatchObject({
      operation: "create_ignore_region",
      item_id: ITEM_ID,
      region: { reason: "untidy_stack" },
    });

    await user.click(
      screen.getByRole("button", { name: "Select ignore region 1" }),
    );
    const point = screen.getByRole("button", {
      name: "Polygon 1, point 1 at 100, 100",
    });
    const regionCanvas = screen.getByRole("img", {
      name: "0 visible-card proposals and 1 ignore region",
    });
    vi.spyOn(regionCanvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(point, { clientX: 10, clientY: 10, pointerId: 5 });
    fireEvent.pointerMove(regionCanvas, {
      clientX: 20,
      clientY: 20,
      pointerId: 5,
    });
    fireEvent.pointerUp(regionCanvas, { pointerId: 5 });
    await waitFor(() => expect(putCount).toBe(2));
    const replaceBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[1]?.[1]?.body,
      ),
    );
    expect(replaceBody.operations[0]).toMatchObject({
      operation: "replace_ignore_region",
      item_id: ITEM_ID,
      region_id: IGNORE_REGION.region_id,
    });

    await user.click(screen.getByRole("button", { name: "Delete selection" }));
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(3),
    );
    const deleteBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[2]?.[1]?.body,
      ),
    );
    expect(deleteBody.operations[0]).toMatchObject({
      operation: "delete_ignore_region",
      item_id: ITEM_ID,
      region_id: IGNORE_REGION.region_id,
    });
  });

  it("saves points added after an ignore region reaches three points", async () => {
    let putCount = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putCount += 1;
        return Promise.resolve(jsonResponse(referenceWithIgnoreRegion([])));
      }
      return Promise.resolve(jsonResponse(reference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await screen.findByRole("img", { name: /visible-card proposal/ });
    await user.click(
      screen.getByRole("button", {
        name: "Draw ignore region in shared workbench",
      }),
    );
    const canvas = screen.getByRole("img", { name: "1 visible-card proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 10 });
    fireEvent.pointerDown(canvas, { clientX: 80, clientY: 80 });
    await waitFor(() => expect(putCount).toBe(1));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Ignore region created.",
      ),
    );
    const createBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[0]?.[1]?.body,
      ),
    );

    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 80 });
    await waitFor(() => expect(putCount).toBe(2));

    const replaceBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        )[1]?.[1]?.body,
      ),
    );
    expect(replaceBody.operations[0]).toMatchObject({
      operation: "replace_ignore_region",
      item_id: ITEM_ID,
      region_id: createBody.operations[0].region.region_id,
      region: {
        geometry: {
          polygons: [
            [
              { x: 100, y: 100 },
              { x: 800, y: 100 },
              { x: 800, y: 800 },
              { x: 100, y: 800 },
            ],
          ],
        },
      },
    });
  });

  it("adds a second polygon and saves its completed points", async () => {
    const responses = [reference(), reference("corrected")];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT")
        return Promise.resolve(jsonResponse(responses[1]));
      return Promise.resolve(jsonResponse(responses[0]));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    await user.click(screen.getByRole("button", { name: "Add polygon" }));
    expect(
      screen.getByRole("button", {
        name: "Select polygon 2 for proposal 1",
      }),
    ).toHaveAttribute("aria-pressed", "true");

    const canvas = screen.getByRole("img", { name: "1 visible-card proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 20 });
    fireEvent.pointerDown(canvas, { clientX: 40, clientY: 20 });
    fireEvent.pointerDown(canvas, { clientX: 30, clientY: 40 });

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(1),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(
      requestBody.operations[0].item.candidates[0].geometry.visible_region
        .polygons,
    ).toHaveLength(2);
  });

  it("commits the clamped edge point and ends the drag when the pointer leaves", async () => {
    const responses = [reference(), reference("corrected")];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        return Promise.resolve(jsonResponse(responses[1]));
      }
      return Promise.resolve(jsonResponse(responses[0]));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("img", { name: /visible-card proposal/ });
    const controls = screen.getByRole("group", {
      name: "Frame navigation",
    });
    expect(
      within(controls).getByRole("button", { name: "Previous frame" }),
    ).toBeInTheDocument();
    expect(
      within(controls).getByRole("button", { name: "Previous frame" }),
    ).toHaveAttribute("aria-keyshortcuts", "ArrowLeft");
    expect(
      screen.getByRole("button", { name: "Accept frame" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add visible card" }),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select proposal 1" }));
    const point = screen.getByRole("button", {
      name: "Polygon 1, point 1 at 100, 100",
    });
    const canvas = screen.getByRole("img", { name: "1 visible-card proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.pointerDown(point, { clientX: 10, clientY: 10, pointerId: 3 });
    expect(point).toHaveAttribute("fill", "#ffffff");
    expect(point).toHaveAttribute("stroke", "#ffd24f");
    expect(point).toHaveAttribute("r", "1");
    fireEvent.pointerMove(canvas, { clientX: 15, clientY: 20, pointerId: 3 });
    fireEvent.pointerLeave(canvas, {
      clientX: -10,
      clientY: 50,
      pointerId: 3,
    });
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 0, 500",
      }),
    ).toBeInTheDocument();
    fireEvent.pointerMove(canvas, {
      clientX: 80,
      clientY: 80,
      pointerId: 3,
    });
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 0, 500",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Polygon 1, point 1 at 800, 800",
      }),
    ).not.toBeInTheDocument();
    fireEvent.pointerUp(canvas, { pointerId: 3 });

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(1),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toHaveLength(1);
    expect(requestBody.operations[0]).toMatchObject({
      operation: "set_frame_review",
      item_id: ITEM_ID,
      item: {
        event_id: ITEM_ID,
        frame_identity: FRAME_IDENTITY,
        status: "detected",
      },
    });
    expect(
      requestBody.operations[0].item.candidates[0].geometry.visible_region
        .polygons[0][0],
    ).toEqual({ x: 0, y: 500 });
    expect(requestBody.operations[0].item.candidates[0].geometry.kind).toBe(
      "reviewed-visible-region/v1",
    );
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 0, 500",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Close editor Esc" }),
    ).not.toBeInTheDocument();
  });

  it("selects a point without moving it until a real drag starts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(reference()))),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    const point = screen.getByRole("button", {
      name: "Polygon 1, point 1 at 100, 100",
    });
    const canvas = screen.getByRole("img", { name: "1 visible-card proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(point, {
      clientX: 12,
      clientY: 12,
      pointerId: 9,
    });
    fireEvent.pointerMove(canvas, {
      clientX: 14,
      clientY: 14,
      pointerId: 9,
    });
    fireEvent.pointerUp(canvas, { pointerId: 9 });

    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Polygon 1, point 1 at 140, 140",
      }),
    ).not.toBeInTheDocument();
  });

  it("keeps edit mode active and selects a card per frame", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((_input, init) =>
        Promise.resolve(
          jsonResponse(
            init?.method === "PUT" ? reference() : referenceWithTwoFrames(),
          ),
        ),
      ),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    const visibleRegionTool = screen.getByRole("button", {
      name: "Edit Visible regions",
    });
    expect(visibleRegionTool).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: "Close editor Esc" }),
    ).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "ArrowRight" });

    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Polygon 1, point 1 at 100, 100",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(visibleRegionTool).toHaveAttribute("aria-pressed", "true");

    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).toBeInTheDocument();
  });

  it("ends edit mode when changing the frame state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((_input, init) =>
        Promise.resolve(
          jsonResponse(
            init?.method === "PUT" ? reference("accepted") : reference(),
          ),
        ),
      ),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    await user.click(screen.getByRole("button", { name: "Accept frame" }));

    expect(
      screen.queryByRole("button", { name: "Close editor Esc" }),
    ).not.toBeInTheDocument();
  });

  it("closes polygon editing with Escape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(reference()))),
    );

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Select proposal 1" }),
    );
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(
      screen.queryByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      }),
    ).not.toBeInTheDocument();
  });

  it("inserts a clicked point between the endpoints of the nearest polygon edge", async () => {
    const responses = [
      referenceWithPolygon([
        { x: 100, y: 100 },
        { x: 900, y: 100 },
        { x: 900, y: 200 },
        { x: 100, y: 800 },
      ]),
      reference("corrected"),
    ];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT")
        return Promise.resolve(jsonResponse(responses[1]));
      return Promise.resolve(jsonResponse(responses[0]));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("img", { name: /visible-card proposal/ });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select proposal 1" }));
    const canvas = screen.getByRole("img", { name: "1 visible-card proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 15 });

    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(
          ([, init]) => init?.method === "PUT",
        ),
      ).toHaveLength(1),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(
      requestBody.operations[0].item.candidates[0].geometry.visible_region
        .polygons[0],
    ).toEqual([
      { x: 100, y: 100 },
      { x: 500, y: 150 },
      { x: 900, y: 100 },
      { x: 900, y: 200 },
      { x: 100, y: 800 },
    ]);
    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 2 at 500, 150",
      }),
    ).toBeInTheDocument();
  });

  it.each(["Backspace", "Delete"])(
    "removes the selected polygon point with %s",
    async (key) => {
      const responses = [reference(), reference("corrected")];
      const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
        if (init?.method === "PUT")
          return Promise.resolve(jsonResponse(responses[1]));
        return Promise.resolve(jsonResponse(responses[0]));
      });
      vi.stubGlobal("fetch", fetchImplementation);

      render(
        <PipelineVisibleCardEditor
          recordingId={RECORDING_ID}
          durationUs={1_000_000}
          generatedRevisionId={REVISION_ID}
          generatedRunId={RUN_ID}
          view="reviewed"
        />,
      );

      await screen.findByRole("img", { name: /visible-card proposal/ });
      const user = userEvent.setup();
      await user.click(
        screen.getByRole("button", { name: "Select proposal 1" }),
      );
      const point = screen.getByRole("button", {
        name: "Polygon 1, point 1 at 100, 100",
      });
      fireEvent.pointerDown(point, { pointerId: 3 });
      fireEvent.keyDown(point, { key });

      await waitFor(() =>
        expect(
          fetchImplementation.mock.calls.filter(
            ([, init]) => init?.method === "PUT",
          ),
        ).toHaveLength(1),
      );
      const requestBody = JSON.parse(
        String(
          fetchImplementation.mock.calls.find(
            ([, init]) => init?.method === "PUT",
          )?.[1]?.body,
        ),
      );
      expect(
        requestBody.operations[0].item.candidates[0].geometry.visible_region
          .polygons[0],
      ).toEqual([
        { x: 800, y: 100 },
        { x: 800, y: 800 },
        { x: 100, y: 800 },
      ]);
      expect(
        screen.queryByRole("button", { name: "Close editor Esc" }),
      ).not.toBeInTheDocument();
    },
  );

  it("selects the requested generated frame and reports both rail items", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(generatedResultWithTwoFrames())),
    );
    vi.stubGlobal("fetch", fetchImplementation);
    const railItems = vi.fn();

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        selectionItemId={SECOND_ITEM_ID}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
        onRailItemsChange={railItems}
      />,
    );

    expect(
      await screen.findByRole("img", { name: /visible-card proposal/ }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(railItems).toHaveBeenLastCalledWith([
        expect.objectContaining({ itemId: ITEM_ID, timeUs: 400_000 }),
        expect.objectContaining({ itemId: SECOND_ITEM_ID, timeUs: 800_000 }),
      ]),
    );
  });

  it("restores generated suggestions as a frame that still needs acceptance", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "PUT")
        return Promise.resolve(jsonResponse(reference()));
      return String(input).includes("/result")
        ? Promise.resolve(jsonResponse(generatedResult()))
        : Promise.resolve(jsonResponse(reference("corrected")));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", {
        name: "Restore suggestion",
      }),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      {
        operation: "restore_frame_suggestions",
        item_id: ITEM_ID,
        item: expect.objectContaining({
          event_id: ITEM_ID,
          candidates: [DETECTOR_CANDIDATE],
        }),
      },
    ]);
  });

  it("toggles an accepted frame back to unreviewed", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(
          init?.method === "PUT" ? reference() : reference("accepted"),
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Mark frame unreviewed" }),
    );
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations).toEqual([
      { operation: "set_frame_unreviewed", item_id: ITEM_ID },
    ]);
    expect(screen.getAllByText(/Unreviewed/)).not.toHaveLength(0);
  });

  it("retries a transient draft save and keeps the review command intact", async () => {
    let putAttempts = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putAttempts += 1;
        if (putAttempts === 1) {
          return Promise.resolve(
            jsonResponse({ message: "temporary outage" }, 503),
          );
        }
        return Promise.resolve(jsonResponse(reference("accepted")));
      }
      return Promise.resolve(jsonResponse(reference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );
    await screen.findByRole("img", { name: /visible-card proposal/ });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mark empty" }));

    await waitFor(
      () => {
        expect(putAttempts).toBe(2);
      },
      { timeout: 3_000 },
    );
    expect(
      fetchImplementation.mock.calls.filter(([input]) =>
        String(input).includes("/pipeline/references/"),
      ),
    ).toHaveLength(3);
  });

  it("records reviewed empty coverage and keeps completion blocked until a frame is decided", async () => {
    const responses = [reference(), reference("accepted")];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(init?.method === "PUT" ? responses[1] : responses[0]),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisibleCardEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );
    await screen.findByRole("img", { name: /visible-card proposal/ });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mark empty" }));
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.some(
          ([, init]) => init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const requestBody = JSON.parse(
      String(
        fetchImplementation.mock.calls.find(
          ([, init]) => init?.method === "PUT",
        )?.[1]?.body,
      ),
    );
    expect(requestBody.operations[0]).toEqual({
      operation: "set_frame_empty",
      item_id: ITEM_ID,
    });
    expect(
      screen.getByText(/Use the Timeline Rail to decide this frame/),
    ).toBeInTheDocument();
  });
});
