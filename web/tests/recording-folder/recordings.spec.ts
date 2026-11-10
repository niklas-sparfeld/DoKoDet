import { expect, test } from "@playwright/test";

test("recording folder appears in the browser list and opens after reload", async ({
  page,
}) => {
  await page.goto("/recordings");
  const recording = page.getByRole("link", { name: "Open video-both.mov" });
  await expect(recording).toBeVisible();
  await expect(recording).toContainText("Not selected");
  await recording.click();
  await expect(page).toHaveURL(/\/recordings\/recording-both$/);
  await page.reload();
  await expect(page).toHaveURL(/\/recordings\/recording-both$/);

  const media = await page.request.get(
    "http://127.0.0.1:8767/v1/repository-bundles/recording-both/video",
  );
  expect(media.status()).toBe(200);
  expect(await media.body()).toEqual(
    Buffer.from("DokoDetector shared repository intake fixture video v1\n"),
  );
});
