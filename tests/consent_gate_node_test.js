// R822: the consent gates fail CLOSED, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// ensureOnline and ensureAiEgress (app-core.js) are the gates every action that starts network activity awaits. Only an
// explicit yes (true) from the consent step lets the action start. A step that is missing, throws, or answers anything but
// true or false starts nothing, and the reader is told why; "Stay offline" (false) is the reader's own answer and is said
// by nothing. And a caller whose gate function is missing altogether (app-core.js not loaded) starts nothing either: the
// two resume buttons, which used to go ahead when the gate was missing, are run here with it missing and with it refusing.
//
// The functions are EXTRACTED from the shipped modules; only the consent step, the network and the toasts are stubs.

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at0 = APP.search(new RegExp("(?:async )?function " + name + "\\("));
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const start = APP.lastIndexOf("\n", at0) + 1;
  let i = APP.indexOf("(", at0), depth = 0;
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
  return APP.slice(start, j);
}

const SAID = "The network consent step did not complete, so nothing was started.";

// One gate with a stubbed consent step: `ask` is the step (a function, or undefined for "not loaded").
function gate(name, askName, ask) {
  const toasts = [];
  const src = (ask === undefined ? "" : `const ${askName} = __ask;\n`) + extract(name) + `\nreturn ${name};`;
  const fn = new Function("window", "toast", "__ask", src)({}, (m, k) => toasts.push([m, k]), ask);
  return { fn, toasts };
}

(async () => {
  for (const [name, askName] of [["ensureOnline", "_ensureOnlineAsk"], ["ensureAiEgress", "_ensureAiEgressAsk"]]) {
    const cases = [
      ["a yes", async () => true, true, 0],
      ["Stay offline", async () => false, false, 0],
      ["a step that throws", async () => { throw new Error("no dialog"); }, false, 1],
      ["a step that answers nothing", async () => undefined, false, 1],
      ["a step that answers a truthy non-yes", async () => "yes", false, 1],
      ["a step that answers 1", async () => 1, false, 1],
      ["a missing step", undefined, false, 1],
    ];
    for (const [what, ask, want, said] of cases) {
      const g = gate(name, askName, ask);
      const got = await g.fn("Do a thing", {});
      assert.strictEqual(got, want, `${name}: ${what} answers ${want}`);
      assert.strictEqual(g.toasts.length, said, `${name}: ${what} ${said ? "says why" : "says nothing"}`);
      if (said) assert.deepStrictEqual(g.toasts[0], [SAID, "err"]);
    }
    // A toast that throws still starts nothing.
    const fn = new Function("window", "toast", "__ask", `const ${askName} = __ask;\n` + extract(name) + `\nreturn ${name};`)(
      {}, () => { throw new Error("no toast"); }, async () => { throw new Error("x"); });
    assert.strictEqual(await fn("Do a thing", {}), false, name + ": a broken toast still starts nothing");
  }

  // The two resume buttons: a missing gate and a refusing gate each start nothing; a yes starts it.
  for (const [name, call] of [["jobResume", (f) => f("dump:en", false)], ["jobResumeQueue", (f) => f("direct")]]) {
    for (const [what, gateFn, starts] of [["missing", undefined, false], ["refusing", async () => false, false],
      ["throwing", async () => { throw new Error("x"); }, false], ["saying yes", async () => true, true]]) {
      const calls = [];
      const api = async (url, o) => { calls.push(url); return {}; };
      const f = new Function("window", "api", "toast", "_renderJobs", "__gate",
        (gateFn === undefined ? "" : "const ensureOnline = __gate;\n") + extract(name) + `\nreturn ${name};`)(
        {}, api, () => {}, () => {}, gateFn);
      let threw = false;
      try { await call(f); } catch (_e) { threw = true; }
      assert.strictEqual(calls.length > 0, starts, `${name} with the gate ${what} ${starts ? "starts" : "starts nothing"}`);
      if (!starts) assert.ok(!threw || what === "throwing", `${name} with the gate ${what} returns quietly`);
    }
  }
  console.log("consent_gate_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
