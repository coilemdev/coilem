/** Real local release rehearsal. Requires the documented Python and Rust setup. */
import { mkdir, open, readFile, stat } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { checkPerformanceRegressions } from './performance-regressions';

const apiUrl = 'http://127.0.0.1:58000';
const landingScreenshot = fileURLToPath(new URL('../test-results/landing-page.png', import.meta.url));
type Excitation = 'sinusoidal' | 'ideal_six_step_120';
type RunRecord = { project_slug: string; run_id: string; status: string };

async function runList(page: Page): Promise<RunRecord[]> {
  // Long solves can leave an idle keep-alive socket closed by the server.
  // Retry only ECONNRESET on read-only requests; HTTP errors still fail below.
  const response = await page.request.get(`${apiUrl}/runs`, { maxRetries: 2 });
  expect(response.ok()).toBe(true);
  return (await response.json()).runs as RunRecord[];
}

async function openMoreRunActions(page: Page): Promise<void> {
  const more = page.getByRole('button', { name: 'More ▾', exact: true });
  if ((await more.getAttribute('aria-expanded')) !== 'true') await more.click();
  await expect(page.getByRole('group', { name: 'More run actions' })).toBeVisible();
}

// The Solve setup shows one section at a time; open the one whose controls come next.
async function openSetupSection(page: Page, section: 'operating' | 'analysis' | 'plan'): Promise<void> {
  const header = page.locator(`button[aria-controls="param-group-content-${section}"]`);
  if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
  await expect(header).toHaveAttribute('aria-expanded', 'true');
}

async function downloadReports(page: Page, info: TestInfo, mode: Excitation): Promise<void> {
  for (const [label, extension, signature] of [
    ['Download PDF', 'pdf', '%PDF-'],
    ['Download CSV', 'csv', 'report_schema,'],
    ['Save replayable run package', 'zip', 'PK'],
  ]) {
    // Download PDF sits in the saved bar; the other exports are under More (#99).
    if (label !== 'Download PDF') await openMoreRunActions(page);
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
  await openSetupSection(page, 'plan');
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
  // The starter SPM 8p/12s is a qualified combination under the FEMM v3 benchmark report.
  await expect(page.locator('.public-report-stage').getByRole('note', { name: 'Benchmark qualification' })).toContainText(/Qualified|Experimental|Benchmark Qualification Pending/);
  for (const tabName of ['Back EMF', 'Torque']) {
    const tab = page.getByRole('tab', { name: tabName, exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
  }
}

test('switches to Elmer with cogging enabled without submitting the unsupported option', async ({ page }) => {
  // Exercise the browser's selection, validation and solve paths without an
  // external Elmer installation or a field solve. Geometry and mesh use the real API.
  await page.route('**/health', async (route) => {
    const response = await route.fetch();
    const health = await response.json();
    health.capabilities.elmer = {
      feature_enabled: true, available: true, qualified: true, adapter_ready: true,
      solver_version: '26.2', grid_version: '26.2',
    };
    await route.fulfill({ response, json: health });
  });
  await page.route('**/solve/validate', async (route) => {
    const body = route.request().postDataJSON();
    if (body.solver !== 'elmer') return route.continue();
    if (body.config.solve_options.cogging_torque) {
      return route.fulfill({ status: 400, json: { detail: { message: 'Cogging torque is solved by Magneto2D only.' } } });
    }
    // Use real input validation for the normalized request; only the runtime
    // capability is simulated in this browser regression.
    const response = await route.fetch({ postData: { ...body, solver: 'magneto2d' } });
    await route.fulfill({ response });
  });
  await page.route('**/solve/stream', (route) => route.fulfill({
    contentType: 'text/event-stream',
    body: 'event: error\ndata: {"message":"Cogging regression finished before solving."}\n\n',
  }));
  await page.goto('/');
  await expect(page.getByRole('status', { name: 'Local backend: ready', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await openSetupSection(page, 'analysis');
  const cogging = page.getByRole('checkbox', { name: 'Cogging torque', exact: true });
  await cogging.check();
  await expect(cogging).toBeChecked();
  await page.locator('button[aria-controls="param-group-content-solver"]').click();
  const validated = page.waitForResponse((response) => (
    response.url().endsWith('/solve/validate') && response.request().postDataJSON()?.solver === 'elmer'
  ));
  await page.getByRole('radio', { name: /Elmer FEM/ }).click();
  const response = await validated;
  expect(response.request().postDataJSON().config.solve_options.cogging_torque).toBe(false);
  expect(response.ok()).toBe(true);
  await openSetupSection(page, 'analysis');
  await expect(cogging).toBeDisabled();
  await expect(cogging).not.toBeChecked();
  const run = page.getByRole('button', { name: '▶ Run analysis', exact: true });
  await expect(run).toBeEnabled();
  const submitted = page.waitForRequest((request) => request.url().endsWith('/solve/stream'));
  await run.click();
  const body = (await submitted).postDataJSON();
  expect(body.solver).toBe('elmer');
  expect(body.config.solve_options.cogging_torque).toBe(false);
  await expect(page.getByRole('alert')).toContainText('Cogging regression finished before solving.');
  await page.locator('button[aria-controls="param-group-content-solver"]').click();
  await page.getByRole('radio', { name: /Magneto2D/ }).click();
  await openSetupSection(page, 'analysis');
  await expect(cogging).toBeChecked();
});

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

  test('loads every bundled example as the geometry its file describes', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('status', { name: 'Local backend: ready', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
    // The files define no tooth shoes, so none may be inherited from the starter motor.
    for (const [label, slots] of [['IPM 10p V-shape', 12], ['IPM 14p flat buried', 18], ['SPM 24p', 27], ['SPM 6p/36s', 36]] as const) {
      await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
      await page.getByRole('menuitem', { name: 'Examples', exact: true }).hover();
      const previewed = page.waitForResponse((response) => (
        response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/preview'
        && response.request().postDataJSON()?.stator?.slot_count === slots
      ));
      await page.getByRole('menuitem', { name: new RegExp(`^${label}`) }).click();
      const response = await previewed;
      expect(response.status(), `${label}: ${await response.text()}`).toBe(200);
      expect(response.request().postDataJSON().stator.tooth_shoe_enabled, label).toBe(false);
      await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
    }
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
      await expect(page.getByRole('status', { name: 'Local backend: ready', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Use Example Motor', exact: true })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await mkdir(dirname(landingScreenshot), { recursive: true });
      await page.screenshot({ path: landingScreenshot, animations: 'disabled' });
      await info.attach('public-landing-page', { path: landingScreenshot, contentType: 'image/png' });
      await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
      await expect(page.getByRole('navigation', { name: 'Motor workflow' })).toBeVisible();
      await expect(page.getByText(/^((Qualified|Experimental) motor combination|Benchmark Qualification Pending)$/)).toBeVisible();
      await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
      // A mouse click on Examples hovers it first; the submenu must stay open.
      await page.getByRole('menuitem', { name: 'Examples', exact: true }).click();
      await expect(page.getByRole('menu', { name: 'Example designs', exact: true })).toBeVisible();
      const pendingDownload = page.waitForEvent('download');
      await page.getByRole('menuitem', { name: 'Save design file (.coilem)', exact: true }).click();
      const download = await pendingDownload;
      expect(download.suggestedFilename()).toMatch(/\.coilem$/);
      const savedDesign = info.outputPath('example.coilem');
      await download.saveAs(savedDesign);
      const saved = JSON.parse(await readFile(savedDesign, 'utf-8'));
      expect(saved.topology).toBe('SPM');
      const designInput = page.locator('input[type="file"][accept*=".coilem"]');
      await designInput.setInputFiles(savedDesign);
      await expect(page.locator('.project-name')).toHaveText(saved.name);
      await designInput.setInputFiles({ name: 'example.openem', mimeType: 'application/json', buffer: await readFile(savedDesign) });
      await expect(page.locator('.project-name')).toHaveText(saved.name);
      await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
      await expect(page.getByRole('radio', { name: /Elmer FEM/ })).toHaveCount(0);
    });

    await test.step('solve the sinusoidal example at Standard quality and download its reports', async () => {
      await openSetupSection(page, 'operating');
      await expect(page.getByRole('radio', { name: /Sinusoidal/ })).toHaveAttribute('aria-checked', 'true');
      await solveStandard(page, 'sinusoidal');
      await expect(page.locator('.public-report-provenance')).toContainText('Sinusoidal');
      await downloadReports(page, info, 'sinusoidal');
      await checkPerformanceRegressions(page);
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
        await openMoreRunActions(page);
        await page.getByRole('button', { name: 'Rerun settings', exact: true }).click();
        await pendingPreview;
        await openSetupSection(page, 'plan');
        await expect(page.getByRole('button', { name: /Standard.*Medium mesh/ })).toBeEnabled();
      } finally {
        releasePreview();
      }
      await expect(page.getByRole('status').filter({ hasText: /settings restored/ })).toBeVisible();
      await expect(page.getByRole('navigation', { name: 'Motor workflow' }).getByRole('button', { name: /Results$/ })).toBeDisabled();
      await openSetupSection(page, 'operating');
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
      const response = await page.request.get(`${apiUrl}/runs/${run.project_slug}/${run.run_id}`, { maxRetries: 2 });
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
        const response = await page.request.get(`${apiUrl}/runs/${run.project_slug}/${run.run_id}`, { maxRetries: 2 });
        expect((await response.json()).integrity.valid).toBe(true);
      }
    });
    expect(nonLocalRequests).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(duplicateKeyWarnings).toEqual([]);
  });
});


test('loads both exact Pyleecan Prius cases through the public Design and Solve routes', async ({ page }) => {
  // Observe the rendered motor origin so the real wheel handler and drawing
  // transform must agree, including the shifted frame beside the phase scope.
  await page.addInitScript(() => {
    const original = CanvasRenderingContext2D.prototype.createRadialGradient;
    CanvasRenderingContext2D.prototype.createRadialGradient = function (...args) {
      const [x, y, inner, , , outer] = args;
      if (this.canvas.matches('.motor-canvas') && Math.abs(inner / outer - 0.82 / 1.2) < 1e-9) {
        this.canvas.dataset.motorOrigin = JSON.stringify([x - outer * 0.04 / 1.2, y - outer * 0.09 / 1.2]);
        this.canvas.dataset.motorRadius = String(outer / 1.2);
      }
      return original.apply(this, args);
    };
  });
  await page.goto('/');
  await expect(page.getByRole('status', { name: 'Local backend: ready', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  for (const [label, caseId, temperature] of [
    ['Pyleecan Prius 8p48s · BEMF', 'prius-2004-tutorial-bemf-v1', 20],
    ['Pyleecan Prius 8p48s · Loaded torque', 'prius-2004-loaded-torque-v1', 60],
  ] as const) {
    await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Examples', exact: true }).hover();
    const previewed = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.reference_case === caseId);
    await page.getByRole('menuitem', { name: new RegExp(`^${label}`) }).click();
    const response = await previewed;
    expect(response.status(), await response.text()).toBe(200);
    const request = response.request().postDataJSON();
    expect(request.solve_params.magnet_temperature_C).toBe(temperature);
    expect(request.winding.coil_span).toBe(6);
    expect(request.solve_params.max_nonlinear_iterations).toBe(200);
    const data = await response.json();
    expect(data.regions.filter((r: {loops?: unknown[]}) => r.loops?.length)).toHaveLength(91);
    expect(data.regions.find((r: {region_type: string}) => r.region_type === 'rotor_core').loops).toHaveLength(10);
    expect(data.metadata.phase_current_convention).toBe('pyleecan_d_axis');
    await page.getByRole('button', { name: 'Show 2D motor view', exact: true }).click();
    await page.getByRole('button', { name: 'Stop and reset preview', exact: true }).click();
    await page.getByRole('button', { name: 'Phases', exact: true }).click();
    const phaseCanvas = page.getByLabel('geometry motor view, phases layer', { exact: true });
    await expect(phaseCanvas).toHaveAttribute('data-motor-origin', /\[/);
    const before = JSON.parse((await phaseCanvas.getAttribute('data-motor-origin'))!) as number[];
    const radius = Number(await phaseCanvas.getAttribute('data-motor-radius'));
    const bounds = (await phaseCanvas.boundingBox())!;
    // The scope must be visible: at this width the motor is right of centre.
    expect(before[0]).toBeGreaterThan(bounds.width / 2 + 50);
    await page.mouse.move(bounds.x + before[0], bounds.y + before[1]);
    await page.mouse.wheel(0, -Math.log(2) / 0.0012);
    await expect(page.getByRole('button', { name: 'Fit motor to view', exact: true })).toBeEnabled();
    await expect.poll(async () => Number(await phaseCanvas.getAttribute('data-motor-radius')) / radius).toBeCloseTo(2, 3);
    // Chromium rounds wheel pointer coordinates to CSS pixels.
    await expect.poll(async () => {
      const after = JSON.parse((await phaseCanvas.getAttribute('data-motor-origin'))!) as number[];
      return Math.hypot(after[0] - before[0], after[1] - before[1]);
    }).toBeLessThan(1.5);
    await page.getByRole('button', { name: 'Fit motor to view', exact: true }).click();
    await page.getByRole('button', { name: 'Phases', exact: true }).click();
    await expect(page.getByText('Published Pyleecan geometry, winding and materials are fixed.', { exact: false })).toBeVisible();
    await expect(page.getByText('No affiliation with or endorsement by EOMYS, the Pyleecan project, or Toyota.', { exact: false })).toBeVisible();
    await page.getByRole('button', { name: 'Show layout view', exact: true }).click();
    await expect(page.locator('.wl-ring-slot')).toHaveCount(48);
    await expect(page.locator('.wl-ring-end-turn')).toHaveCount(24);
    const slot13 = page.locator('.wl-ring-number').filter({ hasText: /^13$/ });
    expect(Number(await slot13.getAttribute('y'))).toBeGreaterThan(250);
    await page.getByRole('button', { name: 'Show 2D motor view', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
    const checked = await page.request.post(`${apiUrl}/solve/validate`, { data: request });
    expect(checked.status()).toBe(200);
    expect((await checked.json()).valid).toBe(true);
    const validated = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/solve/validate');
    await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
    const validation = await validated;
    expect(validation.status()).toBe(200);
    expect((await validation.json()).valid).toBe(true);
    expect(validation.request().postDataJSON().solver).toBe('magneto2d');
    await openSetupSection(page, 'operating');
    await expect(page.getByText(`Pyleecan software reference · ${temperature}°C magnets`, { exact: false })).toBeVisible();
    await expect(page.getByText('No affiliation with or endorsement by EOMYS, the Pyleecan project, or Toyota.', { exact: false })).toBeVisible();
    await page.getByRole('button', { name: '← Back to Design', exact: true }).click();
  }
  await page.getByRole('button', { name: 'Show 2D motor view', exact: true }).click();
  await page.screenshot({ path: fileURLToPath(new URL('../test-results/prius-reference.png', import.meta.url)), fullPage: true });
  await page.getByRole('button', { name: 'Show 3D motor view', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Show 2D motor view', exact: true })).toBeVisible();
  await expect(page.getByText('Loading reference geometry…', { exact: true })).toBeHidden();
  await expect(page.locator('.public-viewport-message')).toHaveCount(0);
  await page.screenshot({ path: fileURLToPath(new URL('../test-results/prius-reference-3d.png', import.meta.url)), fullPage: true });
});

// Zero current is a distinct presentation path: mean cogging torque is close
// to zero, so its percentage ripple must not be presented as a useful metric.
test('shows the cogging swing and exports a report for a real zero-current solve', async ({ page }, info) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await openSetupSection(page, 'operating');
  const current = page.getByLabel(/^Phase Current/);
  await current.fill('0');
  await current.blur();
  await openSetupSection(page, 'plan');
  await page.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
  const submitted = page.waitForRequest((request) => request.method() === 'POST' && new URL(request.url()).pathname === '/solve/stream');
  await page.getByRole('button', { name: '▶ Run analysis', exact: true }).click();
  expect((await submitted).postDataJSON().config.solve_params.current_amplitude_A).toBe(0);
  const completed = page.getByRole('region', { name: 'Completed solver results' });
  await expect(completed).toBeVisible({ timeout: 600_000 });
  await expect(completed).toContainText('Cogging torque p-p');
  await expect(completed.locator('tr').filter({ hasText: 'Torque ripple' }).first()).not.toContainText('%');
  await page.getByRole('button', { name: 'Full results →', exact: true }).click();
  await expect(page.getByText(/^Cogging torque p-p/).first()).toBeVisible();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download PDF', exact: true }).click();
  const report = await downloaded;
  expect(await report.failure()).toBeNull();
  await report.saveAs(info.outputPath('zero-current.pdf'));
});

for (const analysis of ['Back EMF', 'Cogging torque'] as const) {
  test(`runs standalone ${analysis} from the Analysis section`, async ({ page }, info) => {
    test.setTimeout(180_000);
    await page.goto('/');
    await expect(page.getByRole('status', { name: 'Local backend: ready', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
    await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
    await openSetupSection(page, 'analysis');
    const torque = page.getByRole('checkbox', { name: 'Torque', exact: true });
    const backEmf = page.getByRole('checkbox', { name: 'Back EMF', exact: true });
    const cogging = page.getByRole('checkbox', { name: 'Cogging torque', exact: true });
    const losses = page.getByRole('checkbox', { name: 'Losses & efficiency', exact: true });
    await expect(torque).toBeChecked();
    await expect(backEmf).toBeChecked();
    await expect(cogging).not.toBeChecked();
    await expect(losses).not.toBeChecked();
    if (analysis === 'Cogging torque') await cogging.check();
    await torque.uncheck();
    if (analysis === 'Cogging torque') await backEmf.uncheck();
    await openSetupSection(page, 'plan');
    await page.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
    const run = page.getByRole('button', { name: '▶ Run analysis', exact: true });
    await expect(run).toBeEnabled({ timeout: 120_000 });
    if (analysis === 'Back EMF') {
      await page.getByRole('button', { name: /Custom.*Choose the electrical-angle step/ }).click();
      const step = page.getByLabel('Step Size (° elec)', { exact: true });
      await step.fill('30');
      await step.blur();
    }
    await expect(run).toBeEnabled();
    await expect(page.getByRole('region', { name: 'Excitation: no current', exact: true })).toContainText('0 A');
    await expect(page.locator('.public-quality-list').getByText(analysis === 'Back EMF' ? 'Back EMF 12' : 'Cogging 13', { exact: true })).toBeVisible();
    // Switching presets keeps the selected work. The collapsed section lists it.
    await expect(page.locator('button[aria-controls="param-group-content-analysis"]')).toContainText(analysis === 'Back EMF' ? 'Back EMF' : 'Cogging');
    await openSetupSection(page, 'analysis');
    await page.screenshot({ path: info.outputPath('analysis-options.png'), animations: 'disabled' });
    const submitted = page.waitForRequest((request) => request.url().endsWith('/solve/stream'));
    const finished = page.waitForResponse((response) => response.url().endsWith('/solve/stream'));
    await run.click();
    const request = (await submitted).postDataJSON();
    expect(request.config.solve_options.torque_sweep).toBe(false);
    expect(request.config.solve_options.losses_efficiency).toBe(false);
    expect(request.config.solve_options.back_emf).toBe(analysis === 'Back EMF');
    expect(request.config.solve_options.thd_analysis).toBe(false);
    expect((await finished).ok()).toBe(true);
    await expect(page.getByRole('region', { name: 'Completed solver results' })).toBeVisible({ timeout: 120_000 });
    const stream = await (await finished).text();
    const complete = stream.split('\n\n').find((event) => event.startsWith('event: complete'));
    expect(complete).toBeTruthy();
    const payload = JSON.parse(complete!.split('\n').find((line) => line.startsWith('data: '))!.slice(6));
    expect(payload.summary.avg_torque_Nm).toBeNull();
    expect(payload.torque_waveform.torque_Nm).toEqual([]);
    expect(payload.solve_metadata.rotor_positions).toBe(1);
    expect(payload.solve_metadata.current_amplitude_A).toBe(0);
    expect(payload.summary.loss_breakdown).toBeNull();
    await page.getByRole('button', { name: 'Full results →', exact: true }).click();
    const report = page.locator('.public-report-stage');
    await expect(report.getByRole('tab', { name: 'Torque', exact: true })).toHaveCount(0);
    await expect(report.getByRole('tab', { name: 'Torque–speed', exact: true })).toHaveCount(0);
    await expect(report.locator('.public-result-hero')).toHaveCount(0);
    await expect(report.getByRole('heading', { name: 'Losses & efficiency', exact: true })).toHaveCount(0);
    if (analysis === 'Back EMF') {
      await expect(report.getByRole('tab', { name: 'Back EMF', exact: true })).toHaveAttribute('aria-selected', 'true');
      await expect(report.locator('.public-result-emf')).toBeVisible();
    } else {
      await expect(report.getByRole('tab', { name: 'Cogging', exact: true })).toHaveAttribute('aria-selected', 'true');
      await expect(report.getByRole('tab', { name: 'Back EMF', exact: true })).toHaveCount(0);
      await expect(report.locator('.cogging-card')).toBeVisible();
    }
    await page.screenshot({ path: info.outputPath('standalone-results.png'), animations: 'disabled' });
  });
}

test('runs a standalone torque–speed map from Analysis and reopens its saved settings', async ({ page }, info) => {
  test.setTimeout(900_000);
  await page.goto('/');
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await openSetupSection(page, 'analysis');
  const selectedMap = page.getByRole('checkbox', { name: 'Torque–speed map', exact: true });
  await expect(selectedMap).not.toBeChecked();
  await selectedMap.check();
  await page.getByRole('checkbox', { name: 'Torque', exact: true }).uncheck();
  await page.getByRole('checkbox', { name: 'Back EMF', exact: true }).uncheck();
  const settings = page.getByRole('region', { name: 'Torque–speed map settings', exact: true });
  await expect(settings.getByLabel('Peak current', { exact: true })).toHaveValue('60');
  await expect(settings.getByLabel('DC bus', { exact: true })).toHaveValue('48');
  await settings.getByLabel('Drive control', { exact: true }).selectOption('least_loss');
  await openSetupSection(page, 'plan');
  await page.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
  const run = page.getByRole('button', { name: '▶ Run analysis', exact: true });
  await expect(run).toBeEnabled({ timeout: 120_000 });
  await openSetupSection(page, 'analysis');
  await expect(selectedMap).toBeChecked();
  await expect(settings.getByLabel('Drive control', { exact: true })).toHaveValue('least_loss');
  await page.screenshot({ path: info.outputPath('torque-speed-setup.png'), animations: 'disabled' });
  const submitted = page.waitForRequest((request) => request.url().endsWith('/solve/stream'));
  const finished = page.waitForResponse((response) => response.url().endsWith('/solve/stream'));
  await run.click();
  const request = (await submitted).postDataJSON().config;
  expect(request.solve_options.torque_speed_envelope).toBe(true);
  expect(request.solve_options.torque_sweep).toBe(false);
  expect(request.solve_options.back_emf).toBe(false);
  expect(request.solve_options.losses_efficiency).toBe(false);
  expect(request.torque_speed_analysis.control).toBe('least_loss');
  await expect(page.getByRole('region', { name: 'Completed solver results', exact: true })).toBeVisible({ timeout: 780_000 });
  const stream = await (await finished).text();
  expect(stream).toContain('torque_speed_map');
  const complete = stream.split('\n\n').find((event) => event.startsWith('event: complete'));
  expect(complete).toBeTruthy();
  const payload = JSON.parse(complete!.split('\n').find((line) => line.startsWith('data: '))!.slice(6));
  expect(payload.torque_waveform.torque_Nm).toEqual([]);
  expect(payload.solve_metadata.rotor_positions).toBe(1);
  expect(payload.torque_speed_analysis.map.points).toHaveLength(35);
  expect(payload.torque_speed_analysis.map.points.every((point) => point.status === 'ok')).toBe(true);
  await page.getByRole('button', { name: 'Full results →', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Torque–speed', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tab', { name: 'Torque', exact: true })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'Back EMF', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Torque–speed and efficiency', exact: true })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Envelope quantity', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Solve map/ })).toHaveCount(0);
  await expect(page.getByRole('spinbutton')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('torque-speed-results.png'), animations: 'disabled' });
  await openMoreRunActions(page);
  await page.getByRole('button', { name: 'Rerun settings', exact: true }).click();
  await openSetupSection(page, 'analysis');
  await expect(selectedMap).toBeChecked();
  await expect(settings.getByLabel('Drive control', { exact: true })).toHaveValue('least_loss');
  await expect(settings.getByLabel('DC bus', { exact: true })).toHaveValue('48');
});

test('Previous runs handles standalone analyses and missing legacy waveform arrays', async ({ page }) => {
  const errors: string[] = [];
  const solveRequests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (['/solve', '/solve/stream', '/performance/map/stream'].includes(path)) solveRequests.push(path);
  });
  const summary = { avg_torque_Nm: null, torque_ripple_pct: null, back_emf_fundamental_V: null,
    peak_flux_density_teeth_T: 1.2, peak_flux_density_yoke_T: 1, solve_time_s: 2 };
  const metadata = { solver_name: 'magneto2d-test', current_amplitude_A: 0, rotor_positions: 1 };
  const emptyTorque = { electrical_angle_deg: [], torque_Nm: [] };
  const emptyEmf = { electrical_angle_deg: [], phase_a_V: [], phase_b_V: [], phase_c_V: [] };
  const results = {
    map: { summary, solve_metadata: metadata, torque_waveform: {}, back_emf_waveform: {} },
    cogging: { summary: { ...summary, cogging: { peak_to_peak_Nm: 0.2, first_harmonic_Nm: 0.1 } },
      solve_metadata: metadata, torque_waveform: emptyTorque, back_emf_waveform: emptyEmf },
    emf: { summary: { ...summary, back_emf_fundamental_V: 2 }, solve_metadata: metadata, torque_waveform: {},
      back_emf_waveform: { electrical_angle_deg: [0, 90, 180, 270], phase_a_V: [0, 2, 0, -2], phase_b_V: [-1, 1, 1, -1], phase_c_V: [1, -1, -1, 1] } },
    torque: { summary: { ...summary, avg_torque_Nm: 4, torque_ripple_pct: 2 }, solve_metadata: { ...metadata, current_amplitude_A: 10 },
      torque_waveform: { electrical_angle_deg: [0, 30], torque_Nm: [3.9, 4.1] }, back_emf_waveform: {} },
  };
  await page.route('**/runs', (route) => route.fulfill({ json: {
    storage: { used_bytes: 1000, max_bytes: 10000, available_bytes: 9000, accepting_new_runs: true },
    runs: Object.keys(results).map((key) => ({ project_slug: 'regression', run_id: key, project_name: key,
      status: 'complete', solver_name: 'magneto2d-test', completed_at: '2026-11-04T02:00:00Z' })),
  } }));
  await page.route('**/runs/regression/*/comparison', (route) => {
    const key = new URL(route.request().url()).pathname.split('/').at(-2) as keyof typeof results;
    return route.fulfill({ json: { result: results[key] } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  await page.getByRole('button', { name: 'Previous runs', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Previous runs', exact: true });
  await expect(dialog.getByText('Neither run has torque or Back EMF waveforms to overlay.', { exact: false })).toBeVisible();
  await expect(dialog.getByRole('tablist', { name: 'Comparison plots', exact: true })).toHaveCount(0);
  await expect(dialog.getByText('Peak tooth B', { exact: true })).toBeVisible();
  await dialog.getByLabel('Run B · candidate').selectOption('regression/emf');
  await expect(dialog.getByRole('tab', { name: 'Back EMF overlay', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(dialog.getByRole('tab', { name: 'Torque overlay', exact: true })).toHaveCount(0);
  await expect(dialog.getByText('Run A not computed · Run B 4 positions', { exact: true })).toBeVisible();
  await dialog.getByLabel('Run A · baseline').selectOption('regression/torque');
  await dialog.getByRole('tab', { name: 'Torque overlay', exact: true }).click();
  await expect(dialog.getByText('Torque comparison', { exact: true })).toBeVisible();
  await expect(dialog.getByText('Run A 2 positions · Run B not computed', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close previous runs', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Previous runs', exact: true }).click();
  await expect(dialog.getByText('Neither run has torque or Back EMF waveforms to overlay.', { exact: false })).toBeVisible();
  expect(errors).toEqual([]);
  expect(solveRequests).toEqual([]);
});
