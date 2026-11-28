// The SPA's article date with the feed's date flagged (row 457, R847), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// EXTRACTED from the shipped app-core.js rather than re-typed, so a broken helper cannot pass beside a
// correct copy. Driven from tests/test_feed_entry_date_row457.py.

"use strict";

const assert = require("assert");
const SRC = require("./app_source.js").appJs();

function extractFunction(src, name) {
  const at = src.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = src.indexOf("{", src.indexOf(")", at));
  let d = 0, j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return src.slice(at, j);
}

function extractEsc(src) {
  const at = src.indexOf("const esc = (s) =>");
  assert.ok(at !== -1, "esc not found -- was it renamed?");
  return src.slice(at, src.indexOf(";\n", at) + 1);
}

function load(i18n, dir) {
  const window = {OOI18N: i18n};
  const document = {documentElement: {dir: dir || "ltr"}};
  return new Function("window", "OOI18N", "document",
    extractEsc(SRC) + "\n" + extractFunction(SRC, "ooIsoDate") + "\n" + extractFunction(SRC, "ooArticleDateHtml")
    + "\nreturn ooArticleDateHtml;")(window, i18n, document);
}

const HOVER = "This page gave no date of its own. This is the date the source's feed gave the item, which can be "
  + "when it was posted or last updated in the feed rather than when it was first published.";

const date = load(undefined);

// The article's own date: exactly as before, and the feed's date never beside it.
assert.strictEqual(date({published_at: "2026-11-20T08:00:00"}), "2026-11-20");
assert.strictEqual(date({published_at: "2026-11-20T08:00:00", feed_entry_published_at: "2026-11-01T00:00:00"}), "2026-11-20");

// No date of its own: the feed's date, always flagged, with why on hover.
const feed = date({published_at: null, feed_entry_published_at: "2026-11-19T22:15:00"});
assert.ok(feed.startsWith("2026-11-19 <span class=\"muted feed-date\" title=\""), feed);
assert.ok(feed.includes(">· the feed&#39;s date</span>"), feed);
assert.ok(feed.includes("title=\"" + HOVER.replace(/'/g, "&#39;") + "\""), feed);

// Neither: nothing, so a caller that says "undated" still does.
for (const a of [{}, {published_at: null}, {published_at: null, feed_entry_published_at: null}, null, undefined]) {
  assert.strictEqual(date(a), "", JSON.stringify(a));
}

// Values are escaped, never read as markup.
const hostile = date({published_at: "<b>x</b>"});
assert.ok(!hostile.includes("<b>"), hostile);

// Under a translation both strings go through the engine.
const seen = [];
const fr = load({t: (s) => { seen.push(s); return "[fr] " + s; }});
const out = fr({feed_entry_published_at: "2026-11-19T22:15:00"});
assert.ok(out.includes("[fr] the feed&#39;s date"), out);
assert.deepStrictEqual(seen.sort(), [HOVER, "the feed's date"].sort());

// Right to left: the date keeps its isolate, as ooIsoDate gives every other date.
const rtl = load(undefined, "rtl")({feed_entry_published_at: "2026-11-19T22:15:00"});
assert.ok(rtl.startsWith("⁨2026-11-19⁩ "), JSON.stringify(rtl));

console.log("feed_entry_date_node_test: ok");
