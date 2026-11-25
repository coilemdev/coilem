/**
 * Thermal setup and results in the real UI.
 *
 * The electromagnetic solve is replaced by a fixture so these run in seconds.
 * The thermal routes, the validation and the reports are the real ones.
 */
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const repository = fileURLToPath(new URL('../..', import.meta.url));

/** A solved result as the stream delivers it, with or without the losses thermal starts from. */
function solvedRun(ironLossW: number | null): string {
  return execFileSync(process.env.COILEM_TEST_PYTHON || 'python', ['-c', `
from backend.models import IronLoss
from tests.test_analysis_options import config, result_for
result = result_for(config(back_emf=True))
update = {"avg_torque_Nm": 3.2}
iron_W = ${ironLossW === null ? 'None' : ironLossW}
if iron_W is not None:
    update["iron_loss"] = IronLoss(status="experimental", steel="M350-50A", electrical_frequency_Hz=160, iron_loss_W=iron_W,
        iron_hysteresis_loss_W=0.6 * iron_W, iron_eddy_loss_W=0.4 * iron_W, stator_iron_mass_kg=1,
        validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5)
print(result.model_copy(update={"summary": result.summary.model_copy(update=update)}).model_dump_json())
`], { cwd: repository, encoding: 'utf8' });
}

async function openSolve(page: Page, example?: { label: RegExp; slots: number }): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: 'Use Example Motor', exact: true }).click();
  if (example) {
    await page.getByRole('button', { name: 'Design file menu', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Examples', exact: true }).hover();
    const previewed = page.waitForResponse((response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/preview' && response.request().postDataJSON()?.stator?.slot_count === example.slots);
    await page.getByRole('menuitem', { name: example.label }).click();
    expect((await previewed).status()).toBe(200);
  }
  await page.getByRole('button', { name: 'Continue to Solve', exact: true }).click();
}

async function runMockedAnalysis(page: Page, ironLossW: number | null): Promise<void> {
  const body = `event: complete\ndata: ${solvedRun(ironLossW)}\n\n`;
  await page.route('**/solve/stream', (route) => route.fulfill({ contentType: 'text/event-stream', body }));
  const run = page.getByRole('button', { name: '▶ Run analysis', exact: true });
  await expect(run).toBeEnabled({ timeout: 120_000 });
  await run.click();
  await expect(page.getByRole('button', { name: 'Full results →', exact: true })).toBeVisible();
}

const setupTabs = (page: Page) => page.getByRole('tablist', { name: 'Setup shown', exact: true });
const showThermalSetup = (page: Page) => setupTabs(page).getByRole('tab', { name: 'Thermal', exact: true }).click();
const runStatus = (page: Page) => page.locator('.thermal-run-controls [role=status]');
/** The side panel where a run reports, as the electromagnetic solve does. */
const monitor = (page: Page) => page.getByRole('region', { name: 'Thermal estimate status', exact: true });

async function openThermalSection(page: Page, section: 'cooling' | 'insulation' | 'construction' | 'rotor' | 'advanced' | 'curve') {
  const header = page.locator(`button[aria-controls="param-group-content-thermal-${section}"]`);
  if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
  await expect(header).toHaveAttribute('aria-expanded', 'true');
  return page.locator(`#param-group-content-thermal-${section}`);
}

test('thermal has its own setup, explains its inputs and waits for a solved run', async ({ page }) => {
  await openSolve(page);
  await showThermalSetup(page);
  for (const section of ['cooling', 'insulation', 'construction', 'rotor', 'advanced', 'curve']) {
    await expect(page.locator(`button[aria-controls="param-group-content-thermal-${section}"]`)).toBeVisible();
  }
  // The electromagnetic sections stay mounted but out of sight.
  await expect(page.locator('button[aria-controls="param-group-content-operating"]')).toBeHidden();

  await expect(runStatus(page)).toHaveText('Thermal uses the losses of a solved run. Run the electromagnetic analysis first.');
  await expect(page.getByRole('button', { name: '▶ Run thermal estimate', exact: true })).toHaveCount(0);
  await expect(monitor(page)).toContainText('Needs a solved run');

  const cooling = await openThermalSection(page, 'cooling');
  const modes = cooling.getByRole('radiogroup', { name: 'Thermal cooling', exact: true });
  await expect(modes.getByRole('radio', { name: /Still air/ })).toHaveAttribute('aria-checked', 'true');
  await expect(cooling.getByLabel('Ambient / coolant temperature (°C)', { exact: true })).toHaveValue('25');
  const housing = cooling.getByLabel('Housing heat transfer (W/m²K)', { exact: true });
  await expect(housing).toHaveValue('10');

  // Another kind of cooling cannot inherit still-air numbers.
  await modes.getByRole('radio', { name: /Forced air/ }).click();
  await expect(housing).toHaveValue('');
  await expect(cooling.getByRole('note')).toContainText('Enter the three values for your airflow');
  await cooling.getByRole('button', { name: 'Use still-air starter values', exact: true }).click();
  await expect(housing).toHaveValue('10');

  // Each number says what it means and where its range comes from.
  await cooling.getByRole('button', { name: 'Housing to surroundings help', exact: true }).click();
  await expect(page.getByText('Textbook ranges: 2–25 in still air', { exact: false })).toBeVisible();
  await page.keyboard.press('Escape');

  const insulation = await openThermalSection(page, 'insulation');
  await expect(insulation).toContainText('155');

  // Optional inputs show the value the model uses, so no box is blank.
  const rotor = await openThermalSection(page, 'rotor');
  await expect(rotor.getByLabel('Added rotor and magnet heat (W)', { exact: true })).toHaveValue('0');
  await expect(rotor.getByLabel('Share of that heat in the magnets (0–1)', { exact: true })).toHaveValue('0');
  await expect(page.locator('button[aria-controls="param-group-content-thermal-advanced"]')).toContainText('Defaults');
  const advanced = await openThermalSection(page, 'advanced');
  await expect(advanced.getByLabel('Steel conductivity (W/mK)', { exact: true })).toHaveValue('20');
  await expect(advanced.getByLabel('Thermal resistance multiplier', { exact: true })).toHaveValue('1');
  await expect(advanced.getByLabel('Slot conductivity model', { exact: true })).toHaveValue('series_lower_bound');
  expect(await advanced.locator('input').evaluateAll((inputs) => inputs.every((input) => (input as HTMLInputElement).value !== ''))).toBe(true);
  // Only the inputs that move the result are offered, and the mechanical split only when there is a mechanical loss.
  for (const gone of ['Conductor conductivity', 'Housing conductivity', 'Magnet conductivity', 'Exposed end-winding share', 'Mechanical loss']) {
    await expect(advanced.getByText(gone, { exact: false })).toHaveCount(0);
  }

  await page.getByRole('button', { name: 'Go to Electromagnetic setup', exact: true }).click();
  await expect(setupTabs(page).getByRole('tab', { name: 'Electromagnetic', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('button[aria-controls="param-group-content-operating"]')).toBeVisible();
});

test('the mechanical loss split is asked for only when the operating point has a mechanical loss', async ({ page }) => {
  await openSolve(page);
  const header = page.locator('button[aria-controls="param-group-content-operating"]');
  if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
  await page.locator('[data-guide="solve-operating"]').getByRole('spinbutton', { name: 'Mechanical loss', exact: true }).fill('5');
  await showThermalSetup(page);
  const advanced = await openThermalSection(page, 'advanced');
  await expect(advanced.getByRole('note')).toContainText('This run has 5 W of mechanical loss');
  // Where friction heat goes has no default: the three shares are for the user to give.
  for (const name of ['Mechanical loss to bearings (%)', 'Mechanical loss to housing (%)', 'Mechanical loss to rotor (%)']) {
    await expect(advanced.getByLabel(name, { exact: true })).toHaveValue('');
  }
});

test('a run solved without losses is told how to get them, in Solve and in Results', async ({ page }) => {
  await openSolve(page);
  await runMockedAnalysis(page, null);
  await showThermalSetup(page);
  await expect(runStatus(page)).toContainText('The last run has no losses. Turn on Losses & efficiency');
  await expect(monitor(page)).toContainText('Needs a run with losses');
  await expect(page.getByRole('button', { name: '▶ Run thermal estimate', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Go to Electromagnetic setup', exact: true }).click();
  await page.getByRole('button', { name: 'Full results →', exact: true }).click();
  await page.getByRole('tab', { name: 'Thermal', exact: true }).click();
  const notice = page.getByRole('region', { name: 'Thermal setup', exact: true });
  await expect(notice).toContainText("Thermal estimates use this run's losses");
  await expect(notice).toContainText('Losses & efficiency');
  await expect(page.getByRole('region', { name: 'Thermal estimate summary', exact: true })).toHaveCount(0);
});

test('the estimate runs from Solve, shows in Results part by part and exports its reports', async ({ page }, info) => {
  await openSolve(page);
  await runMockedAnalysis(page, 12);
  await showThermalSetup(page);
  await expect(runStatus(page)).toHaveText('Ready. Uses the losses of the solved operating point.');
  await expect(monitor(page)).toContainText('Ready to run');

  // A value the server would refuse is named before anything is sent.
  const cooling = await openThermalSection(page, 'cooling');
  const ambient = cooling.getByLabel('Ambient / coolant temperature (°C)', { exact: true });
  await ambient.fill('500');
  await expect(runStatus(page)).toHaveText('Ambient or coolant temperature must be between -273 and 200 °C.');
  await expect(monitor(page)).toContainText('Check the thermal setup');
  await expect(page.getByRole('button', { name: '▶ Run thermal estimate', exact: true })).toBeDisabled();
  await ambient.fill('25');

  const computed = page.waitForResponse((response) => new URL(response.url()).pathname === '/performance/thermal/point' && response.request().method() === 'POST');
  await page.getByRole('button', { name: '▶ Run thermal estimate', exact: true }).click();
  // The estimate returns in milliseconds. Its running state is held long enough to be seen.
  await expect(monitor(page).getByRole('progressbar', { name: 'Thermal estimate progress', exact: true })).toBeVisible();
  await expect(monitor(page)).toContainText('Running');
  await page.screenshot({ path: info.outputPath('thermal-running.png'), animations: 'disabled' });
  const response = await computed;
  expect(response.status(), await response.text()).toBe(200);
  const analysis = await response.json();
  expect(analysis.result.status).toBe('experimental');
  expect(Object.keys(analysis.result.nodes)).toEqual(expect.arrayContaining(['winding', 'end_winding', 'teeth', 'yoke', 'housing', 'magnets']));
  await expect(runStatus(page)).toContainText('Estimate ready: hottest part is the ');
  await expect(monitor(page)).toContainText('Complete');
  await expect(monitor(page).getByRole('progressbar')).toHaveCount(0);
  for (const line of ['Hottest part', 'Winding against its', 'Magnets', 'Heat to remove', 'Finished ']) {
    await expect(monitor(page)).toContainText(line);
  }
  await page.screenshot({ path: info.outputPath('thermal-complete.png'), animations: 'disabled' });

  await monitor(page).getByRole('button', { name: 'Thermal results →', exact: true }).click();
  const summary = page.getByRole('region', { name: 'Thermal estimate summary', exact: true });
  await expect(summary).toContainText('Hottest part');
  await expect(summary).toContainText('Winding against its 140 °C limit');
  // One unit on the card: the margin is in °C like the temperatures, not in K.
  await expect(summary.locator('.motor-constants-unit')).toHaveText([/^°C$/, /^°C\s*(Spare|Over)$/, /^°C$/]);
  await summary.screenshot({ path: info.outputPath('thermal-summary.png'), animations: 'disabled' });
  // Thermal starts from the losses: it comes after the electromagnetic cards and directly before the losses.
  const order = await page.locator('.public-result-detail').evaluate((grid) => [...grid.children].map((card) => (
    ['thermal-summary-card', 'public-magnetic-loading', 'dq-card', 'losses-card', 'cogging-card'].find((name) => card.classList.contains(name))
      ?? (card.classList.contains('motor-constants') ? 'constants' : card.className))));
  const thermalAt = order.indexOf('thermal-summary-card');
  expect(order.slice(0, 2)).toEqual(['constants', 'public-magnetic-loading']);
  expect(thermalAt).toBeGreaterThan(order.indexOf('public-magnetic-loading'));
  for (const earlier of ['dq-card', 'cogging-card']) expect(thermalAt).toBeGreaterThan(order.indexOf(earlier));
  if (order.includes('losses-card')) expect(order.indexOf('losses-card')).toBe(thermalAt + 1);

  await page.getByRole('tab', { name: 'Thermal', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Thermal estimate', exact: true });
  // Results shows the estimate; the setup is changed in Solve.
  await expect(panel.getByRole('button', { name: /Compute/ })).toHaveCount(0);
  await expect(panel.getByText('Change thermal setup', { exact: true })).toHaveCount(0);
  await expect(panel).toContainText('go back to Solve and open the Thermal setup');
  const card = panel.getByRole('region', { name: 'Thermal results', exact: true });
  for (const tile of ['Hottest part', 'Winding against its limit', 'Magnets', 'Heat to remove']) {
    await expect(card.locator('.thermal-kpis')).toContainText(tile);
  }
  const parts = card.locator('table.thermal-parts');
  for (const part of ['Slot winding', 'End winding', 'Magnets']) {
    await expect(parts.getByRole('button', { name: part, exact: true })).toBeVisible();
  }
  // The fixture run stores no field plot, and the panel says so instead of leaving a hole.
  await expect(card).toContainText('No solved cross-section is stored with this run');
  await parts.getByRole('button', { name: 'Magnets', exact: true }).click();
  const selected = card.getByRole('region', { name: 'Selected thermal part', exact: true });
  await expect(selected).toContainText('Magnets');
  await expect(selected).toContainText('W generated in this part');
  // The result stays as wide as the other Results cards rather than filling the window.
  expect((await panel.boundingBox())!.width).toBeLessThanOrEqual(1082);

  for (const [kind, signature] of [['PDF', '%PDF-'], ['CSV', 'report_schema']] as const) {
    const downloaded = page.waitForEvent('download');
    await card.getByRole('button', { name: `Run + thermal ${kind}`, exact: true }).click();
    const path = info.outputPath(`thermal-point.${kind.toLowerCase()}`);
    await (await downloaded).saveAs(path);
    expect((await readFile(path)).subarray(0, 64).toString('latin1')).toContain(signature);
  }
  await panel.screenshot({ path: info.outputPath('thermal-results.png'), animations: 'disabled' });
});

test('an outer-rotor motor is cooled through its mount and its rotor shell', async ({ page }) => {
  await openSolve(page, { label: /^SPM outrunner 14p\/12s/, slots: 12 });
  await runMockedAnalysis(page, 0.5);
  await showThermalSetup(page);
  const cooling = await openThermalSection(page, 'cooling');
  await expect(cooling.getByLabel('Rotor shell to surroundings (W/m²K)', { exact: true })).toHaveValue('10');
  await expect(cooling.getByLabel('Housing heat transfer (W/m²K)', { exact: true })).toHaveCount(0);
  const construction = await openThermalSection(page, 'construction');
  const mount = construction.getByLabel('Mount to surroundings (K/W)', { exact: true });
  await expect(mount).toHaveValue('10');

  // The mount is an exit for the heat, so the estimate cannot run without it.
  await mount.fill('');
  await expect(runStatus(page)).toHaveText('Enter mount to surroundings (K/W).');
  await mount.fill('10');

  const computed = page.waitForResponse((response) => new URL(response.url()).pathname === '/performance/thermal/point' && response.request().method() === 'POST');
  await page.getByRole('button', { name: '▶ Run thermal estimate', exact: true }).click();
  const response = await computed;
  expect(response.status(), await response.text()).toBe(200);
  const nodes = Object.keys((await response.json()).result.nodes);
  expect(nodes).toContain('mount');
  expect(nodes).not.toContain('housing');

  await page.getByRole('button', { name: 'View Results →', exact: true }).click();
  await page.getByRole('tab', { name: 'Thermal', exact: true }).click();
  const parts = page.getByRole('region', { name: 'Thermal results', exact: true }).locator('table.thermal-parts');
  await expect(parts.getByRole('button', { name: 'Stator mount', exact: true })).toBeVisible();
  await expect(parts.getByRole('button', { name: 'Housing', exact: true })).toHaveCount(0);
});

test('a torque curve stays beside the estimate and says why speeds are missing', async ({ page }) => {
  await openSolve(page);
  await runMockedAnalysis(page, 12);
  await showThermalSetup(page);
  const computed = page.waitForResponse((response) => new URL(response.url()).pathname === '/performance/thermal/point' && response.request().method() === 'POST');
  await page.getByRole('button', { name: '▶ Run thermal estimate', exact: true }).click();
  // The curve records the same inputs as the estimate, as the API would.
  const recordedInputs = (await (await computed).json()).inputs;
  await expect(monitor(page)).toContainText('Complete');

  // The curve itself needs two torque–speed maps, so its stream is a fixture here.
  const held = (torque: number, winding: number, magnets: number) => ({
    torque_Nm: torque, current_peak_A: 42.43, phase_voltage_peak_V: 20, winding_temperature_C: winding, magnet_temperature_C: magnets,
    iterations: 6, temperature_residual_K: 0.001, verification_status: 'PASS', verification_reason: 'Direct solve agrees.',
  });
  const outsideMaps = 'The magnets would run outside the two solved maps (20 to 80 C). Values are never extrapolated: solve a wider pair of maps.';
  const tooHot = 'The winding would settle outside -50 to 250 C with these cooling values, which is beyond what this estimate supports. Raise the cooling values or lower the current.';
  const notConfirmed = 'A direct solve at this point puts the magnets past the temperature limit, so the value read from the maps is not reported.';
  const couldNotRun = 'A direct solve at this point could not run (Magneto2D stopped), so the value read from the maps is not reported.';
  const speed = (rpm: number, point: ReturnType<typeof held> | null, reason: string) => ({
    speed_rpm: rpm, status: point ? 'experimental' : 'unavailable', status_reason: reason,
    limiting_constraint: point ? 'current: drive continuous' : reason, point, user_magnet_case: null,
  });
  const curve = {
    id: 'f'.repeat(32), kind: 'rating', design_name: 'Motor',
    inputs: recordedInputs,
    result: {
      kind: 'thermally_limited_rating', status: 'experimental', status_reason: 'Experimental.', inputs: recordedInputs,
      limits: {}, control: 'mtpa', acceptance_status: 'NOT_COMPARED', cancelled: false, notes: ['Search grid with local refinement.'],
      points: [speed(0, held(10.9, 43, 41.1), 'Coupled estimate.'), speed(1200, held(10.4, 81.2, 78.8), 'Coupled estimate.'),
        // Found on the maps, then rejected by its direct solve: it keeps its numbers but is not a result.
        { ...speed(1500, held(9.1, 120.6, 79.98), notConfirmed), status: 'unavailable', limiting_constraint: 'temperature: magnets' },
        // Its direct solve could not run: the API marks it unavailable and keeps the exception as its reason.
        { ...speed(1650, { ...held(8.7, 110.2, 75.5), status: 'unavailable', verification_status: 'FAIL', verification_reason: 'Direct limiting-point solve failed: Magneto2D stopped' }, couldNotRun),
          status: 'unavailable', limiting_constraint: 'voltage' },
        // Saved by an earlier build: its direct solve raised, yet the speed stayed experimental. It reads as the speed above.
        { ...speed(1700, { ...held(8.25, 112.4, 76.6), verification_status: 'FAIL', verification_reason: 'Magneto2D stopped' },
          'Coupled estimate. The direct solve of this point failed.'), limiting_constraint: 'voltage' },
        speed(1800, null, outsideMaps), speed(4200, null, `${outsideMaps}; ${tooHot}`), speed(6000, null, tooHot)],
    },
  };
  await page.route('**/performance/thermal/stream', (route) => route.fulfill({
    contentType: 'text/event-stream',
    body: `event: progress\ndata: ${JSON.stringify({ stage: 'Solving the cold map', done: 3, total: 58 })}\n\nevent: complete\ndata: ${JSON.stringify(curve)}\n\n`,
  }));
  const section = await openThermalSection(page, 'curve');
  await section.getByRole('button', { name: 'Run torque curve', exact: true }).click();

  // The finished curve is added to the monitor; the estimate is still there.
  await expect(monitor(page)).toContainText('Torque curve · 2 of 8 speeds');
  await expect(monitor(page)).toContainText('Held at 0 rpm');
  await expect(monitor(page)).toContainText('Held at 1,200 rpm');
  await expect(monitor(page)).not.toContainText('Held at 1,700 rpm');
  await expect(monitor(page)).toContainText('Hottest part');
  await expect(monitor(page)).not.toContainText('previous inputs');

  // New cooling: the estimate and the curve are both from the previous inputs until they run again.
  const cooling = await openThermalSection(page, 'cooling');
  const housing = cooling.getByLabel('Housing heat transfer (W/m²K)', { exact: true });
  await housing.fill('12');
  await expect(monitor(page)).toContainText('Inputs changed');
  await expect(monitor(page)).toContainText('Torque curve · 2 of 8 speeds · from the previous inputs');
  await expect(monitor(page)).toContainText('The thermal inputs changed since this torque curve.');
  await housing.fill('10');
  await expect(monitor(page)).not.toContainText('previous inputs');

  await monitor(page).getByRole('button', { name: 'Thermal results →', exact: true }).click();
  await page.getByRole('tab', { name: 'Thermal', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Thermal estimate', exact: true });
  await expect(panel.getByRole('region', { name: 'Thermal results', exact: true }).locator('.thermal-kpis')).toContainText('Hottest part');
  const card = panel.getByRole('region', { name: 'Thermally limited torque curve', exact: true });
  const summary = card.locator('.thermal-rating-summary');
  await expect(summary).toContainText('2 of 8 speeds have a result.');
  await expect(summary).toContainText('No result from 1,500 rpm: A direct solve at this point puts the magnets past the temperature limit');
  const rows = card.locator('.thermal-rating-table tbody tr');
  await expect(rows).toHaveCount(8);
  await expect(rows.nth(1)).toContainText('current: drive continuous');
  // A rejected speed does not show the numbers it was rejected for.
  await expect(rows.nth(2)).toContainText('Not confirmed by the direct solve');
  await expect(rows.nth(2)).not.toContainText('9.1');
  // Nor does a speed whose direct solve could not run.
  await expect(rows.nth(3)).toContainText('Not confirmed by the direct solve');
  await expect(rows.nth(3)).not.toContainText('8.7');
  // Nor a speed an earlier build saved as held although its direct solve could not run.
  await expect(rows.nth(4)).toContainText('Not confirmed by the direct solve');
  await expect(rows.nth(4)).not.toContainText('8.25');
  await expect(card.locator('.thermal-notes').first()).toContainText('1,700 rpm: A direct solve at this point could not run (Magneto2D stopped), so the value read from the maps is not reported.');
  // A missing speed shows dashes and a short reason, not a row of "Unavailable".
  await expect(rows.nth(5)).toContainText('Magnets hotter than the hot map');
  await expect(rows.nth(5)).not.toContainText('Unavailable');
  await expect(rows.nth(7)).toContainText('Too hot with this cooling');
});

test('an edit to the thermal inputs marks the saved estimate as from the previous inputs', async ({ page }, info) => {
  await openSolve(page);
  await runMockedAnalysis(page, 12);
  await showThermalSetup(page);
  await page.getByRole('button', { name: '▶ Run thermal estimate', exact: true }).click();
  await expect(runStatus(page)).toContainText('Estimate ready: hottest part is the ');
  const ready = await runStatus(page).textContent();
  const cooling = await openThermalSection(page, 'cooling');
  const ambient = cooling.getByLabel('Ambient / coolant temperature (°C)', { exact: true });

  // The same value typed another way changes nothing the estimate uses.
  await ambient.fill('25.0');
  await expect(runStatus(page)).toHaveText(ready!);
  await expect(monitor(page)).toContainText('Complete');

  // A new ambient temperature: the saved estimate no longer describes the setup.
  await ambient.fill('40');
  await expect(runStatus(page)).toHaveText('The thermal inputs changed since the last estimate. Run it again to update the temperatures.');
  await expect(runStatus(page)).toHaveClass(/needs-attention/);
  await expect(page.getByRole('button', { name: 'View Results →', exact: true })).toHaveCount(0);
  await expect(monitor(page)).toContainText('Inputs changed');
  await expect(monitor(page)).toContainText('The temperatures below are from the previous inputs.');
  await expect(monitor(page).getByRole('table', { name: 'Previous estimate, from the previous inputs', exact: true })).toBeVisible();
  await expect(monitor(page)).toContainText('From the previous inputs · uncalibrated');
  await expect(monitor(page)).not.toContainText('Finished ');
  await page.screenshot({ path: info.outputPath('thermal-previous-inputs.png'), animations: 'disabled' });

  // Results shows the saved estimate, and says it is from the previous inputs: first in the summary card,
  // whose old temperatures are kept but not shown as current.
  await monitor(page).getByRole('button', { name: 'Thermal results →', exact: true }).click();
  const summaryCard = page.getByRole('region', { name: 'Thermal estimate summary', exact: true });
  await expect(summaryCard).toContainText('From the previous thermal inputs. Run it again under Solve → Thermal to update it.');
  await expect(summaryCard.getByRole('table', { name: 'Previous estimate, from the previous inputs', exact: true })).toBeVisible();
  await expect(summaryCard).toContainText('Hottest part');
  await summaryCard.screenshot({ path: info.outputPath('thermal-summary-previous-inputs.png'), animations: 'disabled' });
  await page.getByRole('tab', { name: 'Thermal', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Thermal estimate', exact: true });
  await expect(panel).toContainText('This estimate is from the previous thermal inputs. Run it again under Solve → Thermal.');

  // Back to the inputs it was run with: current again, with no rerun.
  await page.getByRole('navigation', { name: 'Motor workflow', exact: true }).getByRole('button', { name: /Solve$/ }).click();
  await showThermalSetup(page);
  const again = (await openThermalSection(page, 'cooling')).getByLabel('Ambient / coolant temperature (°C)', { exact: true });
  await again.fill('25');
  await expect(runStatus(page)).toHaveText(ready!);
  await again.fill('40');
  const sent = page.waitForRequest((request) => new URL(request.url()).pathname === '/performance/thermal/point' && request.method() === 'POST');
  await page.getByRole('button', { name: '▶ Run thermal estimate again', exact: true }).click();
  expect((await sent).postDataJSON().inputs.ambient_C).toBe(40);
  await expect(runStatus(page)).toContainText('Estimate ready: hottest part is the ');
  await expect(monitor(page)).toContainText('Complete');
  await expect(monitor(page)).not.toContainText('previous inputs');
  // The new estimate is current everywhere, the Results summary card included.
  await page.getByRole('button', { name: 'View Results →', exact: true }).click();
  await expect(summaryCard).toContainText('Hottest part');
  await expect(summaryCard).not.toContainText('previous thermal inputs');
  await expect(summaryCard.getByRole('table', { name: 'Previous estimate, from the previous inputs', exact: true })).toHaveCount(0);
});

test('one temperature unit is used everywhere in thermal, and it can be changed', async ({ page }) => {
  await openSolve(page);
  await runMockedAnalysis(page, 12);
  await showThermalSetup(page);
  const units = page.getByRole('radiogroup', { name: 'Temperatures in', exact: true });
  await expect(units.getByRole('radio', { name: '°C', exact: true })).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: '▶ Run thermal estimate', exact: true }).click();
  await expect(monitor(page)).toContainText('Complete');
  // Celsius by default, for temperatures and for the margin alike.
  await expect(monitor(page)).toContainText('Winding against its 140 °C limit');
  await expect(monitor(page)).toContainText(/°C (spare|over)/);
  await expect(monitor(page)).not.toContainText(/\dK|K (spare|over)/);
  const cooling = await openThermalSection(page, 'cooling');
  await expect(cooling.getByLabel('Ambient / coolant temperature (°C)', { exact: true })).toHaveValue('25');

  // Fahrenheit: the same motor, read and typed in another unit.
  await units.getByRole('radio', { name: '°F', exact: true }).click();
  await expect(page.locator('.thermal-unit-picker')).toContainText('Reports and solver messages stay in °C.');
  const ambient = cooling.getByLabel('Ambient / coolant temperature (°F)', { exact: true });
  await expect(ambient).toHaveValue('77');
  // A closed section shows its summary in its header, in the same unit.
  await expect(page.locator('button[aria-controls="param-group-content-thermal-insulation"]')).toContainText('winding limit 284 °F');
  await expect(monitor(page)).toContainText('Winding against its 284 °F limit');
  await expect(runStatus(page)).toContainText(/hottest part is the .* °F\./);
  const insulation = await openThermalSection(page, 'insulation');
  await expect(page.locator('button[aria-controls="param-group-content-thermal-cooling"]')).toContainText('77 °F');
  await expect(insulation.getByLabel('Winding hotspot allowance (°F)', { exact: true })).toHaveValue('27');
  await expect(insulation).toContainText('That is the 311 °F rating less the 27 °F allowance.');

  // Typing in the chosen unit keeps the value the estimate uses in °C.
  await openThermalSection(page, 'cooling');
  await ambient.fill('104');
  await ambient.blur();
  await expect(ambient).toHaveValue('104');
  await expect(runStatus(page)).toHaveText('The thermal inputs changed since the last estimate. Run it again to update the temperatures.');
  const sent = page.waitForRequest((request) => new URL(request.url()).pathname === '/performance/thermal/point' && request.method() === 'POST');
  await page.getByRole('button', { name: '▶ Run thermal estimate again', exact: true }).click();
  expect((await sent).postDataJSON().inputs.ambient_C).toBeCloseTo(40, 6);
  await expect(monitor(page)).toContainText('Complete');

  // Results follows, and the choice is remembered.
  await monitor(page).getByRole('button', { name: 'Thermal results →', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Thermal estimate summary', exact: true }).locator('.motor-constants-unit').first()).toHaveText('°F');
  await page.getByRole('tab', { name: 'Thermal', exact: true }).click();
  const card = page.getByRole('region', { name: 'Thermal results', exact: true });
  await expect(card.locator('.thermal-kpis')).toContainText(/°F (spare|over)/);
  await expect(card.locator('table.thermal-parts tbody tr').first()).toContainText('°F');
  await expect(page.getByRole('region', { name: 'Thermal estimate', exact: true })).toContainText('104 °F');
  await page.reload();
  expect(await page.evaluate(() => localStorage.getItem('coilem.thermal.temperatureUnit'))).toBe('F');
});
