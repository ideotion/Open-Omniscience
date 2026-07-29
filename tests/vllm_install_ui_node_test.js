/**
 * Behavioural node test for the two frontend halves of the vLLM-install blocker
 * (skeptic finding, 2026-07-29). Run by tests/test_vllm_install_ui.py, and
 * standalone: `node tests/vllm_install_ui_node_test.js`.
 *
 * app.js is a classic script, not a module, so the functions under test are
 * EXTRACTED FROM THE REAL FILE by name and evaluated -- never re-typed here.
 * A copy-pasted reimplementation would pass while the shipped code was broken,
 * which is the whole failure mode this test exists to prevent.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const APP = fs.readFileSync(
  path.join(__dirname, "..", "src", "static", "app.js"), "utf-8");

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }

/** Pull one top-level `function <name>(...) { ... }` out of app.js by brace matching. */
function extract(name, decl) {
  const head = decl || ("function " + name + "(");
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head + " in app.js");
  let i = APP.indexOf("{", at), depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

// ---------------------------------------------------------------- _apiErrorMessage
const _apiErrorMessage = eval("(" + extract("_apiErrorMessage") + ")");
const res409 = { status: 409, statusText: "Conflict" };

// The regression this test exists for: a DICT detail must render as prose.
const ackBody = { detail: {
  error: "This machine is below a resource floor for a vLLM install.",
  acknowledgeable: true,
  warnings: [{ check: "ram", detail: "This machine has 6.03 GB of total RAM..." }],
  preflight: {},
} };
const ackMsg = _apiErrorMessage(ackBody, res409);
assert(typeof ackMsg === "string", "an object detail must render as a STRING, got " + typeof ackMsg);
assert(new Error(ackMsg).message.indexOf("[object Object]") === -1,
  "an object detail must never render as [object Object]");
assert(ackMsg.indexOf("below a resource floor") !== -1,
  "an object detail must surface its own `error` prose");

// Byte-identical behaviour for every pre-existing shape.
assert(_apiErrorMessage({ detail: "No GPU detected." }, res409) === "No GPU detected.",
  "a string detail must be unchanged");
assert(_apiErrorMessage({ detail: [{ msg: "field required" }, { msg: "bad int" }] }, res409)
  === "field required; bad int", "a Pydantic array detail must be unchanged");
assert(_apiErrorMessage(null, res409) === "409 Conflict", "no detail -> status + statusText");
assert(_apiErrorMessage({ detail: "" }, res409) === "409 Conflict", "empty detail -> status fallback");
assert(_apiErrorMessage({ detail: {} }, res409) === "{}",
  "an object with no prose field is still readable (JSON), never [object Object]");

// ---------------------------------------------------------------- _vllmInstallStart
// Drive the real acknowledge flow with a stubbed api()/confirm(), asserting the
// operator can actually get past a WARNING and can never override a BLOCKING refusal.
const startSrc = extract("_vllmInstallStart", "async function _vllmInstallStart(");

// The eval'd body closes over the names in THIS scope, so the stubs are bound here.
let api, confirm;
function makeStart(stub) {
  api = stub.api;
  confirm = stub.confirm;
  // `window` is referenced for the OOI18N lookup; an empty object exercises the
  // identity-fallback branch, which is the shape a non-en locale must not break.
  globalThis.window = {};
  return eval("(" + startSrc + ")");
}

function stub(firstError, confirmAnswer) {
  const c = [];
  return {
    calls: c,
    api: async (p, opts) => { c.push(JSON.parse(opts.body)); if (c.length === 1 && firstError) throw firstError; return { started: true }; },
    confirm: () => confirmAnswer,
  };
}

function ackError(acknowledgeable) {
  const e = new Error("below a resource floor");
  e.status = 409;
  e.detail = { error: "below a resource floor", acknowledgeable,
               warnings: [{ check: "ram", detail: "6.03 GB of total RAM" }] };
  return e;
}

(async () => {
  // 1. A warning the operator ACCEPTS -> a second POST carrying the acknowledgement.
  let s = stub(ackError(true), true);
  let started = await makeStart(s)();
  assert(s.calls.length === 2, "an accepted warning must retry the install, got " + s.calls.length + " call(s)");
  assert(s.calls[0].acknowledge_low_resources === undefined,
    "the FIRST attempt must not pre-acknowledge -- the warning has not been shown yet");
  assert(s.calls[1].acknowledge_low_resources === true,
    "the retry must carry acknowledge_low_resources:true");
  assert(started && started.started === true, "the accepted path must return the started status");

  // 2. A warning the operator DECLINES -> no retry, and null (not an exception).
  s = stub(ackError(true), false);
  started = await makeStart(s)();
  assert(s.calls.length === 1, "a declined warning must NOT retry");
  assert(started === null, "a declined warning must return null so the caller can say so");

  // 3. A BLOCKING refusal is never overridable, whatever the operator clicks.
  s = stub(ackError(false), true);
  let threw = false;
  try { await makeStart(s)(); } catch (e) { threw = true; }
  assert(threw, "a blocking (acknowledgeable:false) refusal must propagate, never be retried");
  assert(s.calls.length === 1, "a blocking refusal must NOT retry");

  // 4. An unrelated error (no structured detail) still propagates unchanged.
  const plain = new Error("Network is OFF (airplane mode)");
  plain.status = 409;
  s = stub(plain, true);
  threw = false;
  try { await makeStart(s)(); } catch (e) { threw = true; }
  assert(threw, "an error with no acknowledgeable detail must propagate");
  assert(s.calls.length === 1, "an unrelated error must NOT retry");

  console.log("VLLM INSTALL UI OK");
})();
