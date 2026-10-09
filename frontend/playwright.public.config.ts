import { mkdirSync, mkdtempSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const frontendRoot = dirname(fileURLToPath(import.meta.url));
const testResults = join(frontendRoot, 'test-results');
mkdirSync(testResults, { recursive: true });
const runtimeRoot = mkdtempSync(join(testResults, 'public-runtime-'));
const apiUrl = 'http://127.0.0.1:58000';
const uiUrl = 'http://127.0.0.1:54173';

function shellQuote(value: string): string {
  return process.platform === 'win32'
    ? `"${value.replaceAll('"', '""')}"`
    : `'${value.replaceAll("'", "'\\''")}'`;
}

export default defineConfig({
  testDir: './tests',
  testMatch: 'public-release.spec.ts',
  outputDir: './test-results/public-release',
  timeout: 15 * 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
    ['json', { outputFile: 'test-results/public-release.json' }],
  ],
  use: {
    baseURL: uiUrl,
    actionTimeout: 60_000,
    navigationTimeout: 60_000,
    // Continuous trace screenshots force ReadPixels on every animated WebGL
    // frame and stall software-rendered CI. Keep DOM/network traces and the
    // explicit landing/failure screenshots without continuous pixel readbacks.
    trace: { mode: 'retain-on-failure', screenshots: false, snapshots: true, sources: true },
    screenshot: 'only-on-failure',
  },
  // Exercise the full Chromium headless browser used by current Chrome, rather
  // than the separate headless shell, for the interactive WebGL landing page.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: 'chromium', viewport: { width: 1753, height: 980 } } }],
  webServer: [
    {
      command: `${shellQuote(process.env.COILEM_TEST_PYTHON || 'python')} -m uvicorn backend.public_main:app --host 127.0.0.1 --port 58000`,
      cwd: resolve(frontendRoot, '..'),
      url: `${apiUrl}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        COILEM_LOCAL_UI_ORIGIN: uiUrl,
        COILEM_USER_DATA_ROOT: join(runtimeRoot, 'user-data'),
        COILEM_ENABLE_ELMER: '0',
        PYTHONUNBUFFERED: '1',
      },
    },
    {
      command: `${shellQuote(process.execPath)} node_modules/vite/bin/vite.js --config vite.public.config.ts --host 127.0.0.1 --port 54173 --strictPort`,
      cwd: frontendRoot,
      url: uiUrl,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_COILEM_LOCAL_API_BASE: apiUrl },
    },
  ],
});
