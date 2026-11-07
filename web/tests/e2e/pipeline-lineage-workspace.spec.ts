import { expect, test, type Route } from "@playwright/test";

const RECORDING_ID = "recording-lineage-browser-fixture";
const EVENT_NODE = "events-first-pass";
const OBSERVATION_NODE = "observations-assembly";
const ANALYSIS_ID = "analysis-all-sources";

const eventContent = (startUs = 100) => ({
  schema_version: "event-data/v1",
  events: [
    {
      event_id: "event-1",
      event_type: "card_state_changed",
      start_us: startUs,
      end_us: startUs + 100,
    },
  ],
});

function stage(key: string) {
  const reviewable = key !== "round_analyses";
  return {
    key,
    processor_key: `${key}-processor`,
    processor_type: key,
    output_content_type: key,
    has_maintained_reference: reviewable,
    state: key === "events" ? "data-available" : "empty",
    input_options: [],
    compatible_input_sets: [],
    selection_revision: reviewable ? 0 : null,
    selected_generated_revision_id: null,
    selected_completed_reference_revision_id: null,
    runs: [],
    analyses: [],
    reference: reviewable
      ? {
          state: "empty",
          draft_revision: null,
          selected_completion: null,
          source_revision_id: null,
          coverage: null,
          coverage_state: "none",
          affected_count: 0,
          updated_at: null,
        }
      : null,
    can_run: false,
    run_blockers: [],
    can_review: false,
    review_blockers: [],
    comparable_run_ids: [],
  };
}

function revision(nodeId: string, revisionId: string, createdAt: string) {
  return {
    node_id: nodeId,
    revision_id: revisionId,
    content_sha256: "d".repeat(64),
    created_at: createdAt,
  };
}

function graph(copyCreated: boolean) {
  const nodes = [
    {
      node_id: EVENT_NODE,
      name: "First pass",
      content_type: "events",
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "events-r2",
    },
    {
      node_id: OBSERVATION_NODE,
      name: "Assembly",
      content_type: "table_observations",
      source: { recording_id: RECORDING_ID },
      head_revision_id: "observations-r1",
    },
  ];
  const revisions = [
    revision(EVENT_NODE, "events-r1", "2026-11-01T10:00:00Z"),
    revision(EVENT_NODE, "events-r2", "2026-11-02T10:00:00Z"),
    revision(OBSERVATION_NODE, "observations-r1", "2026-11-03T10:00:00Z"),
  ];
  const edges = [
    {
      kind: "revised",
      from: ["revision", EVENT_NODE, "events-r1"],
      to: ["revision", EVENT_NODE, "events-r2"],
    },
    {
      kind: "used",
      role: "events",
      from: ["revision", EVENT_NODE, "events-r2"],
      to: ["run", ANALYSIS_ID],
    },
    {
      kind: "used",
      role: "observations",
      from: ["revision", OBSERVATION_NODE, "observations-r1"],
      to: ["run", ANALYSIS_ID],
    },
  ];
  if (copyCreated) {
    nodes.push({
      node_id: "events-copy",
      name: "First pass copy",
      content_type: "events",
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "events-copy-r1",
    });
    revisions.push(
      revision("events-copy", "events-copy-r1", "2026-11-04T10:00:00Z"),
    );
    edges.push({
      kind: "copied",
      from: ["revision", EVENT_NODE, "events-r2"],
      to: ["revision", "events-copy", "events-copy-r1"],
    });
  }
  return {
    schema_version: "pipeline-lineage-graph/v1",
    nodes,
    revisions,
    runs: [{ run_id: ANALYSIS_ID, run_kind: "analysis", status: "complete" }],
    artifacts: [],
    edges,
  };
}

test("lineage drawer preserves exact revisions, reviews, and all analysis sources", async ({
  page,
}, testInfo) => {
  let copied = false;
  await page.route("**/api/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(value),
      });

    if (path === `/api/recordings/${RECORDING_ID}/pipeline`) {
      await json({
        schema_version: "pipeline-workspace/v1",
        recording_id: RECORDING_ID,
        video: {
          schema_version: "recording-video/v1",
          recording_id: RECORDING_ID,
          relative_path: `recordings/${RECORDING_ID}/video.mp4`,
          video_sha256: "a".repeat(64),
          byte_length: 1,
          duration_us: 1_000_000,
        },
        stages: [
          stage("events"),
          stage("visible_cards"),
          stage("visual_identities"),
          stage("table_observations"),
          stage("round_analyses"),
        ],
        diagnostics: [],
      });
      return;
    }
    if (path === `/api/recordings/${RECORDING_ID}/pipeline/lineage`) {
      await json(graph(copied));
      return;
    }
    if (path.endsWith("/pipeline/nodes/events-first-pass/edit")) {
      copied = true;
      await json({
        node_id: "events-copy",
        revision_id: "events-copy-r1",
        copied: true,
        reason: "downstream_use",
        name: "First pass copy",
      });
      return;
    }
    const revisionMatch = path.match(
      /\/pipeline\/nodes\/([^/]+)\/revisions\/([^/]+)$/,
    );
    if (revisionMatch) {
      const [, nodeId, revisionId] = revisionMatch;
      const name = nodeId === "events-copy" ? "First pass copy" : "First pass";
      await json({
        node_id: nodeId,
        name,
        content_type: "events",
        source: { video_sha256: "a".repeat(64) },
        head_revision_id:
          nodeId === "events-copy" ? "events-copy-r1" : "events-r2",
        revision_id: revisionId,
        content: eventContent(nodeId === "events-copy" ? 150 : 100),
      });
      return;
    }
    if (path.endsWith("/reviews")) {
      await json([
        {
          kind: "item",
          review_id: "review-corrected",
          item_id: "event-1",
          decision: "corrected",
        },
      ]);
      return;
    }
    if (path.endsWith("/video")) {
      await route.fulfill({ status: 200, contentType: "video/mp4", body: "" });
      return;
    }
    await json({ error: `Unmocked browser fixture route: ${path}` }, 404);
  });
  await page.route("**/v1/recordings/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/v1/repository-bundles/**", (route) =>
    route.fulfill({ status: 200, contentType: "video/mp4", body: "" }),
  );

  const selection = JSON.stringify({
    schema_version: "pipeline-lineage-selection/v1",
    selected: { events: { node_id: EVENT_NODE, revision_id: "events-r2" } },
  });
  await page.goto(
    `/recordings/${RECORDING_ID}/pipeline/events?lineage=${encodeURIComponent(selection)}`,
  );
  await expect(page.getByLabel("Start (µs)")).toHaveValue("100");
  await expect(page.getByText("corrected", { exact: true })).toBeVisible();

  const measureLayout = () =>
    page.evaluate(() => {
      const bounds = (selector: string) => {
        const element = document.querySelector(selector);
        if (element === null) return null;
        const rect = element.getBoundingClientRect();
        return {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      };
      const center = document.querySelector('[data-slot="center"]');
      return {
        viewport: { width: window.innerWidth, height: window.innerHeight },
        center: bounds('[data-slot="center"]'),
        inspector: bounds('[aria-label="Workspace inspector"]'),
        rail: bounds('[aria-label="Timeline Rail"]'),
        stepLabels: Array.from(
          document.querySelectorAll(
            '[aria-label="Recording pipeline steps"] a',
          ),
        ).map((link) => link.textContent?.trim()),
        centerHasVideo: center?.querySelector("video") !== null,
        centerButtons: Array.from(center?.querySelectorAll("button") ?? []).map(
          (button) => button.innerText.trim(),
        ),
        centerInputs: Array.from(
          center?.querySelectorAll("input, textarea, select") ?? [],
        ).map((input) => input.getAttribute("aria-label") ?? input.tagName),
        pageScrollWidth: document.documentElement.scrollWidth,
      };
    });

  await page.setViewportSize({ width: 1440, height: 900 });
  const desktopLayout = await measureLayout();
  console.log("M0_DESKTOP_LAYOUT", JSON.stringify(desktopLayout));
  expect(desktopLayout.stepLabels).toEqual([
    "Events",
    "Visible cards",
    "Virtual scenes",
    "Visual identities",
    "Table observations",
    "Round analysis",
  ]);
  expect(desktopLayout.centerHasVideo).toBe(true);
  expect(desktopLayout.centerButtons).toContain("Add event at playhead");
  await page.screenshot({
    path: testInfo.outputPath("0109-m0-current-events-desktop.png"),
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  const narrowLayout = await measureLayout();
  console.log("M0_NARROW_LAYOUT", JSON.stringify(narrowLayout));
  expect(narrowLayout.viewport).toEqual({ width: 390, height: 844 });
  expect(narrowLayout.stepLabels).toEqual(desktopLayout.stepLabels);
  expect(narrowLayout.centerHasVideo).toBe(true);
  expect(narrowLayout.centerButtons).toContain("Add event at playhead");
  expect(narrowLayout.pageScrollWidth).toBe(390);
  await page.screenshot({
    path: testInfo.outputPath("0109-m0-current-events-narrow.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.getByRole("button", { name: "Show lineage" }).click();
  const drawer = page.getByRole("region", { name: "Pipeline lineage" });
  await expect(
    drawer.getByRole("region", { name: "Events lineage" }),
  ).toBeVisible();
  await expect(page.getByLabel("Events data")).toContainText("First pass");
  await expect(page.getByLabel("Events data")).toContainText("events-r2");
  await expect(drawer.getByText("Revision source").first()).toBeVisible();
  const analysis = drawer.getByRole("region", {
    name: "Round analysis lineage",
  });
  await expect(analysis.getByText(`${EVENT_NODE} / events-r2`)).toBeVisible();
  await expect(
    analysis.getByText(`${OBSERVATION_NODE} / observations-r1`),
  ).toBeVisible();

  await page.getByRole("link", { name: "Visible cards" }).click();
  await expect(
    page.getByText("Select a Visible cards data set in the lineage drawer."),
  ).toBeVisible();
  await expect(page).toHaveURL(/lineage=/);

  await page.getByRole("link", { name: "Events" }).click();
  await page.getByRole("button", { name: "Show lineage" }).click();
  await page.getByText("History (2)").click();
  await page.getByRole("button", { name: "r events-r1" }).click();
  await expect(
    page.getByText("This revision is historical and read-only."),
  ).toBeVisible();
  await expect(page.getByText("corrected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "r events-r2" }).last().click();

  await page.getByLabel("Start (µs)").fill("150");
  await expect(
    page.getByText(
      /Created First pass copy from First pass after editing because it has downstream use/,
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Events data")).toContainText("First pass copy");
  await expect(page.getByLabel("Events data")).toContainText("events-copy-r1");
  const selected = JSON.parse(
    new URL(page.url()).searchParams.get("lineage") ?? "{}",
  ) as {
    selected?: { events?: { node_id?: string; revision_id?: string } };
  };
  expect(selected.selected?.events).toEqual({
    node_id: "events-copy",
    revision_id: "events-copy-r1",
  });

  await page.reload();
  await expect(page.getByLabel("Start (µs)")).toHaveValue("150");
});
