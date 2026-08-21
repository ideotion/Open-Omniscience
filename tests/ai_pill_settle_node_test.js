// The AI pill's start watcher, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// THE DEFECT THIS PINS. `_aiPillSettle` used to re-check health at 800ms, 2.5s and 6s
// and then stop -- while the comment three lines above it said, correctly, that a vLLM
// engine load "takes tens of seconds". So on any machine where the start took longer
// than six seconds the watcher gave up first, the pill stayed red, and the backend only
// went green when something ELSE happened to re-check it: opening Settings -> AI, which
// calls loadLlmHealth() on subtab select. Field report, verbatim: "when clicking on it
// to activate AI backend, it seems to work, but doesn't turn green, it turns green only
// when I go to the setting's AI tab."
//
// WHY THIS IS BEHAVIOURAL AND NOT A SOURCE GREP. Every number involved -- the old
// [800, 2500, 6000] and the new bound -- is a plausible-looking constant, and no
// assertion over the presence of one can say whether the watcher is still watching when
// the backend finally answers. It is the still-watching that was broken. So the real
// function is extracted from the shipped file (a re-typed copy would pass while app.js
// was broken) and driven against a clock the test controls.
//
// THE THREE CASES ARE ONE PROPERTY SEEN FROM THREE SIDES: it must outlast a slow start,
// it must not lie when it gives up, and it must not sit waiting on a fast one. A fix
// that only satisfied the first would be a watcher that always waits two minutes.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

// The engine is several ordered modules since 2026-08-20 (S-3); the helper reads the
// module list out of index.html, so this suite cannot come to read a subset of it.
const APP = require("./app_source.js").appJs();

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

// The REAL bound, read out of the shipped source. Changing it in app.js changes what
// this test describes, rather than leaving the test asserting about a number nobody
// ships any more.
const boundMatch = APP.match(/const _AI_SETTLE_MS = ([0-9_]+)\s*;/);
assert.ok(boundMatch, "_AI_SETTLE_MS must be declared in app.js");
const BOUND = Number(boundMatch[1].replace(/_/g, ""));

// The old window, stated here so the discriminating case cannot drift back inside it.
const OLD_WINDOW_MS = 6000;
assert.ok(
  BOUND > OLD_WINDOW_MS * 5,
  "the bound must comfortably outlast a vLLM engine load (~60-90s), not the six " +
  "seconds that produced the field report. Got: " + BOUND,
);

// --- the harness ------------------------------------------------------------------ //

let clock, paints, toasts, healthReloads, apiCalls, respond, done, resolveDone;

function install() {
  clock = 1_000_000;              // any epoch; only differences matter
  paints = [];
  toasts = [];
  healthReloads = 0;
  apiCalls = [];
  done = new Promise((r) => { resolveDone = r; });
  Date.now = () => clock;
  // Advances the fake clock by exactly what it was asked to wait, then runs the
  // callback. The watcher's OWN backoff therefore decides how many iterations a
  // two-and-a-half-minute bound takes, so the real pacing is exercised rather than
  // bypassed -- if the backoff were removed, this test would spin, which is itself
  // information.
  global.setTimeout = (fn, ms) => { clock += (ms || 0); fn(); };
  global.window = {};             // no OOI18N -> t() falls back to identity
  global.api = async (url) => { apiCalls.push({ url, at: clock }); return respond(url); };
}

const SRC = [
  "let _aiStarting = false;",
  "let _aiSettleCancel = null;",
  "const _AI_SETTLE_MS = " + boundMatch[1] + ";",
  "const api = (...a) => global.api(...a);",
  "const toast = (m, k) => { global.__toasts.push({ msg: m, kind: k }); };",
  "function _paintAiPill() { global.__paints.push(_aiStarting); }",
  // Both exits call loadLlmHealth(), so it is the completion signal the test awaits.
  "function loadLlmHealth() { global.__healthReload(); }",
  "function _aiPillSettle() " + functionBody(APP, "_aiPillSettle"),
  "module.exports = { _aiPillSettle, starting: () => _aiStarting };",
].join("\n");

const mod = { exports: {} };
new Function("module", "global", "require", SRC)(mod, global, require);
const { _aiPillSettle, starting } = mod.exports;

// Bridges, so each install() re-points them without rebuilding the module.
Object.defineProperty(global, "__paints", { get: () => paints });
Object.defineProperty(global, "__toasts", { get: () => toasts });
global.__healthReload = () => { healthReloads++; resolveDone(); };

// --- 1. THE ONE THAT MATTERS: it must outlast a slow start ------------------------ //

async function outlastsASlowStart() {
  install();
  // A vLLM engine reaching CUDA-graph capture around t+67s: far past the old six
  // seconds, comfortably inside the new bound. This is the shape the field hit.
  const upAt = 67_000;
  const t0 = clock;
  respond = () => ({ available: clock - t0 >= upAt });

  _aiPillSettle();
  await done;

  // ORDER MATTERS HERE. The pre-fix version scheduled three bare loadLlmHealth calls
  // and never probed at all, so it reaches the end with an EMPTY apiCalls -- and a bare
  // `apiCalls[last]` would then blow up with a TypeError, which is a failure that
  // teaches a future reader nothing. The emptiness IS the finding, so it is asserted
  // first and in words.
  assert.ok(
    apiCalls.length > 0,
    "NEVER PROBED: the watcher scheduled its re-checks blind instead of asking whether " +
    "the backend had come up, so nothing could tell a start that is still loading from " +
    "one that has finished. This is the pre-fix [800, 2500, 6000] shape.",
  );
  const last = apiCalls[apiCalls.length - 1].at - t0;
  assert.ok(
    last >= upAt,
    "GAVE UP TOO EARLY: the backend answered at t+" + upAt + "ms and the last probe was " +
    "at t+" + last + "ms, so the pill was left red for a start that had SUCCEEDED -- it " +
    "would go green only when Settings -> AI happened to re-check. That is the field " +
    "report exactly.",
  );
  assert.strictEqual(
    starting(), false,
    "the watcher must clear the starting flag once the backend answers",
  );
  assert.ok(healthReloads > 0, "a settled start must repaint the pill from live health");
  // And it must not have hammered: the backoff is what makes a two-minute window cheap.
  assert.ok(
    apiCalls.length < 40,
    "expected a backing-off poll, got " + apiCalls.length + " calls in " + last + "ms",
  );
  assert.ok(
    toasts.length === 0,
    "a start that SUCCEEDED must not also report a failure. Got: " +
    JSON.stringify(toasts),
  );
}

// --- 2. the bound must SPEAK, not just stop --------------------------------------- //

async function theBoundSaysSoInsteadOfLeavingItRed() {
  install();
  respond = () => ({ available: false });   // never comes up

  _aiPillSettle();
  await done;

  assert.strictEqual(starting(), false, "the starting state must clear when it gives up");
  assert.ok(
    toasts.length === 1,
    "A BOUNDED WATCHER THAT EXITS SILENTLY PUBLISHES ITS OWN TIMEOUT AS THE OUTCOME: " +
    "giving up without a word leaves a red pill speaking for a start that may still be " +
    "loading. Got toasts: " + JSON.stringify(toasts),
  );
  assert.ok(
    /has not answered yet/.test(toasts[0].msg),
    "the message must say the AI has not answered YET -- not that it failed, which is " +
    "a verdict nothing measured. Got: " + JSON.stringify(toasts[0].msg),
  );
  assert.strictEqual(toasts[0].kind, "err", "the give-up notice must be visible as such");
  const spanned = apiCalls[apiCalls.length - 1].at - 1_000_000;
  assert.ok(
    spanned >= BOUND * 0.8,
    "it must actually watch for its whole bound before giving up; watched " + spanned +
    "ms of a " + BOUND + "ms bound",
  );
}

// --- 3. the twin: a fast start must not wait the whole window --------------------- //

async function aFastStartGoesGreenAtOnce() {
  install();
  const t0 = clock;
  respond = () => ({ available: true });    // Ollama: already answering

  _aiPillSettle();
  await done;

  const last = apiCalls[apiCalls.length - 1].at - t0;
  assert.ok(
    last < 5_000,
    "AN OVER-EAGER FIX IS ALSO A BUG: a backend that is already answering must settle " +
    "immediately, not sit through the bound. Took " + last + "ms.",
  );
  assert.strictEqual(apiCalls.length, 1, "one probe is enough when the answer is yes");
  assert.strictEqual(toasts.length, 0, "nothing to report when it simply worked");
}

// --- 4. the pill shows STARTING while it waits, not the stale red ------------------ //

async function itPaintsStartingWhileWaiting() {
  install();
  const t0 = clock;
  respond = () => ({ available: clock - t0 >= 30_000 });

  _aiPillSettle();
  await done;

  assert.strictEqual(
    paints[0], true,
    "the pill must paint STARTING the moment the watch begins -- showing red through a " +
    "start we ourselves triggered is what made it read as 'it didn't work'",
  );
}

(async () => {
  await outlastsASlowStart();
  await theBoundSaysSoInsteadOfLeavingItRed();
  await aFastStartGoesGreenAtOnce();
  await itPaintsStartingWhileWaiting();
  console.log("ai_pill_settle_node_test: 4 passed");
})().catch((e) => { console.error(e); process.exit(1); });
