// Headless smoke test: node tests/e2e/smoke.js [outdir]
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const assert = require('assert');
const out = process.argv[2] || '.';
(async () => {
  const srv = spawn('python3', ['-m', 'http.server', '8765', '-d', path.join(__dirname, '../../web')], { stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 800));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 860 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/ERR_|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  try {
    await page.goto('http://localhost:8765/#t=24', { waitUntil: 'load' });
    await page.waitForSelector('.card');
    await page.waitForTimeout(600);
    const n = await page.locator('.card').count();
    assert.strictEqual(n, 4, 'expected 4 storm cards, got ' + n);
    assert.strictEqual(await page.locator('.badge:not(.live)').count(), 1, 'exactly one bomb badge');
    // raster canvas has painted pixels
    const painted = await page.evaluate(() => {
      const c = document.querySelector('#map canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let k = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) k++; return k;
    });
    assert(painted > 20000, 'field canvas looks empty: ' + painted);
    // marching squares: contour of a level yields segments, all inside grid
    const seg = await page.evaluate(() => window.__atlas.contour(24, 1008).length);
    assert(seg > 40, 'no isobar segments');
    // markers + time slider
    assert((await page.locator('.lmark').count()) >= 3, 'expected L markers at t=24');
    await page.screenshot({ path: path.join(out, 'shot-overview.png') });
    await page.locator('#slider').fill('30');
    assert.match(await page.locator('#timelabel').innerText(), /\+90 h/);
    // select the bomb storm
    await page.locator('.card', { has: page.locator('.badge:not(.live)') }).click();
    await page.waitForSelector('#detail:not([hidden])');
    await page.fill('#nm', 'Storm Test');
    assert.match(await page.locator('#ep').innerText(), /^STORM TEST\nActive: .*\nMax wind: \d+ km\/h\nMin pressure: \d+ hPa/);
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(out, 'shot-selected.png') });
    // waves layer + units
    await page.click('[data-raster=swh]'); await page.selectOption('#units', 'kt');
    await page.waitForTimeout(300);
    assert.match(await page.locator('#legend').innerText(), /Significant wave height/);
    // play advances
    await page.click('#btn-play'); const t0 = await page.inputValue('#slider'); await page.waitForTimeout(1200); await page.click('#btn-play');
    assert.notStrictEqual(await page.inputValue('#slider'), t0, 'play did not advance');
    // mobile layout renders
    await page.setViewportSize({ width: 390, height: 800 }); await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(out, 'shot-mobile.png') });
    assert.deepStrictEqual(errors, [], 'console errors: ' + errors.join('\n'));
    console.log('E2E OK');
  } catch (e) { console.error('E2E FAIL:', e.message); await page.screenshot({ path: path.join(out, 'fail.png') }); process.exitCode = 1; }
  finally { await browser.close(); srv.kill(); }
})();
