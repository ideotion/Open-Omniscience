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
  "livingStorageGroup", "_livingCount", "livingRunFacts", "livingWalkGroup", "livingWarmGroup", "livingWikiGroups", "livingLawGroups",
  "livingMapGroups", "livingGroupsFor",
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
  extractConst("_LIVING_WALK_STATE") + "\n" +
  extractConst("_LIVING_WALK_WHY") + "\n" +
  extractConst("_LIVING_WARM_STATE") + "\n" +
  extractConst("_LIVING_WARM_WHY") + "\n" +
  extractConst("_LIVING_TRANSPORT") + "\n" +
  "var window = {};\n" +
  // The Q302 display helpers are STUBBED to mark what passed through them: their own
  // behaviour (the alpha-3 / 639-2/T code, the localised hover) is pinned by
  // country_display_node_test.js against the real tables; what matters here is that
  // this view hands them the value instead of printing it raw.
  "function ooCountryCell(v, o) { return '<span class=\"' + ((o && o.cls) || '') + '\">CC(' + esc(v) + ')</span>'; }\n" +
  "function ooLangCell(v, o) { return '<span class=\"' + ((o && o.cls) || '') + '\">LC(' + esc(v) + ')</span>'; }\n" +
  "function ooLangCode(v) { return 'L3(' + v + ')'; }\n" +
  "function ooLangName(v, fb) { return 'NAME(' + v + ')'; }\n" +
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
  assert.deepStrictEqual(titles, ["Live stream", "Other changed pages", "Page walk", "Pages you track", "Storage"],
    "Q707's order: the followed pages, the other changed pages, then the walk's tail");
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

console.log("living_sources_node_test: all checks passed");
