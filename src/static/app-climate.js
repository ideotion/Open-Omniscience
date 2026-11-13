/* app-climate.js — the Climate tab (0.6 gate row A; rulings R661, R662)

   Six published records, each in its own subtab: NASA GISTEMP temperature, NSIDC sea ice,
   NOAA's Oceanic Niño Index, the USGS earthquake catalogue, Our World in Data's emissions
   and energy tables, and one NOAA GHCN-Daily weather station at a time.

   THE DATA IS READ FROM THIS MACHINE. Opening the tab, switching a subtab, drawing a chart:
   all loopback reads of what an earlier fetch stored. The ONE thing that reaches a publisher
   is the Fetch button, and it passes the ONE network consent (ensureOnline, invariant #14)
   and then sends consent:true, because the endpoint refuses without it (#14f). A station id
   is checked before the consent is even asked, so a typo never reaches the popup.

   EVERY SERIES SAYS WHERE IT CAME FROM AND WHEN. The source's own page (a full-URL link,
   confirmed before it opens, invariant #7), its licence, when this machine last fetched it,
   how many values are gaps, and what the parser refused. Nothing is scored, ranked or turned
   into a risk number; caveats are visible, the long form rides in the hover (#oo-tip).

   The renderers below are pure (payload, t, tf) -> HTML so tests/climate_node_test.js runs
   them as real code; only the load* / draw functions touch the DOM or the network.
*/
    let _climateSubtabs = null;
    let _climateView = "gistemp";
    let _climateUnits = null;
    let _climateHosts = {};
    let _climateDrawGen = 0;
    const _climatePick = { gistemp: "GLB", nsidc: "N", owid: "co2", ghcnd: "" };
    const _climateOwid = { area: "World", column: "" };
    const _CLIMATE_IDS = ["gistemp", "nsidc", "oni", "usgs", "owid", "ghcnd", "place"];

    function _climateT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _climateTf() {
      return (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
    }

    // The words each dataset is shown with. Literal t() calls on purpose: the i18n ratchet
    // can only see a literal, and every one of these is a caveat surface (x12).
    function climateText(id, t) {
      switch (id) {
        case "gistemp": return {
          title: t("Global surface temperature (NASA GISTEMP v4)"),
          desc: t("Monthly and yearly land-and-ocean temperature anomalies against the 1951-1980 average, in °C."),
          caveat: t("An anomaly is a difference from the 1951-1980 average, not a temperature. NASA revises past months as late station reports arrive. Yearly means are placed at mid-year, monthly values at mid-month."),
          method: t("NASA GISS combines land stations (GHCN v4) with sea-surface temperatures (ERSST v5) and reports each month's difference from its 1951-1980 average."),
        };
        case "nsidc": return {
          title: t("Sea ice extent (NSIDC Sea Ice Index v3)"),
          desc: t("The daily area of ocean with at least 15% ice cover, in million km², for the Arctic or the Antarctic."),
          caveat: t("Before August 1987 the satellite record has a value every other day. The latest weeks are near-real-time values that NSIDC later replaces with its final product. Days when part of the pole was not observed are counted below."),
          method: t("NSIDC derives extent from passive-microwave satellite data: every grid cell with at least 15% ice concentration counts in full."),
        };
        case "oni": return {
          title: t("El Niño and La Niña (NOAA Oceanic Niño Index)"),
          desc: t("The three-month average sea-surface temperature anomaly in the Niño 3.4 region of the Pacific, in °C."),
          caveat: t("NOAA calls a season warm at +0.5 °C or above and cold at -0.5 °C or below, but an El Niño or La Niña episode needs five overlapping seasons in a row: one value is not an episode. NOAA updates the base period every five years, so past values can change. Each season is placed at its middle month."),
          method: t("NOAA's Climate Prediction Center averages the ERSST v5 sea-surface temperature over 5°N-5°S, 170°W-120°W for each three-month season and subtracts a centred 30-year base period."),
        };
        case "usgs": return {
          title: t("Large earthquakes (USGS catalogue)"),
          desc: t("Earthquakes of magnitude 6.0 and above worldwide, counted per month since January 1973, with each month's largest magnitude."),
          caveat: t("A count of catalogue entries: not a measure of seismic hazard and not a forecast. Detection improved over the decades, so early months may miss events. The month in progress is a gap until it ends, and recent events can still be revised by review."),
          method: t("The USGS ComCat catalogue through its FDSN event service: the service's own count for the window first, then every event of type earthquake at or above magnitude 6.0, counted by origin time in UTC."),
        };
        case "owid": return {
          title: t("Emissions and energy (Our World in Data)"),
          desc: t("Yearly emissions and energy figures by country and region, compiled by Our World in Data from the Global Carbon Project, the Energy Institute and Ember."),
          caveat: t("Our World in Data compiles other producers' figures; each column keeps its original producer's terms. Regions are shown under their published names and are never recomputed here."),
          method: t("Two bulk tables from Our World in Data's public repositories, read column by column; an empty cell is a published gap, never a zero."),
        };
        case "ghcnd": return {
          title: t("Weather station records (NOAA GHCN-Daily)"),
          desc: t("Daily temperature, precipitation and snow measured at one weather station, chosen by its 11-character GHCN id."),
          caveat: t("One station describes one place, not a region and not the climate. Days that failed NOAA's quality checks are gaps, never measurements."),
          method: t("NOAA NCEI's Global Historical Climatology Network - Daily: one file per station, with NCEI's quality-assurance flags."),
        };
        default: return { title: "", desc: "", caveat: "", method: "" };
      }
    }

    function climateParamLabel(id, p, t) {
      if (id === "gistemp") return p === "NH" ? t("Northern hemisphere") : p === "SH" ? t("Southern hemisphere") : t("Global");
      if (id === "nsidc") return p === "S" ? t("Antarctic") : t("Arctic");
      if (id === "owid") return p === "energy" ? t("Energy") : t("Emissions");
      return p || "";
    }

    function climateSeriesLabel(sid, t) {
      switch (sid) {
        case "gistemp.monthly": return t("Monthly anomaly");
        case "gistemp.annual_jd": return t("Yearly mean (January to December)");
        case "nsidc.sea_ice_extent_daily": return t("Daily sea ice extent");
        case "oni.anom": return t("Oceanic Niño Index");
        case "ghcnd.TMAX": return t("Daily maximum temperature");
        case "ghcnd.TMIN": return t("Daily minimum temperature");
        case "ghcnd.PRCP": return t("Daily precipitation");
        case "ghcnd.SNOW": return t("Daily snowfall");
        case "ghcnd.SNWD": return t("Snow depth");
        case "co2.co2": return t("CO₂ emissions");
        case "co2.co2_per_capita": return t("CO₂ emissions per person");
        case "co2.cumulative_co2": return t("Cumulative CO₂ emissions");
        case "co2.share_global_co2": return t("Share of world CO₂ emissions");
        case "co2.methane": return t("Methane emissions");
        case "co2.nitrous_oxide": return t("Nitrous oxide emissions");
        case "co2.total_ghg": return t("Total greenhouse gas emissions");
        case "co2.temperature_change_from_co2": return t("Warming attributed to CO₂ emissions");
        case "energy.primary_energy_consumption": return t("Primary energy consumption");
        case "energy.fossil_share_energy": return t("Fossil share of primary energy");
        case "energy.renewables_share_energy": return t("Renewable share of primary energy");
        case "energy.low_carbon_share_energy": return t("Low-carbon share of primary energy");
        case "energy.electricity_generation": return t("Electricity generation");
        case "energy.renewables_share_elec": return t("Renewable share of electricity");
        case "energy.carbon_intensity_elec": return t("Carbon intensity of electricity");
        default:
          if (/^usgs\.quakes\.count\./.test(sid)) return t("Earthquakes per month, magnitude 6.0 and above");
          if (/^usgs\.quakes\.max_mag\./.test(sid)) return t("Largest magnitude in the month");
          return sid;
      }
    }

    // Units as the reader expects them; anything unknown is shown as the publisher wrote it.
    function climateUnitLabel(u, t) {
      switch (u) {
        case "degC": return "°C";
        case "Mkm2": return t("million km²");
        case "events": return t("events");
        case "magnitude": return t("magnitude");
        default: return u || "";
      }
    }

    function _climateWhen(iso, t) {
      if (!iso) return t("never");
      return ooIsoDateTime(iso) + " UTC";
    }

    function _climateFact(label, valueHtml, hover) {
      const ttl = hover ? ` title="${esc(hover)}"` : "";
      return `<div class="climate-fact"${ttl}><span class="muted">${esc(label)}</span> <span>${valueHtml}</span></div>`;
    }

    // Provenance and freshness of one unit: source, licence, last fetch, what is stored and
    // what the last fetch refused or found missing. Counts and dates, never a verdict.
    function climateFactsHtml(unit, t, tf) {
      if (!unit) return "";
      const txt = climateText(unit.dataset, t);
      const facts = [];
      facts.push(_climateFact(t("Source"),
        `<a href="${esc(unit.source_page)}" target="_blank" rel="noopener noreferrer">${esc(unit.source_page)}</a>`, txt.method));
      facts.push(_climateFact(t("Licence"), esc(unit.licence), ""));
      const rec = unit.last_fetch, st = unit.stored || {};
      if (rec && rec.fetched_at) {
        facts.push(_climateFact(t("Last fetched"), esc(_climateWhen(rec.fetched_at, t)),
          t("When this machine last downloaded the file. Freshness is a date, never a judgement.")));
      } else if (st.stored_rows) {
        facts.push(_climateFact(t("Last fetched"), esc(tf("not recorded on this machine; newest stored values from {when}", {when: _climateWhen(st.newest_vintage, t)})), ""));
      } else {
        facts.push(_climateFact(t("Last fetched"), esc(t("never fetched on this machine")), ""));
      }
      if (st.stored_rows) {
        facts.push(_climateFact(t("Stored"), esc(tf("{rows} values from {vintages} fetches", {rows: fmtNum(st.stored_rows, 0), vintages: fmtNum(st.vintages, 0)})),
          t("A re-fetch stores only values that are new or that the publisher revised; earlier values stay readable and nothing is overwritten.")));
      }
      facts.push(_climateFact(t("Shape documented"), esc(unit.documented_as_of),
        t("When the file layout was written down from the publisher's documentation. The first real download is the check; a file that does not match is refused, never guessed.")));
      return `<div class="climate-facts">${facts.join("")}</div>` + climateDiagnosticsHtml(unit, t, tf);
    }

    // What the last fetch found: new, revised and unchanged values, gaps, refusals and the
    // dataset's own exclusions. Each number is shown only when the record carries it.
    function climateDiagnosticsHtml(unit, t, tf) {
      const rec = unit && unit.last_fetch;
      if (!rec) return "";
      const tally = rec.tally || {}, d = rec.diagnostics || {};
      const n = (v) => fmtNum(v || 0, 0);
      const lines = [];
      lines.push(tf("Last fetch: {new} new, {revised} revised, {unchanged} unchanged values; {gaps} published gaps.",
        {new: n(tally.new), revised: n(tally.revised), unchanged: n(tally.unchanged), gaps: n(tally.gaps)}));
      if (tally.withdrawn) lines.push(tf("{n} stored periods are no longer in the publisher's file; they are kept, not deleted.", {n: n(tally.withdrawn)}));
      if (tally.repeated) lines.push(tf("{n} values repeated a period already in the same file; the first was kept.", {n: n(tally.repeated)}));
      if (d.refused_total) lines.push(tf("{n} lines refused by the parser as not matching the documented layout.", {n: n(d.refused_total)}));
      if (d.coverage_gap_days) lines.push(tf("{n} days with part of the pole not observed.", {n: n(d.coverage_gap_days)}));
      if (d.rows_with_unknown_missing_area) lines.push(tf("{n} days whose observed coverage is unknown.", {n: n(d.rows_with_unknown_missing_area)}));
      if (d.excluded_non_earthquake) lines.push(tf("{n} events that were not earthquakes (explosions, quarry blasts) were left out.", {n: n(d.excluded_non_earthquake)}));
      if (typeof d.unreviewed === "number" && d.unreviewed) lines.push(tf("{n} counted events are not reviewed yet and may change.", {n: n(d.unreviewed)}));
      if (d.missing_days) lines.push(tf("{n} days published as missing.", {n: n(d.missing_days)}));
      if (d.quality_flagged_total) lines.push(tf("{n} days failed NOAA's quality checks and are shown as gaps.", {n: n(d.quality_flagged_total)}));
      if (d.trace_days) lines.push(tf("{n} days of trace precipitation, counted as zero by NOAA.", {n: n(d.trace_days)}));
      if (Array.isArray(d.columns_missing) && d.columns_missing.length) lines.push(tf("Columns not found in the file: {cols}.", {cols: d.columns_missing.join(", ")}));
      return `<ul class="climate-diag hint">${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
    }

    // The n line under a chart: values, gaps and the span. A gap is never counted as a value.
    function climateSeriesNote(s, t, tf) {
      if (!s || !s.points || !s.points.length) return t("Nothing stored for this series yet.");
      let out = tf("n = {n} values, {gaps} gaps, from {first} to {last}", {n: fmtNum(s.n, 0), gaps: fmtNum(s.gaps, 0), first: s.first, last: s.last});
      if (s.periods_with_several_vintages) out += " · " + tf("{n} periods revised by the publisher (latest value shown)", {n: fmtNum(s.periods_with_several_vintages, 0)});
      return out;
    }

    function climateUnitsFor(id) {
      return (_climateUnits || []).filter((u) => u.dataset === id);
    }
    function climateUnit(id, param) {
      return climateUnitsFor(id).find((u) => (u.param || "") === (param || "")) || null;
    }

    async function loadClimate() {
      const nav = $("climate-subtabs");
      if (nav && !_climateSubtabs) {
        const body = $("climate-body");
        if (body) body.addEventListener("click", _climateClick);
        _climateSubtabs = ooSubtabs(nav, showClimateView, { initial: _climateView });
      } else if (_climateSubtabs) _climateSubtabs.select(_climateView);
    }

    function showClimateView(id) {
      if (_CLIMATE_IDS.indexOf(id) < 0) id = "gistemp";
      _climateView = id;
      if (id === "place") { renderClimatePlace(); return; }
      loadClimateUnits();
    }

    async function loadClimateUnits() {
      const t = _climateT();
      try {
        const d = await api("/api/climate/datasets");
        _climateUnits = d.units || [];
        _climateHosts = d.hosts || {};
        renderClimate();
      } catch (e) {
        const body = $("climate-body");
        if (body) body.innerHTML = `<div class="muted">${esc(ooLabelText(t("Could not load"), e.message))}</div>`;
      }
    }

    function _climateParams(id) {
      if (id === "gistemp") return ["GLB", "NH", "SH"];
      if (id === "nsidc") return ["N", "S"];
      if (id === "owid") return ["co2", "energy"];
      if (id === "ghcnd") return climateUnitsFor("ghcnd").map((u) => u.param);
      return [null];
    }

    function renderClimate() {
      const t = _climateT(), tf = _climateTf();
      const body = $("climate-body");
      if (!body) return;
      const id = _climateView, txt = climateText(id, t);
      let p = _climatePick[id];
      if (id === "ghcnd" && !p) { const st = _climateParams("ghcnd"); p = _climatePick.ghcnd = st[0] || ""; }
      const unit = climateUnit(id, id === "oni" || id === "usgs" ? null : p);
      let html = `<h3 class="lib-sub">${esc(txt.title)}</h3><p class="hint" title="${esc(txt.method)}">${esc(txt.desc)}</p>`;
      html += `<div class="card-caveat">${esc(txt.caveat)}</div>`;
      const params = _climateParams(id);
      if (id === "ghcnd") {
        html += `<div class="row" style="align-items:center;gap:8px;margin:8px 0">
          <label for="climate-station" class="muted">${esc(t("Station id"))}</label>
          <input id="climate-station" type="text" maxlength="11" autocomplete="off" spellcheck="false" style="max-width:12em"
            placeholder="USW00094728" title="${esc(t("An 11-character GHCN-Daily station id. USW00094728 is New York, Central Park; NOAA lists every station in ghcnd-stations.txt."))}">
          <button type="button" data-climate-fetch="station">${esc(t("Fetch station"))}</button></div>`;
      }
      if (params.length > 1 || (id === "ghcnd" && params.length)) {
        html += `<div class="seg-toggle wrap climate-params" role="group">` + params.map((q) => `<button type="button" class="${q === p ? "active" : ""}" data-climate-param="${esc(q)}">${esc(climateParamLabel(id, q, t))}</button>`).join("") + `</div>`;
      }
      if (unit) {
        html += climateFactsHtml(unit, t, tf);
        const verb = unit.last_fetch || (unit.stored && unit.stored.stored_rows) ? t("Update from the publisher") : t("Fetch from the publisher");
        if (id !== "ghcnd") html += `<div class="row" style="margin:8px 0"><button type="button" data-climate-fetch="unit" title="${esc(tf("Sends a request to {host}. Refused while airplane mode is on.", {host: unit.host}))}">${esc(verb)}</button></div>`;
        else html += `<div class="row" style="margin:8px 0"><button type="button" class="secondary" data-climate-fetch="refresh" title="${esc(tf("Sends a request to {host}. Refused while airplane mode is on.", {host: unit.host}))}">${esc(t("Update this station"))}</button></div>`;
      } else if (id === "ghcnd") {
        html += `<div class="muted">${esc(t("No station fetched yet. Type a station id above and fetch it."))}</div>`;
      }
      if (id === "owid" && unit && unit.stored && unit.stored.stored_rows) {
        html += `<div class="row" style="gap:8px;align-items:center;margin:6px 0"><label class="muted" for="climate-owid-col">${esc(t("Figure"))}</label><select id="climate-owid-col"></select>
          <label class="muted" for="climate-owid-area">${esc(t("Country or region"))}</label><select id="climate-owid-area"></select></div>`;
      }
      html += `<div id="climate-charts"></div>`;
      body.innerHTML = html;
      if (unit && unit.stored && unit.stored.stored_rows) climateDrawCharts(unit);
    }

    async function _climateOwidPickers(unit, gen) {
      const t = _climateT();
      const colSel = $("climate-owid-col"), areaSel = $("climate-owid-area");
      if (!colSel || !areaSel) return null;
      const cols = (unit.charts || []).map((c) => c[0]);
      if (!cols.some((c) => c.series_id === _climateOwid.column)) _climateOwid.column = cols.length ? cols[0].series_id : "";
      colSel.innerHTML = cols.map((c) => `<option value="${esc(c.series_id)}"${c.series_id === _climateOwid.column ? " selected" : ""}>${esc(climateSeriesLabel(c.series_id, t))}</option>`).join("");
      const a = await api("/api/climate/areas?dataset=owid&param=" + encodeURIComponent(unit.param));
      if (gen !== _climateDrawGen) return null;  // a newer draw owns the pickers now
      const areas = (a.areas || []).slice().sort((x, y) => String(x.name).localeCompare(String(y.name)));
      if (!areas.some((x) => x.code === _climateOwid.area) && areas.length) _climateOwid.area = areas[0].code;
      areaSel.innerHTML = areas.map((x) => `<option value="${esc(x.code)}"${x.code === _climateOwid.area ? " selected" : ""}>${esc(x.name)}</option>`).join("");
      if (!colSel._climateWired) {
        colSel._climateWired = true;
        colSel.addEventListener("change", () => { _climateOwid.column = colSel.value; climateDrawCharts(unit); });
        areaSel.addEventListener("change", () => { _climateOwid.area = areaSel.value; climateDrawCharts(unit); });
      }
      return cols.filter((c) => c.series_id === _climateOwid.column);
    }

    async function climateDrawCharts(unit) {
      const t = _climateT(), tf = _climateTf();
      const host = $("climate-charts");
      if (!host) return;
      // A newer draw (another subtab or parameter) makes this one stale: it stops after each await.
      const gen = ++_climateDrawGen;
      let charts = unit.charts || [], area = unit.area;
      if (unit.dataset === "owid") {
        const pick = await _climateOwidPickers(unit, gen);
        if (gen !== _climateDrawGen) return;
        charts = pick ? [pick] : [];
        area = _climateOwid.area;
      }
      host.innerHTML = charts.map((_c, i) => `<div class="climate-chart" style="margin-top:12px"><div id="climate-chart-${i}"></div><div class="hint" id="climate-note-${i}"></div></div>`).join("");
      for (let i = 0; i < charts.length; i++) {
        const group = charts[i];
        const loaded = await Promise.all(group.map((s) => api("/api/climate/series?" + new URLSearchParams({
          dataset: unit.dataset, series_id: s.series_id, area: area || "", param: unit.param || "",
        }).toString()).catch(() => null)));
        if (gen !== _climateDrawGen) return;
        const withData = loaded.map((d, k) => ({ d, s: group[k] })).filter((x) => x.d && x.d.points && x.d.points.length);
        const el = $("climate-chart-" + i), note = $("climate-note-" + i);
        if (!el) continue;
        if (!withData.length) {
          el.innerHTML = `<div class="muted">${esc(t("Nothing stored for this series yet."))}</div>`;
          continue;
        }
        ooChart(el, withData.map((x) => ({
          label: climateSeriesLabel(x.s.series_id, t), unit: climateUnitLabel(x.s.unit, t), points: x.d.points,
        })), { height: 240, maxWidth: 1100 });
        if (note) note.textContent = withData.map((x) => climateSeriesLabel(x.s.series_id, t) + ": " + climateSeriesNote(x.d, t, tf)).join(" · ");
      }
    }

    function _climateClick(ev) {
      const ab = ev.target.closest("[data-climate-place]");
      if (ab) { climatePlaceShow(ab.getAttribute("data-climate-place") === "again"); return; }
      const pb = ev.target.closest("[data-climate-param]");
      if (pb) {
        _climatePick[_climateView] = pb.getAttribute("data-climate-param");
        renderClimate();
        return;
      }
      const fb = ev.target.closest("[data-climate-fetch]");
      if (!fb) return;
      const kind = fb.getAttribute("data-climate-fetch");
      if (kind === "station") {
        const inp = $("climate-station");
        climateFetch("ghcnd", inp ? inp.value : "");
      } else if (kind === "refresh") {
        climateFetch("ghcnd", _climatePick.ghcnd);
      } else {
        climateFetch(_climateView, _climateView === "oni" || _climateView === "usgs" ? null : _climatePick[_climateView]);
      }
    }

    // ---- "Your place" (R675): temperature and precipitation against 1991-2020, Open-Meteo ----

    const _PLACE_KEY = "oo.climate.place";
    const _PLACE_HOST = "archive-api.open-meteo.com";

    function climatePlaceDefaults(today) {
      // Reanalysis reaches the archive about five days late: the window ends a week ago.
      const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
      const end = new Date(d.getTime() - 7 * 86400000), start = new Date(end.getTime() - 29 * 86400000);
      const iso = (x) => x.toISOString().split("T")[0];
      return {start: iso(start), end: iso(end)};
    }

    // The same rounding the server applies before anything is sent (R675): one decimal.
    function climatePlaceRound(v) {
      const r = Math.round(Number(v) * 10) / 10;
      return Object.is(r, -0) ? 0 : r;
    }

    // A plain sentence for a query the server would refuse, or "" when it is acceptable.
    function climatePlaceProblem(q, today, t) {
      const lat = Number(q.lat), lon = Number(q.lon);
      if (q.lat === "" || q.lon === "" || !isFinite(lat) || !isFinite(lon)) return t("Type a latitude and a longitude in decimal degrees, for example 48.85 and 2.35.");
      if (lat < -90 || lat > 90) return t("Latitude goes from -90 to 90.");
      if (lon < -180 || lon > 180) return t("Longitude goes from -180 to 180.");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(q.start || "") || !/^\d{4}-\d{2}-\d{2}$/.test(q.end || "")) return t("Choose a first and a last day.");
      if (q.end < q.start) return t("The last day comes before the first day.");
      const days = (Date.parse(q.end) - Date.parse(q.start)) / 86400000;
      if (days > 366) return t("A window is at most 366 days.");
      if (q.start < "1940-01-01") return t("The archive starts on 1 January 1940.");
      if (q.end > today.toISOString().split("T")[0]) return t("The archive holds past days only.");
      return "";
    }

    function _climatePlaceSaved() {
      try { const v = JSON.parse(localStorage.getItem(_PLACE_KEY) || "null"); return v && typeof v === "object" ? v : null; } catch (_e) { return null; }
    }
    function _climatePlaceSave(q) {
      // Browser storage is not encrypted, so only the ROUNDED place is remembered (the precision
      // that is sent anyway), never the coordinates as typed (R675).
      const keep = {lat: q.lat === "" ? "" : climatePlaceRound(q.lat), lon: q.lon === "" ? "" : climatePlaceRound(q.lon),
                    start: q.start, end: q.end};
      try { localStorage.setItem(_PLACE_KEY, JSON.stringify(keep)); } catch (_e) { /* a convenience only */ }
    }

    function climatePlaceVarLabel(v, t) {
      switch (v) {
        case "temperature_2m_max": return t("Daily highest temperature");
        case "temperature_2m_min": return t("Daily lowest temperature");
        case "precipitation_sum": return t("Precipitation");
        default: return String(v || "");
      }
    }

    // The result table: every number with its unit, a missing one with its reason, never a verdict.
    function climatePlaceResultHtml(d, t, tf) {
      if (!d || !Array.isArray(d.results)) return "";
      const sign = (x) => (x > 0 ? "+" : "") + fmtNum(x, 1);
      const rows = d.results.map((r) => {
        const name = esc(climatePlaceVarLabel(r.variable, t));
        if (r.value == null) {
          return `<tr><td>${name}</td><td colspan="3" class="muted">${esc(ooLabelText(t("Not computed"), r.reason || ""))}</td></tr>`;
        }
        const unit = r.unit === "°C" ? " °C" : " mm";
        const diff = r.kind === "mean" ? sign(r.value) + " °C" : tf("{pct}% of the average", {pct: fmtNum(r.value, 0)});
        const years = tf("{used} of 30 years used", {used: fmtNum(r.years_used, 0)}) +
          (r.years_excluded ? " · " + tf("{n} excluded for a missing day", {n: fmtNum(r.years_excluded, 0)}) : "");
        return `<tr><td>${name}</td><td>${esc(fmtNum(r.window_value, 1) + unit)}</td><td>${esc(fmtNum(r.baseline_value, 1) + unit)}</td><td><strong>${esc(diff)}</strong><div class="hint">${esc(years)}</div></td></tr>`;
      }).join("");
      let html = `<table class="climate-place-table"><thead><tr><th>${esc(t("Measure"))}</th><th>${esc(t("These days"))}</th><th>${esc(t("Same days, 1991-2020 average"))}</th><th>${esc(t("Difference"))}</th></tr></thead><tbody>${rows}</tbody></table>`;
      if (d.results.some((r) => r.window_in_baseline_period)) {
        html += `<div class="hint">${esc(t("These days fall inside 1991-2020, so they are part of the average they are compared with."))}</div>`;
      }
      const prov = d.provenance || {}, w = prov.window || {}, b = prov.baseline || {};
      const when = (p) => (p && p.fetched_at ? _climateWhen(p.fetched_at, t) : t("not recorded"));
      html += `<div class="climate-facts">` +
        _climateFact(t("Fetched"), esc(tf("these days {w}; the 1991-2020 values {b}", {w: when(w), b: when(b)})), "") +
        _climateFact(t("Licence"), esc(d.license || ""), "") + `</div>`;
      if (d.kept === false) html += `<div class="card-caveat">${esc(t("These values could not be kept on this machine; they are shown once and not stored."))}</div>`;
      return html;
    }

    function renderClimatePlace() {
      const t = _climateT(), tf = _climateTf();
      const body = $("climate-body");
      if (!body) return;
      const saved = _climatePlaceSaved() || {};
      const dflt = climatePlaceDefaults(new Date());
      const q = {lat: saved.lat ?? "", lon: saved.lon ?? "", start: saved.start || dflt.start, end: saved.end || dflt.end};
      body.innerHTML = `<h3 class="lib-sub">${esc(t("Your place: temperature and precipitation against 1991-2020"))}</h3>
        <p class="hint" title="${esc(t("For each day of the window, the same calendar day in each year from 1991 to 2020 is averaged. Temperatures compare the mean of the window with the mean of those days; precipitation compares the window's total with the average total. A baseline year with a missing day is left out and counted."))}">${esc(t("Type a place and a window of up to a year. The difference from the 1991-2020 average of the same calendar days is shown for the daily highest and lowest temperature and for precipitation."))}</p>
        <div class="card-caveat">${esc(t("Reanalysis is a weather model's reconstruction for an area of about 11 km, not a station's measurement. A difference is a fact about these days, not a forecast, a trend or a verdict."))}</div>
        <div class="row" style="flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0">
          <label class="muted" for="climate-place-lat">${esc(t("Latitude"))}</label><input id="climate-place-lat" type="number" step="0.01" min="-90" max="90" style="max-width:8em" value="${esc(q.lat)}">
          <label class="muted" for="climate-place-lon">${esc(t("Longitude"))}</label><input id="climate-place-lon" type="number" step="0.01" min="-180" max="180" style="max-width:8em" value="${esc(q.lon)}">
          <label class="muted" for="climate-place-start">${esc(t("First day"))}</label><input id="climate-place-start" type="date" min="1940-01-01" value="${esc(q.start)}">
          <label class="muted" for="climate-place-end">${esc(t("Last day"))}</label><input id="climate-place-end" type="date" min="1940-01-01" value="${esc(q.end)}">
        </div>
        <div class="hint">${esc(tf("What leaves this machine: the place, rounded to 0.1 degree (about 11 km), and the dates, sent to {host}. The first time for a place, it also downloads the 1991-2020 daily values for that place, about 11,000 days; they are kept in this app's database (encrypted unless you chose to keep it unencrypted), so other windows for the same place need one small request. This browser remembers the rounded place for next time.", {host: _PLACE_HOST}))}</div>
        <div class="row" style="gap:8px;margin:8px 0"><button type="button" data-climate-place="show">${esc(t("Show"))}</button>
          <button type="button" class="secondary" data-climate-place="again" title="${esc(t("Downloads both again, for example once the latest days have been finalised."))}">${esc(t("Fetch again"))}</button></div>
        <div id="climate-place-out"></div>`;
      if (q.lat !== "" && q.lon !== "") climatePlaceShow(false, true);
    }

    async function climatePlaceShow(again, quiet) {
      const t = _climateT(), tf = _climateTf();
      const out = $("climate-place-out"), st = $("climate-status");
      const say = (s) => { if (st) st.textContent = s; };
      const val = (id) => { const el = $(id); return el ? String(el.value).trim() : ""; };
      const q = {lat: val("climate-place-lat"), lon: val("climate-place-lon"), start: val("climate-place-start"), end: val("climate-place-end")};
      const bad = climatePlaceProblem(q, new Date(), t);
      if (bad) { if (!quiet) say(bad); return; }
      _climatePlaceSave(q);
      const lat = climatePlaceRound(q.lat), lon = climatePlaceRound(q.lon);
      const params = new URLSearchParams({lat: String(lat), lon: String(lon), start_date: q.start, end_date: q.end});
      try {
        if (!again) {
          const held = await api("/api/weather/anomaly/held?" + params.toString());
          if (held && held.held) { if (out) out.innerHTML = climatePlaceResultHtml(held, t, tf); say(t("Read from this machine; nothing was sent.")); return; }
          if (quiet) { if (out) out.innerHTML = `<div class="muted">${esc(t("Not fetched on this machine yet for this place and window."))}</div>`; return; }
        }
        // The ONE consent (invariant #14); it names what leaves the machine. A place is personal,
        // so it is asked for EVERY request (R675): when the app is already online the consent
        // popup would not open, and a plain confirmation naming the place stands in for it.
        const ask = tf("Send the place {lat}, {lon} (rounded to 0.1 degree) and the dates to {host}", {lat: fmtNum(lat, 1), lon: fmtNum(lon, 1), host: _PLACE_HOST});
        let online = false;
        try { const nm = await api("/api/system/network"); online = !!(nm && nm.online); } catch (_e) { online = false; }
        if (online) { if (!window.confirm(ask)) return; }
        else if (typeof ensureOnline === "function" && !await ensureOnline(ask)) return;
        say(t("Fetching…"));
        const d = await api("/api/weather/anomaly", {method: "POST", body: JSON.stringify({
          lat: lat, lon: lon, start_date: q.start, end_date: q.end, force: !!again, consent: true,
        })});
        if (!d || d.ok === false) {
          say(ooLabelText(t("Could not fetch"), (d && (d.verdict_note || d.verdict)) || ""));
          return;
        }
        if (out) out.innerHTML = climatePlaceResultHtml(d, t, tf);
        say("");
      } catch (e) {
        say(ooLabelText(t("Could not fetch"), e.message));
      }
    }

    // A GHCN-Daily station id: two letters, then nine letters or digits (the server checks the
    // same pattern; this only spares the consent popup a request that would be refused anyway).
    function climateStationOk(s) {
      return /^[A-Z]{2}[A-Z0-9]{9}$/.test(String(s || "").trim().toUpperCase());
    }

    function _climateHost(id) {
      const u = (_climateUnits || []).find((x) => x.dataset === id);
      return u ? u.host : (_climateHosts[id] || "");
    }

    async function climateFetch(id, param) {
      const t = _climateT(), tf = _climateTf();
      const st = $("climate-status");
      const say = (s) => { if (st) st.textContent = s; };
      if (id === "ghcnd") {
        if (!climateStationOk(param)) { say(t("A GHCN station id is 11 characters: two letters, then nine letters or digits (for example USW00094728).")); return; }
        param = String(param).trim().toUpperCase();
      }
      const title = climateText(id, t).title;
      // The ONE consent (invariant #14); its answer is USED.
      if (typeof ensureOnline === "function"
          && !await ensureOnline(tf("Fetch {dataset} from {host}, over your transport", {dataset: title, host: _climateHost(id)}))) return;
      say(t("Fetching in the background…"));
      try {
        const started = await api("/api/climate/fetch", {method: "POST", body: JSON.stringify({dataset: id, param: param, consent: true})});
        if (started && started.started === false) { say(t("Another climate fetch is already running; try again when it finishes.")); return; }
        const job = await pollJobStatus("/api/climate/fetch/status");
        if (job.state === "error") { say(ooLabelText(t("Climate fetch failed"), job.error || "")); return; }
        if (_jobStillRunning(job)) { say(t("Still running in the background — check the task manager for the result.")); return; }
        const r = job.result || {}, tally = r.tally || {};
        say(tf("Fetched {n} values: {new} new, {revised} revised, {unchanged} unchanged.",
          {n: fmtNum(r.figures || 0, 0), new: fmtNum(tally.new || 0, 0), revised: fmtNum(tally.revised || 0, 0), unchanged: fmtNum(tally.unchanged || 0, 0)}));
        if (id === "ghcnd") _climatePick.ghcnd = param;
        await loadClimateUnits();
      } catch (e) {
        say(ooLabelText(t("Climate fetch failed"), e.message));
      }
    }
