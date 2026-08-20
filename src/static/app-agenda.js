/* app-agenda.js — Agenda and Bulletin

   The Agenda's views, calendar subscriptions and feed directory, and the Bulletin
   (generate, review, publish, annex bundles).

   PART OF THE UI ENGINE. src/static/app.js was decomposed into ordered modules
   (structural debt S-3; docs/design/APPJS_DECOMPOSITION_2026-08-20.md). They share
   ONE global scope -- there is no module system here, and 394 of these top-level names
   are called by inline on*= handlers, which resolve against the global scope and
   nothing else -- and they load in the order index.html lists them, boot last.

   The split was a pure CONTIGUOUS slice, verified at the split commit by
   concatenating the modules in load order and reproducing the pre-split file byte
   for byte. That check is spent now (these files are edited normally), but the rule
   it rested on still holds: DO NOT reorder a declaration across a module boundary.
   Function declarations would survive it, because they hoist; a const or let would
   not, and the failure is a TDZ error at load rather than anything a reader would
   spot in review. Add new code inside the module it belongs to.
*/
    const _MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const AG = { events: [], cals: [], caveat: "", meta: {}, categories: [] };
    // The agenda calendar SUBSCRIPTIONS now live SERVER-SIDE (GET/PUT /api/agenda/prefs,
    // D4) so they survive a browser reset AND a reinstall and ride backups — they used to
    // sit in localStorage ("oo.agenda.subs"), invisible to the server and to every backup.
    // Loaded once per agenda open into this in-memory cache so the sync getters stay
    // synchronous; the setter fires a best-effort PUT (the UI never blocks on the
    // round-trip). `configured=false` means the server has no explicit choice yet, so we
    // keep the first-run default (subscribe to EVERY calendar) — never silently dropping a
    // first-run user's calendars. NOTE: feed EXCLUSIONS and the chosen VIEW deliberately
    // STAY per-machine in localStorage (below) — a per-device display/curation choice ruled
    // per-machine (2026-06-15), not a corpus-level subscription that should ride a backup.
    let _agPrefs = null;   // { subs: Set, configured: bool } — the server-backed subscriptions
    function _agPrefsDefault() { return { subs: new Set(), configured: false }; }
    async function agLoadPrefs() {
      try {
        const p = await api("/api/agenda/prefs");
        _agPrefs = { subs: new Set(p.subs || []), configured: !!p.configured };
      } catch (_e) {
        // Offline / pre-unlock / older backend: a permissive in-memory default so the
        // agenda still works; nothing is persisted until the server answers.
        if (!_agPrefs) _agPrefs = _agPrefsDefault();
      }
      return _agPrefs;
    }
    function agPutPrefs(patch) {
      // Persist a partial prefs update (best-effort — the in-memory cache already reflects
      // it, so a failed write only means it won't survive this session). Loopback only.
      api("/api/agenda/prefs", { method: "PUT", body: JSON.stringify(patch) }).catch(() => {});
    }
    function agSubs() { return new Set((_agPrefs || _agPrefsDefault()).subs); }
    function agSaveSubs(set) {
      if (!_agPrefs) _agPrefs = _agPrefsDefault();
      _agPrefs.subs = new Set(set); _agPrefs.configured = true;
      agPutPrefs({ subs: [..._agPrefs.subs] });
    }
    // Per-machine EXCLUDED feed families (ruled 2026-06-15: "remove = reversible
    // unsubscribe, never delete-from-catalog"; a per-machine store, kept in localStorage).
    // Excluded folders keep their honest verdicts in the directory (anti-hiding) but
    // contribute no imported events.
    function agExcluded() { try { return new Set(JSON.parse(localStorage.getItem("oo.agenda.excluded") || "null") || []); } catch (_e) { return new Set(); } }
    function agSaveExcluded(set) { localStorage.setItem("oo.agenda.excluded", JSON.stringify([...set])); }

    // An imported feed event (already cross-feed deduped server-side) mapped into
    // the agenda's event shape, flagged as the IMPORTED provenance class so it is
    // filterable and never silently blended with curated events.
    function mapImportedToAgenda(e) {
      const d = e.date || "";
      // "imported" is NOT a category — everything in the agenda is imported, so it
      // told the user nothing (maintainer 2026-06-18). Use the feed's REAL facets:
      // category = its kind (holidays / religion / civic / space / science /
      // community), the country, and tags so the agenda filters to a thin view.
      const kind = e.kind || "other";
      const tags = [kind].concat(e.country ? [e.country] : []);
      return {
        title: e.title, category: kind, country: e.country || null, tags: tags,
        confirmed: true,                       // an ICS VEVENT carries a concrete date
        next_occurrence: d,
        // month/day stay NULL deliberately (fix 2026-07-17): those fields are the
        // ANNUAL-RULE placement keys, and an imported VEVENT is evidence for ITS
        // year only. Filling them ghosted every dated instance into EVERY displayed
        // year — three contradictory moon phases on one day (each year's phases
        // drift ~11 days), a 2025 movable feast projected onto 2026, etc. Dated
        // instances place via next_occurrence alone; projecting a dated instance
        // to other years would be fabrication for anything movable.
        month: null,
        day: null,
        calendar: e.family, family_name: e.family_name, family_names: e.family_names,
        kind: kind, countries: e.countries || (e.country ? [e.country] : []),
        sources: e.sources || [], source_count: e.source_count, family_count: e.family_count,
        imported: true,
      };
    }
    // Article-DEDUCED dates → the agenda event shape (mirrors mapImportedToAgenda so
    // every view places them via next_occurrence for free). DEDUCED, never confirmed:
    // a date the text MENTIONS, not proof an event will happen. Clicking opens the
    // exact article set (openAnalysisForIds, via agRow). Counts only, no score.
    function mapDeducedToAgenda(e) {
      const d = e.date || "";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return {
        title: t("{n} articles mention this date").replace("{n}", e.n_articles),
        category: "deduced", country: null, tags: [],
        confirmed: false,                      // deduced from text — never a confirmed event
        next_occurrence: d,
        // NULL like mapImportedToAgenda (fix 2026-07-17): a deduced DATE is
        // year-specific evidence; month/day are the annual-rule keys and would
        // ghost it into every displayed year.
        month: null,
        day: null,
        calendar: "deduced", deduced: true,
        article_ids: e.article_ids || [], n_articles: e.n_articles, n_sources: e.n_sources,
        note: t("Deduced from {n} articles ({s} sources), never confirmed.")
          .replace("{n}", e.n_articles).replace("{s}", e.n_sources),
      };
    }
    async function loadAgenda() {
      const box = $("agenda-list");
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const today = new Date().toISOString().slice(0, 10);
        const [ev, fac, imp, ded] = await Promise.all([
          api("/api/events"), api("/api/events/calendars"),
          api("/api/events/imported?from=" + today).catch(() => ({ events: [] })),
          // Article-DEDUCED upcoming dates (the agenda's article-extracted layer).
          // Degrade quietly — never break the agenda if this is unavailable.
          api("/api/events/deduced").catch(() => ({ events: [] })),
          // Server-side subscription prefs (D4) — populates _agPrefs before agExcluded()
          // below reads it; a failure degrades to the permissive in-memory default.
          agLoadPrefs(),
        ]);
        const excl = agExcluded();
        const imported = (imp.events || []).map(mapImportedToAgenda).filter(e => !excl.has(e.calendar));
        const deduced = (ded.events || []).map(mapDeducedToAgenda).filter(e => !excl.has(e.calendar));
        AG.events = ev.events.concat(imported, deduced); AG.caveat = ev.caveat; AG.cals = fac.calendars;
        // Category chips = the REAL event kinds (holidays / religion / civic / …),
        // never a useless "imported" bucket (maintainer 2026-06-18). Imported events
        // each carry their feed's kind; deduced stays its own honest class. De-duped,
        // sorted, only kinds actually present so the chip row stays thin.
        const importedKinds = [...new Set(imported.map(e => e.category).filter(Boolean))].sort();
        AG.categories = [...new Set((fac.categories || []).concat(importedKinds))].sort()
          .concat(deduced.length ? ["deduced"] : []);
        AG.meta = Object.fromEntries(fac.calendars.map(c => [c.key, c]));
        // First run: the server has no explicit choice yet (configured=false) → default to
        // subscribing to EVERY calendar so the agenda isn't empty. Kept in-memory (NOT
        // persisted) until the user makes an explicit choice, so a newly-added catalog
        // calendar is auto-included and nothing is ever silently dropped (honors the flag).
        if (_agPrefs && !_agPrefs.configured) _agPrefs.subs = new Set(fac.calendars.map(c => c.key));
        $("agenda-country").innerHTML = '<option value="">all</option>' + fac.countries.map(x => `<option value="${esc(x)}">${agFlag(x)} ${esc(x)}</option>`).join("");
        $("agenda-tag").innerHTML = '<option value="">all</option>' + fac.tags.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
        if (!_agViewTabs) _agViewTabs = ooSubtabs($("agenda-views"), agendaSetView);
        renderAgendaCatChips();
        renderAgenda();
      } catch (e) { box.innerHTML = `<div class="muted">Could not load agenda: ${esc(e.message)}</div>`; }
      // The feed DIRECTORY is no longer loaded here: it moved to Settings → Advanced
      // (invariant #8 — this tab shows the agenda, not the catalogue that feeds it)
      // and loads only when that section is expanded. The agenda's own per-event
      // provenance pills do not depend on it: _agFeedById() self-loads the map on
      // first use when _feedDir is still null.
    }

    // -- The Bulletin (design record §13/§16) -------------------------------- //
    // A periodic document built from the corpus. Everything here is LOOPBACK: the
    // deterministic layer is SQL, the optional narration runs on the local model,
    // and nothing in this panel touches the network -- so no consent gate.
    //
    // The load-bearing mechanic: a producer toggle RE-RENDERS from the persisted
    // record. It recomputes nothing and edits nothing, so a number in a published
    // document is always a number the record contains. Excluding is done by
    // passing the exclusions to the render URL, never by writing a trimmed copy.
    // `t` is per-function in this file, never global, so the bulletin block gets its
    // own helper on the _gwT precedent -- a bare t() here passes node --check and
    // throws a ReferenceError in the browser.
    function _bulT(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }
    // Guarded like _bulT, for the same reason: i18n.js may not have loaded. The
    // template is the key and the count is data, so the frame can be translated
    // later without the number ever going through a translation table.
    function _bulTf(s, vars) {
      return (window.OOI18N && OOI18N.tf) ? OOI18N.tf(s, vars)
        : String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m);
    }
    let _bulExcludeSections = new Set();
    let _bulExcludeStories = new Set();
    let _bulFile = null;

    function _bulQuery() {
      const p = new URLSearchParams();
      if (_bulExcludeSections.size) p.set("exclude_sections", [..._bulExcludeSections].join(","));
      if (_bulExcludeStories.size) p.set("exclude_stories", [..._bulExcludeStories].join(","));
      // The document is written in the language the operator is READING the app in.
      // Built here, in the one place both the report and the annexes take their query
      // from, so the two can never come out in different languages.
      const lang = (window.OOI18N && OOI18N.current) ? OOI18N.current() : "en";
      if (lang && lang !== "en") p.set("lang", lang);
      return p;
    }

    async function loadBulletin() {
      const gate = $("bulletin-gate"), controls = $("bulletin-controls");
      if (!gate) return;
      let g = null;
      try { g = await api("/api/bulletin/availability"); }
      catch (e) { gate.textContent = _bulT("Could not check this machine: ") + e.message; return; }
      if (!g.available) {
        // A refusal states its REASON and points at the override, because the
        // gate is never a hard block -- it is a default with a stated basis.
        gate.innerHTML = `<span>${esc(g.reason || _bulT("This machine cannot build a bulletin."))}</span>` +
          ` <span class="muted">${esc(_bulT("You can turn this on anyway in Settings → AI."))}</span>`;
        controls.hidden = true;
        return;
      }
      gate.hidden = true;
      controls.hidden = false;
      await loadBulletinEditions();
    }

    async function loadBulletinEditions() {
      const box = $("bulletin-list");
      if (!box) return;
      let d = null;
      try { d = await api("/api/bulletin/editions"); }
      catch (e) { box.innerHTML = `<div class="muted">${esc(_bulT("Could not list editions: ") + e.message)}</div>`; return; }
      const rows = d.editions || [];
      if (!rows.length) {
        box.innerHTML = `<div class="muted">${esc(_bulT("No editions yet. Build a draft above."))}</div>`;
        return;
      }
      box.innerHTML = `<div style="overflow:auto"><table><tr>
          <th>${esc(_bulT("Covers through"))}</th><th>${esc(_bulT("Period"))}</th><th></th></tr>` +
        rows.map(r => `<tr>
          <td>${esc(r.covers_through || r.filename)}</td>
          <td>${esc(r.cadence || "—")}</td>
          <td class="row" style="gap:6px;justify-content:flex-end">
            <button class="secondary" onclick="bulletinReview('${esc(r.filename)}')">${esc(_bulT("Review"))}</button>
            <button class="secondary" onclick="bulletinOpenFile('${esc(r.filename)}')">${esc(_bulT("Open"))}</button>
            <button class="secondary" onclick="bulletinDelete('${esc(r.filename)}')">${esc(_bulT("Delete"))}</button>
          </td></tr>`).join("") + "</table></div>";
    }

    async function bulletinGenerate(btn) {
      const status = $("bulletin-status");
      const cadence = ($("bul-cadence") || {}).value || "weekly";
      const narrate = !!($("bul-narrate") || {}).checked;
      btn.disabled = true;
      status.textContent = _bulT("Building…");
      try {
        const out = await api(
          `/api/bulletin/generate?cadence=${encodeURIComponent(cadence)}&persist=true&narrate=${narrate}`,
          {method: "POST"});
        status.textContent = out.persisted
          ? _bulT("Draft built.")
          : _bulT("Built, but not saved: ") + (out.persist_error || "");
        await loadBulletinEditions();
        if (out.filename) bulletinReview(out.filename);
      } catch (e) {
        status.textContent = _bulT("Could not build: ") + e.message;
      } finally { btn.disabled = false; }
    }

    async function bulletinReview(filename) {
      const box = $("bulletin-review");
      if (!box) return;
      _bulFile = filename;
      _bulExcludeSections = new Set();
      _bulExcludeStories = new Set();
      box.innerHTML = `<div class="muted">${esc(_bulT("Loading…"))}</div>`;
      let v = null;
      try { v = await api(`/api/bulletin/editions/${encodeURIComponent(filename)}/review`); }
      catch (e) { box.innerHTML = `<div class="muted">${esc(_bulT("Could not open this edition: ") + e.message)}</div>`; return; }
      _bulRender(v);
    }

    function _bulRender(v) {
      const box = $("bulletin-review");
      const state = v.state === "published"
        ? `<span class="pill">${esc(_bulT("published"))}</span>`
        : `<span class="pill">${esc(_bulT("draft"))}</span>`;
      const secs = (v.sections || []).map(s => {
        const off = _bulExcludeSections.has(s.section);
        // A section's REAL window is printed when it differs from the period --
        // §12's whole point is that a 14-day number in a 7-day edition is visible
        // during review rather than discovered afterwards.
        const w = s.window || {};
        const win = (w.days != null && w.matches_period === false)
          ? ` <span class="warn">${esc(_bulT("window:"))} ${esc(w.days)} ${esc(_bulT("days"))}</span>` : "";
        const why = s.error
          ? ` <span class="warn">${esc(_bulT("failed:"))} ${esc(s.error)}</span>`
          : (s.skipped ? ` <span class="muted">${esc(_bulT("skipped:"))} ${esc(s.skipped)}</span>` : "");
        return `<label class="row" style="gap:8px;align-items:baseline">
          <input type="checkbox" ${off ? "" : "checked"} onchange="bulletinToggleSection('${esc(s.section)}')">
          <span><strong>${esc(String(s.section).replace(/_/g, " "))}</strong>
            <span class="muted">${esc(s.rows)} ${esc(_bulT("row(s)"))}</span>${win}${why}</span></label>`;
      }).join("");

      const stories = (v.stories || []).map(s => {
        const off = _bulExcludeStories.has(s.key);
        // Per SENTENCE, per §13: a sentence you can see was checked is a different
        // thing from a paragraph labelled "validated".
        const sents = (s.sentences || []).map(x => x.kept
          ? `<li>${esc(x.text)}</li>`
          : `<li class="muted"><s>${esc(x.text)}</s> — ${esc(_bulT("dropped; not in the evidence:"))} ${esc((x.unsupported || []).join(", "))}</li>`
        ).join("");
        const label = s.narrated
          ? `<div class="warn">${esc(_bulT("AI-derived — unreliable"))}${s.partial ? esc(_bulT("; sentences naming something absent from the sources were removed")) : ""}</div>`
          : `<div class="muted">${esc(_bulT("No model text: "))}${esc(s.fallback_reason || "")}</div>`;
        return `<div style="margin:8px 0">
          <label class="row" style="gap:8px;align-items:baseline">
            <input type="checkbox" ${off ? "" : "checked"} onchange="bulletinToggleStory('${esc(s.key)}')">
            <span><strong>${esc((s.shared_terms || []).join(", ") || "—")}</strong>
              <span class="muted">${esc(s.articles)} ${esc(_bulT("articles"))} · ${esc(s.distinct_sources)} ${esc(_bulT("sources"))}${s.single_source ? esc(_bulT(" · one source only")) : ""}</span></span></label>
          ${label}${sents ? `<ul style="margin:4px 0 0 26px">${sents}</ul>` : ""}</div>`;
      }).join("");

      box.innerHTML = `<h3 style="margin:0 0 4px">${esc(_bulT("Review"))} ${state}</h3>
        <p class="hint" style="margin-top:0">${esc(v.caveat || "")}</p>
        <p class="hint">${esc(v.method || "")}</p>
        <h4 style="margin:12px 0 4px">${esc(_bulT("Sections"))}</h4>${secs || `<div class="muted">${esc(_bulT("None."))}</div>`}
        ${stories ? `<h4 style="margin:12px 0 4px">${esc(_bulT("Stories"))}</h4>${stories}` : ""}
        <div class="row" style="gap:8px;margin-top:12px;flex-wrap:wrap">
          <button class="secondary" onclick="bulletinOpen('html')">${esc(_bulT("Preview"))}</button>
          <button class="secondary" onclick="bulletinDownloadBundle(this)">${esc(_bulT("Download report + annexes"))}</button>
          <button class="secondary" onclick="bulletinOpen('markdown')">${esc(_bulT("Report only"))}</button>
          <button onclick="bulletinPublish(this)">${esc(_bulT("Publish"))}</button>
          <div id="bul-pub" class="hint" style="align-self:center"></div>
        </div>
        <p class="hint">${esc(_bulT("The annexes are one Markdown file per article the report cites, numbered to match, with a contents page. They carry the sources' own text — keep them where you keep the corpus."))}</p>`;
    }

    function bulletinToggleSection(key) {
      if (_bulExcludeSections.has(key)) _bulExcludeSections.delete(key);
      else _bulExcludeSections.add(key);
    }
    function bulletinToggleStory(key) {
      if (_bulExcludeStories.has(key)) _bulExcludeStories.delete(key);
      else _bulExcludeStories.add(key);
    }

    function bulletinOpen(fmt) {
      if (!_bulFile) return;
      const q = _bulQuery();
      q.set("fmt", fmt);
      window.open(`/api/bulletin/editions/${encodeURIComponent(_bulFile)}/render?${q}`, "_blank", "noopener");
    }

    // One click, two files. A browser cannot put two downloads in one response, so
    // the button fetches both and saves each -- the report and the annexes ZIP whose
    // reference numbers match it.
    //
    // BOTH REQUESTS CARRY THE SAME SELECTION. The reference numbers are assigned over
    // the document as it will be published, so annexes built without the operator's
    // exclusions would number a different set and `[0007]` in the report would open
    // the wrong article. Sending the selection to one and not the other is the whole
    // failure mode, which is why the query is built once here.
    async function bulletinDownloadBundle(btn) {
      if (!_bulFile) return;
      const out = $("bul-pub");
      const q = _bulQuery();
      const base = `/api/bulletin/editions/${encodeURIComponent(_bulFile)}`;
      btn.disabled = true;
      if (out) out.textContent = _bulT("Building the annexes…");
      try {
        const rq = new URLSearchParams(q); rq.set("fmt", "markdown");
        const report = await fetch(`${base}/render?${rq}`);
        await _throwIfNotOk(report);
        _saveBlob(await report.blob(), _filenameOf(report, "bulletin.md"));

        const zip = await fetch(`${base}/annexes?${q}`);
        await _throwIfNotOk(zip);
        const n = zip.headers.get("X-OO-Annex-Articles");
        _saveBlob(await zip.blob(), _filenameOf(zip, "annexes.zip"));
        if (out) {
          out.textContent = n && n !== "0"
            ? _bulTf("Downloaded: the report and {n} annexed article(s).", {n: n})
            : _bulT("Downloaded the report. This edition names no articles, so the annexes are empty — regenerate it to populate them.");
        }
      } catch (e) {
        if (out) out.textContent = _bulT("Could not download: ") + e.message;
      } finally { btn.disabled = false; }
    }

    // These two fetches are raw rather than through api(), because their bodies are a
    // document and a ZIP rather than JSON. So the error path has to be re-created —
    // and it goes through the SAME _apiErrorMessage the rest of the app uses, which
    // takes a PARSED payload, so a refusal reads as its reason instead of "500".
    async function _throwIfNotOk(res) {
      if (res.ok) return;
      let data = null;
      try { data = await res.json(); } catch (_) { /* a non-JSON error body is fine */ }
      throw new Error(_apiErrorMessage(data, res));
    }

    // The server names these files; it knows the period and the cadence. Reading the
    // name off Content-Disposition rather than rebuilding it here keeps one namer.
    function _filenameOf(res, fallback) {
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename="([^"]+)"/.exec(cd);
      return (m && m[1]) || fallback;
    }

    function _saveBlob(blob, name) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Revoked on a later tick: revoking synchronously can cancel the download in
      // some browsers before it has read the blob.
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }

    // Opening from the LIST shows the whole edition. A selection belongs to the
    // review screen, where you can see what you are excluding -- carrying one
    // silently into a list click would hand you a document you did not choose.
    function bulletinOpenFile(filename) {
      window.open(
        `/api/bulletin/editions/${encodeURIComponent(filename)}/render?fmt=html`, "_blank", "noopener");
    }

    async function bulletinPublish(btn) {
      if (!_bulFile) return;
      const out = $("bul-pub");
      btn.disabled = true;
      try {
        const r = await api(
          `/api/bulletin/editions/${encodeURIComponent(_bulFile)}/publish?${_bulQuery()}`,
          {method: "POST"});
        out.textContent = _bulT("Published — the record itself is unchanged.");
        toast(_bulT("Published. Nothing was sent anywhere; the document is yours to share."));
        if (r) await loadBulletinEditions();
      } catch (e) { out.textContent = _bulT("Could not publish: ") + e.message; }
      finally { btn.disabled = false; }
    }

    async function bulletinDelete(filename) {
      if (!confirm(_bulT("Delete this edition? The corpus is untouched — only the document goes."))) return;
      try {
        await api(`/api/bulletin/editions/${encodeURIComponent(filename)}`, {method: "DELETE"});
        if (_bulFile === filename) { _bulFile = null; $("bulletin-review").innerHTML = ""; }
        await loadBulletinEditions();
      } catch (e) { toast(_bulT("Could not delete: ") + e.message, "err"); }
    }

    // -- Calendar feed directory: candidates -> explicit verify/import ------- //
    // Families SHOW duplicate providers (one folder, every source listed with a
    // transparent URL). Verify/import are operator clicks through the ethical
    // fetcher -- the directory itself never touches the network.
    let _feedDir = null;
    async function loadFeedDir() {
      try { _feedDir = await api("/api/events/feeds"); } catch { _feedDir = null; }
      if (!_feedDir) { $("feeddir-list").innerHTML = '<div class="muted">Could not load this document.</div>'; return; }
      const kinds = [...new Set(_feedDir.families.map(f => f.kind))].sort();
      $("feeddir-kind").innerHTML = '<option value="">all</option>' +
        kinds.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join("");
      renderFeedDir();
      renderUserCalendars();
    }
    function _verdictChip(v, feed) {
      if (!v) return '<span class="pill">not checked yet</span>';
      if (v.status === "ok") {
        const stale = v.stale_year ? ' <span class="pill warn">stale year</span>' : "";
        return `<span class="pill ok">reachable · ${v.events}</span>${stale}`;
      }
      if (v.status === "not_ical") return '<span class="pill warn">not an iCal file</span>';
      return `<span class="pill err" title="${esc(v.error || "")}">unreachable</span>`;
    }
    // A folder's overall health from its feeds' verdicts: reachable if ANY feed is
    // reachable, dysfunctional if all checked feeds failed, else not-yet-checked.
    function famStatus(f) {
      let anyOk = false, anyChecked = false;
      for (const fd of (f.feeds || [])) {
        if (fd.verdict) { anyChecked = true; if (fd.verdict.status === "ok") anyOk = true; }
      }
      return anyOk ? "ok" : (anyChecked ? "error" : "unchecked");
    }
    const _FEED_SORTS = {
      name: (a, b) => a.name.localeCompare(b.name),
      country: (a, b) => (a.country || "￿").localeCompare(b.country || "￿") || a.name.localeCompare(b.name),
      kind: (a, b) => (a.kind || "").localeCompare(b.kind || "") || a.name.localeCompare(b.name),
      // dysfunctional first, so problems surface (the maintainer's "find the broken ones")
      status: (a, b) => ({ error: 0, unchecked: 1, ok: 2 }[famStatus(a)] - { error: 0, unchecked: 1, ok: 2 }[famStatus(b)]) || a.name.localeCompare(b.name),
      imported: (a, b) => ((b.imported_events || 0) - (a.imported_events || 0)) || a.name.localeCompare(b.name),
    };
    function _feedDirFiltered() {
      if (!_feedDir) return [];
      const kind = $("feeddir-kind").value, q = ($("feeddir-q").value || "").toLowerCase();
      const sf = $("feeddir-status-filter").value, sort = $("feeddir-sort").value || "name";
      const fams = _feedDir.families.filter(f =>
        (!kind || f.kind === kind) &&
        (!sf || famStatus(f) === sf) &&
        (!q || f.name.toLowerCase().includes(q) || (f.country || "").toLowerCase().includes(q)));
      fams.sort(_FEED_SORTS[sort] || _FEED_SORTS.name);
      return fams;
    }
    // Bulk exclude/include (reversible). 'dysfunctional' = every broken folder;
    // 'shown' = the current filtered+sorted set (so the Status filter doubles as a
    // selector, e.g. show Dysfunctional then Exclude shown).
    function agExcludeBulk(which) {
      const s = agExcluded();
      const fams = which === "dysfunctional"
        ? (_feedDir ? _feedDir.families.filter(f => famStatus(f) === "error") : [])
        : _feedDirFiltered();
      fams.forEach(f => s.add(f.key));
      agSaveExcluded(s); renderFeedDir(); _agendaMaybeReload();
    }
    function agExcludeClear() { agSaveExcluded(new Set()); renderFeedDir(); _agendaMaybeReload(); }
    function agToggleExclude(key) {
      const s = agExcluded(); s.has(key) ? s.delete(key) : s.add(key);
      agSaveExcluded(s); renderFeedDir(); _agendaMaybeReload();
    }
    function _agendaMaybeReload() {  // keep the agenda in sync if it's open
      const t = $("tab-agenda"); if (t && t.classList.contains("active")) loadAgenda();
    }
    function renderFeedDir() {
      if (!_feedDir) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const excl = agExcluded();
      let fams = _feedDirFiltered();
      const total = fams.length;
      fams = fams.slice(0, 40);
      // The manual "Verify next 25" button is gone; what replaced it is stated here
      // instead, with the REAL backlog — so the automation is visible rather than
      // implied (ruling 10/11). Every figure is a count the backend measured.
      const _v = _feedDir.verification || {};
      $("feeddir-status").innerHTML =
        esc(`${_feedDir.total_feeds} feeds · ${_feedDir.families.length} folders · ${_feedDir.checked} checked`) +
        (_v.unchecked
          ? ` <span class="muted" title="${esc(_v.method || "")}">· ${_v.unchecked} ${esc(t("not checked yet"))}</span>`
          : "");
      const bulk = `<div class="row" style="gap:6px;margin-bottom:8px;align-items:center;flex-wrap:wrap">
        <button class="secondary tiny" onclick="agExcludeBulk('dysfunctional')">Exclude dysfunctional</button>
        <button class="secondary tiny" onclick="agExcludeBulk('shown')">Exclude shown</button>
        ${excl.size ? `<button class="ghost tiny" onclick="agExcludeClear()">Clear exclusions</button>
          <span class="hint">${excl.size} <span>excluded</span></span>` : ""}</div>`;
      $("feeddir-list").innerHTML = bulk + fams.map(f => {
        const feeds = f.feeds.map(fd => `
          <div class="vr">
            <span>${esc(fd.provider)}${fd.year_pinned ? ` <span class="muted">· ${fd.year_pinned}</span>` : ""}</span>
            <b>${_verdictChip(fd.verdict, fd)}
              <button class="ghost tiny" onclick="feedAction('${esc(fd.id)}','verify')">Verify</button>
              <button class="secondary tiny" onclick="feedAction('${esc(fd.id)}','import')">Import</button></b>
          </div>
          <div class="hint" style="word-break:break-all;margin:0 0 4px"><a href="${esc(fd.url)}" target="_blank" rel="noopener noreferrer">${esc(fd.url)}</a></div>`).join("");
        const isExcl = excl.has(f.key);
        return `<details class="cs-row${isExcl ? " excluded" : ""}" style="padding:6px 10px">
          <summary style="cursor:pointer">${esc(f.name)}
            ${f.duplicates ? `<span class="pill" title="Several providers publish this calendar — compare them below">${f.feeds.length} sources</span>` : ""}
            ${f.imported_events ? `<span class="pill ok">${f.imported_events} imported</span>` : ""}
            ${isExcl ? `<span class="pill warn">excluded</span>` : ""}
            <span class="muted">· ${esc(f.kind)}${f.country ? " · " + esc(f.country) : ""}</span>
            <button class="ghost tiny" style="float:inline-end" onclick="event.preventDefault();event.stopPropagation();agToggleExclude('${esc(f.key)}')">${isExcl ? "Include" : "Exclude"}</button></summary>
          ${feeds}</details>`;
      }).join("") + (total > 40 ? `<div class="hint">+${total - 40} — type to filter</div>` : "");
    }
    async function feedAction(id, action) {
      try {
        await api(`/api/events/feeds/${encodeURIComponent(id)}/${action}`, {method: "POST"});
        toast(action === "import" ? "Imported." : "Checked.", "ok");
      } catch (e) { toast(e.message, "err"); }
      loadFeedDir();
    }
    // NOTE: the "Verify next 25" button is gone (ruling 10/11, 2026-07-31) —
    // verification is progressive now, riding each collection pass, and its tally
    // shows in the task manager's Schedule tab. The per-feed "Check" action below
    // stays: verifying ONE feed you are looking at is a real, bounded choice, not
    // the manual sweep the ruling retired. POST /api/events/feeds/verify-batch is
    // deliberately KEPT on the backend — never remove an endpoint, only a
    // redundant button (the Desk lesson).
    // Upload a local .ics (no network): events join the agenda (deduped) as a
    // removable, user-owned calendar. The file is read client-side and posted.
    async function importIcsFile(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const f = $("ics-file").files && $("ics-file").files[0];
      if (!f) { toast(t("Choose a .ics file first."), "err"); return; }
      const name = ($("ics-name").value || f.name.replace(/\.ics$/i, "")).trim();
      btn.disabled = true;
      try {
        const ics = await f.text();
        const r = await api("/api/events/feeds/import-ics", { method: "POST", body: JSON.stringify({ name, ics }) });
        toast(`${r.added} / ${r.events_in_file}`, "ok");
        $("ics-file").value = ""; $("ics-name").value = "";
        renderUserCalendars(); _agendaMaybeReload();
      } catch (e) { toast(e.message, "err"); }
      finally { btn.disabled = false; }
    }
    // Add a calendar by URL (network): the ONE consent popup fires first, then the
    // fetch goes through the guarded fetcher (robots / kill switch / politeness).
    async function importIcsUrl(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const url = ($("ics-url").value || "").trim();
      if (!url) { toast(t("Enter a calendar URL first."), "err"); return; }
      if (!await ensureOnline(t("Fetch a calendar from a URL you provided"))) return;
      const name = ($("ics-name").value || "").trim();
      btn.disabled = true;
      try {
        const r = await api("/api/events/feeds/import-url", { method: "POST", body: JSON.stringify({ url, name }) });
        toast(`${r.added} / ${r.events_in_file}`, "ok");
        $("ics-url").value = ""; $("ics-name").value = "";
        renderUserCalendars(); _agendaMaybeReload();
      } catch (e) { toast(e.message, "err"); }
      finally { btn.disabled = false; }
    }
    async function renderUserCalendars() {
      let d; try { d = await api("/api/events/feeds/user"); } catch { return; }
      const box = $("feeddir-user"); if (!box) return;
      if (!d.feeds || !d.feeds.length) { box.innerHTML = ""; return; }
      box.innerHTML = `<h3 style="margin-bottom:6px">Your calendars</h3>` + d.feeds.map(f =>
        `<div class="vr"><span>${esc(f.name)} <span class="muted">· ${f.events}</span></span>` +
        `<button class="ghost tiny" onclick="removeUserCalendar('${esc(f.key)}')">Remove</button></div>`).join("");
    }
    async function removeUserCalendar(key) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try { await api("/api/events/feeds/user/" + encodeURIComponent(key), { method: "DELETE" }); toast(t("Calendar removed."), "ok"); }
      catch (e) { toast(e.message, "err"); }
      renderUserCalendars(); _agendaMaybeReload();
    }

    function renderAgendaCals() {
      const subs = agSubs();
      $("agenda-cals").innerHTML = AG.cals.map(c =>
        // aria-pressed: subscribed/not is a TOGGLE state, and after the contrast fix
        // it is carried by the accent background + border. Colour alone must never be
        // the only channel, so the state is announced too.
        `<button class="ag-cal${subs.has(c.key) ? " on" : ""}" data-k="${esc(c.key)}" onclick="toggleCalSub(this)"
           aria-pressed="${subs.has(c.key) ? "true" : "false"}"
           title="${esc(c.description || "")}">${esc(c.name)} <span class="muted">${c.count}</span></button>`).join("");
    }
    function toggleCalSub(btn) {
      const subs = agSubs(); const k = btn.dataset.k;
      subs.has(k) ? subs.delete(k) : subs.add(k);
      agSaveSubs(subs); renderAgendaCals(); renderAgenda();
    }

    function agWhen(e) {
      return e.next_occurrence
        ? `<span class="pill ok">${esc(e.next_occurrence)}</span>`
        : `<span class="pill" title="exact date moves each year">${e.month ? esc(_MONTHS[e.month-1]) : esc(e.cadence||"")}</span>`;
    }
    // Feed id -> {name, url} from the calendar directory, for the visible provenance
    // pill on imported events (maintainer 2026-07-17: "when clicking on events, the
    // source should be clear"). Lazy: reuses the Calendars panel's _feedDir when
    // loaded, else kicks ONE best-effort background load (loopback) and falls back
    // to the family name meanwhile — agRow never blocks on it.
    let _agFeedMap = null, _agFeedMapAsked = false;
    function _agFeedById() {
      if (_agFeedMap) return _agFeedMap;
      if (_feedDir) {
        _agFeedMap = {};
        for (const fam of (_feedDir.families || [])) {
          for (const f of (fam.feeds || [])) {
            if (f && f.id) _agFeedMap[f.id] = { name: f.name || f.id, url: f.url || "" };
          }
        }
        return _agFeedMap;
      }
      if (!_agFeedMapAsked) {
        _agFeedMapAsked = true;
        api("/api/events/feeds").then(d => { _feedDir = d; _agFeedMap = null; }).catch(() => {});
      }
      return null;
    }
    function agRow(e) {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const conf = e.deduced
        ? `<span class="pill warn" title="${esc(T("A date your articles mention — deduced from text, never confirmed."))}">${esc(T("deduced · never confirmed"))}</span>`
        : e.confirmed ? '<span class="pill ok" title="fixed annual date">confirmed</span>'
                      : '<span class="pill" title="follow the official source for the exact date">approx · check source</span>';
      const tags = (e.tags||[]).map(t => `<span class="ag-tag" onclick="$('agenda-tag').value='${esc(t)}';renderAgenda()">${esc(t)}</span>`).join("");
      const alsoIn = (e.also_in && e.also_in.length) ? ` <span class="pill" title="this event also appears in: ${esc(e.also_in.join(', '))}">also in ${e.also_in.length}</span>` : "";
      const imp = (e.imported && e.source_count > 1)
        ? ` <span class="pill" title="${esc((e.family_names || [e.family_name || ""]).filter(Boolean).join(', '))}">${e.source_count}×</span>` : "";
      // Visible provenance on every imported event: WHICH feed(s) delivered it —
      // feed name(s) + URL(s) in the hover (the #oo-tip layering convention), the
      // first provider named in the pill itself. Falls back to the family name
      // until the directory map loads.
      let prov = "";
      if (e.imported && Array.isArray(e.sources) && e.sources.length) {
        const fm = _agFeedById();
        const names = e.sources.map(id => (fm && fm[id] && fm[id].name) || id);
        const detail = e.sources.map(id => fm && fm[id] ? `${fm[id].name} — ${fm[id].url}` : id).join("\n");
        const label = names[0] + (names.length > 1 ? ` +${names.length - 1}` : "");
        prov = ` <span class="pill" title="${esc(T("Calendar feed(s) this event came from:") + "\n" + detail)}">${esc(T("from"))} ${esc(label)}</span>`;
      } else if (e.imported && e.family_name) {
        prov = ` <span class="pill" title="${esc(T("Imported calendar folder"))}">${esc(T("from"))} ${esc(e.family_name)}</span>`;
      }
      const variants = (e.date_variants && e.date_variants.length > 1)
        ? `<div class="hint" style="color:var(--warn)">date varies by source: ${esc(e.date_variants.join(' · '))}</div>` : "";
      const src = e.official_url ? " · " + extLink(e.official_url, "official source ↗") : "";
      // The event title opens the unified analysis window over this event in your
      // corpus (maintainer 2026-06-16: agenda content "highly visible and clickable").
      // A DEDUCED event opens its EXACT article set (the dates came from those
      // articles); other events open a search over the title.
      const openExpr = (e.deduced && Array.isArray(e.article_ids) && e.article_ids.length)
        ? `openAnalysisForIds(${esc(JSON.stringify(e.article_ids))}, ${esc(JSON.stringify(e.title))})`
        : `openAnalysisFor(${esc(JSON.stringify(e.title))})`;
      const titleEl = `<b class="ag-evtitle" style="cursor:pointer" title="Open in analysis — explore this event in your corpus" onclick="event.stopPropagation();${openExpr}">${esc(e.title)}</b>`;
      return `<div class="ag-row"><div class="ag-when">${agWhen(e)}</div>
        <div class="ag-body"><div>${titleEl} <span class="pill">${esc(e.category)}</span> ${e.country&&e.country!=='INT'?`<span class="pill">${esc(e.country)}</span>`:""} ${conf}${alsoIn}${imp}${prov}</div>
          ${variants}
          <div class="hint">${tags} ${e.note?"· "+esc(e.note):""}${src}</div></div></div>`;
    }
    // -- Agenda views: MONTH grid (the ruled default) + the original list ----- //
    // The tab shows DATA only (maintainer principle 2026-06-11): calendar
    // subscriptions and the feed directory live in Settings -> Agenda.
    // The chosen VIEW (month/week/list/…) stays a per-device UI preference in localStorage
    // (the subscriptions moved server-side; which layout you last looked at is transient,
    // per-device display state — MONTH remains the ruled default).
    function agView() { return localStorage.getItem("oo.agenda.view") || "month"; }
    function agendaSetView(v) { localStorage.setItem("oo.agenda.view", v); if (_agViewTabs) _agViewTabs.paint(v); renderAgenda(); }
    let _agViewTabs = null;                          // the Month·Week·List ooSubtabs handle
    const AGV = { y: null, m: null, day: null };   // displayed month (m = 1-12) + picked day
    // Category filter: colored chips replaced the dropdown (ruled 2026-06-15,
    // Item C). The taxonomy is data-driven (derived from the catalog facets), so a
    // new category (e.g. "religious") appears as a chip automatically. Distinct,
    // separable hues; the translated label stays the real identifier (colour is
    // decorative). Single-select with toggle-off.
    let _agCat = "";
    const AG_CAT_HUE = { civic: 210, political: 0, economic: 140, technology: 280, religious: 45, other: 30 };
    function agCatHue(c) {
      if (AG_CAT_HUE[c] != null) return AG_CAT_HUE[c];
      let h = 0; for (let i = 0; i < c.length; i++) h = (h * 31 + c.charCodeAt(i)) >>> 0;
      return h % 360;
    }
    function renderAgendaCatChips() {
      const box = $("agenda-cats"); if (!box) return;
      // Labels are the English category slugs (all keyed ×12) emitted as DOM text,
      // so the i18n engine translates them live on a language switch.
      const chips = [`<button type="button" class="ag-catchip${_agCat === "" ? " on" : ""}" onclick="agSetCat('')">all</button>`];
      for (const c of (AG.categories || [])) {
        chips.push(`<button type="button" class="ag-catchip${_agCat === c ? " on" : ""}" style="--cat:${agCatHue(c)}" onclick="agSetCat('${esc(c)}')"><span class="ag-catdot"></span>${esc(c)}</button>`);
      }
      box.innerHTML = chips.join("");
    }
    function agSetCat(c) { _agCat = (_agCat === c) ? "" : c; renderAgendaCatChips(); renderAgenda(); }
    // ISO-2 → regional-indicator flag emoji (offline, zero-asset). The country CODE
    // stays visible beside it as the unambiguous identifier — a flag is a visual
    // convention, never the sole label (flags ≠ identity; some entities have none,
    // and emoji flags render inconsistently on some platforms).
    function agFlag(cc) {
      if (!cc) return "";
      cc = cc.toUpperCase();
      if (/^[A-Z]{2}$/.test(cc)) return String.fromCodePoint(...[...cc].map(ch => 0x1F1E6 + ch.charCodeAt(0) - 65));
      return "\u{1F310}";   // globe for INT / non-ISO entities
    }
    function agLocale() { return document.documentElement.lang || "en"; }
    // The concrete anchor date the views pivot on (picked day, else 1st of the
    // displayed month, else today) — drives the Week window.
    function agAnchorDate() {
      if (AGV.y == null) return new Date();
      return new Date(AGV.y, AGV.m - 1, AGV.day || 1);
    }
    function agPickDate(y, m, d) { AGV.y = y; AGV.m = m; AGV.day = d; renderAgenda(); }
    function agMonthShift(d) {
      // Audit fix 2026-07-17: the old single-step wraparound (`if (m<1){m=12;y--}
      // if (m>12){m=1;y++}`) only ever handled a +-1 shift correctly -- it hardcoded
      // month 12 / month 1 regardless of how far m had actually gone, so Trimester
      // (+-3) and Semester (+-6) nav landed on the WRONG month across a year
      // boundary (e.g. Feb 2026 - 3 months gave "December 2025" instead of the
      // correct "November 2025"). True modular arithmetic over a 0-based total
      // month count handles any shift correctly, including the plain +-1 case.
      const total = AGV.y * 12 + (AGV.m - 1) + d;
      const y = Math.floor(total / 12);
      const m = ((total % 12) + 12) % 12 + 1;
      AGV.y = y; AGV.m = m; AGV.day = null; renderAgenda();
    }
    function agWeekShift(d) {
      const a = agAnchorDate(); a.setDate(a.getDate() + d * 7);
      AGV.y = a.getFullYear(); AGV.m = a.getMonth() + 1; AGV.day = a.getDate(); renderAgenda();
    }
    // The nav bar (‹ · label · › · Today) is shared by Month and Week — dispatch
    // by the active view so one bar serves both.
    function agNavShift(d) {
      const v = agView();
      if (v === "week") agWeekShift(d);
      else if (v === "year") agYearShift(d);
      else if (v === "decade") agYearShift(d * 10);
      else if (v === "trimester") agMonthShift(d * 3);
      else if (v === "semester") agMonthShift(d * 6);
      else agMonthShift(d);
    }
    function agYearShift(d) { AGV.y = (AGV.y || new Date().getFullYear()) + d; AGV.day = null; renderAgenda(); }
    // YEAR view (Item C remaining): a 12-month overview — per-month event counts +
    // a few honest chips; click a month to drill into the Month grid. Annual rules
    // (e.month) and this year's dated instances are both counted.
    function renderAgendaYear(rows) {
      const box = $("agenda-year"), loc = agLocale(), y = AGV.y;
      const byMonth = {}; for (let m = 1; m <= 12; m++) byMonth[m] = [];
      for (const e of rows) {
        if (e.month) byMonth[e.month].push(e);
        else if (e.next_occurrence && +e.next_occurrence.slice(0, 4) === y) byMonth[+e.next_occurrence.slice(5, 7)].push(e);
      }
      const now = new Date(), curY = now.getFullYear(), curM = now.getMonth() + 1;
      let cards = "";
      for (let m = 1; m <= 12; m++) {
        const evs = byMonth[m];
        const name = new Intl.DateTimeFormat(loc, { month: "long" }).format(new Date(y, m - 1, 1));
        const isCur = y === curY && m === curM;
        const chips = evs.slice(0, 4).map(e =>
          `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}">${esc(e.title.length > 20 ? e.title.slice(0, 19) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 4 ? `<span class="ag-more">+${evs.length - 4}</span>` : "";
        cards += `<div class="ag-ycard${isCur ? " today" : ""}${evs.length ? " has" : ""}" onclick="agOpenMonth(${m})" title="${esc(name)}">
          <div class="ag-ymon">${esc(name)} <span class="muted">${evs.length || ""}</span></div>${chips}${more}</div>`;
      }
      box.innerHTML = `<div class="ag-ygrid">${cards}</div>`;
    }
    function agOpenMonth(m) { AGV.m = m; AGV.day = null; agendaSetView("month"); }
    function agOpenMonthYear(y, m) { AGV.y = y; AGV.m = m; AGV.day = null; agendaSetView("month"); }
    function agOpenYear(y) { AGV.y = y; AGV.day = null; agendaSetView("year"); }
    // Count the events that fall in a given (year, month) — the SAME placement rule
    // the Year view uses: annual rules by e.month, plus dated instances whose
    // next_occurrence lands in that exact year-month. Returns the matching events.
    function agEventsInMonth(rows, y, m) {
      const ym = `${y}-${String(m).padStart(2, "0")}`, out = [];
      for (const e of rows) {
        if (e.month === m) out.push(e);
        else if (e.next_occurrence && e.next_occurrence.slice(0, 7) === ym && !out.includes(e)) out.push(e);
      }
      return out;
    }
    // One clickable month summary card (the Year view's .ag-ycard grammar, reused).
    function agMonthCard(rows, y, m, loc, curY, curM) {
      const evs = agEventsInMonth(rows, y, m);
      const name = new Intl.DateTimeFormat(loc, { month: "long", year: "numeric" }).format(new Date(y, m - 1, 1));
      const isCur = y === curY && m === curM;
      const chips = evs.slice(0, 4).map(e =>
        `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}">${esc(e.title.length > 20 ? e.title.slice(0, 19) + "…" : e.title)}</span>`).join("");
      const more = evs.length > 4 ? `<span class="ag-more">+${evs.length - 4}</span>` : "";
      return `<div class="ag-ycard${isCur ? " today" : ""}${evs.length ? " has" : ""}" onclick="agOpenMonthYear(${y},${m})" title="${esc(name)}">
        <div class="ag-ymon">${esc(name)} <span class="muted">${evs.length || ""}</span></div>${chips}${more}</div>`;
    }
    // TRIMESTER (3 months) + SEMESTER (6 months): a row of consecutive month
    // summary cards anchored on the displayed month — same data path + same click
    // (→ that Month grid) as the Year view. `span` = 3 or 6.
    function renderAgendaMonths(rows, span) {
      const box = $("agenda-months"), loc = agLocale();
      const now = new Date(), curY = now.getFullYear(), curM = now.getMonth() + 1;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let y = AGV.y, m = AGV.m;
      const months = [];
      for (let i = 0; i < span; i++) { months.push([y, m]); m++; if (m > 12) { m = 1; y++; } }
      const start = months[0], end = months[span - 1];
      $("agenda-monthlabel").textContent =
        new Intl.DateTimeFormat(loc, { month: "short", year: "numeric" }).format(new Date(start[0], start[1] - 1, 1)) + " – " +
        new Intl.DateTimeFormat(loc, { month: "short", year: "numeric" }).format(new Date(end[0], end[1] - 1, 1));
      const total = months.reduce((n, [yy, mm]) => n + agEventsInMonth(rows, yy, mm).length, 0);
      if (!total) { box.innerHTML = `<div class="muted">${esc(t9("No events in this period."))}</div>`; return; }
      box.innerHTML = `<div class="ag-mgrid">` + months.map(([yy, mm]) => agMonthCard(rows, yy, mm, loc, curY, curM)).join("") + `</div>`;
    }
    // DECADE: a 10-year overview, the Year view's year-summary scaled to a per-year
    // cell × 10. Each cell counts the year's events (annual rules + that year's dated
    // instances) and links to that Year view. Decade anchored on the floor-10 year.
    function renderAgendaDecade(rows) {
      const box = $("agenda-decade"), loc = agLocale(), now = new Date(), curY = now.getFullYear();
      const y0 = Math.floor((AGV.y || curY) / 10) * 10;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      $("agenda-monthlabel").textContent = `${y0}–${y0 + 9}`;
      // Per-year count: annual rules count once a year; dated instances count in
      // their own year (same placement the Year view applies, summed over months).
      const yearCount = (y) => {
        let n = 0;
        for (const e of rows) {
          if (e.month) n++;
          else if (e.next_occurrence && +e.next_occurrence.slice(0, 4) === y) n++;
        }
        return n;
      };
      let cells = "";
      for (let y = y0; y < y0 + 10; y++) {
        const n = yearCount(y), isCur = y === curY;
        cells += `<div class="ag-ycard${isCur ? " today" : ""}${n ? " has" : ""}" onclick="agOpenYear(${y})" title="${y}">
          <div class="ag-ymon">${y} <span class="muted">${n || ""}</span></div></div>`;
      }
      box.innerHTML = `<div class="ag-dgrid">${cells}</div>`;
    }
    function agNavToday() {
      const t = new Date(); AGV.y = t.getFullYear(); AGV.m = t.getMonth() + 1;
      AGV.day = t.getDate(); renderAgenda();
    }
    function agFiltered() {
      const subs = agSubs();
      const cat = _agCat, country = $("agenda-country").value, tag = $("agenda-tag").value;
      const subOnly = $("agenda-subonly").checked;
      return AG.events.filter(e =>
        (!cat || e.category === cat) && (!country || e.country === country) &&
        (!tag || (e.tags||[]).includes(tag)) &&
        // imported events were explicitly imported -> always shown (bypass subscribed-only)
        (!subOnly || e.imported || (e.sources || [e.calendar]).some(s => subs.has(s))));
    }
    function agShowDay(d) { AGV.day = d; renderAgenda(); }
    // T11: the astronomy layer (Meeus, computed locally) — moon glyphs in the
    // month grid; method+accuracy ride the hover convention (informed consent).
    let _astroYear = null, _astroByDate = {}, _seasonByDate = {};
    async function _ensureAstro(year) {
      if (_astroYear === year) return;
      try {
        const d = await api(`/api/events/astronomy?year=${year}`);
        _astroByDate = {}; _seasonByDate = {};
        for (const fm of (d.full_moons || [])) _astroByDate[fm.date] = {glyph: "\u{1F315}", kind: "full", time: fm.time_utc, method: d.method, acc: d.accuracy};
        for (const nm of (d.new_moons || [])) _astroByDate[nm.date] = {glyph: "\u{1F311}", kind: "new", time: nm.time_utc, method: d.method, acc: d.accuracy};
        // Seasons (equinoxes/solstices, Meeus ch.27) — named astronomically
        // (hemisphere-honest); a solstice sun glyph, an equinox star.
        for (const s of (d.seasons || [])) {
          _seasonByDate[s.date] = {glyph: /solstice/i.test(s.event) ? "☀" : "✦",
            name: s.event, time: s.time_utc, method: d.method, acc: d.accuracy};
        }
        _astroYear = year;
      } catch (_e) { _astroByDate = {}; _seasonByDate = {}; _astroYear = null; }
    }
    // The day-of-month (1..31) of the Nth `weekday` (0=Mon..6=Sun) of month m/year y
    // — week=-1 is the LAST; null when it doesn't exist (e.g. a 5th Friday). Mirrors
    // catalog.nth_weekday so floating events ("3rd Tuesday of March") place every year.
    function nthWeekday(y, m, weekday, week) {
      const ndays = new Date(y, m, 0).getDate();                      // days in month m (1-based)
      const dow = d => (new Date(y, m - 1, d).getDay() + 6) % 7;      // -> 0=Mon … 6=Sun
      if (week === -1) return ndays - ((dow(ndays) - weekday + 7) % 7);
      if (week == null || week < 1) return null;
      const day = 1 + ((weekday - dow(1) + 7) % 7) + (week - 1) * 7;
      return day <= ndays ? day : null;
    }
    function renderAgendaMonth(rows) {
      const box = $("agenda-month"), dayBox = $("agenda-day");
      if (AGV.y == null) { const t = new Date(); AGV.y = t.getFullYear(); AGV.m = t.getMonth() + 1; }
      const y = AGV.y, m = AGV.m, loc = agLocale();
      $("agenda-monthlabel").textContent =
        new Intl.DateTimeFormat(loc, { month: "long", year: "numeric" }).format(new Date(y, m - 1, 1));
      // Events on a specific day of THIS grid: annual rules (month+day, any year)
      // + dated instances (next_occurrence inside exactly this year-month).
      const ym = `${y}-${String(m).padStart(2, "0")}`;
      const byDay = {}, monthOnly = [];
      for (const e of rows) {
        if (e.month === m && e.day) (byDay[e.day] = byDay[e.day] || []).push(e);
        // FLOATING rule (e.g. 3rd Tuesday of March): compute the day for THIS browsed
        // year so it places correctly every year, not only the one next_occurrence holds.
        else if (e.month === m && e.weekday != null && e.week != null) {
          const fd = nthWeekday(y, m, e.weekday, e.week);
          if (fd) (byDay[fd] = byDay[fd] || []).push(e);
        }
        else if (e.next_occurrence && e.next_occurrence.slice(0, 7) === ym) {
          const d = +e.next_occurrence.slice(8, 10);
          if (!(byDay[d] || []).includes(e)) (byDay[d] = byDay[d] || []).push(e);
        } else if (e.month === m && !e.day) monthOnly.push(e);
      }
      // Monday-start grid (4-6 week rows), days outside the month dimmed.
      const first = new Date(y, m - 1, 1), daysIn = new Date(y, m, 0).getDate();
      const lead = (first.getDay() + 6) % 7;                  // Mon=0 … Sun=6
      const cells = [], prevDays = new Date(y, m - 1, 0).getDate();
      for (let i = 0; i < lead; i++) cells.push({ d: prevDays - lead + 1 + i, out: true });
      for (let d = 1; d <= daysIn; d++) cells.push({ d, out: false });
      for (let nd = 1; cells.length % 7; nd++) cells.push({ d: nd, out: true });
      const t = new Date();
      const inThisMonth = t.getFullYear() === y && t.getMonth() + 1 === m;
      const t9m = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const wd = [...Array(7)].map((_, i) =>
        new Intl.DateTimeFormat(loc, { weekday: "short" }).format(new Date(2024, 0, i + 1))); // 2024-01-01 was a Monday
      let html = `<div class="ag-grid ag-grid-head">` + wd.map(w => `<div class="ag-wd">${esc(w)}</div>`).join("") + `</div>`;
      html += `<div class="ag-grid">` + cells.map((c) => {
        if (c.out) return `<div class="ag-cell out"><span class="ag-dn">${c.d}</span></div>`;
        const evs = byDay[c.d] || [];
        const today = inThisMonth && t.getDate() === c.d;
        const iso = `${y}-${String(m).padStart(2, "0")}-${String(c.d).padStart(2, "0")}`;
        const moon = _astroByDate[iso];
        const moonHtml = moon
          ? `<span class="ag-moon" style="float:inline-end;font-size:11px" title="${esc((moon.kind === "full" ? t9m("Full moon") : t9m("New moon")) + " " + moon.time + " UTC — " + moon.method + "; " + moon.acc)}">${moon.glyph}</span>`
          : "";
        const season = _seasonByDate[iso];
        const seasonHtml = season
          ? `<span class="ag-season" style="float:inline-end;font-size:11px;margin-inline-end:2px" title="${esc(t9m(season.name) + " " + season.time + " UTC — " + season.method + "; " + season.acc)}">${season.glyph}</span>`
          : "";
        const chips = evs.slice(0, 3).map(e =>
          `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}${e.confirmed ? "" : " — exact date moves; check the official source"}">${esc(e.title.length > 22 ? e.title.slice(0, 21) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 3 ? `<span class="ag-more">+${evs.length - 3}</span>` : "";
        return `<div class="ag-cell${today ? " today" : ""}${evs.length ? " has" : ""}${AGV.day === c.d ? " sel" : ""}" onclick="agShowDay(${c.d})">
          <span class="ag-dn">${c.d}</span>${moonHtml}${seasonHtml}${chips}${more}</div>`;
      }).join("") + `</div>`;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (monthOnly.length)
        html += `<div class="hint" style="margin-top:8px"><span>${esc(t9("This month — no fixed day:"))}</span> ` +
          monthOnly.map(e => `<span class="ag-tag" title="${esc(e.title)}">${esc(e.title)}</span>`).join(" ") + `</div>`;
      box.innerHTML = html;
      // Day detail under the grid: the familiar honest rows for the picked day.
      if (AGV.day && (byDay[AGV.day] || []).length) {
        const label = new Intl.DateTimeFormat(loc, { dateStyle: "full" }).format(new Date(y, m - 1, AGV.day));
        dayBox.innerHTML = `<h3 style="font-size:13px;margin:12px 0 6px">${esc(label)}</h3>` +
          byDay[AGV.day].map(agRow).join("");
      } else dayBox.innerHTML = "";
    }
    // Events falling on ONE concrete date: annual rules (month+day, any year) +
    // dated instances (next_occurrence === that ISO date). Shared by the Week view.
    function agEventsOn(rows, dt) {
      const y = dt.getFullYear(), m = dt.getMonth() + 1, d = dt.getDate();
      const iso = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const out = [];
      for (const e of rows) {
        if (e.month === m && e.day === d) out.push(e);
        else if (e.next_occurrence === iso && !out.includes(e)) out.push(e);
      }
      return out;
    }
    // WEEK view (ruled 2026-06-15, Item C): the Monday-start 7-day window around
    // the anchor date — taller day columns with more events, the same honest chips
    // + moon glyphs as the month grid; click a day for its detail below.
    function renderAgendaWeek(rows) {
      const box = $("agenda-week"), dayBox = $("agenda-day"), loc = agLocale();
      const anchor = agAnchorDate();
      const monday = new Date(anchor); monday.setDate(anchor.getDate() - ((anchor.getDay() + 6) % 7));
      const days = [...Array(7)].map((_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return d; });
      const sunday = days[6];
      $("agenda-monthlabel").textContent =
        new Intl.DateTimeFormat(loc, { month: "short", day: "numeric" }).format(monday) + " – " +
        new Intl.DateTimeFormat(loc, { month: "short", day: "numeric", year: "numeric" }).format(sunday);
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const now = new Date();
      const same = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
      const monthsInWeek = new Set(days.map(d => d.getMonth() + 1));
      let html = `<div class="ag-grid">` + days.map(d => {
        const evs = agEventsOn(rows, d);
        const isToday = same(d, now);
        const isSel = AGV.day === d.getDate() && AGV.m === d.getMonth() + 1 && AGV.y === d.getFullYear();
        const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        const moon = _astroByDate[iso];
        const moonHtml = moon
          ? `<span class="ag-moon" style="float:inline-end;font-size:11px" title="${esc((moon.kind === "full" ? t9("Full moon") : t9("New moon")) + " " + moon.time + " UTC — " + moon.method + "; " + moon.acc)}">${moon.glyph}</span>`
          : "";
        const wd = new Intl.DateTimeFormat(loc, { weekday: "short" }).format(d);
        const dn = new Intl.DateTimeFormat(loc, { day: "numeric", month: "short" }).format(d);
        const chips = evs.slice(0, 6).map(e =>
          `<span class="ag-chip${e.confirmed ? "" : " approx"}" title="${esc(e.title)}${e.confirmed ? "" : " — exact date moves; check the official source"}">${esc(e.title.length > 30 ? e.title.slice(0, 29) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 6 ? `<span class="ag-more">+${evs.length - 6}</span>` : "";
        return `<div class="ag-cell${isToday ? " today" : ""}${evs.length ? " has" : ""}${isSel ? " sel" : ""}" onclick="agPickDate(${d.getFullYear()},${d.getMonth() + 1},${d.getDate()})">
          <div class="ag-wd">${esc(wd)} <span class="ag-wd-d">${esc(dn)}</span>${moonHtml}</div>${chips}${more}</div>`;
      }).join("") + `</div>`;
      const monthOnly = rows.filter(e => e.month && !e.day && !e.next_occurrence && monthsInWeek.has(e.month));
      if (monthOnly.length)
        html += `<div class="hint" style="margin-top:8px"><span>${esc(t9("This week — no fixed day:"))}</span> ` +
          monthOnly.map(e => `<span class="ag-tag" title="${esc(e.title)}">${esc(e.title)}</span>`).join(" ") + `</div>`;
      box.innerHTML = html;
      const picked = AGV.day ? new Date(AGV.y, AGV.m - 1, AGV.day) : null;
      if (picked && picked >= days[0] && picked <= sunday) {
        const evs = agEventsOn(rows, picked);
        if (evs.length) {
          const label = new Intl.DateTimeFormat(loc, { dateStyle: "full" }).format(picked);
          dayBox.innerHTML = `<h3 style="font-size:13px;margin:12px 0 6px">${esc(label)}</h3>` + evs.map(agRow).join("");
        } else dayBox.innerHTML = "";
      } else dayBox.innerHTML = "";
    }
    function renderAgenda() {
      renderAgendaCals();
      const view = agView();
      if (_agViewTabs) _agViewTabs.paint(view);
      const isMonth = view === "month", isWeek = view === "week", isYear = view === "year", isList = view === "list";
      const isTri = view === "trimester", isSem = view === "semester", isDec = view === "decade";
      const hasBar = isMonth || isWeek || isYear || isTri || isSem || isDec;
      $("agenda-monthbar").style.display = hasBar ? "" : "none";
      $("agenda-month").style.display = isMonth ? "" : "none";
      $("agenda-week").style.display = isWeek ? "" : "none";
      $("agenda-months").style.display = (isTri || isSem) ? "" : "none";
      $("agenda-year").style.display = isYear ? "" : "none";
      $("agenda-decade").style.display = isDec ? "" : "none";
      $("agenda-day").style.display = (isMonth || isWeek) ? "" : "none";
      $("agenda-list").style.display = isList ? "" : "none";
      $("agenda-group-wrap").style.display = isList ? "" : "none";
      const rows = agFiltered();
      $("agenda-monthhint").textContent = AG.caveat || "";
      if (AGV.y == null && hasBar) { const _t = new Date(); AGV.y = _t.getFullYear(); AGV.m = _t.getMonth() + 1; }
      if (isMonth) {
        _ensureAstro(AGV.y).then(() => renderAgendaMonth(rows));
        return;
      }
      if (isWeek) {
        _ensureAstro(agAnchorDate().getFullYear()).then(() => renderAgendaWeek(rows));
        return;
      }
      if (isTri) { renderAgendaMonths(rows, 3); return; }
      if (isSem) { renderAgendaMonths(rows, 6); return; }
      if (isDec) { renderAgendaDecade(rows); return; }
      if (isYear) {
        $("agenda-monthlabel").textContent = String(AGV.y);
        renderAgendaYear(rows);
        return;
      }
      const box = $("agenda-list");
      const groupBy = $("agenda-group").value;
      const tt = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!rows.length) { box.innerHTML = `<p class="hint">${esc(AG.caveat)}</p><div class="muted">${esc(tt("No events this month — adjust filters or subscribe to more calendars in Settings."))}</div>`; return; }
      const groups = {};
      for (const e of rows) {
        const k = groupBy === "month" ? (e.next_occurrence ? _MONTHS[+e.next_occurrence.slice(5,7)-1] : (e.month ? _MONTHS[e.month-1] : "Movable / no fixed date"))
                : groupBy === "calendar" ? (AG.meta[e.calendar]?.name || e.calendar)
                : (e.country || "—");
        (groups[k] = groups[k] || []).push(e);
      }
      box.innerHTML = `<p class="hint">${esc(AG.caveat)} · showing ${rows.length} of ${AG.events.length}</p>` +
        Object.entries(groups).map(([k, list]) =>
          `<h3 style="font-size:13px;margin:12px 0 6px">${esc(k)} <span class="muted">${list.length}</span></h3>` + list.map(agRow).join("")).join("");
    }

    // ===================================================================== //
    //  GOVERNMENTS tab (maintainer chat 2026-06-22): per-country data + a
    //  world-map choropleth + the law tracker, as subtabs over the existing
    //  vintaged official-statistics store (/api/governments/*). Honesty carried:
    //  a value is a producer's published figure (never a score), a gap is a gap.
    // ===================================================================== //
