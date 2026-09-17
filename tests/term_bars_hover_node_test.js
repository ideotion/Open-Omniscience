// Q417's per-language breakdown on the AGGREGATE rows, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The ruling is "aggregates (rising, trends, top) are computed per RING when the term is
// in one, WITH A PER-LANGUAGE BREAKDOWN IN THE HOVER". The backend half shipped first:
// `queries.trending` puts `language_breakdown` on every ring row. The rows it lands on
// are drawn by `termBarsHtml`, which had no hover beyond the term itself -- so the
// composition was computed, serialised and sent on every request, and read by nobody on
// the one surface the ruling names. That is the shipped-but-unread trap this feature's
// own ledger records, inside the feature that recorded it.
//
// WHY BEHAVIOURAL AND NOT A SOURCE GREP. A grep for "Across languages:" in `termBarsHtml`
// passes the moment the string appears anywhere in the slice -- including inside the
// comment explaining the rule, and including a call whose result is discarded. What has
// to be true is about the rendered STRING for a given row: which rows get a breakdown,
// which get none, in what order, and on which side of the `title="` boundary it lands.
// So rows are fed in and the HTML is read back.
//
// EXTRACTED from the shipped modules rather than re-typed: a copy would keep passing
// while the surface regressed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  if (at < 0) throw new Error("no function named " + name);
  let i = APP.indexOf("(", at), depth = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = APP.indexOf("{", i);
  depth = 0;
  for (let j = open; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

// --- the harness ------------------------------------------------------------------- //
// `ooLangName` is stubbed to a table that is deliberately NOT the identity, so an
// assertion can tell a rendered NAME from a rendered CODE. With the identity the two are
// indistinguishable and "the hover names the language" would pass for free.
const NAMES = {en: "English", fr: "French", de: "German", ar: "Arabic", zh: "Chinese"};
function ooLangName(code, fb) { return NAMES[code] || fb || code; }
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
function fmtNum(v) { return String(v); }
const excludeKeyword = () => {};
// No OOI18N: the un-i18n'd fallback path, which is also the path a browser runs when
// i18n.js has not finished loading.
global.window = {};

const SRC = [
  extract("kwLangName"),
  extract("kwLangBreakdownText"),
  extract("termBarsHtml"),
].join("\n");
// eslint-disable-next-line no-eval
eval(SRC);

const RING = {term: "climate", mentions: 61, language_breakdown: {en: 9, fr: 7, de: 2}};
const PLAIN = {term: "transfer window", mentions: 12};
const bars = (rows) => termBarsHtml(rows, (t) => t.mentions, (t) => String(t.mentions));
const esq = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const titleOf = (html, term) => {
  const rx = new RegExp('data-kwstat="' + esq(term) + '"[^>]*?\\stitle="([^"]*)"');
  const m = rx.exec(html);
  assert.ok(m, "no row rendered for " + term + " in: " + html);
  return m[1];
};
const extraOf = (html, term) => {
  const rx = new RegExp('data-kwstat="' + esq(term) + '"[^>]*?\\sdata-oo-tip-extra="([^"]*)"');
  const m = rx.exec(html);
  return m ? m[1] : null;
};

let passed = 0;
function check(what, fn) { fn(); passed++; if (process.env.VERBOSE) console.log("  ok " + what); }

// --- the breakdown reaches the hover, and only the hover ---------------------------- //

check("a ring row carries its composition in the title", () => {
  const html = bars([RING]);
  const title = titleOf(html, "climate");
  assert.ok(/Across languages:/.test(title),
    "the ring row's hover carries no breakdown, so the composition the backend computes " +
    "is still read by nobody on this surface: " + title);
  // the NAME, not the code -- the stub table is not the identity, so this can tell them apart
  assert.ok(/English 9/.test(title), "the hover names a code rather than a language: " + title);
  assert.ok(!/\ben 9\b/.test(title), "the raw code leaked into the hover: " + title);
});

check("the breakdown does not crowd the visible row (invariant #17 is LAYERED)", () => {
  const html = bars([RING]);
  // Everything outside the attributes is what the reader sees without hovering.
  const visible = html.replace(/<[^>]*>/g, " ");
  assert.ok(!/Across languages/.test(visible),
    "the breakdown is rendered as row text, so every row now carries three languages of " +
    "chrome the reader did not ask for: " + visible);
  assert.ok(/climate/.test(visible), "the term itself stopped rendering");
});

// --- the negative space: a term in no ring says nothing ----------------------------- //

check("a term with no ring gets no breakdown", () => {
  const title = titleOf(bars([PLAIN]), "transfer window");
  assert.ok(!/Across languages/.test(title),
    "an ordinary term carries a cross-language hover, which trains the reader to ignore " +
    "the one that means something: " + title);
  // ...and the row still explains what clicking it does, so the absence is a refusal
  // rather than a hover that stopped being written at all.
  assert.ok(/open in analysis/.test(title), "the row lost its own hover: " + title);
});

check("the negative space above is not vacuous", () => {
  // Both rows through ONE render: if the mechanism were dead, the assertion above would
  // pass for the wrong reason and nothing else in this file would notice.
  const html = bars([RING, PLAIN]);
  assert.ok(/Across languages/.test(titleOf(html, "climate")));
  assert.ok(!/Across languages/.test(titleOf(html, "transfer window")));
});

// --- the numbers are the server's own, and they are not added up -------------------- //

check("counts are printed verbatim, with no total and no percentage", () => {
  const title = titleOf(bars([RING]), "climate");
  assert.ok(/English 9/.test(title) && /French 7/.test(title) && /German 2/.test(title), title);
  // The figures OVERLAP -- an article carrying two forms is counted under both -- so a
  // sum or a share would be a number the data cannot support. 9+7+2 = 18.
  assert.ok(!/18/.test(title), "the hover sums overlapping counts: " + title);
  assert.ok(!/%/.test(title), "the hover renders a share of a whole that does not exist: " + title);
});

check("a language with no mentions is dropped, not printed as a zero", () => {
  const title = titleOf(bars([{term: "climate", mentions: 9, language_breakdown: {en: 9, zh: 0}}]),
    "climate");
  assert.ok(/English 9/.test(title), title);
  assert.ok(!/Chinese/.test(title),
    "a language the concept was never seen in is listed at zero, which reads as a " +
    "measured absence rather than nothing to report: " + title);
});

check("the order is by count, and stable when counts tie", () => {
  const title = titleOf(bars([{term: "x", mentions: 5, language_breakdown: {de: 2, en: 9, fr: 7}}]), "x");
  assert.ok(title.indexOf("English 9") < title.indexOf("French 7"), title);
  assert.ok(title.indexOf("French 7") < title.indexOf("German 2"), title);
  // A tie broken by object key order is a hover that reorders itself between two renders
  // of the same corpus, which reads as change where there is none.
  const a = titleOf(bars([{term: "y", mentions: 4, language_breakdown: {fr: 4, en: 4}}]), "y");
  const b = titleOf(bars([{term: "y", mentions: 4, language_breakdown: {en: 4, fr: 4}}]), "y");
  assert.strictEqual(a, b, "the tie is broken by insertion order: " + a + " vs " + b);
});

// --- the title is one attribute, whatever the strings contain ----------------------- //

check("a quote in a term or a language name cannot break out of the attribute", () => {
  NAMES.xx = 'Ka"ren';
  try {
    const term = 'a"b onmouseover=alert(1)';
    const html = bars([{term, mentions: 1, language_breakdown: {xx: 3}}]);
    // The quote is escaped IN PLACE, so it never terminates the attribute: the character
    // that would have closed it is `&quot;` and the text carries on inside the value.
    assert.ok(html.includes('title="a&quot;b onmouseover=alert(1) \u2014 '),
      "the term is not escaped inside the title: " + html);
    assert.ok(html.includes('Ka&quot;ren 3'),
      "a quote inside a LANGUAGE NAME is unescaped, which is the half a term-only escape " +
      "would miss -- the name is appended after the escaping in the old shape: " + html);
    // ...and the attribute still runs to the end of the breakdown, which is what proves
    // the escape held: had it broken out, the captured value would stop at the quote.
    const value = /<a class="tb-label"[^>]*?\stitle="([^"]*)"/.exec(html);
    assert.ok(value && /Across languages: Ka&quot;ren 3$/.test(value[1]),
      "the title attribute ended early, so the rest of it is now markup: " + html);
  } finally {
    delete NAMES.xx;
  }
});

// --- and it SURVIVES the first hover ------------------------------------------------ //

check("the breakdown rides the channel the stats handler appends, not the one it erases", () => {
  // These rows carry `data-kwstat`, so `ooKwStatInit` fetches live keyword stats and
  // OVERWRITES both the title and the #oo-tip text with them. A breakdown left only in
  // the title is true in the DOM and gone the moment anyone points at the row -- caught
  // by reading the rendered bubble back in Chromium, where the stats line stood where
  // the breakdown should have been.
  const html = bars([RING, PLAIN]);
  const extra = extraOf(html, "climate");
  assert.ok(extra && /Across languages:/.test(extra),
    "the row carries no data-oo-tip-extra, so the breakdown is destroyed by the first " +
    "hover: " + html);
  // The same sentence in both channels: the title serves the pre-hover and native paths,
  // the extra survives the overwrite. They must not drift.
  assert.ok(titleOf(html, "climate").endsWith(extra),
    "the two channels carry different text: " + titleOf(html, "climate") + " vs " + extra);
  // ...and the negative space holds here too.
  assert.strictEqual(extraOf(html, "transfer window"), null,
    "an ordinary term carries a per-language addendum into the stats bubble");
});

console.log("term-bars hover: all assertions passed (" + passed + " checks)");
