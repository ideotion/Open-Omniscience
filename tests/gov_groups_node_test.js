/**
 * Behavioural node test for the Governments GROUPS renderer (field feedback
 * 2026-08-07, rulings 43/44/45/47).
 *
 * The engine that computes a group figure already refuses honestly — a summed
 * percentage, a partial roster, a weighted mean with a missing weight. Every one
 * of those refusals reaches the reader through ONE function, `_govGroupHtml`, and
 * a renderer is where an honest payload quietly stops being honest: the vLLM
 * probe's "not asked" became "failed" at exactly this boundary, and the bulletin's
 * caveat was dropped at exactly this boundary. So the refusals, the coverage, the
 * spread and the membership VINTAGE are asserted against rendered output rather
 * than against the payload that feeds it.
 *
 * The function is EXTRACTED FROM THE REAL app.js by name — a re-typed copy would
 * pass while the shipped renderer was broken (the sibling-test convention).
 * Run by tests/test_gov_groups_render.py (and standalone: `node tests/gov_groups_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const APP = fs.readFileSync(
  path.join(__dirname, "..", "src", "static", "app.js"), "utf-8");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(name) {
  const head = "function " + name + "(";
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head + " in app.js");
  // Start at the BODY brace, not the first brace: a default parameter can carry a
  // `{}` and matching from there truncates the body to nothing.
  let p = 0, i = -1;
  for (let j = APP.indexOf("(", at); j < APP.length; j++) {
    if (APP[j] === "(") p++;
    else if (APP[j] === ")") { p--; if (p === 0) { i = APP.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

const box = {};
new Function(
  "esc", "fmtNum", "window",
  extract("_govGroupHtml") + "\n" + extract("_govFmt") + "\n" +
  extract("_govCompact") + "\n" + extract("_govTf") + "\n" + extract("_govNames") + "\n" +
  "this._govGroupHtml = _govGroupHtml;"
).call(box,
  (s) => String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
  (v, d) => (d == null ? String(v) : Number(v).toFixed(d)),
  {}   // no OOI18N: every t()/tf() falls back to the English literal
);
const render = box._govGroupHtml;

// --------------------------------------------------------------------------- //
// fixtures shaped like the REAL /group-aggregate payload
// --------------------------------------------------------------------------- //

function roster(over) {
  return Object.assign({
    group: "european-union", label: "European Union", kind: "bloc",
    known: true, populated: true,
    members: ["fr", "de", "it"], suspended: [], undated_members: [],
    period: "2019", resolved_year: 2019, dates_apply: true, as_of: "2026-08",
    notes: null, caveat: "Membership resolved as of 2019. Registry curated 2026-08.",
  }, over || {});
}

function agg(over) {
  return Object.assign({
    indicator: "SP.DYN.LE00.IN", label: "Life expectancy at birth (years)",
    unit: "years", extensive: false, denominator: "population",
    coverage: {members: 3, reported: 3, missing: [], complete: true},
    spread: {n: 3, min: 79.1, max: 83.4, min_area: "de", max_area: "it"},
    strategies: {},
    default_strategy: "population_weighted",
    caveat: "Strategies are shown side by side and never blended.",
    period: "2019",
  }, over || {});
}

// --------------------------------------------------------------------------- //

test("a refused strategy renders its REASON, not a blank or a zero", () => {
  const html = render({
    group: roster(),
    aggregate: agg({strategies: {
      sum: {label: "Total", refused: "This indicator is intensive — a rate, share, index or per-capita value — so its members' values do not add up to anything."},
      mean: {label: "Mean of members", value: 81.2, basis: "exact", method: "Each member counts once."},
    }}),
  }, false);
  assert(/do not add up to anything/.test(html),
    "the engine's own refusal sentence must reach the reader verbatim");
  assert(/gov-strat-refused/.test(html), "a refusal is marked as one");
  // The defect this guards: a refusal rendered as an empty value cell reads as 0.
  assert(!/gov-strat-val[^]*?Total/.test(html.replace(/\n/g, "")),
    "a refused strategy must not be given a value cell");
});

test("a summed percentage can never appear as a figure", () => {
  const html = render({
    group: roster(),
    aggregate: agg({strategies: {
      sum: {label: "Total", refused: "intensive — refused"},
      mean: {label: "Mean of members", value: 81.2, basis: "exact", method: "m"},
    }}),
  }, false);
  const totalBlock = html.slice(html.indexOf("Total"));
  assert(!/gov-strat-val/.test(totalBlock.slice(0, 200)),
    "Total must carry a reason where its value would be");
});

test("the membership VINTAGE is stated on every group figure", () => {
  const html = render({group: roster(), aggregate: agg({strategies: {}})}, false);
  assert(/membership as of/.test(html), "the roster's year must be stated");
  assert(/2019/.test(html), "the RESOLVED year, not today");
  assert(/2026-08/.test(html), "the registry vintage travels too");
});

test("a suspended member is named rather than silently kept or dropped", () => {
  const html = render({
    group: roster({suspended: ["ml"], members: ["fr", "de", "ml"]}),
    aggregate: agg({strategies: {}}),
  }, false);
  assert(/Suspended \(1\)/.test(html) && /ML/.test(html),
    "suspension is a third state and must be visible");
});

test("a member carried without a sourced accession date is disclosed", () => {
  const html = render({
    group: roster({undated_members: ["fr"]}),
    aggregate: agg({strategies: {}}),
  }, false);
  assert(/without a sourced accession date/.test(html),
    "an undated membership is asserted by the registry, not evidenced — say so");
});

test("an unpopulated group renders its REASON and no figure at all", () => {
  const html = render({
    group: {group: "brics", label: "BRICS", kind: "bloc", known: true, populated: false,
            members: [], as_of: "2026-08",
            reason: "Membership is not held: accession dates are sourced facts and none were available offline."},
    aggregate: null,
    reason: "Membership is not held: accession dates are sourced facts and none were available offline.",
  }, false);
  assert(/Membership is not held/.test(html), "the gap must be named");
  assert(!/gov-strat-val/.test(html), "no figure may be rendered for an unpopulated group");
});

test("the SPREAD rides beside the central figure", () => {
  const html = render({
    group: roster(),
    aggregate: agg({strategies: {mean: {label: "Mean of members", value: 81.2, basis: "exact", method: "m"}}}),
  }, false);
  assert(/Range across reporting members/.test(html),
    "ruling 47's corollary: a headline hiding the range is practically misleading");
  assert(/DE/.test(html) && /IT/.test(html), "the areas at each end are named");
});

test("incomplete coverage offers an explicit override and names who is missing", () => {
  const html = render({
    group: roster(),
    aggregate: agg({coverage: {members: 3, reported: 2, missing: ["it"], complete: false},
                    strategies: {}}),
  }, false);
  assert(/Compute over the members that did report/.test(html),
    "the override is an explicit action, never a default");
  assert(/IT/.test(html), "the missing member is named before the user overrides");
  assert(/2 of 3/.test(html), "coverage is stated as a fraction of the real roster");
});

test("an overridden partial figure carries PARTIAL and the missing set", () => {
  const html = render({
    group: roster(),
    aggregate: agg({coverage: {members: 3, reported: 2, missing: ["it"], complete: false},
                    strategies: {mean: {label: "Mean of members", value: 81.2,
                                        basis: "approximate", method: "m"}}}),
  }, true);
  assert(/PARTIAL/.test(html), "an overridden figure must announce itself");
  assert(/IT/.test(html), "the missing members travel WITH the result");
  assert(!/Compute over the members that did report/.test(html),
    "the override button is spent once used");
});

test("the default strategy is marked as a starting view, never as a winner", () => {
  const html = render({
    group: roster(),
    aggregate: agg({default_strategy: "mean",
                    strategies: {mean: {label: "Mean of members", value: 81.2,
                                        basis: "exact", method: "m"}}}),
  }, false);
  assert(/opens here/.test(html), "the default is a VIEW");
  // The negative space: no ranking vocabulary may reach the reader. Asserted against
  // title-STRIPPED output, because the hover that EXPLAINS the absence of a ranking
  // necessarily contains the words "winner" and "ranked" — the recorded trap where a
  // "must be gone" guard fires on the sentence recording the removal. Rewording the
  // explanation would be the wrong repair: it is what a future session reads before
  // deciding a ranking would be fine.
  const visible = html.replace(/title="[^"]*"/g, "");
  assert(!/\bbest\b|\brecommended\b|\bwinner\b|\bscore\b|\branked\b|#1\b/i.test(visible),
    "the strategies are never ranked — a ranking word here would be a composite by stealth");
  // ...and the guard must be able to fail: prove the needle is real.
  assert(/\bwinner\b/i.test(html),
    "the explanatory hover should still say what the default is NOT");
});

test("exact and approximate are distinguished on the face of the figure", () => {
  const html = render({
    group: roster(),
    aggregate: agg({strategies: {
      population_weighted: {label: "Population-weighted mean", value: 81.9, basis: "exact",
                            method: "Sum of (value x population) divided by the summed population."},
      gdp_weighted: {label: "GDP-weighted mean", value: 82.4, basis: "approximate",
                     method: "APPROXIMATE: this indicator is measured per population, not per gdp."},
    }}),
  }, false);
  assert(/exact/.test(html) && /approximate/.test(html),
    "'weighted mean' alone does not distinguish an identity from an estimate");
});

test("a group with no strategies at all renders no fabricated figure", () => {
  const html = render({group: roster(), aggregate: agg({strategies: {}})}, false);
  assert(!/gov-strat-val/.test(html), "nothing computable means nothing shown");
  assert(/membership as of/.test(html), "but the roster is still stated");
});

console.log("\n" + passed + " passed");
