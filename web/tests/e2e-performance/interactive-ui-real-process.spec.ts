import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { writeFileSync } from "node:fs";
import { performance } from "node:perf_hooks";

const RECORDING_ID = "recording-both";
const IDENTITY_RECORDING_ID = RECORDING_ID;
const REVIEW_ITEMS = 4;
const RUNS = Number(process.env.UI_PERF_CONTEXTS ?? "10");
const OUT = process.env.UI_PERF_SAMPLE_OUTPUT;
if (!OUT) throw new Error("UI_PERF_SAMPLE_OUTPUT is required");

type RequestSample = {
  method: string;
  path: string;
  started_ms: number;
  duration_ms: number | null;
  status: number | null;
  failed: string | null;
  etag: string | null;
  cache_control: string | null;
  resource_type: string;
  range: string | null;
};

type BrowserSample = {
  scenario: string;
  iteration: number;
  browser_cache: "fresh-context" | "same-context-reload";
  server_derived_cache_mode: string | null;
  action_ms: number;
  request_count: number;
  api_request_count: number;
  duplicate_requests: Array<{ key: string; count: number }>;
  range_requests: number;
  range_response: {
    status: number;
    bytes: number;
    content_range: string | null;
  } | null;
  browser_cache_events: string[];
  aborted_requests: string[];
  errors: string[];
  requests: RequestSample[];
};

const samples: BrowserSample[] = [];

async function capture(
  browser: Browser,
  scenario: string,
  iteration: number,
  action: (page: Page, context: BrowserContext) => Promise<void>,
  cacheMode: BrowserSample["browser_cache"] = "fresh-context",
) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  const requests: RequestSample[] = [];
  const errors: string[] = [];
  const abortedRequests: string[] = [];
  const browserCacheEvents: string[] = [];
  const requestByObject = new Map<object, RequestSample>();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  cdp.on("Network.requestServedFromCache", (event) => {
    browserCacheEvents.push(`cache:${event.requestId}`);
  });
  cdp.on("Network.responseReceived", (event) => {
    if (event.response.fromDiskCache || event.response.fromServiceWorker) {
      browserCacheEvents.push(
        `response-cache:${new URL(event.response.url).pathname}`,
      );
    }
  });
  const started = performance.now();
  page.on("request", (request) => {
    const url = new URL(request.url());
    const row: RequestSample = {
      method: request.method(),
      path: `${url.pathname}${url.search}`,
      started_ms: performance.now() - started,
      duration_ms: null,
      status: null,
      failed: null,
      etag: null,
      cache_control: null,
      resource_type: request.resourceType(),
      range: request.headers()["range"] ?? null,
    };
    requests.push(row);
    requestByObject.set(request, row);
  });
  page.on("response", (response) => {
    const row = requestByObject.get(response.request());
    if (row) {
      row.status = response.status();
      row.etag = response.headers()["etag"] ?? null;
      row.cache_control = response.headers()["cache-control"] ?? null;
    }
    if (response.status() >= 400) {
      errors.push(
        `HTTP ${response.status()} ${new URL(response.url()).pathname}`,
      );
    }
  });
  page.on("requestfinished", async (request) => {
    const row = requestByObject.get(request);
    if (!row) return;
    const timing = request.timing();
    const end =
      timing.responseEnd >= 0 ? timing.responseEnd : timing.requestStart;
    row.duration_ms = Math.max(0, end - timing.requestStart);
  });
  page.on("requestfailed", (request) => {
    const row = requestByObject.get(request);
    const failure = request.failure()?.errorText ?? "request failed";
    if (row) row.failed = failure;
    const label = `${request.method()} ${new URL(request.url()).pathname}: ${failure}`;
    if (failure === "net::ERR_ABORTED") abortedRequests.push(label);
    else errors.push(label);
  });
  try {
    await action(page, context);
    const actionMs = performance.now() - started;
    const counts = new Map<string, number>();
    for (const row of requests) {
      const key = `${row.method} ${row.path}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const duplicateRequests = [...counts.entries()]
      .filter(([, count]) => count > 1)
      .map(([key, count]) => ({ key, count }));
    const sample: BrowserSample = {
      scenario,
      iteration,
      browser_cache: cacheMode,
      server_derived_cache_mode: await page.evaluate(() => {
        return (
          (window as unknown as { __m10ServerDerivedCacheMode?: string })
            .__m10ServerDerivedCacheMode ?? null
        );
      }),
      action_ms: actionMs,
      request_count: requests.length,
      api_request_count: requests.filter(
        (row) => row.path.startsWith("/api/") || row.path.startsWith("/v1/"),
      ).length,
      duplicate_requests: duplicateRequests,
      range_requests: requests.filter(
        (row) => row.range !== null && row.path.includes("/video"),
      ).length,
      range_response: await page
        .evaluate(() => {
          return (
            (
              window as unknown as {
                __m10RangeResponse?: {
                  status: number;
                  bytes: number;
                  contentRange: string | null;
                };
              }
            ).__m10RangeResponse ?? null
          );
        })
        .then((value) =>
          value === null
            ? null
            : {
                status: value.status,
                bytes: value.bytes,
                content_range: value.contentRange,
              },
        ),
      browser_cache_events: browserCacheEvents,
      aborted_requests: abortedRequests,
      errors,
      requests,
    };
    samples.push(sample);
    writeFileSync(
      OUT,
      JSON.stringify(
        { schema_version: "interactive-ui-browser-samples/v1", samples },
        null,
        2,
      ) + "\n",
    );
    expect(errors, `${scenario} browser/backend requests`).toEqual([]);
    expect(requests.length, `${scenario} request count`).toBeGreaterThan(0);
    return sample;
  } finally {
    await context.close();
  }
}

async function repeat(
  browser: Browser,
  scenario: string,
  action: (
    page: Page,
    context: BrowserContext,
    iteration: number,
  ) => Promise<void>,
) {
  for (let iteration = 0; iteration < RUNS; iteration += 1) {
    await capture(browser, scenario, iteration, (page, context) =>
      action(page, context, iteration),
    );
  }
}

async function openRecording(
  page: Page,
  recordingId = RECORDING_ID,
  stage = "events",
) {
  await page.goto(
    `/recordings/${encodeURIComponent(recordingId)}/pipeline/${stage}`,
  );
  await expect(
    page.getByRole("navigation", { name: "Recording pipeline steps" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("complementary", { name: "Workspace inspector" })
      .getByText(recordingId, { exact: true }),
  ).toBeVisible();
}

async function openIdentityRecording(page: Page) {
  await openRecording(page, IDENTITY_RECORDING_ID, "visual_identities");
  await page.getByRole("button", { name: "Show lineage" }).click();
  const identities = page
    .getByRole("region", { name: "Pipeline lineage" })
    .getByRole("region", { name: "Visual identities lineage" });
  const latest = identities
    .locator("article")
    .first()
    .getByRole("button")
    .first();
  await expect(latest).toBeVisible();
  await latest.click();
  await expect(latest).toHaveAttribute("aria-pressed", "true");
}

test("recordings list opens the exact recording workspace", async ({
  browser,
}) => {
  await repeat(browser, "recordings_to_workspace", async (page) => {
    await page.goto("/");
    const recording = page.locator(`a[href="/recordings/${RECORDING_ID}"]`);
    await expect(recording).toBeVisible();
    await recording.click();
    await expect(
      page.getByRole("navigation", { name: "Recording pipeline steps" }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("complementary", { name: "Workspace inspector" })
        .getByText(RECORDING_ID, { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Timeline Rail" }),
    ).toBeVisible();
    await expect(
      page.getByRole("complementary", { name: "Workspace inspector" }),
    ).toBeVisible();
  });
});

test("lineage revision switch displays the exact selected revision", async ({
  browser,
}) => {
  await repeat(browser, "displayed_revision_switch", async (page) => {
    await openRecording(page, IDENTITY_RECORDING_ID, "visual_identities");
    await page.getByRole("button", { name: "Show lineage" }).click();
    const lineage = page.getByRole("region", { name: "Pipeline lineage" });
    await expect(lineage).toBeVisible();
    const identityLineage = lineage.getByRole("region", {
      name: "Visual identities lineage",
    });
    const latest = identityLineage
      .locator("article")
      .first()
      .getByRole("button")
      .first();
    await expect(latest).toBeVisible();
    await latest.click();
    await expect(latest).toHaveAttribute("aria-pressed", "true");
    const prior = identityLineage
      .locator("article")
      .nth(1)
      .getByRole("button")
      .first();
    await expect(prior).toBeVisible();
    const revisionId = (await prior.textContent())?.trim().replace(/^r\s*/, "");
    expect(revisionId).toBeTruthy();
    await prior.click();
    await expect(page).toHaveURL(new RegExp(encodeURIComponent(revisionId!)));
    const selectedRevision = identityLineage.getByRole("button", {
      name: `r ${revisionId}`,
    });
    await expect(selectedRevision).toHaveAttribute("aria-pressed", "true");
    await expect(selectedRevision).toBeVisible();
  });
});

test("frame and crop navigation uses exact media identities and a bounded video range", async ({
  browser,
}) => {
  await repeat(browser, "frame_crop_navigation", async (page) => {
    await openIdentityRecording(page);
    const sourceFrame = page.getByRole("region", {
      name: "Visual identity source frame",
    });
    await expect(sourceFrame).toBeVisible();
    await expect(sourceFrame.locator("img").first()).toBeVisible({
      timeout: 30_000,
    });
    const crop = page.getByRole("region", { name: "Selected identity crop" });
    await expect(crop).toBeVisible();
    const cropImage = crop.locator("img");
    await expect(cropImage).toBeVisible({ timeout: 30_000 });
    const frameImage = sourceFrame.locator("img").first();
    const source = await frameImage.getAttribute("src");
    expect(source).toMatch(/^blob:/);
    await expect(page.getByText(/Frame \d+ · requested \d+ μs/)).toBeVisible();
    const cropSource = await cropImage.getAttribute("src");
    expect(cropSource).toContain("/derived-views/identity-crops/");
    const cropCardId = (await cropImage.getAttribute("alt"))?.replace(
      "Frozen processor input crop for ",
      "",
    );
    expect(cropCardId).toBeTruthy();
    const mediaRequests = await page.evaluate(() =>
      performance
        .getEntriesByType("resource")
        .map((entry) => new URL(entry.name).pathname),
    );
    expect(
      mediaRequests.some((path) =>
        path.includes("/derived-views/exact-event/"),
      ),
    ).toBe(true);
    expect(cropSource).toContain(cropCardId!);
    await page.evaluate(() => {
      (
        window as unknown as { __m10ServerDerivedCacheMode: string }
      ).__m10ServerDerivedCacheMode =
        "actual derived-image HTTP response ETag and cache-control retained; browser cache events reported separately";
    });
    const focusCrop = crop.getByRole("button", { name: "Focus crop" });
    await focusCrop.focus();
    await expect(focusCrop).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(
      crop.getByRole("button", { name: "Show all inspector sections" }),
    ).toBeVisible();
    const range = await page.evaluate(async (url) => {
      const response = await fetch(url, {
        headers: { Range: "bytes=0-65535" },
      });
      const body = await response.arrayBuffer();
      return {
        status: response.status,
        bytes: body.byteLength,
        contentRange: response.headers.get("content-range"),
      };
    }, `/v1/repository-bundles/${IDENTITY_RECORDING_ID}/video`);
    await page.evaluate((value) => {
      (
        window as unknown as {
          __m10RangeResponse: typeof value;
        }
      ).__m10RangeResponse = value;
    }, range);
    expect(range.status).toBe(206);
    expect(range.bytes).toBeGreaterThan(0);
    expect(range.bytes).toBeLessThanOrEqual(65_536);
    expect(range.contentRange).toMatch(/^bytes 0-\d+\/\d+$/);
  });
});

test("item review save is durable and visible after reload", async ({
  browser,
}) => {
  for (let iteration = 0; iteration < RUNS; iteration += 1) {
    await capture(
      browser,
      "review_save",
      iteration,
      async (page) => {
        await openIdentityRecording(page);
        const item = page
          .getByRole("navigation", { name: "Identity outcomes" })
          .getByRole("button")
          .nth(iteration % REVIEW_ITEMS);
        await expect(item).toBeVisible();
        await item.press("Enter", { timeout: 5_000 });
        const decision = page.getByRole("button", { name: "Accept identity" });
        await expect(decision).toBeVisible();
        await decision.press("Enter", { timeout: 5_000 });
        await expect(
          page.getByText("Item review: accepted", { exact: true }),
        ).toBeVisible();
        const selected = await item.getAttribute("aria-pressed");
        expect(selected).toBe("true");
        await page.reload();
        await expect(
          page.getByRole("region", { name: "Visual identity data" }),
        ).toBeVisible();
        await expect(
          page.getByText("Item review: accepted", { exact: true }),
        ).toBeVisible();
      },
      "same-context-reload",
    );
  }
});

test("Jobs drawer and history show real persisted job identities", async ({
  browser,
}) => {
  await repeat(browser, "jobs_drawer_history", async (page) => {
    await page.goto("/jobs");
    await page.getByRole("button", { name: "History" }).press("Enter");
    const historyJob = page
      .getByRole("link", { name: "Classify visual identities" })
      .first();
    await expect(historyJob).toBeVisible();
    const href = await historyJob.getAttribute("href");
    expect(href).toMatch(/^\/jobs\//);
    const jobId = href!.split("/").at(-1)!;
    await historyJob.click();
    await expect(page).toHaveURL(/\/jobs\//);
    await expect(
      page.getByRole("heading", { name: "Classify visual identities" }),
    ).toBeVisible();
    await page.goto(`/recordings/${RECORDING_ID}`);
    const toggle = page.getByRole("button", { name: /Jobs/ });
    await expect(toggle).toBeVisible();
    await toggle.press("Enter");
    const drawer = page.getByRole("complementary", { name: "Jobs" });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("button", { name: "History" }).press("Enter");
    const drawerJob = drawer
      .getByRole("link", {
        name: "Classify visual identities",
      })
      .first();
    await expect(drawerJob).toHaveAttribute("href", `/jobs/${jobId}`);
  });
});

test("job submission reaches visible status through the real worker", async ({
  browser,
}) => {
  await repeat(browser, "job_submission_visible_status", async (page) => {
    await openRecording(page, RECORDING_ID, "events");
    await page.getByRole("button", { name: "Detect events…" }).click();
    const dialog = page.getByRole("dialog", { name: "Detect events" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Start detect events" }).click();
    await expect(page.getByRole("link", { name: /^View job / })).toBeVisible();
    const submission = page.getByRole("link", { name: /^View job / });
    const href = await submission.getAttribute("href");
    expect(href).toMatch(/^\/jobs\//);
    const jobId = href!.split("/").at(-1)!;
    const detail = await page.evaluate(async (path) => {
      const deadline = performance.now() + 30_000;
      while (performance.now() < deadline) {
        const response = await fetch(path);
        if (!response.ok) throw new Error(`job detail ${response.status}`);
        const job = await response.json();
        if (job.state === "succeeded") return job;
        if (["failed", "cancelled", "interrupted"].includes(job.state)) {
          throw new Error(`submitted job entered ${job.state}`);
        }
        await new Promise((resolve) => window.setTimeout(resolve, 50));
      }
      throw new Error("submitted job status timed out");
    }, `/api/jobs/${jobId}`);
    expect(detail.id).toBe(jobId);
    expect(detail.state).toBe("succeeded");
    await page.goto(`/jobs/${jobId}`);
    await expect(
      page.getByRole("heading", { name: "Detect card events" }),
    ).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "succeeded" }),
    ).toBeVisible();
  });
});

test("bounded polling and deterministic work coexist with reads, writes and media", async ({
  browser,
}) => {
  for (let iteration = 0; iteration < RUNS; iteration += 1) {
    await capture(browser, "controlled_load", iteration, async (page) => {
      await openRecording(page, RECORDING_ID, "events");
      await page.getByRole("button", { name: "Detect events…" }).click();
      const dialog = page.getByRole("dialog", { name: "Detect events" });
      await dialog.getByRole("button", { name: "Start detect events" }).click();
      const jobLink = page.getByRole("link", { name: /^View job / });
      await expect(jobLink).toBeVisible();
      const jobId = (await jobLink.getAttribute("href"))!.split("/").at(-1)!;
      await page.goto(
        `/recordings/${IDENTITY_RECORDING_ID}/pipeline/visual_identities`,
      );
      await page.getByRole("button", { name: "Show lineage" }).click();
      const identities = page
        .getByRole("region", { name: "Pipeline lineage" })
        .getByRole("region", { name: "Visual identities lineage" });
      const latest = identities
        .locator("article")
        .first()
        .getByRole("button")
        .first();
      await latest.click();
      await page.evaluate(() => {
        const state = {
          active: true,
          inFlight: false,
          count: 0,
          failures: [] as string[],
          timer: 0,
        };
        const poll = async () => {
          if (!state.active || state.inFlight) return;
          state.inFlight = true;
          state.count += 1;
          try {
            const response = await fetch("/api/jobs?scope=active&limit=20");
            if (!response.ok) state.failures.push(`poll ${response.status}`);
            await response.json();
          } catch (error) {
            state.failures.push(String(error));
          } finally {
            state.inFlight = false;
          }
        };
        state.timer = window.setInterval(() => void poll(), 100);
        (window as unknown as { __m10Polling: typeof state }).__m10Polling =
          state;
      });
      const item = page
        .getByRole("navigation", { name: "Identity outcomes" })
        .getByRole("button")
        .nth((RUNS + iteration) % REVIEW_ITEMS);
      await item.press("Enter", { timeout: 5_000 });
      await expect(
        page.getByRole("button", { name: "Accept identity" }),
      ).toBeVisible();
      const acceptIdentity = page.getByRole("button", {
        name: "Accept identity",
      });
      await acceptIdentity.press("Enter", { timeout: 5_000 });
      await expect(
        page.getByText("Item review: accepted", { exact: true }),
      ).toBeVisible();
      await page.evaluate(async (url) => {
        const response = await fetch(url, {
          headers: { Range: "bytes=0-65535" },
        });
        const bytes = await response.arrayBuffer();
        const rangeResponse = {
          status: response.status,
          bytes: bytes.byteLength,
          contentRange: response.headers.get("content-range"),
        };
        (
          window as unknown as {
            __m10RangeResponse: typeof rangeResponse;
          }
        ).__m10RangeResponse = rangeResponse;
        if (response.status !== 206 || bytes.byteLength > 65_536)
          throw new Error("video range failed");
      }, `/v1/repository-bundles/${IDENTITY_RECORDING_ID}/video`);
      await page.evaluate(() =>
        fetch("/api/jobs?scope=history&limit=20").then((response) => {
          if (!response.ok) throw new Error(`history ${response.status}`);
          return response.json();
        }),
      );
      await page.evaluate(
        (recordingId) =>
          fetch(`/api/recordings/${recordingId}/pipeline?stage=events`).then(
            (response) => {
              if (!response.ok) throw new Error(`workspace ${response.status}`);
              return response.json();
            },
          ),
        RECORDING_ID,
      );
      await page.evaluate(async (path) => {
        const deadline = performance.now() + 30_000;
        while (performance.now() < deadline) {
          const response = await fetch(path);
          if (!response.ok) throw new Error(`job status ${response.status}`);
          const job = await response.json();
          if (job.state === "succeeded") return;
          if (["failed", "cancelled", "interrupted"].includes(job.state)) {
            throw new Error(`background job entered ${job.state}`);
          }
          await new Promise((resolve) => window.setTimeout(resolve, 50));
        }
        throw new Error("background job status timed out");
      }, `/api/jobs/${jobId}`);
      await page.evaluate(() => {
        const state = (
          window as unknown as {
            __m10Polling?: {
              active: boolean;
              timer: number;
              count: number;
              failures: string[];
            };
          }
        ).__m10Polling;
        if (state) {
          state.active = false;
          window.clearInterval(state.timer);
        }
      });
      await page.evaluate(async () => {
        const state = (
          window as unknown as { __m10Polling?: { inFlight: boolean } }
        ).__m10Polling;
        const deadline = performance.now() + 5_000;
        while (state?.inFlight && performance.now() < deadline) {
          await new Promise((resolve) => window.setTimeout(resolve, 10));
        }
        if (state?.inFlight)
          throw new Error("bounded polling request did not finish");
      });
      const pollSummary = await page.evaluate(() => {
        const state = (
          window as unknown as {
            __m10Polling?: { count: number; failures: string[] };
          }
        ).__m10Polling;
        return { count: state?.count ?? 0, failures: state?.failures ?? [] };
      });
      expect(pollSummary.failures).toEqual([]);
      expect(pollSummary.count).toBeGreaterThan(0);
    });
  }
});
