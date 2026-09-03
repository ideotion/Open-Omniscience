// S3.4 (ruling 7): the client half of "both ends under load", run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Extracted from the shipped engine rather than re-typed: a copy would pass while the
// real function was broken. The extractor balances PARENTHESES before looking for the
// body brace, so a `{}` in a default parameter cannot truncate a slice to its signature.
//
// WHY BEHAVIOURAL: the property is a SCHEDULE. "the interval multiplies by up to 8x"
// cannot be read off the source -- the old code called setInterval with a constant, which
// is a perfectly good-looking line that simply cannot back off. So the poll chain is
// driven here with a fake clock and the assertion is on the delay it actually asks for.
//
// The NEGATIVE-SPACE TWIN is mandatory: a client that backed off and never came back would
// pass every "it slows down" assertion while leaving a recovered server polled once every
// two minutes forever. Recovery is asserted, and so is the untouched cadence of a healthy
// server -- a backoff that fires when nothing refused is a fabricated slowdown.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

// The signature matters as much as the body: rebuilding a function as
// `function name()` silently drops its PARAMETERS, so the reconstructed copy
// throws ReferenceError on the very argument the real one is called with. Take
// the whole declaration.
function functionSource(src, name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error("no function named " + name);
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const sig = src.slice(at, i);
  return sig + functionBody(src, name);
}

function functionBody(src, name) {
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
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(open, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

// The REAL constants and functions, read out of the shipped engine. Chosen here would
// mean this suite describes a function that no longer exists.
const winMatch = APP.match(/const _LOAD_WINDOW_MS = (\d+);/);
const maxMatch = APP.match(/const _LOAD_MAX_FACTOR = (\d+);/);
assert.ok(winMatch, "_LOAD_WINDOW_MS must be declared in the engine");
assert.ok(maxMatch, "_LOAD_MAX_FACTOR must be declared in the engine");
const LOAD_WINDOW_MS = Number(winMatch[1]);
const LOAD_MAX_FACTOR = Number(maxMatch[1]);

// The Home poll interval, likewise read from the shipped LIVE registry rather than
// hardcoded -- the mutation this suite exists to catch is "schedules at exactly 15000".
const homeMatch = APP.match(/home:\s*\{ms:\s*(\d+),/);
assert.ok(homeMatch, "the LIVE registry must declare a home interval");
const HOME_MS = Number(homeMatch[1]);

// --- the harness ------------------------------------------------------------------- //

let now = 1000000;
const toasts = [];

const sandbox = {
  Date: {now: () => now},
  Math: Math,
  String: String,
  toast: (msg, kind) => toasts.push({msg, kind}),
  window: {},
};

// Build the load tracker out of the real bodies.
const NAMES = ["_noteServerBusy", "_loadFactor", "_noteLoadCadence", "_loadState", "_resetLoadState"];
let src = "let _loadRefusals = []; let _loadBannerFactor = 0;\n" +
          "const _LOAD_WINDOW_MS = " + LOAD_WINDOW_MS + ";\n" +
          "const _LOAD_MAX_FACTOR = " + LOAD_MAX_FACTOR + ";\n";
for (const n of NAMES) src += functionSource(APP, n) + "\n";
src += "return {" + NAMES.join(", ") + "};";

const make = new Function("Date", "Math", "String", "toast", "window", src);
const L = make(sandbox.Date, sandbox.Math, sandbox.String, sandbox.toast, sandbox.window);

function reset() { L._resetLoadState(); toasts.length = 0; }

// --- 1. a healthy server is polled at exactly its declared cadence ------------------ //
reset();
assert.strictEqual(L._loadFactor(), 1, "no refusals must mean no backoff");
assert.strictEqual(HOME_MS * L._loadFactor(), HOME_MS,
  "a healthy server must be polled at the base interval, unchanged");
assert.strictEqual(toasts.length, 0, "a healthy server must produce no banner");

// --- 2. the brief's case: after two refusals the next tick is >= 2x the base -------- //
reset();
L._noteServerBusy();
L._noteServerBusy();
const delay2 = HOME_MS * L._loadFactor();
assert.ok(delay2 >= 2 * HOME_MS,
  "after two 503s the next Home tick must be scheduled at >= 2x the base interval, got " + delay2);
L._noteLoadCadence(delay2);
assert.strictEqual(toasts.length, 1, "exactly one banner, naming the new cadence");
assert.ok(/busy/i.test(toasts[0].msg), "the banner must say the server is busy: " + toasts[0].msg);
assert.ok(toasts[0].msg.indexOf(String(Math.round(delay2 / 1000))) >= 0,
  "the banner must name the cadence it actually moved to (" +
  Math.round(delay2 / 1000) + "s): " + toasts[0].msg);

// --- 3. the banner is not repeated while the cadence is unchanged ------------------- //
const before = toasts.length;
L._noteLoadCadence(delay2);
L._noteLoadCadence(delay2);
assert.strictEqual(toasts.length, before,
  "a banner repeated every tick is a toast storm with extra steps");

// --- 4. the ladder is bounded ------------------------------------------------------- //
reset();
for (let i = 0; i < 50; i++) L._noteServerBusy();
assert.strictEqual(L._loadFactor(), LOAD_MAX_FACTOR,
  "the multiplier must be bounded at " + LOAD_MAX_FACTOR + "x, however many refusals arrive");

// --- 5. THE NEGATIVE TWIN: it comes back on its own -------------------------------- //
// A backoff with no way down is worse than none: it leaves a recovered server polled
// once every two minutes for the rest of the session, and nothing would ever say so.
reset();
L._noteServerBusy(); L._noteServerBusy(); L._noteServerBusy();
assert.ok(L._loadFactor() > 1, "the ladder must have engaged before recovery can be tested");
L._noteLoadCadence(HOME_MS * L._loadFactor());
now += LOAD_WINDOW_MS + 1;                       // the refusals age out of the window
assert.strictEqual(L._loadFactor(), 1,
  "the backoff must decay to the base cadence on its own once refusals stop");
L._noteLoadCadence(HOME_MS);
const recovered = toasts[toasts.length - 1];
assert.ok(/recover/i.test(recovered.msg),
  "recovery must be announced, not silently resumed: " + recovered.msg);
assert.strictEqual(recovered.kind, "ok", "recovery is not a warning");

// --- 6. the refusals counted are the ones inside the window ------------------------- //
reset();
L._noteServerBusy();
now += LOAD_WINDOW_MS + 1;
L._noteServerBusy();
assert.strictEqual(L._loadState().refusals, 1,
  "a refusal older than the window must not keep the client slowed down forever");

// --- 7. the poll chain reads the factor rather than a constant --------------------- //
// The mutation this catches: setInterval(..., spec.ms) -- a line that looks correct and
// cannot back off. Driving the real schedule() with a fake timer records what it asks for.
{
  const liveSrc = APP;

  // BEHAVIOURAL FIRST, deliberately. The source checks below are a useful extra,
  // but if one of them runs first it aborts the suite before the delay is ever
  // driven -- and then the brief's own mutation ("schedules at exactly 15000")
  // is caught by a string rather than by the number it is about. A guard that
  // fires on the wrong assertion is a guard whose claim is untested.
  const nextSrc =
    "const LIVE = {home: {ms: " + HOME_MS + "}};\n" +
    functionSource(liveSrc, "liveNextDelayMs") + "\n" +
    "return liveNextDelayMs;";
  const nextDelay = new Function("_loadFactor", nextSrc)(L._loadFactor);
  reset();
  assert.strictEqual(nextDelay("home"), HOME_MS, "healthy: the declared interval");
  L._noteServerBusy(); L._noteServerBusy();
  assert.ok(nextDelay("home") >= 2 * HOME_MS,
    "loaded: at least twice the declared interval, got " + nextDelay("home"));
  assert.strictEqual(nextDelay("nosuchtab"), null, "an unknown tab has no delay to report");

  // Now the source checks, which say HOW the delay is arrived at.
  const startLiveBody = functionBody(liveSrc, "startLive");
  assert.ok(startLiveBody.indexOf("setTimeout") >= 0,
    "startLive must reschedule (setInterval cannot change its delay)");
  assert.ok(startLiveBody.indexOf("_loadFactor") >= 0,
    "startLive must read the load factor when computing its next delay");
}

console.log("ok - load backoff: base " + HOME_MS + "ms, ceiling " + LOAD_MAX_FACTOR +
            "x, window " + LOAD_WINDOW_MS + "ms, recovers on its own");
