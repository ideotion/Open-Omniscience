/* app-sources.js — coverage, sources, scheduler

   The coverage map and regional breakdown, source management and batch ingest, and
   the collection scheduler with its rate-mode knob.

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
    let _covMapStamp = "";
    async function renderCoverageMap() {
      const mapHost = $("coverage-map");
      if (!mapHost) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      let d;
      try { d = await api("/api/insights/map-coverage"); }
      catch (e) { mapHost.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const stamp = JSON.stringify([d.by_country, d.unlocated]);
      if (stamp === _covMapStamp) return;   // live poll: unchanged, no repaint
      _covMapStamp = stamp;
      const values = {}, names = {}, points = [];
      (d.by_country || []).forEach(r => {
        names[r.country] = ooRegionName(r.country, r.name);
        const v = r.articles;
        if (v != null && isFinite(v) && v > 0) {
          values[r.country] = v;
          if (r.lat != null && r.lon != null) {
            points.push({ iso2: r.country, lat: r.lat, lon: r.lon, value: v, label: names[r.country] });
          }
        }
      });
      const unloc = (d.unlocated && d.unlocated.articles) || 0;
      ooMap(mapHost, {
        values, names, points, unit: t("articles"),
        valueLabel: (iso, v) => `${fmtNum(v)} ${t("articles")}`,
        // click a country -> filter the catalogue table below to it (ties the map to the table).
        onCountry: (code) => { const f = $("cov-filter"); if (f) { f.value = names[code] || code; renderCoverageTable(); } },
        aria: t("Articles collected per country."),
        method: t("Articles collected, grouped by each source's catalogued country (ISO-2). Counts only, no score."),
        caveat: t("Country is operator/catalogue-asserted; articles whose source has no country are counted but never placed on the map — see the language breakdown below.")
          + (unloc ? `  ${fmtNum(unloc)} ${t("with no country.")}` : ""),
      });
      // donut: the 'no country' articles by language (full names via ooLangName).
      const donutHost = $("coverage-unlocated");
      if (donutHost) {
        const byLang = (d.unlocated && d.unlocated.by_language) || {};
        const ddata = Object.keys(byLang).map(code => ({
          value: byLang[code], label: code ? ooLangName(code, code) : t("Unknown language"),
        })).filter(x => x.value > 0);
        if (!ddata.length) {
          donutHost.innerHTML = `<div class="muted">${esc(t("All collected articles have a country."))}</div>`;
        } else {
          const tot = ddata.reduce((s, x) => s + x.value, 0);
          donutHost.innerHTML =
            `<div class="hint" style="margin-bottom:6px">${esc(fmtNum(tot))} ${esc(t("articles with no country, by language"))}</div>`
            + `<div id="cov-donut-svg"></div>`;
          ooDonut("cov-donut-svg", ddata, { unit: t("articles"), centerLabel: t("articles"),
            aria: t("Articles with no country, by language.") });
        }
      }
    }

    async function loadCoverage() {
      renderCoverageMap();   // fire-and-forget the world map + unlocated donut (own stamp)
      const el = $("coverage-summary");
      if (!_covStamp) el.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const [c, d] = await Promise.all([
          api("/api/database/coverage"),
          api("/api/database/countries"),
        ]);
        const stamp = JSON.stringify([c, d.countries, d.missing]);
        if (stamp === _covStamp) return;   // live poll: nothing changed, no repaint
        _covStamp = stamp;
        el.innerHTML =
          `<div class="stat"><div class="n">${c.covered}/${c.total_countries}</div><div class="k">countries</div></div>` +
          `<div class="stat"><div class="n">${c.coverage_pct}%</div><div class="k">coverage</div></div>` +
          `<div class="stat"><div class="n">${c.missing_count}</div><div class="k">not covered</div></div>` +
          `<div class="stat"><div class="n">${(c.thin||[]).length}</div><div class="k">thin (&lt;${c.thin_threshold})</div></div>`;
        renderCoverageRegions(c);
        COV_COUNTRIES = d.countries || [];
        COV_MISSING = (d.missing || []).map(code =>
          ({code, name: (d.missing_names || {})[code] || code}));
        renderCoverageTable();
      } catch (e) {
        _covStamp = "";   // error rendered: force a repaint on the next good poll
        el.innerHTML = `<div class="note err">Coverage unavailable: ${esc(e.message)}</div>`;
      }
    }

    // Regional balance vs the configured floors (configs/catalog_targets.yml) —
    // the de-US-centring metric. Floors are labelled aspirations, never claims.
    // Sorted bars for "sources per region, against that region's floor".
    //
    // GUI audit 2026-07-28 finding V-2: this surface emitted a table and no
    // chart, yet the question it answers -- WHICH regions sit below their
    // floor -- is a length comparison against a target, which the project's
    // own chart-decision framework puts squarely in bar territory (position
    // on a common scale beats reading paired numbers out of a table).
    //
    // Added BESIDE the table, never replacing it (invariant #8 + the Desk
    // lesson: the table stays the precise, screen-readable, sortable record;
    // the chart is the glance). Honest by construction: real counts only, no
    // score; the floor is drawn as its own marked line so "below floor" is
    // visible rather than asserted; a region with no floor configured is
    // still plotted, just without a marker (never a fabricated target).
    function _regionFloorBars(regions) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const rows = (regions || []).filter(r => r && (r.sources > 0 || r.countries_total > 0));
      if (rows.length < 2) return "";          // one bar compares nothing
      rows.sort((a, b) => (b.sources || 0) - (a.sources || 0));
      // Scale to the largest of value-or-floor so a floor above every bar is
      // still on-canvas -- otherwise a badly-missed target would fall off the
      // right edge and read as "no floor".
      const max = Math.max(1, ...rows.map(r => Math.max(r.sources || 0, r.min_sources || 0)));
      const scale = (window.ooViz && ooViz.linearScale)
        ? ooViz.linearScale(0, max, 0, 100)
        : (v => (v / max) * 100);
      const bars = rows.map(r => {
        const below = r.sources_met === false;
        const w = Math.max(0.5, scale(r.sources || 0));
        const floorPct = (r.min_sources != null) ? scale(r.min_sources) : null;
        const marker = floorPct == null ? "" :
          `<span title="${esc(t("floor"))}: ${esc(String(r.min_sources))}" style="position:absolute;`
          + `left:${floorPct.toFixed(1)}%;top:-2px;bottom:-2px;width:2px;background:var(--fg);opacity:.55"></span>`;
        return `<div style="display:flex;align-items:center;gap:8px;font-size:12px;line-height:1.8">`
          + `<span style="flex:0 0 30%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.region)}</span>`
          + `<span style="flex:1;position:relative;background:var(--panel3);border-radius:3px;height:10px">`
          + `<span style="display:block;height:100%;border-radius:3px;width:${w.toFixed(1)}%;`
          + `background:${below ? "var(--warn)" : "var(--accent)"}"></span>${marker}</span>`
          + `<span class="muted" style="flex:0 0 auto">${esc(String(r.sources || 0))}`
          + `${r.min_sources != null ? " / " + esc(String(r.min_sources)) : ""}</span></div>`;
      }).join("");
      return `<div style="margin-top:8px" role="img" aria-label="${esc(t("Sources per region against each region's floor."))}">`
        + bars
        + `<div class="hint" style="margin-top:4px">${esc(t("Bar = sources collected; the vertical mark is that region's floor. Counts only, no score."))}</div></div>`;
    }

    function renderCoverageRegions(c) {
      const reg = c.regional;
      const host = $("coverage-regions");
      if (!reg || !(reg.regions || []).length) { host.innerHTML = ""; return; }
      const mark = ok => ok === null ? '<span class="muted">—</span>'
        : ok ? '<span class="pill ok">ok</span>' : '<span class="pill warn">below floor</span>';
      const rows = reg.regions.filter(r => r.countries_total > 0 || r.sources > 0).map(r =>
        `<tr><td>${esc(r.region)}</td>` +
        `<td>${r.sources}${r.min_sources != null ? ` <span class="muted">/ ${r.min_sources}</span>` : ""} ${mark(r.sources_met)}</td>` +
        `<td>${r.countries_covered}/${r.countries_total}${r.min_countries != null ? ` <span class="muted">/ ${r.min_countries}</span>` : ""} ${mark(r.countries_met)}</td></tr>`
      ).join("");
      const tc = reg.top_country || {};
      const tcName = (c.names || {})[tc.code] || tc.code || "—";
      const over = tc.max_share_pct != null && tc.share_pct > tc.max_share_pct;
      const located = reg.located_share_pct != null
        ? ` · ${reg.located_share_pct}% of sources carry a country` +
          (reg.min_located_share_pct != null ? ` <span class="muted">(floor ${reg.min_located_share_pct}%)</span>` : "")
        : "";
      host.innerHTML =
        `<strong>Regional balance</strong> <span class="muted">(floors are working targets from configs/catalog_targets.yml)</span>` +
        _regionFloorBars(reg.regions) +
        `<div style="overflow:auto;margin-top:6px"><table>` +
        `<tr><th>Region</th><th>Sources / floor</th><th>Countries / floor</th></tr>${rows}</table></div>` +
        `<div style="margin-top:6px">Top country: <strong>${esc(tcName)}</strong> — ${tc.sources} sources, ` +
        `${tc.share_pct}% of located${tc.max_share_pct != null ?
          ` <span class="pill ${over ? "warn" : "ok"}">${over ? "above" : "within"} the ${tc.max_share_pct}% guard</span>` : ""}` +
        `${located}</div>`;
    }

    function renderCoverageTable() {
      const q = ($("cov-filter").value || "").trim().toLowerCase();
      const rows = COV_COUNTRIES.filter(c => {
        if (!q) return true;
        if (c.code.includes(q)) return true;
        if ((c.name || "").toLowerCase().includes(q)) return true;
        return (c.top_tags || []).some(([t]) => t.toLowerCase().includes(q));
      });
      const t = $("coverage-table");
      t.innerHTML = "<tr><th>Country</th><th>Region</th><th>Sources</th><th>Enabled</th><th>Topic keywords (source tags)</th></tr>" +
        (rows.length ? rows.map(c => {
          const label = c.name && c.name !== c.code
            ? `${esc(c.name)} <span class="muted">${esc(c.code.toUpperCase())}</span>`
            : esc(c.code);
          const tags = (c.top_tags || []).map(([t, n]) =>
            `<span class="pill" style="cursor:pointer" title="show ${esc(t)} sources in ${esc(c.name || c.code)}"
                onclick="openSourcesForKeyword(${esc(JSON.stringify(c.code))}, ${esc(JSON.stringify(t))})">${esc(t)} ${n}</span>`
          ).join(" ") || '<span class="muted">—</span>';
          const codeCell = `<strong style="cursor:pointer" title="show sources in ${esc(c.name || c.code)}"
                onclick="openSourcesForKeyword(${esc(JSON.stringify(c.code))}, null)">${label}</strong>`;
          return `<tr><td>${codeCell}</td><td class="muted">${esc(c.region || "—")}</td><td>${c.sources}</td>
                  <td class="muted">${c.enabled}</td><td>${tags}</td></tr>`;
        }).join("") : `<tr><td colspan="5" class="muted">No matching countries.</td></tr>`);
      // Not-covered list (same filter, matched on name or code).
      const miss = COV_MISSING.filter(x =>
        !q || x.code.includes(q) || x.name.toLowerCase().includes(q));
      $("coverage-gaps").innerHTML = miss.length
        ? `<strong>Not covered (${miss.length})</strong>: ` +
          miss.slice(0, 120).map(x =>
            `<span class="pill" title="${esc(x.code.toUpperCase())}">${esc(x.name)}</span>`).join(" ") +
          (miss.length > 120 ? ` <span class="muted">…and ${miss.length - 120} more</span>` : "")
        : `<span class="pill ok">every listed country has at least one source</span>`;
    }

    // -- Sources: ingest dropdown + add + seed ------------------------------ //
    async function loadSources() {
      let sources = [];
      try { sources = await api("/api/sources"); } catch (e) { toast("Could not load sources: " + e.message, "err"); }
      const sel = $("ing-source");
      sel.innerHTML = sources.filter(s => s.rss_url).map(s =>
        `<option value="${s.id}">${esc(s.name)}</option>`).join("")
        || '<option value="">(no sources with an RSS feed)</option>';
      loadUnmanagedLanguages();
    }

    // Surface how many enabled sources are in languages the keyword engine cannot
    // analyse (no stoplist / unsegmented) — junk that pollutes analytics + slows the
    // app. The panel only appears when there's something to disable.
    async function loadUnmanagedLanguages() {
      const panel = $("unmanaged-lang-panel"); if (!panel) return;
      let r; try { r = await api("/api/sources/unmanaged-languages"); } catch (e) { panel.style.display = "none"; return; }
      if (!r || !r.enabled_unmanaged) { panel.style.display = "none"; return; }
      const langs = Object.entries(r.by_language).map(([k, n]) => `${esc(k)} (${n})`).join(", ");
      $("unmanaged-lang-summary").innerHTML =
        `<strong>${r.enabled_unmanaged}</strong> enabled source(s) in languages we can't analyse yet: ${langs}.`;
      panel.style.display = "";
    }

    async function disableUnmanagedLanguages() {
      const btn = $("unmanaged-lang-btn"); if (btn) btn.disabled = true;
      try {
        const r = await api("/api/sources/disable-unmanaged-languages", {method: "POST"});
        toast(`Disabled ${r.disabled} source(s) in unmanaged languages (kept — re-enable any time).`);
        loadUnmanagedLanguages();
        if (typeof loadManagedSources === "function") loadManagedSources();
      } catch (e) { toast(e.message, "err"); }
      finally { if (btn) btn.disabled = false; }
    }

    async function seedDefaults() {
      try {
        const r = await api("/api/sources/seed-defaults", {method: "POST"});
        toast(`Seeded ${r.seeded.created} new source(s) (${r.seeded.skipped} already present).`);
        loadSources(); loadManagedSources(); loadDbStats(); loadCoverage();
      } catch (e) { toast(_failMsg("Seed failed: {error}", e), "err"); }
    }

    async function addSource() {
      const body = {
        name: $("s-name").value.trim(),
        domain: $("s-domain").value.trim(),
        rss_url: $("s-rss").value.trim() || null,
        tags: $("s-tags").value.trim(),
      };
      if (!body.name || !body.domain) { toast("Name and domain are required.", "err"); return; }
      try {
        await api("/api/sources/", {method: "POST", body: JSON.stringify(body)});
        toast("Source added.");
        ["s-name","s-domain","s-rss","s-tags"].forEach(id => $(id).value = "");
        loadSources(); loadManagedSources(); loadDbStats();
      } catch (e) { toast(_failMsg("Add failed: {error}", e), "err"); }
    }

    // -- Sources: management table ------------------------------------------ //
    // Source-management list state: filters + sort + paging.
    const SRC = {offset: 0, limit: 50, sort: "name", order: "asc"};

    // Multi-select dropdown filters (#23): each <details class="msel"> is a checklist.
    // Within a filter the checked values are OR'd; across filters AND'd; tags add an
    // any|all toggle. Read only the checklist's own checkboxes (NOT the tag-mode box).
    function mselValues(id) {
      const det = $(id); if (!det) return [];
      const list = det.querySelector(".msel-list");
      return list ? [...list.querySelectorAll("input:checked")].map(c => c.value) : [];
    }
    function updateMselSummary(id) {
      const det = $(id); if (!det) return;
      const sum = det.querySelector("summary"); if (!sum) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const v = mselValues(id);
      sum.textContent = v.length === 0 ? t("Any") : (v.length === 1 ? v[0] : v.length + " " + t("selected"));
    }
    async function loadSrcFacets() {
      let f; try { f = await api("/api/sources/facets"); } catch (e) { return; }
      const fill = (id, rows, labeler) => {
        const det = $(id); if (!det) return;
        const list = det.querySelector(".msel-list"); if (!list) return;
        list.innerHTML = (rows || []).length
          ? rows.map(x => `<label class="msel-opt"><input type="checkbox" value="${esc(x.key)}" onchange="srcMselChanged('${id}')"> ${esc(labeler ? labeler(x.key) : x.key)} <span class="muted">·${x.n}</span></label>`).join("")
          : `<div class="muted" style="padding:4px">—</div>`;
      };
      fill("src-msel-language", f.languages, k => (typeof ooLangName === "function" ? ooLangName(k, k) : k));
      fill("src-msel-country", f.countries, k => (typeof ooRegionName === "function" ? ooRegionName(k, k) : k));
      fill("src-msel-source_type", f.types);
      fill("src-msel-tag", f.tags);
      ["src-msel-language", "src-msel-country", "src-msel-source_type", "src-msel-tag"].forEach(updateMselSummary);
    }
    function srcMselChanged(id) { updateMselSummary(id); applySrcFilters(); }

    function srcQuery() {
      const p = new URLSearchParams();
      const q = $("src-search").value.trim(); if (q) p.set("q", q);
      const lang = mselValues("src-msel-language"); if (lang.length) p.set("language", lang.join(","));
      const country = mselValues("src-msel-country"); if (country.length) p.set("country", country.join(","));
      const types = mselValues("src-msel-source_type"); if (types.length) p.set("source_type", types.join(","));
      const tags = mselValues("src-msel-tag");
      if (tags.length) { p.set("tag", tags.join(",")); if ($("src-tag-all") && $("src-tag-all").checked) p.set("tag_mode", "all"); }
      const en = $("src-enabled").value; if (en) p.set("enabled", en);
      p.set("sort", SRC.sort); p.set("order", SRC.order);
      p.set("limit", SRC.limit); p.set("offset", SRC.offset);
      return p;
    }

    function applySrcFilters() { SRC.offset = 0; loadManagedSources(); }
    function clearSrcFilters() {
      $("src-search").value = "";
      ["src-msel-language", "src-msel-country", "src-msel-source_type", "src-msel-tag"].forEach(id => {
        const det = $(id); if (det) det.querySelectorAll(".msel-list input").forEach(c => { c.checked = false; });
        updateMselSummary(id);
      });
      if ($("src-tag-all")) $("src-tag-all").checked = false;
      $("src-enabled").value = ""; SRC.offset = 0; loadManagedSources();
    }
    function srcPage(dir) {
      const next = SRC.offset + dir * SRC.limit;
      if (next < 0) return;
      SRC.offset = next; loadManagedSources();
    }
    function setSrcSort(col) {
      if (SRC.sort === col) SRC.order = (SRC.order === "asc" ? "desc" : "asc");
      else { SRC.sort = col; SRC.order = "asc"; }
      SRC.offset = 0; loadManagedSources();
    }
    function srcTh(label, col) {
      const arrow = SRC.sort === col ? (SRC.order === "asc" ? " ▲" : " ▼") : "";
      return `<th style="cursor:pointer" onclick="setSrcSort('${col}')">${label}${arrow}</th>`;
    }

    async function loadManagedSources() {
      const t = $("src-table");
      try {
        const d = await api("/api/catalog/sources?" + srcQuery().toString());
        const shownFrom = d.total ? SRC.offset + 1 : 0;
        const shownTo = Math.min(SRC.offset + SRC.limit, d.total);
        $("src-meta").textContent = `${d.total} source(s)` + (d.total ? ` · showing ${shownFrom}–${shownTo}` : "");
        $("src-page").textContent = `page ${Math.floor(SRC.offset / SRC.limit) + 1} of ${Math.max(1, Math.ceil(d.total / SRC.limit))}`;
        t.innerHTML = "<tr>" + srcTh("Name","name") + srcTh("Domain","domain") + srcTh("Type","source_type") +
          srcTh("Country","country") + srcTh("Lang","language") + srcTh("Pri","priority") +
          srcTh("Articles","articles") + "<th>Enabled</th><th></th></tr>" +
          (d.sources.length ? d.sources.map(s => sourceRow(s)).join("")
            : `<tr><td colspan="9" class="muted">No sources match. Adjust filters, add one, or seed the starter set.</td></tr>`);
      } catch (e) { toast("Could not load sources: " + e.message, "err"); }
    }

    function sourceRow(s) {
      const tags = (s.tags || []).map(x =>
        `<span class="pill" style="cursor:pointer" title="filter by this tag" onclick="srcFilterTag(${esc(JSON.stringify(x))})">${esc(x)}</span>`).join(" ");
      const prio = [1,2,3].map(p =>
        `<option value="${p}" ${s.priority===p?"selected":""}>${p}</option>`).join("");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      return `<tr>
        <td>${esc(s.name)}<div class="muted" style="font-size:12px">${tags}</div></td>
        <td>${esc(s.domain)}${s.rss_url?' <span class="pill ok" title="has RSS feed">rss</span>':''}</td>
        <td class="muted">${esc(s.source_type || "—")}</td>
        <td class="muted" title="${esc((s.country || "").toUpperCase())}">${esc(s.country ? ooRegionName(s.country, s.country_name) : (s.country_name || "—"))}</td>
        <td class="muted" title="${esc(s.language || "")}">${esc(s.language ? ooLangName(s.language, s.language) : "—")}</td>
        <td><select class="tiny" style="width:auto;padding:3px"
              onchange="updateSource(${s.id},{priority:Number(this.value)})">${prio}</select></td>
        <td class="muted">${s.article_count!=null?s.article_count:'—'}</td>
        <td><input type="checkbox" style="width:auto" ${s.enabled?"checked":""}
              onchange="updateSource(${s.id},{enabled:this.checked})"></td>
        <td><button class="tiny ghost" onclick="toggleSourceTrail(${s.id})" title="${esc(t("Discovery"))}">${esc(t("Trail"))}</button>
        <button class="tiny ghost" onclick="qualifyAssist(${s.id}, this)" title="${esc(t("Ask the local model whether this source's stored articles read as articles or as navigation soup. A PROPOSAL to review beside the auditor's own evidence — it never changes this source's status or tags."))}">${esc(t("AI check"))}</button>
        <button class="tiny danger" onclick="deleteSource(${s.id}, ${esc(JSON.stringify(s.name))})">Delete</button></td>
      </tr>
      <tr id="src-trail-${s.id}" style="display:none"><td colspan="9"></td></tr>`;
    }

    // E-S5 (2026-08-01): the qualification ASSIST finally has a home. It has existed
    // since B7.2 with no UI trigger at all — a propose-only classifier nobody could
    // reach, which is a dead end rather than a feature. It stays propose-only: the
    // verdict lands in a dated artifact for review BESIDE the auditor's own evidence,
    // and Source.status / Source.tags are never touched by it.
    async function qualifyAssist(sourceId, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const row = document.getElementById("src-trail-" + sourceId);
      if (btn) { btn.disabled = true; btn.textContent = t("Checking…"); }
      try {
        const r = await api("/api/diagnostics/qualification-assist/run",
          {method: "POST", body: JSON.stringify({source_id: sourceId})});
        // Read against the module's REAL keys (article_count / junk_count /
        // unparseable_count / canary), not an assumed {counts: …} shape.
        const msg = `${t("AI check")}: ${r.checked != null ? r.checked : "?"} ${t("checked")} — `
          + `${r.article_count != null ? r.article_count : "?"} ${t("read as articles")}, `
          + `${r.junk_count != null ? r.junk_count : "?"} ${t("as navigation soup")}, `
          + `${r.unparseable_count != null ? r.unparseable_count : "?"} ${t("unreadable")}`
          + ` — ${t("a proposal only; nothing about this source was changed.")}`;
        // A failed canary means the run itself is untrustworthy, which matters more
        // than any of its numbers — so it is stated first, not buried.
        const bad = r.canary && r.canary.ok === false;
        if (row) {
          row.style.display = "";
          row.firstElementChild.innerHTML =
            (bad ? `<div class="card-caveat">${esc(t("The canary check FAILED — treat this run's numbers as unreliable."))}</div>` : "")
            + `<div class="small">${esc(msg)}</div>`;
        } else if (typeof toast === "function") { toast(msg); }
      } catch (e) {
        if (typeof toast === "function") toast(_apiErrorMessage ? _apiErrorMessage(e) : String(e), "err");
      }
      if (btn) { btn.disabled = false; btn.textContent = t("AI check"); }
    }

    // -- Discovery-trail / qualified-citations panel (2026-07-20 ruling, items 1+2) -- //
    // Per-source provenance (where it was discovered + the citing trail) and the
    // qualified-citations tally, expandable inline in the Sources management row.
    // Reuses the row's own table (no new UI paradigm); the qualification status
    // (L1's Source.status) is surfaced here too, since this panel is exactly where
    // "is this admitted yet" belongs.
    const _srcTrailData = {};   // {sourceId: {qualified:[], disqualified:[], pending:[], never_registered:[]}}
    async function toggleSourceTrail(id) {
      const row = $("src-trail-" + id); if (!row) return;
      if (row.style.display !== "none") { row.style.display = "none"; return; }
      row.style.display = "";
      const cell = row.querySelector("td");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      cell.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const [prov, tally] = await Promise.all([
          api(`/api/sources/${id}/provenance`),
          api(`/api/sources/${id}/citation-tally`),
        ]);
        // Every class -- including never_registered/filtered -- keeps its own dict
        // shape from the API (domain + sample_article_ids, +source_id/name when
        // matched), so the drill list always matches the chip's own count.
        _srcTrailData[id] = {
          qualified: tally.qualified || [], disqualified: tally.disqualified || [],
          pending: tally.pending || [], never_registered: tally.never_registered || [],
        };
        cell.innerHTML = _srcTrailHtml(id, prov, tally);
      } catch (e) { cell.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    function _srcTrailHtml(id, prov, tally) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const qs = prov.qualification_status || "unqualified";
      const qsLabel = qs === "unqualified" ? t("pending") : t(qs);
      const qsClass = qs === "qualified" ? "ok" : (qs === "disqualified" ? "err" : "");
      let html = `<div><span class="pill ${qsClass}">${esc(qsLabel)}</span></div>`;
      html += `<div style="margin-top:6px"><strong>${esc(t("Discovery"))}:</strong> `
        + `${esc(prov.channel || "—")} <span class="muted">— ${esc(prov.detail || "")}</span></div>`;
      if (prov.citing_trail) {
        const ct = prov.citing_trail;
        const citerLink = ct.citing_source_domain
          ? ` (<a href="#" onclick="srcJumpToDomain(${esc(JSON.stringify(ct.citing_source_domain))});return false">${esc(ct.citing_source_name || ct.citing_source_domain)}</a>)`
          : (ct.citing_source_name ? ` (${esc(ct.citing_source_name)})` : "");
        html += `<div class="muted" style="margin-top:2px">${esc(t("First cited by"))}: `
          + `<a href="/api/articles/${ct.article_id}/view" target="_blank" rel="noopener">${esc(ct.article_title || ("#" + ct.article_id))}</a>`
          + citerLink + "</div>";
      }
      // Four DRILLABLE classes (qualified/disqualified/pending/never-registered) --
      // each chip's number is exactly the length of the list it expands to (never a
      // rolled-up total that the drill can't account for). The filtered classes
      // (commerce/social/infrastructure -- guardrail b's "tallied separately", NOT
      // folded into never-registered) get their own always-visible, non-drilling line.
      const classes = [
        ["qualified", tally.qualified || []],
        ["disqualified", tally.disqualified || []],
        ["pending", tally.pending || []],
        ["never_registered", tally.never_registered || []],
      ];
      const chips = classes.map(([k, arr]) => {
        const label = k === "never_registered" ? t("never-registered") : t(k);
        return `<button class="tiny ghost" onclick="_srcTrailToggleClass(${id},'${k}')">${esc(label)}: ${arr.length}</button>`;
      }).join(" ");
      html += `<div style="margin-top:8px">${chips}</div>`;
      html += `<div id="src-trail-cls-${id}" class="muted" style="display:none;margin:4px 0;font-size:.85em"></div>`;
      const c = tally.counts || {};
      html += `<div class="muted" style="font-size:.82em;margin-top:4px">`
        + `filtered (excluded from the funnel, not guilt either way): `
        + `commerce ${c.filtered_commerce || 0} · social ${c.filtered_social || 0} · infrastructure ${c.filtered_infrastructure || 0}</div>`;
      html += `<div class="muted" style="font-size:.82em;margin-top:2px">${esc(tally.caveat || "")}</div>`;
      return html;
    }
    function _srcTrailToggleClass(id, cls) {
      const host = $("src-trail-cls-" + id); if (!host) return;
      const arr = (_srcTrailData[id] && _srcTrailData[id][cls]) || [];
      host.style.display = "";
      host.innerHTML = arr.length
        ? arr.map(d => {
            const jump = `<a href="#" onclick="srcJumpToDomain(${esc(JSON.stringify(d.domain))});return false">${esc(d.domain)}</a>`;
            // "the sources' sources" grammar: also link to THIS source's own
            // citing articles for that domain, not just the domain's own row.
            const ids = d.sample_article_ids || [];
            const artsLink = ids.length
              ? ` <a href="#" onclick="openAnalysisForIds(${esc(JSON.stringify(ids))}, ${esc(JSON.stringify(d.domain))});return false" title="Open the articles that cite this domain">↗</a>`
              : "";
            return jump + artsLink;
          }).join(", ")
        : `<span class="muted">—</span>`;
    }
    // Jump to a cited domain's OWN management row (the drill's "linking to that
    // source's own management row" -- the pending/qualified/disqualified classes'
    // domains ARE sources; never_registered domains simply won't match anything).
    function srcJumpToDomain(domain) {
      $("src-search").value = domain;
      applySrcFilters();
    }

    // Check one option in a multi-select checklist by value (used by tag pills + the
    // coverage→sources jump). If the facets list hasn't loaded the value yet, no-op.
    function srcMselCheck(id, value) {
      const det = $(id); if (!det) return false;
      const cb = [...det.querySelectorAll(".msel-list input")].find(c => c.value === value);
      if (cb) { cb.checked = true; updateMselSummary(id); return true; }
      return false;
    }
    function srcFilterTag(tag) { srcMselCheck("src-msel-tag", tag); applySrcFilters(); }

    // Jump from the Database coverage view to the matching sources.
    function openSourcesForKeyword(code, tag) {
      clearSrcFilters();
      showTab("sources");
      // Facets fill on tab open; wait a tick so the checkboxes exist, then check them.
      loadSrcFacets().then(() => {
        if (code && code !== "(none)") srcMselCheck("src-msel-country", code);
        if (tag) srcMselCheck("src-msel-tag", tag);
        applySrcFilters();
      });
    }

    async function updateSource(id, body) {
      try { await api("/api/sources/" + id, {method: "PUT", body: JSON.stringify(body)});
        toast("Source updated."); }
      catch (e) { toast(_failMsg("Update failed: {error}", e), "err"); loadManagedSources(); }
    }

    async function deleteSource(id, name) {
      if (!confirm(`Delete source "${name}"? This also removes its stored articles.`)) return;
      try { await api("/api/sources/" + id, {method: "DELETE"});
        toast("Source deleted."); loadManagedSources(); loadSources(); loadDbStats(); }
      catch (e) { toast(_failMsg("Delete failed: {error}", e), "err"); }
    }

    async function importSources() {
      const f = $("imp-file").files[0];
      if (!f) { toast("Choose a CSV file first.", "err"); return; }
      $("imp-result").textContent = "Importing…";
      try {
        const fd = new FormData(); fd.append("file", f);
        const res = await fetch("/api/catalog/import", {method: "POST", body: fd});
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || res.statusText);
        const errs = (d.parse_errors || []).concat(d.errors || []);
        $("imp-result").innerHTML =
          `<span class="pill ok">imported</span> created ${d.created}, updated ${d.updated}, ` +
          `skipped ${d.skipped}.` +
          (errs.length ? ` <span class="muted">First issues: ${errs.slice(0,5).map(esc).join("; ")}</span>` : "");
        toast(`Import: +${d.created} new, ${d.updated} updated.`);
        loadManagedSources(); loadSources(); loadDbStats(); loadCoverage();
      } catch (e) { $("imp-result").textContent = ""; toast(_failMsg("Import failed: {error}", e), "err"); }
    }

    function tally(t) {
      return Object.entries(t).filter(([k,v]) => v > 0)
        .map(([k,v]) => `${esc(k)}: ${v}`).join(", ") || "nothing new";
    }

    async function ingestSource() {
      const id = $("ing-source").value;
      if (!id) { toast("No RSS source selected.", "err"); return; }
      $("ingest-result").textContent = "Fetching feed… (rate-limited, may take a moment)";
      try {
        const r = await api(`/api/sources/${id}/ingest`, {method: "POST"});
        $("ingest-result").textContent = "Feed result — " + tally(r.tally);
        toast("Ingest complete."); doSearch();
      } catch (e) { $("ingest-result").textContent = ""; toast(_failMsg("Ingest failed: {error}", e), "err"); }
    }

    async function ingestUrl() {
      const url = $("ing-url").value.trim();
      const id = $("ing-source").value;
      if (!url) { toast("Enter a URL.", "err"); return; }
      if (!id) { toast("Select a source to attribute it to.", "err"); return; }
      $("ingest-result").textContent = "Fetching…";
      try {
        const r = await api("/api/ingest", {method: "POST",
          body: JSON.stringify({source_id: Number(id), url})});
        $("ingest-result").innerHTML = `Result: <span class="pill ${r.result==='stored'?'ok':'warn'}">${esc(r.result)}</span>` +
          (r.detail ? ` — ${esc(r.detail)}` : "");
        if (r.result === "stored") { $("ing-url").value = ""; doSearch(); }
      } catch (e) { $("ingest-result").textContent = ""; toast(_failMsg("Ingest failed: {error}", e), "err"); }
    }

    // -- Batch ingest picker ------------------------------------------------ //
    const BI = { sources: [], selected: new Set() };

    async function loadBatchPicker() {
      try {
        BI.sources = await api("/api/sources/?limit=1000");
        BI.selected = new Set();
      } catch (e) { BI.sources = []; }
      renderBatchPicker();
    }

    function _biFiltered() {
      const q = ($("bi-search").value || "").trim().toLowerCase();
      const lang = ($("bi-lang").value || "").trim().toLowerCase();
      const country = ($("bi-country").value || "").trim().toLowerCase();
      const type = ($("bi-type").value || "").trim().toLowerCase();
      const en = $("bi-enabled").value;
      return BI.sources.filter(s => {
        if (q && !((s.name||"").toLowerCase().includes(q) || (s.domain||"").toLowerCase().includes(q))) return false;
        if (lang && (s.language||"").toLowerCase() !== lang) return false;
        if (country && (s.country||"").toLowerCase() !== country) return false;
        if (type && !(s.source_type||"").toLowerCase().includes(type)) return false;
        if (en === "1" && !s.enabled) return false;
        if (en === "0" && s.enabled) return false;
        return true;
      });
    }

    function renderBatchPicker() {
      const list = $("bi-list"); if (!list) return;
      const rows = _biFiltered();
      if (!rows.length) { list.innerHTML = '<div class="muted">No sources match these filters.</div>'; }
      else {
        list.innerHTML = rows.map(s => {
          const feed = !!s.rss_url;
          const meta = [s.language ? ooLangName(s.language, s.language) : null,
                        s.country ? ooRegionName(s.country, s.country) : null,
                        s.source_type].filter(Boolean).map(esc).join(" · ");
          return `<label class="bi-row${feed ? "" : " bi-nofeed"}" title="${feed ? esc(s.rss_url) : "no RSS feed — cannot batch-fetch"}">
            <input type="checkbox" ${feed ? "" : "disabled"} ${BI.selected.has(s.id) ? "checked" : ""}
              onchange="batchToggle(${s.id}, this.checked)">
            <span class="bi-name">${esc(s.name)}</span>
            <span class="bi-meta muted">${meta}${feed ? "" : " · no feed"}${s.enabled ? "" : " · disabled"}</span></label>`;
        }).join("");
      }
      const ingestable = rows.filter(s => s.rss_url).length;
      $("bi-count").textContent = `${BI.selected.size} selected · ${ingestable} feed-bearing of ${rows.length} shown`;
    }

    function batchToggle(id, on) { on ? BI.selected.add(id) : BI.selected.delete(id); renderBatchPicker(); }

    function batchSelectAll(on) {
      const rows = _biFiltered().filter(s => s.rss_url);
      if (on) rows.forEach(s => BI.selected.add(s.id));
      else rows.forEach(s => BI.selected.delete(s.id));
      renderBatchPicker();
    }

    async function ingestBatch(btn) {
      const ids = [...BI.selected];
      if (!ids.length) { toast("Select at least one source with a feed.", "err"); return; }
      btn.disabled = true;
      $("bi-status").textContent = `Fetching ${ids.length} feed(s)… (ethical & rate-limited; may take a while)`;
      $("bi-results").innerHTML = "";
      try {
        const r = await api("/api/sources/ingest-batch", {method: "POST", body: JSON.stringify({source_ids: ids})});
        $("bi-status").textContent = `Done: ${r.ingested}/${r.requested} fetched · ${tally(r.aggregate)}`;
        $("bi-results").innerHTML = `<table class="bi-res"><tr><th>Source</th><th>Result</th></tr>` +
          r.results.map(x => `<tr><td>${esc(x.source || ("#" + x.source_id))}</td>` +
            `<td>${x.status === "ok" ? tally(x.tally)
              : `<span class="pill warn">${esc(x.status)}</span>${x.detail ? " " + esc(x.detail) : ""}`}</td></tr>`).join("") +
          `</table>`;
        toast("Batch ingest complete."); doSearch();
      } catch (e) { $("bi-status").textContent = ""; toast(_failMsg("Batch ingest failed: {error}", e), "err"); }
      finally { btn.disabled = false; }
    }

    // -- Scheduler ---------------------------------------------------------- //
    function toggleCrawlFields() {
      $("crawl-fields").style.display = $("sch-mode").value === "crawl" ? "flex" : "none";
    }

    // Timezone-proof: the backend reports UTC; the browser knows the operator's
    // zone. Show a relative time ("in ~N min") and keep the exact local moment
    // in the tooltip (maintainer ruling 2026-06-10: no naked zone-less clock).
    function fmtRelative(iso) {
      const d = new Date(iso); if (isNaN(d)) return "";
      const mins = Math.round((d.getTime() - Date.now()) / 60000);
      if (mins <= 0) return "any moment now";
      if (mins < 60) return `in ~${mins} min`;
      const h = Math.floor(mins / 60), m = mins % 60;
      return `in ~${h} h${m ? ` ${m} min` : ""}`;
    }
    // Honest PAST relative time ("2 h ago") -- fmtRelative above is future-oriented
    // ("in ~X min") and reads wrong applied to a past timestamp.
    function fmtAgo(iso) {
      const t = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => v[k]));
      const d = new Date(iso); if (isNaN(d)) return "";
      const mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
      if (mins < 1) return t("just now", {});
      if (mins < 60) return t("{n} min ago", { n: mins });
      const h = Math.floor(mins / 60);
      if (h < 24) return t("{n} h ago", { n: h });
      return t("{n} d ago", { n: Math.floor(h / 24) });
    }
    function fmtLocal(iso) {
      return fmtDateTime(iso);   // app language + full month (not the browser locale)
    }
    function renderSchedStatus(st) {
      if (typeof st.online === "boolean") _paintNetwork(st.online);  // repaint NOW, not at the next poll
      setBackgroundActivity(st.active ? "Collecting…" : null);
      const pill = st.running
        ? (st.active ? '<span class="pill ok">running — scrape in progress</span>'
                     : '<span class="pill ok">running</span>')
        : '<span class="pill">stopped</span>';
      const next = st.next_run
        ? ` · <span title="${esc(fmtLocal(st.next_run))}">next ${esc(fmtRelative(st.next_run))}</span>`
        : "";
      $("sched-status").innerHTML = pill + next;
      const r = st.last_result;
      $("sched-last").innerHTML = st.last_error
        ? `<span class="pill err">last run failed</span> ${esc(st.last_error)}`
        : (r ? `Last run (${esc(r.mode)}): <strong>${r.articles_stored}</strong> stored` +
               (r.pages_fetched ? `, ${r.pages_fetched} pages fetched` : "") +
               `, ${r.sources_processed} source(s), ${esc(String(r.duration_s))}s ` +
               `<span class="muted">at ${esc(fmtLocal(r.finished_at || ""))}</span>`
             : '<span class="muted">No run yet.</span>');
    }

    // Collection-speed slider stops (kbps = kilobits/s, the consumer "download
    // speed" unit). The last stop is "Maximum" (governor mode = maximum).
    const SCHED_SPEED_STOPS = [100, 250, 500, 1000, 2500, 5000, "max"];
    function schedSpeedLabel() {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s => s);
      const sl = $("sch-speed"); if (!sl) return;
      const v = SCHED_SPEED_STOPS[Number(sl.value)];
      const el = $("sch-speed-val");
      if (el) el.textContent = (v === "max") ? T("Maximum") : (v + " kbps");
    }
    // Live "Now: X kbps" readout — polls the activity endpoint ONLY while the
    // Collect settings panel is visible (self-stops when it isn't).
    let _schedRateTimer = null;
    async function _pollSchedRate() {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s => s);
      const el = $("sch-speed-now"), view = $("set-collect");
      if (!el || !view || view.style.display === "none") { stopSchedRatePoll(); return; }
      let a; try { a = await api("/api/scheduler/activity"); } catch { return; }
      const r = a && a.download_rate_kbps, cp = a && a.collect_perf;
      if (r == null || !a.active) { el.textContent = ""; return; }
      let txt = T("Now") + ": " + r + " kbps";
      if (cp && cp.active_workers != null) txt += " · " + cp.active_workers + " " + T("workers");
      el.textContent = txt;
    }
    function startSchedRatePoll() {
      stopSchedRatePoll();
      _pollSchedRate();
      _schedRateTimer = setInterval(() => { if (!document.hidden) _pollSchedRate(); }, 3000);
    }
    function stopSchedRatePoll() {
      if (_schedRateTimer) { clearInterval(_schedRateTimer); _schedRateTimer = null; }
    }

    function applySchedConfig(c) {
      $("sch-interval").value = c.interval_minutes;
      $("sch-mode").value = c.mode;
      $("sch-depth").value = c.crawl_max_depth;
      $("sch-pages").value = c.crawl_max_pages;
      $("sch-autostart").checked = !!c.autostart;
      $("sch-langs").value = (c.select_languages || []).join(", ");
      $("sch-types").value = (c.select_source_types || []).join(", ");
      $("sch-tags").value = (c.select_tags || []).join(", ");
      if ($("sch-export-dir")) $("sch-export-dir").value = c.export_dir || "";
      // Collection speed: map the stored rate mode/target onto the slider stops.
      if ($("sch-speed")) {
        let idx = 2; // 500 kbps default
        if (c.collect_rate_mode === "maximum") {
          idx = SCHED_SPEED_STOPS.length - 1;
        } else {
          const t = Number(c.collect_target_kbps) || 500;
          idx = SCHED_SPEED_STOPS.findIndex(v => v !== "max" && v >= t);
          if (idx < 0) idx = SCHED_SPEED_STOPS.length - 2;  // largest numeric stop
        }
        $("sch-speed").value = idx;
        schedSpeedLabel();
      }
      toggleCrawlFields();
    }

    const _csv = id => $(id).value.split(",").map(x => x.trim()).filter(Boolean);

    // -- Top-bar collection-speed knob (maintainer ruling 2026-07-23) ------- //
    // One click toggles the bandwidth governor between "maximum" (ramp to the
    // worker ceiling; contention back-off + per-host politeness untouched) and
    // the considerate 500 KiB/s "target". PUT /api/scheduler/config is a
    // loopback settings write with no egress side effect (verified S4.7), so
    // no consent popup; the governor reads the mode at the next pass.
    let _rateMode = null;
    function _paintRateMode(mode) {
      const btn = $("rate-toggle");
      if (!btn) return;
      _rateMode = mode;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const max = mode === "maximum";
      btn.classList.toggle("rate-max", max);
      const needle = document.getElementById("rate-needle");
      if (needle) needle.setAttribute("transform", max ? "rotate(48 12 15.5)" : "rotate(-48 12 15.5)");
      btn.title = max
        ? t9("Collection speed: Maximum — uses your connection fully (politeness per host unchanged). Click for the considerate 500 KiB/s target.")
        : t9("Collection speed: 500 KiB/s target — deliberately gentle. Click for Maximum (full speed).");
      btn.setAttribute("aria-pressed", max ? "true" : "false");
    }
    async function loadRateMode() {
      try {
        const c = await api("/api/scheduler/config");
        _paintRateMode(c.collect_rate_mode || "maximum");
      } catch (_e) { /* chrome stays at the default paint; Settings still works */ }
    }
    async function toggleRateMode() {
      const next = _rateMode === "maximum" ? "target" : "maximum";
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const c = await api("/api/scheduler/config",
          {method: "PUT", body: JSON.stringify({collect_rate_mode: next})});
        _paintRateMode((c && c.collect_rate_mode) || next);
        // Keep the Settings → Collect speed slider in sync if that panel is live.
        try { if ($("sch-speed") && c) applySchedConfig(c); } catch (_e) {}
        toast(next === "maximum"
          ? t9("Collection speed set to Maximum — applies from the next pass.")
          : t9("Collection speed set to the 500 KiB/s target — applies from the next pass."));
      } catch (e) { toast("Could not change the collection speed: " + e.message, "err"); }
    }

    async function loadScheduler() {
      try { const s = await api("/api/scheduler/status"); renderSchedStatus(s); _paintCollectToggle(!!(s && s.running)); }
      catch (e) { $("sched-status").textContent = "Scheduler status unavailable: " + e.message; }
      try { applySchedConfig(await api("/api/scheduler/config")); }
      catch (e) { /* config panel stays at defaults */ }
      previewTargets();
      loadBatchPicker();
      startSchedRatePoll();
    }

    // The single primary Collection control: on/off. The schedule / mode / manual /
    // batch knobs are demoted to the "Advanced (legacy)" sections — collection is
    // continuous & automatic; this just switches it on or off.
    function _paintCollectToggle(running) {
      const btn = $("collect-toggle");
      if (!btn) return;
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      btn.textContent = running ? t9("Collection is ON — click to turn off")
                                : t9("Collection is OFF — click to turn on");
      btn.setAttribute("aria-pressed", running ? "true" : "false");
    }
    async function collectToggle() {
      let running = false;
      try { running = !!(await api("/api/scheduler/status")).running; } catch (e) {}
      if (running) { await schedulerStop(); } else { await schedulerStart(); }
      loadScheduler();
    }

    async function previewTargets() {
      const el = $("sched-targets");
      try {
        const t = await api("/api/scheduler/targets");
        if (!t.applies) { el.innerHTML = `<span class="muted">Selection applies to RSS / crawl modes; current mode is <strong>${esc(t.mode)}</strong>.</span>`; return; }
        const langs = Object.entries(t.by_language).map(([k,v])=>`${esc(k)}:${v}`).join("  ");
        const types = Object.entries(t.by_source_type).map(([k,v])=>`${esc(k)}:${v}`).join("  ");
        el.innerHTML = `<span class="pill ${t.matched?'ok':'warn'}">${t.matched} sources targeted</span> ` +
          `of ${t.total_enabled} enabled · this run will process up to <strong>${t.will_process_this_run}</strong>` +
          `<div class="muted" style="font-size:12px;margin-top:4px">by language: ${langs||'—'}</div>` +
          `<div class="muted" style="font-size:12px">by type: ${types||'—'}</div>`;
      } catch (e) { el.textContent = "Could not preview targets: " + e.message; }
    }

    async function schedulerStart() {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!await ensureOnline(t9("Start continuous background collection"))) return;
      try { renderSchedStatus(await api("/api/scheduler/start", {method: "POST"}));
        toast("Scheduler started."); } catch (e) { toast(_failMsg("Start failed: {error}", e), "err"); }
    }
    async function schedulerStop() {
      try { renderSchedStatus(await api("/api/scheduler/stop", {method: "POST"}));
        toast("Scheduler stopped."); } catch (e) { toast(_failMsg("Stop failed: {error}", e), "err"); }
    }
    async function schedulerRunNow() {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!await ensureOnline(t9("Start a collection pass (RSS, crawl, markets, watched Wikipedia pages)"))) return;
      if (!await arbitrate(t9("Start a collection pass (RSS, crawl, markets, watched Wikipedia pages)"))) return;
      try {
        const st = await api("/api/scheduler/run-now", {method: "POST"});
        renderSchedStatus(st);
        toast(st.started ? "Scrape started — results will appear shortly." : "A run is already in progress.");
        // Poll the status a few times so the last-run summary updates without a manual refresh.
        let tries = 0;
        const poll = setInterval(async () => {
          try { const s = await api("/api/scheduler/status"); renderSchedStatus(s);
            if ((!s.active && s.last_run) || ++tries > 20) { clearInterval(poll); doSearch(); loadDbStats(); } }
          catch { clearInterval(poll); }
        }, 1500);
      } catch (e) { toast(_failMsg("Run now failed: {error}", e), "err"); }
    }

    async function saveScheduler() {
      const body = {
        interval_minutes: Number($("sch-interval").value),
        mode: $("sch-mode").value,
        crawl_max_depth: Number($("sch-depth").value),
        crawl_max_pages: Number($("sch-pages").value),
        autostart: $("sch-autostart").checked,
        select_languages: _csv("sch-langs"),
        select_source_types: _csv("sch-types"),
        select_tags: _csv("sch-tags"),
        export_dir: $("sch-export-dir") ? $("sch-export-dir").value.trim() : "",
      };
      // Collection speed: the slider's last stop is "Maximum" (governor mode),
      // every other stop is a download-rate target in kbps.
      if ($("sch-speed")) {
        const sv = SCHED_SPEED_STOPS[Number($("sch-speed").value)];
        if (sv === "max") { body.collect_rate_mode = "maximum"; }
        else { body.collect_rate_mode = "target"; body.collect_target_kbps = sv; }
      }
      try { applySchedConfig(await api("/api/scheduler/config", {method: "PUT", body: JSON.stringify(body)}));
        toast("Schedule saved."); previewTargets(); } catch (e) { toast(_failMsg("Save failed: {error}", e), "err"); }
    }

    // -- Markets (analysis-first dashboard) --------------------------------- //
