import { expect, test, type Page, type Route } from "@playwright/test";
import { Buffer } from "node:buffer";

const RECORDING_ID = "recording-browser-fixture";
const RETIRED_ROUTE_MARKERS = [
  "card-event-review",
  "card-event-reviews",
  "visible-card-review",
  "visible-card-reviews",
  "identity-review",
  "identity-reviews",
];

type Scenario = "fresh" | "generated" | "failed" | "affected" | "reviewed";
type ReviewFixtureState =
  "pending" | "accepted" | "dismissed" | "manual" | "no-selection";
type FrameFixtureState = "ready" | "loading" | "failed";

const REVIEW_RECORDING_ID = "recording-card-event-browser-fixture";
const FRAME_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

function stage(key: string, overrides: Record<string, unknown> = {}) {
  const reviewable = key !== "round_analyses";
  return {
    key,
    processor_key: `${key}-processor`,
    processor_type: key,
    output_content_type: key,
    has_maintained_reference: reviewable,
    state: key === "events" ? "video-only" : "empty",
    input_options: [],
    compatible_input_sets: [],
    selection_revision: reviewable ? 0 : null,
    selected_generated_revision_id: null,
    selected_completed_reference_revision_id: null,
    runs: [],
    analyses: [],
    reference: reviewable
      ? {
          state: "empty",
          draft_revision: null,
          selected_completion: null,
          source_revision_id: null,
          coverage: null,
          coverage_state: "none",
          affected_count: 0,
          updated_at: null,
        }
      : null,
    can_run: key === "events",
    run_blockers: key === "events" ? [] : ["Waiting for the event revision."],
    can_review: false,
    review_blockers: [],
    comparable_run_ids: [],
    ...overrides,
  };
}

function workspace(scenario: Scenario) {
  const generatedRevision = {
    revision_id: "events-revision-2",
    content_type: "events",
    origin: "processor",
    completion_state: "complete",
    coverage_state: "full-recording",
    display_label: "Generated events 2",
    content_sha256: "b".repeat(64),
    input_revision_ids: [],
    producer: {},
    coverage: {},
    created_at: "2026-09-06T00:00:00Z",
  };
  const events =
    scenario === "generated"
      ? stage("events", {
          state: "generated-only",
          input_options: [generatedRevision],
          selection_revision: 4,
          selected_generated_revision_id: generatedRevision.revision_id,
          can_run: true,
          can_review: true,
          runs: [
            {
              run_id: "events-run-2",
              status: "complete",
              attempt: 1,
              request: {},
              state: {},
              input_revision_ids: [],
              implementation: { name: "fixture", version: "v1" },
              model: null,
              configuration: {},
              extraction_policy: {},
              crop_policy: null,
              output_revision_ids: [generatedRevision.revision_id],
              created_at: "2026-09-06T00:00:00Z",
              started_at: "2026-09-06T00:00:00Z",
              completed_at: "2026-09-06T00:00:01Z",
              updated_at: "2026-09-06T00:00:01Z",
              progress: { completed: 1, total: 1 },
              failure: null,
              failed_item_count: 0,
            },
          ],
        })
      : scenario === "failed"
        ? stage("events", {
            state: "failed",
            runs: [
              {
                run_id: "events-failed-1",
                status: "failed",
                attempt: 1,
                request: {},
                state: {},
                input_revision_ids: [],
                implementation: { name: "fixture", version: "v1" },
                model: null,
                configuration: {},
                extraction_policy: {},
                crop_policy: null,
                output_revision_ids: [],
                created_at: "2026-09-06T00:00:00Z",
                started_at: "2026-09-06T00:00:00Z",
                completed_at: "2026-09-06T00:00:01Z",
                updated_at: "2026-09-06T00:00:01Z",
                progress: { completed: 0, total: 1 },
                failure: { code: "fixture_failed", message: "Fixture failed." },
                failed_item_count: 0,
              },
            ],
          })
        : stage("events");
  const visible =
    scenario === "affected"
      ? stage("visible_cards", {
          state: "affected",
          selected_generated_revision_id: "visible-revision-1",
          can_run: false,
          reference: {
            state: "draft",
            draft_revision: 2,
            selected_completion: null,
            source_revision_id: "visible-revision-1",
            coverage: null,
            coverage_state: "none",
            affected_count: 1,
            updated_at: "2026-09-06T00:00:00Z",
          },
        })
      : stage("visible_cards");
  return {
    schema_version: "pipeline-workspace/v1",
    recording_id: RECORDING_ID,
    video: {
      schema_version: "recording-video/v1",
      recording_id: RECORDING_ID,
      relative_path: "recordings/recording-browser-fixture/video.mov",
      video_sha256: "a".repeat(64),
      byte_length: 12,
      duration_us: 10_000_000,
    },
    stages: [
      events,
      visible,
      stage("visual_identities"),
      stage("table_observations"),
      stage("round_analyses"),
    ],
    diagnostics: [],
  };
}

function reviewEventItem(
  state: ReviewFixtureState,
  index: number,
): Record<string, unknown> {
  const itemId = `event-${index}`;
  return {
    item_id: itemId,
    base_item_id: state === "manual" ? null : `generated-event-${index}`,
    review_state:
      state === "dismissed" ? "rejected" : state === "manual" ? "added" : state,
    item: {
      event_id: `generated-event-${index}`,
      event_type: "card_state_changed",
      start_us: index * 1_000_000,
      end_us: index * 1_000_000 + 200_000,
      model_scores: [],
    },
  };
}

function reviewReference(items: Array<Record<string, unknown>>, revision = 1) {
  return {
    recording_id: REVIEW_RECORDING_ID,
    content_type: "events",
    state: {
      recording_id: REVIEW_RECORDING_ID,
      content_type: "events",
      draft_revision: revision,
      draft_state: "draft",
      source_revision_id: "events-revision-2",
      selected_completed_revision_id: null,
      updated_at: "2026-09-06T00:00:00Z",
    },
    draft: {
      recording_id: REVIEW_RECORDING_ID,
      content_type: "events",
      revision,
      source_revision_id: "events-revision-2",
      items,
      coverage: null,
      impact: [],
      updated_at: "2026-09-06T00:00:00Z",
    },
  };
}

function reviewWorkspace(
  state: ReviewFixtureState,
  eventCount = state === "no-selection" ? 0 : 2,
) {
  const body = workspace("fresh");
  const items = Array.from({ length: eventCount }, (_, index) =>
    reviewEventItem(state, index + 1),
  );
  const generatedRevision = {
    revision_id: "events-revision-2",
    content_type: "events",
    origin: "processor",
    completion_state: "complete",
    coverage_state: "full-recording",
    display_label: "Generated events 2",
    content_sha256: "b".repeat(64),
    input_revision_ids: [],
    producer: {},
    coverage: {},
    created_at: "2026-09-06T00:00:00Z",
  };
  body.recording_id = REVIEW_RECORDING_ID;
  body.video.recording_id = REVIEW_RECORDING_ID;
  body.video.relative_path = `recordings/${REVIEW_RECORDING_ID}/video.mov`;
  body.stages = body.stages.map((candidate) =>
    candidate.key === "events"
      ? stage("events", {
          state: "draft",
          input_options: [generatedRevision],
          selection_revision: 1,
          selected_generated_revision_id: generatedRevision.revision_id,
          can_run: false,
          can_review: false,
          reference: {
            state: "draft",
            draft_revision: 1,
            selected_completion: null,
            source_revision_id: generatedRevision.revision_id,
            coverage: null,
            coverage_state: "none",
            affected_count: 0,
            updated_at: "2026-09-06T00:00:00Z",
          },
          runs: [
            {
              run_id: "events-run-2",
              status: "complete",
              attempt: 1,
              request: {},
              state: {
                items: items.map((item) => ({
                  item_id: item.item_id,
                  status: "succeeded",
                  result: item.item,
                  failure: null,
                })),
              },
              input_revision_ids: [],
              implementation: { name: "fixture", version: "v1" },
              model: null,
              configuration: {},
              extraction_policy: {},
              crop_policy: null,
              output_revision_ids: [generatedRevision.revision_id],
              created_at: "2026-09-06T00:00:00Z",
              started_at: "2026-09-06T00:00:00Z",
              completed_at: "2026-09-06T00:00:01Z",
              updated_at: "2026-09-06T00:00:01Z",
              progress: { completed: 2, total: 2 },
              failure: null,
              failed_item_count: 0,
            },
          ],
        })
      : candidate,
  );
  return body;
}

function json(value: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  };
}

async function stubPipeline(
  page: Page,
  scenario: Scenario,
  reviewOptions: {
    state?: ReviewFixtureState;
    frame?: FrameFixtureState;
    eventCount?: number;
  } = {},
) {
  const requestedPaths: string[] = [];
  let currentScenario = scenario;
  let workspaceRequests = 0;
  let conflictOnSelection = true;
  const reviewState = reviewOptions.state ?? "pending";
  const frameState = reviewOptions.frame ?? "ready";
  let reviewItems = Array.from(
    {
      length:
        reviewOptions.eventCount ?? (reviewState === "no-selection" ? 0 : 2),
    },
    (_, index) => reviewEventItem(reviewState, index + 1),
  );
  let reviewRevision = 1;
  await page.route("**/api/**", async (route: Route) => {
    const url = new URL(route.request().url());
    requestedPaths.push(url.pathname);
    if (RETIRED_ROUTE_MARKERS.some((marker) => url.pathname.includes(marker))) {
      await route.fulfill(json({ error: "retired route" }, 404));
      return;
    }
    if (url.pathname === `/api/recordings/${RECORDING_ID}/pipeline`) {
      workspaceRequests += 1;
      await route.fulfill(json(workspace(currentScenario)));
      return;
    }
    if (
      currentScenario === "reviewed" &&
      url.pathname === `/api/recordings/${REVIEW_RECORDING_ID}/pipeline`
    ) {
      workspaceRequests += 1;
      await route.fulfill(
        json(
          reviewWorkspace(
            reviewState,
            reviewOptions.eventCount ??
              (reviewState === "no-selection" ? 0 : 2),
          ),
        ),
      );
      return;
    }
    if (
      currentScenario === "reviewed" &&
      url.pathname ===
        `/api/recordings/${REVIEW_RECORDING_ID}/pipeline/references/events`
    ) {
      await route.fulfill(json(reviewReference(reviewItems, reviewRevision)));
      return;
    }
    if (
      currentScenario === "reviewed" &&
      url.pathname.endsWith("/pipeline/references/events/draft") &&
      route.request().method() === "PUT"
    ) {
      const payload = JSON.parse(route.request().postData() ?? "{}") as {
        operations?: Array<Record<string, unknown>>;
      };
      const operation = payload.operations?.[0];
      if (operation?.operation === "add" && isRecord(operation.item)) {
        reviewItems = [
          ...reviewItems,
          {
            item_id: String(operation.item.event_id),
            base_item_id: null,
            review_state: "added",
            item: operation.item,
          },
        ];
      } else if (typeof operation?.item_id === "string") {
        reviewItems = reviewItems.map((item) =>
          item.item_id !== operation.item_id
            ? item
            : {
                ...item,
                review_state:
                  operation.operation === "accept"
                    ? "accepted"
                    : operation.operation === "correct"
                      ? "corrected"
                      : "rejected",
                item: isRecord(operation.item) ? operation.item : item.item,
              },
        );
      }
      reviewRevision += 1;
      await route.fulfill(json(reviewReference(reviewItems, reviewRevision)));
      return;
    }
    if (
      currentScenario === "reviewed" &&
      url.pathname.includes("/pipeline/derived-views/exact-event/")
    ) {
      if (frameState === "loading") {
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      if (frameState === "failed") {
        await route.fulfill(
          json({ detail: "Fixture frame unavailable." }, 503),
        );
      } else {
        await route.fulfill({
          status: 200,
          contentType: "image/png",
          body: FRAME_BYTES,
        });
      }
      return;
    }
    if (
      url.pathname.endsWith("/events/selection") &&
      route.request().method() === "PUT"
    ) {
      if (conflictOnSelection) {
        conflictOnSelection = false;
        await route.fulfill(json({ error: "selection changed" }, 409));
        return;
      }
      currentScenario = "generated";
      await route.fulfill(
        json({
          selection: {
            revision: 5,
            selected_generated_revision_id: "events-revision-2",
            selected_completed_reference_revision_id: null,
          },
        }),
      );
      return;
    }
    if (url.pathname.endsWith("/events/events-run-2/result")) {
      await route.fulfill(
        json({
          run_id: "events-run-2",
          recording_id: RECORDING_ID,
          processor_type: "cardevent",
          status: "complete",
          attempt: 1,
          request: {},
          state: {},
          revisions: [
            {
              manifest: { revision_id: "events-revision-2" },
              content: { events: [] },
            },
          ],
        }),
      );
      return;
    }
    if (url.pathname.endsWith("/events/events-failed-1")) {
      await route.fulfill(
        json({
          run_id: "events-failed-1",
          status: "failed",
          failure: { code: "fixture_failed", message: "Fixture failed." },
        }),
      );
      return;
    }
    await route.fulfill(json({ error: "unmocked fixture route" }, 404));
  });
  await page.route("**/v1/recordings", async (route) => {
    await route.fulfill(json({ recordings: [] }));
  });
  return {
    requestedPaths,
    workspaceRequestCount: () => workspaceRequests,
    setScenario: (next: Scenario) => {
      currentScenario = next;
    },
  };
}

test("opens fresh accepted video in the recording-owned pipeline", async ({
  page,
}) => {
  const requests = await stubPipeline(page, "fresh");
  await page.goto(`/recordings/${RECORDING_ID}`);

  await expect(page.getByRole("banner")).toBeVisible();
  await expect(page.getByText(RECORDING_ID).first()).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Events task surface" }),
  ).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: "Workspace inspector" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Timeline Rail" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run processor" }),
  ).toBeVisible();
  await expect(page).toHaveURL(
    new RegExp(`/recordings/${RECORDING_ID}/pipeline/events$`),
  );
  expect(
    requests.requestedPaths.some((path) =>
      RETIRED_ROUTE_MARKERS.some((marker) => path.includes(marker)),
    ),
  ).toBe(false);
  expect(requests.workspaceRequestCount()).toBeGreaterThan(0);
});

test("keeps the workspace shell within desktop bounds and preserves task order on mobile", async ({
  page,
}) => {
  await stubPipeline(page, "fresh");
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`/recordings/${RECORDING_ID}/pipeline/events`);
    await expect(
      page.getByRole("region", { name: "Events task surface" }),
    ).toBeVisible();

    const desktopLayout = await page.evaluate(() => {
      const rect = (slot: string) =>
        document
          .querySelector(`[data-slot="${slot}"]`)
          ?.getBoundingClientRect() ?? null;
      return {
        documentHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
        topBarHeight:
          document.querySelector("header")?.getBoundingClientRect().height ?? 0,
        centerWidth: rect("center")?.width ?? 0,
        inspectorWidth: rect("inspector")?.width ?? 0,
        railHeight: rect("bottom")?.height ?? 0,
      };
    });
    expect(desktopLayout.documentHeight).toBeLessThanOrEqual(
      desktopLayout.viewportHeight,
    );
    expect(desktopLayout.topBarHeight).toBeLessThanOrEqual(112);
    expect(desktopLayout.inspectorWidth).toBeGreaterThanOrEqual(288);
    expect(desktopLayout.inspectorWidth).toBeLessThanOrEqual(368);
    expect(desktopLayout.centerWidth).toBeGreaterThan(
      desktopLayout.inspectorWidth,
    );
    expect(desktopLayout.railHeight).toBeGreaterThanOrEqual(96);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileLayout = await page.evaluate(() => {
    const rect = (slot: string) =>
      document
        .querySelector(`[data-slot="${slot}"]`)
        ?.getBoundingClientRect() ?? null;
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      centerTop: rect("center")?.top ?? 0,
      inspectorTop: rect("inspector")?.top ?? 0,
      railTop: rect("bottom")?.top ?? 0,
    };
  });
  expect(mobileLayout.documentWidth).toBeLessThanOrEqual(
    mobileLayout.viewportWidth,
  );
  expect(mobileLayout.centerTop).toBeLessThan(mobileLayout.inspectorTop);
  expect(mobileLayout.inspectorTop).toBeLessThan(mobileLayout.railTop);
});

test("covers generated suggestions, reruns, failed jobs, upstream correction, cold reloads, and save conflicts", async ({
  page,
}) => {
  const requests = await stubPipeline(page, "generated");
  await page.goto(`/recordings/${RECORDING_ID}/pipeline/events?view=generated`);
  await expect(page.getByRole("banner")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Generated result/)).toBeVisible();

  await page.goto(`/recordings/${RECORDING_ID}/pipeline/events?view=generated`);
  await page
    .getByRole("combobox", { name: "Default generated revision" })
    .selectOption("");
  await expect(
    page.getByText(
      "The generated selection changed elsewhere. The winning selection is shown.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Run again" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("banner")).toBeVisible();

  requests.setScenario("failed");
  await page.goto(`/recordings/${RECORDING_ID}/pipeline/events`);
  await page.getByText("Lineage, diagnostics, and history").click();
  await expect(
    page
      .getByRole("list", { name: "Processor history" })
      .getByText("events-failed-1"),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Events Failed" })).toBeVisible();

  requests.setScenario("affected");
  await page.goto(
    `/recordings/${RECORDING_ID}/pipeline/visible_cards?view=reviewed`,
  );
  await expect(
    page
      .getByRole("complementary", { name: "Workspace inspector" })
      .getByRole("heading", { name: "Start visible-card review" }),
  ).toBeVisible();

  await page.goto(`/recordings/${RECORDING_ID}/pipeline/events`);
  await expect(page.getByText("Run processor")).toBeVisible();
  expect(
    requests.requestedPaths.every(
      (path) => !path.includes("evidence-packages"),
    ),
  ).toBe(true);
  expect(
    requests.requestedPaths.some((path) =>
      RETIRED_ROUTE_MARKERS.some((marker) => path.includes(marker)),
    ),
  ).toBe(false);
});

test("does not route retired batch URLs into a review workspace", async ({
  page,
}) => {
  const requests = await stubPipeline(page, "fresh");
  await page.goto("/visible-card-reviews/retired-batch");

  await expect(
    page.getByRole("heading", { name: "Recordings", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/review workspace/i)).not.toBeVisible();
  expect(
    requests.requestedPaths.some((path) =>
      RETIRED_ROUTE_MARKERS.some((marker) => path.includes(marker)),
    ),
  ).toBe(false);
});

for (const fixture of [
  { state: "pending" as const, railState: "pending" },
  { state: "accepted" as const, railState: "accepted" },
  { state: "dismissed" as const, railState: "rejected" },
  { state: "manual" as const, railState: "added" },
  { state: "no-selection" as const, railState: null },
]) {
  test(`renders the reviewed ${fixture.state} CardEvent fixture`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await stubPipeline(page, "reviewed", { state: fixture.state });
    const selection =
      fixture.state === "no-selection"
        ? "view=reviewed"
        : "view=reviewed&item=event-1&t_us=1000000";
    await page.goto(
      `/recordings/${REVIEW_RECORDING_ID}/pipeline/events?${selection}`,
    );

    const taskSurface = page.getByRole("region", {
      name: "Events task surface",
    });
    const controls = page.getByRole("complementary", {
      name: "CardEvent review controls",
    });
    const frame = page.getByRole("region", {
      name: "CardEvent exact source frame",
    });
    await expect(taskSurface).toBeVisible();
    await expect(controls).toBeVisible();
    await expect(frame).toBeVisible();
    await expect(frame.getByRole("img")).toHaveAttribute(
      "alt",
      fixture.state === "no-selection"
        ? "Exact CardEvent source frame at 0:00.000000"
        : "Exact CardEvent source frame at 0:01.000000",
    );
    await expect(frame.getByRole("status")).toContainText(
      fixture.state === "no-selection"
        ? "Exact source frame loaded at 0:00.000000."
        : "Exact source frame loaded at 0:01.000000.",
    );
    expect(await taskSurface.locator("video").count()).toBe(0);

    const expectedItemState = fixture.railState;
    if (expectedItemState === null) {
      await expect(
        page.getByText("Select an event from the Timeline Rail."),
      ).toBeVisible();
      await expect(
        controls.getByRole("button", { name: "Previous Alt+Left" }),
      ).toBeDisabled();
      await expect(
        controls.getByRole("button", { name: "Accept A" }),
      ).toBeDisabled();
    } else {
      await expect(
        page.getByRole("button", {
          name: new RegExp(
            `Card-state change, 0:01–0:01, ${expectedItemState}$`,
          ),
        }),
      ).toBeVisible();
      if (fixture.state === "dismissed") {
        await expect(
          controls.getByRole("button", { name: "Undo dismiss D" }),
        ).toBeEnabled();
      }
    }
  });
}

test("keeps the reviewed CardEvent workbench accessible at desktop and narrow sizes", async ({
  page,
}) => {
  await stubPipeline(page, "reviewed", { state: "pending" });
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(
      `/recordings/${REVIEW_RECORDING_ID}/pipeline/events?view=reviewed&item=event-1&t_us=1000000`,
    );

    const frame = page.getByRole("region", {
      name: "CardEvent exact source frame",
    });
    const controls = page.getByRole("complementary", {
      name: "CardEvent review controls",
    });
    await expect(frame.getByRole("img")).toBeVisible();
    await expect(controls).toBeVisible();
    await expect(
      page.getByRole("complementary", { name: "Workspace inspector" }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Timeline Rail" }),
    ).toBeVisible();

    const layout = await page.evaluate(() => {
      const rect = (selector: string) =>
        document.querySelector(selector)?.getBoundingClientRect() ?? null;
      const frameRect = rect('[aria-label="CardEvent exact source frame"]');
      const controlsRect = rect('[aria-label="CardEvent review controls"]');
      const centerRect = rect('[data-slot="center"]');
      const inspectorRect = rect('[data-slot="inspector"]');
      const railRect = rect('[data-slot="bottom"]');
      return {
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        frame: frameRect
          ? { top: frameRect.top, left: frameRect.left, width: frameRect.width }
          : null,
        controls: controlsRect
          ? {
              top: controlsRect.top,
              right: controlsRect.right,
              width: controlsRect.width,
            }
          : null,
        centerTop: centerRect?.top ?? null,
        inspectorTop: inspectorRect?.top ?? null,
        railTop: railRect?.top ?? null,
      };
    });
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.frame).not.toBeNull();
    expect(layout.controls).not.toBeNull();
    if (layout.frame === null || layout.controls === null) {
      throw new Error("review workbench geometry is unavailable");
    }
    if (viewport.width >= 1024) {
      expect(layout.controls.right).toBeLessThanOrEqual(layout.frame.left);
      expect(layout.frame.width).toBeGreaterThan(layout.controls.width);
    } else {
      expect(layout.frame.top).toBeLessThan(layout.controls.top);
      expect(layout.controls.right).toBeLessThanOrEqual(layout.viewportWidth);
      expect(layout.centerTop).toBeLessThan(layout.inspectorTop);
      expect(layout.inspectorTop).toBeLessThan(layout.railTop);
    }

    const inspector = page.getByRole("complementary", {
      name: "Workspace inspector",
    });
    await expect(
      inspector.getByRole("heading", { name: "Complete event review" }),
    ).toBeVisible();
    await expect(
      inspector.getByRole("heading", { name: "Saved" }),
    ).toBeVisible();
    await expect(
      inspector.getByRole("heading", { name: "Reviewed" }),
    ).toBeVisible();
    await expect(
      inspector.getByRole("heading", { name: "Accepted video" }),
    ).toBeVisible();
  }
});

test("keeps shortcut pills, focus order, frame announcements, and review commands in the browser", async ({
  page,
}) => {
  const requests = await stubPipeline(page, "reviewed", {
    state: "pending",
    eventCount: 2,
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(
    `/recordings/${REVIEW_RECORDING_ID}/pipeline/events?view=reviewed&item=event-1&t_us=1000000`,
  );
  const controls = page.getByRole("complementary", {
    name: "CardEvent review controls",
  });
  await expect(controls).toBeVisible();
  const focusOrder = [
    ["Next Alt+Right", "Alt+Right"],
    ["Seek earlier Left", "Left"],
    ["Seek later Right", "Right"],
    ["Nudge earlier ,", ","],
    ["Nudge later .", "."],
    ["Accept A", "A"],
    ["Dismiss D", "D"],
    ["Add event N", "N"],
  ];
  for (let index = 0; index < focusOrder.length; index += 1) {
    const [name, shortcut] = focusOrder[index];
    const button = controls.getByRole("button", { name });
    await expect(button.locator("kbd")).toHaveText(shortcut);
    if (index === 0) await button.focus();
    await expect(page.locator(":focus")).toHaveAccessibleName(name);
    if (index < focusOrder.length - 1) await page.keyboard.press("Tab");
  }

  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/t_us=1250000/);
  await page.keyboard.press("Alt+ArrowRight");
  await expect(page).toHaveURL(/item=event-2&t_us=2000000/);
  await page.keyboard.press(".");
  await expect(page).toHaveURL(/t_us=2033333/);
  await page.keyboard.press("Alt+ArrowLeft");
  await expect(page).toHaveURL(/item=event-1&t_us=1000000/);
  await page.keyboard.press("a");
  await expect
    .poll(
      () =>
        requests.requestedPaths.filter((path) => path.endsWith("/draft"))
          .length,
    )
    .toBe(2);
  await page.keyboard.press("d");
  await expect
    .poll(
      () =>
        requests.requestedPaths.filter((path) => path.endsWith("/draft"))
          .length,
    )
    .toBe(3);
  await page.keyboard.press("n");
  await expect
    .poll(
      () =>
        requests.requestedPaths.filter((path) => path.endsWith("/draft"))
          .length,
    )
    .toBe(4);
  expect(requests.requestedPaths).not.toContain(
    `/api/recordings/${REVIEW_RECORDING_ID}/pipeline/references/events/retired`,
  );
});

test("announces loading and failed exact source-frame fixtures", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await stubPipeline(page, "reviewed", {
    state: "no-selection",
    frame: "loading",
  });
  await page.goto(
    `/recordings/${REVIEW_RECORDING_ID}/pipeline/events?view=reviewed`,
  );
  const loadingFrame = page.getByRole("region", {
    name: "CardEvent exact source frame",
  });
  await expect(
    loadingFrame.getByText("Loading exact source frame at 0:00.000000…", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(loadingFrame.getByRole("img")).toBeVisible();

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await stubPipeline(page, "reviewed", {
    state: "no-selection",
    frame: "failed",
  });
  await page.reload();
  const failedFrame = page.getByRole("region", {
    name: "CardEvent exact source frame",
  });
  await expect(failedFrame.getByRole("alert")).toContainText(
    "Exact source frame unavailable (503).",
  );
  await expect(failedFrame.getByRole("status")).toContainText(
    "Exact source frame unavailable at 0:00.000000.",
  );
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
