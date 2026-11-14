/* app-maintenance.js — the Maintenance section of Settings → Advanced (R196)

   The quarantine DRY RUN and the two reports that sit beside it, readable without curl.
   Everything here rides the EXISTING loopback routes under /api/quarantine; nothing
   was added server-side.

   DRY RUN ONLY (ruled 2026-10-26, R196 point 2). The panel starts a run with
   write=false and never builds a URL that says otherwise: applying a result stays a
   deliberate API/CLI act until the maintainer has read the counts and samples and
   ruled. Pinned by tests/test_maintenance_panel.py.

   HONESTY. Counts are CANDIDATES under rules fitted to few specimens, never an error
   rate and never a verdict on a source. "Different site" and "site could not be read"
   are separate rows: unknown is not a mismatch. A sample is titles and URLs only, with
   the local reader first (invariant #6); the outbound URL is not linked from here.

   The renderers are pure (payload, t, tf) -> HTML so node can drive them
   (tests/maintenance_node_test.js); only the load and maint functions touch the DOM, and
   every request is to this machine.
*/
    let _maintPoll = null;
    let _maintStatus = null;
    const _MAINT_SIGNALS = ["host_mismatch", "host_confirmed"];

    // The tally keys the job writes, in the order a reader meets them. A key outside this
    // table is shown as the job sent it, never mapped onto the nearest known word.
    function _maintTallyLabel(key, t, tf) {
      const known = {
        "scanned": t("Articles scanned"),
        "quarantined": t("Candidates found"),
        "already_quarantined": t("Already quarantined"),
        "newly_written": t("Newly written"),
        "host:mismatch": t("Stored on a different site than its source"),
        "host:confirmed": t("Different site, confirmed by you"),
        "host:unknown": t("Site could not be read (not counted as different)"),
      };
      if (known[key]) return known[key];
      if (key.indexOf("reason:") === 0) return tf(t("Rule: {name}"), { name: key.slice(7) });
      return key;
    }

    // The job's state word in the user's language. A state this panel has no word for is shown as the
    // job sent it, never mapped onto the nearest known word (the same rule as the tally keys).
    function _maintStateLabel(state, t) {
      const known = {
        "running": t("running"),
        "paused": t("paused"),
        "done": t("done"),
        "error": t("error"),
        "cancelled": t("cancelled"),
      };
      return Object.prototype.hasOwnProperty.call(known, state) ? known[state] : String(state);
    }

    // A sentence the server wrote. It arrives in English whatever the page's language, so it is
    // shown as sent, in its own left-to-right span, behind a small visible label saying so (R289).
    function _maintServerTextHtml(text, t) {
      return ooLabelHtml(esc(t("Server text, in English")), `<span lang="en" dir="ltr">${esc(text)}</span>`);
    }

    // The server names WHAT its method and note sentences mean with a stable key beside the English
    // (R289's proposal, built under R665): the page says that meaning in the reader's language, in
    // plain words. A key is bumped (.v2) only when the meaning changes, so a key this page does not
    // know (a newer server) falls back to the English as sent, labelled. Never a match on the English
    // text itself: that would break silently the day the server's wording moves.
    function _maintKeyedText(key, d, t, tf) {
      switch (key) {
        case "maintenance.samples.v1":
          return t("These are a few of the articles the rules picked in the last run, always the same ones for the same corpus. They let you check what the rules catch; they do not say how often the rules are wrong, and they judge no article. Only titles and addresses are shown.");
        case "maintenance.raw_ids.v1":
          return t("A source is listed when its whole name is a Wikidata code (such as Q11858063). This only reads what is on your computer: nothing is downloaded, renamed or marked. The lowest source numbers come first (not the largest sources), and each article count includes quarantined articles.");
        case "maintenance.furniture.v1":
          if (typeof (d && d.sampled) !== "number" || typeof (d && d.min_share) !== "number") return null;
          return tf(t("Read from the {n} newest articles of this source, not a random choice, so a recent change of page layout weighs more than an old one. A line is listed when it has 12 words or fewer and appears in at least {percent}% of the non-empty articles read, and in 3 of them or more. Lines marked “already stripped by the rules” are taken out of the articles already. This only reads what is on your computer: nothing is marked or removed."),
            { n: fmtNum(d.sampled), percent: fmtNum(Math.round(d.min_share * 1000) / 10) });  // one decimal: 0.335 reads 33.5, never rounded up to 34
        case "maintenance.host_not_measured.v1":
          return t("This run did not compare sites (tick “Also compare each article's site with its source's site” before you start it). These counts were not measured, which is not the same as zero.");
        case "maintenance.host_fact.v1":
          return t("An article stored on another site than its source's own is a fact about where it lives, not a judgement: it may be a shared story, a redirect or a news-agency feed. Nothing is marked for it, even with writing on. Articles whose site could not be read are counted apart, never as a different site.");
        default:
          return null;
      }
    }
    // The method line under a report: the keyed sentence when this page knows the key, else the
    // server's English, labelled. Nothing when the server sent neither.
    function _maintMethodHtml(d, t, tf) {
      const said = _maintKeyedText(d && d.method_key, d, t, tf);
      if (said) return `<div class="hint">${esc(said)}</div>`;
      return (d && d.method) ? `<div class="hint">${_maintServerTextHtml(String(d.method), t)}</div>` : "";
    }
    // A signal's note, the same way (it used to print the English unlabelled).
    function _maintNoteHtml(s, t, tf) {
      const said = _maintKeyedText(s && s.note_key, s, t, tf);
      if (said) return `<div class="hint">${esc(said)}</div>`;
      return (s && s.note) ? `<div class="hint">${_maintServerTextHtml(String(s.note), t)}</div>` : "";
    }

    function maintRunHtml(st, t, tf) {
      if (!st || !st.state || st.state === "idle") {
        return `<div class="hint">${esc(t("No run since this app started."))}</div>`;
      }
      const crit = [
        st.include_stubs ? t("stub pages counted") : null,
        st.include_host_mismatch ? t("sites compared") : null,
        st.dry_run ? t("dry run: nothing was written") : t("this run was started with writing on"),
      ].filter(Boolean).join(" · ");
      const prog = (typeof st.articles_total === "number" && st.articles_total > 0)
        ? ` · ${esc(tf(t("{done} of {total} articles read"), { done: fmtNum(st.articles_done || 0), total: fmtNum(st.articles_total) }))}`
        : "";
      const err = st.error ? `<div class="card-caveat">${_maintServerTextHtml(String(st.error), t)}</div>` : "";
      return `<div><b>${esc(t("State"))}:</b> ${esc(_maintStateLabel(st.state, t))}${prog}</div>`
        + `<div class="hint">${esc(crit)}</div>${err}`;
    }

    // One row per tally key, label first and the count after it. Zero is a measurement
    // and is shown; a signal the run did not ask for is simply absent from the tally.
    function maintTallyHtml(tally, t, tf) {
      const keys = Object.keys(tally || {});
      if (!keys.length) return "";
      const order = (k) => (k === "scanned" ? 0 : k === "quarantined" ? 1 : k.indexOf("reason:") === 0 ? 2 : k.indexOf("host:") === 0 ? 3 : 4);
      keys.sort((a, b) => order(a) - order(b) || (a < b ? -1 : 1));
      const rows = keys.map((k) =>
        `<tr><td>${esc(_maintTallyLabel(k, t, tf))}</td><td class="num">${esc(fmtNum(tally[k]))}</td></tr>`).join("");
      return `<table class="maint-tally"><tbody>${rows}</tbody></table>`
        + `<div class="hint">${esc(t("A rule with no candidate is not listed: that means zero, not unmeasured."))}</div>`;
    }

    // A sample row: the title opens the LOCAL reader (invariant #6). The stored URL is
    // shown as text, not as a link: opening the original goes through the link preview
    // (invariants #6/#7), which this page does not duplicate.
    function maintSampleRowHtml(r, t, tf) {
      if (r.present === false) return `<li class="hint">${esc(tf(t("Article {id} is no longer stored."), { id: r.id }))}</li>`;
      const title = r.title || t("(no title)");
      const bits = [];
      if (r.already_marked) bits.push(esc(t("already quarantined")));
      if (r.source_site || r.article_site) {
        bits.push(esc(tf(t("source site {a} · stored on {b}"), { a: "\u2068" + (r.source_site || "?") + "\u2069", b: "\u2068" + (r.article_site || "?") + "\u2069" })));
      }
      if (r.state === "confirmed") bits.push(esc(t("confirmed by you")));
      return `<li><a href="/api/articles/${encodeURIComponent(r.id)}/view" target="_blank" rel="noopener" dir="auto">${esc(title)}</a>`
        + (bits.length ? ` <span class="hint">— ${bits.join(" · ")}</span>` : "")
        + maintPairButtonHtml(r, t)
        + `<div class="hint" dir="ltr">${esc(r.url || "")}</div></li>`;
    }

    // One small button beside a host-mismatch sample (R193): "this source really publishes on that
    // site", or its withdrawal once confirmed. The pair travels in data attributes and is read back
    // by one delegated listener; a row without a source number or a readable site gets no button.
    function maintPairButtonHtml(r, t) {
      if (!(r && r.source_id >= 1 && r.article_site)) return "";
      const confirmed = r.state === "confirmed";
      // A confirm needs the two sites known and different; a withdraw needs only the pair itself.
      if (!confirmed && !(r.source_site && r.article_site !== r.source_site)) return "";
      const act = confirmed ? "withdraw" : "confirm";
      const label = confirmed ? t("Withdraw") : t("Confirm site");
      const tip = confirmed
        ? t("Count this site as different again in the next dry run.")
        : t("This source really publishes on that site: count it as “confirmed by you” in the next dry run. Nothing is marked or removed.");
      return ` <button type="button" class="secondary" data-maint-pair="${act}" data-source="${esc(String(r.source_id))}"`
        + ` data-site="${esc(r.article_site)}" title="${esc(tip)}">${esc(label)}</button>`;
    }

    // Every pair you confirmed, with when and the note as typed, each withdrawable. The caveat line is
    // visible (R685): a confirmation changes how the next dry run counts the pair, and nothing else.
    function maintPairsHtml(d, t, tf) {
      const rows = (d && d.rows) || [];
      const cav = `<div class="card-caveat">${esc(t("A confirmed site is counted as “confirmed by you” in the next dry run instead of as a different site. Nothing is marked or removed."))}</div>`;
      if (!rows.length) return `<div class="hint">${esc(t("No site confirmed yet. Confirm one from a host-mismatch sample above."))}</div>` + cav;
      const body = rows.map((r) =>
        `<tr><td class="num">${esc(String(r.source_id))}</td><td dir="ltr">${esc(r.article_site)}</td>`
        + `<td>${esc(ooIsoDate(r.confirmed_at || "?"))}</td><td dir="auto">${esc(r.note || "")}</td>`
        + `<td>${maintPairButtonHtml({ source_id: r.source_id, article_site: r.article_site, state: "confirmed" }, t)}</td></tr>`).join("");
      return `<div>${esc(tf(t("{n} confirmed"), { n: fmtNum(d.confirmed != null ? d.confirmed : rows.length) }))}</div>`
        + `<table class="maint-tally"><thead><tr><th>${esc(t("Source number"))}</th><th>${esc(t("Site"))}</th><th>${esc(t("Confirmed"))}</th><th>${esc(t("Note"))}</th><th></th></tr></thead>`
        + `<tbody>${body}</tbody></table>` + cav;
    }

    function maintSamplesHtml(data, t, tf) {
      const sigs = (data && data.signals) || {};
      const names = Object.keys(sigs);
      if (!names.length) return `<div class="hint">${esc(t("No sample is held yet. Start a dry run first."))}</div>`;
      const parts = names.map((sig) => {
        const s = sigs[sig];
        const head = (s.candidates == null)
          ? esc(t("not measured in this run"))
          : esc(tf(t("{shown} shown of {n} candidates"), { shown: fmtNum(s.shown || 0), n: fmtNum(s.candidates) }));
        const note = _maintNoteHtml(s, t, tf);
        const rows = (s.rows || []).map((r) => maintSampleRowHtml(r, t, tf)).join("");
        return `<h4 class="lib-sub"><span dir="ltr">${esc(sig)}</span> — ${head}</h4>${note}<ul class="maint-sample">${rows}</ul>`;
      });
      return parts.join("") + _maintMethodHtml(data, t, tf);
    }

    function maintRawIdsHtml(d, t, tf) {
      if (!d) return "";
      if (!d.raw_id_sources) return `<div class="hint">${esc(t("No source is named by a bare identifier."))}</div>`;
      const rows = (d.rows || []).map((r) =>
        `<tr><td dir="ltr">${esc(r.name)}</td><td dir="ltr">${esc(r.domain || "")}</td><td class="num">${esc(fmtNum(r.articles))}</td>`
        + `<td class="num">${esc(String(r.source_id))}</td></tr>`).join("");
      return `<div>${esc(tf(t("{n} sources, {m} articles in the ones shown"), { n: fmtNum(d.raw_id_sources), m: fmtNum(d.articles_in_shown || 0) }))}</div>`
        + `<table class="maint-tally"><thead><tr><th>${esc(t("Name"))}</th><th>${esc(t("Domain"))}</th><th>${esc(t("Articles"))}</th><th>${esc(t("Source number"))}</th></tr></thead>`
        + `<tbody>${rows}</tbody></table>` + _maintMethodHtml(d, t, tf);
    }

    function maintFurnitureHtml(d, t, tf) {
      if (!d) return "";
      const src = d.source || {};
      const head = `<div>${esc(tf(t("{name}: {k} of {n} articles read"), { name: "\u2068" + (src.name || String(src.id)) + "\u2069", k: fmtNum(d.sampled || 0), n: fmtNum(d.articles_in_source || 0) }))}</div>`;
      const c = d.candidates || [];
      if (!c.length) return head + `<div class="hint">${esc(t("No repeated line reaches the threshold."))}</div>`;
      const rows = c.map((r) =>
        `<tr><td dir="auto">${esc(r.line)}</td><td class="num">${esc(fmtNum(r.articles))}</td>`
        + `<td>${r.known ? esc(t("already stripped by the rules")) : ""}</td></tr>`).join("");
      return head + `<table class="maint-tally"><thead><tr><th>${esc(t("Line"))}</th><th>${esc(t("Articles"))}</th><th></th></tr></thead>`
        + `<tbody>${rows}</tbody></table>` + _maintMethodHtml(d, t, tf);
    }

    // ---- DOM + network (loopback) -------------------------------------------------

    function _maintT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _maintTf() {
      return (window.OOI18N && OOI18N.tf) ? OOI18N.tf
        : ((s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => (v && v[k] != null ? v[k] : "")));
    }

    // The URL a dry run is started with. The ONLY place the panel builds a start URL, and
    // it spells write=false: there is no parameter by which a caller could change that.
    function maintStartUrl(withStubs, withHosts) {
      return "/api/quarantine/start?write=false"
        + (withStubs ? "&include_stubs=true" : "")
        + (withHosts ? "&include_host_mismatch=true" : "");
    }

    function maintRender() {
      const t = _maintT(), tf = _maintTf();
      const st = _maintStatus;
      const run = $("maint-run"); if (run) run.innerHTML = maintRunHtml(st, t, tf);
      const tl = $("maint-tally"); if (tl) tl.innerHTML = maintTallyHtml(st && st.tally, t, tf);
      const live = !!(st && (st.state === "running" || st.state === "paused"));
      if (live) { const sm = $("maint-samples"); if (sm) sm.textContent = t("Samples appear when the run stops."); }
      const show = (id, on) => { const el = $(id); if (el) el.style.display = on ? "" : "none"; };
      show("maint-pause", st && st.state === "running");
      // A resume continues in the paused run's OWN mode, so a paused run that has writing on must
      // not be resumable from here: the panel offers no way to write, resume included.
      show("maint-resume", st && st.state === "paused" && st.dry_run === true);
      show("maint-cancel", live);
      const go = $("maint-start"); if (go) go.disabled = live;
    }

    async function maintRefresh() {
      try { _maintStatus = await api("/api/quarantine/status", { polled: true }); }
      catch (e) { _maintStatus = null; }
      maintRender();
      const live = !!(_maintStatus && (_maintStatus.state === "running" || _maintStatus.state === "paused"));
      if (_maintPoll) { clearTimeout(_maintPoll); _maintPoll = null; }
      // Polls only while a run is live AND the section is open: a folded section must not
      // keep a timer going.
      const sec = document.querySelector('details[data-adv="maintenance"]');
      if (live && sec && sec.open) _maintPoll = setTimeout(maintRefresh, 2000);
      else if (_maintStatus && _maintStatus.state && _maintStatus.state !== "idle") maintLoadSamples();
    }

    async function maintStart(btn) {
      const t = _maintT();
      const out = $("maint-msg"); if (out) out.textContent = "";
      try {
        await api(maintStartUrl(!!($("maint-stubs") || {}).checked, !!($("maint-hosts") || {}).checked), { method: "POST" });
      } catch (e) {
        // 409 = a run is in progress already: a state, not a failure.
        if (out) out.textContent = e && e.status === 409 ? t("A run is already in progress.") : (e && e.message) || String(e);
      }
      maintRefresh();
    }

    async function maintAction(action) {
      if (["pause", "resume", "cancel"].indexOf(action) < 0) return;
      try { await api("/api/quarantine/" + action, { method: "POST" }); } catch (e) { /* the refresh below shows the real state */ }
      maintRefresh();
    }

    async function maintLoadSamples() {
      const t = _maintT(), tf = _maintTf();
      const el = $("maint-samples"); if (!el) return;
      try {
        const d = await api("/api/quarantine/samples");
        el.innerHTML = maintSamplesHtml(d, t, tf);
      } catch (e) { el.textContent = (e && e.message) || String(e); }
    }

    async function maintLoadRawIds() {
      const t = _maintT(), tf = _maintTf();
      const el = $("maint-rawids"); if (!el) return;
      try { el.innerHTML = maintRawIdsHtml(await api("/api/quarantine/raw-id-sources"), t, tf); }
      catch (e) { el.textContent = (e && e.message) || String(e); }
    }

    async function maintLoadFurniture() {
      const t = _maintT(), tf = _maintTf();
      const el = $("maint-furniture"); if (!el) return;
      const id = parseInt(($("maint-fsrc") || {}).value, 10);
      if (!(id >= 1)) { el.textContent = t("Enter a source number first."); return; }
      try { el.innerHTML = maintFurnitureHtml(await api("/api/quarantine/source-furniture?source_id=" + id), t, tf); }
      catch (e) { el.textContent = e && e.status === 404 ? t("No such source.") : ((e && e.message) || String(e)); }
    }

    async function maintLoadPairs() {
      const t = _maintT(), tf = _maintTf();
      const el = $("maint-pairs"); if (!el) return;
      try { el.innerHTML = maintPairsHtml(await api("/api/quarantine/host-pairs"), t, tf); }
      catch (e) { el.textContent = (e && e.message) || String(e); }
    }

    // Confirm or withdraw one pair. Local only: the route stores or deletes one row on this machine.
    // A 409 is the server saying the pair is no longer a mismatch, shown as its own sentence, labelled.
    async function maintPairAct(btn) {
      const t = _maintT();
      const act = btn.getAttribute("data-maint-pair");
      const sid = parseInt(btn.getAttribute("data-source"), 10);
      const site = btn.getAttribute("data-site") || "";
      if (["confirm", "withdraw"].indexOf(act) < 0 || !(sid >= 1) || !site) return;
      const out = $("maint-pair-msg"); if (out) out.textContent = "";
      btn.disabled = true;
      try {
        if (act === "confirm") {
          await api("/api/quarantine/host-pairs", { method: "POST",
            body: JSON.stringify({ source_id: sid, article_site: site }) });
        } else {
          await api("/api/quarantine/host-pairs?source_id=" + sid + "&article_site=" + encodeURIComponent(site), { method: "DELETE" });
        }
        if (out) out.textContent = act === "confirm" ? t("Confirmed.") : t("Withdrawn.");
      } catch (e) {
        if (out) out.innerHTML = e && e.status === 409
          ? esc(t("Nothing to confirm: no stored article of this source lives on that site any more."))
          : e && e.status === 404 ? esc(t("No such source."))
          : _maintServerTextHtml((e && e.message) || String(e), t);
      } finally { btn.disabled = false; }
      maintLoadPairs();
      // The samples only exist once a run has happened; reloading them before that would replace
      // an empty panel with the server's "no sample is held" note.
      if (_maintStatus && _maintStatus.state && _maintStatus.state !== "idle") maintLoadSamples();
    }

    function _maintWirePairs() {
      for (const id of ["maint-samples", "maint-pairs"]) {
        const el = $(id);
        if (el) el.addEventListener("click", (ev) => {
          const b = ev.target && ev.target.closest ? ev.target.closest("button[data-maint-pair]") : null;
          if (b) maintPairAct(b);
        });
      }
    }

    // The Advanced loader runs once per page, so reopening the section after a fold would show the
    // state it was folded in. Re-read when it opens, and wire that once.
    let _maintWired = false;
    function loadMaintenance() {
      if (!_maintWired) {
        const sec = document.querySelector('details[data-adv="maintenance"]');
        if (sec) sec.addEventListener("toggle", () => { if (sec.open) { maintRefresh(); maintLoadPairs(); } });
        _maintWirePairs();
        _maintWired = true;
      }
      maintRefresh(); maintLoadRawIds(); maintLoadPairs();
    }
