import { expect, test, type Route } from "@playwright/test";
import type { PipelineWorkspaceStage } from "../../src/api/client";
import {
  resolvedStatus,
  resolvedTimeline,
} from "../../src/test/roundAnalysisFixture";

const RECORDING_ID = "recording-lineage-browser-fixture";
const FRAME_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);
const EVENT_NODE = "events-first-pass";
const OBSERVATION_NODE = "observations-assembly";
const ANALYSIS_ID = "analysis-all-sources";
const VISIBLE_NODE = "visible-card-review";
const IDENTITY_NODE = "visual-identity-review";
const SCENE_NODE = "virtual-scene-review";
const CALIBRATION_ID = "calibration-r1";

function exactFrameIdentity() {
  return {
    schema_version: "exact-event/v1",
    source_video_sha256: "a".repeat(64),
    requested_time_us: 250000,
    frame_index: 3,
    presentation_timestamp_us: 300000,
    width: 640,
    height: 360,
    decoder_version: "fixture-decoder/v1",
    transform_version: "fixture-transform/v1",
    output_encoding: "jpeg",
    content_type: "image/jpeg",
    image_sha256: "b".repeat(64),
    policy: "exact-event/v1",
  };
}

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
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "observations-r1",
    },
    {
      node_id: VISIBLE_NODE,
      name: "Reviewed visible cards",
      content_type: "visible_cards",
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "visible-r1",
    },
    {
      node_id: IDENTITY_NODE,
      name: "Reviewed visual identities",
      content_type: "visual_identities",
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "identity-r1",
    },
    {
      node_id: SCENE_NODE,
      name: "Reviewed virtual scenes",
      content_type: "virtual_scenes",
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "scene-r1",
    },
  ];
  const revisions = [
    revision(EVENT_NODE, "events-r1", "2026-11-01T10:00:00Z"),
    revision(EVENT_NODE, "events-r2", "2026-11-02T10:00:00Z"),
    revision(OBSERVATION_NODE, "observations-r1", "2026-11-03T10:00:00Z"),
    revision(VISIBLE_NODE, "visible-r1", "2026-11-03T11:00:00Z"),
    revision(IDENTITY_NODE, "identity-r1", "2026-11-03T11:30:00Z"),
    revision(SCENE_NODE, "scene-r1", "2026-11-03T12:00:00Z"),
  ];
  const edges = [
    {
      kind: "produced",
      from: ["run", "observations-run"],
      to: ["revision", OBSERVATION_NODE, "observations-r1"],
    },
    {
      kind: "used",
      role: "events",
      from: ["revision", EVENT_NODE, "events-r2"],
      to: ["run", "observations-run"],
    },
    {
      kind: "used",
      role: "visible_cards",
      from: ["revision", VISIBLE_NODE, "visible-r1"],
      to: ["run", "observations-run"],
    },
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
    nodes.push({
      node_id: "virtual-scene-copy",
      name: "Reviewed virtual scenes copy",
      content_type: "virtual_scenes",
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "scene-r2",
    });
    revisions.push(
      revision("virtual-scene-copy", "scene-r2", "2026-11-04T12:00:00Z"),
    );
    edges.push({
      kind: "copied",
      from: ["revision", SCENE_NODE, "scene-r1"],
      to: ["revision", "virtual-scene-copy", "scene-r2"],
    });
    nodes.push({
      node_id: "visible-card-copy",
      name: "Reviewed visible cards copy",
      content_type: "visible_cards",
      source: { recording_id: RECORDING_ID, video_sha256: "a".repeat(64) },
      head_revision_id: "visible-r2",
    });
    revisions.push(
      revision("visible-card-copy", "visible-r2", "2026-11-04T11:00:00Z"),
    );
    edges.push({
      kind: "copied",
      from: ["revision", VISIBLE_NODE, "visible-r1"],
      to: ["revision", "visible-card-copy", "visible-r2"],
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

test("lineage and M4 node editors preserve exact revisions and geometry evidence", async ({
  page,
}, testInfo) => {
  let copied = false;
  let calibrationMismatch = false;
  let sourceMismatch = false;
  let observationMutations = 0;
  let copiedSceneContent: Record<string, unknown> | null = null;
  let copiedVisibleContent: Record<string, unknown> | null = null;
  await page.route("**/api/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (
      path.includes(`/pipeline/nodes/${OBSERVATION_NODE}/`) &&
      route.request().method() !== "GET"
    )
      observationMutations += 1;
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
    if (
      path ===
      `/api/recordings/${RECORDING_ID}/pipeline/calibrations/${CALIBRATION_ID}`
    ) {
      await json({
        schema_version: "table-plane-calibration/v1",
        calibration_revision_id: CALIBRATION_ID,
        recording_id: RECORDING_ID,
        source_revision: "visible-r1",
        frame_width: 640,
        frame_height: 360,
        image_to_table: [
          [1, 0, 0],
          [0, 1, 0],
          [0, 0, 1],
        ],
        table_to_image: [
          [1, 0, 0],
          [0, 1, 0],
          [0, 0, 1],
        ],
        card_short_size: 80,
        card_long_size: 120,
        card_aspect_ratio: 1.5,
        candidate_receipt_digests: [],
        algorithm_version: "fixture/v1",
        coordinate_system: "fixture",
        corner_order: "fixture",
        angle_convention: "fixture",
        diagnostics: { fit: "recorded fixture" },
        calibration_digest: calibrationMismatch
          ? "e".repeat(64)
          : "c".repeat(64),
      });
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
    if (path === `/api/pipeline/nodes/${SCENE_NODE}/edit`) {
      copied = true;
      const body = await route.request().postDataJSON();
      copiedSceneContent = body.content as Record<string, unknown>;
      await json({
        node_id: "virtual-scene-copy",
        revision_id: "scene-r2",
        copied: true,
        reason: "downstream_use",
        name: "Reviewed virtual scenes copy",
      });
      return;
    }
    if (path === `/api/pipeline/nodes/${VISIBLE_NODE}/edit`) {
      copied = true;
      const body = await route.request().postDataJSON();
      copiedVisibleContent = body.content as Record<string, unknown>;
      await json({
        node_id: "visible-card-copy",
        revision_id: "visible-r2",
        copied: true,
        reason: "downstream_use",
        name: "Reviewed visible cards copy",
      });
      return;
    }
    if (path.includes("/pipeline/nodes/") && path.includes("/reviews/")) {
      await json({ review_id: "review-saved" });
      return;
    }
    const revisionMatch = path.match(
      /\/pipeline\/nodes\/([^/]+)\/revisions\/([^/]+)$/,
    );
    if (revisionMatch) {
      const [, nodeId, revisionId] = revisionMatch;
      if (nodeId === VISIBLE_NODE) {
        await json({
          node_id: nodeId,
          name: "Reviewed visible cards",
          content_type: "visible_cards",
          source: { video_sha256: "a".repeat(64) },
          head_revision_id: "visible-r1",
          revision_id: revisionId,
          metadata: {},
          content: {
            schema_version: "visible-card-data/v2",
            outcomes: [
              {
                event_id: "event-1",
                frame_identity: exactFrameIdentity(),
                status: "detected",
                candidates: [
                  {
                    card_id: "visible-region-1",
                    geometry: {
                      polygons: [
                        [
                          { x: 100, y: 100 },
                          { x: 300, y: 100 },
                          { x: 300, y: 400 },
                        ],
                      ],
                    },
                  },
                ],
                pile_regions: [],
                ignored_regions: [],
                pile_detection_status: "supported",
                error: null,
              },
              {
                event_id: "visible-frame-1",
                frame_identity: exactFrameIdentity(),
                status: "detected",
                candidates: [
                  {
                    card_id: "visible-region-1",
                    geometry: {
                      polygons: [
                        [
                          { x: 100, y: 100 },
                          { x: 300, y: 100 },
                          { x: 300, y: 400 },
                          { x: 100, y: 400 },
                        ],
                      ],
                    },
                  },
                ],
                pile_regions: [],
                ignored_regions: [],
                pile_detection_status: "supported",
                error: null,
              },
            ],
          },
        });
        return;
      }
      if (nodeId === "visible-card-copy" && copiedVisibleContent !== null) {
        await json({
          node_id: nodeId,
          name: "Reviewed visible cards copy",
          content_type: "visible_cards",
          source: { video_sha256: "a".repeat(64) },
          head_revision_id: "visible-r2",
          revision_id: revisionId,
          metadata: {},
          content: copiedVisibleContent,
        });
        return;
      }
      if (nodeId === OBSERVATION_NODE) {
        await json({
          node_id: nodeId,
          name: "Assembly",
          content_type: "table_observations",
          source: { video_sha256: "a".repeat(64) },
          head_revision_id: "observations-r1",
          revision_id: revisionId,
          metadata: {},
          content: {
            schema_version: "table-observation-data/v1",
            observations: [
              {
                observation_id: "observation-1",
                observed_at_ms: 250,
                status: "observed",
                capabilities: ["identity_candidates"],
                cards: [
                  {
                    observed_card_id: "visible-region-1",
                    side: "face_up",
                    identity_status: "unknown",
                    identity_candidates: [],
                  },
                ],
                diagnostics: { assembly: { event_id: "event-1" } },
              },
            ],
          },
        });
        return;
      }
      if (nodeId === IDENTITY_NODE) {
        await json({
          node_id: nodeId,
          name: "Reviewed visual identities",
          content_type: "visual_identities",
          source: { video_sha256: "a".repeat(64) },
          head_revision_id: "identity-r1",
          revision_id: revisionId,
          metadata: {},
          content: {
            schema_version: "visual-identity-data/v2",
            outcomes: [
              {
                card_id: "identity-card-1",
                frame_identity: exactFrameIdentity(),
                geometry: {
                  polygons: [
                    [
                      { x: 100, y: 100 },
                      { x: 300, y: 100 },
                      { x: 300, y: 400 },
                      { x: 100, y: 400 },
                    ],
                  ],
                },
                crop_input_provenance: {
                  input_kind: "reviewed_visible_card",
                  manifest_digest: "f".repeat(64),
                  source_revision_id: "visible-r1",
                  source_revision_digest: "d".repeat(64),
                  source_node_id: VISIBLE_NODE,
                  source_node_revision_id: "visible-r1",
                },
                crop_identity: {
                  status: "usable",
                  image_sha256: "e".repeat(64),
                  crop_policy: "oracle_visible_region",
                },
                candidates: [
                  {
                    identity: "CLUBS_ACE",
                    score: 0.8,
                    score_meaning: "probability",
                  },
                ],
                status: "classified",
                error: null,
                unusable_reason: null,
              },
            ],
          },
        });
        return;
      }
      if (nodeId === SCENE_NODE || nodeId === "virtual-scene-copy") {
        const sceneContent =
          nodeId === "virtual-scene-copy" && copiedSceneContent !== null
            ? copiedSceneContent
            : {
                schema_version: "virtual-scene-data/v1",
                frames: [
                  {
                    frame_id: "scene-frame-1",
                    frame_identity: exactFrameIdentity(),
                    calibration: {
                      revision_id: CALIBRATION_ID,
                      digest: "c".repeat(64),
                    },
                    scene: {
                      source_frame_id: "scene-frame-1",
                      source_frame_width: 640,
                      source_frame_height: 360,
                      calibration_revision_id: CALIBRATION_ID,
                      calibration_digest: "c".repeat(64),
                      poses: [
                        {
                          card_id: "pose-1",
                          center: [320, 180],
                          rotation_degrees: 0,
                        },
                      ],
                      stacking_order: {
                        card_ids: ["pose-1"],
                        uncertain_edges: [],
                        contradictions: [],
                      },
                    },
                    pile_regions: [],
                    ignore_regions: [],
                  },
                ],
              };
        await json({
          node_id: nodeId,
          name:
            nodeId === SCENE_NODE
              ? "Reviewed virtual scenes"
              : "Reviewed virtual scenes copy",
          content_type: "virtual_scenes",
          source: { video_sha256: "a".repeat(64) },
          head_revision_id: nodeId === SCENE_NODE ? "scene-r1" : "scene-r2",
          revision_id: revisionId,
          metadata: {},
          content: sceneContent,
        });
        return;
      }
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
    if (path.includes("/pipeline/derived-views/exact-event/")) {
      const requestedTimeUs = path.split("/").at(-1) ?? "0";
      if (requestedTimeUs === "300000")
        await new Promise((resolve) => setTimeout(resolve, 250));
      const frameUrl = new URL(route.request().url());
      const frameIndex =
        frameUrl.searchParams.get("frame_index") ??
        String(Math.ceil(Number(requestedTimeUs) / 100_000));
      const resolvedTimeUs = String(Number(frameIndex) * 100_000);
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: FRAME_BYTES,
        headers: {
          ETag: `"${"b".repeat(64)}"`,
          "X-DokoDetector-Source-Sha256": sourceMismatch
            ? "b".repeat(64)
            : "a".repeat(64),
          "X-DokoDetector-Frame-Index": frameIndex,
          "X-DokoDetector-Frame-Width": "640",
          "X-DokoDetector-Frame-Height": "360",
          "X-DokoDetector-Requested-Time-Us": requestedTimeUs,
          "X-DokoDetector-Frame-Time-Us": resolvedTimeUs,
          "X-DokoDetector-Frame-Interval-Us": "0",
        },
      });
      return;
    }
    if (path.includes("/pipeline/derived-views/identity-crops/")) {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: FRAME_BYTES,
      });
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
  const verifyScrubRoundTrip = async () => {
    const playhead = page.getByLabel("Recording playhead");
    const before = Number(await playhead.inputValue());
    await playhead.focus();
    await playhead.press("ArrowRight");
    await expect(playhead).toHaveValue(String(before + 1_000));
    await expect(page).toHaveURL(new RegExp(`t_us=${before + 1_000}(?:&|$)`));
    await playhead.press("ArrowLeft");
    await expect(playhead).toHaveValue(String(before));
    await expect(page).toHaveURL(new RegExp(`t_us=${before}(?:&|$)`));
  };
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
        centerText: center?.textContent?.trim() ?? "",
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
  console.log("M3_DESKTOP_LAYOUT", JSON.stringify(desktopLayout));
  expect(desktopLayout.stepLabels).toEqual([
    "Events",
    "Visible cards",
    "Virtual scenes",
    "Visual identities",
    "Table observations",
    "Round analysis",
  ]);
  expect(desktopLayout.centerHasVideo).toBe(false);
  expect(desktopLayout.centerText).toBe("");
  expect(desktopLayout.centerButtons).toEqual([]);
  expect(desktopLayout.centerInputs).toEqual([]);
  await expect(page.getByRole("img", { name: "Source frame" })).toBeVisible();
  await verifyScrubRoundTrip();
  await expect(
    page.getByRole("button", { name: "Add event at timeline cursor" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Play recording" }),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("0109-m3-events-still-desktop.png"),
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  const narrowLayout = await measureLayout();
  console.log("M3_NARROW_LAYOUT", JSON.stringify(narrowLayout));
  expect(narrowLayout.viewport).toEqual({ width: 390, height: 844 });
  expect(narrowLayout.stepLabels).toEqual(desktopLayout.stepLabels);
  expect(narrowLayout.centerHasVideo).toBe(false);
  expect(narrowLayout.centerText).toBe("");
  expect(narrowLayout.centerButtons).toEqual([]);
  expect(narrowLayout.centerInputs).toEqual([]);
  expect(narrowLayout.pageScrollWidth).toBe(390);
  await page.screenshot({
    path: testInfo.outputPath("0109-m3-events-still-narrow.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.getByRole("button", { name: "event-1" }).click();
  await expect(page).toHaveURL(/t_us=100/);
  await expect(
    page.getByRole("region", { name: "Timeline Rail" }),
  ).toContainText("Requested 100 µs · exact frame 100000 µs");
  await page.getByRole("button", { name: /Next frame/ }).click();
  await expect(page).toHaveURL(/t_us=200/);
  const delayedFrameRequest = page.waitForRequest((request) =>
    request.url().includes("exact-event/300000"),
  );
  await page.getByRole("button", { name: /Next frame/ }).click();
  await delayedFrameRequest;
  await page.getByRole("button", { name: /Next frame/ }).click();
  await expect(page).toHaveURL(/t_us=400/);
  await expect(
    page.getByRole("region", { name: "Timeline Rail" }),
  ).toContainText("Requested 400000 µs · exact frame 400000 µs");

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

  await page.getByRole("link", { name: "Visible cards" }).click();
  await page.getByRole("button", { name: "Show lineage" }).click();
  await page.getByRole("button", { name: "r visible-r1" }).click();
  const visibleEditor = page.getByRole("region", {
    name: "Visible-card lineage editor",
  });
  await expect(
    visibleEditor.getByRole("heading", { name: "Visible cards" }),
  ).toBeVisible();
  const visibleSelection = new URL(page.url());
  visibleSelection.searchParams.set("item", "visible-frame-1");
  visibleSelection.searchParams.set("t_us", "250000");
  await page.goto(`${visibleSelection.pathname}${visibleSelection.search}`);
  await expect(visibleEditor.getByText(/Frame visible-frame-1/)).toBeVisible();
  await expect(page.getByRole("img", { name: "Source frame" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Visible region 1" }),
  ).toHaveCount(0);
  await expect(visibleEditor.getByLabel("candidates JSON")).toBeVisible();
  await expect(page.getByRole("button", { name: /Pan left/ })).toBeVisible();
  await expect(page.getByLabel("View zoom")).toBeVisible();
  const visibleCenter = await page
    .getByRole("region", { name: "Spatial evidence surface" })
    .evaluate((element) => ({
      video: element.querySelector("video") !== null,
      text: element.textContent?.trim() ?? "",
      controls: element.querySelectorAll("button, input, textarea, select")
        .length,
      polygons: element.querySelectorAll("svg polygon").length,
    }));
  expect(visibleCenter).toEqual({
    video: false,
    text: "",
    controls: 0,
    polygons: 1,
  });
  await verifyScrubRoundTrip();
  sourceMismatch = true;
  await page.reload();
  await expect(
    visibleEditor.getByText(
      "The recording source changed while loading this frame.",
    ),
  ).toBeVisible();
  await expect(visibleEditor.getByLabel("candidates JSON")).toHaveAttribute(
    "readonly",
    "",
  );
  await expect(
    visibleEditor.getByRole("button", { name: "Accept outcome" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("region", { name: "Spatial evidence surface" }),
  ).toHaveCount(0);
  sourceMismatch = false;
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Spatial evidence surface" }),
  ).toBeVisible();

  const visibleRegions = visibleEditor.getByLabel("candidates JSON");
  const visibleRegionDraft = JSON.parse(
    (await visibleRegions.inputValue()) || "[]",
  ) as unknown[];
  await visibleRegions.fill(
    JSON.stringify([
      ...visibleRegionDraft,
      {
        card_id: "visible-region-2",
        geometry: {
          polygons: [
            [
              { x: 350, y: 100 },
              { x: 500, y: 100 },
              { x: 500, y: 300 },
              { x: 350, y: 300 },
            ],
          ],
        },
      },
    ]),
  );
  await visibleEditor
    .getByRole("button", { name: "Save visible-card changes" })
    .click();
  await expect(page).toHaveURL(/visible-card-copy/);
  expect(copiedVisibleContent).not.toBeNull();
  expect(
    (copiedVisibleContent?.outcomes as Array<{ candidates: unknown[] }>)[1]
      ?.candidates,
  ).toHaveLength(2);

  const identityLineage = JSON.parse(
    new URL(page.url()).searchParams.get("lineage") ?? "{}",
  ) as { selected?: Record<string, unknown> };
  identityLineage.selected = {
    ...identityLineage.selected,
    visual_identities: {
      node_id: IDENTITY_NODE,
      revision_id: "identity-r1",
    },
  };
  await page.goto(
    `/recordings/${RECORDING_ID}/pipeline/visual_identities?lineage=${encodeURIComponent(JSON.stringify(identityLineage))}&item=identity-card-1&t_us=250000`,
  );
  const identityEditor = page.getByRole("region", {
    name: "Visual identity data",
  });
  await expect(
    identityEditor.getByText("oracle_visible_region", { exact: true }),
  ).toBeVisible();
  await expect(identityEditor.getByText("visible-r1").first()).toBeVisible();
  await expect(
    identityEditor.getByRole("img", {
      name: "Frozen processor input crop for identity-card-1",
    }),
  ).toBeVisible();
  const identityCenter = await page
    .getByRole("region", { name: "Spatial evidence surface" })
    .evaluate((element) => ({
      video: element.querySelector("video") !== null,
      text: element.textContent?.trim() ?? "",
      controls: element.querySelectorAll("button, input, textarea, select")
        .length,
      polygons: element.querySelectorAll("svg polygon").length,
    }));
  expect(identityCenter).toEqual({
    video: false,
    text: "",
    controls: 0,
    polygons: 1,
  });
  await verifyScrubRoundTrip();
  await page.getByRole("button", { name: "Focus crop" }).click();
  await expect(
    page.getByRole("button", { name: "Show all inspector sections" }),
  ).toBeVisible();
  const assertSourceAndInspectorDoNotOverlap = async () => {
    const layout = await page.evaluate(() => {
      const center = document.querySelector('[data-slot="center"]');
      const inspector = document.querySelector('[data-slot="inspector"]');
      if (center === null || inspector === null) return null;
      const source = center.getBoundingClientRect();
      const details = inspector.getBoundingClientRect();
      return {
        overlaps:
          source.left < details.right &&
          source.right > details.left &&
          source.top < details.bottom &&
          source.bottom > details.top,
        viewportWidth: window.innerWidth,
        centerLeft: source.left,
        inspectorRight: details.right,
      };
    });
    expect(layout).not.toBeNull();
    expect(layout!.overlaps).toBe(false);
    expect(layout!.centerLeft).toBeGreaterThanOrEqual(0);
    expect(layout!.inspectorRight).toBeLessThanOrEqual(layout!.viewportWidth);
  };
  await assertSourceAndInspectorDoNotOverlap();
  await page.setViewportSize({ width: 390, height: 844 });
  await assertSourceAndInspectorDoNotOverlap();
  await expect(page.getByRole("img", { name: "Source frame" })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page
    .getByRole("button", { name: "Show all inspector sections" })
    .click();
  const classificationChoices = identityEditor.getByRole("region", {
    name: "Identity classification choices",
  });
  await classificationChoices.focus();
  await page.keyboard.press("1");
  await expect(
    identityEditor.getByLabel("Identity outcome JSON"),
  ).toContainText('"score": 1');
  await expect(
    page.locator('[data-identity-card-list-slot="cards"]'),
  ).toHaveCount(0);

  await page.getByRole("link", { name: "Virtual scenes" }).click();
  await page.getByRole("button", { name: "Show lineage" }).click();
  await page.getByRole("button", { name: "r scene-r1" }).click();
  const sceneEditor = page.getByRole("region", {
    name: "Virtual-scene editor",
  });
  await expect(
    sceneEditor.getByRole("heading", { name: "Virtual scenes" }),
  ).toBeVisible();
  const sceneSelection = new URL(page.url());
  sceneSelection.searchParams.set("item", "scene-frame-1");
  sceneSelection.searchParams.set("t_us", "250000");
  await page.goto(`${sceneSelection.pathname}${sceneSelection.search}`);
  await expect(
    page.getByRole("button", { name: "Card pose pose-1" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Card pose pose-1" }).click();
  await expect(page.getByLabel("Table center X")).toHaveValue("320");
  await page.getByText("Calibration diagnostics").click();
  await expect(page.getByText(/recorded fixture/)).toBeVisible();
  await expect(page.getByLabel("Viewpoint")).toHaveValue("source");
  await page.getByLabel("Viewpoint").selectOption("rectified");
  await expect(
    page.locator('[data-slot="center"] [data-viewpoint="rectified"]'),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: "Source frame" })).toHaveAttribute(
    "src",
    /^data:image\/png/,
  );
  const poseOutline = page.getByRole("button", { name: "Card pose pose-1" });
  const poseBox = await poseOutline.boundingBox();
  expect(poseBox).not.toBeNull();
  await page.mouse.move(
    poseBox!.x + poseBox!.width / 2,
    poseBox!.y + poseBox!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    poseBox!.x + poseBox!.width / 2 + 16,
    poseBox!.y + poseBox!.height / 2,
    { steps: 2 },
  );
  await page.mouse.up();
  await expect(page.getByLabel("Table center X")).not.toHaveValue("320");
  const sceneCenter = await page
    .getByRole("region", { name: "Spatial evidence surface" })
    .evaluate((element) => ({
      video: element.querySelector("video") !== null,
      text: element.textContent?.trim() ?? "",
      controls: element.querySelectorAll("button, input, textarea, select")
        .length,
      polygons: element.querySelectorAll("svg polygon").length,
    }));
  expect(sceneCenter).toEqual({
    video: false,
    text: "",
    controls: 0,
    polygons: 1,
  });
  await verifyScrubRoundTrip();
  calibrationMismatch = true;
  await page.reload();
  await expect(
    page.getByText(
      "The calibration response does not match this scene revision.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Save scene" })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Accept frame" }),
  ).toBeDisabled();
  await expect(
    page
      .getByRole("region", { name: "Spatial evidence surface" })
      .locator("svg polygon"),
  ).toHaveCount(0);
  calibrationMismatch = false;
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Card pose pose-1" }),
  ).toBeVisible();
  await page.getByLabel("Viewpoint").selectOption("rectified");
  await expect(
    page.locator('[data-slot="center"] [data-viewpoint="rectified"]'),
  ).toBeVisible();
  await page.getByRole("button", { name: "Accept frame" }).click();
  await expect(
    page.getByText("Review decision saved for this exact revision."),
  ).toBeVisible();
  await page.getByLabel("Table center X").fill("330");
  await page.getByRole("button", { name: "Save scene" }).click();
  await expect(page).toHaveURL(/virtual-scene-copy/);
  await expect(page.getByLabel("Table center X")).toHaveValue("330");

  const observationSelection = JSON.stringify({
    schema_version: "pipeline-lineage-selection/v1",
    selected: {
      events: { node_id: EVENT_NODE, revision_id: "events-r2" },
      visible_cards: { node_id: VISIBLE_NODE, revision_id: "visible-r1" },
      table_observations: {
        node_id: OBSERVATION_NODE,
        revision_id: "observations-r1",
      },
    },
  });
  await page.goto(
    `/recordings/${RECORDING_ID}/pipeline/table_observations?lineage=${encodeURIComponent(observationSelection)}&item=observation-1&t_us=250000`,
  );
  await page
    .getByRole("button", { name: /observation-1.*observed.*1 cards/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Selected table observation" }),
  ).toContainText("observation-1");
  await expect(
    page.getByRole("button", { name: /observation-1.*observed.*1 cards/ }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("region", { name: "Spatial evidence surface" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Spatial evidence surface" })
      .locator("polygon"),
  ).toHaveCount(1);
  await expect(page.getByLabel("Source frame")).toBeVisible();
  const observationCenter = await page
    .locator('[data-slot="center"]')
    .evaluate((element) => ({
      video: element.querySelector("video") !== null,
      text: element.textContent?.trim() ?? "",
      controls: element.querySelectorAll("button, input, textarea, select")
        .length,
      polygons: element.querySelectorAll("svg polygon").length,
    }));
  expect(observationCenter).toEqual({
    video: false,
    text: "",
    controls: 0,
    polygons: 1,
  });
  await verifyScrubRoundTrip();
  await expect(page.getByLabel("Selected table observation")).toContainText(
    "Exact spatial source links",
  );
  await expect(page.getByLabel("Selected table observation")).toContainText(
    "unknown",
  );
  expect(observationMutations).toBe(0);
});

test("round analysis uses the shared frame, rail, inspector, and saved selection", async ({
  page,
}) => {
  const recordingId = "analysis-workspace-browser-fixture";
  const analysisId = "analysis-workspace-1";
  const analysisStage = stage("round_analyses");
  analysisStage.state = "complete";
  analysisStage.analyses = [
    {
      analysis_id: analysisId,
      recording_id: recordingId,
      round_id: "round-analysis-fixture",
      session_id: "session-analysis-fixture",
      state: "complete",
      progress: { completed: 2, total: 2 },
      input_revision_ids: ["observations-r1"],
      request: { rules_version: "fixture/v1", requested_time_us: 1_000_000 },
      created_at: "2026-11-07T00:00:00Z",
      started_at: null,
      completed_at: "2026-11-07T00:00:01Z",
      failure: null,
    },
  ];
  const timeline = {
    ...resolvedTimeline,
    recording_id: recordingId,
    analysis_id: analysisId,
    reconstruction_status: "ambiguous" as const,
    inferred_plays: [
      {
        play_index: 1,
        player: "player-01",
        card: "CLUBS_NINE",
        position: "before" as const,
        before_observation_id: null,
        after_observation_id: "observation-001",
      },
    ],
  };
  let counterfactualSubmission: {
    body: Record<string, unknown>;
    idempotencyKey: string | undefined;
  } | null = null;
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (value: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(value),
      });
    if (path === "/api/jobs" && route.request().method() === "POST") {
      counterfactualSubmission = {
        body: route.request().postDataJSON() as Record<string, unknown>,
        idempotencyKey: route.request().headers()["idempotency-key"],
      };
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ id: "counterfactual-job", state: "queued" }),
      });
      return;
    }
    if (path === "/api/jobs") {
      await json({
        items: [],
        next_cursor: null,
        groups: [],
        queue_revision: 1,
      });
      return;
    }
    if (path === `/api/recordings/${recordingId}/pipeline`) {
      await json({
        schema_version: "pipeline-workspace/v1",
        recording_id: recordingId,
        video: {
          schema_version: "recording-video/v1",
          recording_id: recordingId,
          relative_path: `recordings/${recordingId}/video.mp4`,
          video_sha256: "a".repeat(64),
          byte_length: 1,
          duration_us: 20_000_000,
        },
        stages: [
          stage("events"),
          stage("visible_cards"),
          stage("visual_identities"),
          stage("table_observations"),
          analysisStage,
        ],
        diagnostics: [],
      });
      return;
    }
    if (path === `/api/recordings/${recordingId}/pipeline/lineage`) {
      await json(graph(false));
      return;
    }
    if (path === `/api/recordings/${recordingId}`) {
      await json({
        recording_id: recordingId,
        source: {},
        session_id: "session-analysis-fixture",
      });
      return;
    }
    if (path === `/v1/round-analyses/${analysisId}`) {
      await json({
        ...resolvedStatus,
        analysis_id: analysisId,
        recording_id: recordingId,
      });
      return;
    }
    if (path === `/v1/round-analyses/${analysisId}/timeline`) {
      await json(timeline);
      return;
    }
    if (path.includes("/derived-views/exact-event/")) {
      await route.fulfill({
        status: 200,
        contentType: "image/jpeg",
        body: FRAME_BYTES,
        headers: {
          "X-DokoDetector-Source-Sha256": "a".repeat(64),
          "X-DokoDetector-Frame-Index": "4",
          "X-DokoDetector-Frame-Width": "1",
          "X-DokoDetector-Frame-Height": "1",
          "X-DokoDetector-Requested-Time-Us":
            url.pathname.split("/").at(-1) ?? "0",
          "X-DokoDetector-Frame-Time-Us": url.pathname.split("/").at(-1) ?? "0",
          ETag: `"${"b".repeat(64)}"`,
        },
      });
      return;
    }
    if (path.includes("/repository-bundles/")) {
      await route.fulfill({ status: 200, contentType: "video/mp4", body: "" });
      return;
    }
    if (
      path.includes("/assets/") ||
      path.startsWith("/recordings/") ||
      path.startsWith("/src/") ||
      path.startsWith("/@vite/") ||
      path.startsWith("/@react-refresh") ||
      path.startsWith("/node_modules/") ||
      path === "/"
    ) {
      await route.continue();
      return;
    }
    await route.fulfill({ status: 404, body: `Unmocked route: ${path}` });
  });

  await page.goto(`/recordings/${recordingId}/pipeline/round_analyses`);
  await page
    .getByRole("button", { name: /round-analysis-fixture, 0:01/ })
    .first()
    .click();
  await expect(
    page.locator('[data-slot="center"] img[alt="Source frame"]'),
  ).toBeVisible();
  const playhead = page.getByLabel("Recording playhead");
  const scrubTime = Number(await playhead.inputValue());
  await playhead.focus();
  await playhead.press("ArrowRight");
  await expect(playhead).toHaveValue(String(scrubTime + 1_000));
  await playhead.press("ArrowLeft");
  await expect(playhead).toHaveValue(String(scrubTime));
  await expect(page.locator('[data-slot="center"] video')).toHaveCount(0);
  const evidence = page.getByRole("button", {
    name: /Evidence · observation-002/,
  });
  await evidence.click();
  await expect(page).toHaveURL(/t_us=2000000/);
  await expect(evidence).toHaveAttribute("aria-current", "true");
  await page.getByRole("button", { name: /Rank 2 ·/ }).click();
  await page.reload();
  await expect(page).toHaveURL(/analysis=analysis-workspace-1/);
  await expect(page).toHaveURL(/row=observation-002/);
  await expect(page).toHaveURL(/hypothesis=2/);
  await expect(page.getByRole("combobox", { name: "Hypothesis" })).toHaveValue(
    "2",
  );
  await expect(page.getByText(/result is ambiguous/i)).toBeVisible();
  await expect(page.getByLabel("Counterfactual draft")).toBeVisible();
  await page
    .getByRole("button", { name: /Evidence · observation-001/ })
    .click();
  await page
    .getByLabel("Correct classification for observation-001-card-01")
    .selectOption("CLUBS_NINE");
  const counterfactualAction = page.getByRole("button", {
    name: "Calculate counterfactual…",
  });
  await counterfactualAction.click();
  const launchDialog = page.getByRole("dialog");
  await expect(launchDialog.getByText(analysisId)).toBeVisible();
  await expect(
    launchDialog.getByText(timeline.artifact_hashes.input_sha256),
  ).toBeVisible();
  await expect(
    launchDialog.getByText(timeline.artifact_hashes.result_sha256),
  ).toBeVisible();
  await expect(launchDialog.getByText(/CLUBS_NINE/)).toBeVisible();
  await expect(page.getByLabel("Selected analysis row details")).toContainText(
    "observation-001",
  );
  await launchDialog.getByRole("button", { name: "Cancel" }).click();
  expect(counterfactualSubmission).toBeNull();
  await counterfactualAction.click();
  await page
    .getByRole("button", { name: "Start calculate counterfactual" })
    .click();
  await expect(
    page.getByRole("link", { name: "counterfactual-job" }),
  ).toBeVisible();
  expect(counterfactualSubmission).not.toBeNull();
  expect(counterfactualSubmission?.body.type).toBe("counterfactual");
  expect(counterfactualSubmission?.body.context).toEqual({
    analysis_id: analysisId,
  });
  const request = counterfactualSubmission?.body.request as Record<
    string,
    unknown
  >;
  expect(request.source_input_sha256).toBe(
    timeline.artifact_hashes.input_sha256,
  );
  expect(request.source_result_sha256).toBe(
    timeline.artifact_hashes.result_sha256,
  );
  expect(request.card_identity_overrides).toEqual([
    {
      observation_id: "observation-001",
      observed_card_id: "observation-001-card-01",
      card: "CLUBS_NINE",
    },
  ]);
  expect(counterfactualSubmission?.idempotencyKey).toBeTruthy();
  await expect(page).toHaveURL(/analysis=analysis-workspace-1/);
  await expect(page.locator('[data-slot="center"] button')).toHaveCount(0);
  await expect(page.locator('[data-slot="center"] video')).toHaveCount(0);
  await expect(page.locator('[data-slot="center"]')).toHaveText("");
});

test("exact run comparison uses two shared still-frame surfaces", async ({
  page,
}) => {
  const recordingId = "comparison-workspace-browser-fixture";
  const comparisonStage = stage("events") as unknown as PipelineWorkspaceStage;
  comparisonStage.state = "complete";
  comparisonStage.can_run = false;
  comparisonStage.input_options = [
    {
      revision_id: "reference-r1",
      node_id: "reference-node",
      node_revision_id: "reference-r1",
      is_current_head: true,
      content_type: "events",
      origin: "manual",
      completion_state: "complete",
      coverage_state: "full-recording",
      display_label: "Reviewed events",
      content_sha256: "e".repeat(64),
      input_revision_ids: [],
      producer: {},
      coverage: {},
      created_at: "2026-11-07T00:00:00Z",
    },
  ];
  comparisonStage.selected_completed_reference = {
    node_id: "reference-node",
    revision_id: "reference-r1",
  };
  comparisonStage.comparable_run_ids = ["run-left", "run-right"];
  comparisonStage.runs = ["run-left", "run-right"].map((runId) => ({
    run_id: runId,
    status: "complete",
    attempt: 1,
    request: {},
    state: {},
    input_revision_ids: ["events-r1"],
    implementation: { name: "fixture", version: "v1" },
    model: null,
    configuration: {},
    extraction_policy: {},
    crop_policy: null,
    output_revision_ids: [`${runId}-output`],
    created_at: "2026-11-07T00:00:00Z",
    started_at: null,
    completed_at: null,
    updated_at: "2026-11-07T00:00:00Z",
    progress: { completed: 1, total: 1 },
    failure: null,
    failed_item_count: 0,
  }));

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (value: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(value),
      });
    if (path === `/api/recordings/${recordingId}/pipeline`) {
      await json({
        schema_version: "pipeline-workspace/v1",
        recording_id: recordingId,
        video: {
          schema_version: "recording-video/v1",
          recording_id: recordingId,
          relative_path: `recordings/${recordingId}/video.mp4`,
          video_sha256: "a".repeat(64),
          byte_length: 1,
          duration_us: 20_000_000,
        },
        stages: [
          comparisonStage,
          stage("visible_cards"),
          stage("visual_identities"),
          stage("table_observations"),
          stage("round_analyses"),
        ],
        diagnostics: [],
      });
      return;
    }
    if (path === `/api/recordings/${recordingId}`) {
      await json({
        recording_id: recordingId,
        source: {},
        session_id: "session-compare",
      });
      return;
    }
    if (path.includes("/pipeline/comparisons")) {
      const request = route.request().postDataJSON() as {
        left_run_id: string;
        right_run_id: string;
      };
      await json({
        schema_version: "pipeline-comparison/v1",
        comparison_id: "comparison-browser-1",
        recording_id: recordingId,
        content_type: "events",
        mode: "paired_processor",
        algorithm_version: "pipeline-comparison.v2",
        left: {
          run_id: request.left_run_id,
          revision_id: `${request.left_run_id}-output`,
          status: "complete",
          input_revision_ids: ["events-r1"],
          content_sha256: "b".repeat(64),
          implementation: { name: "fixture", version: "v1" },
          model: null,
          configuration: {},
          extraction_policy: {},
          failure: null,
        },
        right: {
          run_id: request.right_run_id,
          revision_id: `${request.right_run_id}-output`,
          status: "complete",
          input_revision_ids: ["events-r1"],
          content_sha256: "c".repeat(64),
          implementation: { name: "fixture", version: "v1" },
          model: null,
          configuration: {},
          extraction_policy: {},
          failure: null,
        },
        reference: {
          revision_id: "reference-r1",
          input_revision_ids: [],
          content_sha256: "e".repeat(64),
          origin: "manual",
        },
        scope: {
          reviewed: [{ start_us: 0, end_us: 2_000_000 }],
          common_covered: [{ start_us: 0, end_us: 2_000_000 }],
          left_only: [],
          right_only: [],
          reviewed_frame_identities: [],
          common_frame_identities: [],
          left_only_frame_identities: [],
          right_only_frame_identities: [],
        },
        matching_policy: {
          policy_id: "event-timing/v1",
          kind: "event_timing",
          anchor: "start_us",
          tolerance_us: 50000,
        },
        counts: {
          left: {
            reference_events: 1,
            run_events: 1,
            matches: 0,
            misses: 1,
            extras: 0,
            failures: 0,
            not_reviewed: 0,
            unpaired_input: 0,
            neutralized_predictions: 0,
            ignored_regions: 0,
            ignored_pixels: 0,
          },
          right: {
            reference_events: 1,
            run_events: 1,
            matches: 0,
            misses: 1,
            extras: 0,
            failures: 0,
            not_reviewed: 0,
            unpaired_input: 0,
            neutralized_predictions: 0,
            ignored_regions: 0,
            ignored_pixels: 0,
          },
        },
        metrics: {
          left: {
            precision: null,
            recall: null,
            f1: null,
            mean_error_us: null,
            max_error_us: null,
          },
          right: {
            precision: null,
            recall: null,
            f1: null,
            mean_error_us: null,
            max_error_us: null,
          },
        },
        paired_delta: null,
        items: [
          {
            item_id: "comparison-item-1",
            side: "left",
            outcome: "miss",
            source_time_us: 1000000,
            event_type: "card_state_changed",
            reference_event_id: null,
            run_event_id: null,
            reference_event: null,
            run_event: null,
            delta_us: null,
            source_links: {
              derived_view: `/api/recordings/${recordingId}/pipeline/derived-views/exact-event/1000000`,
            },
            frame_identity: null,
            reference_frame_identity: null,
            run_frame_identity: null,
            reference_card_id: null,
            run_card_id: null,
            reference_card: null,
            run_card: null,
            iou: null,
            reference_identity: null,
            run_identity: null,
            reference_candidates: null,
            run_candidates: null,
          },
        ],
      });
      return;
    }
    if (path.includes("/derived-views/exact-event/")) {
      await route.fulfill({
        status: 200,
        contentType: "image/jpeg",
        body: FRAME_BYTES,
        headers: {
          "X-DokoDetector-Source-Sha256": "a".repeat(64),
          "X-DokoDetector-Frame-Index": "4",
          "X-DokoDetector-Frame-Width": "1",
          "X-DokoDetector-Frame-Height": "1",
          "X-DokoDetector-Requested-Time-Us": path.split("/").at(-1) ?? "0",
          "X-DokoDetector-Frame-Time-Us": path.split("/").at(-1) ?? "0",
          ETag: `"${"b".repeat(64)}"`,
        },
      });
      return;
    }
    if (
      path.startsWith("/recordings/") ||
      path === "/" ||
      path.includes("/assets/")
    )
      return route.continue();
    await route.fulfill({ status: 404, body: `Unmocked route: ${path}` });
  });

  await page.goto(`/recordings/${recordingId}/pipeline/events/compare`);
  await expect(
    page.getByRole("combobox", { name: "Left terminal run" }),
  ).toHaveValue("run-right");
  await page.getByRole("button", { name: /miss.*0:01/i }).click();
  const center = page.locator('[data-slot="center"]');
  await expect(center.locator("img[alt='Source frame']")).toHaveCount(2);
  await expect(center.locator("video")).toHaveCount(0);
  await expect(center.locator("button, input, select, textarea")).toHaveCount(
    0,
  );
  await expect(page.getByLabel("Selected comparison outcome")).toContainText(
    "comparison-item-1",
  );
});
