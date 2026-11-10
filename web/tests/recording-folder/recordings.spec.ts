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
  await expect(
    page.getByRole("heading", { name: "Recording pipeline" }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Recording pipeline steps" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Accepted video" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("complementary", { name: "Workspace inspector" })
      .getByText("recording-both", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(
    /\/recordings\/recording-both\/pipeline\/events$/,
  );
  await expect(
    page.getByRole("heading", { name: "Recording pipeline" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Accepted video" }),
  ).toBeVisible();

  const media = await page.request.get(
    "http://127.0.0.1:8767/v1/repository-bundles/recording-both/video",
  );
  expect(media.status()).toBe(200);
  expect(media.headers()["content-type"]).toBe("video/quicktime");
  expect(Number(media.headers()["content-length"])).toBeGreaterThan(0);
  expect((await media.body()).subarray(4, 8).toString()).toBe("ftyp");

  const mediaPage = await page.context().newPage();
  await mediaPage.setContent(
    '<video controls src="http://127.0.0.1:8767/v1/repository-bundles/recording-both/video"></video>',
  );
  const player = mediaPage.locator("video");
  await expect(player).toBeVisible();
  await expect
    .poll(() => player.evaluate((video: HTMLVideoElement) => video.duration))
    .toBeGreaterThan(1);
});
