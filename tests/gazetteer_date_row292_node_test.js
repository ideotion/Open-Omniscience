/**
 * Row 292 (R776): the place card's gazetteer date. A vintage built after daily OSM files were applied ("extract+last file", or
 * "+not-read") names both dates in R775's words; any other vintage reads exactly as before.
 *
 * The functions are EXTRACTED FROM THE SHIPPED SOURCE by name; translations come from the real locale files. Run by
 * tests/test_gazetteer_data_date_row292.py.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const CORE = fs.readFileSync(path.join(STATIC, "app-core.js"), "utf-8");
const ANA = fs.readFileSync(path.join(STATIC, "app-analysis.js"), "utf-8");
const INS = fs.readFileSync(path.join(STATIC, "app-insights.js"), "utf-8");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));
const LANGS = ["en", "fr", "de", "es", "pt", "id", "ru", "ar", "hi", "bn", "ja", "zh"];

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
  const ooIsoDate = (s) => String(s).slice(0, 10);
  const body = [
    extract("ooOsmUpdated", CORE), extract("ooOsmUpdatesClause", CORE), extract("ooOsmUpdatesHtml", CORE),
    extract("_gazetteerDate", ANA), "return _gazetteerDate;",
  ].join("\n");
  return new Function("window", "OOI18N", "esc", "ooIsoDate", body)(window, window.OOI18N, esc, ooIsoDate);
}

// The text a reader sees: tags removed until none is left (a test helper reading this app's own output, never a sanitizer).
function strip(h) {
  let prev;
  do { prev = h; h = h.replace(/<[^>]*>/g, ""); } while (h !== prev);
  return h;
}

test("a vintage without an applied file reads exactly as before", () => {
  const f = build("en");
  assert(f("2026-10-01") === "gazetteer of 2026-10-01", f("2026-10-01"));
  assert(f(null) === "gazetteer without a vintage");
});

test("files applied: both dates; not read: said, and no second date", () => {
  const f = build("en");
  const dated = f("2026-10-01+2026-11-19");
  assert(strip(dated) === "gazetteer of 2026-10-01 · daily change files applied through 2026-11-19", dated);
  assert(dated.includes('title="The date of the last daily change file applied in order since the extract'), dated);
  const unread = strip(f("2026-10-01+not-read"));
  assert(unread === "gazetteer of 2026-10-01 · daily updates applied, data date not read", unread);
});

test("every language: both dates, no placeholder left", () => {
  for (const lang of LANGS) {
    const h = strip(build(lang)("2026-10-01+2026-11-19"));
    assert(!/\{\w+\}/.test(h), lang + ": a placeholder was left: " + h);
    assert(h.includes("2026-10-01") && h.includes("2026-11-19"), lang + ": a date is missing: " + h);
  }
});

// The Insights entity line names the built gazetteer's vintage (Q805): the same two dates, never the raw "+not-read" value.
function buildLine(lang) {
  const loc = LOCALE(lang);
  const t = (s) => (loc[s] || s);
  const tf = (s, v) => t(s).replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
  const window = { OOI18N: { t, tf } };
  const ooIsoDate = (s) => String(s).slice(0, 10);
  const body = [extract("ooOsmUpdated", CORE), extract("ooOsmUpdatesClause", CORE), extract("_gazetteerArtifactLine", INS),
    "return (v) => _gazetteerArtifactLine(v, OOI18N.tf);"].join("\n");
  return new Function("window", "OOI18N", "ooIsoDate", body)(window, window.OOI18N, ooIsoDate);
}

test("the Insights gazetteer line: as before, or both dates, never the raw value", () => {
  const f = buildLine("en");
  assert(f("2026-10-01") === "Gazetteer: the built artifact, vintage 2026-10-01", f("2026-10-01"));
  assert(f(null) === "Gazetteer: the built artifact, vintage ?", f(null));
  assert(f("2026-10-01+2026-11-19") === "Gazetteer: the built artifact, vintage 2026-10-01 · daily change files applied through 2026-11-19", f("2026-10-01+2026-11-19"));
  assert(f("2026-10-01+not-read") === "Gazetteer: the built artifact, vintage 2026-10-01 · daily updates applied, data date not read", f("2026-10-01+not-read"));
  for (const lang of LANGS) {
    const h = buildLine(lang)("2026-10-01+not-read");
    assert(!h.includes("not-read") && !h.includes("+") && !/\{\w+\}/.test(h), lang + ": " + h);
  }
});

console.log(`all assertions passed (${passed} tests)`);
