import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

import { chooseSetup, newDesign, stator, rotor, health, configureSection, continueSetup, completeWinding } from './design-helpers';

test('progressive arrangement hover previews explain both motors without selecting one', async ({ page }, info) => {
  await newDesign(page, 'Inrunner', false);
  const arrangement = page.getByRole('group', { name: 'Rotor arrangement', exact: true });
  const inner = arrangement.getByRole('button', { name: /Inrunner/ });
  const outer = arrangement.getByRole('button', { name: /Outrunner/ });
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await inner.hover();
  const preview = page.getByRole('tooltip');
  await expect(preview).toBeInViewport();
  await expect(preview.getByRole('heading', { name: 'Inrunner', exact: true })).toBeVisible();
  await expect(preview.getByRole('img')).toHaveAccessibleName(/fixed outer stator, rotating inner rotor, magnets on the rotor’s outer face/);
  await expect(preview.locator('[data-part="magnet"]')).toHaveCount(8);
  await expect(preview.locator('[data-part="stator-tooth"]')).toHaveCount(12);
  for (const label of ['Stator', 'Rotor', 'Magnets']) await expect(preview.getByText(label, { exact: true })).toBeVisible();
  await expect(arrangement.locator('[aria-pressed="true"]')).toHaveCount(0);
  await preview.hover();
  await page.waitForTimeout(250); // Remains hoverable beyond the delayed-close interval.
  await expect(preview).toBeVisible();
  await page.screenshot({ path: info.outputPath('arrangement-inrunner-preview.png') });
  await outer.hover();
  await expect(preview.getByRole('heading', { name: 'Outrunner', exact: true })).toBeVisible();
  await expect(preview.getByRole('img')).toHaveAccessibleName(/fixed inner stator, rotating outer rotor, magnets on the rotor’s inner face/);
  await expect(preview.locator('[data-part="magnet"]')).toHaveCount(8);
  await expect(preview.locator('[data-part="stator-tooth"]')).toHaveCount(12);
  await expect(arrangement.locator('[aria-pressed="true"]')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('arrangement-outrunner-preview.png') });
  await page.setViewportSize({ width: 760, height: 480 });
  await outer.hover();
  await expect.poll(async () => {
    const box = await preview.boundingBox();
    return Boolean(box && box.x >= 12 && box.y >= 12 && box.x + box.width <= 748 && box.y + box.height <= 468);
  }).toBe(true);
  await outer.click();
  await expect(preview).toHaveCount(0);
  await expect(outer).toHaveAttribute('aria-pressed', 'true');
});

test('progressive arrangement previews support keyboard focus and Escape without changing selection', async ({ page }) => {
  await newDesign(page, 'Inrunner', false);
  const arrangement = page.getByRole('group', { name: 'Rotor arrangement', exact: true });
  await expect(arrangement.getByRole('button', { name: /Inrunner/ })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(arrangement.getByRole('button', { name: /Outrunner/ })).toBeFocused();
  await expect(page.getByRole('tooltip').getByRole('heading', { name: 'Outrunner', exact: true })).toBeVisible();
  await expect(arrangement.locator('[aria-pressed="true"]')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await page.keyboard.press('Shift+Tab');
  await expect(page.getByRole('tooltip').getByRole('heading', { name: 'Inrunner', exact: true })).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await expect(arrangement.getByRole('button', { name: /Inrunner/ })).toHaveAttribute('aria-pressed', 'true');
});

test('progressive topology and IPM layout previews show surface, flat and paired V magnets without selecting them', async ({ page }, info) => {
  await newDesign(page, 'Inrunner', false);
  const arrangement = page.getByRole('group', { name: 'Rotor arrangement', exact: true });
  await arrangement.getByRole('button', { name: /Inrunner/ }).click();
  const topology = page.locator('[data-guide="topology-selector"]');
  const spm = topology.getByRole('button', { name: /^SPM/ });
  const ipm = topology.getByRole('button', { name: /^IPM/ });
  const preview = page.getByRole('tooltip');
  await spm.hover();
  await expect(preview.getByRole('heading', { name: 'SPM', exact: true })).toBeVisible();
  await expect(preview.getByRole('img')).toHaveAttribute('data-topology', 'SPM');
  await expect(preview.getByRole('img')).toHaveAccessibleName(/magnets on the rotor’s outer face/);
  await expect(preview.locator('[data-part="magnet"]')).toHaveCount(8);
  await expect(preview.locator('[data-part="stator-tooth"]')).toHaveCount(12);
  await expect(topology.locator('[aria-pressed="true"]')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('topology-spm-preview.png') });
  await ipm.hover();
  await expect(preview.getByRole('heading', { name: 'IPM · flat buried', exact: true })).toBeVisible();
  await expect(preview.getByRole('img')).toHaveAttribute('data-ipm-layout', 'flat_buried');
  await expect(preview.getByRole('img')).toHaveAccessibleName(/one straight tangential magnet bar per pole enclosed in rotor steel/);
  await expect(preview.locator('rect[data-part="magnet"]')).toHaveCount(8);
  for (const label of ['Stator', 'Rotor', 'Magnets']) await expect(preview.getByText(label, { exact: true })).toBeVisible();
  await expect(topology.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(page.getByRole('group', { name: 'IPM rotor layout', exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('topology-ipm-preview.png') });
  await ipm.click();
  await expect(preview).toHaveCount(0);
  const layouts = page.getByRole('group', { name: 'IPM rotor layout', exact: true });
  const flat = layouts.getByRole('button', { name: /^Flat/ });
  const v = layouts.getByRole('button', { name: /^V-shape/ });
  await flat.hover();
  await expect(preview.getByRole('img')).toHaveAttribute('data-ipm-layout', 'flat_buried');
  await expect(preview.locator('rect[data-part="magnet"]')).toHaveCount(8);
  await expect(layouts.locator('[aria-pressed="true"]')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('layout-flat-buried-preview.png') });
  await v.hover();
  await expect(preview.getByRole('heading', { name: 'IPM · V-shape', exact: true })).toBeVisible();
  await expect(preview.getByRole('img')).toHaveAttribute('data-ipm-layout', 'v_shape');
  await expect(preview.getByRole('img')).toHaveAccessibleName(/two angled magnets per pole forming a V enclosed in rotor steel/);
  await expect(preview.locator('[data-pole]')).toHaveCount(8);
  await expect(preview.locator('polygon[data-part="magnet"]')).toHaveCount(16);
  await expect(layouts.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(stator(page)).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('layout-v-shaped-preview.png') });
  // Programmatic first-row focus stays quiet; deliberate keyboard focus explains
  // the second layout, and Enter is still required to choose it.
  await expect(flat).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(v).toBeFocused();
  await expect(preview.getByRole('heading', { name: 'IPM · V-shape', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(preview).toHaveCount(0);
  await expect(layouts.locator('[aria-pressed="true"]')).toHaveCount(0);
  await page.keyboard.press('Enter');
  await expect(v).toHaveAttribute('aria-pressed', 'true');
  await expect(preview).toHaveCount(0);
  await expect(stator(page)).toBeVisible();
  await arrangement.getByRole('button', { name: /Outrunner/ }).click();
  await spm.hover();
  await expect(preview.getByRole('img')).toHaveAttribute('data-arrangement', 'outer');
  await expect(preview.getByRole('img')).toHaveAccessibleName(/magnets on the rotor’s inner face/);
  await expect(ipm).toBeDisabled();
});

test('progressive incomplete geometry does not flash a retry button after preview failures or edits', async ({ page }) => {
  await newDesign(page);
  await page.route((url) => url.pathname === '/preview', (route) => route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Stator geometry is incomplete.' }) }));
  const failedPreview = (yoke?: number) => page.waitForResponse((r) => new URL(r.url()).pathname === '/preview'
    && r.status() === 422 && r.request().postDataJSON()?.stator?.OD_mm === 48
    && (yoke === undefined || r.request().postDataJSON()?.stator?.yoke_thickness_mm === yoke));
  const odResponse = failedPreview();
  await stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true }).fill('48');
  await odResponse;
  await expect(page.getByRole('button', { name: 'Retry geometry preview', exact: true })).toHaveCount(0);
  const yokeResponse = failedPreview(5.8);
  await stator(page).getByRole('spinbutton', { name: 'Yoke Thickness', exact: true }).fill('5.8');
  await yokeResponse;
  await expect(page.getByRole('button', { name: 'Retry geometry preview', exact: true })).toHaveCount(0);
  await expect(stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: /^Continue Setup: Tooth/ })).toBeDisabled();
});

test('progressive physical scale follows OD auto-fit, zoom, resize and view reset', async ({ page }, info) => {
  await newDesign(page);
  const scale = page.getByRole('img', { name: /^View scale:/ });
  await expect(scale).toHaveCount(0);
  const od = stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true });
  const pixelsPerMm = async () => Number(await scale.getAttribute('data-pixels-per-mm'));
  const expectedFit = async (diameter: number, zoom = 1) => {
    const box = await page.locator('canvas.motor-canvas').boundingBox();
    if (!box) throw new Error('Motor canvas is not visible');
    return Math.min(box.width, box.height) * 0.85 / diameter * zoom;
  };
  const accurate = async (diameter: number, zoom = 1) => {
    await expect.poll(async () => Math.abs(await pixelsPerMm() - await expectedFit(diameter, zoom))).toBeLessThan(0.001);
    const measured = await scale.evaluate((el) => ({
      lengthMm: Number(el.getAttribute('data-mm')),
      pxPerMm: Number(el.getAttribute('data-pixels-per-mm')),
      renderedPixels: el.querySelector('svg')!.getBoundingClientRect().width - 2,
    }));
    // Chromium lays out SVG widths on a 1/64 CSS-pixel grid.
    expect(Math.abs(measured.renderedPixels - measured.lengthMm * measured.pxPerMm)).toBeLessThan(0.02);
  };
  await od.fill('100');
  await expect(scale).toBeInViewport();
  await expect(scale).toContainText('Auto-fit');
  await accurate(100);
  await stator(page).getByRole('spinbutton', { name: 'Yoke Thickness', exact: true }).fill('5.8');
  await accurate(100);
  const original = await pixelsPerMm();
  await page.screenshot({ path: info.outputPath('scale-100mm.png') });
  await od.fill('200');
  await accurate(200);
  expect(await pixelsPerMm()).toBeCloseTo(original / 2, 4);
  await page.screenshot({ path: info.outputPath('scale-200mm.png') });
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await accurate(200, 1.25);
  await expect(scale).toContainText('View scale');
  await page.setViewportSize({ width: 1260, height: 760 });
  await accurate(200, 1.25);
  const box = await scale.boundingBox();
  const canvas = await page.locator('canvas.motor-canvas').boundingBox();
  expect(box && canvas && box.x >= canvas.x && box.y >= canvas.y && box.x + box.width <= canvas.x + canvas.width && box.y + box.height <= canvas.y + canvas.height).toBe(true);
  await page.getByRole('button', { name: /^Fit .* to view$/ }).click();
  await accurate(200);
  await expect(scale).toContainText('Auto-fit');
});

test('progressive New Design requires arrangement and topology, then deliberate blank field entry', async ({ page }, info) => {
  await newDesign(page, 'Inrunner', false);
  const arrangement = page.getByRole('group', { name: 'Rotor arrangement', exact: true });
  const topology = page.locator('[data-guide="topology-selector"]');
  await expect(arrangement.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(topology.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(topology.getByRole('button', { name: /^SPM/ })).toBeDisabled();
  await expect(stator(page)).toHaveCount(0);
  await expect(page.locator('.viewport-label-cad')).toHaveText('New Design');
  await page.screenshot({ path: info.outputPath('new-design-unselected.png') });
  await arrangement.getByRole('button', { name: /Inrunner/ }).click();
  await expect(topology.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(stator(page)).toHaveCount(0);
  await topology.getByRole('button', { name: /^SPM/ }).click();
  for (const input of await stator(page).getByRole('spinbutton').all()) await expect(input).toHaveValue('');
  const next = page.getByRole('button', { name: /^Continue Setup: Tooth/ });
  await expect(next).toBeDisabled();
  await stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true }).fill('150');
  const readout = page.getByRole('status', { name: 'Active geometry dimension', exact: true });
  await expect(page.locator('.public-stator-construction-readout')).toHaveCount(0);
  await expect(readout).toContainText('Stator Ø 150.0 mm');
  await expect(page.locator('canvas.motor-canvas')).toHaveAttribute('data-editing-dimension', 'stator-od');
  await expect(stator(page).getByRole('spinbutton', { name: 'Bore Diameter (ID)', exact: true })).toHaveValue('');
  await stator(page).getByRole('spinbutton', { name: 'Yoke Thickness', exact: true }).fill('8');
  await expect(readout).toContainText('Yoke thickness 8.0 mm');
  await expect(page.locator('canvas.motor-canvas')).toHaveAttribute('data-editing-dimension', 'yoke-thickness');
  await stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true }).fill('12');
  await stator(page).getByRole('spinbutton', { name: 'Bore Diameter (ID)', exact: true }).fill('100');
  await expect(next).toBeDisabled();
  await page.screenshot({ path: info.outputPath('new-design-blank-values.png') });
  await stator(page).getByRole('spinbutton', { name: 'Stack Length', exact: true }).fill('50');
  await next.click();
  const teeth = page.locator('[data-guide="section-advanced"]');
  await expect(teeth.getByRole('group', { name: 'Tooth Profile', exact: true }).locator('[aria-pressed="true"]')).toHaveCount(0);
  for (const input of await teeth.getByRole('spinbutton').all()) await expect(input).not.toHaveValue('');
  await expect(teeth.locator('.public-param-field-error')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Continue Setup: Rotor/ })).toBeDisabled();
});

test('progressive topology choices are explicit for outrunner and IPM layouts', async ({ page }) => {
  await newDesign(page, 'Outrunner', false);
  const arrangement = page.getByRole('group', { name: 'Rotor arrangement', exact: true });
  const topology = page.locator('[data-guide="topology-selector"]');
  await arrangement.getByRole('button', { name: /Outrunner/ }).click();
  await expect(topology.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(topology.getByRole('button', { name: /^IPM/ })).toBeDisabled();
  await topology.getByRole('button', { name: /^SPM/ }).click();
  await expect(stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true })).toHaveValue('');
  await arrangement.getByRole('button', { name: /Inrunner/ }).click();
  await expect(topology.locator('[aria-pressed="true"]')).toHaveCount(0);
  await topology.getByRole('button', { name: /^IPM/ }).click();
  const ipm = page.getByRole('group', { name: 'IPM rotor layout', exact: true });
  await expect(ipm.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(stator(page)).toHaveCount(0);
  await ipm.getByRole('button', { name: /Flat \/ buried/ }).click();
  await expect(stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true })).toBeFocused();
  await expect(stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true })).toHaveValue('');
});

for (const layout of [{ name: 'V-IPM', button: /^V-shape/ }, { name: 'flat-IPM', button: /^Flat/ }]) {
test(`progressive ${layout.name} stator geometry and tooth dimensions follow the entered values`, async ({ page }, info) => {
  await newDesign(page, 'Inrunner', false);
  await page.getByRole('group', { name: 'Rotor arrangement', exact: true }).getByRole('button', { name: /Inrunner/ }).click();
  await page.locator('[data-guide="topology-selector"]').getByRole('button', { name: /^IPM/ }).click();
  await page.getByRole('group', { name: 'IPM rotor layout', exact: true }).getByRole('button', { name: layout.button }).click();
  const pending = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.stator?.ID_mm === 70 && r.request().postDataJSON()?.stator?.slot_count === 21);
  for (const [name, value] of [['Outer Diameter', '150'], ['Yoke Thickness', '10'], ['Slot Count', '21'], ['Bore Diameter (ID)', '70'], ['Stack Length', '100']]) {
    await stator(page).getByRole('spinbutton', { name, exact: true }).fill(value);
  }
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  const preview = await response.json();
  const teeth = preview.regions.filter((r: { region_type: string }) => r.region_type === 'stator_tooth');
  expect(teeth).toHaveLength(21);
  expect(Math.min(...teeth.flatMap((r: { points: [number, number][] }) => r.points.map(([x, y]) => Math.hypot(x, y)))) * 2).toBeCloseTo(70, 5);
  await stator(page).getByRole('spinbutton', { name: 'Bore Diameter (ID)', exact: true }).focus();
  await expect(page.getByRole('status', { name: 'Active geometry dimension', exact: true })).toContainText('Bore Ø 70.0 mm');
  await page.screenshot({ path: info.outputPath(`${layout.name.toLowerCase()}-bore-70mm.png`) });
  await continueSetup(page, 'Tooth');
  const section = page.locator('[data-guide="section-advanced"]');
  await expect(section.locator('input[aria-label="V Angle"], input[aria-label="V Depth"]')).toHaveCount(0);
  await section.getByRole('button', { name: 'Tooth shoes', exact: true }).click();
  await section.getByRole('spinbutton', { name: 'Shoe Height', exact: true }).fill('1');
  await section.getByRole('spinbutton', { name: 'Shoe Overhang', exact: true }).fill('0.5');
  await section.getByRole('spinbutton', { name: 'Bore Tooth Width', exact: true }).fill('4.8');
  const widthsReady = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.stator?.tooth_width_mm === 4.1);
  await section.getByRole('spinbutton', { name: 'Yoke Tooth Width', exact: true }).fill('4.1');
  const widths = await widthsReady;
  expect(widths.status(), await widths.text()).toBe(200);
  const payload = await widths.json();
  expect(payload.metadata.bore_tooth_width_mm).toBeCloseTo(4.8, 5);
  expect(payload.metadata.tooth_width_at_yoke_mm).toBeCloseTo(4.1, 5);
  const dimension = page.getByRole('status', { name: 'Active geometry dimension', exact: true });
  await expect(dimension).toHaveText(/Yoke tooth 4\.10? mm/);
  await page.screenshot({ path: info.outputPath(`${layout.name.toLowerCase()}-yoke-tooth-4.1mm.png`) });
  await section.getByRole('spinbutton', { name: 'Bore Tooth Width', exact: true }).focus();
  await expect(dimension).toHaveText(/Bore tooth 4\.80? mm/);
  await page.screenshot({ path: info.outputPath(`${layout.name.toLowerCase()}-bore-tooth-4.8mm.png`) });
  if (layout.name === 'V-IPM') {
    // Tooth setup completes independently of V-pocket settings. Rotor setup
    // starts at Pole Count, with the V controls after the magnet dimensions.
    await continueSetup(page, 'Rotor');
    await expect(rotor(page).getByRole('spinbutton', { name: 'Pole Count', exact: true })).toBeFocused();
    const rotorLabels = await rotor(page).locator('.public-param-row:has(input)').evaluateAll((rows) => rows.map((row) => row.querySelector('.param-label')?.firstChild?.textContent));
    expect(rotorLabels).toEqual(['Pole Count', 'Rotor OD', 'Magnet Thick.', 'Magnet Width', 'V Angle', 'V Depth']);
    const vAngle = rotor(page).getByRole('spinbutton', { name: 'V Angle', exact: true });
    const vDepth = rotor(page).getByRole('spinbutton', { name: 'V Depth', exact: true });
    await expect(vAngle).toHaveValue('');
    await expect(vDepth).toHaveValue('');
    const beforePocket = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview'
      && new URL(r.url()).searchParams.has('diagnostic') && r.request().postDataJSON()?.rotor?.magnet_width_mm === 12);
    for (const [name, value] of [['Pole Count', '8'], ['Rotor OD', '58'], ['Magnet Thick.', '4'], ['Magnet Width', '12']]) {
      await rotor(page).getByRole('spinbutton', { name, exact: true }).fill(value);
    }
    const initialRotor = await beforePocket;
    expect(initialRotor.status()).toBe(200);
    expect((await initialRotor.json()).regions.filter((region: { region_type: string }) => region.region_type.startsWith('magnet_'))).toHaveLength(16);
    await expect(rotor(page).getByRole('button', { name: /^Continue Setup: Winding/ })).toBeDisabled();
    // Search follows the controls into their new section without losing entries.
    const search = page.getByPlaceholder('Search slot, magnet, turns…');
    await search.fill('v depth');
    await expect(vDepth).toBeVisible();
    await expect(page.locator('[data-guide="section-advanced"]')).toHaveCount(0);
    await search.fill('');
    // Entering the same numeric defaults must still confirm the controls and
    // request full geometry. A real pocket error belongs to this Rotor section.
    const rotorReady = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview'
      && !new URL(r.url()).searchParams.has('stator_only') && r.request().postDataJSON()?.rotor?.magnet_width_mm === 12);
    await vAngle.fill('40');
    await vDepth.fill('30');
    const rejected = await rotorReady;
    expect(rejected.status()).toBe(200);
    expect((await rejected.json()).metadata.diagnostic_only).toBe(true);
    await expect(health(page).getByRole('alert').filter({ hasText: 'V Depth needs attention' }).first()).toBeVisible();
    await expect(vDepth.locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('pocket');
    await expect(rotor(page).locator('.param-group-header')).toHaveClass(/status-attention/);
    await expect(dimension).toContainText('V Depth 30.0 mm');
    await expect(page.locator('.viewport-preview-note')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('v-ipm-pocket-error.png') });
  }
});
}

test('progressive repeated New Design replaces the workspace instead of retaining old sidebars', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && /same key|duplicate.*key/i.test(message.text())) errors.push(message.text());
  });
  await newDesign(page);
  for (let cycle = 0; cycle < 4; cycle += 1) {
    await expect(page.locator('.public-parameter-panel')).toHaveCount(1);
    await expect(page.locator('.public-motor-viewport')).toHaveCount(1);
    await expect(page.locator('.design-health-panel')).toHaveCount(1);
    const diameter = stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true });
    await expect(diameter).toHaveValue('');
    await expect(diameter).toBeFocused();
    await expect(health(page)).toContainText('0 of 6 parts drawn');
    await diameter.fill(String(130 + cycle));
    await continueSetup(page, 'Tooth');
    await continueSetup(page, 'Rotor');
    await continueSetup(page, 'Winding');
    const turns = page.locator('[data-guide="section-winding"]').getByRole('spinbutton', { name: 'Turns / Coil', exact: true });
    await turns.fill('100');
    if (cycle === 1) await turns.fill(''); // An invalid draft must not survive the reset.
    if (cycle === 2) {
      await page.getByRole('button', { name: 'Collapse design health', exact: true }).click();
      await page.getByRole('button', { name: 'Expand motor view', exact: true }).click();
    }
    await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
    await page.getByRole('menuitem', { name: 'New Design', exact: true }).click();
    await expect(page.locator('.public-parameter-panel')).toHaveCount(1);
    await expect(page.locator('.design-workspace')).not.toHaveClass(/is-viewport-expanded/);
    await expect(health(page)).not.toHaveClass(/is-collapsed/);
    await expect(health(page).locator('.public-health-attention .severity-error')).toHaveCount(0);
    await expect(page.getByPlaceholder('Search slot, magnet, turns…')).toHaveValue('');
    await chooseSetup(page);
  }
  await expect(stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true })).toBeFocused();
  await expect(health(page)).toContainText('0 of 6 parts drawn');
  await page.screenshot({ path: info.outputPath('repeated-new-design.png') });
  expect(errors).toEqual([]);
});

test('progressive order, section focus and shoe limit explain the construction flow', async ({ page }, info) => {
  await newDesign(page);
  const outer = stator(page).getByRole('spinbutton', { name: /Outer Diameter/ });
  await expect(outer).toBeFocused();
  const labels = await stator(page).locator('.public-param-row:has(input)').evaluateAll((rows) => rows.map((row) => row.querySelector('.param-label')?.firstChild?.textContent));
  expect(labels).toEqual(['Outer Diameter', 'Yoke Thickness', 'Slot Count', 'Bore Diameter (ID)', 'Stack Length']);
  await outer.fill('150');
  await stator(page).getByRole('spinbutton', { name: /Bore Diameter/ }).fill('100');
  await continueSetup(page, 'Tooth');
  const profile = page.getByRole('group', { name: 'Tooth Profile', exact: true });
  await expect(profile.getByRole('button', { name: 'Plain', exact: true })).toBeFocused();
  const teeth = page.locator('[data-guide="section-advanced"]');
  const boreTooth = teeth.getByRole('spinbutton', { name: /Bore Tooth Width/ });
  await expect(boreTooth.locator('xpath=ancestor::label')).toHaveCSS('opacity', '0.6');
  await profile.getByRole('button', { name: 'Tooth shoes', exact: true }).click();
  await boreTooth.fill('21.6'); // The exact 6.08 mm opening permits 2.9 mm per side in 0.1 mm steps.
  const overhang = teeth.getByRole('spinbutton', { name: /Shoe Overhang/ });
  await expect(overhang).toHaveAttribute('max', '2.9');
  const updated = page.waitForResponse((response) => new URL(response.url()).pathname === '/preview'
    && response.request().postDataJSON()?.stator?.tooth_shoe_overhang_mm === 2.9);
  await overhang.fill('3.5');
  await expect(overhang).toHaveValue('2.9');
  const alert = health(page).locator('.public-health-attention .severity-warning').filter({ hasText: 'Shoe Overhang needs attention' });
  await expect(alert.locator('.design-health-issue-title')).toHaveText('Shoe Overhang needs attention');
  const advisory = overhang.locator('xpath=ancestor::label').locator('.public-param-field-warning');
  await expect(advisory).toContainText('Maximum 2.9 mm per side');
  await expect(advisory).toContainText('0.28 mm of slot mouth remains');
  await expect(advisory).toContainText('adjacent tooth shoes');
  const warningBox = await advisory.boundingBox();
  const inputBox = await overhang.boundingBox();
  expect(warningBox && inputBox && warningBox.y >= inputBox.y + inputBox.height).toBe(true);
  await overhang.press('ArrowUp');
  await expect(overhang).toHaveValue('2.9');
  await expect(alert).toBeVisible();
  const response = await updated;
  expect(response.status(), await response.text()).toBe(200);
  expect((await response.json()).regions.filter((region: { region_type: string }) => region.region_type === 'stator_tooth')).toHaveLength(12);
  await expect(alert).not.toContainText('Updating the drawing');
  await page.screenshot({ path: info.outputPath('shoe-overhang-limit.png') });
  await overhang.fill('2.5');
  await expect(alert).toHaveCount(0);
  await continueSetup(page, 'Rotor');
  await expect(rotor(page).getByRole('spinbutton', { name: 'Pole Count', exact: true })).toBeFocused();
  await expect(rotor(page).getByRole('spinbutton', { name: /Rotor OD/ }).locator('xpath=ancestor::label')).toHaveCSS('opacity', '0.6');
  await continueSetup(page, 'Winding');
  await expect(page.locator('[data-guide="section-winding"]').getByRole('group', { name: 'Type', exact: true }).getByRole('button', { name: 'Concentrated', exact: true })).toBeFocused();
});

test('progressive confirmed magnets preserve coverage when pole count changes', async ({ page }, info) => {
  await newDesign(page);
  await stator(page).getByRole('spinbutton', { name: /Outer Diameter/ }).fill('150');
  await stator(page).getByRole('spinbutton', { name: /Bore Diameter/ }).fill('90');
  await stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true }).fill('15');
  await continueSetup(page, 'Tooth');
  await continueSetup(page, 'Rotor');
  const poleCount = rotor(page).getByRole('spinbutton', { name: 'Pole Count', exact: true });
  const rendered = page.waitForResponse((response) => new URL(response.url()).pathname === '/preview'
    && response.request().postDataJSON()?.rotor?.pole_count === 6);
  await poleCount.fill('6');
  const response = await rendered;
  expect(response.status(), await response.text()).toBe(200);
  const preview = await response.json();
  expect(preview.regions.filter((region: { region_type: string }) => region.region_type.startsWith('magnet_'))).toHaveLength(6);
  await configureSection(page, 'rotor');
  await expect(health(page)).toContainText('5 of 6 parts drawn');
  await expect(health(page)).toContainText('Winding needs attention');
  await expect(page.locator('.viewport-preview-note')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeDisabled();
  const thickness = rotor(page).getByRole('spinbutton', { name: /Magnet Thick/ });
  const od = rotor(page).getByRole('spinbutton', { name: /Rotor OD/ });
  const width = rotor(page).getByRole('spinbutton', { name: /Magnet Width/ });
  const expectedWidth = 2 * Math.PI * (Number(await od.inputValue()) / 2 + Number(await thickness.inputValue()) / 2) / 6 * 0.75;
  await expect.poll(async () => Number(await width.inputValue())).toBeCloseTo(expectedWidth, 5);
  const oldWidth = Number(await width.inputValue());
  const nextPreview = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.rotor?.pole_count === 10);
  await poleCount.fill('10');
  const nextResponse = await nextPreview;
  expect(nextResponse.status()).toBe(200);
  expect((await nextResponse.json()).regions.filter((r: { region_type: string }) => r.region_type.startsWith('magnet_'))).toHaveLength(10);
  await expect.poll(async () => Number(await width.inputValue()) / oldWidth).toBeCloseTo(0.6, 5);
  // Focus styling moves to the clicked row; dimmed inputs remain usable.
  await poleCount.focus();
  await expect(poleCount.locator('xpath=ancestor::label')).toHaveCSS('opacity', '1');
  await expect(thickness.locator('xpath=ancestor::label')).toHaveCSS('opacity', '0.6');
  await thickness.click();
  await expect(thickness).toBeFocused();
  await expect(thickness.locator('xpath=ancestor::label')).toHaveCSS('opacity', '1');
  await expect(poleCount.locator('xpath=ancestor::label')).toHaveCSS('opacity', '0.6');
  await page.screenshot({ path: info.outputPath('pole-count-and-field-focus.png') });
});

test('progressive rotor diameter shrinks from above 40 mm to 25 mm before magnets are configured', async ({ page }, info) => {
  await newDesign(page);
  for (const [label, value] of [['Outer Diameter', '118'], ['Yoke Thickness', '5.8'], ['Slot Count', '15'], ['Bore Diameter (ID)', '72'], ['Stack Length', '50']]) {
    await stator(page).getByRole('spinbutton', { name: label, exact: true }).fill(value);
  }
  await continueSetup(page, 'Tooth');
  const teeth = page.locator('[data-guide="section-advanced"]');
  await teeth.getByRole('button', { name: 'Tooth shoes', exact: true }).click();
  for (const [label, value] of [['Bore Tooth Width', '13'], ['Yoke Tooth Width', '11'], ['Shoe Height', '1'], ['Shoe Overhang', '0.5']]) {
    await teeth.getByRole('spinbutton', { name: label, exact: true }).fill(value);
  }
  await continueSetup(page, 'Rotor');
  await rotor(page).getByRole('spinbutton', { name: 'Pole Count', exact: true }).fill('10');
  const od = rotor(page).getByRole('spinbutton', { name: 'Rotor OD', exact: true });
  const redAt20mm = async () => {
    const scale = Number(await page.getByRole('img', { name: /^View scale:/ }).getAttribute('data-pixels-per-mm'));
    return page.locator('canvas.motor-canvas').evaluate((el, pxPerMm) => {
      const canvas = el as HTMLCanvasElement;
      const box = canvas.getBoundingClientRect();
      return canvas.getContext('2d')!.getImageData(Math.round((box.width / 2 + 20 * pxPerMm) * canvas.width / box.width), Math.round(canvas.height / 2), 1, 1).data[0];
    }, scale);
  };
  for (const diameter of [50, 25, 45, 30]) {
    const rendered = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.rotor?.OD_mm === diameter);
    await od.fill(String(diameter));
    const response = await rendered;
    expect(response.status(), await response.text()).toBe(200);
    const preview = await response.json();
    const rotorRegions = preview.regions.filter((r: { region_type: string }) => /^rotor/i.test(r.region_type));
    const radius = Math.max(...rotorRegions.flatMap((r: { points: [number, number][] }) => r.points.map(([x, y]) => Math.hypot(x, y))));
    expect(radius * 2).toBeCloseTo(diameter, 5);
    // Check the actual filled motor, independently of its label and API data:
    // 20 mm from centre is iron at OD 50/45, and empty space at OD 25/30.
    if (diameter > 40) await expect.poll(redAt20mm).toBeGreaterThan(40);
    else await expect.poll(redAt20mm).toBeLessThan(35);
    await expect(page.getByRole('status', { name: 'Active geometry dimension', exact: true })).toContainText(`${diameter.toFixed(1)} mm`);
    await expect(health(page).locator('.public-health-attention .severity-error')).toHaveCount(0);
    if (diameter === 25) await page.screenshot({ path: info.outputPath('rotor-25mm.png') });
  }
  const thickness = rotor(page).getByRole('spinbutton', { name: 'Magnet Thick.', exact: true });
  const width = rotor(page).getByRole('spinbutton', { name: 'Magnet Width', exact: true });
  await thickness.fill('3');
  for (const diameter of [50, 25]) {
    const rendered = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.rotor?.OD_mm === diameter);
    await od.fill(String(diameter));
    const response = await rendered;
    expect(response.status(), await response.text()).toBe(200);
    expect(response.request().postDataJSON().rotor.magnet_thickness_mm).toBe(3);
    expect(response.request().postDataJSON().rotor.magnet_width_mm).toBeCloseTo(2 * Math.PI * (diameter / 2 + 1.5) / 10 * 0.75, 5);
    await expect(thickness).toHaveValue('3');
    await expect(width).toHaveValue('');
  }
  await width.fill('5');
  const withEnteredWidth = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.rotor?.OD_mm === 45);
  await od.fill('45');
  const response = await withEnteredWidth;
  expect(response.status(), await response.text()).toBe(200);
  expect(response.request().postDataJSON().rotor.magnet_width_mm).toBe(5);
  await expect(width).toHaveValue('5');
  await expect(thickness).toHaveValue('3');
  // A width the user actually entered must remain theirs. Explain a real
  // clash at that input rather than silently resizing it or hiding the error.
  await width.fill('12');
  const conflictingWidth = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.rotor?.OD_mm === 25 && r.request().postDataJSON()?.rotor?.magnet_width_mm === 12);
  await od.fill('25');
  expect((await conflictingWidth).status()).toBe(400);
  await expect(width).toHaveValue('12');
  await expect(health(page).locator('.public-health-attention .severity-error')).toContainText('Magnet Width needs attention');
  await expect(width.locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('pole pitch');
  const correctedWidth = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.rotor?.OD_mm === 25 && r.request().postDataJSON()?.rotor?.magnet_width_mm === 5);
  await width.fill('5');
  expect((await correctedWidth).status()).toBe(200);
  await expect(health(page).locator('.public-health-attention .severity-error')).toHaveCount(0);
});

for (const layout of ['Inrunner', 'Outrunner']) {
  test(`progressive ${layout} shoe height and overhang show their measured yellow spans`, async ({ page }, info) => {
    await page.addInitScript(() => {
      const paths = new WeakMap<CanvasRenderingContext2D, { last: [number, number] | null; length: number }>();
      const begin = CanvasRenderingContext2D.prototype.beginPath;
      const move = CanvasRenderingContext2D.prototype.moveTo;
      const line = CanvasRenderingContext2D.prototype.lineTo;
      const stroke = CanvasRenderingContext2D.prototype.stroke;
      CanvasRenderingContext2D.prototype.beginPath = function () { paths.set(this, { last: null, length: 0 }); return begin.call(this); };
      CanvasRenderingContext2D.prototype.moveTo = function (x, y) { const p = paths.get(this); if (p) p.last = [x, y]; return move.call(this, x, y); };
      CanvasRenderingContext2D.prototype.lineTo = function (x, y) {
        const p = paths.get(this);
        if (p) { if (p.last) p.length += Math.hypot(x - p.last[0], y - p.last[1]); p.last = [x, y]; }
        return line.call(this, x, y);
      };
      CanvasRenderingContext2D.prototype.stroke = function (path?: Path2D) {
        if (this.canvas.matches('.motor-canvas') && String(this.strokeStyle).includes('251, 191, 36') && this.getLineDash().length) {
          this.canvas.dataset.measuredDimensionLength = String(paths.get(this)?.length ?? 0);
        }
        return path ? stroke.call(this, path) : stroke.call(this);
      };
    });
    await newDesign(page, layout);
    await continueSetup(page, 'Tooth');
    const teeth = page.locator('[data-guide="section-advanced"]');
    await teeth.getByRole('button', { name: 'Tooth shoes', exact: true }).click();
    await configureSection(page, 'advanced', ['Shoe Height', 'Shoe Overhang']);
    const canvas = page.locator('canvas.motor-canvas');
    const label = page.getByRole('status', { name: 'Active geometry dimension', exact: true });
    for (const [field, dimension, mm] of [['Shoe Height', 'shoe-height', 1.5], ['Shoe Overhang', 'shoe-overhang', 0.5]] as const) {
      await teeth.getByRole('spinbutton', { name: field, exact: true }).fill(String(mm));
      await expect(canvas).toHaveAttribute('data-editing-dimension', dimension);
      await expect(label).toContainText(new RegExp(`${field === 'Shoe Height' ? 'Shoe height' : 'Shoe overhang / side'} ${mm.toFixed(field === 'Shoe Height' ? 1 : 2)} mm`));
      await expect.poll(async () => {
        const measured = Number(await canvas.getAttribute('data-measured-dimension-length'));
        const scale = Number(await page.getByRole('img', { name: /^View scale:/ }).getAttribute('data-pixels-per-mm'));
        return Math.abs(measured - mm * scale);
      }).toBeLessThan(0.02);
      await page.screenshot({ path: info.outputPath(`${layout.toLowerCase()}-${dimension}.png`) });
    }
    await expect(page.getByRole('button', { name: 'Dims', exact: true })).toHaveAttribute('aria-pressed', 'false');
    await teeth.getByRole('button', { name: 'Plain', exact: true }).click();
    await expect(label).toHaveCount(0);
  });
}

test('progressive focused bore dimension changes length while the yoke dimension stays fixed', async ({ page }, info) => {
  await page.addInitScript(() => {
    const starts = new WeakMap<CanvasRenderingContext2D, [number, number]>();
    const moveTo = CanvasRenderingContext2D.prototype.moveTo;
    const lineTo = CanvasRenderingContext2D.prototype.lineTo;
    CanvasRenderingContext2D.prototype.moveTo = function (x, y) {
      starts.set(this, [x, y]);
      return moveTo.call(this, x, y);
    };
    CanvasRenderingContext2D.prototype.lineTo = function (x, y) {
      const start = starts.get(this);
      if (start && this.canvas.matches('.motor-canvas') && String(this.strokeStyle).includes('251, 191, 36') && this.getLineDash().length) {
        this.canvas.dataset.dimensionLineLength = String(Math.hypot(x - start[0], y - start[1]));
      }
      return lineTo.call(this, x, y);
    };
  });
  await newDesign(page);
  await stator(page).getByRole('spinbutton', { name: /Outer Diameter/ }).fill('150');
  const bore = stator(page).getByRole('spinbutton', { name: /Bore Diameter \(ID\)/ });
  await stator(page).getByRole('spinbutton', { name: 'Yoke Thickness', exact: true }).fill('8');
  await bore.fill('40');
  const readout = page.getByRole('status', { name: 'Active geometry dimension', exact: true });
  await expect(readout).toContainText('Bore Ø 40.0 mm');
  const canvas = page.locator('.public-motor-viewport canvas.motor-canvas');
  await expect(canvas).toHaveAttribute('data-editing-dimension', 'bore');
  await expect.poll(async () => Number(await canvas.getAttribute('data-dimension-line-length'))).toBeGreaterThan(0);
  const before = Number(await canvas.getAttribute('data-dimension-line-length'));
  await bore.fill('80');
  await expect(readout).toContainText('Bore Ø 80.0 mm');
  await expect.poll(async () => Number(await canvas.getAttribute('data-dimension-line-length')) / before).toBeCloseTo(2, 5);
  await page.screenshot({ path: info.outputPath('focused-bore-dimension.png') });
  await stator(page).getByRole('spinbutton', { name: 'Yoke Thickness', exact: true }).focus();
  await expect(readout).toContainText('Yoke thickness 8.0 mm');
  const pxPerMm = Number(await page.getByRole('img', { name: /^View scale:/ }).getAttribute('data-pixels-per-mm'));
  await expect.poll(async () => Number(await canvas.getAttribute('data-dimension-line-length'))).toBeCloseTo(8 * pxPerMm, 5);
  await page.screenshot({ path: info.outputPath('focused-yoke-dimension.png') });
  await continueSetup(page, 'Tooth');
  await expect(readout).toHaveCount(0);
});

for (const layout of ['Inrunner', 'Outrunner']) {
  test(`progressive ${layout} stays on the existing Design page and saves its motor`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined }));
    await newDesign(page, layout);
    await expect(health(page)).toContainText('0 of 6 parts drawn');
    await expect(page.getByRole('button', { name: 'Show 3D motor view', exact: true })).toBeDisabled();
    await stator(page).getByRole('spinbutton', { name: /Outer Diameter/ }).fill(layout === 'Inrunner' ? '102' : '29');
    await stator(page).getByRole('spinbutton', { name: 'Yoke Thickness', exact: true }).fill(layout === 'Inrunner' ? '8' : '2');
    if (layout === 'Outrunner') await stator(page).getByRole('spinbutton', { name: 'Hub Bore (ID)', exact: true }).fill('10');
    await expect(health(page)).toContainText('1 of 6 parts drawn');
    await page.screenshot({ path: info.outputPath(`${layout.toLowerCase()}-yoke.png`) });
    if (layout === 'Inrunner') await stator(page).getByRole('spinbutton', { name: 'Bore Diameter (ID)', exact: true }).fill('60');
    await stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true }).fill('24');
    await expect(health(page)).toContainText('2 of 6 parts drawn');
    await stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true }).fill('12');
    await continueSetup(page, 'Tooth');
    await page.getByRole('group', { name: 'Tooth Profile', exact: true }).getByRole('button', { name: 'Tooth shoes', exact: true }).click();
    await configureSection(page, 'advanced');
    await expect(health(page)).toContainText('3 of 6 parts drawn');
    await expect(page.locator('.viewport-preview-note')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath(`${layout.toLowerCase()}-tooth-profile.png`) });
    await continueSetup(page, 'Rotor');
    const od = rotor(page).getByRole('spinbutton', { name: /Rotor OD/ });
    await od.press('Enter'); // An untouched empty field does not accept an internal default.
    await configureSection(page, 'rotor');
    await expect(health(page)).toContainText('5 of 6 parts drawn');
    await rotor(page).getByRole('spinbutton', { name: /Magnet Thick/ }).press('Enter');
    await configureSection(page, 'rotor');
    await expect(health(page)).toContainText('5 of 6 parts drawn');
    await continueSetup(page, 'Winding');
    await page.locator('[data-guide="section-winding"]').getByRole('spinbutton', { name: 'Turns / Coil', exact: true }).fill('11');
    await completeWinding(page);
    await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
    if (layout === 'Inrunner') {
      const search = page.getByRole('searchbox', { name: 'Search design parameters', exact: true });
      await search.fill('magnet');
      await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
      await search.fill('');
      await page.locator('[data-guide="section-winding"] .param-group-header').click();
      const winding = page.locator('[data-guide="section-winding"]');
      await winding.getByRole('group', { name: 'Wire', exact: true }).getByRole('button', { name: 'Specified', exact: true }).click();
      for (const label of ['Wire Ø (bare)', 'Strands in Hand', 'End-turn Extension']) await expect(winding.getByRole('spinbutton', { name: label, exact: true })).toHaveValue('');
      await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeDisabled();
      await winding.getByRole('combobox', { name: 'Wire Gauge', exact: true }).selectOption('24');
      await expect(winding.getByRole('spinbutton', { name: 'Wire Ø (bare)', exact: true })).not.toHaveValue('');
      await winding.getByRole('spinbutton', { name: 'Strands in Hand', exact: true }).fill('1');
      await winding.getByRole('spinbutton', { name: 'End-turn Extension', exact: true }).fill('0');
      await winding.getByRole('group', { name: 'Wire', exact: true }).getByRole('button', { name: 'Derived', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
    }
    await expect(page.getByRole('button', { name: 'Show 3D motor view', exact: true })).toBeEnabled();
    await expect(page.locator('.design-workspace')).toBeVisible();
    await page.screenshot({ path: info.outputPath(`${layout.toLowerCase()}-complete.png`) });
    await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
    const downloaded = page.waitForEvent('download');
    await page.getByRole('menuitem', { name: /^Save design file/ }).click();
    const saved = JSON.parse(await readFile((await (await downloaded).path())!, 'utf8'));
    expect(saved.rotor_layout ?? 'inner').toBe(layout === 'Inrunner' ? 'inner' : 'outer');
    expect(saved.stator.OD_mm).toBe(layout === 'Inrunner' ? 102 : 29);
    expect(saved.stator.slot_count).toBe(12);
    expect(saved.stator.tooth_shoe_enabled).toBe(true);
    expect(saved.winding.turns_per_coil).toBe(11);
    expect(errors).toEqual([]);
  });
}

test('progressive native inputs flag invalid values, support undo and block a magnet clash', async ({ page }) => {
  await newDesign(page);
  const diameter = stator(page).getByRole('spinbutton', { name: /Outer Diameter/ });
  await diameter.fill('100');
  await diameter.fill('');
  await expect(diameter).toHaveAttribute('aria-invalid', 'true');
  await expect(health(page).locator('.public-health-attention .severity-error')).toContainText('Outer Diameter needs attention');
  await expect(diameter.locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('Enter a numeric value for Outer Diameter.');
  await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeDisabled();
  await diameter.press('Escape');
  await expect(diameter).toHaveValue('100');
  await expect(diameter).toHaveAttribute('aria-invalid', 'false');
  await diameter.fill('102');
  await stator(page).getByRole('spinbutton', { name: 'Yoke Thickness', exact: true }).fill('8');
  await expect(health(page)).toContainText('1 of 6 parts drawn');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(diameter).toHaveValue('100');
  await expect(health(page)).toContainText('1 of 6 parts drawn');
  await continueSetup(page, 'Tooth');
  const profile = page.getByRole('group', { name: 'Tooth Profile', exact: true });
  await profile.getByRole('button', { name: 'Tooth shoes', exact: true }).click();
  await page.locator('[data-guide="section-advanced"]').getByRole('spinbutton', { name: /Shoe Height/ }).fill('');
  await profile.getByRole('button', { name: 'Plain', exact: true }).click();
  await expect(health(page).locator('.public-health-attention .severity-error')).toHaveCount(0);
  await continueSetup(page, 'Rotor');
  await rotor(page).getByRole('spinbutton', { name: /Rotor OD/ }).press('Enter');
  await configureSection(page, 'rotor');
  await rotor(page).getByRole('spinbutton', { name: /Magnet Thick/ }).fill('8');
  await expect(health(page)).toContainText('Magnets intersect the stator');
  await expect(health(page).locator('.public-health-attention .severity-error')).toContainText('Magnet Thick. needs attention');
  await expect(rotor(page).getByRole('spinbutton', { name: /Magnet Thick/ }).locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('Magnets intersect the stator');
  await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeDisabled();
  await rotor(page).getByRole('spinbutton', { name: /Magnet Thick/ }).fill('4');
  await expect(health(page)).not.toContainText('Magnets intersect the stator');
});

for (const layout of ['Inrunner', 'Outrunner']) {
  test(`progressive ${layout} shows large-airgap advice beside the row without blocking Solve`, async ({ page }, info) => {
    await newDesign(page, layout);
    await continueSetup(page, 'Tooth');
    await continueSetup(page, 'Rotor');
    await configureSection(page, 'rotor');
    const warning = rotor(page).locator('.public-airgap-advisory');
    await expect(warning).toHaveCount(0);
    const largePreview = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.ok()
      && (layout === 'Inrunner'
        ? r.request().postDataJSON()?.rotor?.OD_mm === 34 && r.request().postDataJSON()?.rotor?.magnet_width_mm === 10
        : r.request().postDataJSON()?.rotor?.OD_mm === 50 && r.request().postDataJSON()?.rotor?.ID_mm === 40));
    await rotor(page).getByRole('spinbutton', { name: 'Rotor OD', exact: true }).fill(layout === 'Inrunner' ? '34' : '50');
    if (layout === 'Inrunner') await rotor(page).getByRole('spinbutton', { name: 'Magnet Width', exact: true }).fill('10');
    else await rotor(page).getByRole('spinbutton', { name: 'Magnet Seat', exact: true }).fill('40');
    expect((await largePreview).status()).toBe(200);
    await expect(rotor(page).locator('.public-airgap-row')).toContainText(layout === 'Inrunner' ? '9.00' : '4.50');
    await expect(warning).toBeInViewport();
    await expect(warning).toHaveAttribute('role', 'status');
    await expect(warning).toContainText('Airgap is substantially oversized');
    await expect(warning).toContainText('torque per ampere');
    await expect(warning).toContainText('advisory, not a maximum-airgap limit');
    const rowBox = await rotor(page).locator('.public-airgap-row').boundingBox();
    const warningBox = await warning.boundingBox();
    expect(warningBox!.y).toBeGreaterThanOrEqual(rowBox!.y + rowBox!.height);
    await page.screenshot({ path: info.outputPath(`${layout.toLowerCase()}-airgap-warning.png`) });
    await continueSetup(page, 'Winding');
    const completed = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.ok()
      && r.request().postDataJSON()?.winding?.turns_per_coil === 11);
    await page.locator('[data-guide="section-winding"]').getByRole('spinbutton', { name: 'Turns / Coil', exact: true }).fill('11');
    await completed;
    await completeWinding(page);
    await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
    // Bringing the gap back to the existing practical upper limit clears the advice.
    await rotor(page).locator('.param-group-header').click();
    if (layout === 'Inrunner') await rotor(page).getByRole('spinbutton', { name: 'Rotor OD', exact: true }).fill('49');
    else await rotor(page).getByRole('spinbutton', { name: 'Magnet Seat', exact: true }).fill('33');
    await expect(warning).toHaveCount(0);
  });
}

for (const [layout, slots, poles] of [['Inrunner', 12, 8], ['Inrunner', 33, 16], ['Outrunner', 12, 14]] as const) {
  test(`progressive ${layout} ${slots}s shows one copper dot per turn in each coil side`, async ({ page }, info) => {
    await page.addInitScript(() => {
      const proto = CanvasRenderingContext2D.prototype;
      const begin = proto.beginPath; const arc = proto.arc; const fill = proto.fill; const fillRect = proto.fillRect;
      const state = new WeakMap<CanvasRenderingContext2D, { arcs: number; batches: number[] }>();
      const current = (ctx: CanvasRenderingContext2D) => {
        let value = state.get(ctx);
        if (!value) { value = { arcs: 0, batches: [] }; state.set(ctx, value); }
        return value;
      };
      proto.beginPath = function () { current(this).arcs = 0; return begin.call(this); };
      proto.arc = function (...args) { current(this).arcs += 1; return arc.apply(this, args); };
      proto.fillRect = function (...args) {
        if (this.canvas.matches('.motor-canvas') && args[0] === 0 && args[1] === 0) {
          current(this).batches = []; this.canvas.dataset.turnDotBatches = '[]';
        }
        return fillRect.apply(this, args);
      };
      proto.fill = function (...args) {
        if (this.canvas.matches('.motor-canvas') && this.fillStyle === '#703916') {
          const value = current(this); value.batches.push(value.arcs);
          this.canvas.dataset.turnDotBatches = JSON.stringify(value.batches);
        }
        return fill.apply(this, args as never);
      };
    });
    await newDesign(page, layout);
    await stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true }).fill(String(slots));
    await continueSetup(page, 'Tooth');
    await continueSetup(page, 'Rotor');
    await rotor(page).getByRole('spinbutton', { name: 'Pole Count', exact: true }).fill(String(poles));
    await continueSetup(page, 'Winding');
    await configureSection(page, 'winding', ['Turns / Coil']);
    const turns = page.locator('[data-guide="section-winding"]').getByRole('spinbutton', { name: 'Turns / Coil', exact: true });
    const rendered = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.ok() && r.request().postDataJSON()?.winding?.turns_per_coil === 14);
    await turns.fill('14');
    const preview = await (await rendered).json();
    const sides = preview.regions.filter((r: { region_type: string }) => /^slot_\d+.*\([abc][+\-−]\)/i.test(r.region_type)).length;
    expect(sides).toBeGreaterThan(0);
    // Zoom in so dense windings have enough screen pixels to show every dot.
    for (let i = 0; i < 3; i += 1) await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    const canvas = page.locator('canvas.motor-canvas');
    const counts = () => canvas.evaluate((el) => JSON.parse((el as HTMLCanvasElement).dataset.turnDotBatches ?? '[]'));
    await expect.poll(counts).toEqual(Array(sides).fill(14));
    await page.screenshot({ path: info.outputPath(`${layout.toLowerCase()}-${slots}s-turn-dots.png`) });
    await turns.fill('21');
    await expect.poll(counts).toEqual(Array(sides).fill(21));
  });
}

test('progressive slot arrows select the next multiple of three and respect the bounds', async ({ page }) => {
  await newDesign(page);
  const slots = stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true });
  await slots.fill('12');
  await slots.press('ArrowUp');
  await expect(slots).toHaveValue('15');
  await slots.press('ArrowDown');
  await expect(slots).toHaveValue('12');
  // The native spinner buttons use the same valid-count stepping.
  const box = await slots.boundingBox();
  if (!box) throw new Error('Slot Count input is not visible');
  await slots.hover();
  await slots.click({ position: { x: box.width - 15, y: box.height * 0.4 } });
  await expect(slots).toHaveValue('15');
  await slots.click({ position: { x: box.width - 15, y: box.height * 0.6 } });
  await expect(slots).toHaveValue('12');
  await slots.fill('10');
  await expect(slots).toHaveAttribute('aria-invalid', 'true');
  await slots.press('ArrowUp');
  await expect(slots).toHaveValue('12');
  await expect(slots).toHaveAttribute('aria-invalid', 'false');
  await slots.fill('10');
  await slots.press('ArrowDown');
  await expect(slots).toHaveValue('9');
  await slots.fill('6');
  await slots.press('ArrowDown');
  await expect(slots).toHaveValue('6');
  await slots.fill('96');
  await slots.press('ArrowUp');
  await expect(slots).toHaveValue('96');
  await slots.fill('12.5');
  await expect(health(page).locator('.public-health-attention .severity-error')).toContainText('Slot Count needs attention');
  await expect(slots.locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('Slot Count must be a whole number.');
  await slots.press('ArrowUp');
  await expect(slots).toHaveValue('15');
});

test('progressive errors live in Design Health and keep inline guidance without viewport or footer notices', async ({ page }, info) => {
  await newDesign(page);
  await stator(page).getByRole('spinbutton', { name: /Outer Diameter/ }).fill('150');
  const slots = stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true });
  const motor = page.locator('.public-motor-viewport');
  const before = await page.locator('canvas.motor-canvas').boundingBox();
  await slots.fill('14');
  await expect(slots).toBeFocused();
  const alert = health(page).locator('.public-health-attention .severity-error').filter({ hasText: 'Slot Count needs attention' });
  await expect(alert).toBeInViewport();
  await expect(alert).toContainText('Slot Count needs attention');
  await expect(health(page).locator('.public-health-status-card')).toHaveClass(/error/);
  await expect(health(page).locator('.design-health-score-label')).toHaveText('Need attention');
  await expect(health(page).locator('.public-health-attention')).not.toContainText('Winding needs attention');
  await expect(page.locator('.public-design-edit-toast')).toHaveCount(0);
  const badge = await alert.boundingBox();
  const panel = await health(page).boundingBox();
  expect(badge && panel && badge.x >= panel.x && badge.x + badge.width <= panel.x + panel.width).toBe(true);
  await expect(motor.locator('[role="alert"]')).toHaveCount(0);
  await expect(page.locator('.public-viewport-attention')).toHaveCount(0);
  await expect(page.locator('.panel-footer-cta .has-error, .panel-footer-cta .is-warning')).toHaveCount(0);
  expect(await page.locator('canvas.motor-canvas').boundingBox()).toEqual(before);
  await expect(slots).toHaveAttribute('aria-invalid', 'true');
  await expect(slots.locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('12, 15 or 18');
  await expect(stator(page).locator('.param-group-header')).toHaveClass(/status-attention/);
  await expect(page.locator('.panel-footer-cta')).not.toContainText('Winding needs attention');
  await expect(page.getByRole('button', { name: 'Retry geometry preview', exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('immediate-slot-error.png') });
  await page.getByRole('button', { name: 'Collapse design health', exact: true }).click();
  await expect(health(page)).toHaveClass(/tone-error/);
  await page.getByRole('button', { name: 'Show design health: Need attention', exact: true }).click();
  await expect(alert).toBeVisible();
  // Missing and invalid values cannot be bypassed by Continue.
  await expect(page.getByRole('button', { name: /^Continue Setup: Tooth/ })).toBeDisabled();
  await expect(stator(page).locator('.param-group-header')).toHaveAttribute('aria-expanded', 'true');
  const valid = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.stator?.slot_count === 15 && r.ok());
  await slots.fill('15');
  await valid;
  await expect(alert).toHaveCount(0);
  await expect(slots).toHaveAttribute('aria-invalid', 'false');
  await expect(stator(page).locator('.param-group-header')).not.toHaveClass(/status-attention/);
  await expect(page.locator('.panel-next-feedback.is-progress')).not.toHaveCSS('color', 'rgb(252, 165, 165)');
  await slots.fill('100');
  await expect(alert).toContainText('Slot Count needs attention');
  await expect(slots.locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('Slot Count must be at most 96');
  await page.setViewportSize({ width: 1260, height: 760 });
  await expect(alert).toBeInViewport();
  await slots.fill('15');
  await expect(alert).toHaveCount(0);
});

test('progressive geometry advisories stay in Design Health during construction and after completion', async ({ page }, info) => {
  await newDesign(page);
  await continueSetup(page, 'Tooth');
  const teeth = page.locator('[data-guide="section-advanced"]');
  await teeth.getByRole('button', { name: 'Tooth shoes', exact: true }).click();
  for (const [name, value] of [['Bore Tooth Width', '5'], ['Yoke Tooth Width', '8'], ['Shoe Height', '1']]) {
    await teeth.getByRole('spinbutton', { name, exact: true }).fill(value);
  }
  const rendered = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.stator?.tooth_shoe_overhang_mm === 0.5 && r.ok());
  await teeth.getByRole('spinbutton', { name: 'Shoe Overhang', exact: true }).fill('0.5');
  const payload = await (await rendered).json();
  const message = payload.metadata.geometry_warnings?.find((warning: string) => /tooth-shoe shoulder/i.test(warning));
  expect(message).toBeTruthy();
  const advisory = health(page).locator('.public-health-attention .severity-warning').filter({ hasText: message });
  await expect(advisory).toBeVisible();
  await expect(health(page).locator('.design-health-score-label')).toHaveText('Need attention');
  await expect(health(page).locator('.public-health-status-card')).toHaveClass(/warning/);
  await expect(health(page).locator('.design-health-issue-copy').filter({ hasText: message })).toHaveCount(1);
  await expect(page.locator('.panel-footer-cta .is-warning, .panel-footer-cta .has-error, .public-viewport-attention')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Continue Setup: Rotor/ })).toBeEnabled();
  await page.screenshot({ path: info.outputPath('health-geometry-advisory.png') });
  await continueSetup(page, 'Rotor');
  await continueSetup(page, 'Winding');
  await completeWinding(page);
  await expect(advisory).toBeVisible();
  await expect(health(page).locator('.design-health-issue-copy').filter({ hasText: message })).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
  await page.screenshot({ path: info.outputPath('health-completed-advisory.png') });
  await page.locator('[data-guide="section-advanced"] .param-group-header').click();
  const corrected = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.stator?.tooth_width_mm === 3 && r.ok());
  await teeth.getByRole('spinbutton', { name: 'Yoke Tooth Width', exact: true }).fill('3');
  await corrected;
  await expect(advisory).toHaveCount(0);
});

test('progressive unsupported winding reports its error in Design Health', async ({ page }, info) => {
  await newDesign(page);
  await stator(page).getByRole('spinbutton', { name: 'Slot Count', exact: true }).fill('24');
  await continueSetup(page, 'Tooth');
  await continueSetup(page, 'Rotor');
  await rotor(page).getByRole('spinbutton', { name: 'Pole Count', exact: true }).fill('12');
  await continueSetup(page, 'Winding');
  const winding = page.locator('[data-guide="section-winding"]');
  await winding.getByRole('button', { name: 'Concentrated', exact: true }).click();
  await expect(winding.getByRole('button', { name: 'Alternate', exact: true })).toBeDisabled();
  await expect(winding.getByRole('button', { name: 'All', exact: true })).toBeDisabled();
  await expect(health(page).locator('.public-health-attention .severity-error')).toContainText('Winding needs attention');
  await expect(health(page).locator('.design-health-score-label')).toHaveText('Need attention');
  await expect(health(page).locator('.public-health-status-card')).toHaveClass(/error/);
  await expect(page.locator('.public-motor-viewport [role="alert"], .panel-footer-cta .has-error, .panel-footer-cta .is-warning')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeDisabled();
  await page.screenshot({ path: info.outputPath('health-winding-error.png') });
});

test('progressive preview masks hide unbuilt rotor, magnets and copper', async ({ page }) => {
  await page.goto('/');
  const stages = await page.evaluate(async () => {
    const path = '/progressiveDesign.ts';
    const { newBuildConfig, progressiveGeometry } = await import(/* @vite-ignore */ path);
    const config = newBuildConfig('inner');
    const regions = ['stator_yoke', 'stator_tooth', 'rotor_core', 'shaft', 'magnet_n_0', 'airgap', 'slot_1_A', 'winding_symbol'].map((region_type) => ({ region_type, points: [[1, 1], [2, 1], [2, 2]] }));
    const preview = { regions, metadata: {}, validation_errors: [], generation_time_ms: 0 };
    return [ {}, { stator: true }, { stator: true, slots: true },
      { stator: true, slots: true, rotor: true },
      { stator: true, slots: true, rotor: true, magnets: true },
      { stator: true, slots: true, rotor: true, magnets: true, winding: true },
    ].map((built) => progressiveGeometry(config, built, preview).regions.map((r: { region_type: string }) => r.region_type));
  });
  expect(stages).toEqual([ [], ['stator_yoke'], ['stator_yoke', 'stator_tooth'],
    ['stator_yoke', 'stator_tooth', 'rotor_core', 'shaft'],
    ['stator_yoke', 'stator_tooth', 'rotor_core', 'shaft', 'magnet_n_0', 'airgap'],
    ['stator_yoke', 'stator_tooth', 'rotor_core', 'shaft', 'magnet_n_0', 'airgap', 'slot_1_A', 'winding_symbol'],
  ]);
});

test('progressive changes preserve normal loading of a shipped motor example', async ({ page }) => {
  await newDesign(page);
  await page.locator('input[type="file"]').setInputFiles('src/public/examples/validation_spm_24p_small.openem');
  await expect(page.locator('.design-workspace')).toBeVisible();
  await expect(health(page)).not.toContainText('Design in progress');
  await completeWinding(page);
  await expect(page.getByRole('button', { name: 'Continue to Solve', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Show 3D motor view', exact: true })).toBeEnabled();
  await expect(page.locator('.progressive-design')).toHaveCount(0);
});

test('progressive entry feedback shows ranges, defers tooth advice and reuses the drawn widths', async ({ page }, info) => {
  await newDesign(page);
  const od = stator(page).getByRole('spinbutton', { name: 'Outer Diameter', exact: true });
  await od.fill('150');
  await od.fill('');
  await expect(od.locator('xpath=ancestor::label').locator('.public-param-field-error')).toContainText('Valid range: 30–500 mm');
  await expect(health(page).getByRole('alert')).toContainText('Valid range: 30–500 mm');
  await page.screenshot({ path: info.outputPath('outer-diameter-valid-range.png') });
  const ready = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview'
    && r.request().postDataJSON()?.stator?.slot_count === 18 && r.request().postDataJSON()?.stator?.stack_length_mm === 60);
  for (const [name, value] of [['Outer Diameter', '150'], ['Yoke Thickness', '10'], ['Slot Count', '18'], ['Bore Diameter (ID)', '60'], ['Stack Length', '60']]) {
    await stator(page).getByRole('spinbutton', { name, exact: true }).fill(value);
  }
  const response = await ready;
  expect(response.status(), await response.text()).toBe(200);
  const payload = await response.json();
  expect(payload.metadata.geometry_warnings.some((warning: string) => /bore tooth/i.test(warning))).toBe(true);
  await expect(health(page).locator('.severity-warning').filter({ hasText: /Bore tooth/ })).toHaveCount(0);
  await continueSetup(page, 'Tooth');
  const teeth = page.locator('[data-guide="section-advanced"]');
  const bore = teeth.getByRole('spinbutton', { name: 'Bore Tooth Width', exact: true });
  const yoke = teeth.getByRole('spinbutton', { name: 'Yoke Tooth Width', exact: true });
  await expect(bore).toHaveValue(String(Number(payload.metadata.bore_tooth_width_mm.toFixed(1))));
  await expect(yoke).toHaveValue(String(Number(payload.metadata.tooth_width_at_yoke_mm.toFixed(2))));
  await expect(bore.locator('xpath=ancestor::label')).toHaveAttribute('data-entry-configured', 'true');
  await teeth.getByRole('button', { name: 'Plain', exact: true }).click();
  await expect(page.getByRole('button', { name: /^Continue Setup: Rotor/ })).toBeEnabled();
  await expect(health(page).locator('.severity-warning').filter({ hasText: /Bore tooth/ })).toBeVisible();
  await bore.focus();
  await expect(page.getByRole('status', { name: 'Active geometry dimension', exact: true })).toContainText(`Bore tooth ${payload.metadata.bore_tooth_width_mm.toFixed(1)} mm`);
  await page.screenshot({ path: info.outputPath('prefilled-tooth-widths.png') });
  await page.locator('[data-guide="section-materials"] .param-group-header').click();
  await expect(page.getByRole('button', { name: /Import steel material.*optional/ })).toBeVisible();
});

test('progressive V-IPM diagnostic magnets stay visible and show physical magnet and V dimensions', async ({ page }, info) => {
  await page.addInitScript(() => {
    const paths = new WeakMap<CanvasRenderingContext2D, [number, number][]>();
    const begin = CanvasRenderingContext2D.prototype.beginPath;
    const move = CanvasRenderingContext2D.prototype.moveTo;
    const line = CanvasRenderingContext2D.prototype.lineTo;
    const stroke = CanvasRenderingContext2D.prototype.stroke;
    CanvasRenderingContext2D.prototype.beginPath = function () { paths.set(this, []); return begin.call(this); };
    CanvasRenderingContext2D.prototype.moveTo = function (x, y) { paths.get(this)?.push([x, y]); return move.call(this, x, y); };
    CanvasRenderingContext2D.prototype.lineTo = function (x, y) { paths.get(this)?.push([x, y]); return line.call(this, x, y); };
    CanvasRenderingContext2D.prototype.stroke = function (path?: Path2D) {
      if (this.canvas.matches('.motor-canvas') && String(this.strokeStyle).includes('251, 191, 36') && this.getLineDash().length) {
        const previous = JSON.parse(this.canvas.dataset.dimensionPaths ?? '[]');
        this.canvas.dataset.dimensionPaths = JSON.stringify([...previous, paths.get(this) ?? []].slice(-3));
      }
      return path ? stroke.call(this, path) : stroke.call(this);
    };
  });
  await newDesign(page, 'Inrunner', false);
  await page.getByRole('group', { name: 'Rotor arrangement', exact: true }).getByRole('button', { name: /Inrunner/ }).click();
  await page.locator('[data-guide="topology-selector"]').getByRole('button', { name: /^IPM/ }).click();
  await page.getByRole('group', { name: 'IPM rotor layout', exact: true }).getByRole('button', { name: /^V-shape/ }).click();
  for (const [name, value] of [['Outer Diameter', '150'], ['Yoke Thickness', '10'], ['Slot Count', '18'], ['Bore Diameter (ID)', '70'], ['Stack Length', '60']]) {
    await stator(page).getByRole('spinbutton', { name, exact: true }).fill(value);
  }
  await continueSetup(page, 'Tooth');
  await continueSetup(page, 'Rotor');
  const pending = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview'
    && r.request().postDataJSON()?.rotor?.v_depth_mm === 0.1 && r.request().postDataJSON()?.rotor?.v_angle_deg === 30);
  for (const [name, value] of [['Pole Count', '6'], ['Rotor OD', '65'], ['Magnet Thick.', '2'], ['Magnet Width', '4.7'], ['V Angle', '30'], ['V Depth', '0.1']]) {
    await rotor(page).getByRole('spinbutton', { name, exact: true }).fill(value);
  }
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  const payload = await response.json();
  expect(payload.metadata.diagnostic_only).toBe(true);
  const magnets = payload.regions.filter((region: { region_type: string }) => region.region_type.startsWith('magnet_'));
  expect(magnets).toHaveLength(12);
  expect(Math.max(...magnets.flatMap((region: { points: [number, number][] }) => region.points.map(([x, y]) => Math.hypot(x, y))))).toBeGreaterThan(32.5);
  await expect(health(page)).toContainText('Increase V Depth');
  await expect(health(page)).not.toContainText(/v_depth_mm|magnet_width_mm|magnet_thickness_mm|v_angle_deg/);
  const canvas = page.locator('canvas.motor-canvas');
  const dimension = page.getByRole('status', { name: 'Active geometry dimension', exact: true });
  for (const [name, text, size] of [['Magnet Thick.', 'Magnet Thick. 2.0 mm', 2], ['Magnet Width', 'Magnet Width 4.7 mm', 4.7], ['V Depth', 'V Depth 0.1 mm', 0.1]] as const) {
    await rotor(page).getByRole('spinbutton', { name, exact: true }).focus();
    await expect(dimension).toHaveText(text);
    await expect.poll(async () => {
      const paths = JSON.parse(await canvas.getAttribute('data-dimension-paths') ?? '[]') as [number, number][][];
      const points = paths.at(-1) ?? [];
      const length = points.slice(1).reduce((sum, point, i) => sum + Math.hypot(point[0] - points[i][0], point[1] - points[i][1]), 0);
      const scale = Number(await page.getByRole('img', { name: /^View scale:/ }).getAttribute('data-pixels-per-mm'));
      return Math.abs(length - size * scale);
    }).toBeLessThan(0.02);
  }
  await rotor(page).getByRole('spinbutton', { name: 'V Angle', exact: true }).focus();
  await expect(dimension).toHaveText('V Angle 30.0°');
  await expect.poll(async () => {
    const paths = JSON.parse(await canvas.getAttribute('data-dimension-paths') ?? '[]') as [number, number][][];
    const legs = paths.slice(-2);
    if (legs.some((points) => points.length !== 2)) return 0;
    const vectors = legs.map((points) => [points[1][0] - points[0][0], points[1][1] - points[0][1]]);
    const cosine = (vectors[0][0] * vectors[1][0] + vectors[0][1] * vectors[1][1]) / (Math.hypot(...vectors[0]) * Math.hypot(...vectors[1]));
    return Math.acos(Math.max(-1, Math.min(1, cosine))) * 180 / Math.PI;
  }).toBeCloseTo(30, 5);
  await page.screenshot({ path: info.outputPath('v-ipm-diagnostic-angle.png') });
  // The actual canvas contains a red magnet beyond the iron OD, not just a
  // diagnostic response or a measurement label over an empty drawing.
  await rotor(page).getByRole('spinbutton', { name: 'Pole Count', exact: true }).focus();
  const points = magnets[0].points as [number, number][];
  const probe = [0, 1].map((axis) => points.reduce((sum, point, i) => sum + point[axis] * (i === 0 ? 0.55 : 0.15), 0));
  const scale = Number(await page.getByRole('img', { name: /^View scale:/ }).getAttribute('data-pixels-per-mm'));
  await expect.poll(async () => canvas.evaluate((element, input) => {
    const el = element as HTMLCanvasElement;
    const box = el.getBoundingClientRect();
    const rgba = el.getContext('2d')!.getImageData(Math.round((box.width / 2 + input.point[0] * input.scale) * el.width / box.width), Math.round((box.height / 2 - input.point[1] * input.scale) * el.height / box.height), 1, 1).data;
    return rgba[0] - rgba[1];
  }, { point: probe, scale })).toBeGreaterThan(50);
  const suggestion = payload.validation_errors.find((issue: { suggestion?: string }) => /try V Depth/.test(issue.suggestion ?? '')).suggestion.match(/try V Depth ([\d.]+) mm/)[1];
  await expect(health(page)).toContainText(`try V Depth ${suggestion} mm`);
  const corrected = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview' && r.request().postDataJSON()?.rotor?.v_depth_mm === Number(suggestion));
  await rotor(page).getByRole('spinbutton', { name: 'V Depth', exact: true }).fill(suggestion);
  const fixed = await (await corrected).json();
  expect(fixed.metadata.diagnostic_only).toBe(false);
  await expect(health(page).getByRole('alert')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('v-ipm-corrected-depth.png') });
});

test('progressive flat-IPM magnet and bridge rows select their physical dimensions', async ({ page }, info) => {
  await newDesign(page, 'Inrunner', false);
  await page.getByRole('group', { name: 'Rotor arrangement', exact: true }).getByRole('button', { name: /Inrunner/ }).click();
  await page.locator('[data-guide="topology-selector"]').getByRole('button', { name: /^IPM/ }).click();
  await page.getByRole('group', { name: 'IPM rotor layout', exact: true }).getByRole('button', { name: /^Flat/ }).click();
  await continueSetup(page, 'Tooth');
  await continueSetup(page, 'Rotor');
  const ready = page.waitForResponse((r) => new URL(r.url()).pathname === '/preview'
    && r.request().postDataJSON()?.rotor?.magnet_width_mm === 8 && r.request().postDataJSON()?.rotor?.bridge_thickness_mm === 1.5);
  for (const [name, value] of [['Pole Count', '8'], ['Rotor OD', '50'], ['Magnet Thick.', '2'], ['Magnet Width', '8'], ['Outer Bridge', '1.5']]) {
    await rotor(page).getByRole('spinbutton', { name, exact: true }).fill(value);
  }
  const response = await ready;
  expect(response.status(), await response.text()).toBe(200);
  const payload = await response.json();
  expect(payload.metadata.diagnostic_only).toBe(false);
  expect(payload.regions.filter((region: { region_type: string }) => region.region_type.startsWith('magnet_'))).toHaveLength(8);
  for (const [name, text, id] of [['Magnet Thick.', 'Magnet Thick. 2.0 mm', 'magnet-thickness'], ['Magnet Width', 'Magnet Width 8.0 mm', 'magnet-width'], ['Outer Bridge', 'Outer Bridge 1.50 mm', 'outer-bridge']]) {
    await rotor(page).getByRole('spinbutton', { name, exact: true }).focus();
    await expect(page.getByRole('status', { name: 'Active geometry dimension', exact: true })).toHaveText(text);
    await expect(page.locator('canvas.motor-canvas')).toHaveAttribute('data-editing-dimension', id);
  }
  await expect(rotor(page).getByRole('spinbutton', { name: 'V Angle', exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('flat-ipm-magnet-bridge-dimension.png') });
});
