// The dossier's country rails and its rail counter, rendered by the REAL renderer (0.8 row A,
// brief S08-01 S2/S3).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Mostly refusals: a statistics row shows no value; an election's date caveat is VISIBLE
// text, never only a hover; a rail with nothing says so instead of rendering empty; a country
// rail that is not joined says why by its code; the counter names how many joined rails had
// rows. EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-dossier.js"), "utf-8");

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = SRC.indexOf("(", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "(") depth++;
    else if (SRC[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = SRC.indexOf("{", i);
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}

const FNS = ["_dossierChannel", "_dossierRailName", "_dossierNotJoinedReason", "_dossierLaneAbsence",
             "passportLine", "_dossierRailBody", "_dossierRailSource", "_dossierRailCount", "_dossierTabsHtml", "_dossierRailPanel", "dossierHtml"];
const src =
  "function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;'); }\n" +
  "function ooCountryCode(c) { return String(c).toUpperCase(); }\n" +
  "function ooPlaceKind(k) { return {text: String(k || '')}; }\n" +
  FNS.map(extract).join("\n") + "\n" +
  "module.exports = {" + FNS.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();

const country = {iso2: "fr", iso3: "FRA"};
const WINDOW = "The exact day is not yet set — only the legal window is known. Confirm at the official source.";
const d = {
  qid: "Q142", lang: "en", item: {label: "France", description: "country"},
  routes: {}, passport: {articles: 0, sources: 0, countries: 0, languages: 0},
  rails: [
    {key: "news", joined: true, articles: 0, by_channel: {}},
    {key: "places", joined: true, count: 1, places: [{id: "relation/1", name: "France", kind: "country", country: "fr", articles: 0}]},
    {key: "stats", joined: true, country, count: 30, series: [
      {agency: "worldbank", series_id: "SP.POP.TOTL", ref_area: "FRA", periods: 64, first: "1960", last: "2023", fetched: "2026-11-02T00:00:00Z"}]},
    {key: "climate", joined: true, country, count: 0, series: [], licences: {}},
    {key: "agenda", joined: true, country, count: 1, events: [
      {title: "France — Projet de loi de finances (annual budget bill)", calendar: "economic", confirmed: false, next_occurrence: null, until_year: 2031}]},
    {key: "elections", joined: true, country, count: 1, events: [
      {title: "France — Presidential election 2027", calendar: "elections", confirmed: false, until_year: 2027,
       month: 4, date_confidence: "window", date_caveat: WINDOW}]},
  ],
  not_joined: [{key: "markets", joined: false, reason: "Market series are keyed by ticker symbol, not by a Wikidata item."}],
  availability: {joined: 6, with_rows: 4, rails_with_rows: ["places", "stats", "agenda", "elections"], rails_without_rows: ["news", "climate"]},
  method: "M", method_country: "This item is a country, so the rails keyed by country join too.", caveat: "C",
  article_ids: [],
};

const html = R.dossierHtml(d, t, tf);
const v = visible(html);

// The counter says how many joined rails had rows.
assert.ok(v.includes("4 of 6 joined rails have rows on this machine"), v);
// A statistics series is named with its periods and dates, and no value.
assert.ok(v.includes("SP.POP.TOTL") && v.includes("64 periods") && v.includes("1960 – 2023"), v);
assert.ok(!/67[\d.,]*/.test(v), "a value leaked: " + v);
assert.ok(v.includes("1 of 30 shown"), "a bounded list says how many it shows");
// An empty rail says so.
assert.ok(v.includes("No climate series stored for this country on this machine."), v);
// The election's caveat is visible text, in the caveat class, not only a hover.
assert.ok(v.includes(WINDOW), v);
assert.ok(/class="card-caveat small">[^<]*legal window/.test(html), html);
// An election's year and month are its date; another event's until_year (the year it stops)
// is never shown as its date.
assert.ok(v.includes("Presidential election 2027 2027-04"), v);
assert.ok(!v.includes("2031"), v);
// A confirmed:false event without its own caveat still reads as not confirmed.
assert.ok(v.includes("annual budget bill) not confirmed"), v);
// The country part of the method is shown when the item is a country.
assert.ok(v.includes("This item is a country"), v);

// A city: the country rails are named as not joined, with the reason keyed by its code.
const city = {...d, rails: d.rails.slice(0, 2), availability: {joined: 2, with_rows: 1}, method_country: null,
  not_joined: ["stats", "climate", "agenda", "elections"].map((k) => ({key: k, joined: false, code: "not-a-country", reason: "server words"}))};
const vc = visible(R.dossierHtml(city, t, tf));
assert.ok(vc.includes("Statistics Joined only for a country"), vc);
assert.ok(vc.includes("Elections Joined only for a country"), vc);
assert.ok(!vc.includes("server words"), "a known code shows the keyed words");
assert.ok(!vc.includes("This item is a country"), vc);
const vu = visible(R.dossierHtml({...city, not_joined: [{key: "stats", joined: false, code: "country-unconfirmed", reason: "server words"}]}, t, tf));
assert.ok(vu.includes("none of its names names the country its code says"), vu);

console.log("all checks passed");
