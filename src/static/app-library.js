/* app-library.js — Library and the live poller

   The Library's views, storage footprint, metric tiles, the qualification and
   language tiles, composition figures, and the LIVE per-tab refresh manager.

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
    let DB_KEYS = null;   // current rendered stat keys (rebuild grid only when they change)

    // Two-class sources split (2026-07-23 field-feedback S1.3): the raw "sources" COUNT(*)
    // blends enabled+qualified (actively collecting) sources with disabled discovery
    // candidates awaiting review — the exact figure a field export showed as "~50k sources"
    // and read as an alarm. Never show it as one bare number: skip the flat key, label the
    // two split keys the backend now sends (database.py's counts["sources_qualified"] /
    // counts["sources_candidates"]) in plain language.
    const DB_STAT_HIDDEN_KEYS = new Set(["sources"]);
    const DB_STAT_LABELS = {
      sources_qualified: "Sources (collecting)",
      sources_pending: "Sources awaiting qualification (enabled)",
      sources_candidates: "Discovered candidates",
    };

    // B14: the COMPLETE on-disk footprint (A12b backend, GET /api/diagnostics/storage-footprint)
    // shown wherever storage size shows — the Library dashboard + the task-manager System tab.
    // It is a RECURSIVE disk walk (potentially slow on a 100 GB+ corpus), so it is fetched
    // LAZILY on tab open + CACHED — NEVER on the live poll (which would self-inflict the freeze
    // the scale mandate warns against) — with a Re-measure button. Honest split: the ENCRYPTED
    // private corpus (irreplaceable) vs re-downloadable PUBLIC blobs (dumps/maps/models). Bytes
    // only, no score; the method rides the #oo-tip hover.
    const _SF_PUBLIC = new Set(["wiki_dumps", "osm_regions", "ollama_models"]);
    let _sfCache = null;     // last storage-footprint payload (envelope .data)
    let _sfPending = null;   // in-flight promise, so two hosts share one walk

    async function _fetchStorageFootprint(force) {
      if (_sfCache && !force) return _sfCache;
      if (_sfPending) return _sfPending;
      _sfPending = api("/api/diagnostics/storage-footprint")
        .then(r => { _sfCache = (r && r.data) || null; _sfPending = null; return _sfCache; })
        .catch(e => { _sfPending = null; throw e; });
      return _sfPending;
    }

    function _sfLabel(kind, name, t) {
      const L = { db: t("Database"), wal: t("Database WAL"), shm: t("Database SHM"),
        wiki_dumps: t("Wikipedia dumps"), osm_regions: t("OpenStreetMap regions"),
        staging: t("Backup/restore staging"), other: t("Other (data folder)"),
        ollama_models: t("Local AI models") };
      return L[kind] || name || kind;
    }

    function _sfPaint(host, d, t) {
      if (!d || !Array.isArray(d.components)) {
        host.innerHTML = `<div class="muted">${esc(t("No storage measurement yet."))}</div>`; return;
      }
      const total = (d.totals || {}).grand_total_bytes || 0;
      const priv = d.components.filter(c => !_SF_PUBLIC.has(c.kind)).reduce((a, c) => a + (c.bytes || 0), 0);
      const pub = d.components.filter(c => _SF_PUBLIC.has(c.kind)).reduce((a, c) => a + (c.bytes || 0), 0);
      const rows = d.components.filter(c => (c.bytes || 0) > 0).sort((a, b) => b.bytes - a.bytes).map(c => {
        const pct = total ? Math.round(100 * c.bytes / total) : 0;
        const isPub = _SF_PUBLIC.has(c.kind);
        // "encrypted" is strictly true only of the DB triple (SQLCipher at rest); the honest
        // per-component tag is public=re-downloadable vs private=local. The summary line below
        // carries the "encrypted corpus" framing where the DB dominates the private bytes.
        const tag = isPub ? t("re-downloadable") : t("private (local)");
        const ttl = (c.detail || "") + (c.outside_data_dir ? ` · ${t("outside the data folder")}` : "");
        return `<div class="sf-row" style="display:flex;gap:8px;align-items:center;margin:3px 0"${ttl ? ` title="${esc(ttl)}"` : ""}>`
          + `<div style="flex:0 0 42%;min-width:0">${esc(_sfLabel(c.kind, c.name, t))} <span class="muted" style="font-size:11px">· ${esc(tag)}</span></div>`
          + `<div style="flex:1;height:8px;background:var(--panel2, rgba(128,128,128,.18));border-radius:4px;overflow:hidden"><div style="width:${pct}%;height:100%;background:${isPub ? "var(--muted, #8c95a6)" : "var(--accent)"}"></div></div>`
          + `<div style="flex:0 0 auto;font-variant-numeric:tabular-nums">${esc(_fmtBytes(c.bytes))}</div></div>`;
      }).join("");
      host.innerHTML =
        `<div class="row" style="justify-content:space-between;align-items:baseline;gap:8px">`
        + `<div><b style="font-size:1.15em">${esc(_fmtBytes(total))}</b> <span class="muted">${esc(t("on disk, all stores"))}</span></div>`
        + `<button class="secondary" style="font-size:11px;padding:2px 8px" onclick="renderStorageFootprint('${esc(host.id)}', true)">${esc(t("Re-measure"))}</button></div>`
        + `<div class="muted" style="font-size:11px;margin:3px 0 8px"${d.method ? ` title="${esc(d.method)}"` : ""}>`
        // Honest label (no fabricated security): the private sum includes -shm + backup
        // staging, which are NOT necessarily encrypted — so it is "Private (local)", with the
        // corpus's at-rest encryption noted, not a blanket "encrypted" claim over every byte.
        + `${esc(t("Private (local; corpus encrypted at rest)"))}: <b>${esc(_fmtBytes(priv))}</b> · `
        + `${esc(t("Re-downloadable (dumps / maps / models)"))}: <b>${esc(_fmtBytes(pub))}</b></div>`
        + rows;
    }

    // Fetch (lazily, cached) + paint the footprint into a host. Paints the cache instantly on
    // re-open, then re-measures only when forced. Called on Library-tab open + System-tab open.
    async function renderStorageFootprint(hostId, force) {
      const host = document.getElementById(hostId);
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      if (_sfCache && !force) { _sfPaint(host, _sfCache, t); return; }
      host.innerHTML = `<div class="muted">${esc(t("Measuring on-disk footprint…"))}</div>`;
      try {
        const d = await _fetchStorageFootprint(force);
        _sfPaint(host, d, t);
        if (typeof loadDbStats === "function" && document.getElementById("db-file")) loadDbStats();
      } catch (e) {
        host.innerHTML = `<div class="note err">${esc(t("Could not measure storage:"))} ${esc(e.message || e)}</div>`;
      }
    }

    // Library central dashboard (field remark 16): the at-a-glance roll-up of everything
    // DOWNLOADED (the raw, re-downloadable layer) + everything EXTRAPOLATED (the AI-derived
    // layer). Honest counts + on-disk byte sizes only, no score; own stamp so the 16s poll
    // only repaints on a real change. The Database section below keeps the store detail.
    let _libOvStamp = "";
    // -- Ingest rhythm heatmap (2026-08-01 ruling 10) ---------------------- //
    // The maintainer asked to diversify the app's data-visualization vocabulary.
    // This is the first activation: a weekday x hour-of-day density grid over the
    // SAME articles_per_hour series the Activity tiles already fetch — no new
    // backend, no new poll, and it answers a question a line chart cannot ("when
    // does my collection actually run?").
    //
    // The honesty problem this had to solve: an empty cell is ambiguous. The
    // backend returns a bucket only for hours that HAVE articles, so a missing
    // hour inside the observed span is a true zero — but a slot that never
    // occurred at all (a 3-day-old corpus has no second Tuesday) is NOT a zero,
    // it is unobserved. Those two are rendered differently and never blended,
    // the same rule ooMap's no-data hatch follows.
    const _RHYTHM_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    function _ingestRhythm(series) {
      const pts = (series || [])
        .map(p => ({ms: Date.parse(String(p.t).length <= 19 ? p.t + "Z" : p.t), n: +p.n || 0}))
        .filter(p => isFinite(p.ms));
      if (!pts.length) return null;
      const first = Math.min(...pts.map(p => p.ms)), last = Math.max(...pts.map(p => p.ms));
      // slot = [weekday 0..6 (Mon-first)][hour 0..23]
      const total = [], seen = [];
      for (let d = 0; d < 7; d++) { total.push(new Array(24).fill(0)); seen.push(new Array(24).fill(0)); }
      const slot = (ms) => {
        const dt = new Date(ms);
        return [(dt.getUTCDay() + 6) % 7, dt.getUTCHours()];
      };
      // Walk every hour of the OBSERVED span so a slot's occurrence count is real:
      // an average over "times this hour actually came round" is comparable, an
      // average over an assumed full week is not.
      const HOUR = 36e5, MAX_HOURS = 24 * 400;   // bounded: a huge window can't hang the UI
      let steps = 0;
      for (let ms = first; ms <= last && steps < MAX_HOURS; ms += HOUR, steps++) {
        const [d, h] = slot(ms); seen[d][h] += 1;
      }
      if (steps >= MAX_HOURS) return null;       // honestly render nothing rather than a partial grid
      pts.forEach(p => { const [d, h] = slot(p.ms); total[d][h] += p.n; });
      return {total, seen, first, last, n: pts.reduce((a, p) => a + p.n, 0)};
    }
    function ingestRhythmSvg(series) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const g = _ingestRhythm(series);
      if (!g) return "";
      // Colour by the AVERAGE per occurrence (comparable across slots seen a
      // different number of times); the hover states both the total and the
      // occurrences, so the reader can always recover the raw counts.
      let peak = 0;
      for (let d = 0; d < 7; d++) for (let h = 0; h < 24; h++) {
        if (g.seen[d][h] > 0) peak = Math.max(peak, g.total[d][h] / g.seen[d][h]);
      }
      const cw = 15, ch = 15, padL = 34, padT = 16;
      const w = padL + 24 * cw + 4, hgt = padT + 7 * ch + 16;
      let cells = "";
      for (let d = 0; d < 7; d++) for (let h = 0; h < 24; h++) {
        const x = padL + h * cw, y = padT + d * ch;
        const occ = g.seen[d][h];
        if (!occ) {   // NEVER a zero: this slot did not occur in the observed span
          cells += `<rect x="${x}" y="${y}" width="${cw - 1}" height="${ch - 1}" fill="url(#rhythm-none)"`
            + `><title>${esc(t(_RHYTHM_DAYS[d]))} ${h}:00 — ${esc(t("not observed yet"))}</title></rect>`;
          continue;
        }
        const avg = g.total[d][h] / occ;
        const frac = peak > 0 ? avg / peak : 0;
        const fill = frac <= 0 ? "var(--panel2)"
          : `color-mix(in srgb, var(--accent) ${Math.round(12 + frac * 88)}%, var(--panel2))`;
        const title = `${t(_RHYTHM_DAYS[d])} ${h}:00 — `
          + t("{total} articles over {occ} occurrence(s), {avg} on average")
              .replace("{total}", fmtNum(g.total[d][h])).replace("{occ}", String(occ))
              .replace("{avg}", fmtNum(avg, 1));
        cells += `<rect x="${x}" y="${y}" width="${cw - 1}" height="${ch - 1}" fill="${fill}"`
          + ` stroke="var(--border)" stroke-width="0.4"><title>${esc(title)}</title></rect>`;
      }
      const dayLabels = _RHYTHM_DAYS.map((d, i) =>
        `<text x="${padL - 4}" y="${padT + i * ch + 11}" text-anchor="end" font-size="8.5"
           fill="var(--muted)">${esc(t(d).slice(0, 3))}</text>`).join("");
      const hourLabels = [0, 6, 12, 18].map(h =>
        `<text x="${padL + h * cw}" y="${padT - 5}" font-size="8.5" fill="var(--muted)">${h}:00</text>`).join("");
      return `<div class="lib-rhythm">
        <svg viewBox="0 0 ${w} ${hgt}" width="100%" style="display:block;max-width:${w}px" role="img"
             aria-label="${esc(t("Ingest rhythm: articles collected by weekday and hour of day (UTC)."))}">
          <defs><pattern id="rhythm-none" width="4" height="4" patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4"
            stroke="var(--border)" stroke-width="1"></line></pattern></defs>
          ${dayLabels}${hourLabels}${cells}
        </svg>
        <div class="hint muted">${esc(t("Hatched = that hour has not come round yet in the recorded span — not a zero."))}</div>
        <div class="card-caveat">${esc(t("Shading is the AVERAGE articles per occurrence of that weekday-hour (UTC), because slots recur a different number of times in a short window; the hover gives the real total and how many times the slot occurred. Counts only, never a score."))}</div>
      </div>`;
    }

    // -- Library subtabs (2026-08-01 ruling 9) ----------------------------- //
    // Seven stacked sections became five views through the ONE universal subtab
    // component (invariant #18). The panels are untouched — this is a regrouping,
    // not a rewrite — and each view's loaders fire on SELECT, not on tab open, so
    // opening the Library no longer pays for the recursive storage walk and the
    // coverage map before you have asked for them ("folded must not mean
    // fetched", the Advanced-tab precedent). Each view loads once per session.
    let _libViewTabs = null, _libView = "overview";
    const _libViewLoaded = new Set();
    const _LIB_VIEW_LOADERS = {
      overview: () => { renderLibraryOverview(); },
      activity: () => { renderLibraryActivityGraphs(); },
      tracked:  () => { renderLibraryWikiGraphs(); renderLibraryLawGraphs(); },
      composition: () => { renderCompositionFigures(); },
      storage:  () => { renderStorageFootprint("library-storage"); },
      coverage: () => { loadCoverage(); },
    };
    function selectLibraryView(key) {
      if (!_LIB_VIEW_LOADERS[key]) key = "overview";
      _libView = key;
      document.querySelectorAll("#tab-library .lib-view").forEach(el => {
        el.style.display = (el.id === "lib-view-" + key) ? "" : "none";
      });
      if (!_libViewLoaded.has(key)) {
        _libViewLoaded.add(key);
        try { _LIB_VIEW_LOADERS[key](); }
        catch (e) { _libViewLoaded.delete(key); }   // a failed load must be retryable
      }
    }
    function _wireLibraryViews() {
      const nav = $("library-views");
      if (!nav) { renderLibraryOverview(); return; }   // defensive: markup missing
      if (!_libViewTabs) _libViewTabs = ooSubtabs(nav, selectLibraryView, {initial: _libView});
      selectLibraryView(_libView);
    }
    async function renderLibraryOverview() {
      const host = $("library-overview");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      let d, fig;
      try {
        // Figures endpoint is 60 s-cached server-side, so polling it here is cheap.
        [d, fig] = await Promise.all([
          api("/api/library/overview"),
          api("/api/database/figures").catch(() => ({})),
        ]);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const stamp = JSON.stringify([d.downloaded, d.derived, fig]);
      if (stamp === _libOvStamp) return;   // live poll: unchanged, no repaint
      _libOvStamp = stamp;
      const num = v => (v == null ? "—" : fmtNum(v));
      const sz = v => (v == null || !v) ? "—" : _fmtBytes(v);
      const tile = (n, k) => `<div class="stat"><div class="n">${esc(n)}</div><div class="k">${esc(k)}</div></div>`;
      const dl = d.downloaded || {}, der = d.derived || {};
      const wiki = dl.wikipedia || {}, maps = dl.maps || {}, laws = dl.laws || {};
      const dlTiles = [
        tile(num(wiki.tracked_pages), t("Wikipedia pages tracked")),
        tile(num(wiki.revisions), t("Wikipedia revisions")),
        tile(`${num((wiki.dumps || {}).count)} · ${sz((wiki.dumps || {}).total_bytes)}`, t("Wikipedia dumps")),
        tile(`${num((maps.osm_regions || {}).count)} · ${sz((maps.osm_regions || {}).total_bytes)}`, t("OpenStreetMap regions")),
        tile(num((dl.markets || {}).commodity_prices), t("Market price points")),
        tile(num(laws.documents), t("Law documents")),
        tile(num(laws.revisions), t("Law revisions")),
        tile(num((dl.statistics || {}).figures), t("Official statistics figures")),
        tile(`${num((dl.models || {}).count)} · ${sz((dl.models || {}).total_bytes)}`, t("Local AI models")),
      ].join("");
      // EXTRAPOLATED: each AI-analysis kind shown by name (nothing hidden) + AI keywords + watches.
      const KIND_LABELS = { summary: t("AI summaries"), translation: t("AI translations"),
        synthesis: t("AI syntheses"), entities: t("AI entities") };
      const aaKinds = (der.article_analyses || {}).by_kind || {};
      const aaTiles = Object.keys(aaKinds).length
        ? Object.entries(aaKinds).map(([k, v]) => tile(num(v), KIND_LABELS[k] || `${t("AI")} ${esc(k)}`)).join("")
        : tile("—", t("AI summaries"));
      const derTiles = aaTiles
        + tile(num((der.ai_keywords || {}).total), t("AI-extracted keywords"))
        + tile(num(der.watches_enabled), t("Active watches"));
      // Computed corpus figures (field ask 2026-07-02): averages + ingestion rate.
      // Real counts, no score; each label states its method. "—" when not yet known.
      const figTiles = (fig && fig.articles) ? [
        tile(num(fig.avg_word_count), t("Avg words / article")),
        tile(num(fig.avg_keywords_per_article), t("Avg keywords / article")),
        tile(num(fig.articles_per_day), t("Articles / day (avg since first)")),
        tile(num(fig.articles_per_hour_recent), t("Articles / hour (last 24h)")),
      ].join("") : "";
      // Downloaded section TIDIED (field feedback item 5): a compact, collapsed-by-
      // default <details> disclosure — the established "adv-collect" convention
      // (Settings' own legacy/advanced sections) — instead of a permanently-open
      // 9-tile grid. Nothing lost, just less default visual space; the live
      // Activity/Wikipedia/Law GRAPH sections below carry the evolution-over-time
      // view these bare counts used to be the only source of.
      host.innerHTML =
        (figTiles
          ? `<div class="hint" style="margin-bottom:6px">${esc(t("Corpus figures — measured averages and the current ingestion rate:"))}</div>`
            + `<div class="stat-grid">${figTiles}</div>`
          : "")
        + `<details class="adv-collect" style="margin-top:10px"><summary>${esc(t("Downloaded — the raw, re-downloadable layer"))}</summary>`
        + `<div class="stat-grid" style="margin-top:8px">${dlTiles}</div></details>`
        + `<div class="hint" style="margin:12px 0 6px">${esc(t("Extrapolated — AI-derived from your corpus (unreliable, never the trusted index):"))}</div>`
        + `<div class="stat-grid">${derTiles}</div>`;
    }

    // -- Library counter-evolution graphs (S2, 2026-07-23 field-feedback) -------
    // Small honest evolution graphs for counters that had no history anywhere
    // (sources/keywords/Wikipedia+law tracked counts) plus a live-DERIVED
    // articles/hour series (real history since Article.created_at already
    // existed -- backfills with no gap). Reuses the EXISTING dashChartSvg (the
    // small-tile renderer, line-when-dense/bars-when-sparse, invariant #16) and
    // chartEnlarge (click-to-enlarge into an interactive ooChart) -- no new
    // visual language, no larger tile footprint than any other Library number.
    const LIB_METRIC_LABEL_KEYS = {
      articles_per_hour: "Articles / hour",
      sources: "Sources tracked",
      keywords: "Distinct keywords",
      wiki_pages: "Wikipedia pages tracked",
      wiki_revisions: "Wikipedia revisions tracked",
      law_documents: "Law documents tracked",
      law_revisions: "Law revisions tracked",
    };
    // The y-axis UNIT per metric — the tiles used to pass "" so the axis stated
    // no unit at all, which is half of why a flat "23" beside a bare "n=2" read
    // as "23 documents or 2?" (maintainer-reported 2026-08-01).
    const LIB_METRIC_UNIT_KEYS = {
      articles_per_hour: "articles / hour",
      sources: "sources",
      keywords: "keywords",
      wiki_pages: "pages",
      wiki_revisions: "revisions",
      law_documents: "documents",
      law_revisions: "revisions",
    };
    // What one DATAPOINT is, per metric: the counter metrics are hourly
    // SNAPSHOTS of a running total, while articles_per_hour is a per-HOUR
    // bucket derived from created_at. n= now says which.
    const LIB_METRIC_N_UNIT_KEYS = {articles_per_hour: "hours"};
    const LIB_DEFAULT_N_UNIT = "snapshots";
    // 2026-07-24 Session A §5: per-tile WINDOW SWITCHER (ruled) — every Library
    // graph tile, including the new qualification one, starts on the SAME
    // default window and can be independently switched without reloading the
    // whole panel. "All" maps to the backend's own generous (not literally
    // unbounded) history cap.
    const LIB_WINDOWS = [[7, "7d"], [30, "30d"], [90, "90d"], [3650, "All"]];
    const LIB_DEFAULT_DAYS = 30;
    let _libTileDays = {};    // metric (or "__qual") -> the window currently shown
    let _libGraphData = {};   // metric -> last-fetched /api/library/history payload
    function _libAllZero(nums) {
      // "zero/no-data" (ruled): every point is 0, or there simply are no points —
      // hide-flat collapses this to a one-line note instead of a silently blank
      // or misleadingly-flat chart (the never-blank-and-silent rule).
      return !nums.length || nums.every(n => !n);
    }
    function _libWindowChips(key, current) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return `<div style="display:flex;gap:3px;margin-top:4px" class="lib-win-row">` +
        LIB_WINDOWS.map(([d, lbl]) =>
          `<button type="button" class="chip tiny${d === current ? " on" : ""}" onclick="_libSetWindow('${key}', ${d})">${esc(t(lbl))}</button>`
        ).join("") + `</div>`;
    }
    async function _libGraphTile(metric, days) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const cur = days || _libTileDays[metric] || LIB_DEFAULT_DAYS;
      _libTileDays[metric] = cur;
      const label = t(LIB_METRIC_LABEL_KEYS[metric] || metric);
      let d;
      try {
        d = await api(`/api/library/history?metric=${encodeURIComponent(metric)}&days=${cur}`);
      } catch (e) {
        return `<div id="lib-tile-${esc(metric)}" style="flex:1;min-width:180px;padding:6px;border:1px solid var(--border);border-radius:8px">
          <b style="font-size:12.5px">${esc(label)}</b>
          <div class="note err" style="font-size:11px">${esc(e.message || e)}</div></div>`;
      }
      _libGraphData[metric] = d;
      const series = Array.isArray(d.series) ? d.series : [];
      const flat = _libAllZero(series.map(p => p.n));
      // Library metrics are COUNTS: zero-based axis (Item Y), a NEUTRAL colour
      // (a falling keyword count is not "bad" — market up=green semantics do not
      // apply), the real unit on the axis, and an n= that says what it counts.
      const body = flat
        ? `<div class="muted" style="padding:14px 0;font-size:12px">${esc(t("No data yet."))}</div>`
        : dashChartSvg(series.map(p => ({observed_on: p.t, price: p.n})),
                       t(LIB_METRIC_UNIT_KEYS[metric] || ""),
                       {zeroBase: true, neutral: true,
                        nUnit: t(LIB_METRIC_N_UNIT_KEYS[metric] || LIB_DEFAULT_N_UNIT)});
      const began = d.recording_began_at
        ? `<div class="hint muted" style="font-size:11px">${esc(t("Recording began at {x}.").replace("{x}", d.recording_began_at))}</div>`
        : "";
      return `<div id="lib-tile-${esc(metric)}" style="flex:1;min-width:180px;padding:6px;border:1px solid var(--border);border-radius:8px">
        <div style="display:flex;align-items:baseline;gap:6px;justify-content:space-between">
          <b style="font-size:12.5px">${esc(label)}</b>
          <button class="ghost tiny" onclick="enlargeLibMetric('${metric}')" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>
        </div>${body}${began}${_libWindowChips(metric, cur)}</div>`;
    }
    async function _renderLibGraphHost(hostId, metrics) {
      const host = $(hostId);
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const tiles = await Promise.all(metrics.map(([m, days]) => _libGraphTile(m, days)));
        host.innerHTML = `<div class="row" style="flex-wrap:wrap;gap:10px">${tiles.join("")}</div>`;
      } catch (e) {
        host.innerHTML = `<div class="note err">${esc(e.message || e)}</div>`;
      }
    }

    // -- The 4-line source-QUALIFICATION tile (2026-07-24 Session A §5) --------
    // qualified / disqualified / never-judged / candidates on ONE shared axis
    // (all four are source COUNTS — same unit, so multi-axis is never the
    // honest answer here per the dual-axis rejection); auto-switches to log10
    // when the cross-series spread is large, always labelled "log scale",
    // never silently. Counts only — never a quality score.
    const LIB_QUAL_METRICS = [
      "sources_qualified", "sources_disqualified", "sources_never_judged", "sources_candidates",
    ];
    const LIB_QUAL_LABELS = {
      sources_qualified: "Qualified", sources_disqualified: "Disqualified",
      // NOT "Never judged", which this line claimed until 2026-08-04 and is false for
      // roughly the population the livelock fix was about: the metric counts
      // status == "unqualified", and an attempt that concludes no_evidence deliberately
      // leaves status alone, so an enabled feedless source is tried over and over and
      // still counted here. "Awaiting a verdict" is what the number actually measures.
      sources_never_judged: "Awaiting a verdict", sources_candidates: "Candidates",
    };
    // Wrap an LTR-shaped VALUE before interpolating it into a translated sentence, so the
    // bidi algorithm treats it as one run instead of reordering its parts against the
    // surrounding RTL text. Measured in the real Arabic page: "بدأ التسجيل في " + an ISO
    // timestamp renders in visual order ".07T18:00:00-07-2026" -- the year at the wrong
    // end, which is a MISREAD date, not merely an ugly one. With U+2068 FIRST STRONG
    // ISOLATE / U+2069 POP DIRECTIONAL ISOLATE around it: ".2026-07-07T18:00:00".
    //
    // Plain characters, not markup, so they survive esc() and work anywhere a string is
    // interpolated. Needed for punctuation-joined runs (dates, versions, IDs, URLs,
    // ranges); a bare number does not need it and does not get one, since an isolate on a
    // lone digit is invisible clutter. LTR locales are unaffected -- the characters are
    // zero-width and the reordering they suppress only happens in an RTL paragraph.
    const _LTR_ISOLATE = ["⁨", "⁩"];
    function _ltrIsolate(v) {
      return v == null ? v : _LTR_ISOLATE[0] + String(v) + _LTR_ISOLATE[1];
    }
    // Fetched for the composition note, deliberately NOT charted as a fifth line: it is a
    // SUBSET of the line above (nested series on one axis read as separate populations),
    // and it starts recording today while the others have months, so a new line would
    // appear to begin at zero when it simply was not being recorded. One data point is
    // enough to state the split in words, which is what the note does.
    const LIB_QUAL_SPLIT_METRIC = "sources_never_attempted";
    let _libQualSeries = [];   // stashed live series (enlarge + in-place re-render)
    function _libQualSpread(series) {
      const vals = series.flatMap(s => s.points.map(p => p.v)).filter(v => v > 0);
      return vals.length ? Math.max(...vals) / Math.min(...vals) : 1;
    }
    // Whether a log axis is even POSSIBLE for these series. Source counts legitimately
    // start at zero and log10(0) is undefined, so ooChart refuses log mode on such data
    // and falls back to linear -- this asks the same question, so the tile's own "log
    // scale" chip can never claim a scale the chart declined to use.
    function _libQualLogOk(series) {
      return series.every(s => (s.points || []).every(p => p.v != null && +p.v > 0));
    }
    async function _libQualificationTile(days) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const cur = days || _libTileDays.__qual || LIB_DEFAULT_DAYS;
      _libTileDays.__qual = cur;
      const label = t("Source qualification");
      let payloads, splitPayload = null;
      try {
        const all = await Promise.all(
          LIB_QUAL_METRICS.concat([LIB_QUAL_SPLIT_METRIC]).map(m =>
            api(`/api/library/history?metric=${encodeURIComponent(m)}&days=${cur}`)));
        payloads = all.slice(0, LIB_QUAL_METRICS.length);
        splitPayload = all[all.length - 1];
      } catch (e) {
        return `<div id="lib-tile-__qual" style="flex:2;min-width:280px;padding:6px;border:1px solid var(--border);border-radius:8px">
          <b style="font-size:12.5px">${esc(label)}</b>
          <div class="note err" style="font-size:11px">${esc(e.message || e)}</div></div>`;
      }
      _libQualSeries = LIB_QUAL_METRICS.map((m, i) => ({
        // NO unit. ooChart's legend renders `label` then `n=N · unit`, where n is the
        // DATAPOINT count -- so the slot is the unit OF N, not of the values. Passing the
        // label read "Qualified n=29 · Qualified" (redundant); passing "sources" read
        // "Qualified n=29 · sources", which a reader takes as "29 sources in this
        // category" and cannot be true of all four series at once. It is 29 daily
        // samples. An adversarial critic reading the screenshot caught the second form.
        // What the values count is said by the tile's title and its caveat.
        label: t(LIB_QUAL_LABELS[m] || m),
        points: (payloads[i].series || []).map(p => ({t: p.t, v: p.n})),
      }));
      const flat = _libAllZero(_libQualSeries.flatMap(s => s.points.map(p => p.v)));
      const logY = _libQualSpread(_libQualSeries) > 50 && _libQualLogOk(_libQualSeries);
      const began = payloads.map(p => p.recording_began_at).filter(Boolean).sort()[0];
      const beganNote = began
        ? `<div class="hint muted" style="font-size:11px">${esc(t("Recording began at {x}.").replace("{x}", _ltrIsolate(began)))}</div>`
        : "";
      const body = flat
        ? `<div class="muted" style="padding:14px 0;font-size:12px">${esc(t("No data yet."))}</div>`
        : `<div class="lib-qual-chart"></div>` + (logY
            ? `<div class="hint muted" style="font-size:10.5px">${esc(t("log scale"))}</div>` : "");
      return `<div id="lib-tile-__qual" style="flex:2;min-width:280px;padding:6px;border:1px solid var(--border);border-radius:8px">
        <div style="display:flex;align-items:baseline;gap:6px;justify-content:space-between">
          <b style="font-size:12.5px">${esc(label)}</b>
          <button class="ghost tiny" onclick="enlargeLibQualification()" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>
        </div>${body}${_libQualSplitNote(payloads, splitPayload)}${beganNote}${_libWindowChips("__qual", cur)}</div>`;
    }
    // The composition of the "Awaiting a verdict" line, in words. Extracted as a pure
    // function of the two payloads so a test can drive it directly: a source guard
    // asserting the identifier appears would survive deleting the sentence.
    function _libQualNewest(payload) {
      const pts = (payload && payload.series) || [];
      // Newest by timestamp, not by array position: a reordered payload must not silently
      // become "the latest reading".
      let best = null;
      for (const p of pts) if (best === null || String(p.t) > String(best.t)) best = p;
      return best === null ? null : best.n;
    }
    function _libQualSplitText(awaiting, never) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : null;
      const fmt = (tpl, vars) => (tf ? tf(tpl, vars)
        : Object.keys(vars).reduce((s, k) => s.split("{" + k + "}").join(String(vars[k])), t(tpl)));
      // An absent reading is stated as absent. Rendering 0 here would claim every waiting
      // source had been attempted, which is the opposite of what "not recorded yet" means.
      if (awaiting === null || never === null) {
        return t("Not yet recorded: how many of these have never been attempted.");
      }
      if (never > awaiting) {
        // Structurally a subset, so this can only be two readings from different
        // snapshots. Say that rather than printing a negative remainder.
        return t("The two readings come from different snapshots, so the split is not comparable yet.");
      }
      // Label:value, not prose. A conjugated verb cannot agree with an interpolated
      // count without CLDR plural rules this app does not have -- the prose form read
      // "1 have never been attempted", and the French carried the identical error
      // because the TEMPLATE always pluralised. Russian has three plural forms and
      // Arabic six, so per-form keys are not the answer either. Nothing conjugates here,
      // so every locale is correct by construction. Caught by an adversarial critic
      // reading the rendered screenshot, not by any mechanical check.
      return fmt(
        "Awaiting a verdict: {awaiting} · never attempted: {never} · tried without one: {tried}",
        {awaiting: awaiting, never: never, tried: awaiting - never});
    }
    function _libQualSplitNote(payloads, splitPayload) {
      const i = LIB_QUAL_METRICS.indexOf("sources_never_judged");
      const awaiting = i < 0 ? null : _libQualNewest(payloads[i]);
      const never = _libQualNewest(splitPayload);
      return `<div class="hint muted" style="font-size:11px">${esc(_libQualSplitText(awaiting, never))}</div>`;
    }
    function _libRenderQualChart(root) {
      const scope = root || document;
      const host = scope.querySelector ? scope.querySelector(".lib-qual-chart") : null;
      const live = _libQualSeries.filter(s => s.points.length);
      if (!host || !live.length) return;   // defensive: a flat/errored tile has no chart host
      // zeroBase: these are source COUNTS, so the axis starts at a true zero
      // (ignored under logY, where log(0) is undefined — stated in ooChart).
      const logY = _libQualSpread(_libQualSeries) > 50 && _libQualLogOk(_libQualSeries);
      ooChart(host, live, {height: 150, indexed: false, logY: logY, zeroBase: !logY});
    }
    function enlargeLibQualification() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const live = _libQualSeries.filter(s => s.points.length);
      if (!live.length) return;   // defensive: nothing to enlarge
      chartEnlarge(t("Source qualification"), live,
        t("Counts only, never a quality score. Qualified = actively collecting; disqualified and awaiting-a-verdict are enabled but not (yet) admitted; candidates are disabled, awaiting review. Awaiting a verdict does not mean untried: an attempt that finds nothing to judge is recorded and leaves the status alone, so a source with no feed stays here however often it is tried."),
        {scales: true});
    }

    // -- Per-language corpus growth (small multiples) --------------------------
    // "Which languages is my corpus actually growing in" — the feedback surface
    // the language-equilibrium lever never had. One panel per language on ONE
    // shared scale, which is what makes the panels comparable at a glance.
    //
    // Every number the endpoint declines to plot is stated here rather than
    // dropped: the ranked-out tail, the articles with no asserted language (the
    // lever's own blind spot), and where the series starts if the corpus is
    // younger than the window.
    const LIB_LANG_TOP_N = 12;
    // Pure, so the disclosures can be tested for what they SAY rather than for
    // which identifiers appear in the source. A substring guard over the tile
    // survives a mutation that leaves `d.other` in a variable binding and drops
    // the sentence -- which is precisely the class of silent truncation these
    // sentences exist to prevent.
    function _libLangNotes(d, t, tf) {
      const notes = [];
      notes.push(d.bucket === "hour" ? t("Articles stored per hour.") : t("Articles stored per day."));
      const other = d.other || {};
      if (other.languages) {
        notes.push(tf("{langs} more languages ({articles} articles) are counted but not drawn.",
          {langs: other.languages, articles: other.articles}));
      }
      const un = d.unassigned || {};
      if (un.articles) {
        notes.push(tf("{n} articles have no asserted language and are not drawn — the equilibrium lever cannot see them either ({deduced} carry a deduced one).",
          {n: un.articles, deduced: un.with_deduced_language}));
      }
      // Said only when the series is genuinely CLAMPED by the corpus's own start —
      // the backend decides that, rather than the frontend re-deriving it from two
      // timestamps and getting the bucket arithmetic subtly wrong.
      if (d.clamped_to_corpus_start && d.corpus_began_at) {
        notes.push(tf("The corpus itself begins at {x}, so the series starts there.", {x: d.corpus_began_at}));
      }
      return notes;
    }
    async function _libLanguageTile(days) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((tpl, v) => String(tpl).replace(/\{(\w+)\}/g, (m, k) => (k in v ? v[k] : m)));
      const cur = days || _libTileDays.__lang || LIB_DEFAULT_DAYS;
      _libTileDays.__lang = cur;
      const label = t("Growth by language");
      let d;
      try {
        d = await api(`/api/library/languages?days=${cur}&top_n=${LIB_LANG_TOP_N}`);
      } catch (e) {
        return `<div id="lib-tile-__lang" style="flex:1 1 100%;padding:6px;border:1px solid var(--border);border-radius:8px">
          <b style="font-size:12.5px">${esc(label)}</b>
          <div class="note err" style="font-size:11px">${esc(e.message || e)}</div></div>`;
      }
      // The panel label is the language NAME in the current UI locale, via the
      // browser's own CLDR data (ooLangName) — the code is what the lever keys on,
      // not what a reader should have to decode. Degrades to the code.
      const panels = (d.series || []).map(s => ({
        label: ooLangName(s.language, s.language),
        points: (s.points || []).map(p => ({date: p.t, count: p.n})),
      }));
      // neutral: a language growing more slowly than another is not "bad", so the
      // market up=green/down=red semantics must not be borrowed here.
      const body = panels.length
        ? smallMultiplesSvg(panels, {neutral: true})
        : `<div class="muted" style="padding:14px 0;font-size:12px">${esc(t("No data yet."))}</div>`;

      const notes = _libLangNotes(d, t, tf).map(esc);
      return `<div id="lib-tile-__lang" style="flex:1 1 100%;padding:6px;border:1px solid var(--border);border-radius:8px">
        <b style="font-size:12.5px">${esc(label)}</b>
        ${body}
        <div class="hint muted" style="font-size:11px">${notes.join(" ")}</div>
        ${_libWindowChips("__lang", cur)}</div>`;
    }

    // Re-render exactly ONE tile in place when its window chip is clicked —
    // never the whole panel (a switch on one metric must not disturb the
    // others' state or cause a visible flash across the row).
    async function _libSetWindow(key, days) {
      const el = $(key === "__qual" ? "lib-tile-__qual"
        : key === "__lang" ? "lib-tile-__lang" : "lib-tile-" + key);
      if (!el) return;
      const html = key === "__qual" ? await _libQualificationTile(days)
        : key === "__lang" ? await _libLanguageTile(days)
        : await _libGraphTile(key, days);
      const tmp = document.createElement("div");
      tmp.innerHTML = html;
      const fresh = tmp.firstElementChild;
      if (!fresh) return;
      el.replaceWith(fresh);
      if (key === "__qual") _libRenderQualChart(fresh);
    }

    // The live current-rate readout stays in renderLibraryOverview's own
    // "Articles / hour (last 24h)" tile above (unchanged) — this graph adds the
    // EVOLUTION over time the maintainer asked for, alongside the counters that
    // had no history at all until this feature shipped, plus the qualification
    // funnel's own 4-line breakdown (§5).
    // ===== Library -> Composition: what the corpus is MADE OF ============== //
    // Three figures (GUI visualization plan C1/C2/C5). Each is a horizontal SORTED
    // BAR or a Lorenz curve — position and length carry the quantity, colour carries
    // only category, and every one ends in the shared figMeta panel so its method,
    // caveat and n are on screen without a click.
    //
    // SVG, not canvas: an SVG figure has a DOM, so the .sr-only data table below each
    // chart is the same numbers a sighted reader sees, and the figure can be exported
    // as vector. Canvas is reserved for ooChart, where pan/zoom over many points
    // earns it.

    // A horizontal bar row set. `rows` are {label, n, hatched?, title?}. The bar
    // LENGTH is the only quantitative channel; a hatched row is an absence and is
    // textured rather than coloured, so it can never be mistaken for a short bar.
    function _figBars(rows, opts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const o = opts || {};
      if (!rows.length) return figEmpty(o.empty);
      const max = Math.max(...rows.map(r => Math.max(0, +r.n || 0)), 1);
      const w = 100, labelW = o.labelW || 34;
      const body = rows.map((r) => {
        const n = Math.max(0, +r.n || 0);
        const pct = (n / max) * (w - labelW - 12);
        const fill = r.hatched ? figGapFill() : (r.color || "var(--fig-1)");
        return `<div class="fig-bar-row"${r.title ? ` title="${esc(r.title)}"` : ""}>` +
          `<span class="fig-bar-label">${esc(r.label)}</span>` +
          `<span class="fig-bar-track"><span class="fig-bar-fill" style="width:${pct.toFixed(2)}%;` +
          `background:${r.hatched ? "transparent" : fill};` +
          (r.hatched ? "background-image:repeating-linear-gradient(45deg, var(--fig-gap) 0 1.25px, transparent 1.25px 6px);border:1px solid var(--border)" : "") +
          `"></span></span>` +
          `<span class="fig-bar-n">${r.hatched ? esc(t("not measured")) + " · " : ""}${esc(fmtNum(n))}</span>` +
          `</div>`;
      }).join("");
      // One shared <defs> for the hatch, and the sr-only table so the numbers are
      // readable without seeing the bars.
      return `<svg width="0" height="0" style="position:absolute">${figGapDefs()}</svg>` +
        `<div class="fig-bars" role="img" aria-label="${esc(o.aria || o.title || "")}">${body}</div>` +
        `<table class="sr-only"><caption>${esc(o.title || "")}</caption><tbody>` +
        rows.map(r => `<tr><th scope="row">${esc(r.label)}</th><td>` +
          (r.hatched ? esc(t("not measured")) : esc(fmtNum(Math.max(0, +r.n || 0)))) +
          `</td></tr>`).join("") + `</tbody></table>`;
    }

    // The Lorenz curve: cumulative share of articles against cumulative share of
    // sources. The equality DIAGONAL is drawn and labelled, because the curve means
    // nothing without it — the gap between the two IS the inequality, and a curve
    // shown alone reads as an arbitrary shape.
    function _figLorenz(curve, opts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const o = opts || {};
      if (!curve || curve.length < 2) return figEmpty(o.empty);
      const W = 320, H = 220, padL = 40, padB = 30, padT = 10, padR = 10;
      // ooViz.linearScale, wired here for the first time (it was written, node-tested
      // and never called).
      const X = ooViz.linearScale(0, 1, padL, W - padR);
      const Y = ooViz.linearScale(0, 1, H - padB, padT);
      const pts = curve.map(p => `${X(p.sources).toFixed(2)},${Y(p.articles).toFixed(2)}`).join(" ");
      const ticks = [0, 0.25, 0.5, 0.75, 1];
      const grid = ticks.map(v =>
        `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${W - padR}" y2="${Y(v).toFixed(1)}"` +
        ` stroke="var(--border-soft)" stroke-width="1"/>` +
        `<text x="${padL - 5}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end" font-size="8.5"` +
        ` fill="var(--muted)">${Math.round(v * 100)}%</text>`).join("");
      const xlab = ticks.map(v =>
        `<text x="${X(v).toFixed(1)}" y="${H - padB + 12}" text-anchor="middle" font-size="8.5"` +
        ` fill="var(--muted)">${Math.round(v * 100)}%</text>`).join("");
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block;max-width:${W}px"` +
        ` role="img" aria-label="${esc(o.aria || "")}">${grid}${xlab}` +
        `<line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" stroke="var(--fig-6)"` +
        ` stroke-width="1.5" stroke-dasharray="4 3"/>` +
        `<polyline points="${pts}" fill="none" stroke="var(--fig-1)" stroke-width="2"/>` +
        // The diagonal's label sits BESIDE the line, not on it: printed on the line it
        // was unreadable exactly where the two cross.
        `<text x="${X(0.56)}" y="${Y(0.34)}" font-size="8.5" fill="var(--muted)">` +
        `${esc(t("equal draw"))}</text>` +
        `</svg>` +
        `<div class="hint muted">${esc(t("Horizontal: share of sources, fewest articles first. Vertical: share of articles."))}</div>`;
    }

    async function renderCompositionFigures() {
      const host = $("lib-composition");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Each figure fetches independently and renders its own failure, so one broken
      // endpoint leaves the other two on screen instead of blanking the whole view.
      const get = async (path) => { try { return await api(path); } catch (e) { return {__err: e}; } };
      const [quar, sent, conc] = await Promise.all([
        get("/api/insights/figures/quarantine-composition"),
        get("/api/insights/figures/sentiment-measurability"),
        get("/api/insights/figures/source-concentration"),
      ]);
      const block = (title, inner, d) =>
        `<div class="fig-block"><h3 class="fig-title">${esc(title)}</h3>${inner}` +
        (d && !d.__err ? figMeta(d) : "") + `</div>`;
      const errLine = (d) => `<div class="fig-empty">${esc(t("Could not load this figure."))}</div>`;

      // --- C2: tone measurability. Deliberately FIRST: it is the figure that makes
      // an existing gap visible, and on a multilingual corpus it is the largest one.
      let sentHtml;
      if (sent.__err) sentHtml = errLine(sent);
      else {
        const rows = [];
        for (const r of (sent.rows || [])) {
          // ooLangName, not a bare code: the shipped CLDR helper already renders the
          // full language name in the reader's own locale.
          const name = ooLangName(r.language, r.language);
          if (r.measured > 0) {
            rows.push({label: `${name} · ${t("measured")}`, n: r.measured, color: "var(--fig-1)",
                       title: t("A tone value was stored for these articles.")});
          }
          if (r.unmeasured > 0) {
            // The label is just the language: the hatch and the value's own "not
            // measured" prefix already state the condition, and saying it a third
            // time in the label crowded the row for no added information.
            rows.push({label: r.supported ? `${name} · ${t("no tone stored")}` : name,
                       n: r.unmeasured, hatched: !r.supported,
                       color: "var(--fig-3)",
                       title: r.supported
                         ? t("This language can be scored, but these articles carry no tone value.")
                         : t("The tone engine cannot read this language, so these articles were never scored.")});
          }
        }
        if (sent.untagged && sent.untagged.n) {
          rows.push({label: t("no asserted language"), n: sent.untagged.n, hatched: true,
                     title: t("These articles carry no language, which is the tone gate's own blind spot.")});
        }
        sentHtml = _figBars(rows, {
          title: t("Articles with and without a tone measurement, by language"),
          aria: t("Articles with and without a tone measurement, by language"),
          empty: t("No article carries a language yet."),
        }) + figGapKey();
      }

      // --- C1: quarantine composition
      let quarHtml;
      if (quar.__err) quarHtml = errLine(quar);
      else if (!(quar.rows || []).length) {
        quarHtml = figEmpty(t("Nothing in this corpus is quarantined."));
      } else {
        quarHtml = _figBars((quar.rows || []).map(r => ({
          label: (r.reason || t("reason not recorded")) +
            (r.criteria_version ? ` · ${r.criteria_version}` : ""),
          n: r.n, color: "var(--fig-3)",
        })), {
          title: t("Quarantined articles by the reason recorded"),
          aria: t("Quarantined articles by the reason recorded"),
        });
      }

      // --- C5: source concentration
      let concHtml;
      if (conc.__err) concHtml = errLine(conc);
      else {
        const g = conc.gini;
        // gini() returns null when undefined (fewer than two sources, or no
        // articles). A Gini of 0 means perfect EQUALITY, so printing 0 here would
        // state the opposite of "we cannot say".
        const gLine = g == null
          ? `<div class="hint">${esc(t("Gini is undefined for this set — it needs at least two sources with articles."))}</div>`
          : `<div class="hint"><strong>${esc(fmtNum(g, 3))}</strong> ${esc(t("Gini"))}` +
            (conc.top_share != null
              ? ` <span class="muted">· ${esc(OOI18N && OOI18N.tf
                  ? OOI18N.tf("top 3 sources hold {pct}% of articles",
                              {pct: fmtNum(conc.top_share * 100, 1)})
                  : "top 3 hold " + fmtNum(conc.top_share * 100, 1) + "%")}</span>`
              : "") + `</div>`;
        concHtml = _figLorenz(conc.curve, {
          aria: t("Lorenz curve of how unevenly the corpus draws on its sources"),
          empty: t("No source has stored an article yet."),
        }) + gLine;
      }

      host.innerHTML =
        block(t("Tone measurement by language"), sentHtml, sent) +
        block(t("Quarantine composition"), quarHtml, quar) +
        block(t("How evenly the corpus draws on its sources"), concHtml, conc) +
        // C4 is a FULL articles scan, so it stays behind an explicit click — never
        // loaded just because the subtab was opened.
        `<div class="fig-block"><h3 class="fig-title">${esc(t("Article length"))}</h3>` +
        `<div id="fig-length-host"><button class="secondary" id="fig-length-run">` +
        `${esc(t("Measure article lengths"))}</button>` +
        `<div class="hint muted">${esc(t("This reads every article row, so it runs only when you ask."))}</div>` +
        `</div></div>`;
      const runBtn = $("fig-length-run");
      if (runBtn) runBtn.addEventListener("click", renderArticleLengthFigure);
    }

    // C4 — the word-count distribution. Its own function because it is the one figure
    // here that costs a full scan, so it must be reachable only by a deliberate act.
    async function renderArticleLengthFigure() {
      const box = $("fig-length-host");
      if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      box.innerHTML = `<div class="muted">${esc(t("Measuring…"))}</div>`;
      let d;
      try { d = await api("/api/insights/figures/article-length"); }
      catch (e) { box.innerHTML = `<div class="fig-empty">${esc(t("Could not load this figure."))}</div>`; return; }
      // measurable === false means the set was EMPTY. The underlying report returns
      // all-None percentiles with an all-ZERO histogram for an empty set, which draws
      // as a flat row of bars — a fabricated "we measured, and found nothing".
      if (!d.measurable) {
        box.innerHTML = figEmpty(t("No article carries a word count in a space-separated language yet.")) +
          figMeta(d);
        return;
      }
      const ex = d.excluded_unsegmented || {};
      const rows = (d.buckets || []).map(b => ({label: b.label, n: b.n, color: "var(--fig-1)"}));
      box.innerHTML =
        _figBars(rows, {
          title: t("Articles by word-count range"),
          aria: t("Articles by word-count range"),
        }) +
        `<div class="hint muted">${esc(t("Ranges, not equal-width bins — compare one bar with another, not the shape."))}</div>` +
        `<div class="hint">${esc(OOI18N && OOI18N.tf
          ? OOI18N.tf("{scanned} articles scanned · {counted} had a word count · {excluded} excluded as not space-separated",
                      {scanned: fmtNum(d.scanned), counted: fmtNum(d.with_word_count), excluded: fmtNum(ex.n || 0)})
          : `${d.scanned} scanned · ${d.with_word_count} counted · ${ex.n || 0} excluded`)}</div>` +
        ((ex.languages || []).length
          ? `<div class="hint muted">${esc(t("Excluded languages"))}: ` +
            (ex.languages || []).map(l => esc(ooLangName(l, l))).join(", ") + `</div>`
          : "") +
        figMeta(d);
    }

    async function renderLibraryActivityGraphs() {
      const host = $("lib-activity-graphs");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const tiles = await Promise.all([
          _libGraphTile("articles_per_hour", LIB_DEFAULT_DAYS),
          _libGraphTile("sources", LIB_DEFAULT_DAYS),
          _libGraphTile("keywords", LIB_DEFAULT_DAYS),
          _libQualificationTile(LIB_DEFAULT_DAYS),
        ]);
        // The rhythm heatmap sits BESIDE the tiles, never instead of them (the
        // chart-beside-table rule): it reuses the articles_per_hour series
        // _libGraphTile has already fetched and stashed, so it costs no request.
        const rhythmSeries = ((_libGraphData.articles_per_hour || {}).series) || [];
        const rhythm = ingestRhythmSvg(rhythmSeries);
        // Per-language growth sits BESIDE the counters, never instead of them.
        // Its own fetch: it is the one series the /history metrics cannot express
        // (a list of series, not a single [{t,n}]).
        const lang = await _libLanguageTile(LIB_DEFAULT_DAYS);
        host.innerHTML = `<div class="row" style="flex-wrap:wrap;gap:10px">${tiles.join("")}</div>`
          + `<div class="row" style="flex-wrap:wrap;gap:10px;margin-top:10px">${lang}</div>`
          + (rhythm ? `<h3 class="lib-sub">${esc(t("Ingest rhythm"))}</h3>` + rhythm : "");
        _libRenderQualChart(host);
      } catch (e) {
        host.innerHTML = `<div class="note err">${esc(e.message || e)}</div>`;
      }
    }
    function renderLibraryWikiGraphs() {
      return _renderLibGraphHost("lib-wiki-graphs", [
        ["wiki_pages", LIB_DEFAULT_DAYS], ["wiki_revisions", LIB_DEFAULT_DAYS],
      ]);
    }
    function renderLibraryLawGraphs() {
      return _renderLibGraphHost("lib-law-graphs", [
        ["law_documents", LIB_DEFAULT_DAYS], ["law_revisions", LIB_DEFAULT_DAYS],
      ]);
    }
    function enlargeLibMetric(metric) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const d = _libGraphData[metric];
      if (!d || !Array.isArray(d.series)) return;   // defensive: nothing to enlarge
      const label = t(LIB_METRIC_LABEL_KEYS[metric] || metric);
      const caveat = d.recording_began_at
        ? t("Recording began at {x}.").replace("{x}", d.recording_began_at) : "";
      chartEnlarge(label, [{label, unit: label,
        points: d.series.map(p => ({t: p.t, v: p.n}))}], caveat);
    }

    async function loadDbStats() {
      const el = $("db-stats");
      try {
        const s = await api("/api/database/stats");
        const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
        const entries = Object.entries(s.counts || {}).filter(([k]) => !DB_STAT_HIDDEN_KEYS.has(k));
        const keys = entries.map(([k]) => k).join(",");
        if (DB_KEYS !== keys) {                       // (re)build grid with stable number nodes
          DB_KEYS = keys;
          el.innerHTML = entries.length
            ? entries.map(([k]) =>
                `<div class="stat"><div class="n" id="db-n-${k}" data-v="0">0</div><div class="k">${esc(t9(DB_STAT_LABELS[k] || k))}</div></div>`).join("")
            : '<div class="muted">No tables yet.</div>';
        }
        for (const [k, v] of entries) {
          const n = document.getElementById("db-n-" + k);
          if (n) animateCount(n, v);
        }
        // The DB file is ONE component of the whole footprint; once the Storage-footprint
        // panel has measured it, show the all-stores total here too so the number is honest
        // about being only the database (never implying it is the app's whole disk use).
        const _t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
        const gt = _sfCache && (_sfCache.totals || {}).grand_total_bytes;
        const foot = gt ? ` <span class="muted">· ${esc(_t("all stores"))} <strong>${esc(_fmtBytes(gt))}</strong> (${esc(_t("see Storage footprint below"))})</span>` : "";
        $("db-file").innerHTML = s.file
          ? `Backend <span class="pill">${esc(s.backend)}</span> · on disk ` +
            `<strong>${humanBytes(s.file.bytes)}</strong> ` +
            `<span class="muted">(${esc(s.file.path)})</span>` + foot
          : `Backend <span class="pill">${esc(s.backend)}</span> · ${esc(s.url_summary)}`;
      } catch (e) { el.innerHTML = `<div class="note err">Could not load stats: ${esc(e.message)}</div>`; DB_KEYS = null; }
    }

    // Live polling manager: each tab can register a refresh fn + interval; only
    // the active tab's poller runs, and only while the window is visible.
    const LIVE = {
      // Home self-updates while open: stats strip + status + briefing (the latter
      // re-renders only when generated_at changes). Replaces the old Refresh
      // button. Conservative cadence; stats are server-cached ~30 s.
      home:     {ms: 15000, fn: () => refreshHomeLive()},
      // Stats every tick; the coverage panel every 4th (it groups all sources,
      // cheap but no need for 4s cadence) — live data, so no Refresh button.
      // Only the VISIBLE Library view is polled (2026-08-01 ruling 9): refreshing a
      // subtab nobody is looking at would re-fetch the coverage map and re-walk the
      // counters behind the user's back, defeating the point of loading a view on
      // select. Each branch refreshes exactly the panels its own view shows.
      library:  {ms: 4000, fn: () => {
        if (_libView === "storage") loadDbStats();
        if ((++_covTick % 4) === 1) {
          if (_libView === "coverage") loadCoverage();
          if (_libView === "overview") renderLibraryOverview();
        }
      }},
      ingest:   {ms: 5000, fn: () => refreshSchedulerLive()},
      insights: {ms: 6000, fn: () => loadInsights()},
      wiki:     {ms: 6000, fn: () => refreshWikiLive()},
    };
    let _live = null;
    function startLive(name) {
      stopLive();
      const spec = LIVE[name];
      if (!spec) return;
      // Single-flight: never stack an identical poll while the previous one is still in
      // flight. Under 429 backpressure a poll (which awaits several api() calls, each of
      // which may itself be retrying) can outlast its interval; without this guard the
      // ticks pile up and add load exactly when the server is already saturated.
      // refreshHomeLive returns a promise for its whole awaited chain, so Home is covered.
      let inflight = false;
      const tick = async () => {
        if (inflight) return;
        inflight = true;
        try { await spec.fn(); } finally { inflight = false; }
      };
      tick();
      _live = {name, timer: setInterval(() => { if (!document.hidden) tick(); }, spec.ms)};
    }
    function stopLive() { if (_live) { clearInterval(_live.timer); _live = null; } }
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      const active = document.querySelector(".tab-page.active");
      if (active && !_live) startLive(active.id.replace("tab-", ""));
    });

    // Live refreshers that only touch STATUS/PROGRESS displays (never the config
    // inputs the user may be editing).
    async function refreshSchedulerLive() {
      try { renderSchedStatus(await api("/api/scheduler/status")); } catch (e) { /* keep last */ }
    }
    let _wikiStatusBuilt = false;
    function renderWikiStatus(s) {
      const el = $("wiki-status");
      if (!_wikiStatusBuilt) {
        _wikiStatusBuilt = true;
        el.innerHTML =
          `<span class="pill"><span id="wiki-n-watched" data-v="0">0</span>/` +
          `<span id="wiki-n-pages" data-v="0">0</span> pages watched</span> · ` +
          `<span id="wiki-n-rev" data-v="0">0</span> tracked edits · ` +
          `<span class="pill" id="wiki-flag-pill"><span id="wiki-n-flagged" data-v="0">0</span> flagged</span>`;
      }
      animateCount($("wiki-n-watched"), s.watched);
      animateCount($("wiki-n-pages"), s.pages);
      animateCount($("wiki-n-rev"), s.revisions);
      animateCount($("wiki-n-flagged"), s.flagged);
      $("wiki-flag-pill").className = "pill " + (s.flagged ? "warn" : "ok");
    }

    async function refreshWikiLive() {
      try { renderWikiStatus(await api("/api/wiki/status")); } catch (e) { /* keep last */ }
      loadWikiDumps();
    }

    // -- World coverage ----------------------------------------------------- //
    let COV_COUNTRIES = [];   // cached per-country rows for client-side filtering
    let COV_MISSING = [];     // [{code, name}] for the gap pills
    let _covTick = 0;         // slow-cadence counter for the library live poller
    let _covStamp = "";       // last payload fingerprint (skip repaint when unchanged)

    // Part-to-whole with more categories than a donut can honestly carry: sorted
    // horizontal bars, the replacement this project's OWN chart-decision framework
    // names (docs/research/dataviz/chart_decision_framework.md). Bar length on a
    // common scale beats angle/area for reading shares, and it degrades gracefully
    // to any number of rows. Same data contract and same honesty as ooDonut: real
    // total, real per-row counts, no score.
    function _ooShareBars(el, items, total, opts, t) {
      const max = items[0] ? items[0].value : 1;
      const rows = items.map((d) =>
        `<div style="display:flex;align-items:center;gap:8px;font-size:12px;line-height:1.7">`
        + `<span style="flex:0 0 34%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"`
        + ` title="${esc(d.label)}">${esc(d.label)}</span>`
        + `<span style="flex:1;background:var(--panel3);border-radius:3px;height:9px;position:relative">`
        + `<span style="display:block;height:100%;border-radius:3px;background:var(--accent);`
        + `width:${Math.max(1, Math.round(d.value / max * 100))}%"></span></span>`
        + `<span class="muted" style="flex:0 0 auto">${esc(fmtNum(d.value))} · `
        + `${Math.round(d.value / total * 100)}%</span></div>`
      ).join("");
      el.innerHTML =
        `<div role="img" aria-label="${esc(opts.aria || "")}">`
        + `<div style="font-size:12px;margin-bottom:6px">${esc(fmtNum(total))} `
        + `${esc(opts.centerLabel || "")}</div>${rows}</div>`;
    }

    // Reusable self-contained SVG DONUT (no deps; like ooChart/ooMap) — categorical
    // proportions with a legend. data: [{label, value}] (labels already display-ready).
    // Stroke-dasharray on one circle per slice handles any slice count AND the single
    // full-ring case robustly. Honest: shows the real total + per-slice counts; no score.
    //
    // SLICE-COUNT GUARD (GUI audit 2026-07-28, finding V-4). The project's own
    // committed chart-decision framework says, for part-to-whole: "Pie/donut only
    // if <=4-5 slices, share labels shown, and precise comparison is not required;
    // otherwise bars" — and lists "many-slice pie" on its REJECT list. This
    // renderer had no guard and its only caller feeds it `unlocated.by_language`,
    // an UNBOUNDED language set: past ~5 slices the evenly-spaced hues stop being
    // distinguishable and angle-reading stops being reliable, which is exactly the
    // failure the framework rejects. Above the threshold we fall back to sorted
    // bars. NOTHING IS TRUNCATED -- every category is still shown, just in the
    // encoding that can carry it (the anti-capping rule: a display cap may never
    // silently drop data).
    const _DONUT_MAX_SLICES = 5;

    function ooDonut(host, data, opts) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      const el = (typeof host === "string") ? document.getElementById(host) : host;
      if (!el) return;
      opts = opts || {};
      const items = (data || []).filter(d => d && d.value > 0).slice().sort((a, b) => b.value - a.value);
      const total = items.reduce((s, d) => s + d.value, 0);
      if (!items.length || total <= 0) {
        el.innerHTML = `<div class="muted">${esc(opts.empty || t("Nothing to chart."))}</div>`;
        return;
      }
      if (items.length > _DONUT_MAX_SLICES) { _ooShareBars(el, items, total, opts, t); return; }
      const size = opts.size || 184, cx = size / 2, cy = size / 2;
      const sw = size * 0.16, rMid = size * 0.42 - sw / 2;
      const C = 2 * Math.PI * rMid;
      const color = i => `hsl(${Math.round(i * 360 / items.length) % 360} 60% 55%)`;
      let acc = 0;
      const slices = items.map((d, i) => {
        const frac = d.value / total;
        const seg = `<circle cx="${cx}" cy="${cy}" r="${rMid.toFixed(2)}" fill="none" stroke="${color(i)}"`
          + ` stroke-width="${sw.toFixed(2)}" stroke-dasharray="${(frac * C).toFixed(2)} ${C.toFixed(2)}"`
          + ` stroke-dashoffset="${(-acc * C).toFixed(2)}"><title>${esc(d.label)}: ${esc(fmtNum(d.value))}`
          + `${opts.unit ? " " + esc(opts.unit) : ""} (${Math.round(frac * 100)}%)</title></circle>`;
        acc += frac;
        return seg;
      }).join("");
      const legend = items.map((d, i) =>
        `<div style="display:flex;align-items:center;gap:6px;font-size:12px;line-height:1.6">`
        + `<span style="width:10px;height:10px;border-radius:2px;background:${color(i)};flex:none"></span>`
        + `<span>${esc(d.label)}</span>`
        + `<span class="muted" style="margin-left:auto">${esc(fmtNum(d.value))} · ${Math.round(d.value / total * 100)}%</span></div>`
      ).join("");
      el.innerHTML =
        `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">`
        + `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${esc(opts.aria || "")}" style="flex:none">`
        + `<g transform="rotate(-90 ${cx} ${cy})">${slices}</g>`
        + `<text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="${(size * 0.17).toFixed(0)}" font-weight="700" fill="currentColor">${esc(fmtNum(total))}</text>`
        + `<text x="${cx}" y="${(cy + size * 0.13).toFixed(0)}" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.6">${esc(opts.centerLabel || "")}</text>`
        + `</svg><div style="flex:1;min-width:160px;max-height:200px;overflow:auto">${legend}</div></div>`;
    }

    // Library "World coverage" map (field remark 10): per-country ARTICLE counts via the
    // shared ooMap choropleth + a donut of the 'no country' articles by language. Its own
    // stamp so a live poll only repaints when the data actually changes (no zoom-reset churn).
