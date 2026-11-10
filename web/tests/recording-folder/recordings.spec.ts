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

test("recording folder saves, selects, edits and reopens two event-set alternatives", async ({
  page,
}) => {
  const legacyEventReads: string[] = [];
  page.on("request", (request) => {
    if (
      request.url().includes("/api/pipeline/nodes/") ||
      request.url().includes("/api/recordings/recording-both/pipeline")
    ) {
      legacyEventReads.push(request.url());
    }
  });
  await page.goto("/recordings/recording-both/event-sets");
  await expect(
    page.getByRole("region", { name: "Event sets" }).getByRole("heading", {
      name: "Event sets",
    }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Add event" }).click();
  await page.getByLabel("Start (µs)").fill("100");
  await page.getByLabel("End (µs)").fill("200");
  await page.getByRole("button", { name: "Save event set" }).click();
  await expect(page.getByRole("status")).toContainText("Saved manual-");
  await page.getByRole("button", { name: "Select reference" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Selected this event set",
  );

  await page.getByLabel("End (µs)").fill("300");
  await page.getByRole("button", { name: "Save as alternative" }).click();
  await expect(page.getByRole("status")).toContainText("Saved manual-");
  const alternatives = page.getByRole("list", {
    name: "Saved event-set versions",
  });
  await expect(alternatives.getByRole("listitem")).toHaveCount(2);
  await page.getByRole("button", { name: "Select generated" }).click();
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Event sets" }).getByRole("heading", {
      name: "Event sets",
    }),
  ).toBeVisible();
  await expect(alternatives.getByText("generated")).toHaveCount(1);

  const savedButtons = page
    .getByRole("list", { name: "Saved event-set versions" })
    .getByRole("button");
  await savedButtons.first().click();
  await page.getByLabel("Start (µs)").fill("150");
  await page.getByRole("button", { name: "Save event set" }).click();
  await expect(page.getByRole("status")).toContainText("version 2");
  await page.reload();
  await expect(page.getByRole("button", { name: /version 2/ })).toBeVisible();
  await page.getByRole("button", { name: /version 2/ }).click();
  await expect(page.getByLabel("Start (µs)")).toHaveValue("150");
  expect(legacyEventReads).toEqual([]);
});
