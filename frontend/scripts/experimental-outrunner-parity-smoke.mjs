// Real meshes and retained per-angle fields; kept outside the release suite.
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { chromium } from '@playwright/test';

const base = process.env.COILEM_OUTRUNNER_REVIEW_URL || 'http://127.0.0.1:58152';
const output = new URL('../../output/femm-outrunner-review/ui-parity-smoke/', import.meta.url);
const retained = '337bbb5a32b245a0b56fa09c546a1c7a';
const legacy = JSON.parse(await readFile(new URL(`../../output/femm-outrunner-review/ui-smoke-data/experimental/femm-outrunner/${retained}/request.json`, import.meta.url), 'utf8'));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chromium', headless: true });
const page = await browser.newPage({ viewport: { width: 1660, height: 1120 } });
const errors = [], receipt = {};
page.on('pageerror', error => errors.push(error.stack || error.message));
const shot = name => page.screenshot({ path: fileURLToPath(new URL(name+'.png', output)), fullPage: true });
const openFixture = async () => {
  await page.getByRole('button', { name: 'Design file menu' }).click();
  await page.getByRole('menuitem', { name: 'Examples', exact: true }).hover();
  await page.getByRole('menuitem', { name: /LRK outrunner 14p/ }).click();
  await page.getByRole('region', { name: 'Outrunner motor viewport' }).waitFor();
};
const waitMesh = gap => page.waitForFunction(expected => {
  const label = document.querySelector('.viewport-cad-status')?.textContent || '';
  const advanced = document.querySelector('select[aria-label="Gap mesh target (mm)"]');
  return label.includes('elements') && advanced?.value === String(expected);
}, gap, { timeout: 120000 });
try {
  await page.goto(base);
  await page.evaluate(({ retained, legacy }) => localStorage.setItem(`coilem.outrunner.run:${legacy.project.fixture_id}`, JSON.stringify({ run_id: retained, ...legacy })), { retained, legacy });
  await openFixture();
  const angle = page.getByLabel('Rotor position CCW mechanical degrees');
  await page.getByRole('button', { name: 'Play motor preview', exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector('input[aria-label="Rotor position CCW mechanical degrees"]')?.value) > 10);
  await page.getByRole('button', { name: 'Pause motor preview', exact: true }).click();
  assert.ok(Number(await angle.inputValue()) > 10);
  receipt.design_play = true;
  await page.getByRole('button', { name: 'Reset motor preview', exact: true }).click();
  await page.getByRole('button', { name: 'Show mesh view', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.viewport-cad-status')?.textContent?.includes('elements'), null, { timeout: 120000 });
  await shot('design-mesh');
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  assert.deepEqual(await page.locator('.public-solve-setup .param-group-label').allTextContents(), ['Operating point', 'Analysis', 'Accuracy plan', 'Advanced options']);
  assert.equal(await page.locator('.public-solve-setup .param-group-header[aria-expanded=true]').count(), 1);
  await page.getByRole('button', { name: /^Accuracy plan/ }).click();
  await waitMesh(.05);
  await shot('solve-standard');
  const meshes = {};
  for (const [name, gap] of [['Preview', .1], ['High accuracy', .025], ['Standard', .05]]) {
    await page.locator('.public-solve-plan-choices button').filter({ hasText: name }).click();
    await waitMesh(gap);
    await page.waitForFunction(() => !document.querySelector('.public-solve-footer .public-run-btn')?.disabled);
    meshes[name] = Number((await page.locator('.viewport-cad-status').textContent()).replace(/[^0-9]/g, ''));
  }
  assert.ok(meshes.Preview < meshes.Standard && meshes.Standard < meshes['High accuracy']);
  receipt.mesh_elements = meshes;
  console.log('PASS design playback, section order, accordion and actual preset meshes', meshes);
  await shot('solve-accuracy-plan');
  // Recover the user's legacy completed run with the new defaulted fields.
  await page.reload(); await openFixture();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await page.getByRole('button', { name: 'Show Field solution view', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('.outrunner-field-buffer'), null, { timeout: 120000 });
  const scrub = page.getByLabel('Solved field position', { exact: true });
  assert.equal(await scrub.getAttribute('max'), '48');
  await shot('field-angle-0');
  const heatHashes = [];
  for (const index of [0, 24]) {
    await scrub.fill(String(index));
    await page.waitForFunction(expected => !document.querySelector('.outrunner-field-buffer') && document.querySelector('input[aria-label="Solved field position"]')?.value === String(expected), index, { timeout: 120000 });
    const response = await page.request.get(`${base}/experimental/outrunner/runs/${retained}/frames/${index}/layers/heat.webp`);
    assert.ok(response.ok()); heatHashes.push(createHash('sha256').update(await response.body()).digest('hex'));
  }
  assert.notEqual(heatHashes[0], heatHashes[1]);
  receipt.actual_field_heat_sha256 = heatHashes;
  await shot('field-angle-24');
  await page.getByRole('button', { name: 'Play field solution', exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector('input[aria-label="Solved field position"]')?.value) > 24, null, { timeout: 120000 });
  await page.getByRole('button', { name: 'Pause field solution', exact: true }).click();
  receipt.field_playback = true;
  console.log('PASS legacy 49-point restore and real changing solved-field playback');
  await page.getByRole('button', { name: /Results/ }).first().click();
  await page.getByRole('tab', { name: 'Field solution', exact: true }).click();
  await page.getByRole('region', { name: 'Solved magnetic field map' }).waitFor();
  await shot('results-field');
  receipt.results_field = true;
  // Fresh low-cost Preview point checks the actual new solve/mesh/cache route.
  await page.getByRole('button', { name: '← Back to Solve', exact: true }).click();
  await page.getByRole('button', { name: /^Accuracy plan/ }).click();
  await page.getByRole('button', { name: /^Preview/ }).click();
  await waitMesh(.1);
  await page.getByRole('button', { name: /^Analysis/ }).first().click();
  await page.getByRole('radio', { name: 'Original operating point only' }).check();
  await page.waitForFunction(() => !document.querySelector('.public-solve-footer .public-run-btn')?.disabled);
  await shot('solve-preview-ready');
  await page.getByRole('button', { name: '▶ Run analysis', exact: true }).click();
  await page.getByRole('heading', { name: 'Original operating point', exact: true }).waitFor({ timeout: 120000 });
  receipt.fresh_preview_result = await page.getByRole('heading', { name: 'Original operating point', exact: true }).locator('..').textContent();
  await page.getByRole('tab', { name: 'Field solution', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('.outrunner-field-buffer'), null, { timeout: 120000 });
  await shot('results-preview-point');
  assert.deepEqual(errors, []);
  await writeFile(new URL('receipt.json', output), JSON.stringify({ status: 'PASS', ...receipt, page_errors: errors }, null, 2));
  console.log('PASS fresh Preview solve and zero page errors');
} catch (error) {
  await shot('failure').catch(() => undefined);
  console.log('Page errors:', errors);
  throw error;
} finally { await browser.close(); }
