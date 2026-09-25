// The Living sources view's renderers, run as REAL code (S04-08 slice 6; Q1016).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What this view must NOT do is most of what it is, so most checks below are refusals:
//
//   * a lane that never ran reads "Not run yet", never a row of zeros -- zero is a
//     measurement, and there was nothing to measure;
//   * a change the stream only COUNTED reads as counted, with no diff button: there is
//     no stored text to show, and an empty diff would claim nobody changed anything;
//   * a change kind outside the four known ones is shown as the source sent it, never
//     mapped onto the nearest known word;
//   * the storage cells are Settings -> Storage's own, minus the budget's edit box
//     (this tab shows data; the setting stays in Settings, invariant #8);
//   * freshness is dates, never a verdict ("stale", "outdated", "healthy"...);
//   * every instant is said as UTC, because the digits on the wire are UTC;
//   * a failed map download is counted and explained under the manager's own word.
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
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}

// Settings -> Storage's cells (reused, never copied) and the task manager's cause line.
const HELPERS = [
  "humanBytes", "_storageLaneName", "_storageLaneHover", "_storageSignedBytes", "_storagePct",
  "_storageGrowthHtml", "_storageBudgetHtml", "_storageSizeHtml", "_jobWhy",
];
const LIVING = [
  "livingWhen", "livingSigned", "livingFactHtml", "livingGroupsHtml", "_livingUnmeasured",
  "livingStorageGroup", "livingWikiGroups", "livingLawGroups", "livingMapGroups", "livingGroupsFor",
  "livingDiffHtml", "livingStreamRowsHtml", "livingLawRowsHtml", "livingMapRowsHtml",
];
// `window` is defined so `window.OOI18N && ...` resolves to the fallbacks: a sandbox
// without it raises ReferenceError on the bare global read (the recorded node trap).
const src =
  extractConst("esc") + "\n" +
  extractConst("_LTR_ISOLATE") + "\n" +
  extract("_ltrIsolate") + "\n" +
  extractConst("_isDownloadKind") + "\n" +
  extractConst("_LIVING_CHANGE_KINDS") + "\n" +
  extractConst("_LIVING_MAP_STATE") + "\n" +
  "var window = {};\n" +
  // The Q302 display helpers are STUBBED to mark what passed through them: their own
  // behaviour (the alpha-3 / 639-2/T code, the localised hover) is pinned by
  // country_display_node_test.js against the real tables; what matters here is that
  // this view hands them the value instead of printing it raw.
  "function ooCountryCell(v, o) { return '<span class=\"' + ((o && o.cls) || '') + '\">CC(' + esc(v) + ')</span>'; }\n" +
  "function ooLangCell(v, o) { return '<span class=\"' + ((o && o.cls) || '') + '\">LC(' + esc(v) + ')</span>'; }\n" +
  HELPERS.map(extract).join("\n") + "\n" +
  LIVING.map(extract).join("\n") + "\n" +
  "module.exports = {humanBytes, " + LIVING.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
// What a reader SEES: tags and their attributes (the hovers) removed, entities decoded.
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html)
  .replace(/[⁨⁩]/g, "")
  .replace(/<[^>]*>/g, " "))
  .replace(/\s+/g, " ").trim();
const hovers = (html) => decode([...String(html).matchAll(/title="([^"]*)"/g)].map((m) => m[1]).join(" | "));
const noJunk = (html, what) => {
  for (const bad of ["undefined", "null", "NaN", "[object Object]"]) {
    assert.ok(!visible(html).includes(bad) && !hovers(html).includes(bad), `${what} drew "${bad}": ${html}`);
  }
};
const VERDICTS = /\b(stale|outdated|out of date|up[- ]to[- ]date|healthy|unhealthy|score|good|bad|behind schedule)\b/i;
const noVerdict = (html, what) => {
  const m = (visible(html) + " " + hovers(html)).match(VERDICTS);
  assert.ok(!m, `${what} passes a verdict ("${m && m[0]}"): ${visible(html)}`);
};
const GIB = 1024 ** 3;
const group = (groups, title) => {
  const g = groups.find((x) => x.title === title);
  assert.ok(g, `no "${title}" group in ${groups.map((x) => x.title)}`);
  return R.livingGroupsHtml([g]);
};

// --- 1. dates are UTC, and "never" is a word -------------------------------------- //
assert.strictEqual(R.livingWhen(null, t), "never");
assert.strictEqual(visible(R.livingWhen("2026-09-25T10:11:12.345+00:00", t)), "2026-09-25 10:11 UTC");
assert.ok(R.livingWhen("2026-09-25T10:11:12+00:00", t).includes("⁨"),
  "a date was not bidi-isolated: an Arabic page would reorder its digits");
assert.strictEqual(visible(R.livingSigned(40)), "+40");
assert.strictEqual(visible(R.livingSigned(-7)), "-7");
assert.strictEqual(R.livingSigned(null), "", "an absent size change drew a figure");

// --- 2. the stream: never run, unreadable, measured -------------------------------- //
const STORAGE = {
  kind: "wiki", implemented: true, size_state: "present", bytes: 5 * GIB,
  budget: { gb: 20, source: "published", used_share: 0.25, exhausted: false,
    setting: "wiki_budget_gb", min_gb: 1, max_gb: 500, published_gb: 20, reason: null },
  growth: { measured: false, reason: "not-enough-readings" },
};
{
  const groups = R.livingWikiGroups({ kind: "wiki", stream: { measured: false, reason: "lane-never-run" },
    tracked: { measured: false, reason: "unreadable" }, storage: STORAGE }, t, tf);
  const stream = group(groups, "Live stream");
  assert.ok(visible(stream).includes("Not run yet"), stream);
  assert.ok(!/\d/.test(visible(stream).replace("Live stream", "")),
    "a lane that never ran drew a figure: zero is a measurement, and nothing was measured");
  assert.ok(hovers(stream).includes("never run"), "the reason is not in the hover");
  const tracked = group(groups, "Pages you track");
  assert.ok(visible(tracked).includes("Could not be read"), tracked);
  assert.ok(hovers(tracked).includes("other figures on this page are unaffected"));
  noJunk(R.livingGroupsHtml(groups), "the unmeasured wiki groups");
}
const WIKI = {
  kind: "wiki",
  stream: { measured: true, pages: 12, changes: 10, changes_with_text: 3, changes_not_followed: 480,
    last_change_at: "2026-09-25T09:00:00+00:00", contiguous_through: null,
    cursor_read_at: "2026-09-25T09:01:00+00:00", open_gaps: 1 },
  tracked: { measured: true, pages: 4, never_checked: 1, newest_check_at: "2026-09-25T08:00:00+00:00",
    oldest_check_at: "2026-08-01T08:00:00+00:00", changes: 6, flagged: 2 },
  storage: STORAGE,
};
{
  const groups = R.livingWikiGroups(WIKI, t, tf);
  const stream = group(groups, "Live stream");
  assert.ok(visible(stream).includes("Text stored for 3 of 10"),
    "the stored share must read as n of m -- the numerator alone overstates what was kept");
  assert.ok(visible(stream).includes("Complete through Not declared yet"),
    "a feed with no declared point drew a date or a zero");
  assert.ok(visible(stream).includes("2026-09-25 09:00 UTC"));
  const tracked = group(groups, "Pages you track");
  assert.strictEqual(visible(tracked).split("Pages you track").length - 1, 1,
    "the group's title was repeated as its first label (seen in the Chromium walk)");
  assert.ok(visible(tracked).includes("Oldest check 2026-08-01 08:00 UTC"),
    "the OLDEST check is the freshness figure that matters; it must be shown as a date");
  const all = R.livingGroupsHtml(groups);
  noJunk(all, "the measured wiki groups");
  noVerdict(all, "the measured wiki groups");
}

// --- 3. storage: Settings' own cells, without the edit box ------------------------- //
{
  const g = R.livingStorageGroup(STORAGE, t);
  const html = R.livingGroupsHtml([g]);
  assert.ok(!/<input/i.test(html) && !html.includes("saveLaneBudget"),
    "the budget's edit box leaked into a data tab (invariant #8: the setting lives in Settings)");
  assert.ok(visible(html).includes(R.humanBytes(5 * GIB)), html);
  assert.ok(visible(html).includes("20 GB") && visible(html).includes("25% used"), html);
  assert.strictEqual(STORAGE.budget.setting, "wiki_budget_gb", "the renderer mutated the payload it was given");
  const none = R.livingGroupsHtml([R.livingStorageGroup(null, t)]);
  assert.ok(visible(none).includes("Could not be read") && !/\d/.test(visible(none)),
    "an unreadable storage report drew a figure");
}

// --- 4. law and maps ---------------------------------------------------------------- //
{
  const law = R.livingGroupsHtml(R.livingLawGroups({ kind: "law", tracker: { measured: true, documents: 9,
    jurisdictions: 3, never_checked: 0, newest_check_at: "2026-09-24T00:00:00+00:00",
    oldest_check_at: null, changes: 2, flagged: 1 }, storage: null }, t));
  assert.ok(visible(law).includes("Oldest check never"), law);
  noJunk(law, "the law groups");
  noVerdict(law, "the law groups");
  const maps = R.livingGroupsHtml(R.livingMapGroups({ kind: "osm", maps: { measured: true, regions: 5,
    by_state: { done: 1, downloading: 1, queued: 0, paused: 1, error: 2 }, other_state: 0,
    bytes_on_disk: 3 * GIB, freshness: { measured: false, reason: "not-recorded" } }, storage: null }, t));
  assert.ok(visible(maps).includes("Failed 2"),
    "failed downloads were not counted: the manager writes 'error', not 'failed'");
  assert.ok(visible(maps).includes("Date of the map data Not recorded"),
    "the file's own write time must never stand in for the date of the map data");
  noJunk(maps, "the map groups");
  assert.deepStrictEqual(R.livingGroupsFor({ kind: "radio" }, t, tf), [], "an unknown source drew groups");
  assert.deepStrictEqual(R.livingGroupsFor(null, t, tf), []);
}

// --- 5. the stream's timeline --------------------------------------------------------- //
{
  assert.ok(visible(R.livingStreamRowsHtml([], t, tf)).startsWith("No changes recorded"));
  const rows = R.livingStreamRowsHtml([
    { id: 1, change_kind: "edit", recorded_at: "2026-09-25T09:00:00+00:00", byte_delta: 40,
      title: "Rome <b>", language: "en", text_stored: true, revision_id: 42,
      diff_method: "unified", diff_added: 3, diff_removed: 1 },
    { id: 2, change_kind: "log-thing", recorded_at: "2026-09-25T08:55:00+00:00", byte_delta: null,
      title: "Paris", language: "fr", text_stored: false, revision_id: null,
      diff_method: null, diff_added: null, diff_removed: null },
    { id: 3, change_kind: "create", recorded_at: "2026-09-25T08:50:00+00:00", byte_delta: 900,
      title: "Lyon", language: "fr", text_stored: true, revision_id: 43,
      diff_method: "no-previous-text", diff_added: null, diff_removed: null },
    { id: 4, change_kind: "delete", recorded_at: "2026-09-25T08:45:00+00:00", byte_delta: -5,
      title: "Nice", language: "fr", text_stored: true, revision_id: 44,
      diff_method: "too-large", diff_added: null, diff_removed: null },
  ], t, tf);
  const parts = rows.split('<div class="living-row">').slice(1);
  assert.strictEqual(parts.length, 4);
  const [edit, counted, created, large] = parts;
  assert.ok(visible(edit).includes("Lines added: 3, removed: 1") && edit.includes("livingShowDiff(42, this)"), edit);
  assert.ok(edit.includes('id="living-diff-42"'));
  assert.ok(visible(edit).includes("Rome <b>") && !edit.includes("Rome <b>"), "a title was not escaped");
  assert.ok(visible(edit).includes("+40"));
  assert.ok(visible(edit).includes("LC(en)"), "the language went to the screen without its display helper (Q302)");
  assert.ok(visible(counted).includes("Counted only"), counted);
  assert.ok(!counted.includes("livingShowDiff") && !counted.includes("living-diff-"),
    "a counted-only change offered a diff: there is no stored text to show");
  assert.ok(visible(counted).includes("log-thing"), "an unknown change kind was not shown as sent");
  assert.ok(hovers(counted).includes("The source's own word"), "an unknown kind carries no explanation");
  assert.ok(visible(created).includes("no earlier stored text") && !created.includes("livingShowDiff"));
  assert.ok(visible(large).includes("too large") && !large.includes("livingShowDiff"));
  assert.ok(visible(large).includes("deletion"), "a known kind was not shown as its noun");
  const proto = R.livingStreamRowsHtml([{ id: 5, change_kind: "constructor", title: "X",
    text_stored: false, revision_id: null }], t, tf);
  assert.ok(visible(proto).includes("constructor") && !proto.includes("function"),
    "a kind named like an Object property was looked up on the prototype");
  noJunk(rows, "the stream rows");
  noVerdict(rows, "the stream rows");
}

// --- 6. a stored diff, coloured and escaped ------------------------------------------- //
{
  const d = R.livingDiffHtml("--- previous\n+++ current\n@@ -1 +1 @@\n+new <script>\n-old\n same");
  const lines = d.split("</div>").filter(Boolean);
  assert.strictEqual(lines.length, 6);
  assert.ok(lines[0].includes("var(--muted)") && lines[1].includes("var(--muted)") && lines[2].includes("var(--muted)"),
    "a unified header was coloured as an added or removed line");
  assert.ok(lines[3].includes("var(--ok)") && lines[4].includes("var(--err)") && lines[5].includes("var(--muted)"));
  assert.ok(!d.includes("<script>") && d.includes("&lt;script&gt;"), "diff text was not escaped");
  assert.strictEqual(R.livingDiffHtml(null).includes("null"), false);
}

// --- 7. law rows -------------------------------------------------------------------------- //
{
  assert.ok(visible(R.livingLawRowsHtml([], t)).startsWith("No changes recorded"));
  const rows = R.livingLawRowsHtml([
    { id: 1, document_id: 7, jurisdiction: "fr", title: "Code civil", observed_at: "2026-09-20T12:00:00",
      delta_bytes: -1200, flagged: true, flag_reasons: ["large-removal", ""], diff: "-old line\n+new line" },
    { id: 2, document_id: 8, jurisdiction: "de", title: "BGB", observed_at: "2026-09-19T12:00:00",
      delta_bytes: 30, flagged: false, flag_reasons: [], diff: "" },
  ], t);
  const [fr, de] = rows.split('<div class="living-row">').slice(1);
  assert.ok(visible(fr).includes("CC(fr)") && visible(fr).includes("-1200") && visible(fr).includes("large-removal"),
    "the jurisdiction went to the screen without its display helper (Q302)");
  assert.strictEqual((fr.match(/pill warn/g) || []).length, 1, "an empty flag reason drew an empty pill");
  assert.ok(fr.includes("<details>") && fr.includes("var(--err)"), "the stored diff is missing");
  assert.ok(fr.includes('href="/api/law/documents/7/view"'), "the local stored copy is not linked first (invariant #6)");
  assert.ok(!/href="https?:/.test(rows), "a law row linked straight outside the app");
  assert.ok(visible(de).includes("No stored diff") && !de.includes("<details>"));
  assert.ok(visible(fr).includes("2026-09-20 12:00 UTC"));
  noJunk(rows, "the law rows");
}

// --- 8. map rows: the manager's word, the task manager's cause line ------------------- //
{
  assert.ok(visible(R.livingMapRowsHtml([], t)).includes("Settings → OpenStreetMap"));
  const rows = R.livingMapRowsHtml([
    { key: "fr", name: "France", status: "error", downloaded_bytes: 0, total_bytes: 0, error: "HTTP 503" },
    { key: "de", name: "Germany", status: "paused", paused_by: "airplane", downloaded_bytes: GIB, total_bytes: 4 * GIB },
    { key: "it", name: "Italy", status: "verifying", downloaded_bytes: 10, total_bytes: 0 },
  ], t);
  const [fr, de, it] = rows.split("<tr>").slice(2);
  assert.ok(visible(fr).includes("Failed") && visible(fr).includes("Failed: HTTP 503"),
    "a failed download did not say why: the manager's 'error' must reach the cause line as a failure");
  assert.ok(visible(de).includes("Paused by airplane mode"), de);
  assert.ok(visible(de).includes(`${R.humanBytes(GIB)} / ${R.humanBytes(4 * GIB)}`), de);
  assert.ok(visible(it).includes("verifying"), "an unknown state was mapped instead of shown");
  noJunk(rows, "the map rows");
}

// --- 9. every word goes through the translator ------------------------------------------ //
{
  const seen = new Set();
  const tt = (s) => { seen.add(s); return "«" + s + "»"; };
  // The storage cells are left out of the label sweep: they translate through the page's
  // own OOI18N (Settings -> Storage's code), which this sandbox does not load.
  const groups = R.livingWikiGroups(WIKI, tt, tf);
  const html = R.livingGroupsHtml(groups.slice(0, 2));
  for (const label of ["Live stream", "Pages followed", "Text stored for", "Complete through", "Pages you track", "Pages", "Storage"]) {
    assert.ok(seen.has(label), `"${label}" never reached the translator`);
  }
  for (const m of html.matchAll(/<div class="muted">([^<]*)<\/div>/g)) {
    assert.ok(m[1].startsWith("«"), `a label skipped the translator: ${m[1]}`);
  }
  const rows = R.livingStreamRowsHtml([{ id: 1, change_kind: "edit", recorded_at: null, title: "X",
    text_stored: false, revision_id: null }], tt, tf);
  assert.ok(visible(rows).includes("«edit»"), "a known change kind was not translated");
  assert.ok(visible(rows).includes("«never»"), "a missing date was not translated");
}

console.log("living_sources_node_test: all checks passed");
