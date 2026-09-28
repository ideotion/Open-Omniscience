// The Claim Workspace's renderers, run as REAL code (gate row K, brief S05-11 S1).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What this view must NOT do is most of what it is, so most checks are refusals:
//
//   * no verdict and no score -- "true", "false", "verified", "credible", "score"... never
//     appear in what a reader sees, whatever the payload;
//   * a path with nothing joining it is "no shared origin found", never "independent";
//   * every built step prints its METHOD on the page (not only in a hover);
//   * steps ④ and ⑥ are shown in their place and say they are not built;
//   * the empty trail (no related article) still draws every step, and step ⑤ says what
//     WOULD be needed (the Socratic empty state), never a blank;
//   * articles open in the LOCAL reader (invariant #6), and a shared outbound URL is shown
//     as text, never as a bare external link;
//   * country and language go through the Q302 display helpers, never printed raw.
//
// EXTRACTED from the shipped modules rather than re-typed.

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
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf("\n    };\n", at) !== -1 && name.startsWith("_CLAIM")
    ? APP.indexOf("\n    };\n", at) + 7 : APP.indexOf(";\n", at) + 1);
}

const FNS = [
  "claimRef", "_claimStep", "_claimFacts", "_claimArticleLink", "claimRelatedHtml",
  "claimIndependenceHtml", "claimTimelineHtml", "_claimSilentHtml", "claimMissingHtml",
  "claimNotBuiltHtml", "claimWorkspaceHtml",
];
const src =
  extractConst("esc") + "\n" +
  "var window = {};\n" +
  "function ooCountryCell(v, o) { return '<span>CC(' + esc(v) + ')</span>'; }\n" +
  "function ooLangCell(v, o) { return '<span>LC(' + esc(v) + ')</span>'; }\n" +
  "function _omniCrossNote(c) { return c ? ' · CROSS(' + c.n + ')' : ''; }\n" +
  extract("ooLabelText") + "\n" + extract("ooListJoin") + "\n" +
  extractConst("_CLAIM_JOIN_LABELS") + "\n" +
  extractConst("_CLAIM_DISCRIMINATORS") + "\n" +
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

// A trail shaped like the backend's wire-echo fixture.
const WS = {
  claim: "Glacier melt in the Alps has doubled since 2000",
  query: { text: '"Glacier" OR "melt"', derived: true, terms: ["Glacier", "melt"], expanded: true },
  cross_language: { n: 1 },
  related: {
    total: 6, at_index_cap: false, shown: 3, limit: 3, ordering: "relevance",
    articles: [
      { id: 11, position: 1, title: "Alps glacier melt doubled", source: "Wire Desk", published_at: "2026-08-27T12:00:00", language: "en" },
      { id: 12, position: 2, title: "Study: Alpine ice loss", source: "Echo Times", published_at: "2026-08-28T12:00:00", language: "en" },
      { id: 13, position: 3, title: "Zurich glaciologists", source: "Alpine Review", published_at: null, language: "de" },
    ],
  },
  independence: {
    n_articles: 3, n_sources: 3, n_paths: 2, n_joined_paths: 1, n_unjoined: 1,
    paths: [
      { path: 1, article_ids: [11, 12], n_articles: 2, sources: ["Echo Times", "Wire Desk"], n_sources: 2, unjoined: false,
        joins: [{ kind: "same_wire", detail: "Reuters", article_ids: [11, 12] },
                { kind: "shared_link", detail: "https://journal.example/study", article_ids: [11, 12] }] },
      { path: 2, article_ids: [13], n_articles: 1, sources: ["Alpine Review"], n_sources: 1, unjoined: true, joins: [] },
    ],
  },
  timeline: [
    { id: 11, title: "Alps glacier melt doubled", source: "Wire Desk", published_at: "2026-08-27T12:00:00", wire: "Reuters",
      said: "Glacier melt in the Alps doubled.", country: "gb", language: "en", path: 1, first_in_corpus: true },
    { id: 12, title: "Study: Alpine ice loss", source: "Echo Times", published_at: "2026-08-28T12:00:00", wire: "Reuters",
      said: null, country: "au", language: "en", path: 1, first_in_corpus: false },
    { id: 13, title: "Zurich glaciologists", source: "Alpine Review", published_at: null, wire: null,
      said: "The melt has doubled.", country: "ch", language: "de", path: 2, first_in_corpus: false },
  ],
  missing: {
    countries: { total: 1, items: [{ key: "jp", corpus_sources: 4 }], in_trail: ["au", "ch", "gb"], corpus_total: 4 },
    languages: { total: 0, items: [], in_trail: ["de", "en"], corpus_total: 2 },
    source_types: { total: 1, items: [{ key: "statistics", corpus_sources: 1 }], in_trail: ["news"], corpus_total: 2 },
    would_discriminate: [
      { code: "no_primary_record", fact: {} },
      { code: "undated", fact: { n: 1 } },
      { code: "figure_source", fact: { figures: ["2000"] } },
    ],
  },
};

const EMPTY = {
  claim: "Penguins migrate to the Sahara",
  query: { text: '"Penguins" OR "Sahara"', derived: true, terms: ["Penguins", "Sahara"] },
  cross_language: null,
  related: { total: 0, at_index_cap: false, shown: 0, limit: 50, ordering: "relevance", articles: [] },
  independence: { n_articles: 0, n_sources: 0, n_paths: 0, n_joined_paths: 0, n_unjoined: 0, paths: [], join_counts: {} },
  timeline: [],
  missing: {
    countries: { total: 2, items: [{ key: "fr", corpus_sources: 3 }, { key: "jp", corpus_sources: 1 }] },
    languages: { total: 1, items: [{ key: "fr", corpus_sources: 3 }] },
    source_types: { total: 1, items: [{ key: "news", corpus_sources: 4 }] },
    would_discriminate: [{ code: "no_related", fact: {} }],
  },
};

const VERDICT = /\b(true|false|verified|debunked|credible|reliable|trustworthy|score|rating|confirmed|proven|fake)\b/i;

// 1. The whole trail: every step in order, ④ and ⑥ in place and not built.
const html = R.claimWorkspaceHtml(WS, t, tf);
const seen = visible(html);
const order = ["①", "②", "③", "④", "⑤", "⑥"].map((n) => html.indexOf(n));
assert.ok(order.every((x, i) => x !== -1 && (i === 0 || x > order[i - 1])), "steps out of order: " + order);
assert.strictEqual((html.match(/class="claim-step claim-later"/g) || []).length, 2, "④ and ⑥ are the not-built steps");
assert.strictEqual((seen.match(/Not built yet\./g) || []).length, 2);
// Every built step prints its method on the page.
assert.strictEqual((html.match(/class="claim-method"/g) || []).length, 4, "one visible method per built step");
// No verdict word, whatever the claim.
assert.ok(!VERDICT.test(seen.replace(WS.claim, "")), "a verdict word was drawn: " + seen.match(VERDICT));
for (const bad of ["undefined", "null", "NaN", "[object Object]"]) assert.ok(!seen.includes(bad), `drew "${bad}"`);

// 2. The independence step: joins named, the unjoined never called independent.
const ind = visible(R.claimIndependenceHtml(WS, t, tf));
assert.ok(ind.includes("Attribute the same news wire") && ind.includes("Reuters"), ind);
assert.ok(ind.includes("Cite the same page"), ind);
assert.ok(ind.includes("No shared origin found"), ind);
assert.ok(ind.includes("absence of evidence, never proof of independence"), ind);
assert.ok(!/\bindependent\b/i.test(ind.replace("proof of independence", "").replace("Grouped by independence", "")),
  "an unjoined article was called independent: " + ind);
assert.ok(ind.includes("#1 #2") && ind.includes("#3"), "paths refer to step ①'s numbers: " + ind);
// A shared outbound URL is text, never a link.
assert.ok(!/href="https:\/\/journal/.test(R.claimIndependenceHtml(WS, t, tf)), "external URL rendered as a link");

// 3. Articles open in the local reader; country and language through the display helpers.
assert.ok(html.includes('href="/api/articles/11/view"'), "local reader link missing");
assert.ok(!/href="https?:/.test(html), "a bare external link was drawn");
assert.ok(seen.includes("CC(gb)") && seen.includes("LC(de)") && seen.includes("CC(jp)"), "Q302 helpers bypassed");

// 4. The timeline: first-in-corpus marked once, the wire named, the no-sentence case said.
const tl = visible(R.claimTimelineHtml(WS, t, tf));
assert.strictEqual((tl.match(/first in your corpus/g) || []).length, 1);
assert.ok(tl.includes("attributes Reuters"));
assert.ok(tl.includes("No sentence carries the claim's words"), tl);
assert.ok(tl.includes("undated"), tl);

// 5. What's missing: the silent facets and the discriminators, with their facts filled.
const miss = visible(R.claimMissingHtml(WS, t, tf));
assert.ok(miss.includes("none silent"), "a facet with nothing silent must say so: " + miss);
assert.ok(miss.includes("The claim states figures (2000)"), miss);
assert.ok(miss.includes("Articles without a publication date: 1."), miss);
assert.ok(miss.includes("statistics"), miss);

// 6. The empty trail: every step still drawn; ⑤ says what WOULD be needed.
const e = R.claimWorkspaceHtml(EMPTY, t, tf);
const ev = visible(e);
assert.ok(ev.includes("No related article, so there is nothing to group."));
assert.ok(ev.includes("No related article, so there is no timeline."));
assert.ok(ev.includes("No article in your corpus matches these words."), ev);
assert.ok(ev.includes("CC(fr)"), "the corpus's silent countries are still listed");
assert.ok(!VERDICT.test(ev.replace(EMPTY.claim, "")));

// 7. A claim with no searchable word asks for words, and draws no counts.
const nw = visible(R.claimRelatedHtml({ query: { text: "" }, related: {} }, t, tf));
assert.ok(nw.includes("no words the index can search for"), nw);

// 8. The index-cap and the read bound are both said.
const cap = visible(R.claimRelatedHtml(Object.assign({}, WS, {
  related: Object.assign({}, WS.related, { total: 20000, at_index_cap: true }) }), t, tf));
assert.ok(cap.includes("at least 20000"), cap);
assert.ok(cap.includes("The trail reads the 3 best matches"), cap);
assert.ok(cap.includes("CROSS(1)"), "the cross-language disclosure is shown");

console.log("claim workspace node test: all checks passed");
