// The Wikipedia lane's hits and held versions, run as REAL code (R52).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// R52's promise is that a term found in a Wikipedia text this machine holds -- a changed
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
//     and one that names none draws no link.
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
  "laneWhichText", "laneOmniRows", "laneVersionMetaHtml", "laneVersionNotesHtml",
  "laneVersionOutHtml", "laneAddedHtml", "laneFailText",
];
const opened = [];
const src =
  extractConst("esc") + "\n" +
  extractBlockConst("safeUrl") + "\n" +
  extractConst("_LTR_ISOLATE") + "\n" +
  extract("_ltrIsolate") + "\n" +
  extract("livingWhen") + "\n" +
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

console.log("lane_version_node_test: all checks passed");
