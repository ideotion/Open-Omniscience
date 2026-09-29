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
        // Each family's KEY beside its name, index for index: a user calendar's only
        // source is its family key, and agRow names it from here.
        families: e.families || (e.family ? [e.family] : []),
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
        AG.countries = fac.countries || [];
        _agFillCountryOptions();
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

    // Q308 rules PICKERS specifically -- "by localised name, the code as a
    // secondary column" -- which is why this surface shows BOTH where an
    // ordinary cell shows the code alone (Q302). An <option> carries no
    // reliable hover, so the layered form Q302 relies on is not available here
    // and the more specific ruling is the one that can actually be honoured.
    // The VALUE stays the stored alpha-2: a picker that silently changed what
    // it submits would break every filter reading it.
    // The names AND their order are the reader's language, so a switch rebuilds the
    // options from the facet list drawn last -- never a fetch -- keeping the pick
    // (2026-09-27 re-walk, L-3: they stayed English, in English order, until a reload).
    function _agFillCountryOptions() {
      const sel = $("agenda-country"); if (!sel || !AG.countries) return;
      const cur = sel.value;
      sel.innerHTML = '<option value="">all</option>' +
        AG.countries.slice().sort(ooCountryCompare).map(x => {
          const code = ooCountryCode(x), name = ooCountryName(x, "");
          const label = name && name !== code ? `${name} (${code})` : code;
          return `<option value="${esc(x)}">${agFlag(x)} ${esc(label)}</option>`;
        }).join("");
      sel.value = cur;
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
    // The cadence is stored as its CODE ("weekly"); the list shows the same label the
    // Period picker does, through the same keys (M14).
    const _BUL_CADENCE_LABEL = {daily: "Daily", weekly: "Weekly", monthly: "Monthly",
      trimester: "Trimester", semester: "Semester", yearly: "Yearly"};
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
    // WHAT A LANGUAGE SWITCH REPAINTS FROM (K-repaint). Every line this panel writes was
    // composed in the language on screen at the time, and none of it is a key the DOM
    // walker could match again, so the Review, the list, the gate and the status lines
    // all stayed in the old language after a switch. They keep their INPUTS instead --
    // the payloads they drew and each status line as its key and values -- and
    // `_bulRepaint` (called from app-boot's one `oo:langchange` listener) redraws from
    // those. It never fetches.
    let _bulGate = null, _bulView = null, _bulEditions = null, _bulPrivacyData = null;
    const _bulMsgs = {};
    function _bulSay(id, key, vars) {
      _bulMsgs[id] = {key, vars: vars || null};
      _bulPaintMsg(id);
    }
    function _bulPaintMsg(id) {
      const el = $(id), m = _bulMsgs[id];
      if (!el || !m) return;
      el.textContent = m.vars ? _bulTf(m.key, m.vars) : _bulT(m.key);
    }
    // A story's shared terms, each through the ONE keyword label (re-walk M-3/M-5): the
    // Review listed a Russian story's terms bare in a French UI. The row names the term's
    // RECORDED language and nothing more -- the review translates nothing, so a foreign
    // term reads "in Russian", and a term in the reader's own language carries no tag.
    // Rendered from the payload at paint time, so `_bulRepaint` renames the language
    // after a switch without a fetch. kwLabelHtml marks each term data-i18n-dyn.
    function _bulStoryTermsHtml(s) {
      const rows = (s && s.shared_term_rows && s.shared_term_rows.length)
        ? s.shared_term_rows
        : ((s && s.shared_terms) || []).map((term) => ({term: term}));
      if (!rows.length) return "—";
      if (typeof kwLabelHtml !== "function") {
        return `<span data-i18n-dyn>${esc(rows.map((r) => r.term).join(", "))}</span>`;
      }
      const ui = String(typeof uiLangCode === "function" ? uiLangCode() : "en").split("-")[0].toLowerCase();
      return rows.map((r) => {
        const lang = String(r.language || "").trim().toLowerCase();
        const row = {term: r.term, normalized: r.normalized || r.term};
        if (lang && lang !== "?" && lang.split("-")[0] !== ui) {
          row.translation_source_lang = lang;
          row.translation_tier = "untranslated";
        }
        return kwLabelHtml(row, {inButton: true});
      }).join(", ");
    }

    function _bulRepaint() {
      _bulPaintGate();
      if (_bulEditions) _bulPaintEditions();
      if (_bulView && _bulFile) { _bulRender(_bulView); _bulPaintPrivacy(); }
      for (const id of Object.keys(_bulMsgs)) _bulPaintMsg(id);
    }

    function _bulQuery() {
      const p = new URLSearchParams();
      if (_bulExcludeSections.size) p.set("exclude_sections", [..._bulExcludeSections].join(","));
      if (_bulExcludeStories.size) p.set("exclude_stories", [..._bulExcludeStories].join(","));
      const lang = _bulLang();
      if (lang) p.set("lang", lang);
      return p;
    }
    // The document is written in the language the operator is READING the app in.
    // ONE helper for every URL that renders an edition -- the report and the annexes
    // (through _bulQuery) and the editions list's Open -- so no two of them can come
    // out in different languages: Open built its own URL without it and opened an
    // English document on a French page (2026-09-27 re-walk, M-12). null = English,
    // the server's default, so an English reader's URL is unchanged.
    function _bulLang() {
      const lang = (window.OOI18N && OOI18N.current) ? OOI18N.current() : "en";
      return lang && lang !== "en" ? lang : null;
    }

    async function loadBulletin() {
      const gate = $("bulletin-gate"), controls = $("bulletin-controls");
      if (!gate) return;
      let g = null;
      try { g = await api("/api/bulletin/availability"); }
      catch (e) { _bulSay("bulletin-gate", "Could not check this machine: {error}", {error: e.message}); return; }
      delete _bulMsgs["bulletin-gate"];
      _bulGate = g;
      _bulPaintGate();
      _bulSyncIntroOptIn();
      if (g.available) await loadBulletinEditions();
    }

    // THE OPENING'S OPT-IN (register ruling D2, placed by RC08.2 = a). An edition
    // opens on the fixed paragraph; this setting lets a narration run ALSO hand the
    // opening to the model. It is the server's setting rather than a page-local
    // flag, so the narrate endpoint reads the same answer this box shows.
    async function _bulSyncIntroOptIn() {
      const cb = $("bul-narrate-intro"); if (!cb) return;
      try {
        const s = await api("/api/settings");
        cb.checked = !!s.bulletin_narrate_introduction;
      } catch (e) { cb.checked = false; }
      if (!cb.dataset.wired) {
        cb.dataset.wired = "1";
        cb.addEventListener("change", async () => {
          try {
            await api("/api/settings", {method: "PUT",
              body: JSON.stringify({bulletin_narrate_introduction: cb.checked})});
          } catch (e) { _bulSyncIntroOptIn(); }
        });
      }
    }

    function _bulPaintGate() {
      const g = _bulGate, gate = $("bulletin-gate"), controls = $("bulletin-controls");
      if (!g || !gate || !controls) return;
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
      // TWO VERDICTS (ruled 2026-09-07, open question 4): the document is produced
      // on any machine and only the NARRATION layer is gated. Reading `available`
      // for both would draw a checkbox that cannot work and say nothing about why,
      // so the model verdict is rendered on its own control -- disabled, unticked,
      // with the hardware reason beside it rather than a failure at build time.
      _bulPaintNarrationGate(g);
    }

    function _bulPaintNarrationGate(g) {
      const box = $("bul-narrate-gate"), cb = $("bul-narrate"), lbl = $("bul-narrate-label");
      if (!cb) return;
      const ok = g.narration_available !== false;
      cb.disabled = !ok;
      if (!ok) cb.checked = false;
      if (lbl) lbl.style.opacity = ok ? "" : ".6";
      const ib = $("bul-narrate-intro"), il = $("bul-narrate-intro-label");
      if (ib) ib.disabled = !ok;
      if (il) il.style.opacity = ok ? "" : ".6";
      if (!box) return;
      box.hidden = ok;
      if (ok) { box.textContent = ""; return; }
      // The reason is the gate's own words. Paraphrasing a hardware fact into a
      // second wording is how two surfaces come to disagree about one machine.
      box.textContent = _bulTf("Narration is unavailable on this machine: {reason}",
        {reason: g.narration_reason || _bulT("this machine cannot practically run a local model")})
        + " " + _bulT("The document is complete without it.");
    }

    async function loadBulletinEditions() {
      const box = $("bulletin-list");
      if (!box) return;
      let d = null;
      try { d = await api("/api/bulletin/editions"); }
      catch (e) {
        _bulEditions = null;
        box.innerHTML = `<div class="muted">${esc(_bulTf("Could not list editions: {error}", {error: e.message}))}</div>`;
        return;
      }
      _bulEditions = d.editions || [];
      _bulPaintEditions();
    }

    function _bulPaintEditions() {
      const box = $("bulletin-list"), rows = _bulEditions || [];
      if (!box) return;
      if (!rows.length) {
        box.innerHTML = `<div class="muted">${esc(_bulT("No editions yet. Build a draft above."))}</div>`;
        return;
      }
      box.innerHTML = `<div style="overflow:auto"><table><tr>
          <th>${esc(_bulT("Covers through"))}</th><th>${esc(_bulT("Period"))}</th><th></th></tr>` +
        rows.map(r => `<tr>
          <td>${esc(r.covers_through || r.filename)}</td>
          <td>${esc(r.cadence ? _bulT(_BUL_CADENCE_LABEL[r.cadence] || r.cadence) : "—")}</td>
          <td class="row" style="gap:6px;justify-content:flex-end">
            <button class="secondary" data-on-click="bulletinReview(${esc(JSON.stringify(r.filename))})">${esc(_bulT("Review"))}</button>
            <button class="secondary" data-on-click="bulletinOpenFile(${esc(JSON.stringify(r.filename))})">${esc(_bulT("Open"))}</button>
            <button class="secondary" data-on-click="bulletinDelete(${esc(JSON.stringify(r.filename))})">${esc(_bulT("Delete"))}</button>
          </td></tr>`).join("") + "</table></div>";
    }

    async function bulletinGenerate(btn) {
      const cadence = ($("bul-cadence") || {}).value || "weekly";
      const narrate = !!($("bul-narrate") || {}).checked;
      btn.disabled = true;
      _bulSay("bulletin-status", "Building…");
      try {
        const out = await api(
          `/api/bulletin/generate?cadence=${encodeURIComponent(cadence)}&persist=true&narrate=${narrate}`,
          {method: "POST"});
        if (out.persisted) _bulSay("bulletin-status", "Draft built.");
        else _bulSay("bulletin-status", "Built, but not saved: {error}", {error: out.persist_error || ""});
        await loadBulletinEditions();
        if (out.filename) bulletinReview(out.filename);
      } catch (e) {
        _bulSay("bulletin-status", "Could not build: {error}", {error: e.message});
      } finally { btn.disabled = false; }
    }

    async function bulletinReview(filename) {
      const box = $("bulletin-review");
      if (!box) return;
      // A status line belongs to the edition it was about: opening ANOTHER one drops it,
      // while re-reading the same one (after narration finishes) keeps it on screen.
      if (filename !== _bulFile) delete _bulMsgs["bul-pub"];
      _bulFile = filename;
      _bulView = null;
      _bulPrivacyData = null;
      _bulExcludeSections = new Set();
      _bulExcludeStories = new Set();
      box.innerHTML = `<div class="muted">${esc(_bulT("Loading…"))}</div>`;
      let v = null;
      try { v = await api(`/api/bulletin/editions/${encodeURIComponent(filename)}/review`); }
      catch (e) { box.innerHTML = `<div class="muted">${esc(_bulTf("Could not open this edition: {error}", {error: e.message}))}</div>`; return; }
      _bulView = v;
      _bulRender(v);
      // The §18 enumeration is fetched right after the review renders, so it is on
      // screen before the operator reaches the download button rather than after.
      _bulPrivacy();
    }

    // ONE renderer for a narrated unit's label and per-sentence verdicts, shared by
    // the introduction and (through the same shape) by every story. Written once so
    // the two cannot come to disagree about what "dropped" looks like.
    function _bulUnit(u) {
      const sents = (u.sentences || []).map(x => x.kept
        ? `<li>${esc(x.text)}</li>`
        : `<li class="muted"><s>${esc(x.text)}</s> — ${esc(_bulT("dropped; not in the evidence:"))} ${esc((x.unsupported || []).join(", "))}</li>`
      ).join("");
      const label = u.narrated
        ? `<div class="warn">${esc(_bulT("AI-derived — unreliable"))}${u.partial ? esc(_bulT("; sentences naming something absent from the sources were removed")) : ""}</div>`
        // A non-narrated unit WITHOUT a reason is not a failure: since D2 every edition
        // opens on the fixed template by default, and "No model text:" followed by
        // nothing read as a failure nobody explained (caught in the row H walk).
        : (u.fallback_reason
          ? `<div class="muted">${esc(_bulTf("No model text: {reason}", {reason: u.fallback_reason}))}</div>`
          : `<div class="muted">${esc(_bulT("Fixed text from the edition's own counts; no model wrote it."))}</div>`);
      return `<div style="margin:8px 0">${label}<div>${esc(u.text || "")}</div>` +
        (sents ? `<ul style="margin:4px 0 0 12px">${sents}</ul>` : "") + `</div>`;
    }

    function _bulRender(v) {
      // One style for the Review's two checkbox rows, sections and stories, so they cannot
      // come to disagree: the box keeps its natural size beside a label that wraps itself.
      const _BUL_CHECK_ROW = "gap:8px;align-items:baseline;flex-wrap:nowrap";
      const _BUL_CHECK_BOX = "width:auto;flex:none;margin:0;padding:0";
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
          ? ` <span class="warn">${esc(_bulTf("window: {days} days", {days: w.days}))}</span>` : "";
        // A skip reason is a FIXED producer sentence where it can be (keyed x12), and
        // data where it carries a number; `_bulT` returns the latter unchanged.
        const why = s.error
          ? ` <span class="warn">${esc(_bulT("failed:"))} ${esc(s.error)}</span>`
          : (s.skipped ? ` <span class="muted">${esc(_bulTf("skipped: {reason}", {reason: s.skipped_i18n
              // A reason carrying a number is a FRAME plus its values (click-through B16, V5).
              ? _bulTf(s.skipped_i18n, s.skipped_vars || {}) : _bulT(s.skipped)}))}</span>` : "");
        // The heading the DOCUMENT prints for this section (render.py `_section_heading`:
        // the slug humanised and capitalised), through the same keys -- the raw slug
        // ("rising concepts") was the one English word left in a translated review.
        const slug = String(s.section).replace(/_/g, " ");
        const heading = _bulT(slug.charAt(0).toUpperCase() + slug.slice(1));
        // The checkbox sits INLINE with its label (click-through B16, V6): app.css gives
        // every input `width:100%`, so inside this wrapping flex row the box took a line of
        // its own and pushed the section name under it.
        return `<label class="row" style="${_BUL_CHECK_ROW}">
          <input type="checkbox" style="${_BUL_CHECK_BOX}" ${off ? "" : "checked"} data-on-change="bulletinToggleSection(${esc(JSON.stringify(s.section))})">
          <span style="flex:1;min-width:0"><strong>${esc(heading)}</strong>
            <span class="muted">${esc(_bulTf("{n} row(s)", {n: s.rows}))}</span>${win}${why}</span></label>`;
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
          : `<div class="muted">${esc(_bulTf("No model text: {reason}", {reason: s.fallback_reason || ""}))}</div>`;
        // Each count is ONE keyed frame chosen by the count, the singular key for one (the
        // app's "{n} article" / "{n} articles" pair): a number welded to a plural noun read
        // "1 sources" beside "one source only" (click-through B17, T4). A locale whose plural
        // has more forms than two writes its "many" frame as a label and a count.
        const nArt = Number(s.articles) || 0, nSrc = Number(s.distinct_sources) || 0;
        const counts = _bulTf(nArt === 1 ? "{n} article" : "{n} articles", {n: fmtNum(nArt, 0)})
          + " · " + _bulTf(nSrc === 1 ? "{n} source" : "{n} sources", {n: fmtNum(nSrc, 0)});
        return `<div style="margin:8px 0">
          <label class="row" style="${_BUL_CHECK_ROW}">
            <input type="checkbox" style="${_BUL_CHECK_BOX}" ${off ? "" : "checked"} data-on-change="bulletinToggleStory('${esc(s.key)}')">
            <span style="flex:1;min-width:0"><strong>${_bulStoryTermsHtml(s)}</strong>
              <span class="muted">${esc(counts)}${s.single_source ? esc(_bulT(" · one source only")) : ""}</span></span></label>
          ${label}${sents ? `<ul style="margin:4px 0 0 26px">${sents}</ul>` : ""}</div>`;
      }).join("");

      // The introduction is a Layer-B unit like any other, so it owes the same
      // per-sentence account (§13). Shown ABOVE the sections because that is where
      // it sits in the document: an operator reviewing what a model wrote should
      // meet the opening paragraph first, exactly as a reader will.
      const intro = v.introduction
        ? `<h4 style="margin:12px 0 4px">${esc(_bulT("Introduction"))}</h4>` + _bulUnit(v.introduction)
        : "";

      box.innerHTML = `<h3 style="margin:0 0 4px">${esc(_bulT("Review"))} ${state}</h3>
        <p class="hint" style="margin-top:0">${esc(_bulT(v.caveat || ""))}</p>
        <p class="hint">${esc(_bulT(v.method || ""))}</p>
        ${intro}
        <h4 style="margin:12px 0 4px">${esc(_bulT("Sections"))}</h4>${secs || `<div class="muted">${esc(_bulT("None."))}</div>`}
        ${stories ? `<h4 style="margin:12px 0 4px">${esc(_bulT("Stories"))}</h4>${stories}` : ""}
        <div class="row" style="gap:8px;margin-top:12px;flex-wrap:wrap">
          <button class="secondary" data-on-click="bulletinNarrate(this)" id="bul-narrate-run">${esc(_bulT("Narrate with the local model"))}</button>
          <button class="secondary" data-on-click="bulletinOpen('html')">${esc(_bulT("Preview"))}</button>
          <button class="secondary" data-on-click="bulletinDownloadBundle(this)">${esc(_bulT("Download report + annexes"))}</button>
          <button class="secondary" data-on-click="bulletinOpen('markdown')">${esc(_bulT("Report only"))}</button>
          <button data-on-click="bulletinPublish(this)">${esc(_bulT("Publish"))}</button>
          <div id="bul-pub" class="hint" style="align-self:center"></div>
        </div>
        <p class="hint">${esc(_bulT("The annexes are one Markdown file per article the report cites, numbered to match, with a contents page. They carry the sources' own text — keep them where you keep the corpus."))}</p>
        <div id="bul-privacy" class="hint" style="margin-top:8px"></div>`;
      _bulPaintMsg("bul-pub");
    }

    // §18: what a READER of the export can see, stated where the operator clicks —
    // and BEFORE the click, not in a dialog after it. Rendered as part of the review
    // rather than behind a toggle, because informed consent in this app is visible by
    // default; the long form lives in the note inside the ZIP.
    //
    // It is measured against the SAME selection the download will use, or it would
    // describe a different file from the one about to be sent.
    async function _bulPrivacy() {
      const box = $("bul-privacy");
      if (!box || !_bulFile) return;
      const q = _bulQuery(); q.set("kind", "annexes");
      try {
        _bulPrivacyData = {d: await api(`/api/bulletin/editions/${encodeURIComponent(_bulFile)}/export-privacy?${q}`)};
      } catch (e) { _bulPrivacyData = {error: e.message}; }
      _bulPaintPrivacy();
    }

    // The enumeration's own sentences are FIXED server strings (privacy.py), keyed x12
    // like every other caveat: the what, why and caveat are the consent text an operator
    // reads before a file leaves the machine, and they were the one English block left.
    function _bulPaintPrivacy() {
      const box = $("bul-privacy"), p = _bulPrivacyData;
      if (!box || !p) return;
      if (p.error != null) {
        // A failed enumeration is an UNANSWERED question, never an all-clear. Saying
        // so is the whole point of the tri-state underneath it.
        box.textContent = _bulTf("What a reader of these files could see could not be listed: {error}",
          {error: p.error}) + " " + _bulT("That is an unanswered question, not an all-clear.");
        return;
      }
      const d = p.d || {};
      const rows = (d.items || []).map(it => {
        const mark = it.present === true
          ? (it.n != null ? `${_bulT("yes")} (${it.n})` : _bulT("yes"))
          : (it.present === false ? _bulT("no") : _bulT("NOT MEASURED"));
        return `<li><strong>${esc(_bulT(it.what))}</strong> — ${esc(mark)}<br>
          <span class="muted">${esc(_bulT(it.why_it_matters))}</span></li>`;
      }).join("");
      box.innerHTML = `<strong>${esc(_bulT("What a reader of these files can see"))}</strong>
        <p class="muted" style="margin:4px 0">${esc(_bulT(d.caveat || ""))}</p>
        <ul style="margin:4px 0 0 18px">${rows}</ul>`;
    }

    function bulletinToggleSection(key) {
      if (_bulExcludeSections.has(key)) _bulExcludeSections.delete(key);
      else _bulExcludeSections.add(key);
      _bulPrivacy();
    }
    function bulletinToggleStory(key) {
      if (_bulExcludeStories.has(key)) _bulExcludeStories.delete(key);
      else _bulExcludeStories.add(key);
      _bulPrivacy();
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
      const q = _bulQuery();
      const base = `/api/bulletin/editions/${encodeURIComponent(_bulFile)}`;
      btn.disabled = true;
      _bulSay("bul-pub", "Building the annexes…");
      try {
        const rq = new URLSearchParams(q); rq.set("fmt", "markdown");
        const report = await fetch(`${base}/render?${rq}`);
        await _throwIfNotOk(report);
        _saveBlob(await report.blob(), _filenameOf(report, "bulletin.md"));

        const zip = await fetch(`${base}/annexes?${q}`);
        await _throwIfNotOk(zip);
        const n = zip.headers.get("X-OO-Annex-Articles");
        _saveBlob(await zip.blob(), _filenameOf(zip, "annexes.zip"));
        if (n && n !== "0") _bulSay("bul-pub", "Downloaded: the report and {n} annexed article(s).", {n: n});
        else _bulSay("bul-pub", "Downloaded the report. This edition names no articles, so the annexes are empty — regenerate it to populate them.");
      } catch (e) {
        _bulSay("bul-pub", "Could not download: {error}", {error: e.message});
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
      const p = new URLSearchParams();
      const lang = _bulLang();
      if (lang) p.set("lang", lang);
      p.set("fmt", "html");
      window.open(
        `/api/bulletin/editions/${encodeURIComponent(filename)}/render?${p}`, "_blank", "noopener");
    }

    // Narration is a BACKGROUND JOB (§14), not a request that returns when the model
    // is done: on a long run that would be a multi-minute synchronous handler, which
    // is the freeze family this app has paid for three times. So this STARTS it and
    // returns, and the task manager is where the run is watched and stopped.
    //
    // RESUME IS THE DEFAULT. Nothing here sends restart=true: discarding a paused run
    // has to be an explicit act, because the loss only ever surfaces as a progress bar
    // back at zero.
    let _bulNarratePoll = null;

    async function bulletinNarrate(btn) {
      if (!_bulFile) return;
      btn.disabled = true;
      try {
        await api(`/api/bulletin/editions/${encodeURIComponent(_bulFile)}/narrate?${_bulQuery()}`,
          {method: "POST"});
        _bulSay("bul-pub", "Narrating in the background — watch it in the task manager.");
        _bulWatchNarration();
      } catch (e) {
        _bulSay("bul-pub", "Could not start narration: {error}", {error: e.message});
        btn.disabled = false;
      }
    }

    // The poll stops on a terminal state and re-reads the review, so the operator sees
    // the paragraphs appear. It never invents a percentage: the numbers are the job's
    // own done/total over UNITS, which is a real count of work, not an ETA.
    function _bulWatchNarration() {
      if (_bulNarratePoll) clearInterval(_bulNarratePoll);
      _bulNarratePoll = setInterval(async () => {
        let d = null;
        try { d = await api("/api/bulletin/narration"); }
        catch { clearInterval(_bulNarratePoll); _bulNarratePoll = null; return; }
        const job = d.job || {}, btn = $("bul-narrate-run");
        const n = {done: job.done || 0, total: job.total || 0};
        if (job.running) {
          _bulSay("bul-pub", "Narrating — units: {done} of {total}", n);
          return;
        }
        clearInterval(_bulNarratePoll); _bulNarratePoll = null;
        if (btn) btn.disabled = false;
        {
          // Three outcomes, three sentences. An ERROR is named rather than folded
          // into "finished" -- a run that lost its model must not read as a run that
          // had nothing to say -- and a CANCEL says how to resume, because the cursor
          // is saved and starting again continues rather than starts over.
          //
          // The state word is never interpolated: it arrives in English, and dropping
          // an English word into a translated sentence is the mixed-language defect
          // the frame-translates-data-does-not rule exists to prevent. Each state
          // gets its own keyable frame, and the counts stay label:value so nothing
          // has to conjugate with a number in twelve languages.
          if (job.state === "error") {
            _bulSay("bul-pub", "Narration stopped: {error}", {error: job.error || ""});
          } else if (job.state === "cancelled") {
            _bulSay("bul-pub",
              "Narration stopped — units: {done} of {total}. Start it again to resume.", n);
          } else {
            _bulSay("bul-pub", "Narration finished — units: {done} of {total}", n);
          }
        }
        if (_bulFile) bulletinReview(_bulFile);
      }, 3000);
    }

    async function bulletinPublish(btn) {
      if (!_bulFile) return;
      btn.disabled = true;
      try {
        const r = await api(
          `/api/bulletin/editions/${encodeURIComponent(_bulFile)}/publish?${_bulQuery()}`,
          {method: "POST"});
        _bulSay("bul-pub", "Published — the record itself is unchanged.");
        toast(_bulT("Published. Nothing was sent anywhere; the document is yours to share."));
        if (r) await loadBulletinEditions();
      } catch (e) { _bulSay("bul-pub", "Could not publish: {error}", {error: e.message}); }
      finally { btn.disabled = false; }
    }

    async function bulletinDelete(filename) {
      if (!confirm(_bulT("Delete this edition? The corpus is untouched — only the document goes."))) return;
      try {
        await api(`/api/bulletin/editions/${encodeURIComponent(filename)}`, {method: "DELETE"});
        if (_bulFile === filename) {
          _bulFile = null; _bulView = null; _bulPrivacyData = null; delete _bulMsgs["bul-pub"];
          $("bulletin-review").innerHTML = "";
        }
        await loadBulletinEditions();
      } catch (e) { toast(_bulTf("Could not delete: {error}", {error: e.message}), "err"); }
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
      // The option's VALUE stays the stored kind code; its text is the kind's keyed
      // English label, so the i18n walker translates the option both ways on a switch.
      // The codes were printed raw, and only `civic` had a key, so the menu read "tout,
      // civique, community, holidays" in French (2026-09-27 re-walk, U-3).
      $("feeddir-kind").innerHTML = '<option value="">all</option>' +
        kinds.map(k => `<option value="${esc(k)}">${esc(_feedKindLabel(k))}</option>`).join("");
      renderFeedDir();
      renderUserCalendars();
    }
    // A calendar family's KIND is a stored code (configs/calendar_feeds.yml); it shows
    // through a keyed label and a code with no label shows as stored. Capitalised
    // labels on purpose: "Science", "Space", "Civic" and "Other" are the World map's
    // existing keys, and a bare lowercase "science" key would also make the walker
    // translate a corpus keyword spelled that way (LESSONS 2026-09-16).
    const _FEED_KIND_LABEL = {
      holidays: "Public holidays", religion: "Religion", civic: "Civic",
      community: "Community", science: "Science", space: "Space", other: "Other",
    };
    function _feedKindLabel(k) { return _FEED_KIND_LABEL[k] || String(k == null ? "" : k); }
    function _verdictChip(v, feed) {
      if (!v) return '<span class="pill">not checked yet</span>';
      if (v.status === "ok") {
        const stale = v.stale_year ? ' <span class="pill warn">stale year</span>' : "";
        // "reachable · 12" was one text node no key matches; the word is keyed and
        // the count stays data (drawn by renderFeedDir, which repaints on a switch).
        return `<span class="pill ok">${esc(_bulT("reachable"))} · ${esc(fmtNum(v.events || 0, 0))}</span>${stale}`;
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
    // A family's NAME is catalogue text (configs/calendar_feeds.yml), in English. All but
    // two of the families the directory loads are "<Country> — public holidays", and those
    // are drawn from their parts: the country's name in the reader's language through the
    // one ooCountryName, in a keyed frame. The others go through their own keys, and a
    // name in any other shape (a subdivision, a family a later catalogue adds) shows as
    // stored. The rows read "Afghanistan — public holidays" in every locale
    // (2026-09-27 re-walk, U-3).
    function _feedFamName(f) {
      const name = String(f.name || f.key || "");
      if (f.kind === "holidays" && f.country && name.endsWith(" — public holidays")) {
        const cn = ooCountryName(f.country, "");
        if (cn && cn !== ooCountryCode(f.country)) return _bulTf("{country} — public holidays", {country: cn});
      }
      return _bulT(name);
    }
    // Sorted by the name ON SCREEN, in the reader's language, so a French list does not
    // run in English order (the L-3 lesson of the Agenda's Country picker): every
    // comparator takes that name order as its third argument.
    const _FEED_SORTS = {
      name: (a, b, byName) => byName(a, b),
      country: (a, b, byName) => (a.country || "￿").localeCompare(b.country || "￿") || byName(a, b),
      kind: (a, b, byName) => (a.kind || "").localeCompare(b.kind || "") || byName(a, b),
      // dysfunctional first, so problems surface (the maintainer's "find the broken ones")
      status: (a, b, byName) => ({ error: 0, unchecked: 1, ok: 2 }[famStatus(a)] - { error: 0, unchecked: 1, ok: 2 }[famStatus(b)]) || byName(a, b),
      imported: (a, b, byName) => ((b.imported_events || 0) - (a.imported_events || 0)) || byName(a, b),
    };
    function _feedDirFiltered() {
      if (!_feedDir) return [];
      const kind = $("feeddir-kind").value, q = ($("feeddir-q").value || "").toLowerCase();
      const sf = $("feeddir-status-filter").value, sort = $("feeddir-sort").value || "name";
      const shown = new Map(_feedDir.families.map(f => [f, _feedFamName(f)]));
      const lc = (window.OOI18N && OOI18N.current && OOI18N.current()) || "en";
      const coll = new Intl.Collator(lc);
      const byName = (a, b) => coll.compare(shown.get(a), shown.get(b));
      // The search matches the name on screen AND the catalogue's own, so an English
      // query still finds a row a French reader sees translated.
      const fams = _feedDir.families.filter(f =>
        (!kind || f.kind === kind) &&
        (!sf || famStatus(f) === sf) &&
        (!q || shown.get(f).toLowerCase().includes(q) || f.name.toLowerCase().includes(q)
            || (f.country || "").toLowerCase().includes(q)));
      const cmp = _FEED_SORTS[sort] || _FEED_SORTS.name;
      fams.sort((a, b) => cmp(a, b, byName));
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
      // Keyed frames with the counts as data (2026-09-27 re-walk, U-3 / L-8): the line
      // was one English literal with a t()'d tail welded on, so it read "241 feeds ·
      // 241 folders · 0 checked · 241 pas encore vérifié". It is composed here, so
      // app-boot.js's oo:langchange listener redraws it -- the walker cannot.
      const n = (x) => fmtNum(x || 0, 0);
      $("feeddir-status").innerHTML =
        esc(_bulTf("{feeds} feeds · {folders} folders · {checked} checked", {
          feeds: n(_feedDir.total_feeds), folders: n(_feedDir.families.length), checked: n(_feedDir.checked) })) +
        (_v.unchecked
          ? ` <span class="muted" title="${esc(_v.method ? t(_v.method) : "")}">· ${esc(_bulTf("{n} not checked yet", {n: n(_v.unchecked)}))}</span>`
          : "");
      const bulk = `<div class="row" style="gap:6px;margin-bottom:8px;align-items:center;flex-wrap:wrap">
        <button class="secondary tiny" data-on-click="agExcludeBulk('dysfunctional')">Exclude dysfunctional</button>
        <button class="secondary tiny" data-on-click="agExcludeBulk('shown')">Exclude shown</button>
        ${excl.size ? `<button class="ghost tiny" data-on-click="agExcludeClear()">Clear exclusions</button>
          <span class="hint">${excl.size} <span>excluded</span></span>` : ""}</div>`;
      $("feeddir-list").innerHTML = bulk + fams.map(f => {
        const feeds = f.feeds.map(fd => `
          <div class="vr">
            <span>${esc(fd.provider)}${fd.year_pinned ? ` <span class="muted">· ${fd.year_pinned}</span>` : ""}</span>
            <b>${_verdictChip(fd.verdict, fd)}
              <button class="ghost tiny" data-on-click="feedAction('${esc(fd.id)}','verify')">Verify</button>
              <button class="secondary tiny" data-on-click="feedAction('${esc(fd.id)}','import')">Import</button></b>
          </div>
          <div class="hint" style="word-break:break-all;margin:0 0 4px"><a href="${esc(fd.url)}" target="_blank" rel="noopener noreferrer">${esc(fd.url)}</a></div>`).join("");
        const isExcl = excl.has(f.key);
        return `<details class="cs-row${isExcl ? " excluded" : ""}" style="padding:6px 10px">
          <summary style="cursor:pointer">${esc(_feedFamName(f))}
            ${f.duplicates ? `<span class="pill" title="Several providers publish this calendar — compare them below">${esc(_bulTf("{n} sources", {n: n(f.feeds.length)}))}</span>` : ""}
            ${f.imported_events ? `<span class="pill ok">${esc(_bulTf("{n} imported", {n: n(f.imported_events)}))}</span>` : ""}
            ${isExcl ? `<span class="pill warn">excluded</span>` : ""}
            <span class="muted">· ${esc(t(_feedKindLabel(f.kind)))}${f.country ? " · " + ooCountryCell(f.country) : ""}</span>
            <button class="ghost tiny" style="float:inline-end" data-on-click="ooPreventStop(event);agToggleExclude(${esc(JSON.stringify(f.key))})">${isExcl ? "Include" : "Exclude"}</button></summary>
          ${feeds}</details>`;
      }).join("") + (total > 40 ? `<div class="hint">${esc(_bulTf("+{n} — type to filter", {n: n(total - 40)}))}</div>` : "");
    }
    // A language switch redraws the directory from the payload it holds -- never a
    // fetch. Guarded on the status line, which only renderFeedDir writes: `_feedDir`
    // alone is not enough, since the Agenda's provenance pills load it without the
    // directory ever being opened (2026-09-27 re-walk, U-3).
    function repaintFeedDirFromCache() {
      const st = $("feeddir-status");
      if (_feedDir && st && st.textContent.trim()) renderFeedDir();
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
        `<button class="ghost tiny" data-on-click="removeUserCalendar('${esc(f.key)}')">Remove</button></div>`).join("");
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
        `<button class="ag-cal${subs.has(c.key) ? " on" : ""}" data-k="${esc(c.key)}" data-on-click="toggleCalSub(this)"
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
        : `<span class="pill" title="exact date moves each year">${e.month ? esc(_agMonth(e.month-1)) : esc(e.cadence||"")}</span>`;
    }
    // Election date-confidence tiers (src/civic/elections.py, maintainer ruling
    // 2026-07-14, V1_PATHWAY §4.5): catalog.agenda() annotates every ELECTIONS-calendar
    // event with date_confidence + date_caveat (and, for a projected entry, a
    // projection object) -- this was computed on every response and never rendered
    // (audit P1-04). Four renderable states: scheduled / window / projected, plus a
    // PASSED sub-state -- a projected date that has gone by with no confirmed result,
    // which the backend module frames as an investigative lead, never a routine caveat,
    // and deliberately never re-projects to a next cycle. date_confidence is null for
    // every non-election event AND for the refusal-1 gap (an election with no sourced
    // date at all), so callers fall back to the plain e.confirmed pill exactly as
    // before whenever it is absent -- non-election calendars must not regress.
    // Never reads e.cadence for anything: the backend deliberately doesn't either
    // (free prose, not a sourced recurrence rule), and re-reading it here would be the
    // same fabrication risk one layer up.
    function agElectionTier(e) {
      if (e.date_confidence == null) return null;
      if (e.date_confidence === "projected" && e.projection && e.projection.status === "passed")
        return "passed";
      return e.date_confidence;                      // "scheduled" | "window" | "projected"
    }
    // ONE {pill class, chip class, short label} map so the full pill (agRow) and the
    // small grid chips (Year / Month-card / Month-grid / Week) can never disagree
    // about what a tier means. PASSED gets its own colour + class -- distinguishable
    // from a routine "approx" chip, never blended into it.
    const _AG_TIER_META = {
      scheduled: { pillCls: "ok",           chipCls: "",          label: "scheduled" },
      window:    { pillCls: "tier-window",  chipCls: "tier-window", label: "window" },
      projected: { pillCls: "warn",         chipCls: "approx",    label: "projected" },
      passed:    { pillCls: "err",          chipCls: "leadpassed", label: "projected · passed" },
    };
    // The confidence pill for one full row (agRow / the day-detail lists): tier-aware
    // for elections, byte-identical to the pre-existing markup for everything else.
    function agConfPill(e) {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (e.deduced)
        return `<span class="pill warn" title="${esc(T("A date your articles mention — deduced from text, never confirmed."))}">${esc(T("deduced · never confirmed"))}</span>`;
      const tier = agElectionTier(e);
      if (tier) {
        const meta = _AG_TIER_META[tier];
        const glyph = tier === "passed" ? "⚑ " : "";     // the lead marker, untranslated
        return `<span class="pill ${meta.pillCls}" title="${esc(T(e.date_caveat || ""))}">${glyph}${esc(T(meta.label))}</span>`;
      }
      return e.confirmed ? '<span class="pill ok" title="fixed annual date">confirmed</span>'
                          : '<span class="pill" title="follow the official source for the exact date">approx · check source</span>';
    }
    // The small calendar-grid chips' modifier class -- tier-aware for elections,
    // "approx"/"" for everything else exactly as before.
    function agChipCls(e) {
      const tier = agElectionTier(e);
      return tier ? _AG_TIER_META[tier].chipCls : (e.confirmed ? "" : "approx");
    }
    // The chips' hover-title suffix: the backend's OWN translated caveat for a tier,
    // else `fallback` (which a call site sets to its pre-existing suffix, or "" where
    // none existed) -- so a non-election chip's title is untouched by this change.
    function agChipTitleSuffix(e, fallback) {
      const tier = agElectionTier(e);
      if (!tier) return fallback || "";
      if (!e.date_caveat) return "";
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return " — " + T(e.date_caveat);
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
      // Every sentence on the row is ONE keyed frame with its values as variables, so a
      // locale orders and punctuates it itself -- "also in 2" and "from Nager" were built
      // by gluing an English word to a number or a name (click-through B16, V3).
      const tfa = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s2, v) =>
        String(s2).replace(/\{(\w+)\}/g, (m2, k) => (v && v[k] != null) ? v[k] : m2));
      const conf = agConfPill(e);
      const tags = (e.tags||[]).map(t => `<span class="ag-tag" data-on-click="ooSetValue('agenda-tag', '${esc(t)}');renderAgenda()">${esc(t)}</span>`).join("");
      const alsoIn = (e.also_in && e.also_in.length)
        ? ` <span class="pill" title="${esc(tfa("This event also appears in: {calendars}", {calendars: e.also_in.join(", ")}))}">`
          + `${esc(tfa("also in {n}", {n: e.also_in.length}))}</span>` : "";
      const imp = (e.imported && e.source_count > 1)
        ? ` <span class="pill" title="${esc((e.family_names || [e.family_name || ""]).filter(Boolean).join(', '))}">${e.source_count}×</span>` : "";
      // Visible provenance on every imported event: WHICH feed(s) delivered it —
      // feed name(s) + URL(s) in the hover (the #oo-tip layering convention), the
      // first provider named in the pill itself. Falls back to the family name
      // until the directory map loads.
      let prov = "";
      if (e.imported && Array.isArray(e.sources) && e.sources.length) {
        const fm = _agFeedById();
        // A calendar the user added (.ics upload or URL) is its own family, and its only
        // "feed" is the family key ("user-harbour-a"), which the bundled directory never
        // lists -- so the pill read that internal key (click-through B17, T3). The event
        // carries each family's key beside its name; a source with no directory entry
        // that IS one of those keys is named by the calendar's own name.
        const famName = (id) => {
          const i = Array.isArray(e.families) ? e.families.indexOf(id) : -1;
          if (i >= 0 && Array.isArray(e.family_names) && e.family_names[i]) return e.family_names[i];
          return id === e.calendar && e.family_name ? e.family_name : null;
        };
        const names = e.sources.map(id => (fm && fm[id] && fm[id].name) || famName(id) || id);
        const detail = e.sources.map(id => fm && fm[id] ? `${fm[id].name} — ${fm[id].url}` : (famName(id) || id)).join("\n");
        const label = names[0] + (names.length > 1 ? ` +${names.length - 1}` : "");
        prov = ` <span class="pill" title="${esc(T("Calendar feed(s) this event came from:") + "\n" + detail)}">${esc(tfa("from {feed}", {feed: label}))}</span>`;
      } else if (e.imported && e.family_name) {
        prov = ` <span class="pill" title="${esc(T("Imported calendar folder"))}">${esc(tfa("from {feed}", {feed: e.family_name}))}</span>`;
      }
      const variants = (e.date_variants && e.date_variants.length > 1)
        ? `<div class="hint" style="color:var(--warn)">${esc(tfa("date varies by source: {dates}", {dates: e.date_variants.join(" · ")}))}</div>` : "";
      // agenda-span-display (2026-09-09). `_span_for`, `_span_end_date`,
      // `_in_active_range` and the origin_year/until_year fields shipped with their
      // own test file on 2026-07-31 and REACHED NO SURFACE: app-agenda.js read
      // neither `e.span` nor the year range, so a month-span event ("Dry January",
      // a multi-day summit) rendered as a single START DAY and a recurrence that
      // has ended simply stopped appearing with nothing said. The catalogue had the
      // answer and the reader could not see it.
      //
      // ASSERTED, NOT DEDUCED: every value here comes from the event catalogue's
      // own explicitly-stated fields — `_span_for` is built "only from explicitly
      // stated start+end, never guessed" — so this is the same catalogue-asserted
      // class the source facts carry, and the hover says so.
      //
      // `until_year` is worded about the LISTING rather than the world: the
      // catalogue suppresses occurrences past that year, which is a fact about what
      // this app will show, not a claim that the event will never happen again.
      const catalogNote = esc(T("Stated by the event catalog (asserted, not deduced)."));
      let span = "";
      if (e.span && e.span.start && e.span.end) {
        const text = e.span.active
          ? tfa("On now, ends {end}", {end: e.span.end})
          : tfa("Runs {start} – {end}", {start: e.span.start, end: e.span.end});
        span = ` <span class="pill${e.span.active ? " ok" : ""}" title="${catalogNote}">${esc(text)}</span>`;
      }
      const years = [
        e.origin_year != null ? tfa("since {year}", {year: e.origin_year}) : null,
        e.until_year != null ? tfa("nothing listed after {year}", {year: e.until_year}) : null,
      ].filter(Boolean).join(" · ");
      const yearNote = years
        ? ` <span class="muted" title="${catalogNote}">· ${esc(years)}</span>` : "";
      const src = e.official_url ? " · " + extLink(e.official_url, T("official source ↗")) : "";
      // The event title opens the unified analysis window over this event in your
      // corpus (maintainer 2026-06-16: agenda content "highly visible and clickable").
      // A DEDUCED event opens its EXACT article set (the dates came from those
      // articles); other events open a search over the title.
      const openExpr = (e.deduced && Array.isArray(e.article_ids) && e.article_ids.length)
        ? `openAnalysisForIds(${esc(JSON.stringify(e.article_ids))}, ${esc(JSON.stringify(e.title))})`
        : `openAnalysisFor(${esc(JSON.stringify(e.title))})`;
      const titleEl = `<b class="ag-evtitle" style="cursor:pointer" title="Open in analysis — explore this event in your corpus" data-on-click="ooStop(event);${openExpr}">${esc(e.title)}</b>`;
      return `<div class="ag-row"><div class="ag-when">${agWhen(e)}</div>
        <div class="ag-body"><div>${titleEl} <span class="pill">${esc(e.category)}</span> ${e.country&&e.country!=='INT'?ooCountryCell(e.country,{cls:"pill"}):""} ${conf}${span}${alsoIn}${imp}${prov}${yearNote}</div>
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
      const chips = [`<button type="button" class="ag-catchip${_agCat === "" ? " on" : ""}" data-on-click="agSetCat('')">all</button>`];
      for (const c of (AG.categories || [])) {
        chips.push(`<button type="button" class="ag-catchip${_agCat === c ? " on" : ""}" style="--cat:${agCatHue(c)}" data-on-click="agSetCat('${esc(c)}')"><span class="ag-catdot"></span>${esc(c)}</button>`);
      }
      box.innerHTML = chips.join("");
    }
    function agSetCat(c) { _agCat = (_agCat === c) ? "" : c; renderAgendaCatChips(); renderAgenda(); }
    // ISO-2 → regional-indicator flag emoji (offline, zero-asset). The country CODE
    // stays visible beside it as the unambiguous identifier — a flag is a visual
    // convention, never the sole label (flags ≠ identity; some entities have none,
    // and emoji flags render inconsistently on some platforms).
    function agFlag(cc) {
      // Q307: the emoji is DERIVED from the alpha-2, which is itself derived from
      // whatever form the code arrives in. The old body gated on /^[A-Z]{2}$/ and
      // fell through to the globe for anything else -- correct while every code was
      // alpha-2, and it would have silently globed EVERY country the moment the
      // agenda started showing alpha-3. `ooCountryFlag` (app-core.js) owns the
      // derivation now, so the flag and the code on screen cannot disagree.
      if (!cc) return "";
      if (typeof ooCountryFlag === "function") return ooCountryFlag(cc);
      const up = String(cc).toUpperCase();
      if (/^[A-Z]{2}$/.test(up)) return String.fromCodePoint(...[...up].map(ch => 0x1F1E6 + ch.charCodeAt(0) - 65));
      return "\u{1F310}";   // globe for INT / non-ISO entities
    }
    function agLocale() { return document.documentElement.lang || "en"; }
    // A month's short name in the reader's language, through Intl like the grids'
    // weekday names, rather than the English _MONTHS array: the undated pill and the
    // "by month" headings read "Aug" on a French page -- the class the 2026-09-27
    // re-walk measured on the World map (L-6). Both redraw with renderAgenda on a switch.
    function _agMonth(i) {
      try {
        return new Intl.DateTimeFormat(agLocale(), {month: "short", timeZone: "UTC"}).format(Date.UTC(2001, i, 15));
      } catch (_e) { return _MONTHS[i] || ""; }
    }
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
          `<span class="ag-chip${agChipCls(e) ? " " + agChipCls(e) : ""}" title="${esc(e.title + agChipTitleSuffix(e))}">${esc(e.title.length > 20 ? e.title.slice(0, 19) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 4 ? `<span class="ag-more">+${evs.length - 4}</span>` : "";
        cards += `<div class="ag-ycard${isCur ? " today" : ""}${evs.length ? " has" : ""}" data-on-click="agOpenMonth(${m})" title="${esc(name)}">
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
        `<span class="ag-chip${agChipCls(e) ? " " + agChipCls(e) : ""}" title="${esc(e.title + agChipTitleSuffix(e))}">${esc(e.title.length > 20 ? e.title.slice(0, 19) + "…" : e.title)}</span>`).join("");
      const more = evs.length > 4 ? `<span class="ag-more">+${evs.length - 4}</span>` : "";
      return `<div class="ag-ycard${isCur ? " today" : ""}${evs.length ? " has" : ""}" data-on-click="agOpenMonthYear(${y},${m})" title="${esc(name)}">
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
        cells += `<div class="ag-ycard${isCur ? " today" : ""}${n ? " has" : ""}" data-on-click="agOpenYear(${y})" title="${y}">
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
        // imported events were explicitly imported -> always shown (bypass subscribed-only).
        // DEDUCED events bypass too (2026-08-20 matrix walk): they are derived from the
        // user's OWN corpus (mapDeducedToAgenda, "like imported events", 2026-06-16) and
        // their synthetic "deduced" calendar can never be subscribed — so with
        // #agenda-subonly defaulting CHECKED they were invisible in EVERY view at default
        // settings while the category filter still offered "deduced" as an empty lens.
        // The never-confirmed pill + note stay on every row; this only stops the default
        // filter suppressing a category it cannot admit.
        (!subOnly || e.imported || e.deduced || (e.sources || [e.calendar]).some(s => subs.has(s))));
    }
    function agShowDay(d) { AGV.day = d; renderAgenda(); }
    // T11: the astronomy layer (Meeus, computed locally) — moon glyphs in the
    // month grid; method+accuracy ride the hover convention (informed consent).
    let _astroYear = null, _astroByDate = {}, _seasonByDate = {};
    // [payload bucket, kind, glyph] for the four principal lunar phases.
    const _MOON_BUCKETS = [
      ["new_moons", "new", "\u{1F311}"],
      ["first_quarters", "first_quarter", "\u{1F313}"],
      ["full_moons", "full", "\u{1F315}"],
      ["last_quarters", "last_quarter", "\u{1F317}"],
    ];
    // ONE label map for the four phases, so the two grids (month and week) can
    // never disagree about what a glyph means. A kind with no entry falls back
    // to the kind itself rather than mislabelling it as one of the others.
    // The four season points, by the server's event id. The hover printed the id itself
    // ("june_solstice"), which is no key, so it read raw in every locale; the names are
    // the astronomical ones the server's naming rule prescribes (never "summer").
    function _seasonLabel(ev, tr) {
      const L = {march_equinox: "March equinox", june_solstice: "June solstice",
                 september_equinox: "September equinox", december_solstice: "December solstice"};
      return L[ev] ? tr(L[ev]) : String(ev || "");
    }
    function _moonLabel(kind, tr) {
      const L = {new: "New moon", first_quarter: "First quarter moon",
                 full: "Full moon", last_quarter: "Last quarter moon"};
      return L[kind] ? tr(L[kind]) : String(kind || "");
    }
    // The method + accuracy half of a moon or season hover. Both are FIXED sentences the
    // server sends (src/events/astronomy.py, Meeus), so they are keyed and translated
    // here; appended verbatim they read in English in every locale (the 2026-09-26
    // click-through, U9). One helper so the month and week grids cannot disagree.
    //
    // KEYED FRAMES, not joins (the 2026-09-26 leftovers, Y11): the two halves were
    // glued with a literal "; " and the hover with " UTC — ", so an Arabic hover read
    // an ASCII ";" between two Arabic sentences. Each locale now writes its own
    // separator. A half the server did not send is left out, never an empty slot.
    function _astroNote(x, tr, tfn) {
      const m = x.method ? tr(x.method) : "", a = x.acc ? tr(x.acc) : "";
      return (m && a) ? tfn("{method}; {accuracy}", { method: m, accuracy: a }) : (m || a);
    }
    // The whole hover: what, when (UTC, as the server computed it), and how.
    function _astroTitle(what, x, tr, tfn) {
      return tfn("{event} {time} UTC — {note}", { event: what, time: x.time, note: _astroNote(x, tr, tfn) });
    }
    async function _ensureAstro(year) {
      if (_astroYear === year) return;
      try {
        const d = await api(`/api/events/astronomy?year=${year}`);
        _astroByDate = {}; _seasonByDate = {};
        // The FOUR principal phases. The quarters were the one accepted loss when
        // the redundant moons ICS feed was retired (ruling 2026-07-17); they are
        // computed by the same Meeus ch.49 layer, so they carry the same method
        // and accuracy note and go through the same hover convention.
        for (const [bucket, kind, glyph] of _MOON_BUCKETS) {
          for (const ph of (d[bucket] || [])) {
            _astroByDate[ph.date] = {glyph: glyph, kind: kind, time: ph.time_utc, method: d.method, acc: d.accuracy};
          }
        }
        // Seasons (equinoxes/solstices, Meeus ch.27) — named astronomically
        // (hemisphere-honest); a solstice sun glyph, an equinox star.
        for (const s of (d.seasons || [])) {
          // The SEASON'S OWN method (Y11): Meeus ch. 27, which the server computes and
          // now sends as `seasons_method`. The hover used the payload's top-level method,
          // which is the MOON's (ch. 49) -- a method note naming the wrong computation.
          // No fallback to it: a season without its own method says only its accuracy.
          _seasonByDate[s.date] = {glyph: /solstice/i.test(s.event) ? "☀" : "✦",
            name: s.event, time: s.time_utc,
            method: d.seasons_method || "", acc: d.seasons_accuracy || d.accuracy};
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
      const tf9m = (window.OOI18N && OOI18N.tf) ? OOI18N.tf
        : ((x, v) => x.replace(/\{(\w+)\}/g, (mm, k) => (v && v[k] != null) ? String(v[k]) : mm));
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
          ? `<span class="ag-moon" style="float:inline-end;font-size:11px" title="${esc(_astroTitle(_moonLabel(moon.kind, t9m), moon, t9m, tf9m))}">${moon.glyph}</span>`
          : "";
        const season = _seasonByDate[iso];
        const seasonHtml = season
          ? `<span class="ag-season" style="float:inline-end;font-size:11px;margin-inline-end:2px" title="${esc(_astroTitle(_seasonLabel(season.name, t9m), season, t9m, tf9m))}">${season.glyph}</span>`
          : "";
        const chips = evs.slice(0, 3).map(e =>
          `<span class="ag-chip${agChipCls(e) ? " " + agChipCls(e) : ""}" title="${esc(e.title + agChipTitleSuffix(e, e.confirmed ? "" : " — exact date moves; check the official source"))}">${esc(e.title.length > 22 ? e.title.slice(0, 21) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 3 ? `<span class="ag-more">+${evs.length - 3}</span>` : "";
        return `<div class="ag-cell${today ? " today" : ""}${evs.length ? " has" : ""}${AGV.day === c.d ? " sel" : ""}" data-on-click="agShowDay(${c.d})">
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
      const tf9 = (window.OOI18N && OOI18N.tf) ? OOI18N.tf
        : ((x, v) => x.replace(/\{(\w+)\}/g, (mm, k) => (v && v[k] != null) ? String(v[k]) : mm));
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
          ? `<span class="ag-moon" style="float:inline-end;font-size:11px" title="${esc(_astroTitle(_moonLabel(moon.kind, t9), moon, t9, tf9))}">${moon.glyph}</span>`
          : "";
        const wd = new Intl.DateTimeFormat(loc, { weekday: "short" }).format(d);
        const dn = new Intl.DateTimeFormat(loc, { day: "numeric", month: "short" }).format(d);
        const chips = evs.slice(0, 6).map(e =>
          `<span class="ag-chip${agChipCls(e) ? " " + agChipCls(e) : ""}" title="${esc(e.title + agChipTitleSuffix(e, e.confirmed ? "" : " — exact date moves; check the official source"))}">${esc(e.title.length > 30 ? e.title.slice(0, 29) + "…" : e.title)}</span>`).join("");
        const more = evs.length > 6 ? `<span class="ag-more">+${evs.length - 6}</span>` : "";
        return `<div class="ag-cell${isToday ? " today" : ""}${evs.length ? " has" : ""}${isSel ? " sel" : ""}" data-on-click="agPickDate(${d.getFullYear()},${d.getMonth() + 1},${d.getDate()})">
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
        const k = groupBy === "month" ? (e.next_occurrence ? _agMonth(+e.next_occurrence.slice(5,7)-1) : (e.month ? _agMonth(e.month-1) : tt("Movable / no fixed date")))
                : groupBy === "calendar" ? (AG.meta[e.calendar]?.name || e.calendar)
                // Grouping by COUNTRY keys on the stored value (so two spellings of
                // one country cannot become two groups) and the heading renders the
                // alpha-3 below -- the key and the label are different jobs, and
                // keying on a rendered label is how a display change silently
                // re-partitions a list.
                : (e.country || "");
        (groups[k] = groups[k] || []).push(e);
      }
      // TWO NODES, deliberately. i18n.js's DOM walker matches a WHOLE text node
      // against a locale key (src/static/i18n.js `tr()`), so concatenating the
      // served caveat with a count produced one node that matched nothing: in
      // every non-English locale this line rendered the caveat in English AND
      // the bare English "showing 153 of 153" beside it (measured in Chromium at
      // fr and ja, 2026-09-09). The caveat gets its own node so the walker can
      // reach it -- the same paragraph the month view already translates -- and
      // the count is translated here, at render time, through the same
      // template-is-the-key rule the rest of this file uses (`_bulTf`), so the
      // numbers never pass through a translation table.
      box.innerHTML = `<p class="hint"><span>${esc(AG.caveat)}</span> · <span>${
        esc(_bulTf("showing {shown} of {total}", {shown: rows.length, total: AG.events.length}))}</span></p>` +
        Object.entries(groups).map(([k, list]) => {
          // Only the country grouping holds a code; month and calendar keys are
          // already prose and must not be run through a country formatter.
          const head = groupBy === "country"
            ? (k ? ooCountryCell(k) : esc(tt("No country")))
            : esc(k);
          return `<h3 style="font-size:13px;margin:12px 0 6px">${head} <span class="muted">${list.length}</span></h3>` + list.map(agRow).join("");
        }).join("");
    }

    // ===================================================================== //
    //  GOVERNMENTS tab (maintainer chat 2026-06-22): per-country data + a
    //  world-map choropleth + the law tracker, as subtabs over the existing
    //  vintaged official-statistics store (/api/governments/*). Honesty carried:
    //  a value is a producer's published figure (never a score), a gap is a gap.
    // ===================================================================== //
