/** UI fault/race regressions using analytic map inputs and the real drive API. */
import { expect, test, type Page } from '@playwright/test';

export async function checkPerformanceRegressions(page: Page): Promise<void> {
  let provideMap = false;
  await page.route('**/performance/map/status', async (route) => {
    const peak = route.request().postDataJSON().map.peak_current_A as number;
    const currents = [0, peak / 4, peak / 2, 3 * peak / 4, peak];
    const gammas = [0, 15, 30, 45, 60, 75, 90];
    const points = currents.flatMap((current) => gammas.map((gamma) => {
      const id = -current * Math.sin(gamma * Math.PI / 180);
      const iq = current * Math.cos(gamma * Math.PI / 180);
      return {
        current_peak_A: current, gamma_deg: gamma, i_d_A: id, i_q_A: iq, status: 'ok',
        avg_torque_Nm: 6 * 0.044 * iq, lambda_d_Wb: 0.044 + 0.00014 * id, lambda_q_Wb: 0.00014 * iq,
        iron_loss_W: 30, iron_hysteresis_loss_W: 20, iron_eddy_loss_W: 10,
      };
    }));
    await route.fulfill({ json: {
      scope_key: 'browser-regression-map-0001', solves_total: 29, solves_finished: provideMap ? 29 : 0, positions_per_point: 12,
      map: provideMap ? {
        scope_key: 'browser-regression-map-0001', pole_pairs: 4, current_peak_A: currents, gamma_deg: gammas,
        reference_speed_rpm: 2400, rotor_positions: 12, mesh_density: 'normal', points,
      } : null, torque_agreement_pct: [],
    } });
  });
  await page.route('**/performance/map/stream', (route) => route.fulfill({
    contentType: 'text/event-stream', body: 'event: progress\ndata: {"done":1,"total":29,"status":"ok","elapsed_s":1}\n\n',
  }));
  await page.getByRole('tab', { name: 'Torque–speed', exact: true }).click();
  await test.step('an unfinished map stream recovers without reloading', async () => {
    await page.getByRole('button', { name: /^Solve map \(/ }).click();
    await expect(page.getByRole('alert')).toContainText('ended before completion');
    await expect(page.getByRole('button', { name: /^Solve map \(/ })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toHaveCount(0);
  });
  provideMap = true;
  await page.locator('.performance-limits select').last().selectOption('standard');
  await expect(page.locator('.performance-stats')).toBeVisible();
  await test.step('an empty optional current limit is submitted as null', async () => {
    const continuous = page.getByLabel(/^Continuous current/);
    await continuous.fill('');
    await continuous.blur();
    const submitted = page.waitForRequest((request) => request.url().endsWith('/performance/drive'));
    const computed = page.waitForResponse((response) => response.url().endsWith('/performance/drive'));
    await page.getByRole('button', { name: 'Apply limits', exact: true }).click();
    expect((await submitted).postDataJSON().limits.continuous_current_A).toBeNull();
    const response = await computed;
    expect(response.ok()).toBe(true);
    expect((await response.json()).envelope.curves.map((curve: { limit: string }) => curve.limit)).toEqual(['peak']);
    await expect(continuous).toHaveValue('');
  });
  await test.step('an older response cannot overwrite a newer drive control', async () => {
    let releaseOld!: () => void;
    let requestHeld!: () => void;
    const oldHeld = new Promise<void>((resolve) => { releaseOld = resolve; });
    const firstHeld = new Promise<void>((resolve) => { requestHeld = resolve; });
    await page.route('**/performance/drive', async (route) => {
      const response = await route.fetch();
      if (route.request().postDataJSON().control === 'mtpa') { requestHeld(); await oldHeld; }
      await route.fulfill({ response });
    });
    try {
      await page.getByRole('button', { name: 'Apply limits', exact: true }).click();
      await firstHeld;
      const latest = page.waitForResponse((response) => response.url().endsWith('/performance/drive')
        && response.request().postDataJSON().control === 'least_loss');
      await page.locator('.performance-limits select').first().selectOption('least_loss');
      expect((await latest).ok()).toBe(true);
      await expect(page.getByRole('button', { name: 'Apply limits', exact: true })).toBeEnabled();
      const old = page.waitForResponse((response) => response.url().endsWith('/performance/drive')
        && response.request().postDataJSON().control === 'mtpa');
      releaseOld();
      await old;
      const submitted = page.waitForRequest((request) => request.url().endsWith('/performance/report/csv'));
      const downloaded = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Performance CSV', exact: true }).click();
      expect((await submitted).postDataJSON().control).toBe('least_loss');
      expect(await (await downloaded).failure()).toBeNull();
      await expect(page.locator('.performance-limits select').first()).toHaveValue('least_loss');
    } finally { releaseOld(); await page.unroute('**/performance/drive'); }
  });
  await page.unroute('**/performance/map/status');
  await page.unroute('**/performance/map/stream');
  await page.getByRole('tab', { name: 'Torque', exact: true }).click();
}
