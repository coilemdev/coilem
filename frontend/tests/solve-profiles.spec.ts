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
  await page.getByRole('combobox', { name: 'Run setup', exact: true }).selectOption('');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill(name);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
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
  await expect(page.locator('.public-run-setups').getByRole('button')).toHaveCount(2);
  await page.getByRole('button', { name: 'Save', exact: true }).click(); // Unchanged Save must not create a version.
  await current.fill('33'); await current.press('Tab');
  await expect(page.getByText('Modified from Rated current.', { exact: false })).toBeVisible();
  await selector.selectOption(''); await selector.selectOption(id);
  await expect(current).toHaveValue('22');
  await page.getByRole('textbox', { name: 'Setup name', exact: true }).dblclick();
  await page.getByLabel('Setup name', { exact: true }).fill('Rated operating point');
  await page.getByLabel('Setup name', { exact: true }).press('Enter');
  await current.fill('33'); await current.press('Tab');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const filePath = info.outputPath('setups.coilem');
  const file = await saveFile(page, filePath);
  expect(file.run_setups.activeId).toBe(id);
  expect(file.run_setups.activeVersion).toBe(3);
  expect(file.run_setups.profiles[0].name).toBe('Rated operating point');
  expect(file.solve_params.current_amplitude_A).toBe(33);
  expect(file.run_setups.profiles[0].parameters.mesh_density).toBeUndefined();
  await saveSetup(page, 'A second point');
  await page.getByRole('button', { name: 'Delete', exact: true }).click();
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
  await expect(selector).toHaveValue(id);
  await expect((await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true })).toHaveValue('33');
  await expect(page.getByText('Modified from Rated operating point.', { exact: false })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('inline setup naming supports keyboard, cancellation, blur and one Save for name plus settings', async ({ page }, info) => {
  await start(page);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill('Discard this name');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByLabel('Setup name', { exact: true })).toHaveValue('Custom');
  await saveSetup(page, 'Original');
  const panel = page.locator('.public-run-setups');
  const name = panel.getByRole('textbox', { name: 'Setup name', exact: true });
  const selector = panel.getByRole('combobox', { name: 'Run setup', exact: true });
  const id = await selector.inputValue();
  await name.focus();
  await name.press('F2');
  await name.fill('Cancelled');
  await name.press('Escape');
  await expect(name).toHaveValue('Original');
  await expect(name).toHaveAttribute('readonly', '');
  await name.dblclick();
  await name.fill('Renamed on blur');
  await name.press('Tab');
  await expect(name).toHaveAttribute('readonly', '');
  await expect(name).toHaveValue('Renamed on blur');
  const current = (await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true });
  await current.fill('31'); await current.press('Tab');
  await name.dblclick();
  await name.fill('Combined edit');
  await panel.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(name).toHaveAttribute('readonly', '');
  await panel.getByRole('button', { name: 'Save', exact: true }).click();
  const file = await saveFile(page, info.outputPath('inline-name.coilem'));
  expect(file.run_setups.activeId).toBe(id);
  expect(file.run_setups.activeVersion).toBe(3);
  expect(file.run_setups.profiles).toHaveLength(1);
  expect(file.run_setups.profiles[0].name).toBe('Combined edit');
  expect(file.run_setups.profiles[0].parameters.current_amplitude_A).toBe(31);
  await panel.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(panel.getByRole('button')).toHaveCount(2);
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(selector).toHaveValue(id);
  await expect(name).toHaveValue('Combined edit');
  const picker = await panel.locator('.public-run-setup-picker').boundingBox();
  const save = await panel.getByRole('button', { name: 'Save', exact: true }).boundingBox();
  const remove = await panel.getByRole('button', { name: 'Delete', exact: true }).boundingBox();
  expect(picker && save && remove).toBeTruthy();
  expect(save!.x).toBeGreaterThan(picker!.x + picker!.width);
  expect(remove!.x).toBeGreaterThan(save!.x);
  expect(Math.abs(save!.y - picker!.y)).toBeLessThan(1);
  expect(Math.abs(remove!.y - picker!.y)).toBeLessThan(1);
});

test('reopening the original file restores the last setup including accuracy and advanced settings', async ({ page }, info) => {
  await start(page);
  const original = await saveFile(page, info.outputPath('original.coilem'));
  delete original.run_setups;
  const file = { name: 'original.coilem', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(original)) };
  const open = async (input: typeof file) => {
    await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles(input);
    await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  };
  await open(file);
  const current = (await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true });
  await current.fill('31'); await current.press('Tab');
  await page.locator('button[aria-controls="param-group-content-plan"]').click();
  await page.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
  await page.locator('button[aria-controls="param-group-content-advanced"]').click();
  await page.getByRole('group', { name: 'Nonlinear solver', exact: true }).getByRole('button', { name: 'Newton', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Maximum nonlinear iterations', exact: true }).fill('120');
  await page.getByRole('spinbutton', { name: 'Maximum nonlinear iterations', exact: true }).press('Tab');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill('Newton preview');
  await page.getByRole('checkbox', { name: 'Include accuracy and solver settings', exact: true }).check();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const id = await page.getByRole('combobox', { name: 'Run setup', exact: true }).inputValue();
  await page.reload();
  await open(file);
  await expect(page.getByRole('combobox', { name: 'Run setup', exact: true })).toHaveValue(id);
  await expect(page.getByLabel('Setup name', { exact: true })).toHaveValue('Newton preview');
  await expect((await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true })).toHaveValue('31');
  const exported = await saveFile(page, info.outputPath('restored.coilem'));
  expect(exported.solve_params).toMatchObject({ current_amplitude_A: 31, nonlinear_solver: 'newton',
    solve_quality: 'quick', mesh_density: 'coarse', max_nonlinear_iterations: 120 });
  expect(exported.run_setups.activeId).toBe(id);
  expect(exported.run_setups.activeVersion).toBe(1);
  // A portable file owns edits made after its setup was saved, even in a fresh browser.
  exported.solve_params.current_amplitude_A = 42;
  await page.evaluate(() => localStorage.clear());
  await open({ ...file, buffer: Buffer.from(JSON.stringify(exported)) });
  await expect(page.getByLabel('Setup name', { exact: true })).toHaveValue('Newton preview (Modified)');
  await expect((await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true })).toHaveValue('42');
  // A different design with the same filename must not inherit this library.
  await open({ ...file, buffer: Buffer.from(JSON.stringify({ ...original, name: 'Different motor' })) });
  await expect(page.getByRole('combobox', { name: 'Run setup', exact: true })).toHaveValue('');
  await expect(page.getByRole('combobox', { name: 'Run setup', exact: true }).locator('option', { hasText: 'Newton preview' })).toHaveCount(0);
});

test('reference setups are immutable, apply complete conditions, and edits save as a user copy', async ({ page }, info) => {
  await start(page);
  const source = new URL('../src/public/examples/prius-2004-loaded-torque-v1.coilem', import.meta.url);
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles({ name: 'Prius.coilem', mimeType: 'application/json', buffer: await readFile(source) });
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  await selector.selectOption('builtin:prius-2004-tutorial-bemf-v1');
  await expect(page.getByRole('textbox', { name: 'Setup name', exact: true })).toHaveAttribute('readonly', '');
  await page.getByRole('textbox', { name: 'Setup name', exact: true }).dblclick();
  await expect(page.getByRole('textbox', { name: 'Setup name', exact: true })).toHaveAttribute('readonly', '');
  await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeDisabled();
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
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill('My BEMF point');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
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
