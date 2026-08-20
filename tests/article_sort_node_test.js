// The Articles-tab sort controls, run as real code (rulings 20/21, field feedback
// 2026-08-07).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The sort used to live in Advanced, three subtabs from the only list that reads it, and
// the searched-keyword-count button silently overrode it in the request. Moving the
// control is the visible half; the half that matters is that there is now exactly ONE
// sort state, so a header, a select and a count button can never show three answers.
//
// EXTRACTED from src/static/app.js rather than re-typed -- a re-typed copy would pass
// while the shipped code was broken. Behavioural, because what is being asserted is what
// clicking twice DOES, which no source grep can see.

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"), "utf8");

function extract(name) {
  // Scan to the signature's balanced parens, THEN take the body brace, so a `{}` in a
  // default parameter cannot truncate the slice to the signature alone.
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in app.js -- was it renamed?");
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

// A two-element stand-in for the shipped controls, plus the escape/i18n shims the
// renderer reaches for. `reloads` counts how often the list would be re-fetched.
function harness() {
  const els = { "an-adv-sort": { value: "" }, "an-adv-dir": { value: "desc" } };
  const state = { reloads: 0, kwSort: false };
  const src = extract("_anTh") + "\n" + extract("_anSortBy") + "\n" + extract("_anSortChanged");
  const ctx = {};
  new Function("ctx", "$", "esc", "window", "OOI18N", "_anLoadArticles", "_anArtParams",
    src + "\nctx._anTh=_anTh; ctx._anSortBy=_anSortBy; ctx._anSortChanged=_anSortChanged;"
  )(ctx,
    (id) => els[id] || null,
    (s) => String(s),
    { OOI18N: { t: (s) => s } },
    { t: (s) => s },
    () => { state.reloads++; },
    {});                      // a loaded corpus, so a reload is possible
  return { els, state, ...ctx };
}

// --- ruling 21: a header click IS the sort, and clicking again reverses it ----------
{
  const h = harness();
  h._anSortBy("title");
  assert.strictEqual(h.els["an-adv-sort"].value, "title");
  assert.strictEqual(h.els["an-adv-dir"].value, "asc", "alphabetical opens A-Z");
  h._anSortBy("title");
  assert.strictEqual(h.els["an-adv-dir"].value, "desc", "the same header reverses");
  h._anSortBy("title");
  assert.strictEqual(h.els["an-adv-dir"].value, "asc", "...and reverses back");
}

// A count or a date opens on the LARGEST/most recent, which is what a reader means by
// "sort by this" for those columns; a name opens A-Z.
{
  const h = harness();
  h._anSortBy("top_keyword");
  assert.strictEqual(h.els["an-adv-dir"].value, "desc");
  h._anSortBy("date");
  assert.strictEqual(h.els["an-adv-dir"].value, "desc");
  h._anSortBy("source");
  assert.strictEqual(h.els["an-adv-dir"].value, "asc");
}

// Switching to a DIFFERENT column must not inherit the previous column's direction.
{
  const h = harness();
  h._anSortBy("date");            // desc
  h._anSortBy("date");            // asc
  h._anSortBy("title");
  assert.strictEqual(h.els["an-adv-sort"].value, "title");
  assert.strictEqual(h.els["an-adv-dir"].value, "asc");
  h._anSortBy("top_keyword");
  assert.strictEqual(h.els["an-adv-dir"].value, "desc",
    "a fresh column opens on its own natural direction, not the last one used");
}

// --- every click re-orders the LIST, and only the list ------------------------------
{
  const h = harness();
  h._anSortBy("title");
  h._anSortBy("title");
  assert.strictEqual(h.state.reloads, 2, "each click reloads the article list once");
}

// --- the header is a readout as well as a control -----------------------------------
{
  const h = harness();
  let th = h._anTh("title", "Title");
  assert.ok(th.includes("<th>") && th.includes("<button"), "a header must be a real button");
  assert.ok(th.includes('aria-pressed="false"'), "an inactive column is not pressed");
  assert.ok(!th.includes("↑") && !th.includes("↓"), "...and carries no arrow");

  h._anSortBy("title");                       // -> title asc
  th = h._anTh("title", "Title");
  assert.ok(th.includes('aria-pressed="true"'));
  assert.ok(th.includes("↑"), "the ACTIVE column shows its direction as a character");
  // ...and the other columns stay clean, so exactly one column ever claims the sort.
  assert.ok(!h._anTh("date", "Published").includes("↑"));
  assert.ok(!h._anTh("date", "Published").includes("↓"));

  h._anSortBy("title");                       // -> title desc
  assert.ok(h._anTh("title", "Title").includes("↓"));
}

// --- ONE sort state: the searched-keyword count and the column sort cannot disagree --
{
  const h = harness();
  h._anSortBy("top_keyword");
  assert.strictEqual(h.els["an-adv-sort"].value, "top_keyword");
  // _anSortChanged is what the select's onchange calls; it drops the count sort so the
  // request cannot carry two orders with one quietly winning.
  const body = extract("_anSortChanged");
  assert.ok(/_anKwSort\s*=\s*false/.test(body),
    "changing the column sort must clear the searched-keyword count sort");
  const kw = extract("_anToggleKwSort");
  assert.ok(kw.includes('$("an-adv-sort")') && /sb\.value\s*=\s*""/.test(kw),
    "...and turning the count sort ON must clear the column sort, not override it");
}

// --- the negative-space twin: no corpus loaded yet, nothing to reload ---------------
{
  const els = { "an-adv-sort": { value: "" }, "an-adv-dir": { value: "desc" } };
  let reloads = 0;
  const ctx = {};
  new Function("ctx", "$", "esc", "window", "OOI18N", "_anLoadArticles", "_anArtParams",
    extract("_anSortBy") + "\n" + extract("_anSortChanged")
    + "\nctx._anSortBy=_anSortBy;"
  )(ctx, (id) => els[id] || null, (s) => String(s), { OOI18N: { t: (s) => s } },
    { t: (s) => s }, () => { reloads++; }, null);   // _anArtParams null == no corpus yet
  ctx._anSortBy("title");
  assert.strictEqual(els["an-adv-sort"].value, "title", "the choice is still recorded");
  assert.strictEqual(reloads, 0, "but nothing is fetched when there is no corpus");
}

console.log("article sort: all assertions passed");
