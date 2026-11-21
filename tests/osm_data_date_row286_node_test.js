/**
 * Row 286 (R775): the OpenStreetMap surfaces state the date of the last daily change file applied in order since the extract,
 * BESIDE the extract's date. With no file applied a surface is exactly what it was; with files applied and their date not read
 * it says so and nothing stands in for the date; no surface claims the data is current to that date, in any of the 12 languages.
 *
 * The functions are EXTRACTED FROM THE SHIPPED SOURCE by name (the sibling-test convention); translations come from the real
 * locale files. Run by tests/test_osm_data_date_row286.py.
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
const ANA = fs.readFileSync(path.join(STATIC, "app-analysis.js"), "utf-8");
const LANGS = ["en", "fr", "de", "es", "pt", "id", "ru", "ar", "hi", "bn", "ja", "zh"];
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
  const ooIsoDate = (s) => String(s).slice(0, 10);
  const _osmLaneByA3 = () => build.lane;
  const body = [
    extract("ooOsmUpdated", CORE), extract("ooOsmUpdatesClause", CORE), extract("ooOsmUpdatesHtml", CORE),
    extract("_osmPickLaneCell", MAP), extract("_osmVintageHead", MAP), extract("_osmCardDate", ANA),
    "return { _osmPickLaneCell, _osmVintageHead, _osmCardDate, ooOsmUpdatesClause };",
  ].join("\n");
  return new Function("window", "OOI18N", "esc", "ooIsoDate", "_osmLaneByA3", body)(window, window.OOI18N, esc, ooIsoDate, _osmLaneByA3);
}
build.lane = {};

const EXTRACT = "2026-10-01T21:00:00+00:00";
const NONE = { extract: EXTRACT, last_diff: null, diff_sequence: null, updates: "none" };
const DATED = { extract: EXTRACT, last_diff: "2026-11-19T21:00:00+00:00", diff_sequence: 4321, updates: "dated" };
const UNREAD = { extract: EXTRACT, last_diff: null, diff_sequence: 4321, updates: "date_not_read" };
const strip = (h) => h.replace(/<[^>]*>/g, "");

test("no file applied: every surface reads exactly as before, the extract's date alone", () => {
  const f = build("en");
  build.lane = { ZZZ: { status: "complete", vintage: EXTRACT, data_date: NONE } };
  assert(f._osmPickLaneCell({ alpha3: "ZZZ" }) === '<span class="pill ok">Read · data as of 2026-10-01</span>', f._osmPickLaneCell({ alpha3: "ZZZ" }));
  assert(f._osmVintageHead("Fixture Land", EXTRACT, NONE, true) === "Fixture Land, as of 2026-10-01");
  assert(f._osmCardDate(EXTRACT, NONE) === "OpenStreetMap data of 2026-10-01");
  // a payload from a build before row 286 (no data_date) reads the same way
  assert(f._osmCardDate(EXTRACT, undefined) === "OpenStreetMap data of 2026-10-01");
  assert(f._osmVintageHead("Fixture Land", null, NONE, true) === "Fixture Land, date not stated in the extract");
  assert(f._osmVintageHead("Fixture Land", null, NONE, false) === "Fixture Land");
});

test("files applied: the extract's date is named as the extract's, the last file's own date beside it, the method on hover", () => {
  const f = build("en");
  build.lane = { ZZZ: { status: "complete", vintage: EXTRACT, data_date: DATED } };
  const cell = f._osmPickLaneCell({ alpha3: "ZZZ" });
  assert(strip(cell) === "Read · extract of 2026-10-01 · daily change files applied through 2026-11-19", cell);
  assert(cell.includes('title="The date of the last daily change file applied in order since the extract'), cell);
  assert(strip(f._osmVintageHead("Fixture Land", EXTRACT, DATED, true)) === "Fixture Land: extract of 2026-10-01 · daily change files applied through 2026-11-19");
  assert(strip(f._osmCardDate(EXTRACT, DATED)) === "OpenStreetMap extract of 2026-10-01 · daily change files applied through 2026-11-19");
  assert(!cell.includes("data as of"), "the extract's date is no longer called the data's date: " + cell);
});

test("files applied, their date not read: the extract's date and a visible 'not read', no date stands in", () => {
  const f = build("en");
  build.lane = { ZZZ: { status: "complete", vintage: EXTRACT, data_date: UNREAD } };
  const cell = strip(f._osmPickLaneCell({ alpha3: "ZZZ" }));
  assert(cell === "Read · extract of 2026-10-01 · daily updates applied, data date not read", cell);
  const card = strip(f._osmCardDate(EXTRACT, UNREAD));
  assert(card === "OpenStreetMap extract of 2026-10-01 · daily updates applied, data date not read", card);
  assert(!/\d{4}-\d{2}-\d{2}.*\d{4}-\d{2}-\d{2}/.test(card), "a second date appeared: " + card);
  // a 'dated' state without its date never draws an empty date either
  assert(f.ooOsmUpdatesClause({ updates: "dated", last_diff: null }) === "daily updates applied, data date not read");
});

test("every language: both dates distinct, no placeholder left, no 'current as of' wording", () => {
  // The words R775 forbids for d2, per language: 'current / up to date as of' and their equivalents.
  const BANNED = {
    en: [/current as of/i, /up to date/i], fr: [/à jour au/i, /actuel/i], de: [/aktuell/i], es: [/actualizado al/i, /vigente/i],
    pt: [/atualizado em/i], id: [/terkini per/i], ru: [/актуальн\S* на/i], ar: [/محدَّث حتى/], hi: [/तक अद्यतन/],
    bn: [/পর্যন্ত হালনাগাদ/], ja: [/時点で最新/], zh: [/最新截至/, /截至.*最新/],
  };
  for (const lang of LANGS) {
    const f = build(lang);
    build.lane = { ZZZ: { status: "complete", vintage: EXTRACT, data_date: DATED } };
    const outs = [strip(f._osmPickLaneCell({ alpha3: "ZZZ" })), strip(f._osmVintageHead("ZZZ", EXTRACT, DATED, true)),
      strip(f._osmCardDate(EXTRACT, DATED))];
    build.lane = { ZZZ: { status: "complete", vintage: EXTRACT, data_date: UNREAD } };
    outs.push(strip(f._osmPickLaneCell({ alpha3: "ZZZ" })), strip(f._osmCardDate(EXTRACT, UNREAD)));
    for (const o of outs) {
      assert(!/\{\w+\}/.test(o), lang + ": a placeholder was left: " + o);
      assert(o.includes("2026-10-01"), lang + ": the extract's date is gone: " + o);
      for (const re of BANNED[lang]) assert(!re.test(o), lang + ": a 'current as of' wording: " + o);
    }
    for (const o of outs.slice(0, 3)) assert(o.includes("2026-11-19"), lang + ": the last file's date is missing: " + o);
    for (const o of outs.slice(3)) assert(!o.includes("2026-11-19"), lang + ": a date stood in for the unread one: " + o);
  }
});

console.log(`all assertions passed (${passed} tests)`);
