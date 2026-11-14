// The pattern lists, Who and the dismissed-cards button, run as REAL code (R685).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What these lists must NOT do is most of what they are:
//   * an item says what was measured, never a verdict ("fake", "manipulated", "propaganda"...);
//   * a value from the server (a source name, a phrase, a headline) is text, never markup;
//   * the count line says how many and when; the caveat is a VISIBLE line under it, and the method
//     and thresholds are one click away behind a real button that says whether it is open
//     (aria-expanded) and what it opens;
//   * an empty list says so, never an empty box;
//   * nothing is shown for a dismissed count of zero.
//
// The module is loaded as it ships (a stub document takes its two listeners), so a renamed
// or broken renderer fails here rather than in a browser.

"use strict";
const assert = require("assert");
const path = require("path");

global.window = {};
global.document = {addEventListener() {}};
const P = require(path.join(__dirname, "..", "src", "static", "app-patterns.js"));

const t = (s) => s;
const tf = (s, v) => String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m));
const VERDICT = /\b(fake|manipulat|propaganda|disinformation|misinformation|lie|lying|liar|bot|troll|coordinated|campaign|flood(ing)?|launder)/i;
let checks = 0;
function ok(cond, msg) { assert.ok(cond, msg); checks++; }

const XSS = "<img src=x onerror=alert(1)>";
const SAMPLES = {
  copypasta: {items: [{phrase: "the minister said " + XSS, n_words: 9, distinct_sources: 4, n_articles: 7, sources: ["a", "b", "c", "d"], article_ids: [1, 2, 3]}],
              min_sources: 3, k: 8, recent_days: 14},
  flooded_topic: {items: [{source: "Daily " + XSS, term: "port strike", share_now: 0.42, baseline_share: 0.05, recent_articles: 21, recent_total: 50, article_ids: [4]}],
                  z_min: 2.5, recent_days: 7, min_share: 0.1},
  headline_body_mismatch: {items: [{article_id: 9, title: "Shock " + XSS, lexical_div: 0.81}], d_min: 0.67, recent_days: 14},
  manufactured_emergence: {items: [{term: "zeta-x", recent_articles: 12, recent_sources: 5, prior_count: 0, anchored: false, article_ids: [5, 6]}],
                           min_sources: 3, recent_days: 7, prior_days: 90},
  recycled_claim: {clusters: [{recent_title: "Old news", first_seen: "2025-01-02", resurfaced: "2026-11-01", gap_days: 668, distinct_sources: 2, n_articles: 3, article_ids: [7]}],
                   min_gap_days: 60, recent_days: 14, lookback_days: 365},
  source_laundering: {clusters: [{origin: "https://example.org/x", origin_domain: "example.org", distinct_sources: 12, n_articles: 30, source_names: ["a"], article_ids: [8]}],
                      min_sources: 3, min_articles: 3},
  disputed_chronology: {items: [{distinct_sources: 3, distinct_dates: 2, span_days: 4, n_articles: 3, sources: ["a", "b", "c"], article_ids: [10, 11]}],
                        lookback_days: 30, min_sources: 2, tolerance_days: 2},
  story_propagation: {items: [{term: "heatwave", distinct_sources: 6, span_days: 5, first_source: "Wire A", first_seen: "2026-11-02", n_articles: 9, article_ids: [12]}],
                      lookback_days: 21, min_sources: 3, min_span_days: 2},
};

// Every one of the eight routes has a sample here, and every sample renders one measured line.
ok(P.OO_PATTERNS.length === 8, "eight pattern lists");
for (const def of P.OO_PATTERNS) {
  const sample = SAMPLES[def.type];
  ok(sample, "a sample for " + def.type);
  const payload = Object.assign({method: "Counted.", caveat: "A shape, not a verdict.", computed_at: "2026-11-13T20:00:00+00:00"}, sample);
  const html = P.patternListHtml(def.type, payload, t, tf);
  const item = payload[def.key][0];
  const line = P.patternItemText(def.type, item, t, tf);
  ok(line && !/\{\w+\}/.test(line), def.type + ": every placeholder filled: " + line);
  ok(!VERDICT.test(line), def.type + ": an item states a measurement, never a verdict: " + line);
  ok(!html.includes("<img"), def.type + ": server text is escaped, never markup");
  ok(html.includes("1 found, computed 2026-11-13T20:00:00+00:00"), def.type + ": count and computed time on the count line");
  ok(/<button type="button" class="ghost tiny pat-how" aria-expanded="false" aria-controls="pat-how-/.test(html), def.type + ": the method control is a real, announced button");
  // The caveat is VISIBLE (never behind the toggle in the full UI); the button opens the method and thresholds.
  const region = html.slice(html.indexOf('role="region"'));
  ok(/<p class="card-caveat pat-caveat">A shape, not a verdict\.<\/p>/.test(html), def.type + ": the caveat is a visible line");
  ok(html.indexOf("A shape, not a verdict.") < html.indexOf('role="region"') && !region.includes("A shape, not a verdict."),
     def.type + ": the caveat sits before, never inside, the region the button hides");
  ok(region.includes("Counted."), def.type + ": the method is one click away, in the region the button opens");
  ok(/<ul class="hint pat-thresholds"><li>/.test(html), def.type + ": the thresholds the server applied are listed in words");
  const ids = P.patternItemIds(item);
  ok(ids.length > 0 && html.includes("Open " + ids.length + " articles"), def.type + ": each item opens its articles");
}
ok(P.patternItemText("source_laundering", SAMPLES.source_laundering.clusters[0], t, tf) === "12 sources (30 articles) cite the same origin: example.org",
   "the R685 example reads exactly as ruled");
// Headline vs body: the server lists an item when EITHER check passed; the line names the one that did.
const HB = {d_min: 0.67, sentiment_gap_min: 0.5};
ok(P.patternItemText("headline_body_mismatch", {title: "T", lexical_div: 0.3, sentiment_gap: 0.9}, t, tf, HB) ===
   "“T”: the headline's tone differs from the article body's (sentiment gap 0.9)", "a tone-only item never claims a word divergence");
ok(P.patternItemText("headline_body_mismatch", {title: "T", lexical_div: 0.8, sentiment_gap: 0.9}, t, tf, HB).includes("and its tone differs"),
   "both checks passed: both are said");
ok(P.patternItemText("headline_body_mismatch", {title: "T", lexical_div: 0.8, sentiment_gap: null}, t, tf, HB) ===
   "“T”: the headline's words are rare in the article body (divergence 0.8)", "a word-only item (or a non-English one) says only that");
// The "first N" note appears only where a limit was asked: the two signals routes take none.
const many = Array.from({length: 120}, () => ({distinct_sources: 2, distinct_dates: 2, span_days: 3, sources: ["a", "b"]}));
ok(!P.patternListHtml("disputed_chronology", {items: many}, t, tf).includes("Showing the first"), "no cap note on a list nobody capped");
ok(P.patternListHtml("copypasta", {items: Array.from({length: 100}, () => SAMPLES.copypasta.items[0])}, t, tf).includes("Showing the first 100."),
   "the cap note where the page asked for at most 100");
ok(P.patternItemText("flooded_topic", SAMPLES.flooded_topic.items[0], t, tf).includes("42% of its recent articles"), "shares are shown as percentages");

// An empty list says so; it is never an empty box.
const empty = P.patternListHtml("copypasta", {items: [], caveat: "c", computed_at: "2026-11-13T20:00:00+00:00"}, t, tf);
ok(empty.includes("0 found") && empty.includes("Nothing matches these thresholds in your corpus yet."), "an empty list says so");
// No computed time on the payload: the line says only the count, never an invented time.
const notime = P.patternListHtml("copypasta", {items: []}, t, tf);
ok(notime.includes("0 found") && !notime.includes("computed"), "no time is shown that the server did not send");
// An unknown threshold key is left out rather than printed raw.
ok(P.patternThresholds({weird_key: 3}, t, tf).length === 0, "unknown threshold keys are not printed");

// The Insights overview: every list named, its count or its state, and the button that opens it.
const ov = P.patternsOverviewHtml({copypasta: 3, flooded_topic: null}, t, tf);
ok(ov.includes("3 found") && ov.includes("could not be read") && ov.includes("Loading…"), "overview counts, failures and pending rows");
ok((ov.match(/data-pattern-list="/g) || []).length === 8, "every list has its button in the overview");

// Who: names are text, counts are counts, the caveat is visible as on the eight lists.
const who = P.whoListHtml({entities: [{name: "Ada " + XSS, "class": "person", articles: 4, mentions: 9}], caveat: "Deduced from text, never confirmed.",
  computed_at: "2026-11-13T20:00:00+00:00", min_articles: 1}, t, tf);
ok(!who.includes("<img") && who.includes("person · 4 articles · 9 mentions"), "who rows are escaped counts");
ok(who.includes('aria-controls="pat-how-who"') && who.includes('<p class="card-caveat pat-caveat">Deduced from text, never confirmed.</p>'), "who shows its caveat as a visible line");
ok(P.whoListHtml({entities: []}, t, tf).includes("No people or organisations found yet."), "an empty Who says so");

// The dismissed-cards button: nothing for zero, the count otherwise.
ok(P.briefDismissedHtml(0, t, tf) === "" && P.briefDismissedHtml(undefined, t, tf) === "", "no button when nothing is dismissed");
ok(P.briefDismissedHtml(3, t, tf).includes("Show 3 dismissed cards"), "the count of dismissed cards");

console.log("pattern lists: " + checks + " checks passed");
