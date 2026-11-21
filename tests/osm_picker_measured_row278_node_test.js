/**
 * Row 278: the OSM picker's "Daily changes" cell. A measured figure leads, with its count and date, and the estimate moves to
 * the hover; without one the estimate stays and the reason is in the hover; a missing figure is never drawn as 0.
 *
 * The functions are EXTRACTED FROM THE SHIPPED SOURCE by name (the sibling-test convention); translations come from the real
 * locale files. Run by tests/test_osm_picker_measured_row278.py.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const MAP = fs.readFileSync(path.join(STATIC, "app-map.js"), "utf-8");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

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
  assert(false, "unbalanced " + name);
}

function build(lang) {
  const loc = LOCALE(lang);
  const t = (s) => (loc[s] || s);
  const tf = (s, v) => t(s).replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
  const window = { OOI18N: { t, tf } };
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  const humanBytes = (n) => n + " B";
  const ooIsoDate = (s) => String(s).slice(0, 10);
  const _osmPicker = { diff: { method: "M.", caveat: "C." } };
  const body = extract("_osmDiffEstimate", MAP) + "\n" + extract("_osmDiffCell", MAP) + "\nreturn _osmDiffCell;";
  return new Function("window", "OOI18N", "esc", "humanBytes", "ooIsoDate", "_osmPicker", body)(window, window.OOI18N, esc, humanBytes, ooIsoDate, _osmPicker);
}

test("a measured figure leads with its count and date; the estimate is in the hover", () => {
  const cell = build("en")({
    diff_daily_estimate_bytes: 5000,
    diff_measured: { median_bytes: 2048, files_measured: 3, files_applied: 4, through: "2026-11-21", method: "Measured on this machine: x." },
    diff_measured_reason: null,
  });
  assert(cell.startsWith("2048 B a file "), cell);
  assert(cell.includes("measured here: 3 files, through 2026-11-21"), cell);
  assert(cell.includes("Before the first daily update: about 5000 B a day (estimate)."), cell);
  assert(!cell.includes("~5000"), "the estimate no longer leads: " + cell);
});

test("without a measurement the estimate stays and the reason is in the hover, never a 0", () => {
  const reason = "not measured yet: no daily change file has been applied for this country";
  const cell = build("en")({ diff_daily_estimate_bytes: 5000, diff_measured: null, diff_measured_reason: reason });
  assert(cell.startsWith("~5000 B a day"), cell);
  assert(cell.includes(`title="${reason}"`) && cell.includes(">not measured yet<"), cell);
  assert(!/\b0 B\b/.test(cell), cell);
});

test("an older payload without the field draws exactly as before", () => {
  const fn = build("en");
  assert(fn({ diff_daily_estimate_bytes: 5000 }).startsWith("~5000 B a day"), "estimate");
  assert(fn({ diff_daily_estimate_bytes: null }).includes("—"), "dash");
});

test("a file without a stated time says measured here without a date; French is translated", () => {
  const cell = build("fr")({
    diff_daily_estimate_bytes: null,
    diff_measured: { median_bytes: 10, files_measured: 2, files_applied: 2, through: null, method: "m" },
  });
  assert(cell.includes("mesuré ici : 2 fichiers") && !cell.includes("jusqu"), cell);
  assert(cell.includes("par fichier"), cell);
});

console.log(`all assertions passed (${passed})`);
