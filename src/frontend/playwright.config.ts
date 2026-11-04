// The Playwright end-to-end tests (e2e/). Run them with: npm run e2e
//
// The web server (e2e/serve.mjs) builds the frontend, copies a template database to a new database for the run,
// and starts "main.py serve" on port 8123 with the fake LLM and the fixed demo time (TRIAD_NOW).
// So each run starts from the same data, and it does not touch the database or the ports (8000, 5173) of dev.sh.
// The tests share one server and one database. So they run one at a time (workers: 1), in the order of the files.
//
// The tests take the screenshots of the journey. They go to test-results/screenshots/.
// "npm run e2e:screens" writes them to doc/screenshots/ (the report and the README use them).

import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.TRIAD_E2E_PORT ?? 8123);
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results/output',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    locale: 'en-US',
    timezoneId: 'America/New_York',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 },
    },
  ],
  webServer: {
    command: 'node e2e/serve.mjs',
    url: `${BASE_URL}/api/health`,
    env: { TRIAD_E2E_PORT: String(PORT) },
    reuseExistingServer: false,
    timeout: 300_000,
    stdout: 'ignore',
    stderr: 'pipe',
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
  },
});
