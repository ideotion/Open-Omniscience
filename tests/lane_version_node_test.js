// The Wikipedia lane's hits and held versions, run as REAL code (R52).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// R52's promise is that a term found in a text the Wikipedia lane holds -- a changed
// page's latest or previous text, or an earlier version of a followed page -- can be added
// to the corpus AS THAT VERSION. So what these renderers must not do is mostly how that
// could quietly go wrong:
//
//   * a hit that does not say WHICH text it is reads as the page's current text, which a
//     previous or earlier version is not;
//   * a token outside the known four is shown as the server sent it, never mapped onto the
//     nearest known word;
//   * the note saying where the text lives is visible by default, and the newest version of
//     a followed page says the corpus already holds it instead of offering it as new;
//   * the outbound link's visible text is the full address (invariant #6), and a scheme
//     that is not http(s) is never made clickable;
//   * every «Add to corpus» outcome that names an article links to it in the LOCAL reader,
//     and one that names none draws no link;
//   * the Search tab's section says WHAT WAS SEARCHED before its hits -- only this
//     machine's texts, per edition, never Wikipedia itself -- so an empty list never reads
//     as «Wikipedia does not say this», and it says when the corpus's filters did not
//     reach these texts;
//   * a locked app hides the section (the corpus's search already says so) and every
//     other absence is named, never an empty box.
//
// EXTRACTED from the shipped modules rather than re-typed: a re-typed copy would pass
// while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function braceEnd(from) {
  const open = APP.indexOf("{", from);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) return j + 1; }
  }
  throw new Error("unbalanced braces after " + from);
}

function extract(name) {
  // Balanced PARENS first, then the body brace (the recorded default-parameter trap).
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  return APP.slice(at, braceEnd(i));
}

function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}

// An arrow or object const whose body spans lines: up to its balanced closing brace.
function extractBlockConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  const end = braceEnd(at);
  return APP.slice(at, end) + ";";
}

const LANE = [
  "laneWhichText", "laneHitSub", "laneOmniRows", "laneVersionMetaHtml", "laneVersionNotesHtml",
  "laneVersionOutHtml", "laneAddedHtml", "laneFailText", "laneSnippetHtml", "_laneEditionsText",
  "laneCoverageHtml", "_laneKey", "laneHitHtml", "laneSearchHtml",
];
const opened = [];
const src =
  extractConst("esc") + "\n" +
  extractBlockConst("safeUrl") + "\n" +
  extractConst("_LTR_ISOLATE") + "\n" +
  extract("_ltrIsolate") + "\n" +
  extract("livingWhen") + "\n" +
  extract("ooListJoin") + "\n" +
  extract("ooLabelText") + "\n" +
  extractBlockConst("_LANE_WHICH") + "\n" +
  "var window = {};\n" +
  // The dialog is the one impure edge a row reaches: stubbed to record what it was asked.
  "function openLaneVersion(source, ownerId, revid) { OPENED.push([source, ownerId, revid]); }\n" +
  LANE.map(extract).join("\n") + "\n" +
  "module.exports = {" + LANE.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", "OPENED", src)(m, m.exports, opened);
  return m.exports;
})();

// The fallback t marks what passed through it, so a word that skipped translation shows.
const t = (s) => "T(" + s + ")";
const tf = (s, v) => "TF(" + s.replace(/\{(\w+)\}/g, (_, k) => v[k]) + ")";
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/[⁨⁩]/g, "").replace(/<[^>]*>/g, " "))
  .replace(/\s+/g, " ").trim();
const noJunk = (html, what) => {
  for (const bad of ["undefined", "null", "NaN", "[object Object]"]) {
    assert.ok(!visible(html).includes(bad), `${what} drew "${bad}": ${html}`);
  }
};

// --- 1. which text a hit is, in words; an unknown token as sent ----------------------- //
assert.strictEqual(R.laneWhichText("latest", t), "T(latest text held)");
assert.strictEqual(R.laneWhichText("previous", t), "T(previous text held)");
assert.strictEqual(R.laneWhichText("earlier", t), "T(earlier version)");
assert.strictEqual(R.laneWhichText("newest", t), "T(newest version)");
assert.strictEqual(R.laneWhichText("sideways", t), "sideways",
  "an unknown token was mapped onto a known word instead of shown as sent");
assert.strictEqual(R.laneWhichText(null, t), "", "an absent token drew a word");

// --- 2. the palette rows ------------------------------------------------------------ //
assert.deepStrictEqual(R.laneOmniRows(null, t), []);
assert.deepStrictEqual(R.laneOmniRows({ available: false, reason: "lane-never-run", items: [] }, t), [],
  "a lane that never ran drew rows");
assert.deepStrictEqual(R.laneOmniRows({ available: true, total: 0, items: [] }, t), []);
{
  const lane = { available: true, total: 2, items: [
    { source: "warm", owner_id: 7, revid: 2201, title: "Salt <works>", page_id: 11, edition: "frwiki",
      which: "previous", revised_at: "2025-02-03T04:05:06+00:00" },
    { source: "hot", owner_id: 9, revid: 3301, title: null, page_id: 12, edition: "enwiki",
      which: "earlier", revised_at: null },
  ] };
  const rows = R.laneOmniRows(lane, t);
  assert.strictEqual(rows.length, 2);
  assert.strictEqual(rows[0].label, "Salt <works>", "the palette escapes labels itself; this is data");
  assert.strictEqual(rows[0].sub, "frwiki · T(previous text held) · 2025-02-03");
  assert.strictEqual(rows[1].label, "#12", "a page with no held title is named by its id, never blank");
  assert.strictEqual(rows[1].sub, "enwiki · T(earlier version)", "an unknown date drew a placeholder");
  rows[0].run();
  rows[1].run();
  assert.deepStrictEqual(opened, [["warm", 7, 2201], ["hot", 9, 3301]],
    "a row opened something other than THE version it names");
}

// --- 3. the dialog: meta, notes, the outbound link ---------------------------------- //
const V = { source: "warm", owner_id: 7, edition: "frwiki", page_id: 11, title: "Salt works",
  revid: 2201, revised_at: "2025-02-03T04:05:06+00:00", which: "previous", deleted: false,
  newest_followed: false, url: "https://fr.wikipedia.org/w/index.php?title=Salt_works&oldid=2201",
  text: "The older text.", chars: 15 };
{
  const meta = R.laneVersionMetaHtml(V, t, tf);
  assert.strictEqual(visible(meta), "frwiki · T(previous text held) · 2025-02-03 04:05 UTC · TF(revision 2201)");
  noJunk(R.laneVersionMetaHtml({ ...V, revised_at: null, which: null }, t, tf), "an undated version's meta");
  assert.ok(!R.laneVersionMetaHtml({ ...V, edition: "<b>x</b>" }, t, tf).includes("<b>"), "meta is not escaped");

  const held = visible(R.laneVersionNotesHtml(V, t));
  assert.ok(held.includes("T(Held on this machine by the Wikipedia lane, not in your corpus."), held);
  assert.ok(!held.includes("deleted"), "a page never deleted was said to be deleted");
  const gone = visible(R.laneVersionNotesHtml({ ...V, deleted: true }, t));
  assert.ok(gone.includes("T(The page has been deleted on Wikipedia since. Its text stays here.)"), gone);
  const newest = visible(R.laneVersionNotesHtml({ ...V, source: "hot", which: "newest", newest_followed: true }, t));
  assert.ok(newest.includes("Your corpus already holds it as an article."), newest);
  assert.ok(!newest.includes("not in your corpus"),
    "the newest version of a followed page was offered as if the corpus did not hold it");
  assert.ok(!R.laneVersionNotesHtml(V, t).includes("hidden"), "the note is not visible by default");

  const out = R.laneVersionOutHtml(V, t);
  assert.ok(visible(out).endsWith(V.url), "invariant #6: the link's visible text is not the full address");
  assert.ok(out.includes(`href="${V.url.replace(/&/g, "&amp;")}"`), out);
  const js = R.laneVersionOutHtml({ ...V, url: "javascript:alert(1)" }, t);
  assert.ok(!js.includes('href="javascript'), "a non-http(s) scheme was made clickable: " + js);
  assert.strictEqual(R.laneVersionOutHtml({ ...V, url: null }, t), "", "no address drew an empty link");
}

// --- 4. what «Add to corpus» did --------------------------------------------------- //
{
  const created = R.laneAddedHtml({ status: "created", article_id: 42, title: "Salt works", revid: 2201 }, t);
  assert.ok(created.includes('class="note ok"'), created);
  assert.ok(created.includes('href="/api/articles/42/view"'), "the new article is not one click away: " + created);
  assert.ok(visible(created).startsWith("T(Added to your corpus as its own article.)"), created);
  for (const status of ["exists", "same_text"]) {
    const html = R.laneAddedHtml({ status, article_id: 5, title: "x", revid: 1 }, t);
    assert.ok(html.includes('href="/api/articles/5/view"'), `${status} does not link the article it means`);
    assert.ok(!html.includes(" ok\""), `${status} is drawn as a fresh addition`);
  }
  assert.ok(visible(R.laneAddedHtml({ status: "same_text", article_id: 5 }, t))
    .includes("T(Your corpus already holds an article with exactly these words.)"));
  const empty = R.laneAddedHtml({ status: "skipped-empty-after-strip", title: "x", revid: 1 }, t);
  assert.ok(!empty.includes("<a "), "an outcome naming no article drew a link: " + empty);
  noJunk(empty, "the empty-text outcome");
  assert.ok(visible(R.laneAddedHtml({ status: "mystery", article_id: 3 }, t)).startsWith("mystery"),
    "an unknown outcome was mapped onto a known one");
}

// --- 5. the routes' refusals, in words --------------------------------------------- //
assert.strictEqual(R.laneFailText({ detail: "not-held", message: "Not Found" }, t),
  "T(This version is no longer held on this machine.)");
assert.strictEqual(R.laneFailText({ detail: "no-title", message: "Conflict" }, t),
  "T(The lane holds no title for this page, and an article needs one.)");
assert.strictEqual(R.laneFailText({ detail: "lane-unreadable" }, t), "T(The Wikipedia lane could not be read just now.)");
assert.strictEqual(R.laneFailText({ detail: "lane-never-run" }, t), "T(The Wikipedia lane has not run on this machine yet.)");
assert.strictEqual(R.laneFailText({ detail: "locked", message: "The app is locked" }, t), "The app is locked",
  "a refusal this surface does not name lost the server's own message");

// --- 6. the Search tab's section: what was searched, then the hits ------------------- //
const noHandler = (html, what) => assert.ok(!/\son[a-z]+=/i.test(html), `${what} carries an inline handler: ${html}`);
assert.strictEqual(R.laneSnippetHtml([{ text: "a <b> ", hit: false }, { text: "salt", hit: true }]),
  "a &lt;b&gt; <mark>salt</mark>");
assert.strictEqual(R.laneSnippetHtml(null), "", "no snippet drew something");
{
  const cov = { changed_pages: { pages: 3, editions: [{ edition: "en", pages: 2 }, { edition: "fr", pages: 1 }] },
    stream_pages: { pages: 5, editions: [{ edition: "en", pages: 5 }] }, pending: 0, failed: 0, warm_enabled: true };
  const text = visible(R.laneCoverageHtml(cov, t));
  assert.ok(text.startsWith("T(Searched only the texts the Wikipedia lane holds on this machine, not Wikipedia itself:)"), text);
  assert.ok(text.includes("T(Other changed pages, by their latest and previous texts): 3 (en 2, fr 1)"), text);
  assert.ok(text.includes("T(Pages the stream has followed, by their older versions): 5 (en 5)"), text);
  assert.ok(!text.includes("waiting") && !text.includes("set aside") && !text.includes("is off"),
    "a zero queue or WARM switched on drew a line: " + text);
  const busy = visible(R.laneCoverageHtml({ ...cov, pending: 7, failed: 2, warm_enabled: false }, t));
  assert.ok(busy.includes("T(Texts waiting to be indexed, not searched yet): 7"), busy);
  assert.ok(busy.includes("T(Texts set aside because they could not be read): 2"), busy);
  assert.ok(busy.includes("T(Fetching other changed pages is off. Texts already fetched are kept.)"), busy);
  assert.ok(!visible(R.laneCoverageHtml({ ...cov, warm_enabled: null }, t)).includes("is off"),
    "an unreadable switch was reported as off");
  const empty = visible(R.laneCoverageHtml({ changed_pages: { pages: 0, editions: [] }, stream_pages: { pages: 0, editions: [] } }, t));
  assert.ok(empty.includes("T(The Wikipedia lane holds no text yet.)"), empty);
  assert.strictEqual(R.laneCoverageHtml(null, t), "");
  noJunk(R.laneCoverageHtml({}, t), "a coverage block with nothing in it");
}
const HIT = { source: "warm", owner_id: 7, revid: 2201, title: "Salt <works>", page_id: 11, edition: "fr",
  which: "previous", revised_at: "2025-02-03T04:05:06+00:00",
  snippet: [{ text: "…the ", hit: false }, { text: "salt", hit: true }, { text: " pans…", hit: false }] };
{
  const row = R.laneHitHtml(HIT, { added: {}, failed: {}, busy: {} }, t);
  noHandler(row, "a hit row");
  for (const b of row.match(/<button[^>]*>/g)) {
    assert.ok(b.includes('data-source="warm"') && b.includes('data-owner="7"') && b.includes('data-revid="2201"'),
      "a row's button names another version than the row shows: " + b);
  }
  assert.ok(row.includes("data-lane-open") && row.includes("data-lane-add"), row);
  assert.ok(row.includes("Salt &lt;works&gt;") && !row.includes("<works>"), "a title was not escaped");
  assert.ok(visible(row).includes("fr · T(previous text held) · 2025-02-03"), visible(row));
  assert.ok(row.includes('dir="auto"') && row.includes("<mark>salt</mark>"), row);
  assert.ok(!/data-lane-add[^>]*disabled/.test(row), "a fresh row's add button is off");
  const key = "warm:7:2201";
  const added = R.laneHitHtml(HIT, { added: { [key]: { status: "created", article_id: 42 } }, failed: {}, busy: {} }, t);
  assert.ok(/data-lane-add[^>]*disabled/.test(added), "an added version can be added again");
  assert.ok(added.includes('href="/api/articles/42/view"'), "the added article is not one click away");
  assert.ok(/data-lane-add[^>]*disabled/.test(R.laneHitHtml(HIT, { added: {}, failed: {}, busy: { [key]: true } }, t)),
    "a second click could go out while the first is in flight");
  const failed = R.laneHitHtml(HIT, { added: {}, failed: { [key]: { detail: "not-held" } }, busy: {} }, t);
  assert.ok(failed.includes('class="note err"') && visible(failed).includes("T(This version is no longer held on this machine.)"));
  assert.ok(!R.laneHitHtml({ ...HIT, snippet: null }, {}, t).includes("lane-snip"), "an absent snippet drew an empty line");
}
{
  const d = { available: true, total: 41, items: [HIT], coverage: { changed_pages: { pages: 3, editions: [{ edition: "fr", pages: 3 }] },
    stream_pages: { pages: 0, editions: [] } } };
  const st = { d, filtered: false, added: {}, failed: {}, busy: {} };
  const html = R.laneSearchHtml(st, t, tf);
  noHandler(html, "the section");
  noJunk(html, "the section");
  const text = visible(html);
  assert.ok(text.startsWith("T(Wikipedia texts held on this machine)"), "the hits are not marked as Wikipedia: " + text);
  assert.ok(text.includes("TF(41 result(s) (showing 1))"), "the total is not the route's own: " + text);
  assert.ok(html.indexOf("Searched only") < html.indexOf('<li class="living-row"'),
    "what was searched comes after the hits instead of before them");
  assert.ok(/class="card-caveat">T\(Older versions are found by the lines a later edit removed\./.test(html),
    "the caveat is not visible by default");
  assert.ok(!text.includes("Your filters"), "the filter note shows with no filter set");
  assert.ok(visible(R.laneSearchHtml({ ...st, filtered: true }, t, tf)).includes("T(Your filters apply to the corpus only"));
  assert.ok(visible(R.laneSearchHtml({ ...st, d: { ...d, fields_not_applied: ["source"] } }, t, tf)).includes("T(Your filters apply"),
    "a source: in the query did not say it missed these texts");
  const none = visible(R.laneSearchHtml({ ...st, d: { ...d, total: 0, items: [] } }, t, tf));
  assert.ok(none.includes("T(None of the texts the Wikipedia lane holds contains these words.)"), none);
  assert.ok(none.includes("T(Searched only the texts the Wikipedia lane holds"), "an empty answer did not say what it searched");
  assert.ok(visible(R.laneSearchHtml({ ...st, d: { ...d, total: 1 } }, t, tf)).includes("TF(1 result(s))"));
}
assert.strictEqual(R.laneSearchHtml(null, t, tf), "", "no search drew a section");
assert.ok(visible(R.laneSearchHtml({ loading: true }, t, tf)).endsWith("T(Loading…)"));
assert.ok(R.laneSearchHtml({ error: { detail: "lane-unreadable" } }, t, tf).includes("T(The Wikipedia lane could not be read just now.)"));
assert.strictEqual(R.laneSearchHtml({ d: { available: false, reason: "locked" } }, t, tf), "",
  "a locked app drew a second lock message beside the corpus's");
assert.ok(visible(R.laneSearchHtml({ d: { available: false, reason: "lane-never-run" } }, t, tf))
  .includes("T(The Wikipedia lane has not run on this machine yet.)"));
assert.ok(visible(R.laneSearchHtml({ d: { available: false, reason: "sqlite_too_old" } }, t, tf)).includes("3.43"));
assert.ok(visible(R.laneSearchHtml({ d: { available: false, reason: "index_not_built" } }, t, tf))
  .includes("T(The search index of these texts is built the next time the Wikipedia lane runs.)"));
assert.ok(visible(R.laneSearchHtml({ d: { available: false, reason: "mystery" } }, t, tf)).endsWith("mystery"),
  "an unknown absence was mapped onto a known one");
assert.ok(visible(R.laneSearchHtml({ d: { available: true, error: "query_invalid", total: null, items: [] } }, t, tf))
  .includes("T(These texts were not searched: their index could not read this query.)"));
assert.strictEqual(R.laneSearchHtml({ d: { available: true, total: null, items: [] } }, t, tf), "",
  "a query with nothing to search for drew a section");

console.log("lane_version_node_test: all checks passed");
