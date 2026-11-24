// Row 361 group 7 (app-analysis.js): the advanced-search notes and the per-filter caveats follow
// a language switch. Each is drawn through ooLive (row 364), so the switch calls the kept render again. The
// helper here is reduced to "draw now, keep the render, redraw on switchTo"; its own behaviour is tested on the
// real code in oo_live_node_test.js.
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
  "let apiFail = null; const api = async () => { if (apiFail) throw new Error(apiFail); return {}; };",
  "let _advFacets = { near: { default: 5 } };",
  "const _advHistLoad = async () => {};",
  fnSource("_advSaveNearDefault"), fnSource("_advHistToggle"),
  "module.exports = { _advSaveNearDefault, _advHistToggle, switchTo, els, fail: (m) => { apiFail = m; } };",
].join("\n");

const mod = { exports: {} };
new Function("module", "require", SRC)(mod, require);
const H = mod.exports;
const el = (id, v) => (H.els[id] = { id, textContent: "", value: v == null ? "" : v });

(async () => {
  // 1. The NEAR default note: a tf() frame with the number as data, redrawn in the new language.
  H.switchTo("en");
  const note = el("an-adv-note"); el("adv-near-default", "8");
  await H._advSaveNearDefault();
  assert.strictEqual(note.textContent, "Saved: a NEAR without its own number now means 8 words.");
  H.switchTo("fr");
  assert.strictEqual(note.textContent, "FR[Saved: a NEAR without its own number now means 8 words.]");
  // 2. A failure keeps the server's words as data inside the translated frame.
  H.fail("disk full");
  await H._advSaveNearDefault();
  assert.strictEqual(note.textContent, "FR[Could not save: disk full]");
  H.switchTo("en");
  assert.strictEqual(note.textContent, "Could not save: disk full");
  // 3. Search history on/off: the closing line follows the switch.
  H.fail(null);
  await H._advHistToggle(true);
  H.switchTo("fr");
  assert.strictEqual(note.textContent, "FR[Search history is on. It stays on this machine.]");
  console.log("analysis_group7_switch_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });

