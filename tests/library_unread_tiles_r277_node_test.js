/**
 * Row 277: the Library overview's downloaded-layer tiles never show an unread count as 0.
 *
 * _paintLibraryOverview is EXTRACTED FROM THE SHIPPED SOURCE and run on three payloads: a real 0,
 * an unread list (available:false with its reason), and a protected Ollama store. Translations come
 * from the REAL locale files, so the visible "not read" and the hover reason are checked in French too.
 *
 * Run by tests/test_library_unread_tiles_r277.py (and standalone).
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const LIB = fs.readFileSync(path.join(STATIC, "app-library.js"), "utf-8");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }

function extract(name, src) {
  const head = "function " + name + "(";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  const i = src.indexOf("{", src.indexOf(")", at));
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

const PAINT = extract("_paintLibraryOverview", LIB);
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function paint(lang, downloaded) {
  const cat = LOCALE(lang);
  const OOI18N = { t: (k) => (cat[k] != null ? cat[k] : k) };
  const host = { innerHTML: "" };
  // eslint-disable-next-line no-new-func
  const run = new Function("window", "OOI18N", "esc", "fmtNum", "_fmtBytes", "_kwPerArticleTile", "host", "d",
    PAINT + "\n_paintLibraryOverview(host, d, {});");
  run({ OOI18N }, OOI18N, esc, (v) => String(v), (v) => v + " B", () => "", host, { downloaded, derived: {} });
  return host.innerHTML;
}

function tileFor(html, label) {
  const tiles = html.split('<div class="stat"').slice(1);
  const hit = tiles.find((x) => x.includes(`<div class="k">${esc(label)}</div>`));
  assert(hit, "no tile labelled " + label);
  return hit;
}

const EN = LOCALE("en");
const FR = LOCALE("fr");
const DUMPS = "The list of finished downloads could not be read, so nothing is counted.";
const PROT = "Ollama's models are in a protected location this app cannot read (on Linux, the service install), so they are not counted.";

// A real zero stays a zero, with no "not read".
let html = paint("en", { wikipedia: { dumps: { count: 0, total_bytes: 0 } }, maps: { osm_regions: { count: 2, total_bytes: 5 } },
  models: { count: 0, total_bytes: 0 } });
let t = tileFor(html, "Wikipedia dumps");
assert(t.includes('<div class="n">0 · —</div>') && !t.includes("stat-unread"), "a real 0 was not shown as 0: " + t);
t = tileFor(html, "OpenStreetMap regions");
assert(t.includes('<div class="n">2 · 5 B</div>'), "a real count was lost: " + t);
console.log("ok  - a real zero and a real count are shown as measured");

// An unread list is "—", a VISIBLE "not read", and the reason in the hover -- never 0.
html = paint("en", { wikipedia: { dumps: { count: null, total_bytes: null, available: false, reason: DUMPS } },
  models: { count: null, total_bytes: null, available: false, reason: PROT } });
for (const [label, reason] of [["Wikipedia dumps", DUMPS], ["Local AI models", PROT]]) {
  t = tileFor(html, label);
  assert(t.includes('<div class="n">—</div>'), label + ": not a dash: " + t);
  assert(!/<div class="n">0/.test(t), label + ": shown as 0");
  assert(t.includes(`<div class="k stat-unread">not read</div>`), label + ": no visible 'not read'");
  assert(t.includes(`title="${esc(reason)}"`), label + ": the reason is not in the hover");
}
console.log("ok  - an unread count is a dash with a visible 'not read' and its reason in the hover");

// The same in French, from the real catalogue.
html = paint("fr", { models: { count: null, total_bytes: null, available: false, reason: PROT } });
t = tileFor(html, FR["Local AI models"]);
assert(t.includes(`<div class="k stat-unread">${esc(FR["not read"])}</div>`), "the visible label is not translated");
assert(t.includes(`title="${esc(FR[PROT])}"`), "the hover reason is not translated");
assert(FR["not read"] !== EN["not read"] && FR[PROT] !== EN[PROT], "the French catalogue repeats the English");
console.log("ok  - the label and the reason are translated");

// Every reason the server can send is a key in all twelve catalogues.
for (const code of ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"]) {
  const c = LOCALE(code);
  for (const k of ["not read", "This count could not be read.", DUMPS, PROT,
    "The local AI model store could not be read, so nothing is counted."]) {
    assert(typeof c[k] === "string" && c[k].length > 0, code + " lacks " + k);
  }
}
console.log("ok  - every string is in all 12 catalogues");
