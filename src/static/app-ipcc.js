// IPCC AR6 Summaries for Policymakers: the list (local read), the one click that fetches (egress), and the
// operator-curated suggested predictions of a stored report (local reads and writes, row 121).
// Open Omniscience - GPL-3.0-or-later. The list read makes no request and is NOT consent-gated; the
// fetch passes the ONE network consent (invariant #14) and sends consent:true, because the endpoint
// refuses without it (#14f). No inline handlers: the list is delegated from #ipcc-list.
(function () {
  "use strict";
  let _wired = false;
  function _tx(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }

  async function loadIpccSpm() {
    const host = document.getElementById("ipcc-list");
    if (!host) return;
    if (!_wired) {
      _wired = true;
      host.addEventListener("click", (ev) => {
        const b = ev.target.closest("button[data-ipcc-key]");
        if (b) ipccFetch(b.getAttribute("data-ipcc-key"));
        const p = ev.target.closest("button[data-ipcc-pred]");
        if (p) loadIpccPredictions(p.getAttribute("data-ipcc-pred"));
      });
    }
    try {
      const d = await api("/api/ipcc/spm");
      host.innerHTML = (d.items || []).map((i) => {
        const when = i.approved ? " · " + esc(_tx("approved")) + " " + esc(i.approved) : "";
        const state = i.stored ? esc(_tx("stored in your corpus")) : esc(_tx("not fetched yet"));
        const btn = i.stored ? `<button type="button" data-ipcc-pred="${esc(i.key)}"
          title="${esc(_tx("Reads the copy in your corpus; nothing is sent anywhere."))}">${esc(_tx("Suggested predictions"))}</button>` : `<button type="button" data-ipcc-key="${esc(i.key)}"
          title="${esc(_tx("Sends one request to www.ipcc.ch. Refused while airplane mode is on."))}">${esc(_tx("Fetch from IPCC"))}</button>`;
        return `<div class="row" style="align-items:center;gap:8px;margin-top:6px"><div style="flex:1 1 auto"><strong>${esc(i.title)}</strong>
          <span class="muted">${esc(i.working_group)}${when} · ${state}</span></div><div style="flex:0 0 auto">${btn}</div></div>`;
      }).join("");
    } catch (e) {
      host.textContent = _tx("IPCC list failed:") + " " + e.message;
    }
  }

  async function ipccFetch(key) {
    const t = _tx;
    const st = document.getElementById("ipcc-status");
    // The ONE consent (invariant #14); its answer is USED.
    if (typeof ensureOnline === "function"
        && !await ensureOnline(t("Fetch an IPCC report from www.ipcc.ch (one request, over your transport)"))) return;
    if (st) st.textContent = t("Fetching in the background…");
    try {
      const started = await api("/api/ipcc/spm/" + encodeURIComponent(key) + "/fetch",
        {method: "POST", body: JSON.stringify({consent: true})});
      // The job kind is one singleton: a refused start is ANOTHER report's run, never this click's answer.
      if (started && started.started === false) {
        if (st) st.textContent = t("Another IPCC fetch is already running; try again when it finishes.");
        return;
      }
      const job = await pollJobStatus("/api/ipcc/spm/status");
      if (job.state === "error") {
        if (st) st.textContent = t("IPCC fetch failed:") + " " + (job.error || "");
        return;
      }
      if (_jobStillRunning(job)) {
        if (st) st.textContent = t("Still running in the background — check the task manager for the result.");
        return;
      }
      const r = job.result || {};
      if (st) st.textContent = t("IPCC report:") + " " + t(r.status || "") + (r.reason ? " — " + r.reason : "");
      loadIpccSpm();
    } catch (e) {
      if (st) st.textContent = t("IPCC fetch failed:") + " " + e.message;
    }
  }

  // Row 121 (G4): the app SUGGESTS sentences by their wording, the operator DECIDES. Local reads and writes only.
  let _predKey = null, _predData = null, _predFilter = "all", _predWired = false;

  async function loadIpccPredictions(key) {
    const panel = document.getElementById("ipcc-pred");
    if (!panel) return;
    if (!_predWired) {
      _predWired = true;
      panel.addEventListener("click", (ev) => {
        const b = ev.target.closest("button[data-ipcc-decide]");
        if (b) ipccDecide(b.getAttribute("data-ipcc-hash"), b.getAttribute("data-ipcc-decide"), b.hasAttribute("data-ipcc-orphan"));
      });
      panel.addEventListener("change", (ev) => {
        if (ev.target && ev.target.id === "ipcc-pred-filter") { _predFilter = ev.target.value; _renderPredictions(); }
      });
    }
    _predKey = key;
    panel.innerHTML = `<div class="muted">${esc(_tx("Loading…"))}</div>`;
    try {
      _predData = await api("/api/ipcc/spm/" + encodeURIComponent(key) + "/predictions");
      _renderPredictions();
    } catch (e) {
      panel.textContent = _tx("Suggested predictions failed:") + " " + e.message;
    }
  }

  function _decisionLabel(d) {
    if (d === "kept") return _tx("kept as a prediction");
    if (d === "set_aside") return _tx("set aside");
    return _tx("not decided yet");
  }

  function _renderPredictions() {
    const view = document.getElementById("ipcc-pred");
    const d = _predData;
    if (!view || !d) return;
    const c = d.counts || {};
    const head = `<h3 style="margin:0;font-size:13px">${esc(_tx("Suggested predictions"))} <span class="muted">&mdash; ${esc(d.title || "")}</span></h3>
      <p class="card-caveat" style="margin-top:6px">${esc(_tx(d.caveat || ""))}</p>
      <details style="margin-top:4px"><summary class="hint">${esc(_tx("How sentences are suggested"))}</summary>
        <p class="hint">${esc(_tx(d.method || ""))}</p></details>`;
    if (!d.stored) {
      view.innerHTML = head + `<p class="hint">${esc(_tx("This report is not stored in your corpus yet: fetch it first."))}</p>`;
      return;
    }
    const reader = d.article_id != null
      ? ` · <a href="/api/articles/${encodeURIComponent(d.article_id)}/view" target="_blank" rel="noopener">${esc(_tx("open the report in the reader"))}</a>` : "";
    const tooLong = c.too_long ? ` · ${esc(_tx("passages too long to be one sentence (a table or figure), not shown:"))} ${esc(c.too_long)}` : "";
    const counts = `<p class="hint" style="margin-top:6px">${esc(_tx("suggested:"))} ${esc(c.suggested)} · ${esc(_tx("kept:"))} ${esc(c.kept)}
      · ${esc(_tx("set aside:"))} ${esc(c.set_aside)} · ${esc(_tx("not decided yet:"))} ${esc(c.undecided)}${tooLong}${reader}</p>`;
    const opt = (v, label) => `<option value="${v}"${_predFilter === v ? " selected" : ""}>${esc(_tx(label))}</option>`;
    const filter = `<label class="hint">${esc(_tx("Show"))} <select id="ipcc-pred-filter">${opt("all", "all suggestions")}${opt("undecided", "not decided yet")}${opt("kept", "kept as a prediction")}${opt("set_aside", "set aside")}</select></label>`;
    const want = (dec) => _predFilter === "all" || (_predFilter === "undecided" ? !dec : dec === _predFilter);
    const btn = (h, value, label, on, orphan) => `<button type="button" data-ipcc-hash="${esc(h)}" data-ipcc-decide="${value}"${orphan ? " data-ipcc-orphan" : ""} aria-pressed="${on ? "true" : "false"}">${esc(_tx(label))}</button>`;
    const row = (i) => {
      const cues = [].concat((i.cues || {}).likelihood || [], (i.cues || {}).confidence || [], (i.cues || {}).future || []);
      const undo = i.decision ? btn(i.hash, "undecided", "Undo", false) : "";
      return `<li style="margin-top:8px"><div>&ldquo;${esc(i.sentence)}&rdquo;</div>
        <div class="muted" title="${esc(_tx("The words that made the app suggest this sentence."))}">${esc(_tx("matched:"))} ${esc(cues.join(" · "))} · ${esc(_decisionLabel(i.decision))}</div>
        <div class="row" style="gap:6px;margin-top:4px">${btn(i.hash, "kept", "Keep as a prediction", i.decision === "kept")}${btn(i.hash, "set_aside", "Set aside", i.decision === "set_aside")}${undo}</div></li>`;
    };
    const shown = (d.items || []).filter((i) => want(i.decision));
    const list = shown.length ? `<ol style="padding-left:18px">${shown.map(row).join("")}</ol>`
      : `<p class="hint">${esc(_tx("Nothing to show under this choice."))}</p>`;
    const orphans = (d.not_suggested_now || []).filter((o) => want(o.decision));
    const orphanList = orphans.length ? `<h4 style="margin:10px 0 0;font-size:12px">${esc(_tx("Decided earlier, no longer suggested by this method"))}</h4>
      <ul style="padding-left:18px">${orphans.map((o) => `<li style="margin-top:6px"><div>&ldquo;${esc(o.sentence)}&rdquo;</div>
        <div class="muted">${esc(_decisionLabel(o.decision))}</div><div class="row" style="gap:6px;margin-top:4px">${btn(o.hash, "kept", "Keep as a prediction", o.decision === "kept")}${btn(o.hash, "set_aside", "Set aside", o.decision === "set_aside")}${btn(o.hash, "undecided", "Undo", false, true)}</div></li>`).join("")}</ul>` : "";
    view.innerHTML = head + counts + `<div id="ipcc-pred-msg" class="hint" role="status" aria-live="polite"></div>` + filter + list + orphanList;
  }

  async function ipccDecide(hash, decision, orphan) {
    if (!_predKey || !hash) return;
    // A sentence this method no longer suggests cannot be decided on again once its decision is gone: say so first.
    if (orphan && decision === "undecided"
        && !window.confirm(_tx("This sentence is no longer suggested, so once removed it cannot be kept again. Remove your decision?"))) return;
    const note = document.getElementById("ipcc-pred-msg") || document.getElementById("ipcc-status");
    try {
      await api("/api/ipcc/spm/" + encodeURIComponent(_predKey) + "/predictions/decide",
        {method: "POST", body: JSON.stringify({sentence_hash: hash, decision: decision})});
      await loadIpccPredictions(_predKey);
    } catch (e) {
      if (note) note.textContent = _tx("Saving the decision failed:") + " " + e.message;
    }
  }

  window.loadIpccSpm = loadIpccSpm;
  window.loadIpccPredictions = loadIpccPredictions;
  window.ipccFetch = ipccFetch;
})();
