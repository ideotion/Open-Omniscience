// The Insights header when the index scans are not known yet (audit 0.5.0, A-002), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// /api/insights/status answers the totals at once and runs the two mention-index scans in the background, so
// indexed_articles / remaining / mentions are null with a named state until a pass lands. A null painted through
// animateCount would read "0 indexed": a zero standing for "not known". The words are the Library tile's keys (already
// translated), and the long form rides the hover bubble. EXTRACTED from the shipped modules, never re-typed.

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

const mark = (s) => "«" + s + "»";
const tfMark = (s, v) => mark(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m));
const I18N = { t: mark, tf: tfMark };

// A tiny DOM: elements by id, with dataset, textContent, title, className, innerHTML.
const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, dataset: {}, textContent: "", title: "", className: "", innerHTML: "", removeAttribute(a) { if (a === "title") this.title = ""; } };
  return els[id];
}
const animated = [];

const src = [
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}",
  "const $ = (id) => el(id);",
  "function animateCount(e, to) { animated.push([e.id, to]); e.dataset.v = String(to); e.textContent = String(to); }",
  extract("fmtNum"),
  extract("_insUnknownText"),
  extract("_insCountsNote"),
  extract("_insStatusFrame"),
  extract("_insRemainingHtml"),
  extract("_paintInsStatus"),
  "return { _insStatusFrame, _insRemainingHtml, _paintInsStatus, _insCountsNote };",
].join("\n");
const mod = new Function("window", "OOI18N", "el", "animated", src)({ OOI18N: I18N }, I18N, el, animated);

let n = 0;
function test(name, fn) { fn(); n++; console.log("ok  - " + name); }

const totals = { total_articles: 120, keywords: 900, entities: 40 };

test("a pass that has not landed paints 'counting…', never a zero, and does not animate the unknown", () => {
  const s = { ...totals, indexed_articles: null, remaining: null, mentions: null, index_counts_state: "computing", pending_since: null };
  const html = mod._insStatusFrame(s);
  assert.ok(html.includes("«counting…»"), html);
  assert.ok(!html.includes('id="ins-n-indexed" data-v="0">0'), "an unknown indexed count must not read as 0");
  mod._paintInsStatus(s);
  assert.strictEqual(els["ins-n-indexed"].textContent, "«counting…»");
  assert.strictEqual(els["ins-n-mentions"].textContent, "«counting…»");
  assert.ok(!animated.some(([id]) => id === "ins-n-indexed" || id === "ins-n-mentions"), "null is not tweened from zero");
  assert.deepStrictEqual(animated.map(([id]) => id).sort(), ["ins-n-entities", "ins-n-keywords", "ins-n-total"], "the exact totals still animate");
  assert.strictEqual(els["ins-remaining"].innerHTML, "", "no '0 to index' for an unknown remaining");
  assert.ok(els["ins-pill"].title.includes("«Counting every keyword mention in the background since"), els["ins-pill"].title);
  assert.ok(els["ins-pill"].title.includes("—"), "an unknown start is a dash, not the epoch");
});

test("a failed pass says 'not counted' and names the reason and the retry window on hover", () => {
  const s = { ...totals, indexed_articles: null, remaining: null, mentions: null, index_counts_state: "failed",
    index_counts_failure: { kind: "statement-deadline", deadline_s: 400, at: "2026-10-26T10:00:00+00:00", retry_after_s: 1200 } };
  mod._paintInsStatus(s);
  assert.strictEqual(els["ins-n-indexed"].textContent, "«not counted»");
  const note = els["ins-pill"].title;
  assert.ok(note.includes("«passed its 400 s limit»") || note.includes("passed its 400 s limit"), note);
  assert.ok(note.includes("20 min") || note.includes("after 20"), note);
});

test("a counted pass paints the numbers and states when they were counted and how long they are carried", () => {
  const s = { ...totals, indexed_articles: 100, remaining: 20, mentions: 5000, index_counts_state: "counted",
    index_counts_computed_at: "2026-10-26T10:00:00+00:00", index_counts_recount_after_s: 1320 };
  animated.length = 0;
  mod._paintInsStatus(s);
  assert.ok(animated.some(([id, v]) => id === "ins-n-indexed" && v === 100));
  assert.ok(animated.some(([id, v]) => id === "ins-n-mentions" && v === 5000));
  assert.strictEqual(els["ins-pill"].className, "pill warn");
  assert.ok(els["ins-remaining"].innerHTML.includes("<strong>20</strong>"));
  assert.ok(els["ins-pill"].title.includes("22 min"), els["ins-pill"].title);
  assert.strictEqual(els["ins-n-mentions"].title, els["ins-pill"].title);
});

test("a payload from before this change (no state field) paints exactly as it did", () => {
  const s = { ...totals, indexed_articles: 7, remaining: 0, mentions: 31 };
  animated.length = 0;
  mod._paintInsStatus(s);
  assert.ok(animated.some(([id, v]) => id === "ins-n-indexed" && v === 7));
  assert.strictEqual(els["ins-pill"].className, "pill ok");
  assert.strictEqual(els["ins-pill"].title, "", "no state, no note");
});

console.log(`${n} checks passed`);
