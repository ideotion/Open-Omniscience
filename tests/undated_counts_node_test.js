// The undated line and mark under an article chart (row 459, R853), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// EXTRACTED from the shipped app-core.js rather than re-typed. Driven from tests/test_undated_counts_row459.py.

"use strict";

const assert = require("assert");
const SRC = require("./app_source.js").appJs();

function extractFunction(src, name) {
  const at = src.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = src.indexOf("{", src.indexOf(")", at));
  let d = 0, j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return src.slice(at, j);
}

function extractEsc(src) {
  const at = src.indexOf("const esc = (s) =>");
  assert.ok(at !== -1, "esc not found -- was it renamed?");
  return src.slice(at, src.indexOf(";\n", at) + 1);
}

function load(i18n) {
  const window = {OOI18N: i18n};
  const body = [extractEsc(SRC)].concat(["ooUndatedCounts", "ooUndatedText", "ooUndatedMethod", "ooUndatedLine",
    "ooUndatedMark"].map((n) => extractFunction(SRC, n))).join("\n")
    + "\nreturn {counts: ooUndatedCounts, text: ooUndatedText, line: ooUndatedLine, mark: ooUndatedMark};";
  return new Function("window", "OOI18N", body)(window, i18n);
}

const H = load(undefined);
const A = (n, m, extra) => Object.assign({kind: "collection", n: n, feed_dated: m, feed_dated_reason: null}, extra || {});

// n = 0, or no block at all: nothing drawn.
assert.strictEqual(H.line(A(0, 0)), "");
assert.strictEqual(H.line(null), "");
assert.strictEqual(H.mark(A(0, 0)), "");

// Kind A: drawn at the collection date, with the feed split.
assert.strictEqual(H.text(A(3, 1)),
  "Articles without a date of their own: 3, drawn at the day the app collected them; with the feed's date: 1");
assert.strictEqual(H.text(A(3, null, {feed_dated_reason: "over_cap"})),
  "Articles without a date of their own: 3, drawn at the day the app collected them; feed dates not counted");

// Kind B: left out, of a chart or of a figure.
assert.ok(H.text({kind: "left_out", n: 2, feed_dated: 0}).includes("left out of this chart; with the feed's date: 0"));
assert.ok(H.text({kind: "left_out_figure", n: 2, feed_dated: 1}).includes("left out of this figure"));

// Not counted: said, never 0 and never silence.
assert.strictEqual(H.text({kind: "collection", n: null, feed_dated: null}), "Articles without a date of their own: not counted");
assert.ok(H.line({kind: "collection", n: null}).includes("not counted"));
assert.ok(H.mark({kind: "collection", n: null}).includes("dates not counted"));

// A narrowed range sums the per-bucket split; without one it is not counted for that range.
const b = A(3, 1, {by_bucket: [{date: "2026-W24", n: 2, feed_dated: 1}, {date: "2026-W36", n: 1, feed_dated: 0}]});
assert.ok(H.text(b, ["2026-W36"]).includes(": 1, drawn") && H.text(b, ["2026-W36"]).includes("feed's date: 0"));
assert.strictEqual(H.text(b, ["2026-W30"]), "");  // nothing undated in that range: no line
assert.strictEqual(H.text(A(3, 1), ["2026-W36"]), "Articles without a date of their own: not counted");
assert.ok(H.text(b, null).includes(": 3, drawn"));

// The line carries the method on hover; the mark opens the full line in one click.
const line = H.line(A(3, 1));
assert.ok(line.startsWith('<div class="hint undated-line" title="The app dates each article'), line);
const mark = H.mark(A(3, 1));
assert.ok(mark.startsWith('<details class="undated-mark"><summary'), mark);
assert.ok(mark.includes("◷ 3 by collection date") && mark.includes("with the feed&#39;s date: 1"), mark);

// Under a translation every string goes through the engine.
const seen = [];
const fr = load({t: (s) => { seen.push(s); return "[fr] " + s; }, tf: (s, v) => { seen.push(s); return "[fr] " + s.replace("{n}", v.n).replace("{m}", v.m); }});
assert.ok(fr.line(A(3, 1)).includes("[fr] Articles without a date of their own: 3"));
assert.ok(seen.some((s) => s.startsWith("The app dates each article")));

// Values are escaped, never read as markup.
assert.ok(!H.line({kind: "<b>", n: 1, feed_dated: 0}).includes("<b>"));

console.log("undated_counts_node_test: ok");
