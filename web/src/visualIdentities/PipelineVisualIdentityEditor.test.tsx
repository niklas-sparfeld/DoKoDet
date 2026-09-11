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
  cropIdentity: typeof CROP | null = CROP,
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
    crop_identity:
      cropIdentity === null ? null : { ...cropIdentity, frame_identity: frame },
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
  reviewState:
    | "pending"
    | "accepted"
    | "face_down"
    | "identity_unusable"
    | "source_problem" = "pending",
  additionalItems: Array<{
    cardId: string;
    reviewState?:
      | "pending"
      | "accepted"
      | "face_down"
      | "identity_unusable"
      | "source_problem";
    requestedTimeUs?: number;
  }> = [],
  revision = reviewState === "pending" ? 0 : 1,
  sourceRevisionId: string | null = REVISION_ID,
) {
  const itemSpecs = [{ cardId: CARD_ID, reviewState }, ...additionalItems];
  const items = itemSpecs.map((spec) => {
    const itemReviewState = spec.reviewState ?? reviewState;
    const itemOutcome =
      itemReviewState === "identity_unusable"
        ? {
            ...outcome([], spec.cardId, spec.requestedTimeUs),
            status: "unusable" as const,
            candidates: [],
            unusable_reason: "Reviewed identity unusable.",
          }
        : itemReviewState === "face_down"
          ? {
              ...outcome([], spec.cardId, spec.requestedTimeUs),
              status: "face_down" as const,
              candidates: [],
            }
          : itemReviewState === "source_problem"
            ? {
                ...outcome([], spec.cardId, spec.requestedTimeUs),
                status: "failed" as const,
                candidates: [],
                error: "Reviewed source problem.",
              }
            : outcome(undefined, spec.cardId, spec.requestedTimeUs);
    return {
      item_id: spec.cardId,
      base_item_id: null,
      review_state: itemReviewState,
      item: itemOutcome,
    };
  });
  return {
    recording_id: RECORDING_ID,
    content_type: "visual_identities",
    state: {
      recording_id: RECORDING_ID,
      content_type: "visual_identities",
      draft_revision: revision,
      draft_state: "draft",
      source_revision_id: sourceRevisionId,
      selected_completed_revision_id: null,
      updated_at: "2026-09-06T00:00:00Z",
    },
    draft: {
      recording_id: RECORDING_ID,
      content_type: "visual_identities",
      revision,
      source_revision_id: sourceRevisionId,
      items,
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

type PutBody = {
  expected_revision?: number;
  operations?: Array<{ operation?: string }>;
};

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
      await screen.findByRole("img", {
        name: `Resolved source frame for ${CARD_ID}`,
      }),
    ).toHaveAttribute(
      "src",
      expect.stringContaining("derived-views/exact-event/750000"),
    );
    const images = screen.getAllByRole("img");
    expect(images[0]).toHaveAccessibleName(
      `Derived identity crop for ${CARD_ID}`,
    );
    expect(images[1]).toHaveAccessibleName(
      `Resolved source frame for ${CARD_ID}`,
    );
    expect(screen.getByText(/immutable/)).toBeInTheDocument();
    expect(
      fetchImplementation.mock.calls.filter(([input]) =>
        String(input).includes(
          "/pipeline/visual-identities/identity-run-1/result",
        ),
      ),
    ).toHaveLength(1);
  });

  it("prewarms only the next eligible identity items", async () => {
    const fetchImplementation = vi.fn<typeof fetch>((input) =>
      String(input).includes("/pipeline/visual-identities/") &&
      String(input).includes("/result")
        ? Promise.resolve(
            jsonResponse(
              generatedResult(undefined, [
                outcome(),
                outcome(undefined, "card-2", 1_000_000),
              ]),
            ),
          )
        : Promise.resolve(new Response("warm")),
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
      />,
    );

    expect(
      await screen.findByRole("img", {
        name: "Resolved source frame for card-2",
      }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(([input]) =>
          String(input).includes("/derived-views/"),
        ),
      ).toHaveLength(2),
    );
    expect(
      fetchImplementation.mock.calls
        .filter(([input]) => String(input).includes("/derived-views/"))
        .map(([input]) => String(input)),
    ).toEqual([
      expect.stringContaining("exact-event/750000"),
      expect.stringContaining("identity-crops/identity-revision-1/card-1"),
    ]);
  });

  it("skips unusable, missing, and revisionless crops while warming frames", async () => {
    const missingCrop = {
      ...outcome(undefined, "missing-crop", 1_000_000),
      crop_identity: null,
    };
    const unusableCrop = {
      ...outcome(undefined, "unusable-crop", 1_250_000),
      crop_identity: { ...CROP, status: "unusable" as const },
    };
    const fetchImplementation = vi.fn<typeof fetch>((input) =>
      String(input).includes("/result")
        ? Promise.resolve(
            jsonResponse(
              generatedResult(undefined, [
                outcome(),
                missingCrop,
                unusableCrop,
              ]),
            ),
          )
        : Promise.resolve(new Response("warm")),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={2_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        selectionItemId="missing-crop"
        view="generated"
      />,
    );

    await screen.findByRole("img", {
      name: "Resolved source frame for missing-crop",
    });
    await waitFor(() =>
      expect(
        fetchImplementation.mock.calls.filter(([input]) =>
          String(input).includes("/derived-views/"),
        ),
      ).toHaveLength(3),
    );
    const derivedUrls = fetchImplementation.mock.calls
      .filter(([input]) => String(input).includes("/derived-views/"))
      .map(([input]) => String(input));
    expect(derivedUrls).toEqual([
      expect.stringContaining("exact-event/1250000"),
      expect.stringContaining("exact-event/750000"),
      expect.stringContaining("identity-crops/identity-revision-1/card-1"),
    ]);
    expect(derivedUrls.some((url) => url.includes("missing-crop"))).toBe(false);
    expect(derivedUrls.some((url) => url.includes("unusable-crop"))).toBe(
      false,
    );
  });

  it("skips crops when a maintained review has no source revision", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(reference("pending", [], 0, null))),
    );
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={2_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={null}
        view="reviewed"
      />,
    );

    await screen.findByRole("img", {
      name: "Resolved source frame for card-1",
    });
    expect(
      fetchImplementation.mock.calls.some(([input]) =>
        String(input).includes("identity-crops"),
      ),
    ).toBe(false);
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

  it("shows a placeholder while the selected crop preview loads", async () => {
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

    const firstCrop = await screen.findByRole("img", {
      name: `Derived identity crop for ${CARD_ID}`,
    });
    fireEvent.load(firstCrop);
    expect(firstCrop).toHaveAttribute("data-loaded", "true");
    await waitFor(() =>
      expect(window.location.search).toContain(`item=${CARD_ID}`),
    );

    fireEvent.keyDown(window, { key: "ArrowRight" });

    const nextCrop = await screen.findByRole("img", {
      name: "Derived identity crop for card-2",
    });
    expect(nextCrop).toHaveAttribute("data-loaded", "false");
    expect(screen.getByText("Loading crop preview…")).toBeInTheDocument();

    fireEvent.load(nextCrop);
    expect(nextCrop).toHaveAttribute("data-loaded", "true");
    expect(screen.queryByText("Loading crop preview…")).not.toBeInTheDocument();
  });

  it("colors identity polygons by review state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          jsonResponse(
            reference("pending", [
              { cardId: "accepted-card", reviewState: "accepted" },
              {
                cardId: "unusable-card",
                reviewState: "identity_unusable",
              },
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
        generatedRunId={null}
        view="reviewed"
      />,
    );

    const overlay = await screen.findByLabelText("Visible card geometry");
    expect(overlay.querySelector('[data-card-id="card-1"]')).toMatchObject({
      attributes: expect.objectContaining({
        fill: expect.objectContaining({ value: "rgba(196, 154, 239, 0.2)" }),
        stroke: expect.objectContaining({ value: "#ffd24f" }),
      }),
    });
    expect(
      overlay.querySelector('[data-card-id="accepted-card"]'),
    ).toMatchObject({
      attributes: expect.objectContaining({
        fill: expect.objectContaining({ value: "rgba(85, 213, 137, 0.2)" }),
        stroke: expect.objectContaining({ value: "#55d589" }),
      }),
    });
    expect(
      overlay.querySelector('[data-card-id="unusable-card"]'),
    ).toMatchObject({
      attributes: expect.objectContaining({
        fill: expect.objectContaining({ value: "rgba(255, 125, 114, 0.16)" }),
        stroke: expect.objectContaining({ value: "#ff7d72" }),
      }),
    });
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

  it("switches an existing review to the selected generated result", async () => {
    const nextRevisionId = "identity-revision-2";
    const rebased = reference("pending", [], 1, nextRevisionId);
    let putBody: Record<string, unknown> | null = null;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putBody = JSON.parse(String(init.body));
        return Promise.resolve(jsonResponse(rebased));
      }
      return Promise.resolve(jsonResponse(reference("pending", [], 1)));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={nextRevisionId}
        generatedRunId={null}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: /Visual identity review/ });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Operator ID"), "operator-01");
    await user.click(
      screen.getByRole("button", { name: "Switch review to selected result" }),
    );

    await waitFor(() => expect(putBody).not.toBeNull());
    expect(putBody).toMatchObject({
      expected_revision: 1,
      operator_id: "operator-01",
      operations: [{ operation: "rebase", source_revision_id: nextRevisionId }],
    });
    expect(
      await screen.findByRole("img", {
        name: `Derived identity crop for ${CARD_ID}`,
      }),
    ).toHaveAttribute("src", expect.stringContaining(nextRevisionId));
    expect(
      screen.getByText(/switched to the selected generated result/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Switch review to selected result",
      }),
    ).not.toBeInTheDocument();
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
      reference("face_down"),
      reference(),
      reference("source_problem"),
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
    expect(screen.getAllByText("Identity unusable").length).toBeGreaterThan(0);

    fireEvent.keyDown(window, { key: "u" });
    await waitFor(() => expect(putIndex).toBe(4));
    expect(screen.getByText("Unreviewed")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "f" });
    await waitFor(() => expect(putIndex).toBe(5));
    expect(screen.getAllByText("Face down").length).toBeGreaterThan(0);

    fireEvent.keyDown(window, { key: "f" });
    await waitFor(() => expect(putIndex).toBe(6));
    expect(screen.getByText("Unreviewed")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "s" });
    await waitFor(() => expect(putIndex).toBe(7));
    expect(screen.getAllByText("Source problem").length).toBeGreaterThan(0);

    fireEvent.keyDown(window, { key: "s" });
    await waitFor(() => expect(putIndex).toBe(8));
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
      "set_identity_face_down",
      "set_identity_unreviewed",
      "report_identity_source_problem",
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

  it("replays queued decisions on a delayed save response", async () => {
    let resolveFirst!: (value: Response) => void;
    let resolveSecond!: (value: Response) => void;
    const firstSave = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const secondSave = new Promise<Response>((resolve) => {
      resolveSecond = resolve;
    });
    let putCount = 0;
    const railStates: string[] = [];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "PUT") {
        putCount += 1;
        return putCount === 1 ? firstSave : secondSave;
      }
      return Promise.resolve(
        jsonResponse(
          reference("pending", [
            { cardId: "card-2", requestedTimeUs: 900_000 },
          ]),
        ),
      );
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={RUN_ID}
        view="reviewed"
        onRailItemsChange={(items) => {
          railStates.splice(
            0,
            railStates.length,
            ...items.map((item) => item.state),
          );
        }}
      />,
    );

    await screen.findByRole("heading", { name: /Visual identity review/ });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Operator ID"), "operator-01");
    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() => expect(putCount).toBe(1));

    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByText("card-2")).toBeInTheDocument());
    fireEvent.keyDown(window, { key: "a" });
    expect(putCount).toBe(1);

    resolveFirst(
      jsonResponse(
        reference("accepted", [{ cardId: "card-2", requestedTimeUs: 900_000 }]),
      ),
    );
    await waitFor(() => expect(putCount).toBe(2));
    await waitFor(() => expect(railStates).toEqual(["accepted", "accepted"]));

    resolveSecond(
      jsonResponse(
        reference(
          "accepted",
          [
            {
              cardId: "card-2",
              reviewState: "accepted",
              requestedTimeUs: 900_000,
            },
          ],
          2,
        ),
      ),
    );
    await waitFor(() => expect(railStates).toEqual(["accepted", "accepted"]));

    const putBodies = fetchImplementation.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(putBodies.map((body) => body.expected_revision)).toEqual([0, 1]);
    expect(putBodies.map((body) => body.operations[0].item_id)).toEqual([
      CARD_ID,
      "card-2",
    ]);
  });

  it("batches decisions queued while a save is in flight", async () => {
    let resolveFirst!: (value: Response) => void;
    const firstSave = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const putBodies: PutBody[] = [];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method !== "PUT")
        return Promise.resolve(
          jsonResponse(
            reference("pending", [
              { cardId: "card-2", reviewState: "pending" },
            ]),
          ),
        );
      const body = JSON.parse(String(init.body)) as PutBody;
      putBodies.push(body);
      if (putBodies.length === 1) return firstSave;
      return Promise.resolve(
        jsonResponse(
          reference(
            "accepted",
            [{ cardId: "card-2", reviewState: "pending" }],
            2,
          ),
        ),
      );
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
    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() => expect(putBodies).toHaveLength(1));
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByText("card-2")).toBeInTheDocument());
    fireEvent.keyDown(window, { key: "a" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Mark unreviewed/ }),
      ).toBeInTheDocument(),
    );
    fireEvent.keyDown(window, { key: "a" });

    resolveFirst(
      jsonResponse(
        reference(
          "accepted",
          [{ cardId: "card-2", reviewState: "pending" }],
          1,
        ),
      ),
    );
    await waitFor(() => expect(putBodies).toHaveLength(2));

    expect(putBodies[1]?.expected_revision).toBe(1);
    expect(
      putBodies[1]?.operations?.map((operation) => operation.operation),
    ).toEqual(["accept_identity_suggestion", "set_identity_unreviewed"]);
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

  it("uses the backend coverage kind when completing the reference", async () => {
    let completionPayload: Record<string, unknown> | null = null;
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      if (init?.method === "POST") {
        completionPayload = JSON.parse(String(init.body));
        return Promise.resolve(jsonResponse(reference("accepted", [], 2)));
      }
      return Promise.resolve(jsonResponse(reference("accepted")));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    render(
      <PipelineVisualIdentityEditor
        recordingId={RECORDING_ID}
        durationUs={1_000_000}
        generatedRevisionId={REVISION_ID}
        generatedRunId={null}
        view="reviewed"
      />,
    );

    await screen.findByRole("heading", { name: /Visual identity review/ });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Reviewer ID"), "reviewer-01");
    const completeButton = screen.getByRole("button", {
      name: "Complete reference",
    });
    await waitFor(() => expect(completeButton).not.toBeDisabled());
    await user.click(completeButton);

    await waitFor(() => expect(completionPayload).not.toBeNull());
    expect(completionPayload).toMatchObject({
      coverage: {
        kind: "visual_identities",
        cards: [{ card_id: CARD_ID, decision: "identity" }],
      },
    });
  });
});
