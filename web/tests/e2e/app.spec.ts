import { expect, test } from "@playwright/test";

import {
  ANALYSIS_ID,
  resolvedStatus,
  resolvedTimeline,
} from "../../src/test/roundAnalysisFixture";

test("loads the frontend foundation shell", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle("DokoDetector");
  await expect(
    page.getByRole("heading", { name: "Round analysis timeline" }),
  ).toBeVisible();
});

test.beforeEach(async ({ page }) => {
  await page.route("**/v1/round-analyses/**", async (route) => {
    if (route.request().url().endsWith("/timeline")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(resolvedTimeline),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(resolvedStatus),
    });
  });
});

test("renders a resolved analysis in synchronized desktop columns", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/round-analyses/${ANALYSIS_ID}`);

  await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Table observation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Reconstruction hypothesis" }),
  ).toBeVisible();
  await expect(page.getByRole("listbox").getByRole("option")).toHaveCount(2);
  await expect(page.getByText("No central frame available")).toBeVisible();

  const rowStyle = await page
    .getByRole("option", { name: /observation-001/ })
    .evaluate((element) => getComputedStyle(element).gridTemplateColumns);
  expect(rowStyle.split(" ")).toHaveLength(3);

  const scriptSource = await page
    .locator('script[type="module"]')
    .getAttribute("src");
  expect(scriptSource).toMatch(/^\/round-analyses\/assets\/index-[^/]+\.js$/);
});

test("restores deep links and moves the selected row with keyboard navigation", async ({
  page,
}) => {
  await page.goto(
    `/round-analyses/${ANALYSIS_ID}?row=observation-002&hypothesis=2`,
  );

  const selectedRow = page.getByRole("option", {
    name: /observation-002/,
    selected: true,
  });
  await expect(selectedRow).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Hypothesis" })).toHaveValue(
    "2",
  );
  await expect(
    page.getByRole("option", { name: /observation-002/, selected: true }),
  ).toContainText("Hearts Ten");

  await selectedRow.press("ArrowUp");

  await expect(page).toHaveURL(
    `/round-analyses/${ANALYSIS_ID}?hypothesis=2&row=observation-001`,
  );
  await expect(
    page.getByRole("option", { name: /observation-001/, selected: true }),
  ).toBeVisible();

  await expect(page.getByText("Clubs Nine").first()).toBeVisible();
});
