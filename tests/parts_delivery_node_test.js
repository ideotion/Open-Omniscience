// The page's delivery of a numbered file set (1 MB parts, 2026-10-01), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHAT IS GUARDED is the person's side of «cap the size of each zip to 1MB … by splitting and
// numbering the files»: a set of hundreds of files must reach their disk five to a click (the
// number one upload message takes), the MANIFEST first, with no file skipped or repeated and the
// position kept between clicks; a typed part number must restart from there (through its own
// button, or through "again") WITHOUT saving the manifest again; a second click while files are
// on their way, or a set that another button replaced, must neither repeat files nor write the
// old set's status; no message may say a file was SAVED (the page only asks the browser); and the
// buttons must say what one click will do. None of that is visible in a diff, and a source grep
// cannot tell "five per click" from "all of them in a loop", so the functions are EXTRACTED from
// the shipped module and driven here against a fake page.

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
  mk("parts-bar"); mk("parts-status"); mk("parts-next"); mk("parts-rest"); mk("parts-from-wrap"); mk("parts-from-go");
  mk("parts-from", {value: "1"}); mk("all-diag-status");
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
    constLine("_PARTS_PER_CLICK"), constLine("_ALL_DIAG_POLL_CEILING_MS"),
    "let _partsSet = null;", "let _partsGen = 0;", "let _partsBusy = 0;",
    extract("_partsFiles"), extract("_partsWindow"), extract("_partsNextLabel"),
    extract("_partsStatus"), extract("_partsRender"), extract("_partsOffer"), extract("_partsTyped"),
    extract("_partsSave"), extract("partsSaveNext"), extract("partsSaveRest"), extract("partsSaveFrom"),
    extract("_partsReady"), extract("downloadKeywordParts"), extract("downloadDiagnosticsVolumes"),
    extract("runAllDiagnostics"),
    "return {_partsFiles, _partsWindow, _partsNextLabel, _partsOffer, _partsSave, partsSaveNext," +
    " partsSaveRest, partsSaveFrom, downloadKeywordParts, downloadDiagnosticsVolumes, runAllDiagnostics," +
    " state: () => _partsSet};",
  ].join("\n");
  const $ = (id) => page.els[id] || null;
  const fakeWindow = {};   // no OOI18N: the tf() fallback path, which is the boot-time state too
  // setTimeout runs at once (no real waiting), but every requested delay is recorded: the 400 ms
  // stagger between downloads is what keeps a browser from dropping the concurrent ones.
  // `opts.hold` (an array) holds the timers instead of running them, so a test can change the page
  // while a save is waiting between two files.
  const delays = opts.delays || [];
  return new Function("$", "document", "window", "setTimeout", "api", src)($, page.document, fakeWindow,
    (fn, ms) => { delays.push(ms); if (opts.hold) opts.hold.push(fn); else fn(); return 0; },
    opts.api || (async () => { throw new Error("no api"); }));
}

// The name listing() gives part n of `of` (three digits, as the real set pads them at this size).
function partName(n, of) { return `oo-x-part-${String(n).padStart(3, "0")}-of-${of}.zip`; }

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

const READY_SENTENCE = "The archive is ready. Press “All diagnostics, again” to save it as numbered files.";

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
    assert.strictEqual(api._partsNextLabel(221, 220), "Save the last file", "never 'the last 1'");
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
    assert.ok(/^Asked your browser to save all 221 files\./.test(page.els["parts-status"].textContent),
      page.els["parts-status"].textContent);
    assert.ok(!/ saved/.test(page.els["parts-status"].textContent.split(".")[0]), "the page asks, it does not claim a file was saved");
    assert.strictEqual(page.els["parts-next"].hidden, true, "nothing left to offer");
  }

  // ---- a set of five or fewer saves with ONE click
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(4, 1));
    assert.strictEqual(page.els["parts-rest"].hidden, true);
    await api.partsSaveNext();
    assert.strictEqual(page.clicked.length, 5);
    assert.ok(/^Asked your browser to save all 5 files\./.test(page.els["parts-status"].textContent));
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

  // ---- a typed part number restarts there, through its own button, and does NOT save the manifest again
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1), "keywords");
    await api.partsSaveNext();                       // manifest + parts 1-4
    assert.strictEqual(page.els["parts-status"].textContent, "Asked your browser to save 5 of 31 files.");
    assert.strictEqual(page.els["parts-from"].value, "5", "the box shows the next part to save");
    assert.strictEqual(page.els["parts-from-go"].hidden, false, "the button that uses the box is there");
    page.els["parts-from"].value = "12";             // the person types a part number...
    await api.partsSaveNext();                       // ...and presses the ordinary button: the box is not read
    assert.deepStrictEqual(page.clicked.slice(5).map((c) => c.download),
      [5, 6, 7, 8, 9].map((n) => partName(n, 30)),
      "'Save the next 5' continues where the last click stopped");
    page.els["parts-from"].value = "12";
    await api.partsSaveFrom();
    const names = page.clicked.slice(10).map((c) => c.download);
    assert.deepStrictEqual(names, [12, 13, 14, 15, 16].map((n) => partName(n, 30)));
    assert.ok(!names.includes("oo-x-manifest.zip"), "the manifest is not saved again");
    assert.strictEqual(page.els["parts-from"].value, "17");
    assert.strictEqual(page.els["parts-status"].textContent, "Asked your browser to save 15 of 31 files.",
      "the count is the files asked for (10 + 5), not the position (17)");
  }

  // ---- files are counted by the files asked for, not by clicks: parts 3 and 4 sent again are not counted twice
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1), "keywords");
    await api.partsSaveNext();                       // files 0-4: the manifest and parts 1-4
    page.els["parts-from"].value = "3";
    await api.partsSaveFrom();                       // parts 3-7: files 3-7, of which 3 and 4 were sent
    assert.strictEqual(page.clicked.length, 10);
    assert.strictEqual(page.els["parts-status"].textContent, "Asked your browser to save 8 of 31 files.");
  }

  // ---- a set replaced during the LAST wait of a save does not get the old save's status
  {
    const page = makePage(); const hold = []; const api = load(page, {hold});
    api._partsOffer(listing(3, 1), "keywords");      // four files: one click saves them all
    const old = api.partsSaveNext();
    for (let k = 0; k < 4; k++) {                    // release the first three waits, stop at the fourth
      for (let spin = 0; spin < 5 && hold.length === 0; spin++) await Promise.resolve();
      assert.strictEqual(hold.length, 1, "a wait is pending after file " + (k + 1));
      if (k < 3) hold.shift()();
    }
    assert.strictEqual(page.clicked.length, 4, "all four files were handed over; the last wait is pending");
    api._partsOffer(listing(2, 1), "keywords");      // another button took the bar...
    page.els["parts-status"].textContent = "NEW SET";
    hold.shift()();                                  // ...and the old loop's last wait ends
    await old;
    assert.strictEqual(page.els["parts-status"].textContent, "NEW SET", "the old save wrote nothing over the new set");
    assert.strictEqual(api.state().pos, 0, "and moved nothing in it");
  }
  // ---- a number past the end is clamped and SAID; a missing or zero number saves nothing and says what to type
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1), "keywords");
    page.els["parts-from"].value = "40";
    await api.partsSaveFrom();
    assert.deepStrictEqual(page.clicked.map((c) => c.download), [partName(30, 30)],
      "40 on a 30-part set starts at the last part and saves only it");
    assert.ok(/^There are only 30 parts, so saving starts at the last part\. /.test(page.els["parts-status"].textContent),
      page.els["parts-status"].textContent);
    for (const bad of ["", "0", "-4", "abc"]) {
      const before = page.clicked.length;
      page.els["parts-from"].value = bad;
      await api.partsSaveFrom();
      assert.strictEqual(page.clicked.length, before, "nothing is saved for " + JSON.stringify(bad));
      assert.strictEqual(page.els["parts-status"].textContent, "Type a part number from 1 to 30.");
    }
  }

  // ---- after every file was handed over the box is not a dead end: it names the last part, and the button resends from it
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(12, 1), "keywords");
    await api.partsSaveRest();
    assert.strictEqual(page.clicked.length, 13);
    assert.strictEqual(page.els["parts-next"].hidden, true);
    assert.strictEqual(page.els["parts-rest"].hidden, true);
    assert.strictEqual(page.els["parts-from-wrap"].hidden, false, "the box stays");
    assert.strictEqual(page.els["parts-from-go"].hidden, false, "and so does the button that uses it");
    assert.strictEqual(page.els["parts-from"].value, "12", "never '13 of 12'");
    page.els["parts-from"].value = "7";
    await api.partsSaveFrom();
    assert.deepStrictEqual(page.clicked.slice(13).map((c) => c.download),
      [7, 8, 9, 10, 11].map((n) => partName(n, 12)));
    assert.strictEqual(page.els["parts-status"].textContent, "Asked your browser to save those files again.",
      "a part sent again is not counted twice, and the line says what the click did");
  }

  // ---- a second click while files are on their way does nothing (no doubled downloads, buttons disabled meanwhile)
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1), "keywords");
    const first = api.partsSaveNext();
    assert.strictEqual(page.els["parts-next"].disabled, true, "the buttons are disabled while files are on their way");
    assert.strictEqual(page.els["parts-from-go"].disabled, true);
    assert.strictEqual(page.els["parts-rest"].disabled, true, "so is 'save all the rest'");
    const second = api.partsSaveNext();
    await Promise.all([first, second]);
    assert.strictEqual(page.clicked.length, 5, "two clicks, five files");
    assert.strictEqual(new Set(page.clicked.map((c) => c.download)).size, 5);
    assert.strictEqual(page.els["parts-next"].disabled, false, "usable again");
    assert.strictEqual(api.state().pos, 5);
  }

  // ---- a set that another button replaced is not finished, and its status is never written
  {
    const page = makePage();
    const api = load(page, {api: async () => listing(3, 1)});
    api._partsOffer(listing(30, 1), "keywords");
    const old = api.partsSaveRest();
    await api.downloadKeywordParts({disabled: false}, "default");
    await old;
    assert.ok(page.clicked.length < 31, "the old loop stopped: " + page.clicked.length);
    assert.ok(/^4 files of at most 1 MB each are ready \(manifest: 1, numbered parts: 3\)\./.test(page.els["parts-status"].textContent),
      page.els["parts-status"].textContent);
    assert.strictEqual(api.state().files.length, 4);
  }

  // ---- a build that is overtaken by a newer button leaves the bar to the newer one
  {
    const page = makePage(); const waiting = [];
    const api = load(page, {api: (url) => url.includes("max_mb=0")
      ? Promise.resolve(listing(8, 1)) : new Promise((resolve) => waiting.push(() => resolve(listing(3, 1))))});
    const slow = api.downloadKeywordParts({disabled: false}, "default");
    await api.downloadKeywordParts({disabled: false}, "all");
    assert.strictEqual(api.state().pcount, 8);
    waiting[0]();
    await slow;
    assert.strictEqual(api.state().pcount, 8, "the slow build finished later and did not take the bar back");
    assert.ok(/numbered parts: 8\)/.test(page.els["parts-status"].textContent), page.els["parts-status"].textContent);
  }

  // ---- "again" starts at the part number the person typed, but only for the same kind of set
  {
    const page = makePage(); const calls = [];
    const api = load(page, {api: async (url) => { calls.push(url); return listing(12, 1); }});
    await api.downloadKeywordParts({disabled: false}, "default");
    page.els["parts-from"].value = "9";
    await api.downloadKeywordParts({disabled: false}, "again");
    assert.deepStrictEqual(page.clicked.map((c) => c.download),
      [9, 10, 11, 12].map((n) => partName(n, 12)),
      "typed 9 then 'again': parts 9-12, no manifest");
    // an untouched box is not a typed number: the manifest goes first
    const pg2 = makePage();
    const a2 = load(pg2, {api: async () => listing(12, 1)});
    await a2.downloadKeywordParts({disabled: false}, "default");
    await a2.downloadKeywordParts({disabled: false}, "again");
    assert.strictEqual(pg2.clicked[0].download, "oo-x-manifest.zip");
    // a number typed for the keyword files is not applied to the diagnostics archive
    const pg3 = makePage();
    const a3 = load(pg3, {api: async () => listing(12, 1)});
    await a3.downloadKeywordParts({disabled: false}, "default");
    pg3.els["parts-from"].value = "9";
    await a3.downloadDiagnosticsVolumes({disabled: false});
    assert.strictEqual(pg3.clicked[0].download, "oo-x-manifest.zip");
    // ...and one typed for the archive is applied to "again" of the archive
    pg3.els["parts-from"].value = "6";
    await a3.downloadDiagnosticsVolumes({disabled: false});
    assert.strictEqual(pg3.clicked[5].download, partName(6, 12), pg3.clicked.map((c) => c.download).join());
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
    assert.ok(/^13 files of at most 1 MB each are ready \(manifest: 1, numbered parts: 12\)\./.test(page.els["parts-status"].textContent),
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


  // ---- a part sent again is a side trip: "Save the next 5" goes on from the furthest file, not back over saved ones
  {
    const page = makePage(); const api = load(page);
    api._partsOffer(listing(30, 1), "keywords");
    for (let k = 0; k < 4; k++) await api.partsSaveNext();      // files 0-19: the manifest and parts 1-19
    assert.strictEqual(api.state().pos, 20);
    page.els["parts-from"].value = "3";
    await api.partsSaveFrom();                                  // parts 3-7 again
    assert.deepStrictEqual(page.clicked.slice(20).map((c) => c.download), [3, 4, 5, 6, 7].map((n) => partName(n, 30)));
    assert.strictEqual(api.state().pos, 20, "the side trip did not pull the position back");
    assert.strictEqual(page.els["parts-next"].textContent, "Save the next 5");
    assert.strictEqual(page.els["parts-from"].value, "20", "the box names the next part the ordinary button saves");
    await api.partsSaveNext();
    assert.deepStrictEqual(page.clicked.slice(25).map((c) => c.download), [20, 21, 22, 23, 24].map((n) => partName(n, 30)),
      "the next click goes on at part 20, not back at part 8");
    // and from a fresh set a typed number still moves the position on (a person resuming after a crash)
    const pg2 = makePage(); const a2 = load(pg2);
    a2._partsOffer(listing(30, 1), "keywords");
    pg2.els["parts-from"].value = "12";
    await a2.partsSaveFrom();
    assert.strictEqual(a2.state().pos, 17, "typing 12 on an untouched set resumes there: the next click saves part 17");
  }

  // ---- keyword build overtaken: its REFUSAL does not write over the newer set either
  {
    const page = makePage(); const waiting = [];
    const api = load(page, {api: (url) => url.includes("max_mb=0")
      ? Promise.resolve(listing(8, 1)) : new Promise((_res, rej) => waiting.push(() => rej(new Error("slow refusal"))))});
    const slow = api.downloadKeywordParts({disabled: false}, "default");
    await api.downloadKeywordParts({disabled: false}, "all");
    waiting[0]();
    await slow;
    assert.ok(/numbered parts: 8\)/.test(page.els["parts-status"].textContent),
      "the old build's refusal said nothing: " + page.els["parts-status"].textContent);
  }

  // ---- the diagnostics split overtaken by a newer button: neither its refusal nor its files take the bar
  {
    for (const outcome of ["refuse", "succeed"]) {
      const page = makePage(); const waiting = [];
      const api = load(page, {api: (url) => url.includes("all-job/volumes")
        ? new Promise((res, rej) => waiting.push(() => {
            if (outcome === "refuse") { const e = new Error("boom"); e.status = 404; rej(e); } else res(listing(3, 1));
          }))
        : Promise.resolve(listing(8, 1))});
      const slow = api.downloadDiagnosticsVolumes({disabled: false});
      await api.downloadKeywordParts({disabled: false}, "all");
      waiting[0]();
      await slow;
      assert.strictEqual(api.state().kind, "keywords", outcome + ": the newer keyword set keeps the bar");
      assert.strictEqual(api.state().pcount, 8);
      assert.ok(/numbered parts: 8\)/.test(page.els["parts-status"].textContent),
        outcome + ": " + page.els["parts-status"].textContent);
      assert.strictEqual(page.clicked.length, 0, outcome + ": the old split saved nothing");
    }
  }

  // ---- a finished All diagnostics build replaces the bar like any other button: it takes a number, and who keeps the bar is ONE rule (cases below)
  // The fake api answers the build's start, one "done" poll and the split; `holdKeyword` holds a keyword build.
  function buildApi(holdKeyword) {
    return (url) => {
      if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
      if (url === "/api/diagnostics/all-job/status") return Promise.resolve({state: "done", ready: true});
      if (url === "/api/diagnostics/all-job/volumes") return Promise.resolve(listing(4, 1));
      return holdKeyword ? new Promise((resolve) => holdKeyword.push(() => resolve(listing(3, 1)))) : Promise.resolve(listing(3, 1));
    };
  }
  {
    // an older keyword build still on its way when the diagnostics build finishes does not take the bar back
    const page = makePage(); const held = [];
    const api = load(page, {api: buildApi(held)});
    const keyword = api.downloadKeywordParts({disabled: false}, "default");   // waits
    await api.runAllDiagnostics({disabled: false});
    assert.strictEqual(api.state().kind, "diagnostics");
    held[0]();
    await keyword;
    assert.strictEqual(api.state().kind, "diagnostics", "the keyword build that landed later left the bar to the archive");
    assert.ok(/numbered parts: 3\)/.test(page.els["parts-status"].textContent) === false, page.els["parts-status"].textContent);
  }
  {
    // a set the person has begun to save is never cut: the finished archive waits, and the five files all go out
    const page = makePage(); const hold = [];
    const api = load(page, {hold, api: buildApi(null)});
    api._partsOffer(listing(30, 1), "keywords");
    const saving = api.partsSaveNext();
    const build = api.runAllDiagnostics({disabled: false});
    let finished = 0; saving.then(() => finished++); build.then(() => finished++);
    for (let spin = 0; spin < 400 && finished < 2; spin++) {
      await Promise.resolve();
      if (hold.length) hold.shift()();
    }
    assert.strictEqual(finished, 2, "both finished");
    assert.strictEqual(page.clicked.length, 5, "the save in flight was not cut");
    assert.strictEqual(api.state().kind, "keywords", "and the archive did not take the bar from it");
    assert.strictEqual(page.els["all-diag-status"].textContent, READY_SENTENCE);
  }
  {
    // a keyword set landed earlier and the person saved five of its files: the finished archive waits too
    const page = makePage();
    const api = load(page, {api: buildApi(null)});
    await api.downloadKeywordParts({disabled: false}, "default");      // before the build was asked for
    await api.partsSaveNext();
    await api.runAllDiagnostics({disabled: false});
    assert.strictEqual(api.state().kind, "keywords", "five files handed over: the person's work stays");
    assert.strictEqual(page.els["all-diag-status"].textContent, READY_SENTENCE);
    // ...while an unsaved older set is simply replaced by the archive that was asked for later
    const pg2 = makePage(); const a2 = load(pg2, {api: buildApi(null)});
    await a2.downloadKeywordParts({disabled: false}, "default");
    await a2.runAllDiagnostics({disabled: false});
    assert.strictEqual(a2.state().kind, "diagnostics", "an unsaved set asked for before the build gives way to it");
    assert.strictEqual(pg2.els["all-diag-status"].textContent, "");
  }
  {
    // a press made while the build ran that ended with NOTHING to show leaves the bar to the archive
    for (const press of ["again-409", "keyword-refused", "keyword-404"]) {
      const page = makePage(); const statusHeld = []; let volumeCalls = 0;
      const api = load(page, {api: (url) => {
        if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
        if (url === "/api/diagnostics/all-job/status") return new Promise((resolve) => statusHeld.push(() => resolve({state: "done", ready: true})));
        if (url === "/api/diagnostics/all-job/volumes") {
          volumeCalls++;
          if (volumeCalls === 1 && press === "again-409") { const e = new Error("build running"); e.status = 409; return Promise.reject(e); }
          return Promise.resolve(listing(4, 1));
        }
        const e = new Error("refused"); e.status = press === "keyword-404" ? 404 : 500; return Promise.reject(e);
      }});
      const diag = api.runAllDiagnostics({disabled: false});
      for (let spin = 0; spin < 10 && statusHeld.length === 0; spin++) await Promise.resolve();
      if (press === "again-409") await api.downloadDiagnosticsVolumes({disabled: false});
      else await api.downloadKeywordParts({disabled: false}, press === "keyword-404" ? "again" : "default");
      assert.strictEqual(api.state(), null, press + ": the press left no set on the bar");
      statusHeld[0]();
      await diag;
      assert.strictEqual(api.state().kind, "diagnostics", press + ": the finished archive took the free bar");
      assert.strictEqual(api.state().pcount, 4);
    }
  }
  {
    // "All diagnostics, again" answers the "archive is ready, press again" line: it is cleared
    const page = makePage();
    const api = load(page, {api: async () => listing(4, 1)});
    page.els["all-diag-status"].textContent = READY_SENTENCE;
    await api.downloadDiagnosticsVolumes({disabled: false});
    assert.strictEqual(page.els["all-diag-status"].textContent, "");
  }


  // ---- a button pressed WHILE the diagnostics build runs is the newer request: the finished archive does not take the bar from it
  {
    for (const keywordFinishesFirst of [false, true]) {
      const page = makePage(); const statusHeld = []; const keywordHeld = [];
      const api = load(page, {api: (url) => {
        if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
        if (url === "/api/diagnostics/all-job/status") return new Promise((resolve) => statusHeld.push(() => resolve({state: "done", ready: true})));
        if (url === "/api/diagnostics/all-job/volumes") return Promise.resolve(listing(4, 1));
        return new Promise((resolve) => keywordHeld.push(() => resolve(listing(3, 1))));
      }});
      const diag = api.runAllDiagnostics({disabled: false});
      for (let spin = 0; spin < 10 && statusHeld.length === 0; spin++) await Promise.resolve();
      assert.strictEqual(statusHeld.length, 1, "the build is being polled");
      const keyword = api.downloadKeywordParts({disabled: false}, "default");   // pressed while it runs
      for (let spin = 0; spin < 10 && keywordHeld.length === 0; spin++) await Promise.resolve();
      if (keywordFinishesFirst) { keywordHeld[0](); await keyword; }
      statusHeld[0]();
      await diag;
      assert.strictEqual(page.els["all-diag-status"].textContent, READY_SENTENCE, "the archive says it is ready and what to press");
      if (!keywordFinishesFirst) { keywordHeld[0](); await keyword; }
      assert.strictEqual(api.state().kind, "keywords", "the keyword set the person asked for last has the bar");
      assert.ok(/numbered parts: 3\)/.test(page.els["parts-status"].textContent), page.els["parts-status"].textContent);
    }
  }


  // ---- a diagnostics set on the bar when the build finishes is of the PREVIOUS archive, whose files the new split replaced: dead, so the archive takes the bar
  {
    const page = makePage(); let current = listing(8, 1);
    const api = load(page, {api: (url) => {
      if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
      if (url === "/api/diagnostics/all-job/status") return Promise.resolve({state: "done", ready: true});
      return Promise.resolve(current);
    }});
    await api.downloadDiagnosticsVolumes({disabled: false});            // "again" on the old archive: five of nine files handed over
    assert.strictEqual(api.state().offered.size, 5);
    current = listing(6, 1);                                           // a new build: other files, the old ones are gone
    await api.runAllDiagnostics({disabled: false});
    assert.strictEqual(api.state().kind, "diagnostics");
    assert.strictEqual(api.state().pcount, 6, "the bar offers the new archive, not the old set's dead files");
    assert.strictEqual(page.els["all-diag-status"].textContent, "");
    // and when the bar already holds THIS archive (the person pressed "again" before the page noticed) it is left alone
    const pg2 = makePage(); const a2 = load(pg2, {api: (url) => url.startsWith("/api/diagnostics/all-job?")
      ? Promise.resolve({started: true}) : url === "/api/diagnostics/all-job/status"
        ? Promise.resolve({state: "done", ready: true}) : Promise.resolve(listing(8, 1))});
    await a2.downloadDiagnosticsVolumes({disabled: false});
    const same = a2.state();
    pg2.els["all-diag-status"].textContent = "stale";
    await a2.runAllDiagnostics({disabled: false});
    assert.strictEqual(a2.state(), same, "the same set stays: its position and what was handed over are kept");
    assert.strictEqual(a2.state().offered.size, 5);
    assert.strictEqual(pg2.els["all-diag-status"].textContent, "", "and no 'press again' line is written for an archive already fetched");
  }

  // ---- a newer press that an even newer press overtook does not keep the archive off a bar that ended up empty
  {
    const page = makePage(); const statusHeld = []; const keywordHeld = []; let volumeCalls = 0;
    const api = load(page, {api: (url) => {
      if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
      if (url === "/api/diagnostics/all-job/status") return new Promise((resolve) => statusHeld.push(() => resolve({state: "done", ready: true})));
      if (url === "/api/diagnostics/all-job/volumes") {
        volumeCalls++;
        if (volumeCalls === 1) { const e = new Error("build running"); e.status = 409; return Promise.reject(e); }
        return Promise.resolve(listing(4, 1));
      }
      return new Promise((resolve) => keywordHeld.push(() => resolve(listing(3, 1))));
    }});
    const diag = api.runAllDiagnostics({disabled: false});
    for (let spin = 0; spin < 10 && statusHeld.length === 0; spin++) await Promise.resolve();
    const keyword = api.downloadKeywordParts({disabled: false}, "all");           // slow, still in flight...
    for (let spin = 0; spin < 10 && keywordHeld.length === 0; spin++) await Promise.resolve();
    await api.downloadDiagnosticsVolumes({disabled: false});                        // ...overtaken by an "again" that is refused (409)
    assert.strictEqual(api.state(), null, "the bar is empty");
    statusHeld[0]();
    await diag;
    assert.strictEqual(api.state().kind, "diagnostics", "the finished archive took the empty bar");
    keywordHeld[0]();
    await keyword;
    assert.strictEqual(api.state().kind, "diagnostics", "and the overtaken keyword build did not take it back");
  }


  // ---- an OLDER request ending while the newest is still on its way does not clear the newest's marker
  {
    const page = makePage(); const statusHeld = []; const againHeld = []; const keywordHeld = []; let volumeCalls = 0;
    const api = load(page, {api: (url) => {
      if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
      if (url === "/api/diagnostics/all-job/status") return new Promise((resolve) => statusHeld.push(() => resolve({state: "done", ready: true})));
      if (url === "/api/diagnostics/all-job/volumes") {
        volumeCalls++;
        if (volumeCalls === 1) return new Promise((resolve) => againHeld.push(() => resolve(listing(4, 1))));
        return Promise.resolve(listing(4, 1));
      }
      return new Promise((resolve) => keywordHeld.push(() => resolve(listing(3, 1))));
    }});
    const diag = api.runAllDiagnostics({disabled: false});
    for (let spin = 0; spin < 10 && statusHeld.length === 0; spin++) await Promise.resolve();
    const again = api.downloadDiagnosticsVolumes({disabled: false});                   // the older press, in flight
    for (let spin = 0; spin < 10 && againHeld.length === 0; spin++) await Promise.resolve();
    const keyword = api.downloadKeywordParts({disabled: false}, "all");              // the newest press, in flight
    for (let spin = 0; spin < 10 && keywordHeld.length === 0; spin++) await Promise.resolve();
    againHeld[0]();
    await again;                                                                      // the older one ends, overtaken
    statusHeld[0]();
    await diag;
    assert.strictEqual(api.state(), null, "the build deferred: the newest press (the keyword build) is still on its way");
    keywordHeld[0]();
    await keyword;
    assert.strictEqual(api.state().kind, "keywords", "and the keyword set it asked for then took the bar");
  }

  {
    // the same with the roles swapped: an older KEYWORD build ends, the newest press is an "again" still on its way
    const page = makePage(); const statusHeld = []; const againHeld = []; const keywordHeld = []; let volumeCalls = 0;
    const api = load(page, {api: (url) => {
      if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
      if (url === "/api/diagnostics/all-job/status") return new Promise((resolve) => statusHeld.push(() => resolve({state: "done", ready: true})));
      if (url === "/api/diagnostics/all-job/volumes") {
        volumeCalls++;
        if (volumeCalls === 1) return new Promise((resolve) => againHeld.push(() => resolve(listing(4, 1))));
        return Promise.resolve(listing(4, 1));
      }
      return new Promise((resolve) => keywordHeld.push(() => resolve(listing(3, 1))));
    }});
    const diag = api.runAllDiagnostics({disabled: false});
    for (let spin = 0; spin < 10 && statusHeld.length === 0; spin++) await Promise.resolve();
    const keyword = api.downloadKeywordParts({disabled: false}, "all");              // the older press, in flight
    for (let spin = 0; spin < 10 && keywordHeld.length === 0; spin++) await Promise.resolve();
    const again = api.downloadDiagnosticsVolumes({disabled: false});                   // the newest press, in flight
    for (let spin = 0; spin < 10 && againHeld.length === 0; spin++) await Promise.resolve();
    keywordHeld[0]();
    await keyword;                                                                    // the older one ends, overtaken
    statusHeld[0]();
    await diag;
    assert.strictEqual(api.state(), null, "the build deferred: the newest press (an 'again') is still on its way");
    againHeld[0]();
    await again;
    assert.strictEqual(api.state().kind, "diagnostics");
  }

  // ---- the comparison with the archive on the bar is by NAME: two archives with the same number of files are still two
  {
    const page = makePage(); let stem = "oo-old";
    const L = () => { const l = listing(8, 1); l.files.forEach((f) => { f.name = f.name.replace("oo-x", stem); }); return l; };
    const api = load(page, {api: (url) => url.startsWith("/api/diagnostics/all-job?") ? Promise.resolve({started: true})
      : url === "/api/diagnostics/all-job/status" ? Promise.resolve({state: "done", ready: true}) : Promise.resolve(L())});
    await api.downloadDiagnosticsVolumes({disabled: false});            // "again" on the previous archive
    stem = "oo-new";                                                    // a new build of the same corpus: same count, new stem
    await api.runAllDiagnostics({disabled: false});
    assert.ok(api.state().files[0].name.startsWith("oo-new"),
      "the old archive's dead set was kept because its file COUNT matched: " + api.state().files[0].name);
  }

  // ---- "again" pressed AFTER the build was asked, answered with this very archive, its save still going when the poll sees "done"
  {
    const page = makePage(); const hold = []; const statusHeld = [];
    const api = load(page, {hold, api: (url) => url.startsWith("/api/diagnostics/all-job?") ? Promise.resolve({started: true})
      : url === "/api/diagnostics/all-job/status" ? new Promise((resolve) => statusHeld.push(() => resolve({state: "done", ready: true})))
        : Promise.resolve(listing(8, 1))});
    const diag = api.runAllDiagnostics({disabled: false});
    for (let spin = 0; spin < 10 && statusHeld.length === 0; spin++) await Promise.resolve();
    const again = api.downloadDiagnosticsVolumes({disabled: false});
    for (let spin = 0; spin < 20; spin++) await Promise.resolve();
    const same = api.state();
    assert.ok(same && same.saving, "setup: the set the press fetched is mid-save");
    statusHeld[0]();
    await diag;
    assert.strictEqual(api.state(), same, "the same archive stays on the bar, its save uncut");
    assert.strictEqual(page.els["all-diag-status"].textContent, "", "and no 'press again' line is written for the archive already on the bar");
    while (hold.length) { hold.shift()(); for (let s = 0; s < 5; s++) await Promise.resolve(); }
    await again;
  }

  // ---- an "again" that landed with the PREVIOUS archive and is still saving when the new one is split: that set is dead, the bar is taken
  {
    const page = makePage(); const hold = []; const statusHeld = []; let built = false;
    const L = (stem) => { const l = listing(8, 1); l.files.forEach((f) => { f.name = f.name.replace("oo-x", stem); }); return l; };
    const api = load(page, {hold, api: (url) => url.startsWith("/api/diagnostics/all-job?") ? Promise.resolve({started: true})
      : url === "/api/diagnostics/all-job/status" ? new Promise((resolve) => statusHeld.push(() => resolve({state: "done", ready: true})))
        : Promise.resolve(L(built ? "oo-new" : "oo-old"))});
    const diag = api.runAllDiagnostics({disabled: false});
    for (let spin = 0; spin < 10 && statusHeld.length === 0; spin++) await Promise.resolve();
    const again = api.downloadDiagnosticsVolumes({disabled: false});   // answered by the previous archive, whose save begins
    for (let spin = 0; spin < 20; spin++) await Promise.resolve();
    assert.ok(api.state() && api.state().saving, "setup: the previous archive's save is going");
    built = true;                                                      // the build's split replaced those files on the server
    statusHeld[0]();
    await diag;
    assert.ok(api.state().files[0].name.startsWith("oo-new"), "a press that has already LANDED does not count as 'on its way': " + api.state().files[0].name);
    assert.strictEqual(page.els["all-diag-status"].textContent, "");
    while (hold.length) { hold.shift()(); for (let s = 0; s < 5; s++) await Promise.resolve(); }
    await again;
    assert.ok(api.state().files[0].name.startsWith("oo-new"), "the dead set's loop did not take the bar back");
  }

  // ---- "again" refused after the ready line was written leaves that line standing: the archive is still ready
  {
    for (const status of [404, 409, 500]) {
      const page = makePage();
      const api = load(page, {api: async () => { const e = new Error("refused"); e.status = status; throw e; }});
      page.els["all-diag-status"].textContent = READY_SENTENCE;
      await api.downloadDiagnosticsVolumes({disabled: false});
      assert.strictEqual(page.els["all-diag-status"].textContent, READY_SENTENCE, status + ": a refused press wiped the ready line");
    }
  }

  // ---- the split sweeps the previous archive's files BEFORE it writes the new ones: a failed or lost split leaves no dead set on the bar
  {
    for (const failure of ["500", "network", "409"]) {
      const page = makePage(); let failNow = false;
      const api = load(page, {api: (url) => {
        if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
        if (url === "/api/diagnostics/all-job/status") return Promise.resolve({state: "done", ready: true});
        if (failNow) {
          const e = new Error(failure === "network" ? "network" : "split failed");
          if (failure !== "network") e.status = Number(failure);
          return Promise.reject(e);
        }
        return Promise.resolve(listing(8, 1));
      }});
      await api.downloadDiagnosticsVolumes({disabled: false});          // "again": five files handed over
      const old = api.state();
      assert.strictEqual(old.offered.size, 5);
      failNow = true;
      await api.runAllDiagnostics({disabled: false});
      if (failure === "409") {
        assert.strictEqual(api.state(), old, "409 (another build is running) swept nothing: the set stays");
      } else {
        assert.strictEqual(api.state(), null, failure + ": the swept archive's set is off the bar");
        assert.strictEqual(page.els["parts-bar"].hidden, true, failure + ": and the bar is hidden, not left empty");
        assert.strictEqual(page.els["parts-status"].textContent, "");
        const before = page.clicked.length;
        await api.partsSaveNext();
        assert.strictEqual(page.clicked.length, before, failure + ": no click can ask for the dead files");
      }
      assert.ok(/^Could not split the archive: /.test(page.els["all-diag-status"].textContent), page.els["all-diag-status"].textContent);
    }
    // a KEYWORD set on the bar is not the split's to drop
    const page = makePage(); let failNow = false;
    const api = load(page, {api: (url) => {
      if (url.startsWith("/api/diagnostics/all-job?")) return Promise.resolve({started: true});
      if (url === "/api/diagnostics/all-job/status") return Promise.resolve({state: "done", ready: true});
      if (failNow && url === "/api/diagnostics/all-job/volumes") { const e = new Error("split failed"); e.status = 500; return Promise.reject(e); }
      return Promise.resolve(listing(3, 1));
    }});
    await api.downloadKeywordParts({disabled: false}, "default");
    failNow = true;
    await api.runAllDiagnostics({disabled: false});
    assert.strictEqual(api.state().kind, "keywords", "a failed split does not touch a keyword set");
  }

  console.log("all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
