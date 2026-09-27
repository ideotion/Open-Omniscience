// The boot locale sends the SAME event a switch sends (2026-09-27 re-walk M-2/M-9), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// After a reload in fr, a keyword surface whose data beat the locale file painted English
// frames ("in russe", "Trending now:") inside [data-i18n-dyn] nodes the walker must skip,
// and nothing repainted them: `init()` resolved `ready` but dispatched no `oo:langchange`,
// and only a switch did. Driven here against the shipped i18n.js with the locale fetch
// held back, the way the re-walk reproduced it (fr.json delayed 2.5 s).
//
// What must hold: a non-English boot fires exactly ONE `oo:langchange`, AFTER the map is
// loaded (a listener that repaints must get French from t(), not English), marked as the
// boot's; an English boot fires none (there is no map to wait for).

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "i18n.js"), "utf-8");

async function boot(lang, localeMap, delayMs) {
  const target = new EventTarget();
  const document = {
    readyState: "complete",
    documentElement: {},
    body: null,
    getElementById: () => null,
    addEventListener: (type, fn) => target.addEventListener(type, fn),
    dispatchEvent: (e) => target.dispatchEvent(e),
  };
  const store = { "oo.lang": lang };
  const window = {};
  const events = [];
  // Registered BEFORE the script, as app-boot.js's listener is in the page: every app
  // module is evaluated before the locale fetch can resolve.
  document.addEventListener("oo:langchange", (e) => {
    events.push({ detail: e.detail, t: window.OOI18N.t("in {language}") });
  });
  const ctx = {
    window, document, CustomEvent, setTimeout, console,
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
    fetch: (url) => new Promise((res) => setTimeout(() => res({
      ok: true,
      json: async () => { assert.ok(url.endsWith("/" + lang + ".json"), url); return localeMap; },
    }), delayMs || 0)),
  };
  vm.runInNewContext(SRC, ctx);
  await window.OOI18N.ready;
  await new Promise((r) => setTimeout(r, 20));
  return events;
}

(async () => {
  const fr = { _meta: { dir: "ltr" }, "in {language}": "en {language}" };

  const ev = await boot("fr", fr, 60);
  assert.strictEqual(ev.length, 1, "a French boot must fire oo:langchange exactly once, fired " + ev.length);
  assert.strictEqual(ev[0].detail.lang, "fr");
  assert.strictEqual(ev[0].detail.boot, true, "the event must say it is the boot's, not a switch");
  assert.strictEqual(ev[0].t, "en {language}",
    "the event fired before the locale map was loaded: a repaint would still paint English");

  const en = await boot("en", {}, 0);
  assert.strictEqual(en.length, 0, "an English boot has no map to wait for and must fire nothing");

  // A locale file that fails to load still ends the boot: the map is empty, and the one
  // event lets the surfaces settle on the English they already show.
  const broken = await boot("de", {}, 10);
  assert.strictEqual(broken.length, 1);

  console.log("all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
