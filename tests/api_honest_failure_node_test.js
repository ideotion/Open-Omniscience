/**
 * Behavioural node test for the api()/toggleNetwork() P0 pair (visual audit
 * 2026-09-08, §4.2 and §0c). The functions are EXTRACTED FROM THE REAL
 * src/static/app-core.js by name -- a re-typed copy would pass while the
 * shipped code was still broken (the sibling-test convention; see
 * tests/axis_honesty_node_test.js).
 *
 * Run by tests/test_api_honest_failure.py (and standalone:
 * `node tests/api_honest_failure_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const HOME = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-home.js"), "utf-8");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) {
  return Promise.resolve().then(fn).then(() => {
    passed += 1;
    console.log("ok  - " + name);
  });
}

// Same balanced-brace extraction every node suite in this repo uses (see
// axis_honesty_node_test.js) -- duplicated here rather than shared, per the
// established convention.
function extract(name, decl, src) {
  const SRC = src || APP;
  const head = decl || ("function " + name + "(");
  const at = SRC.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = SRC.indexOf("(", at); j < SRC.length; j++) {
    if (SRC[j] === "(") p++;
    else if (SRC[j] === ")") { p--; if (p === 0) { i = SRC.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}") { depth--; if (depth === 0) return SRC.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

function fakeRes({status, headers = {}, body = ""}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: {
      get(name) {
        const key = Object.keys(headers).find((k) => k.toLowerCase() === String(name).toLowerCase());
        return key == null ? null : headers[key];
      },
    },
    statusText: "Status " + status,
    text: async () => body,
  };
}

// ========================================================================= //
//  GROUP 1 -- api(): audit §4.2 (parse-failure honesty) + §the-429-budget    //
//  (Retry-After gating, item (c)). The REAL api() and _apiErrorMessage are   //
//  extracted; only the small side-effect helpers it calls (telemetry/UI     //
//  counters, none of which affect its control flow) are stubbed.            //
// ========================================================================= //
function makeApiSandbox(fetchImpl) {
  const apiSrc = extract("api", "async function api(");
  const errSrc = extract("_apiErrorMessage");
  const src = `
    let setTimeout = (fn) => { fn(); return 0; };   // no real delays in tests
    let fetch = (...args) => this._fetchImpl(...args);
    let _bumpInflight = () => {};
    let _noteReachable = () => {};
    let _noteServerBusy = () => {};
    let _noteBusyRetry = () => {};
    const _API_MAX_RETRIES = 4;
    const _API_MAX_RETRIES_POLLED = 1;
    const _API_RETRY_MAX_MS = 8000;
    ${errSrc}
    ${apiSrc}
    this.api = api;
  `;
  const sandbox = { _fetchImpl: fetchImpl };
  // eslint-disable-next-line no-new-func
  new Function(src).call(sandbox);
  return sandbox;
}

async function run() {
  await test("§4.2: a 200 declaring JSON with an unparseable body THROWS, marked .parseFailure", async () => {
    const sandbox = makeApiSandbox(async () =>
      fakeRes({status: 200, headers: {"Content-Type": "application/json"}, body: "{not valid json!!! <<<"}));
    let threw = null;
    try { await sandbox.api("/api/briefing"); } catch (e) { threw = e; }
    assert(threw, "api() must throw on an unparseable JSON-declared body, it resolved instead");
    assert(threw.parseFailure === true, "the thrown error must carry .parseFailure = true, got " + JSON.stringify(threw));
  });

  await test("§4.2 regression guard: a legitimate non-JSON body is NOT thrown, still returned raw", async () => {
    const sandbox = makeApiSandbox(async () =>
      fakeRes({status: 200, headers: {"Content-Type": "text/plain"}, body: "hello world"}));
    const data = await sandbox.api("/api/briefing/draft/export.md");
    assert(data === "hello world", "a non-JSON-declared body must still come back as raw text, got " + JSON.stringify(data));
  });

  await test("a normal JSON body still parses and returns as before", async () => {
    const sandbox = makeApiSandbox(async () =>
      fakeRes({status: 200, headers: {"Content-Type": "application/json"}, body: JSON.stringify({cards: [1, 2, 3], total: 3})}));
    const data = await sandbox.api("/api/briefing");
    assert(Array.isArray(data.cards) && data.cards.length === 3 && data.total === 3,
      "a valid JSON body must parse through unchanged, got " + JSON.stringify(data));
  });

  await test("(c) 429 WITH Retry-After is retried and can still succeed", async () => {
    let calls = 0;
    const sandbox = makeApiSandbox(async () => {
      calls += 1;
      if (calls === 1) return fakeRes({status: 429, headers: {"Retry-After": "0"}, body: ""});
      return fakeRes({status: 200, headers: {"Content-Type": "application/json"}, body: "{}"});
    });
    const data = await sandbox.api("/api/briefing");
    assert(calls === 2, "a Retry-After-bearing 429 must be retried once, saw " + calls + " fetch call(s)");
    assert(data && typeof data === "object", "the retried call must eventually succeed");
  });

  await test("(c) 429 WITHOUT Retry-After is NOT retried -- the quota-budget fix", async () => {
    // /api/articles is a 100/hour QUOTA 429. Blindly retrying it (the old
    // behaviour: up to _API_MAX_RETRIES=4 extra attempts) spends the very
    // budget that is already exhausted. Without a Retry-After to honour, the
    // fixed code must ask exactly ONCE and surface the refusal.
    let calls = 0;
    const sandbox = makeApiSandbox(async () => {
      calls += 1;
      return fakeRes({status: 429, headers: {}, body: ""});   // no Retry-After, ever
    });
    let threw = null;
    try { await sandbox.api("/api/articles"); } catch (e) { threw = e; }
    assert(calls === 1,
      "a 429 with NO Retry-After must be issued exactly once, not retried blindly -- saw " + calls +
      " fetch call(s) (old behaviour would retry up to 5 total for a quota it cannot out-wait)");
    assert(threw, "a 429 with no Retry-After must still surface as a thrown refusal to the caller");
  });

  // ----------------------------------------------------------------------- //
  //  (c2) The retry split, added 2026-09-09 after the (c) fix above outgrew   //
  //  its own premise. It keyed "quota vs burst" on Retry-After's PRESENCE,    //
  //  which held only while the quota limiter sent none. The audit's finding   //
  //  (c) fix then made src/api/main.py's rate-limit handler answer with a     //
  //  real Retry-After -- correctly, a client cannot back off without one --   //
  //  and that alone would have turned every exhausted-quota refusal back into //
  //  four more requests against the exhausted quota. Measured in Chromium     //
  //  before the fix: a 429 carrying `Retry-After: 120` left the Search tab    //
  //  showing its previous results, unchanged, for the whole retry budget.     //
  //  The distinction is now HOW LONG, not WHETHER.                            //
  // ----------------------------------------------------------------------- //

  await test("(c2) a LONG Retry-After (a quota) is reported, never waited out", async () => {
    let calls = 0;
    const sandbox = makeApiSandbox(async () => {
      calls += 1;
      // 120 s -- fifteen times _API_RETRY_MAX_MS. Sleeping through it is not a
      // retry, it is a hang; and re-issuing spends a budget already spent.
      return fakeRes({status: 429, headers: {"Retry-After": "120"}, body: ""});
    });
    let threw = null;
    try { await sandbox.api("/api/articles"); } catch (e) { threw = e; }
    assert(calls === 1,
      "a quota-length Retry-After must be issued exactly ONCE -- saw " + calls + " fetch call(s)");
    assert(threw, "it must surface as a thrown refusal, not a silent wait");
    assert(threw.retryAfter === 120,
      "the server's own stated wait must ride on the error so a surface can say WHEN, got " +
      JSON.stringify(threw.retryAfter));
  });

  await test("(c2) a SHORT Retry-After (a burst) is still waited out and retried", async () => {
    // heavy.py and insights.py both answer their busy-retry 429 with
    // `Retry-After: 2`. That case must keep working exactly as before -- the
    // split must not turn a load-shed refusal into a user-visible failure.
    let calls = 0;
    const sandbox = makeApiSandbox(async () => {
      calls += 1;
      if (calls === 1) return fakeRes({status: 429, headers: {"Retry-After": "0"}, body: ""});
      return fakeRes({status: 200, headers: {"Content-Type": "application/json"}, body: "{}"});
    });
    const data = await sandbox.api("/api/insights/corpus-keywords");
    assert(calls === 2, "a short Retry-After must still be retried, saw " + calls + " fetch call(s)");
    assert(data && typeof data === "object", "and the retry must be able to succeed");
  });

  await test("(c2) the boundary is the retry budget itself, not a magic number", async () => {
    // _API_RETRY_MAX_MS is 8000. A wait AT the budget is retried; one PAST it is
    // reported. Pinning both sides means a future change to the budget moves the
    // boundary coherently instead of leaving a hardcoded threshold behind.
    for (const [seconds, expectRetry] of [[8, true], [9, false]]) {
      let calls = 0;
      const sandbox = makeApiSandbox(async () => {
        calls += 1;
        if (calls === 1) return fakeRes({status: 429, headers: {"Retry-After": String(seconds)}, body: ""});
        return fakeRes({status: 200, headers: {"Content-Type": "application/json"}, body: "{}"});
      });
      let threw = null;
      try { await sandbox.api("/api/articles"); } catch (e) { threw = e; }
      if (expectRetry) {
        assert(calls === 2 && !threw,
          "Retry-After=" + seconds + "s is within the 8000 ms budget and must be retried, saw " +
          calls + " call(s), threw=" + !!threw);
      } else {
        assert(calls === 1 && threw && threw.retryAfter === seconds,
          "Retry-After=" + seconds + "s exceeds the 8000 ms budget and must be reported, saw " +
          calls + " call(s), retryAfter=" + (threw && threw.retryAfter));
      }
    }
  });

  await test("(c2) with no Retry-After the error carries NO wait -- never a guess", async () => {
    // The absence of a number must reach the surface as an absence, so it says
    // "later" rather than inventing a clock time (CLAUDE.md: degrade loudly,
    // never fabricate).
    const sandbox = makeApiSandbox(async () => fakeRes({status: 429, headers: {}, body: ""}));
    let threw = null;
    try { await sandbox.api("/api/articles"); } catch (e) { threw = e; }
    assert(threw && threw.retryAfter === undefined,
      "an unstated wait must stay unstated on the error, got " + JSON.stringify(threw && threw.retryAfter));
  });
}

// ========================================================================= //
//  GROUP 2 -- toggleNetwork(): audit §0c (the ~5s dead-toggle race). The     //
//  REAL toggleNetwork(), _paintNetwork() and _paintNetToggleBootDefault()   //
//  are extracted; api()/ensureOnline() are controllable spies (they are     //
//  each covered on their own terms elsewhere -- ensureOnline by             //
//  tests/test_network_consent.py, api() by Group 1 above) so this group     //
//  isolates exactly the decision toggleNetwork() makes.                     //
// ========================================================================= //
function makeClassList(el) {
  el._classes = new Set();
  return {
    add: (...c) => c.forEach((x) => el._classes.add(x)),
    remove: (...c) => c.forEach((x) => el._classes.delete(x)),
    toggle: (c, force) => {
      if (force === undefined) { if (el._classes.has(c)) el._classes.delete(c); else el._classes.add(c); }
      else if (force) el._classes.add(c); else el._classes.delete(c);
      return el._classes.has(c);
    },
    contains: (c) => el._classes.has(c),
  };
}
function makeEl() {
  const el = { _attrs: {}, textContent: "", title: "" };
  el.classList = makeClassList(el);
  el.setAttribute = (k, v) => { el._attrs[k] = v; };
  el.getAttribute = (k) => (k in el._attrs ? el._attrs[k] : null);
  return el;
}

function makeNetSandbox({apiImpl, ensureOnlineImpl} = {}) {
  const paintSrc = extract("_paintNetwork");
  const bootSrc = extract("_paintNetToggleBootDefault");
  const resolveSrc = extract("_resolveNetState", "async function _resolveNetState(");
  const toggleSrc = extract("toggleNetwork", "async function toggleNetwork(");
  const src = `
    const document = this.document, window = {};
    function $(id) { return document.getElementById(id); }
    let _netOnline = true;
    let _netStateKnown = false;
    let _egressState = null;
    let _coachChecked = false;
    function _paintActivity() {}
    function dismissNetCoach() {}
    function maybeShowNetCoach() {}
    function _flashNet() {}
    function _airplanePopup() {}
    function toast() {}
    let api = (...args) => this._apiImpl(...args);
    let ensureOnline = (...args) => this._ensureOnlineImpl(...args);
    ${paintSrc}
    ${bootSrc}
    ${resolveSrc}
    ${toggleSrc}
    this.toggleNetwork = toggleNetwork;
    this._paintNetwork = _paintNetwork;
    this._paintNetToggleBootDefault = _paintNetToggleBootDefault;
    this.getNetStateKnown = () => _netStateKnown;
    this.setNetStateKnown = (v) => { _netStateKnown = v; };
    this.getNetOnline = () => _netOnline;
  `;
  const netToggleEl = makeEl();
  const netPlaneEl = makeEl();
  const bodyEl = { classList: makeClassList({}) };
  const elements = {"net-toggle": netToggleEl, "net-plane": netPlaneEl};
  const fakeDocument = {
    getElementById: (id) => (id in elements ? elements[id] : null),
    body: bodyEl,
  };
  const sandbox = {
    document: fakeDocument,
    _apiImpl: apiImpl || (async () => ({})),
    _ensureOnlineImpl: ensureOnlineImpl || (async () => true),
  };
  // eslint-disable-next-line no-new-func
  new Function(src).call(sandbox);
  sandbox.netToggleEl = netToggleEl;
  sandbox.netPlaneEl = netPlaneEl;
  return sandbox;
}

async function runToggleTests() {
  await test("§0c: a click BEFORE any confirmed state still opens the consent path when actually offline", async () => {
    // Reproduces the audit's exact reported shape: the button carries NO
    // confirming class yet (the pre-fix DOM state -- nothing has painted
    // "off"), _netStateKnown is false, and the TRUE backend state is
    // offline. Old code read `goingOnline = btn.classList.contains("off")`
    // === false here and silently took the "already offline, no-op" branch
    // -- ensureOnline() was never called and #net-consent never opened.
    const apiCalls = [];
    let ensureOnlineCalls = 0;
    const sandbox = makeNetSandbox({
      apiImpl: async (path, opts) => { apiCalls.push([path, opts]); return {online: false}; },
      ensureOnlineImpl: async () => { ensureOnlineCalls += 1; return true; },
    });
    // No boot-default paint here on purpose: prove the fix lives in
    // toggleNetwork()'s own logic, not merely in the cosmetic early paint.
    assert(!sandbox.netToggleEl.classList.contains("off"), "test setup: button must start with no state class");
    await sandbox.toggleNetwork();
    assert(ensureOnlineCalls === 1,
      "toggleNetwork() must call ensureOnline() exactly once when the real state is offline, saw " + ensureOnlineCalls +
      " -- a click swallowed here means #net-consent never opens (audit §0c)");
    assert(apiCalls.some(([p, o]) => p === "/api/system/network" && !(o && o.method)),
      "toggleNetwork() must resolve the real state via GET /api/system/network when it isn't yet confirmed");
    assert(!apiCalls.some(([p, o]) => p === "/api/system/network" && o && o.method === "POST" && JSON.parse(o.body).online === false),
      "toggleNetwork() must NOT also fire the go-OFFLINE POST when the real answer was 'go online'");
    assert(sandbox.getNetStateKnown() === true, "resolving the real state must mark it confirmed for next time");
  });

  await test("fast path unaffected once the state is already confirmed (offline, known)", async () => {
    const apiCalls = [];
    let ensureOnlineCalls = 0;
    const sandbox = makeNetSandbox({
      apiImpl: async (path, opts) => { apiCalls.push([path, opts]); return {online: false}; },
      ensureOnlineImpl: async () => { ensureOnlineCalls += 1; return true; },
    });
    sandbox.setNetStateKnown(true);
    sandbox.netToggleEl.classList.add("off");   // confirmed offline
    await sandbox.toggleNetwork();
    assert(ensureOnlineCalls === 1, "a confirmed offline state must still go through ensureOnline() on click");
    assert(!apiCalls.some(([p]) => p === "/api/system/network"),
      "once the state is already confirmed, toggleNetwork() must not spend an extra GET resolving it again");
  });

  await test("fast path unaffected once the state is confirmed (online, known) -- goes offline, no consent needed", async () => {
    const apiCalls = [];
    let ensureOnlineCalls = 0;
    const sandbox = makeNetSandbox({
      apiImpl: async (path, opts) => { apiCalls.push([path, opts]); return {online: false}; },
      ensureOnlineImpl: async () => { ensureOnlineCalls += 1; return true; },
    });
    sandbox.setNetStateKnown(true);
    // no "off" class => confirmed ONLINE
    await sandbox.toggleNetwork();
    assert(ensureOnlineCalls === 0, "going offline must never route through the online-consent function");
    assert(apiCalls.some(([p, o]) => p === "/api/system/network" && o && o.method === "POST" &&
      JSON.parse(o.body).online === false), "going offline must still POST online:false");
  });

  await test("the boot-time default paints the toggle offline instantly, with zero network calls", async () => {
    const apiCalls = [];
    const sandbox = makeNetSandbox({apiImpl: async (path, opts) => { apiCalls.push([path, opts]); return {online: false}; }});
    sandbox._paintNetToggleBootDefault();
    assert(sandbox.netToggleEl.classList.contains("off"), "the boot default must paint the toggle as offline immediately");
    assert(sandbox.netPlaneEl.getAttribute("fill") === "currentColor", "the plane glyph must be filled (offline) immediately");
    assert(apiCalls.length === 0, "the boot-time default paint must make zero network calls");
    assert(sandbox.getNetStateKnown() === false, "the boot default is a best-known guess, not a confirmed answer");
  });
}

// ========================================================================= //
//  GROUP 3 -- END-TO-END: the exact hand-verified audit §4.2 reproduction,   //
//  spanning BOTH owned files. The REAL api() (app-core.js) is wired to a    //
//  malformed-JSON fetch mock, and the REAL loadHome()/loadBriefing()        //
//  (app-home.js) are extracted and run against it -- proving the two files  //
//  actually cooperate to produce an honest failure, not just that each      //
//  file's piece looks right in isolation.                                   //
// ========================================================================= //
function makeHomeSandbox(fetchImpl) {
  const apiSrc = extract("api", "async function api(");
  const loadHomeSrc = extract("loadHome", "async function loadHome(", HOME);
  // Extracted, not stubbed. The stats read-failure copy moved out of loadHome() into
  // its own function (2026-09-09) so a language switch and the boot-locale race can
  // re-derive it -- see tests/test_i18n_boot_readiness.py. Stubbing it here would
  // make this end-to-end test assert against a stub's output instead of the shipped
  // copy, which is the whole thing the sibling-test convention exists to prevent.
  const renderStatsFailureSrc = extract("renderHomeStatsFailure", "function renderHomeStatsFailure(", HOME);
  const loadBriefingSrc = extract("loadBriefing", "async function loadBriefing(", HOME);
  const src = `
    const document = this.document, window = {};
    function $(id) { return document.getElementById(id); }
    const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));
    let setTimeout = (fn) => { fn(); return 0; };
    let fetch = (...args) => this._fetchImpl(...args);
    let _bumpInflight = () => {};
    let _noteReachable = () => {};
    let _noteServerBusy = () => {};
    let _noteBusyRetry = () => {};
    const _API_MAX_RETRIES = 4;
    const _API_MAX_RETRIES_POLLED = 1;
    const _API_RETRY_MAX_MS = 8000;
    ${extract("_apiErrorMessage")}
    ${apiSrc}
    // loadHome() unconditionally kicks off every OTHER Home panel too (not
    // under test here) -- stub them so extracting loadHome doesn't require
    // extracting the whole surface transitively.
    function renderHomeStats() {}
    function renderHomeStatus() {}
    function loadHomeAlerts() {}
    function loadHomeTrends() { return Promise.resolve(); }
    function loadHomeRecent() { return Promise.resolve(); }
    function loadHomeLatest() { return Promise.resolve(); }
    function loadHomeChannels() { return Promise.resolve(); }
    function _syncHomeSubtabs() {}
    function refreshDraftCount() {}
    function renderBriefing() { throw new Error("renderBriefing must not run on a read failure"); }
    // The module-level flags renderHomeStatsFailure()/loadHome() share. Declared here
    // because the extraction is per-function; their real declarations sit beside the
    // functions in app-home.js.
    let _homeStatsFailed = false;
    let _homeStatsAwaitingI18n = false;
    ${renderStatsFailureSrc}
    ${loadBriefingSrc}
    ${loadHomeSrc}
    this.loadHome = loadHome;
    this.loadBriefing = loadBriefing;
  `;
  const statsEl = makeEl();
  const feedEl = makeEl();
  const elements = {"home-stats": statsEl, "briefing-feed": feedEl};
  const fakeDocument = { getElementById: (id) => (id in elements ? elements[id] : null) };
  const sandbox = { document: fakeDocument, _fetchImpl: fetchImpl };
  // eslint-disable-next-line no-new-func
  new Function(src).call(sandbox);
  sandbox.statsEl = statsEl;
  sandbox.feedEl = feedEl;
  return sandbox;
}

async function runEndToEndTests() {
  await test("§4.2 END-TO-END: a malformed /api/database/stats + /api/briefing render an honest failure, never the empty-corpus copy", async () => {
    const sandbox = makeHomeSandbox(async (path) => {
      // Exactly the hand-verified audit reproduction: a 200 whose body is not
      // valid JSON, for BOTH endpoints.
      if (String(path).indexOf("/api/database/stats") !== -1 || String(path).indexOf("/api/briefing") !== -1) {
        return fakeRes({status: 200, headers: {"Content-Type": "application/json"}, body: "{not valid json!!! <<<"});
      }
      return fakeRes({status: 200, headers: {"Content-Type": "application/json"}, body: "{}"});
    });
    await sandbox.loadHome();
    await sandbox.loadBriefing();
    const statsHtml = sandbox.statsEl.innerHTML || "";
    const feedHtml = sandbox.feedEl.innerHTML || "";
    // The honest failure copy is ALLOWED to mention "empty corpus" as a named
    // CONTRAST ("that is not the same as..."); what must never appear is the
    // actual empty-corpus sentence itself (the false claim the audit found).
    assert(statsHtml.toLowerCase().indexOf("library is empty") === -1,
      "the stat strip must never show the empty-corpus copy on a read failure, got: " + statsHtml);
    assert(feedHtml.toLowerCase().indexOf("no leads yet") === -1,
      "the briefing must never show the empty-corpus 'No Leads yet' copy on a read failure, got: " + feedHtml);
    assert(/could not be read/i.test(statsHtml), "the stat strip must name that the data could not be read, got: " + statsHtml);
    assert(/could not be read/i.test(feedHtml), "the briefing must name that the data could not be read, got: " + feedHtml);
  });
}

run()
  .then(runToggleTests)
  .then(runEndToEndTests)
  .then(() => { console.log(passed + " api-honest-failure checks passed"); })
  .catch((e) => {
    console.error("FAIL (unexpected): " + (e && e.stack || e));
    process.exit(1);
  });
