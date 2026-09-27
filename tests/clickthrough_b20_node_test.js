/**
 * Behavioural node test for batch B20 of the 2026-09-27 row R walk (the five ooMap
 * surfaces): a contested area named in the reader's language (R1), one worldview across
 * every drawn map (R3), the Statistics and Super-groups maps following a language switch
 * from the payload they hold (R4), the Governments map's unit word translated (R6) and
 * the contested claims reachable by the shared #oo-tip bubble (R9).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention;
 * see tests/clickthrough_b12_node_test.js). Translations come from the REAL locale files.
 *
 * Run by tests/test_clickthrough_b20_maps.py (and standalone:
 * `node tests/clickthrough_b20_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const read = (name) => fs.readFileSync(path.join(STATIC, name), "utf-8");
const MAP = read("app-map.js");
const CORE = read("app-core.js");
const GOV = read("app-gov-law.js");
const INS = read("app-insights.js");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) {
  return Promise.resolve().then(fn).then(() => { passed += 1; console.log("ok  - " + name); });
}

// Same balanced-brace extraction every node suite here uses (duplicated per convention).
function extract(name, decl, src) {
  const head = decl || ("function " + name + "(");
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

const ESC = `const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));`;

// A fake i18n engine over a real locale, shaped like src/static/i18n.js's export --
// which has `current()` and NO `lang` property. That absence is R1's whole defect.
function i18n(lang) {
  const map = lang === "en" ? {} : LOCALE(lang);
  return {
    t: (s) => (map[s] == null ? s : map[s]),
    tf: (s, v) => {
      let out = map[s] == null ? s : map[s];
      if (v) out = out.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
      return out;
    },
    current: () => lang,
  };
}

// A contested area in the asset's own shape (src/static/world_disputed.json).
const AREA = {
  id: "1159321231", name: "Abyei",
  names: { en: "Abyei", fr: "Abyei-FR", ar: "أبيي", zh: "阿卜耶伊" },
  claims: [{ a2: "sd", name: "Sudan", self: false }, { a2: "ss", name: "S. Sudan", self: false }],
  views: { iso: null, ru: "sd" },
  rings: [[[28, 9], [29, 9], [29, 10], [28, 10], [28, 9]]],
};

function disputedModule(lang) {
  const window = { OOI18N: i18n(lang) };
  const src = ESC + "\n"
    + "const project = (lon, lat) => ({ x: lon, y: lat });\n"
    + "const ooRegionName = (code, fb) => 'N[' + code + ']';\n"
    + extract("ooLabelText", null, CORE) + "\n"
    + extract("_ooDisputedViewNote", null, MAP) + "\n"
    + extract("_ooDisputedName", null, MAP) + "\n"
    + extract("_ooDisputedClaims", null, MAP) + "\n"
    + extract("_ooMapPath", null, MAP) + "\n"
    + extract("_ooDisputedLayer", null, MAP) + "\n"
    + "return { _ooDisputedName, _ooDisputedLayer };";
  const OOI18N = window.OOI18N;
  // eslint-disable-next-line no-new-func
  return new Function("window", "OOI18N", src)(window, OOI18N);
}

async function run() {
  // ============ R1: the area's own name, in the reader's language ============ //
  await test("R1: a contested area is named from the ACTIVE locale, through current()", () => {
    for (const lang of ["fr", "ar", "zh"]) {
      const m = disputedModule(lang);
      assert(m._ooDisputedName(AREA) === AREA.names[lang],
        lang + ": the area kept its English name: " + m._ooDisputedName(AREA));
    }
    assert(disputedModule("en")._ooDisputedName(AREA) === "Abyei", "English is the English name");
  });

  await test("R1: a locale the source has no NAME_<lang> for falls back to the English name", () => {
    const m = disputedModule("bn");
    assert(m._ooDisputedName(AREA) === "Abyei", "no bn name must read the English one");
  });

  // ============ R9: the claims ride the #oo-tip convention's carrier =========== //
  await test("R9: a contested path carries its claims as a title ATTRIBUTE, not an SVG <title>", () => {
    const m = disputedModule("fr");
    const out = m._ooDisputedLayer({ areas: [AREA] }, "contested", () => "#000", {});
    assert(out.shown === 1, "the area was not drawn");
    assert(!/<title>/.test(out.markup),
      "a <title> child only reaches a mouse, and beside the bubble it is a second tooltip: " + out.markup);
    const m2 = /<path [^>]*data-oomap-disputed="1159321231"[^>]* title="([^"]*)"/.exec(out.markup);
    assert(m2, "the contested path has no title attribute for #oo-tip to mark: " + out.markup);
    // Both claims and the area's name are in the ONE hover the bubble reads.
    assert(m2[1].indexOf("Abyei-FR") === 0, "the hover does not lead with the area's name: " + m2[1]);
    assert(m2[1].indexOf("N[sd]") !== -1 && m2[1].indexOf("N[ss]") !== -1, "a claim is missing: " + m2[1]);
  });

  await test("R9: under a named worldview the path still carries the hover, and drills", () => {
    const m = disputedModule("en");
    const out = m._ooDisputedLayer({ areas: [AREA] }, "ru", () => "#123", { sd: 5 });
    assert(/data-iso="sd"/.test(out.markup) && / title="[^"]*attributed to/.test(out.markup),
      "the attributed path lost its drill or its hover: " + out.markup);
  });

  // ============ R3: one worldview, every drawn map ============================ //
  await test("R3: a worldview change re-renders every OTHER drawn map from its own options", () => {
    const calls = [];
    const mk = (id, opts, connected) => {
      const host = { id, _ooOpts: opts, isConnected: connected !== false };
      const wrap = { parentElement: host };
      return { host, svg: { closest: (sel) => (sel === ".oomap-wrap" ? wrap : null) } };
    };
    const a = mk("oo-coverage-map", { tag: "world" });
    const b = mk("coverage-map", { tag: "sources" });
    const c = mk("gov-map-host", null);                    // never drawn with options
    const d = mk("statfig-map", { tag: "stat" }, false);   // detached from the document
    const document = { querySelectorAll: (sel) => (sel === "svg#oo-choro" ? [a.svg, b.svg, c.svg, d.svg] : []) };
    const src = extract("_ooMapRedrawOthers", null, MAP) + "\nreturn _ooMapRedrawOthers;";
    // eslint-disable-next-line no-new-func
    const redraw = new Function("document", "ooMap", src)(document, (host, opts) => { calls.push([host.id, opts.tag]); });
    redraw(a.host);
    assert(JSON.stringify(calls) === JSON.stringify([["coverage-map", "sources"]]),
      "expected only the Sources map to be redrawn, got " + JSON.stringify(calls));
  });

  await test("R3: the change handler calls that redraw after re-rendering its own host", () => {
    const wire = extract("_wireOoMap", null, MAP);
    const at = wire.indexOf('wvSel.addEventListener("change"');
    assert(at !== -1, "the worldview change handler moved");
    const handler = wire.slice(at, wire.indexOf("});", at));
    assert(handler.indexOf("_ooMapRedrawOthers(host)") > handler.indexOf("void ooMap(host"),
      "a worldview change must reach every other drawn map: " + handler);
  });

  // ============ R4: the two maps that did not follow a language switch ========= //
  await test("R4: the Statistics map redraws from its cached payload, only when drawn, no fetch", async () => {
    const drawn = [];
    const hostWith = (hasSvg) => ({ querySelector: (sel) => (sel === "svg#oo-choro" && hasSvg ? {} : null) });
    const make = (host, last) => {
      const src = "let _statMapLast = LAST;\n" + extract("repaintStatMapFromCache", null, MAP)
        + "\nreturn repaintStatMapFromCache;";
      // eslint-disable-next-line no-new-func
      return new Function("$", "_statMapDraw", "esc", "LAST", "api", src)(
        (id) => (id === "statfig-map" ? host : { id }),
        async (...args) => { drawn.push(args); },
        (s) => s, last,
        () => { throw new Error("a language switch must never fetch"); });
    };
    const last = { d: { cells: [1] }, series: "SP.DYN.LE00.IN", isLevel: false };
    make(hostWith(false), last)();
    make(hostWith(true), null)();
    assert(drawn.length === 0, "redrew a map that was never drawn: " + drawn.length);
    make(hostWith(true), last)();
    await Promise.resolve();
    assert(drawn.length === 1 && drawn[0][2] === last.d && drawn[0][3] === last.series,
      "did not redraw from the cached payload: " + JSON.stringify(drawn));
  });

  await test("R4: the ring map redraws through showRingMap with the payload it holds", () => {
    const calls = [];
    const hostWith = (hasSvg) => ({ querySelector: (sel) => (sel === "svg#oo-choro" && hasSvg ? {} : null) });
    const make = (host, last) => {
      const src = "let _ringMapLast = LAST;\n" + extract("repaintRingMapFromCache", null, INS)
        + "\nreturn repaintRingMapFromCache;";
      // eslint-disable-next-line no-new-func
      return new Function("$", "showRingMap", "LAST", src)(
        (id) => (id === "sg-ringmap" ? host : null), (...a) => calls.push(a), last);
    };
    const last = { ringId: "election", d: { found: true, countries: [] } };
    make(hostWith(false), last)();
    assert(calls.length === 0, "redrew a ring map that holds no drawn map");
    make(hostWith(true), last)();
    assert(calls.length === 1 && calls[0][0] === "election" && calls[0][1] === last.d,
      "the redraw must pass the cached payload so showRingMap skips its fetch: " + JSON.stringify(calls));
    // ...and showRingMap really does skip the fetch when handed one.
    const body = extract("showRingMap", "async function showRingMap(", INS);
    assert(/const d = cached \|\| await api\(/.test(body), "showRingMap fetches even with a cached payload");
  });

  // ============ R6: the Governments map's unit word ============================ //
  await test("R6: the Governments map hands ooMap the unit WORD translated, a symbol unchanged", async () => {
    const seen = [];
    const run = async (lang, unit) => {
      const OOI18N = i18n(lang);
      const src = "let _govMapLast = null;\n"
        + extract("_govMapCaveatText", null, GOV) + "\n"
        + extract("_govMapDraw", "async function _govMapDraw(", GOV) + "\nreturn _govMapDraw;";
      // eslint-disable-next-line no-new-func
      const draw = new Function("window", "OOI18N", "$", "ooMap", "ooRegionName", "_govIndLabel",
        "ooLabelText", "ooCountryCode", "ooCountryTitle", "_govFmt", src)(
        { OOI18N }, OOI18N, () => ({ textContent: "" }), async (host, opts) => { seen.push(opts.unit); },
        (c) => c, (s) => s, (a, b) => a + ": " + b, (c) => c, (c) => c, (v) => String(v));
      await draw({}, { label: "Life expectancy at birth (years)", unit }, { by_country: [{ country: "fr", value: 82 }] });
      return seen[seen.length - 1];
    };
    assert(await run("fr", "years") === LOCALE("fr")["years"], "fr kept the English unit word");
    assert(await run("zh", "years") === LOCALE("zh")["years"], "zh kept the English unit word");
    assert(await run("ar", "index") === LOCALE("ar")["index"], "ar kept the English unit word 'index'");
    assert(await run("fr", "%") === "%", "a symbol must pass through unchanged");
    assert(await run("fr", "USD") === "USD", "a currency code must pass through unchanged");
  });

  console.log("all assertions passed (" + passed + " tests)");
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
