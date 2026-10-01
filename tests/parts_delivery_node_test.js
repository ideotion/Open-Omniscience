// The page's delivery of a numbered file set (1 MB parts, 2026-10-01), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHAT IS GUARDED is the person's side of «cap the size of each zip to 1MB … by splitting and
// numbering the files»: a set of hundreds of files must reach their disk five to a click (the
// number one upload message takes), the MANIFEST first, with no file skipped or repeated and the
// position kept between clicks; a typed part number must restart from there WITHOUT saving the
// manifest again; and the buttons must say what one click will do. None of that is visible in a
// diff, and a source grep cannot tell "five per click" from "all of them in a loop", so the
// functions are EXTRACTED from the shipped module and driven here against a fake page.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  let at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  if (APP.slice(at - 6, at) === "async ") at -= 6;
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

function constLine(name) {
  const at = APP.indexOf("const " + name + " =");
  assert.ok(at !== -1, name + " not found");
  return APP.slice(at, APP.indexOf(";", at) + 1);
}

// A fake page: elements by id, anchors that record what they were asked to download.
function makePage() {
  const els = {};
  const mk = (id, extra) => (els[id] = Object.assign({id, hidden: true, textContent: "", value: ""}, extra));
  mk("parts-bar"); mk("parts-status"); mk("parts-next"); mk("parts-rest"); mk("parts-from-wrap");
  mk("parts-from", {value: "1"});
  const clicked = [];
  const document = {
    body: {appendChild() {}},
    createElement() {
      return {click() { clicked.push({href: this.href, download: this.download}); }, remove() {}};
    },
  };
  return {els, clicked, document};
}

function load(page, opts) {
  opts = opts || {};
  const src = [
    constLine("_PARTS_PER_CLICK"),
    "let _partsSet = null;",
    extract("_partsFiles"), extract("_partsWindow"), extract("_partsNextLabel"),
    extract("_partsStatus"), extract("_partsRender"), extract("_partsOffer"), extract("_partsSave"),
    extract("partsSaveNext"), extract("partsSaveRest"), extract("_partsReady"),
    extract("downloadKeywordParts"), extract("downloadDiagnosticsVolumes"),
    "return {_partsFiles, _partsWindow, _partsNextLabel, _partsOffer, _partsSave, partsSaveNext," +
    " partsSaveRest, downloadKeywordParts, downloadDiagnosticsVolumes, state: () => _partsSet};",
  ].join("\n");
  const $ = (id) => page.els[id] || null;
  const fakeWindow = {};   // no OOI18N: the tf() fallback path, which is the boot-time state too
  // setTimeout runs at once (no real waiting), but every requested delay is recorded: the 400 ms
  // stagger between downloads is what keeps a browser from dropping the concurrent ones.
  const delays = opts.delays || [];
  return new Function("$", "document", "window", "setTimeout", "api", src)($, page.document, fakeWindow,
    (fn, ms) => { delays.push(ms); fn(); return 0; }, opts.api || (async () => { throw new Error("no api"); }));
}

function listing(parts, manifests) {
  const files = [];
  for (let i = 1; i <= parts; i++) {
    files.push({name: `oo-x-part-${String(i).padStart(3, "0")}-of-${parts}.zip`, bytes: 999999, sha256: "a", kind: "part"});
  }
  for (let i = 1; i <= manifests; i++) {
    files.push({name: manifests === 1 ? "oo-x-manifest.zip" : `oo-x-manifest-0${i}-of-0${manifests}.zip`,
                bytes: 5000, sha256: "b", kind: "manifest"});
  }
  return {files, download_base: "/api/diagnostics/keywords/parts/set1/"};
}

(async () => {
  // ---- the order: manifest first, then the parts in order, whatever order the listing came in
  {
    const page = makePage(); const api = load(page);
    const order = api._partsFiles(listing(7, 1)).map((f) => f.name);
    assert.strictEqual(order[0], "oo-x-manifest.zip", "the manifest is saved first");
    assert.deepStrictEqual(order.slice(1), listing(7, 0).files.map((f) => f.name), "parts keep their order");
    const two = api._partsFiles(listing(3, 2)).map((f) => f.kind);
    assert.deepStrictEqual(two, ["manifest", "manifest", "part", "part", "part"], "a paged manifest comes first too");
  }

  // ---- the window arithmetic never leaves the set
  {
    const page = makePage(); const api = load(page);
    assert.deepStrictEqual(api._partsWindow(12, 0, 5), {from: 0, to: 5});
    assert.deepStrictEqual(api._partsWindow(12, 10, 5), {from: 10, to: 12}, "the last click is short");
    assert.deepStrictEqual(api._partsWindow(12, 99, 5), {from: 12, to: 12}, "past the end saves nothing");
    assert.deepStrictEqual(api._partsWindow(12, -3, 5), {from: 0, to: 5});
  }

  // ---- the label says what ONE click does from here
  {
    const page = makePage(); const api = load(page);
    assert.strictEqual(api._partsNextLabel(3, 0), "Save all 3 files", "a small set saves with the one click");
    assert.strictEqual(api._partsNextLabel(5, 0), "Save all 5 files", "five is still one click");
    assert.strictEqual(api._partsNextLabel(221, 0), "Save the first 5");
    assert.strictEqual(api._partsNextLabel(221, 5), "Save the next 5");
    assert.strictEqual(api._partsNextLabel(221, 217), "Save the last 4");
    assert.strictEqual(api._partsNextLabel(221, 215), "Save the next 5", "six left: one more click after this");
    assert.strictEqual(api._partsNextLabel(221, 216), "Save the last 5");
  }

  // ---- 221 files: five to a click, nothing skipped or repeated, position kept
  {
    const page = makePage(); const api = load(page);
    const L = listing(220, 1);
    api._partsOffer(L);
    assert.strictEqual(page.els["parts-next"].textContent, "Save the first 5");
    assert.strictEqual(page.els["parts-rest"].hidden, false, "'save all the rest' is offered on a big set");
    let clicks = 0;
    while (api.state().pos < api.state().files.length) {
      const before = page.clicked.length;
      await api.partsSaveNext();
      clicks++;
      assert.ok(page.clicked.length - before <= 5, "never more than five files to a click");
      assert.ok(clicks < 100, "terminates");
    }
    assert.strictEqual(clicks, 45, "ceil(221 / 5) clicks");
    assert.strictEqual(page.clicked.length, 221, "every file saved");
    assert.strictEqual(new Set(page.clicked.map((c) => c.download)).size, 221, "none twice");
    assert.strictEqual(page.clicked[0].download, "oo-x-manifest.zip");
    assert.strictEqual(page.clicked[1].download, "oo-x-part-001-of-220.zip");
    assert.strictEqual(page.clicked[220].download, "oo-x-part-220-of-220.zip");
    assert.ok(page.clicked[2].href.startsWith("/api/diagnostics/keywords/parts/set1/oo-x-part-002-of-220"));
    assert.ok(/^All 221 files saved\./.test(page.els["parts-status"].textContent));
    assert.strictEqual(page.els["parts-next"].hidden, true, "nothing left to offer");
  }

  // ---- a set of five or fewer saves with ONE click
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(4, 1));
    assert.strictEqual(page.els["parts-rest"].hidden, true);
    await api.partsSaveNext();
    assert.strictEqual(page.clicked.length, 5);
    assert.ok(/^All 5 files saved\./.test(page.els["parts-status"].textContent));
  }

  // ---- "save all the rest": the click the person asked for, every remaining file once
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1));
    await api.partsSaveNext();
    await api.partsSaveRest();
    assert.strictEqual(page.clicked.length, 31);
    assert.strictEqual(new Set(page.clicked.map((c) => c.download)).size, 31);
  }

  // ---- a typed part number restarts there and does NOT save the manifest again
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1));
    await api.partsSaveNext();                       // manifest + parts 1-4
    assert.strictEqual(page.els["parts-from"].value, "5", "the box shows the next part to save");
    page.els["parts-from"].value = "12";             // the person types a part number
    await api.partsSaveNext();
    const names = page.clicked.slice(5).map((c) => c.download);
    assert.deepStrictEqual(names, [12, 13, 14, 15, 16].map((n) => `oo-x-part-0${n}-of-30.zip`));
    assert.ok(!names.includes("oo-x-manifest.zip"), "the manifest is not saved again");
    assert.strictEqual(page.els["parts-from"].value, "17");
  }

  // ---- an untouched box on the very first click does not skip the manifest
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1));
    assert.strictEqual(page.els["parts-from"].value, "1");
    await api.partsSaveNext();
    assert.strictEqual(page.clicked[0].download, "oo-x-manifest.zip");
  }

  // ---- a file name is never put in a URL unescaped
  {
    const page = makePage(); const api = load(page);
    api._partsOffer({files: [{name: "a b#c.zip", kind: "part"}], download_base: "/x/"});
    await api.partsSaveNext();
    assert.strictEqual(page.clicked[0].href, "/x/a%20b%23c.zip");
  }

  // ---- the downloads are staggered: a browser drops files opened in one tick
  {
    const page = makePage(); const delays = []; const api = load(page, {delays});
    api._partsOffer(listing(30, 1));
    await api.partsSaveNext();
    assert.strictEqual(page.clicked.length, 5);
    assert.ok(delays.filter((ms) => ms >= 300).length >= 5, "a wait of at least 300 ms after each file: " + delays);
  }

  // ---- the three keyword buttons and the diagnostics button, end to end against a fake api()
  {
    const page = makePage(); const calls = []; const btn = {disabled: false};
    const api = load(page, {api: async (url) => { calls.push(url); return listing(12, 1); }});
    await api.downloadKeywordParts(btn, "default");
    assert.strictEqual(calls[0], "/api/diagnostics/keywords?format=parts");
    assert.strictEqual(page.clicked.length, 0, "a build spent the click: nothing is saved until the person clicks again");
    assert.ok(/^13 files of at most 1 MB each are ready: the manifest and 12 numbered parts\./.test(page.els["parts-status"].textContent),
      page.els["parts-status"].textContent);
    assert.strictEqual(page.els["parts-next"].textContent, "Save the first 5");
    assert.strictEqual(btn.disabled, false, "the button is usable again");
    await api.partsSaveNext();
    assert.strictEqual(page.clicked.length, 5);
    assert.strictEqual(page.clicked[0].download, "oo-x-manifest.zip");
  }
  {
    const page = makePage(); const calls = [];
    const api = load(page, {api: async (url) => { calls.push(url); return listing(12, 1); }});
    await api.downloadKeywordParts({disabled: false}, "all");
    assert.ok(/format=parts/.test(calls[0]) && /per_lang=1000000000/.test(calls[0]) && /max_mb=0/.test(calls[0]),
      "'All keywords' asks for every keyword and no total cap: " + calls[0]);
  }
  {
    const page = makePage(); const calls = []; const btn = {disabled: false};
    const api = load(page, {api: async (url) => { calls.push(url); return listing(12, 1); }});
    await api.downloadKeywordParts(btn, "again");
    assert.strictEqual(calls[0], "/api/diagnostics/keywords/parts/latest");
    assert.strictEqual(page.clicked.length, 5, "'again' saves the first five at once: the click that asked is still alive");
    assert.strictEqual(page.clicked[0].download, "oo-x-manifest.zip");
    assert.strictEqual(page.els["parts-next"].textContent, "Save the next 5");
    assert.strictEqual(btn.disabled, false);
  }
  {
    const page = makePage(); const btn = {disabled: false};
    const api = load(page, {api: async () => { const e = new Error("gone"); e.status = 404; throw e; }});
    await api.downloadKeywordParts(btn, "again");
    assert.strictEqual(page.clicked.length, 0);
    assert.ok(/^No keyword files are kept on this machine yet/.test(page.els["parts-status"].textContent));
    assert.strictEqual(btn.disabled, false, "a refusal leaves the button usable");
    assert.strictEqual(page.els["parts-next"].hidden, true, "nothing to save is offered");
  }
  {
    const page = makePage(); const calls = [];
    const api = load(page, {api: async (url) => { calls.push(url); return listing(8, 1); }});
    await api.downloadDiagnosticsVolumes({disabled: false});
    assert.strictEqual(calls[0], "/api/diagnostics/all-job/volumes");
    assert.strictEqual(page.clicked.length, 5, "'All diagnostics, again' saves the first five at once");
    for (const [status, words] of [[404, /^No archive to split yet/], [409, /^A build is running/], [500, /^Could not split the archive/]]) {
      const pg = makePage();
      const a2 = load(pg, {api: async () => { const e = new Error("boom"); e.status = status; throw e; }});
      await a2.downloadDiagnosticsVolumes({disabled: false});
      assert.ok(words.test(pg.els["parts-status"].textContent), status + ": " + pg.els["parts-status"].textContent);
      assert.strictEqual(pg.clicked.length, 0);
    }
  }

  console.log("all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
