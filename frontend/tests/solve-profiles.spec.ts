import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';

async function start(page: Page) {
  await page.addInitScript(() => Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Run setup', exact: true })).toBeVisible();
}

async function selectSetup(page: Page, value: string | null) {
  if (value === null) throw new Error('A saved setup must have an identity');
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  await selector.click();
  await page.getByRole('listbox', { name: 'Run setup choices', exact: true })
    .locator(`[role="option"][data-value=${JSON.stringify(value)}]`).click();
}
async function expectSetupOption(page: Page, label: string, count: number) {
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  await selector.click();
  await expect(page.getByRole('option', { name: label, exact: false })).toHaveCount(count);
  await selector.press('Escape');
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
async function saveSetup(page: Page, name: string, includeNumerics = true) {
  await selectSetup(page, '');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill(name);
  const numerical = page.getByRole('checkbox', { name: 'Include accuracy and solver settings', exact: true });
  await expect(numerical).toBeChecked();
  if (!includeNumerics) await numerical.uncheck();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
}

test('losses request a full cycle while mesh choices, saved setups and legacy files keep their plan', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await start(page);
  const analysis = page.locator('[data-guide="solve-analysis"]');
  const openAnalysis = async () => {
    const header = page.locator('button[aria-controls="param-group-content-analysis"]');
    if (await header.getAttribute('aria-expanded') !== 'true') await header.click();
  };
  const openPlan = async () => {
    const header = page.locator('button[aria-controls="param-group-content-plan"]');
    if (await header.getAttribute('aria-expanded') !== 'true') await header.click();
  };
  await openAnalysis();
  const losses = analysis.getByRole('checkbox', { name: 'Losses & efficiency', exact: true });
  await losses.check();
  // The rotor-loss option adds its own note under the full-cycle one.
  const fullCycleNote = analysis.getByRole('note').filter({ hasText: 'Full 360°' });
  await expect(fullCycleNote).toHaveText('Full 360° electrical sweep selected for stator losses and efficiency.');
  await openPlan();
  const plan = page.locator('[data-guide="solve-plan"]');
  const planHeader = page.locator('button[aria-controls="param-group-content-plan"]');
  await expect(plan.getByRole('button', { name: /Standard.*Medium mesh/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(plan.getByRole('spinbutton', { name: 'Step Size (° elec)', exact: true })).toHaveCount(0);
  await plan.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
  await expect(plan.getByRole('button', { name: /Preview.*Coarse mesh/ })).toHaveAttribute('aria-pressed', 'true');
  await planHeader.click();
  await expect(planHeader).toContainText('Preview · 360° at 15° for losses');
  await openPlan();
  await plan.getByRole('button', { name: /Standard.*Medium mesh/ }).click();
  const stepToggle = plan.getByRole('button', { name: /Full-cycle step/ });
  if (await stepToggle.getAttribute('aria-expanded') !== 'true') await stepToggle.click();
  const step = plan.getByRole('spinbutton', { name: 'Step Size (° elec)', exact: true });
  await step.fill('30'); await step.press('Tab');
  await saveSetup(page, 'Loss study');
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  const id = await selector.getAttribute('data-value');
  const file = await saveFile(page, info.outputPath('loss-study.coilem'));
  expect(file.solve_params).toMatchObject({ solve_quality: 'custom', rotor_sweep_range_deg: 360, rotor_step_deg: 30, mesh_density: 'normal' });
  expect(file.run_setups.profiles.find((profile: { id: string }) => profile.id === id).parameters.rotor_sweep_range_deg).toBe(360);
  await openAnalysis(); await losses.uncheck();
  await openPlan(); await plan.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
  await selectSetup(page, ''); await selectSetup(page, id);
  await openAnalysis(); await expect(losses).toBeChecked();
  await expect(analysis.getByRole('note').filter({ hasText: 'Full 360°' })).toContainText('360°');
  const legacy = structuredClone(file);
  Object.assign(legacy.solve_params, { solve_quality: 'standard', rotor_sweep_range_deg: 60 });
  legacy.run_setups.scope += '-legacy';
  Object.assign(legacy.run_setups.profiles[0].parameters, { solve_quality: 'standard', rotor_sweep_range_deg: 60 });
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles({ name: 'legacy-losses.coilem', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(legacy)) });
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
  const imported = await saveFile(page, info.outputPath('imported-loss-study.coilem'));
  expect(imported.solve_params).toMatchObject({ solve_quality: 'standard', rotor_sweep_range_deg: 60 }); // Files open as saved.
  expect(imported.run_setups.profiles[0].parameters.rotor_sweep_range_deg).toBe(60); // Saved versions change only on explicit update.
  await page.route('**/solve/stream', route => route.fulfill({ contentType: 'text/event-stream', body: 'event: error\ndata: {"error_code":"PROBE_STOP","message":"Request captured"}\n\n' }));
  const request = page.waitForRequest('**/solve/stream');
  await expect(page.getByRole('button', { name: /Run analysis/ })).toBeEnabled();
  await page.getByRole('button', { name: /Run analysis/ }).click();
  const submitted = (await request).postDataJSON();
  // Standard with Back EMF already solves a full cycle, so the request keeps the file's plan.
  expect(submitted.config.solve_options.back_emf).toBe(true);
  expect(submitted.config.solve_params).toMatchObject({ solve_quality: 'standard', mesh_density: 'normal' });
  expect(submitted.config.solve_options.losses_efficiency).toBe(true);
  expect(submitted.config.solve_options.cogging_torque).toBe(false);
  expect(errors).toEqual([]);
});

test('user setups support save, apply, update, rename, copy, delete and file round-trip', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await start(page);
  const section = await operating(page);
  const current = section.getByRole('spinbutton', { name: 'Phase Current', exact: true });
  await current.fill('22'); await current.press('Tab');
  await saveSetup(page, 'Rated current');
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  const save = page.getByRole('button', { name: 'Save', exact: true });
  const id = await selector.getAttribute('data-value');
  await expect(page.locator('.public-run-setup-actions').getByRole('button')).toHaveCount(2);
  await expect(save).toBeDisabled();
  await current.fill('33'); await current.press('Tab');
  await expect(save).toBeEnabled();
  await current.fill('22'); await current.press('Tab');
  await expect(save).toBeDisabled(); // Reverting the edit must not create a version.
  await current.fill('33'); await current.press('Tab');
  await expect(page.getByText('Modified from Rated current.', { exact: false })).toBeVisible();
  await selectSetup(page, ''); await selectSetup(page, id);
  await expect(current).toHaveValue('22');
  await expect(save).toBeDisabled();
  await page.getByRole('textbox', { name: 'Setup name', exact: true }).dblclick();
  await page.getByLabel('Setup name', { exact: true }).fill('Rated operating point');
  await page.getByLabel('Setup name', { exact: true }).press('Enter');
  await expect(save).toBeDisabled();
  await current.fill('33'); await current.press('Tab');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(save).toBeDisabled();
  await expect(page.getByRole('status').filter({ hasText: 'Updated setup “Rated operating point”.' })).toBeVisible();
  const filePath = info.outputPath('setups.coilem');
  const file = await saveFile(page, filePath);
  expect(file.run_setups.activeId).toBe(id);
  expect(file.run_setups.activeVersion).toBe(3);
  expect(file.run_setups.profiles[0].name).toBe('Rated operating point');
  expect(file.solve_params.current_amplitude_A).toBe(33);
  expect(file.run_setups.profiles[0].includesNumerics).toBe(true);
  expect(file.run_setups.profiles[0].parameters.mesh_density).toBe(file.solve_params.mesh_density);
  await saveSetup(page, 'A second point');
  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delete setup', exact: true }).click();
  await expect(selector).toHaveAttribute('data-value', '');
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles(filePath);
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expect(selector).toHaveAttribute('data-value', id);
  await expect((await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true })).toHaveValue('33');
  await expectSetupOption(page, 'A second point', 0);
  await expect(selector).toBeEnabled();
  await page.screenshot({ path: info.outputPath('saved-setups.png') });
  await start(page);
  await expectSetupOption(page, 'Rated operating point', 1);
  await expect(selector).toHaveAttribute('data-value', id);
  await expect((await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true })).toHaveValue('33');
  await expect(page.getByText('Modified from Rated operating point.', { exact: false })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('inline setup naming supports keyboard, cancellation, blur and one Save for name plus settings', async ({ page }, info) => {
  await start(page);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByLabel('Setup name', { exact: true }).fill('Discard this name');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByLabel('Setup name', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Setup name', { exact: true })).toHaveAttribute('placeholder', 'Setup name');
  await saveSetup(page, 'Original');
  const panel = page.locator('.public-run-setups');
  const name = panel.getByRole('textbox', { name: 'Setup name', exact: true });
  const selector = panel.getByRole('combobox', { name: 'Run setup', exact: true });
  const id = await selector.getAttribute('data-value');
  await name.focus();
  await name.press('F2');
  await name.fill('Cancelled');
  await expect(panel.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
  await name.press('Escape');
  await expect(name).toHaveValue('Original');
  await expect(name).toHaveAttribute('readonly', '');
  await expect(panel.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  await name.dblclick();
  await name.fill('Renamed on blur');
  await name.press('Tab');
  await expect(name).toHaveAttribute('readonly', '');
  await expect(name).toHaveValue('Renamed on blur');
  // The rename stays open while focus is on Save, and ends when focus leaves Save.
  const saveButton = panel.getByRole('button', { name: 'Save', exact: true });
  await name.dblclick();
  await name.fill('Renamed past Save');
  await saveButton.focus();
  await expect(name).not.toHaveAttribute('readonly', '');
  await saveButton.press('Tab');
  await expect(name).toHaveAttribute('readonly', '');
  await expect(name).toHaveValue('Renamed past Save');
  const current = (await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true });
  await current.fill('31'); await current.press('Tab');
  await name.dblclick();
  await name.fill('Combined edit');
  await panel.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(name).toHaveAttribute('readonly', '');
  await expect(panel.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  const file = await saveFile(page, info.outputPath('inline-name.coilem'));
  expect(file.run_setups.activeId).toBe(id);
  expect(file.run_setups.activeVersion).toBe(4);
  expect(file.run_setups.profiles).toHaveLength(1);
  expect(file.run_setups.profiles[0].name).toBe('Combined edit');
  expect(file.run_setups.profiles[0].parameters.current_amplitude_A).toBe(31);
  await panel.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(panel.locator('.public-run-setup-actions').getByRole('button')).toHaveCount(2);
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(selector).toHaveAttribute('data-value', id);
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
  await expect(page.getByRole('checkbox', { name: 'Include accuracy and solver settings', exact: true })).toBeChecked();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const id = await page.getByRole('combobox', { name: 'Run setup', exact: true }).getAttribute('data-value');
  await page.reload();
  await open(file);
  await expect(page.getByRole('combobox', { name: 'Run setup', exact: true })).toHaveAttribute('data-value', id);
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
  await expect(page.getByRole('combobox', { name: 'Run setup', exact: true })).toHaveAttribute('data-value', '');
  await expectSetupOption(page, 'Newton preview', 0);
});

test('reference setups are immutable, apply complete conditions, and edits save as a user copy', async ({ page }, info) => {
  await start(page);
  const source = new URL('../src/public/examples/prius-2004-loaded-torque-v1.coilem', import.meta.url);
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles({ name: 'Prius.coilem', mimeType: 'application/json', buffer: await readFile(source) });
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  await selectSetup(page, 'builtin:prius-2004-tutorial-bemf-v1');
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
  await expect(selector).not.toHaveAttribute('data-value', /^builtin:/);
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
  await saveSetup(page, 'Operating only', false);
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  const id = await selector.getAttribute('data-value');
  const accuracy = page.locator('[data-guide="solve-plan"]');
  const accuracyHeader = page.locator('button[aria-controls="param-group-content-plan"]');
  if (await accuracyHeader.getAttribute('aria-expanded') !== 'true') await accuracyHeader.click();
  await accuracy.getByRole('button', { name: /Preview.*Coarse mesh/ }).click();
  await selectSetup(page, ''); await selectSetup(page, id);
  await expect(accuracy.getByRole('button', { name: /Preview.*Coarse mesh/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled(); // Accuracy was explicitly excluded.
  await page.route('**/solve/stream', async route => {
    await route.fulfill({ contentType: 'text/event-stream', body: 'event: error\ndata: {"error_code":"PROBE_STOP","message":"Request captured"}\n\n' });
  });
  const request = page.waitForRequest('**/solve/stream');
  await page.getByRole('button', { name: /Run analysis/ }).click();
  const submitted = (await request).postDataJSON();
  expect(submitted.run_setup).toMatchObject({ id, version: 1, name: 'Operating only', kind: 'user', includes_numerics: false });
  expect(submitted.config.solve_params.solve_quality).toBe('quick');
});

test('setups saved on an edited example stay with that design, not the example', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await start(page);
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  // An edited copy of the starter, saved with the example's library as earlier versions did.
  const edited = await saveFile(page, info.outputPath('starter.coilem'));
  edited.stator.OD_mm += 2;
  edited.run_setups = { schema: 1, scope: 'example:spm-8p12s', profiles: [], activeId: null, activeVersion: null };
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles({ name: 'edited.coilem', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(edited)) });
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await saveSetup(page, 'Edited point');
  await expectSetupOption(page, 'Edited point', 1);
  const saved = await saveFile(page, info.outputPath('edited-saved.coilem'));
  expect(saved.run_setups.scope).not.toBe('example:spm-8p12s');
  expect(saved.run_setups.profiles.map((profile: { name: string }) => profile.name)).toEqual(['Edited point']);
  await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Reset to example design', exact: true }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expectSetupOption(page, 'Edited point', 0);
  expect(errors).toEqual([]);
});

test('a second window picks up setups saved in the first before storing its own', async ({ page, context }) => {
  await start(page);
  const other = await context.newPage();
  await start(other);
  await saveSetup(page, 'From window A');
  const otherSelector = other.getByRole('combobox', { name: 'Run setup', exact: true });
  await expectSetupOption(other, 'From window A', 1);
  await saveSetup(other, 'From window B');
  await expectSetupOption(page, 'From window B', 1);
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('coilem.run-setups.v1:example:spm-8p12s') ?? 'null'));
  expect(stored.profiles.map((profile: { name: string }) => profile.name).sort()).toEqual(['From window A', 'From window B']);
  await other.close();
});

test('setup libraries follow the design through Reset and the rotor-arrangement switch', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await start(page);
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  const current = async () => (await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true });
  await (await current()).fill('22'); await (await current()).press('Tab');
  await saveSetup(page, 'Starter point');
  const starterId = await selector.getAttribute('data-value');
  await (await current()).fill('30'); await (await current()).press('Tab');
  // Reset returns the starter with its active setup applied, as a reload does.
  await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Reset to example design', exact: true }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expect(selector).toHaveAttribute('data-value', starterId);
  await expect(await current()).toHaveValue('22');
  // A design opened from a file keeps its own library through Outrunner and back.
  const original = await saveFile(page, info.outputPath('starter.coilem'));
  delete original.run_setups;
  await page.locator('input[type="file"][accept*=".coilem"]').setInputFiles({ name: 'other.coilem', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ ...original, name: 'Other motor' })) });
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expectSetupOption(page, 'Starter point', 0);
  await saveSetup(page, 'File point');
  const fileId = await selector.getAttribute('data-value');
  await page.getByRole('button', { name: '← Back to Design', exact: true }).click();
  const arrangement = page.getByRole('group', { name: 'Rotor arrangement', exact: true });
  await arrangement.getByRole('button', { name: /Outrunner/ }).click();
  await expect(arrangement.getByRole('button', { name: /Outrunner/ })).toHaveAttribute('aria-pressed', 'true');
  await arrangement.getByRole('button', { name: /Inrunner/ }).click();
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
  await expect(selector).toHaveAttribute('data-value', fileId);
  await expectSetupOption(page, 'Starter point', 0);
  expect(errors).toEqual([]);
});

test('New setup accepts direct keyboard naming without first pressing Save', async ({ page }, info) => {
  await start(page);
  const name = page.getByRole('textbox', { name: 'Setup name', exact: true });
  await expect(name).toHaveAttribute('placeholder', 'Setup name');
  await expect(name).toBeEditable();
  await name.click();
  await name.pressSequentially('High Speed', { delay: 40 });
  await expect(name).toHaveValue('High Speed');
  await expect(name).toBeFocused();
  await expect(page.getByRole('checkbox', { name: 'Include accuracy and solver settings', exact: true })).toBeChecked();
  await name.press('Enter');
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  await expect(selector).not.toHaveAttribute('data-value', '');
  await expect(name).toHaveValue('High Speed');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  const file = await saveFile(page, info.outputPath('typed-setup.coilem'));
  expect(file.run_setups.profiles[0].name).toBe('High Speed');
  await selectSetup(page, '');
  await name.click(); await name.pressSequentially('Discard me'); await name.press('Escape');
  await expect(name).toHaveValue('');
  await expect(name).toHaveAttribute('placeholder', 'Setup name');
  await expect(selector).toBeEnabled();
});

test('run setup menu matches the app and supports keyboard selection, cancellation and narrow screens', async ({ page }, info) => {
  await start(page);
  await saveSetup(page, 'Base');
  const current = (await operating(page)).getByRole('spinbutton', { name: 'Phase Current', exact: true });
  await current.fill('45'); await current.press('Tab');
  await saveSetup(page, 'High speed');
  const selector = page.getByRole('combobox', { name: 'Run setup', exact: true });
  const highId = await selector.getAttribute('data-value');
  const menu = page.getByRole('listbox', { name: 'Run setup choices', exact: true });
  await selector.click();
  await expect(menu).toBeVisible();
  await expect(menu.getByRole('option', { name: 'New setup…', exact: true })).toBeVisible();
  await expect(menu.getByRole('group', { name: 'Your setups', exact: true })).toBeVisible();
  await expect(menu.getByRole('option', { name: 'High speed', exact: true })).toHaveAttribute('aria-selected', 'true');
  await menu.screenshot({ path: info.outputPath('run-setup-menu.png') });
  await selector.press('Home');
  await expect(selector).toHaveAttribute('aria-activedescendant', await menu.getByRole('option', { name: 'New setup…', exact: true }).getAttribute('id'));
  await selector.press('Escape');
  await expect(menu).toHaveCount(0); await expect(selector).toBeFocused();
  await expect(selector).toHaveAttribute('data-value', highId);
  await expect(current).toHaveValue('45');
  await selector.press('b'); await selector.press('Enter');
  await expect(page.getByRole('textbox', { name: 'Setup name', exact: true })).toHaveValue('Base');
  await expect(current).toHaveValue('30');
  await expect(selector).toBeEnabled();
  await selector.press('ArrowDown'); await expect(menu).toBeVisible();
  await selector.press('End');
  await expect(selector).toHaveAttribute('aria-activedescendant', await menu.getByRole('option', { name: 'High speed', exact: true }).getAttribute('id'));
  await selector.press('Tab');
  await expect(page.getByRole('textbox', { name: 'Setup name', exact: true })).toHaveValue('High speed');
  await expect(current).toHaveValue('45');
  await selector.click(); await page.getByText('Run setup', { exact: true }).click();
  await expect(menu).toHaveCount(0); await expect(selector).toHaveAttribute('data-value', highId);
  await page.setViewportSize({ width: 600, height: 700 });
  await selector.click(); await expect(menu).toBeInViewport();
  const box = await menu.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(12); expect(box!.x + box!.width).toBeLessThanOrEqual(588);
  expect(box!.y).toBeGreaterThanOrEqual(12); expect(box!.y + box!.height).toBeLessThanOrEqual(688);
  await menu.screenshot({ path: info.outputPath('run-setup-menu-narrow.png') });
  await selector.press('Home'); await selector.press('Enter');
  const name = page.getByRole('textbox', { name: 'Setup name', exact: true });
  await expect(name).toHaveValue(''); await expect(name).toHaveAttribute('placeholder', 'Setup name'); await expect(name).toBeFocused();
  await expect(current).toHaveValue('45'); // New setup preserves the current settings.
});
