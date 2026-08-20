// The Library qualification tile's composition note, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Extracted from src/static/app.js rather than re-typed: a copy would pass while the
// shipped function was broken. The extractor starts brace-matching at the BODY brace
// (past any default parameter), which is the shape that once truncated an ooChart slice
// to its signature and made every assertion over it pass for free.
//
// What is worth testing here is the NEGATIVE space. The note reports how much of the
// "awaiting a verdict" line has never been attempted, and the tempting implementation
// prints 0 when the second reading is missing -- which claims every waiting source HAS
// been attempted, the exact inverse of "not recorded yet". So each case asserts what the
// sentence says, not merely that a sentence came out.

const fs = require("fs");
const path = require("path");

// The engine is several ordered modules since 2026-08-20 (S-3); the helper reads the
// module list out of index.html, so this suite cannot come to read a subset of it.
const APP = require("./app_source.js").appJs();

function functionBody(src, name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error("no function named " + name);
  // Balance the PARENTHESES first, so a `{}` inside a default parameter cannot be
  // mistaken for the body brace.
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(open, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

// The two functions under test are pure; give them the one global they consult.
global.window = {};
const src = [
  "function _libQualNewest(payload) " + functionBody(APP, "_libQualNewest"),
  "function _libQualSplitText(awaiting, never) " + functionBody(APP, "_libQualSplitText"),
  "return {_libQualNewest, _libQualSplitText};",
].join("\n");
const {_libQualNewest, _libQualSplitText} = new Function(src)();

let passed = 0;
function check(name, cond, detail) {
  if (!cond) { console.error("FAIL: " + name + (detail ? " -- " + detail : "")); process.exit(1); }
  passed++;
}

// --- _libQualNewest --------------------------------------------------------------------

check("no payload reads as absent, not as zero",
  _libQualNewest(null) === null && _libQualNewest(undefined) === null);

check("an empty series reads as absent",
  _libQualNewest({series: []}) === null);

check("a zero reading is a real reading",
  _libQualNewest({series: [{t: "2026-08-04T00", n: 0}]}) === 0,
  "0 is a measurement; only a missing point is absent, and conflating them is the bug");

check("the newest point wins by TIMESTAMP, not array position",
  _libQualNewest({series: [
    {t: "2026-08-04T09", n: 7},
    {t: "2026-08-02T09", n: 99},
  ]}) === 7,
  "a reordered payload must not silently become 'the latest reading'");

// --- _libQualSplitText -----------------------------------------------------------------

const normal = _libQualSplitText(1253, 663);
check("the normal case names all three numbers",
  normal.includes("1253") && normal.includes("663") && normal.includes("590"),
  normal);

// Label:value, so no verb agrees with an interpolated count. A prose form read
// "1 have never been attempted" at a count of one, in English AND in French, because the
// template always pluralised -- and CLDR plural rules (three forms in Russian, six in
// Arabic) are not something this app has. Asserted on the SHAPE so a future rewrite back
// into prose reddens here rather than in a screenshot.
check("a count of one reads correctly, because nothing conjugates",
  !/\b1 have\b/.test(_libQualSplitText(3, 1)) && !/\bhave\b/.test(_libQualSplitText(3, 1)),
  _libQualSplitText(3, 1));

check("the remainder is awaiting minus never, not a re-print of either",
  _libQualSplitText(10, 4).includes("6"),
  _libQualSplitText(10, 4));

const missing = _libQualSplitText(1253, null);
check("an absent second reading is STATED as absent",
  /not yet recorded/i.test(missing), missing);
check("and does NOT print a zero or a full split",
  !missing.includes("1253") && !/\b0\b/.test(missing),
  "printing 0 would claim every waiting source had been attempted: " + missing);

check("an absent first reading is also stated",
  /not yet recorded/i.test(_libQualSplitText(null, 5)));

const skew = _libQualSplitText(4, 9);
check("a subset larger than its superset is reported as incomparable readings",
  /different snapshots/i.test(skew), skew);
check("and never as a negative remainder",
  !skew.includes("-5"),
  "structurally impossible, so it can only be two snapshots: " + skew);

check("equal readings mean nothing has been attempted yet, and say so with a zero",
  _libQualSplitText(12, 12).includes("0"),
  _libQualSplitText(12, 12));

console.log(passed + " passed");
