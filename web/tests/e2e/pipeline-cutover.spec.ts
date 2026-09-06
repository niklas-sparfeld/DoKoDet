import { expect, test, type Page, type Route } from "@playwright/test";

const RECORDING_ID = "recording-browser-fixture";
const RETIRED_ROUTE_MARKERS = [
  "card-event-review",
  "card-event-reviews",
  "visible-card-review",
  "visible-card-reviews",
  "identity-review",
  "identity-reviews",
];

type Scenario = "fresh" | "generated" | "failed" | "affected";

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

function json(value: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  };
}

async function stubPipeline(page: Page, scenario: Scenario) {
  const requestedPaths: string[] = [];
  let currentScenario = scenario;
  let workspaceRequests = 0;
  let conflictOnSelection = true;
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

  await expect(
    page.getByRole("heading", { name: "Recording pipeline" }),
  ).toBeVisible();
  await expect(page.getByText("Accepted video")).toBeVisible();
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

test("covers generated suggestions, reruns, failed jobs, upstream correction, cold reloads, and save conflicts", async ({
  page,
}) => {
  const requests = await stubPipeline(page, "generated");
  await page.goto(`/recordings/${RECORDING_ID}/pipeline/events?view=generated`);
  await expect(
    page.getByRole("heading", { name: "Recording pipeline" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Review" }).first(),
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
  await expect(
    page.getByRole("heading", { name: "Recording pipeline" }),
  ).toBeVisible();

  requests.setScenario("failed");
  await page.goto(`/recordings/${RECORDING_ID}/pipeline/events`);
  await page.getByText("Retained runs and actual inputs").click();
  await expect(
    page.getByRole("button", { name: /events-failed-1/ }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Events Failed" })).toBeVisible();

  requests.setScenario("affected");
  await page.goto(
    `/recordings/${RECORDING_ID}/pipeline/visible_cards?view=reviewed`,
  );
  await expect(
    page
      .getByRole("region", { name: "Visible cards" })
      .getByRole("link", { name: "Continue review" }),
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
