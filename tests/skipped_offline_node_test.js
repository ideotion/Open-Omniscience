// The four buttons that used to read a kill-switch refusal as a quiet success, run as REAL code (invariant #14e's corollary).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Pressed in airplane mode, "Ingest this feed", "Ingest the selected feeds", "Track changes now" (law) and "Track now" (Wikipedia)
// came back with an all-zero tally and the same success toast as a quiet feed. The server now says `skipped_offline`; what is
// guarded here is what each handler DOES with it, and the refusals are the point: no success toast for a run that fetched
// nothing, no refresh of a list nothing changed, and the pre-existing figures untouched when nothing was refused.
//
// EXTRACTED from the shipped modules (a re-typed copy would pass while the real handler was broken).

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // `async function name(`, balanced parens first (a `{}` in a default parameter would truncate the slice), then the body.
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const at = APP.slice(at0 - 6, at0) === "async " ? at0 - 6 : at0;
  let i = APP.indexOf("(", at0), depth = 0;
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

const S1 = "Airplane mode is on: nothing was fetched. Click the plane in the top bar to go online, then try again.";
const S3 = "Not fetched (airplane mode)";

// One sandbox per case, so a handler cannot leak state into the next.
function sandbox(responses) {
  const log = { toasts: [], texts: {}, html: {}, calls: [], searches: 0, laws: 0, wikis: 0 };
  const els = {};
  const el = (id) => (els[id] = els[id] || {
    set textContent(v) { log.texts[id] = v; }, get textContent() { return log.texts[id] || ""; },
    set innerHTML(v) { log.html[id] = v; }, get innerHTML() { return log.html[id] || ""; },
    disabled: false, value: "7",
  });
  const api = async (path, opts) => {
    log.calls.push(path);
    const hit = Object.keys(responses).find((p) => path.startsWith(p));
    assert.ok(hit, "no canned response for " + path);
    return responses[hit];
  };
  const src = [
    "var window = {};",                                      // OOI18N absent: also the boot-time state
    "var BI = { selected: new Set([1, 2]) };",
    "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}",
    "function _govT(s){return s;}",
    "function _govTf(str, vars){return String(str).replace(/\\{(\\w+)\\}/g,(m,k)=>(vars&&vars[k]!=null)?String(vars[k]):m);}",
    "function _failMsg(t, e){return t;}", "function _ores(){return 'false';}",
    extract("tally"), extract("ingestSource"), extract("ingestBatch"), extract("lawTrack"), extract("trackWikiNow"),
    "return { ingestSource, ingestBatch, lawTrack, trackWikiNow, tally };",
  ].join("\n");
  const f = new Function("$", "api", "toast", "doSearch", "loadLaw", "loadLawChanges", "loadWiki", "loadSources", src);
  const api2 = f(el, api, (m, k) => log.toasts.push([m, k || "ok"]),
    () => { log.searches++; }, () => { log.laws++; }, () => {}, () => { log.wikis++; }, () => {});
  return { h: api2, log, el };
}
const zero = { stored: 0, duplicate: 0, fetch_failed: 0, entries: 0 };

(async () => {
  // ---- ingestSource ------------------------------------------------------------------------------------------------
  {
    const { h, log, el } = sandbox({ "/api/sources/7/ingest": { source_id: 7, tally: { ...zero, skipped_offline: 1 } } });
    await h.ingestSource();
    assert.strictEqual(log.texts["ingest-result"], S1, "a refused feed says so in the result line");
    assert.deepStrictEqual(log.toasts, [[S1, "warn"]], "and only a warning, never 'Ingest complete.'");
    assert.strictEqual(log.searches, 0, "nothing changed, so the corpus is not refreshed");
  }
  {
    const { h, log } = sandbox({ "/api/sources/7/ingest": { source_id: 7, tally: { ...zero, stored: 3 } } });
    await h.ingestSource();
    assert.ok(/stored: 3/.test(log.texts["ingest-result"]) && !/skipped_offline|Airplane/.test(log.texts["ingest-result"]));
    assert.deepStrictEqual(log.toasts, [["Ingest complete.", "ok"]]);
    assert.strictEqual(log.searches, 1);
  }
  // ---- tally: the key never prints as a count ----------------------------------------------------------------------
  {
    const { h } = sandbox({});
    assert.strictEqual(h.tally({ skipped_offline: 2 }), "nothing new", "skipped_offline alone is not an outcome");
    assert.strictEqual(h.tally({ stored: 1, skipped_offline: 2 }), "stored: 1");
  }
  // ---- ingestBatch -------------------------------------------------------------------------------------------------
  {
    const refused = { source_id: 1, source: "A", status: "ok", tally: { ...zero, skipped_offline: 1 } };
    const { h, log } = sandbox({ "/api/sources/ingest-batch": {
      requested: 2, ingested: 2, aggregate: { ...zero, skipped_offline: 2 },
      results: [refused, { ...refused, source_id: 2, source: "B" }] } });
    await h.ingestBatch({ disabled: false });
    assert.strictEqual(log.texts["bi-status"], S1);
    assert.ok(log.html["bi-results"].includes(S3) && !/skipped_offline/.test(log.html["bi-results"]), "every row says it was not fetched");
    assert.deepStrictEqual(log.toasts, [[S1, "warn"]]);
    assert.strictEqual(log.searches, 0);
  }
  {
    const { h, log } = sandbox({ "/api/sources/ingest-batch": {
      requested: 2, ingested: 2, aggregate: { ...zero, stored: 4, skipped_offline: 1 },
      results: [{ source_id: 1, source: "A", status: "ok", tally: { ...zero, skipped_offline: 1 } },
                { source_id: 2, source: "B", status: "ok", tally: { ...zero, stored: 4 } }] } });
    await h.ingestBatch({ disabled: false });
    assert.ok(log.texts["bi-status"].startsWith("Done: 1/2 fetched"), "a refused feed is not 'fetched': " + log.texts["bi-status"]);
    assert.ok(log.texts["bi-status"].includes("1 not fetched (airplane mode)") && log.texts["bi-status"].includes("stored: 4"));
    assert.ok(log.html["bi-results"].includes(S3) && log.html["bi-results"].includes("stored: 4"));
    assert.deepStrictEqual(log.toasts, [["Batch ingest complete.", "ok"]]);
    assert.strictEqual(log.searches, 1);
  }
  {
    const { h, log } = sandbox({ "/api/sources/ingest-batch": {
      requested: 1, ingested: 1, aggregate: { ...zero, stored: 2 },
      results: [{ source_id: 1, source: "A", status: "ok", tally: { ...zero, stored: 2 } }] } });
    await h.ingestBatch({ disabled: false });
    assert.ok(log.texts["bi-status"].startsWith("Done: 1/1 fetched") && !/airplane/i.test(log.texts["bi-status"]), "unchanged when nothing was refused");
    assert.deepStrictEqual(log.toasts, [["Batch ingest complete.", "ok"]]);
  }
  // ---- lawTrack ----------------------------------------------------------------------------------------------------
  const law = (r) => ({ "/api/law/track": r });
  const base = { documents: 3, baselines: 0, changed: 0, flagged: 0, unchanged: 0 };
  {
    const { h, log } = sandbox(law({ ...base, errors: 3, skipped_offline: 3 }));
    await h.lawTrack(null);
    assert.deepStrictEqual(log.toasts, [[S1, "warn"]], "'3 errors' would blame the documents for the person's own setting");
    assert.strictEqual(log.laws, 1, "the list is still reloaded, as it was after any run");
  }
  {
    const { h, log } = sandbox(law({ ...base, baselines: 2, errors: 1, skipped_offline: 1 }));
    await h.lawTrack(null);
    assert.strictEqual(log.toasts.length, 1);
    assert.ok(log.toasts[0][0].startsWith("Tracked 3 law(s): 2 baselines") && log.toasts[0][0].endsWith("1 not fetched (airplane mode)"), log.toasts[0][0]);
  }
  {
    const { h, log } = sandbox(law({ ...base, baselines: 1, errors: 2 }));
    await h.lawTrack(null);
    assert.deepStrictEqual(log.toasts, [["Tracked 3 law(s): 1 baselines, 0 changed, 0 flagged, 2 errors.", "ok"]], "real errors read exactly as before");
  }
  // ---- trackWikiNow ------------------------------------------------------------------------------------------------
  const wiki = (r) => ({ "/api/wiki/track-now": r });
  {
    const { h, log } = sandbox(wiki({ pages: 0, new_revisions: 0, flagged: 0, skipped_offline: 2 }));
    await h.trackWikiNow();
    assert.strictEqual(log.texts["wiki-progress"], S1, "not '0 page(s): 0 new edit(s)'");
    assert.deepStrictEqual(log.toasts, [[S1, "warn"]]);
  }
  {
    const { h, log } = sandbox(wiki({ pages: 1, new_revisions: 3, flagged: 1, skipped_offline: 1 }));
    await h.trackWikiNow();
    assert.strictEqual(log.texts["wiki-progress"], "1 page(s): 3 new edit(s), 1 flagged. 1 not fetched (airplane mode)");
    assert.deepStrictEqual(log.toasts, [["Tracking complete.", "ok"]]);
  }
  {
    const { h, log } = sandbox(wiki({ pages: 0, new_revisions: 0, flagged: 0 }));
    await h.trackWikiNow();
    assert.strictEqual(log.texts["wiki-progress"], "0 page(s): 0 new edit(s), 0 flagged.", "no watched pages is still just that");
    assert.deepStrictEqual(log.toasts, [["Tracking complete.", "ok"]]);
  }
  console.log("skipped_offline_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
