// The unlock page's recovery sentences, run as real EXTRACTED code (src/static/unlock.js) against a
// small fake i18n built from the real locale files. Open Omniscience - Global Intelligence Platform
// for Investigative Journalism. Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
//   * nothing is said unless the server reports an attempt that is running;
//   * the log's size is written through the page's own unit strings (binary steps, SI names);
//   * with this machine's own earlier measurement the page states it beside the estimate, and
//     states an overrun instead of hiding it; with none it says there is none -- no invented figure;
//   * no sentence carries a percent, and no placeholder survives into the text in ANY locale.

"use strict";

const assert = require("assert");
const path = require("path");
const fs = require("fs");

const SRC = require("./app_source.js").pageSource("unlock.html");
const LOC = path.join(__dirname, "..", "src", "static", "locales");

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

function build(lang) {
  const map = JSON.parse(fs.readFileSync(path.join(LOC, lang + ".json"), "utf-8"));
  const tf = (s, vars) => {
    let out = map[s] == null ? s : map[s];
    if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (vars[k] == null ? m : String(vars[k])));
    return out;
  };
  const t = (s) => (map[s] == null ? s : map[s]);
  const win = { OOI18N: { tf, t } };
  const code = extract(SRC, "_recSize") + extract(SRC, "_recClock") + extract(SRC, "recoveryLines")
    + "return { _recSize, _recClock, recoveryLines };";
  return new Function("window", "OOI18N", "t", code)(win, win.OOI18N, t);
}

const GIB = 1024 ** 3, MIB = 1024 ** 2;
const strip = (s) => s.replace(/[\u2068\u2069]/g, "").replace(/\u00a0/g, " ");

const en = build("en");

// sizes: whole numbers from 100 up, one decimal below, binary steps under SI names
assert.strictEqual(strip(en._recSize(512 * MIB)), "512 MB");
assert.strictEqual(strip(en._recSize(1.5 * GIB)), "1.5 GB");
assert.strictEqual(strip(en._recSize(120 * GIB)), "120 GB");
assert.strictEqual(en._recSize(null), "\u2014");
assert.strictEqual(en._recClock(52), "00:52");
assert.strictEqual(en._recClock(3725), "62:05");
assert.strictEqual(en._recClock(-4), "00:00");

// nothing is said unless an attempt is running
assert.deepStrictEqual(en.recoveryLines(null), []);
assert.deepStrictEqual(en.recoveryLines({ active: false }), []);

// no earlier measurement: the size, then the honest absence -- no figure invented
let lines = en.recoveryLines({ active: true, wal_bytes: 3 * GIB, eta_s: null, basis: null, elapsed_s: 4 });
assert.strictEqual(lines.length, 2);
assert.ok(strip(lines[0]).includes("3.0 GB"));
assert.ok(lines[0].includes("Nothing is downloaded"));
assert.ok(lines[1].includes("no earlier measurement on this machine"));
assert.ok(!/\d\d:\d\d/.test(lines.join(" ")), "an unmeasured estimate must not show a time");

// measured: the basis sits beside the estimate
const basis = { wal_bytes: 2 * GIB, seconds: 80 };
lines = en.recoveryLines({ active: true, wal_bytes: 3 * GIB, eta_s: 120, basis, elapsed_s: 30 });
assert.strictEqual(lines.length, 2);
assert.ok(strip(lines[1]).includes("2.0 GB took 01:20"), lines[1]);
assert.ok(lines[1].includes("about 02:00"), lines[1]);

// an overrun is stated, not hidden
lines = en.recoveryLines({ active: true, wal_bytes: 3 * GIB, eta_s: 120, basis, elapsed_s: 121 });
assert.strictEqual(lines.length, 3);
assert.ok(lines[2].includes("That estimate has passed"));
lines = en.recoveryLines({ active: true, wal_bytes: 3 * GIB, eta_s: 120, basis, elapsed_s: 120 });
assert.strictEqual(lines.length, 2, "exactly on the estimate is not yet an overrun");

// a half-known basis is no basis: never a zero dressed as a measurement
for (const bad of [{ wal_bytes: 0, seconds: 10 }, { wal_bytes: GIB, seconds: 0 }, null]) {
  lines = en.recoveryLines({ active: true, wal_bytes: GIB, eta_s: 40, basis: bad, elapsed_s: 1 });
  assert.ok(lines[1].includes("no earlier measurement"), JSON.stringify(bad));
}

// every locale composes all four sentences with no placeholder left and no percent
let checked = 0;
for (const f of fs.readdirSync(LOC).filter((n) => n.endsWith(".json"))) {
  const lang = f.replace(".json", "");
  const ui = build(lang);
  const all = []
    .concat(ui.recoveryLines({ active: true, wal_bytes: 3 * GIB, eta_s: null, basis: null, elapsed_s: 1 }))
    .concat(ui.recoveryLines({ active: true, wal_bytes: 3 * GIB, eta_s: 120, basis, elapsed_s: 500 }));
  assert.strictEqual(all.length, 5, lang);
  for (const line of all) {
    assert.ok(!/\{\w+\}/.test(line), lang + ": placeholder left in " + line);
    assert.ok(!line.includes("%"), lang + ": a percent in " + line);
  }
  assert.ok(strip(all[0]).includes("3.0") || strip(all[0]).includes("3,0"), lang + ": size missing");
  checked++;
}
assert.strictEqual(checked, 12);
console.log("unlock recovery node test OK");
