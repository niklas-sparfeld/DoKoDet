import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/recording-folder",
  workers: 1,
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:4179", browserName: "chromium" },
  webServer: [
    {
      command:
        "../backend/.venv/bin/python ../backend/tests/recording_folder_browser_server.py",
      url: "http://127.0.0.1:8767/v1/recordings",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        "VITE_API_PROXY_TARGET=http://127.0.0.1:8767 npm run dev -- --host 127.0.0.1 --port 4179 --strictPort",
      url: "http://127.0.0.1:4179",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
