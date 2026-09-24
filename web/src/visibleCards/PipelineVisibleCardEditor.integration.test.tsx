import userEvent from "@testing-library/user-event";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";
import * as fixtures from "./PipelineVisibleCardEditorFixtures";
const {
  DETECTOR_CANDIDATE,
  FRAME_IDENTITY,
  ITEM_ID,
  RECORDING_ID,
  REVISION_ID,
  RUN_ID,
  SECOND_ITEM_ID,
  emptyReference,
  generatedResult,
  generatedResultWithFrames,
  generatedResultWithTwoFrames,
  jsonResponse,
  reference,
} = fixtures;

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
          'button[title="Generated visible-card results are read-only. (N)"]',
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
});
