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
  FRAME_IDENTITY,
  IGNORE_REGION,
  ITEM_ID,
  PROPOSAL_REVISION_ID,
  RECORDING_ID,
  REVISION_ID,
  RUN_ID,
  SECOND_ITEM_ID,
  emptyReference,
  generatedResult,
  generatedResultWithTwoCandidates,
  jsonResponse,
  reference,
  referenceAfterCopyingPreviousIgnoreRegion,
  referenceWithAdjacentCandidates,
  referenceWithEmptyCandidates,
  referenceWithIgnoreRegion,
  referenceWithMultiPolygonGeometry,
  referenceWithReviewedPreviousIgnoreRegion,
  referenceWithSegmentedGeometry,
  referenceWithTwoCandidates,
} = fixtures;

describe("PipelineVisibleCardEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
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

  it("shows incomplete calibration preview data without crashing", async () => {
    const currentReference = {
      ...reference(),
      draft: {
        ...reference().draft,
        proposal_revision_id: PROPOSAL_REVISION_ID,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) =>
        Promise.resolve(
          jsonResponse(
            String(input).includes("/pipeline/calibration-refinement")
              ? {
                  schema_version: "table-plane-calibration-refinement/v1",
                  recording_id: RECORDING_ID,
                  proposal_revision_id: PROPOSAL_REVISION_ID,
                  draft: {
                    draft_id: "draft-1",
                    revision: 0,
                    anchors: [],
                    commands: [],
                  },
                  preview: {
                    status: "blocked",
                    changed_frame_ids: null,
                    gates: null,
                    most_affected_frame_ids: null,
                  },
                  anchor_contributions: [],
                }
              : String(input).includes("/pipeline/proposed-card-scenes")
                ? { recording_id: RECORDING_ID, runs: [] }
                : currentReference,
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
    expect(
      await screen.findByText(/The preview data is incomplete/),
    ).toBeInTheDocument();
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
        return Promise.resolve(
          jsonResponse(generatedResultWithTwoCandidates()),
        );
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
});
