import { defineConfig, devices } from "@playwright/test";

const port = process.env.E2E_WEB_PORT || "3107";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  workers: 2,
  timeout: 45000,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "line",
  use: { baseURL: `http://localhost:${port}`, trace: "retain-on-failure" },
  webServer: {
    command: `env -u NO_COLOR NEXT_DIST_DIR=.next-e2e pnpm dev --hostname 127.0.0.1 --port ${port}`,
    url: `http://localhost:${port}/calendar`,
    reuseExistingServer: false,
    timeout: 120000,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], browserName: "chromium" } },
    { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium" } },
  ],
});
