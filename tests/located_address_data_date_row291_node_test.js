/**
 * Row 291 (R775): a located infobox address's hover names the extract's date and, once a daily change file was applied, the last
 * one's own date (or that it was not read) in the words every OSM surface uses. With no file applied the hover is unchanged.
 *
 * The functions are EXTRACTED FROM THE SHIPPED SOURCE by name; translations come from the real locale files. Run by
 * tests/test_located_addresses_after_update_row291.py.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const CORE = fs.readFileSync(path.join(STATIC, "app-core.js"), "utf-8");
const MAP = fs.readFileSync(path.join(STATIC, "app-map.js"), "utf-8");
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
  const project = () => ({ x: 10, y: 20 });
  const body = [
    extract("ooOsmUpdated", CORE), extract("ooOsmUpdatesClause", CORE), extract("_ooWikiAddrMarker", MAP),
    "return _ooWikiAddrMarker;",
  ].join("\n");
  return new Function("window", "OOI18N", "esc", "ooIsoDate", "project", body)(window, window.OOI18N, esc, ooIsoDate, project);
}

const EXTRACT = "2026-10-01T21:00:00+00:00";
const PT = { edition: "en", title: "Fixture Hall", field: "address", address: "1 Fixture Road", lat: 1, lon: 2,
  osm_object: "way/13", osm_vintage: EXTRACT };
const titleOf = (html) => { const m = / title="([^"]*)"/.exec(html); assert(m, "no title: " + html); return m[1]; };

test("no file applied, or an answer from before row 291: the hover is exactly what it was", () => {
  const f = build("en");
  const want = "1 Fixture Road, from the address field of Fixture Hall (en). Located at OpenStreetMap way/13, extract of 2026-10-01.";
  assert(titleOf(f(PT)) === want, titleOf(f(PT)));
  assert(titleOf(f({ ...PT, osm_data_date: { extract: EXTRACT, last_diff: null, diff_sequence: null, updates: "none" } })) === want);
});

test("files applied: the last file's own date follows the extract's; not read: said, no date", () => {
  const f = build("en");
  const dated = titleOf(f({ ...PT, osm_data_date: { extract: EXTRACT, last_diff: "2026-11-19T21:00:00+00:00", diff_sequence: 7, updates: "dated" } }));
  assert(dated.endsWith("extract of 2026-10-01. · daily change files applied through 2026-11-19"), dated);
  const unread = titleOf(f({ ...PT, osm_data_date: { extract: EXTRACT, last_diff: null, diff_sequence: 7, updates: "date_not_read" } }));
  assert(unread.endsWith("extract of 2026-10-01. · daily updates applied, data date not read"), unread);
});

test("every language: both dates present, no placeholder left", () => {
  for (const lang of LANGS) {
    const f = build(lang);
    const h = titleOf(f({ ...PT, osm_data_date: { extract: EXTRACT, last_diff: "2026-11-19T21:00:00+00:00", diff_sequence: 7, updates: "dated" } }));
    assert(!/\{\w+\}/.test(h), lang + ": a placeholder was left: " + h);
    assert(h.includes("2026-10-01") && h.includes("2026-11-19"), lang + ": a date is missing: " + h);
  }
});

console.log(`all assertions passed (${passed} tests)`);
