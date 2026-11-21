const { chromium } = require('playwright');
const fs = require('fs');
const [OUT] = process.argv.slice(2);
const BASE = 'http://127.0.0.1:8768/';
const PLACES = { measured: true, n: 1, points: [
  { external_id: 'en:Rome', title: 'Rome', edition: 'en', lat: 41.9, lon: 12.5, joinable: true } ] };
const ADDR = { measured: true, complete: true, truncated: false, n: 2, points: [
  { edition: 'fr', title: 'Salle Fixture', external_id: 'fr:Salle Fixture', field: 'adresse', address: '2 Rue Fixture, Paris',
    lat: 48.85, lon: 2.35, osm_object: 'way/42', osm_vintage: '2026-10-01T00:00:00+00:00' },
  { edition: 'de', title: 'Haus Fixture', external_id: 'de:Haus Fixture', field: 'adresse', address: 'Fixturestraße 7, Berlin',
    lat: 52.52, lon: 13.40, osm_object: 'node/7', osm_vintage: null } ] };

async function open(ctx) {
  const pg = await ctx.newPage();
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  await pg.route('**/api/wiki/lane/places*', r => r.fulfill({ json: PLACES }));
  await pg.route('**/api/wiki/lane/located-addresses*', r => r.fulfill({ json: ADDR }));
  await pg.goto(BASE, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(800);
  await pg.evaluate(() => showTab('timemap'));
  await pg.waitForTimeout(1500);
  await pg.evaluate(() => [...document.querySelectorAll('#tab-timemap [data-oomap-wiki]')][0].click());
  await pg.waitForTimeout(2500);
  return { pg, errs };
}
const facts = (pg) => pg.evaluate(() => {
  const s = [...document.querySelectorAll('svg#oo-choro rect, svg#oo-choro circle')]
    .filter(e => /Fixture|Rome \(en\)/.test(e.getAttribute('title') || e.dataset.ooTip || ''));
  return { markers: s.map(e => ({ tag: e.tagName, title: e.getAttribute('title') || e.dataset.ooTip, tip_target: e.classList.contains('oo-tip-target'),
    title_children: e.querySelectorAll('title').length })) };
});
const tip = (pg) => pg.evaluate(() => { const t = document.getElementById('oo-tip'); const cs = getComputedStyle(t);
  return { text: t.textContent, opacity: cs.opacity, aria_hidden: t.getAttribute('aria-hidden') }; });
async function shot(pg, el, file) {
  const b = await el.boundingBox(); const tb = await pg.locator('#oo-tip').boundingBox();
  const x0 = Math.max(0, Math.min(b.x, tb ? tb.x : b.x) - 40), y0 = Math.max(0, Math.min(b.y, tb ? tb.y : b.y) - 60);
  const x1 = Math.max(b.x + b.width, tb ? tb.x + tb.width : 0) + 40, y1 = Math.max(b.y + b.height, tb ? tb.y + tb.height : 0) + 60;
  await pg.screenshot({ path: `${OUT}/${file}`, type: 'jpeg', quality: 70, clip: { x: x0, y: y0, width: x1 - x0, height: y1 - y0 } });
  return fs.statSync(`${OUT}/${file}`).size;
}
(async () => {
  const b = await chromium.launch();
  const out = {};
  // Desktop: a mouse hover on each marker.
  { const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } });
    const { pg, errs } = await open(ctx);
    out.desktop = await facts(pg); out.desktop.hover = [];
    for (const [sel, file] of [['rect[title*="Rue Fixture"]', 'desktop-hover-dated-address.jpg'],
                               ['rect[title*="Fixturestraße"]', 'desktop-hover-undated-address.jpg'],
                               ['circle[title="Rome (en)"]', 'desktop-hover-page.jpg']]) {
      const el = await pg.locator('svg#oo-choro ' + sel).first().elementHandle();
      await el.hover({ force: true }); await pg.waitForTimeout(500);
      const t = await tip(pg); out.desktop.hover.push({ sel, ...t, file, bytes: await shot(pg, el, file) });
      await pg.mouse.move(5, 5); await pg.waitForTimeout(300);
    }
    out.desktop.page_errors = errs; await ctx.close(); }
  // Phone: a touch long-press on the dated square (it had no way to reach the provenance before).
  { const ctx = await b.newContext({ viewport: { width: 412, height: 900 }, hasTouch: true, isMobile: true, deviceScaleFactor: 1 });
    const { pg, errs } = await open(ctx);
    out.phone = await facts(pg);
    const el = await pg.locator('svg#oo-choro rect[title*="Rue Fixture"]').first().elementHandle();
    await el.scrollIntoViewIfNeeded();
    const bb = await el.boundingBox();
    const cdp = await ctx.newCDPSession(pg);
    const pt = { x: bb.x + bb.width / 2, y: bb.y + bb.height / 2 };
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [pt] });
    await pg.waitForTimeout(800);
    const t = await tip(pg);
    out.phone.long_press = { ...t, file: 'phone-long-press-dated-address.jpg', bytes: await shot(pg, el, 'phone-long-press-dated-address.jpg') };
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    out.phone.page_errors = errs; await ctx.close(); }
  await b.close();
  console.log(JSON.stringify(out, null, 1));
})();
