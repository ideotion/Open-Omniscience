/**
 * The feed tally says a Stop in words (R353 = B, OPEN_QUEUE item 20): `stopped_unwalked` is
 * the pipeline's count of a feed's entries a Stop left unrequested (R327). It is not an
 * outcome (R320/R337), so it never prints as a raw "stopped_unwalked: 11" beside the real
 * counts; it is said after them as a translated sentence, with the long form on the hover.
 *
 * `tally` and `tallyHover` are EXTRACTED FROM THE SHIPPED SOURCE by name (a re-typed copy
 * would pass while the real code was still broken); translations come from the REAL locale
 * files. Run by tests/test_stopped_unwalked_tally.py (and standalone:
 * `node tests/stopped_unwalked_tally_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const SOURCES = fs.readFileSync(path.join(STATIC, "app-sources.js"), "utf-8");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

// Same balanced-brace extraction every node suite here uses (duplicated per convention).
function extract(name, src) {
  const head = "function " + name + "(";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = src.indexOf("(", at); j < src.length; j++) {
    if (src[j] === "(") p++;
    else if (src[j] === ")") { p--; if (p === 0) { i = src.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

// A window carrying the real OOI18N.t / tf semantics over one locale file (missing key -> the key).
function load(code) {
  const dict = code ? LOCALE(code) : {};
  const t = (s) => (dict[s] != null ? dict[s] : s);
  const tf = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? v[k] : m);
  const window = {OOI18N: {t, tf}};
  const OOI18N = window.OOI18N;
  const fns = new Function("window", "OOI18N",
    extract("tally", SOURCES) + "\n" + extract("tallyHover", SOURCES) + "\nreturn {tally, tallyHover};");
  return fns(window, OOI18N);
}

test("a Stop is said in words after the counts, never as a raw key", () => {
  const {tally} = load("en");
  const line = tally({new: 4, duplicate: 2, stopped_unwalked: 11});
  assert(!line.includes("stopped_unwalked"), "raw key printed: " + line);
  assert(line === "new: 4, already stored: 2 · 11 entries not asked for (you stopped collection)", "line: " + line);
});

test("a Stop with nothing walked reads as the sentence alone", () => {
  const {tally} = load("en");
  assert(tally({new: 0, stopped_unwalked: 7}) === "7 entries not asked for (you stopped collection)",
    "line: " + tally({new: 0, stopped_unwalked: 7}));
});

test("no Stop: the tally is unchanged, and skipped_offline still stays out", () => {
  const {tally, tallyHover} = load("en");
  assert(tally({new: 3, skipped_offline: 0}) === "new: 3", tally({new: 3}));
  assert(tally({new: 0, stopped_unwalked: 0}) === "nothing new", "zero tally");
  assert(tally({skipped_offline: 1}) === "nothing new", "skipped_offline printed");
  assert(tallyHover({new: 3}) === "", "a hover without a Stop");
});

test("the hover carries the long form, translated", () => {
  const en = load("en").tallyHover({stopped_unwalked: 2});
  assert(/never requested/.test(en) && /not failures/.test(en), "en hover: " + en);
  const fr = load("fr").tallyHover({stopped_unwalked: 2});
  assert(fr && fr !== en, "fr hover not translated: " + fr);
});

test("all 12 locales translate the line and keep the count", () => {
  for (const code of ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"]) {
    const {tally} = load(code);
    const line = tally({new: 4, stopped_unwalked: 11});
    assert(line.includes("11") && line.includes("new: 4"), code + ": " + line);
    assert(!line.includes("stopped_unwalked") && !/\{\w+\}/.test(line), code + ": " + line);
    if (code !== "en") assert(!line.includes("entries not asked for"), code + " untranslated: " + line);
  }
});

test("the outcome keys are words in every locale; an unknown key is shown as sent (R665)", () => {
  const en = load("en").tally({stored: 3, duplicate: 12, "ff:dns": 1});
  assert(en === "new articles stored: 3, already stored: 12, ff:dns: 1", "en: " + en);
  for (const code of ["ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"]) {
    const {tally} = load(code);
    const line = tally({stored: 3, duplicate: 12, fetch_failed: 2, "ff:dns": 1, brand_new_key: 5});
    assert(!/\bstored\b|\bduplicate\b|fetch_failed/.test(line), code + " left a raw key: " + line);
    assert(line.includes("ff:dns: 1") && line.includes("brand_new_key: 5"), code + " an unknown key must be shown as sent: " + line);
    assert(tally({}) !== "nothing new", code + ": 'nothing new' untranslated");
  }
  assert(load("en").tally({toString: 2}) === "toString: 2", "an inherited property name is not a known key");
});

console.log(`\n${passed} passed`);
