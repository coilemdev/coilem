/** Real local release rehearsal. Requires the documented Python and Rust setup. */
import { mkdir, open, readFile, stat } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

const apiUrl = 'http://127.0.0.1:58000';
const landingScreenshot = fileURLToPath(new URL('../test-results/landing-page.png', import.meta.url));
type Excitation = 'sinusoidal' | 'ideal_six_step_120';
type RunRecord = { project_slug: string; run_id: string; status: string };

async function runList(page: Page): Promise<RunRecord[]> {
  const response = await page.request.get(`${apiUrl}/runs`);
  expect(response.ok()).toBe(true);
  return (await response.json()).runs as RunRecord[];
}

async function downloadReports(page: Page, info: TestInfo, mode: Excitation): Promise<void> {
  for (const [label, extension, signature] of [
    ['Download PDF', 'pdf', '%PDF-'],
    ['Download CSV', 'csv', 'report_schema,'],
    ['Save replayable run package', 'zip', 'PK'],
  ]) {
    const pendingDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: label, exact: true }).click();
    const download = await pendingDownload;
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${extension}$`));
    const output = info.outputPath(`${mode}.${extension}`);
    await download.saveAs(output);
    expect((await stat(output)).size).toBeGreaterThan(0);
    const file = await open(output, 'r');
    try {
      const { buffer, bytesRead } = await file.read(Buffer.alloc(signature.length), 0, signature.length, 0);
      expect(bytesRead).toBe(signature.length);
      expect(buffer.toString()).toBe(signature);
    } finally {
      await file.close();
    }
  }
}

async function solveStandard(page: Page, mode: Excitation): Promise<void> {
  const standard = page.getByRole('button', { name: /Standard.*Medium mesh/ });
  await standard.click();
  await expect(standard).toHaveAttribute('aria-pressed', 'true');
  const runButton = page.getByRole('button', { name: '▶ Run analysis', exact: true });
  await expect(runButton).toBeEnabled({ timeout: 120_000 });
  const submitted = page.waitForRequest((request) => (
    request.method() === 'POST' && new URL(request.url()).pathname === '/solve/stream'
  ));
  await runButton.click();
  const body = (await submitted).postDataJSON();
  expect(body.config.solve_params.solve_quality).toBe('standard');
  expect(body.config.solve_params.excitation_mode).toBe(mode);
  expect(body.config.solve_params.current_amplitude_convention).toBe(mode === 'sinusoidal' ? 'rms' : 'plateau');
  await expect(page.getByRole('region', { name: 'Completed solver results' })).toBeVisible({ timeout: 600_000 });
  await expect(page.getByRole('button', { name: 'Full results →', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Full results →', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Electromagnetic performance', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Saved solve run' })).toBeVisible();
  for (const tabName of ['Back EMF', 'Torque']) {
    const tab = page.getByRole('tab', { name: tabName, exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
  }
}

test.describe('public developer preview release rehearsal', () => {
  test.describe.configure({ mode: 'serial' });

  test('rejects an untrusted-origin simple cancel POST before a solve exists', async ({ request }) => {
    const before = await request.get(`${apiUrl}/runs`);
    expect(before.ok()).toBe(true);
    expect((await before.json()).runs).toEqual([]);
    const response = await request.post(`${apiUrl}/solve/cancel`, {
      headers: { Origin: 'http://localhost:54174', 'Content-Type': 'text/plain' },
      data: '',
    });
    expect(response.status()).toBe(403);
    expect((await response.json()).detail.error_code).toBe('UNTRUSTED_ORIGIN');
    expect(response.headers()['access-control-allow-origin']).toBeUndefined();
    const after = await request.get(`${apiUrl}/runs`);
    expect((await after.json()).runs).toEqual([]);
  });

  test('reopens a design, completes Standard sine and six-step runs, exports and compares them, then cancels safely', async ({ page }, info) => {
    // Both real Standard solves and their exports share this scenario's budget.
    // Allow their combined duration on the two-core CI runner.
    test.setTimeout(30 * 60_000);
    const pageErrors: string[] = [];
    const duplicateKeyWarnings: string[] = [];
    const nonLocalRequests: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (/same key|unique ["']key["']/i.test(message.text())) duplicateKeyWarnings.push(message.text());
    });
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (!['blob:', 'data:'].includes(url.protocol) && !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) {
        nonLocalRequests.push(request.url());
      }
    });
    // Exercise the supported download fallback instead of an operating-system picker.
    await page.addInitScript(() => {
      Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined });
    });
    await test.step('capture the public landing page and reopen a saved example', async () => {
      await page.goto('/');
      await expect(page.getByRole('status').filter({ hasText: 'Local: ready' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Use Example Motor', exact: true })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await mkdir(dirname(landingScreenshot), { recursive: true });
      await page.screenshot({ path: landingScreenshot, animations: 'disabled' });
      await info.attach('public-landing-page', { path: landingScreenshot, contentType: 'image/png' });
      await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
      await expect(page.getByRole('navigation', { name: 'Motor workflow' })).toBeVisible();
      await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
      const pendingDownload = page.waitForEvent('download');
      await page.getByRole('menuitem', { name: 'Save design file (.openem)', exact: true }).click();
      const download = await pendingDownload;
      expect(download.suggestedFilename()).toMatch(/\.openem$/);
      const savedDesign = info.outputPath('example.openem');
      await download.saveAs(savedDesign);
      const saved = JSON.parse(await readFile(savedDesign, 'utf-8'));
      expect(saved.topology).toBe('SPM');
      await page.locator('input[type="file"][accept*=".openem"]').setInputFiles(savedDesign);
      await expect(page.locator('.project-name')).toHaveText(saved.name);
      await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
      await expect(page.getByRole('radio', { name: /Elmer FEM/ })).toHaveCount(0);
    });

    await test.step('solve the sinusoidal example at Standard quality and download its reports', async () => {
      await expect(page.getByRole('radio', { name: /Sinusoidal/ })).toHaveAttribute('aria-checked', 'true');
      await solveStandard(page, 'sinusoidal');
      await expect(page.locator('.public-report-provenance')).toContainText('Sinusoidal');
      await downloadReports(page, info, 'sinusoidal');
    });

    await test.step('replay inputs and solve ideal six-step at Standard quality', async () => {
      // Keep the debounced preview in flight while checking that replay controls
      // remain usable. A background preview must not claim the operation lock.
      let releasePreview!: () => void;
      let previewStarted!: () => void;
      const previewReleased = new Promise<void>((resolve) => { releasePreview = resolve; });
      const pendingPreview = new Promise<void>((resolve) => { previewStarted = resolve; });
      await page.route('**/preview', async (route) => {
        previewStarted();
        await previewReleased;
        await route.continue();
      }, { times: 1 });
      try {
        await page.getByRole('button', { name: 'Rerun settings', exact: true }).click();
        await pendingPreview;
        await expect(page.getByRole('button', { name: /Standard.*Medium mesh/ })).toBeEnabled();
      } finally {
        releasePreview();
      }
      await expect(page.getByRole('status').filter({ hasText: /settings restored/ })).toBeVisible();
      await expect(page.getByRole('navigation', { name: 'Motor workflow' }).getByRole('button', { name: /Results$/ })).toBeDisabled();
      await page.getByRole('radio', { name: /Ideal six-step/ }).click();
      await expect(page.getByLabel(/Conducting phase current/)).toBeVisible();
      await solveStandard(page, 'ideal_six_step_120');
      const command = page.getByRole('region', { name: 'Ideal six-step command states' });
      await expect(command).toBeVisible();
      await expect(command.locator('li > strong')).toHaveText(['S1', 'S2', 'S3', 'S4', 'S5', 'S6']);
      await expect(page.locator('.public-report-provenance')).toContainText('Ideal six-step (120°)');
      await downloadReports(page, info, 'ideal_six_step_120');
    });

    const completed = (await runList(page)).filter((run) => run.status === 'complete');
    expect(completed).toHaveLength(2);
    const savedModes: string[] = [];
    for (const run of completed) {
      const response = await page.request.get(`${apiUrl}/runs/${run.project_slug}/${run.run_id}`);
      expect(response.ok()).toBe(true);
      const stored = await response.json();
      expect(stored.integrity.valid).toBe(true);
      expect(stored.request.resolved_config.solve_params.solve_quality).toBe('standard');
      savedModes.push(stored.request.resolved_config.solve_params.excitation_mode);
      expect(Number.isFinite(stored.result.summary.avg_torque_Nm)).toBe(true);
      expect(stored.result.torque_waveform.electrical_angle_deg.length).toBeGreaterThan(2);
      await info.attach(`summary-${stored.request.resolved_config.solve_params.excitation_mode}`, {
        body: JSON.stringify({ summary: stored.result.summary, solve_metadata: stored.result.solve_metadata }, null, 2),
        contentType: 'application/json',
      });
    }
    expect(savedModes.sort()).toEqual(['ideal_six_step_120', 'sinusoidal']);

    await test.step('navigate saved-run comparison and history', async () => {
      await page.getByRole('button', { name: 'Compare runs', exact: true }).click();
      await expect(page.getByText('Descriptive run comparison', { exact: true })).toBeVisible();
      await expect(page.locator('[aria-label="Run comparison metric differences"]')).toBeVisible();
      await page.getByRole('tab', { name: 'Back EMF overlay', exact: true }).click();
      await page.getByRole('button', { name: 'Previous runs', exact: true }).click();
      const history = page.getByRole('dialog', { name: 'Previous runs' });
      await expect(history.getByRole('region', { name: 'Local run storage' })).toContainText('used');
      await expect(history.getByLabel('Run A · baseline').locator('option')).toHaveCount(2);
      await page.getByRole('button', { name: 'Close previous runs', exact: true }).click();
      await page.getByRole('button', { name: '← Back to Solve', exact: true }).click();
    });

    await test.step('cancel a later run while preserving both completed records', async () => {
      const runButton = page.getByRole('button', { name: 'Run again', exact: true });
      await expect(runButton).toBeEnabled();
      const started = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/solve/stream');
      await runButton.click();
      expect((await started).ok()).toBe(true);
      await page.getByRole('button', { name: '■ Cancel solve', exact: true }).click();
      await expect(page.getByText('Analysis canceled. The previous completed result is still available.', { exact: true })).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole('region', { name: 'Completed solver results' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Full results →', exact: true })).toBeVisible();
      const retained = (await runList(page)).filter((run) => run.status === 'complete');
      expect(retained.map((run) => run.run_id).sort()).toEqual(completed.map((run) => run.run_id).sort());
      for (const run of retained) {
        const response = await page.request.get(`${apiUrl}/runs/${run.project_slug}/${run.run_id}`);
        expect((await response.json()).integrity.valid).toBe(true);
      }
    });
    expect(nonLocalRequests).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(duplicateKeyWarnings).toEqual([]);
  });
});
