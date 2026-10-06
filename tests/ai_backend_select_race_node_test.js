// The AI backend <select>, run as real code (tests/test_ai_backend_select_race.py runs this file).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// THE DEFECT THIS PINS (found by the 2026-10-06 row-I sweep, which read the select as REVERTED in 12 of
// 45 runs). `loadAiBackendPanel` writes the select from the server's stored value, so a load that was
// already in flight when the operator picked held the OLD value and put the select back for seconds,
// until the load that follows the save corrected it. A second, rarer ordering: two quick picks, where
// the first save's reload reaches the server before the second save and writes the older value; and a third,
// a load that began before a save landed answering after it (a panel refresh, or the first save's reload).
//
// WHY THIS IS BEHAVIOURAL. A text pin of the guard passes when the guard's capture is moved after its
// `await` (the mutation that neutralises it). So the real functions are extracted from the shipped file
// and driven against a server whose answers this test controls and releases in the order it chooses.

"use strict";

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function functionSource(src, name) {
  const at = src.indexOf("async function " + name + "(");
  if (at < 0) throw new Error("no async function named " + name);
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

const counters = ["let _aiBackendPicks = 0;", "let _aiBackendSaving = 0;"].map((line) => {
  assert.ok(APP.includes(line), "the shipped file must declare: " + line);
  return line;
}).join("\n");

const LOAD = functionSource(APP, "loadAiBackendPanel");
const SET = functionSource(APP, "setAiBackend");

// One harness per scenario: a select, a server with a stored value, and a queue of deferred answers.
function harness() {
  const sel = { value: "auto" };
  const box = { innerHTML: "" };
  const server = { stored: "auto" };
  const pending = [];                    // answers waiting to be released, in request order
  const log = [];
  const api = (path, opts) => new Promise((resolve, reject) => {
    const entry = { path, opts, resolve, reject };
    if (path === "/api/llm/backend") entry.snapshot = server.stored;   // what the server held when ASKED
    pending.push(entry);
  });
  const env = {
    $: (id) => (id === "ai-backend-select" ? sel : id === "ai-backend-box" ? box : null),
    api,
    toast: (m) => log.push(m),
    _failMsg: (m) => m,
    loadLlmHealth: () => {},
    esc: (x) => String(x == null ? "" : x),
    OOI18N: { t: (s) => s },
    window: { OOI18N: { t: (s) => s } },
    document: { getElementById: () => null, querySelector: () => null },
    console,
  };
  // Any helper the panel's rendering calls that this test does not care about is a no-op returning "".
  const sandbox = new Proxy(env, {
    has: () => true,
    get: (t, k) => (k in t ? t[k] : k in globalThis ? globalThis[k] : (k === Symbol.unscopables ? undefined : () => "")),
  });
  const factory = new Function("sandbox", "with (sandbox) { " + counters + "\n" + LOAD + "\n" + SET +
    "\nreturn { loadAiBackendPanel, setAiBackend }; }");
  const fns = factory(sandbox);
  const payload = (stored) => ({ stored_override: stored, backend: stored, gpu: {}, vllm: {}, ollama: {} });
  // Release the oldest pending call of a path: a settings PUT stores the value; a status GET answers
  // with the value it saw WHEN ASKED (that is the stale answer the defect wrote into the select).
  const release = (path) => {
    const at = pending.findIndex((p) => p.path === path);
    assert.ok(at >= 0, "no pending " + path);
    const [p] = pending.splice(at, 1);
    if (path === "/api/settings") {
      server.stored = JSON.parse(p.opts.body).llm_backend;
      p.resolve({});
    } else p.resolve(payload(p.snapshot));
  };
  // Release the n-th pending call of a path (0 = oldest): the order answers arrive in is the test's to choose.
  const releaseNth = (path, n) => {
    const hits = pending.map((p, i) => (p.path === path ? i : -1)).filter((i) => i >= 0);
    assert.ok(hits.length > n, "no pending " + path + " #" + n);
    const [p] = pending.splice(hits[n], 1);
    p.resolve(payload(p.snapshot));
  };
  const fail = (path) => {
    const at = pending.findIndex((p) => p.path === path);
    const [p] = pending.splice(at, 1);
    p.reject(new Error("refused"));
  };
  const tick = () => new Promise((r) => setImmediate(r));
  return { sel, server, pending, release, releaseNth, fail, tick, ...fns };
}

async function settle(h) { for (let i = 0; i < 5; i++) await h.tick(); }

(async () => {
  // 1. A load already in flight when the operator picks must not put the old value back.
  {
    const h = harness();
    h.loadAiBackendPanel();                    // starts while stored = "auto"
    await settle(h);
    h.sel.value = "ollama"; h.setAiBackend("ollama");      // the operator picks and the save starts
    await settle(h);
    h.release("/api/llm/backend");             // the stale load answers "auto" AFTER the pick
    await settle(h);
    assert.strictEqual(h.sel.value, "ollama", "a load that started before the pick wrote the old value");
    h.release("/api/settings");                // the save lands
    await settle(h);
    h.sel.value = "auto";                      // something else moved the select: a fresh reload must put the stored value back
    h.release("/api/llm/backend");             // the reload that follows the save (it saw "ollama")
    await settle(h);
    assert.strictEqual(h.sel.value, "ollama", "the reload that follows a landed save must write the stored value");
  }
  // 1b. The save has already landed when the stale load answers: only the capture-at-start covers this.
  {
    const h = harness();
    h.loadAiBackendPanel();
    await settle(h);
    h.sel.value = "ollama"; h.setAiBackend("ollama");
    await settle(h);
    h.release("/api/settings");                // the save lands: nothing is in flight any more
    await settle(h);
    const stale = h.pending.findIndex((p) => p.path === "/api/llm/backend" && p.snapshot === "auto");
    assert.ok(stale >= 0);
    h.release("/api/llm/backend");             // the OLDEST pending load: the one that started before the pick
    await settle(h);
    assert.strictEqual(h.sel.value, "ollama", "the stale load wrote the old value after the save had landed");
    while (h.pending.length) h.release("/api/llm/backend");
    await settle(h);
    assert.strictEqual(h.sel.value, "ollama");
  }
  // 2. Two quick picks: the first save's reload must not write while the second save is in flight.
  {
    const h = harness();
    h.sel.value = "ollama"; h.setAiBackend("ollama");
    await settle(h);
    h.sel.value = "vllm"; h.setAiBackend("vllm");
    await settle(h);
    h.release("/api/settings");                // first save lands (stored = ollama)
    await settle(h);
    h.release("/api/llm/backend");             // ITS reload answers "ollama" while the second save is pending
    await settle(h);
    assert.strictEqual(h.sel.value, "vllm", "the first save's reload wrote the older value");
    h.release("/api/settings");                // second save lands (stored = vllm)
    await settle(h);
    while (h.pending.length) h.release("/api/llm/backend");
    await settle(h);
    assert.strictEqual(h.sel.value, "vllm");
  }
  // 2b. Two picks in the SAME tick, both saves landing before the first save's reload answers, and that
  // reload answering LAST with the value it saw (the first pick's): a landed save must invalidate it.
  {
    const h = harness();
    h.sel.value = "ollama"; h.setAiBackend("ollama");
    h.sel.value = "vllm"; h.setAiBackend("vllm");
    await settle(h);
    h.release("/api/settings");                // first save lands: its reload asks and sees "ollama"
    await settle(h);
    h.release("/api/settings");                // second save lands: its reload asks and sees "vllm"
    await settle(h);
    h.sel.value = "auto";                      // moved by something else: only a FRESH reload may write it back
    h.releaseNth("/api/llm/backend", 1);       // the SECOND reload answers first ("vllm")
    await settle(h);
    assert.strictEqual(h.sel.value, "vllm", "the second reload (fresh) must write the stored value");
    h.releaseNth("/api/llm/backend", 0);       // the first reload answers last ("ollama"): stale, must leave the select alone
    await settle(h);
    assert.strictEqual(h.sel.value, "vllm", "the first save's reload, answering last, wrote the older value");
  }
  // 2c. One pick, and ANOTHER load (a refresh of the panel, or opening the AI subtab) started before the
  // save landed answers after the save's own reload with the old value.
  {
    const h = harness();
    h.sel.value = "ollama"; h.setAiBackend("ollama");
    await settle(h);
    h.loadAiBackendPanel();                    // the refresh: asks now and sees "auto"
    await settle(h);
    h.release("/api/settings");                // the save lands: its reload asks and sees "ollama"
    await settle(h);
    h.releaseNth("/api/llm/backend", 1);       // the save's reload answers first
    await settle(h);
    h.releaseNth("/api/llm/backend", 0);       // the refresh answers last with the old value
    await settle(h);
    assert.strictEqual(h.sel.value, "ollama", "a load that began before the save landed wrote the old value");
  }
  // 3. A refused save: the select honestly returns to what the server holds.
  {
    const h = harness();
    h.sel.value = "ollama"; h.setAiBackend("ollama");
    await settle(h);
    h.fail("/api/settings");
    await settle(h);
    h.release("/api/llm/backend");
    await settle(h);
    assert.strictEqual(h.sel.value, "auto", "a refused save must not leave a value the server never stored");
  }
  // 4. Nothing was picked: a load writes the select (the panel still reflects the server).
  {
    const h = harness();
    h.server.stored = "vllm";
    h.loadAiBackendPanel();
    await settle(h);
    h.release("/api/llm/backend");
    await settle(h);
    assert.strictEqual(h.sel.value, "vllm");
  }
  console.log("ai_backend_select_race: ok");
})().catch((e) => { console.error(e); process.exit(1); });
