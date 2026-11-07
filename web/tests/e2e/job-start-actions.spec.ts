import { expect, test } from "@playwright/test";

test.describe("job start actions fixture", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/jobs?**", (route) =>
      route.fulfill({
        json: { items: [], next_cursor: null, groups: [], queue_revision: 1 },
      }),
    );
  });

  test("supports keyboard, a long form, both drawers and desktop layout", async ({
    page,
  }) => {
    const jobSubmissions: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/jobs")) {
        jobSubmissions.push(request.url());
      }
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/job-start-actions-fixture.html");
    await page.getByRole("button", { name: "Show lineage" }).click();
    const lineage = page.getByRole("region", { name: "Pipeline lineage" });
    await expect(lineage).toBeVisible();
    await expect(lineage.getByText("Fixture events")).toBeVisible();
    await lineage.getByRole("button", { name: "r events-r1" }).click();
    await page.getByRole("button", { name: /Jobs/ }).click();
    const jobs = page.getByRole("complementary", { name: "Jobs" });
    await expect(jobs).toBeVisible();

    const start = page.getByRole("button", { name: "Run fixture action…" });
    await start.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Run fixture action" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Option 24")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(start).toBeFocused();
    await expect(lineage).toBeVisible();
    await expect(jobs).toBeVisible();
    await jobs.getByRole("button", { name: "Close Jobs drawer" }).click();
    await expect(jobs).toBeHidden();
    await expect(
      page.getByRole("main", { name: "Workspace center" }),
    ).toBeVisible();
    expect(jobSubmissions).toEqual([]);
  });

  test("uses a narrow sheet and keeps form controls inside its scroll area", async ({
    page,
  }) => {
    const jobSubmissions: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/jobs")) {
        jobSubmissions.push(request.url());
      }
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/job-start-actions-fixture.html");
    await page.getByRole("button", { name: "Run fixture action…" }).click();
    const dialog = page.getByRole("dialog", { name: "Run fixture action" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeVisible();
    const geometry = await dialog.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return { width: rect.width, viewport: window.innerWidth };
    });
    expect(geometry.width).toBe(geometry.viewport);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(
      page.getByRole("main", { name: "Workspace center" }),
    ).toBeVisible();
    expect(jobSubmissions).toEqual([]);
  });
});
