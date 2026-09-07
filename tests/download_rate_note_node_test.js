// PERF-09's task-manager rate line, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The backend now measures a per-job download rate, and a payload nobody draws is the
// recorded "machine-readable answer with no caller" dead end -- so the RENDER is part of
// the slice, not a follow-up. There is no browser in this lane, so it is driven in node.
//
// What is actually being guarded is a set of REFUSALS, and none of them is visible in a
// diff: an unmeasured rate must draw NOTHING (a "0 B/s" or a "—" beside a download that
// started a second ago is a number where there is no measurement), while a STALL must
// draw, because a running transfer whose bytes stopped is the one case an operator needs
// to see. A source-level assertion cannot tell those apart -- both are "the function
// mentions r.measured" -- so this runs the function.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace: a `{}` in a default parameter would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
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

// The real `esc` and `_fmtBytes`/`_fmtDur` shapes; OOI18N absent, which is also the
// boot-time state, so the tf() fallback path is exercised too.
const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = {};\n" +
  extract("_fmtBytes") + "\n" +
  extract("_fmtDur") + "\n" +
  extract("_rateNote") + "\n" +
  "module.exports = { _rateNote };";
const { _rateNote } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s; // the identity the real t() falls back to before i18n loads

// --- a measured rate draws, with its method in the hover ------------------- //
{
  const out = _rateNote({ state: "running", rate: {
    measured: true, bytes_per_s: 1048576, window_s: 12.0, samples: 13,
    method: "bytes received by the download worker itself, divided by the wall time",
  } }, t);
  assert.ok(out.includes("1.0 MB/s"), "the measured rate is not drawn: " + out);
  assert.ok(out.includes("title="), "the method is not offered on hover: " + out);
  assert.ok(/Not an estimate made in the browser/.test(out),
    "the hover does not say whose measurement this is: " + out);
  assert.ok(!/left/.test(out), "an ETA was drawn without eta_seconds: " + out);
}

// --- an ETA draws only when the payload carries one ------------------------ //
{
  const out = _rateNote({ state: "running", rate: {
    measured: true, bytes_per_s: 1048576, eta_seconds: 240, method: "m",
  } }, t);
  assert.ok(out.includes("1.0 MB/s"), out);
  assert.ok(out.includes("4 min"), "the ETA is not drawn: " + out);
  assert.ok(out.includes("left"), out);
}

// --- THE REFUSALS. An unmeasured rate draws nothing at all ----------------- //
for (const reason of [
  "no bytes observed yet",
  "only one sample in the window so far",
  "measured over 0.30 s, under the 1 s floor",
  "not measured in this session",
]) {
  const out = _rateNote({ state: "running", rate: { measured: false, reason } }, t);
  assert.strictEqual(out, "",
    "an unmeasured rate drew something (" + reason + "): " + JSON.stringify(out));
}
{
  // ...and neither a missing block nor a missing job invents one.
  assert.strictEqual(_rateNote({ state: "running" }, t), "");
  assert.strictEqual(_rateNote(null, t), "");
  // A zero must never reach the renderer as a rate, but if it ever did it is
  // still a measurement and is drawn as one -- the honesty lives in the OWNER,
  // which omits rather than zeroes, and this pins that the renderer does not
  // quietly paper over a producer that starts fabricating zeroes.
  const z = _rateNote({ state: "running", rate: { measured: true, bytes_per_s: 0, method: "m" } }, t);
  assert.ok(z.includes("0 B/s"), z);
}

// --- A STALL draws, and ONLY for a job that is supposed to be moving -------- //
{
  const stalled = { measured: false, reason: "no bytes received in the last 20 s", idle_s: 95 };
  const running = _rateNote({ state: "running", rate: stalled }, t);
  assert.ok(/no data for/.test(running), "a stalled RUNNING download drew nothing: " + running);
  assert.ok(/2 min/.test(running), running);
  assert.ok(/still open/.test(running),
    "the stall hover does not explain that the download resumes: " + running);

  // A PAUSED or QUEUED download is not stalled -- it is stopped, which the state
  // pill already says. Drawing "no data for 3 days" beside it would report a
  // fault where there is none.
  for (const state of ["paused", "queued", "failed"]) {
    assert.strictEqual(_rateNote({ state, rate: stalled }, t), "",
      "a " + state + " download drew a stall note");
  }
}

console.log("all assertions passed");
