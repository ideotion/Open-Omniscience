/**
 * Node test for _libLangNotes -- what the per-language growth tile SAYS about
 * the data it is not drawing.
 *
 * WHY BEHAVIOURAL, NOT A SUBSTRING GUARD. The first version of these assertions
 * checked that `d.other` and `d.unassigned` appear in the tile's source. Both
 * survived a mutation that neutered the sentences while leaving the identifiers
 * in a variable binding -- a guard that cannot fail, protecting exactly the
 * silent-truncation the sentences exist to prevent.
 *
 * The tile draws the busiest twelve languages. Everything it declines to draw
 * has to be stated, or a twelve-panel grid reads as "this is the corpus":
 *   - the ranked-out tail (how many languages, how many articles);
 *   - articles with NO asserted language, which are excluded from the panels and
 *     are also the size of the equilibrium lever's own blind spot;
 *   - a series that starts late because the CORPUS is younger than the window.
 *
 * Each comes with its negative-space twin, because an over-eager disclosure
 * invents missing data just as dishonestly as an omission hides it.
 *
 * Extracted from the real app.js, brace-matched from the BODY brace.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const APP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"), "utf-8");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(name) {
  const decl = "function " + name + "(";
  const at = APP.indexOf(decl);
  assert(at !== -1, "could not find " + name);
  let p = 0, i = -1;
  for (let j = at + decl.length - 1; j < APP.length; j++) {
    if (APP[j] === "(") p++;
    else if (APP[j] === ")") { p--; if (p === 0) { i = APP.indexOf("{", j); break; } }
  }
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces in " + name);
}

const src = extract("_libLangNotes");
assert(src.length > 300, "the extracted body is suspiciously small -- a vacuous test");
const sandbox = {};
new Function(src + "\nthis._libLangNotes = _libLangNotes;").call(sandbox);
const { _libLangNotes } = sandbox;

// The real i18n contract: t() falls back to the English key, tf() interpolates
// AFTER translation (the frame translates, the data does not).
const t = (s) => s;
const tf = (tpl, v) => String(tpl).replace(/\{(\w+)\}/g, (m, k) => (k in v ? String(v[k]) : m));
const notes = (d) => _libLangNotes(d, t, tf).join(" ");

const FULL = {
  bucket: "day",
  other: {languages: 0, articles: 0},
  unassigned: {articles: 0, with_deduced_language: 0},
  clamped_to_corpus_start: false,
  corpus_began_at: "2027-01-01T00:00:00",
};
const with_ = (over) => Object.assign({}, FULL, over);

// --------------------------------------------------------------------------- //
//  The bin is named, so a point can be read
// --------------------------------------------------------------------------- //
test("the bucket is stated, and it is the one the payload reports", () => {
  assert(/per day/.test(notes(with_({bucket: "day"}))), "a daily bin must say so");
  assert(/per hour/.test(notes(with_({bucket: "hour"}))), "an hourly bin must say so");
});

// --------------------------------------------------------------------------- //
//  The ranked-out tail
// --------------------------------------------------------------------------- //
test("languages ranked out of the panels are counted in the open", () => {
  const s = notes(with_({other: {languages: 7, articles: 412}}));
  assert(/7 more languages/.test(s), `the tail must be disclosed: ${s}`);
  assert(/412 articles/.test(s), `with its article count: ${s}`);
});

test("...and nothing is claimed missing when nothing was ranked out (the twin)", () => {
  assert(!/more languages/.test(notes(FULL)), "an over-eager disclosure invents missing data");
});

// --------------------------------------------------------------------------- //
//  The lever's blind spot
// --------------------------------------------------------------------------- //
test("articles with no asserted language are stated, with the deduced share", () => {
  const s = notes(with_({unassigned: {articles: 900, with_deduced_language: 340}}));
  assert(/900 articles have no asserted language/.test(s), `the blind spot must be sized: ${s}`);
  assert(/340 carry a deduced one/.test(s), `and its deduced share named: ${s}`);
  assert(/equilibrium lever cannot see them/.test(s),
    "the number is only meaningful once it says whose blind spot it is");
});

test("...and a fully-tagged corpus is not told it has a blind spot (the twin)", () => {
  assert(!/no asserted language/.test(notes(FULL)), "nothing to disclose, nothing said");
});

// --------------------------------------------------------------------------- //
//  A late start is explained -- only when it is real
// --------------------------------------------------------------------------- //
test("a series clamped by the corpus's own start says so", () => {
  const s = notes(with_({clamped_to_corpus_start: true}));
  assert(/corpus itself begins at 2027-01-01/.test(s), `the clamp must be explained: ${s}`);
});

test("...and an ordinary window is not given an explanation it does not need", () => {
  assert(!/corpus itself begins/.test(notes(FULL)),
    "explaining a late start that is not happening is its own fabrication");
});

test("the clamp is not claimed when the timestamp is missing", () => {
  const s = notes(with_({clamped_to_corpus_start: true, corpus_began_at: null}));
  assert(!/corpus itself begins/.test(s), "never render a sentence around a null date");
});

// --------------------------------------------------------------------------- //
//  Shape
// --------------------------------------------------------------------------- //
test("a payload missing its disclosure blocks degrades instead of throwing", () => {
  // A degraded/partial response must not take the whole Library tab down.
  const s = notes({bucket: "day"});
  assert(/per day/.test(s), "the bucket note survives a minimal payload");
});

test("no template placeholder ever reaches the user", () => {
  const s = notes(with_({
    other: {languages: 2, articles: 5},
    unassigned: {articles: 3, with_deduced_language: 1},
    clamped_to_corpus_start: true,
  }));
  assert(!/\{[a-z_]+\}/.test(s), `an uninterpolated placeholder leaked: ${s}`);
});

console.log(`\n${passed} passed`);
