// A Lead's summary, method, caveat, ranking line and type chip read in the UI language
// (click-through re-walk 2026-09-27, defects L-1, L-2, N-8).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// EXTRACTED from the shipped UI engine, never re-typed: a copy would pass while the
// real renderer was broken. Driven with the REAL French locale file and the same
// t/tf semantics as src/static/i18n.js, and its OUTPUT is read -- the claim is "a
// reader in French sees French, with the data left as data", which no grep can prove.

"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = require("./app_source.js").appJs();
const FR = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "src", "static", "locales", "fr.json"), "utf-8"));

function fnSource(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in the UI engine -- renamed?");
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
function objLiteral(name) {
  const at = APP.indexOf("const " + name + " = {");
  assert.ok(at !== -1, name + " not found in the UI engine");
  const open = APP.indexOf("{", at);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j) + ";";
}

// i18n.js's t/tf, over one locale map.
function engine(map) {
  const t = (s) => (map[s] == null ? s : map[s]);
  const tf = (s, vars) => {
    if (s == null) return s;
    let out = map[s] == null ? s : map[s];
    if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) =>
      (vars[k] === undefined || vars[k] === null) ? m : String(vars[k]));
    return out;
  };
  return { t, tf };
}

function load({ map, lang, withI18n = true }) {
  const window = withI18n ? { OOI18N: engine(map) } : {};
  const document = { documentElement: { lang } };
  const fmtNum = (x) => "#" + x;              // proves numbers go through the app formatter
  const src = [
    objLiteral("_CARD_TYPE_LABELS"),
    fnSource("_cardMonthDay"), fnSource("_cardFrameVars"), fnSource("cardFrames"),
    fnSource("cardText"), fnSource("cardTitle"), fnSource("cardTypeLabel"),
    "return {cardText, cardTitle, cardFrames, cardTypeLabel};",
  ].join("\n");
  // eslint-disable-next-line no-new-func
  return new Function("window", "document", "fmtNum", "OOI18N", src)(
    window, document, fmtNum, window.OOI18N);
}

let passed = 0;
function check(name, fn) { fn(); passed++; console.log("ok -", name); }

const fr = load({ map: FR, lang: "fr" });

// The laundering card of L-1, as the producer ships it (numbers are numbers, names data).
const LAUNDER = {
  type: "source_laundering",
  title: "3 sources, one origin: origin.example",
  summary: "5 articles from 3 distinct sources (Alpha, Beta, Gamma) all cite the same origin — …",
  caveat: "Several sources citing the same single origin are NOT independent corroboration — …",
  method: "Outbound origins cited by >= 3 distinct sources …",
  i18n: {
    title: [{ t: "{n} sources, one origin: {origin}", v: { n: 3, origin: "origin.example" } }],
    summary: [{
      t: "{n} articles from {sources} distinct sources ({names}) all cite the same origin — "
        + "apparent corroboration that traces to ONE source. It may be a legitimate primary "
        + "source, or a single-origin claim dressed as consensus. Read the origin yourself.",
      v: { n: 5, sources: 3, names: "Alpha, Beta, Gamma" },
    }],
    method: [{
      t: "Outbound origins cited by >= {v1} distinct sources (and >= {v2} articles); "
        + "social/storefront/infrastructure origins excluded (CDNs, cookie/privacy-policy pages, "
        + "share widgets, license footers); at most one card per registrable origin domain. "
        + "Independence = distinct sources, not article count.",
      v: { v1: "3", v2: "3" },
    }],
  },
};

check("the laundering title, summary and method render in French, data kept", () => {
  const title = fr.cardTitle(LAUNDER);
  assert.strictEqual(title, "#3 sources, une seule origine : origin.example");
  const summary = fr.cardText(LAUNDER, "summary");
  assert.ok(summary.indexOf("Alpha, Beta, Gamma") !== -1, summary);
  assert.ok(summary.indexOf("#5") === 0, "a count must go through fmtNum: " + summary);
  assert.ok(summary.indexOf("apparent corroboration") === -1, "still English: " + summary);
  const method = fr.cardText(LAUNDER, "method");
  assert.ok(method.indexOf("Outbound origins") === -1, "still English: " + method);
  // an exact-spelling number travels as a string and is NOT reformatted
  assert.ok(method.indexOf(">= 3 ") !== -1 || method.indexOf("≥ 3") !== -1 || /\b3\b/.test(method), method);
  assert.ok(method.indexOf("#3") === -1, "a string var must keep its spelling: " + method);
});

check("a caveat with no frame (an older card) goes through t(): a keyed constant translates", () => {
  const caveat = Object.keys(FR).find(k => k.startsWith("Several sources citing the same single origin"));
  assert.ok(caveat && FR[caveat] !== caveat, "the laundering caveat must be keyed in fr.json");
  assert.strictEqual(fr.cardText({ caveat }, "caveat"), FR[caveat]);
});

check("an older card's sentence with data welded in stays English, never half-filled", () => {
  const s = "Only Alpha carried this; no other source published near-identical text.";
  assert.strictEqual(fr.cardText({ summary: s }, "summary"), s);
  assert.strictEqual(fr.cardText({}, "summary"), "");
});

check("a tr var is itself translated, an md var is this language's month and day", () => {
  const alert = { i18n: { title: [{
    t: "{tier}: {n} alert signal(s)", v: { tier: "Watch", n: 2 }, tr: ["tier"] }] } };
  assert.strictEqual(fr.cardTitle(alert), FR["{tier}: {n} alert signal(s)"]
    .replace("{tier}", FR.Watch).replace("{n}", "#2"));
  assert.notStrictEqual(FR.Watch, "Watch");
  const through = { i18n: { summary: [{
    t: "{n} articles in your corpus were published on {day} in earlier years ({first}–{last}).",
    v: { n: 4, day: "03-14", first: "2019", last: "2025" }, md: ["day"] }] } };
  const out = fr.cardText(through, "summary");
  assert.ok(out.indexOf("14 mars") !== -1, "month-day not localised: " + out);
  assert.ok(out.indexOf("2019–2025") !== -1, "years are data, never regrouped: " + out);
});

check("the ranking line renders from its frames", () => {
  const frames = [
    { t: "Ranked by a disclosed order (independent sources → sample magnitude → recency), never a score.", v: {} },
    { t: "This lead: {sources} independent source(s); n={n} (magnitude tier {tier}/{tiers}); freshest evidence {age} day(s) old.",
      v: { sources: 2, n: 12, tier: 1, tiers: 4, age: "0.5" } },
  ];
  const out = fr.cardFrames(frames);
  assert.ok(out.indexOf("Ranked by") === -1 && out.indexOf("This lead") === -1, out);
  assert.ok(out.indexOf("0.5") !== -1 && out.indexOf("#12") !== -1, out);
});

check("sentences join with a space, but not after a full-width stop", () => {
  const zh = load({ map: { "A.": "甲。", "B.": "乙。" }, lang: "zh" });
  assert.strictEqual(zh.cardFrames([{ t: "A.", v: {} }, { t: "B.", v: {} }]), "甲。乙。");
  assert.strictEqual(fr.cardFrames([{ t: "A.", v: {} }, { t: "B.", v: {} }]), "A. B.");
});

check("the type chip is a keyed label, and an unlisted type still shows its id", () => {
  assert.strictEqual(fr.cardTypeLabel("source_laundering"), FR["Source laundering"]);
  assert.notStrictEqual(FR["Source laundering"], "Source laundering");
  assert.strictEqual(fr.cardTypeLabel("brand_new_type"), "brand new type");
});

check("a producer's own title template still wins over the frames", () => {
  const c = { title: "E", title_i18n: "“{term}” is rising in your corpus", title_vars: { term: "x" },
    i18n: { title: [{ t: "Nope {n}", v: { n: 1 } }] } };
  assert.ok(fr.cardTitle(c).indexOf("x") !== -1 && fr.cardTitle(c).indexOf("Nope") === -1);
});

check("without the i18n engine every field is its English", () => {
  const bare = load({ map: FR, lang: "fr", withI18n: false });
  assert.strictEqual(bare.cardText(LAUNDER, "summary"), LAUNDER.summary);
  assert.strictEqual(bare.cardTitle(LAUNDER).indexOf("une seule origine"), -1);
});

console.log(passed + " checks passed");
