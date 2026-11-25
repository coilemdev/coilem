import { expect, test, type Page } from '@playwright/test';

const apiUrl = `http://127.0.0.1:${process.env.COILEM_TEST_API_PORT || 58000}`;

const upToDate = {
  current: '0.5.11',
  enabled: true,
  disabled_by: null,
  switch: 'COILEM_UPDATE_CHECK',
  checked_at: '2026-12-01T12:00:00+00:00',
  up_to_date: true,
  latest: null,
  release_url: null,
  upgrade_command: null,
  self_upgrade: false,
  last_upgrade: null,
};

const newer = {
  ...upToDate,
  up_to_date: false,
  latest: '0.5.12',
  release_url: 'https://github.com/coilemdev/coilem/releases/tag/v0.5.12',
  upgrade_command: 'uv tool upgrade coilem',
};

async function serveUpdates(page: Page, status: object) {
  await page.route(`${apiUrl}/updates`, (route) => route.fulfill({ json: status }));
}

test('the version label announces a newer release and how to get it', async ({ page }) => {
  await serveUpdates(page, newer);
  await page.goto('/');

  const label = page.getByRole('button', { name: /Version 0\.5\.12 is available/ });
  await expect(label).toContainText('Update');
  await label.click();

  const panel = page.locator('.version-update .popover-panel');
  await expect(panel).toContainText('coilEM 0.5.12 is available.');
  await expect(panel.locator('code').first()).toHaveText('uv tool upgrade coilem');
  await expect(panel).toContainText('uvx coilem@latest');
  await expect(panel.getByRole('link')).toHaveCount(0);
});

test('with no newer release the version is plain text with no menu', async ({ page }) => {
  await serveUpdates(page, upToDate);
  await page.goto('/');

  await expect(page.locator('.version-label .logo-version')).toHaveText(/^v\d+\.\d+\.\d+/);
  await expect(page.locator('.version-label button')).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /newer version/ })).toHaveCount(0);
});

test('where coilEM can upgrade itself, one button upgrades and the page reloads when it is back', async ({ page }) => {
  await serveUpdates(page, { ...newer, self_upgrade: true });
  let upgrades = 0;
  let health: 'up' | 'down' = 'up';
  await page.route(`${apiUrl}/updates/upgrade`, async (route) => {
    upgrades += 1;
    health = 'down';
    await route.fulfill({ status: 202, json: { restarting: true, from: '0.5.11', to: '0.5.12' } });
    setTimeout(() => { health = 'up'; }, 3000);
  });
  await page.route(`${apiUrl}/health`, async (route) => {
    if (health === 'down') await route.abort('connectionrefused');
    else await route.fallback();
  });
  await page.goto('/');

  await page.getByRole('button', { name: /Version 0\.5\.12 is available/ }).click();
  const panel = page.locator('.version-update .popover-panel');
  await expect(panel).toHaveText(/^coilEM 0\.5\.12 is available\.\s*Upgrade and restart$/);
  const reloaded = page.waitForEvent('load', { timeout: 30_000 });
  await panel.getByRole('button', { name: 'Upgrade and restart' }).click();

  await expect(panel.getByRole('status')).toContainText('Upgrading to coilEM 0.5.12…');
  await reloaded;
  expect(upgrades).toBe(1);
});

test('a refused upgrade says why and leaves the page alone', async ({ page }) => {
  await serveUpdates(page, { ...newer, self_upgrade: true });
  await page.route(`${apiUrl}/updates/upgrade`, (route) => route.fulfill({
    status: 409,
    json: { detail: { error_code: 'SOLVE_RUNNING', message: 'A solve is running. Wait for it to finish, or cancel it, then upgrade.' } },
  }));
  await page.goto('/');

  await page.getByRole('button', { name: /Version 0\.5\.12 is available/ }).click();
  const panel = page.locator('.version-update .popover-panel');
  await panel.getByRole('button', { name: 'Upgrade and restart' }).click();

  await expect(panel.getByRole('alert')).toContainText('A solve is running.');
  await expect(panel.getByRole('button', { name: 'Upgrade and restart' })).toBeVisible();
});

test('after an upgrade that did not finish, the menu says so and gives the command', async ({ page }) => {
  await serveUpdates(page, {
    ...newer,
    self_upgrade: true,
    last_upgrade: { ok: false, from: '0.5.11', to: null, message: 'The upgrade command failed (exit code 2); its output is in the terminal coilEM runs in.', manual: 'uv tool upgrade coilem' },
  });
  await page.goto('/');

  await page.getByRole('button', { name: /Version 0\.5\.12 is available/ }).click();

  const panel = page.locator('.version-update .popover-panel');
  await expect(panel.getByRole('alert')).toContainText('The upgrade did not finish. The upgrade command failed (exit code 2)');
  await expect(panel.locator('code')).toHaveText('uv tool upgrade coilem');
  await expect(panel.getByRole('button', { name: 'Try again' })).toBeVisible();
});
