// ooIsoDate / ooIsoDateTime (0.5.1 item 46), run as REAL code extracted from app-core.js.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Under a right-to-left document an Arabic letter before an ISO date turns its digits into Arabic
// numbers (bidi rule W2) and the hyphen stops joining them, so 2025-12-14 draws as 14-12-2025.
// The helpers wrap the date in a first-strong isolate there and nowhere else:
//   * left-to-right (and an unset direction) output is BYTE-IDENTICAL to the raw slice;
//   * an empty or missing value stays "" (a lone pair of isolates would defeat `|| t("undated")`
//     and every `.filter(Boolean)` that follows);
//   * the date digits themselves are untouched, so a reader and a copy-paste get the same date.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
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

function load(dir) {
  const src = "var document = { documentElement: { dir: " + JSON.stringify(dir) + " } };\n"
    + extract("ooIsoDate") + "\n" + extract("ooIsoDateTime") + "\n"
    + "module.exports = { ooIsoDate, ooIsoDateTime };";
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
}
const FSI = "⁨", PDI = "⁩";

for (const dir of ["ltr", "", undefined]) {
  const R = load(dir);
  assert.strictEqual(R.ooIsoDate("2025-12-14T10:30:00+00:00"), "2025-12-14", "ltr: the raw slice, byte for byte");
  assert.strictEqual(R.ooIsoDate("2025-12-14T10:30:00", 7), "2025-12", "the length argument is honoured");
  assert.strictEqual(R.ooIsoDateTime("2025-12-14T10:30:00+00:00"), "2025-12-14 10:30");
}

const RTL = load("rtl");
assert.strictEqual(RTL.ooIsoDate("2025-12-14T10:30:00"), FSI + "2025-12-14" + PDI);
assert.strictEqual(RTL.ooIsoDate("2025-12-14", 7), FSI + "2025-12" + PDI);
assert.strictEqual(RTL.ooIsoDateTime("2025-12-14T10:30:00Z"), FSI + "2025-12-14 10:30" + PDI);
// What a reader or a copy sees is the same date once the isolates are ignored.
assert.strictEqual(RTL.ooIsoDate("2025-12-14T10:30:00").replace(/[⁨⁩]/g, ""), "2025-12-14");

for (const R of [load("ltr"), RTL]) {
  for (const empty of [null, undefined, ""]) {
    assert.strictEqual(R.ooIsoDate(empty), "", "an absent date stays empty, never a bare pair of isolates");
    assert.strictEqual(R.ooIsoDateTime(empty), "");
  }
  assert.ok(!/undefined|null|NaN/.test(R.ooIsoDate(undefined) + R.ooIsoDateTime(null)));
  assert.strictEqual(R.ooIsoDate(20251214).replace(/[⁨⁩]/g, ""), "20251214", "a non-string is coerced, not thrown on");
}

console.log("oo_iso_date: all checks passed");
