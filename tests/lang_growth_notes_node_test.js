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

// Tests are QUEUED and awaited, not called and counted. The first version of this
// runner did `fn(); passed += 1;`, which reports an async test as "ok" the instant
// it returns a pending promise -- so the two tile tests below printed a pass while
// their assertions had not run, and the ReferenceError they were written to catch
// surfaced afterwards as an unhandled rejection, well past the summary line. A
// runner that cannot fail is the same defect as a guard that cannot fail.
const QUEUE = [];
function test(name, fn) { QUEUE.push([name, fn]); }
async function run() {
  for (const [name, fn] of QUEUE) {
    await fn();
    passed += 1;
    console.log("ok  - " + name);
  }
  console.log(`\n${passed} passed`);
}

function extract(name) {
  const decl = "function " + name + "(";
  let at = APP.indexOf(decl);
  assert(at !== -1, "could not find " + name);
  // Keep an `async` prefix: slicing from `function` alone hands back a body that
  // still contains `await`, which is a SyntaxError rather than a wrong answer --
  // loud, but only if you notice it is the harness and not the code.
  const before = APP.slice(Math.max(0, at - 8), at);
  if (/async\s*$/.test(before)) at -= before.length - before.search(/async\s*$/);
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

// --------------------------------------------------------------------------- //
//  The tile renders at all
// --------------------------------------------------------------------------- //
// node --check proves the file PARSES; it cannot see a ReferenceError. This
// codebase has already shipped one in a Library tile (a bare `t` in the
// source-tag click handler), so the template gets driven once with a realistic
// payload, with every collaborator stubbed and none of them silently absent:
// `undefined is not a function` is the same class of defect.
const I18N = {
  t: (s) => s,
  tf: (tpl, v) => String(tpl).replace(/\{(\w+)\}/g, (m, k) => String(v[k])),
};
// The window constants come from app.js, not from a stub: the chips a stub
// produced would be the test's own opinion of the windows, not the app's.
const CONSTS = ["LIB_WINDOWS", "LIB_DEFAULT_DAYS", "LIB_LANG_TOP_N"].map(name => {
  const m = APP.match(new RegExp("\\n\\s*const " + name + " = [^\\n]+"));
  assert(m, "could not read " + name + " from app.js");
  return m[0].trim();
});
const tileSrc = [
  ...CONSTS,
  "let _libTileDays = {};",
  extract("_libWindowChips"),
  src,
  extract("_libLanguageTile"),
  "this._libLanguageTile = _libLanguageTile;",
].join("\n");

test("the tile renders a panel grid, its notes and its window chips", async () => {
  const calls = [];
  const box = {};
  new Function(
    "esc", "api", "smallMultiplesSvg", "ooLangName", "window", "OOI18N",
    tileSrc
  ).call(box,
    (s) => String(s),
    (u) => { calls.push(u); return Promise.resolve({
      bucket: "day",
      series: [{language: "en", total: 9, points: [{t: "2027-01-01", n: 9}]},
               {language: "fr", total: 4, points: [{t: "2027-01-01", n: 4}]}],
      other: {languages: 3, articles: 11},
      unassigned: {articles: 6, with_deduced_language: 2},
      clamped_to_corpus_start: true, corpus_began_at: "2027-01-01T00:00:00",
    }); },
    (panels) => `<svg data-panels="${panels.length}"></svg>`,
    (code) => ({en: "English", fr: "French"})[code] || code,
    {OOI18N: I18N}, I18N
  );

  return box._libLanguageTile(30).then(html => {
    assert(/\/api\/library\/languages\?days=30&top_n=12/.test(calls[0] || ""),
      `the tile must request the feed with its window: ${calls[0]}`);
    assert(/id="lib-tile-__lang"/.test(html), "the tile needs the id its window chips re-render");
    assert(/data-panels="2"/.test(html), "both languages must reach the renderer");
    assert(/3 more languages/.test(html) && /6 articles have no asserted language/.test(html),
      `the disclosures must reach the DOM, not just the notes array: ${html}`);
    assert(/_libSetWindow\('__lang'/.test(html), "the window chips must carry this tile's own key");
  });
});

test("...and a failing fetch degrades to a visible error, not a blank tab", () => {
  const box = {};
  new Function("esc", "api", "smallMultiplesSvg", "ooLangName", "window", "OOI18N", tileSrc).call(box,
    (s) => String(s),
    () => Promise.reject(new Error("boom")),
    () => "", (c) => c,
    {OOI18N: I18N}, I18N);
  return box._libLanguageTile(30).then(html => {
    assert(/note err/.test(html) && /boom/.test(html),
      `a failed fetch must say so where the tile was: ${html}`);
    assert(/id="lib-tile-__lang"/.test(html), "even the error keeps the id, so chips still work");
  });
});

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
