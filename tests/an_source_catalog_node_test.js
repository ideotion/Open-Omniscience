// The analysis window's Sources catalogue cell — run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// This exists because the source-text version of the same guard was VACUOUS. The
// retirement note claims the #an window is a strict superset of the retired #corpus-win
// modal; for Sources it was not, and the first repair named "country / region / language
// / type / tags" and shipped three of the five. A test asserting the string "s.tags"
// appears in the renderer passes against code that reads s.tags and throws it away —
// which is exactly the mutant that survived it. So the cell is executed instead.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  // The real helpers are display-name lookups; stubbed so the assertions read the
  // renderer's own behaviour rather than the catalogue's contents.
  "function ooRegionName(code, fallback){ return 'CC:' + String(code); }\n" +
  "function ooLangName(code, fallback){ return 'LG:' + String(code); }\n" +
  extract("_anSourceCatalogHtml") + "\n";

const _anSourceCatalogHtml = new Function(src + "return _anSourceCatalogHtml;")();

// --- every catalogue field the modal showed reaches the cell -------------------- //
const full = _anSourceCatalogHtml({
  name: "Alpha", country: "fr", region: "Western Europe", language: "fr",
  source_type: "newspaper", tags: ["politics", "economy"],
});
assert.ok(full.includes("CC:fr"), "country must render");
assert.ok(full.includes("Western Europe"), "REGION must render — it rides on the row already");
assert.ok(full.includes("LG:fr"), "language must render");
assert.ok(full.includes("newspaper"), "source type must render");
assert.ok(full.includes("politics") && full.includes("economy"),
  "TAGS must render — the first repair named them and did not ship them");

// --- a source the catalogue holds nothing for says so, rather than claiming nothing -- //
assert.strictEqual(_anSourceCatalogHtml({name: "Bare"}), "—",
  "no catalogue facts must read as an em dash, never as an empty cell");
assert.strictEqual(_anSourceCatalogHtml({}), "—");
assert.strictEqual(_anSourceCatalogHtml(null), "—", "a missing row must not throw");

// --- tags alone still render, and do not leave a stray em dash beside them ------ //
const tagsOnly = _anSourceCatalogHtml({tags: ["science"]});
assert.ok(tagsOnly.includes("science"), "tags alone must still render");
assert.ok(!tagsOnly.includes("—"),
  "a row WITH tags is not a row with no catalogue facts — the em dash must not ride along");

// --- an empty tag list is not a tag ------------------------------------------- //
assert.strictEqual(_anSourceCatalogHtml({tags: []}), "—",
  "an empty tags array holds no facts and must read the same as none at all");

// --- the fields are ASSERTED values, escaped like any untrusted text ------------ //
const nasty = _anSourceCatalogHtml({region: "<script>x</script>", tags: ["<b>t</b>"]});
assert.ok(!nasty.includes("<script>"), "catalogue text must be escaped");
assert.ok(nasty.includes("&lt;b&gt;t&lt;/b&gt;"), "tag text must be escaped too");

// --- the separator stays the app's, so a two-field row reads as one line -------- //
const two = _anSourceCatalogHtml({country: "de", source_type: "agency"});
assert.ok(two.includes("·"), "multiple facts are joined by the app's middle dot");

console.log("an_source_catalog_node_test: all assertions passed");
