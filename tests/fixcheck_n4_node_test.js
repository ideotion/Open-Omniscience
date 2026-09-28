/**
 * Behavioural node test for the 2026-09-27 fix-check walk's row N item N-4: the three
 * job lines in Settings → Advanced → Diagnostics (re-index, keyword fold, search
 * re-index) kept the language they were drawn in after a live switch, because their
 * watch loop ends once the job is done and nothing drew them again until the fold was
 * reopened. `repaintDiagnosticsJobsFromCache` redraws each line from the reading it last
 * drew, with no fetch, and leaves alone a line something else has written since.
 *
 * The functions under test are EXTRACTED FROM THE SHIPPED SOURCE by name (the sibling
 * node suites' convention). Run by tests/test_fixcheck_walk.py (and standalone:
 * `node tests/fixcheck_n4_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const DIAG = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-diagnostics.js"), "utf-8");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) {
  return Promise.resolve().then(fn).then(() => { passed += 1; console.log("ok  - " + name); });
}

// Same balanced-brace extraction every node suite here uses (duplicated per convention).
function extract(name, src) {
  const head = "function " + name + "(";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = src.indexOf("(", at); j < src.length; j++) {
    if (src[j] === "(") p++;
    else if (src[j] === ")") { p--; if (p === 0) { i = src.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

const FR = { "Articles checked": "Articles vérifiés", "reindexed": "réindexés" };
const AR = { "Articles checked": "المقالات التي فُحصت", "reindexed": "أُعيدت فهرستها" };

function load() {
  const I = { lang: "fr" };
  const dict = () => (I.lang === "fr" ? FR : I.lang === "ar" ? AR : {});
  I.t = (s) => dict()[s] || s;
  const reads = [];
  const api = async (url) => { reads.push(url); return { state: "done", checked: 462, reindexed: 0 }; };
  const doc = { querySelector: () => null };
  const src = "const _jobWatch = {};\nconst _jobLast = {};\n"
    + ["_diagSectionOpen", "_armJobSettle", "_settleJob", "_watchJobLine", "repaintDiagnosticsJobsFromCache"]
      .map((n) => extract(n, DIAG)).join("\n")
    + "\nreturn { _watchJobLine, repaintDiagnosticsJobsFromCache };";
  // eslint-disable-next-line no-new-func
  const f = new Function("api", "document", "window", "OOI18N", src)(api, doc, { OOI18N: I }, I);
  return { f, I, reads };
}

const render = (s, _report, t) => `${t("Articles checked")}: ${s.checked} · ${t("reindexed")}: ${s.reindexed}`;
const line = () => ({ textContent: "", isConnected: true });

(async () => {
  await test("N-4: a finished job's line follows a live language switch, with no fetch", async () => {
    const { f, I, reads } = load();
    const st = line();
    await f._watchJobLine("fts", "/status", null, render, st, I.t, true).done;
    assert(st.textContent === "Articles vérifiés: 462 · réindexés: 0", "not drawn in fr: " + st.textContent);
    const before = reads.length;
    I.lang = "ar";
    f.repaintDiagnosticsJobsFromCache();
    assert(st.textContent === "المقالات التي فُحصت: 462 · أُعيدت فهرستها: 0",
      "the line kept the old language after the switch: " + st.textContent);
    assert(reads.length === before, "a language switch fetched: " + reads.slice(before));
    I.lang = "en";
    f.repaintDiagnosticsJobsFromCache();
    assert(st.textContent === "Articles checked: 462 · reindexed: 0", "a second switch did not repaint: " + st.textContent);
  });

  await test("N-4: a line written by something else since, or gone, is left alone", async () => {
    const { f, I } = load();
    const a = line(), b = line();
    await f._watchJobLine("reindex", "/status", null, render, a, I.t, true).done;
    await f._watchJobLine("fold", "/status", null, render, b, I.t, true).done;
    a.textContent = "Échec : disque plein";   // an error written by a button handler
    b.isConnected = false;                     // the panel was redrawn
    const bText = b.textContent;
    I.lang = "ar";
    f.repaintDiagnosticsJobsFromCache();
    assert(a.textContent === "Échec : disque plein", "a newer message was overwritten by an old reading");
    assert(b.textContent === bText, "a detached line was redrawn");
  });

  console.log(`fixcheck_n4_node_test: ${passed} passed`);
})().catch((e) => { console.error(e); process.exit(1); });
