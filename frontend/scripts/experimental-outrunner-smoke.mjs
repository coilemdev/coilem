// Run against tools.experimental.serve_outrunner, with the opt-in UI build.
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = new URL('../../output/femm-outrunner-review/ui-browser-smoke/', import.meta.url);
await mkdir(root, { recursive: true });
const browser = await chromium.launch({ channel: 'chromium', headless: true });
const page = await browser.newPage({ viewport: { width: 1450, height: 1050 }, acceptDownloads: true });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto('http://127.0.0.1:58151');
  await page.getByRole('button', { name: 'Design file menu' }).click();
  await page.getByRole('menuitem', { name: 'Examples', exact: true }).hover();
  await page.getByRole('menuitem', { name: /LRK outrunner 14p/ }).click();
  await page.getByRole('heading', { name: 'Motor cross-section' }).waitFor();
  await page.getByRole('button', { name: 'Run fresh analysis' }).waitFor();
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(x => x.textContent === 'Run fresh analysis')?.disabled);
  assert.equal(await page.locator('svg[aria-label="Outer rotor, fourteen magnets and twelve winding regions"] path').count(), 28);
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save .coilem', exact: true }).click();
  const download = await downloaded;
  const target = fileURLToPath(new URL('saved.coilem', root));
  await download.saveAs(target);
  const saved = JSON.parse(await readFile(target, 'utf8'));
  const original = JSON.parse(await readFile(new URL('../src/public/outrunner/lrk_12s14p.coilem', import.meta.url), 'utf8'));
  assert.deepEqual(saved, original);
  await page.locator('input[type=file]').setInputFiles(target);
  await page.getByLabel('Analysis', { exact: true }).selectOption('source_point');
  await page.getByRole('button', { name: 'Run fresh analysis' }).click();
  await page.waitForFunction(() => document.querySelector('.outrunner-workspace')?.textContent.includes('· COMPLETE'), null, { timeout: 120000 });
  const point = page.getByRole('heading', { name: 'Original operating point', exact: true }).locator('..');
  await point.waitFor();
  assert.match(await point.textContent(), /-55\.4093 mN/);
  await page.screenshot({ path: fileURLToPath(new URL('source-point.png', root)), fullPage: true });
  await page.reload();
  await page.getByRole('button', { name: 'Design file menu' }).click();
  await page.getByRole('menuitem', { name: 'Examples', exact: true }).hover();
  await page.getByRole('menuitem', { name: /LRK outrunner 14p/ }).click();
  await page.getByRole('heading', { name: 'Original operating point', exact: true }).waitFor();
  assert.equal(errors.length, 0, errors.join('\n'));
  await writeFile(new URL('receipt.json', root), JSON.stringify({ status: 'PASS', saved_project_exact: true,
    preview_regions: 28, fresh_source_torque_mNm: -55.4093, completed_run_reloaded: true, page_errors: errors }, null, 2));
  console.log('PASS: frozen example, exact save/reopen, fresh native source point, completed-run recovery');
} catch (failure) {
  await page.screenshot({ path: fileURLToPath(new URL('failure.png', root)), fullPage: true }).catch(() => undefined);
  throw failure;
} finally {
  await browser.close();
}
