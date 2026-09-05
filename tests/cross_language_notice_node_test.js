// The R1 cross-language disclosure, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Expansion changes WHICH articles match, so the ruling requires it stated on the
// surface, never silent. That makes the RENDER the honesty rail rather than a
// decoration -- a payload nobody draws is exactly the "machine-readable answer with no
// caller" dead end -- and there is no browser here, so it is driven in node instead.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace: a `{}` in a default parameter would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
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

// Shims the renderer reaches for. `esc` and `t` are the real shapes; OOI18N is absent,
// which is also the boot-time state, so this exercises the fallback path too.
const src = "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,"
  + "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n"
  + "var window = {};\n"
  + extract("_crossLangNotice") + "\n"
  + "module.exports = { _crossLangNotice };";
const { _crossLangNotice } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const EXPANDED = {
  expanded: true,
  caveat: "This search matched the concept in every language the ring covers.",
  terms: [{
    term: "climate", normalized: "climate", expanded: true,
    ring_id: "climate", concept: "climate", matched_language: "en",
    added_terms: ["climat", "klima"],
    by_language: { fr: ["climat"], de: ["klima"] },
  }],
};
const DECLINED = {
  expanded: false,
  caveat: "This search matched the concept in every language the ring covers.",
  terms: [{
    term: "strom", normalized: "strom", expanded: false, declined: "several-senses",
    senses: [{ ring_id: "electricity", concept: "electricity" },
             { ring_id: "river", concept: "river" }],
  }],
};

// 1. An expansion is NAMED, with its concept and its per-language members.
{
  const html = _crossLangNotice(EXPANDED, false);
  assert.ok(html.includes("climate"), "the typed term is not shown");
  assert.ok(html.includes("climat") && html.includes("klima"),
    "the per-language members are not shown -- the reader cannot see what was added");
  assert.ok(html.includes("fr:") && html.includes("de:"),
    "the breakdown does not say WHICH language each added word came from");
  assert.ok(/onclick="_anSetExpand\(false\)"/.test(html),
    "no way back to the literal term -- the ruling requires one click");
}

// 2. A REFUSAL still discloses. Silence here would make an ambiguous term look like an
//    ordinary unexpanded search, and the reader would never learn there was a choice.
{
  const html = _crossLangNotice(DECLINED, false);
  assert.ok(html.includes("strom"), "the declined term is not named");
  assert.ok(html.includes("electricity") && html.includes("river"),
    "the senses are not offered -- a decline with no choice attached is just silence");
  assert.ok(!/onclick="_anSetExpand\(false\)"/.test(html),
    "nothing was expanded, so there is nothing to narrow back from");
}

// 3. Narrowed: the state is stated, and the way BACK is offered. Without this the
//    reader can reach the literal term and never find their way out of it.
{
  const html = _crossLangNotice(null, true);
  assert.ok(html.length > 0, "narrowing is a state the reader chose -- say so");
  assert.ok(/onclick="_anSetExpand\(true\)"/.test(html), "no way back to the concept");
}

// 4. NEGATIVE SPACE: an ordinary search renders NOTHING. A notice on every search would
//    train the reader to ignore it, which costs exactly the searches it matters on.
{
  assert.strictEqual(_crossLangNotice(null, false), "", "a plain search must be silent");
  assert.strictEqual(_crossLangNotice({ expanded: false, terms: [] }, false), "",
    "an empty terms list must render nothing");
}

// 5. The data is ESCAPED. A ring member is config-sourced, but a term is user-typed and
//    reaches this renderer, so the notice must not become an injection surface.
{
  const html = _crossLangNotice({
    expanded: true, caveat: "",
    terms: [{ term: "<img src=x onerror=alert(1)>", expanded: true,
              ring_id: "r", concept: "<b>c</b>", added_terms: ["x"],
              by_language: { fr: ["<script>"] } }],
  }, false);
  assert.ok(!html.includes("<img src=x"), "the typed term was not escaped");
  assert.ok(!html.includes("<script>"), "a member term was not escaped");
  assert.ok(html.includes("&lt;img"), "escaping should keep the text, not drop it");
}

console.log("cross_language_notice_node_test: all assertions passed");

// ---------------------------------------------------------------- the omnibar half
//
// `search_omni` publishes `cross_language`, a per-row `via_ring` and a separate
// `cross_language_items` count, and until this landed NOTHING in the frontend read any
// of them -- the "machine-readable answer with no caller" dead end, in the feature whose
// own commit message names that trap. These drive the two pure helpers the palette uses.

// `OOI18N` is a real GLOBAL in the browser that `window.OOI18N` aliases, and the shipped
// guard is `window.OOI18N && OOI18N.tf` -- so the sandbox has to provide both, or the
// engine-present path throws a ReferenceError the browser would never see. `state` is the
// one object both names point at, so a test can swap the engine out and back.
// `OOI18N` is a real GLOBAL in the browser that `window.OOI18N` aliases, and the shipped
// guard is `window.OOI18N && OOI18N.tf` -- so the sandbox has to provide both, or the
// engine-present path throws a ReferenceError the browser would never see. ONE sandbox
// holds all three functions: two would each define that global, and the survivor would
// silently serve the other block's state.
const OMNI_SRC = "var state = { OOI18N: { t: (s) => s, tf: (f, v) => f.replace("
  + "/\\{(\\w+)\\}/g, (_m, k) => (v && v[k] != null ? String(v[k]) : '{' + k + '}')) },"
  + " open: () => {} };\n"
  + "var window = state;\n"
  + "Object.defineProperty(globalThis, 'OOI18N', {get: () => state.OOI18N});\n"
  + "var _omniLive = null;\n"
  + "function openCorpus() {}\nfunction showTab() {}\n"
  + extract("_omniTypedRows") + "\n"
  + extract("_omniCrossNote") + "\n"
  + extract("_omniItems") + "\n"
  + "module.exports = { _omniTypedRows, _omniCrossNote, _omniItems, state,"
  + " setLive: (d) => { _omniLive = d; } };";
const OMNI = (() => {
  const m = { exports: {} };
  new Function("module", "exports", OMNI_SRC)(m, m.exports);
  return m.exports;
})();

// The group total must be compared against the rows the reader TYPED. Three prefix hits
// out of four matches, plus two sibling rows, is the shape that used to hide the total.
{
  const g = {total: 4, items: [1, 2, 3, 4, 5], cross_language_items: 2};
  assert.strictEqual(OMNI._omniTypedRows(g), 3);
  assert.ok(g.total > OMNI._omniTypedRows(g),
    "the 'N matches in total' note must survive the sibling rows");
  // ...and a group with no siblings is unchanged.
  assert.strictEqual(OMNI._omniTypedRows({total: 9, items: [1, 2, 3]}), 3);
  assert.strictEqual(OMNI._omniTypedRows({}), 0);
}

// An expansion is named on the header; a refusal is named too, or a search that quietly
// matched LESS reads as an ordinary one.
{
  const note = OMNI._omniCrossNote(EXPANDED);
  assert.ok(note.includes("climate"), note);
  assert.ok(note.includes("also matched as the concept"), note);
  assert.ok(note.startsWith(" · "), "it is appended to an existing header");

  const declined = OMNI._omniCrossNote(DECLINED);
  assert.ok(declined.includes("denotes several concepts"), declined);

  // The negative space: an ordinary search carries no extra weight at all.
  assert.strictEqual(OMNI._omniCrossNote(null), "");
  assert.strictEqual(OMNI._omniCrossNote({terms: []}), "");
}

// Without the i18n engine there is no keyed frame to fill, so it discloses NOTHING
// rather than emitting a half-built sentence with a literal {term} in it.
{
  const saved = OMNI.state.OOI18N;
  OMNI.state.OOI18N = {t: (s) => s};   // t but no tf, the boot-time shape
  assert.strictEqual(OMNI._omniCrossNote(EXPANDED), "");
  OMNI.state.OOI18N = saved;
  assert.ok(OMNI._omniCrossNote(EXPANDED).includes("climate"), "restored");
}

// ------------------------------------------------------------------ and its WIRING
//
// The two helpers above being right says nothing about whether `_omniItems` USES them:
// a mutation blanking the header note, and one dropping the per-row label, both survived
// a helper-only suite. So drive the real row builder (the recorded "a test of a HELPER is
// not a test of its WIRING" lesson) with the module state it reads.

function omniRows(payload) {
  OMNI.setLive(Object.assign({q: "climate"}, payload));
  return OMNI._omniItems("climate");
}

const LIVE = {
  cross_language: EXPANDED,
  groups: [
    {kind: "articles", total: 12, items: [{article_id: 1, title: "A", url: "/a"}]},
    {kind: "keywords", total: 4, cross_language_items: 1, items: [
      {term: "climate", normalized_term: "climate", frequency: 9},
      {term: "climat", normalized_term: "climat", frequency: 3, via_ring: "climate"},
    ]},
  ],
};

{
  const rows = omniRows(LIVE);
  const art = rows.find((r) => r.label === "A");
  assert.ok(art.grp.includes("also matched as the concept"),
    "the ARTICLES header does not disclose the expansion: " + art.grp);

  const typed = rows.find((r) => r.label.startsWith("climate"));
  const sibling = rows.find((r) => r.label.startsWith("climat "));
  assert.ok(typed.grp.includes("also matched as the concept"),
    "the KEYWORDS header does not disclose the expansion: " + typed.grp);
  // The row the reader did NOT type says why it is here; the one they did says nothing.
  assert.ok(sibling.sub.includes("climat") && sibling.sub.includes("concept"), sibling.sub);
  assert.ok(!typed.sub.includes("concept"),
    "a prefix hit must not be labelled as a cross-language sibling: " + typed.sub);
  // O1 end to end: 4 matches, 1 of the 2 rows is a sibling, so 4 > 1 typed row and the
  // true total survives. With the padded count (2) the note would have 4 > 2 -- still
  // true here, so the discriminating case is the one below.
  assert.ok(typed.grp.includes("4"), typed.grp);
}

{
  // The discriminating shape for the padded-count bug: total 2, two typed rows and two
  // siblings. 2 > 2 is false, so the note is correctly absent; 2 > 4 would be too --
  // this pins the direction that DOES differ.
  const rows = omniRows({groups: [{kind: "keywords", total: 3, cross_language_items: 2,
    items: [
      {term: "climate", normalized_term: "climate"},
      {term: "climat", normalized_term: "climat", via_ring: "climate"},
      {term: "klima", normalized_term: "klima", via_ring: "climate"},
    ]}]});
  assert.ok(rows[0].grp.includes("3"),
    "3 prefix matches behind 1 typed row: the total must still be disclosed, "
    + "and the padded count (3 rows) would have hidden it -- got: " + rows[0].grp);
}

{
  // Negative space: an ordinary search carries no note on any header, and no row claims
  // a concept. An over-eager disclosure invents a widening that never happened.
  const rows = omniRows({groups: LIVE.groups.map((g) => Object.assign({}, g,
    {items: g.items.map((i) => { const c = Object.assign({}, i); delete c.via_ring; return c; })}))});
  rows.forEach((r) => {
    assert.ok(!r.grp.includes("concept"), "a plain search disclosed an expansion: " + r.grp);
    assert.ok(!(r.sub || "").includes("concept"), "a plain row claimed a concept: " + r.sub);
  });
}

console.log("omnibar disclosure: ok");
