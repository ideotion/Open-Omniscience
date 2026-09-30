// Living sources' two cross-edition views, run as REAL code (0.5 row F, S05-06; Q712's 4-5).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Mostly refusals:
//   * an edition the item was not found in is a NAMED state (walk never ran / not
//     finished / finished and none), never a blank cell or a 0;
//   * a change count the stream never recorded is "not followed", not 0; a recorded 0 is 0;
//   * no ratio, score or verdict word anywhere, and the size spread is two sizes;
//   * a top-list row the count did not reach is "not counted", not 0;
//   * the method and the caveat are printed, never only hovered.
// EXTRACTED from the shipped module, not re-typed.

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
  let end = at, depth = 0;
  for (; end < APP.length; end++) {
    const c = APP[end];
    if (c === "{" || c === "[" || c === "(") depth++;
    else if (c === "}" || c === "]" || c === ")") depth--;
    else if (c === ";" && depth === 0) { end++; break; }
  }
  return APP.slice(at, end);
}

const FUNCS = [
  "_wikiEdCell", "_wikiLaneStateHtml", "wikiDivCandidatesHtml", "_wikiDivStateText", "_wikiDivRowHtml",
  "wikiDivergenceHtml", "wikiAttentionHtml", "livingWhen", "_livingCount",
];
const src =
  extractConst("esc") + "\n" +
  extractConst("_LTR_ISOLATE") + "\n" +
  extract("_ltrIsolate") + "\n" +
  extractConst("_WIKI_DIV_STATES") + "\n" +
  extractConst("_WIKI_LANE_STATES") + "\n" +
  "var window = {};\n" +
  "function ooLangCell(v, o) { return '<span class=\"' + ((o && o.cls) || '') + '\">LC(' + esc(v) + ')</span>'; }\n" +
  "function ooLangCode(v) { return 'L3(' + v + ')'; }\n" +
  "function fmtNum(v) { return String(v); }\n" +
  "function humanBytes(n) { return n + ' B'; }\n" +
  FUNCS.map(extract).join("\n") + "\n" +
  "module.exports = {" + FUNCS.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/[⁨⁩]/g, "").replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();
const hovers = (html) => decode([...String(html).matchAll(/title="([^"]*)"/g)].map((m) => m[1]).join(" | "));
const noJunk = (html, what) => {
  for (const bad of ["undefined", "null", "NaN", "[object Object]"]) {
    assert.ok(!visible(html).includes(bad) && !hovers(html).includes(bad), `${what} drew "${bad}": ${html}`);
  }
};
const FORBIDDEN = /\b(score|ratio|rank(?:ing)? of|gap|lag|divergent|diverges|viral|trending|because|caused?|healthy|stale)\b/i;
const noVerdict = (html, what) => {
  const m = (visible(html) + " " + hovers(html)).match(FORBIDDEN);
  assert.ok(!m, `${what} passes a verdict ("${m && m[0]}"): ${visible(html)}`);
};

const DIV = {
  measured: true, reason: null, qid: "Q42", window_days: 7, n_editions: 4, n_found: 2, n_sized: 2,
  smallest: { edition: "fr", length_bytes: 900 }, largest: { edition: "en", length_bytes: 5000 },
  method: "METHOD", caveat: "CAVEAT",
  editions: [
    { edition: "en", state: "found", page_id: 7, title: "Douglas Adams", length_bytes: 5000,
      read_at: "2026-09-29T10:00:00+00:00", followed: true, changes_in_window: 0, walk: null },
    { edition: "fr", state: "found", page_id: 8, title: "Douglas Adams", length_bytes: 900,
      read_at: "2026-09-29T11:00:00+00:00", followed: false, changes_in_window: null, walk: null },
    { edition: "de", state: "walk-never-ran", walk: null },
    { edition: "es", state: "walk-incomplete", walk: { pages_seen: 10, edition_articles: 40, completed_at: null } },
  ],
  candidates: { items: [{ qid: "Q42", changes_in_window: 5, editions_found: 2 }], n: 1, window_days: 7 },
};

// --- 1. the comparison table ------------------------------------------------------- //
{
  const html = R.wikiDivergenceHtml(DIV, t, tf);
  noJunk(html, "divergence"); noVerdict(html, "divergence");
  const v = visible(html);
  assert.ok(v.includes("Douglas Adams") && v.includes("5000 B") && v.includes("900 B"));
  assert.ok(v.includes("The walk has not run for this edition."));
  assert.ok(v.includes("The walk has not finished this edition (10 of 40 pages), so the item may be there."));
  assert.ok(v.includes("Smallest: L3(fr), 900 B. Largest: L3(en), 5000 B."), v);
  // An unfollowed page is "not followed" (unknown), a followed one with nothing recorded is 0.
  assert.ok(/not followed/.test(v));
  assert.ok(/LC\(en\)\s*<?/.test(html) && /<td>0<\/td>/.test(html), "a recorded zero must draw 0");
  assert.ok(hovers(html).includes("unknown, not zero"));
  // The method and the caveat are PRINTED, not only hovered.
  assert.ok(v.includes("METHOD") && v.includes("CAVEAT"));
  assert.ok(html.includes('class="card-caveat"'));
}
// --- 2. no extremes from one size; the finished-and-none state is named ------------ //
{
  const one = JSON.parse(JSON.stringify(DIV));
  one.n_sized = 1;
  assert.ok(!visible(R.wikiDivergenceHtml(one, t, tf)).includes("Smallest"), "one size has no spread");
  const none = { measured: false, reason: "item-not-found", qid: "Q9", window_days: 7, n_sized: 0,
    editions: [{ edition: "en", state: "none-after-complete-walk", walk: null }], method: "M", caveat: "C" };
  const v = visible(R.wikiDivergenceHtml(none, t, tf));
  assert.ok(v.includes("The walk has not found Q9 in any edition it has read."));
  assert.ok(v.includes("The walk finished this edition and found no page for this item."));
}
// --- 3. the named refusals --------------------------------------------------------- //
assert.strictEqual(R.wikiDivergenceHtml({ measured: false, reason: "no-item-chosen", candidates: { items: [] } }, t, tf), "");
assert.ok(visible(R.wikiDivergenceHtml({ measured: false, reason: "qid-invalid", qid: "x" }, t, tf)).includes("Write Q followed by a number"));
assert.ok(visible(R.wikiDivergenceHtml({ measured: false, reason: "lane-never-run" }, t, tf)).includes("has not run on this machine yet"));
assert.ok(visible(R.wikiDivergenceHtml({ measured: false, reason: "lane-unreadable" }, t, tf)).includes("could not be read"));
assert.strictEqual(R.wikiDivCandidatesHtml({ reason: "lane-never-run" }, t, tf), "");
// An unknown state is shown as the server sent it, never mapped onto the nearest.
assert.ok(visible(R.wikiDivergenceHtml({ ...DIV, editions: [{ edition: "en", state: "weird" }] }, t, tf)).includes("weird"));

// --- 4. suggestions are buttons carrying only the item ----------------------------- //
{
  const html = R.wikiDivCandidatesHtml(DIV, t, tf);
  assert.ok(html.includes('data-div-qid="Q42"'));
  assert.ok(visible(html).includes("Q42: 5 changes, found in 2 editions"));
  assert.ok(!/onclick/i.test(html), "no inline handlers: the CSP forbids them");
  assert.ok(visible(R.wikiDivCandidatesHtml({ candidates: { items: [], window_days: 7 } }, t, tf)).includes("No suggestion yet"));
}

// --- 5. the attention table -------------------------------------------------------- //
{
  const ATT = { measured: true, edition: "en", day: "2026-09-29", n: 3, skipped: 1, method: "METHOD", caveat: "CAVEAT",
    rows: [
      { rank: 1, title: "Main Page", views: 1000000, press_day: 0, press_7d: 2 },
      { rank: 2, title: "Some <b>Title</b>", views: 500, press_day: 3, press_7d: 11 },
      { rank: 3, title: "Late", views: 10, press_day: null, press_7d: null },
    ] };
  const html = R.wikiAttentionHtml(ATT, t, tf);
  noJunk(html, "attention"); noVerdict(html, "attention");
  const v = visible(html);
  assert.ok(v.includes("Top 3 of the list for 2026-09-29."));
  assert.ok(html.includes("Some &lt;b&gt;Title&lt;/b&gt;"), "a title is text, never markup");
  assert.ok(/<td>0<\/td><td>2<\/td>/.test(html), "a counted zero must draw 0");
  assert.ok(v.includes("not counted") && v.includes("1 row(s) were not counted"));
  assert.ok(v.includes("METHOD") && v.includes("CAVEAT"));
  assert.ok(html.includes('class="card-caveat"'));
  assert.ok(!html.includes("Main Page</td><td>1000000</td><td>0</td><td>2</td><td>"), "no derived column");
  assert.ok(visible(R.wikiAttentionHtml({ measured: false, reason: "no-top-list-yet" }, t, tf)).includes("No list of most-viewed pages"));
  assert.ok(visible(R.wikiAttentionHtml({ measured: false, reason: "lane-unreadable" }, t, tf)).includes("could not be read"));
}
console.log("all checks passed");
// --- 6. the size bar: zero baseline, longest = full, exact figure beside it --------- //
{
  const html = R.wikiDivergenceHtml(DIV, t, tf);
  assert.ok(html.includes('style="width:100%"'), "the largest size fills the bar");
  assert.ok(html.includes('style="width:18%"'), "900 of 5000 is 18% of the largest");
  assert.ok(/aria-hidden="true"/.test(html), "the bar is decoration: the figure carries the reading");
}
console.log("bar checks passed");
