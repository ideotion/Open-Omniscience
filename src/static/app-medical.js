// The medical lane (S07-01; R745, R750): what medical.db holds (local read) and the one click that fetches PubMed
// update files (egress). Open Omniscience - GPL-3.0-or-later. The status read makes no request and is NOT
// consent-gated; the fetch passes the ONE network consent (invariant #14) and sends consent:true, because the
// endpoint refuses without it (#14f). The gap is stated by the page itself and the count of cited papers NOT
// found is drawn beside the found ones (R750): a paper missing here is never presented as missing from PubMed.
(function () {
  "use strict";
  let _wired = false;
  function _t(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }
  function _tf(s, v) {
    if (window.OOI18N && OOI18N.tf) return OOI18N.tf(s, v);
    return s.replace(/\{(\w+)\}/g, (_m, k) => (k in v ? String(v[k]) : _m));
  }

  function _countsHtml(d) {
    const c = d.coverage || {};
    const k = d.by_class || {};
    const lines = [];
    lines.push(_tf("Your articles cite {cited} papers: {found} found, {missing} not found yet.",
      {cited: c.cited || 0, found: c.cited_found || 0, missing: c.cited_not_found || 0}));
    if (c.named) {
      lines.push(_tf("You named {named} papers: {found} found, {missing} not found yet.",
        {named: c.named, found: c.named_found || 0, missing: c.named_not_found || 0}));
    }
    lines.push(_tf("Kept: {papers} records ({journal} journal, {preprint} preprint, {retracted} retracted; {withdrawn} withdrawn).",
      {papers: d.papers || 0, journal: k.journal || 0, preprint: k.preprint || 0, retracted: k.retracted || 0,
       withdrawn: d.withdrawn || 0}));
    lines.push(d.last_file
      ? _tf("Newest file applied: {name}.", {name: d.last_file.name})
      : _t("No update file applied yet."));
    return lines.map((l) => `<div>${esc(l)}</div>`).join("");
  }

  async function loadMedical() {
    const host = document.getElementById("medical-counts");
    if (!host) return;
    if (!_wired) {
      _wired = true;
      const b = document.getElementById("medical-fetch-btn");
      if (b) b.addEventListener("click", medicalFetch);
    }
    try {
      const d = await api("/api/medical/status");
      host.innerHTML = _countsHtml(d);
      const inp = document.getElementById("medical-files");
      if (inp && d.max_files) inp.max = String(d.max_files);
    } catch (e) {
      host.textContent = _t("Medical papers status failed:") + " " + e.message;
    }
  }

  async function medicalFetch() {
    const t = _t;
    const st = document.getElementById("medical-status");
    const inp = document.getElementById("medical-files");
    const files = Math.max(1, Math.min(30, parseInt(inp && inp.value, 10) || 7));
    // The ONE consent (invariant #14); its answer is USED.
    if (typeof ensureOnline === "function"
        && !await ensureOnline(t("Fetch PubMed update files from ftp.ncbi.nlm.nih.gov (tens of megabytes each, over your transport)"))) return;
    if (st) st.textContent = t("Fetching in the background…");
    try {
      const started = await api("/api/medical/fetch",
        {method: "POST", body: JSON.stringify({consent: true, files: files})});
      if (started && started.started === false) {
        if (st) st.textContent = t("A PubMed fetch is already running; try again when it finishes.");
        return;
      }
      const job = await pollJobStatus("/api/medical/fetch/status");
      if (job.state === "error") {
        if (st) st.textContent = t("PubMed fetch failed:") + " " + (job.error || "");
        return;
      }
      if (_jobStillRunning(job)) {
        if (st) st.textContent = t("Still running in the background — check the task manager for the result.");
        return;
      }
      const r = job.result || {};
      const applied = (r.applied || []).length;
      let msg = _tf("Applied {applied} files; {remaining} listed files not applied yet.",
        {applied: applied, remaining: r.remaining || 0});
      if (r.failed) {
        msg += " " + (r.failed.error === "airplane_mode"
          ? t("Stopped: airplane mode is on.")
          : _tf("Stopped at {file}: {error}", {file: r.failed.file, error: r.failed.reason || r.failed.error}));
      } else if (r.stopped || job.state === "cancelled") {
        msg += " " + t("Stopped before the end, as asked.");
      }
      if (st) st.textContent = msg;
      loadMedical();
    } catch (e) {
      if (st) st.textContent = t("PubMed fetch failed:") + " " + e.message;
    }
  }

  window.loadMedical = loadMedical;
  window.medicalFetch = medicalFetch;
})();
