// The Home stop line (R111 / diagnostics rank 4), run as the real shipped code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// ``renderBriefing`` and ``_briefStamp`` are EXTRACTED from src/static/app-home.js by name
// (never re-typed) and run with minimal stubs: where the line sits (above the empty state,
// before the family nav, after the progress bar), when it repaints (the repaint key carries the
// markers), when it goes away (a complete feed), that a hostile reason is never reflected, and
// that every one of the 12 locales builds it with no placeholder left and no English leaking in.
// Written from the coordinator's check of PR #1284, which ran this against the merged code.

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

// Build a renderer bound to one locale, with the real extracted functions.
function makeRenderer(code) {
  const map = loadMap(code);
  const OOI18N = {
    t: (s) => (map[s] == null ? s : map[s]),
    tf: (s, vars) => {   // same semantics as src/static/i18n.js tf()
      if (s == null) return s;
      let out = map[s] == null ? s : map[s];
      if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null ? m : String(vars[k])));
      return out;
    },
  };
  const elements = { "briefing-feed": { innerHTML: "" }, "brief-generated": { textContent: "" } };
  const log = { repoll: 0, cancel: 0 };
  const src = `
    const window = { OOI18N };
    const $ = (id) => elements[id] || null;
    const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));
    const uiLangCode = () => code;
    let _briefCards = {}, _lastBriefGen = null;
    const _famLabels = {};
    const _homeTabKey = "__ov";
    const renderCorpusTier = () => {};
    const fmtDateTime = (s) => String(s);
    const _scheduleBriefRepoll = () => { log.repoll++; };
    const _cancelBriefRepoll = () => { log.cancel++; };
    const briefProgressHtml = () => '<div class="brief-progress">PROGRESS</div>';
    const famHue = () => "hsl(1 1% 1%)";
    const cardHtml = (c) => '<div class="card" data-id="' + c.id + '">CARD</div>';
    const _overviewHtml = () => "<OV/>";
    const _homePanelTabsHtml = () => "";
    const ooSubtabs = () => {};
    const selectHomeFamily = () => {};
    const _renderOverviewTrends = () => {};
    ${extract("_briefStamp")}
    ${extract("renderBriefing")}
    return { renderBriefing, _briefStamp, get last() { return _lastBriefGen; } };
  `;
  const api = new Function("OOI18N", "elements", "code", "log", src)(OOI18N, elements, code, log);
  return { api, elements, log };
}

const BASE = { generated_at: "2026-01-01T00:00:00+00:00", count: 1, total: 1, corpus_tier: { tier: "early" } };
const CARD_BUCKETS = [{ bucket: "rising", label: "Rising", cards: [{ id: "c1" }] }];
const EN_KEPT = "This is the previous feed: the last refresh stopped early because the machine was short of memory.";
const EN_INCOMPLETE_DL = "Some cards may be missing: the last refresh stopped early because it ran out of time.";
let checks = 0;
const ok = (cond, msg) => { checks++; assert.ok(cond, msg); };

// ---- 1. kept feed, empty buckets: the line is ABOVE the empty-state frame
{
  const { api, elements } = makeRenderer("en");
  api.renderBriefing({ ...BASE, buckets: [], cards: [], kept_reason: "memory_short" });
  const h = elements["briefing-feed"].innerHTML;
  ok(h.startsWith('<p class="card-caveat" id="brief-stopped">'), "stop line is the first node above the empty state: " + h.slice(0, 120));
  ok(h.includes(EN_KEPT), "kept/memory text");
  ok(h.indexOf("brief-stopped") < h.indexOf("No Leads yet"), "stop line precedes the empty-state heading");
  ok(h.includes("No Leads yet"), "the empty-state frame is still there");
}
// ---- 2. incomplete feed with cards: the line sits before the family nav, above the cards
{
  const { api, elements } = makeRenderer("en");
  api.renderBriefing({ ...BASE, buckets: CARD_BUCKETS, cards: [{ id: "c1" }], incomplete_reason: "deadline" });
  const h = elements["briefing-feed"].innerHTML;
  ok(h.startsWith('<p class="card-caveat" id="brief-stopped">' + EN_INCOMPLETE_DL), "incomplete/deadline text first: " + h.slice(0, 160));
  ok(h.indexOf("brief-stopped") < h.indexOf('<nav class="tabs home-fam"'), "line before the nav");
  ok(h.includes('data-id="c1"'), "cards still rendered");
}
// ---- 3. complete feed: no line at all
{
  const { api, elements } = makeRenderer("en");
  api.renderBriefing({ ...BASE, buckets: CARD_BUCKETS, cards: [{ id: "c1" }] });
  ok(!elements["briefing-feed"].innerHTML.includes("brief-stopped"), "no marker -> no line (cards)");
  api.renderBriefing({ ...BASE, buckets: [], cards: [] });
  ok(!elements["briefing-feed"].innerHTML.includes("brief-stopped"), "no marker -> no line (empty)");
  ok(elements["briefing-feed"].innerHTML.includes("No Leads yet"), "empty state present without a marker");
}
// ---- 4. refreshing (a background recompute is running) keeps the line, after the progress bar
{
  const { api, elements, log } = makeRenderer("en");
  api.renderBriefing({ ...BASE, buckets: [], cards: [], kept_reason: "memory_short", refreshing: true });
  const h = elements["briefing-feed"].innerHTML;
  ok(h.startsWith('<div class="brief-progress">PROGRESS</div><p class="card-caveat" id="brief-stopped">'), "progress then line: " + h);
  ok(!h.includes("No Leads yet"), "refreshing + empty shows only the banner (pre-existing behaviour)");
  ok(log.repoll === 1, "repoll scheduled while refreshing");
}
// ---- 5. both markers: kept wins (the earlier 'some cards may be missing' is not shown)
{
  const { api, elements } = makeRenderer("en");
  api.renderBriefing({ ...BASE, buckets: CARD_BUCKETS, cards: [{ id: "c1" }], kept_reason: "deadline", incomplete_reason: "memory_short" });
  const h = elements["briefing-feed"].innerHTML;
  ok(h.includes("This is the previous feed:") && h.includes("because it ran out of time."), "kept text with the kept reason");
  ok(!h.includes("Some cards may be missing"), "the incomplete line is not shown when kept is set");
  ok((h.match(/id="brief-stopped"/g) || []).length === 1, "exactly one stop line");
}
// ---- 6. unknown/garbage reason never reflects into the page; falls to the time reason (server sanitises first)
{
  const { api, elements } = makeRenderer("en");
  api.renderBriefing({ ...BASE, buckets: CARD_BUCKETS, cards: [{ id: "c1" }], kept_reason: "<img src=x onerror=alert(1)>" });
  const h = elements["briefing-feed"].innerHTML;
  ok(!h.includes("<img"), "garbage reason is not reflected");
  ok(h.includes("because it ran out of time."), "garbage reason reads as the time reason (so the server-side allow-list matters)");
}
// ---- 7. the live guard: the key carries the markers, so a kept feed repaints and a recovery repaints
{
  const { api, elements } = makeRenderer("en");
  const A = { ...BASE, buckets: CARD_BUCKETS, cards: [{ id: "c1" }] };
  const B = { ...A, kept_reason: "memory_short" };                       // same generated_at, marker appeared
  const C = { ...A, generated_at: "2026-02-02T00:00:00+00:00" };         // a complete refresh landed
  const D = { ...A, generated_at: "2026-02-02T00:00:00+00:00", incomplete_reason: "deadline" };
  api.renderBriefing(A);
  ok(api.last === api._briefStamp(A), "render stores the same key the guard computes");
  ok(api._briefStamp(B) !== api.last, "kept marker on the same generated_at changes the key -> the poll repaints");
  api.renderBriefing(B);
  ok(elements["briefing-feed"].innerHTML.includes("brief-stopped"), "line appears after the repaint");
  ok(api._briefStamp(B) === api.last, "an unchanged kept feed does NOT repaint on every poll");
  ok(api._briefStamp(C) !== api.last, "a complete feed (new generated_at, no marker) changes the key");
  api.renderBriefing(C);
  ok(!elements["briefing-feed"].innerHTML.includes("brief-stopped"), "the line is gone once the feed is complete");
  ok(api._briefStamp(D) !== api._briefStamp(C), "incomplete marker is in the key too");
  // a marker removed without a new generated_at (marker cleared in place) also repaints
  ok(api._briefStamp(A) !== api._briefStamp(B), "key differs with and without the marker");
  // null / missing generated_at ("building" payload): the key is stable and string-safe
  ok(api._briefStamp({ generated_at: null, buckets: [] }) === "|en||", "null generated_at -> '|en||'");
  ok(api._briefStamp({ buckets: [] }) === "|en||", "missing generated_at -> '|en||'");
}
// ---- 8. every locale: the line is built from keys that exist, with no placeholder left and no English leak
for (const code of LOCALES) {
  const { api, elements } = makeRenderer(code);
  for (const [kind, reason] of [["kept_reason", "memory_short"], ["kept_reason", "deadline"], ["incomplete_reason", "memory_short"], ["incomplete_reason", "deadline"]]) {
    api.renderBriefing({ ...BASE, buckets: CARD_BUCKETS, cards: [{ id: "c1" }], [kind]: reason });
    const m = elements["briefing-feed"].innerHTML.match(/<p class="card-caveat" id="brief-stopped">(.*?)<\/p>/);
    ok(m, `${code}/${kind}/${reason}: stop line present`);
    const line = m[1];
    ok(!/\{\w+\}/.test(line), `${code}/${kind}/${reason}: no placeholder left: ${line}`);
    ok(!line.includes("&amp;#"), `${code}: no double escaping`);
    if (code !== "en") {
      ok(!/the last refresh stopped early|the machine was short of memory|it ran out of time/.test(line), `${code}/${kind}/${reason}: English leaked into the line: ${line}`);
    }
  }
}
console.log(`home_stop_line_node_test.js: ${checks} assertions passed (12 locales x 4 lines checked for placeholder/English leaks)`);
