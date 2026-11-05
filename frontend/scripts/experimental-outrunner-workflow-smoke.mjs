// Real local UI/solver rehearsal, kept separate from the default release suite.
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = new URL('../../output/femm-outrunner-review/ui-workflow-smoke/', import.meta.url);
const base = process.env.COILEM_OUTRUNNER_REVIEW_URL || 'http://127.0.0.1:58152';
await mkdir(root, { recursive: true });
const browser = await chromium.launch({ channel: 'chromium', headless: true });
const page = await browser.newPage({ viewport: { width: 1650, height: 1050 }, acceptDownloads: true });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const screenshot = async name => page.screenshot({ path: fileURLToPath(new URL(name+'.png', root)), fullPage: true });
const openFixture = async () => {
  await page.getByRole('button', { name: 'Design file menu' }).click();
  await page.getByRole('menuitem', { name: 'Examples', exact: true }).hover();
  await page.getByRole('menuitem', { name: /LRK outrunner 14p/ }).click();
  await page.getByRole('region', { name: 'Outrunner motor viewport' }).waitFor();
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(x => x.textContent === 'Continue to Solve')?.disabled);
};
try {
  await page.goto(base);
  await openFixture();
  const arrangement = page.getByRole('group', { name: 'Rotor arrangement', exact: true });
  assert.equal(await arrangement.getByRole('button', { name: /^Outrunner/ }).getAttribute('aria-pressed'), 'true');
  await page.locator('canvas[aria-label="geometry motor view, none layer"]').waitFor();
  await screenshot('design-2d');
  await page.getByRole('button', { name: 'Show 3D motor view', exact: true }).click();
  await page.getByRole('group', { name: 'Show or hide motor parts' }).waitFor();
  await page.getByRole('button', { name: 'Reset view', exact: true }).click();
  await screenshot('design-3d');
  await page.getByRole('button', { name: 'Show 2D motor view', exact: true }).click();
  await arrangement.getByRole('button', { name: /^Inrunner/ }).click();
  await page.getByRole('group', { name: 'Rotor arrangement', exact: true }).getByRole('button', { name: /^Outrunner/ }).click();
  await page.getByRole('region', { name: 'Outrunner motor viewport' }).waitFor();
  await page.getByRole('button', { name: 'Design file menu' }).click();
  const downloading = page.waitForEvent('download');
  await page.getByRole('menuitem', { name: 'Save design file (.coilem)', exact: true }).click();
  const downloaded = await downloading;
  const target = fileURLToPath(new URL('saved.coilem', root));
  await downloaded.saveAs(target);
  const saved = JSON.parse(await readFile(target, 'utf8'));
  const original = JSON.parse(await readFile(new URL('../src/public/outrunner/lrk_12s14p.coilem', import.meta.url), 'utf8'));
  assert.deepEqual(saved, original);
  await page.locator('input[type=file][accept*=".coilem"]').setInputFiles(target);
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await page.getByLabel('Analysis', { exact: true }).selectOption('source_point');
  await screenshot('solve-setup');
  await page.getByRole('button', { name: '▶ Run analysis', exact: true }).click();
  await page.getByRole('heading', { name: 'Original operating point', exact: true }).waitFor({ timeout: 120000 });
  assert.match(await page.getByRole('heading', { name: 'Original operating point', exact: true }).locator('..').textContent(), /-55\.4093/);
  await screenshot('results-source-point');
  await page.reload();
  await openFixture();
  await page.getByRole('button', { name: /Results/ }).click();
  await page.getByRole('heading', { name: 'Original operating point', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  await writeFile(new URL('receipt.json', root), JSON.stringify({ status: 'PASS', shared_design_solve_results: true,
    inrunner_outrunner_switch: true, common_2d_and_3d_renderers: true, saved_project_exact: true,
    fresh_source_torque_mNm: -55.4093, completed_run_reloaded: true, page_errors: errors }, null, 2));
  console.log('PASS: shared workflow, arrangement switch, 2D/3D, exact file roundtrip, fresh solver, run recovery');
} catch (failure) {
  await screenshot('failure').catch(() => undefined);
  throw failure;
} finally {
  await browser.close();
}
