// The next-pass preview label, run as real EXTRACTED code in both UIs against small fakes.
// Open Omniscience - Global Intelligence Platform for Investigative Journalism.
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The activity poll is answered from the last good preview (it never waits on the database
// pool), so a preview that is not fresh must SAY so, with its age: nothing while fresh, a
// "being computed" line when nothing exists yet for the current settings, a refresh line
// while it ages, and a plain warning once the last refresh has not completed.

"use strict";

const assert = require("assert");
const path = require("path");
const fs = require("fs");

const APP = require("./app_source.js").appJs();
const TM = require("./app_source.js").pageSource("taskmanager.html");
const EN = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", "en.json"), "utf-8"));

function extract(src, name) {
  const at = src.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  let d = 0, j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return src.slice(at, j) + "\n";
}
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const tf = (s, o) => s.replace(/\{(\w+)\}/g, (m, k) => (o && o[k] != null ? String(o[k]) : m));
const dur = (s) => (s == null ? "—" : "~" + Math.round(s) + " s");

const app = new Function("esc", "_fmtDur", extract(APP, "_planNoteHtml") + "return _planNoteHtml;")(esc, dur);
const tm = new Function("esc", "t", "tf", "fmtDur", extract(TM, "planNoteHtml") + "return planNoteHtml;")(esc, (s) => s, tf, dur);
const render = { "the app": (p) => app(p, (s) => s, tf), "/tasks": (p) => tm(p) };

const fails = [];
function check(name, fn) { try { fn(); } catch (e) { fails.push(name + ": " + e.message); } }

for (const [ui, draw] of Object.entries(render)) {
  check(ui + ": a fresh preview, or a payload without a state, says nothing", () => {
    assert.strictEqual(draw({ state: "fresh", age_s: 3, stale: false }), "");
    assert.strictEqual(draw({ planned_total: 5 }), "");
    assert.strictEqual(draw(null), "");
  });
  check(ui + ": nothing computed yet for these settings says so", () => {
    assert.ok(draw({ state: "computing", age_s: null }).includes("The next-pass preview is being computed."));
  });
  check(ui + ": an ageing preview names its age and the background refresh", () => {
    const h = draw({ state: "refreshing", age_s: 22, stale: false });
    assert.ok(h.includes("This preview is ~22 s old and is being refreshed in the background."), h);
  });
  check(ui + ": a preview whose refresh has not completed says the figures may no longer be true", () => {
    const h = draw({ state: "stale", age_s: 130, stale: true });
    assert.ok(h.includes("~130 s old: the last refresh has not completed"), h);
    assert.ok(h.includes("may no longer be true"), h);
    const e = draw({ state: "refreshing", age_s: 20, stale: false, refresh_error: { type: "TimeoutError" } });
    assert.ok(e.includes("has not completed"), "a recorded refresh failure reads as not completed: " + e);
  });
  check(ui + ": no placeholder survives", () => {
    for (const p of [{ state: "refreshing", age_s: 22 }, { state: "stale", age_s: 90, stale: true }]) {
      assert.ok(!/\{\w+\}/.test(draw(p)), draw(p));
    }
  });
}

check("every sentence is a locale key", () => {
  for (const k of [
    "The next-pass preview is being computed.",
    "This preview is {age} old and is being refreshed in the background.",
    "This preview is {age} old: the last refresh has not completed, so the figures may no longer be true.",
  ]) {
    assert.ok(k in EN, "missing locale key: " + k);
    assert.ok(APP.includes(k) && TM.includes(k), "the sentence moved: " + k);
  }
});

if (fails.length) { console.log(fails.join("\n")); process.exit(1); }
console.log("plan preview label: all checks ok");
