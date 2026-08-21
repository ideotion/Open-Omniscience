// The Feed's restart-while-loading race (ruling 8/41, field feedback 2026-08-07).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The Reshuffle button is rendered by loadFeed's own first act, so it is clickable while
// that very page is still in flight. Before the generation counter, clicking it cleared
// the list and the stored cursor, then bounced off the busy guard -- and the in-flight
// page landed anyway: rows from the ORDER THE READER LEFT, and its cursor written back
// over the cleared mark. The next scroll then sent the NEW seed with a cursor from the
// OLD permutation, silently skipping everything between them. Skipping is the one thing
// a keyset walk over a bijection is supposed to make impossible, so this is not cosmetic.
//
// EXTRACTED from src/static/app.js rather than re-typed, and BEHAVIOURAL: the fix is
// three lines that a source grep cannot tell from the comments explaining them.

const fs = require("fs");
const path = require("path");
const assert = require("assert");

// The UI engine is ordered modules since the S-3 decomposition; ask the shared
// helper, which reads the module list out of index.html and cannot drift.
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balance the signature's parens FIRST, so a `{}` in a default parameter cannot
  // truncate the slice to the signature alone.
  let at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in app.js -- was it renamed?");
  // Carry an `async` modifier into the slice. Anchoring on "function <name>(" alone
  // drops it, and the extracted body then fails to parse on its own `await` -- the
  // failure looks like a broken test rather than a truncated anchor.
  const ASYNC = "async ";
  if (APP.slice(Math.max(0, at - ASYNC.length), at) === ASYNC) at -= ASYNC.length;
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

// A list that records what was appended, a "more" slot, and an `api` whose response we
// release by hand -- which is what makes the interleaving deterministic rather than a
// timing test.
function harness() {
  const list = { html: "", children: [], insertAdjacentHTML(_, h) { this.html += h; } };
  const more = { innerHTML: "" };
  const els = { "feed-list": list, "feed-more": more, "feed-controls": null };
  const store = {};
  const pending = [];
  const state = { requests: [] };

  const src =
    extract("loadFeed") + "\n" +
    extract("_feedRestart") + "\n" +
    "ctx.loadFeed=loadFeed; ctx._feedRestart=_feedRestart;\n" +
    "ctx.peek=()=>({busy:_feedBusy, done:_feedDone, gen:_feedGen});";

  const ctx = {};
  new Function(
    "ctx", "$", "esc", "api", "window", "OOI18N", "localStorage",
    "_feedControls", "_feedOrder", "_feedSeed", "_feedMark", "_feedSetMark",
    "_feedCard", "_feedNote", "URLSearchParams",
    // The module-level state the two functions close over in app.js.
    "let _feedBusy = false, _feedDone = false, _feedHeld = null, _feedGen = 0;\n" + src
  )(
    ctx,
    (id) => els[id] || null,
    (s) => String(s),
    (url) => new Promise((resolve, reject) => { state.requests.push(url); pending.push({ resolve, reject }); }),
    { OOI18N: { t: (s) => s } },
    { t: (s) => s },
    { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; }, removeItem: (k) => { delete store[k]; } },
    () => {},                                   // _feedControls
    () => "shuffled",                           // _feedOrder
    () => (store.seed ? Number(store.seed) : 1),
    (o) => store["mark:" + o] || "",            // _feedMark
    (o, v) => { store["mark:" + o] = v; },      // _feedSetMark
    (a) => `<article data-id="${a.id}"></article>`,
    () => {},                                   // _feedNote
    URLSearchParams
  );
  return { ctx, list, more, store, state, pending };
}

const page = (ids, cursor) => ({
  results: ids.map((id) => ({ id })), next_cursor: cursor, has_more: true, held_back: null,
});

// --- the race itself ---------------------------------------------------------------
(async () => {
  {
    const h = harness();
    h.ctx.loadFeed(true);                       // first page, in flight
    assert.strictEqual(h.state.requests.length, 1, "the first page was never requested");
    assert.ok(h.ctx.peek().busy, "the walk should be marked busy while in flight");

    // The reader reshuffles before it lands: new seed, cleared marks, cleared list.
    h.store.seed = "999";
    h.store["mark:shuffled"] = "";
    h.ctx._feedRestart();
    assert.strictEqual(h.state.requests.length, 2, "the restart must issue its own page");
    assert.ok(h.state.requests[1].includes("seed=999"), "the restart must use the NEW seed");

    // Now the ORIGINAL page arrives, late.
    h.pending[0].resolve(page([11, 12], "OLD-CURSOR"));
    await new Promise((r) => setTimeout(r, 0));

    assert.strictEqual(
      h.list.html, "",
      "a page from the order the reader left was appended to the order they chose"
    );
    assert.strictEqual(
      h.store["mark:shuffled"], "",
      "the abandoned page wrote its cursor over the cleared mark -- the next scroll " +
      "would send the NEW seed with a cursor from the OLD permutation and skip the gap"
    );

    // ...and the replacement page still lands normally.
    h.pending[1].resolve(page([21, 22], "NEW-CURSOR"));
    await new Promise((r) => setTimeout(r, 0));
    assert.ok(h.list.html.includes('data-id="21"'), "the restarted page never arrived");
    assert.strictEqual(h.store["mark:shuffled"], "NEW-CURSOR", "the live cursor must be the new one");
    assert.strictEqual(h.ctx.peek().busy, false, "the live walk must be released when it lands");
  }

  // --- the negative-space twin: with NO restart, a page must still append -----------
  // A "discard everything" mutation would satisfy every assertion above.
  {
    const h = harness();
    h.ctx.loadFeed(true);
    h.pending[0].resolve(page([31, 32], "C1"));
    await new Promise((r) => setTimeout(r, 0));
    assert.ok(h.list.html.includes('data-id="31"'), "an undisturbed page must be appended");
    assert.strictEqual(h.store["mark:shuffled"], "C1", "an undisturbed page must set the cursor");
  }

  // --- a late FAILURE must not report over the walk that replaced it ----------------
  {
    const h = harness();
    h.ctx.loadFeed(true);
    h.ctx._feedRestart();
    h.more.innerHTML = "SENTINEL";
    h.pending[0].reject(new Error("stale boom"));
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(
      h.more.innerHTML, "SENTINEL",
      "an abandoned page reported its own failure over the live walk"
    );
  }

  console.log("feed restart race: ok");
})().catch((e) => { console.error(e); process.exit(1); });
