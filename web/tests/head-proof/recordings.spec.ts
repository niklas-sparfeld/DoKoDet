import { expect, test } from "@playwright/test";

test("persisted metadata list opens a recording after backend restart", async ({
  page,
}) => {
  await page.goto("/recordings");
  const rows = page.locator('a[href^="/recordings/"]');
  await expect(rows).toHaveCount(2);

  const selected = rows.filter({ hasText: "Generated selected" });
  const empty = page.locator('a[href="/recordings/missing-head"]');
  await expect(selected).toHaveCount(1);
  await expect(empty).toHaveCount(1);
  await expect(
    selected.locator("dt").filter({ hasText: "visible cards" }),
  ).toBeVisible();
  await expect(
    selected.locator("dd").filter({ hasText: "Not selected" }).first(),
  ).toBeVisible();
  await expect(selected.locator("ol")).toHaveCount(0);

  await selected.click();
  await expect(page).toHaveURL(/\/recordings\/m4-recording/);
  await expect(
    page.getByRole("navigation", { name: "Recording pipeline steps" }),
  ).toBeVisible();
});
