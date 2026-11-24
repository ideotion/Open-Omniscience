// Row 361 group 8 (app-analysis.js): the synthesis window, the bulk translate/summary panel and its queue,
// and the custom-extractor panel follow a language switch. Each part is drawn through ooLive/ooLiveHtml
// (row 364), so the switch calls the kept render again. The helper here is reduced to "draw now, keep the
// render, redraw on switchTo, a null release lets go"; its own behaviour is tested on the real code in
// oo_live_node_test.js. What is tested HERE is that a redraw keeps what the reader did (ticks, the target
// language, the skip box, the extractor picked) and that no drawn part holds another one.
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
  "const _tfn = (s, v) => OOI18N.tf(s, v);",
  "const kept = new Map();",
  "function ooLive(el, render) { if (!el) return; if (render == null) { kept.delete(el); return; } kept.set(el, [render, false]); el.textContent = String(render()); }",
  "function ooLiveHtml(el, render) { if (!el) return; kept.set(el, [render, true]); el.innerHTML = String(render()); }",
  "function switchTo(l) { lang = l; kept.forEach(([r, h], el) => { if (h) el.innerHTML = String(r()); else el.textContent = String(r()); }); }",
  "const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;');",
  "const ooLabelHtml = (a, b) => a + ': ' + b;",
  "const ooLabelText = (a, b) => a + ': ' + b;",
  "const ooLangCell = (l) => '<i>' + esc(l) + '</i>';",
  "const ooIsoDate = (s) => s ? String(s).slice(0, 10) : '';",
  "const ooFetchedOffSiteNote = () => '';",
  "const ooSaidHtml = (o, f) => '<said>' + esc(o[f]) + '</said>';",
  "const els = {}; const $ = (id) => els[id] || null;",
  "let boxes = [];",
  "const document = { querySelectorAll: (q) => (q.indexOf(':checked') >= 0 ? boxes.filter((b) => b.checked) : boxes) };",
  "const _SYNTH_MAX = 2; let _synthBusy = false;",
  "const _synthT = () => OOI18N.t;",
  "const _uiLangName = () => 'English';",
  "let _bulkQueue = [], _bulkPaused = false;",
  "const _bulkSelLabel = (op) => tr(op);",
  "const _aiRuns = {}; const _aiProg = {};",
  fnSource("_synthSelectListHtml"), fnSource("_synthSelectIntroHtml"), fnSource("_bulkPanelHtml"),
  fnSource("_bulkQueueHtml"), fnSource("_bulkJobLine"), fnSource("_aiRunOptionsHtml"), fnSource("_aiProgSet"),
  "module.exports = { _synthSelectListHtml, _synthSelectIntroHtml, _bulkPanelHtml, _bulkQueueHtml, _aiRunOptionsHtml, _aiProgSet,",
  "  switchTo, tr, els, kept, setBoxes: (b) => { boxes = b; }, setQueue: (q, p) => { _bulkQueue = q; _bulkPaused = p; }, prog: _aiProg };",
].join("\n");

const mod = { exports: {} };
new Function("module", "require", SRC)(mod, require);
const H = mod.exports;
const el = (id, extra) => (H.els[id] = Object.assign({ id, textContent: "", innerHTML: "", value: "", checked: false }, extra || {}));

// 1. The synthesis list: a first draw ticks the most relevant; a redraw keeps the reader's own ticks.
H.switchTo("en");
const cands = { total: 5, results: [{ id: 1, title: "A" }, { id: 2, title: "" }, { id: 3, title: "C <x>" }] };
H.setBoxes([]);
let html = H._synthSelectListHtml(cands);
assert.strictEqual((html.match(/ checked /g) || []).length, 2, "the first two are pre-ticked");
assert.ok(html.includes('<span class="muted">(untitled)</span>'), "the untitled label is a key, not raw English");
H.setBoxes([{ value: "1", checked: false }, { value: "2", checked: false }, { value: "3", checked: true }]);
H.switchTo("fr");
html = H._synthSelectListHtml(cands);
assert.ok(/value="3" checked/.test(html) && !/value="1" checked/.test(html), "a redraw keeps the ticks on screen: " + html);
assert.ok(html.includes("FR[(untitled)]") && html.includes("C &lt;x&gt;"), "the title is data, escaped");
const intro = H._synthSelectIntroHtml(cands);
assert.ok(intro.includes("FR[showing the top 3 by search relevance]") && intro.includes("FR[Pick up to 2 articles."), intro);

// 2. The bulk panel: a fresh open starts from the defaults; a redraw keeps the target and the skip box.
H.switchTo("en");
html = H._bulkPanelHtml("translate", "an", true);
assert.ok(html.includes('value="English"') && html.includes('id="bulk-skip-an" checked'));
el("bulk-tgt-an", { value: "Deutsch" }); el("bulk-skip-an", { checked: false });
H.switchTo("fr");
html = H._bulkPanelHtml("translate", "an", false);
assert.ok(html.includes('value="Deutsch"') && !html.includes('id="bulk-skip-an" checked'), html);
assert.ok(html.includes("FR[Translate all matched articles]") && html.includes(">FR[Add to queue]</button>"));
html = H._bulkPanelHtml("translate", "an", true);
assert.ok(html.includes('value="English"'), "a fresh open does not inherit an earlier panel's entries");

// 3. The queue is drawn from the entries as last read, in the language of the moment.
H.setQueue([{ id: 4, op: "summarize", state: "done", stored: 3 }], false);
html = H._bulkQueueHtml();
assert.ok(html.includes("FR[Translation &amp; summary queue]") && html.includes("FR[Clear finished]"), html);
H.setQueue([], false);
assert.strictEqual(H._bulkQueueHtml(), "", "an empty queue draws nothing");

// 4. The extractor list keeps the reader's pick across a redraw; the progress render is kept per panel.
H.switchTo("en");
const usable = [{ id: 9, label: "People <p>", output_kind: "person" }];
html = H._aiRunOptionsHtml("an", usable);
assert.ok(html.includes('value="builtin" selected'), "the built-in is the default pick");
el("ai-run-pick-an", { value: "9", options: [{}, {}] });
H.switchTo("fr");
html = H._aiRunOptionsHtml("an", usable);
assert.ok(html.includes('value="9" selected') && !html.includes('value="builtin" selected'), html);
assert.ok(html.includes("FR[Built-in: AI keywords]") && html.includes("People &lt;p&gt;"));
const prog = el("ai-run-prog-an");
H.switchTo("en");
H._aiProgSet("an", () => H.tr("Processing") + " 1/4…");
assert.strictEqual(prog.innerHTML, "Processing 1/4…");
assert.strictEqual(typeof H.prog.an, "function", "the progress render is kept for the panel, so a reopened panel draws it");
H.switchTo("fr");
assert.strictEqual(prog.innerHTML, "FR[Processing] 1/4…", "the progress line follows the switch");

console.log("analysis_group8_switch_node_test.js: OK");
