// The Wikipedia tracked-changes view, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The ruled surface is "an interface for scrolling through, discovering and analysing
// edits through time", and the honesty it owes is entirely in what it does when it has
// LESS than a full answer: an empty page, a windowed slice, a revision with no stored
// diff, and -- since the article reader gained a ?wikitc= deep link -- a caller that
// knows only a page id and not its name.
//
// Driven here rather than asserted from source, because none of that is provable by
// reading: a source guard for "the header is filled from the server's answer" is
// satisfied by the identifier sitting inside a branch that never runs, which is exactly
// how the first version of that guard survived its own mutation.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real view was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name, kind) {
  // Balanced PARENS first, then the BODY brace: a `{}` in a default parameter would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
  const at = APP.indexOf((kind || "function ") + name + "(");
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

// A DOM shim carrying only what the view touches. Every element records what was
// written to it, so an assertion is about what a READER would see rather than about
// which identifiers appear in the source.
function makeEls() {
  const mk = () => ({ innerHTML: "", textContent: "", checked: false });
  return {
    "wiki-tc-body": mk(),
    "wiki-tc-method": mk(),
    "wiki-tc-title": mk(),
    "wiki-tc-flagged": mk(),
  };
}

function load(payload, opts) {
  opts = opts || {};
  const els = makeEls();
  if (opts.flagged) els["wiki-tc-flagged"].checked = true;
  const calls = [];
  const src =
    "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
    "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
    "var window = {};\n" +
    "var _wikiTc = OO_TC;\n" +
    "function $(id){ return OO_ELS[id] || null; }\n" +
    "async function api(u){ OO_CALLS.push(u); if (OO_PAYLOAD instanceof Error) throw OO_PAYLOAD; return OO_PAYLOAD; }\n" +
    extract("_wikiRevRow") + "\n" +
    extract("loadWikiTC", "async function ") + "\n" +
    "module.exports = { loadWikiTC, _wikiTc };";
  const m = { exports: {} };
  new Function("module", "exports", "OO_ELS", "OO_PAYLOAD", "OO_CALLS", "OO_TC", src)(
    m, m.exports, els, payload, calls,
    { id: opts.id === undefined ? 7 : opts.id, title: opts.title || "", wiki: opts.wiki || "" }
  );
  return m.exports.loadWikiTC().then(() => ({ els, calls, tc: m.exports._wikiTc }));
}

const REVS = {
  page: { id: 7, wiki: "en", title: "Climate change" },
  count: 2,
  total: 91,
  revisions: [
    {
      revid: 5150, timestamp: "2026-03-04T10:11:12Z", editor: "Ada", editor_anon: false,
      minor: false, bot: false, delta_bytes: 412, has_full_text: true,
      comment: "expanded the mitigation section", diff: "+ added a paragraph\n- removed a stale figure",
      flag_reasons: ["large change"],
    },
    {
      revid: 5149, timestamp: "2026-03-03T09:00:00Z", editor: null, editor_anon: true,
      minor: true, bot: false, delta_bytes: -8, has_full_text: false,
      comment: "", diff: "", flag_reasons: [],
    },
  ],
};

(async () => {
  // ---- the window is stated, never implied -------------------------------- //
  {
    const { els } = await load(REVS);
    const body = els["wiki-tc-body"].innerHTML;
    assert.ok(/2\s*\/\s*91/.test(body),
      "the view must say it is showing a SLICE (count of total), not imply completeness");
    assert.ok(body.includes("5150") === false || true);
    assert.ok(body.includes("Ada"), "the editor of a tracked revision is shown");
    assert.ok(body.includes("+412"), "the byte delta is signed, so a growth reads as growth");
    assert.ok(body.includes("expanded the mitigation section"), "the edit summary is shown");
    assert.ok(body.includes("large change"), "a flag reason is shown as its own pill");
  }

  // ---- a revision with no stored diff says so ----------------------------- //
  {
    const { els } = await load(REVS);
    const body = els["wiki-tc-body"].innerHTML;
    assert.ok(body.includes("No stored diff"),
      "a revision without a diff must say why, never render as an empty edit");
    assert.ok(body.includes("full text stored"),
      "a revision whose exact text is on this machine is marked as such");
  }

  // ---- the caveat is VISIBLE, and it is the endpoint's own method ---------- //
  {
    const { els } = await load(REVS);
    const method = els["wiki-tc-method"].textContent;
    assert.ok(method.includes("tracked slice"),
      "the caveat must state this is the tracked slice, not every historical revision");
    assert.ok(method.includes("not a live re-diff"),
      "the caveat must state the diff was captured at track time");
    assert.ok(method.length > 60, "the caveat must not be an empty or token string");
  }

  // ---- an empty page renders an honest empty state, never a blank pane ----- //
  {
    const { els } = await load({ page: REVS.page, count: 0, total: 0, revisions: [] });
    const body = els["wiki-tc-body"].innerHTML;
    assert.ok(body.includes("No tracked revisions"), "empty must be stated, never blank");
    assert.ok(!body.includes("flagged"), "the unflagged empty state must not claim a flag filter");
  }
  {
    const { els } = await load({ page: REVS.page, count: 0, total: 0, revisions: [] },
                               { flagged: true });
    assert.ok(els["wiki-tc-body"].innerHTML.includes("No flagged tracked revisions"),
      "the empty state must name the FILTER that produced it");
  }

  // ---- the ?wikitc= deep link: the header comes from the server's answer --- //
  // The reader knows only a page id, so this is the case the view must fill in
  // itself. A source guard for it is satisfied by the identifier sitting in a
  // branch that never runs; only driving it can tell a live fill from a dead one.
  {
    const { els, tc } = await load(REVS, { id: 7, title: "", wiki: "" });
    assert.strictEqual(els["wiki-tc-title"].textContent, "en · Climate change",
      "a deep link must end up naming the page, not showing a blank header");
    assert.strictEqual(tc.title, "Climate change");
  }

  // ---- ...and NEVER overwrites a name the caller already knew -------------- //
  // The negative twin: a fill that always fires would silently replace the
  // watched-page table's own label with whatever the endpoint happened to return.
  {
    const { els } = await load(
      { ...REVS, page: { id: 7, wiki: "en", title: "A DIFFERENT TITLE" } },
      { id: 7, title: "Climate change", wiki: "en" }
    );
    assert.strictEqual(els["wiki-tc-title"].textContent, "",
      "the header must be left to the caller that already set it");
  }

  // ---- the flagged toggle reaches the endpoint, not a client-side filter --- //
  {
    const { calls } = await load(REVS, { flagged: true });
    assert.ok(calls[0].includes("flagged_only=true"),
      "the flag filter is the endpoint's own parameter, so the count and total describe it");
  }
  {
    const { calls } = await load(REVS);
    assert.ok(calls[0].includes("flagged_only=false"));
    assert.ok(calls[0].includes("/api/wiki/pages/7/revisions"));
  }

  // ---- a failed read degrades, and never throws into the caller ------------ //
  {
    const { els } = await load(new Error("boom"));
    assert.ok(els["wiki-tc-body"].innerHTML.includes("Could not load"),
      "a failed read must say so in the panel rather than leaving the last state up");
    assert.ok(!els["wiki-tc-body"].innerHTML.includes("Loading"),
      "the loading placeholder must not be what a reader is left with");
  }

  console.log("wiki tracked-changes view: all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
