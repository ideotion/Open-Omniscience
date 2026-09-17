// The cross-language LENS and the counts it draws, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// PR 1 shipped the disclosure; this is the half a reader can touch -- the literal
// toggle and the 40-form cap switch (Q503/Q504), the per-form counts (Q509) and the
// group-by-language view (Q508). Every function driven here is PURE or
// state-only-on-module-globals, which is why it can be driven at all: the honesty in
// this feature lives in what these renderers refuse to say, and a refusal is only real
// if something exercises it.
//
// EXTRACTED from the shipped modules rather than re-typed: a re-typed copy would pass
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

// The shims are the BOOT-TIME shapes on purpose: no OOI18N engine, no `ooLangCell`, no
// `fmtNum`. Every one of these renderers guards for exactly that, and a sandbox that
// supplied them would leave the guard untested -- which is the branch a reader on a
// slow first paint actually gets.
const NAMES = ["_anParseLens", "_anApplyLens", "_anLensSeed", "_anApplyLensSeed",
               "_anWriteLensToUrl", "_anSlug", "_anFormCountsHtml", "_anLangCell",
               "_anGroupRowsByLanguage", "_crossLangNotice"];
const src = "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,"
  + "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n"
  + "var window = {};\n"
  // `ooLangCell` is SHIMMED, not extracted: it is app-core's own Q302 renderer (the
  // 639-2/3 code visible, the localised name in the hover) with its own tests and its
  // own two code tables, and what is under test here is which of the three language
  // states a row is in -- not how a code is spelled. The shim keeps the value visible
  // so an assertion can find it.
  + "function ooLangCell(v){return '<span>' + esc(String(v == null ? '' : v)) + '</span>';}\n"
  // The lens state the shipped module holds as module-level `let`s. Declared here with
  // the SAME defaults the module declares, because "both on unless the reader said
  // otherwise" is itself one of the rulings under test.
  + "var _anExpand = true, _anCap = true, _anSenses = {};\n"
  + "var location = {search: '', pathname: '/', hash: ''};\n"
  + "var history = {replaceState: function (_s, _t, url) {\n"
  + "  const i = String(url).indexOf('?');\n"
  + "  location.search = i < 0 ? '' : String(url).slice(i);\n"
  + "}};\n"
  + NAMES.map(extract).join("\n") + "\n"
  + "function _setLens(e, c, s) { _anExpand = e; _anCap = c; _anSenses = s || {}; }\n"
  + "function _getLens() { return {expand: _anExpand, cap: _anCap, senses: _anSenses}; }\n"
  + "module.exports = {" + NAMES.join(", ") + ", _setLens, _getLens, location};";
const M = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();
const { _anParseLens, _anApplyLens, _anLensSeed, _anApplyLensSeed, _anWriteLensToUrl,
        _anSlug, _anFormCountsHtml, _anLangCell, _anGroupRowsByLanguage,
        _crossLangNotice, _setLens, _getLens } = M;

// ---------------------------------------------------------------- the lens, parsed

// 1. NEGATIVE SPACE, and the one that matters most: a URL with no lens in it returns
//    null rather than the default lens. The difference is not cosmetic -- the boot path
//    feeds this straight into the seed of the tab a deep link opens, so a `{}` here
//    would silently stamp "expansion on, cap on" over whatever that tab had saved.
{
  assert.strictEqual(_anParseLens(""), null, "an empty query string invented a lens");
  assert.strictEqual(_anParseLens("?corpus=1,2,3&label=x"), null,
    "an ordinary deep link invented a lens and would overwrite the tab's own");
}

// 2. Each control, read on its own. `expand=0` must not disturb the cap and vice versa:
//    they are separate questions ("every language" vs "every FORM of every language").
{
  assert.deepStrictEqual(_anParseLens("?expand=0"), {expand: false, cap: true, senses: {}});
  assert.deepStrictEqual(_anParseLens("?cap=0"), {expand: true, cap: false, senses: {}});
  assert.deepStrictEqual(_anParseLens("?expand=0&cap=0"),
    {expand: false, cap: false, senses: {}});
}

// 3. A pin round-trips, and a MALFORMED one is refused rather than guessed at. A ring id
//    may itself contain no colon but a TERM can, so the split is on the LAST one.
{
  const L = _anParseLens("?sense=climate:climate-change&sense=strom:electricity");
  assert.deepStrictEqual(L.senses, {climate: "climate-change", strom: "electricity"});
  assert.deepStrictEqual(_anParseLens("?sense=nocolon").senses, {},
    "a pair with no separator was accepted");
  assert.deepStrictEqual(_anParseLens("?sense=:ring").senses, {},
    "a pin with an empty term was accepted");
  assert.deepStrictEqual(_anParseLens("?sense=term:").senses, {},
    "a pin with an empty ring was accepted");
  assert.deepStrictEqual(_anParseLens("?sense=a:b:c").senses, {"a:b": "c"},
    "the term/ring split is not on the LAST colon");
}

// 4. THE ROUND TRIP, which is what Q504 actually asks for: what the writer puts in the
//    URL is what the reader gets back. Asserted through the SHIPPED writer, so a change
//    to either side that breaks the pair reddens here rather than in a browser.
{
  // Including a pin held WITH EXPANSION OFF: the URL is state, not a request, so the
  // sense the reader chose survives a share even while nothing is being expanded --
  // the same thing the tab's own seed does, because two persistence paths that disagree
  // about one piece of state is how a reload and a link start showing different searches.
  for (const want of [{expand: false, cap: true, senses: {}},
                      {expand: true, cap: false, senses: {}},
                      {expand: false, cap: false, senses: {climate: "climate-change"}}]) {
    _setLens(want.expand, want.cap, want.senses);
    M.location.search = "";
    _anWriteLensToUrl();
    assert.deepStrictEqual(_anParseLens(M.location.search), want,
      "a lens written to the URL did not read back as itself: " + M.location.search);
  }
}

// 4b. The DEFAULT lens writes NOTHING. A URL that spells out the defaults on every
//     search is noise a reader would copy into every link they share, and it would make
//     the "no lens here" case above unreachable in practice.
{
  _setLens(true, true, {});
  M.location.search = "?corpus=1,2";
  _anWriteLensToUrl();
  assert.ok(!/expand=|cap=|sense=/.test(M.location.search),
    "the default lens was written into the URL: " + M.location.search);
  assert.ok(M.location.search.includes("corpus=1"),
    "writing the lens destroyed the rest of the query string");
}

// ---------------------------------------------------------------- the lens, applied

// 5. IDEMPOTENCE. `loadAnalysis` applies the lens to the params every tab reads, and
//    `_articleQuery` applies it again to its own copy -- and `sense` is APPENDED, not
//    set. Without the clear-first this sends every pin to the server twice, which is the
//    kind of defect that produces a correct-looking page and a wrong one on the next
//    control the reader touches.
{
  // Expansion ON, because a pin is only SENT when something is being expanded -- with it
  // off there would be no `sense=` to double and the test would pass vacuously.
  _setLens(true, false, {climate: "climate-change"});
  const once = _anApplyLens(new URLSearchParams("query=climat")).toString();
  const twice = _anApplyLens(_anApplyLens(new URLSearchParams("query=climat"))).toString();
  assert.ok(once.includes("sense=") && once.includes("literal_cap=false"),
    "the fixture does not actually exercise a pin and a cap: " + once);
  assert.strictEqual(twice, once, "applying the lens twice changed the query");
  assert.strictEqual(once.split("sense=").length - 1, 1, "the pin was sent twice");
}

// 6. An ID-SEEDED corpus is an exact set with no term to widen, so NOTHING is sent --
//    sending it would offer a choice that does not exist.
{
  _setLens(false, false, {climate: "climate-change"});
  const q = _anApplyLens(new URLSearchParams("ids=1,2,3")).toString();
  // ... and with expansion ON too, which is the state that would actually append a pin.
  _setLens(true, false, {climate: "climate-change"});
  const q2 = _anApplyLens(new URLSearchParams("ids=1,2,3")).toString();
  assert.ok(!/expand=|literal_cap=|sense=|ui_lang=/.test(q2),
    "the lens rode an id-seeded corpus with expansion on: " + q2);
  assert.ok(!/expand=|literal_cap=|sense=|ui_lang=/.test(q),
    "the lens rode an id-seeded corpus: " + q);
}

// 7. Each control reaches the request under its OWN name, and only when it is OFF: the
//    server's defaults are the same as the reader's, so an untouched lens adds nothing.
{
  _setLens(true, true, {});
  assert.ok(!/expand=|literal_cap=/.test(_anApplyLens(new URLSearchParams("query=x")).toString()),
    "the default lens padded every request");
  _setLens(false, true, {});
  assert.ok(_anApplyLens(new URLSearchParams("query=x")).toString().includes("expand=false"));
  _setLens(true, false, {});
  assert.ok(_anApplyLens(new URLSearchParams("query=x")).toString().includes("literal_cap=false"));
}

// 8. A pin is meaningless with expansion OFF (nothing is expanded), so it rides inside
//    the same guard rather than being sent to be ignored.
{
  _setLens(false, true, {climate: "climate-change"});
  assert.ok(!_anApplyLens(new URLSearchParams("query=climat")).toString().includes("sense="),
    "a sense pin was sent with expansion off");
}

// 9. A TAB SEED written before the lens existed carries NEITHER key, and that must mean
//    the DEFAULT, not "off". `!== false` rather than truthiness is the whole difference,
//    and getting it wrong would silently narrow every saved tab in the workspace.
{
  _setLens(false, false, {x: "y"});
  _anApplyLensSeed(undefined);
  assert.deepStrictEqual(_getLens(), {expand: true, cap: true, senses: {}},
    "an absent lens seed did not restore the defaults");
  _anApplyLensSeed({});
  assert.deepStrictEqual(_getLens(), {expand: true, cap: true, senses: {}},
    "an empty lens seed was read as 'everything off'");
  _anApplyLensSeed({expand: false, cap: false, senses: {climate: "c"}});
  assert.deepStrictEqual(_getLens(),
    {expand: false, cap: false, senses: {climate: "c"}});
  // And the seed a tab persists is a COPY, not the live object -- otherwise two tabs
  // would share one sense map and a pick on either would silently apply to both.
  const seed = _anLensSeed();
  seed.senses.climate = "tampered";
  assert.strictEqual(_getLens().senses.climate, "c", "the tab seed aliases the live state");
}

// ---------------------------------------------------------------- the language column

// 10. THREE STATES, kept apart because they are three different facts. The one that
//     would be easiest to get wrong is the third: a blank cell in a Language column
//     reads as the reader's own language, which is a claim the article never made.
{
  assert.ok(_anLangCell({language: "fr"}).includes("fr"), "an asserted language is not shown");
  const ded = _anLangCell({detected_language: "de"});
  assert.ok(ded.includes("de"), "a deduced language is not shown");
  assert.ok(ded.includes("deduced"), "a deduced language is presented as the source's own claim");
  assert.ok(ded.includes("title="), "the deduced caveat is not carried in the hover");
  assert.strictEqual(_anLangCell({}).includes("—"), true, "an unknown language rendered blank");
  assert.strictEqual(_anLangCell(null).includes("—"), true, "a null article rendered blank");
  // An ASSERTED language is never dressed as deduced, even when both fields are present.
  assert.ok(!_anLangCell({language: "fr", detected_language: "de"}).includes("deduced"),
    "an asserted language was labelled deduced");
}

// 11. Grouping is a VIEW: every row that went in comes out, exactly once. A grouper that
//     drops or duplicates a row changes what the reader believes matched, while the
//     total above it goes on saying something else.
{
  const items = [{language: "fr"}, {language: "en"}, {language: "fr"}, {}, {detected_language: "en"}];
  const rows = items.map((_a, i) => `<tr id="r${i}"></tr>`);
  const html = _anGroupRowsByLanguage(items, rows);
  for (let i = 0; i < rows.length; i++) {
    assert.strictEqual(html.split(`id="r${i}"`).length - 1, 1,
      `row ${i} does not appear exactly once in the grouped view`);
  }
  // DESCENDING count, so the reader meets the languages this corpus actually carries
  // first. en has 2 (one asserted, one deduced) and fr has 2, so the tie breaks
  // alphabetically -- deterministic, because two runs over one corpus that disagree
  // about the order would read as the corpus having changed.
  assert.ok(html.indexOf(">en<") < html.indexOf(">fr<") || html.indexOf("en") < html.indexOf("fr"),
    "the tie between two equally-sized languages is not broken alphabetically");
  assert.ok(html.includes("Language not recorded"),
    "an article claiming no language was filed under a plausible one");
}

// 11b. The unrecorded bucket is its OWN, even when a language with the same row count
//      exists: the grouped view must never invent a language a row refuses to claim.
{
  const items = [{}, {language: "fr"}];
  const html = _anGroupRowsByLanguage(items, ["<tr id='a'></tr>", "<tr id='b'></tr>"]);
  assert.ok(html.includes("Language not recorded") && html.includes("fr"),
    "the unrecorded article was folded into a real language");
}

// ---------------------------------------------------------------- the per-form counts

// 12. AN UNMEASURED FORM IS NOT A ZERO. A 0 in this row reads as "this corpus carries
//     nothing in that language", which is a different fact from "this form could not be
//     counted" -- and the one the payload marks `unmeasured` precisely to avoid.
{
  const html = _anFormCountsHtml({
    forms: [{form: "climate", articles: 120, language: "en"},
            {form: "klima", unmeasured: "this form could not be counted", language: "de"}],
    measured_forms: 2, total_forms: 2, total: 140,
  });
  assert.ok(html.includes("climate") && html.includes("120"), "a measured form is not drawn");
  assert.ok(html.includes("klima"), "an unmeasured form was dropped from the list");
  assert.ok(!/klima<\/b>|klima[^<]*<b>\s*0/.test(html), "an unmeasured form was drawn as 0");
  assert.ok(html.includes("could not be counted"),
    "an unmeasured form carries no reason, so it reads as a zero with styling");
}

// 13. THE TOTAL IS LABELLED AS THE DISTINCT COUNT. The per-form figures OVERLAP, so a
//     bare total beside them invites the reader to add the forms up and find a
//     discrepancy they will read as a bug in the corpus rather than in the caption.
{
  const html = _anFormCountsHtml({
    forms: [{form: "a", articles: 5}, {form: "b", articles: 5}],
    measured_forms: 2, total_forms: 2, total: 7,
    caveat: "These figures overlap: an article carrying two forms is counted under each.",
  });
  assert.ok(html.includes("counted once each"), "the total is not marked as the distinct count");
  assert.ok(html.includes("overlap"), "the payload's overlap caveat is not carried");
}

// 14. WHEN THE CAP BIT, the measured list says so. Without it the reader reads a partial
//     list as the whole concept, which is the exact anti-capping rule: the cap may bound
//     which forms were SEARCHED and may never bound a number presented as a total.
{
  const capped = _anFormCountsHtml({
    forms: [{form: "a", articles: 1}], measured_forms: 40, total_forms: 119, total: 900,
  });
  assert.ok(capped.includes("40") && capped.includes("119"),
    "a capped count does not say how many forms the concept actually has");
  const whole = _anFormCountsHtml({
    forms: [{form: "a", articles: 1}], measured_forms: 3, total_forms: 3, total: 9,
  });
  assert.ok(!/of\s*3\s*forms/.test(whole),
    "an uncapped count still hedges, which trains the reader to ignore the hedge");
}

// 15. NEGATIVE SPACE and escaping. A ring member is config-sourced but the endpoint
//     echoes the reader's own term, so this must not become an injection surface.
{
  assert.ok(_anFormCountsHtml(null).includes("No forms"), "a null payload rendered nothing");
  assert.ok(_anFormCountsHtml({forms: []}).includes("No forms"), "an empty list rendered nothing");
  const html = _anFormCountsHtml({forms: [{form: "<img src=x onerror=alert(1)>", articles: 1}]});
  assert.ok(!html.includes("<img src=x"), "a form was not escaped");
  assert.ok(html.includes("&lt;img"), "escaping should keep the text, not drop it");
}

// ---------------------------------------------------------------- the cap switch

// 16. Q503's NOTE, both ways round -- and NEVER both at once. The payload reports
//     `capped` only when a cap actually bit, so the sentence offering to lift it comes
//     from the payload and the one offering to restore it comes from the reader's own
//     lens; drawing both would tell the reader the search is simultaneously limited and
//     not limited.
{
  const CAPPED = {expanded: true, caveat: "", capped: true, cap: 40,
    cap_caveat: "The search was widened to the most-mentioned forms only.",
    terms: [{term: "covid", normalized: "covid", expanded: true, concept: "covid-19",
             by_language: {en: ["coronavirus"]}}]};
  const html = _crossLangNotice(CAPPED, false, false);
  assert.ok(/onclick="_anSetCap\(false\)"/.test(html), "a capped search offers no way to lift it");
  assert.ok(html.includes("most-mentioned forms"), "the cap is applied and never mentioned");
  assert.ok(!/onclick="_anSetCap\(true\)"/.test(html), "both cap sentences were drawn at once");
}

// 17. With the cap OFF the payload says nothing, so the way BACK has to come from the
//     lens. Including on a term that touches no ring at all: without this branch a
//     reader who turned the cap off and then searched an ordinary word would have no
//     control on screen and no way to learn the lens was still set.
{
  const html = _crossLangNotice(null, false, true);
  assert.ok(/onclick="_anSetCap\(true\)"/.test(html),
    "with the cap off there is no way to restore it");
  assert.ok(!/onclick="_anSetCap\(false\)"/.test(html), "both cap sentences were drawn at once");
  // and the default state still renders NOTHING, so the rail stays worth reading.
  assert.strictEqual(_crossLangNotice(null, false, false), "", "a plain search must be silent");
}

// 18. Q509's TRIGGER is drawn for each expanded term, and it carries the slot id the
//     handler writes into. A trigger whose slot id the handler cannot reconstruct is a
//     button that silently does nothing -- so the id is passed, not re-derived.
{
  const html = _crossLangNotice({expanded: true, caveat: "", terms: [
    {term: "Climat", normalized: "climat", expanded: true, concept: "climate-change",
     by_language: {fr: ["climat"]}}]}, false, false);
  assert.ok(html.includes("an-xforms-" + _anSlug("climat")),
    "the per-form counts have no slot to render into");
  assert.ok(/_anFormCounts\(&quot;Climat&quot;, &quot;climat&quot;\)/.test(html),
    "the count trigger does not carry the slot key, so it must guess it back");
}

// 19. The slug is DOM-id-safe for a term in any script -- the feature exists for Arabic,
//     Japanese and Hindi readers, so an id built from their terms has to work.
{
  for (const term of ["مناخ", "気候", "जलवायु", "climate change", "a:b", ""]) {
    const s = _anSlug(term);
    assert.ok(/^[A-Za-z0-9_-]*$/.test(s), `slug for ${term} is not id-safe: ${s}`);
  }
  assert.notStrictEqual(_anSlug("مناخ"), _anSlug("気候"), "two scripts collide on one id");
}

console.log("cross_language_lens_node_test: all assertions passed");
