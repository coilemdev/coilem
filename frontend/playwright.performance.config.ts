/** Opt-in, real Standard-map acceptance; deliberately outside the routine suite. */
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const root = dirname(fileURLToPath(import.meta.url));
mkdirSync(join(root, 'test-results'), { recursive: true });
// Playwright also loads this config in workers; they must share the server's
// chosen directory instead of creating another, unused runtime.
if (!process.env.COILEM_ACCEPTANCE_RUNTIME) {
  const owned = mkdtempSync(join(root, 'test-results', 'performance-runtime-'));
  process.env.COILEM_ACCEPTANCE_RUNTIME = owned;
  process.env.COILEM_ACCEPTANCE_OWNED_RUNTIME = owned;
  writeFileSync(join(owned, '.acceptance-owned'), owned);
}
const runtime = process.env.COILEM_ACCEPTANCE_RUNTIME;
process.env.COILEM_ACCEPTANCE_RUNTIME = runtime;
const quote = (value: string) => process.platform === 'win32'
  ? `"${value.replaceAll('"', '""')}"` : `'${value.replaceAll("'", "'\\''")}'`;

export default defineConfig({
  testDir: './tests', testMatch: 'performance-acceptance.spec.ts',
  outputDir: './test-results/performance-acceptance',
  timeout: 120 * 60_000, expect: { timeout: 30_000 },
  workers: 1, retries: 0, fullyParallel: false,
  reporter: [['list'], ['json', { outputFile: 'test-results/performance-acceptance.json' }], ['./tests/performance-reporter.ts']],
  use: {
    baseURL: 'http://127.0.0.1:58010', actionTimeout: 60_000,
    navigationTimeout: 60_000, screenshot: 'only-on-failure',
    trace: { mode: 'retain-on-failure', screenshots: false, snapshots: true, sources: true },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: 'chromium', viewport: { width: 1753, height: 980 } } }],
  webServer: {
    command: `${quote(process.env.COILEM_TEST_PYTHON || 'python')} -m backend.launcher --port 58010 --no-browser`,
    cwd: resolve(root, '..'), url: 'http://127.0.0.1:58010/health',
    reuseExistingServer: false, timeout: 120_000,
    env: {
      COILEM_USER_DATA_ROOT: join(runtime, 'user-data'), COILEM_ENABLE_ELMER: '0',
      COILEM_BUILD_COMMIT: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: resolve(root, '..'), encoding: 'utf8' }).trim(),
      COILEM_SOLVE_CACHE_MAX_BYTES: '200000000', PYTHONUNBUFFERED: '1',
      COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS: '1',
      COILEM_MAGNETO2D_GMSH_SOLVE_WORKERS: '2',
      COILEM_MAGNETO2D_PER_ANGLE_SOLVER_WORKERS: '1',
      COILEM_MAGNETO2D_FIELD_PREVIEW_WORKERS: '1',
    },
  },
});
