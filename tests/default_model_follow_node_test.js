/**
 * The setup chain must be able to RECOGNISE the end of the model download.
 *
 * Field report 2026-08-02: "the install still fails after reinstall. It seems that
 * model does not download." The install had in fact succeeded. The chain then hung on
 * the download step, because `_followJob` returns when the polled payload carries a
 * `state` that is not "running", and `/api/llm/default-model/status` published no
 * top-level `state` on EITHER branch: the vLLM half nested a BackgroundJob under
 * `job`, and the Ollama half returned the raw pull queue (`active`/`queue`/`history`),
 * which has no `state` anywhere. So the follower polled every three seconds forever.
 *
 * Both halves of this test matter, and the second is the one that proves the first is
 * worth anything: the new payloads TERMINATE, and the old ones DO NOT. Without the
 * negative half, a payload shape that quietly lost its `state` again would still pass.
 *
 * `_followJob` is EXTRACTED FROM THE REAL app.js -- a re-typed copy would pass while
 * the shipped code was broken.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const APP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"), "utf-8");

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }

function extract(name) {
  const head = "async function " + name + "(";
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head + " in app.js");
  // Start brace-matching at the BODY brace, never the first brace after the name:
  // a default parameter such as `opts = {}` would otherwise close depth immediately
  // and yield an empty body that passes every assertion vacuously.
  let i = at + head.length - 1, parens = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") parens++;
    else if (APP[i] === ")") { parens--; if (parens === 0) { i++; break; } }
  }
  let body = APP.indexOf("{", i), depth = 0;
  for (let j = body; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

let api;                                   // eslint-disable-line prefer-const
// `_followJob` guards on `window.OOI18N` but then reads the BARE global, exactly as
// the browser resolves it -- so the eval'd body needs both bindings, as its sibling
// node tests do.
const OOI18N = { t: (s) => s };
global.window = { OOI18N };
const realSetTimeout = setTimeout;
// eslint-disable-next-line no-global-assign
setTimeout = (fn) => realSetTimeout(fn, 0);

const _followJob = eval("(" + extract("_followJob") + ")");

// The payloads below are the SHAPES the endpoint returns, kept deliberately literal so
// a change to those shapes has to come here too.
const NEW_VLLM_DONE = {
  backend: "vllm",
  plan: {backend: "vllm", artifact: "mistralai/Ministral-3-3B-Instruct-2512"},
  job: {state: "done", detail: "downloaded"},
  state: "done",
  detail: "downloaded",
};
const NEW_OLLAMA_DONE = {
  backend: "ollama",
  plan: {backend: "ollama", artifact: "ministral-3:3b-instruct-2512-q4_K_M"},
  queue: {active: null, queue: [], history: [{model: "ministral-3:3b-instruct-2512-q4_K_M", status: "done"}]},
  state: "done",
  detail: "downloaded",
};
// Exactly what the endpoint used to return -- the shapes that hung.
const OLD_VLLM = {backend: "vllm", plan: {}, job: {state: "done"}};
const OLD_OLLAMA = {backend: "ollama", plan: {}, queue: {active: null, queue: [], history: []}};

async function follows(payloads, maxPolls) {
  // Resolves with the follower's return value, or the string "HUNG" if it is still
  // polling after maxPolls -- never an actual infinite loop in the test.
  let polls = 0;
  let hung = false;
  api = async () => {
    polls += 1;
    if (polls > maxPolls) { hung = true; throw new Error("__stop__"); }
    return payloads[Math.min(polls - 1, payloads.length - 1)];
  };
  try {
    const out = await _followJob("/api/llm/default-model/status", () => {});
    return {out, polls};
  } catch (e) {
    return {out: hung ? "HUNG" : "THREW:" + e.message, polls};
  }
}

(async () => {
  // ------------------------------------------------- the new shapes terminate
  for (const [name, payload] of [["vLLM", NEW_VLLM_DONE], ["Ollama", NEW_OLLAMA_DONE]]) {
    const r = await follows([payload], 20);
    assert(r.out !== "HUNG", name + ": the follower never returned on the new payload");
    assert(r.out && r.out.state === "done", name + ": expected state=done, got " + JSON.stringify(r.out));
    assert(r.polls === 1, name + ": should finish on the first poll, took " + r.polls);
  }

  // A running download is followed to its end rather than reported early.
  {
    const running = Object.assign({}, NEW_OLLAMA_DONE, {state: "running", detail: "pulling 42%"});
    const r = await follows([running, running, NEW_OLLAMA_DONE], 20);
    assert(r.out !== "HUNG", "a running download must still be followed to completion");
    assert(r.out.state === "done" && r.polls === 3, "expected 3 polls to done, got " + r.polls);
  }

  // An error is RETURNED, not thrown -- the chain stops and says why.
  {
    const failed = {backend: "ollama", state: "error", detail: "ollama: connection refused"};
    const r = await follows([failed], 20);
    assert(r.out !== "HUNG" && r.out.state === "error", "a failed download must be reported");
    assert(String(r.out.detail).includes("connection refused"), "the real reason must survive");
  }

  // ------------------------------------- the negative twin: the old shapes HUNG
  // This is the whole point. If a future payload drops `state` again, the assertions
  // above go green while the chain hangs in the field -- exactly what happened. These
  // two prove the property being tested is the one that was broken.
  for (const [name, payload] of [["vLLM", OLD_VLLM], ["Ollama", OLD_OLLAMA]]) {
    const r = await follows([payload], 6);
    assert(r.out === "HUNG", name + ": the pre-fix payload should have hung, but returned " + JSON.stringify(r.out));
  }

  console.log("ok - the download step can recognise its own end, on both backends");
})();
