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
  "var _NAMES = {fr: 'French', de: 'German', ar: 'Arabic', zh: 'Chinese', en: 'English', es: 'Spanish'};\n" +
  "function ooLangName(code, fb){ return _NAMES[code] || fb || code; }\n" +
  "var window = {}; var OOI18N;\n" +
  "function openLinkPreview(){}\n" +
  // Records what a sense pick opened (M4), so the test can read the pin it carried.
  "var _opened = [];\n" +
  "function openAnalysisFor(q, opts){ _opened.push({q: q, opts: opts}); }\n" +
  extract("_kwTf") + "\n" +
  extract("kwLangName") + "\n" +
  extract("kwTier") + "\n" +
  extract("kwLangBreakdownText") + "\n" +
  extract("uiLangCode") + "\n" +
  extract("_kwLangCells") + "\n" +
  extract("_kwScopeTail") + "\n" +
  extract("kwMentionLangs") + "\n" +
  extract("kwLangListName") + "\n" +
  extract("_kwLabelState") + "\n" +
  extract("kwLabelParts") + "\n" +
  extract("kwHoverText") + "\n" +
  extract("kwQidHtml") + "\n" +
  extract("kwHasTag") + "\n" +
  extract("kwTipExtraAttr") + "\n" +
  extract("kwSensePickerHtml") + "\n" +
  extract("kwSensesAfterHtml") + "\n" +
  extract("kwPickSense") + "\n" +
  extract("kwLabelHtml") + "\n" +
  "module.exports = { kwLabelHtml, kwTier, kwHoverText, kwSensePickerHtml, kwLangName, kwLangBreakdownText,\n" +
  // The UI language, as the browser sees it (`window.OOI18N` IS the global there): only
  // `current`, so every string still takes the un-i18n'd fallback path.
  "  kwLabelParts, kwMentionLangs, setUi: function (c) { OOI18N = window.OOI18N = {current: function () { return c; }}; },\n" +
  "  kwQidHtml, kwHasTag, kwTipExtraAttr, kwSensesAfterHtml, kwPickSense, opened: _opened };";
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

// --- THE QID CLICK STOPS AT THE QID (M9) ------------------------------------ //
// It sits inside keyword chips that are clickable themselves; without stopping the event
// the local preview opened AND the chip's own action ran behind it.
{
  const out = K.kwQidHtml({ translation_qid: "Q7590" });
  const m = out.match(/onclick='([^']*)'/);
  assert.ok(m, "the QID lost its handler: " + out);
  let stopped = 0, previewed = null;
  const handler = new Function("event", "openLinkPreview", m[1].replace(/&quot;/g, '"'));
  const ret = handler({ stopPropagation: () => { stopped++; } }, (u) => { previewed = u; });
  assert.strictEqual(stopped, 1, "the QID click still bubbles to the enclosing chip (M9)");
  assert.strictEqual(previewed, "https://www.wikidata.org/wiki/Q7590", "the local preview did not open");
  assert.strictEqual(ret, false, "the default (href='#') is not prevented");
}

// --- A LABEL DRAWN INSIDE A BUTTON NESTS NO BUTTON (M4) ---------------------- //
// The parser closes an outer <button> at the first nested one, which hoisted the sense
// buttons out of the analysis chip and left its count dangling.
{
  const wahl = {
    term: "Wahl", normalized: "wahl", translation_tier: "untranslated",
    translation_source_lang: "de", translation_declined: "several-senses",
    senses: [
      { ring_id: "election", concept: "election", translation: "élection" },
      { ring_id: "public_election", concept: "public election", translation: "élection" },
    ],
  };
  const inside = K.kwLabelHtml(wahl, { inButton: true });
  assert.ok(!/<button/.test(inside), "a label drawn inside a button still nests buttons: " + inside);
  assert.ok(/Several senses/.test(inside), "the refusal must still be stated inside the chip: " + inside);
  const after = K.kwSensesAfterHtml(wahl);
  assert.ok(/data-kwpin="wahl:election"/.test(after) && /data-kwpin="wahl:public_election"/.test(after), after);
  // ...and only for the row the inline label would have drawn a picker for.
  assert.strictEqual(K.kwSensesAfterHtml({ term: "x", translation_tier: "verified", translation: "y",
    senses: [{ ring_id: "a" }] }), "");
  // Two senses reading the same in the reader's language are told apart on the button.
  const labels = [...after.matchAll(/<button[^>]*>([^<]*)<\/button>/g)].map((m) => m[1]);
  assert.strictEqual(labels.length, 2, after);
  assert.notStrictEqual(labels[0], labels[1], "two senses still read identically (M4): " + labels);
  assert.ok(labels.every((l) => l.startsWith("élection")), labels);
  // A label shared by nobody stays the bare translation.
  const solo = K.kwSensePickerHtml({ normalized: "wahl", senses: [
    { ring_id: "election", concept: "election", translation: "election" },
    { ring_id: "voting", concept: "voting", translation: "voting" }] });
  assert.ok(/>election</.test(solo) && />voting</.test(solo), solo);
  // The sense the analysis lens already pinned stays pressed across a re-render.
  const pinned = K.kwSensesAfterHtml(wahl, { wahl: "public_election" });
  assert.ok(/data-kwpin="wahl:public_election" aria-pressed="true"/.test(pinned), pinned);
  assert.ok(/data-kwpin="wahl:election" aria-pressed="false"/.test(pinned), pinned);
}

// --- A PICK OPENS THE ANALYSIS WITH THE SENSE PINNED (M4) -------------------- //
{
  const buttons = [];
  const group = { querySelectorAll: () => buttons };
  const mk = (pin) => {
    const attrs = { "data-kwpin": pin, "aria-pressed": "false" };
    const b = {
      getAttribute: (k) => attrs[k], setAttribute: (k, v) => { attrs[k] = String(v); }, attrs,
      closest: () => group,
    };
    buttons.push(b);
    return b;
  };
  const b1 = mk("wahl:election"), b2 = mk("wahl:voting");
  b1.setAttribute("aria-pressed", "true");
  K.opened.length = 0;
  assert.strictEqual(K.kwPickSense(b2), true);
  assert.strictEqual(K.opened.length, 1, "a pick opened nothing -- the picker is a dead end again");
  const { q, opts } = K.opened[0];
  assert.strictEqual(q, "wahl");
  assert.deepStrictEqual(opts.lens.senses, { wahl: "voting" }, "the pin is not the term:ring_id the reader chose");
  assert.strictEqual(opts.lens.expand, true, "a pinned sense with expansion off would search nothing");
  assert.strictEqual(b2.attrs["aria-pressed"], "true");
  assert.strictEqual(b1.attrs["aria-pressed"], "false", "the previous pick is still marked pressed");
  // A malformed pin is refused, never guessed at.
  K.opened.length = 0;
  assert.strictEqual(K.kwPickSense(mk("no-colon")), false);
  assert.strictEqual(K.kwPickSense(mk(":election")), false);
  assert.strictEqual(K.opened.length, 0);
}

// --- THE TAG'S HOVER REACHES A KEYBOARD READER THROUGH THE ROW (M2) ---------- //
{
  const verified = { term: "software", normalized: "software", translation: "logiciel",
    translation_tier: "verified", translation_source_lang: "fr", translation_qid: "Q7397" };
  const attr = K.kwTipExtraAttr(verified);
  assert.ok(/^ data-oo-tip-extra="/.test(attr), attr);
  assert.ok(/Original: software/.test(attr) && /Q7397/.test(attr), "the tier hover is not on the row: " + attr);
  // No tag, no tier hover: only the breakdown the row carried before (or nothing).
  assert.strictEqual(K.kwTipExtraAttr({ term: "budget", translation_tier: "same_language",
    translation_source_lang: "en" }), "");
  assert.ok(/Across languages:/.test(K.kwTipExtraAttr({ term: "x", translation_tier: "same_language",
    language_breakdown: { fr: 3, de: 1 } })));
  assert.strictEqual(K.kwHasTag({ term: "x", translation_tier: "untranslated" }), false,
    "a term whose language nobody measured draws no tag, so it claims no tag hover either");
}

// --- A LABEL INSIDE A LINK LEAVES ITS QID FOR AFTER THE LINK (M7) ----------- //
// The trend rows, the Home trends and the term lists draw the label inside an <a>. The
// QID is an anchor of its own, and a nested anchor closes the outer one early, so the
// rest of the row (the count, the bar) fell out of the link. `inLink` leaves the QID out
// for the caller to draw after its closing tag; the tag and the translation stay.
{
  const verified = { term: "software", normalized: "software", translation: "logiciel",
    translation_tier: "verified", translation_source_lang: "fr", translation_qid: "Q7397" };
  const inLink = K.kwLabelHtml(verified, { inLink: true });
  assert.ok(!/<a\b/.test(inLink), "a label drawn inside a link still nests an anchor: " + inLink);
  assert.ok(/>logiciel</.test(inLink) && /translated from French/.test(inLink), inLink);
  assert.ok(/class="kw-qid"/.test(K.kwLabelHtml(verified)), "the default label lost its QID");
}

// --- A SPLIT KEYWORD IS NOT CALLED FOREIGN (M11) ---------------------------- //
// Keys are language-agnostic (Q416), so one keyword holds English "software" AND Spanish
// "software"; its `translation_source_lang` is the MAJORITY, and the label used to tag the
// English word "in Spanish" in the English UI. The server now measures the row's OWN
// mentions (`mention_languages`) and the label must name the split instead -- or, when the
// reader's language is the only one, draw no tag at all.
{
  K.setUi("en");
  const split = { term: "software", normalized: "software", translation_tier: "untranslated",
    translation_source_lang: "es", mention_languages: { en: 36, es: 27 },
    language_counts_scope: "corpus" };
  const out = K.kwLabelHtml(split);
  assert.ok(!/>in es</.test(out) && !/in Spanish</.test(out),
    "a keyword used in the reader's own language is still tagged as foreign: " + out);
  assert.ok(/>in English and Spanish</.test(out),
    "the split is not named on the tag: " + out);
  assert.ok(/Mentions by language: \S+ 36 · \S+ 27 \(in your whole corpus\)/.test(out),
    "the hover does not carry the per-language counts WITH their scope: " + out);
  assert.strictEqual(K.kwHasTag(split), true);
  // The reader's language is the ONLY one measured: no tag, and no translation shown.
  const onlyUi = { term: "software", normalized: "software", translation: "programa",
    translation_tier: "verified", translation_source_lang: "es", mention_languages: { en: 12 } };
  const o2 = K.kwLabelHtml(onlyUi);
  assert.ok(/>software</.test(o2) && !/>programa</.test(o2),
    "a word only ever used in the reader's language was 'translated' into it: " + o2);
  assert.ok(!/kw-tag/.test(o2), "a word only in the reader's language still draws a tag: " + o2);
  assert.strictEqual(K.kwHasTag(onlyUi), false);
  // Another UI: the same split is foreign to a French reader, and translated from both.
  K.setUi("fr");
  const fr = Object.assign({}, split, { translation: "logiciel", translation_tier: "verified" });
  const o3 = K.kwLabelHtml(fr);
  assert.ok(/>logiciel</.test(o3), o3);
  // The list grammar is the UI language's own (CLDR ListFormat), not an English "and".
  assert.ok(/translated from English et Spanish/.test(o3),
    "the translation's tag names only the majority language: " + o3);
  // Without a measurement the label falls back to the ladder's one language, as before.
  K.setUi("en");
  const plain = K.kwLabelHtml({ term: "haushaltsdefizit", normalized: "haushaltsdefizit",
    translation_tier: "untranslated", translation_source_lang: "de" });
  assert.ok(/in German/.test(plain), plain);
}

// --- THE BREAKDOWN SAYS WHICH COUNT IT IS (M12) ------------------------------ //
{
  K.setUi("en");
  const windowed = K.kwLangBreakdownText({ language_breakdown: { fr: 7, de: 2, "?": 3 },
    language_counts_scope: "window", language_counts_days: 7 });
  assert.ok(/\(in the last 7 days\)$/.test(windowed), "a windowed breakdown does not say so: " + windowed);
  assert.ok(/Language not recorded 3/.test(windowed) && !/\? 3/.test(windowed),
    "an unrecorded mention language is printed as a bare '?': " + windowed);
  const day = K.kwLangBreakdownText({ language_breakdown: { fr: 1 },
    language_counts_scope: "window", language_counts_days: 1 });
  assert.ok(/\(in the last day\)$/.test(day), day);
  const whole = K.kwLangBreakdownText({ language_breakdown: { fr: 1 }, language_counts_scope: "corpus" });
  assert.ok(/\(in your whole corpus\)$/.test(whole), whole);
  // A country-narrowed read claims no scope rather than "the whole corpus".
  const narrowed = K.kwLangBreakdownText({ language_breakdown: { fr: 1 }, language_counts_scope: "country" });
  assert.ok(!/\(/.test(narrowed), narrowed);
}

console.log("keyword_label_node_test.js: OK");
