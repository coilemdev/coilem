import { expect, test } from '@playwright/test';
import { screenshotPanel } from './performance-capture';

test('capture includes the bottom axis inside nested Results scroll containers', async ({ page }, info) => {
  await page.setContent(`
    <style>body{margin:0}.outer{height:500px;overflow:hidden}.scroll{height:450px;overflow:auto}
    .performance-panel{width:800px;height:1900px;background:#123;display:flex;flex-direction:column;justify-content:space-between}
    footer{height:100px;background:#fc0}</style>
    <div class="outer"><div class="scroll" style="max-height:450px"><section class="performance-panel">
    <header>Torque–speed</header><svg width="800" height="1000"><path d="M0 0L600 900" stroke="red"/></svg>
    <footer>Efficiency map · Speed (rpm)</footer></section></div></div>`);
  const viewport = page.viewportSize();
  const original = await page.locator('.scroll').getAttribute('style');
  const png = await screenshotPanel(page, info.outputPath('complete-panel.png'));
  expect(png!.readUInt32BE(20), 'PNG covers all 1900 pixels, including the bottom axis').toBe(1900);
  expect(page.viewportSize()).toEqual(viewport);
  expect(await page.locator('.scroll').getAttribute('style')).toBe(original);
  await expect(page.locator('.outer')).toHaveCSS('height', '500px');
  await expect(page.locator('.outer')).toHaveCSS('overflow', 'hidden');
});
