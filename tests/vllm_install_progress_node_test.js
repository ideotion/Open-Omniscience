/**
 * Behavioural node test for install PROGRESS reporting (field report 2026-08-01:
 * "clicking on the install button just changes its color, and users are left
 * with no UI information about what's going on, whether the install is really
 * ongoing, or not").
 *
 * The root cause was not a missing progress widget. POST-ing a job endpoint only
 * SPAWNS the worker thread and returns at once, so the setup chain's
 * `await _vllmInstallStart()` had STARTED the install, not finished it -- it then
 * raced straight on to the next step while gigabytes were still downloading.
 * `_followJob` is what turns "started" into "finished, and here is every line".
 *
 * As with the sibling test, the function is EXTRACTED FROM THE REAL app.js by
 * name -- a re-typed copy would pass while the shipped code was broken.
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

function extract(name, decl) {
  const head = decl || ("async function " + name + "(");
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head + " in app.js");
  let i = APP.indexOf("{", at), depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

// `_followJob` closes over `api`, `OOI18N` and `setTimeout`. Provide them, and make
// setTimeout instant so the test does not actually wait 3 s per poll.
let api;                                   // eslint-disable-line prefer-const
// `_followJob` reads OOI18N via `window`, exactly as the browser does.
const OOI18N = { t: (s) => s };
global.window = { OOI18N };
const realSetTimeout = setTimeout;
// eslint-disable-next-line no-global-assign
setTimeout = (fn) => realSetTimeout(fn, 0);

const _followJob = eval("(" + extract("_followJob") + ")");

(async () => {
  // ---------------------------------------------------------------- reports EVERY line
  {
    const states = [
      { state: "running", detail: "preparing the managed venv" },
      { state: "running", detail: "installing uv (a fast resolver...)" },
      { state: "running", detail: "uv install vllm==0.26.0" },
      { state: "done", detail: "installed" },
    ];
    let i = 0;
    api = async () => states[Math.min(i++, states.length - 1)];
    const seen = [];
    const out = await _followJob("/api/llm/vllm/install/status", (l) => seen.push(l));
    assert(out.state === "done", "must resolve with the TERMINAL status, got " + out.state);
    assert(seen.length >= 3, "every progress line must be reported, saw " + seen.length);
    assert(seen[0] === "preparing the managed venv",
      "the first real phase must reach the UI, got " + seen[0]);
    assert(seen.includes("uv install vllm==0.26.0"),
      "the resolver line must reach the UI -- this is the one that shows work is happening");
  }

  // ------------------------------------------------- a FAILED job resolves, never throws
  // The caller must be able to tell "the job failed" from "the poll broke", and act
  // differently: a failed install must stop the chain, not be mistaken for success.
  {
    api = async () => ({ state: "error", error: "pip exited 1" });
    const out = await _followJob("/x", () => {});
    assert(out.state === "error", "a failed job must RESOLVE with its status, not throw");
    assert(out.error === "pip exited 1", "the real error must survive to the caller");
  }

  // --------------------------------------------- a transient blip must not abandon the job
  // Giving up on the first network hiccup would report failure while a multi-GB
  // download was still running and still costing the operator bandwidth.
  {
    let n = 0;
    api = async () => {
      n += 1;
      if (n <= 2) throw new Error("network blip");
      return { state: "done" };
    };
    const out = await _followJob("/x", () => {});
    assert(out.state === "done", "a couple of failed polls must not abandon a live job");
  }

  // ------------------------------------------------- a SUSTAINED outage is reported, not hidden
  // Silently returning success here is the exact failure this whole change is about.
  {
    api = async () => { throw new Error("down"); };
    let threw = false;
    try { await _followJob("/x", () => {}); } catch (e) { threw = true; }
    assert(threw, "a sustained outage must surface, never be reported as a finished job");
  }

  console.log("VLLM INSTALL PROGRESS OK");
})().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
