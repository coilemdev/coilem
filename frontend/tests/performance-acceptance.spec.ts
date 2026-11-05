/** #139/#142: actual native solves and browser downloads; no intercepted API responses. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile, readdir, statfs, writeFile } from 'node:fs/promises';
import os from 'node:os';
import { resolve, join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { formatSignificant as significant } from '../src/public/numberFormat';
import { screenshotPanel } from './performance-capture';
import type { TorqueSpeedAnalysisResult } from '../src/public/performance';

const examples = [
  { id: 'spm-8p12s', menu: 'SPM 8p/12s' },
  { id: 'ipm-14p-flat', menu: 'IPM 14p flat buried' },
  { id: 'ipm-10p-v', menu: 'IPM 10p V-shape' },
  { id: 'spm-24p', menu: 'SPM 24p' },
  { id: 'spm-6p36s', menu: 'SPM 6p/36s' },
];
const requested = (process.env.COILEM_ACCEPTANCE_CASES || 'spm-8p12s,ipm-14p-flat').split(',');
if (requested.some((id) => !examples.some((item) => item.id === id))) throw new Error('Unknown acceptance example');
const sha256 = (data: string | Buffer) => createHash('sha256').update(data).digest('hex');
const git = (...args: string[]) => execFileSync('git', args, { encoding: 'utf8' }).trim();
const root = resolve('..');
const recheckDirectory = process.env.COILEM_ACCEPTANCE_RECHECK_DIR;
const evidenceRoot = resolve(recheckDirectory ? 'test-results/performance-recheck-evidence' : 'test-results/performance-evidence');
const setupOnly = process.env.COILEM_ACCEPTANCE_SETUP_ONLY === '1';

async function section(page: Page, key: string) {
  const header = page.locator(`button[aria-controls="param-group-content-${key}"]`);
  if (await header.getAttribute('aria-expanded') !== 'true') await header.click();
}


for (const example of examples.filter((item) => requested.includes(item.id))) {
  test(`Standard map and Performance view: ${example.id}`, async ({ page, browser }) => {
    const output = join(evidenceRoot, example.id);
    await mkdir(evidenceRoot, { recursive: true });
    // Never combine a new attempt with stale passing receipts/downloads.
    await mkdir(output);
    const save = async (name: string, value: unknown) => writeFile(join(output, name), `${JSON.stringify(value, null, 2)}\n`);
    await save('attempt.json', { example: example.id, started_utc: new Date().toISOString(), phase: 'setup' });
    const measured: TorqueSpeedAnalysisResult | null = recheckDirectory
      ? JSON.parse(await readFile(resolve(recheckDirectory, example.id, 'analysis.json'), 'utf8')) : null;
    if (measured) {
      expect(measured.map.points).toHaveLength(70);
      expect(measured.map.points.every((point: { status: string }) => point.status === 'ok')).toBe(true);
      // Reuse only the actual measured native map, through the app's normal
      // persisted-map path. The API and browser responses remain real.
      const directory = join(process.env.COILEM_ACCEPTANCE_RUNTIME!, 'user-data/performance_maps', measured.map.scope_key);
      await mkdir(directory, { recursive: true });
      await writeFile(join(directory, 'map_measured.json'), JSON.stringify(measured.map));
      for (const name of ['environment.json', 'timing.json', 'request.json', 'map-progress.json']) {
        await copyFile(resolve(recheckDirectory!, example.id, name), join(output, name));
      }
    }
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const source = git('rev-parse', 'HEAD');
    const trackedChanges = git('status', '--porcelain', '--untracked-files=no');
    if (!setupOnly) expect(trackedChanges, 'measure a committed source tree').toBe('');
    const healthResponse = await page.request.get('/health');
    expect(healthResponse.ok()).toBe(true);
    const health = await healthResponse.json();
    const binary = join(root, 'solvers/magneto2d/target/release', process.platform === 'win32' ? 'magneto2d.exe' : 'magneto2d');
    const disk = await statfs(root);
    if (!setupOnly && !measured) {
      const minimum = example.id === 'ipm-14p-flat' ? 6 : 3.5;
      expect(disk.bavail * disk.bsize, `need ${minimum} GiB free before a cold Standard map`).toBeGreaterThanOrEqual(minimum * 2 ** 30);
    }
    await save(measured ? 'recheck-environment.json' : 'environment.json', {
      source_commit: source, tracked_tree_clean: !trackedChanges, setup_only: setupOnly, application_version: health.version,
      platform: process.platform, os_release: os.release(), architecture: os.arch(),
      cpu_model: os.cpus()[0]?.model, logical_cpus: os.cpus().length, memory_bytes: os.totalmem(),
      node: process.version, chromium: browser.version(),
      python: execFileSync(process.env.COILEM_TEST_PYTHON || 'python', ['--version'], { encoding: 'utf8' }).trim(),
      native_binary_sha256: sha256(await readFile(binary)),
      github_run_url: process.env.GITHUB_RUN_ID ? `https://github.com/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}` : null,
      sample_count: measured ? 0 : 1, cache_policy: measured ? 'reuse the previously measured native map for UI/export checks' : 'fresh isolated runtime; no existing map for this design',
      free_disk_bytes_before: disk.bavail * disk.bsize,
      worker_policy: { gmsh_producers: 1, parallel_angle_solves: 2, native_workers_per_angle: 1, field_preview_workers: 1 },
    });
    // Headless Chromium cannot operate the native Save As dialog. Exercise the
    // browser-download fallback, as the regular public release rehearsal does.
    await page.addInitScript(() => {
      Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined });
    });
    await page.goto('/');
    await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
    await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Examples', exact: true }).click();
    await page.getByRole('menuitem', { name: new RegExp(example.menu.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click();
    await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
    await section(page, 'plan');
    const standard = page.getByRole('button', { name: /Standard.*Medium mesh/ });
    await standard.click();
    await expect(standard).toHaveAttribute('aria-pressed', 'true');
    await section(page, 'analysis');
    await page.getByRole('checkbox', { name: 'Torque–speed map', exact: true }).check();
    for (const name of ['Torque', 'Back EMF', 'Cogging torque', 'Losses & efficiency']) {
      await page.getByRole('checkbox', { name, exact: true }).uncheck();
    }
    const settings = page.getByRole('region', { name: 'Torque–speed map settings', exact: true });
    await settings.getByLabel('Map grid', { exact: true }).selectOption('standard');
    await settings.getByLabel('Drive control', { exact: true }).selectOption('mtpa');
    await page.screenshot({ path: join(output, 'setup.png'), animations: 'disabled' });
    const mapDirectory = join(process.env.COILEM_ACCEPTANCE_RUNTIME!, 'user-data/performance_maps');
    const existingScopes = await readdir(mapDirectory).catch(() => []);
    const run = page.getByRole('button', { name: '▶ Run analysis', exact: true });
    await expect(run).toBeEnabled({ timeout: 120_000 });
    if (measured) {
      const request = JSON.parse(await readFile(resolve(recheckDirectory!, example.id, 'request.json'), 'utf8'));
      const status = await page.request.post('/performance/map/status', { data: {
        request, map: { preset: 'standard', peak_current_A: measured.settings.limits.peak_current_A },
      } });
      expect(status.ok(), 'recheck map identity preflight').toBe(true);
      const stored = await status.json();
      expect(stored.scope_key, 'recheck needs the original map identity; never start a cold grid').toBe(measured.map.scope_key);
      expect(stored.map).toEqual(measured.map);
    }
    if (setupOnly) {
      console.log(`${example.id}: setup only; no solve or acceptance result recorded`);
      return;
    }
    if (measured) {
      // Check the UI's actual submitted configuration as well as the archived
      // request above. Forward the real request/response only after confirming
      // it has the seeded covering map; never turn a recheck into a cold run.
      await page.route('**/solve/stream', async (route) => {
        try {
          const request = route.request().postDataJSON();
          const status = await page.request.post('/performance/map/status', { data: {
            request, map: { preset: 'standard', peak_current_A: measured.settings.limits.peak_current_A },
          } });
          expect(status.ok()).toBe(true);
          const stored = await status.json();
          expect(stored.scope_key, 'submitted configuration must reuse the measured map').toBe(measured.map.scope_key);
          expect(stored.map).toEqual(measured.map);
        } catch (error) {
          await route.abort();
          throw error;
        }
        await route.continue();
      });
    }
    const submitted = page.waitForRequest((request) => new URL(request.url()).pathname === '/solve/stream');
    const finished = page.waitForResponse((response) => new URL(response.url()).pathname === '/solve/stream', { timeout: 110 * 60_000 });
    const startedUtc = new Date().toISOString();
    const started = performance.now();
    await save('attempt.json', { example: example.id, started_utc: startedUtc, phase: 'request_started', recheck: !!measured });
    await run.click();
    const request = (await submitted).postDataJSON();
    await save(measured ? 'recheck-request.json' : 'request.json', request);
    expect(request.config.solve_params.mesh_density).toBe('normal');
    expect(request.config.torque_speed_analysis.preset).toBe('standard');
    const response = await finished;
    expect(response.ok()).toBe(true);
    const stream = await response.text();
    const wallSeconds = (performance.now() - started) / 1000;
    const events = stream.split(/\r?\n\r?\n/).map((block) => {
      const kind = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      return kind && data ? { kind, data: JSON.parse(data) } : null;
    }).filter((event) => event !== null);
    const failures = events.filter((event) => event.kind === 'error');
    await save('stream-errors.json', failures);
    expect(failures).toEqual([]);
    const completed = events.find((event) => event.kind === 'complete');
    expect(completed, 'real solve must finish').toBeTruthy();
    const result = completed!.data;
    const analysis: TorqueSpeedAnalysisResult = result.torque_speed_analysis;
    expect(analysis).toBeTruthy();
    await save('analysis.json', analysis);
    await save('attempt.json', { example: example.id, started_utc: startedUtc, phase: 'stream_completed', browser_request_wall_s: wallSeconds });
    const progress = events.filter((event) => event.kind === 'progress' && event.data.stage === 'torque_speed_map').map((event) => event.data);
    if (!measured) {
      await save('map-progress.json', progress);
      await save('timing.json', {
      example: example.id, started_utc: startedUtc, completed_utc: new Date().toISOString(),
      browser_request_wall_s: wallSeconds, backend_analysis_s: result.solve_metadata.solve_time_s,
      map_phase_s: progress.at(-1).elapsed_s - progress[0].elapsed_s,
      map_start_elapsed_s: progress[0].elapsed_s, map_end_elapsed_s: progress.at(-1).elapsed_s,
      timing_resolution_s: 0.1, points: analysis.map.points.length, distinct_solves: 61,
      rotor_positions_per_point: analysis.map.rotor_positions, mesh_density: analysis.map.mesh_density,
      request_sha256: sha256(JSON.stringify(request)), map_scope_key: analysis.map.scope_key,
      });
      expect(existingScopes).not.toContain(analysis.map.scope_key);
      expect(progress.map((item) => item.position)).toEqual(Array.from({ length: 62 }, (_, i) => i));
    } else {
      expect(existingScopes).toContain(analysis.map.scope_key);
      expect(analysis.map).toEqual(measured.map);
      expect(progress).toEqual([]);
      await save('recheck-progress.json', progress);
      await save('recheck.json', {
        source_commit: source, measured_map_sha256: sha256(JSON.stringify(measured.map)),
        returned_map_sha256: sha256(JSON.stringify(analysis.map)), grid_resolved_again: false,
      });
    }
    expect(analysis.map.points).toHaveLength(70);
    expect(analysis.map.points.every((point: { status: string }) => point.status === 'ok')).toBe(true);
    expect(analysis.map.rotor_positions).toBe(24);
    await expect(page.getByRole('region', { name: 'Completed solver results', exact: true })).toBeVisible({ timeout: 120_000 });
    await page.getByRole('button', { name: 'Full results →', exact: true }).click();
    const panel = page.locator('.performance-panel');
    await expect(panel.getByRole('heading', { name: 'Torque–speed and efficiency', exact: true })).toBeVisible();
    await expect(panel.locator('[aria-label="Saved map settings"]')).toContainText('Standard 7×10');
    await expect(panel.locator('.status-summary')).toContainText(/Experimental/i);
    const torque = panel.getByRole('img', { name: 'Torque against speed for the drive limits', exact: true });
    await expect(torque).toBeVisible();
    const curves = await torque.locator('path[stroke]').evaluateAll((paths) => paths.map((path) => path.getAttribute('d')));
    expect(curves).toHaveLength(2);
    expect(curves.every((path) => path && path.length > 100 && !/NaN|Infinity/.test(path))).toBe(true);
    const peak = analysis.envelope!.curves.find((curve) => curve.limit === 'peak')!;
    const efficiency = analysis.efficiency_map!.efficiency_pct.flat().filter((value): value is number => typeof value === 'number');
    const stats = await panel.locator('.performance-stats').innerText();
    expect(stats).toContain(significant(peak.torque_Nm[0]));
    expect(stats).toContain(significant(peak.peak_power_W / 1000));
    expect(stats).toContain(Math.max(...efficiency).toFixed(1));
    await screenshotPanel(page, join(output, 'torque-efficiency.png'));
    const quantity = panel.getByRole('group', { name: 'Envelope quantity', exact: true });
    await quantity.getByRole('button', { name: 'Power', exact: true }).click();
    await expect(panel.getByRole('img', { name: 'Power against speed for the drive limits', exact: true })).toBeVisible();
    const efficiencyChart = panel.getByRole('img', { name: /^Efficiency over speed and torque/ });
    await expect(efficiencyChart).toBeVisible();
    expect(await efficiencyChart.locator('rect[fill]').count()).toBe(efficiency.length);
    await screenshotPanel(page, join(output, 'power-efficiency.png'));
    await panel.getByText('Map details: Ld, Lq and torque check', { exact: true }).click();
    await expect(panel.locator('.performance-inductance tbody tr')).toHaveCount(6);
    await screenshotPanel(page, join(output, 'map-details.png'));
    let reportRequest: unknown;
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/performance/report/csv') {
        reportRequest = request.postDataJSON();
      }
    });
    for (const [label, filename] of [['PDF report', 'performance.pdf'], ['Performance CSV', 'performance.csv'], ['id/iq table', 'idiq.csv'], ['Map points CSV', 'map.csv']]) {
      await panel.getByRole('button', { name: 'Export', exact: true }).click();
      const pending = page.waitForEvent('download');
      await panel.getByRole('group', { name: 'Downloads', exact: true }).getByRole('button', { name: label, exact: true }).click();
      await (await pending).saveAs(join(output, filename));
    }
    expect(reportRequest, 'capture the actual report inputs').toBeTruthy();
    await save('report-request.json', reportRequest);
    expect(errors).toEqual([]);
    expect(git('rev-parse', 'HEAD')).toBe(source);
    expect(git('status', '--porcelain', '--untracked-files=no')).toBe('');
    await save('browser-check.json', { passed: true, page_errors: errors, headline_text: stats, torque_paths: curves, efficiency_cells: efficiency.length,
      checked: ['torque curves', 'power curves', 'efficiency cells', 'experimental status', 'Ld/Lq table', 'PDF download', 'performance CSV download', 'id/iq CSV download', 'map CSV download'] });
    console.log(measured ? `${example.id}: saved native map UI/export recheck passed`
      : `${example.id}: ${wallSeconds.toFixed(1)} s total; Standard map ${(progress.at(-1).elapsed_s - progress[0].elapsed_s).toFixed(1)} s`);
  });
}
