import { expect, test } from "@playwright/test";

import {
  ANALYSIS_ID,
  ambiguousStatus,
  ambiguousTimeline,
  changedCounterfactualResponse,
  impossibleStatus,
  impossibleTimeline,
  incompleteStatus,
  incompleteTimeline,
  resolvedStatus,
  resolvedTimeline,
  unchangedCounterfactualResponse,
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
    const fixture = new URL(page.url()).searchParams.get("fixture");
    const variants = {
      ambiguous: { status: ambiguousStatus, timeline: ambiguousTimeline },
      incomplete: { status: incompleteStatus, timeline: incompleteTimeline },
      impossible: { status: impossibleStatus, timeline: impossibleTimeline },
    } as const;
    const selected =
      fixture === null ? null : variants[fixture as keyof typeof variants];
    const status = selected?.status ?? resolvedStatus;
    const timeline = selected?.timeline ?? resolvedTimeline;
    if (
      route.request().method() === "POST" &&
      route.request().url().includes("/counterfactuals")
    ) {
      const counterfactual =
        new URL(page.url()).searchParams.get("counterfactual") === "unchanged"
          ? unchangedCounterfactualResponse
          : changedCounterfactualResponse;
      await route.fulfill({
        contentType: "application/json",
        status: 201,
        body: JSON.stringify(counterfactual),
      });
      return;
    }
    if (route.request().url().endsWith("/timeline")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(timeline),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(status),
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
  await expect(
    page
      .getByRole("option", { name: /observation-001/ })
      .getByRole("group", { name: "Counterfactual" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Open evidence frame for event 1" })
    .click();
  const frameDialog = page.getByRole("dialog", { name: /Event 1/ });
  await expect(frameDialog).toBeVisible();
  await expect(
    frameDialog.getByRole("img", {
      name: "Enlarged evidence frame for event 1",
    }),
  ).toHaveCount(1);
  await frameDialog
    .getByRole("button", { name: "Close enlarged evidence frame" })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
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

test("explains failure states and stacks the timeline at the narrow test width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/round-analyses/${ANALYSIS_ID}?fixture=incomplete`);

  await expect(page.getByText("Incomplete input")).toBeVisible();
  await expect(page.getByText("No retained hypotheses.")).toBeVisible();
  await expect(page.getByText("Missing Frame:")).toBeVisible();

  const rowDisplay = await page
    .getByRole("option", { name: /observation-001/ })
    .evaluate((element) => getComputedStyle(element).display);
  expect(rowDisplay).toBe("block");

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(horizontalOverflow).toBeLessThanOrEqual(0);
  await expect(page.getByText("Raw reconstruction-result JSON")).toBeVisible();
});

test("shows retained alternatives and search truncation as text cues", async ({
  page,
}) => {
  await page.goto(`/round-analyses/${ANALYSIS_ID}?fixture=ambiguous`);

  await expect(
    page.getByText(/This result is ambiguous\. Each retained hypothesis/),
  ).toBeVisible();
  await expect(page.getByText("Search Truncated:")).toBeVisible();
  await expect(page.getByText("Player 01 · Clubs Nine")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Jump to observation-001" }),
  ).toBeVisible();
});

test("runs a changed counterfactual and marks the derived differences", async ({
  page,
}) => {
  await page.goto("/round-analyses/" + ANALYSIS_ID + "?counterfactual=changed");

  await expect(
    page.getByRole("heading", { name: "Counterfactual run" }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Exclude observation observation-001" })
    .check();
  await page.getByRole("button", { name: "Run counterfactual" }).click();

  await expect(
    page.getByRole("heading", { name: "Baseline versus counterfactual" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Changed observations and cards" }),
  ).toBeVisible();
  await expect(
    page.getByText("Changed", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Clubs Nine").last()).toBeVisible();
  await expect(
    page.getByText(
      "Search truncation makes this comparison incomplete. The displayed hypotheses may not include every legal sequence.",
    ),
  ).toBeVisible();
});

test("shows stable no-change markers for an unchanged counterfactual", async ({
  page,
}) => {
  await page.goto(
    "/round-analyses/" + ANALYSIS_ID + "?counterfactual=unchanged",
  );

  await page
    .getByRole("checkbox", { name: "Exclude observation observation-001" })
    .check();
  await page.getByRole("button", { name: "Run counterfactual" }).click();

  await expect(page.getByText("No card-play changes.")).toBeVisible();
  await expect(
    page.getByText("No selected or ignored source actions changed."),
  ).toBeVisible();
  await expect(page.getByText("No focused decisions changed.")).toBeVisible();
});
