// The ONE country/language display helper — run as REAL code, not read as text.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Ruling Q302's note is the ruling: the CODE is displayed and the localised NAME is in
// the hover. A source-level guard cannot tell those two apart — `ooCountryCell` mentions
// both a code and a title whichever way round it puts them — so the helper is executed
// and the rendered HTML is what gets asserted. The four Q303 disclosures, the fail-closed
// refusals and the alpha-2 derivation are all behaviour, and behaviour is what this file
// reads.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function span(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

function constSpan(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const end = APP.indexOf("`;", at);
  assert.ok(end !== -1, name + " is not the backtick table this test expects");
  return APP.slice(at, end + 2);
}

// The real tables and the real functions. Nothing here is re-typed: a copy would agree
// with a broken shipped helper, which is the whole reason this harness extracts.
const src = [
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
    "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  // `ooRegionName`/`ooLangName` live in app-map.js and wrap Intl.DisplayNames. Stubbed
  // so the assertions read THIS helper's behaviour rather than the platform's CLDR
  // data — and stubbed to ECHO their input, so a test that expected a name would fail
  // loudly rather than silently reading a code back as if it were one.
  "function ooRegionName(code, fallback){ return 'NAME(' + String(code) + ')'; }",
  "function ooLangName(code, fallback){ return 'LNAME(' + String(code) + ')'; }",
  "const window = {};",
  constSpan("_OO_ISO3_TO_2_TEXT"),
  "const OO_ISO3_TO_ISO2 = {}; const OO_ISO2_TO_ISO3 = {};",
  "_OO_ISO3_TO_2_TEXT.split(/\\s+/).forEach((p)=>{if(!p)return;const[a,b]=p.split(':');" +
    "if(!a||!b)return;OO_ISO3_TO_ISO2[a]=b;OO_ISO2_TO_ISO3[b]=a;});",
  constSpan("_OO_ISO1_TO_3_TEXT"),
  "const OO_LANG1_TO_3 = {}; const OO_LANG3_TO_1 = {};",
  "_OO_ISO1_TO_3_TEXT.split(/\\s+/).forEach((p)=>{if(!p)return;const[a,b]=p.split(':');" +
    "if(!a||!b)return;OO_LANG1_TO_3[a]=b;OO_LANG3_TO_1[b]=a;});",
  // Through OO_CLDR_WRONG_ABOUT, not only through OO_COUNTRY_ALIASES: the override
  // table is what keeps the `an` hover from saying Curaçao, and a slice that stopped
  // one declaration short left `ooCountryName` throwing on it.
  APP.slice(APP.indexOf("const OO_SPECIAL_ALPHA3 = "),
            APP.indexOf("\n", APP.indexOf("const OO_CLDR_WRONG_ABOUT = "))),
  span("ooCountryAlpha2"),
  span("ooCountryCode"),
  span("ooCountryKind"),
  span("ooCountryName"),
  span("ooCountryTitle"),
  span("ooCountryCell"),
  span("ooCountryCompare"),
  span("ooCountryFlag"),
  span("ooLangBase"),
  span("ooLangCode"),
  span("ooLangStorage"),
  span("ooLangDisplayName"),
  span("ooLangCell"),
].join("\n") + "\n";

const F = new Function(src + "return {ooCountryAlpha2,ooCountryCode,ooCountryKind," +
  "ooCountryName,ooCountryTitle,ooCountryCell,ooCountryCompare,ooCountryFlag," +
  "ooLangCode,ooLangStorage,ooLangDisplayName,ooLangCell,OO_ISO3_TO_ISO2,OO_LANG1_TO_3};")();

// -- anti-vacuity: the tables really loaded ---------------------------------------- //
assert.strictEqual(Object.keys(F.OO_ISO3_TO_ISO2).length, 216,
  "the alpha-3 table did not parse -- every assertion below would pass for free");
assert.strictEqual(Object.keys(F.OO_LANG1_TO_3).length, 183,
  "the 639-1 table did not parse -- every language assertion below would pass for free");

// -- Q302, the ruling's own shape: CODE visible, NAME in the hover ------------------ //
const fr = F.ooCountryCell("fr");
assert.ok(/>FRA</.test(fr), "the alpha-3 code must be the VISIBLE text: " + fr);
assert.ok(/title="NAME\(fr\)"/.test(fr),
  "the localised name must be in the title, derived from the ALPHA-2: " + fr);
assert.ok(!/>France</.test(fr), "the NAME must not be the visible text (Q302's note): " + fr);

// The hover is derived from the alpha-2 whatever form the caller holds — the whole
// point of the derivation, and the case Intl.DisplayNames silently gets wrong.
assert.strictEqual(F.ooCountryName("FRA", ""), "NAME(fr)");
assert.strictEqual(F.ooCountryName("France", ""), "");   // a NAME is not a code: no alpha-2

// -- the two codes CLDR answers wrongly (the 2026-09-16 Chromium walk) ------------- //
// `ooRegionName` is stubbed here as NAME(x), so a name that came back as anything
// BUT "NAME(an)" proves the override was consulted BEFORE the CLDR lookup -- which is
// the whole fix: in a real browser that lookup returns "Curaçao" for AN, naming a
// different territory than the code means, and nothing about the shape of the answer
// would have told a reviewer.
assert.strictEqual(F.ooCountryName("an", ""), "Netherlands Antilles");
assert.strictEqual(F.ooCountryName("ANT", ""), "Netherlands Antilles");
assert.strictEqual(F.ooCountryName("int", ""), "International");
assert.strictEqual(F.ooCountryName("INT", ""), "International");
// eu/xk deliberately still go to CLDR, which names both correctly and localised.
assert.strictEqual(F.ooCountryName("eu", ""), "NAME(eu)");
assert.strictEqual(F.ooCountryName("xk", ""), "NAME(xk)");
// and the disclosure still rides beside the corrected name.
assert.ok(/Netherlands Antilles/.test(F.ooCountryTitle("an")),
  "the ANT hover must name the territory the code means");
assert.ok(/not an ISO code/.test(F.ooCountryTitle("an")),
  "and must still disclose that it is not an ISO code (Q303)");

// -- the code, from every form a caller legitimately holds -------------------------- //
assert.strictEqual(F.ooCountryCode("fr"), "FRA");
assert.strictEqual(F.ooCountryCode("FR"), "FRA");
assert.strictEqual(F.ooCountryCode("FRA"), "FRA");
assert.strictEqual(F.ooCountryCode("uk"), "GBR", "Q303: the law jurisdiction `uk` reads GBR");
assert.strictEqual(F.ooCountryCode("gb"), "GBR");
assert.strictEqual(F.ooCountryCode(""), "");
assert.strictEqual(F.ooCountryCode(null), "");

// -- Q303: the four non-ISO codes, and each one DISCLOSED --------------------------- //
const specials = { eu: "EUU", int: "INT", xk: "XKX", an: "ANT" };
Object.keys(specials).forEach((a2) => {
  const code = specials[a2];
  assert.strictEqual(F.ooCountryCode(a2), code);
  assert.strictEqual(F.ooCountryKind(a2), "non-iso", a2 + " must be disclosed as non-ISO");
  assert.ok(/not an ISO code/.test(F.ooCountryTitle(a2)),
    a2 + "'s hover must carry Q303's disclosure, got: " + F.ooCountryTitle(a2));
  assert.ok(/title="[^"]*not an ISO code[^"]*"/.test(F.ooCountryCell(a2)),
    a2 + "'s rendered cell must carry the disclosure in its title");
});
// The mirror: an ordinary ISO country must NOT be labelled non-ISO. Without this the
// disclosure could be printed on everything and every assertion above would still pass.
assert.strictEqual(F.ooCountryKind("fr"), "iso");
assert.ok(!/not an ISO code/.test(F.ooCountryTitle("fr")),
  "a real ISO country must not carry the non-ISO disclosure");
assert.strictEqual(F.ooCountryKind("gbr"), "iso");

// -- fail-closed: an aggregate is never a country, junk stays VISIBLE --------------- //
["HIC", "WLD", "XD", "Z4", "floop"].forEach((junk) => {
  assert.strictEqual(F.ooCountryKind(junk), "unresolved", junk + " must not read as a country");
  assert.ok(!/not an ISO code/.test(F.ooCountryTitle(junk)),
    junk + " is unreadable, not a disclosed non-ISO code -- those are different facts");
});
assert.strictEqual(F.ooCountryCode("WLD"), "WLD",
  "an unreadable value renders AS ITSELF -- never blanked, never a fabricated code");
assert.ok(/not a recognised country code/.test(F.ooCountryTitle("WLD")),
  "an unreadable code owes the reader a hover that says so");
// An ABSENT value and an UNREADABLE one are different facts and must render differently.
assert.strictEqual(F.ooCountryCell(""), "");
assert.strictEqual(F.ooCountryCell("", { empty: "—" }), "—");
assert.ok(F.ooCountryCell("WLD").length > 0, "an unreadable value still renders something");

// -- Q307: the flag is derived from the alpha-2, whatever form arrives -------------- //
assert.strictEqual(F.ooCountryFlag("fr"), F.ooCountryFlag("FRA"),
  "the flag must be the same whether the caller holds alpha-2 or alpha-3");
assert.strictEqual(F.ooCountryFlag("fr"), "\u{1F1EB}\u{1F1F7}");
assert.strictEqual(F.ooCountryFlag("int"), "\u{1F310}", "a non-ISO entity keeps the globe");
assert.strictEqual(F.ooCountryFlag("WLD"), "\u{1F310}");
assert.strictEqual(F.ooCountryFlag(""), "");

// -- Q308: pickers order by LOCALISED NAME, code as the secondary key --------------- //
// The stub names sort in alpha-2 order, so a comparator keyed on the CODE would put
// DEU before FRA and this assertion would fail — which is what makes it discriminating.
const ordered = ["us", "de", "fr"].sort(F.ooCountryCompare);
assert.deepStrictEqual(ordered, ["de", "fr", "us"],
  "order must follow the localised NAME (NAME(de) < NAME(fr) < NAME(us)), got " + ordered);

// -- Q306: the language code on screen, the name in the hover ----------------------- //
assert.strictEqual(F.ooLangCode("fr"), "fra");
assert.strictEqual(F.ooLangCode("en-US"), "eng", "a region subtag is not a different language");
assert.strictEqual(F.ooLangCode("de"), "deu", "639-2/T, not the bibliographic `ger`");
assert.strictEqual(F.ooLangCode("zh"), "zho", "639-2/T, not the bibliographic `chi`");
assert.strictEqual(F.ooLangCode("fra"), "fra", "an already-639-3 code passes through");
assert.strictEqual(F.ooLangCode("yue"), "yue", "a 639-3 code with no 639-1 passes through");
assert.strictEqual(F.ooLangStorage("fra"), "fr");
assert.strictEqual(F.ooLangStorage("yue"), "",
  "no two-letter answer exists -- refuse rather than invent a tag");
const lc = F.ooLangCell("fr");
assert.ok(/>fra</.test(lc), "the 639-2/3 code must be the visible text: " + lc);
assert.ok(/title="LNAME\(fr\)"/.test(lc),
  "the language name must be in the title, derived from the 639-1: " + lc);

// -- escaping: a value from a corpus reaches an attribute ---------------------------- //
const nasty = F.ooCountryCell('a"><script>x</script>');
assert.ok(!/<script>/.test(nasty), "a hostile stored value must not break out: " + nasty);

console.log("country_display_node_test.js: OK");
