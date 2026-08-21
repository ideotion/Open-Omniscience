/**
 * The "Add series to the corpus" control, driven with the REAL function extracted
 * from app.js.
 *
 * WHY A NODE TEST AND NOT A BROWSER DRIVE. The happy path was browser-verified (it
 * reports "0 new / 0 updated / 1298 already current"), but the case that matters most
 * is the one a browser cannot easily produce: a run the operator CANCELS. That path
 * must not report the tally it happened to reach as a finished walk -- a partial index
 * reading as complete is a fabricated pass, and it is invisible precisely because the
 * numbers shown are real.
 */
const fs = require("fs");
const path = require("path");

// The UI engine is ordered modules since the S-3 decomposition; ask the shared
// helper, which reads the module list out of index.html and cannot drift.
const APP = require("./app_source.js").appJs();

/** Extract a top-level function, brace-matching from its BODY brace.
 *  Starting at the first `{` after the name would stop at a default-parameter `{}`
 *  and yield the signature alone, and every assertion over that empty slice would
 *  pass for free (the recorded ooChart trap). */
function fnSource(src, name) {
  const re = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const m = re.exec(src);
  if (!m) throw new Error(`function ${name} not found`);
  let i = m.index + m[0].length - 1, depth = 0;
  for (; i < src.length; i++) {           // walk to the end of the parameter list
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const bodyStart = src.indexOf("{", i);
  let d = 0, j = bodyStart;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return src.slice(m.index, j);
}

let passed = 0, failed = 0;
function ok(cond, label) {
  if (cond) { passed++; } else { failed++; console.error("FAIL:", label); }
}

/** Run runSeriesCorpus against a scripted /status sequence; return the final message. */
async function drive(statuses) {
  const el = { textContent: "", disabled: false };
  const calls = [];
  const ctx = {
    $: (id) => (id === "statcorpus-msg" || id === "statcorpus-run") ? el : null,
    api: async (url, opts) => {
      calls.push(url);
      if (opts && opts.method === "POST") return { started: true };
      return statuses.length > 1 ? statuses.shift() : statuses[0];
    },
    _failMsg: (tpl, e) => tpl.replace("{error}", (e && e.message) || String(e)),
    setTimeout: (fn) => fn(),            // collapse the poll delay
    window: {},
  };
  // The i18n helpers are extracted from app.js too, not doubled: an identity double
  // would hide exactly the defect this harness found in the first cut (a template
  // fallback that never substituted, so the reader saw a literal "{created}").
  const src = ["_govT", "_govTf", "runSeriesCorpus"].map(n => fnSource(APP, n)).join("\n");
  const fn = new Function(...Object.keys(ctx), `${src}; return runSeriesCorpus;`)(
    ...Object.values(ctx),
  );
  await fn();
  return { msg: el.textContent, disabled: el.disabled, calls };
}

(async () => {
  // 1. A COMPLETE run says so, and reports its real tally.
  let r = await drive([{ state: "done", result: { created: 5, updated: 2, unchanged: 1291, complete: true } }]);
  ok(/5/.test(r.msg) && /2/.test(r.msg) && /1291/.test(r.msg), "a complete run reports its tally");
  ok(/every stored series/.test(r.msg), "a complete run says the walk finished");
  ok(!/stopped/.test(r.msg), "a complete run does not claim it stopped early");

  // 2. THE ONE THAT MATTERS: a CANCELLED run must not read as finished. The tally is
  //    real either way, so only the sentence can carry the difference.
  r = await drive([{ state: "done", result: { created: 5, updated: 0, unchanged: 100, complete: false } }]);
  ok(/stopped before the end/.test(r.msg), "a cancelled run says it stopped before the end");
  ok(!/every stored series/.test(r.msg), "a cancelled run must NOT claim the corpus is complete");
  ok(/again/.test(r.msg), "...and says how to continue it");

  // 3. An error is surfaced, not swallowed into a plausible-looking tally.
  r = await drive([{ state: "error", error: "disk full" }]);
  ok(/disk full/.test(r.msg), "an error surfaces the backend's own words");
  ok(!/already current/.test(r.msg), "an error never renders as a tally");

  // 4. A missing result is not rendered as zeros-and-done... it renders zeros, which is
  //    honest ONLY because `complete` is then undefined -> not `false` -> the finished
  //    sentence. Pin the shape so a future change has to think about it.
  r = await drive([{ state: "done" }]);
  ok(/0/.test(r.msg), "a resultless done run renders zeros rather than nothing");

  // 5. The button is re-enabled on every path, so the control can never wedge.
  ok(r.disabled === false, "the button is re-enabled after a run");
  r = await drive([{ state: "error", error: "x" }]);
  ok(r.disabled === false, "the button is re-enabled after an error");

  // 6. It is LOCAL: no consent-gated online call is made. The endpoint reads figures
  //    already stored, so prompting for the network consent would teach the operator
  //    that the popup means nothing.
  r = await drive([{ state: "done", result: { complete: true } }]);
  ok(r.calls.every(u => u.startsWith("/api/governments/series-corpus")),
     "only the series-corpus endpoints are called");

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
