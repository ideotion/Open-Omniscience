// One date tag reads the same on /investigate and in the agenda (row 316). investigate.js printed the stored
// status raw (candidate / confirmed / rejected); two of those words have no locale key, so they stayed English in
// every language. It now says it through _tagStatusLabel, a local copy of the agenda's _agStatusLabel, because the
// standalone page does not load app-agenda.js. This holds the two copies to the same key for every token.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const INV = fs.readFileSync(path.join(__dirname, "..", "src", "static", "investigate.js"), "utf8");

function extract(text, name) {
  const at = text.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = text.indexOf("{", text.indexOf(")", at));
  let d = 0, j = open;
  for (; j < text.length; j++) {
    if (text[j] === "{") d++;
    else if (text[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return text.slice(at, j);
}
function load(text, name) {
  const t = (s) => "T[" + s + "]";
  const win = { OOI18N: { t } };
  return new Function("window", "OOI18N", extract(text, name) + "\nreturn " + name + ";")(win, win.OOI18N);
}

const agenda = load(APP, "_agStatusLabel");
const page = load(INV, "_tagStatusLabel");
const tokens = ["candidate", "confirmed", "rejected", "a-status-from-a-newer-server", "toString", "", undefined, null];
for (const st of tokens) {
  assert.strictEqual(page(st), agenda(st), "the two pages disagree on " + String(st));
}
assert.strictEqual(page("confirmed"), "T[confirmed by you]");
assert.strictEqual(page("rejected"), "T[rejected by you]");
assert.strictEqual(page("candidate"), "T[not checked]", "an unconfirmed extraction says it was not checked");

// A safety net, not the usual path (the cell is built after an awaited fetch, by which time i18n.js has normally run):
// with no i18n engine the English key itself is returned, which the page's text-node walker translates because it
// stands alone in its cell.
const bare = new Function("window", extract(INV, "_tagStatusLabel") + "\nreturn _tagStatusLabel;")({});
assert.strictEqual(bare("candidate"), "not checked");

// The cell goes through the label, never the raw token.
assert.ok(INV.includes("<td>${esc(_tagStatusLabel(t.status))}</td>"), "the date-tag cell must use the label");
assert.ok(!INV.includes("esc(t.status)"), "the raw status print came back");

console.log("date tag status: all checks passed");
