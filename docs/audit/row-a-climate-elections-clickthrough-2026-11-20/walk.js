// 0.6 row A click-through (S06-04 §4, Q1128 = a): the Agenda's three election tiers and a passed
// projected date, the climate figures with their baseline lines and freshness diagnostics, a
// population-weighted figure with its weighting line, and the statistics directory's
// verified-of-total line -- in en, ar (RTL), hi and es.
//
// Driven through the real sidebar, subtabs, view switcher, selects and buttons, and the real
// top-bar language switcher. The server boots in airplane mode and nothing here goes online:
// every response is loopback, every request off 127.0.0.1 is recorded as a failure.
//
//   OO_WALK_BASE=http://127.0.0.1:8761 OO_WALK_OUT=<dir> node walk.js
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.OO_WALK_BASE || "http://127.0.0.1:8761";
const OUT = process.env.OO_WALK_OUT || "/tmp/claude-0/rowa-walk";
const LANGS = (process.env.OO_WALK_LANGS || "en,ar,hi,es").split(",");
const JUNK = /\b(undefined|NaN|null)\b|\[object Object\]/g;
fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function closeWizard(pg) {
  await pg.evaluate(() => {
    for (const id of ["guide-wizard", "first-run", "net-coach"]) {
      const d = document.getElementById(id);
      if (d && d.open && d.close) d.close();
    }
  });
  await sleep(150);
}

async function switchLang(pg, loc, errors) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    await closeWizard(pg);
    await pg.keyboard.press("Escape");
    await pg.mouse.move(2, 2);
    await sleep(500);
    try {
      await pg.click("#lang-switch", { timeout: 6000 });
      await pg.waitForSelector(`#lang-menu [data-lang='${loc}']`, { state: "visible", timeout: 6000 });
      await pg.click(`#lang-menu [data-lang='${loc}']`, { timeout: 6000 });
      await pg.waitForFunction((l) => document.documentElement.lang === l, loc, { timeout: 6000 });
      await sleep(600);
      return;
    } catch (e) {
      if (attempt === 3) errors.push(`switcher ${loc}: ${String(e).slice(0, 160)}`);
    }
  }
}

async function openTab(pg, tab) {
  await closeWizard(pg);
  // Settings is opened from its top-bar button (the sidebar lists the data tabs only).
  if (tab === "settings") await pg.click("button[data-on-click=\"showTab('settings')\"]", { timeout: 8000 });
  else await pg.click(`.nav-item[data-tab='${tab}']`, { timeout: 8000 });
  await pg.waitForFunction((t) => {
    const e = document.getElementById("tab-" + t);
    return e && e.offsetParent !== null;
  }, tab, { timeout: 10000 });
  await sleep(900);
}

const text = (pg, sel) => pg.evaluate((s) => { const e = document.querySelector(s); return e ? e.innerText : null; }, sel);
const junkIn = (s) => [...new Set(((s || "").match(JUNK) || []))].sort();

async function shot(pg, name, sel) {
  const file = path.join(OUT, name + ".png");
  if (sel) {
    const el = await pg.$(sel);
    if (el) { await el.screenshot({ path: file }); return name + ".png"; }
  }
  await pg.screenshot({ path: file, fullPage: false });
  return name + ".png";
}

(async () => {
  const browser = await chromium.launch();
  const report = { base: BASE, when: new Date().toISOString(), langs: {} };
  for (const loc of LANGS) {
    const errors = [], bad = [], offsite = [];
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    const pg = await ctx.newPage();
    pg.on("pageerror", (e) => errors.push(`pageerror: ${e}`));
    pg.on("console", (m) => { if (m.type() === "error") errors.push(`console.error: ${m.text().slice(0, 200)}`); });
    pg.on("response", (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
    pg.on("request", (r) => { const u = r.url(); if (!/^(https?:\/\/127\.0\.0\.1[:/]|data:|blob:|about:)/.test(u)) offsite.push(u); });
    const R = { errors, bad, offsite, shots: [] };
    report.langs[loc] = R;

    await pg.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await sleep(2500);
    await switchLang(pg, loc, errors);
    R.dir = await pg.evaluate(() => document.documentElement.dir || getComputedStyle(document.documentElement).direction);

    // ---- Agenda: the list view, elections only, then the coverage report.
    await openTab(pg, "agenda");
    await pg.click("#agenda-views button[data-tab='list']");
    await sleep(1200);
    R.agenda_list = await pg.evaluate(() => {
      const rows = [...document.querySelectorAll("#agenda-list *")].filter((e) => /Walk|DE|ES|IT|JP|PT|France|United States/.test(e.innerText || "") && e.children.length < 6);
      return (document.getElementById("agenda-list") || {}).innerText || "";
    });
    R.agenda_tier_pills = await pg.evaluate(() => {
      const out = {};
      for (const c of ["tier-window", "warn", "err", "ok", "tier-scheduled", "leadpassed", "approx"]) out[c] = document.querySelectorAll(`#agenda-list .${c}`).length;
      return out;
    });
    // Find the two walk rows and the scheduled one; scroll each into view for the picture.
    for (const [label, needle] of [["agenda-list-passed", "Walk Greece"], ["agenda-list-projected", "Walk Portugal"], ["agenda-list-scheduled", "United States"]]) {
      const ok = await pg.evaluate((n) => {
        const el = [...document.querySelectorAll("#agenda-list *")].find((e) => e.children.length === 0 && (e.textContent || "").includes(n));
        if (!el) return false;
        el.scrollIntoView({ block: "center" });
        return true;
      }, needle);
      R[label.replace(/-/g, "_") + "_found"] = ok;
      await sleep(400);
      R.shots.push(await shot(pg, `${label}-${loc}`));
    }
    R.agenda_junk = junkIn(R.agenda_list);
    await pg.click("#agenda-views button[data-tab='coverage']");
    await pg.waitForFunction(() => /\S/.test((document.getElementById("agenda-coverage") || {}).innerText || ""), null, { timeout: 15000 }).catch((e) => errors.push("coverage: " + String(e).slice(0, 120)));
    await sleep(1200);
    R.coverage = await text(pg, "#agenda-coverage");
    R.coverage_junk = junkIn(R.coverage);
    await pg.evaluate(() => document.getElementById("agenda-coverage").scrollIntoView({ block: "start" }));
    R.shots.push(await shot(pg, `agenda-coverage-${loc}`));

    // ---- Climate: each dataset's facts and diagnostics; the place against 1991-2020.
    await openTab(pg, "climate");
    R.climate = {};
    for (const ds of ["gistemp", "nsidc", "oni", "usgs", "owid", "ghcnd"]) {
      await pg.click(`#climate-subtabs button[data-tab='${ds}']`);
      await pg.waitForFunction(() => document.querySelector("#climate-body .climate-facts"), null, { timeout: 15000 }).catch((e) => errors.push(`climate ${ds}: ${String(e).slice(0, 120)}`));
      await sleep(1500);
      const body = await text(pg, "#tab-climate");
      const diag = await pg.evaluate(() => [...document.querySelectorAll("#climate-body .climate-diag li")].map((l) => l.innerText));
      const caveat = await text(pg, "#climate-caveat");
      R.climate[ds] = { diagnostics: diag, caveat, junk: junkIn(body), svg: await pg.evaluate(() => document.querySelectorAll("#climate-body svg, #climate-body canvas").length) };
      if (["gistemp", "nsidc", "usgs", "ghcnd"].includes(ds)) R.shots.push(await shot(pg, `climate-${ds}-${loc}`));
    }
    await pg.click("#climate-subtabs button[data-tab='place']");
    await pg.waitForSelector("#climate-place-lat", { timeout: 10000 });
    await pg.fill("#climate-place-lat", "48.86");
    await pg.fill("#climate-place-lon", "2.35");
    await pg.fill("#climate-place-start", "2026-06-01");
    await pg.fill("#climate-place-end", "2026-08-31");
    await pg.click("button[data-climate-place='show']");
    await pg.waitForSelector("#climate-place-out table", { timeout: 15000 }).catch((e) => errors.push("place: " + String(e).slice(0, 120)));
    await sleep(800);
    R.place = { out: await text(pg, "#climate-place-out"), status: await text(pg, "#climate-status") };
    R.place.junk = junkIn(R.place.out);
    R.shots.push(await shot(pg, `climate-place-${loc}`));

    // ---- Governments -> Groups -> computed from members: Europe, GDP per capita, population-weighted.
    await openTab(pg, "law");
    await pg.click("#gov-subtabs button[data-tab='groups']");
    await sleep(800);
    await pg.click("#gov-lens button[data-lens='computed']");
    await pg.waitForFunction(() => (document.getElementById("gov-grp-pick") || {}).options && document.getElementById("gov-grp-pick").options.length > 0 && document.getElementById("gov-grp-ind").options.length > 0, null, { timeout: 15000 }).catch((e) => errors.push("groups: " + String(e).slice(0, 120)));
    await pg.selectOption("#gov-grp-pick", "europe").catch((e) => errors.push("pick europe: " + String(e).slice(0, 120)));
    await pg.selectOption("#gov-grp-ind", "NY.GDP.PCAP.CD").catch((e) => errors.push("pick ind: " + String(e).slice(0, 120)));
    await sleep(1500);
    const allow = await pg.$("#gov-grp-body button[data-on-click='renderGovGroup(true)']");
    R.group_refused_first = !!allow;
    if (allow) { await allow.click(); await sleep(1500); }
    R.group = { body: await text(pg, "#gov-grp-body"),
      weighting: await pg.evaluate(() => [...document.querySelectorAll("#gov-grp-body .gov-strat-weighting")].map((e) => e.innerText)) };
    R.group.junk = junkIn(R.group.body);
    await pg.evaluate(() => { const w = document.querySelector("#gov-grp-body .gov-strat-weighting") || document.getElementById("gov-grp-body"); w.scrollIntoView({ block: "center" }); });
    await sleep(300);
    R.shots.push(await shot(pg, `group-weighted-${loc}`));

    // ---- Settings -> Advanced: the statistics directory's verified-of-total line.
    await openTab(pg, "settings");
    await pg.click("#set-subtabs button[data-tab='advanced']");
    await sleep(600);
    // The directory is a collapsed section of Advanced; it loads when it is opened, by its own summary.
    await pg.click("details.adv-sec[data-adv='stats'] > summary");
    await pg.waitForFunction(() => /\S/.test((document.getElementById("stat-coverage") || {}).textContent || ""), null, { timeout: 15000 }).catch((e) => errors.push("directory: " + String(e).slice(0, 120)));
    await sleep(600);
    R.directory = { line: await text(pg, "#stat-coverage"), hover: await pg.evaluate(() => (document.getElementById("stat-coverage") || {}).title || "") };
    await pg.evaluate(() => document.getElementById("stat-coverage").scrollIntoView({ block: "center" }));
    await sleep(300);
    R.shots.push(await shot(pg, `directory-${loc}`));

    await ctx.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 1));
  console.log(JSON.stringify(Object.fromEntries(Object.entries(report.langs).map(([k, v]) => [k, { errors: v.errors.length, bad: v.bad.length, offsite: v.offsite.length }]))));
})();
