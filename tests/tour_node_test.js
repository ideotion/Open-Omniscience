// The onboarding tour's step builder and renderer, run as REAL code (gate row K, brief S05-11 S5).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What the tour must NOT do is most of what it is, so most checks are refusals:
//
//   * it never leaves a tab out: every tab is either a step or named in the "more" step, at
//     every interface depth (the recorded onboarding lesson: emphasis is not exclusion);
//   * at Standard and Full there is no "more" step, because nothing is unpinned;
//   * a tab the tour has no sentence for is still a step, with its name and its button;
//   * no sentence about a tab carries a score, a rating, a grade or a ranking: the app shows
//     counts and methods;
//   * every step says on the page that the tour changes nothing, not only in a hover;
//   * a tab label from the DOM is escaped, never trusted as markup.
//
// EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-tour.js"), "utf-8");

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = SRC.indexOf("(", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "(") depth++;
    else if (SRC[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = SRC.indexOf("{", i);
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}

const FNS = ["_tourNum", "tourBlurb", "tourSteps", "tourAction", "tourStepHtml"];
const src =
  "function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;'); }\n" +
  FNS.map(extract).join("\n") + "\n" +
  "module.exports = {" + FNS.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();

// The sidebar as index.html has it (the python test pins this list against the page).
const IDS = ["home", "feed", "explore", "insights", "observatory", "timemap", "law", "agenda",
  "indices", "markets", "living", "library"];
const LABEL = (id) => id.charAt(0).toUpperCase() + id.slice(1);
const tabs = (depth) => IDS.map((id) => ({
  id, label: LABEL(id), pinned: depth !== "essentials" || id === "home" || id === "feed",
}));

// every known tab has a sentence, and none says anything a verdict would
const BANNED = /\b(score[sd]?|rating|rated|rank(ed|ing)?|grade[sd]?|credib\w*|trustworth\w*|reliab\w*|best|worst)\b/i;
for (const id of IDS) {
  const s = R.tourBlurb(id, t);
  assert.ok(s.length > 20, id + " has no sentence");
  assert.ok(!BANNED.test(s), id + " promises a judgement: " + s);
}
assert.strictEqual(R.tourBlurb("a-tab-added-later", t), "", "an unknown tab gets no invented sentence");

// ESSENTIALS: chrome, the two pinned tabs, "more", depth
const ess = R.tourSteps(tabs("essentials"), "essentials", t, tf);
assert.deepStrictEqual(ess.map((s) => s.kind), ["chrome", "tab", "tab", "more", "depth"]);
const more = ess.find((s) => s.kind === "more");
assert.strictEqual(more.title, "10 more tabs");
assert.deepStrictEqual(more.list, IDS.slice(2).map(LABEL), "every unpinned tab is named, in sidebar order");
const named = new Set(ess.filter((s) => s.kind === "tab").map((s) => s.tab).concat(IDS.filter((i) => more.list.includes(LABEL(i)))));
assert.deepStrictEqual([...named].sort(), [...IDS].sort(), "every tab is a step or in the list");
assert.ok(more.body.includes("Show more") && more.body.includes("command palette"), more.body);
assert.ok(more.body.includes("the tab you have open always stays listed"), "the open tab is named as listed, not as hidden: " + more.body);
// digit grouping goes through the app formatter when there is one, like the sidebar's "Show more (N)"
const G = (() => { const m = { exports: {} }; new Function("fmtNum", "module", "exports", src)((n) => "#" + n, m, m.exports); return m.exports; })();
assert.strictEqual(G.tourSteps(tabs("essentials"), "essentials", t, tf).find((s) => s.kind === "more").title, "#10 more tabs");
assert.ok(visible(G.tourStepHtml(ess[0], 0, ess.length, t, tf)).includes("Step #1 of #5"));
assert.ok(ess[ess.length - 1].body.includes("Essentials now"), ess[ess.length - 1].body);

// STANDARD and FULL: every tab is its own step and there is no "more"
for (const depth of ["standard", "full"]) {
  const st = R.tourSteps(tabs(depth), depth, t, tf);
  assert.deepStrictEqual(st.map((s) => s.kind), ["chrome"].concat(IDS.map(() => "tab"), ["depth"]), depth);
  assert.deepStrictEqual(st.filter((s) => s.kind === "tab").map((s) => s.tab), IDS, depth + " keeps the sidebar's order");
}
assert.ok(R.tourSteps(tabs("standard"), "standard", t, tf).pop().body.includes("Standard now"));
assert.ok(R.tourSteps(tabs("full"), "full", t, tf).pop().body.includes("Full now"));

// A tab the tour has no sentence for is still a step, with its name and its button.
const late = R.tourSteps([{ id: "newtab", label: "New tab", pinned: true }], "full", t, tf);
assert.strictEqual(late[1].title, "New tab");
assert.strictEqual(late[1].body, "");
assert.strictEqual(R.tourAction(late[1], t, tf).label, "Open New tab");
const lateHtml = R.tourStepHtml(late[1], 1, late.length, t, tf);
assert.ok(visible(lateHtml).includes("New tab") && lateHtml.includes("data-tour-act=\"open\""), lateHtml);

// The buttons: a tab opens, "more" reveals, depth goes to the setting, the top bar has none.
assert.strictEqual(R.tourAction(ess[0], t, tf), null);
assert.deepStrictEqual(R.tourAction(ess[1], t, tf), { act: "open", label: "Open Home" });
assert.strictEqual(R.tourAction(more, t, tf).act, "more");
assert.strictEqual(R.tourAction(ess[ess.length - 1], t, tf).act, "depth");
assert.ok(!R.tourStepHtml(ess[0], 0, ess.length, t, tf).includes("data-tour-act"));

// Every step, on the page, says the tour changes nothing and counts the step.
ess.forEach((s, i) => {
  const v = visible(R.tourStepHtml(s, i, ess.length, t, tf));
  assert.ok(v.includes("The tour changes nothing: it sets no filter, hides no tab and keeps no record."), v);
  assert.ok(v.includes("Step " + (i + 1) + " of " + ess.length), v);
});
// the "more" step lists the labels
const moreHtml = R.tourStepHtml(more, 3, ess.length, t, tf);
assert.strictEqual((moreHtml.match(/<li /g) || []).length, 10);
assert.ok(moreHtml.includes("dir=\"auto\""), "labels take their own direction");

// A label from the DOM is text, never markup.
const hostile = R.tourSteps([{ id: "x", label: "<img src=x onerror=alert(1)>", pinned: true }], "full", t, tf);
const hostileHtml = R.tourStepHtml(hostile[1], 1, hostile.length, t, tf);
assert.ok(!hostileHtml.includes("<img"), hostileHtml);
assert.ok(hostileHtml.includes("&lt;img"), hostileHtml);
const hostileList = R.tourStepHtml({ kind: "more", title: "1 more tab", body: "", list: ["<b>x</b>"] }, 0, 1, t, tf);
assert.ok(!hostileList.includes("<b>x"), hostileList);

console.log("tour node test: all checks passed");
