/** Fast browser regressions for the acceptance harness; no backend or solves. */
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: 'performance-harness.spec.ts',
  outputDir: './test-results/performance-harness',
  workers: 1, retries: 0,
  use: { viewport: { width: 1000, height: 650 } },
});
