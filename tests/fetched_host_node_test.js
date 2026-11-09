// The SPA's "fetched from another site" note, run as REAL code (queue item 61, R635).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// EXTRACTED from the shipped modules rather than re-typed, so a broken helper cannot pass
// beside a correct copy. Driven from tests/test_fetched_host_item61.py.

"use strict";

const assert = require("assert");
const SRC = require("./app_source.js").appJs();

// The standalone /investigate page does not load the engine, so it carries its own copy of the note.
const INVESTIGATE = require("fs").readFileSync(
  require("path").join(__dirname, "..", "src", "static", "investigate.js"), "utf-8");

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

function extractEsc(src, head) {
  const at = src.indexOf(head);
  assert.ok(at !== -1, "esc not found -- was it renamed?");
  return src.slice(at, src.indexOf(";\n", at) + 1);
}

function loadFrom(src, escHead, name, i18n) {
  const window = {OOI18N: i18n};
  return new Function("window", "OOI18N",
    extractEsc(src, escHead) + "\n" + extractFunction(src, name) + "\nreturn " + name + ";")(window, i18n);
}

const COPIES = [
  ["app-core.js", (i18n) => loadFrom(SRC, "const esc = (s) =>", "ooFetchedOffSiteNote", i18n)],
  ["investigate.js", (i18n) => loadFrom(INVESTIGATE, "const esc = s =>", "offSiteNote", i18n)],
];

for (const [where, load] of COPIES) {
  // No i18n engine: the English key is the text.
  const note = load(undefined);

  // Another site: the host, escaped, after a separator (so the source never reads as the fetcher), the reason on hover.
  const off = note({fetched_host: "other.example", fetched_off_site: true});
  assert.ok(off.startsWith(" · <span class=\"muted fetched-off-site\" title=\""), off);
  assert.ok(off.includes(">fetched from other.example</span>"), off);
  assert.ok(off.includes("title=\"This article is credited to the source, but the stored page was fetched from another site.\""), off);

  // The host is data from the network: it is escaped, never read as markup.
  const hostile = note({fetched_host: "a<b>\"'&.example", fetched_off_site: true});
  assert.ok(hostile.includes("fetched from a&lt;b&gt;&quot;&#39;&amp;.example"), hostile);
  assert.ok(!hostile.includes("<b>"), hostile);

  // Nothing is said unless the server said "another site" and named the host.
  for (const a of [
    {fetched_host: "www.good.example", fetched_off_site: false},
    {fetched_host: "other.example", fetched_off_site: null},
    {fetched_host: "other.example"},
    {fetched_host: null, fetched_off_site: true},
    {fetched_host: "", fetched_off_site: true},
    {fetched_host: "other.example", fetched_off_site: "true"},
    {},
    null,
    undefined,
  ]) {
    assert.strictEqual(note(a), "", where + " " + JSON.stringify(a));
  }

  // Under a translation both strings go through the engine, the host into the frame.
  const seen = [];
  const fr = load({
    t: (s) => { seen.push(s); return "[fr] " + s; },
    tf: (s, v) => { seen.push(s); return "récupéré depuis " + v.host; },
  });
  const frOut = fr({fetched_host: "other.example", fetched_off_site: true});
  assert.ok(frOut.includes(">récupéré depuis other.example</span>"), frOut);
  assert.ok(frOut.includes("title=\"[fr] This article is credited to the source"), frOut);
  assert.deepStrictEqual(seen.sort(), [
    "This article is credited to the source, but the stored page was fetched from another site.",
    "fetched from {host}",
  ]);
}

console.log("fetched_host_node_test: ok");
