import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';

async function start(page: Page) {
  await page.addInitScript(() => Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Run setup', exact: true })).toBeVisible();
}
async function operating(page: Page) {
  const section = page.locator('[data-guide="solve-operating"]');
  if (!await section.getByRole('spinbutton', { name: 'Phase Current', exact: true }).isVisible()) {
    await page.locator('button[aria-controls="param-group-content-operating"]').click();
  }
  return section;
}
async function saveFile(page: Page, path: string) {
  await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
  const pending = page.waitForEvent('download');
  await page.getByRole('menuitem', { name: 'Save design file (.coilem)', exact: true }).click();
  const download = await pending; await download.saveAs(path);
  return JSON.parse(await readFile(path, 'utf8'));
}
async function saveSetup(page: Page, name: string) {
  await page.getByRole('button', { name: 'Save setup…', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill(name);
  await page.getByRole('button', { name: 'Save setup', exact: true }).click();
}

test('user setups support save, apply, update, rename, copy, delete and file round-trip', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await start(page);
  const section = await operating(page);
  const current = section.getByRole('spinbutton', { name: 'Phase Current', exact: true });
  await current.fill('22'); await current.press('Tab');
  await saveSetup(page, 'Rated current');
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  const id = await selector.inputValue();
  await current.fill('33'); await current.press('Tab');
  await expect(page.getByText('Modified from Rated current.', { exact: false })).toBeVisible();
  await selector.selectOption(''); await selector.selectOption(id);
  await expect(current).toHaveValue('22');
  await page.getByRole('button', { name: 'Rename setup', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill('Rated operating point');
  await page.getByRole('button', { name: 'Save name', exact: true }).click();
  await current.fill('33'); await current.press('Tab');
  await page.getByRole('button', { name: 'Update setup', exact: true }).click();
  const filePath = info.outputPath('setups.coilem');
  const file = await saveFile(page, filePath);
  expect(file.run_setups.activeId).toBe(id);
  expect(file.run_setups.activeVersion).toBe(3);
  expect(file.run_setups.profiles[0].name).toBe('Rated operating point');
  expect(file.solve_params.current_amplitude_A).toBe(33);
  expect(file.run_setups.profiles[0].parameters.mesh_density).toBeUndefined();
  await saveSetup(page, 'A second point');
  await page.getByRole('button', { name: 'Delete setup', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delete setup', exact: true }).click();
  await expect(selector).toHaveValue('');
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles(filePath);
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expect(selector).toHaveValue(id);
  await expect((await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true })).toHaveValue('33');
  await expect(selector.locator('option', { hasText: 'A second point' })).toHaveCount(0);
  await expect(selector).toBeEnabled();
  await page.screenshot({ path: info.outputPath('saved-setups.png') });
  await start(page);
  await expect(selector.locator('option', { hasText: 'Rated operating point' })).toHaveCount(1);
  await selector.selectOption(''); await selector.selectOption(id);
  await expect((await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true })).toHaveValue('33');
  expect(errors).toEqual([]);
});

test('reference setups are immutable, apply complete conditions, and edits save as a user copy', async ({ page }, info) => {
  await start(page);
  const source = new URL('../src/public/examples/prius-2004-loaded-torque-v1.coilem', import.meta.url);
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles({ name: 'Prius.coilem', mimeType: 'application/json', buffer: await readFile(source) });
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  await selector.selectOption('builtin:prius-2004-tutorial-bemf-v1');
  await expect(page.getByRole('button', { name: 'Update setup', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Rename setup', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Delete setup', exact: true })).toHaveCount(0);
  const file = await saveFile(page, info.outputPath('reference.coilem'));
  expect(file.reference_case).toBe('prius-2004-tutorial-bemf-v1');
  expect(file.solve_params.rated_speed_rpm).toBe(1000);
  expect(file.solve_params.current_amplitude_A).toBe(0);
  expect(file.solve_params.current_amplitude_convention).toBe('peak');
  expect(file.solve_params.current_angle_deg).toBe(140);
  expect(file.solve_params.magnet_temperature_C).toBe(20);
  const section = await operating(page);
  await section.getByRole('spinbutton', { name: 'Rated Speed', exact: true }).fill('1100');
  await section.getByRole('spinbutton', { name: 'Rated Speed', exact: true }).press('Tab');
  await expect(page.getByText('Modified from Prius · no-load BEMF reference.', { exact: false })).toBeVisible();
  await section.getByRole('combobox', { name: 'Magnet temp', exact: true }).selectOption('60');
  await page.getByRole('button', { name: 'Save a copy…', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill('My BEMF point');
  await page.getByRole('button', { name: 'Save setup', exact: true }).click();
  await expect(selector).not.toHaveValue(/^builtin:/);
  const copied = await saveFile(page, info.outputPath('reference-copy.coilem'));
  expect(copied.run_setups.profiles[0].includesNumerics).toBe(true);
  expect(copied.run_setups.profiles[0].parameters.rated_speed_rpm).toBe(1100);
  expect(copied.solve_params.magnet_temperature_C).toBe(60);
  expect(copied.reference_case).toBe('prius-2004-loaded-torque-v1');
  expect(copied.solve_params.current_amplitude_A).toBe(0);
  expect(copied.run_setups.profiles[0].builtin).toBeUndefined();
});

test('ordinary setup application preserves accuracy and submits its versioned identity', async ({ page }) => {
  await start(page);
  await saveSetup(page, 'Operating only');
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  const id = await selector.inputValue();
  const accuracy = page.locator('[data-guide="solve-plan"]');
  const accuracyHeader = page.locator('button[aria-controls="param-group-content-plan"]');
  if (await accuracyHeader.getAttribute('aria-expanded') !== 'true') await accuracyHeader.click();
  await accuracy.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
  await selector.selectOption(''); await selector.selectOption(id);
  await expect(accuracy.getByRole('button', { name: /Preview.*Coarse mesh/ })).toHaveAttribute('aria-pressed', 'true');
  await page.route('**/solve/stream', async route => {
    await route.fulfill({ contentType: 'text/event-stream', body: 'event: error\ndata: {"error_code":"PROBE_STOP","message":"Request captured"}\n\n' });
  });
  const request = page.waitForRequest('**/solve/stream');
  await page.getByRole('button', { name: /Run analysis/ }).click();
  const submitted = (await request).postDataJSON();
  expect(submitted.run_setup).toMatchObject({ id, version: 1, name: 'Operating only', kind: 'user', includes_numerics: false });
  expect(submitted.config.solve_params.solve_quality).toBe('quick');
});
