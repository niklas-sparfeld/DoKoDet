import { expect, test } from "@playwright/test";

const job = (id: string, label = `Fixture ${id}`) => ({
  schema_version: "backend-job/v1",
  id,
  type: "calibration_preview",
  label,
  state: "succeeded",
  revision: 3,
  created_at: "2026-11-06T10:00:00Z",
  updated_at: "2026-11-06T10:00:01Z",
  started_at: "2026-11-06T10:00:00Z",
  finished_at: "2026-11-06T10:00:01Z",
  context: {},
  request: {},
  request_hash: "hash",
  idempotency_key: "key",
  creator: null,
  correlation_id: null,
  parent_id: null,
  parent_step_id: null,
  retry_of: null,
  phase: "published",
  waiting_reason: null,
  failure: null,
  coverage: null,
  warnings: [],
  inputs: [],
  implementation: {},
  results: [
    {
      kind: "calibration_preview",
      path: `/api/jobs/${id}/calibration-preview`,
    },
  ],
  steps: [{ id: "preview", label: "Preview", state: "succeeded" }],
  capabilities: {
    cancel: { allowed: false, reason: null },
    retry: { allowed: false, reason: null },
    reorder: { allowed: false, reason: null },
  },
  worker_owner: null,
});

const logs = { entries: [], next_after: 0, truncated_before: 0 };

async function mockJobApi(page: import("@playwright/test").Page) {
  await page.route("**/api/jobs?**", async (route) => {
    const url = new URL(route.request().url());
    const scope = url.searchParams.get("scope");
    if (scope === "history" && url.searchParams.has("cursor")) {
      await route.fulfill({
        json: {
          items: [job("job-2")],
          next_cursor: null,
          groups: [],
          queue_revision: 1,
        },
      });
    } else {
      await route.fulfill({
        json: {
          items: scope === "history" ? [job("job-1")] : [],
          next_cursor: scope === "history" ? "history-2" : null,
          groups: [],
          queue_revision: 1,
        },
      });
    }
  });
  await page.route("**/api/jobs/*/logs**", (route) =>
    route.fulfill({ json: logs }),
  );
  await page.route("**/api/jobs/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    return route.fulfill({ json: job(id) });
  });
}

test("history pagination and browser navigation keep the exact job and result link", async ({
  page,
}) => {
  await mockJobApi(page);
  await page.goto("/jobs");
  await page.getByRole("button", { name: "History" }).click();
  const firstLink = page.getByRole("link", { name: "Fixture job-1" });
  await expect(firstLink).toBeVisible();
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByRole("link", { name: "Fixture job-2" })).toBeVisible();
  await firstLink.click();
  await expect(page).toHaveURL(/\/jobs\/job-1$/);
  await expect(
    page.getByRole("link", { name: "Open exact result" }),
  ).toHaveAttribute("href", "/api/jobs/job-1/calibration-preview");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Fixture job-1" }),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/jobs\/?$/);
  await page.goForward();
  await expect(page).toHaveURL(/\/jobs\/job-1$/);
  await expect(
    page.getByRole("link", { name: "Open exact result" }),
  ).toHaveAttribute("href", "/api/jobs/job-1/calibration-preview");
});

test("global Jobs drawer stays usable on desktop and narrow layouts", async ({
  page,
}) => {
  await page.route("**/api/jobs?**", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            ...job("queued-1", "Queued fixture"),
            state: "queued",
            capabilities: {
              cancel: { allowed: true },
              retry: { allowed: false },
              reorder: { allowed: true },
            },
          },
          {
            ...job("running-1", "Running fixture"),
            state: "running",
            capabilities: {
              cancel: { allowed: true },
              retry: { allowed: false },
              reorder: { allowed: false },
            },
          },
          {
            ...job("cancelling-1", "Cancelling fixture"),
            state: "cancelling",
            capabilities: {
              cancel: { allowed: false },
              retry: { allowed: false },
              reorder: { allowed: false },
            },
          },
        ],
        next_cursor: null,
        groups: ["queued-1", "running-1", "cancelling-1"].map((id) => ({
          group_id: id,
          child_job_ids: [id],
        })),
        queue_revision: 4,
      },
    }),
  );
  await page.route("**/v1/recordings", (route) =>
    route.fulfill({ json: { recordings: [] } }),
  );
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /Jobs/ });
  await expect(toggle).toContainText("3");
  await toggle.click();
  await expect(
    page.getByRole("link", { name: "Queued fixture" }),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "running" }),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "cancelling" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Enable queue reordering" }).click();
  const drawer = page.getByRole("complementary", { name: "Jobs" });
  const content = page.locator(".jobsAppContent");
  const drawerBox = await drawer.boundingBox();
  const contentBox = await content.boundingBox();
  expect(
    drawerBox && contentBox && contentBox.x + contentBox.width,
  ).toBeLessThanOrEqual(drawerBox?.x ?? 0);
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await toggle.click();
  await expect(drawer).toBeVisible();
  expect((await drawer.boundingBox())?.width).toBeLessThanOrEqual(390);
});

test("detail loading recovers after disconnection and list polling resumes after hidden-page return", async ({
  page,
}) => {
  let detailAttempts = 0;
  let activeLists = 0;
  await page.route("**/api/jobs?**", async (route) => {
    activeLists += 1;
    await route.fulfill({
      json: {
        items: [],
        next_cursor: null,
        groups: [],
        queue_revision: activeLists,
      },
    });
  });
  await page.route("**/api/jobs/job-offline", async (route) => {
    detailAttempts += 1;
    if (detailAttempts === 1)
      await route.fulfill({ status: 503, json: { detail: "offline" } });
    else await route.fulfill({ json: job("job-offline") });
  });
  await page.route("**/api/jobs/job-offline/logs**", (route) =>
    route.fulfill({ json: logs }),
  );
  await page.goto("/jobs/job-offline");
  await expect(
    page.getByRole("heading", { name: "Fixture job-offline" }),
  ).toBeVisible({ timeout: 8000 });
  expect(detailAttempts).toBeGreaterThanOrEqual(2);
  const beforeHidden = activeLists;
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(2300);
  expect(activeLists).toBe(beforeHidden);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => activeLists).toBeGreaterThan(beforeHidden);
});

test("drawer shows empty, disconnected, and failed job states", async ({
  page,
}) => {
  let disconnected = false;
  await page.route("**/api/jobs?**", async (route) => {
    const scope = new URL(route.request().url()).searchParams.get("scope");
    if (disconnected && scope === "active") return route.abort();
    await route.fulfill({
      json: {
        items:
          scope === "history"
            ? [{ ...job("failed-1", "Failed fixture"), state: "failed" }]
            : [],
        next_cursor: null,
        groups: [],
        queue_revision: 1,
      },
    });
  });
  await page.route("**/v1/recordings", (route) =>
    route.fulfill({ json: { recordings: [] } }),
  );
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /Jobs/ });
  await toggle.click();
  await expect(
    page.getByRole("status").filter({ hasText: "No active jobs" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "History" }).click();
  await expect(
    page.getByRole("link", { name: "Failed fixture" }),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "failed" }),
  ).toBeVisible();
  disconnected = true;
  await page.getByRole("button", { name: "Active (0)" }).click();
  await expect(page.getByRole("alert")).toContainText("Unable to load jobs");
});
