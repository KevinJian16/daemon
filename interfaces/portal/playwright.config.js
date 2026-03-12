import { defineConfig } from "@playwright/test";

const repoRoot = "/Users/kevinjian/daemon";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8002",
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    viewport: { width: 1440, height: 1100 },
  },
  webServer: {
    command:
      "bash -lc 'cd /Users/kevinjian/daemon/interfaces/portal && npm run build && cd /Users/kevinjian/daemon && python3 interfaces/portal/scripts/reset_portal_fixture.py && /Users/kevinjian/daemon/.venv/bin/uvicorn services.api:create_app --factory --host 127.0.0.1 --port 8002 --log-level warning'",
    url: "http://127.0.0.1:8002/portal/",
    cwd: repoRoot,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
