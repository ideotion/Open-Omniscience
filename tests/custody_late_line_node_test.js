// The custody "recorded late" line, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The endpoint answers a late count that could not be read as null plus a reason and the
// time it asked, and a line that drew "?" for that hid the one fact an operator needs:
// that the count is UNKNOWN, why, and how old the attempt is. A source-level assertion
// cannot tell "drew the reason" from "mentions the reason", so this runs the function,
// EXTRACTED from the shipped module (a re-typed copy would pass while the real one broke).

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

const el = { textContent: "x" };
const FMT = { fn: null };
const src =
  "var window = {};\n" +
  "var fmtDateTime = (iso) => FMT.fn ? FMT.fn(iso) : '';\n" +
  "const $ = (id) => id === 'cust-late' ? EL : null;\n" +
  extract("_qualTf") + "\n" +
  extract("_renderCustodyLate") + "\n" +
  "module.exports = { _renderCustodyLate };";
const { _renderCustodyLate } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", "EL", "FMT", src)(m, m.exports, el, FMT);
  return m.exports;
})();
const draw = (L) => { el.textContent = "x"; _renderCustodyLate(L); return el.textContent; };

// --- nothing queued, nothing recorded: the line is empty -------------------- //
assert.strictEqual(draw({ pending: 0, recorded_late: 0 }), "");
assert.strictEqual(draw(null), "");

// --- a count that was NOT REQUESTED is not an unreadable one ---------------- //
{
  const out = draw({ pending: 3, recorded_late: null, recorded_late_reason: "not requested" });
  assert.ok(out.includes("3 ingest entries"), out);
  assert.ok(!/could not be read/.test(out), "an unrequested count was called unreadable: " + out);
}

// --- THE REFUSAL: an unreadable count says so, with the reason, never "?" --- //
{
  const out = draw({ pending: 2, recorded_late: null, recorded_late_reason: "the database is locked" });
  assert.ok(/could not be read \(the database is locked\)/.test(out), "the reason is not drawn: " + out);
  assert.ok(!/ \? /.test(out) && !/\?\s+have been/.test(out), "an unknown count was drawn as ?: " + out);
  assert.ok(!/have been recorded late, each/.test(out), "a count was claimed that was never read: " + out);
}

// --- unread with NOTHING queued: the frame does not open with "0 ... are queued" - //
{
  const out = draw({ pending: 0, recorded_late: null, recorded_late_reason: "DatabaseLockedError" });
  assert.ok(/^How many ingest entries have been recorded late could not be read \(DatabaseLockedError\)\./.test(out), out);
  assert.ok(!/are queued/.test(out) && !/^0 /.test(out), "an unread count opened with a queue of zero: " + out);
}

// --- a read count is drawn as a number, and a zero stays a zero ------------- //
{
  const out = draw({ pending: 1, recorded_late: 0 });
  assert.ok(/ 0 have been recorded late/.test(out), out);
}
{
  const out = draw({ pending: 0, recorded_late: 7 });
  assert.ok(/ 7 have been recorded late/.test(out), out);
}

// --- the age of the reading is carried, with the verb that fits ------------- //
{
  const at = "2026-10-25T21:00:00Z";
  const counted = draw({ pending: 0, recorded_late: 7, recorded_late_computed_at: at });
  assert.ok(/Counted at /.test(counted), counted);
  const asked = draw({ pending: 2, recorded_late: null, recorded_late_reason: "boom", recorded_late_computed_at: at });
  assert.ok(/Asked at /.test(asked) && !/Counted at/.test(asked), asked);
  const bad = draw({ pending: 0, recorded_late: 7, recorded_late_computed_at: "not a date" });
  assert.ok(bad.includes("Counted at not a date"), "an unparseable time was dropped or garbled: " + bad);
  // The app's own formatter is used when present (the app language, not the browser's); where it returns nothing the browser's form is used.
  FMT.fn = () => "25 octobre 2026, 21:00";
  const fr = draw({ pending: 0, recorded_late: 7, recorded_late_computed_at: at });
  assert.ok(fr.includes("Counted at 25 octobre 2026, 21:00."), "the app formatter was not used: " + fr);
  FMT.fn = () => "";
  const fb = draw({ pending: 0, recorded_late: 7, recorded_late_computed_at: at });
  assert.ok(fb.includes("Counted at ") && !fb.includes("octobre"), "no fallback when the formatter answers nothing: " + fb);
  FMT.fn = null;
  const none = draw({ pending: 0, recorded_late: 7 });
  assert.ok(!/Counted at|Asked at/.test(none), "a time was invented: " + none);
}

console.log("all assertions passed");
