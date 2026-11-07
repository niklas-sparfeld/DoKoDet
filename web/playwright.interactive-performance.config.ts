import { defineConfig } from "@playwright/test";

const baseURL = process.env.UI_PERF_WEB_URL;
if (!baseURL) throw new Error("UI_PERF_WEB_URL is required for this suite");

export default defineConfig({
  testDir: "./tests/e2e-performance",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: "line",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    browserName: "chromium",
  },
});
