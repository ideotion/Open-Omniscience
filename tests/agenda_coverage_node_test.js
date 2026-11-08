// Drives the Agenda's Elections coverage renderer (app-agenda.js) in node with a stub DOM,
// so the guards in test_agenda_elections_coverage.py check what it DRAWS, not only its source.
// Run by tests/test_agenda_elections_coverage.py::test_the_renderer_draws_what_the_report_says.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const src = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-agenda.js"), "utf8");
const block = src.slice(src.indexOf("let _agCov = null"), src.indexOf("function agNavToday()"));

const box = { innerHTML: "", style: { display: "" } };
let calls = 0, answer = null, view = "coverage";
const ctx = {
  window: {}, document: { documentElement: { dir: "ltr" } },
  $: (id) => (id === "agenda-coverage" ? box : null),
  esc: (s) => (s == null ? "" : String(s)).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"),
  agView: () => view,
  api: () => { calls++; const a = answer; return a instanceof Error ? Promise.reject(a) : Promise.resolve(a); },
  agFlag: () => "", ooCountryCode: (c) => c, ooCountryName: (c) => ({ FR: "France", NG: "Nigeria" }[c] || ""),
  ooCountryCompare: (a, b) => a.localeCompare(b),
  ooIsoDate: (s) => (ctx.document.documentElement.dir === "rtl" ? "⁨" + s + "⁩" : s),
};
vm.createContext(ctx);
vm.runInContext(block + "\nthis._probe = { render: renderAgendaCoverage, filter: agCovFilter, repaint: _agCovRepaint, reset: () => { _agCov = null; _agCovState = ''; } };", ctx);
const P = ctx._probe;
const tick = () => new Promise((r) => setImmediate(r));

const REPORT = {
  as_of: "2025-12-14", caveat: "FLOOR CAVEAT",
  tier_report: {
    floor_countries: 2, caveat: "TIER CAVEAT", method: "THE METHOD",
    counts: { scheduled: 1, dateless: 1, window: 0, projected_upcoming: 0, projected_passed: 0, missing: 0 },
    countries: [
      { cc: "NG", state: "dateless", reason: "WHY <b>", entries: [{ title: "Vote <script>", missing_fields: ["date", "rule"] }] },
      { cc: "FR", state: "scheduled", entries: [{ title: "Présidentielle" }, { title: "Municipales", missing_fields: ["SHOULD-NOT-SHOW"] }] },
    ],
  },
};

(async () => {
  // 1. It draws both caveats, the method, full counts, and escapes server text.
  answer = REPORT; P.reset(); P.render(); await tick(); await tick();
  let h = box.innerHTML;
  for (const s of ["FLOOR CAVEAT", "TIER CAVEAT", "THE METHOD", "2 floor countries", "2025-12-14", "France (FR)"]) assert(h.includes(s), "draws " + s);
  assert(!h.includes("<script>") && h.includes("Vote &lt;script&gt;") && h.includes("WHY &lt;b&gt;"), "server text is escaped");
  assert(h.includes("fields needed: date, rule"), "names the missing fields");
  assert(!h.includes("SHOULD-NOT-SHOW"), "a dated country is never asked why it has no date");
  assert(h.indexOf("France") < h.indexOf("Nigeria"), "rows sorted by country");
  assert(!/%|score/i.test(h.replace(/style="[^"]*"/g, "")), "no percentage or score");
  assert.strictEqual(calls, 1);

  // 2. A state chip filters the rows but the chips keep the full counts.
  P.filter("dateless"); h = box.innerHTML;
  assert(!h.includes("France (FR)") && h.includes("Nigeria (NG)"), "the filter narrows the rows");
  assert(/scheduled<\/span> 1/.test(h), "chips keep the full counts while filtered");
  P.filter("window"); assert(box.innerHTML.includes("No floor country is in this state."));
  P.filter("window"); assert(box.innerHTML.includes("France (FR)"), "clicking the active chip clears it");

  // 3. A language switch repaints from the held answer and never asks again.
  ctx.document.documentElement.dir = "rtl"; P.repaint();
  assert.strictEqual(calls, 1, "repaint never fetches");
  assert(box.innerHTML.includes("⁨2025-12-14⁩"), "the date is isolated in RTL");
  ctx.document.documentElement.dir = "ltr";

  // 4. A failure is shown once, the repaint leaves it alone, and the next visit asks again.
  answer = new Error("down"); P.reset(); P.render(); await tick(); await tick();
  assert(box.innerHTML.includes("Could not load the elections coverage report."));
  assert.strictEqual(calls, 2);
  P.repaint(); assert.strictEqual(calls, 2, "repaint does not retry a failure");
  answer = REPORT; P.render(); await tick(); await tick();
  assert.strictEqual(calls, 3, "the next visit asks again");
  assert(box.innerHTML.includes("THE METHOD"));

  // 5. A failure that lands while the user is on another view is not drawn as stale news on
  //    the way back: coming back asks again at once.
  answer = new Error("down"); P.reset(); P.render(); view = "list"; await tick(); await tick();
  assert.strictEqual(calls, 4);
  view = "coverage"; answer = REPORT; P.render(); await tick(); await tick();
  assert.strictEqual(calls, 5, "coming back after an unseen failure asks again");
  assert(box.innerHTML.includes("THE METHOD"), "and draws the answer, not the old failure");

  // 6. An answer without a tier_report is a failure too, and a repaint does not fetch for it.
  answer = { as_of: "x" }; P.reset(); P.render(); await tick(); await tick();
  assert(box.innerHTML.includes("Could not load"));
  P.repaint(); assert.strictEqual(calls, 6, "no fetch from a repaint");
  console.log("agenda coverage node test: ok");
})().catch((e) => { console.error(e); process.exit(1); });
