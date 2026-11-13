import { expect, type Page } from '@playwright/test';

export async function chooseSetup(page: Page, layout = 'Inrunner') {
  await page.getByRole('group', { name: 'Rotor arrangement', exact: true }).getByRole('button', { name: new RegExp(layout) }).click();
  await page.locator('[data-guide="topology-selector"]').getByRole('button', { name: /^SPM/ }).click();
}

export async function newDesign(page: Page, layout = 'Inrunner', choose = true) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
  await page.getByRole('menuitem', { name: 'New Design', exact: true }).click();
  await expect(page.locator('.design-workspace')).toBeVisible();
  await expect(page.locator('.public-parameter-panel')).toBeVisible();
  await expect(page.locator('.design-health-panel')).toBeVisible();
  await expect(page.locator('.progressive-design')).toHaveCount(0);
  if (choose) await chooseSetup(page, layout);
}

export const stator = (page: Page) => page.locator('[data-guide="section-stator"]');
export const rotor = (page: Page) => page.locator('[data-guide="section-rotor"]');
export const health = (page: Page) => page.locator('.design-health-panel');

// Test fixtures explicitly enter the values that earlier prototypes preselected.
export async function configureSection(page: Page, section: string, skip: string[] = []) {
  const group = page.locator(`[data-guide="section-${section}"]`);
  if (!await group.locator('[data-entry-required="true"][data-entry-configured="false"]').count()) return;
  await expect(group).toHaveAttribute('data-guide-active', 'true');
  const outer = await page.getByRole('group', { name: 'Rotor arrangement', exact: true }).getByRole('button', { name: /Outrunner/ }).getAttribute('aria-pressed') === 'true';
  const value = async (part: string, label: string, fallback: number) => Number(await page.locator(`[data-guide="section-${part}"]`).getByRole('spinbutton', { name: label, exact: true, includeHidden: true }).inputValue()) || fallback;
  for (let pass = 0; pass < 5; pass += 1) {
    const fields = group.locator('[data-entry-required="true"][data-entry-configured="false"]');
    let changed = false;
    const keys = await fields.evaluateAll((elements) => elements.map((el) => el.getAttribute('data-entry-field')!));
    for (const key of keys) {
      const field = group.locator(`[data-entry-field=${JSON.stringify(key)}]`);
      const label = key.slice(key.indexOf(':') + 1);
      if (skip.includes(label) || !await field.isVisible()) continue;
      if (await field.locator('input').count()) {
        const od = await value('stator', 'Outer Diameter', outer ? 28 : 100);
        const bore = await value('stator', outer ? 'Hub Bore (ID)' : 'Bore Diameter (ID)', outer ? 10 : 60);
        const slots = await value('stator', 'Slot Count', 12);
        const yoke = await value('stator', 'Yoke Thickness', outer ? 2 : 8);
        const poles = await value('rotor', 'Pole Count', outer ? 14 : 8);
        const rod = await value('rotor', 'Rotor OD', outer ? od + 7 : bore - 10);
        const thick = await value('rotor', 'Magnet Thick.', outer ? 1.5 : 4);
        const seat = outer ? await value('rotor', 'Magnet Seat', od + 3.8) : 0;
        const seeds: Record<string, number> = {
          'Outer Diameter': outer ? 28 : 100, 'Yoke Thickness': outer ? 2 : 8,
          'Slot Count': 12, 'Bore Diameter (ID)': 60, 'Hub Bore (ID)': 10, 'Stack Length': outer ? 6 : 50,
          'Bore Tooth Width': Number((Math.PI * bore / slots - 2).toFixed(1)),
          'Yoke Tooth Width': Number((2 * Math.PI * (outer ? bore / 2 + yoke : od / 2 - yoke) / slots * (outer ? 0.28 : 0.41)).toFixed(2)),
          'Slot Opening': 4, 'Shoe Height': 1, 'Shoe Overhang': 0.75,
          'Pole Count': outer ? 14 : 8, 'Rotor OD': outer ? od + 7 : bore - 10, 'Magnet Seat': od + 3.8,
          'Magnet Thick.': outer ? 1.5 : 4,
          'Magnet Width': 2 * Math.PI * (outer ? seat / 2 - thick / 2 : rod / 2 + thick / 2) / poles * (outer ? 0.85 : 0.75),
          'Turns / Coil': 10, 'Parallel Paths': 1, 'Winding Temp': 100, 'Phase Current': outer ? 4 : 24.3,
        };
        const input = field.locator('input');
        const min = Number(await input.getAttribute('min'));
        const max = Number(await input.getAttribute('max') ?? Infinity);
        await input.fill(String(Math.max(min, Math.min(max, seeds[label] ?? min))));
      } else if (await field.locator('select').count()) {
        const select = field.locator('select');
        const options = await select.locator('option:not(:disabled)').evaluateAll((opts) => opts.map((o) => (o as HTMLOptionElement).value));
        await select.selectOption(options.find((v) => v === 'M350-50A' || v === 'N42') ?? options[0]);
      } else {
        await field.locator('button:not(:disabled)').first().click();
      }
      changed = true;
    }
    if (!changed) break;
  }
}

export async function continueSetup(page: Page, next: string) {
  const active = page.locator('.param-group[data-guide-active="true"]');
  const section = (await active.getAttribute('data-guide'))!.replace('section-', '');
  await configureSection(page, section);
  await page.getByRole('button', { name: new RegExp(`^Continue Setup: ${next}`) }).click();
}

export async function completeWinding(page: Page) {
  await configureSection(page, 'winding');
  await page.locator('[data-guide="section-materials"] .param-group-header').click();
  await configureSection(page, 'materials');
}
