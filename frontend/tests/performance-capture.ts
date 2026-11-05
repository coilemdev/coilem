import type { Page } from '@playwright/test';

export async function screenshotPanel(page: Page, path: string) {
  // A locator screenshot can still be clipped by the Results scroll container.
  // Expand only clipping ancestors for capture, then restore the actual UI.
  const panel = page.locator('.performance-panel');
  const restore = await panel.evaluate((element) => {
    const changed: Array<{ index: number; style: string | null }> = [];
    let parent = element.parentElement;
    let index = 0;
    while (parent && parent !== document.body) {
      const style = getComputedStyle(parent);
      if (/auto|scroll|hidden|clip/.test(`${style.overflow} ${style.overflowY}`)) {
        changed.push({ index, style: parent.getAttribute('style') });
        parent.style.setProperty('overflow', 'visible', 'important');
        parent.style.setProperty('height', 'auto', 'important');
        parent.style.setProperty('max-height', 'none', 'important');
      }
      parent = parent.parentElement;
      index++;
    }
    return changed;
  });
  try {
    const bounds = await panel.boundingBox();
    if (!bounds) throw new Error('Performance panel has no capture bounds');
    const viewport = page.viewportSize()!;
    await page.setViewportSize({ width: viewport.width, height: Math.max(viewport.height, Math.ceil(bounds.y + bounds.height + 32)) });
    try { return await panel.screenshot({ path, animations: 'disabled' }); }
    finally { await page.setViewportSize(viewport); }
  } finally {
    await panel.evaluate((element, changes) => {
      let parent = element.parentElement;
      let index = 0;
      while (parent && parent !== document.body) {
        const change = changes.find((item) => item.index === index);
        if (change) {
          if (change.style === null) parent.removeAttribute('style');
          else parent.setAttribute('style', change.style);
        }
        parent = parent.parentElement;
        index++;
      }
    }, restore);
  }
}
