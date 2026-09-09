/**
 * The agenda row's span pill and year note, driven for real.
 *
 * `src/events/catalog.py` has computed `span` (start/end/active) and the
 * origin_year/until_year range since 2026-07-31, with its own test file, and
 * `agRow` read none of it: a month-span event rendered as a single START DAY and
 * a recurrence whose listing has ended simply stopped appearing with nothing
 * said.
 *
 * The Python side of this slice guards that the reads STAY in the source. This
 * suite is the half a grep cannot do: it EXECUTES the shipped `agRow` and reads
 * the HTML back, so the difference between "on now" and "upcoming" is checked as
 * behaviour rather than as the presence of a substring. Extracted from the
 * shipped module by name -- a re-typed copy would pass while the real row
 * asserted a span for an event that has none.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const APP = require("./app_source.js").appJs();

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(head) {
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let i = APP.indexOf("{", APP.indexOf(")", at));
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces in " + head);
}

// The row's neighbours are stubbed; the row itself is the shipped source. Each
// stub returns a marker so a test can tell "the pill is absent" from "the whole
// row failed to build".
const sandbox = { window: {} };
new Function(
  'const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"\']/g,'
  + ' c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","\'":"&#39;"}[c])));\n'
  + 'const agConfPill = () => "<span class=\\"pill\\">CONF</span>";\n'
  + 'const agWhen = () => "WHEN";\n'
  + 'const extLink = (u, l) => "<a>" + l + "</a>";\n'
  + 'const _agFeedById = () => ({});\n'
  + "const window = this.window;\n"
  + extract("function agRow(") + "\n"
  + "this.agRow = agRow;"
).call(sandbox);

const { agRow } = sandbox;

const base = { title: "A thing", category: "civic", country: "INT", tags: [] };
const pills = (html) => [...html.matchAll(/<span class="pill[^"]*"[^>]*>([\s\S]*?)<\/span>/g)]
  .map((m) => m[1].trim());
const muted = (html) => [...html.matchAll(/<span class="muted"[^>]*>([\s\S]*?)<\/span>/g)]
  .map((m) => m[1].trim());

test("an ACTIVE span says it is on now and names the end", () => {
  const html = agRow({...base, span: {start: "2026-09-01", end: "2026-09-30", active: true}});
  const p = pills(html);
  assert(p.some((s) => s === "On now, ends 2026-09-30"),
    "expected the active wording, got " + JSON.stringify(p));
});

test("an UPCOMING span names both ends and never claims it is on now", () => {
  const html = agRow({...base, span: {start: "2027-01-01", end: "2027-01-31", active: false}});
  const p = pills(html);
  assert(p.some((s) => s === "Runs 2027-01-01 – 2027-01-31"),
    "expected the range wording, got " + JSON.stringify(p));
  assert(!html.includes("On now"),
    "a future span must not be described as running -- that is the fabricated fact");
});

test("active and upcoming are visually distinct, not one string in two colours", () => {
  const on = agRow({...base, span: {start: "a", end: "b", active: true}});
  const off = agRow({...base, span: {start: "a", end: "b", active: false}});
  assert(/class="pill ok"/.test(on), "the active span carries the ok state: " + on);
  assert(!/class="pill ok"/.test(off), "an upcoming span must not be painted as live");
});

test("an event with NO span renders no span pill at all", () => {
  const html = agRow({...base});
  assert(!html.includes("On now"), "no default banner");
  assert(!html.includes("Runs "), "no default range");
  // The row still built: its ordinary pills are there.
  assert(pills(html).includes("civic"), "the row itself must still render: " + html);
});

test("a HALF span (start but no end) is not enough to draw a range", () => {
  // The degenerate case a truthiness check on `e.span` alone would print as
  // "Runs 2026-09-01 – undefined".
  const html = agRow({...base, span: {start: "2026-09-01", end: null, active: true}});
  assert(!html.includes("undefined"), "a missing end must suppress the pill: " + html);
  assert(!html.includes("On now"), "and must not be reported as on now");
});

test("the year range prints both halves when both are stated", () => {
  const m = muted(agRow({...base, origin_year: 1950, until_year: 2030}));
  assert(m.length === 1, "expected one note, got " + JSON.stringify(m));
  assert(m[0].includes("since 1950"), m[0]);
  assert(m[0].includes("nothing listed after 2030"), m[0]);
});

test("one half absent drops that half rather than printing an empty one", () => {
  const only = muted(agRow({...base, origin_year: 1950}));
  assert(only.length === 1 && only[0].includes("since 1950"), JSON.stringify(only));
  assert(!only[0].includes("nothing listed"), "the absent half must not print: " + only[0]);
  assert(!/·\s*·/.test(only[0]) && !/·\s*$/.test(only[0]),
    "and must not leave its separator behind: " + only[0]);
  const end = muted(agRow({...base, until_year: 2030}));
  assert(end.length === 1 && end[0].includes("nothing listed after 2030"), JSON.stringify(end));
  assert(!end[0].includes("since"), "the absent half must not print: " + end[0]);
});

test("neither stated renders no note", () => {
  assert(muted(agRow({...base})).length === 0, "no note for an event with no year range");
});

test("year ZERO is a stated year, not an absent one", () => {
  // `if (e.origin_year)` would drop it. The catalogue's absent value is null.
  const m = muted(agRow({...base, origin_year: 0}));
  assert(m.length === 1 && m[0].includes("since 0"),
    "a falsy-but-stated year must still print: " + JSON.stringify(m));
});

test("both facts carry the catalog-asserted hover", () => {
  const html = agRow({...base, span: {start: "a", end: "b", active: true},
                      origin_year: 1950});
  const notes = (html.match(/Stated by the event catalog \(asserted, not deduced\)\./g) || []);
  assert(notes.length === 2,
    "the span pill and the year note each need the hover, got " + notes.length);
});

console.log(`\n${passed} passed`);
