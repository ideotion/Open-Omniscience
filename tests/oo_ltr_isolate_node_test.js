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
console.log("ooLtrIsolate: all checks passed");
