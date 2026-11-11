import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const backendUrl = "http://127.0.0.1:18081";
let backend: ChildProcess | null = null;
let root = "";

async function startBackend() {
  backend = spawn(
    "mise",
    [
      "exec",
      "--",
      "uv",
      "run",
      "--project",
      "../backend",
      "python",
      "../backend/scripts/detection_set_e2e_server.py",
      "--root",
      root,
      "--port",
      "18081",
    ],
    { cwd: process.cwd(), stdio: "ignore" },
  );
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (backend.exitCode !== null)
      throw new Error(`Detection-set backend exited with ${backend.exitCode}.`);
    try {
      const response = await fetch(
        `${backendUrl}/api/recordings/recording-both/pipeline`,
      );
      if (response.ok) return;
    } catch {
      // Wait for the isolated server to start.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Detection-set backend did not start.");
}

async function stopBackend() {
  if (backend === null || backend.exitCode !== null) return;
  backend.kill("SIGTERM");
  await new Promise<void>((resolve) => {
    backend?.once("exit", () => resolve());
    setTimeout(resolve, 5_000);
  });
  backend = null;
}

test.beforeAll(async () => {
  root = await mkdtemp(resolve(tmpdir(), "doko-detection-set-e2e-"));
  await startBackend();
});

test.afterAll(async () => {
  await stopBackend();
  if (root !== "") await rm(root, { recursive: true, force: true });
});

test("detector output, segment edit, geometry review, and exact reopen survive restart", async ({
  page,
  request,
}) => {
  const savedEventSet = await request.post(
    `${backendUrl}/api/recordings/recording-both/event-sets`,
    {
      data: {
        set_id: "browser-events",
        version: "1",
        content: {
          schema_version: "event-data/v1",
          events: [
            {
              event_id: "event-000000",
              event_type: "card_state_changed",
              start_us: 0,
              end_us: 100_000,
            },
            {
              event_id: "event-000001",
              event_type: "card_state_changed",
              start_us: 250_000,
              end_us: 350_000,
            },
            {
              event_id: "event-000002",
              event_type: "card_state_changed",
              start_us: 500_000,
              end_us: 600_000,
            },
          ],
        },
        origin: "manual",
        provenance: { source: "browser-proof" },
      },
    },
  );
  expect(savedEventSet.ok()).toBeTruthy();
  const eventVersion = await (
    await request.get(
      `${backendUrl}/api/recordings/recording-both/event-sets/browser-events/versions/1`,
    )
  ).json();
  const eventListing = await (
    await request.get(`${backendUrl}/api/recordings/recording-both/event-sets`)
  ).json();
  const eventSelection = await request.put(
    `${backendUrl}/api/recordings/recording-both/event-sets/selection`,
    {
      data: {
        choice: "generated",
        reference: { set_id: "browser-events", version: "1" },
        expected_recording_version: eventListing.recording_version,
      },
    },
  );
  expect(eventSelection.ok(), await eventSelection.text()).toBeTruthy();
  const runResponse = await request.post(
    `${backendUrl}/api/recordings/recording-both/pipeline/visible-cards`,
    {
      data: {
        run_id: "browser-detector-run",
        input_event_set_ref: {
          set_id: "browser-events",
          version: "1",
          content_sha256: eventVersion.content_sha256,
        },
      },
    },
  );
  expect(runResponse.ok(), await runResponse.text()).toBeTruthy();
  const run = await runResponse.json();
  const deadline = Date.now() + 30_000;
  let result: Record<string, unknown> | null = null;
  while (Date.now() < deadline) {
    const response = await request.get(
      `${backendUrl}/api/recordings/recording-both/pipeline/visible-cards/${run.run_id}/result`,
    );
    if (response.ok()) {
      const body = await response.json();
      if (body.status === "complete" || body.status === "failed") {
        result = body;
        break;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  expect(result).not.toBeNull();
  expect(result).toMatchObject({ status: "complete" });
  expect(
    (
      result as {
        revisions: Array<{ content: { outcomes: Array<{ status: string }> } }>;
      }
    ).revisions[0].content.outcomes.map((outcome) => outcome.status),
  ).toEqual(["detected", "empty", "failed"]);
  const detectionRef = (
    result as { detection_set_ref: { set_id: string; version: string } }
  ).detection_set_ref;
  const original = await (
    await request.get(
      `${backendUrl}/api/recordings/recording-both/detection-sets/${detectionRef.set_id}/versions/${detectionRef.version}`,
    )
  ).json();
  expect(
    original.content.frames.map(
      (frame: { frame_id: string }) => frame.frame_id,
    ),
  ).toEqual(["event-000000", "event-000001"]);
  expect(original.content.frames[1].detections).toEqual([]);

  await page.goto("/recordings/recording-both/pipeline/visible_cards");
  const openSetLink = page.getByRole("link", {
    name: `Open detection set ${detectionRef.set_id} · version ${detectionRef.version}`,
  });
  await expect(openSetLink).toBeVisible();
  await openSetLink.click();
  await expect(
    page.getByRole("heading", {
      name: new RegExp(`Detection set ${detectionRef.set_id}`),
    }),
  ).toBeVisible();
  const segments = page.getByRole("textbox", { name: "Detection segments" });
  await expect(segments).toBeVisible();
  const before = JSON.parse(await segments.inputValue()) as Array<
    Record<string, unknown>
  >;
  before[0].polygon = [
    { x: 9, y: 6 },
    { x: 54, y: 6 },
    { x: 54, y: 48 },
    { x: 9, y: 48 },
  ];
  await segments.fill(JSON.stringify(before, null, 2));
  await page
    .getByRole("button", { name: "Save as new detection version" })
    .click();
  await expect(page).toHaveURL(/detection_version=2/);
  await expect(
    page.getByRole("heading", { name: new RegExp("version 2") }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Accept geometry" }).click();
  await expect(page.getByText(/Geometry accepted review saved/)).toBeVisible();

  const versionTwo = await (
    await request.get(
      `${backendUrl}/api/recordings/recording-both/detection-sets/${detectionRef.set_id}/versions/2`,
    )
  ).json();
  expect(
    versionTwo.content.frames[0].detections[0].segments[0].polygon[0],
  ).toEqual({ x: 9, y: 6 });
  expect(
    original.content.frames[0].detections[0].segments[0].polygon[0],
  ).not.toEqual({ x: 9, y: 6 });

  const exactUrl = page.url();
  await stopBackend();
  await startBackend();
  await page.goto(exactUrl);
  await expect(
    page.getByText(/Geometry reviews for this version/),
  ).toBeVisible();
  await expect(page.getByText(/accepted ·/)).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Detection segments" }),
  ).toHaveValue(/"x": 9/);
});
