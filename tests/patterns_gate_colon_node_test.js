// Settings -> Advanced -> Diagnostics: the Patterns gate's labels use the READER's colon
// (2026-09-27 re-walk U-7), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The labels were welded to an ASCII ": ", which is wrong in fr ("Taille du corpus : 453")
// and zh/ja ("语料库规模：453"); they go through the locale's own "{prefix}: {text}" frame
// now, like the At-rest panel beside them. EXTRACTED from the shipped modules.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
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

// Renders the gate with a stubbed locale whose "{prefix}: {text}" frame is `frame`.
function gate(frame, map) {
  const box = { innerHTML: "" }, state = { textContent: "" }, cb = { checked: false, disabled: false };
  const els = { "patterns-gate": box, "patterns-gate-state": state, "patterns-lens": cb };
  const src =
    "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
    "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}\n" +
    "const $ = (id) => els[id];\n" +
    "const fmtNum = (x) => String(x);\n" +
    "const window = { OOI18N: { t: (s) => (map[s] != null ? map[s] : s),\n" +
    "  tf: (s, v) => (s === '{prefix}: {text}' ? frame : s).replace(/\\{(\\w+)\\}/g, (m, k) => v[k]) } };\n" +
    "const OOI18N = window.OOI18N;\n" +
    "let _patternsGate = { corpus_articles: 453, corpus_bar: 100000, corpus_met: false,\n" +
    "  false_positive_rate: null, false_positive_bar: 0.05, can_flip: false, caveat: '' };\n" +
    extract("ooLabelHtml") + "\n" + extract("_renderPatternsGate") + "\n" +
    "_renderPatternsGate();";
  new Function("els", "map", "frame", src)(els, map, frame);
  return box.innerHTML;
}
const fr = gate("{prefix} : {text}", { "Corpus size": "Taille du corpus", "False-positive rate": "Taux de faux positifs" });
assert.ok(fr.includes("<span>Taille du corpus</span> : <b>453</b>"), "fr must use its own ' : ' (U-7): " + fr);
assert.ok(fr.includes("<span>Taux de faux positifs</span> : <span class=\"pill warn\">"), fr);
assert.ok(!/<\/span>: /.test(fr), "an ASCII colon is still welded on: " + fr);
const zh = gate("{prefix}：{text}", { "Corpus size": "语料库规模" });
assert.ok(zh.includes("<span>语料库规模</span>：<b>453</b>"), "zh must use the full-width colon: " + zh);
const en = gate("{prefix}: {text}", {});
assert.ok(en.includes("<span>Corpus size</span>: <b>453</b> / 100000"), en);

console.log("all assertions passed");
