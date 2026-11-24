// Row 361 group 10 (app-diagnostics.js): the chronology summary follows a language switch. The scanner cannot
// count it (the summary is built by a top-level function that translates inside itself), so this test is what
// holds it: _chronoRender marks the summary off the walker, and chronoRepaint -- called from app-boot's
// oo:langchange listener -- draws it again from the reading it holds, and only once a reading was drawn.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();
const BOOT = require("fs").readFileSync(require("path").join(__dirname, "..", "src", "static", "app-boot.js"), "utf8");

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
  "const window = { OOI18N, ooTimeline: null };",
  "const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;');",
  "const els = {}; const $ = (id) => els[id] || null;",
  "let _chronoData = null, _chronoTimer = null, _chronoReadAt = 0, draws = 0;",
  "const _chronoDur = (s) => String(s) + 's';",
  "const _chronoWhen = (iso) => iso || '—';",
  "const _chronoDraw = () => { draws++; };",
  "const setInterval = () => 1; const clearInterval = () => {};",
  fnSource("_chronoRender"), fnSource("_chronoSummaryHtml"), fnSource("chronoRepaint"),
  "module.exports = { _chronoRender, chronoRepaint, els, setLang: (l) => { lang = l; }, hold: (d) => { _chronoData = d; }, draws: () => draws };",
].join("\n");

const mod = { exports: {} };
new Function("module", "require", SRC)(mod, require);
const H = mod.exports;
const attrs = {};
const sum = H.els["chrono-summary"] = { innerHTML: "", children: [], setAttribute(k, v) { attrs[k] = v; } };

// 1. Nothing drawn yet: a switch draws nothing.
H.hold({ summary: { anchor_at: "2026-11-01" } });
H.chronoRepaint();
assert.strictEqual(sum.innerHTML, "", "a panel nobody opened stays as it is");

// 2. Drawn: marked off the walker; a switch redraws it in the new language, from the reading held.
const d = { summary: { anchor_at: "2026-11-01", wall_clock_s: 60, since_last_restart_s: 5 } };
H.hold(d);
H._chronoRender(d);
sum.children = [{}];
assert.strictEqual(attrs["data-i18n-dyn"], "", "the summary keeps out of the walker");
assert.ok(sum.innerHTML.includes(">Wall clock<"), sum.innerHTML);
H.setLang("fr");
H.chronoRepaint();
assert.ok(sum.innerHTML.includes(">FR[Wall clock]<") && sum.innerHTML.includes(">FR[Since the last restart]<"), sum.innerHTML);
assert.ok(sum.innerHTML.includes('id="chrono-since-restart">5s<'), "the live counter's span is drawn again");
assert.strictEqual(H.draws(), 2, "the timeline is redrawn with it");

// 3. The listener calls it.
assert.ok(/addEventListener\("oo:langchange"[\s\S]*chronoRepaint\(\)/.test(BOOT), "app-boot's listener calls chronoRepaint");

console.log("diag_group10_chrono_switch_node_test.js: OK");
