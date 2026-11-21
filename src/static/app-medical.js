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
    const cov = d.coverage || {};
    const k = d.by_class || {};
    const lines = [];
    lines.push(_tf("Your articles cite {cited} paper identifiers (PMID, DOI or PMCID): {found} found, {missing} not found yet.",
      {cited: cov.cited || 0, found: cov.cited_found || 0, missing: cov.cited_not_found || 0}));
    if (cov.named) {
      lines.push(_tf("You named {named} paper identifiers: {found} found, {missing} not found yet.",
        {named: cov.named, found: cov.named_found || 0, missing: cov.named_not_found || 0}));
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
    const countsEl = document.getElementById("medical-counts");
    if (!countsEl) return;
    if (!_wired) {
      _wired = true;
      const b = document.getElementById("medical-fetch-btn");
      if (b) b.addEventListener("click", medicalFetch);
    }
    try {
      const d = await api("/api/medical/status");
      countsEl.innerHTML = _countsHtml(d);
      const inp = document.getElementById("medical-files");
      if (inp && d.max_files) inp.max = String(d.max_files);
    } catch (e) {
      countsEl.textContent = _t("Medical papers status failed:") + " " + e.message;
    }
  }

  async function medicalFetch() {
        const statusEl = document.getElementById("medical-status");
    const inp = document.getElementById("medical-files");
    const files = Math.max(1, Math.min(30, parseInt(inp && inp.value, 10) || 7));
    // The ONE consent (invariant #14); its answer is USED.
    if (typeof ensureOnline === "function"
        && !await ensureOnline(_t("Fetch PubMed update files from ftp.ncbi.nlm.nih.gov (tens of megabytes each, over your transport)"))) return;
    if (statusEl) statusEl.textContent = _t("Fetching in the background…");
    try {
      const started = await api("/api/medical/fetch",
        {method: "POST", body: JSON.stringify({consent: true, files: files})});
      if (started && started.started === false) {
        if (statusEl) statusEl.textContent = _t("A PubMed fetch is already running; try again when it finishes.");
        return;
      }
      const job = await pollJobStatus("/api/medical/fetch/status");
      if (job.state === "error") {
        if (statusEl) statusEl.textContent = _t("PubMed fetch failed:") + " " + (job.error || "");
        return;
      }
      if (_jobStillRunning(job)) {
        if (statusEl) statusEl.textContent = _t("Still running in the background — check the task manager for the result.");
        return;
      }
      const r = job.result || {};
      if (r.stopped && r.listed == null) {
        // Stopped during the corpus scan: nothing was asked of NLM and the last counts stand.
        if (statusEl) statusEl.textContent = _t("Stopped before the end, as asked.");
        return;
      }
      const applied = (r.applied || []).length;
      let msg = _tf("Applied {applied} files; {remaining} listed files not applied yet.",
        {applied: applied, remaining: r.remaining || 0});
      if (r.failed) {
        msg += " " + (r.failed.error === "airplane_mode"
          ? _t("Stopped: airplane mode is on.")
          // R768/R769: stopped by a transport change, the server's fixed sentence
          : (r.failed.error === "protected_mode" || r.failed.error === "protected_mode_off" || r.failed.error === "settings_unreadable")
          ? _t(r.failed.reason || "")
          : _tf("Stopped at {file}: {error}. Files are applied in NLM's order, so this one is tried again first next time.",
              {file: r.failed.file, error: r.failed.reason || r.failed.error}));
      }
      if (r.stopped) {
        msg += " " + _t("Stopped before the end, as asked.");
      }
      if (statusEl) statusEl.textContent = msg;
      loadMedical();
    } catch (e) {
      if (statusEl) statusEl.textContent = _t("PubMed fetch failed:") + " " + e.message;
    }
  }

  // ---- The Papers subtab of the analysis (S07-01 S1): papers BESIDE the news, never blended into it.
  // A local read (no request, no consent needed): the analysed articles' own links, matched against
  // medical.db. Every paper shows its provenance class as a badge, and a retraction, an erratum or an
  // expression of concern as its own badge; the no-medical-advice line and the gap are visible by
  // default, never behind a toggle. A paper not kept here is counted, never listed (R750).
  const _CLASS_LABEL = {journal: "Journal record", preprint: "Preprint", retracted: "Retracted"};
  const _CLASS_HOVER = {
    journal: "PubMed indexes this record as a journal publication. Peer review is the journal's claim; this app does not check it. Not retracted in this copy of the record: a retraction recorded later may not be in it yet.",
    preprint: "A preprint: not peer reviewed. PubMed lists it, which is not an endorsement.",
    retracted: "The PubMed record says this paper was retracted. Read it as retracted, whatever the articles citing it say.",
  };
  const _NOTICE_LABEL = {erratum: "Erratum published", concern: "Expression of concern", retraction: "Retraction notice"};
  let _papersSeq = 0;

  function _badge(text, cls, hover) {
    const ti = hover ? ` title="${esc(_t(hover))}"` : "";
    return `<span class="pill med-badge med-${esc(cls)}"${ti}>${esc(_t(text))}</span>`;
  }

  function _paperHtml(p, i) {
    const badges = [_badge(_CLASS_LABEL[p.provenance_class] || p.provenance_class, p.provenance_class,
      _CLASS_HOVER[p.provenance_class])];
    (p.notices || []).forEach((n) => { if (_NOTICE_LABEL[n]) badges.push(_badge(_NOTICE_LABEL[n], "notice-" + n)); });
    if (p.withdrawn) badges.push(_badge("Withdrawn from PubMed", "withdrawn"));
    const ids = [`PMID ${p.pmid}`];
    if (p.doi) ids.push(`DOI ${p.doi}`);
    if (p.pmcid) ids.push(p.pmcid);
    const meta = [p.journal, p.pub_date].filter(Boolean).map(esc).join(" · ");
    const since = p.retracted_seen_at
      ? `<div class="card-caveat">${esc(_tf("Retracted in this install's copy since {date}.", {date: ooIsoDate(p.retracted_seen_at)}))}</div>`
      : "";
    const title = p.title || p.vernacular_title || _t("(no title in the record)");
    return `<div class="med-paper" style="padding:8px 0;border-bottom:1px solid var(--line)">
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">${badges.join("")}</div>
      <div style="margin-top:4px;font-weight:600">${esc(title)}</div>
      <div class="muted">${meta}${meta ? " · " : ""}${esc(ids.join(" · "))}</div>${since}
      <div class="hint" style="margin-top:2px">${esc(_tf("Cited by {n} of the analysed articles.", {n: p.cited_by}))}
        <button type="button" class="linkish" data-med-open="${i}">${esc(_t("Open the citing articles"))}</button></div>
    </div>`;
  }

  async function renderAnPapers(params) {
    const papersEl = document.getElementById("an-papers");
    if (!papersEl || !params) return;
    const seq = ++_papersSeq;
    papersEl.innerHTML = `<div class="muted">${esc(_t("Loading…"))}</div>`;
    let res;
    try {
      res = await api("/api/medical/corpus-papers?" + params.toString());
    } catch (e) {
      if (seq === _papersSeq) papersEl.textContent = _t("Medical papers failed:") + " " + e.message;
      return;
    }
    if (seq !== _papersSeq) return;  // a newer analysis superseded this one
    const parts = [];
    parts.push(`<p class="card-caveat" style="margin-top:0">${esc(_t("This app never gives medical advice. A paper listed here is one your articles link to, not a recommendation."))}</p>`);
    parts.push(`<p class="hint" style="margin-top:0">${esc(_t("Shown beside the news, never mixed into it. Each badge is the class the PubMed record states; peer review is the journal's claim and is not checked here."))}</p>`);
    parts.push(`<div>${esc(_tf("{citing} of {n} analysed articles cite {cited} paper identifiers: {found} found here, {missing} not found yet.",
      {citing: res.articles_citing || 0, n: res.n_articles || 0, cited: res.cited || 0, found: res.found || 0, missing: res.not_found || 0}))}</div>`);
    if (res.capped) parts.push(`<div class="hint">${esc(_tf("Only the first {n} articles were read.", {n: res.n_articles || 0}))}</div>`);
    parts.push(`<p class="card-caveat">${esc(_t("Only papers NLM revised recently are in the update files, so most papers your articles cite will not be found yet. A paper not found here is not missing from PubMed."))}</p>`);
    parts.push(`<div class="hint">${esc(res.last_file
      ? _tf("Newest file applied: {name}.", {name: res.last_file.name}) + (res.last_file.finished_at ? " (" + ooIsoDate(res.last_file.finished_at) + ")" : "")
      : _t("No update file applied yet."))}</div>`);
    const papers = res.papers || [];
    if (!res.cited) {
      parts.push(`<div class="muted" style="margin-top:8px">${esc(_t("No paper identifier found in these articles' links."))}</div>`);
    } else if (!papers.length) {
      parts.push(`<div class="muted" style="margin-top:8px">${esc(_t("None of the cited papers is kept yet. Fetch PubMed update files in Advanced, Medical papers."))}</div>`);
    } else {
      parts.push(`<div style="margin-top:8px">${papers.map(_paperHtml).join("")}</div>`);
    }
    papersEl.innerHTML = parts.join("");
    papersEl.querySelectorAll("[data-med-open]").forEach((b) => b.addEventListener("click", () => {
      const p = papers[+b.getAttribute("data-med-open")];
      if (p && typeof openAnalysisForIds === "function") {
        openAnalysisForIds(p.article_ids, _t("Citing") + " PMID " + p.pmid);
      }
    }));
  }

  window.loadMedical = loadMedical;
  window.medicalFetch = medicalFetch;
  window.renderAnPapers = renderAnPapers;
})();
