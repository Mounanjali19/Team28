import { defineConfig } from "@playwright/test";

// Runs against a running stack (./scripts/run.sh). Override with E2E_BASE_URL.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
});
