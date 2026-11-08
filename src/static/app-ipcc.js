// IPCC AR6 Summaries for Policymakers: the list (local read) and the one click that fetches (egress).
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
      });
    }
    try {
      const d = await api("/api/ipcc/spm");
      host.innerHTML = (d.items || []).map((i) => {
        const when = i.approved ? " · " + esc(_tx("approved")) + " " + esc(i.approved) : "";
        const state = i.stored ? esc(_tx("stored in your corpus")) : esc(_tx("not fetched yet"));
        const btn = i.stored ? "" : `<button type="button" data-ipcc-key="${esc(i.key)}"
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
      await api("/api/ipcc/spm/" + encodeURIComponent(key) + "/fetch",
        {method: "POST", body: JSON.stringify({consent: true})});
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

  window.loadIpccSpm = loadIpccSpm;
  window.ipccFetch = ipccFetch;
})();
