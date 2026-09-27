// The 2026-09-27 click-through leftovers (batch B15), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What a source-level check cannot see: whether each fixed sentence goes through the
// translator ON ITS OWN (a joined caveat is a string no locale holds), whether the
// Insights header's counters survive being substituted into a translated frame, and
// whether an aggregate's English name is translated before the shared area cell reads
// it. A MARKING translator ("«…»") shows every string that went through it, so one that
// skipped it is visible. EXTRACTED from the shipped modules, never re-typed.

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

const mark = (s) => "«" + s + "»";
const tfMark = (s, v) => mark(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m));
const I18N = { t: mark, tf: tfMark };

const src = [
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}",
  "function ooCountryCode(c){return String(c||'').toUpperCase();}",
  "function _govIndicatorGrid(){return '<div class=\"grid\"></div>';}",
  extract("fmtNum"),
  extract("_govTf"),
  extract("_govAggHtml"),
  extract("_govGroupHtml"),
  extract("_statAreaLocal"),
  extract("_insStatusFrame"),
  extract("_insRemainingHtml"),
  "return { _govAggHtml, _govGroupHtml, _statAreaLocal, _insStatusFrame, _insRemainingHtml };",
].join("\n");
// Both the `window.OOI18N` and the bare `OOI18N` reads resolve (the node-harness trap).
const mod = new Function("window", "OOI18N", src)({ OOI18N: I18N }, I18N);

let n = 0;
function test(name, fn) { fn(); n++; console.log("ok  - " + name); }

// --- W15: the aggregate caveat is translated PART BY PART ------------------------- //
test("W15: each caveat part is its own key; the joined text is only a fallback", () => {
  const d = { code: "EUU", name: "European Union", as_of: "2026-08", indicators: [],
              caveat: "First. Second.", caveats: ["First.", "Second."] };
  const html = mod._govAggHtml(d);
  assert.ok(html.includes("«First.» «Second.»"), "the parts were not translated one by one: " + html);
  assert.ok(!html.includes("«First. Second.»"), "the joined string went through t(): " + html);
  // An older server sends only the joined text: it is shown as sent, never dropped.
  const old = mod._govAggHtml({ code: "EUU", name: "European Union", indicators: [], caveat: "Joined." });
  assert.ok(old.includes("Joined."), "the older shape lost its caveat: " + old);
});

// --- W8: the aggregate NAME is a key ------------------------------------------------ //
test("W8: the published aggregate's name reads in the UI language", () => {
  const html = mod._govAggHtml({ code: "EUU", name: "European Union", indicators: [], caveats: [] });
  assert.ok(html.includes("<strong>«European Union»</strong>"), html);
  const rows = [
    { ref_area: "EUU", area_kind: "aggregate", area_name: "European Union" },
    { ref_area: "FRA", area_kind: "country", area_name: null },
  ];
  const out = mod._statAreaLocal(rows);
  assert.strictEqual(out[0].area_name, "«European Union»");
  assert.strictEqual(out[1].area_name, null, "a country's absent name must stay absent");
  assert.strictEqual(rows[0].area_name, "European Union", "the payload was mutated in place");
  assert.deepStrictEqual(mod._statAreaLocal(undefined), [], "an absent list is an empty one");
});

// --- W16: a group's refusal reason is a key ---------------------------------------- //
test("W16: an unpopulated group's reason goes through the translator", () => {
  const html = mod._govGroupHtml({ group: { members: [], as_of: "2026-09" }, aggregate: null,
                                   reason: "Membership is not held." }, false);
  assert.ok(html.includes("«Membership is not held.»"), html);
});

// --- W17: the Insights header is a set of keyed frames around live counters -------- //
test("W17: the header frames are translated and keep the counters the tween writes to", () => {
  const s = { indexed_articles: 12345, total_articles: 20000, keywords: 2242, entities: 2, mentions: 31590 };
  const html = mod._insStatusFrame(s);
  for (const id of ["ins-n-indexed", "ins-n-total", "ins-n-keywords", "ins-n-entities", "ins-n-mentions",
                    "ins-pill", "ins-remaining"]) {
    assert.ok(html.includes(`id="${id}"`), id + " is gone: " + html);
  }
  assert.ok(html.includes('data-v="12345">12 345</span>'), "a counter skipped fmtNum: " + html);
  assert.ok(html.includes("articles indexed»") && html.includes("entities)»") && html.includes("mentions»"),
    "a frame skipped the translator: " + html);
  assert.ok(!/[\u0001-\u0005]/.test(html), "a marker was left in the page");
  assert.ok(html.startsWith("<span data-i18n-dyn>"), "the walker would cache the translated frame");
  // First paint: every counter starts at 0 so the tween grows it.
  assert.ok(mod._insStatusFrame(null).includes('data-v="0">0</span>'));
  assert.strictEqual(mod._insRemainingHtml({ remaining: 0 }), "");
  assert.strictEqual(mod._insRemainingHtml({ remaining: 1234 }), "· «<strong>1 234</strong> to index»");
});

console.log(`clickthrough B15 node suite: all assertions passed (${n})`);
