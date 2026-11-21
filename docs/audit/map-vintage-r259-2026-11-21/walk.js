const { chromium } = require('playwright');
const fs = require('fs');
const [OUT, TAG] = process.argv.slice(2);
const SURFACES = [
  ['world-map', 'timemap', []],
  ['world-map-offline-osm', 'timemap', ['[data-oomap-osm]']],
  ['library-world-coverage', 'library', ['coverage']],
  ['governments-map', 'law', ['map']],
  ['governments-statistics', 'law', ['statistics']],
  ['insights-map', 'insights', ['map']],
  ['insights-supergroups', 'insights', ['supergroups', '#concept-browse [data-on-click^="selectConceptGroup"], [data-on-click^="selectConceptGroup"]']],
  ['living-law-map', 'living', ['law']],
  ['living-maps', 'living', ['osm']],
];
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  const out = [];
  for (const [name, tab, clicks] of SURFACES) {
    await pg.goto('http://127.0.0.1:8759/', { waitUntil: 'networkidle' });
    await pg.waitForTimeout(800);
    await pg.click(`.nav-item[data-tab="${tab}"]`);
    await pg.waitForTimeout(800);
    for (const c of clicks) {
      const btn = c.includes('[') ? pg.locator(c).first() : pg.locator(`#tab-${tab} [data-tab="${c}"]:visible, #subtab-strip [data-tab="${c}"]:visible`).first();
      try { await btn.click({ timeout: 3000 }); } catch (e) { out.push({ name, note: 'no button ' + c }); }
      await pg.waitForTimeout(2500);
    }
    const leg = pg.locator('[data-oomap-borders]:visible').first();
    try { await leg.waitFor({ timeout: 8000 }); } catch (e) { out.push({ name, legend: null }); continue; }
    const hid = await leg.evaluate((el) => { let h = el; while (h && !h.querySelector('svg#oo-choro')) h = h.parentElement; h.setAttribute('data-r259-host', '1'); return true; });
    const host = pg.locator('[data-r259-host]').first();
    const facts = await host.evaluate((h) => {
      const paths = [...h.querySelectorAll('path[data-oomap-disputed]')];
      return {
        legend: (h.querySelector('[data-oomap-borders]') || {}).textContent,
        offline_osm: ([...h.querySelectorAll('span[title]')].find(x => /Bounded preview/.test(x.getAttribute('title'))) || {}).textContent || null,
        legend_hover: (h.querySelector('[data-oomap-borders]') || {}).getAttribute('title'),
        disputed: paths.length,
        hatched: paths.filter(p => p.getAttribute('fill') === 'url(#oomap-contested)').length,
        attributed: paths.filter(p => p.hasAttribute('data-iso')).length,
        convention: [...new Set(paths.map(p => p.getAttribute('data-oomap-convention') || 'natural-earth'))],
      };
    });
    await host.scrollIntoViewIfNeeded();
    const file = `${TAG}-${name}.jpg`;
    await host.screenshot({ path: `${OUT}/${file}`, type: 'jpeg', quality: 60 });
    await host.evaluate((h) => h.removeAttribute('data-r259-host'));
    out.push({ name, file, bytes: fs.statSync(`${OUT}/${file}`).size, ...facts });
  }
  await b.close();
  console.log(JSON.stringify({ tag: TAG, surfaces: out, page_errors: errs }, null, 1));
})();
