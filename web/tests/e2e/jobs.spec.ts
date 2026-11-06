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
