// Row 361 group 9 (app-diagnostics.js), found by row 365's closure charge: the unattended-run status line and the
// field-data download line were written by a local say()/set() closure handed t()/tf() output, which the row 352
// scan could not see. They now go through ooLive (row 364), so a switch calls the kept render again. The helper
// here is reduced to "draw now, keep the render, redraw on switchTo"; its own behaviour is tested on the real code
// in oo_live_node_test.js.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function fnSource(name) {
  const m = new RegExp("(?:async\\s+)?function\\s+" + name + "\\s*\\(").exec(APP);
  assert.ok(m, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", m.index));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(m.index, j);
}

const SRC = [
  "let lang = 'en';",
  "const tr = (s) => lang === 'fr' ? 'FR[' + s + ']' : s;",
  "const OOI18N = { t: tr, tf: (s, v) => tr(s).replace(/\\{(\\w+)\\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)) };",
  "const window = { OOI18N };",
  "const kept = new Map();",
  "function ooLive(el, render) { if (!el) return; kept.set(el, render); el.textContent = String(render()); }",
  "function switchTo(l) { lang = l; kept.forEach((r, el) => { el.textContent = String(r()); }); }",
  "const els = {}; const $ = (id) => els[id] || null;",
  "let reply = null, fail = null;",
  "const api = async () => { if (fail) throw new Error(fail); return reply; };",
  "const ensureOnline = async () => true;",
  "const navigator = {};",
  "const setTimeout = (f) => f();",
  "const location = { port: '8000' };",
  "const FIELD_DATA_EXPORTS = [{ kind: 'file', url: '/x', name: 'a-{press}.json' }];",
  "let fetchFail = null;",
  "const fetch = async () => { if (fetchFail) throw new Error(fetchFail); return { ok: true, headers: { get: () => null }, blob: async () => ({}) }; };",
  "const _fieldSaveParts = async () => 2;",
  fnSource("unattendedStart"), fnSource("unattendedLog"), fnSource("downloadFieldData"),
  "module.exports = { unattendedStart, unattendedLog, downloadFieldData, switchTo, els,",
  "  set: (r, f) => { reply = r; fail = f; }, fetchFail: (m) => { fetchFail = m; } };",
].join("\n");

const mod = { exports: {} };
new Function("module", "require", SRC)(mod, require);
const H = mod.exports;
const el = (id) => (H.els[id] = { id, textContent: "", value: "", style: {}, focus() {}, select() {} });

(async () => {
  // 1. Arming: the decision line follows the switch; the server's reason stays as it came.
  H.switchTo("en");
  const st = el("unatt-status");
  H.set({ qualification: { started: false, reason: "no candidates" } }, null);
  await H.unattendedStart(null);
  assert.strictEqual(st.textContent, "Armed. Collecting · source qualification not started — no candidates");
  H.switchTo("fr");
  assert.strictEqual(st.textContent, "FR[Armed.] FR[Collecting] · FR[source qualification not started] — no candidates");
  H.set(null, "disk <full>");
  await H.unattendedStart(null);
  H.switchTo("en");
  assert.strictEqual(st.textContent, "Could not arm: disk <full>");

  // 2. The log: the hand-off line follows the switch (no clipboard here, so it says to copy by hand).
  el("unatt-log");
  H.set({ text: "log" }, null);
  await H.unattendedLog(null);
  assert.strictEqual(st.textContent, "Ready below — select and copy.");
  H.switchTo("fr");
  assert.strictEqual(st.textContent, "FR[Ready below — select and copy.]");

  // 3. The field-data line: the count is the one at the time it was drawn, in the language of the moment.
  H.switchTo("en");
  const out = el("field-data-status");
  await H.downloadFieldData(null);
  assert.strictEqual(out.textContent, "Done: 2 files.");
  H.switchTo("fr");
  assert.strictEqual(out.textContent, "FR[Done: 2 files.]");
  H.fetchFail("HTTP 500");
  await H.downloadFieldData(null);
  assert.strictEqual(out.textContent, "FR[Stopped after 0 files: HTTP 500]");
  H.switchTo("en");
  assert.strictEqual(out.textContent, "Stopped after 0 files: HTTP 500");

  console.log("diag_group9_switch_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
