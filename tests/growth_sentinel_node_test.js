// The growth sentinel's three states, and the bar that must not be drawn, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `queries._growth_of` substitutes the recent COUNT into `growth` when the prior rate
// scaled to the window comes to less than one mention. Printed as "↑N×" that count becomes
// a fabricated magnitude: a field bulletin rendered 5,701 mentions against a prior of 4 as
// "×5701.0", on 19 of its 20 rows. The bulletin renderer was fixed then; the six chrome
// sites in app.js were not, and this suite is what pins their fix.
//
// EXTRACTED from src/static/app.js rather than re-typed -- a copy would pass while the
// shipped function was broken. The extractor balances the PARENTHESES before looking for
// the body brace, so a `{}` in a default parameter cannot truncate the slice to its
// signature (the shape that once made every assertion over an ooChart slice pass for free).
//
// WHY BEHAVIOURAL AND NOT A SOURCE GREP: a source assertion here would be satisfied by the
// COMMENTS, which necessarily quote both the honest sentences and the "↑N×" form they
// replace -- the recorded trap where a guard is satisfied by the explanation of the rule it
// guards. What matters is which branch is REACHED for a given row, so rows are fed in.
//
// The NEGATIVE-SPACE TWIN is mandatory in both directions: a fix that returned the honest
// sentence unconditionally would satisfy every sentinel case while destroying the ratio
// rendering on the surfaces that were always correct, so a measured ratio is asserted to
// still render byte-for-byte as it does today.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

// The engine is several ordered modules since 2026-08-20 (S-3); the helper reads the
// module list out of index.html, so this suite cannot come to read a subset of it.
const APP = require("./app_source.js").appJs();

function functionSource(src, name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error("no function named " + name);
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

// --- the harness ------------------------------------------------------------------ //
// Only what the extracted functions actually reach: the i18n pair (absent here, so the
// guarded fallbacks run -- which is itself worth exercising, since i18n.js may not have
// loaded in the browser either), fmtNum, and esc.

global.window = {};                       // no OOI18N: the un-i18n'd path
function fmtNum(v) { return String(v); }  // identity, so assertions read as the raw number
function esc(s) { return String(s); }
const excludeKeyword = () => {};

const SRC = [
  functionSource(APP, "growthIsRatio"),
  functionSource(APP, "growthFallback"),
  functionSource(APP, "termBarsHtml"),
].join("\n");

// eslint-disable-next-line no-eval
eval(SRC);

let passed = 0;
function check(what, fn) { fn(); passed++; if (process.env.VERBOSE) console.log("  ok " + what); }

// --- growthIsRatio: three states, and `null` is not `false` ----------------------- //

check("the flag is believed when present", () => {
  assert.strictEqual(growthIsRatio({growth_is_ratio: true, expected: 0.1}), true);
  assert.strictEqual(growthIsRatio({growth_is_ratio: false, expected: 99}), false);
});

check("expected is the fallback for payloads predating the flag", () => {
  // The flag is COMPUTED from expected, so reading it is honest rather than a guess.
  assert.strictEqual(growthIsRatio({expected: 5.0}), true);
  assert.strictEqual(growthIsRatio({expected: 0.93}), false);
  assert.strictEqual(growthIsRatio({expected: 1}), true, "the boundary is >= 1");
});

check("a row that cannot say reports null, never false", () => {
  // This is the distinction the whole fix rests on: `null` means unmeasurable, and
  // collapsing it to `false` would state a sentinel that was never established.
  assert.strictEqual(growthIsRatio({recent: 9}), null);
  assert.strictEqual(growthIsRatio({expected: null}), null);
  assert.strictEqual(growthIsRatio({expected: "not a number"}), null);
  assert.strictEqual(growthIsRatio(null), null);
});

// --- growthFallback: null for a real ratio, a sentence otherwise ------------------ //

check("a measured ratio yields null, so the caller keeps its own rendering", () => {
  assert.strictEqual(growthFallback({growth: 3.6, recent: 18, prior: 5, expected: 5.0}), null);
  assert.strictEqual(growthFallback({growth: 3.6, recent: 18, prior: 5, growth_is_ratio: true}), null);
});

check("the field case: 5701 mentions against a prior of 4 is never a multiple", () => {
  const row = {growth: 5701.0, recent: 5701, prior: 4, expected: 0.93, growth_is_ratio: false};
  const out = growthFallback(row);
  assert.ok(out, "the sentinel must produce a sentence");
  assert.ok(!out.includes("×"), "a count must never be dressed as a multiple: " + out);
  assert.ok(!out.includes("5701×"), out);
  assert.ok(out.includes("5701"), "the real count is still stated: " + out);
  assert.ok(out.includes("4"), "and the prior it stands against: " + out);
  assert.ok(/too thin a baseline/.test(out), out);
});

check("no prior at all reads as new, not as a thin baseline", () => {
  const out = growthFallback({growth: 12, recent: 12, prior: 0, growth_is_ratio: false});
  assert.ok(/nothing prior to compare/.test(out), out);
  assert.ok(!out.includes("×"), out);
});

check("an unmeasurable row states the count and stops", () => {
  // Neither flag nor expected: it does not claim a multiple, and it does not invent a
  // reason it has no evidence for either.
  const out = growthFallback({growth: 7, recent: 7, prior: 2});
  assert.ok(!out.includes("×"), out);
  assert.ok(!/too thin|nothing prior/.test(out), "no reason may be asserted: " + out);
  assert.ok(out.includes("7"), out);
});

check("a missing growth never prints undefined", () => {
  const out = growthFallback({recent: 3, prior: 1, expected: 0.2});
  assert.ok(!/undefined|NaN|×/.test(out), out);
  assert.ok(out.includes("3"), out);
});

check("the window option names the baseline it was measured over", () => {
  const row = {growth: 40, recent: 40, prior: 6, expected: 0.4,
               growth_is_ratio: false, window_days: 7, baseline_days: 30};
  assert.ok(/30/.test(growthFallback(row, {window: true})), "the baseline width is stated");
  // Without it the sentence still stands -- it just says "prior period".
  assert.ok(growthFallback(row).length > 0);
});

// --- termBarsHtml: a row off the scale gets no bar, not a short one --------------- //

const RATIO = {term: "alpha", growth: 3.6, recent: 18, prior: 5, expected: 5.0, growth_is_ratio: true};
const SENTINEL = {term: "beta", growth: 5701, recent: 5701, prior: 4, expected: 0.93, growth_is_ratio: false};

check("the sentinel draws NO fill while the ratio still does", () => {
  const html = termBarsHtml([RATIO, SENTINEL],
    (t) => (growthIsRatio(t) === true ? t.growth : null),
    (t) => growthFallback(t) || `↑${t.growth}× (${t.recent} recent · ${t.prior} prior)`);
  const rows = html.split('<div class="tb-row">').slice(1);
  assert.strictEqual(rows.length, 2, "both rows keep their place");
  assert.ok(rows[0].includes("tb-fill"), "a measured rate is still drawn");
  assert.ok(!rows[1].includes("tb-fill"),
    "a count has no length on a rate scale -- not even the 2% stub, which would read as a very small rate");
});

check("the scale is taken over the rows that share it", () => {
  // The defect: with the 5701 count on the scale, the ×3.6 ratio rounds to a 0% bar and
  // the chart shows one full bar and nothing else. Its own width is the assertion.
  const html = termBarsHtml([RATIO, SENTINEL],
    (t) => (growthIsRatio(t) === true ? t.growth : null),
    (t) => String(t.growth));
  const width = /width:(\d+)%/.exec(html);
  assert.ok(width, "the ratio row must still be drawn");
  assert.strictEqual(width[1], "100",
    "the only row on the rate scale is the whole scale; if the count were included this would be 0");
});

check("a bar chart with no scalable row at all still renders every row", () => {
  const html = termBarsHtml([SENTINEL], () => null, (t) => growthFallback(t));
  assert.ok(html.includes("beta"), "the term is still listed");
  assert.ok(!html.includes("tb-fill"), html);
  assert.ok(!/NaN|Infinity/.test(html), "an empty scale must not leak a non-number: " + html);
});

check("the unrelated mentions chart is untouched by any of this", () => {
  // trd-top passes plain counts and shares the helper; its bars must be byte-identical.
  const html = termBarsHtml(
    [{term: "a", mentions: 10}, {term: "b", mentions: 5}],
    (t) => t.mentions, (t) => `${t.mentions} mentions`);
  const widths = [...html.matchAll(/width:(\d+)%/g)].map((m) => m[1]);
  assert.deepStrictEqual(widths, ["100", "50"]);
});

console.log(`growth sentinel: ${passed} checks passed`);
