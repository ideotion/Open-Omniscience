// The markets Load / Refresh / Retry verdict box says how many feeds a Stop left unfetched (R377), run as the real shipped code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// ``_renderFeedVerdicts`` is EXTRACTED from src/static/app-markets.js by name (never re-typed). The import-all route now ENDS the batch at a Stop: the feeds it cut
// or never reached are no longer ``offline`` failures in ``results``, so without this line a partial load read as complete (invariant #14e's corollary). The
// string is the one the law tracker already keys, so nothing new is translated; this proves every locale builds it with no placeholder and no English left in.

"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const REPO = path.join(__dirname, "..");
const { appJs } = require(path.join(path.resolve(REPO), "tests", "app_source.js"));
const APP = appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in the app source");
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

const LOCALES = ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"];
function loadMap(code) {
  if (code === "en") return {};
  const d = JSON.parse(fs.readFileSync(path.join(REPO, "src", "static", "locales", code + ".json"), "utf-8"));
  delete d._meta;
  return d;
}

function makeRenderer(code) {
  const map = loadMap(code);
  const OOI18N = {
    t: (s) => (map[s] == null ? s : map[s]),
    tf: (s, vars) => {   // same semantics as src/static/i18n.js tf()
      let out = map[s] == null ? s : map[s];
      if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null ? m : String(vars[k])));
      return out;
    },
  };
  const elements = { box: { innerHTML: "" } };
  const src = `
    const window = { OOI18N };
    const $ = (id) => elements[id] || null;
    const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));
    const fmtNum = (n) => String(n);
    ${extract("_renderFeedVerdicts")}
    return { render: _renderFeedVerdicts };
  `;
  const api = new Function("OOI18N", "elements", src)(OOI18N, elements);
  return { api, elements };
}

let checks = 0;
const ok = (c, m) => { assert.ok(c, m); checks++; };

const FAIL = { key: "f1", symbol: "S1", status: "fetch_failed", verdict: "dead-series", verdict_note: "gone upstream", retryable: false };

// English: the line, alone, with failures, and absent.
{
  const { api, elements } = makeRenderer("en");
  api.render("box", { results: [], skipped_offline: 28 }, "");
  ok(elements.box.innerHTML.includes("28 not fetched (airplane mode)"), "a Stop's unfetched count is drawn when there are no failures: " + elements.box.innerHTML);
  api.render("box", { results: [FAIL], skipped_offline: 3, retryable_failed_keys: [] }, "");
  ok(elements.box.innerHTML.includes("3 not fetched (airplane mode)") && elements.box.innerHTML.includes("dead-series"), "the line sits with the failures it does not replace");
  api.render("box", { results: [FAIL] }, "");
  ok(!elements.box.innerHTML.includes("not fetched"), "no line without skipped_offline");
  api.render("box", { results: [], skipped_offline: 0 }, "");
  ok(elements.box.innerHTML === "", "a complete clean load leaves the box empty");
}

// Every locale builds the line with no placeholder left and no English leaking in.
for (const code of LOCALES) {
  const { api, elements } = makeRenderer(code);
  api.render("box", { results: [], skipped_offline: 12 }, "");
  const html = elements.box.innerHTML;
  ok(html.includes("12"), `${code}: the count is in the line`);
  ok(!/\{\w+\}/.test(html), `${code}: no placeholder left: ${html}`);
  if (code !== "en") ok(!html.includes("not fetched"), `${code}: English leaked into the line: ${html}`);
}
console.log(`markets_skipped_offline_node_test.js: ${checks} assertions passed (4 shapes in English, 12 locales checked for the count, placeholder and English leaks)`);
