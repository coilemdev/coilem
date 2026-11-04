/** Unrequested performance maps do not appear or start work in Results. */
import { expect, test, type Page } from '@playwright/test';

export async function checkPerformanceRegressions(page: Page): Promise<void> {
  await test.step('an operating-point run leaves the opt-in map out of Results', async () => {
    await expect(page.getByRole('tab', { name: 'Torque–speed', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Solve map/ })).toHaveCount(0);
    await expect(page.getByRole('tab', { name: 'Torque', exact: true })).toBeVisible();
  });
}
