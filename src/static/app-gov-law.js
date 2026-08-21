/* app-gov-law.js — Governments and World Law

   The Governments tab (indicators, per-country views, the choropleth) and the World
   Law tracker (documents, revisions, diffs, AI change summaries).

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
    let _govSubtabs = null, _govInds = null, _govMapData = null, _govMapInit = false, _govCountriesInit = false;

    function _govCompact(v) {
      const a = Math.abs(v);
      if (a >= 1e12) return (v / 1e12).toFixed(a >= 1e13 ? 0 : 1) + "T";
      if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + "B";
      if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
      if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "k";
      return fmtNum(v, 1);
    }
    // Every unit in the catalog gets a branch, and an UNKNOWN unit is appended
    // rather than dropped. The old fallthrough was `fmtNum(v, 2)`, which silently
    // discarded the unit for six of the catalog's eleven: GDP-PPP rendered as
    // "99 594 884 137 256.80" and mobile subscriptions as a bare "141.60", which
    // reads as a broken percentage rather than as subscriptions per 100 people
    // (field feedback 2026-08-07, item 8). A new unit added to the catalog now
    // degrades to "value unit" instead of to a naked number, and
    // test_governments_units.py fails if it has no explicit branch here.
    function _govFmt(v, unit) {
      // `t` is NOT a global in this file; bind it or every call throws at runtime
      // (test_no_app_function_calls_i18n_t_without_binding_it exists because that
      // has shipped before). Unkeyed units fall back to their English form.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (v == null || !isFinite(v)) return "—";
      if (unit === "%") return fmtNum(v, 1) + "%";
      if (unit === "years" || unit === "index") return fmtNum(v, 1);
      if (unit === "USD") return "$" + _govCompact(v);
      // International dollars are PPP-converted and are NOT US dollars; giving them
      // a "$" would silently equate two different units.
      if (unit === "intl$") return "Int$" + _govCompact(v);
      if (unit === "people") return _govCompact(v);
      // These use fmtNum's OWN magnitude-scaled precision rather than a fixed number
      // of decimals, per the app-wide units principle (sensible significant digits
      // scaled to magnitude). A fixed 1 decimal would render 141.6 correctly and turn
      // 3.78 physicians per 1,000 into 3.8, losing a real digit on the small end.
      if (unit === "per 100" || unit === "per 1,000" || unit === "per 100,000")
        return fmtNum(v) + " " + t(unit);
      if (unit === "births/woman") return fmtNum(v) + " " + t("births/woman");
      if (unit === "t/capita") return fmtNum(v) + " " + t("t/capita");
      return unit ? fmtNum(v, 2) + " " + t(unit) : fmtNum(v, 2);
    }

    async function loadGovIndicators() {
      if (_govInds) return _govInds;
      try { _govInds = (await api("/api/governments/indicators")).indicators || []; }
      catch (e) { _govInds = []; }
      return _govInds;
    }

    // Entry point (TAB_LOADERS.law): wire the subtabs once, then show the default.
    async function loadGovernments() {
      const nav = $("gov-subtabs");
      // {initial:"countries"} fires showGovView("countries") on creation; on a re-open
      // select() re-paints the nav highlight AND fires the loader (stays in sync).
      if (nav && !_govSubtabs) _govSubtabs = ooSubtabs(nav, showGovView, {initial: "countries"});
      else if (_govSubtabs) _govSubtabs.select("countries");
    }
    function showGovView(cat) {
      ["countries", "compare", "groups", "map", "law", "statistics"].forEach(v =>
        { const el = $("gov-" + v); if (el) el.style.display = (v === cat) ? "" : "none"; });
      if (cat === "countries") loadGovCountries();
      // Ruling 4: two countries side by side. Ruling 32/43/44/45/47: groups, in two
      // lenses — the producer's own published aggregates, and figures computed here.
      else if (cat === "compare") loadGovCompare();
      else if (cat === "groups") loadGovGroupsTab();
      else if (cat === "map") loadGovMap();
      else if (cat === "law") loadLaw();
      // Official FIGURES (2026-07-31): vintages, revision anomalies, triangulation and the
      // tracked auto-refresh list are DATA about governments, so they live here rather than
      // in Settings (invariant #8). The producer directory stayed in Settings → Advanced.
      else if (cat === "statistics") { loadStatFigures(); loadStatSubs(); }
    }

    // ---- Countries subtab ---- //
    async function loadGovCountries() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      loadLawPointer();
      if (_govCountriesInit) return;
      _govCountriesInit = true;
      const sel = $("gov-country"); if (!sel) return;
      await loadGovIndicators();
      // Derive the available countries from a populous indicator's coverage.
      let rows = [];
      try { rows = (await api("/api/governments/map?indicator=SP.POP.TOTL")).by_country || []; }
      catch (e) { rows = []; }
      if (!rows.length) {
        // try GDP as a fallback before declaring the store empty
        try { rows = (await api("/api/governments/map?indicator=NY.GDP.MKTP.CD")).by_country || []; }
        catch (e) { rows = []; }
      }
      const codes = [...new Set(rows.map(r => r.country))].sort(
        (a, b) => ooRegionName(a, a).localeCompare(ooRegionName(b, b)));
      if (!codes.length) {
        sel.innerHTML = "";
        $("gov-country-data").innerHTML =
          `<div class="muted">${esc(t("Country data loads automatically in the background when online — or use “Load standard country data” to fetch it now."))}</div>`;
        return;
      }
      sel.innerHTML = codes.map(c => `<option value="${esc(c)}">${esc(ooRegionName(c, c))}</option>`).join("");
      loadGovCountry(codes[0]);
    }
    async function loadGovCountry(iso) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("gov-country-data"); if (!host || !iso) return;
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      let d; try { d = await api("/api/governments/country/" + encodeURIComponent(iso)); }
      catch (e) { host.innerHTML = `<div class="muted">${esc(t("Could not load this country."))}</div>`; return; }
      host.innerHTML = _govIndicatorGrid(d)
        + `<div class="card-caveat" style="margin-top:10px">${esc(d.caveat || "")}</div>`;
    }

    // ONE indicator card, reused by the Countries, Compare and Aggregates surfaces.
    // Hoisted out of loadGovCountry when Compare and the aggregate view arrived: three
    // copies of a card that renders a producer's figure would drift, and the half that
    // drifts is always the caveat rather than the number.
    function _govIndCard(ind) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const latest = ind.latest;
      const val = latest ? _govFmt(latest.value, ind.unit) : "—";
      const yr = latest ? ` <span class="muted">(${esc(latest.year)})</span>` : "";
      // Gate the chart on the points that will actually be PLOTTED, not on the raw
      // series: a series of several entries with one non-null value used to pass
      // this check and then hand dashChartSvg a single point, which is how a
      // one-point card ended up drawing an axis at all.
      const pts = (ind.series || []).filter(p => p.value != null);
      const spark = pts.length > 1
        ? dashChartSvg(pts.map(p => ({observed_on: p.year + "-01-01", price: p.value})),
                       ind.unit || "", {nUnit: t("years")})
        : "";
      // A definition where the number reads as an error and is not one. Rides the
      // #oo-tip hover convention (invariant #17), which marks the element for free.
      const note = ind.note ? ` title="${esc(ind.note)}"` : "";
      // The display bound, stated only where it BIT. `series_stored` is what the store
      // holds; the series is what this response carried. Silence here is what makes a
      // 30-year sparkline indistinguishable from a producer that started reporting in
      // 1996, so the shortfall is named — and only when there is one.
      const stored = ind.series_stored;
      const cut = (typeof stored === "number" && stored > (ind.series || []).length)
        ? `<div class="muted" style="font-size:10px;margin-top:3px">${esc(_govTf(
            "Years shown: {shown} of {stored} held",
            {shown: (ind.series || []).length, stored: stored}))}</div>`
        : "";
      return `<div class="gov-ind">
        <div class="gov-ind-label"${note}>${esc(ind.label)}</div>
        <div class="gov-ind-val">${esc(val)}${yr}</div>
        <div class="gov-ind-spark">${spark}</div>${cut}</div>`;
    }

    // Category-grouped grid over an /country|/aggregate payload's `indicators`.
    function _govIndicatorGrid(d) {
      const cats = {};
      (d.indicators || []).forEach(i => { (cats[i.category] = cats[i.category] || []).push(i); });
      return Object.keys(cats).map(c =>
        `<h3 style="font-size:13px;margin:14px 0 6px;text-transform:capitalize">${esc(c)}</h3>
         <div class="gov-ind-grid">${cats[c].map(_govIndCard).join("")}</div>`).join("");
    }

    // Guarded composite lookup: the TEMPLATE is the key and the numbers are data, so
    // the frame translates ×12 and no figure ever passes through a translation table.
    function _govTf(str, vars) {
      return (window.OOI18N && OOI18N.tf) ? OOI18N.tf(str, vars)
        : String(str).replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m);
    }

    // The country codes this store actually holds figures for, alpha-2, sorted by the
    // reader's own locale name. Derived from the map endpoint, which already drops
    // aggregates (they have no alpha-2), so a picker built from it cannot offer XD as a
    // nation — the field defect that started ruling 1(b).
    let _govCountryCodes = null;
    async function _govCodes() {
      if (_govCountryCodes) return _govCountryCodes;
      let rows = [];
      for (const code of ["SP.POP.TOTL", "NY.GDP.MKTP.CD"]) {
        try { rows = (await api("/api/governments/map?indicator=" + code)).by_country || []; }
        catch (e) { rows = []; }
        if (rows.length) break;
      }
      _govCountryCodes = [...new Set(rows.map(r => r.country))]
        .sort((a, b) => ooRegionName(a, a).localeCompare(ooRegionName(b, b)));
      return _govCountryCodes;
    }
    function _govCountryOptions(codes, selected) {
      return codes.map(c =>
        `<option value="${esc(c)}"${c === selected ? " selected" : ""}>${esc(ooRegionName(c, c))}</option>`
      ).join("");
    }
    function _govEmptyStore(t) {
      return `<div class="muted">${esc(t("Country data loads automatically in the background when online — or use “Load standard country data” to fetch it now."))}</div>`;
    }

    // A long member list is INFORMATION OVERFLOW, not a caveat to hide. The
    // non-negotiable's own answer is LAYERING: the sentence and the counts stay
    // visible, and the full roster rides the translated #oo-tip hover (invariant #17).
    // Ruling 44 is satisfied regardless — the missing members travel in the PAYLOAD,
    // which is what an export quotes; this only decides how many fit on one screen.
    function _govNames(codes, head) {
      const all = (codes || []).map(c => String(c).toUpperCase());
      head = head || 8;
      return {
        full: all.join(", "),
        short: all.length > head
          ? all.slice(0, head).join(", ") + " " + _govTf("… and {n} more", {n: all.length - head})
          : all.join(", "),
      };
    }

    // ---- Compare subtab (ruling 4) ---- //
    // Two countries, every curated indicator, side by side. DISPLAY only: nothing here
    // is derived, so the only way to get it wrong is to render a gap as a value.
    let _govCmpInit = false;
    async function loadGovCompare() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_govCmpInit) return;
      _govCmpInit = true;
      const a = $("gov-cmp-a"), b = $("gov-cmp-b"); if (!a || !b) return;
      const codes = await _govCodes();
      if (!codes.length) { const h = $("gov-cmp-body"); if (h) h.innerHTML = _govEmptyStore(t); return; }
      a.innerHTML = _govCountryOptions(codes, codes[0]);
      b.innerHTML = _govCountryOptions(codes, codes[1] || codes[0]);
      renderGovCompare();
    }
    async function renderGovCompare() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("gov-cmp-body"); if (!host) return;
      const a = $("gov-cmp-a") && $("gov-cmp-a").value, b = $("gov-cmp-b") && $("gov-cmp-b").value;
      if (!a || !b) return;
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      let da, dbb;
      try {
        [da, dbb] = await Promise.all([
          api("/api/governments/country/" + encodeURIComponent(a)),
          api("/api/governments/country/" + encodeURIComponent(b)),
        ]);
      } catch (e) { host.innerHTML = `<div class="muted">${esc(t("Could not load these countries."))}</div>`; return; }
      const byId = (d) => { const m = {}; (d.indicators || []).forEach(i => { m[i.id] = i; }); return m; };
      const ma = byId(da), mb = byId(dbb);
      const nameA = ooRegionName(da.iso2 || a, a), nameB = ooRegionName(dbb.iso2 || b, b);
      // One row per indicator, grouped by category — the same vocabulary as the
      // Countries grid, so a reader moving between the two surfaces reads one layout.
      const cats = {};
      (da.indicators || []).forEach(i => { (cats[i.category] = cats[i.category] || []).push(i); });
      const cell = (ind) => {
        if (!ind || !ind.latest) return `<td class="gov-cmp-gap">—</td>`;
        return `<td><span class="gov-cmp-v">${esc(_govFmt(ind.latest.value, ind.unit))}</span>`
          + ` <span class="muted">(${esc(ind.latest.year)})</span></td>`;
      };
      const rows = Object.keys(cats).map(c =>
        `<tr class="gov-cmp-cat"><th colspan="3">${esc(c)}</th></tr>`
        + cats[c].map(ind => {
            const note = ind.note ? ` title="${esc(ind.note)}"` : "";
            const ia = ma[ind.id], ib = mb[ind.id];
            // A row where NEITHER side has a figure is still shown: an indicator both
            // countries lack is a real, readable fact about coverage, and dropping it
            // would quietly shorten the comparison to whatever happens to be held.
            return `<tr><th scope="row"${note}>${esc(ind.label)}</th>${cell(ia)}${cell(ib)}</tr>`;
          }).join("")
      ).join("");
      host.innerHTML =
        `<div style="overflow-x:auto"><table class="gov-cmp">
           <thead><tr><th scope="col">${esc(t("Indicator"))}</th>
             <th scope="col">${esc(nameA)}</th><th scope="col">${esc(nameB)}</th></tr></thead>
           <tbody>${rows}</tbody></table></div>`
        + `<div class="card-caveat" style="margin-top:10px">${esc(t("Each side carries its own most recent year: the two producers do not publish on the same calendar, so a difference between two years is not a difference between two countries. A dash is a published gap, never a zero."))}</div>`
        + `<div class="card-caveat">${esc(da.caveat || "")}</div>`;
    }

    // ---- Groups subtab: two lenses (rulings 32, 43, 44, 45, 47) ---- //
    let _govLens = "published", _govAggs = null, _govAggAll = false, _govGroupsInit = false;

    function showGovLens(lens) {
      _govLens = lens;
      const nav = $("gov-lens");
      if (nav) Array.prototype.forEach.call(nav.querySelectorAll("[data-lens]"), (b) =>
        b.setAttribute("aria-pressed", b.dataset.lens === lens ? "true" : "false"));
      const pub = $("gov-lens-published"), com = $("gov-lens-computed");
      if (pub) pub.style.display = lens === "published" ? "" : "none";
      if (com) com.style.display = lens === "computed" ? "" : "none";
      if (lens === "published") loadGovAggregates(); else loadGovGroups();
    }

    async function loadGovGroupsTab() {
      if (!_govGroupsInit) { _govGroupsInit = true; showGovLens(_govLens); }
      else showGovLens(_govLens);
    }

    // --- lens 1: the producer's OWN aggregates (ruling 32) --- //
    async function loadGovAggregates() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const sel = $("gov-agg-pick"); if (!sel) return;
      if (!_govAggs) {
        try { _govAggs = await api("/api/governments/aggregates"); }
        catch (e) { _govAggs = null; }
        const note = $("gov-agg-note");
        if (note) note.textContent = (_govAggs && _govAggs.caveat) || "";
      }
      if (!_govAggs) { const h = $("gov-agg-body"); if (h) h.innerHTML = _govEmptyStore(t); return; }
      _govPaintAggregateOptions();
      if (sel.value) loadGovAggregate(sel.value);
    }
    function _govPaintAggregateOptions() {
      const sel = $("gov-agg-pick"); if (!sel || !_govAggs) return;
      const prev = sel.value;
      const all = _govAggs.aggregates || [];
      // The shortlist is the DEFAULT view, not a ranking — the full set ships in the
      // same payload so "Show all" cannot fail on its own.
      const rows = _govAggAll ? all : all.filter(a => a.shortlist);
      const held = rows.filter(a => a.has_data), empty = rows.filter(a => !a.has_data);
      const opt = (a) => `<option value="${esc(a.code)}">${esc(a.name)}</option>`;
      // An aggregate this install holds nothing for is OFFERED but grouped apart and
      // labelled: "the World Bank publishes no figure" and "this install has not fetched
      // it" are different facts, and an empty row cannot tell them apart on its own.
      sel.innerHTML = held.map(opt).join("")
        + (empty.length
          ? `<optgroup label="${esc(_govT("not fetched here yet"))}">${empty.map(opt).join("")}</optgroup>`
          : "");
      if (prev && sel.querySelector(`option[value="${CSS.escape(prev)}"]`)) sel.value = prev;
      else if (!sel.value && sel.options.length) sel.value = sel.options[0].value;
    }
    function _govT(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }
    function govToggleAllAggregates(btn) {
      _govAggAll = !_govAggAll;
      if (btn) {
        btn.setAttribute("aria-pressed", _govAggAll ? "true" : "false");
        btn.textContent = _govAggAll ? _govT("Show the shortlist") : _govT("Show all");
      }
      _govPaintAggregateOptions();
      const sel = $("gov-agg-pick");
      if (sel && sel.value) loadGovAggregate(sel.value);
    }
    async function loadGovAggregate(code) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("gov-agg-body"); if (!host || !code) return;
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      let d;
      try { d = await api("/api/governments/aggregate/" + encodeURIComponent(code)); }
      catch (e) { host.innerHTML = `<div class="muted">${esc(t("Could not load this aggregate."))}</div>`; return; }
      const any = (d.indicators || []).some(i => i.latest);
      host.innerHTML =
        `<div class="gov-agg-head"><strong>${esc(d.name || d.code)}</strong>`
        + ` <span class="pill">${esc(t("published aggregate"))}</span>`
        + ` <span class="muted">${esc(_govTf("registry as of {as_of}", {as_of: d.as_of || "—"}))}</span></div>`
        + (any
            ? _govIndicatorGrid(d)
            : `<div class="muted" style="margin-top:10px">${esc(t("No figure for this aggregate is held here yet — it fills in as the background load reaches it."))}</div>`)
        + `<div class="card-caveat" style="margin-top:10px">${esc(d.caveat || "")}</div>`;
    }

    // --- lens 2: computed from members (rulings 43/44/45/47) --- //
    let _govGroups = null;
    async function loadGovGroups() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const gsel = $("gov-grp-pick"), isel = $("gov-grp-ind");
      if (!gsel || !isel) return;
      if (!_govGroups) {
        try { _govGroups = await api("/api/governments/groups"); }
        catch (e) { _govGroups = null; }
        const note = $("gov-grp-note");
        if (note) note.textContent = (_govGroups && _govGroups.caveat) || "";
      }
      if (!_govGroups) { const h = $("gov-grp-body"); if (h) h.innerHTML = _govEmptyStore(t); return; }
      if (!gsel.options.length) {
        const gs = _govGroups.groups || [];
        const kind = (k, label) => {
          const rows = gs.filter(g => g.kind === k);
          if (!rows.length) return "";
          return `<optgroup label="${esc(label)}">` + rows.map(g =>
            // An UNPOPULATED group is offered, not hidden: "BRICS exists and its
            // membership dates are not sourced yet" is a more useful answer than
            // "no such group", and the refusal it produces says exactly that.
            `<option value="${esc(g.key)}">${esc(g.label)}${g.populated ? "" : " — " + t("membership not held")}</option>`
          ).join("") + `</optgroup>`;
        };
        gsel.innerHTML = kind("continent", t("Continents (ours)"))
          + kind("wb_region", t("World Bank regions (the producer's member lists)"))
          + kind("bloc", t("Political blocs"));
      }
      if (!isel.options.length) {
        await loadGovIndicators();
        isel.innerHTML = (_govInds || []).map(i =>
          `<option value="${esc(i.id)}">${esc(i.label)}</option>`).join("");
      }
      renderGovGroup();
    }

    async function renderGovGroup(allowIncomplete) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("gov-grp-body"); if (!host) return;
      const g = $("gov-grp-pick") && $("gov-grp-pick").value;
      const i = $("gov-grp-ind") && $("gov-grp-ind").value;
      const yr = ($("gov-grp-year") && $("gov-grp-year").value || "").trim();
      if (!g || !i) return;
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      let d;
      const q = "/api/governments/group-aggregate?group=" + encodeURIComponent(g)
        + "&indicator=" + encodeURIComponent(i)
        + (yr ? "&year=" + encodeURIComponent(yr) : "")
        + (allowIncomplete ? "&allow_incomplete=true" : "");
      try { d = await api(q); }
      catch (e) { host.innerHTML = `<div class="muted">${esc(t("Could not compute this group."))}</div>`; return; }
      host.innerHTML = _govGroupHtml(d, allowIncomplete);
    }

    // Pure renderer over a /group-aggregate payload, so it is testable without a DOM.
    function _govGroupHtml(d, allowIncomplete) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const roster = d.group || {}, agg = d.aggregate;
      // Ruling 45: EVERY group surface states the vintage it resolved against and the
      // roster it used. A figure computed with today's membership over a 1995 series is
      // wrong in a way no reader can detect, so the roster is never implicit.
      const vintage = `<div class="gov-grp-vintage">`
        + esc(_govTf("Members: {n} · membership as of {year} · registry curated {as_of}", {
            n: (roster.members || []).length,
            year: roster.resolved_year || t("today"),
            as_of: roster.as_of || "—",
          }))
        + (roster.suspended && roster.suspended.length
            ? ` <span class="warn">` + esc(_govTf("Suspended ({n}): {who}", {
                n: roster.suspended.length, who: roster.suspended.join(", ").toUpperCase()})) + `</span>`
            : "")
        + (roster.undated_members && roster.undated_members.length
            ? ` <span class="warn">` + esc(_govTf("Carried without a sourced accession date: {n}", {
                n: roster.undated_members.length})) + `</span>`
            : "")
        + `</div>`;

      if (!agg) {
        // A known group with no sourced roster. Named, with the reason, never hidden.
        return vintage + `<div class="card-caveat">${esc(d.reason || roster.reason || "")}</div>`;
      }

      const cov = agg.coverage || {}, spread = agg.spread || {};
      const strategies = agg.strategies || {};
      // Presentation order is the engine's own STRATEGIES order — never a ranking. The
      // default is a starting VIEW and is marked as that word, not as a winner.
      const order = ["sum", "mean", "median", "population_weighted", "gdp_weighted", "labour_force_weighted"];
      const cards = order.filter(k => strategies[k]).map(k => {
        const r = strategies[k];
        const isDefault = agg.default_strategy === k;
        if (r.refused) {
          return `<div class="gov-strat gov-strat-refused">
            <div class="gov-strat-label">${esc(r.label || k)}</div>
            <div class="gov-strat-why">${esc(r.refused)}</div></div>`;
        }
        return `<div class="gov-strat${isDefault ? " gov-strat-default" : ""}">
          <div class="gov-strat-label">${esc(r.label || k)}${isDefault
            ? ` <span class="pill" title="${esc(t("A starting view, not a winner: the strategies answer different questions and are never ranked or blended."))}">${esc(t("opens here"))}</span>` : ""}</div>
          <div class="gov-strat-val">${esc(_govFmt(r.value, agg.unit))}</div>
          <div class="gov-strat-basis">${esc(r.basis === "exact" ? t("exact") : t("approximate"))}</div>
          <div class="gov-strat-why">${esc(r.method || "")}</div></div>`;
      }).join("");

      // Ruling 47's corollary: the SPREAD rides beside every central figure, because a
      // headline hiding a ten-fold range is technically true and practically misleading.
      const spreadLine = (spread.n
        ? `<div class="gov-grp-spread">` + esc(_govTf(
            "Range across reporting members ({n}): {min} ({minArea}) to {max} ({maxArea})", {
              n: spread.n,
              min: _govFmt(spread.min, agg.unit), minArea: (spread.min_area || "").toUpperCase(),
              max: _govFmt(spread.max, agg.unit), maxArea: (spread.max_area || "").toUpperCase(),
            })) + `</div>`
        : "");

      const missing = cov.missing || [];
      const coverageLine = `<div class="gov-grp-cov">` + esc(_govTf(
        "Members reporting this indicator: {reported} of {members}", {
          reported: cov.reported || 0, members: cov.members || 0})) + `</div>`;
      // Refuse-by-default: the override is an explicit click and the missing members
      // travel in the PAYLOAD, so an export cannot read a partial figure as complete.
      const override = (!cov.complete && missing.length && !allowIncomplete)
        ? `<div class="gov-grp-override">
             <button type="button" class="secondary tiny" onclick="renderGovGroup(true)">${esc(t("Compute over the members that did report"))}</button>
             <span class="muted" title="${esc(_govNames(missing).full)}">${esc(_govTf("missing: {who}", {who: _govNames(missing).short}))}</span>
           </div>`
        : "";
      const partial = (!cov.complete && allowIncomplete)
        ? `<div class="card-caveat" title="${esc(_govNames(missing).full)}">` + esc(_govTf(
            "PARTIAL — members computed: {reported} of {members}. Missing: {who}. This is not the group's figure and nothing downstream can tell the difference from one; the missing members travel with the exported result.",
            {reported: cov.reported || 0, members: cov.members || 0,
             who: _govNames(missing).short})) + `</div>`
        : "";

      const period = d.aggregate && d.aggregate.period;
      const head = `<div class="gov-grp-head"><strong>${esc(roster.label || roster.group || "")}</strong>`
        + ` — ${esc(agg.label || agg.indicator || "")}`
        + (period ? ` <span class="muted">(${esc(period)})</span>` : "")
        + ` <span class="pill">${esc(t("computed here"))}</span></div>`;

      return head + vintage + coverageLine + spreadLine + override + partial
        + `<div class="gov-strat-grid">${cards}</div>`
        + (roster.notes ? `<div class="card-caveat">${esc(roster.notes)}</div>` : "")
        + `<div class="card-caveat">${esc(agg.caveat || "")}</div>`
        + `<div class="card-caveat">${esc(d.caveat || "")}</div>`;
    }

    // ---- Map subtab ---- //
    async function loadGovMap() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const sel = $("gov-map-ind"); if (!sel) return;
      if (!_govMapInit) {
        _govMapInit = true;
        await loadGovIndicators();
        sel.innerHTML = (_govInds || []).map(i => `<option value="${esc(i.id)}">${esc(i.label)}</option>`).join("");
      }
      const indicator = sel.value || (_govInds && _govInds[0] && _govInds[0].id);
      if (!indicator) return;
      const host = $("gov-map-host");
      if (host) host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try { _govMapData = await api("/api/governments/map?indicator=" + encodeURIComponent(indicator)); }
      catch (e) { _govMapData = null; }
      // year selector from the data's years (latest first); "" = latest available per country
      const ysel = $("gov-map-year");
      if (ysel && _govMapData) {
        const years = (_govMapData.years || []).slice().reverse();
        ysel.innerHTML = `<option value="">${esc(t("Latest available"))}</option>`
          + years.map(y => `<option value="${esc(y)}">${esc(y)}</option>`).join("");
      }
      renderGovMap();
    }
    async function renderGovMap() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("gov-map-host"); if (!host) return;
      const sel = $("gov-map-ind"), ysel = $("gov-map-year");
      const indicator = sel && sel.value, year = ysel && ysel.value;
      let data = _govMapData;
      // a specific year needs its own fetch (the cached payload is "latest per country")
      if (year && (!data || data.year !== year)) {
        try { data = await api("/api/governments/map?indicator=" + encodeURIComponent(indicator) + "&year=" + encodeURIComponent(year)); }
        catch (e) { data = null; }
      }
      if (!data || !(data.by_country || []).length) {
        host.innerHTML = `<div class="muted">${esc(t("Country data loads automatically in the background when online — the map fills in once it lands."))}</div>`;
        $("gov-map-caveat").textContent = "";
        return;
      }
      const meta = data.indicator || {};
      const values = {}, names = {};
      (data.by_country || []).forEach(r => {
        if (r.value != null) values[r.country] = r.value;
        names[r.country] = ooRegionName(r.country, r.country);
      });
      await ooMap(host, {
        values, names,
        scale: "sequential", label: meta.label || "", unit: meta.unit || "",
        valueLabel: (iso, v) => `${ooRegionName(iso, iso)}: ${_govFmt(v, meta.unit)}`,
        caveat: data.caveat || "",
        onCountry: (iso) => {   // click a country -> its detail in the Countries subtab
          if (_govSubtabs) _govSubtabs.select("countries");
          const cs = $("gov-country");
          if (cs) { cs.value = iso; if (cs.value === iso) loadGovCountry(iso); }
        },
      });
      $("gov-map-caveat").textContent = (meta.label ? meta.label + " · " : "")
        + (data.year ? data.year + " · " : t("Latest available") + " · ") + (data.caveat || "");
    }

    async function govLoadStandard(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ensureOnline === "function" && !(await ensureOnline())) return;  // the ONE consent
      const old = btn && btn.textContent;
      if (btn) { btn.disabled = true; btn.textContent = t("Loading…"); }
      try {
        // The load runs ~3 min in a background job (returns {started, job}); poll the
        // job to completion and report the REAL stored figures — never the empty
        // start-state (which read "Loaded 0 figures." the instant the job began).
        await api("/api/governments/load-standard", {method: "POST", body: JSON.stringify({})});
        toast(t("Loading country data in the background…"), "ok",
          (typeof openTaskManager === "function") ? openTaskManager : null);
        const st = await pollJobStatus("/api/governments/load-standard/status", {
          onProgress: (s) => { if (btn && s.total) btn.textContent = t("Loading…") + " " + (s.done || 0) + "/" + s.total; },
        });
        if (st.state === "error") {
          toast((st.error) || t("Could not load country data."), "err");
        } else if (_jobStillRunning(st)) {
          // Polling gave up before the job finished — say so; never toast the
          // not-yet-final tally as if it were the result ("Loaded 0 figures.").
          toast(t("Still loading in the background — check the task manager for the result."), "ok",
            (typeof openTaskManager === "function") ? openTaskManager : null);
        } else {
          const res = st.result || {};
          let msg = t("Loaded country data:") + " " + (res.stored || 0) + " " + t("figures.");
          if (res.complete === false) msg += " " + t("(stopped early — partial)");
          toast(msg, "ok");
        }
        _govCountriesInit = false; _govMapInit = false; _govMapData = null;
        loadGovCountries();
      } catch (e) {
        toast((e && e.message) || t("Could not load country data."), "err");
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = old || t("Load standard country data"); }
      }
    }

    let _lawStatus = null;
    async function loadLaw() {
      try {
        const s = await api("/api/law/status");
        _lawStatus = s;
        const jur = Object.entries(s.jurisdictions || {});
        $("law-status").innerHTML =
          `<div class="stat"><div class="n">${s.documents}</div><div class="k">laws</div></div>` +
          `<div class="stat"><div class="n">${s.tracked}</div><div class="k">with baseline</div></div>` +
          `<div class="stat"><div class="n">${s.changes}</div><div class="k">changes</div></div>` +
          `<div class="stat"><div class="n">${s.flagged}</div><div class="k">flagged</div></div>` +
          `<div class="stat"><div class="n">${jur.length}</div><div class="k">jurisdictions</div></div>`;
      } catch (e) { _lawStatus = null; $("law-status").innerHTML = '<div class="muted">Status unavailable.</div>'; }
      loadLawChanges(); loadLawDocs();
    }
    // Field report 2026-07-17 (S2c): the law tracker is 2 clicks deep from the
    // Governments tab's default (Countries) view -- a small always-visible chip
    // makes it discoverable without changing the default subtab.
    // governments-law-pointer-misleading-zero-tracked (P1): this chip used to
    // label /api/law/status's `tracked` field (server-side: documents WITH A
    // COMPLETED BASELINE) as "tracked" -- reading "0 tracked" on a corpus with 23
    // real documents being watched, before any online pass has run a baseline. One
    // click away, the Law subtab uses the SAME API response correctly, showing
    // BOTH numbers ("23 documents tracked · 0 baselined"). Since the two concepts
    // are legitimately distinct, the pointer now shows both too, matching that
    // established wording exactly instead of collapsing to one misleading word.
    async function loadLawPointer() {
      const host = $("gov-law-pointer"); if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => v[k]));
      try {
        const s = await api("/api/law/status");
        host.textContent = "⚖ " + tf("Law: {documents} tracked · {baselined} baselined · {changes} changes",
          { documents: s.documents, baselined: s.tracked, changes: s.changes });
        host.title = t("Open the Law subtab — change tracking for statutes, gazettes and IP records.");
      } catch (e) { host.textContent = ""; }
    }
    // Colourised unified diff (green added / red removed), bounded for the feed.
    function renderDiff(diff, max = 400) {
      if (!diff) return "";
      const lines = diff.split("\n").slice(0, max);
      const more = diff.split("\n").length > max ? `<div class="dl ctx">… (diff truncated)</div>` : "";
      return `<div class="law-diff">` + lines.map(ln => {
        const c = ln[0] === "+" ? "add" : (ln[0] === "-" ? "del" : "ctx");
        return `<div class="dl ${c}">${esc(ln)}</div>`;
      }).join("") + more + `</div>`;
    }

    async function loadLawChanges() {
      const box = $("law-changes");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => v[k]));
      const fo = $("law-flagged-only") ? $("law-flagged-only").checked : false;
      try {
        const d = await api("/api/law/changes?flagged_only=" + fo);
        if (!d.changes || !d.changes.length) {
          // Field report 2026-07-17 (S2a): distinguish "nothing changed" from
          // "never ran" -- a working tracker with zero real amendments must NOT
          // read like a broken/never-started one.
          const s = _lawStatus;
          if (s && s.documents) {
            const scope = fo ? t("no FLAGGED changes") : t("no changes");
            const when = s.last_checked_at
              ? tf("last pass {ago}", { ago: fmtAgo(s.last_checked_at) })
              : t("never checked yet");
            box.innerHTML = `<div class="muted">` + esc(tf(
              "{scope} — {documents} documents tracked · {tracked} baselined · {when}.",
              { scope, documents: s.documents, tracked: s.tracked, when })) + `</div>`;
          } else {
            box.innerHTML = `<div class="muted">${esc(t("No documents tracked yet."))}</div>`;
          }
          return;
        }
        box.innerHTML = `<p class="hint">${esc(d.caveat)}</p>` + d.changes.map(ch =>
          `<div class="panel" style="background:var(--panel2); margin-top:8px">
            <b>${esc(ch.jurisdiction.toUpperCase())}</b> · ${esc(ch.title)}
            <span class="pill ${ch.flagged?'warn':''}">${ch.delta_bytes>0?'+':''}${ch.delta_bytes} bytes</span>
            ${(ch.flag_reasons||[]).length?'<span class="hint">'+ch.flag_reasons.map(esc).join(', ')+'</span>':''}
            <div class="hint" style="margin-top:4px">${ch.observed_at?fmtDateTime(ch.observed_at):''} ·
              <a href="/api/law/documents/${ch.document_id}/view" target="_blank" rel="noopener" title="offline stored copy + history">open reader</a> ·
              ${extLink(ch.official_url, "official source ↗", "muted")}</div>
            ${renderDiff(ch.diff)}
            <div class="law-ai-summary" data-rev="${ch.id}">${lawAiSummaryHtml(ch.id, ch.ai_summary)}</div>
          </div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load changes.</div>'; }
    }
    // AI change summaries (S3, ruled): auto-populated for UI-language-floor
    // jurisdictions; every other change offers an on-demand button. Loopback local
    // inference (airplane-safe since the §7 gate split) -- no ensureOnline gate,
    // matching the single-article summarize() precedent.
    function lawAiSummaryHtml(revId, s) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (s && s.summary) {
        return `“${esc(s.summary)}” <span class="muted">— ${esc(s.model)}</span>`
          + `<div class="hint muted">${esc(t("Generated by a local model — verify against the diff above."))}</div>`;
      }
      return `<button class="secondary tiny" onclick="lawSummarize(${revId}, this)">${esc(t("Summarize this change"))}</button>`;
    }
    async function lawSummarize(revId, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = btn.closest(".law-ai-summary");
      btn.disabled = true; btn.textContent = t("Summarizing locally…");
      try {
        const r = await api(`/api/law/revisions/${revId}/summarize`, { method: "POST" });
        if (r.ai_summary) { if (host) host.innerHTML = lawAiSummaryHtml(revId, r.ai_summary); return; }
        toast(t("Failed:") + " " + esc(r.status || "unavailable"), "err");
      } catch (e) {
        toast(t("Failed:") + " " + esc(e.message || e), "err");
      }
      btn.disabled = false; btn.textContent = t("Summarize this change");
    }
    // Field report 2026-07-17 (S2b): the per-doc last_status was written to the
    // table but never surfaced loudly -- classify it (verdict, from the API) into
    // a small coloured badge, keeping the REAL message on hover (never invented).
    const _LAW_VERDICT_PILL = {
      never_checked: "", robots_blocked: "warn", error: "warn", empty: "warn",
      changed: "ok", reverted: "", baselined: "ok", unchanged: "", other: "",
      re_extracted: "ok",
    };
    function lawVerdictBadge(x) {
      const tr = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const labels = {
        never_checked: tr("not checked yet"), robots_blocked: tr("robots-blocked"),
        error: tr("fetch error"), empty: tr("no usable text"), changed: tr("changed"),
        reverted: tr("reverted"), baselined: tr("baselined"), unchanged: tr("unchanged"),
        other: tr("other"), re_extracted: tr("re-read by us"),
      };
      const cls = _LAW_VERDICT_PILL[x.verdict] || "";
      const label = labels[x.verdict] || x.verdict;
      const hover = x.last_status ? esc(x.last_status) : tr("Never fetched yet.");
      return `<span class="pill ${cls}" title="${hover}">${esc(label)}</span>`;
    }
    let _lawDocsById = {};
    async function loadLawDocs() {
      const tr = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/law/documents");
        const tbl = $("law-docs");
        _lawDocsById = {};
        d.documents.forEach(x => { _lawDocsById[x.id] = x; });
        tbl.innerHTML = "<thead><tr><th>Jurisdiction</th><th>Title</th><th>Category</th><th>Status</th><th>Changes</th><th></th></tr></thead><tbody>" +
          d.documents.map(x =>
            `<tr${x.watched?'':' style="opacity:.55"'}><td>${esc(x.jurisdiction.toUpperCase())}</td><td>${esc(x.title)}</td><td>${esc(x.category)}</td>
              <td>${lawVerdictBadge(x)}${x.watched?'':' <span class="pill">'+esc(tr("not tracked"))+'</span>'}</td>
              <td>${x.revisions}${x.flagged?` (${x.flagged} flagged)`:''}</td>
              <td><a href="/api/law/documents/${x.id}/view" target="_blank" rel="noopener" title="offline stored copy + history">reader</a>
                · ${extLink(x.official_url||x.url, "official ↗", "muted")}
                · <a href="#" onclick="lawSetWatched(${x.id}, ${!x.watched}); return false" title="${x.watched?esc(tr('Stop tracking this document (its history stays).')):esc(tr('Resume tracking this document.'))}">${x.watched?esc(tr('stop')):esc(tr('resume'))}</a></td></tr>`).join("") +
          "</tbody>";
      } catch (e) { /* table optional */ }
    }
    async function lawAddDocument(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const msg = $("law-add-msg");
      const jurisdiction = $("law-add-jur").value.trim();
      const title = $("law-add-title").value.trim();
      const url = $("law-add-url").value.trim();
      const official_url = $("law-add-official").value.trim() || null;
      if (!jurisdiction || !title || !url) {
        msg.textContent = t("Jurisdiction, title and URL are all required.");
        return;
      }
      const online = await ensureOnline(t("Track a document now"));
      if (!online) return;
      btn.disabled = true;
      const label = btn.textContent; btn.textContent = t("Adding & tracking…");
      try {
        const r = await api("/api/law/documents", {
          method: "POST",
          body: JSON.stringify({ jurisdiction, title, url, official_url }),
        });
        msg.textContent = `${t("Added.")} ${t("Status:")} ${r.last_status || r.track_result.status}`;
        $("law-add-jur").value = ""; $("law-add-title").value = "";
        $("law-add-url").value = ""; $("law-add-official").value = "";
        loadLaw();
      } catch (e) {
        msg.textContent = e.message;
      } finally {
        btn.disabled = false; btn.textContent = label;
      }
    }
    async function lawSetWatched(id, watched) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        if (watched) {
          // Resuming re-adds by URL (the backend reactivates the SAME row rather
          // than duplicating it) -- a real fetch happens immediately, so gate it
          // like any other "track now" action.
          const x = _lawDocsById[id];
          if (!x) return;
          const online = await ensureOnline(t("Resume tracking this document"));
          if (!online) return;
          await api("/api/law/documents", {
            method: "POST",
            body: JSON.stringify({
              jurisdiction: x.jurisdiction, title: x.title, url: x.url,
              official_url: x.official_url || null,
            }),
          });
        } else {
          await api(`/api/law/documents/${id}`, { method: "DELETE" });
        }
      } catch (e) {
        toast(e.message, "err");
      }
      loadLaw();
    }
    async function lawTrack(btn) {
      // Long synchronous op (ethical, rate-limited fetch of each watched document):
      // give a persistent busy state so it never reads as "nothing happened".
      const label = btn ? btn.textContent : null;
      if (btn) { btn.disabled = true; btn.textContent = "Tracking…"; }
      const st = $("law-status");
      if (st) st.innerHTML = '<div class="muted">Tracking watched laws — ethical, rate-limited fetch; this can take a moment…</div>';
      try { const r = await api("/api/law/track", {method:"POST"});
        toast(`Tracked ${r.documents} law(s): ${r.baselines} baselines, ${r.changed} changed, ${r.flagged} flagged, ${r.errors} errors.`);
        loadLaw(); loadLawChanges && loadLawChanges();
      } catch (e) { toast(_failMsg("Tracking failed: {error}", e), "err"); if (st) loadLaw(); }
      finally { if (btn) { btn.disabled = false; btn.textContent = label || "Track changes now"; } }
    }
    async function lawSeed() {
      try { const r = await api("/api/law/seed", {method:"POST"});
        toast(`Seeded ${r.sources.created} sources, ${r.documents.created} laws.`); loadLaw(); }
      catch (e) { toast(e.message, "err"); }
    }

    // -- In-app documentation reader ---------------------------------------- //
