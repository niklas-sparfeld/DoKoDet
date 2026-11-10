import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/head-proof",
  workers: 1,
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:4178", browserName: "chromium" },
  webServer: [
    {
      command:
        "../backend/.venv/bin/python ../backend/tests/head_proof_browser_server.py",
      url: "http://127.0.0.1:8766/v1/recordings",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        "VITE_API_PROXY_TARGET=http://127.0.0.1:8766 npm run dev -- --host 127.0.0.1 --port 4178 --strictPort",
      url: "http://127.0.0.1:4178",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
