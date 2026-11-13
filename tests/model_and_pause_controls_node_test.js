/**
 * Behavioural node test for the controls added beside the jobs they act on: the low-memory pause's own label (it read as
 * idle), and the vLLM install cost line drawn from the preflight before the click. Run by
 * tests/test_model_and_pause_controls.py, and standalone: `node tests/model_and_pause_controls_node_test.js`.
 *
 * The functions are EXTRACTED FROM THE REAL FILES by name and evaluated, never re-typed here.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const APP = require("./app_source.js").appJs();
const TM = fs.readFileSync(path.join(__dirname, "..", "src", "static", "taskmanager.js"), "utf8");

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }

function extract(src, name) {
  const head = "function " + name + "(";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let i = src.indexOf("{", at), depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

// ------------------------------------------------ the low-memory pause names itself, in both task managers
const pausedApp = eval("(" + extract(APP, "_storagePausedText") + ")");
const pausedTm = eval("(" + extract(TM, "storagePausedText") + ")");
for (const [nm, fn] of [["app-core", pausedApp], ["taskmanager", pausedTm]]) {
  assert(fn("paused-low-memory", null) === "Paused: low memory", nm + ": the low-memory pause read as something else");
  // The storage override does not cover it: an override in force must not hide the pause.
  assert(fn("paused-low-memory", {overridden: true}) === "Paused: low memory", nm + ": the storage override hid the memory pause");
  assert(fn("running", null) === null, nm + ": a running loop drew a paused label");
}

// ------------------------------------------------ the install cost line, before the click
const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => String(v[k]));
const cost = eval("(" + extract(APP, "vllmCostLine") + ")");
assert(cost({disk: {measured: true, free_gb: 40, floor_gb: 25}, ram: {measured: true, total_gb: 16}, blocking: [], warnings: []}, t, tf)
  === "40 GB free, needs 25 GB · 16 GB RAM", "the plain cost line");
assert(cost({disk: {measured: true, free_gb: 3, floor_gb: 25}, ram: {measured: false}, blocking: [{detail: "x"}], warnings: []}, t, tf)
  === "Cannot install here: 3 GB free, needs 25 GB", "a blocking preflight leads with the refusal and draws no unmeasured RAM");
assert(cost({disk: {measured: false}, ram: {measured: true, total_gb: 6}, blocking: [], warnings: [{detail: "x"}]}, t, tf)
  === "Low resources: 6 GB RAM", "a warning preflight says so and draws no unmeasured disk");
assert(cost({}, t, tf) === "" && cost(null, t, tf) === "", "nothing measured draws nothing, never a fabricated figure");

console.log("MODEL AND PAUSE CONTROLS OK");
