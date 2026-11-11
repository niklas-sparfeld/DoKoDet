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
  const firstSaved = await page.getByRole("status").textContent();
  const firstSetId = firstSaved?.match(/manual-[^ ]+/)?.[0];
  expect(firstSetId).toBeTruthy();
  await page.getByRole("button", { name: "Select reference" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Selected this event set",
  );

  await page.getByLabel("End (µs)").fill("300");
  await page.getByRole("button", { name: "Save as alternative" }).click();
  await expect(page.getByRole("status")).toContainText("Saved manual-");
  const secondSaved = await page.getByRole("status").textContent();
  const secondSetId = secondSaved?.match(/manual-[^ ]+/)?.[0];
  expect(secondSetId).toBeTruthy();
  const alternatives = page.getByRole("list", {
    name: "Saved event-set versions",
  });
  await expect(alternatives.getByRole("listitem")).toHaveCount(4);
  await page.getByRole("button", { name: "Select generated" }).click();
  await page
    .getByRole("button", { name: `Open ${firstSetId} version 1` })
    .click();
  await expect(page.getByRole("status")).toContainText(
    `Opened ${firstSetId} version 1`,
  );
  await page.getByLabel("Start (µs)").fill("150");
  await page.getByRole("button", { name: "Save event set" }).click();
  await expect(page.getByRole("status")).toContainText("version 2");
  await page.getByRole("button", { name: "Review as accepted" }).click();
  await expect(page.getByRole("status")).toContainText("Saved accepted review");
  const editedResponse = await page.request.get(
    `http://127.0.0.1:8767/api/recordings/recording-both/event-sets/${firstSetId}/versions/2`,
  );
  expect(editedResponse.status()).toBe(200);
  expect((await editedResponse.json()).content.events[0].start_us).toBe(150);
  await page.getByRole("button", { name: "Select reference" }).click();

  const restarted = await page.request.post(
    "http://127.0.0.1:8767/__test/restart",
  );
  expect(restarted.status()).toBe(200);
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Event sets" }).getByRole("heading", {
      name: "Event sets",
    }),
  ).toBeVisible();
  const reopenedAlternatives = page.getByRole("list", {
    name: "Saved event-set versions",
  });
  await expect(reopenedAlternatives.getByRole("listitem")).toHaveCount(5);
  const editedFirst = reopenedAlternatives.getByRole("listitem").filter({
    has: page.getByRole("button", { name: `Open ${firstSetId} version 2` }),
  });
  const selectedSecond = reopenedAlternatives.getByRole("listitem").filter({
    has: page.getByRole("button", { name: `Open ${secondSetId} version 1` }),
  });
  await expect(editedFirst).toContainText("reference");
  await expect(selectedSecond).toContainText("generated");
  await page
    .getByRole("button", { name: `Open ${firstSetId} version 2` })
    .click();
  await expect(page.getByLabel("Start (µs)")).toHaveValue("150");
  await expect(
    page.getByRole("list", { name: "Saved event-set reviews" }),
  ).toContainText("overall: accepted");
  await page
    .getByRole("button", { name: `Open ${secondSetId} version 1` })
    .click();
  await expect(page.getByLabel("Start (µs)")).toHaveValue("100");
  await expect(page.getByLabel("End (µs)")).toHaveValue("300");
  expect(legacyEventReads).toEqual([]);
});

test("event-set workspace opens an exact parent from a saved link after restart", async ({
  page,
}) => {
  await page.goto(
    "/recordings/recording-both/event-sets?set=retained-reference&version=1",
  );
  await expect(page.getByLabel("Start (µs)")).toHaveValue("500000");
  await expect(page.getByRole("status")).toContainText(
    "Opened retained-reference version 1",
  );
  const restarted = await page.request.post(
    "http://127.0.0.1:8767/__test/restart",
  );
  expect(restarted.status()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("Start (µs)")).toHaveValue("500000");
  await expect(page.getByRole("status")).toContainText(
    "Opened retained-reference version 1",
  );
});

test("pre-M3 visible-card output reopens its exact event parent after selection and restart", async ({
  page,
}) => {
  const recordingId = "cardeventnet-IMG_0662";
  const parentSetId = "1dca5a93-4a87-59f6-ab83-d5c72154916b";
  const parentVersion = "d41f92f9-7fd1-52db-a065-7c94f963713a";
  const expectedOutputFileSha256 =
    "23d6a61ffa5c362d2e7bbf1f24c708c93a1800d684573a1fe4078961119da45c";
  const expectedOutputContentSha256 =
    "e7d585be69996a440c7c56d6e3fb3a2cd582288327b82555561a38c49191a1ad";
  const expectedParentContentSha256 =
    "00ce1f56caf862db76601d6e82cd36587d56f2c9fd23de208364559b910832f5";
  const forbiddenRuntimeReads: string[] = [];
  await page.route(
    new RegExp(
      `/api/recordings/${recordingId}/pipeline/(?:runs|lineage)(?:/|$)`,
    ),
    async (route) => {
      forbiddenRuntimeReads.push(route.request().url());
      await route.abort();
    },
  );
  const savedOutputFacts = async () => {
    const response = await page.request.get(
      "http://127.0.0.1:8767/__test/saved-output-sha256",
    );
    expect(response.ok()).toBeTruthy();
    return (await response.json()) as {
      file_sha256: string;
      content_sha256: string;
    };
  };
  const outputBefore = await savedOutputFacts();
  expect(outputBefore).toEqual({
    file_sha256: expectedOutputFileSha256,
    content_sha256: expectedOutputContentSha256,
  });
  const parentDetail = async () => {
    const response = await page.request.get(
      `http://127.0.0.1:8767/api/recordings/${recordingId}/event-sets/${parentSetId}/versions/${parentVersion}`,
    );
    expect(response.ok()).toBeTruthy();
    return (await response.json()).content_sha256 as string;
  };
  expect(await parentDetail()).toBe(expectedParentContentSha256);
  const initialSelectionResponse = await page.request.get(
    `http://127.0.0.1:8767/api/recordings/${recordingId}/event-sets`,
  );
  expect(initialSelectionResponse.ok()).toBeTruthy();
  const initialSelection = await initialSelectionResponse.json();
  expect(initialSelection.head.generated.set_id).toBe(
    "retained-generated-alternative",
  );

  await page.goto(`/recordings/${recordingId}`);
  await page.getByRole("link", { name: "Visible cards" }).click();
  const exactParentLink = page.getByRole("link", {
    name: `Open exact event parent ${parentSetId}@${parentVersion}`,
  });
  await expect(exactParentLink).toBeVisible();
  await exactParentLink.click();
  await expect(page).toHaveURL(
    new RegExp(
      `/recordings/${recordingId}/event-sets\\?set=${parentSetId}&version=${parentVersion}`,
    ),
  );
  await expect(page.getByLabel("Start (µs)").first()).toHaveValue("2001934");

  await page.getByRole("button", { name: "Select generated" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Selected this event set as the generated choice.",
  );
  const changedSelectionResponse = await page.request.get(
    `http://127.0.0.1:8767/api/recordings/${recordingId}/event-sets`,
  );
  const changedSelection = await changedSelectionResponse.json();
  expect(changedSelection.head.generated).toEqual({
    set_id: parentSetId,
    version: parentVersion,
  });

  await page.getByRole("link", { name: "Open recording workspace" }).click();
  await page.getByRole("link", { name: "Visible cards" }).click();
  await expect(exactParentLink).toBeVisible();
  const restarted = await page.request.post(
    "http://127.0.0.1:8767/__test/restart",
  );
  expect(restarted.status()).toBe(200);
  await page.reload();
  await expect(exactParentLink).toBeVisible();
  await exactParentLink.click();
  await expect(page.getByLabel("Start (µs)").first()).toHaveValue("2001934");

  const persistedSelectionResponse = await page.request.get(
    `http://127.0.0.1:8767/api/recordings/${recordingId}/event-sets`,
  );
  const persistedSelection = await persistedSelectionResponse.json();
  expect(persistedSelection.head.generated).toEqual({
    set_id: parentSetId,
    version: parentVersion,
  });
  expect(await savedOutputFacts()).toEqual(outputBefore);
  expect(await parentDetail()).toBe(expectedParentContentSha256);
  expect(forbiddenRuntimeReads).toEqual([]);
});

test("normal recording workflow edits an event, runs detection and reopens its exact input", async ({
  page,
}) => {
  await page.goto("/recordings");
  await page.getByRole("link", { name: "Open video-both.mov" }).click();
  await expect(page).toHaveURL(/\/recordings\/recording-both$/);
  await expect(
    page.getByRole("heading", { name: "Recording pipeline" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Visible cards" }).click();
  await page.getByRole("button", { name: "Play recording" }).click();
  await expect(
    page.getByRole("button", { name: "Pause recording" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Events" }).click();
  await page.getByRole("link", { name: "Open event-set workspace" }).click();
  await expect(
    page.getByRole("region", { name: "Event sets" }).getByRole("heading", {
      name: "Event sets",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Open retained-reference version 1" })
    .click();
  await expect(
    page.getByRole("list", { name: "Saved event-set reviews" }),
  ).toContainText("overall: accepted");
  await page.getByLabel("Start (µs)").fill("550000");
  await page.getByRole("button", { name: "Save as alternative" }).click();
  await expect(page.getByRole("status")).toContainText("Saved manual-");
  const savedNotice = await page.getByRole("status").textContent();
  const correctedSetId = savedNotice?.match(/manual-[^ ]+/)?.[0];
  expect(correctedSetId).toBeTruthy();
  await page.getByRole("button", { name: "Select generated" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Selected this event set",
  );

  // Inspect the unselected generated alternative. Selection remains on the correction.
  await page
    .getByRole("button", { name: "Open retained-generated version 1" })
    .click();
  await expect(page.getByLabel("Start (µs)")).toHaveValue("600000");
  await page.getByRole("link", { name: "Open recording workspace" }).click();
  await page.getByRole("link", { name: "Visible cards" }).click();
  await page.getByRole("button", { name: "Detect visible cards…" }).click();
  const dialog = page.getByRole("dialog", { name: "Detect visible cards" });
  await expect(dialog).toContainText(
    `Event set ${correctedSetId}@1 · generated`,
  );
  await dialog
    .getByLabel("Detector and model")
    .selectOption({ label: "Cloud · Gemini" });
  const responsePromise = page.waitForResponse(
    (candidate) =>
      candidate.url().includes("/api/jobs") &&
      candidate.request().method() === "POST",
  );
  await dialog
    .getByRole("button", { name: "Start detect visible cards" })
    .click();
  const response = await responsePromise;
  expect(response.status(), await response.text()).toBe(202);
  const accepted = await response.json();
  const jobId = accepted.id as string;
  const waitForJob = async () => {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const result = await page.request.get(
        `http://127.0.0.1:8767/api/jobs/${jobId}`,
      );
      if (result.ok()) {
        const job = await result.json();
        if (["succeeded", "failed"].includes(job.state)) return job;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new Error("The visible-card job did not reach a terminal state.");
  };
  const job = await waitForJob();
  expect(job.state).toBe("succeeded");
  const runList = await page.request.get(
    "http://127.0.0.1:8767/api/recordings/recording-both/pipeline/visible-cards",
  );
  expect(runList.ok()).toBeTruthy();
  const visibleRuns = (await runList.json()).runs as Array<{ run_id: string }>;
  const runId = visibleRuns[0]?.run_id;
  expect(runId).toBeTruthy();
  const runResponse = await page.request.get(
    `http://127.0.0.1:8767/api/recordings/recording-both/pipeline/visible-cards/${runId}/result`,
  );
  expect(runResponse.ok()).toBeTruthy();
  const savedRun = await runResponse.json();
  expect(savedRun.request.input_event_set_ref).toMatchObject({
    set_id: correctedSetId,
    version: "1",
  });
  expect(savedRun.revisions.length).toBeGreaterThan(0);

  // Change the current event selection after the detector has frozen its input.
  await page.getByRole("link", { name: "Events" }).click();
  await page.getByRole("link", { name: "Open event-set workspace" }).click();
  await page
    .getByRole("button", { name: "Open retained-generated version 1" })
    .click();
  const selectUneditedAlternative = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      response.url().endsWith("/event-sets/selection"),
  );
  await page.getByRole("button", { name: "Select generated" }).click();
  expect((await selectUneditedAlternative).status()).toBe(200);
  await expect(page.getByRole("status")).toContainText(
    "Selected this event set as the generated choice.",
  );
  const restarted = await page.request.post(
    "http://127.0.0.1:8767/__test/restart",
  );
  expect(restarted.status()).toBe(200);
  await page.goto(`/recordings/recording-both/pipeline/visible_cards`);
  const reopened = await page.request.get(
    `http://127.0.0.1:8767/api/recordings/recording-both/pipeline/visible-cards/${runId}/result`,
  );
  expect(reopened.ok()).toBeTruthy();
  const reopenedRun = await reopened.json();
  expect(reopenedRun.request.input_event_set_ref).toMatchObject({
    set_id: correctedSetId,
    version: "1",
  });
  const exactInput = await page.request.get(
    `http://127.0.0.1:8767/api/recordings/recording-both/event-sets/${correctedSetId}/versions/1`,
  );
  expect(exactInput.ok()).toBeTruthy();
  expect((await exactInput.json()).content.events[0].start_us).toBe(550000);
  await expect(
    page.getByRole("heading", { name: "Recording pipeline" }),
  ).toBeVisible();
});
