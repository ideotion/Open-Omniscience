// Settings -> Advanced -> Diagnostics: the job lines follow the JOB (2026-09-27 re-walk
// M-7), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// M-7, measured: after a Pause and a Resume from the task manager, the fold ran to done
// while the Diagnostics line kept reading "... · paused", because the one loop that wrote
// it ended the moment the job stopped running; and a Diagnostics section opened on a paused
// fold showed nothing. `_watchJobLine` is now the only writer of each line, so this drives
// it through a scripted sequence of status reads.
//
// It returns the watch: `done` ends with the watch, `settled` as soon as a read finds the
// job not running. The Fold / Clean up / Search re-index buttons wait on `settled`, so they
// come back at a pause (the button is how a paused run is continued from Diagnostics) while
// the watch keeps following the job.
//
// EXTRACTED from the shipped modules rather than re-typed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
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

// ---------------------------------------------------------------------------------- //
//  M-7: the watcher                                                                    //
// ---------------------------------------------------------------------------------- //
function makeWatcher() {
  const env = { statuses: [], calls: [], sectionOpen: true };
  const src =
    "const _jobWatch = {};\n" +
    "const document = { querySelector: () => ({ open: env.sectionOpen }) };\n" +
    // Every wait is a macrotask of 0 ms: the loop's own cadence is not what is under test.
    "const setTimeout = (fn) => global.setTimeout(fn, 0);\n" +
    "async function api(url) { env.calls.push(url);\n" +
    "  if (url.endsWith('/report')) return { report: true };\n" +
    "  const s = env.statuses.length > 1 ? env.statuses.shift() : env.statuses[0];\n" +
    "  if (s instanceof Error) throw s; return s; }\n" +
    extract("_diagSectionOpen") + "\n" + extract("_armJobSettle") + "\n" +
    extract("_settleJob") + "\n" + extract("_watchJobLine") + "\n" +
    "module.exports = { _watchJobLine };";
  const m = { exports: {} };
  new Function("module", "exports", "env", "global", src)(m, m.exports, env, global);
  env.watch = m.exports._watchJobLine;
  return env;
}
const render = (s, report) => s.state + (report ? "+report" : "");
const id = (s) => s;
const S = (state, extra) => Object.assign({ state: state, running: state === "running" }, extra || {});

(async () => {
  // --- a Resume from ELSEWHERE is followed to the end ------------------------------ //
  {
    const env = makeWatcher();
    env.statuses = [S("paused"), S("paused"), S("running"), S("running"), S("done")];
    const line = { textContent: "" };
    await env.watch("fold", "/status", "/report", render, line, id).done;
    assert.strictEqual(line.textContent, "done+report",
      "the line stopped at the pause and never saw the run finish (M-7): " + line.textContent);
  }

  // --- opening Diagnostics on a PAUSED job shows it (it was blank) ------------------ //
  {
    const env = makeWatcher();
    env.sectionOpen = false;   // closed again right after the first read
    env.statuses = [S("paused")];
    const line = { textContent: "" };
    await env.watch("fold", "/status", "/report", render, line, id, true).done;
    assert.strictEqual(line.textContent, "paused", "a paused job opened on reads as nothing");
    assert.strictEqual(env.calls.length, 1, "a closed section must not keep polling a paused job");
  }

  // --- opening it on a job that never ran says nothing ------------------------------ //
  {
    const env = makeWatcher();
    env.statuses = [S("idle")];
    const line = { textContent: "" };
    await env.watch("fold", "/status", "/report", render, line, id, true).done;
    assert.strictEqual(line.textContent, "", "an idle job must not paint a line on open");
    assert.strictEqual(env.calls.length, 1);
    // ...but a refusal is named, as the button would name it.
    env.statuses = [S("idle", { refusal: "lemmatisation-off" })];
    await env.watch("fold", "/status", "/report", render, line, id, true).done;
    assert.strictEqual(line.textContent, "idle");
  }

  // --- one watcher per line: a second start kicks it, never a second loop ---------- //
  {
    const env = makeWatcher();
    env.statuses = [S("running"), S("running"), S("running"), S("done")];
    const line = { textContent: "" };
    const a = env.watch("fts", "/status", null, render, line, id);
    const b = env.watch("fts", "/status", null, render, line, id);
    assert.strictEqual(a, b, "a second start must join the running watcher");
    await a.done;
    assert.strictEqual(line.textContent, "done");
    assert.strictEqual(env.calls.length, 4, "two loops read the status twice as often: " + env.calls.length);
    // ...and the key is released, so the NEXT run gets a watcher of its own.
    env.calls.length = 0;
    env.statuses = [S("done")];
    await env.watch("fts", "/status", null, render, line, id).done;
    assert.strictEqual(env.calls.length, 1);
  }

  // --- a status that cannot be read ends the watch without touching the line -------- //
  {
    const env = makeWatcher();
    env.statuses = [new Error("503")];
    const line = { textContent: "kept" };
    const w = env.watch("reindex", "/status", null, render, line, id);
    await w.done;
    await w.settled;   // never left hanging: a button waiting on it would stay disabled
    assert.strictEqual(line.textContent, "kept");
  }

  // --- the BUTTON comes back at a pause; the watch goes on to the end ----------------- //
  {
    const env = makeWatcher();
    env.statuses = [S("running"), S("paused"), S("paused"), S("running"), S("done")];
    const line = { textContent: "" };
    const w = env.watch("fold", "/status", "/report", render, line, id);
    let ended = false;
    w.done.then(() => { ended = true; });
    await w.settled;
    assert.strictEqual(line.textContent, "paused");
    assert.strictEqual(ended, false,
      "the button waited for the whole run: a paused job could not be continued from Diagnostics");
    await w.done;
    assert.strictEqual(line.textContent, "done+report");
  }

  // --- a read already in flight when the button starts cannot release the button ---- //
  {
    const env = makeWatcher();
    // The open-section read was taken BEFORE the button's start reached the server.
    env.statuses = [S("paused"), S("running"), S("done")];
    const line = { textContent: "" };
    const opened = env.watch("fold", "/status", "/report", render, line, id, true);
    const pressed = env.watch("fold", "/status", "/report", render, line, id);
    assert.strictEqual(opened, pressed);
    await pressed.settled;
    assert.strictEqual(line.textContent, "done+report",
      "a stale 'paused' read released the button while the job ran: " + line.textContent);
    await pressed.done;
  }

  console.log("all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
