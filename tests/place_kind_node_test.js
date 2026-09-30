// A Place's kind is shown in the interface language (R71 b, item 14), run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `ooPlaceKind` is EXTRACTED from app-core.js rather than re-typed, and the i18n engine is
// driven by the REAL locale files, so an assertion about Japanese is an assertion about what
// a Japanese reader sees.

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " was not found in the engine");
  let i = APP.indexOf("(", at), depth = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = APP.indexOf("{", i);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

const LOCALES = path.join(__dirname, "..", "src", "static", "locales");
const TABLE = {};
const table = (l) => (TABLE[l] = TABLE[l] || JSON.parse(fs.readFileSync(path.join(LOCALES, l + ".json"), "utf-8")));
let LANG = "en";
const OOI18N = {
  t: (s) => { const v = table(LANG)[s]; return v == null ? s : v; },
  tf: (s, vars) => String(OOI18N.t(s)).replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m),
};
const sandbox = new Function("window", "OOI18N", extract("ooPlaceKind") + "; return ooPlaceKind;");
const ooPlaceKind = sandbox({ OOI18N }, OOI18N);

const OSM_PLACE_VALUES = [
  "country", "state", "region", "province", "district", "county", "municipality", "city", "borough",
  "suburb", "quarter", "neighbourhood", "city_block", "plot", "town", "village", "hamlet",
  "isolated_dwelling", "farm", "allotments", "continent", "archipelago", "island", "islet",
  "square", "locality", "sea", "ocean", "boundary=administrative",
];
const LANGS = ["en", "ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"];

// English is OSM's own word, spaces for underscores; the hover still names the OSM word.
LANG = "en";
assert.strictEqual(ooPlaceKind("city").text, "city");
assert.strictEqual(ooPlaceKind("isolated_dwelling").text, "isolated dwelling");
assert.ok(ooPlaceKind("city").title.includes("city"), "the hover names OSM's word");

// Every OSM place value is known in every language, and a translation is not the English word
// left in place for a language that has its own (checked on words that differ from English in every language).
for (const lang of LANGS) {
  LANG = lang;
  for (const v of OSM_PLACE_VALUES) {
    const r = ooPlaceKind(v);
    assert.ok(r.text, `${lang}: ${v} has no label`);
    assert.ok(r.title.includes(v), `${lang}: the hover for ${v} does not name OSM's word`);
    // The label must come from the locale file itself: the stub t() falls back to the English
    // key, so a MISSING translation would pass every assertion above.
    LANG = "en";
    const key = ooPlaceKind(v).text;
    LANG = lang;
    assert.ok(table(lang)[key] != null, `${lang}: "${key}" is not keyed in the locale file`);
  }
  assert.ok(table(lang)["OpenStreetMap's word: {kind}"] != null, `${lang}: the hover template is not keyed`);
  if (lang !== "en") {
    assert.notStrictEqual(ooPlaceKind("hamlet").text, "hamlet", `${lang}: hamlet was left in English`);
    assert.notStrictEqual(ooPlaceKind("island").text, "island", `${lang}: island was left in English`);
  }
}
LANG = "fr";
assert.strictEqual(ooPlaceKind("hamlet").text, "hameau");
LANG = "ja";
assert.strictEqual(ooPlaceKind("village").text, "村");
LANG = "ar";
assert.ok(ooPlaceKind("city").title.includes("⁨city⁩"), "the OSM word is isolated inside right-to-left text");

// A kind this table does not know is shown as OSM wrote it, with no invented label or hover.
LANG = "fr";
assert.deepStrictEqual(ooPlaceKind("amenity=hospital"), { text: "amenity=hospital", title: "" });
assert.deepStrictEqual(ooPlaceKind("toString"), { text: "toString", title: "" }, "no prototype lookups");
// An absent kind stays absent.
assert.deepStrictEqual(ooPlaceKind(null), { text: "", title: "" });
assert.deepStrictEqual(ooPlaceKind("  "), { text: "", title: "" });

console.log("place kind: ok");
