import { expect, test } from "@playwright/test";

test("loads the frontend foundation shell", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle("DokoDetector");
  await expect(
    page.getByRole("heading", { name: "Round analysis timeline" }),
  ).toBeVisible();
});
