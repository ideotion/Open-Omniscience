// The all-diagnostics poller's honest exit, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Extracted from src/static/app.js rather than re-typed: a copy would pass while the
// shipped function was broken. The extractor balances the PARENTHESES before looking for
// the body brace, so a `{}` in a default parameter cannot truncate the slice to its
// signature (the shape that once made every assertion over an ooChart slice pass for free).
//
// WHY THIS IS BEHAVIOURAL AND NOT A SOURCE GREP: the defect was an absence. The loop ran a
// fixed number of iterations and then simply ended, leaving the status frozen on its last
// "Building in the background… 42%" line -- which a field report read, correctly, as the
// app having stopped. No source assertion over the presence of a string can distinguish
// "the message exists in the file" from "the message is reached when the ceiling is hit",
// and it is the reaching that was broken. So the ceiling is actually driven here, with a
// fake clock, and the assertion is on what the operator ends up reading.
//
// The NEGATIVE-SPACE TWIN is mandatory in the other direction too: a fix that painted the
// honest message unconditionally would satisfy the first case while destroying the normal
// download path, so the terminal states are asserted to still win.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const APP = fs.readFileSync(
  path.join(__dirname, "..", "src", "static", "app.js"), "utf8");

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

// The REAL ceiling, read out of the shipped source -- not a number chosen here, so raising
// or lowering it in app.js cannot silently make this test describe a different function.
const ceilMatch = APP.match(/const _ALL_DIAG_POLL_CEILING_MS = ([^;]+);/);
assert.ok(ceilMatch, "_ALL_DIAG_POLL_CEILING_MS must be declared in app.js");

// --- the harness ------------------------------------------------------------------ //

let clock, statusText, opened, apiCalls, respond;

function install() {
  clock = 1_000_000;           // any epoch; only differences matter
  statusText = null;
  opened = [];
  apiCalls = [];
  Date.now = () => clock;
  // A sleep that advances the fake clock by exactly what it was asked to wait, and
  // resolves at once. This is what lets a 6-hour ceiling be reached in milliseconds --
  // and it means the loop's own poll interval decides how many iterations that takes,
  // so the real pacing is exercised rather than bypassed.
  global.setTimeout = (fn, ms) => { clock += (ms || 0); fn(); };
  global.window = { open: (u) => opened.push(u) };
  global.$ = () => ({ set textContent(v) { statusText = v; }, get textContent() { return statusText; } });
  global._fmtBytes = (n) => n + " B";
  global.api = async (url) => { apiCalls.push(url); return respond(url); };
}

const SRC =
  "const _ALL_DIAG_POLL_CEILING_MS = " + ceilMatch[1] + ";\n" +
  "async function runAllDiagnostics(btn) " + functionBody(APP, "runAllDiagnostics") + "\n" +
  "module.exports = { runAllDiagnostics };";

const mod = { exports: {} };
new Function("module", "global", "require", SRC)(mod, global, require);
const { runAllDiagnostics } = mod.exports;

// --- 1. the ceiling must SPEAK, not just stop ------------------------------------- //

async function ceilingReportsInsteadOfFreezing() {
  install();
  // A build that never finishes: exactly the corpus-scale case, where ~55 members each
  // allowed a 300 s deadline outlive any display ceiling worth setting.
  respond = (url) => url.endsWith("/status")
    ? { state: "running", done: 12, total: 55, detail: "source-audit.json", started_at: 0 }
    : { started: true };

  await runAllDiagnostics(null);

  assert.ok(statusText, "the poller must leave a message");
  assert.ok(
    !/Building in the background/.test(statusText),
    "FROZEN PROGRESS LINE: the ceiling left the last progress line standing as though it " +
    "were the outcome -- the exact appearance of a crash. Got: " + JSON.stringify(statusText),
  );
  assert.ok(
    /Still building/.test(statusText),
    "the ceiling must say the build is still running server-side. Got: " +
    JSON.stringify(statusText),
  );
  // And it must have actually polled for the whole window rather than bailing early.
  assert.ok(
    apiCalls.filter((u) => u.endsWith("/status")).length > 100,
    "expected the ceiling to be reached by real polling, not by an early exit; " +
    "status polls: " + apiCalls.filter((u) => u.endsWith("/status")).length,
  );
}

// --- 2. the twin: a finished build still downloads -------------------------------- //

async function readyStillDownloads() {
  install();
  let polls = 0;
  respond = (url) => {
    if (!url.endsWith("/status")) return { started: true };
    polls++;
    return polls < 3
      ? { state: "running", done: 1, total: 55, detail: "debug-bundle.json", started_at: 0 }
      : { state: "done", ready: true, download_bytes: 4242 };
  };

  await runAllDiagnostics(null);

  assert.deepStrictEqual(
    opened, ["/api/diagnostics/all-job/download"],
    "a finished build must still be downloaded -- an honest ceiling message must not have " +
    "replaced the normal path",
  );
  assert.ok(/Ready/.test(statusText), "got: " + JSON.stringify(statusText));
}

// --- 3. the twin, other direction: a real failure still reads as a failure --------- //

async function errorStillReportsFailure() {
  install();
  respond = (url) => url.endsWith("/status")
    ? { state: "error", error: "disk full" }
    : { started: true };

  await runAllDiagnostics(null);

  assert.ok(
    /Build failed/.test(statusText) && /disk full/.test(statusText),
    "a backend error state must still report the failure and its reason. Got: " +
    JSON.stringify(statusText),
  );
  assert.ok(
    !/Still building/.test(statusText),
    "a FAILED build must never be described as still building",
  );
}

(async () => {
  await ceilingReportsInsteadOfFreezing();
  await readyStillDownloads();
  await errorStillReportsFailure();
  console.log("ok - all-diagnostics poll loop: ceiling speaks, terminal states still win");
})().catch((e) => { console.error(e); process.exit(1); });
