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
