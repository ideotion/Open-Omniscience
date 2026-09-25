// Settings → Storage's renderers, run as REAL code (S04-08 slice 4; Q1006, Q1010, Q1011).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The slice's acceptance names this suite: "a node test that an unmeasured rate renders
// no figure". What it guards is a set of REFUSALS, and each pair below is a few
// characters apart in source and opposite on screen:
//
//   * an UNMEASURED growth draws words and NO DIGIT on the surface -- the numbers that
//     explain the wait ride the hover, where they cannot pass for a growth figure;
//   * `measured` must be `=== true`: a payload that says "yes", or forgot the delta,
//     falls through to the words rather than to a figure;
//   * a lane with no published budget says so, never "0" and never a number;
//   * an absent lane is "not created" or "not built", never "0 B" -- while a file that
//     exists and is EMPTY must still draw "0 B", because that is a measurement;
//   * an unreadable reading is named, never "null", "undefined" or "NaN".
//
// EXTRACTED from the shipped modules rather than re-typed: a re-typed copy would pass
// while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace (the recorded default-parameter trap).
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = APP.indexOf("{", i);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

function extractConst(name) {
  // The app's own esc() is an arrow const, not a declaration; the statement ends at the
  // first ";\n" (no newline sits inside its character map).
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}

const NAMES = [
  "humanBytes", "_storageLaneName", "_storageLaneHover", "_storageSignedBytes", "_storagePct",
  "_storageGrowthHtml", "_storageBudgetHtml", "_storageSizeHtml", "_storageTableHtml",
  "_storageReadingHtml", "_storageDiskHtml",
];
// `window` is defined so `window.OOI18N && ...` resolves to the fallbacks: a sandbox
// without it raises ReferenceError on the bare global read (the recorded node trap).
// The REAL esc(), so the Save button's quoting is checked against what ships, and the
// REAL bidi isolate the growth figures and dates go through (app-library.js).
const src =
  extractConst("esc") + "\n" +
  extractConst("_LTR_ISOLATE") + "\n" +
  extract("_ltrIsolate") + "\n" +
  "var window = {};\n" +
  NAMES.map(extract).join("\n") + "\n" +
  "module.exports = {" + NAMES.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

// What a reader SEES: tags and their attributes (the hovers) removed, entities decoded.
const FSI = "\u2068", PDI = "\u2069";
const visible = (html) => String(html)
  .replace(/[\u2068\u2069]/g, "")
  .replace(/<[^>]*>/g, " ")
  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&amp;/g, "&")
  .replace(/\s+/g, " ").trim();
const hovers = (html) => [...String(html).matchAll(/title="([^"]*)"/g)].map((m) => m[1]).join(" | ")
  .replace(/[\u2068\u2069]/g, "");
const rawHovers = (html) => [...String(html).matchAll(/title="([^"]*)"/g)].map((m) => m[1]).join(" | ");
const noJunk = (html, what) => {
  for (const bad of ["undefined", "null", "NaN"]) {
    assert.ok(!visible(html).includes(bad) && !hovers(html).includes(bad), `${what} drew "${bad}": ${html}`);
  }
};
const GIB = 1024 ** 3, MIB = 1024 ** 2;

// --- 1. growth: an unmeasured rate renders NO figure ---------------------------- //
{
  const cases = [
    { measured: false, reason: "no_history", samples: 0, window_days: 30, min_span_days: 7 },
    { measured: false, reason: "too_short", samples: 5, span_days: 2.5, window_days: 30, min_span_days: 7 },
    { measured: false, reason: "unreadable", samples: 0, window_days: 30, min_span_days: 7 },
    // A payload that says "yes" is not a measurement...
    { measured: "yes", reason: "too_short", delta_bytes: 5 * GIB, per_30_days_bytes: 9 * GIB, span_days: 3 },
    // ...and neither is one that forgot its delta.
    { measured: true, span_days: 12, samples: 40 },
  ];
  for (const g of cases) {
    const html = R._storageGrowthHtml(g);
    const seen = visible(html);
    assert.ok(seen.length > 0, "an unmeasured growth drew nothing at all: " + JSON.stringify(g));
    assert.ok(!/\d/.test(seen), `an unmeasured growth drew a figure: "${seen}" for ${JSON.stringify(g)}`);
    assert.ok(!/per 30 days/.test(seen), "an unmeasured growth drew a rate: " + seen);
    noJunk(html, "unmeasured growth");
  }
  // The wait is explained -- in the HOVER, where a number cannot pass for growth.
  const short = R._storageGrowthHtml(cases[1]);
  assert.ok(/7/.test(hovers(short)) && /2\.5/.test(hovers(short)),
    "the too-short hover lost the days it needs / has: " + hovers(short));
  assert.strictEqual(visible(short), "Not measured yet");
  assert.strictEqual(visible(R._storageGrowthHtml(cases[2])), "Could not be read");
  // An absent lane's size cell already explains itself; growth draws nothing there.
  assert.strictEqual(R._storageGrowthHtml({ measured: false, reason: "absent" }), "");
  assert.strictEqual(R._storageGrowthHtml({ measured: false, reason: "unmeasurable" }), "");
  assert.strictEqual(R._storageGrowthHtml(null), "");
}

// --- 2. growth: a measured rate renders its figure, signed ----------------------- //
{
  const up = R._storageGrowthHtml({ measured: true, delta_bytes: 1288 * MIB, per_30_days_bytes: 2760 * MIB,
    span_days: 14, samples: 200, from: "2026-09-11T08:00:00", to: "2026-09-25T08:00:00" });
  assert.ok(/^\+1\.3 GB in 14 days/.test(visible(up)), visible(up));
  assert.ok(/≈ \+2\.7 GB per 30 days at that rate/.test(visible(up)), visible(up));
  assert.ok(/200 readings/.test(hovers(up)) && /2026-09-11/.test(hovers(up)), hovers(up));
  const down = R._storageGrowthHtml({ measured: true, delta_bytes: -300 * MIB, per_30_days_bytes: -900 * MIB,
    span_days: 10, samples: 30, from: "2026-09-15T00:00:00", to: "2026-09-25T00:00:00" });
  assert.ok(/^−300\.0 MB in 10 days/.test(visible(down)), "a shrinking lane lost its sign: " + visible(down));
  const flat = R._storageGrowthHtml({ measured: true, delta_bytes: 0, per_30_days_bytes: 0,
    span_days: 9.4, samples: 12, from: "2026-09-16T00:00:00", to: "2026-09-25T00:00:00" });
  assert.strictEqual(visible(flat), "No change in 9 days");
  noJunk(up + down + flat, "measured growth");
  // In a right-to-left page a signed size and an ISO date reorder against the sentence
  // ("MB 6.0+", the year at the wrong end), so each rides inside a bidi isolate.
  assert.ok(up.includes(FSI + "+1.3 GB" + PDI) && up.includes(FSI + "+2.7 GB" + PDI),
    "a signed growth figure is not isolated for RTL: " + JSON.stringify(up));
  assert.ok(rawHovers(up).includes(FSI + "2026-09-11" + PDI) && rawHovers(up).includes(FSI + "2026-09-25" + PDI),
    "a hover date is not isolated for RTL: " + JSON.stringify(rawHovers(up)));
}

// --- 3. budget: never an invented number ------------------------------------------ //
{
  const none = R._storageBudgetHtml({ kind: "law", budget: { gb: null, published_gb: null, reason: "not_ruled" } });
  assert.strictEqual(visible(none), "No published budget");
  assert.ok(/never invents/.test(hovers(none)), hovers(none));
  const noTable = R._storageBudgetHtml({ kind: "wiki", budget: { gb: null, published_gb: null, reason: null } });
  assert.ok(/could not be read/.test(hovers(noTable)), "an unreadable table was explained as not ruled");

  const pub = R._storageBudgetHtml({ kind: "wiki", budget: { gb: 20, published_gb: 20, source: "published",
    used_share: 0.004, exhausted: false, setting: "wiki_lane_budget_gb", min_gb: 1, max_gb: 2000 } });
  assert.ok(/^20 GB the published default/.test(visible(pub)), visible(pub));
  assert.ok(/<1% used/.test(visible(pub)), "a lane holding something read as 0% used: " + visible(pub));
  assert.ok(/id="storage-budget-wiki"/.test(pub) && /min="1"/.test(pub) && /max="2000"/.test(pub),
    "the editable budget lost its field or its server bounds");
  assert.ok(pub.includes('saveLaneBudget(&quot;wiki&quot;, &quot;wiki_lane_budget_gb&quot;, this)'),
    "the save names the wrong setting, or quotes it by hand instead of esc(JSON.stringify(...))");

  const mine = R._storageBudgetHtml({ kind: "wiki", budget: { gb: 35, published_gb: 20, source: "yours",
    used_share: 0.5, exhausted: false } });
  assert.ok(/35 GB yours; the published default is 20 GB/.test(visible(mine)), visible(mine));
  assert.ok(!/<input/.test(mine), "a budget without server bounds was offered for editing");

  const full = R._storageBudgetHtml({ kind: "wiki", budget: { gb: 1, published_gb: 20, source: "yours",
    used_share: 1.02, exhausted: true } });
  assert.ok(/Budget reached: new page text is not stored/.test(visible(full)), visible(full));
  assert.ok(/102% used/.test(visible(full)), visible(full));
  noJunk(none + pub + mine + full, "budget");
}

// --- 4. size: absent is never 0 B; an empty file is ------------------------------ //
{
  const absent = R._storageSizeHtml({ kind: "wiki", implemented: true, size_state: "absent", bytes: null });
  assert.strictEqual(visible(absent), "Not created yet");
  const notBuilt = R._storageSizeHtml({ kind: "osm", implemented: false, size_state: "absent", bytes: null });
  assert.strictEqual(visible(notBuilt), "Not built yet");
  const unmeasurable = R._storageSizeHtml({ kind: "press", implemented: true, size_state: "unmeasurable", bytes: null });
  assert.strictEqual(visible(unmeasurable), "Cannot be measured");
  for (const h of [absent, notBuilt, unmeasurable]) assert.ok(!/\d/.test(visible(h)), "an absent lane drew a size: " + h);
  // A file that EXISTS and is empty is a measurement, and it draws.
  assert.strictEqual(visible(R._storageSizeHtml({ kind: "wiki", implemented: true, size_state: "present", bytes: 0 })), "0 B");
  const elsewhere = R._storageSizeHtml({ kind: "press", implemented: true, size_state: "present",
    bytes: 3 * GIB, other_volume_free_bytes: 50 * GIB });
  assert.ok(/On another drive: 50\.0 GB free/.test(visible(elsewhere)), visible(elsewhere));
}

// --- 5. the whole table carries every lane and the four headers ------------------ //
{
  const rep = { lanes: [
    { kind: "press", implemented: true, size_state: "present", bytes: 2 * GIB,
      budget: { gb: null, reason: "not_ruled" }, growth: { measured: false, reason: "no_history" } },
    { kind: "wiki", implemented: true, size_state: "absent", bytes: null,
      budget: { gb: 20, published_gb: 20, source: "published" }, growth: { measured: false, reason: "absent" } },
    { kind: "law", implemented: false, size_state: "absent", bytes: null,
      budget: { gb: null, reason: "not_ruled" }, growth: { measured: false, reason: "absent" } },
    { kind: "osm", implemented: false, size_state: "absent", bytes: null,
      budget: { gb: null, reason: "not_ruled" }, growth: { measured: false, reason: "absent" } },
  ] };
  const table = R._storageTableHtml(rep);
  for (const w of ["Lane", "On disk", "Budget", "Growth, last 30 days",
                   "Corpus", "Wikipedia / Wikimedia", "Law", "Maps / OpenStreetMap"]) {
    assert.ok(visible(table).includes(w), `the table lost "${w}"`);
  }
  assert.strictEqual((table.match(/<tr>/g) || []).length, 5, "one header row and one row per lane");
  noJunk(table, "table");
  assert.strictEqual(R._storageTableHtml({ lanes: [] }), "");
}

// --- 6. the boot reading: unreadable is named, the reference is stated ------------ //
{
  const ref = { reference_machine: { cores: 2, ram_gb: 3.5, ram_bytes: 3.5 * GIB } };
  const ok = R._storageReadingHtml({ reading: { when: "boot", cores: 8, ram_bytes: 16 * GIB, disk_free_bytes: 120 * GIB },
    table: ref });
  assert.ok(/This machine, read at boot: 8 CPU cores · 16\.0 GB of RAM · 120\.0 GB of free disk/.test(visible(ok)), visible(ok));
  assert.ok(/reference machine with 2 CPU cores and 3\.5 GB of RAM/.test(visible(ok)), visible(ok));

  const blind = R._storageReadingHtml({ reading: { when: "now", cores: null, ram_bytes: null, disk_free_bytes: null },
    table: ref });
  assert.ok(/read just now: CPU cores could not be read · RAM could not be read · free disk could not be read/.test(visible(blind)), visible(blind));
  noJunk(blind, "unreadable reading");

  // NO VERDICT between the reading and the reference, even for a genuinely small
  // machine: the reference's "3.5 GB" is what its class reports, so a strict "below"
  // would call the reference machine smaller than itself. The operator compares.
  const small = R._storageReadingHtml({ reading: { when: "boot", cores: 1, ram_bytes: 3.3 * GIB, disk_free_bytes: GIB },
    table: ref });
  assert.ok(!/below|fewer|less RAM|smaller/i.test(visible(small)), "the reading passed a verdict: " + visible(small));
  assert.ok(!/card-caveat/.test(small), "the reading drew a warning nobody ruled");

  const noTable = R._storageReadingHtml({ reading: { when: "boot", cores: 4, ram_bytes: 8 * GIB, disk_free_bytes: GIB },
    table: null, table_error: "the budget table is not valid YAML" });
  assert.ok(/budget table could not be read/.test(visible(noTable)), visible(noTable));
  assert.ok(/not valid YAML/.test(hovers(noTable)), "the table error left the hover");
}

// --- 7. disk left, and budgets against it ----------------------------------------- //
{
  const plenty = R._storageDiskHtml({ disk: { free_bytes: 100 * GIB, total_bytes: 250 * GIB }, claimable_bytes: 20 * GIB, budgets_fit: true });
  assert.ok(/Disk left: 100\.0 GB free of 250\.0 GB/.test(visible(plenty)), visible(plenty));
  assert.ok(/Your budgets can still take 20\.0 GB; the drive has 100\.0 GB free\./.test(visible(plenty)), visible(plenty));
  assert.ok(!/card-caveat/.test(plenty), "a budget that fits was drawn as a warning");

  const tight = R._storageDiskHtml({ disk: { free_bytes: 15 * GIB, total_bytes: 64 * GIB }, claimable_bytes: 20 * GIB, budgets_fit: false });
  assert.ok(/card-caveat/.test(tight) && /That is more than the drive has free/.test(visible(tight)),
    "budgets larger than the free disk were not said in words: " + visible(tight));
  // The tone is the SERVER's three-state answer: an unknown is neither a fit nor a warning.
  const unknown = R._storageDiskHtml({ disk: { free_bytes: 15 * GIB, total_bytes: 64 * GIB }, claimable_bytes: 20 * GIB, budgets_fit: null });
  assert.ok(!/card-caveat/.test(unknown) && !/more than the drive/.test(visible(unknown)), visible(unknown));

  const unread = R._storageDiskHtml({ disk: { free_bytes: null, total_bytes: null }, claimable_bytes: 20 * GIB });
  assert.ok(/could not be read/.test(visible(unread)) && !/\d/.test(visible(unread)),
    "an unreadable disk drew a figure: " + visible(unread));
  // No numeric budget at all: the comparison line is not drawn.
  assert.ok(!/budgets can still take/.test(visible(R._storageDiskHtml({ disk: { free_bytes: GIB, total_bytes: 2 * GIB }, claimable_bytes: null }))));
}

console.log("lane storage: all assertions passed");
