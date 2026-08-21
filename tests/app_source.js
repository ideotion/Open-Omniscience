/*
 * Read the whole UI engine from a node test, whatever it is split into.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 *
 * This is `tests/js_source_helper.py`'s `app_js()` one language over, and it
 * exists for the same reason. `src/static/app.js` was one file until 2026-08-20,
 * when it became seventeen ordered modules (structural debt S-3); fourteen node
 * suites read it with a hand-rolled
 *
 *     fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"))
 *
 * and every one of them broke at once. That they broke LOUDLY is the good case:
 * each extracts a function BY NAME and asserts it was found, so a missing file
 * is a failed assertion rather than a suite that quietly tests nothing.
 *
 * The module list is read out of `index.html` rather than hard-coded here, so a
 * module added, renamed or re-ordered cannot leave this helper reading a subset
 * of the engine while every extraction still appears to succeed.
 *
 * Concatenated with no separator, exactly as the Python helper does, so byte
 * offsets are the same on both sides.
 */

"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");

function appModules() {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf-8");
  const re = /<script src="\/static\/(app(?:-[a-z0-9-]+)?\.js)"/g;
  const out = [];
  let m;
  while ((m = re.exec(html)) !== null) out.push(m[1]);
  if (!out.length) {
    throw new Error(
      "index.html loads no app module -- the script tags moved or were renamed. " +
      "Every node suite that extracts a function from the engine is now reading nothing."
    );
  }
  return out;
}

function appJs() {
  return appModules().map((m) => fs.readFileSync(path.join(STATIC, m), "utf-8")).join("");
}

module.exports = { appJs, appModules, STATIC };
