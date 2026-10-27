/**
 * Behavioural node test for the background-AI status line (Settings -> Advanced -> Diagnostics, `_paintAiCoordinator`).
 *
 * The line printed the job's state word raw (`done`, `cancelled`, `error`: measured in the source, the keys existed in all
 * twelve locales and the code never called t()), printed the worker's English `detail` without its keyed frame, and joined
 * that English "paused — ... is running" line to the translated pill that says the same. The function under test is EXTRACTED
 * FROM THE SHIPPED SOURCE by name (the sibling node suites' convention). Run by tests/test_ai_coordinator_status_line.py
 * (and standalone: `node tests/ai_coordinator_state_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const DIAG = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-diagnostics.js"), "utf-8");
const CORE = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-core.js"), "utf-8");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(name, src) {
  const head = "function " + name + "(";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = src.indexOf("(", at); j < src.length; j++) {
    if (src[j] === "(") p++;
    else if (src[j] === ")") { p--; if (p === 0) { i = src.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

const FR = {
  "done": "terminé", "cancelled": "annulé", "error": "erreur", "running": "en cours",
  "paused — your batch is running": "en pause — votre lot est en cours",
  "Start background AI": "Démarrer l'IA en arrière-plan", "Pause background AI": "Suspendre l'IA en arrière-plan",
  "all enabled sweeps are up to date": "tous les balayages activés sont à jour",
};

function paint(st, lang) {
  const els = { "aic-toggle-btn": { dataset: {}, textContent: "" }, "aic-status": { innerHTML: "" }, "aic-hw": null };
  const t = (s) => (lang === "fr" && FR[s]) || s;
  const src = "const esc = (x) => String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;');\n"
    + "const _jobLabel = (j, t) => (j.label_i18n ? t(j.label_i18n).replace(/\\{(\\w+)\\}/g, (m, k) => (j.label_vars && k in j.label_vars ? j.label_vars[k] : m)) : j.label);\n"
    + extract("_framedText", CORE) + "\n" + extract("_paintAiCoordinator", DIAG) + "\nreturn _paintAiCoordinator;";
  // eslint-disable-next-line no-new-func
  const fn = new Function("$", "window", "OOI18N", src)((id) => els[id], { OOI18N: { t } }, { t });
  fn(st);
  return els["aic-status"].innerHTML;
}

test("a finished, stopped or failed lane prints its state word in the page's language", () => {
  assert(paint({ state: "done" }, "fr") === "terminé", paint({ state: "done" }, "fr"));
  assert(paint({ state: "cancelled" }, "fr") === "annulé", "cancelled");
  assert(paint({ state: "error" }, "fr") === "erreur", "error");
  assert(paint({ state: "cancelled" }, "en") === "cancelled", "English is unchanged");
});

test("idle prints nothing, and a word outside the closed list prints as sent (not hidden, not a prototype key)", () => {
  assert(paint({ state: "idle" }, "fr") === "", "idle");
  assert(paint({ state: "frozen" }, "fr") === "frozen", "unknown word");
  assert(paint({ state: "constructor" }, "fr") === "constructor", "a prototype key must not print a function");
});

test("a running lane's line goes through its keyed frame", () => {
  const st = { state: "running", detail: "all enabled sweeps are up to date", detail_i18n: "all enabled sweeps are up to date", detail_vars: {} };
  assert(paint(st, "fr") === "tous les balayages activés sont à jour", paint(st, "fr"));
  assert(paint({ state: "running" }, "fr") === "en cours", "no detail reads as running");
  assert(paint({ state: "running", detail: "plain English line" }, "fr") === "plain English line", "no frame: as sent");
});

test("while a user's batch holds the model the English line is not printed beside the translated pill", () => {
  const st = { state: "running", detail: "paused — some holder is running", user_batch: { held: true, holders: ["x"] } };
  const out = paint(st, "fr");
  assert(out === '<span class="pill warn">en pause — votre lot est en cours</span>', out);
  const joined = paint({ state: "cancelled", user_batch: { held: true } }, "fr");
  assert(joined === 'annulé · <span class="pill warn">en pause — votre lot est en cours</span>', joined);
});

console.log("all checks passed (" + passed + ")");
