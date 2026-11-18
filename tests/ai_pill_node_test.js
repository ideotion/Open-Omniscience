// The AI pill's shared health vocabulary, run as REAL code (row 164, 2026-11-18).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The task manager painted an offline AI as plain "pill warn": the state was colour alone,
// with no diagonal bar and no hover reason, against the app's own pill. Both pages now call
// ooAiPillState from ai-pill.js. This loads the shipped file and checks every state it maps.

const assert = require("assert");
const path = require("path");
global.window = {};
require(path.join(__dirname, "..", "src", "static", "ai-pill.js"));
const f = global.window.ooAiPillState;
assert.strictEqual(typeof f, "function", "ai-pill.js must define window.ooAiPillState");

const t = (s) => "[" + s + "]";  // a translator that marks what went through it

// Serving: green, no bar.
let s = f({ available: true }, t);
assert.strictEqual(s.cls, "pill ok");
assert.ok(!/ai-off/.test(s.cls));

// Every not-serving state carries the bar AND a non-empty hover: never colour alone.
const offline = [
  null,
  { available: false },
  { available: false, no_backend: true },
  { available: false, detail: "connection refused" },
  { available: false, hardware_practical: false, hardware_reason: "4 GB RAM" },
  { available: false, hardware_practical: null },
];
for (const h of offline) {
  s = f(h, t);
  assert.strictEqual(s.cls, "pill warn ai-off", JSON.stringify(h));
  assert.ok(s.title && s.title.length > 3, "no hover for " + JSON.stringify(h));
}

// The reason is named, translated, and leads the hover.
s = f({ available: false, no_backend: true }, t);
assert.ok(s.title.startsWith("[No AI backend is reachable right now"), s.title);
assert.ok(s.title.includes("[AI is offline"), s.title);
s = f({ available: false, detail: "connection refused" }, t);
assert.ok(s.title.startsWith("connection refused — "), s.title);
// Unsuitable hardware points at the override, not at starting a backend.
s = f({ available: false, hardware_practical: false, hardware_reason: "4 GB RAM" }, t);
assert.ok(s.title.startsWith("4 GB RAM — [AI features are off by default"), s.title);
assert.ok(!s.title.includes("click to start"), s.title);
// null hardware verdict falls through to the ordinary offline copy.
s = f({ available: false, hardware_practical: null }, t);
assert.ok(s.title.includes("[AI is offline"), s.title);

// Without a translator it still answers (English).
s = f(null);
assert.strictEqual(s.cls, "pill warn ai-off");

console.log("all assertions passed");
