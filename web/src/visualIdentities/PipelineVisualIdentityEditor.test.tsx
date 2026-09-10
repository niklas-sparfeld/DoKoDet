import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PipelineVisualIdentityEditor } from "./PipelineVisualIdentityEditor";

const RECORDING_ID = "identity-pipeline-recording";
const RUN_ID = "identity-run-1";
const REVISION_ID = "identity-revision-1";
const CARD_ID = "card-1";
const FRAME = {
  schema_version: "exact-event/v1",
  source_video_sha256: "a".repeat(64),
  requested_time_us: 750_000,
  frame_index: 7,
  presentation_timestamp_us: 750_000,
  width: 100,
  height: 100,
  decoder_version: "fixture-decoder/v1",
  transform_version: "fixture-frame/v1",
  output_encoding: "jpeg",
  content_type: "image/jpeg",
  image_sha256: "b".repeat(64),
  policy: "exact-event/v1",
};
const GEOMETRY = {
  kind: "detector-box/v1",
  box_2d: { x_min: 100, y_min: 100, x_max: 800, y_max: 800 },
};
const CROP = {
  schema_version: "visible-region-crop/v1",
  status: "usable",
  frame_identity: FRAME,
  geometry: GEOMETRY,
  pixel_bounds: { x_min: 10, y_min: 10, x_max: 80, y_max: 80 },
  crop_policy: "raw_rectangular",
  output_encoding: "ppm",
  content_type: "image/x-portable-pixmap",
  decoder_version: "fixture-decoder/v1",
  transform_version: "fixture-transform/v1",
  image_sha256: "c".repeat(64),
  unusable_reason: null,
};

function outcome(
  candidates = [{ identity: "CLUBS_NINE", score: 0.8 }],
  cardId = CARD_ID,
  requestedTimeUs = FRAME.requested_time_us,
) {
  const frame = {
    ...FRAME,
    requested_time_us: requestedTimeUs,
    presentation_timestamp_us: requestedTimeUs,
  };
  return {
    card_id: cardId,
    frame_identity: frame,
    geometry: GEOMETRY,
    crop_identity: { ...CROP, frame_identity: frame },
    classifier: {
      provider: "fixture.identity",
      implementation: { name: "fixture", version: "v1" },
      model: { name: "fixture-model", version: "v1" },
    },
    status: "classified",
    candidates,
    unusable_reason: null,
    error: null,
  };
}

function generatedResult(
  candidates = [{ identity: "CLUBS_NINE", score: 0.8 }],
  outcomes = [outcome(candidates)],
) {
  return {
    run_id: RUN_ID,
    recording_id: RECORDING_ID,
    processor_type: "visual-card-identity",
    status: "complete",
    attempt: 1,
    request: {},
    state: {},
    revisions: [
      {
        manifest: { revision_id: REVISION_ID },
        content: { outcomes },
      },
    ],
  };
}

function reference(
  reviewState: "pending" | "accepted" | "identity_unusable" = "pending",
) {
  const itemOutcome =
    reviewState === "identity_unusable"
      ? {
          ...outcome(),
          status: "unusable" as const,
          candidates: [],
          unusable_reason: "Reviewed identity unusable.",
        }
      : outcome();
  return {
    recording_id: RECORDING_ID,
    content_type: "visual_identities",
    state: {
      recording_id: RECORDING_ID,
      content_type: "visual_identities",
      draft_revision: reviewState === "pending" ? 0 : 1,
      draft_state: "draft",
      source_revision_id: REVISION_ID,
      selected_completed_revision_id: null,
      updated_at: "2026-09-06T00:00:00Z",
    },
    draft: {
      recording_id: RECORDING_ID,
      content_type: "visual_identities",
      revision: reviewState === "pending" ? 0 : 1,
      source_revision_id: REVISION_ID,
      items: [
        {
          item_id: CARD_ID,
          base_item_id: null,
          review_state: reviewState,
          item: itemOutcome,
        },
      ],
      coverage: null,
      impact: [],
      updated_at: "2026-09-06T00:00:00Z",
    },
  };
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PipelineVisualIdentityEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("keeps generated identity output immutable and exposes derived source context", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(generatedResult([]))),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    expect(
      await screen.findByRole("heading", {
        name: "Visual identity suggestions",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: `Resolved source frame for ${CARD_ID}` }),
    ).toHaveAttribute(
      "src",
      expect.stringContaining("derived-views/exact-event/750000"),
    );
    expect(screen.getByText(/immutable/)).toBeInTheDocument();
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
  });

  it("navigates between cards and updates the selected frame", async () => {
    const popstate = vi.fn();
    window.addEventListener("popstate", popstate);
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          jsonResponse(
            generatedResult(undefined, [
              outcome(),
              outcome(undefined, "card-2", 1_000_000),
            ]),
          ),
        ),
      ),
    );

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="generated"
      />,
    );

    const overlay = await screen.findByLabelText("Visible card geometry");
    const polygons = overlay.querySelectorAll("polygon");
    expect(polygons).toHaveLength(2);
    expect(polygons[0]).toHaveAttribute("data-card-id", CARD_ID);
    expect(polygons[0]).toHaveAttribute("data-current", "true");
    expect(polygons[1]).toHaveAttribute("data-card-id", "card-2");
    expect(polygons[1]).toHaveAttribute("data-current", "false");

    await waitFor(() =>
      expect(window.location.search).toContain(`item=${CARD_ID}`),
    );
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() =>
      expect(window.location.search).toContain("t_us=1000000"),
    );
    expect(popstate).toHaveBeenCalled();
    expect(
      screen
        .getByLabelText("Visible card geometry")
        .querySelector('[data-card-id="card-2"]'),
    ).toHaveAttribute("data-current", "true");
    window.removeEventListener("popstate", popstate);
  });

  it("keeps generated identities visible while a new review has no reference", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) =>
        Promise.resolve(
          String(input).endsWith("/pipeline/references/visual_identities")
            ? jsonResponse({ message: "not found" }, 404)
            : jsonResponse(generatedResult()),
        ),
      ),
    );

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        displayedRevisionId={null}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    expect(
      await screen.findByRole("heading", {
        name: "Start visual identity review",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("img", {
        name: `Resolved source frame for ${CARD_ID}`,
      }),
    ).toBeInTheDocument();
  });

  it("reports generated rail items and honors explicit item selection", async () => {
    const railItems = vi.fn();
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        jsonResponse(
          generatedResult(undefined, [
            outcome(),
            outcome(
              [{ identity: "HEARTS_QUEEN", score: 0.7 }],
              "card-2",
              1_000_000,
            ),
          ]),
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={2_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        selectionItemId="card-2"
        view="generated"
        onRailItemsChange={railItems}
      />,
    );

    expect(
      await screen.findByRole("img", {
        name: "Resolved source frame for card-2",
      }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(railItems).toHaveBeenLastCalledWith([
        {
          itemId: CARD_ID,
          label: "Card 1",
          state: "unreviewed",
          timeUs: 750_000,
          cropPolicy: "raw_rectangular",
        },
        {
          itemId: "card-2",
          label: "Card 2",
          state: "unreviewed",
          timeUs: 1_000_000,
          cropPolicy: "raw_rectangular",
        },
      ]),
    );
  });

  it("uses a localized identity label while saving the canonical command", async () => {
    const responses = [reference(), reference("accepted")];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(init?.method === "PUT" ? responses[1] : responses[0]),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: /Visual identity review/ });
    const choices = screen.getByLabelText("Canonical identities");
    expect(choices.querySelectorAll("button")).toHaveLength(20);
    expect(screen.queryByRole("button", { name: /9/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "♥ Dame" })).toHaveAttribute(
      "data-suit",
      "hearts",
    );
    expect(screen.getByRole("button", { name: "♦ Dame" })).toHaveAttribute(
      "data-suit",
      "diamonds",
    );
    expect(screen.getByRole("button", { name: "♥ 10" })).toHaveTextContent(
      "♥ 10",
    );
    expect(
      screen.getByRole("button", { name: "♥ Dame" }).querySelector("span"),
    ).toHaveAttribute("data-suit", "hearts");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Operator ID"), "operator-01");
    await user.click(screen.getByRole("button", { name: "♥ Dame" }));

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
      operation: "select_identity",
      item_id: CARD_ID,
      identity: "HEARTS_QUEEN",
    });
    expect(screen.queryByText("Geometry editor")).not.toBeInTheDocument();
    expect(screen.queryByText("80.0%")).not.toBeInTheDocument();
  });

  it("keeps review actions in the inspector and toggles all review states", async () => {
    const responses = [
      reference("accepted"),
      reference(),
      reference("identity_unusable"),
      reference(),
    ];
    let putIndex = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) =>
      Promise.resolve(
        jsonResponse(
          init?.method === "PUT" ? responses[putIndex++] : reference(),
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: /Visual identity review/ });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Operator ID"), "operator-01");

    expect(screen.getByText("Unreviewed")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Accept suggestion/ }),
    ).toBeInTheDocument();
    expect(
      screen
        .queryByRole("button", { name: /Accept suggestion/ })
        ?.closest("section[aria-label='Selected visual identity']"),
    ).toBeNull();

    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() => expect(putIndex).toBe(1));
    expect(screen.getByText("Accepted")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() => expect(putIndex).toBe(2));
    expect(screen.getByText("Unreviewed")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "u" });
    await waitFor(() => expect(putIndex).toBe(3));
    expect(screen.getByText("Unusable")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "u" });
    await waitFor(() => expect(putIndex).toBe(4));
    expect(screen.getByText("Unreviewed")).toBeInTheDocument();

    const operations = fetchImplementation.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(
        ([, init]) => JSON.parse(String(init?.body)).operations[0].operation,
      );
    expect(operations).toEqual([
      "accept_identity_suggestion",
      "set_identity_unreviewed",
      "set_identity_unusable",
      "set_identity_unreviewed",
    ]);
  });

  it("retries a transient identity draft save", async () => {
    let putAttempts = 0;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putAttempts += 1;
        return Promise.resolve(
          putAttempts === 1
            ? jsonResponse({ message: "temporary identity failure" }, 503)
            : jsonResponse(reference("accepted")),
        );
      }
      return Promise.resolve(jsonResponse(reference()));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: /Visual identity review/ });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Operator ID"), "operator-01");
    await user.click(screen.getByRole("button", { name: "♥ Dame" }));

    await waitFor(() => expect(putAttempts).toBe(2));
    expect(screen.getByText("Identity selected: ♥ Dame.")).toBeInTheDocument();
  });

  it("keeps completion blocked until the empty prediction is reviewed", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(reference())),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: /Visual identity review/ });
    expect(screen.getByText(/still need a decision/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Complete reference" }),
    ).toBeDisabled();
  });
});
