import { expect, test } from "@playwright/test";

test("loads the frontend foundation shell", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle("DokoDetector");
  await expect(
    page.getByRole("heading", { name: "Round analysis timeline" }),
  ).toBeVisible();
});

test("loads an analysis entry route and its typed API smoke view", async ({
  page,
}) => {
  const analysisId = "550e8400-e29b-41d4-a716-446655440033";
  await page.route("**/v1/round-analyses/**", async (route) => {
    if (route.request().url().endsWith("/timeline")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          analysis_id: analysisId,
          reconstruction_status: "resolved",
          rows: [{}, {}],
          hypotheses: [{}],
          warnings: [],
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        analysis_id: analysisId,
        recording_id: "recording-0033",
        round_id: "round-0033",
        session_id: "550e8400-e29b-41d4-a716-446655440034",
        state: "complete",
        total_evidence_packages: 2,
        completed_evidence_packages: 2,
        result: {},
        error: null,
        created_at: "2026-08-30T12:00:00Z",
        started_at: "2026-08-30T12:00:01Z",
        completed_at: "2026-08-30T12:00:02Z",
      }),
    });
  });

  await page.goto(`/round-analyses/${analysisId}`);

  await expect(page.getByText("Timeline API connected")).toBeVisible();
  await expect(page.getByText(/2 evidence rows/)).toBeVisible();
  await expect(page.getByText(/1 retained hypothesis/)).toBeVisible();

  const scriptSource = await page
    .locator('script[type="module"]')
    .getAttribute("src");
  expect(scriptSource).toMatch(/^\/round-analyses\/assets\/index-[^/]+\.js$/);
});
