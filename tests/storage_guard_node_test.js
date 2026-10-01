// The storage guard's notice, run as real EXTRACTED code in both UIs (the app's vitals panel /
// Schedule subtab and the standalone /tasks page) against small fakes. Open Omniscience -
// Global Intelligence Platform for Investigative Journalism. Copyright (C) 2026 Ideotion.
// GPL-3.0-or-later.
//
//   * an engaged guard draws each note from its FRAME with the numbers filled in through the
//     page's own byte formatter, the retry button, and the method one hover away (which says
//     that quitting and reopening ends what the app itself holds open);
//   * it draws NOTHING unless collection is meant to be running: a "Collection is paused"
//     notice over a stopped scheduler or airplane mode would claim a state that is not the case;
//   * a healthy or absent guard draws nothing, and no placeholder survives into the text.

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
const bytes = (n) => (n == null ? "—" : Math.round(n / 1048576) + " MB");

const FRAME_WAL = "Collection is paused: the database's write-ahead log has grown to {size} (this machine's limit is {limit}) and cannot be reset while something still holds it open, such as a long read or a long write. Collection resumes by itself as soon as the log can be reset.";
const GUARD = { engaged: true, notes: [{ kind: "wal", frame: FRAME_WAL, vars: { size: 3221225472, limit: 1073741824 } }] };
const ok = (over) => Object.assign({ running: true, online: true, storage_guard: GUARD }, over || {});

const app = new Function("esc", "_fmtBytes",
  extract(APP, "_storageGuardHtml") + "return _storageGuardHtml;")(esc, bytes);
const tm = new Function("esc", "fmtBytes", "tf", "t",
  extract(TM, "storageGuardHtml") + "return storageGuardHtml;")(esc, bytes, tf, (s) => s);
const render = {
  "the app": (a) => app(a, (s) => s, tf),
  "/tasks": (a) => tm(a),
};

const fails = [];
function check(name, fn) { try { fn(); } catch (e) { fails.push(name + ": " + e.message); } }

for (const [ui, draw] of Object.entries(render)) {
  check(ui + ": an engaged guard draws the sentence with the numbers filled in", () => {
    const html = draw(ok());
    assert.ok(html.includes("has grown to 3072 MB (this machine&#39;s limit") || html.includes("has grown to 3072 MB (this machine's limit"), html);
    assert.ok(html.includes("limit is 1024 MB)"), html);
    assert.ok(!/\{\w+\}/.test(html), "a placeholder survived: " + html);
  });
  check(ui + ": the retry button is there and the hover carries the restart sentence", () => {
    const html = draw(ok());
    assert.ok(/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), html);
    assert.ok(html.includes("Try again now"), html);
    assert.ok(html.includes("quitting and reopening the app ends anything the app itself is holding open"), html);
  });
  check(ui + ": nothing is drawn while the scheduler is stopped", () => {
    assert.strictEqual(draw(ok({ running: false })), "");
  });
  check(ui + ": nothing is drawn in airplane mode", () => {
    assert.strictEqual(draw(ok({ online: false })), "");
  });
  check(ui + ": a healthy or absent guard draws nothing", () => {
    assert.strictEqual(draw(ok({ storage_guard: { engaged: false, notes: [] } })), "");
    assert.strictEqual(draw(ok({ storage_guard: null })), "");
    assert.strictEqual(draw(null), "");
  });
}

check("the hover key in both UIs is a locale key (the page translates it by that exact text)", () => {
  for (const [name, src] of [["app-core", APP], ["taskmanager", TM]]) {
    const m = src.match(/t\("(Measured from the size of the database[^"]*)"\)/);
    assert.ok(m, name + " lost its hover text");
    assert.ok(m[1] in EN, name + ": the hover text is not a locale key: " + m[1].slice(0, 60));
  }
});

if (fails.length) {
  console.log(fails.join("\n"));
  process.exit(1);
}
console.log("storage guard notice: all checks ok");
