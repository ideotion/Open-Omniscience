/* app-ai-tools.js — qualification, AI backends, custody

   Source candidates and the qualification gates, the AI settings surface (pill,
   backends, vLLM lifecycle, model store), per-article summarize/translate/framing,
   and the chain-of-custody panel.

   PART OF THE UI ENGINE. src/static/app.js was decomposed into ordered modules
   (structural debt S-3; docs/design/APPJS_DECOMPOSITION_2026-08-20.md). They share
   ONE global scope -- there is no module system here, and 413 globals are named by
   inline on*= handlers that can resolve against nothing else -- and they load in the
   order index.html lists them, with app-boot.js last.

   The split was a pure CONTIGUOUS slice, verified at the split commit by
   concatenating the modules in load order and reproducing the pre-split file byte
   for byte. That check is spent now (these files are edited normally), but the rule
   it rested on still holds: DO NOT reorder a declaration across a module boundary.
   Function declarations would survive it, because they hoist; a const or let would
   not, and the failure is a TDZ error at load rather than anything a reader would
   spot in review. Add new code inside the module it belongs to.
*/
    async function loadCandidates() {
      try {
        const r = await api("/api/sources/candidates?status=candidate&limit=50");
        const panel = $("candidates-panel"), list = $("candidates-list");
        if (!panel || !list) return;
        if (!r.count) { panel.style.display = "none"; return; }
        panel.style.display = "";
        list.innerHTML = "<table><tr><th>Domain</th><th>Channel</th><th>Evidence</th><th>First seen</th><th></th></tr>" +
          r.candidates.map(c => {
            const ev = c.channel === "citation"
              ? `cited by ${esc(c.evidence.distinct_citing_articles)} of your articles`
              : `catalog entry for ${esc((c.evidence.country || "").toUpperCase())} (you have ${esc(c.evidence.your_sources_there)} there)`;
            return `<tr><td>${esc(c.domain)}</td><td>${esc(c.channel)}</td><td>${ev}</td>` +
              `<td>${esc((c.first_seen || "").slice(0, 10))}</td>` +
              `<td><button class="secondary tiny" onclick="candidateAct(${c.id}, 'promote')">Promote (disabled)</button> ` +
              `<button class="ghost tiny" onclick="candidateAct(${c.id}, 'dismiss')">Dismiss</button></td></tr>`;
          }).join("") + "</table>";
      } catch (e) { /* candidates are optional surface; stay quiet */ }
    }
    async function candidateAct(id, action) {
      try {
        const r = await api(`/api/sources/candidates/${id}/${action}`, {method: "POST"});
        toast(action === "promote"
          ? `Promoted ${r.promoted} (created disabled — enable it below when ready).`
          : `Dismissed ${r.dismissed}.`);
        loadCandidates(); loadManagedSources();
      } catch (e) { toast(`${action} failed: ` + e.message, "err"); }
    }

    // Bulk source QUALIFICATION (2026-07-23 field-feedback S1.2): the manual catch-up
    // for the steady-state ride-along (5 candidates/pass — far too slow to drain a
    // Wikidata-discovery-scale backlog). Networked (each judgment trial-fetches a few
    // articles) -> the one consent popup; cancel lives in the task manager (kind
    // "qualify-sources-bulk"), same grammar as discoverWorld.
    // ---- The quality-gates panel (maintainer amendment 2026-08-03) ------------------
    // Renders ENTIRELY from GET /api/sources/qualification/config. The panel deliberately
    // holds no copy of the criteria or the bounds: a threshold described in two places
    // drifts, and then the UI explains a gate the engine no longer applies.
    //
    // Units and the hover explanation are NOT built here either. Invariant #17 already
    // marks any element carrying a translated `title` and opens the ONE shared #oo-tip
    // bubble on hover, keyboard focus or touch long-press. So each row just carries a
    // title; the shipped convention does the rest.
    let _qualCfg = null;

    function _qualShare(row) {
      // A share must never be printed as a bare 0.5 (the units principle). The unit string
      // already says "share ... (0-1)", so this adds the reading in percent beside it.
      const v = Number(row.value);
      return (row.unit || "").includes("(0–1)") && v >= 0 && v <= 1
        ? `${v} (${Math.round(v * 100)}% )`.replace(" )", ")")
        : String(row.value);
    }

    function _qualTunableHtml(row) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      // The hover carries the long form (impact + why the bound is where it is); the
      // visible surface keeps the value, the unit and the range present.
      const why = [row.impact, row.floor_reason].filter(Boolean).join(" — ");
      return `<div class="row" style="gap:8px;align-items:baseline;flex-wrap:wrap;margin:4px 0">
        <span title="${esc(why)}"><b>${esc(row.label)}</b></span>
        <span>${esc(_qualShare(row))}</span>
        <span class="muted">${esc(row.unit || "")}</span>
        <span class="hint" title="${esc(t("The safe range. Outside it the value is corrected AND reported — never silently."))}">${t("safe range")} ${row.lo}–${row.hi}</span>
      </div>`;
    }

    async function loadQualificationGates() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = $("qual-gates"), state = $("qual-state"), crit = $("qual-criteria");
      if (!host) return;
      try {
        const cfg = await api("/api/sources/qualification/config");
        _qualCfg = cfg;
        const c = cfg.counts || {};
        // "How many could the current floor actually disqualify" is worth more than any
        // control on the page: on the field corpus that number is zero.
        state.innerHTML = `${t("Judged so far")}: <b>${c.qualified || 0}</b> ${t("qualified")}
          · <b>${c.disqualified || 0}</b> ${t("disqualified")}
          · <b>${c.unqualified || 0}</b> ${t("not yet judged")}`;

        const en = $("qual-enabled");
        const perPass = (cfg.gates || []).flatMap(g => g.tunables || [])
          .find(r => r.key === "qualification_per_pass");
        if (en) en.checked = !!(perPass && Number(perPass.value) > 0);
        const hint = $("qual-enabled-hint");
        if (hint) {
          hint.textContent = (perPass && Number(perPass.value) > 0)
            ? `${perPass.value} ${t("sources per collection pass")}`
            : t("off — candidates stay unjudged; nothing is deleted and no verdict changes");
        }

        crit.innerHTML = `<h3 style="margin:0 0 6px">${t("What the source gate looks at")}</h3>` +
          (cfg.criteria || []).map(x => `<div style="margin:6px 0">
            <span title="${esc(x.desc)}"><b>${esc(x.name)}</b></span>
            ${x.can_disqualify
              ? `<span class="warn" title="${esc(t("The ONLY criterion that can disqualify a source. The others are style-ambiguous, so they can never exceed a watch flag — that cap is deliberate and is not adjustable."))}">${t("can disqualify")}</span>`
              : `<span class="muted">${t("watch only")}</span>`}
          </div>`).join("");

        host.innerHTML = (cfg.gates || []).map(g => `<div class="panel" style="margin:10px 0">
          <h3 style="margin:0">${esc(g.question)}</h3>
          <p class="hint" style="margin:4px 0">${esc(g.note)} <span class="muted">${t("Verdict")}: ${esc(g.verdict)}</span></p>
          ${(g.tunables || []).map(_qualTunableHtml).join("")}
        </div>`).join("");

        const scope = cfg.scope || {};
        const u = $("qual-scope-unqualified"), sh = $("qual-scope-shipped");
        if (u) u.checked = !!scope.scrape_unqualified;
        if (sh) sh.checked = !!scope.scrape_app_provided_only;
        _qualScopeCount();
      } catch (e) {
        state.textContent = _apiErrorMessage(e);
      }
    }

    // The live count for the current 2x2, so the toggles are concrete without a paragraph
    // of explanation. Loopback only.
    async function _qualScopeCount() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const out = $("qual-scope-count");
      if (!out) return;
      try {
        // `matched` is this endpoint's own name for "sources the current selection picks";
        // it runs select_sources, so it already reflects both scope toggles.
        const r = await api("/api/scheduler/targets");
        const n = r && r.matched;
        out.textContent = (n === undefined || n === null)
          ? "" : `${t("This will scrape")} ${n} ${t("sources")} (${t("of")} ${r.total_enabled} ${t("enabled")}).`;
      } catch (e) { out.textContent = ""; }
    }

    async function qualSaveToggle(el) {
      // Off is 0; on restores the last non-zero value, defaulting to the shipped 5.
      const per = el.checked ? (_qualLastPerPass || 5) : 0;
      if (el.checked === false) {
        const rows = (_qualCfg && _qualCfg.gates || []).flatMap(g => g.tunables || []);
        const cur = rows.find(r => r.key === "qualification_per_pass");
        if (cur && Number(cur.value) > 0) _qualLastPerPass = Number(cur.value);
      }
      await _qualPut({qualification_per_pass: per});
    }
    let _qualLastPerPass = 5;

    async function qualSaveScope() {
      await _qualPut({
        scrape_unqualified: !!($("qual-scope-unqualified") || {}).checked,
        scrape_app_provided_only: !!($("qual-scope-shipped") || {}).checked,
      });
    }

    async function _qualPut(body) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      // Loopback settings write with no egress side effect (save_settings only), so it is
      // never ensureOnline-gated -- same reasoning as the collection-speed knob.
      try {
        await api("/api/scheduler/config", {method: "PUT", body: JSON.stringify(body)});
        toast(t("Saved."), "ok");
        loadQualificationGates();
      } catch (e) { toast(_apiErrorMessage(e), "err"); }
    }

    async function loadQualifyBulk() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const out = $("qualify-bulk-status");
      if (!out) return;
      try {
        const st = await api("/api/sources/qualify-bulk/status");
        const bl = st.backlog || {};
        const backlog = (bl.unqualified || 0) + (bl.due_disqualified || 0);
        const cancelBtn = $("qualify-bulk-cancel-btn");
        if (st.running) {
          out.textContent = (st.detail || t("Working…"))
            + (st.progress ? ` (${st.done}/${st.total})` : "");
          if (cancelBtn) cancelBtn.style.display = "";
        } else {
          out.textContent = backlog
            ? `${fmtNum(backlog)} ${esc(t("candidates awaiting qualification"))}`
            : t("No candidates awaiting qualification.");
          if (cancelBtn) cancelBtn.style.display = "none";
        }
      } catch (e) { out.textContent = t("Could not load qualification status."); }
    }
    async function qualifyBulkStart(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const out = $("qualify-bulk-status");
      const say = (msg) => { if (out) out.textContent = msg; };
      if (typeof ensureOnline === "function"
          && !await ensureOnline(t("Qualify the source backlog — a background job that trial-fetches a few articles from each candidate to judge extraction validity")))
        return;
      if (btn) btn.disabled = true;
      say(t("Starting…"));
      try {
        const d = await api("/api/sources/qualify-bulk", {method: "POST"});
        if (d && d.started === false && d.job && d.job.state === "running") {
          say(t("Already running — see the task manager."));
        }
        const cancelBtn = $("qualify-bulk-cancel-btn");
        if (cancelBtn) cancelBtn.style.display = "";
        const st = await pollJobStatus("/api/sources/qualify-bulk/status", {
          intervalMs: 4000,
          onProgress: (s) => {
            if (!s) return;
            const p = s.progress ? ` ${s.done}/${s.total}` : "";
            say((s.detail || t("Working…")) + p);
          },
        });
        if (st && st.state === "error") {
          say(t("Qualification failed — see console"));
          console.error("qualifyBulkStart", st.error);
        } else if (_jobStillRunning(st)) {
          say(t("Still running in the background — see the task manager."));
        } else if (st && st.result) {
          const r = st.result;
          say(`${r.qualified || 0} ${t("qualified")} · ${r.disqualified || 0} ${t("disqualified")} · `
            + `${r.no_evidence || 0} ${t("no evidence yet")}`
            + (r.paused_reason ? ` — ${r.paused_reason}` : ""));
        }
      } catch (e) {
        say(t("Qualification failed — see console"));
        console.error("qualifyBulkStart", e);
      } finally {
        if (btn) btn.disabled = false;
        loadQualifyBulk();
      }
    }
    async function qualifyBulkCancel() {
      try { await api("/api/sources/qualify-bulk/cancel", {method: "POST"}); }
      catch (e) { /* best-effort */ }
      loadQualifyBulk();
    }

    async function exportMethods(qArg) {
      // RM-07: the *how* behind the current search, as a downloadable document.
      const q = (qArg != null ? qArg : $("q").value.trim());
      if (!q) { toast("Run a search first — the appendix records the query.", "err"); return; }
      try {
        const r = await api("/api/reports/methods",
          {method: "POST", body: JSON.stringify({query: q})});
        const blob = new Blob([r.markdown], {type: "text/markdown"});
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "methods-appendix.md";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(a.href);
        toast(`Methods appendix downloaded (${r.article_count} articles).`);
      } catch (e) { toast(_failMsg("Methods export failed: {error}", e), "err"); }
    }

    // The "AI" pill (B4, 2026-07-24 field-feedback Session B — was the "LLM" pill,
    // renamed + simplified: green/red by whether the ACTIVE backend [Ollama or vLLM,
    // dual-backend B1] is reachable, NO model count anymore). The local model is
    // refused under airplane mode (we boot offline), so a once-at-boot check goes
    // stale "offline". This re-checks on: boot, going online (_paintNetwork), opening
    // Settings → AI, after any LLM action, when the tab regains focus, and on click —
    // so it tracks a backend that started/stopped later.
    // Clicking GREEN opens Settings → AI (which also re-checks health); clicking RED
    // tries to START the preferred installed backend (vLLM first, since it is the one
    // this app can actually start/stop) and falls back to Settings → AI (the install
    // flow) when nothing can be started automatically.
    function openAiSettings() {
      showTab("settings");
      try { (_setSubtabs || { select: showSetCat }).select("models"); }
      catch (e) { showSetCat("models"); }
    }
    // Clicking the red AI pill should START the local AI, not merely navigate to a
    // panel (field report 2026-07-30: "clicking the AI button does not start vLLM, it
    // should start either vLLM or Ollama automatically and load the default model and
    // then turn green"). The previous version only ever tried vLLM, and only under four
    // simultaneous conditions -- so on an Ollama-only machine, or with no vLLM model
    // chosen, it silently fell through to opening Settings.
    //
    // WHERE THE LINE IS, and why it is not "do everything silently": starting a local
    // daemon is free, local and instantly reversible, so it happens automatically.
    // DOWNLOADING a model is multi-gigabyte network traffic that egresses CLEARNET via
    // the Ollama process (NOT through Tor) -- so it is offered, with its size, and
    // never begun by a single click on a status pill.
    async function aiPillStartOrInstall() {
      // ONE server-side decision, not a fourth copy of it.
      //
      // This used to re-derive "which backend do I start" in the browser from
      // vllm_can_launch / ollama.can_launch plus a settings read -- a fourth ordering
      // beside routing, provisioning and activation, and one with a real hole: if
      // llm_model_vllm was unset it fell through to Ollama even on a GPU machine whose
      // vLLM was installed and whose default weights were already downloaded. The
      // server now answers the question in one place (src/llm/activation.py), which is
      // also what the maintainer asked for: clicking this starts whichever backend
      // this machine should run, vLLM preferred where it can serve.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let act = null;
      try {
        toast(t("Starting the local AI…"));
        act = await api("/api/llm/activation/start", {method: "POST"});
      } catch (e) {
        toast(t("Could not start the local AI:") + " " + (e.message || e), "err");
        openAiSettings();
        return;
      }
      if (act.ready || act.started) {
        // A vLLM engine load takes tens of seconds, so "started" is not "answering"
        // and the detail says which -- never a bare spinner over an unknown wait.
        if (act.detail) toast(act.detail);
        if (act.backend === "ollama") await _aiPillEnsureModel(t);
        _aiPillSettle();
        return;
      }
      // A blocker is structural (nothing installed, weights not downloaded). It is
      // reported in words and the operator is sent to the flow that can fix it --
      // installing a BACKEND is a bigger, consented chain that lives in Settings.
      if (act.detail) toast(act.detail, "err");
      openAiSettings();
    }

    // A START IS NOT AN INSTANT, and the watcher has to outlive the thing it watches.
    //
    // This used to re-check at 800ms, 2.5s and 6s and then stop -- while the comment
    // three lines above it said, correctly, that a vLLM engine load "takes tens of
    // seconds" (it reaches CUDA-graph capture around t+67s). So on every machine where
    // the start took longer than six seconds the watcher gave up first, the pill stayed
    // red, and the backend only went green when something ELSE happened to re-check:
    // opening Settings -> AI, which calls loadLlmHealth() on subtab select. That is the
    // reported symptom exactly -- "it seems to work, but doesn't turn green, it turns
    // green only when I go to the setting's AI tab".
    //
    // A BOUNDED WATCHER THAT EXITS SILENTLY PUBLISHES ITS OWN TIMEOUT AS THE WORK'S
    // OUTCOME (the same defect the all-diagnostics watcher had). So this one: is bounded
    // by what the work actually costs rather than by a number that felt generous once;
    // backs off instead of hammering; and when it does give up it SAYS SO, because a red
    // pill left to speak for a start that may still be loading is a fabricated verdict.
    const _AI_SETTLE_MS = 150000;   // ~2.5 min -- comfortably past a vLLM engine load
    let _aiSettleCancel = null;
    function _aiPillSettle() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_aiSettleCancel) _aiSettleCancel();      // one watcher at a time
      let stopped = false;
      _aiSettleCancel = () => { stopped = true; };
      _aiStarting = true;
      _paintAiPill();                               // the pulse starts immediately
      const t0 = Date.now();
      let delay = 700;
      const done = () => { _aiStarting = false; _aiSettleCancel = null; };
      const tick = async () => {
        if (stopped) return;
        let up = false;
        try { const h = await api("/api/llm/health"); up = !!(h && h.available); }
        catch (e) { /* transient -- keep waiting, the bound below is the real limit */ }
        if (stopped) return;
        if (up) { done(); loadLlmHealth(); return; }
        if (Date.now() - t0 >= _AI_SETTLE_MS) {
          done();
          loadLlmHealth();                          // paint whatever is actually true
          toast(t("The local AI has not answered yet. It may still be loading — open AI settings for the details."), "err");
          return;
        }
        delay = Math.min(Math.round(delay * 1.4), 8000);
        setTimeout(tick, delay);
      };
      setTimeout(tick, delay);
    }

    // Returns true if a model is present (or a download was started). Offers the
    // default model when none is installed -- the "load the default model" half of the
    // ask, with the download offered rather than silently begun.
    async function _aiPillEnsureModel(t) {
      let d = null;
      try { d = await api("/api/llm/models"); } catch (e) { return false; }
      if ((d.installed || []).length) return true;
      if (!(d.ministral && d.ministral.tag)) return false;
      // The SAME backend-aware path as the button, never the Ollama-only one: on a
      // machine vLLM will serve, pulling the Ollama image would download the wrong
      // artifact and still leave the pill red.
      await installDefaultModel(null);
      return true;
    }
    async function aiPillClick() {
      try {
        const h = await api("/api/llm/health");
        if (h.available) { openAiSettings(); return; }
      } catch (e) { /* treat as offline — fall through */ }
      await aiPillStartOrInstall();
    }
    // ----------------------------------------------------------------------- //
    //  The pill has FOUR states, not two (maintainer 2026-08-12): "there's a
    //  difference between AI is active and ready, and AI is working".
    //
    //    off       nothing is serving            red + diagonal bar
    //    starting  a start we asked for is in flight   accent + breathing pulse
    //    ready     serving, idle                 green, still
    //    working   serving, mid-inference        green + travelling underline
    //
    //  Two rules hold across all four. The LABEL is always the constant "AI", so the
    //  footprint never moves and nothing to its right shifts (invariant #3). And the
    //  state is never carried by colour or motion ALONE: each has its own SHAPE, and
    //  the hover title says it in words -- which is also what keeps the pill readable
    //  under `prefers-reduced-motion`, where app.css disables every animation outright.
    // ----------------------------------------------------------------------- //
    let _aiStarting = false;      // a start we asked for has not settled yet
    let _aiHealth = null;         // last /api/llm/health payload (null = never read)
    let _aiBusyLocal = 0;         // inference THIS browser drives -- free, instant
    let _aiBusyServer = false;    // work the server reported (sweeps, batch holds)
    let _aiBusyLabel = null;      // what it is working on, for the hover title

    function _aiBusy() { return _aiBusyLocal > 0 || _aiBusyServer; }

    // Bracket anything in this browser that makes a model compute, so the pill
    // reports it INSTANTLY and without asking the server. The server cannot see a
    // bulk run driven straight from here anyway (it is a stream this page owns), and
    // a round trip to learn what we already know would be both slower and pointless.
    async function aiWorking(fn) {
      _aiBusyLocal++;
      _paintAiPill();
      try { return await fn(); }
      finally { _aiBusyLocal = Math.max(0, _aiBusyLocal - 1); _paintAiPill(); }
    }

    function _paintAiPill() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("llm");
      if (!el) return;
      el.style.cursor = "pointer";
      el.onclick = aiPillClick;
      el.textContent = "AI";      // constant footprint, never a count

      // STARTING outranks the last health reading on purpose: we know we just asked
      // for a start, which makes any earlier "offline" reading stale by definition.
      // Showing red through a start we ourselves triggered is what made the old pill
      // read as "it didn't work".
      if (_aiStarting) {
        el.className = "pill ai-starting";
        el.title = t("Starting the local AI… — a model load can take a minute");
        return;
      }
      const h = _aiHealth;
      if (h && h.available) {
        if (_aiBusy()) {
          el.className = "pill ok ai-busy";
          el.title = (_aiBusyLabel ? _aiBusyLabel + " — " : "")
            + t("AI is working right now");
        } else {
          el.className = "pill ok";
          el.title = t("AI — click to open AI settings");
        }
        return;
      }
      if (h && h.hardware_practical === false) {
        // HARDWARE SUITABILITY (2026-07-30): a state distinct from "offline".
        // Starting a backend would not fix this machine, so the pill must NOT
        // invite that — it points at the disclosure + the override instead.
        // `=== false` on purpose: `null` means the probe could not decide, which
        // must fall through to the ordinary offline copy rather than assert a
        // hardware verdict nothing measured.
        el.className = "pill warn ai-off";
        el.title = (h.hardware_reason ? h.hardware_reason + " — " : "")
          + t("AI features are off by default on this hardware — open AI settings to override");
        return;
      }
      el.className = "pill warn ai-off";
      if (!h) {
        // The health probe itself failed, so a backend is certainly not serving:
        // showing the neutral pill here would read as "fine" on no evidence.
        el.title = t("AI — click to open AI settings");
        return;
      }
      // V4 (2026-07-29): the red pill must name the REAL situation. `no_backend`
      // means NOTHING is reachable (not merely that the selected backend is down),
      // so lead with the server's own resolution sentence (`backend_reason` —
      // English server text, the same class as `h.detail`) instead of a generic
      // "offline".
      const why = h.no_backend ? (h.backend_reason || h.detail || "") : (h.detail || "");
      el.title = (why ? why + " — " : "")
        + t("AI is offline — click to start it, or open AI settings to install one");
    }

    // Work the SERVER is doing (background sweeps, a batch holding the model) has to
    // be asked for -- but only where an answer is possible. Three gates keep this from
    // becoming the polling storm the 2026-07-01 field diagnostics found (F5: ~28.9k
    // /api/scheduler/activity calls overnight, contending with the encrypted store):
    //
    //   * it does not run at all unless a backend is actually SERVING -- an AI-off
    //     machine, which is most of them, pays nothing;
    //   * it stops while the tab is hidden;
    //   * /api/llm/activity reads only in-memory state (a dict and two counters behind
    //     locks). No DB, no subprocess, no socket -- which is the property that makes
    //     polling it defensible at all, and why it is a new endpoint rather than a
    //     second caller of the heavy activity route.
    let _aiActPollTimer = null;
    function _aiActShouldPoll() {
      return !!(_aiHealth && _aiHealth.available) && !document.hidden;
    }
    // Faster while something is running, because the interesting edge is the END of
    // the work; calm while idle, because nothing is expected to change.
    function _aiActCadence() { return _aiBusy() ? 4000 : 15000; }
    function _ensureAiActivityPoll() {
      if (_aiActPollTimer) { clearTimeout(_aiActPollTimer); _aiActPollTimer = null; }
      if (!_aiActShouldPoll()) {
        // The backend went away: drop the server-side claim rather than leaving a
        // stale "working" on a pill whose backend is gone.
        if (_aiBusyServer) { _aiBusyServer = false; _aiBusyLabel = null; _paintAiPill(); }
        return;
      }
      const tick = async () => {
        if (!_aiActShouldPoll()) { _aiActPollTimer = null; return; }
        try {
          const a = await api("/api/llm/activity");
          const was = _aiBusyServer;
          _aiBusyServer = !!(a && a.working);
          // A named task ("Translating → German: …") says the most; failing that the
          // MODEL is still a real fact worth putting in the title, and the counter
          // alone carries no words. Both come from the same payload — this composes
          // what is there, it does not invent a label when there is none.
          _aiBusyLabel = (a && (a.label || (a.models || [])[0])) || null;
          if (was !== _aiBusyServer) _paintAiPill();
          else if (_aiBusyServer) _paintAiPill();   // the label may have moved on
        } catch (e) { /* transient -- keep the last known state, never invent one */ }
        _aiActPollTimer = setTimeout(tick, _aiActCadence());
      };
      tick();
    }

    async function loadLlmHealth() {
      const el = $("llm");
      if (!el) return;
      try { _aiHealth = await api("/api/llm/health"); }
      catch (e) { _aiHealth = null; }    // null = the probe failed, never a fake "fine"
      _paintAiPill();
      _ensureAiActivityPoll();           // only polls while a backend is actually up
    }

    // --------------------------------------------------------------------- //
    //  Dual-backend + vLLM lifecycle panel (Settings -> AI, B1/B2/B4, 2026-07-24
    //  field-feedback Session B). Disclosed decision (never a silent switch),
    //  the install/start/stop controls, and honest "starting…" states (model
    //  load takes tens of seconds — never a fake instant green).
    // --------------------------------------------------------------------- //
    // ------------------------------------------------------------------ //
    //  ONE setup control (maintainer 2026-07-31, the Settings review). The AI
    //  tab used to scatter three separate installs across three panels -- the
    //  Ollama binary, vLLM, and the default model -- so "get local AI working"
    //  meant finding all three and knowing which applied to this machine. This
    //  box states the WHOLE remaining plan in one place and runs it from one
    //  button, choosing the backend from the hardware (vLLM where a dedicated
    //  GPU can serve it, Ollama otherwise) instead of asking the operator to.
    //
    //  NOTHING IS LOST (the Desk lesson): the per-component controls stay
    //  exactly where they were, and this box HIDES ITSELF once there is nothing
    //  left to do -- it is a shortcut past the scatter, never a replacement.
    //
    //  WHERE THE LINE IS, same as the pill's: starting a local daemon is free
    //  and reversible, so it just happens; DOWNLOADING is multi-gigabyte
    //  CLEARNET traffic (not through Tor), so the total is stated up front and
    //  the whole chain runs only after one explicit confirmation.
    // ------------------------------------------------------------------ //
    async function _aiSetupPlan() {
      // Every fact comes from the server. A failed read returns null so the box
      // hides rather than proposing a plan built on a guess.
      let b, dm;
      try {
        b = await api("/api/llm/backend");
        dm = await api("/api/llm/default-model");
      } catch (e) { return null; }
      const vllm = b.vllm || {};
      const oll = b.ollama || {installed: !!b.ollama_available, running: !!b.ollama_available};
      // THE TARGET IS THE SERVER'S PROVISIONING ANSWER, not a GPU probe read here.
      //
      // It used to be `gpu.available ? "vllm" : "ollama"`, which ignores the operator's
      // explicit choice in Settings entirely -- so switching a GPU machine to Ollama
      // left this card offering to install vLLM, the backend they had just moved away
      // from, while saying nothing about the one that was actually missing. That is the
      // maintainer's own case (2026-08-12: "if a user decides to switch from vLLM to
      // Ollama and the latter is neither detected nor installed, put the setup tool
      // back with the missing engine"). /default-model resolves through
      // _provisioning_backend, which honours the choice.
      const target = dm && dm.backend === "vllm" ? "vllm" : "ollama";
      const steps = [];
      if (target === "vllm" && !vllm.installed) {
        let s = null;
        try { s = await api("/api/llm/vllm/status"); } catch (e) { /* size stays unknown */ }
        steps.push({
          id: "install-vllm",
          label: "Install vLLM",
          size: (s && s.estimated_size_note) || "several GB",
        });
      }
      if (target === "ollama" && !oll.installed) {
        let s = null;
        try { s = await api("/api/llm/install/status"); } catch (e) { return null; }
        steps.push({
          id: "install-ollama",
          label: "Install Ollama",
          size: "",
          scripted: !!(s.platform && s.platform.scripted),
          download_url: (s.platform && s.platform.download_url) || "https://ollama.com/download",
        });
      }
      // THE MODEL STEP IS TRI-STATE, and reading it as a boolean is what kept this card
      // on screen for people who were finished (maintainer 2026-08-12: "when the local
      // AI is properly installed (including ministral download), remove Setup Local AI,
      // it's pointless"). It used to test `models.installed.length` -- the RUNNING
      // daemon's list -- so a stopped Ollama reported nothing and the card offered to
      // re-download a model already on the disk.
      //
      // `installed === null` means the probe could not answer, which is NOT "absent".
      // The honest move there is to propose nothing: a stopped-but-installed backend is
      // already handled by the hero card above, which says so and offers Start. Once it
      // starts, the probe answers and this card comes back if the model really is
      // missing. Offering several GB on an unreadable probe is the trap the store
      // panel's own note names.
      if (dm && dm.artifact && dm.installed === false) {
        steps.push({id: "model", label: "Download the default model",
                    artifact: dm.artifact, size: dm.size || "", note: dm.mechanism_note || "",
                    caveats: dm.caveats || []});
      }
      return {target, steps, backend: b, running: target === "vllm" ? !!vllm.running : !!oll.running};
    }

    let _aiSetupRunning = false;
    async function loadAiSetup() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("ai-setup-box");
      if (!box || _aiSetupRunning) return;   // never clobber a run's own output
      const plan = await _aiSetupPlan();
      if (!plan || !plan.steps.length) { box.style.display = "none"; box.innerHTML = ""; return; }
      const backendName = plan.target === "vllm" ? "vLLM" : "Ollama";
      const rows = plan.steps.map((s) => {
        const size = s.size ? ` <span class="muted">(${esc(s.size)})</span>` : "";
        const what = s.id === "model" ? `${s.label} — <code>${esc(s.artifact)}</code>` : esc(s.label);
        return `<li>${what}${size}</li>`;
      }).join("");
      // macOS/Windows have no scripted Ollama install, so a "one click" button
      // there would be a promise the app cannot keep -- link the real installer.
      const manual = plan.steps.find((s) => s.id === "install-ollama" && !s.scripted);
      const action = manual
        ? `<p><a href="${esc(manual.download_url)}" target="_blank" rel="noopener">${esc(t("Open ollama.com/download ↗"))}</a> ` +
          `<span class="muted">${esc(t("then return here — the rest is one click."))}</span></p>`
        : `<p><button id="ai-setup-btn" onclick="runAiSetup(this)">${esc(t("Set up local AI"))}</button></p>`;
      box.style.display = "";
      box.innerHTML =
        `<div class="panel" style="border-color:var(--accent);margin:0 0 10px">` +
        `<strong>${esc(t("Set up local AI"))}</strong>` +
        `<p class="muted" style="margin:6px 0">` +
        esc(t("This machine will use")) + ` <b>${esc(backendName)}</b>. ` +
        esc(t("Remaining steps:")) + `</p><ul style="margin:4px 0 8px 18px">${rows}</ul>` +
        `<p class="card-caveat">${esc(t("The downloads go over the clear internet — not through this app's Tor proxy. They happen once; the model then runs fully offline."))}</p>` +
        action +
        `<div id="ai-setup-status" class="hint" style="margin-top:6px"></div></div>`;
    }

    async function runAiSetup(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const plan = await _aiSetupPlan();
      if (!plan || !plan.steps.length) { loadAiSetup(); return; }
      // ONE consent for the WHOLE chain, naming every artifact and its size --
      // the same "state the cost before the bytes" rule the per-step buttons
      // follow, asked once instead of three times.
      const lines = plan.steps.map((s) =>
        "• " + (s.id === "model" ? `${s.label}: ${s.artifact}` : s.label) + (s.size ? `  (${s.size})` : ""));
      const modelStep = plan.steps.find((s) => s.id === "model");
      const ok = confirm(
        t("Set up local AI on this machine?") + "\n\n" + lines.join("\n") + "\n\n" +
        t("This downloads over the clearnet — not through Tor.") +
        (modelStep && modelStep.note ? "\n" + modelStep.note : "") +
        (modelStep && modelStep.caveats.length ? "\n\n" + modelStep.caveats.join("\n") : "")
      );
      if (!ok) return;
      // ONE egress window for the WHOLE chain, taken here so the per-step calls
      // below find it already open and never ask again. The collector is not
      // started: this allows the install to reach the network, nothing else.
      if (!await ensureAiEgress(t("Set up local AI (downloads several GB over the clear internet)"))) return;
      const status = $("ai-setup-status");
      const say = (msg) => { if (status) status.textContent = msg; };
      const was = btn ? btn.textContent : "";
      _aiSetupRunning = true;
      if (btn) { btn.disabled = true; btn.textContent = t("Working…"); }
      try {
        // The plan is a KNOWN, finite list, so "step i of N" is a real count, not
        // an invented percentage. Within a step we show the job's own reported
        // line and never synthesise a fraction: pip gives no reliable progress
        // figure, and the installer is explicit about never faking one.
        const total = plan.steps.length;
        let idx = 0;
        for (const step of plan.steps) {
          idx += 1;
          const label = t(step.label || step.id);
          const head = OOI18N && OOI18N.tf
            ? OOI18N.tf("Step {i} of {n} — {label}", {i: idx, n: total, label})
            : `Step ${idx} of ${total} — ${label}`;
          const sayStep = (line) => say(line ? `${head} · ${line}` : head);
          sayStep("");
          if (step.id === "install-vllm") {
            // Reuses the existing installer, 409-acknowledgement path included --
            // a resource warning must still be answerable here, not only from the
            // vLLM section's own button.
            const r = await _vllmInstallStart();
            if (!r) { say(t("Cancelled.")); return; }   // the operator declined the warning
            // AWAIT the install. Starting it is not finishing it: the POST returns
            // the moment the worker thread is spawned, so the chain used to race
            // straight on to downloading a model into a venv that did not exist
            // yet and starting a server whose backend was still installing.
            const done = await _followJob("/api/llm/vllm/install/status", sayStep);
            if (done.state === "error") {
              say(t("vLLM install failed:") + " " + (done.error || done.detail || ""));
              return;   // never carry on into steps that need the backend
            }
            if (done.state === "cancelled") { say(t("Cancelled.")); return; }
          } else if (step.id === "install-ollama") {
            // Ends in the "Install Ollama" box below: elevation is explicit and
            // may need a password this app must never pretend to have.
            say(t("Continue in the Install Ollama box below."));
            await prepareOllamaInstall();
            return;
          } else if (step.id === "model") {
            // The chain already took ONE consent covering this download, so the
            // per-button confirm would be a second ask for the same bytes.
            await _installDefaultModel(null, {confirmed: true});
            // Same defect as the vLLM step: this POST only STARTS a multi-GB
            // Hugging Face fetch. Without following it, the chain reported "Done."
            // while gigabytes were still arriving, and then tried to start a
            // server against weights that were not there yet.
            const done = await _followJob("/api/llm/default-model/status", sayStep);
            if (done.state === "error") {
              say(t("Model download failed:") + " " + (done.error || done.detail || ""));
              return;
            }
            if (done.state === "cancelled") { say(t("Cancelled.")); return; }
            // "idle" means the queue was never asked for this artifact -- the install
            // call refused (a missing prerequisite, say) and reported that itself.
            // Carrying on would start a server against weights that are not coming and
            // then print "Done.", which is the one outcome worse than a visible failure.
            if (done.state === "idle") {
              say(t("The model download never started — see the message above."));
              return;
            }
          }
        }
        // Free, local, reversible -- so it just happens, per the pill's own rule.
        say(t("Starting the local AI…"));
        try { await aiPillStartOrInstall(); } catch (e) { /* the panels report the real state */ }
        say(t("Done."));
      } catch (e) {
        say(t("Setup failed:") + " " + (e.message || e));
      } finally {
        _aiSetupRunning = false;
        if (btn) { btn.disabled = false; btn.textContent = was; }
        refreshAiPanels();
      }
    }

    // ----------------------------------------------------------------- //
    //  THE ONE LOCAL-AI CARD (2026-08-04 rework)
    //
    //  State, the single action, and the hardware the choice was made from --
    //  replacing a backend panel, a vLLM panel and an Ollama panel that each told
    //  a third of the story. Every fact is read from the server; a failed read
    //  says so rather than rendering a confident blank.
    // ----------------------------------------------------------------- //
    // The frame translates, the data does not: a fixed keyable template with
    // {named} holes, interpolated after lookup. A concatenated fragment ("running
    // on" + a name) cannot be keyed usefully -- word order and agreement differ per
    // language -- which is what OOI18N.tf exists for.
    function _tf(tpl, vars) {
      if (window.OOI18N && OOI18N.tf) return OOI18N.tf(tpl, vars);
      return String(tpl).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
    }

    function _hwChips(gpu, cap) {
      const chip = (label, value, title) =>
        `<span class="pill" title="${esc(title || "")}"><span class="muted">${esc(label)}</span> ${esc(value)}</span>`;
      const out = [];
      if (gpu && gpu.available) {
        out.push(chip("GPU", gpu.name || "detected", "A dedicated GPU was detected, so vLLM can serve here."));
        if (gpu.vram_mb) out.push(chip("VRAM", Math.round(gpu.vram_mb / 1024) + " GB", ""));
      } else {
        out.push(chip("GPU", (window.OOI18N && OOI18N.t ? OOI18N.t("none detected") : "none detected"),
          "No dedicated GPU was found. vLLM needs one; Ollama runs on the CPU."));
      }
      // Field names read from inference_capability()'s real payload, not assumed:
      // total_ram_gb / cpu_cores / unified_ram_gb. A missing one is omitted rather
      // than rendered as a blank chip.
      if (cap) {
        const ram = cap.total_ram_gb || cap.unified_ram_gb;
        if (ram) out.push(chip("RAM", ram + " GB", cap.method || ""));
        if (cap.cpu_cores) out.push(chip("Cores", String(cap.cpu_cores), ""));
      }
      return `<div class="row" style="gap:6px;flex-wrap:wrap;margin-top:6px">${out.join("")}</div>`;
    }

    async function loadAiHero() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("ai-hero");
      if (!box) return;
      let act = null, b = null, health = null;
      try {
        act = await api("/api/llm/activation");
        b = await api("/api/llm/backend");
      } catch (e) {
        box.innerHTML = `<p class="muted">${esc(t("Could not read the local AI state."))}</p>`;
        return;
      }
      try { health = await api("/api/llm/health"); } catch (e) { health = null; }

      const name = act.backend === "vllm" ? "vLLM" : "Ollama";
      const serving = !!(health && health.available);
      // THREE states, not two: serving / installed-but-stopped / not set up. The
      // middle one is the whole reason "it won't start" was reported -- collapsing
      // it into "off" is what left the operator with nothing to press.
      let head, action = "";
      if (serving) {
        head = `<span class="ok">●</span> ` +
               esc(_tf("Ready — running on {backend}", {backend: name})) +
               ((health.installed_models || []).length
                  ? ` <span class="muted">${esc(health.installed_models[0])}</span>` : "");
        if (act.backend === "vllm") {
          action = `<button class="ghost" onclick="stopVllm(this)">${esc(t("Stop"))}</button>`;
        }
      } else if (act.can_start) {
        head = `<span class="warn">●</span> ` +
               esc(_tf("Installed but not running — {backend}", {backend: name}));
        action = `<button onclick="aiStartNow(this)">${esc(t("Start the local AI"))}</button>`;
      } else {
        head = `<span class="muted">●</span> ` + esc(t("Not set up on this machine yet"));
      }

      const why = act.chosen_because ? `<div class="hint" style="margin-top:4px">${esc(act.chosen_because)}</div>` : "";
      // A blocker is the actionable half: it names what is missing instead of
      // leaving a dead control and a spinner.
      const blocker = act.blocker
        ? `<div class="card-caveat" style="margin-top:6px">${esc(act.blocker)}</div>` : "";
      // A start that FAILED stays on the card, with the server's own first words.
      // Field report 2026-08-04: "vLLM doesn't seem to start" -- a toast is gone by
      // the time the operator goes looking for the reason, and a path to a log file
      // asks them to go and find it. The HEAD is the right end for a startup failure:
      // vLLM's EngineCore is a CHILD process, so its traceback prints before the
      // parent's stack.
      //
      // `act.last_start` is the SERVER's answer, so it survives a reload and catches a
      // death that happened long after the click (a CUDA OOM well into a model load).
      // The local one covers the moment before the next poll, and the backends whose
      // failures the vLLM-only tri-state cannot see.
      if (serving) _aiStartFailure = null;
      const fail = act.last_start || (serving ? null : _aiStartFailure);
      let failed = "";
      if (fail) {
        failed = `<div class="card-caveat" style="margin-top:6px">${esc(fail.detail || "")}`
               + `${fail.log_hint ? " " + esc(fail.log_hint) : ""}</div>`;
        if (fail.server_log_head) {
          failed += `<details style="margin-top:6px"><summary>${esc(t("What the server printed"))}</summary>`
                  + `<pre style="white-space:pre-wrap;overflow-x:auto;max-height:220px;font-size:12px">`
                  + `${esc(fail.server_log_head)}</pre></details>`;
        }
      }
      box.innerHTML =
        `<div style="font-size:15px">${head}</div>` + why + blocker + failed +
        _hwChips(b.gpu || {}, b.hardware || null) +
        (action ? `<div class="row" style="gap:8px;margin-top:8px">${action}</div>` : "");
    }

    //: The last start that did not take, kept until one does. Cleared by loadAiHero
    //: the moment a backend actually serves, so a stale failure can never outlive it.
    let _aiStartFailure = null;

    async function aiStartNow(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const was = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = t("Starting…"); }
      try {
        const r = await api("/api/llm/activation/start", {method: "POST"});
        _aiStartFailure = (r.ready || r.started) ? null : r;
        if (r.detail) toast(r.detail, (r.ready || r.started) ? "" : "err");
      } catch (e) {
        toast(_apiErrorMessage ? _apiErrorMessage(e) : String(e), "err");
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = was; }
        // A vLLM engine takes tens of seconds, so re-read a few times rather than
        // painting one snapshot that will be wrong in five seconds.
        [1000, 4000, 12000].forEach(ms => setTimeout(() => { loadAiHero(); loadLlmHealth(); }, ms));
      }
    }

    // Where the weights actually live. CONFIGURED and DETECTED are separate facts:
    // an env var reaches processes this app spawns, so a systemd-managed Ollama keeps
    // its own store, and saying "they are in the app folder" when they are not would
    // leave the operator no way to understand why.
    async function loadAiStore() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("ai-store-box");
      if (!box) return;
      let r = null;
      try { r = await api("/api/llm/model-store"); } catch (e) { box.textContent = ""; return; }
      const gb = (n) => (n === null || n === undefined) ? "" : ` <span class="muted">(${(n / 1e9).toFixed(1)} GB)</span>`;
      let html = `<div>${esc(t("Models are stored in"))} <code>${esc(r.root)}</code></div>`;
      // The path IN USE leads when it is not the app's: printing the configured one
      // (near-empty) beside a size reads as "you have no models" to an operator whose
      // real store holds twenty GB, which is how "the app downloaded them into
      // ~/.ollama" gets discovered by opening a file manager instead of this panel.
      if (r.ollama.in_app_folder === false) {
        html += `<div style="margin-top:2px">Ollama: <code>${esc(r.ollama.detected)}</code>` +
                `${gb(r.ollama.detected_bytes)} <span class="muted">${esc(t("in use"))}</span></div>` +
                `<div class="muted">${esc(t("app folder, not in use"))}: ` +
                `<code>${esc(r.ollama.configured)}</code>${gb(r.ollama.bytes)}</div>`;
      } else {
        html += `<div style="margin-top:2px">Ollama: <code>${esc(r.ollama.configured)}</code>${gb(r.ollama.bytes)}</div>`;
      }
      html += `<div>Hugging Face: <code>${esc(r.huggingface.configured)}</code>${gb(r.huggingface.bytes)}</div>`;
      // A SPLIT is its own state, and it is the one the operator actually reported
      // ("models did download into ~/.ollama, yet there is another folder containing
      // ollama models in .../data/models/ollama"). It is NOT covered by the note above:
      // when the daemon is measurably reading the app folder, in_app_folder is true and
      // nothing was said at all, so a second folder full of models stayed orphaned with
      // no offer to consolidate. The button belongs to either state.
      if (r.ollama.split_note) {
        html += `<div class="card-caveat" style="margin-top:4px">${esc(r.ollama.split_note)}</div>`;
      }
      if (r.ollama.note) {
        html += `<div class="card-caveat" style="margin-top:4px">${esc(r.ollama.note)}</div>`;
      }
      if (r.ollama.note || r.ollama.split_note) {
        html += `<div style="margin-top:4px"><button class="ghost tiny" onclick="migrateOllamaStore(this)">` +
                esc(t("Move them into the app folder")) + `</button>`;
        // The reclaim is a SEPARATE button, and only after a copy has put every model in
        // the app folder. A copy alone does not finish the job the operator asked for --
        // the folder they wanted emptied is still full -- but folding the deletion into
        // the copy would make a destructive step the default, and an interrupted "move"
        // over a multi-GB store is how both copies get lost.
        html += ` <button class="ghost tiny" onclick="migrateOllamaStore(this, true)" ` +
                `title="${esc(t("Deletes only the files confirmed already copied into the app folder. Run the copy first."))}">` +
                esc(t("…then delete the originals")) + `</button></div>`;
      }
      // Weights downloaded before the store moved here are still on the disk. Nothing
      // said so, so a model an operator already had reported "not downloaded" and its
      // start was refused -- which is what "vLLM doesn't seem to start" looked like.
      // No button: an HF cache uses symlinks into its own blobs/, so a copy that is
      // not symlink-aware would silently double the size or break the links. Naming
      // the folder is honest; a move this app has not built and tested would not be.
      if (r.huggingface.note) {
        html += `<div class="card-caveat" style="margin-top:4px">${esc(r.huggingface.note)}`
              + `${gb(r.huggingface.legacy_bytes)}</div>`;
      }
      box.innerHTML = html;
    }

    // ---- Uninstall the local AI (maintainer 2026-08-12) --------------------- //
    //
    // THE PLAN IS READ BEFORE THE BUTTON IS DRAWN, and again before it acts, because
    // the plan IS the consent: how much each backend would free, and which pieces this
    // app cannot remove. The Ollama program was installed on the system with
    // administrator rights, so what is offered there is its removal commands, not a
    // button that pretends to run them.
    function _gbytes(n) {
      return (n === null || n === undefined) ? "" : ` (${(n / 1e9).toFixed(1)} GB)`;
    }

    async function loadAiUninstall() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("ai-uninstall-box");
      if (!box) return;
      let plan = null;
      try { plan = await api("/api/llm/uninstall/plan"); }
      catch (e) { box.textContent = t("Could not read what is installed."); return; }
      const installed = plan.installed || [];
      if (!installed.length) {
        box.innerHTML = `<div>${esc(t("Nothing to uninstall — no AI backend is installed on this machine."))}</div>`;
        return;
      }
      const rows = (plan.backends || []).filter((b) => b.installed).map((b) => {
        const name = b.backend === "vllm" ? "vLLM" : "Ollama";
        const size = b.removable ? esc(_gbytes(b.bytes)) : "";
        const why = b.removable ? "" :
          `<div class="card-caveat" style="margin-top:2px">${esc(b.kept_reason || "")}</div>` +
          ((b.manual_removal || []).length
            ? `<pre style="white-space:pre-wrap;overflow-x:auto;font-size:12px;margin:4px 0">${esc(b.manual_removal.join("\n"))}</pre>`
            : "");
        return `<div style="margin-top:6px"><b>${esc(name)}</b>${size}` +
          (b.removable ? "" : ` <span class="muted">— ${esc(t("this app cannot remove it"))}</span>`) +
          `${why}<div style="margin-top:4px">` +
          `<button class="ghost tiny" onclick="uninstallAi(${esc(JSON.stringify([b.backend]))}, this)">` +
          `${esc(t("Uninstall"))} ${esc(name)}</button></div></div>`;
      }).join("");
      // Offered only when BOTH are here, because that is when it is a different action
      // rather than a second name for the same one.
      const both = plan.both_installed
        ? `<div style="margin-top:8px"><button class="ghost tiny" ` +
          `onclick="uninstallAi(${esc(JSON.stringify(["vllm", "ollama"]))}, this)">` +
          `${esc(t("Uninstall both backends"))}</button></div>` : "";
      const stores = (plan.stores || []).filter((st) => st.exists);
      const storeRows = stores.length
        ? `<div style="margin-top:8px">${esc(t("Downloaded models on this machine:"))}` +
          stores.map((st) =>
            `<div class="muted"><code>${esc(st.path)}</code>${esc(_gbytes(st.bytes))}` +
            (st.removable ? "" : ` — ${esc(t("kept"))}`) + `</div>`).join("") + `</div>`
        : "";
      box.innerHTML =
        `<div>${esc(plan.method || "")}</div>` + rows + both + storeRows +
        `<label class="small" style="display:block;margin-top:8px">` +
        `<input type="checkbox" id="ai-uninstall-models"> ` +
        esc(t("also delete the downloaded models in this app's folder")) + `</label>` +
        `<div id="ai-uninstall-status" class="hint" style="margin-top:6px"></div>`;
    }

    async function uninstallAi(backends, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const status = $("ai-uninstall-status");
      const delete_models = !!($("ai-uninstall-models") || {}).checked;
      // Re-read the plan rather than trusting the one the panel was drawn from: it may
      // be minutes old, and the numbers in this confirm are what is being consented to.
      let plan = null;
      try { plan = await api("/api/llm/uninstall/plan"); } catch (e) { plan = null; }
      const wanted = (((plan || {}).backends) || []).filter((b) => backends.indexOf(b.backend) >= 0);
      const lines = wanted.map((b) => {
        const name = b.backend === "vllm" ? "vLLM" : "Ollama";
        return b.removable
          ? `• ${name}${_gbytes(b.bytes)}`
          : `• ${name} — ${b.kept_reason || t("this app cannot remove it")}`;
      });
      if (delete_models) {
        for (const st of (((plan || {}).stores) || [])) {
          if (st.exists && st.removable) lines.push(`• ${st.kind}${_gbytes(st.bytes)} — ${st.path}`);
        }
      }
      if (!confirm(t("Uninstall the local AI? This cannot be undone.") + "\n\n" + lines.join("\n"))) return;
      const was = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = t("Removing…"); }
      try {
        const r = await api("/api/llm/uninstall", {
          method: "POST",
          body: JSON.stringify({backends, delete_models, confirm: true}),
        });
        // WHAT WAS KEPT IS REPORTED AS PROMINENTLY AS WHAT WENT. A button that says
        // "Uninstalled." whatever happened would leave an operator believing the
        // program is gone when it is still there and will still be serving next boot.
        const freed = r.freed_bytes ? _gbytes(r.freed_bytes).trim() : "";
        let msg = r.complete
          ? t("Uninstalled.") + (freed ? " " + freed : "")
          : t("Partly uninstalled.") + (freed ? " " + freed : "");
        if ((r.kept || []).length) {
          msg += "\n" + r.kept.map((k) => `• ${k.what}: ${k.reason || ""}`).join("\n");
        }
        if (status) { status.style.whiteSpace = "pre-wrap"; status.textContent = msg; }
      } catch (e) {
        if (status) status.textContent = t("Uninstall failed:") + " " +
          (_apiErrorMessage ? _apiErrorMessage(e) : String(e));
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = was; }
        refreshAiPanels();
      }
    }

    async function migrateOllamaStore(btn, reclaim) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const ask = reclaim
        ? t("Delete the originals? Only files already confirmed present in the app folder are removed — anything that was not copied stays. This cannot be undone.")
        : t("Copy the existing models into the app folder? Nothing is deleted — the originals stay where they are until you remove them yourself.");
      if (!confirm(ask)) return;
      const was = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = reclaim ? t("Deleting…") : t("Copying…"); }
      try {
        const r = await api("/api/llm/model-store/migrate" + (reclaim ? "?reclaim=true" : ""), {method: "POST"});
        toast(r.ok ? (reclaim
                        ? t("Done.") + ` ${r.copied} copied, ${r.removed} originals removed.`
                        : t("Copied.") + ` ${r.copied} copied, ${r.skipped} already there.`)
                   : (r.reason || t("Could not copy the models.")), r.ok ? "" : "err");
      } catch (e) {
        toast(_apiErrorMessage ? _apiErrorMessage(e) : String(e), "err");
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = was; }
        loadAiStore();
      }
    }

    // The dual-use model list. One button per model; the artifact behind it is
    // whichever build the ACTIVE backend can use. A model with no verified build for
    // that backend renders DISABLED with its reason rather than vanishing.
    let _catalogSel = new Set();
    async function loadModelCatalog() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("llm-catalog-box");
      if (!box) return;
      let c = null;
      try { c = await api("/api/llm/models/catalog"); } catch (e) { box.innerHTML = ""; return; }
      const rows = (c.models || []).map((m) => {
        const id = "mc-" + m.key;
        // WHERE A BUILD EXISTS AT ALL, shown on every row. Distinct from whether it
        // is usable on the backend running here: "Ollama only" is a fact about the
        // model, "not available for vllm" is a fact about this machine, and a reader
        // needs both to tell a model that was never published for their backend from
        // one that is simply discontinued.
        const only = m.only_label
          ? ` <span class="pill" title="${esc(t("This model has a verified build for one backend only."))}">${esc(t(m.only_label))}</span>`
          : "";
        if (!m.available) {
          // It exists elsewhere -- name where, and the identifier -- so the row is
          // informative rather than just a refusal.
          const elsewhere = m.other_artifact
            ? `<div class="hint"><code>${esc(m.other_artifact)}</code></div>` : "";
          // No control at all, not a DISABLED one. There is nothing here to act on,
          // and a dead tick-box is exactly the "useless element" this pass removes;
          // the row stays because WHY a model is missing is worth reading.
          return `<div class="row" style="gap:10px;align-items:flex-start;opacity:.65;margin:8px 0;` +
            `padding:8px;border:1px solid var(--line);border-radius:8px">` +
            `<span style="flex:1"><b>${esc(m.label)}</b>${only} <span class="muted">— ${esc(_tf("not available for {backend}", {backend: c.backend}))}</span>` +
            elsewhere +
            `<div class="hint">${esc(m.absent_reason || "")}</div></span></div>`;
        }
        // installed === null means the probe could not answer (a stopped daemon
        // genuinely does not know), which is not the same claim as "not installed".
        const bits = [m.size, m.licence, m.verification === "search-verified" ? t("identifier search-verified") : null]
          .filter(Boolean).map(esc).join(" · ");
        // ONE BIG BUTTON PER MODEL, and it DISAPPEARS once it has done its job
        // (maintainer 2026-08-09: "replace small tick boxes with big buttons ...
        // automatically remove useless elements of the UI such as a button to download
        // a model which is already downloaded"). A tick-box plus a shared "Download
        // selected" made choosing one model a two-step gesture and left a live control
        // on a row where there was nothing left to do.
        //
        // `installed === null` keeps its OWN answer rather than being folded into
        // either: a stopped daemon cannot tell us, and offering a download is the
        // honest move there -- downloading something already present is harmless,
        // whereas hiding the button on a guess would strand the operator.
        const action = m.installed === true
          ? `<span class="pill ok">${esc(t("Downloaded"))}</span>`
          : `<button data-mckey="${esc(m.key)}" onclick="installOneModel(${esc(JSON.stringify(m.key))}, this)">` +
            `${esc(t("Download"))}</button>` +
            (m.installed === null
              ? ` <span class="hint">${esc(t("already present? — could not read"))}</span>` : "");
        return `<div class="row" id="${esc(id)}" style="gap:10px;align-items:flex-start;margin:8px 0;` +
          `padding:8px;border:1px solid var(--line);border-radius:8px">` +
          `<span style="flex:1"><b>${esc(m.label)}</b>` +
          `${m.is_default ? ` <span class="pill">${esc(t("default"))}</span>` : ""}${only}` +
          `<div class="hint"><code>${esc(m.artifact)}</code>${bits ? " · " + bits : ""}</div>` +
          (m.summary ? `<div class="hint">${esc(m.summary)}</div>` : "") + `</span>` +
          `<span style="flex:0 0 auto;white-space:nowrap">${action}</span></div>`;
      }).join("");
      box.innerHTML =
        `<div style="font-weight:600">${esc(t("Available models"))}</div>` +
        `<div class="hint" style="margin:2px 0 6px">${esc(c.method || "")}</div>` +
        rows +
        `<div class="row" style="gap:8px;margin-top:8px;align-items:center">` +
        `<span id="mc-status" class="hint"></span></div>`;
    }

    // One model, one click. Shares the SAME endpoint and the same egress consent as the
    // multi-key path it replaces -- only the gesture changed, not the contract.
    async function installOneModel(key, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const status = $("mc-status");
      if (!await ensureAiEgress(t("Download local models (over the clear internet)"))) return;
      const was = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = t("Starting…"); }
      try {
        const r = await api("/api/llm/models/install",
          {method: "POST", body: JSON.stringify({keys: [key]})});
        for (const ref of (r.refused || [])) {
          toast(`${ref.label || ref.key}: ${ref.reason || t("refused")}`, "err");
        }
        if (r.action === "nothing_to_do") {
          if (status) status.textContent = t("Nothing to download — it was refused.");
          return;
        }
        if (status) status.textContent = t("Downloading:") + " " + (r.queued || []).join(", ");
        if (r.backend === "ollama") _llmPullStartPoll();
        const st = await _followJob(
          "/api/llm/models/install/status?backend=" + encodeURIComponent(r.backend || ""),
          (m) => { if (status) status.textContent = m; });
        if (status) {
          status.textContent = st.state === "error"
            ? (t("Download failed:") + " " + (st.detail || "")) : (st.detail || t("Done."));
        }
        // Repaint so the finished row loses its button and the picker gains the model.
        loadModelCatalog();
        loadLlmModels();
      } catch (e) {
        if (status) status.textContent = t("Download failed:") + " " + (e.message || e);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = was || t("Download"); }
      }
    }

    function refreshAiPanels() {
      loadAiHero(); loadAiStore(); loadModelCatalog(); syncAiCoordinator();
      loadAiSetup(); loadAiBackendPanel(); loadVllmStatusPanel();
      loadOllamaInstall(); loadLlmModels(); loadLlmHealth(); loadCustomModelBox();
      loadAiUninstall();
    }

    async function loadAiBackendPanel() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("ai-backend-box");
      const sel = $("ai-backend-select");
      if (!box) return;
      try {
        const b = await api("/api/llm/backend");
        const gpu = b.gpu || {};
        const vllm = b.vllm || {};
        // Ollama is now reported as two INDEPENDENT facts (installed / running), so
        // "installed but stopped" is finally a state the UI can see. Older payloads
        // carried only `ollama_available`; fall back to it so a stale server still
        // renders truthfully rather than claiming "not installed".
        const oll = b.ollama || {installed: !!b.ollama_available, running: !!b.ollama_available,
                                 can_launch: false};
        const ollTxt = oll.installed
          ? (oll.running ? t("installed, running") : t("installed, not running"))
          : t("not installed");
        // HARDWARE SUITABILITY (2026-07-30). `hw` may be absent from an older
        // server payload — render nothing then, rather than claiming a verdict.
        const hw = b.hardware;
        let hwHtml = "";
        if (hw && typeof hw.practical === "boolean") {
          const chk = hw.override_requested ? " checked" : "";
          const line = hw.practical
            ? (hw.overridden
                // Practical ONLY because the operator forced it: say so plainly, so
                // an override is never mistaken for a hardware pass.
                ? `<p class="card-caveat">${esc(t("AI features are enabled by your override, not by this hardware."))} ${esc(hw.reason)}</p>`
                : `<p class="hint">${esc(t("Hardware:"))}${hw.name ? " " + esc(hw.name) + " —" : ""} ${esc(hw.reason)}</p>`)
            : `<p class="card-caveat">${esc(t("AI features are off by default on this hardware."))} ${esc(hw.reason)}</p>`;
          // RULING 15 (2026-07-31): the tier between "refused" and "fine" -- a
          // CPU-only machine, a thin-VRAM card, a small unified-memory Mac. These
          // are EXPECTATIONS, not refusals, and this is the ONE place on the tab
          // that states them: the maintainer's review found the same "no GPU"
          // sentence repeated in four separate boxes, which reads as nagging and
          // buries the one statement that carries the actual consequence.
          const warns = (hw.warnings || []).length
            ? `<ul class="hint" style="margin:4px 0 4px 18px">` +
              hw.warnings.map((w) => `<li>${esc(w)}</li>`).join("") + `</ul>`
            : "";
          hwHtml = line + warns +
            `<p><label><input type="checkbox" id="ai-hw-override"${chk}` +
            ` onchange="setAllowImpracticalHw(this.checked)"> ` +
            `${esc(t("Run local AI anyway on this hardware"))}</label>` +
            ` <span class="muted">${esc(t("Your choice always wins — this is a default, never a block."))}</span></p>` +
            `<p class="hint">${esc(hw.method)} ${esc(hw.caveat)}</p>`;
        }
        box.innerHTML =
          `<p><b>Active backend:</b> ${esc(b.backend)} <span class="muted">— ${esc(b.reason)}</span></p>` +
          // The GPU is named here only when there IS one -- its absence is stated
          // ONCE, in the hardware block below, with the consequence attached.
          // (Repeating "not detected" here made it the first of four identical
          // sentences on this tab; maintainer review, 2026-07-31.)
          `<p class="hint">${gpu.available ? "GPU: " + esc(gpu.name || "detected") + " &middot; " : ""}` +
          `vLLM: ${vllm.installed ? "installed" : "not installed"}` +
          `${vllm.installed ? (vllm.running ? ", running" : ", not running") : ""}` +
          ` &middot; Ollama: ${esc(ollTxt)}</p>` +
          // A LAUNCH control, offered precisely when the software is present but not
          // answering (maintainer 2026-07-29). Shown only when it is honest to show:
          // `can_launch` is decided server-side so the rule lives in one place, and a
          // backend that is absent gets the install box instead, never a Launch button
          // that could only fail.
          (oll.can_launch
            ? `<p><button class="btn" onclick="launchOllama(this)">${esc(t("Launch Ollama"))}</button>` +
              ` <span class="muted">${esc(t("starts the local Ollama service"))}</span></p>`
            : "") +
          (b.vllm_can_launch
            ? `<p class="hint">${esc(t("vLLM is installed but not running — use Start in the vLLM section below."))}</p>`
            : "") +
          // V4: selection != capability. When neither backend can serve a request,
          // say so where the decision is disclosed, in the theme-aware caveat colour
          // (invariant #23's var(--caveat), AA-verified on all 17 themes).
          (b.no_backend
            ? `<p class="card-caveat">${esc(t("No AI backend is reachable right now — install or start one below."))}</p>`
            : "") +
          // HARDWARE SUITABILITY (2026-07-30, maintainer-ruled). Disclosed in BOTH
          // directions — never a silent block, never a silent enable — beside the
          // checkbox that reverses it. The caveat colour is invariant #23's
          // var(--caveat) (AA-verified on all 17 themes).
          hwHtml;
        if (sel) sel.value = b.stored_override || "auto";
      } catch (e) {
        box.innerHTML = `<p class="muted">Could not read the backend status.</p>`;
      }
    }

    async function setAllowImpracticalHw(on) {
      // The operator's explicit "run it anyway" (2026-07-30). Loopback settings
      // PUT only — no egress, so never ensureOnline-gated (same class as the
      // top-bar rate knob). Repaints from the SERVER's re-computed verdict rather
      // than assuming the flip took, and refreshes the pill so its third state
      // (impractical vs offline) updates immediately.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        await api("/api/settings", {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({llm_allow_impractical_hw: !!on}),
        });
        toast(on ? t("Local AI enabled on this hardware.") : t("Local AI back to the default for this hardware."));
      } catch (e) {
        toast("AI: " + e.message, "err");
      }
      loadAiBackendPanel();
      loadLlmHealth();
    }

    async function launchOllama(btn) {
      // Immediate feedback, then the REAL outcome from the server -- never an
      // optimistic green. The backend waits for the daemon to actually answer and
      // says so honestly if it did not, so a slow start reads as "still starting"
      // rather than as a ready server the next call would find unreachable.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const was = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = t("Launching…"); }
      try {
        const r = await api("/api/llm/ollama/start", {method: "POST"});
        if (r.started && r.ready) toast(t("Ollama is running."));
        else if (r.started) toast(r.note || t("Ollama was launched — it may still be starting."));
        else toast(t("Ollama was already running."));
      } catch (e) {
        toast("Ollama: " + e.message, "err");
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = was; }
      }
      loadAiBackendPanel();
      loadLlmHealth();
    }

    async function setAiBackend(value) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        await api("/api/settings", {method: "PUT", body: JSON.stringify({llm_backend: value})});
        toast(t("AI backend preference saved."));
      } catch (e) { toast("Backend: " + e.message, "err"); }
      loadAiBackendPanel();
      loadLlmHealth();
    }

    async function loadVllmStatusPanel() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("vllm-status-box");
      const installBox = $("vllm-install-box");
      if (!box) return;
      try {
        const s = await api("/api/llm/vllm/status");
        const parts = [];
        parts.push(s.installed ? "installed" : "not installed");
        if (s.installed) parts.push(s.running ? "running" : "not running");
        // GPU presence is NOT restated here. It is one of the four repetitions the
        // maintainer's 2026-07-31 review flagged, and the hardware block at the top
        // of this tab already states it once with its consequence. What this
        // section owes the operator is why ITS controls are unavailable, which the
        // install box and the Start button's title say directly.
        // The last start's own output, shown exactly when it is needed: installed but
        // not running (field report 2026-07-29 — a start that failed on a bad model id
        // or a CUDA OOM previously died with its reason discarded, leaving only a
        // permanent "not running").
        //
        // BOTH ENDS are rendered, in reading order (field report 2026-08-02). Only the
        // tail was shown, on the assumption that a CUDA OOM puts the numbers at the
        // end — true when a running server dies, false for a startup failure, where
        // vLLM's EngineCore child prints the reason FIRST and the parent then dumps
        // ~20 KB ending in "See root cause above". The operator's log was 29,855 bytes
        // and the reason sat in the 21,855 that were not shown.
        const lg = s.server_log || {};
        const gap = lg.elided_bytes > 0
          ? `<p class="muted">${esc(OOI18N && OOI18N.tf
              ? OOI18N.tf("… {n} bytes not shown …", {n: lg.elided_bytes.toLocaleString()})
              : `… ${lg.elided_bytes} bytes not shown …`)}</p>`
          : "";
        const pre = (txt) => `<pre style="max-height:16em;overflow:auto;white-space:pre-wrap">${esc(txt)}</pre>`;
        const logBlock = (s.installed && !s.running && lg.available && ((lg.head || "") + (lg.tail || "")).trim())
          ? `<details style="margin-top:6px"><summary>${esc(t("Why it is not running — last server output"))}</summary>` +
            (lg.head ? pre(lg.head) + gap : "") +
            pre(lg.tail || "") +
            (lg.truncated ? `<p class="muted">${esc(t("Truncated — full log:"))} ${esc(lg.path || "")}</p>` : "") +
            `</details>`
          : "";
        box.innerHTML = `<p class="hint">${esc(parts.join(" · "))} &middot; ${esc(s.base_url || "")}</p>` + logBlock;
        if (!s.installed) {
          if (!installBox) return;
          if (!s.gpu || !s.gpu.available) {
            installBox.style.display = "";
            // States the CONSEQUENCE, not the detection: "no GPU" is said once, at
            // the top of this tab (maintainer review 2026-07-31). What is genuinely
            // needed here is why vLLM is not offered and what serves instead.
            installBox.innerHTML =
              `<p class="muted">${esc(t("vLLM needs a dedicated NVIDIA GPU, so it is not offered on this machine — installing it would put several GB into a backend that could never serve here. Ollama, above, is the path that works: local inference runs on the CPU."))}</p>`;
          } else {
            installBox.style.display = "";
            installBox.innerHTML =
              `<p class="muted">vLLM is not installed. This downloads ${esc(s.estimated_size_note || "several GB")} ` +
              `(vLLM + torch + the CUDA runtime) into a dedicated venv — never the app's own environment.</p>` +
              `<button onclick="installVllm(this)">Install vLLM (${esc(s.verified_version || "")})</button>` +
              `<div id="vllm-install-progress" class="hint" style="margin-top:6px"></div>`;
          }
        } else {
          installBox.style.display = "none";
        }
        const btn = $("vllm-start-btn");
        const canStart = !!(s.installed && s.gpu && s.gpu.available);
        if (btn) {
          btn.disabled = !canStart;
          // A disabled control that does not say WHY is a dead end. The reason is
          // carried in the #oo-tip hover (invariant #17) rather than as a fifth
          // copy of the GPU sentence in the page body.
          btn.title = canStart ? "" : (!s.installed
            ? t("vLLM is not installed.")
            : t("vLLM needs a dedicated NVIDIA GPU — see Hardware at the top of this tab."));
        }
      } catch (e) {
        box.innerHTML = `<p class="muted">Could not read vLLM status.</p>`;
      }
    }

    // The install endpoint answers 409 with a machine-readable detail when the
    // resource preflight WARNS (low RAM / a RAM-backed unpack area). That is a
    // "state the cost, then let the operator decide" refusal, not a dead end --
    // without this the button is unclickable forever on exactly the machines the
    // preflight exists to warn (verified: a 6.03 GB host warns on every click).
    // A BLOCKING refusal (acknowledgeable:false) is never offered an override.
    async function _vllmInstallStart() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        return await api("/api/llm/vllm/install", {method: "POST", body: JSON.stringify({})});
      } catch (e) {
        const d = e && e.detail;
        if (!(e.status === 409 && d && typeof d === "object" && d.acknowledgeable)) throw e;
        const warnings = (d.warnings || []).map(w => "• " + (w.detail || w.check)).join("\n\n");
        const ok = confirm(
          (d.error || t("This machine is below a resource floor for a vLLM install.")) +
          "\n\n" + warnings + "\n\n" +
          t("Install anyway? The download is several GB and cannot be resumed if it fails."));
        if (!ok) return null;
        return await api("/api/llm/vllm/install",
          {method: "POST", body: JSON.stringify({acknowledge_low_resources: true})});
      }
    }

    // Follow a BackgroundJob to its END, reporting every progress line.
    //
    // WHY THIS EXISTS (field report 2026-08-01: "clicking install just changes the
    // button colour, users are left with no information whether the install is
    // really ongoing"): POST-ing a job endpoint only SPAWNS the worker thread and
    // returns at once. A caller that awaits the POST has started the work, not
    // finished it -- so it can neither show progress nor know the outcome. Both
    // multi-GB steps in the setup chain did exactly that.
    //
    // Resolves to the terminal status. Never throws for a job that merely FAILED --
    // the caller must be able to distinguish "failed" from "the poll itself broke",
    // so a failed job returns its status and a broken poll rejects.
    async function _followJob(statusUrl, onDetail) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let misses = 0;
      for (;;) {
        await new Promise((r) => setTimeout(r, 3000));
        let st;
        try {
          st = await api(statusUrl);
          misses = 0;
        } catch (e) {
          // A transient blip must not abandon a job that is still running and
          // still costing the operator bandwidth. Give up only on a sustained
          // outage, and say so rather than silently reporting success.
          if (++misses >= 5) throw new Error(t("Lost contact with the job.") + " " + (e.message || e));
          continue;
        }
        if (onDetail) {
          const line = st.detail || st.state || "";
          if (line) onDetail(line);
        }
        if (st.state && st.state !== "running") return st;
      }
    }

    async function installVllm(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (btn) { btn.disabled = true; btn.textContent = "Starting the install…"; }
      const prog = $("vllm-install-progress");
      const say = (m) => { const el = $("vllm-install-progress") || prog; if (el) el.textContent = m; };
      try {
        // Was `await ensureOnline(...)` with the RESULT DISCARDED -- every sibling
        // call site does `if (!await ...) return;`, so declining the consent here
        // did not stop the install: it carried on to the backend, which refused,
        // and the operator saw "I clicked Stay offline and it tried anyway".
        // Fixed while switching to the egress window (collector stays stopped).
        if (!await ensureAiEgress(t("Install vLLM (downloads several GB over the clear internet)"))) {
          say(t("Install cancelled."));
          return;
        }
        const started = await _vllmInstallStart();
        if (started === null) {  // the operator declined the resource warning
          say(t("Install cancelled."));
          if (btn) { btn.disabled = false; btn.textContent = t("Install vLLM"); }
          return;
        }
        say(t("Installing — this can take several minutes…"));
        await _followJob("/api/llm/vllm/install/status", say);
        loadVllmStatusPanel();
        loadModelCatalog();  // the download button unblocks once vLLM exists
      } catch (e) {
        say("Install: " + e.message);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = t("Install vLLM"); }
      }
    }

    async function startVllm(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const model = ($("vllm-model-input") || {}).value || "";
      const status = $("vllm-action-status");
      if (!model.trim()) { toast(t("Enter a model id first."), "err"); return; }
      if (btn) btn.disabled = true;
      if (status) status.textContent = t("Starting the local AI backend…");
      try {
        await api("/api/llm/vllm/start", {method: "POST", body: JSON.stringify({model: model.trim()})});
        setTimeout(() => { loadVllmStatusPanel(); loadLlmHealth(); }, 3000);
      } catch (e) {
        if (status) status.textContent = "Start: " + e.message;
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function stopVllm(btn) {
      if (btn) btn.disabled = true;
      try {
        await api("/api/llm/vllm/stop", {method: "POST", body: JSON.stringify({})});
        loadVllmStatusPanel();
        loadLlmHealth();
      } catch (e) { toast("Stop: " + e.message, "err"); }
      finally { if (btn) btn.disabled = false; }
    }

    function _llmMethodNote(method) {
      if (!method || !method.parts || method.parts < 2) return "";
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : null;
      const key = method.mode === "hierarchical"
        ? "Hierarchical summary over {n} parts — each part was summarised, then those summaries were summarised together."
        : "Translated in {n} parts — the article was split at paragraph boundaries and every part was translated.";
      const txt = tf ? tf(key, {n: method.parts}) : key.replace("{n}", method.parts);
      return `<div class="card-caveat">${esc(txt)}</div>`;
    }

    async function summarize(id, btn) {
      const cell = btn.parentElement.querySelector(".summary");
      cell.textContent = "Summarizing locally…";
      try {
        const r = await api(`/api/llm/articles/${id}/summarize`,
          {method: "POST", body: JSON.stringify({output_language: _uiLangName(),
            // the UI language CODE drives the native-output directive (remark 13) so a
            // single-article summary comes out in the UI language, like bulk/synthesis.
            ui_lang: (window.OOI18N && OOI18N.current) ? OOI18N.current() : "en"})});
        // LLM output is a model artifact — fluent, and capable of being wrong. Carry a
        // constant verify-against-the-source note (B1 disclosure; auto-translated x12 by
        // the i18n observer). Data is esc()'d (innerHTML).
        cell.innerHTML = `“${esc(r.result)}” <span class="muted">— ${esc(r.model)}</span>`
          + _llmMethodNote(r.method)
          + `<div class="hint muted">Generated by a local model — verify against the stored article.</div>`;
      } catch (e) { cell.textContent = ""; toast("Summarize: " + e.message, "err"); }
      loadLlmHealth();   // success or failure both tell us if Ollama is reachable now
    }

    async function translateArticle(id, btn) {
      const cell = btn.parentElement.querySelector(".summary");
      cell.textContent = "Translating locally…";
      try {
        const r = await api(`/api/llm/articles/${id}/translate`,
          // Default the target to the UI language (remark 13): "translation should be made
          // in the UI language", not always English.
          {method: "POST", body: JSON.stringify({target_language: _uiLangName()})});
        cell.innerHTML = `<span class="muted">[${esc(r.source_language ? ooLangName(r.source_language, r.source_language) : "?")}→${esc(ooLangName(r.target_language, r.target_language))}]</span> `
          + `${esc(r.result)} <span class="muted">— ${esc(r.model)}</span>`
          + _llmMethodNote(r.method)
          + `<div class="hint muted">Generated by a local model — verify against the stored article.</div>`;
      } catch (e) { cell.textContent = ""; toast("Translate: " + e.message, "err"); }
      loadLlmHealth();
    }

    // Framing comparison — moved into Insights, scoped to the explored term.
    // elId lets a second surface (the corpus window's Sentiment sub-tab) REUSE
    // this exact renderer + its English-only VADER disclosure (d.caveat) by
    // pointing it at a fresh host, instead of relocating the Insights DOM.
    async function loadFraming(term, elId) {
      const el = $(elId || "ins-framing");
      el.innerHTML = "<span class='muted'>Comparing how outlets frame this…</span>";
      try {
        const d = await api("/api/framing?query=" + encodeURIComponent(term));
        if (!d.framing || !d.framing.length) {
          el.innerHTML = "<span class='muted'>Not enough coverage to compare framing for this term.</span>"; return;
        }
        const tLoc = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        const rows = d.framing.map(f => {
          // avg_tone is null when VADER could not read this outlet's coverage (it is an
          // ENGLISH lexicon). Render the honest gap -- never 0.00, never "neutral".
          const cls = f.tone_label === 'positive' ? 'ok' : f.tone_label === 'negative' ? 'err' : '';
          const tone = (f.avg_tone != null)
            ? `<span class="pill ${cls}">${esc(f.tone_label || '')} ${f.avg_tone.toFixed(2)}</span>`
            : `<span class="muted" title="${esc(tLoc('VADER is an English lexicon: tone is measured only for English coverage. No tone here means unmeasured — not neutral.'))}">—</span>`;
          return `<tr><td>${esc(f.source)}</td>
               <td>${tone}</td>
               <td class="muted">${f.article_count}</td>
               <td class="muted" style="font-size:12px">${(f.top_terms||[]).slice(0,6).map(esc).join(", ")}</td></tr>`;
        }).join("");
        el.innerHTML = `<table><tr><th>Outlet</th><th>Tone (VADER)</th><th>#</th><th>Emphasised terms</th></tr>${rows}</table>
          <div class="hint">${esc(d.caveat||"")}</div>`;
      } catch (e) {
        el.innerHTML = "<span class='muted'>Framing unavailable (needs the [analysis] extra installed).</span>";
      }
    }

    async function exportEvidence(qArg) {
      const q = (qArg != null ? qArg : $("q").value.trim());
      if (!q) { toast("Enter a search query to scope the evidence bundle.", "err"); return; }
      try {
        const bundle = await api("/api/reports/evidence",
          {method: "POST", body: JSON.stringify({query: q, case_name: q})});
        const blob = new Blob([JSON.stringify(bundle, null, 2)], {type: "application/json"});
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "evidence-bundle.json"; a.click();
        toast(`Signed bundle: ${bundle.manifest.item_count} item(s), verify with scripts/verify_evidence.py`);
      } catch (e) { toast("Evidence export: " + e.message, "err"); }
    }

    // -- Chain of custody --------------------------------------------------- //
    function renderCustodyStatus(s) {
      const id = s.signer || {};
      const trunc = (h) => h ? esc(h.slice(0, 16)) + "…" : "—";
      const pqcPill = s.pqc_effective
        ? '<span class="pill ok">hybrid (Ed25519 + ML-DSA)</span>'
        : (s.pqc_enabled && !s.pqc_available
            ? '<span class="pill warn">requested, library not installed</span>'
            : '<span class="pill">Ed25519 only</span>');
      const otsPill = s.ots_effective
        ? '<span class="pill ok">OpenTimestamps (Bitcoin)</span>'
        : (s.anchoring_mode === "opentimestamps" && !s.ots_available
            ? '<span class="pill warn">requested, library not installed</span>'
            : '<span class="pill">local-only</span>');
      $("custody-status").innerHTML =
        `Signing: ${pqcPill} &nbsp; Timestamps: ${otsPill} &nbsp;` +
        `<span class="pill ${s.key_protection==='aes256gcm-scrypt'?'ok':'warn'}" ` +
        `title="Set OO_KEY_PASSPHRASE to encrypt keys at rest">keys: ${esc(s.key_protection)}</span>` +
        `<div class="muted" style="font-size:12px;margin-top:4px">` +
        `Ed25519 pub ${trunc(id.ed25519_pub)}` +
        (id.ml_dsa_pub ? ` · ${esc(id.ml_dsa_variant)} pub ${trunc(id.ml_dsa_pub)}` : "") + `</div>`;
    }

    function applyCustodyToggles(s) {
      $("cust-pqc").checked = !!s.pqc_enabled;
      $("cust-ots").checked = s.anchoring_mode === "opentimestamps";
      $("cust-autolog").checked = !!s.auto_log_on_ingest;
      $("cust-actor").value = s.default_actor || "";
      $("cust-ots-warn").style.display = $("cust-ots").checked ? "block" : "none";
    }

    async function loadCustody() {
      try {
        const s = await api("/api/custody/settings");
        renderCustodyStatus(s); applyCustodyToggles(s);
      } catch (e) { $("custody-status").textContent = "Custody settings unavailable: " + e.message; }
    }

    async function saveCustody() {
      const body = {
        pqc_enabled: $("cust-pqc").checked,
        anchoring_mode: $("cust-ots").checked ? "opentimestamps" : "local",
        auto_log_on_ingest: $("cust-autolog").checked,
        default_actor: $("cust-actor").value.trim() || null,
      };
      try {
        const s = await api("/api/custody/settings", {method: "PUT", body: JSON.stringify(body)});
        renderCustodyStatus(s); applyCustodyToggles(s);
        if (s.pqc_enabled && !s.pqc_available)
          toast("PQC requested, but the 'pqc' extra is not installed — signing stays Ed25519-only.", "warn");
        else if (s.anchoring_mode === "opentimestamps" && !s.ots_available)
          toast("OpenTimestamps requested, but the 'timestamping' extra is not installed.", "warn");
        else toast("Custody settings saved.");
      } catch (e) { toast(_failMsg("Save failed: {error}", e), "err"); }
    }

    function custItem() {
      const id = $("cust-item").value.trim();
      if (!id) { toast("Enter an item id (e.g. article:42).", "err"); return null; }
      return id;
    }

    async function viewChain() {
      const id = custItem(); if (!id) return;
      try {
        const d = await api("/api/custody/" + encodeURIComponent(id));
        const t = $("cust-entries");
        t.innerHTML = "<tr><th>#</th><th>Action</th><th>Actor</th><th>Time</th><th>Sig</th></tr>" +
          d.entries.map(e =>
            `<tr><td>${e.seq}</td><td>${esc(e.action)}</td><td>${esc(e.actor||"—")}</td>
             <td class="muted" style="font-size:12px">${esc((e.timestamp&&e.timestamp.asserted_time||e.timestamp&&e.timestamp.kind)||"—")}</td>
             <td><span class="pill">${esc(e.signature&&e.signature.algorithm||"?")}</span></td></tr>`).join("");
        $("cust-result").textContent = `${d.entry_count} custody entr${d.entry_count===1?"y":"ies"}.`;
      } catch (e) { $("cust-entries").innerHTML = ""; toast("View chain: " + e.message, "err"); }
    }

    async function verifyChain() {
      const id = custItem(); if (!id) return;
      try {
        const d = await api("/api/custody/" + encodeURIComponent(id) + "/verify");
        $("cust-result").innerHTML = d.verified
          ? '<span class="pill ok">verified</span> chain intact, signatures valid.'
          : '<span class="pill err">FAILED</span> ' + esc((d.issues||[]).join("; "));
      } catch (e) { toast("Verify: " + e.message, "err"); }
    }

    async function exportCustody() {
      const id = $("cust-item").value.trim();
      try {
        const bundle = await api("/api/custody/export" + (id ? "?item_id=" + encodeURIComponent(id) : ""));
        const blob = new Blob([JSON.stringify(bundle, null, 2)], {type: "application/json"});
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "custody-bundle.json"; a.click();
        toast(`Bundle: ${bundle.entry_count} entr${bundle.entry_count===1?"y":"ies"} — verify with scripts/verify_custody.py`);
      } catch (e) { toast("Export: " + e.message, "err"); }
    }

    async function anchorRoot() {
      const root = $("cust-root").value.trim();
      if (!root) { toast("Enter a Merkle root (hex).", "err"); return; }
      const provider = $("cust-ots").checked ? "opentimestamps" : "local";
      try {
        const r = await api("/api/custody/anchor",
          {method: "POST", body: JSON.stringify({merkle_root: root, provider})});
        $("cust-result").innerHTML = `Anchored via <span class="pill ok">${esc(r.provider)}</span> — ${esc(r.detail)}`;
      } catch (e) { toast("Anchor: " + e.message, "err"); }
    }

