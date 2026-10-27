// The per-feed "Check" / "Import" buttons of the calendar directory, run as REAL code (invariant #14e's corollary).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Pressed in airplane mode, "Check" toasted a green "Checked." for a feed the kill switch never let anyone fetch. The server now answers
// `skipped_offline`; what is guarded here is what the handler DOES with it. EXTRACTED from the shipped module (a re-typed copy would
// pass while the real handler was broken).

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const at = APP.slice(at0 - 6, at0) === "async " ? at0 - 6 : at0;
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
  return APP.slice(at, j);
}

const S1 = "Airplane mode is on: nothing was fetched. Click the plane in the top bar to go online, then try again.";

function sandbox(reply) {
  const log = { toasts: [], calls: [], reloads: 0 };
  const api = async (path) => {
    log.calls.push(path);
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const src = ["function _bulT(s){return s;}", extract("feedAction"), "return { feedAction };"].join("\n");
  const f = new Function("api", "toast", "loadFeedDir", src);
  return { h: f(api, (m, k) => log.toasts.push([m, k || "ok"]), () => { log.reloads++; }), log };
}

(async () => {
  {
    const { h, log } = sandbox({ feed: "x", verdict: { status: "skipped_offline" }, skipped_offline: 1 });
    await h.feedAction("wph-hol-ad", "verify");
    assert.deepStrictEqual(log.toasts, [[S1, "warn"]], "a refused check is a warning, never 'Checked.'");
    assert.deepStrictEqual(log.calls, ["/api/events/feeds/wph-hol-ad/verify"]);
  }
  {
    const { h, log } = sandbox({ feed: "x", verdict: { status: "ok", events: 3 } });
    await h.feedAction("wph-hol-ad", "verify");
    assert.deepStrictEqual(log.toasts, [["Checked.", "ok"]], "an answered check reads exactly as before");
    assert.strictEqual(log.reloads, 1);
  }
  {
    const { h, log } = sandbox({ feed: "x", verdict: { status: "unreachable", error: "HTTP 503" } });
    await h.feedAction("wph-hol-ad", "verify");
    assert.deepStrictEqual(log.toasts, [["Checked.", "ok"]], "a real 'unreachable' is still a verdict the directory shows");
  }
  {
    const { h, log } = sandbox({ added: 4 });
    await h.feedAction("wph-hol-ad", "import");
    assert.deepStrictEqual(log.toasts, [["Imported.", "ok"]]);
  }
  {
    const { h, log } = sandbox(new Error("network kill switch is active -- collection stopped by operator"));
    await h.feedAction("wph-hol-ad", "import");
    assert.deepStrictEqual(log.toasts, [["network kill switch is active -- collection stopped by operator", "err"]], "an import refusal is already named (502)");
  }
  console.log("feed_verify_offline_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
