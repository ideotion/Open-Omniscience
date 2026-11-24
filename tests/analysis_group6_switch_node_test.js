// Row 361 group 6 (app-analysis.js): the Lead provenance panel, the article facet chips and the filter note follow
// a language switch. Each is drawn through ooLiveHtml (row 364), so the switch calls the kept render again. The
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
  "const OOI18N = { t: tr };",
  "const window = { OOI18N };",
  "const kept = new Map();",
  "function ooLiveHtml(el, render) { if (!el) return; kept.set(el, render); el.innerHTML = String(render()); }",
  "function ooLive(el, render) { if (!el) return; kept.set(el, render); el.innerHTML = String(render()); }",
  "function switchTo(l) { lang = l; kept.forEach((r, el) => { el.innerHTML = String(r()); }); }",
  "const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;');",
  "const famHue = () => '#123';",
  "const cardTypeLabel = (p) => tr('type ' + p);",
  "const ooLabelHtml = (a, b) => a + ': ' + b;",
  "const ooLangCell = (l) => '<i>' + esc(l) + '</i>';",
  "const _anCtlLabel = (label) => '<b>' + esc(label) + '</b>';",
  "const els = {}; const $ = (id) => els[id] || null;",
  "let _anArtFacetSel = { source: '', language: '' };",
  "let _anArtFacetData = { sources: [{ source_id: 7, name: 'Daily <News>', n: 3 }], languages: [{ language: 'fr', n: 2 }] };",
  fnSource("_anRenderProvenance"), fnSource("_anProvenanceHtml"),
  fnSource("_anRenderArtFacetChips"), fnSource("_anArtFacetChipsHtml"),
  "module.exports = { _anRenderProvenance, _anRenderArtFacetChips, switchTo, els };",
].join("\n");

const mod = { exports: {} };
new Function("module", "require", SRC)(mod, require);
const H = mod.exports;
const el = (id) => (H.els[id] = { id, innerHTML: "", hidden: true, style: { setProperty() {}, removeProperty() {} } });

// 1. The provenance panel: caveat, method and the plain trigger are redrawn in the new language; the card name is data.
H.switchTo("en");
const prov = el("an-prov");
H._anRenderProvenance({ card: "Spike <x>", producer: "spike", bucket: "trends", family: "Trends",
  caveat: "Early corpus", method: "Counted mentions", trigger: { plain: "A spike", math: [{ label: "Ratio", value: "3.2" }] } });
assert.strictEqual(prov.hidden, false);
assert.ok(prov.innerHTML.includes('<p class="card-caveat">Early corpus</p>'), "the caveat is visible, not behind a toggle");
H.switchTo("fr");
for (const s of ["FR[Early corpus]", "FR[Counted mentions]", "FR[A spike]", "FR[From this Lead]", "FR[Ratio]", "FR[type spike]"]) {
  assert.ok(prov.innerHTML.includes(s), s + " after the switch: " + prov.innerHTML);
}
assert.ok(prov.innerHTML.includes("Spike &lt;x&gt;"), "the card's name is data, escaped, never translated");
H._anRenderProvenance(null);
assert.strictEqual(prov.hidden, true);
assert.strictEqual(prov.innerHTML, "");

// 2. The facet chips: their labels and the Apply button follow the switch, drawn from the facets the list holds.
H.switchTo("en");
const chips = el("an-art-facets");
H._anRenderArtFacetChips();
assert.ok(chips.innerHTML.includes(">Apply filter</button>"));
H.switchTo("fr");
assert.ok(chips.innerHTML.includes(">FR[Apply filter]</button>"), chips.innerHTML);
assert.ok(chips.innerHTML.includes("<b>FR[source]</b>") && chips.innerHTML.includes("<b>FR[language]</b>"));
assert.ok(chips.innerHTML.includes("Daily &lt;News&gt;"), "a source name is data");

console.log("analysis_group6_switch_node_test.js: OK");
