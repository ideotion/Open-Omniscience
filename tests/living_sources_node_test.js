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
  "_sizeText", "humanBytes", "_storageLaneName", "_storageLaneHover", "_storageSignedBytes", "_storagePct",
  "_storageGrowthHtml", "_storageBudgetHtml", "_storageSizeHtml", "ooLabelText", "_jobWhy",
  "_jobLabel", "_framedText",
];
const LIVING = [
  "livingWhen", "livingSigned", "livingFactHtml", "livingGroupsHtml", "_livingUnmeasured",
  "livingStorageGroup", "_livingCount", "livingRunFacts", "livingWalkGroup", "livingCoverageGroup", "livingLocatedFact", "livingWarmGroup", "livingWikiGroups", "livingLawGroups",
  "livingMapGroups", "livingDailyGroup", "livingGroupsFor",
  "livingDiffHtml", "livingStreamRowsHtml", "livingLawRowsHtml", "livingMapRowsHtml",
  "lawFloorStateWords", "lawFloorStateWhy", "lawFloorBasisWords", "lawFloorStatesIn", "lawFloorCountsHtml", "livingLawFloorHtml",
];
// `window` is defined so `window.OOI18N && ...` resolves to the fallbacks: a sandbox
// without it raises ReferenceError on the bare global read (the recorded node trap).
const src =
  "function ooLtrIsolate(s){return String(s==null?'':s);} function ooLtrPct(s){return String(s==null?'':s);}" + "\n" +
  "function ooIsoDate(s){return String(s==null?'':s).slice(0,10);}" + "\n" +
    extractConst("esc") + "\n" +
  extractConst("_LTR_ISOLATE") + "\n" +
  extract("_ltrIsolate") + "\n" +
  extractConst("_isDownloadKind") + "\n" +
  extractConst("_LIVING_CHANGE_KINDS") + "\n" +
  extractConst("_LIVING_MAP_STATE") + "\n" +
  extractConst("_LIVING_WALK_STATE") + "\n" +
  extractConst("_LIVING_WALK_WHY") + "\n" +
  extractConst("_LIVING_WARM_STATE") + "\n" +
  extractConst("_LIVING_WARM_WHY") + "\n" +
  extractConst("_LIVING_TRANSPORT") + "\n" +
  extractConst("_LAW_FLOOR_ORDER") + "\n" +
  "var window = {};\n" +
  // The Q302 display helpers are STUBBED to mark what passed through them: their own
  // behaviour (the alpha-3 / 639-2/T code, the localised hover) is pinned by
  // country_display_node_test.js against the real tables; what matters here is that
  // this view hands them the value instead of printing it raw.
  "function ooCountryCell(v, o) { return '<span class=\"' + ((o && o.cls) || '') + '\">CC(' + esc(v) + ')</span>'; }\n" +
  "function ooLangCell(v, o) { return '<span class=\"' + ((o && o.cls) || '') + '\">LC(' + esc(v) + ')</span>'; }\n" +
  "function ooLangCode(v) { return 'L3(' + v + ')'; }\n" +
  "function ooLangName(v, fb) { return 'NAME(' + v + ')'; }\n" +
  // The reader's own label frame lives in app-core.js ("{prefix}: {text}" per locale); the view must use it, not weld a colon.
  "function ooLabelHtml(label, value) { return label + ' :: ' + value; }\n" +
  HELPERS.map(extract).join("\n") + "\n" +
  LIVING.map(extract).join("\n") + "\n" +
  "module.exports = {humanBytes, _jobWhy, " + LIVING.join(", ") + "};";
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

// --- 2b. the run: hours across restarts, and a visible line when the lane has gone quiet ---- //
{
  const run = { measured: true, hours: 60.4, stops_n: 1, idle_now: null,
    first_activity_at: "2026-09-14T00:00:00+00:00", last_activity_at: "2026-09-16T22:00:00+00:00" };
  const stream = group(R.livingWikiGroups({ ...WIKI, stream: { ...WIKI.stream, run } }, t, tf), "Live stream");
  assert.ok(visible(stream).includes("Run so far 60 hours of activity, stops: 1"), visible(stream));
  assert.ok(!visible(stream).includes("No sign of life"), "an active lane drew the stopped line");
  const quiet = { ...run, idle_now: { since: "2026-09-16T23:00:00+00:00", hours: 6.2 } };
  const quietGroups = R.livingWikiGroups({ ...WIKI, stream: { ...WIKI.stream, run: quiet } }, t, tf);
  const q = group(quietGroups, "Live stream");
  assert.ok(visible(q).includes("Stopped No sign of life for 6 hours"), visible(q));
  assert.ok(visible(q).includes("Last sign of life 2026-09-16 22:00 UTC"),
    "the time of the last sign of life is its own figure, never inside the sentence");
  assert.ok(hovers(q).includes("Go online with the airplane button"), "the way back was not stated");
  // No reading is not a run of zero hours: no figure is drawn, and a lane with a file but no sign
  // of life in the window SAYS so (a lane that stopped a week ago is the case that matters most).
  for (const bad of [undefined, null]) {
    const g = group(R.livingWikiGroups({ ...WIKI, stream: { ...WIKI.stream, run: bad } }, t, tf), "Live stream");
    assert.ok(!visible(g).includes("Run so far"), "drew a run from a payload with no run block");
  }
  const none = group(R.livingWikiGroups({ ...WIKI, stream: { ...WIKI.stream,
    run: { measured: false, reason: "x", window_days: 7, hours: null } } }, t, tf), "Live stream");
  assert.ok(visible(none).includes("Run so far No sign of life in the last 7 days"), visible(none));
  assert.ok(!/Run so far \d/.test(visible(none)), "drew a figure for no reading");
  const unread = group(R.livingWikiGroups({ ...WIKI, stream: { ...WIKI.stream,
    run: { measured: false, reason: "the run clock could not be read: OperationalError" } } }, t, tf), "Live stream");
  assert.ok(visible(unread).includes("Run so far Could not be read"), visible(unread));
  assert.ok(!hovers(unread).includes("no walk request made"),
    "an unreadable run clock claimed a measured absence in its hover");
  noJunk(R.livingGroupsHtml(quietGroups), "the run rows");
  noVerdict(R.livingGroupsHtml(quietGroups), "the run rows");
}

// --- 3. storage: Settings' own cells, without the edit box ------------------------- //
{
  const g = R.livingStorageGroup(STORAGE, t);
  const html = R.livingGroupsHtml([g]);
  assert.ok(!/<input/i.test(html) && !html.includes("saveLaneBudget"),
    "the budget's edit box leaked into a data tab (invariant #8: the setting lives in Settings)");
  // visible() on both sides: a size carries its own bidi isolate since P8 (2026-09-26).
  assert.ok(visible(html).includes(visible(R.humanBytes(5 * GIB))), html);
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
  // The OSM lane's daily change files (S06-01 S5): counts, the newest file's OWN date, re-baselines as dated events with the country.
  const DAILY = { measured: true, countries_cut: 3, countries_updated: 2, files_applied: 41, newest_file_at: "2026-11-04T23:59:00+00:00",
    last_applied_at: "2026-11-05T01:00:00+00:00", rebaselines_total: 2, hand_recuts: 1, rebaselines_not_shown: 0,
    rebaselines: [{ alpha3: "FRA", detected_at: "2026-10-30T08:15:00+00:00", from_time: null, to_time: null },
                  { alpha3: "DEU", detected_at: "2026-09-01T07:00:00+00:00", from_time: null, to_time: null }] };
  const daily = R.livingGroupsHtml([R.livingDailyGroup(DAILY, t, tf)]);
  const dv = visible(daily);
  assert.ok(dv.includes("Countries cut 3") && dv.includes("Reached by the daily files 2") && dv.includes("Change files applied 41"), dv);
  assert.ok(dv.includes("Newest change file 2026-11-04 23:59 UTC"), "the newest file's own date, said as UTC: " + dv);
  assert.ok(dv.includes("Re-baselines 2") && dv.includes("Cut again by hand 1"), "the two kinds of re-cut are counted apart: " + dv);
  assert.ok(dv.indexOf("2026-10-30 08:15 UTC") < dv.indexOf("2026-09-01 07:00 UTC"), "events are listed newest first, as the server sent them");
  assert.ok(daily.includes("CC(FRA)") && daily.includes("CC(DEU)"), "a country goes through the display helper, never printed raw");
  noJunk(daily, "the daily group"); noVerdict(daily, "the daily group");
  const none = visible(R.livingGroupsHtml([R.livingDailyGroup({ ...DAILY, rebaselines: [], rebaselines_total: 0, hand_recuts: 0 }, t, tf)]));
  assert.ok(none.includes("Re-baselines 0") && none.includes("Re-baseline events None"), "no event reads as None, and a zero is a measured zero: " + none);
  const older = visible(R.livingGroupsHtml([R.livingDailyGroup({ ...DAILY, rebaselines_not_shown: 4 }, t, tf)]));
  assert.ok(older.includes("4 older events are not shown."), older);
  const oldLane = R.livingGroupsHtml([R.livingDailyGroup({ ...DAILY, files_applied: null, last_applied_at: null, rebaselines_total: null, hand_recuts: null, rebaselines: [] }, t, tf)]);
  assert.ok(visible(oldLane).includes("Change files applied Not recorded") && visible(oldLane).includes("Re-baselines Not recorded"),
    "a table the lane lacks is Not recorded, never 0: " + visible(oldLane));
  assert.ok(hovers(oldLane).includes("older build"), "and says why on hover");
  assert.ok(visible(oldLane).includes("Re-baseline events Not recorded") && !visible(oldLane).includes("Re-baseline events None"),
    "an events list the lane could not read is NOT 'None': that would state that nothing happened: " + visible(oldLane));
  const noStamp = visible(R.livingGroupsHtml([R.livingDailyGroup({ ...DAILY, newest_file_at: null }, t, tf)]));
  assert.ok(noStamp.includes("Newest change file Not recorded"), "files applied but no recorded date is Not recorded, not 'never': " + noStamp);
  assert.ok(visible(R.livingGroupsHtml([R.livingDailyGroup({ ...DAILY, newest_file_at: null, countries_updated: 0, files_applied: 0 }, t, tf)])).includes("Newest change file never"),
    "and no file at all is 'never'");
  assert.ok(visible(R.livingGroupsHtml([R.livingDailyGroup({ measured: false, reason: "lane-never-run" }, t, tf)])).includes("Not run yet"));
  assert.ok(visible(R.livingGroupsHtml([R.livingDailyGroup(undefined, t, tf)])).includes("Could not be read"), "an overview without the block is named, not blank");
  noJunk(oldLane, "the old-lane daily group");
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
  assert.ok(/<details[ >]/.test(fr) && fr.includes("var(--err)"), "the stored diff is missing");
  // The fold carries its change id, so a language switch can re-open it (re-walk O-3).
  assert.ok(fr.includes('<details data-change-id="1">'), "the law fold lost its change id");
  assert.ok(fr.includes('href="/api/law/documents/7/view"'), "the local stored copy is not linked first (invariant #6)");
  assert.ok(!/href="https?:/.test(rows), "a law row linked straight outside the app");
  assert.ok(visible(de).includes("No stored diff") && !de.includes("<details"));
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
  assert.ok(visible(de).includes(visible(`${R.humanBytes(GIB)} / ${R.humanBytes(4 * GIB)}`)), de);
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

// --- 10. the page walk (Q701 = c): "N of M", never a percentage; absence is a word ---- //
{
  const titles = R.livingWikiGroups(WIKI, t, tf).map((g) => g.title);
  assert.deepStrictEqual(titles, ["Live stream", "Other changed pages", "Page walk", "Edition coverage", "Pages you track", "Storage"],
    "Q707's order: the followed pages, the other changed pages, then the walk, then the per-edition coverage (v0.6 row D), then the tail");
  // Off is the operator's switch: the state says so and names where it is set.
  const off = R.livingWalkGroup({ walk: { enabled: false, state: "off", measured: false,
    reason_counts: "walk-never-run" } }, t, tf);
  assert.strictEqual(off.title, "Page walk");
  assert.strictEqual(off.facts.length, 1, "a walk that never ran drew figures");
  assert.strictEqual(off.facts[0].label, "State",
    "the group's title was repeated as its first label (the defect the Chromium walk found)");
  assert.strictEqual(off.facts[0].value, "Off");
  assert.ok(off.facts[0].hover.includes("Settings → Wikipedia"), "an off walk does not say where it is switched on");
  // No walker in this process, or an older server with no walk block: a word, never a zero.
  for (const src of [{ walk: { enabled: true, state: "not_running", measured: false, reason_counts: "lane-never-run" } }, {}]) {
    const html = R.livingGroupsHtml([R.livingWalkGroup(src, t, tf)]);
    assert.ok(visible(html).includes("Not running now") && !/\d/.test(visible(html)), html);
    noJunk(html, "an unmeasured walk");
  }
  // Paused, with its named reason in the reader's own label frame.
  const paused = R.livingWalkGroup({ walk: { enabled: true, state: "paused", reason: "network_off",
    measured: false } }, t, tf);
  assert.strictEqual(paused.facts[0].value, "Paused: Airplane mode is on.");
  const tor = R.livingWalkGroup({ walk: { enabled: true, state: "paused", reason: "transport_unavailable",
    measured: false } }, t, tf);
  assert.ok(tor.facts[0].value.includes("never goes direct"),
    "a walk held by protected mode must say it waits rather than going direct");
  // A state this build does not know is shown as sent, never mapped onto a known word.
  assert.strictEqual(R.livingWalkGroup({ walk: { enabled: true, state: "dozing" } }, t, tf).facts[0].value, "dozing");
  const WALK = {
    enabled: true, state: "walking", reason: null, measured: true,
    pages_seen: 1234567, requests: 24700, response_bytes: 3 * GIB,
    editions: [
      { edition: "fr", pages_seen: 1234000, edition_articles: 2600000, completed_at: null,
        consecutive_failures: 0, last_error: null },
      { edition: "de", pages_seen: 567, edition_articles: 500, completed_at: "2026-09-28T10:00:00+00:00",
        consecutive_failures: 0, last_error: null },
      { edition: "ar", pages_seen: 0, edition_articles: null, completed_at: null,
        consecutive_failures: 3, last_error: "service_busy" },
    ],
    throughput: { window_days: 7, by_transport: {
      pool: { hours: 4, requests: 240, pages: 12000, response_bytes: 1, busy_ms: 1 },
      direct: { hours: 0, requests: 0, pages: 0, response_bytes: 0, busy_ms: 0 },
    } },
  };
  const g = R.livingWalkGroup({ walk: WALK }, t, tf);
  const html = R.livingGroupsHtml([g]);
  const fact = (label) => {
    const f = g.facts.find((x) => x.label === label);
    assert.ok(f, `no "${label}" fact in ${g.facts.map((x) => x.label)}`);
    return f;
  };
  assert.strictEqual(fact("State").value, "Walking");
  assert.strictEqual(fact("Pages seen").value, "1234567");
  assert.ok(!visible(html).includes("%") && !hovers(html).includes("%") && !/<progress|<meter/i.test(html),
    "the walk drew a percentage or a bar: the edition counts a different set, so the ratio can pass 100%");
  assert.strictEqual(fact("L3(fr)").value, "1234000 of 2600000");
  assert.ok(fact("L3(fr)").hover.startsWith("NAME(fr): "),
    "Q302/Q306: the code shows and the name in the UI language is the hover");
  assert.strictEqual(fact("L3(de)").value, "567 of 500 · pass complete",
    "a count past the edition's own figure must be shown as measured, never capped");
  const ar = fact("L3(ar)");
  assert.strictEqual(ar.value, "0 of an unknown total · waiting",
    "an edition whose own count is unknown must say so, never divide by nothing");
  assert.ok(ar.hover.includes("The wiki asked clients to slow down.") && ar.hover.includes("doubles each time"),
    "a waiting edition does not say why, or when it is asked again");
  const rate = fact("Measured rate, your proxy pool");
  assert.strictEqual(rate.value, "3000 pages an hour");
  assert.ok(!g.facts.some((f) => f.label.includes("direct connection")),
    "a transport with no measured hour drew a rate: no hours is no rate, not a rate of zero");
  noJunk(html, "the measured walk");
  noVerdict(html, "the measured walk");
  // Every word but the language code goes through the translator.
  const seen = new Set();
  const tt = (x) => { seen.add(x); return "«" + x + "»"; };
  const ttf = (x, v) => { seen.add(x); return tf(x, v); };
  R.livingWalkGroup({ walk: WALK }, tt, ttf);
  for (const label of ["Page walk", "State", "Walking", "Pages seen", "Requests answered", "Answers weighed",
    "{n} of {m}", "{n} of an unknown total", "pass complete", "waiting", "Measured rate, {transport}",
    "your proxy pool", "{n} pages an hour", "The wiki asked clients to slow down."]) {
    assert.ok(seen.has(label), `"${label}" never reached the translator`);
  }
}

// --- 11. the task manager says why the walk waits; a download's line never ----------- //
// (The frame is written by OOI18N.tf in the page -- this sandbox has none, so the English
// comes back; that the frame IS a key in all twelve locales is test_wiki_walk.py's.)
{
  const why = R._jobWhy({ kind: "wiki-walk", state: "paused", detail: "Airplane mode is on.",
    detail_i18n: "Airplane mode is on.", detail_vars: {} }, t);
  assert.strictEqual(visible(why), "Airplane mode is on.", "the walk's cause was not drawn");
  assert.strictEqual(R._jobWhy({ kind: "wiki-walk", state: "running" }, t), "",
    "a walking walk drew a cause line it does not have");
  assert.ok(!visible(R._jobWhy({ kind: "wiki-walk", state: "paused", paused_by: "airplane" }, t)).includes("Paused by"),
    "the walk took a download's cause line: it is not a download");
}

// --- 11b. the article list's index build draws its detail in the in-app window too ----- //
// (the caveat while it runs, and the keyed reason a refusal for space carries: its error is English only)
{
  const why = R._jobWhy({ kind: "article-indexes", state: "failed", error: "Declined: the database volume has 5 bytes free",
    detail: "The article list's indexes were not built: 5 MB free.", detail_i18n: "The article list's indexes were not built: 5 MB free.",
    detail_vars: {} }, t);
  assert.ok(visible(why).includes("were not built"), "the refusal's reason was not drawn for the index build");
  assert.ok(!visible(why).includes("Declined"), "the English error string was drawn instead of the keyed detail");
  assert.strictEqual(R._jobWhy({ kind: "article-indexes", state: "running" }, t), "", "a row with no detail drew a line");
}

// --- 11c. the repair of a damaged library file draws its detail the same way (R121/R129) ----- //
{
  const detail = "Repairing the damaged library file: table 2 of 9 (articles), 120 rows copied so far, 3 entries could not be read.";
  const why = R._jobWhy({ kind: "repair-database", state: "running", detail, detail_i18n: detail, detail_vars: {} }, t);
  assert.ok(visible(why).includes("table 2 of 9"), "the repair's progress line was not drawn");
  const refused = R._jobWhy({ kind: "repair-database", state: "failed", error: "Declined: no-room",
    detail: "The app did not repair your damaged library file: the drive has 1 MB free.", detail_i18n: "The app did not repair your damaged library file: the drive has 1 MB free.",
    detail_vars: {} }, t);
  assert.ok(visible(refused).includes("did not repair"), "the refusal's keyed reason was not drawn for the repair");
  assert.ok(!visible(refused).includes("Declined"), "the English error string was drawn instead of the keyed detail");
  assert.strictEqual(R._jobWhy({ kind: "repair-database", state: "running" }, t), "", "a row with no detail drew a line");
}

// --- 12. the other changed pages (Q707's WARM tier): counts, and absence as a word --- //
{
  // No fetcher in this process, or an older server with no warm block: a word, never a zero.
  for (const src of [{ warm: { state: "not_running", measured: false, reason_counts: "lane-never-run" } }, {}]) {
    const g = R.livingWarmGroup(src, t, tf);
    assert.strictEqual(g.title, "Other changed pages");
    assert.strictEqual(g.facts.length, 1, "a WARM tier with nothing measured drew figures");
    assert.strictEqual(g.facts[0].label, "State",
      "the group's title was repeated as its first label (the defect the Chromium walk found)");
    const html = R.livingGroupsHtml([g]);
    assert.ok(visible(html).includes("Not running now") && !/\d/.test(visible(html)), html);
    noJunk(html, "an unmeasured WARM tier");
  }
  // Rows not written yet: the state says so, and neither a count nor the share is drawn.
  const fresh = R.livingWarmGroup({ warm: { state: "not_started", measured: false,
    reason_counts: "warm-never-run", share: 0.9 } }, t, tf);
  assert.strictEqual(fresh.facts[0].value, "Not started yet");
  assert.strictEqual(fresh.facts.length, 1, "a WARM tier with no rows drew a count or its share");
  // Paused, with its named reason in the reader's own label frame.
  const share = R.livingWarmGroup({ warm: { state: "paused", reason: "warm_share_spent", measured: false } }, t, tf);
  assert.strictEqual(share.facts[0].value,
    "Paused: Changed pages have used their share of the storage budget; the rest is kept for the pages you follow.",
    "a WARM tier stopped at its share must say the rest is kept for the followed pages");
  const tor = R.livingWarmGroup({ warm: { state: "paused", reason: "transport_unavailable", measured: false } }, t, tf);
  assert.ok(tor.facts[0].value.includes("never goes direct"),
    "a WARM tier held by protected mode must say it waits rather than going direct");
  // A state or a reason this build does not know is shown as sent, never mapped.
  assert.strictEqual(R.livingWarmGroup({ warm: { state: "dozing" } }, t, tf).facts[0].value, "dozing");
  assert.strictEqual(R.livingWarmGroup({ warm: { state: "paused", reason: "a_new_token" } }, t, tf).facts[0].value,
    "Paused", "an unknown reason was drawn as if this build knew it");
  const WARM = {
    state: "fetching", reason: null, measured: true, share: 0.9, waiting: { ar: "service_busy" },
    pages_with_text: 1500, due: 320, texts_fetched: 2100, promoted: 4, requests: 60, response_bytes: 2 * GIB,
    editions: [
      { edition: "fr", pages_with_text: 1500, due: 20, texts_fetched: 2100, requests: 58, response_bytes: 1, promoted: 4 },
      { edition: "ar", pages_with_text: 0, due: 300, texts_fetched: 0, requests: 2, response_bytes: 1, promoted: 0 },
    ],
  };
  const g = R.livingWarmGroup({ warm: WARM }, t, tf);
  const html = R.livingGroupsHtml([g]);
  const fact = (label) => {
    const f = g.facts.find((x) => x.label === label);
    assert.ok(f, `no "${label}" fact in ${g.facts.map((x) => x.label)}`);
    return f;
  };
  assert.strictEqual(fact("State").value, "Fetching");
  assert.strictEqual(fact("Pages with text").value, "1500");
  assert.strictEqual(fact("Waiting for text").value, "320");
  assert.strictEqual(fact("Texts fetched").value, "2100");
  assert.strictEqual(fact("Now followed").value, "4");
  assert.ok(fact("Now followed").hover.includes("the texts fetched before stay"),
    "a page that became followed must say its earlier texts were kept");
  assert.strictEqual(fact("Requests answered").value, "60");
  assert.strictEqual(fact("Stops at").value, "90% of the budget");
  assert.ok(fact("Stops at").hover.includes("The share is a ruled default."),
    "the share was ruled (R55 keeps 90%), and must not still read as a proposal");
  assert.ok(!fact("Stops at").hover.includes("proposed"), "a ruled share still called a proposal");
  assert.strictEqual(fact("L3(fr)").value, "1500 with text · 20 to fetch");
  assert.ok(fact("L3(fr)").hover.startsWith("NAME(fr): "),
    "Q302/Q306: the code shows and the name in the UI language is the hover");
  const ar = fact("L3(ar)");
  assert.strictEqual(ar.value, "0 with text · 300 to fetch · waiting");
  assert.ok(ar.hover.includes("The wiki asked clients to slow down.") && ar.hover.includes("doubles each time"),
    "a waiting edition does not say why, or when it is asked again");
  assert.ok(!R.livingWarmGroup({ warm: { ...WARM, share: undefined } }, t, tf).facts.some((f) => f.label === "Stops at"),
    "an older server with no share drew one");
  // Off is the operator's switch: the state says so and names where it is set.
  const off = R.livingWarmGroup({ warm: { enabled: false, state: "off", measured: false,
    reason_counts: "warm-never-run" } }, t, tf);
  assert.strictEqual(off.facts.length, 1, "an off WARM tier that never fetched drew figures");
  assert.strictEqual(off.facts[0].value, "Off");
  assert.ok(off.facts[0].hover.includes("Settings → Wikipedia"), "an off WARM tier does not say where it is switched on");
  // Switched off after it fetched: the texts it kept are still there, so they are still counted.
  const offKept = R.livingWarmGroup({ warm: { ...WARM, enabled: false, state: "off" } }, t, tf);
  assert.strictEqual(offKept.facts[0].value, "Off");
  assert.strictEqual(offKept.facts.find((f) => f.label === "Pages with text").value, "1500",
    "switching WARM off hid the texts it kept");
  noJunk(html, "the measured WARM tier");
  noVerdict(html, "the measured WARM tier");
  // Every word but the language code goes through the translator.
  const seen = new Set();
  const tt = (x) => { seen.add(x); return "«" + x + "»"; };
  const ttf = (x, v) => { seen.add(x); return tf(x, v); };
  R.livingWarmGroup({ warm: WARM }, tt, ttf);
  for (const label of ["Other changed pages", "State", "Fetching", "Pages with text", "Waiting for text",
    "Texts fetched", "Now followed", "Requests answered", "Answers weighed", "Stops at", "{pct}% of the budget",
    "{n} with text · {m} to fetch", "waiting", "The wiki asked clients to slow down.",
    "It is asked again after a pause that doubles each time, up to an hour."]) {
    assert.ok(seen.has(label), `"${label}" never reached the translator`);
  }
}

// --- the language coverage floor (v0.6.0 row C, S1) -------------------------------- //
// Every floor country is in ONE of four states, never a blank; zh is its own line; the floor file's own unverified
// status is VISIBLE; and a count of countries is never turned into a share or a verdict.
{
  const CHECKED = {
    state: "checked", reason: null, as_of: "2026-09-07",
    verification_status: "drafted-from-training-knowledge; clearnet check pending", countries: 6,
    by_state: { tracked: ["fr"], "verified-not-yet-tracked": ["de"], unverified: ["tw"], "no-eligible-source": ["cn", "ye"] },
    languages: [
      { language: "ar", official: ["ye"], states: { tracked: 0, "verified-not-yet-tracked": 0, unverified: 0, "no-eligible-source": 1 }, documents: 0 },
      { language: "fr", official: ["fr"], regional: ["de"], states: { tracked: 1, "verified-not-yet-tracked": 1, unverified: 0, "no-eligible-source": 0 }, documents: 3 },
      { language: "zh", official: ["cn"], regional: ["tw"], contested: ["tw"],
        states: { tracked: 0, "verified-not-yet-tracked": 0, unverified: 1, "no-eligible-source": 1 }, documents: 0 },
    ],
    zh_beyond_floor: { hk: "no-eligible-source", mo: "unverified" },
    many_country_sources: { eu: { "eur-lex.europa.eu": false }, int: { "treaties.un.org": true, "coe.int": true } },
    unplaced_documents: { tl: 6 },
  };
  const html = R.livingLawFloorHtml({ floor: CHECKED }, t, tf);
  const text = visible(html);
  noJunk(html, "the language floor");
  noVerdict(html, "the language floor");
  // every state is a WORD, and "No eligible source" is a state the reader can see, not an empty cell
  for (const word of ["Tracked here", "Verified, not tracked yet", "Not verified", "No eligible source"]) {
    assert.ok(text.includes(word), `the floor never said "${word}"`);
  }
  assert.ok(!text.includes("Not looked up"), "a readable catalogue drew the unchecked state");
  // the tally is a count of countries per state, and the head says how many and as of when
  assert.ok(text.includes("6 countries on the floor · list dated 2026-09-07"), text);
  assert.ok(/Tracked here 1/.test(text.replace(/\s+/g, " ")) || /Tracked here\s*1/.test(text), "the tally lost its count");
  // never a share: no percent sign, no ratio word
  assert.ok(!/%|percent|\bout of\b/i.test(text), `the floor drew a share: ${text}`);
  // the floor file's OWN status is visible in the card-caveat line, not behind a toggle or a hover
  assert.ok(/<p class="card-caveat">[^<]*drafted from memory/.test(html), "the unverified floor is not a visible caveat");
  assert.ok(!/hidden/.test(html), "the floor hid something");
  // zh is its own row, FIRST, open, with the territories its seed names beside it and not on the floor
  const firstRow = html.indexOf("<details");
  assert.ok(html.slice(firstRow, firstRow + 400).includes("LC(zh)"), "zh is not the first row");
  assert.ok(/<details class="living-row" open>[^]*?LC\(zh\)/.test(html), "zh is not open");
  assert.ok(text.includes("Named by the Chinese seed list but not on the floor") && /territories\)\s*::\s*CC\(hk\)/.test(text),
    `the territories line did not go through the label frame: ${text}`);
  assert.ok(text.includes("CC(hk) No eligible source") && text.includes("CC(mo) Not verified"), text);
  // the basis is labelled and a contested row says so
  assert.ok(text.includes("official language") && text.includes("regional language"), text);
  assert.ok(text.includes("CC(tw) regional language · contested · Not verified"), text);
  // each language lists its countries, each with its state: fr -> fr tracked, de verified
  assert.ok(text.includes("CC(fr) official language · Tracked here") && text.includes("CC(de) regional language · Verified, not tracked yet"), text);
  // the disclosures: many-country sources credited to none, documents with no country credited to none
  assert.ok(text.includes("3 sources that serve many countries at once are credited to no single country."), text);
  assert.ok(text.includes("6 tracked documents state no country and are credited to none."), text);
  assert.ok(text.includes("ordering by population reached waits for a dated population table"), text);
  // every word of chrome goes through the translator
  const seen = new Set();
  const tt = (x) => { seen.add(x); return "«" + x + "»"; };
  const ttf = (x, v) => { seen.add(x); return tf(x, v); };
  R.livingLawFloorHtml({ floor: CHECKED }, tt, ttf);
  for (const label of ["Tracked here", "Verified, not tracked yet", "Not verified", "No eligible source", "official language",
    "regional language", "contested", "{n} countries on the floor · list dated {date}", "{n} tracked documents in this language",
    "Named by the Chinese seed list but not on the floor (the floor excludes territories)",
    "{n} sources that serve many countries at once are credited to no single country.",
    "{n} tracked documents state no country and are credited to none."]) {
    assert.ok(seen.has(label), `"${label}" never reached the translator`);
  }
  // an ISO-ish state this build does not know is shown as sent, never mapped onto the nearest known word
  assert.strictEqual(R.lawFloorStateWords("on-the-fence", t), "on-the-fence");
  // a status that is no longer "drafted" is printed, not replaced by the old caveat
  const settled = R.livingLawFloorHtml({ floor: { ...CHECKED, verification_status: "verified 2026-12-01" } }, t, tf);
  assert.ok(visible(settled).includes("Status of the list of countries: verified 2026-12-01"), visible(settled));
  assert.ok(!visible(settled).includes("drafted from memory"), "a settled list still carried the unsettled caveat");
}
{
  // R679: within a state the SERVER's order holds (population reached from the operator's dated table), never a re-sort by
  // code in the browser, and the note names the table's source and date instead of saying the order is waiting.
  const POP = {
    state: "checked", reason: null, as_of: "2026-09-07", verification_status: "verified 2026-12-01", countries: 3,
    by_state: { tracked: [], "verified-not-yet-tracked": ["in", "bd", "aa"], unverified: [], "no-eligible-source": [] },
    order: { by: "population", source: "UN WPP 2024", as_of: "2024-07-11", reason: null, missing: ["aa"] },
    languages: [{ language: "bn", official: ["aa", "bd", "in"], states: { tracked: 0, "verified-not-yet-tracked": 3, unverified: 0, "no-eligible-source": 0 }, documents: 0 }],
    zh_beyond_floor: {}, many_country_sources: {}, unplaced_documents: {},
  };
  const text = visible(R.livingLawFloorHtml({ floor: POP }, t, tf));
  assert.ok(text.indexOf("CC(in)") < text.indexOf("CC(bd)") && text.indexOf("CC(bd)") < text.indexOf("CC(aa)"),
    `the browser re-sorted the server's population order: ${text}`);
  assert.ok(text.includes("listed by population reached (UN WPP 2024, 2024-07-11); any the table lacks follow by code"), text);
  assert.ok(!text.includes("waits for a dated population table"), "a placed table still read as waiting");
}
{
  // The catalogue could not be read: tracked is still true, the rest is "Not looked up", never "No eligible source".
  const UNCHECKED = {
    state: "unchecked", reason: "LawCatalogUnreadable: boom", as_of: "2026-09-07", verification_status: "drafted-x", countries: 2,
    by_state: { tracked: ["fr"], "verified-not-yet-tracked": [], unverified: [], "no-eligible-source": [], unchecked: ["de"] },
    languages: [{ language: "fr", official: ["fr", "de"], states: { tracked: 1, "verified-not-yet-tracked": 0, unverified: 0, "no-eligible-source": 0, unchecked: 1 }, documents: 1 }],
    zh_beyond_floor: { hk: "unchecked", mo: "unchecked" }, many_country_sources: null, unplaced_documents: {},
  };
  const html = R.livingLawFloorHtml({ floor: UNCHECKED }, t, tf);
  const text = visible(html);
  noJunk(html, "the unchecked floor");
  assert.ok(text.includes("Not looked up") && text.includes("LawCatalogUnreadable: boom"), text);
  // a state with nobody in it is a measured zero and is drawn as one, in the tally and in the language row
  assert.ok(text.includes("Verified, not tracked yet 0 Not verified 0 No eligible source 0 Not looked up 1"), text);
  assert.ok(/<p class="card-caveat">[^<]*could not be read/.test(html), "the unreadable catalogue is not a visible caveat");
  assert.ok(text.includes("CC(de) official language · Not looked up"), text);
  // the reader is told nothing about "no source" for a lookup that never happened
  assert.ok(!text.includes("CC(de) official language · No eligible source"), text);
  // no floor at all, and a floor with nothing to list: a sentence, never a throw or a blank
  assert.ok(visible(R.livingLawFloorHtml({}, t, tf)).includes("This build reports no language floor."));
  assert.ok(visible(R.livingLawFloorHtml({ floor: { state: "unchecked", reason: "the floor file is absent", by_state: null, languages: null } }, t, tf))
    .includes("could not be read, so nothing is counted. the floor file is absent"));
}
{
  // A payload from a newer build: a state this client has no word for is COUNTED and LISTED as sent (the tally still adds up to
  // the countries), sorts after the known ones, and a null member list or a null source map does not throw.
  const NEWER = {
    state: "checked", reason: null, as_of: "2026-09-07", verification_status: "drafted-x", countries: 3,
    by_state: { tracked: ["fr"], "verified-not-yet-tracked": [], unverified: null, "no-eligible-source": [], "brand-new-state": ["de", "es"] },
    languages: [{ language: "fr", official: ["fr", "de", "es"], states: { tracked: 1, "brand-new-state": 2 }, documents: 1 }],
    zh_beyond_floor: null, many_country_sources: { eu: null, int: { "treaties.un.org": true } }, unplaced_documents: { tl: "x" },
  };
  const html = R.livingLawFloorHtml({ floor: NEWER }, t, tf);
  const text = visible(html).replace(/\s+/g, " ");
  noJunk(html, "the newer-build floor");
  assert.ok(text.includes("brand-new-state 2"), `an unknown state was dropped from the counts: ${text}`);
  assert.ok(text.includes("Tracked here 1") && text.includes("Verified, not tracked yet 0") && text.includes("Not verified 0"), text);
  assert.ok(text.includes("CC(de) official language · brand-new-state") && text.includes("CC(es) official language · brand-new-state"), text);
  assert.ok(text.indexOf("CC(fr) official language · Tracked here") < text.indexOf("CC(de) official language · brand-new-state"),
    "an unknown state sorted ahead of a known one");
  assert.ok(text.includes("1 sources that serve many countries at once are credited to no single country."), text);
  assert.ok(!text.includes("state no country"), "a non-numeric document count drew a disclosure");
}

// --- coverage per edition: counts as "n of m", a missing total is said, nothing is a score -------- //
{
  const COV = { measured: true, reason: null,
    totals: { pages_seen: 300, edition_articles: 1000, editions_without_total: 1, editions_with_a_run: 2, gaps: 3 },
    editions: [
      { edition: "en", has_run: true, pages_seen: 300, edition_articles: 1000,
        full_text: { hot_pages_with_text: 40, warm_pages_with_text: 25, share_lower_bound: 0.1333, share_upper_bound: 0.2167 },
        last_event_recorded_at: "2026-09-25T09:00:00+00:00", gaps: { total: 3, by_reason: { reconnect: 3 } } },
      { edition: "fr", has_run: true, pages_seen: 10, edition_articles: null, full_text: { hot_pages_with_text: 0, warm_pages_with_text: null },
        last_event_recorded_at: null, gaps: { total: 0, by_reason: {} } },
      { edition: "de", has_run: false, reason: "no-run-yet" },
    ],
    located: { measured: false, reason: "address-extractor-not-built" } };
  const g = group(R.livingWikiGroups({ ...WIKI, coverage: COV }, t, tf), "Edition coverage");
  noJunk(g, "the coverage group"); noVerdict(g, "the coverage group");
  const text = visible(g);
  assert.ok(text.includes("All editions 300 of 1,000 pages seen") || text.includes("All editions 300 of 1000 pages seen"), text);
  assert.ok(hovers(g).includes("1 editions have no article count yet; their pages are left out of both figures."), "a missing total was not said");
  assert.ok(text.includes("L3(fr) 10 pages seen, total unknown"), "a missing total drew a ratio: " + text);
  assert.ok(text.includes("L3(de) No run yet") && !/L3\(de\) \d/.test(text), "a never-run edition drew a figure: " + text);
  assert.ok(hovers(g).includes("between 40 and 65 pages"), "the full-text range is lower and upper bound, not one number");
  assert.ok(text.includes("Addresses located Not measured yet"), "the located share drew a number it does not have: " + text);
  assert.ok(!/%/.test(text), "a percentage was drawn: " + text);
  // Editions the walk never touched or whose total was never read: no zero, no closed range, no ratio over a total that is not there.
  const PART = { measured: true, reason: null,
    totals: { pages_seen: 10, edition_articles: 0, editions_without_total: 3, editions_with_a_run: 3, gaps: 1 },
    editions: [
      { edition: "it", has_run: true, pages_seen: 10, edition_articles: null, full_text: { hot_pages_with_text: 0, warm_pages_with_text: null },
        last_event_recorded_at: null, gaps: { total: 0, by_reason: {} } },
      { edition: "fr", has_run: true, pages_seen: null, edition_articles: null, full_text: { hot_pages_with_text: 1, warm_pages_with_text: null },
        last_event_recorded_at: null, last_event_unreadable: true, gaps: { total: 0, by_reason: {} } },
      { edition: "pt", has_run: true, pages_seen: null, edition_articles: null, full_text: { hot_pages_with_text: 0, warm_pages_with_text: null },
        last_event_recorded_at: null, gaps: { total: 1, by_reason: { reconnect: 1 } } },
    ], located: { measured: false, reason: "address-extractor-not-built" } };
  const part = group(R.livingWikiGroups({ ...WIKI, coverage: PART }, t, tf), "Edition coverage");
  noJunk(part, "the partial coverage group");
  const ptext = visible(part);
  assert.ok(ptext.includes("All editions 10 pages seen, total unknown") && !/of 0 pages/.test(ptext), "a ratio over a total that is not there: " + ptext);
  assert.ok(ptext.includes("L3(fr) The walk has not run for this edition.") && ptext.includes("L3(pt) The walk has not run for this edition."), ptext);
  assert.ok(!/\b0 pages seen/.test(ptext), "an edition the walk never touched drew 0 pages seen: " + ptext);
  const phov = hovers(part);
  assert.ok(!/between 0 and 0|between 1 and 1/.test(phov), "a closed range with the second tier never run: " + phov);
  assert.ok(phov.includes("at least 1 pages; the second tier has not run"), phov);
  // The walk ran for no edition at all: the aggregate says it is not measured, never "0 pages seen".
  const NOWALK = { ...PART, editions: PART.editions.map((e) => ({ ...e, pages_seen: null })) };
  const nowalk = group(R.livingWikiGroups({ ...WIKI, coverage: NOWALK }, t, tf), "Edition coverage");
  assert.ok(visible(nowalk).includes("All editions Not measured yet") && !/\b0 pages seen/.test(visible(nowalk)), visible(nowalk));
  assert.ok(phov.includes("Last event: Could not be read"), "an unreadable last event drew 'never'");
  // R17 step 4 (R678): the located counters, summed over editions, as "n of m"; the reasons are counts in the hover; the scan's progress is said.
  const LOC = { ...COV, located: { measured: true, complete: false, texts_read: { hot: 30, warm: 10 }, texts_held: { hot: 30, warm: 70 },
    per_edition: { en: { found: 7, located: 2, ambiguous: 1, no_house_number: 1, pending: 2, lookup_failed: 1, skipped_about_a_person: 3, skipped_a_home: 1 }, fr: { found: 1, outside_your_osm_countries: 1 } } } };
  const lg = group(R.livingWikiGroups({ ...WIKI, coverage: LOC }, t, tf), "Edition coverage");
  noJunk(lg, "the located counters"); noVerdict(lg, "the located counters");
  assert.ok(visible(lg).includes("Addresses located 2 of 8 addresses located"), visible(lg));
  const lh = hovers(lg);
  assert.ok(lh.includes("1 ambiguous, 0 not located, 1 outside your OpenStreetMap countries, 1 without a house number."), lh);
  assert.ok(lh.includes("4 pages about a person or a home were not read.") && lh.includes("Read 40 of 100 stored pages so far."), lh);
  assert.ok(lh.includes("2 addresses are still being looked up.") && lh.includes("1 addresses could not be looked up"), lh);
  assert.ok(lh.includes("Addresses outside your OpenStreetMap countries are not located."), "the Q820 scope sentence is missing: " + lh);
  const empty = group(R.livingWikiGroups({ ...WIKI, coverage: { ...COV, located: { measured: true, complete: true, per_edition: {} } } }, t, tf), "Edition coverage");
  assert.ok(visible(empty).includes("Addresses located No address found yet") && !/Read \d/.test(hovers(empty)), visible(empty));
  const never = group(R.livingWikiGroups({ ...WIKI, coverage: { measured: false, reason: "lane-never-run" } }, t, tf), "Edition coverage");
  assert.ok(visible(never).includes("Not run yet") && !/\d/.test(visible(never).replace("Edition coverage", "")), visible(never));
  const none = group(R.livingWikiGroups(WIKI, t, tf), "Edition coverage");
  assert.ok(visible(none).includes("Could not be read"), "a payload without a coverage block threw or drew figures");
}

console.log("living_sources_node_test: all checks passed");
