// ooLtrIsolate (0.5.1, R277): run as REAL code extracted from app-core.js, under ltr, unset and rtl.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const CORE = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-core.js"), "utf8");

function extract(name) {
  const at = CORE.indexOf("function " + name + "(");
  assert(at !== -1, "could not find " + name);
  const open = CORE.indexOf("{", CORE.indexOf(")", at));
  let depth = 0;
  for (let j = open; j < CORE.length; j++) {
    if (CORE[j] === "{") depth++;
    else if (CORE[j] === "}" && --depth === 0) return CORE.slice(at, j + 1);
  }
  throw new Error("unterminated " + name);
}
function load(dir) {
  const doc = dir === undefined ? "{documentElement: {}}" : `{documentElement: {dir: ${JSON.stringify(dir)}}}`;
  // eslint-disable-next-line no-new-func
  return new Function("const document = " + doc + ";\n" + extract("ooLtrIsolate") + "\nreturn ooLtrIsolate;")();
}
function loadPct(dir) {
  const doc = dir === undefined ? "{documentElement: {}}" : `{documentElement: {dir: ${JSON.stringify(dir)}}}`;
  // eslint-disable-next-line no-new-func
  return new Function("const document = " + doc + ";\n" + extract("ooLtrPct") + "\nreturn ooLtrPct;")();
}
const FSI = "⁨", PDI = "⁩";
const LTR = load("ltr"), UNSET = load(undefined), RTL = load("rtl");

for (const f of [LTR, UNSET]) {
  assert.strictEqual(f("+3"), "+3", "ltr/unset: the input, byte for byte");
  assert.strictEqual(f("0–100"), "0–100");
}
assert.strictEqual(RTL("+3"), FSI + "+3" + PDI);
assert.strictEqual(RTL("0.5–2"), FSI + "0.5–2" + PDI);
assert.strictEqual(RTL("+3").replace(/[⁨⁩]/g, ""), "+3", "only the isolate pair is added");
for (const empty of ["", null, undefined]) {
  for (const f of [LTR, RTL]) assert.strictEqual(f(empty), "", "an absent value stays empty, never a bare pair");
}
assert.strictEqual(RTL(0), FSI + "0" + PDI, "a number is coerced, not thrown on");
// ooLtrPct (2026-11-07, item 46 S4 b): the "digits then percent" runs of a composed sentence, rtl only.
const PCT_LTR = loadPct("ltr"), PCT_UNSET = loadPct(undefined), PCT_RTL = loadPct("rtl");
for (const f of [PCT_LTR, PCT_UNSET]) assert.strictEqual(f("مستخدم 12.5%"), "مستخدم 12.5%", "ltr/unset: byte for byte");
assert.strictEqual(PCT_RTL("مستخدم 12.5%"), "مستخدم " + FSI + "12.5%" + PDI);
assert.strictEqual(PCT_RTL("12 %"), FSI + "12 %" + PDI, "a spaced sign stays with its digits");
assert.strictEqual(PCT_RTL("{share} ٪ (3)"), "{share} ٪ (3)", "no digits next to the sign: nothing to pin");
assert.strictEqual(PCT_RTL("٣٫٥٪ من 10"), FSI + "٣٫٥٪" + PDI + " من 10", "Arabic-Indic digits and sign");
assert.strictEqual(PCT_RTL("5% و 7%"), FSI + "5%" + PDI + " و " + FSI + "7%" + PDI, "every run, not the first");
assert.strictEqual(PCT_RTL("3 of 10"), "3 of 10", "a number without a sign is untouched");
for (const empty of ["", null, undefined]) assert.strictEqual(PCT_RTL(empty), "");
assert.strictEqual(PCT_RTL("12.5%").replace(/[⁨⁩]/g, ""), "12.5%", "only the isolate pair is added");
console.log("ooLtrIsolate: all checks passed");
