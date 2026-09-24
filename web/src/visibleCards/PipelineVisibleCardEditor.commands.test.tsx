import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PipelineVisibleCardEditor } from "./PipelineVisibleCardEditor";
import * as fixtures from "./PipelineVisibleCardEditorFixtures";
const {
  DETECTOR_CANDIDATE,
  ITEM_ID,
  PROPOSAL_REVISION_ID,
  RECORDING_ID,
  REVISION_ID,
  RUN_ID,
  SECOND_ITEM_ID,
  generatedResult,
  generatedResultWithTwoFrames,
  jsonResponse,
  reference,
  referenceWithPolygon,
} = fixtures;

describe("PipelineVisibleCardEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
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

  it("polls a queued proposal run until it reaches a terminal result", async () => {
    let runReads = 0;
    const queuedRun = {
      run_id: "proposal-poll-1",
      recording_id: RECORDING_ID,
      processor_type: "visible-card-scene-proposal",
      status: "queued",
      attempt: 1,
      request: { input_revision_ids: [REVISION_ID] },
      state: { output_revision_ids: [] },
    };
    const completeRun = {
      ...queuedRun,
      status: "complete",
      state: { output_revision_ids: [PROPOSAL_REVISION_ID] },
    };
    const fetchImplementation = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      if (url.endsWith("/pipeline/proposed-card-scenes")) {
        return Promise.resolve(
          jsonResponse({ recording_id: RECORDING_ID, runs: [queuedRun] }),
        );
      }
      if (url.endsWith("/pipeline/proposed-card-scenes/proposal-poll-1")) {
        runReads += 1;
        return Promise.resolve(jsonResponse(completeRun));
      }
      return Promise.resolve(
        jsonResponse(url.includes("/result") ? generatedResult() : reference()),
      );
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

    await waitFor(
      () => {
        expect(runReads).toBeGreaterThanOrEqual(1);
        expect(
          screen.getByRole("button", { name: "Inspect proposed card scenes" }),
        ).toBeInTheDocument();
      },
      { timeout: 4_000 },
    );
  });

  it("reloads the winning draft after a stale revision and retries the queued command", async () => {
    let putAttempts = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putAttempts += 1;
        return Promise.resolve(
          putAttempts === 1
            ? jsonResponse({ message: "stale draft" }, 409)
            : jsonResponse(reference("accepted")),
        );
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

    await userEvent.click(
      await screen.findByRole("button", { name: "Mark empty" }),
    );
    const reloadButton = await screen.findByRole("button", {
      name: "Reload winning draft and retry",
    });
    await userEvent.click(reloadButton);

    await waitFor(() => expect(putAttempts).toBe(2));
    expect(screen.getByRole("heading", { name: "Saved" })).toBeInTheDocument();
    const putBodies = fetchImplementation.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(putBodies[0].operations).toEqual([
      { operation: "set_frame_empty", item_id: ITEM_ID },
    ]);
    expect(putBodies[1].operations).toEqual(putBodies[0].operations);
  });

  it("applies the calibration preview with its draft revision and digest", async () => {
    const currentReference = {
      ...reference(),
      draft: {
        ...reference().draft,
        proposal_revision_id: PROPOSAL_REVISION_ID,
      },
    };
    const refinement = {
      schema_version: "table-plane-calibration-refinement/v1",
      recording_id: RECORDING_ID,
      proposal_revision_id: PROPOSAL_REVISION_ID,
      draft: {
        draft_id: "calibration-draft-1",
        revision: 3,
        anchors: [],
        commands: [],
      },
      preview: {
        status: "pass",
        candidate_calibration: null,
        accepted_anchor_count: 4,
        rejected_candidate_count: 0,
        fit_residual: 0,
        held_out_alignment_change_px: 0,
        changed_frame_ids: [],
        changed_card_ids: [],
        max_source_pixel_displacement: 0,
        most_affected_frame_ids: [],
        gates: [],
        failure: null,
        preview_digest: "preview-digest-1",
      },
      anchor_contributions: [],
    };
    let appliedPayload: Record<string, unknown> | null = null;
    const fetchImplementation = vi.fn<typeof fetch>((input, init) => {
      const url = String(input);
      if (url.includes("/pipeline/calibration-refinement/apply")) {
        appliedPayload = JSON.parse(String(init?.body));
        return Promise.resolve(
          jsonResponse({
            schema_version: "table-plane-calibration-refinement/v1",
            action: "applied",
            recording_id: RECORDING_ID,
            source_proposal_revision_id: PROPOSAL_REVISION_ID,
            proposal_revision_id: "applied-proposal-revision",
            calibration_revision_id: "calibration-revision-1",
            receipt: {},
            reference: currentReference,
          }),
        );
      }
      if (url.includes("/pipeline/calibration-refinement")) {
        return Promise.resolve(jsonResponse(refinement));
      }
      if (url.endsWith("/pipeline/proposed-card-scenes")) {
        return Promise.resolve(
          jsonResponse({
            recording_id: RECORDING_ID,
            runs: [
              {
                run_id: "proposal-calibration-1",
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
      return Promise.resolve(
        jsonResponse(
          url.includes("/result") ? generatedResult() : currentReference,
        ),
      );
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

    await userEvent.click(
      await screen.findByRole("button", { name: "Apply calibration to table" }),
    );
    await waitFor(() => expect(appliedPayload).not.toBeNull());
    expect(appliedPayload).toEqual({
      draft_id: "calibration-draft-1",
      expected_revision: 3,
      preview_digest: "preview-digest-1",
      operator_id: expect.any(String),
      confirm_affected: false,
    });
    expect(
      await screen.findByText(/Applied calibration calibration-revision-1/),
    ).toBeInTheDocument();
  });
});
