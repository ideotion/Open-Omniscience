// S04-06's ONE keyword label helper, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Q401 = a inverts the old grammar: the TRANSLATION becomes the visible term and a small
// "translated from French" tag follows it. What actually needs guarding is not that the
// function mentions the right fields -- a source assertion survives code that reads a
// field and throws it away (`const x = (false && row.translation)` keeps the substring) --
// but WHICH WORD ENDS UP ON SCREEN for each of the four tiers. So this drives it.
//
// The two refusals are the load-bearing half and neither is visible in a diff:
//   * an UNTRANSLATED term must show ITSELF, never a blank and never a tag claiming a
//     translation that does not exist;
//   * a term already in the reader's language must carry NO tag at all, because tagging
//     every native keyword would be noise over most of any corpus.
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

// ONE sandbox for every function under test: two `runInNewContext` blocks each defining
// the same global throw, and two that merely assign leave the earlier block silently
// reading the later block's state (the recorded app-*.js shared-scope trap).
const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}\n" +
  // `ooLangName` lives in app-map.js and resolves a code to a language NAME in the UI
  // locale through CLDR. Stubbed with a table that is deliberately NOT the identity, so
  // an assertion below can tell a rendered NAME from a rendered CODE -- with the identity
  // the two are indistinguishable and the Q402 claim would pass for free.
  "var _NAMES = {fr: 'French', de: 'German', ar: 'Arabic', zh: 'Chinese'};\n" +
  "function ooLangName(code, fb){ return _NAMES[code] || fb || code; }\n" +
  "var window = {};\n" +
  "function openLinkPreview(){}\n" +
  extract("_kwTf") + "\n" +
  extract("kwLangName") + "\n" +
  extract("kwTier") + "\n" +
  extract("kwHoverText") + "\n" +
  extract("kwQidHtml") + "\n" +
  extract("kwSensePickerHtml") + "\n" +
  extract("kwLabelHtml") + "\n" +
  "module.exports = { kwLabelHtml, kwTier, kwHoverText, kwSensePickerHtml, kwLangName };";
const K = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

// --- VERIFIED: the translation is the VISIBLE term, the original goes to the hover -- //
{
  const out = K.kwLabelHtml({
    term: "climat", normalized: "climat", translation: "climate",
    translation_tier: "verified", translation_source_lang: "fr",
    translation_source: "ring", translation_qid: "Q7942",
  });
  assert.ok(/>climate</.test(out), "the translation is not the visible term (Q401): " + out);
  assert.ok(!/>climat</.test(out), "the ORIGINAL is still rendered as the visible term: " + out);
  assert.ok(/translated from French/.test(out),
    "the 'translated from X' tag is missing, or printed the CODE instead of the NAME: " + out);
  assert.ok(!/translated from fr\b/.test(out), "the tag printed a language CODE (Q402 = a): " + out);
  assert.ok(/Original: climat/.test(out), "the original is not offered in the hover (Q401): " + out);
  assert.ok(/Q7942/.test(out), "the QID is not drawn (Q418 = a): " + out);
  assert.ok(/openLinkPreview/.test(out),
    "the QID does not open the LOCAL preview first (invariant #6): " + out);
}

// --- TENTATIVE: visible, marked, and attributed ---------------------------- //
{
  const out = K.kwLabelHtml({
    term: "Kanzleramt", normalized: "kanzleramt", translation: "chancellery",
    translation_tier: "tentative", translation_source_lang: "de",
    translation_source: "llm", translation_model: "m2",
  });
  assert.ok(/>chancellery</.test(out), out);
  assert.ok(out.includes("≈"), "the ~ marker is not VISIBLE on the surface: " + out);
  assert.ok(/kw-tentative/.test(out), "the tentative tier is not styled apart: " + out);
  assert.ok(/translated from German/.test(out), out);
  assert.ok(/Model: m2/.test(out), "a tentative claim is unattributed: " + out);
}

// --- UNTRANSLATED: shows ITSELF, tagged with what it is -------------------- //
{
  const out = K.kwLabelHtml({
    term: "haushaltsdefizit", normalized: "haushaltsdefizit",
    translation_tier: "untranslated", translation_source_lang: "de",
  });
  assert.ok(/>haushaltsdefizit</.test(out),
    "an untranslated keyword must still show itself (R7): " + out);
  assert.ok(/in German/.test(out), "an untranslated keyword is not tagged with its language: " + out);
  assert.ok(!/translated from/.test(out),
    "an untranslated term claims a translation it does not have: " + out);
}

// --- SAME LANGUAGE: no tag at all ------------------------------------------ //
{
  // FAITHFUL to what the server actually sends: `to_dict()` emits
  // `translation_source_lang` whenever the term has a language, and for a same-language
  // row that language is the reader's own. An earlier draft omitted it, so `srcName` was
  // empty and no tag could render for a reason unrelated to the tier -- the mutation that
  // tags same-language rows SURVIVED against that fixture.
  const out = K.kwLabelHtml({
    term: "budget", normalized: "budget", translation_tier: "same_language",
    translation_source_lang: "en",
  });
  assert.ok(/>budget</.test(out), out);
  assert.ok(!/kw-tag/.test(out),
    "a term already in the reader's language was tagged; that is noise, not information: " + out);
  assert.ok(!/translated|in German|in French/.test(out), out);
}

// --- SEVERAL SENSES: refuses, and OFFERS the choice ------------------------ //
{
  const out = K.kwLabelHtml({
    term: "Wahl", normalized: "wahl", translation_tier: "untranslated",
    translation_source_lang: "de", translation_declined: "several-senses",
    senses: [
      { ring_id: "election", concept: "election", translation: "election" },
      { ring_id: "voting", concept: "voting", translation: "voting" },
    ],
  });
  assert.ok(/>Wahl</.test(out), "the term itself must still be shown: " + out);
  assert.ok(/Several senses/.test(out), "the refusal is not stated: " + out);
  // A refusal that names a choice and offers no way to make it is the recorded dead end.
  assert.ok(/data-kwpin="wahl:election"/.test(out), "the picker offers no pin: " + out);
  assert.ok(/data-kwpin="wahl:voting"/.test(out), out);
  // ...and it offers them by what they READ AS, never by a bare ring id.
  assert.ok(/>election</.test(out) && />voting</.test(out),
    "the picker labels its options with ring ids rather than translations: " + out);
}

// --- THE WALKER MUST NEVER TRANSLATE A KEYWORD ----------------------------- //
// `i18n.js` translates any text node whose trimmed content EXACTLY matches a key, and it
// cannot tell chrome from data. A corpus containing the keyword "Language" or "Original"
// is one collision away from a fabricated term, so every span carrying a TERM opts out.
{
  for (const row of [
    { term: "Language", normalized: "language", translation_tier: "same_language" },
    { term: "climat", normalized: "climat", translation: "climate",
      translation_tier: "verified", translation_source_lang: "fr" },
    { term: "Original", normalized: "original", translation_tier: "untranslated",
      translation_source_lang: "de" },
  ]) {
    const out = K.kwLabelHtml(row);
    const spans = out.match(/<span class="kw-term"[^>]*>/g) || [];
    assert.strictEqual(spans.length, 1, "expected exactly one term span: " + out);
    assert.ok(/data-i18n-dyn/.test(spans[0]),
      "the term span does not opt out of the i18n walker -- a keyword matching a chrome "
      + "key would be silently translated as if it were chrome: " + out);
  }
}

// --- THE OLDER PAYLOAD SHAPE STILL RENDERS HONESTLY ------------------------ //
// An endpoint that has not yet been given `target_lang` sends no `translation_tier`.
// The helper must derive one rather than claim a tier nobody computed.
{
  assert.strictEqual(K.kwTier({ translation: "climate" }), "verified");
  assert.strictEqual(K.kwTier({ tentative: "chancellery" }), "tentative");
  assert.strictEqual(K.kwTier({}), "untranslated");
  assert.strictEqual(K.kwTier(null), "untranslated");
}

// --- A MISSING LANGUAGE NEVER PRINTS AN EMPTY TAG -------------------------- //
{
  const out = K.kwLabelHtml({ term: "x", normalized: "x", translation_tier: "untranslated" });
  assert.ok(!/kw-tag/.test(out), "an empty language rendered an empty tag: " + out);
  assert.strictEqual(K.kwLangName(""), "");
  assert.strictEqual(K.kwLangName(null), "");
}

console.log("keyword_label_node_test.js: OK");
