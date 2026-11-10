import { expect, test } from "@playwright/test";

test("persisted HEAD list remains visible with an unavailable recording", async ({
  page,
}) => {
  await page.goto("/recordings");
  const rows = page.locator('a[href^="/recordings/"]');
  const valid = rows.filter({
    has: page.locator('[data-stage-state="data-available"]'),
  });
  const unavailable = rows.filter({
    has: page.locator('[data-stage-state="unavailable"]'),
  });
  await expect(valid).toHaveCount(1);
  await expect(unavailable).toHaveCount(2);
  await expect(
    valid.locator('[data-stage-state="data-available"]'),
  ).toContainText("Data available");
  await expect(
    rows.locator('[data-stage-state="unavailable"]').first(),
  ).toContainText("Unavailable");
  await page.reload();
  await expect(valid).toHaveCount(1);
  await valid.click();
  await expect(page).toHaveURL(/\/recordings\/m4-recording/);
  await expect(
    page.getByRole("navigation", { name: "Recording pipeline steps" }),
  ).toBeVisible();
});
