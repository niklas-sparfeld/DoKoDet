import { expect, test } from "@playwright/test";

test.describe("job start actions fixture", () => {
  test("supports keyboard, a long form, both drawers and desktop layout", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/job-start-actions-fixture.html");
    const start = page.getByRole("button", { name: "Run fixture action…" });
    await start.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Run fixture action" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Option 24")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(start).toBeFocused();
    await page.getByRole("button", { name: "Choose revision" }).click();
    await page.getByRole("button", { name: "Open job details" }).click();
    await expect(
      page.getByRole("main", { name: "Workspace center" }),
    ).toBeVisible();
  });

  test("uses a narrow sheet and keeps form controls inside its scroll area", async ({
    page,
  }) => {
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
  });
});
