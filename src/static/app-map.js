/* app-map.js — world map and offline datasets

   The ooMap choropleth with its lenses and signal layers, the temporal map, the
   region and folder pickers, and the offline datasets reached beside them: wiki
   dumps, pages and tracked changes, OSM regions, and the official-statistics panels.

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
    const MAP_W = 720, MAP_H = 360;
    let MAP_VB = {x: 0, y: 0, w: MAP_W, h: MAP_H};
    const lon2x = lon => (Number(lon) + 180) / 360 * MAP_W;
    const lat2y = lat => (90 - Number(lat)) / 180 * MAP_H;

    function applyVB() {
      const svg = document.getElementById("oo-map");
      if (svg) svg.setAttribute("viewBox", `${MAP_VB.x} ${MAP_VB.y} ${MAP_VB.w} ${MAP_VB.h}`);
    }
    function zoomMap(f) {
      const cx = MAP_VB.x + MAP_VB.w/2, cy = MAP_VB.y + MAP_VB.h/2;
      MAP_VB.w = Math.min(MAP_W, Math.max(40, MAP_VB.w * f));
      MAP_VB.h = Math.min(MAP_H, Math.max(20, MAP_VB.h * f));
      MAP_VB.x = cx - MAP_VB.w/2; MAP_VB.y = cy - MAP_VB.h/2;
      applyVB();
    }
    function resetMap() { MAP_VB = {x: 0, y: 0, w: MAP_W, h: MAP_H}; applyVB(); }

    function buildMapSvg(cities) {
      const placed = cities.filter(c => c.lat != null && c.lon != null);
      // graticule every 30 degrees
      let grid = "";
      for (let lon = -180; lon <= 180; lon += 30)
        grid += `<line x1="${lon2x(lon)}" y1="0" x2="${lon2x(lon)}" y2="${MAP_H}" stroke="var(--border)" stroke-width="0.3"/>`;
      for (let lat = -90; lat <= 90; lat += 30)
        grid += `<line x1="0" y1="${lat2y(lat)}" x2="${MAP_W}" y2="${lat2y(lat)}" stroke="var(--border)" stroke-width="0.3"/>`;
      const maxM = Math.max(1, ...placed.map(c => (c.top||[]).reduce((s,t)=>s+t.mentions,0)));
      const dots = placed.map(c => {
        const x = lon2x(c.lon).toFixed(1), y = lat2y(c.lat).toFixed(1);
        const m = (c.top||[]).reduce((s,t)=>s+t.mentions,0);
        const r = (1.5 + 4*Math.sqrt(m/maxM)).toFixed(1);
        const terms = (c.top||[]).map(t=>t.term+" "+t.mentions).join(", ");
        return `<g><circle cx="${x}" cy="${y}" r="${r}" fill="var(--accent)" fill-opacity="0.75">
            <title>${esc(c.name)}${c.country?" ("+esc(c.country)+")":""}: ${esc(terms)}</title></circle>
          <text x="${x}" y="${(y-Number(r)-1).toFixed(1)}" fill="var(--fg)" font-size="4" text-anchor="middle">${esc(c.name)}</text></g>`;
      }).join("");
      if (!placed.length)
        return `<div class="muted">No placed cities yet. Index the corpus (sources need a city), or generate the full gazetteer (scripts/build_city_gazetteer.py).</div>`;
      return `<svg id="oo-map" viewBox="0 0 ${MAP_W} ${MAP_H}" width="100%" style="max-width:${MAP_W}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px;cursor:grab">
        ${grid}${dots}</svg>`;
    }

    function wireMapDrag() {
      const svg = document.getElementById("oo-map");
      if (!svg) return;
      let dragging = false, sx = 0, sy = 0;
      svg.addEventListener("mousedown", e => { dragging = true; sx = e.clientX; sy = e.clientY; svg.style.cursor = "grabbing"; });
      window.addEventListener("mouseup", () => { dragging = false; if (svg) svg.style.cursor = "grab"; });
      svg.addEventListener("mousemove", e => {
        if (!dragging) return;
        const rect = svg.getBoundingClientRect();
        MAP_VB.x -= (e.clientX - sx) * MAP_VB.w / rect.width;
        MAP_VB.y -= (e.clientY - sy) * MAP_VB.h / rect.height;
        sx = e.clientX; sy = e.clientY; applyVB();
      });
    }

    // ============================ ooMap ================================ //
    // Universal CHOROPLETH world map (no deps, like ooChart/ooSubtabs). Colours
    // each country POLYGON by a measured data dimension on a sequential scale,
    // with in-map zoom/pan, a legend, honest no-data, and a centroid POINT
    // fallback for territories the coarse 110m geometry has no polygon for
    // (a point, never an invented border). Reuses the equirectangular
    // projection (lon2x/lat2y, MAP_W/MAP_H). Maintainer ruling 2026-06-18.
    // Localised COUNTRY name from an ISO-2 code via the browser's CLDR data
    // (Intl.DisplayNames) — accurate in every locale, no translation tables. Falls
    // back to the supplied English name / the code. Reusable wherever the UI shows
    // a country as a NAME (the map, the Sources table); code-only surfaces (FR/US)
    // stay as their language-neutral codes.
    const _ooRegionDN = {};
    function ooRegionName(code, fallback) {
      const cc = (code || "").trim().toUpperCase();
      if (!cc) return fallback || "";
      const lang = (window.OOI18N && OOI18N.current && OOI18N.current()) || "en";
      try {
        if (!_ooRegionDN[lang]) _ooRegionDN[lang] = new Intl.DisplayNames([lang], { type: "region" });
        return _ooRegionDN[lang].of(cc) || fallback || cc;
      } catch { return fallback || cc; }
    }
    // The language analog (field test 2026-06-19 #52/#53, THEME-4): show the full
    // language NAME in the current UI locale via the browser's own CLDR data, instead
    // of a bare 2-letter code (e.g. "fr" -> "French" / "Français" / "Französisch"),
    // EXCEPT the top status-bar flag/code. Per-locale cached; degrades to the code on
    // an unknown/structurally-invalid tag. Re-derives on oo:langchange (same as names).
    const _ooLangDN = {};
    function ooLangName(code, fallback) {
      const lc = (code || "").trim();
      if (!lc) return fallback || "";
      const ui = (window.OOI18N && OOI18N.current && OOI18N.current()) || "en";
      try {
        if (!_ooLangDN[ui]) _ooLangDN[ui] = new Intl.DisplayNames([ui], { type: "language" });
        return _ooLangDN[ui].of(lc) || fallback || lc;
      } catch { return fallback || lc; }
    }

    // Server-side folder picker (field test 2026-06-22 #8: "Browse buttons, never
    // manual path typing"). Lists subdirectories via /api/fs/list (folders only,
    // never file names) so the user can pick a backup destination / .eml import
    // folder ON THIS MACHINE without typing the path. Writes the chosen absolute
    // path into the given input. Listeners are addEventListener (no inline onclick).
    let _fpState = { inputId: null, requireWritable: false, current: null };
    async function ooFolderPicker(inputId, requireWritable) {
      _fpState = { inputId, requireWritable: !!requireWritable, current: null };
      const inp = $(inputId);
      await _fpNav((inp && inp.value || "").trim() || null);
      const dlg = $("folder-picker");
      if (dlg && dlg.showModal) dlg.showModal();
    }
    async function _fpNav(path) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s) => s;
      let d;
      try {
        d = await api("/api/fs/list?show_hidden=false" + (path ? "&path=" + encodeURIComponent(path) : ""));
      } catch (e) {
        $("fp-list").innerHTML = `<div class="muted" style="padding:10px">${esc(e.message)}</div>`;
        return;
      }
      _fpState.current = d.path;
      $("fp-path").textContent = d.path;
      const rows = [];
      if (d.parent) rows.push(`<div class="fp-row" data-path="${esc(d.parent)}" style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--line)">⬆ ${esc(t("Parent folder"))}</div>`);
      for (const e of (d.entries || [])) rows.push(`<div class="fp-row" data-path="${esc(e.path)}" style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--line)">📁 ${esc(e.name)}</div>`);
      if (!(d.entries || []).length) rows.push(`<div class="muted" style="padding:10px">${esc(t("No sub-folders here."))}</div>`);
      $("fp-list").innerHTML = rows.join("");
      $("fp-list").querySelectorAll(".fp-row").forEach(el => el.addEventListener("click", () => _fpNav(el.dataset.path)));
      const useBtn = $("fp-use");
      const blocked = _fpState.requireWritable && d.writable === false;
      if (useBtn) useBtn.disabled = !!blocked;
      $("fp-note").textContent = blocked
        ? t("This folder is not writable — pick another for a backup destination.")
        : (d.truncated ? t("Showing the first folders only.") : "");
    }
    function ooFolderPickerUse() {
      const inp = $(_fpState.inputId);
      if (inp && _fpState.current) { inp.value = _fpState.current; inp.dispatchEvent(new Event("change")); }
      const dlg = $("folder-picker");
      if (dlg) dlg.close();
    }

    let _ooMapGeo = null;                            // cached world_countries.json
    async function _ooMapGeoLoad() {
      if (_ooMapGeo !== null) return _ooMapGeo;
      try { const r = await fetch("/static/world_countries.json"); _ooMapGeo = r.ok ? await r.json() : false; }
      catch { _ooMapGeo = false; }                   // absent -> honest "unavailable", never an error
      return _ooMapGeo;
    }
    function _ooMapPath(rings) {                      // [[lon,lat]...] rings -> SVG path 'd'
      return (rings || []).map(ring => ring.length
        ? "M" + ring.map(p => `${lon2x(p[0]).toFixed(1)} ${lat2y(p[1]).toFixed(1)}`).join("L") + "Z" : "").join(" ");
    }
    // Sequential fill: t in [0,1] -> theme accent over panel2. The MINIMUM data
    // value still reads as >=12% accent so a data area is never mistaken for the
    // hatched "no data" fill. color-mix inherits the active theme palette.
    function _ooMapFill(t) {
      const pct = Math.round(12 + Math.max(0, Math.min(1, t)) * 88);
      return `color-mix(in srgb, var(--accent) ${pct}%, var(--panel2))`;
    }
    // Diverging fill for SIGNED data (e.g. mean tone): t in [-1,1] -> a
    // theme-aware red(--err)..panel..green(--ok) ramp (negative left, positive
    // right). Signed data must never ride a one-sided sequential scale.
    function _ooMapFillDiverging(t) {
      const m = Math.max(-1, Math.min(1, t));
      const pct = Math.round(10 + Math.abs(m) * 80);
      return `color-mix(in srgb, ${m < 0 ? "var(--err)" : "var(--ok)"} ${pct}%, var(--panel2))`;
    }

    // Signal marker SHAPE by certainty class (THEME-2): colour = kind, shape =
    // certainty, so the map reads without relying on colour alone.
    function _ooSigClass(s) {
      if (s && s.source === "corpus-mention") return "deduced";   // extracted from text, never confirmed
      if (s && !s.confirmed) return "scheduled";                  // an upcoming/unconfirmed event
      return "confirmed";
    }
    function _ooSigClassLabel(cls) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      return cls === "deduced" ? t("deduced · never confirmed")
        : cls === "scheduled" ? t("scheduled / unconfirmed") : t("confirmed");
    }
    // Returns the SVG marker element string: confirmed = circle, scheduled =
    // triangle, deduced = diamond. `fill` is the pre-built fill/stroke attr string.
    function _ooSigMarker(cls, x, y, r, fill, titleEsc) {
      const ttl = `<title>${titleEsc}</title>`;
      if (cls === "scheduled") {
        const pts = `${x},${(y - r).toFixed(1)} ${(x - r).toFixed(1)},${(y + r * 0.8).toFixed(1)} ${(x + r).toFixed(1)},${(y + r * 0.8).toFixed(1)}`;
        return `<polygon points="${pts}" ${fill}>${ttl}</polygon>`;
      }
      if (cls === "deduced") {
        const pts = `${x},${(y - r).toFixed(1)} ${(x + r).toFixed(1)},${y} ${x},${(y + r).toFixed(1)} ${(x - r).toFixed(1)},${y}`;
        return `<polygon points="${pts}" ${fill}>${ttl}</polygon>`;
      }
      return `<circle cx="${x}" cy="${y}" r="${r}" ${fill}>${ttl}</circle>`;
    }

    // The choropleth scale is LINEAR by default (faithful to magnitude; it
    // surfaces real skew rather than flattening it). opts:
    //   values {iso2:number} · points [{iso2,lat,lon,value,label}] (centroid
    //   fallback) · label · unit · method · caveat · aria · names {iso2:name}
    //   · valueLabel(iso2,v)->string · onCountry(iso2) · labelsOn/onLabels
    async function ooMap(host, opts) {
      if (!host) return;
      opts = opts || {};
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      const geo = await _ooMapGeoLoad();
      if (!geo || !geo.countries) { host.innerHTML = `<div class="muted">${esc(t("Map geometry unavailable."))}</div>`; return; }
      const values = opts.values || {}, names = opts.names || {};
      const nums = Object.values(values).filter(v => typeof v === "number" && isFinite(v));
      const maxV = nums.length ? Math.max(...nums) : 0, minV = nums.length ? Math.min(...nums) : 0;
      const span = maxV - minV;
      const diverging = opts.scale === "diverging";
      const maxAbs = nums.length ? Math.max(...nums.map(v => Math.abs(v))) : 0;
      const fillFor = v => diverging
        ? _ooMapFillDiverging(maxAbs > 0 ? v / maxAbs : 0)
        : _ooMapFill(span > 0 ? (v - minV) / span : (v > 0 ? 1 : 0));
      const vlabel = (iso, v) => opts.valueLabel ? opts.valueLabel(iso, v) : `${v} ${opts.unit || ""}`.trim();

      const W = MAP_W, H = MAP_H;
      let grid = "";
      for (let lon = -180; lon <= 180; lon += 30) grid += `<line x1="${lon2x(lon)}" y1="0" x2="${lon2x(lon)}" y2="${H}" stroke="var(--border)" stroke-width="0.25"/>`;
      for (let lat = -90; lat <= 90; lat += 30) grid += `<line x1="0" y1="${lat2y(lat)}" x2="${W}" y2="${lat2y(lat)}" stroke="var(--border)" stroke-width="0.25"/>`;

      // Effective geometry: real OSM admin boundaries (opt-in) AUGMENT the coarse
      // 110m polygons by ISO code (#51). An OSM-derived shape REPLACES the coarse
      // one for that country and ADDS countries the 110m set never had (microstates),
      // so a data-bearing microstate renders a true polygon instead of a centroid
      // point. Honest: only closed OSM rings reach here; everything else is unchanged.
      const osmAreas = opts.osmAreas || null;
      let eff = geo.countries, osmUsed = 0;
      if (osmAreas) {
        eff = Object.assign({}, geo.countries);
        for (const iso in osmAreas) {
          const a = osmAreas[iso];
          if (!a || !a.rings || !a.rings.length) continue;
          eff[iso] = { name: (geo.countries[iso] && geo.countries[iso].name) || a.name || iso, rings: a.rings, osm: true };
          osmUsed++;
        }
      }
      const geoCodes = new Set(Object.keys(eff).map(s => s.toLowerCase()));
      let paths = "";
      for (const [iso, c] of Object.entries(eff)) {
        const code = iso.toLowerCase(), v = values[code];
        const has = typeof v === "number" && isFinite(v);
        const d = _ooMapPath(c.rings); if (!d) continue;
        const fill = has ? fillFor(v) : "url(#oomap-nodata)";
        const title = `${ooRegionName(code, c.name)} — ${has ? vlabel(code, v) : t("no data")}${c.osm ? " · " + t("boundary from OSM") : ""}`;
        paths += `<path d="${d}" fill="${fill}" stroke="${c.osm ? "var(--accent)" : "var(--border)"}" stroke-width="${c.osm ? "0.5" : "0.3"}" data-iso="${esc(code)}"`
          + `${opts.onCountry ? ' style="cursor:pointer"' : ""}><title>${esc(title)}</title></path>`;
      }
      // Centroid POINT fallback: areas WITH data but NO polygon (microstates).
      const pointRows = (opts.points || []).filter(p => p.lat != null && p.lon != null
        && typeof p.value === "number" && isFinite(p.value) && !geoCodes.has((p.iso2 || "").toLowerCase()));
      let pts = "";
      for (const p of pointRows) {
        const x = lon2x(p.lon).toFixed(1), y = lat2y(p.lat).toFixed(1), iso = (p.iso2 || "").toLowerCase();
        pts += `<circle cx="${x}" cy="${y}" r="2.4" fill="${fillFor(p.value)}" stroke="var(--accent)" stroke-width="0.5" `
          + `data-iso="${esc(iso)}"${opts.onCountry ? ' style="cursor:pointer"' : ""}>`
          + `<title>${esc((p.label || p.iso2 || "") + " — " + vlabel(iso, p.value) + " " + t("(shown as a point)"))}</title></circle>`;
      }
      // Mentioned-places OVERLAY (switchable, slice 4): hollow markers DISTINCT
      // from the solid centroid points, sized by article spread (raw count). A
      // different data layer (what the corpus mentions, deduced) over the fills.
      let overlayPts = "";
      if (opts.placesOn && Array.isArray(opts.overlayPoints)) {
        const ov = opts.overlayPoints.filter(p => p.lat != null && p.lon != null);
        const ovMax = Math.max(1, ...ov.map(p => +p.value || 0));
        for (const p of ov) {
          const x = lon2x(p.lon).toFixed(1), y = lat2y(p.lat).toFixed(1);
          const r = (1.3 + 3.2 * Math.sqrt((+p.value || 0) / ovMax)).toFixed(1);
          overlayPts += `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="var(--accent)" stroke-width="0.7" opacity="0.85">`
            + `<title>${esc((p.label || "") + " — " + (p.value != null ? fmtNum(p.value) + " " + t("articles") + " " : "") + t("(mentioned, deduced)"))}</title></circle>`;
        }
      }

      // Server-IP location LAYER (data-arch slice 6c): the captured server IPs,
      // geolocated OFFLINE, as filled VIOLET squares — DISTINCT from the editorial
      // source-country choropleth and from the hollow mentioned-places circles. It is
      // OUR network vantage point (CDN edge / anycast), never the publisher's origin.
      let serverPts = "";
      if (opts.serverOn && Array.isArray(opts.serverPoints)) {
        const sv = opts.serverPoints.filter(p => p.lat != null && p.lon != null);
        const svMax = Math.max(1, ...sv.map(p => +p.value || 0));
        for (const p of sv) {
          const cx = lon2x(p.lon), cy = lat2y(p.lat);
          const s = 2 + 3 * Math.sqrt((+p.value || 0) / svMax);
          serverPts += `<rect x="${(cx - s / 2).toFixed(1)}" y="${(cy - s / 2).toFixed(1)}" width="${s.toFixed(1)}" height="${s.toFixed(1)}" fill="#8b5cf6" stroke="var(--panel)" stroke-width="0.4" opacity="0.85">`
            + `<title>${esc((p.label || "") + " — " + (p.value != null ? fmtNum(p.value) + " " + t("articles") + " " : "") + t("(server IP location)"))}</title></rect>`;
        }
      }

      // Signals LAYER (slice 5a — folding the temporal map in): curated/extracted
      // EVENTS placed in space AND time, kind-coloured, filtered by the focus
      // window and faded by distance in time. Reuses the temporal map's data
      // (/api/timemap) + helpers (kindColor / TMAP_KINDS / fmtYear / fmtDate). The
      // in-map slider moves the focus moment. Confirmed = filled, future/unconfirmed
      // = a hollow/dashed ring (the temporal map's honest convention).
      let signalPts = "", sigKinds = [], sigVisible = [];
      if (opts.signalsOn && Array.isArray(opts.signals)) {
        const focus = opts.focusT, win = opts.windowY || 0;
        sigVisible = opts.signals.filter(s => s.lat != null && s.lon != null
          && typeof s.t === "number"
          && (!win || focus == null || Math.abs(s.t - focus) <= win));
        sigKinds = [...new Set(sigVisible.map(s => s.kind))];
        signalPts = sigVisible.map((s, i) => {
          const x = +lon2x(s.lon).toFixed(1), y = +lat2y(s.lat).toFixed(1);
          const dist = focus == null ? 0 : Math.abs(s.t - focus);
          const op = Math.max(0.2, 1 - (win ? dist / win : 0) * 0.8);
          // Item 2 (field-feedback A6, ruled): a hazard's radius scales with its
          // REAL magnitude (sqrt scale -- area, not radius, grows linearly with
          // magnitude, so a M9 doesn't visually swallow a M5) when one is known;
          // a GDACS non-quake alert (no magnitude) falls through to the SAME
          // honest default every other kind already uses -- never a fabricated
          // size for a fact the provider didn't state.
          const r = (s.kind === "hazard" && typeof s.magnitude === "number")
            ? Math.min(9, 2.4 + Math.sqrt(Math.max(0, s.magnitude)) * 1.2)
            : (s.confirmed ? 3 : 2.4);
          const col = kindColor(s.kind);
          // SHAPE encodes the event's CERTAINTY CLASS (field test 2026-06-19,
          // THEME-2: "deduced events as shapes"), COLOUR encodes the kind — so the
          // map reads without relying on colour alone: a corpus-extracted (deduced,
          // never-confirmed) event is a hollow DIAMOND, a scheduled/unconfirmed
          // future event a hollow TRIANGLE, a confirmed event a filled CIRCLE. The
          // shape is FIXED per event (independent of the focus slider) so sliding
          // the time window never morphs a marker.
          const cls = _ooSigClass(s);
          const ring = cls === "confirmed"
            ? `fill="${col}" fill-opacity="0.82" stroke="var(--bg)" stroke-width="0.4"`
            : `fill="transparent" stroke="${col}" stroke-width="1.1"${cls === "deduced" ? ' stroke-dasharray="1.6 1.2"' : ""}`;
          const ti = `${s.title} — ${fmtDate(s)} · ${kindLabel(s.kind)}${s.place ? " · " + s.place : ""} · ${_ooSigClassLabel(cls)}`;
          // a larger transparent hit disc keeps the whole marker clickable (the
          // temporal-map lesson: hollow rings were clickable only on the 1px edge).
          const clk = opts.onSignal ? ` data-oomap-sig="${i}" style="cursor:pointer"` : "";
          return `<g${clk} opacity="${op.toFixed(2)}">`
            + (opts.onSignal ? `<circle cx="${x}" cy="${y}" r="${(r + 3.5).toFixed(1)}" fill="transparent"></circle>` : "")
            + _ooSigMarker(cls, x, y, r, ring, esc(ti)) + `</g>`;
        }).join("");
      }

      // sr-only top list + aria summary (chart a11y pattern, PR G).
      const top = Object.keys(values).map(k => [k, values[k]]).filter(r => typeof r[1] === "number")
        .sort((a, b) => b[1] - a[1]).slice(0, 8);
      const srTop = (opts.srRows || top.map(r => (names[r[0]] || r[0].toUpperCase()) + ": " + vlabel(r[0], r[1])))
        .map(s => `<li>${esc(s)}</li>`).join("");
      const aria = opts.aria || opts.label || "map";

      // Dynamic non-overlapping country labels (THEME-2): build candidates from the
      // located areas (opts.points carry lat/lon/label/value), highest-value first.
      // The greedy declutter + the constant-on-screen font size run in
      // _ooMapLayoutLabels on every viewBox change (so labels stay readable as you
      // zoom and never overlap). Opt-in via the in-map "Labels" toggle.
      const labelCands = (opts.labelsOn && Array.isArray(opts.points))
        ? opts.points.filter(p => p.lat != null && p.lon != null && p.label)
            .map(p => ({ x: lon2x(p.lon), y: lat2y(p.lat), text: String(p.label), value: +p.value || 0 }))
            .sort((a, b) => b.value - a.value)
        : [];

      // OSM offline-region overlay (THEME-2): the bounded preview parsed by OOPBF
      // from a downloaded .osm.pbf — ways as thin polylines + nodes as faint dots,
      // both CAPPED so a dense region can't choke the SVG. Reuses the same lon2x/
      // lat2y projection (no second projection). Honest preview, never fabricated.
      let osmHtml = "";
      const osm = opts.osmOn && opts.osmGeo ? opts.osmGeo : null;
      if (osm) {
        const lines = (osm.lines || []).slice(0, 3000).map(cs => {
          const pts = cs.map(c => `${lon2x(c.lon).toFixed(1)},${lat2y(c.lat).toFixed(1)}`).join(" ");
          return `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="0.4" vector-effect="non-scaling-stroke" opacity="0.7"/>`;
        }).join("");
        const allPts = osm.points || [];
        const step = Math.max(1, Math.ceil(allPts.length / 4000));   // sample to cap rendered dots
        let dots = "";
        for (let i = 0; i < allPts.length; i += step) {
          const p = allPts[i];
          dots += `<circle cx="${lon2x(p.lon).toFixed(1)}" cy="${lat2y(p.lat).toFixed(1)}" r="0.5" fill="var(--accent)" opacity="0.55"/>`;
        }
        osmHtml = `<g id="oomap-osm">${lines}${dots}</g>`;
      }

      // Granularity + places overlay (slice 4) — finer/coarser spatial resolution,
      // also "controls inside the map". Continent = the per-country values
      // pre-aggregated by the loader; Places = the mentioned-places overlay.
      const granHtml = opts.onGranularity ? `
        <div class="oomap-gran" role="group" aria-label="${esc(t("Granularity"))}"
             style="position:absolute;bottom:8px;left:8px;display:flex;flex-wrap:wrap;gap:4px;z-index:5">
          <button class="tiny secondary" data-oomap-gran="country" aria-pressed="${opts.granularity !== "continent"}"${opts.granularity !== "continent" ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>${esc(t("Country"))}</button>
          <button class="tiny secondary" data-oomap-gran="continent" aria-pressed="${opts.granularity === "continent"}"${opts.granularity === "continent" ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>${esc(t("Continent"))}</button>
          ${opts.onPlaces ? `<button class="tiny secondary" data-oomap-places aria-pressed="${opts.placesOn ? "true" : "false"}"${opts.placesOn ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>${esc(t("Places"))}</button>` : ""}
          ${opts.onSignals ? `<button class="tiny secondary" data-oomap-signals aria-pressed="${opts.signalsOn ? "true" : "false"}"${opts.signalsOn ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>${esc(t("Signals"))}</button>` : ""}
          ${opts.onServer ? `<button class="tiny secondary" data-oomap-server aria-pressed="${opts.serverOn ? "true" : "false"}"${opts.serverOn ? ' style="border-color:var(--accent);color:var(--accent)"' : ""} title="${esc(t("Server IP locations — offline geo; a CDN edge / anycast host, not the publisher's origin"))}">${esc(t("Server IPs"))}</button>` : ""}
          ${opts.onLabels ? `<button class="tiny secondary" data-oomap-labels aria-pressed="${opts.labelsOn ? "true" : "false"}"${opts.labelsOn ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>${esc(t("Labels"))}</button>` : ""}
          ${opts.onOsm ? `<button class="tiny secondary" data-oomap-osm aria-pressed="${opts.osmOn ? "true" : "false"}"${opts.osmOn ? ' style="border-color:var(--accent);color:var(--accent)"' : ""} title="${esc(t("Overlay a downloaded offline-map region (preview)"))}">${esc(t("OSM"))}</button>` : ""}
        </div>` : "";
      // In-map TIME slider (slice 5a) — appears above the bottom-left controls when
      // the Signals layer is on; sweeps the focus moment (antiquity -> near future).
      // A Linear/Log toggle (batch F item 1) chooses the position->year mapping; the
      // labelled tick strip names the year at 0/¼/½/¾/1 so the scale is never a hidden
      // warp (log ticks bunch at the old end, linear ticks are evenly spaced).
      const _tsc = opts.timeScale === "log" ? "log" : opts.timeScale;   // may be undefined when no toggle
      const scaleBtns = opts.onTimeScale ? `<span class="oomap-tscale" role="group" aria-label="${esc(t("Time scale"))}" style="display:inline-flex;gap:3px">
            <button class="tiny secondary" data-oomap-tscale="linear" aria-pressed="${_tsc !== "log"}"${_tsc !== "log" ? ' style="border-color:var(--accent);color:var(--accent)"' : ""} title="${esc(t("Even year-by-year sweep"))}">${esc(t("Linear"))}</button>
            <button class="tiny secondary" data-oomap-tscale="log" aria-pressed="${_tsc === "log"}"${_tsc === "log" ? ' style="border-color:var(--accent);color:var(--accent)"' : ""} title="${esc(t("Compress antiquity so recent years — where most events are — get more of the slider"))}">${esc(t("Log"))}</button>
          </span>` : "";
      const tickStrip = (Array.isArray(opts.focusTicks) && opts.focusTicks.length) ? `<div style="position:relative;height:11px;margin-top:1px">
          ${opts.focusTicks.map(tk => {
            const pos = tk.pos <= 0 ? 'left:0;transform:none;text-align:left'
              : tk.pos >= 1 ? 'right:0;left:auto;transform:none;text-align:right'
              : `left:${(tk.pos * 100).toFixed(1)}%;transform:translateX(-50%)`;
            return `<span style="position:absolute;${pos};font-size:8.5px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap">${esc(tk.label)}</span>`;
          }).join("")}
        </div>` : "";
      const sliderHtml = opts.signalsOn ? `
        <div class="oomap-time" style="position:absolute;bottom:36px;left:8px;right:8px;z-index:5;display:flex;flex-direction:column;gap:1px;background:color-mix(in srgb, var(--panel) 82%, transparent);padding:3px 8px;border-radius:6px">
          <div style="display:flex;align-items:center;gap:8px">
            <input type="range" data-oomap-focus min="0" max="1000" value="${opts.focusSlider != null ? opts.focusSlider : 1000}" step="1" style="flex:1" aria-label="${esc(t("Moment in focus"))}">
            <strong style="font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap">${esc(opts.focusLabel || "")}</strong>
            ${scaleBtns}
          </div>
          ${tickStrip}
        </div>` : "";

      // In-map dimension picker (the "controls inside the map" convention) — the
      // active dimension paints the choropleth; switching re-colours it.
      const pickerHtml = (opts.dimensions && opts.dimensions.length > 1) ? `
        <div class="oomap-dims" role="group" aria-label="${esc(t("Map dimension"))}"
             style="position:absolute;top:8px;left:8px;display:flex;flex-wrap:wrap;gap:4px;z-index:5;max-width:62%">
          ${opts.dimensions.map(dm => `<button class="tiny secondary" data-oomap-dim="${esc(dm.id)}" aria-pressed="${dm.id === opts.activeDim ? "true" : "false"}"`
            + `${dm.id === opts.activeDim ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>${esc(dm.label)}</button>`).join("")}
        </div>` : "";
      // Legend: a sequential ramp for counts, a diverging red..panel..green ramp
      // for signed data (the 0 sits at the centre stop).
      const legendBar = diverging
        ? `<span class="muted">${esc(fmtNum(minV))}</span>
           <span style="width:110px;height:10px;border:1px solid var(--border);border-radius:3px;background:linear-gradient(to right, ${_ooMapFillDiverging(-1)}, ${_ooMapFillDiverging(0)}, ${_ooMapFillDiverging(1)})"></span>
           <span class="muted">${esc(fmtNum(maxV))}${opts.unit ? " " + esc(opts.unit) : ""}</span>`
        : `<span class="muted">${esc(fmtNum(minV))}</span>
           <span style="width:90px;height:10px;border:1px solid var(--border);border-radius:3px;background:linear-gradient(to right, ${_ooMapFill(0)}, ${_ooMapFill(1)})"></span>
           <span class="muted">${esc(fmtNum(maxV))}${opts.unit ? " " + esc(opts.unit) : ""}</span>`;

      host.innerHTML = `<div class="oomap-wrap" style="position:relative">
        <svg id="oo-choro" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(aria)}"
             style="display:block;background:var(--panel2);border:1px solid var(--border);border-radius:8px;cursor:grab;aspect-ratio:${W} / ${H}">
          <defs><pattern id="oomap-nodata" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--panel2)"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--border)" stroke-width="1"/></pattern></defs>
          ${grid}${paths}${pts}${overlayPts}${serverPts}${signalPts}${osmHtml}
          <g id="oomap-labels"></g>
        </svg>
        <div class="oomap-controls" style="position:absolute;top:8px;right:8px;display:flex;flex-direction:column;gap:4px;z-index:5">
          <button class="tiny secondary" data-oomap="in" title="${esc(t("Zoom in"))}">＋</button>
          <button class="tiny secondary" data-oomap="out" title="${esc(t("Zoom out"))}">－</button>
          <button class="tiny secondary" data-oomap="reset" title="${esc(t("Reset view"))}">⟲</button>
          <button class="tiny secondary" data-oomap="big" title="${esc(t("Enlarge the map"))}">⛶</button>
        </div>
        ${pickerHtml}${granHtml}${sliderHtml}
        <ul class="sr-only">${srTop}</ul>
      </div>
      <div class="oomap-legend" style="margin-top:8px;display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:12px">
        ${opts.label ? `<span>${esc(opts.label)}</span>` : ""}
        <span style="display:inline-flex;align-items:center;gap:6px">${legendBar}</span>
        <span style="display:inline-flex;align-items:center;gap:5px">
          <span style="width:14px;height:10px;border:1px solid var(--border);background:repeating-linear-gradient(45deg,var(--panel2),var(--panel2) 2px,var(--border) 2px,var(--border) 3px)"></span>
          ${esc(t("no data"))}</span>
        ${pointRows.length ? `<span class="muted">○ ${esc(t("small areas shown as points"))}</span>` : ""}
        ${opts.placesOn ? `<span class="muted">○ ${esc(t("mentioned places (deduced)"))}</span>` : ""}
        ${opts.serverOn ? `<span class="muted" style="display:inline-flex;align-items:center;gap:5px"><span style="width:9px;height:9px;background:#8b5cf6"></span>${esc(t("server IP location (CDN edge / anycast)"))}</span>` : ""}
        ${opts.serverOn && opts.serverMeta ? `<span class="muted" title="${esc(t("Many sources sharing one host/ASN — a shape to investigate, never a verdict."))}">${esc(opts.serverMeta)}</span>` : ""}
        ${opts.serverOn ? `<span class="muted">${esc(t("IP Geolocation by DB-IP"))} · <a href="https://db-ip.com" target="_blank" rel="noopener">db-ip.com</a> · CC BY 4.0</span>` : ""}
        ${opts.signalsOn ? sigKinds.map(k => `<span style="display:inline-flex;align-items:center;gap:4px"><span style="width:9px;height:9px;border-radius:50%;background:${kindColor(k)}"></span>${esc(kindLabel(k))}</span>`).join("") : ""}
        ${opts.signalsOn ? `<span class="muted" style="display:inline-flex;align-items:center;gap:6px" title="${esc(t("Shape = certainty; colour = kind."))}">● ${esc(t("confirmed"))} · ▲ ${esc(t("scheduled"))} · ◆ ${esc(t("deduced"))}</span>` : ""}
        ${osm ? `<span class="muted" title="${esc(t("Bounded preview from a downloaded .osm.pbf — not the full region; no network."))}">${esc(t("offline OSM"))}: ${(osm.points || []).length} ${esc(t("nodes"))} · ${(osm.lines || []).length} ${esc(t("ways"))}${osm.truncated ? " · " + esc(t("preview")) : ""}${osm.areaCount ? " · " + osm.areaCount + " " + esc(t("country boundaries")) : ""}</span>` : ""}
      </div>
      ${opts.method ? `<div class="hint" style="margin-top:4px">${esc(opts.method)}</div>` : ""}
      ${opts.caveat ? `<div class="card-caveat" style="margin-top:4px">${esc(opts.caveat)}</div>` : ""}`;
      host._ooSigVisible = sigVisible;             // for signal click-to-detail resolution
      host._ooLabels = labelCands;                 // for the dynamic-label declutter (re-laid-out on zoom)
      _wireOoMap(host, opts);
      _ooMapLayoutLabels(host, { x: 0, y: 0, w: W, h: H });   // initial layout (world view)
    }
    // Greedy non-overlapping label declutter (THEME-2), re-run on every viewBox
    // change so labels stay constant-size on screen, never overlap, and reveal more
    // detail as you zoom in. Highest-value countries win ties (placed first).
    function _ooMapLayoutLabels(host, vb) {
      const g = host && host.querySelector("#oomap-labels"); if (!g) return;
      const cands = host._ooLabels || [];
      if (!cands.length) { g.innerHTML = ""; return; }
      const fs = Math.max(2.4, 11 * (vb.w / MAP_W));   // ≈ constant on-screen size as the viewBox zooms
      const placed = [], pad = fs * 0.25;
      let out = "";
      for (const c of cands) {
        if (c.x < vb.x || c.x > vb.x + vb.w || c.y < vb.y || c.y > vb.y + vb.h) continue;  // off the visible viewBox
        const w = c.text.length * fs * 0.55 + pad, h = fs * 1.1;
        const box = { x: c.x - w / 2, y: c.y - h / 2, w, h };
        if (placed.some(p => !(box.x + box.w < p.x || box.x > p.x + p.w || box.y + box.h < p.y || box.y > p.y + p.h))) continue;
        placed.push(box);
        out += `<text x="${c.x.toFixed(1)}" y="${c.y.toFixed(1)}" font-size="${fs.toFixed(2)}" text-anchor="middle" `
          + `dominant-baseline="middle" fill="var(--fg)" stroke="var(--panel2)" stroke-width="${(fs * 0.18).toFixed(2)}" `
          + `paint-order="stroke" style="pointer-events:none">${esc(c.text)}</text>`;
        if (placed.length >= 80) break;   // bound the work
      }
      g.innerHTML = out;
    }

    // Instance-local viewBox zoom/pan (the Google-Maps "controls inside the map"
    // convention). State lives in a closure per render -- no module globals, so
    // re-renders cannot accumulate listeners (drag listeners are added on
    // mousedown and removed on mouseup).
    function _wireOoMap(host, opts) {
      const svg = host.querySelector("#oo-choro"); if (!svg) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const W = MAP_W, H = MAP_H;
      // Reset the ⛶ glyph/title when fullscreen exits (Esc or the button). Wired once.
      // worldmap-fullscreen-hides-legend-caveat (P1): fullscreen used to target
      // .oomap-wrap specifically (the SVG + in-map controls only) -- but
      // .oomap-legend, the method hint, and the caveat div are SIBLINGS of
      // .oomap-wrap, not descendants, so the browser natively hid all three the
      // moment fullscreen engaged (a fullscreen element shows only its own
      // subtree). `host` (the caller's dedicated map container, e.g.
      // #oo-coverage-map) already wraps EVERYTHING this render produces --
      // .oomap-wrap, .oomap-legend, the method hint, and the caveat -- and
      // nothing unrelated, so targeting it instead shows the whole map
      // including its caveat while fullscreen. Verified this does not depend on
      // .oomap-wrap being the exact fullscreen root: the viewBox zoom/pan math
      // operates purely on the SVG's own viewBox attribute (ancestor-
      // independent), and the CSS `.mm-big` fallback class is a generic
      // fixed-position overlay that works on any element.
      if (!host._ooFsWired) {
        host._ooFsWired = true;
        document.addEventListener("fullscreenchange", () => {
          const fsBtn = host.querySelector('[data-oomap="big"]'); if (!fsBtn) return;
          const on = document.fullscreenElement === host;
          fsBtn.textContent = on ? "🗗" : "⛶";
          fsBtn.title = on ? t("Exit fullscreen") : t("Enlarge the map");
        });
      }
      let vb = { x: 0, y: 0, w: W, h: H };
      const apply = () => {
        svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
        // Re-declutter labels for the new viewBox (THEME-2: dynamic, constant-size,
        // non-overlapping — more reveal as you zoom). No-op when labels are off.
        if (host._ooLabels && host._ooLabels.length) _ooMapLayoutLabels(host, vb);
      };
      const zoom = (f, ax, ay) => {
        const cx = ax != null ? ax : vb.x + vb.w / 2, cy = ay != null ? ay : vb.y + vb.h / 2;
        const w = Math.min(W, Math.max(W * 0.04, vb.w * f)), sc = w / vb.w;
        vb.x = cx - (cx - vb.x) * sc; vb.y = cy - (cy - vb.y) * sc; vb.w = w; vb.h *= sc; apply();
      };
      host.querySelectorAll("[data-oomap]").forEach(b => b.addEventListener("click", () => {
        const a = b.dataset.oomap;
        if (a === "in") zoom(0.7); else if (a === "out") zoom(1.4);
        else if (a === "big") {
          // TRUE fullscreen (field test 2026-06-19 #12), with a CSS fallback for
          // browsers without the API. The in-map ⛶ stays the visible exit control
          // (clicking it again exits); Esc also exits natively. Targets `host`
          // itself (see the worldmap-fullscreen-hides-legend-caveat comment above)
          // so the legend/method/caveat stay visible in fullscreen too.
          try {
            if (document.fullscreenElement === host) { document.exitFullscreen(); }
            else if (host.requestFullscreen) {
              host.requestFullscreen().then(() => { b.title = t("Exit fullscreen"); b.textContent = "🗗"; })
                .catch(() => host.classList.toggle("mm-big"));
            } else { host.classList.toggle("mm-big"); }
          } catch (_e) { host.classList.toggle("mm-big"); }
        }
        else { vb = { x: 0, y: 0, w: W, h: H }; apply(); }
      }));
      if (opts && opts.onDimension) host.querySelectorAll("[data-oomap-dim]").forEach(b =>
        b.addEventListener("click", () => opts.onDimension(b.dataset.oomapDim)));
      if (opts && opts.onGranularity) host.querySelectorAll("[data-oomap-gran]").forEach(b =>
        b.addEventListener("click", () => opts.onGranularity(b.dataset.oomapGran)));
      if (opts && opts.onPlaces) { const pb = host.querySelector("[data-oomap-places]"); if (pb) pb.addEventListener("click", () => opts.onPlaces()); }
      if (opts && opts.onSignals) { const sb = host.querySelector("[data-oomap-signals]"); if (sb) sb.addEventListener("click", () => opts.onSignals()); }
      if (opts && opts.onServer) { const vb = host.querySelector("[data-oomap-server]"); if (vb) vb.addEventListener("click", () => opts.onServer()); }
      if (opts && opts.onLabels) { const lb = host.querySelector("[data-oomap-labels]"); if (lb) lb.addEventListener("click", () => opts.onLabels()); }
      if (opts && opts.onOsm) { const ob = host.querySelector("[data-oomap-osm]"); if (ob) ob.addEventListener("click", () => opts.onOsm()); }
      if (opts && opts.onFocus) { const fs = host.querySelector("[data-oomap-focus]"); if (fs) fs.addEventListener("input", () => opts.onFocus(+fs.value)); }
      if (opts && opts.onTimeScale) host.querySelectorAll("[data-oomap-tscale]").forEach(b =>
        b.addEventListener("click", () => opts.onTimeScale(b.dataset.oomapTscale)));
      if (opts && opts.onSignal) host.querySelectorAll("[data-oomap-sig]").forEach(g =>
        g.addEventListener("click", () => { const s = (host._ooSigVisible || [])[+g.dataset.oomapSig]; if (s) opts.onSignal(s, host._ooSigVisible || []); }));
      svg.addEventListener("wheel", e => {
        e.preventDefault();
        const m = svg.getScreenCTM().inverse(), p = svg.createSVGPoint();
        p.x = e.clientX; p.y = e.clientY; const qp = p.matrixTransform(m);
        zoom(Math.exp(e.deltaY * 0.0015), qp.x, qp.y);
      }, { passive: false });
      let drag = false, sx = 0, sy = 0;
      svg.addEventListener("mousedown", e => {
        drag = true; sx = e.clientX; sy = e.clientY; svg.style.cursor = "grabbing";
        const mv = ev => {
          if (!drag) return; const r = svg.getBoundingClientRect();
          vb.x -= (ev.clientX - sx) * vb.w / r.width; vb.y -= (ev.clientY - sy) * vb.h / r.height;
          sx = ev.clientX; sy = ev.clientY; apply();
        };
        const up = () => { drag = false; svg.style.cursor = "grab"; window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); };
        window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
      });
      if (opts && opts.onCountry) svg.addEventListener("click", e => {
        if (drag) return; const el = e.target.closest("[data-iso]");
        if (el && el.dataset.iso) opts.onCountry(el.dataset.iso);
      });
    }

    // Map-tab choropleth: per-country coverage with a DIMENSION PICKER (slice 3).
    // The endpoint returns every measure per country in ONE payload, so switching
    // dimension is instant (no re-fetch) — the picker just re-colours the map.
    let _ooMapPayload = null, _ooMapDim = "sources", _ooMapGran = "country", _ooMapPlacesOn = false, _ooMapWhere = null, _ooMapLabelsOn = false;
    let _ooMapOsmOn = false, _ooMapOsmGeo = null, _ooMapOsmLoading = false;   // in-browser .pbf overlay (THEME-2)
    // Signals layer (slice 5a): lazily-fetched space-time events + the focus slider.
    // _ooMapTimeScale = how the slider position maps to a focus YEAR (batch F item 1):
    // "log" (default, unchanged) compresses antiquity so the recent end — where most
    // events are — gets most of the travel; "linear" is an even year-by-year sweep.
    // NEITHER is a hidden warp: the focus-year label + the tick strip name the actual
    // year at every position, so the compression is always explicit.
    let _ooMapSignalsOn = false, _ooMapSignals = null, _ooMapFocusSlider = 1000, _ooMapFocusRAF = 0, _ooMapTimeScale = "log";
    // Server-IP location layer (data-arch slice 6c): captured server IPs geolocated
    // OFFLINE, DISTINCT from the editorial Source.country choropleth. Lazily fetched.
    let _ooMapServerOn = false, _ooMapServerLoc = null;
    // World-map LENS strip (field-test Item 6): the map's lenses become first-class
    // ooSubtabs. Each lens PRESETS the existing in-map layer state (a Coverage
    // choropleth vs the Stories/Places/Server overlays); the in-map toggles still
    // fine-tune within a lens (they can COMBINE layers). The lens does not add a map
    // engine — it drives the state _renderOoMapDim already reads. "coverage" is the
    // default (always-available, no extra fetch); Stories is one click away.
    let _ooMapLens = "coverage", _ooMapLensTabs = null;
    // Story-type (kind) filter under the Stories lens: null = all kinds; a kind string
    // narrows the plotted signals to that story type. Client-side over already-fetched
    // signals (no new endpoint). Counts only, deduced — never a verdict.
    let _ooMapStoryKind = null;
    // Hazard lens state (2026-08-01 ruling 4). "Major only" starts ON so the map
    // opens on the events the strip is about; it is a DEFAULT LENS the user can
    // clear in one click, never an exclusion — the bar states that in words.
    let _ooMapHazMajorOnly = true, _ooMapHazType = null;
    const OOMAP_HAZ_MIN_MAGNITUDE = 6.0;   // mirrors alerts.DEFAULT_MIN_MAGNITUDE
    // A map signal is "major" on the SAME provider-declared facts the alert layer
    // uses: the provider's own orange/red level, or its measured magnitude.
    function _hazardSignalIsMajor(s) {
      const sev = String(s.severity || "").toLowerCase();
      if (sev === "watch" || sev === "urgent") return true;
      const m = Number(s.magnitude);
      if (isFinite(m) && s.magnitude != null && m >= OOMAP_HAZ_MIN_MAGNITUDE) return true;
      return sev === "strong" || sev === "major";
    }
    // Preset the map into a named lens: toggle the layer flags, lazily fetch that
    // lens's data (reusing the SAME endpoints the in-map toggles use — no new fetch),
    // then re-render. Fired by the ooSubtabs strip (incl. its {initial}).
    async function selectOoMapLens(key) {
      _ooMapLens = key;
      _ooMapSignalsOn = (key === "stories");
      _ooMapPlacesOn = (key === "places");
      _ooMapServerOn = (key === "servers");
      if (key !== "stories") _ooMapStoryKind = null;   // don't leak a kind filter across lenses
      try {
        if (key === "stories" && _ooMapSignals == null) {
          const d = await api("/api/timemap?limit=4000&hazards=true");
          _ooMapSignals = (d.signals || []).filter(s => typeof s.t === "number" && s.lat != null && s.lon != null);
        } else if (key === "places" && !_ooMapWhere) {
          _ooMapWhere = await api("/api/insights/where?limit=400");
        } else if (key === "servers" && !_ooMapServerLoc) {
          _ooMapServerLoc = await api("/api/insights/server-locations");
        }
      } catch (_e) {
        // Degrade honestly: an empty layer + the empty state, never a crash.
        if (key === "stories" && _ooMapSignals == null) _ooMapSignals = [];
        if (key === "places" && !_ooMapWhere) _ooMapWhere = { places: [] };
        if (key === "servers" && !_ooMapServerLoc) _ooMapServerLoc = { countries: [], clusters: [], unavailable: {} };
      }
      _renderOoMapLensDesc();
      _renderOoMapLensBar();
      if (_ooMapPayload) _renderOoMapDim();
    }
    // A one-line, honest description of the active lens (translated).
    function _renderOoMapLensDesc() {
      const el = $("oomap-lens-desc"); if (!el) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      const d = {
        coverage: t("Countries shaded by a measured dimension of your corpus — no data stays un-shaded, never zero. No score."),
        stories: t("Location-based events extracted from your corpus, by type. Deduced, never a verdict — click a place to open its corpus."),
        places: t("The places your articles mention — what the corpus is about. Deduced from text, never confirmed."),
        servers: t("Where the servers we reached are located (offline geo) — a CDN edge / anycast host, not the publisher's origin; unavailable over Tor."),
      };
      el.textContent = d[_ooMapLens] || "";
    }
    // Story-type chips under the Stories lens (field-test Item 6 incitement UI): the
    // event KINDS present in the corpus with a COUNT each, clickable to filter the
    // plotted signals to one story type. Counts only, deduced — "142 climate · 88
    // conflict" is the invitation to click in, never a ranking/score. Empty otherwise.
    function _renderOoMapLensBar() {
      const bar = $("oomap-lens-bar"); if (!bar) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      if (_ooMapLens !== "stories") { bar.innerHTML = ""; return; }
      const sig = Array.isArray(_ooMapSignals) ? _ooMapSignals : [];
      if (!sig.length) {
        bar.innerHTML = `<div class="muted">${esc(t("No located events in your corpus yet — collect more, or explore the Coverage lens."))}</div>`;
        return;
      }
      const counts = {};
      sig.forEach(s => { const k = s.kind || "article"; counts[k] = (counts[k] || 0) + 1; });
      const kinds = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
      const chip = (key, label, n, on, dot) => `<button type="button" class="tiny secondary" data-story-kind="${esc(key)}" aria-pressed="${on ? "true" : "false"}"`
        + `${on ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>`
        + (dot ? `<span style="width:8px;height:8px;border-radius:50%;background:${dot};display:inline-block;margin-right:4px;vertical-align:middle"></span>` : "")
        + `${esc(label)}${n != null ? ` <span class="muted">${esc(fmtNum(n))}</span>` : ""}</button>`;
      const allOn = _ooMapStoryKind == null;
      const chips = [chip("__all", t("All stories"), sig.length, allOn, null)]
        .concat(kinds.map(k => chip(k, kindLabel(k), counts[k], _ooMapStoryKind === k, kindColor(k))));
      // Hazard row (ruling 4): a "Major only" default lens + a hazard-TYPE filter,
      // shown only when there are hazard signals to filter. Every count is real,
      // and the caveat states that the default hides nothing permanently.
      const haz = sig.filter(s => (s.kind || "") === "hazard");
      let hazRow = "";
      if (haz.length) {
        const majorN = haz.filter(_hazardSignalIsMajor).length;
        const types = {};
        haz.forEach(s => { const k = String(s.hazard_type || "").toLowerCase(); if (k) types[k] = (types[k] || 0) + 1; });
        const tkeys = Object.keys(types).sort((a, b) => types[b] - types[a]);
        const majorChip = `<button type="button" class="tiny secondary" id="oomap-haz-major"`
          + ` aria-pressed="${_ooMapHazMajorOnly ? "true" : "false"}"`
          + `${_ooMapHazMajorOnly ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>`
          + `${esc(t("Major only"))} <span class="muted">${esc(fmtNum(majorN))}/${esc(fmtNum(haz.length))}</span></button>`;
        const typeChips = [`<button type="button" class="tiny secondary" data-haz-type="__all"`
          + ` aria-pressed="${_ooMapHazType == null ? "true" : "false"}"`
          + `${_ooMapHazType == null ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>`
          + `${esc(t("All hazard types"))}</button>`]
          .concat(tkeys.map(k => `<button type="button" class="tiny secondary" data-haz-type="${esc(k)}"`
            + ` aria-pressed="${_ooMapHazType === k ? "true" : "false"}"`
            + `${_ooMapHazType === k ? ' style="border-color:var(--accent);color:var(--accent)"' : ""}>`
            + `${esc(hazardTypeLabel(k))} <span class="muted">${esc(fmtNum(types[k]))}</span></button>`));
        hazRow = `<div style="display:flex;flex-wrap:wrap;gap:5px;align-items:center;margin-top:5px">
            <span class="muted" style="font-size:12px">${esc(t("Hazards"))}:</span>${majorChip}${typeChips.join("")}
          </div>
          <div class="card-caveat" style="margin-top:4px">${esc(t("“Major only” is a default lens, not an exclusion: it shows provider orange/red alerts and magnitude M6+ first. Click it off to see every hazard the snapshot holds. A magnitude is the provider's measurement of size, never a statement about consequences."))}</div>`;
      }
      bar.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:5px;align-items:center">
          <span class="muted" style="font-size:12px">${esc(t("Story types"))}:</span>${chips.join("")}
        </div>
        <div class="card-caveat" style="margin-top:5px">${esc(t("Story types are deduced from your corpus by event kind — counts only, never a verdict or ranking."))}</div>${hazRow}`;
      bar.querySelectorAll("[data-story-kind]").forEach(b => b.addEventListener("click", () => {
        const k = b.dataset.storyKind;
        _ooMapStoryKind = (k === "__all") ? null : k;
        _renderOoMapLensBar();
        if (_ooMapPayload) _renderOoMapDim();
      }));
      const majorBtn = bar.querySelector("#oomap-haz-major");
      if (majorBtn) majorBtn.addEventListener("click", () => {
        _ooMapHazMajorOnly = !_ooMapHazMajorOnly;
        _renderOoMapLensBar();
        if (_ooMapPayload) _renderOoMapDim();
      });
      bar.querySelectorAll("[data-haz-type]").forEach(b => b.addEventListener("click", () => {
        const k = b.dataset.hazType;
        _ooMapHazType = (k === "__all") ? null : k;
        _renderOoMapLensBar();
        if (_ooMapPayload) _renderOoMapDim();
      }));
    }
    // Aggregate the per-country values into CONTINENTS (slice 4): a SUM for counts,
    // a sentiment_n-WEIGHTED mean for tone (the honest cross-country average).
    function _ooMapContinentAgg(rows, dim) {
      const acc = {};
      rows.forEach(r => {
        const c = r.continent; if (!c) return;
        const v = r[dim.id]; if (v == null || !isFinite(v)) return;
        if (!acc[c]) acc[c] = { sum: 0, wsum: 0, wn: 0 };
        if (dim.id === "sentiment") { const n = r.sentiment_n || 0; acc[c].wsum += v * n; acc[c].wn += n; }
        else acc[c].sum += v;
      });
      const out = {};
      Object.keys(acc).forEach(c => {
        out[c] = dim.id === "sentiment"
          ? (acc[c].wn > 0 ? { value: acc[c].wsum / acc[c].wn, n: acc[c].wn } : null)
          : { value: acc[c].sum, n: null };
      });
      return out;
    }
    function _ooMapDims() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      return [
        { id: "sources", label: t("Sources"), unit: t("sources"), scale: "sequential",
          caveat: t("Catalogued sources based in each country — counts only, no score.") },
        { id: "articles", label: t("Articles"), unit: t("articles"), scale: "sequential",
          caveat: t("Articles collected from sources in each country — counts only, no score.") },
        { id: "keywords", label: t("Keyword mentions"), unit: t("mentions"), scale: "sequential",
          caveat: t("Keyword mentions in articles from sources in each country — counts only, no score.") },
        { id: "sentiment", label: t("Mean tone"), unit: t("tone"), scale: "diverging",
          caveat: t("Mean article tone (VADER) — English-lexicon only, unreliable for other languages; only English articles are scored. Deduced, never a verdict.") },
      ];
    }
    async function _renderOoMapDim() {
      const host = $("oo-coverage-map"); if (!host || !_ooMapPayload) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      const dims = _ooMapDims();
      const dim = dims.find(d => d.id === _ooMapDim) || dims[0];
      const rows = _ooMapPayload.by_country || [];
      const continentMode = _ooMapGran === "continent";
      const contAgg = continentMode ? _ooMapContinentAgg(rows, dim) : null;
      const values = {}, names = {}, points = [], rowBy = {};
      rows.forEach(r => {
        names[r.country] = ooRegionName(r.country, r.name); rowBy[r.country] = r;
        let v;
        if (continentMode) { const ca = r.continent && contAgg[r.continent]; if (!ca) return; v = ca.value; }
        else v = r[dim.id];
        if (v != null && isFinite(v)) {
          values[r.country] = v;
          if (r.lat != null && r.lon != null) points.push({ iso2: r.country, lat: r.lat, lon: r.lon, value: v, label: continentMode ? t(r.continent) : names[r.country] });
        }
      });
      const nWith = Object.keys(values).length;
      // 'unlocated' is data from sources WITH NO country (only the count dims).
      const unloc = dim.id === "sentiment" ? 0 : ((_ooMapPayload.unlocated && _ooMapPayload.unlocated[dim.id]) || 0);
      const aria = continentMode
        ? `${dim.label} — ${t("by continent")}.`
        : `${dim.label} — ${nWith} ${t("countries with data")}.`;
      let caveat = dim.caveat
        + (unloc ? `  ${unloc} ${dim.unit} ${t("with no country — counted, not mapped.")}` : "");
      if (_ooMapPlacesOn) caveat += `  ${t("Mentioned places: deduced from text, never confirmed.")}`;
      // Server-IP layer (slice 6c): offline-geolocated captured server IPs, distinct
      // from the editorial source-country choropleth; the endpoint's own caveat travels.
      const serverPoints = (_ooMapServerOn && _ooMapServerLoc && Array.isArray(_ooMapServerLoc.countries))
        ? _ooMapServerLoc.countries.filter(c => c.lat != null && c.lon != null)
            .map(c => ({ lat: c.lat, lon: c.lon, value: c.articles,
                         label: (names[c.country] || (c.country || "").toUpperCase()) })) : [];
      let serverMeta = "";
      if (_ooMapServerOn && _ooMapServerLoc) {
        caveat += `  ${_ooMapServerLoc.caveat || t("Server location is our vantage point (CDN edge / anycast), not the publisher's origin; unavailable over Tor.")}`;
        const nClusters = (_ooMapServerLoc.clusters || []).length;
        const tor = (_ooMapServerLoc.unavailable || {}).tor_or_proxy || 0;
        const bits = [];
        if (nClusters) bits.push(`${nClusters} ${t("shared-host clusters")}`);
        if (tor) bits.push(`${fmtNum(tor)} ${t("unavailable (Tor/proxy)")}`);
        serverMeta = bits.join(" · ");
      }
      const fmtCount = v => dim.id === "sentiment" ? (v >= 0 ? "+" : "") + fmtNum(v, 2) : `${fmtNum(v)} ${dim.unit}`;
      const fmtV = (iso, v) => continentMode
        ? `${t((rowBy[iso] || {}).continent || "")} — ${fmtCount(v)}`
        : (dim.id === "sentiment"
            ? `${fmtCount(v)} · ${t("n=")}${(rowBy[iso] || {}).sentiment_n || 0}`
            : fmtCount(v));
      const srRows = continentMode
        ? Object.keys(contAgg).filter(c => contAgg[c]).sort((a, b) => contAgg[b].value - contAgg[a].value)
            .map(c => `${t(c)}: ${fmtCount(contAgg[c].value)}`)
        : undefined;
      const overlayPoints = (_ooMapPlacesOn && _ooMapWhere && Array.isArray(_ooMapWhere.places))
        ? _ooMapWhere.places.map(p => ({ lat: p.lat, lon: p.lon, value: p.articles, label: p.name })) : [];
      // Signals layer: derive the time span from the plottable signals, map the
      // slider position to a focus YEAR, and use an adaptive window (~1/12 of the
      // span) so the slider sweeps meaningfully whatever the corpus's time range.
      let sig = _ooMapSignalsOn && Array.isArray(_ooMapSignals) ? _ooMapSignals : [];
      // Story-lens (field-test Item 6): narrow the plotted signals to one story type
      // when a kind chip is selected. Client-side over the already-fetched signals.
      if (sig.length && _ooMapStoryKind) sig = sig.filter(s => (s.kind || "article") === _ooMapStoryKind);
      // Hazard filters (2026-08-01 ruling 4). "Major only" is ON BY DEFAULT — a
      // DEFAULT LENS, not an exclusion: one click restores full recall, and the
      // bar says so. It narrows ONLY hazard signals; every other story kind is
      // untouched. The hazard-TYPE filter is the same grammar one level down.
      if (sig.length && _ooMapHazMajorOnly) {
        sig = sig.filter(s => (s.kind || "") !== "hazard" || _hazardSignalIsMajor(s));
      }
      if (sig.length && _ooMapHazType) {
        sig = sig.filter(s => (s.kind || "") !== "hazard"
          || String(s.hazard_type || "").toLowerCase() === _ooMapHazType);
      }
      let focusT = null, windowY = 0, focusSlider = _ooMapFocusSlider, focusLabel = "", focusTicks = [];
      if (sig.length) {
        const ts = sig.map(s => s.t);
        const tmin = Math.min(...ts), tmax = Math.max(...ts), spanY = tmax - tmin;
        windowY = Math.max(5, spanY / 12);
        // Time slider (field test 2026-06-19 #14: "more recent events than medieval").
        // Map slider position -> AGE (years before the most recent). LOG compresses
        // antiquity so the recent end gets most of the travel (fine resolution) while
        // antiquity compresses; LINEAR (batch F item 1) is an even year-by-year sweep.
        // NEITHER is a hidden warp: the focus YEAR label below AND the tick strip name
        // the actual year at each slider position, so the compression is explicit.
        const _LOGB = 10;
        const ageAt = (frac) => spanY <= 0 ? 0
          : (_ooMapTimeScale === "linear"
              ? spanY * (1 - frac)
              : spanY * (Math.pow(_LOGB, 1 - frac) - 1) / (_LOGB - 1));
        const yearAt = (frac) => tmax - ageAt(frac);
        focusT = yearAt(focusSlider / 1000);   // 0 = oldest, 1 = most recent
        focusLabel = (typeof fmtYear === "function") ? fmtYear(focusT) : String(Math.round(focusT));
        // Honest labelled ticks: the year at 0/.25/.5/.75/1 — non-uniform in log
        // (compressed at the old end), uniform in linear — so the warp is VISIBLE.
        focusTicks = [0, 0.25, 0.5, 0.75, 1].map(frac => ({
          pos: frac,
          label: (typeof fmtYear === "function") ? fmtYear(yearAt(frac)) : String(Math.round(yearAt(frac))),
        }));
      }
      await ooMap(host, {
        values, names, points, aria, srRows,
        scale: dim.scale, label: dim.label, unit: dim.unit,
        method: _ooMapPayload.method || "", caveat,
        dimensions: dims.map(d => ({ id: d.id, label: d.label })), activeDim: dim.id,
        onDimension: id => { _ooMapDim = id; _renderOoMapDim(); },
        granularity: _ooMapGran,
        onGranularity: g => { _ooMapGran = (g === "continent" ? "continent" : "country"); _renderOoMapDim(); },
        placesOn: _ooMapPlacesOn, overlayPoints,
        onPlaces: async () => {
          _ooMapPlacesOn = !_ooMapPlacesOn;
          if (_ooMapPlacesOn && !_ooMapWhere) {
            try { _ooMapWhere = await api("/api/insights/where?limit=400"); }
            catch { _ooMapWhere = { places: [] }; }
          }
          _renderOoMapDim();
        },
        signalsOn: _ooMapSignalsOn, signals: sig, focusT, windowY, focusSlider, focusLabel, focusTicks,
        timeScale: _ooMapTimeScale,
        onTimeScale: v => { _ooMapTimeScale = (v === "linear" ? "linear" : "log"); _renderOoMapDim(); },
        onSignals: async () => {
          _ooMapSignalsOn = !_ooMapSignalsOn;
          if (_ooMapSignalsOn && _ooMapSignals == null) {
            try {
              const d = await api("/api/timemap?limit=4000&hazards=true");
              _ooMapSignals = (d.signals || []).filter(s => typeof s.t === "number" && s.lat != null && s.lon != null);
            } catch { _ooMapSignals = []; }
          }
          _renderOoMapDim();
        },
        serverOn: _ooMapServerOn, serverPoints, serverMeta,
        onServer: async () => {
          _ooMapServerOn = !_ooMapServerOn;
          if (_ooMapServerOn && !_ooMapServerLoc) {
            try { _ooMapServerLoc = await api("/api/insights/server-locations"); }
            catch { _ooMapServerLoc = { countries: [], clusters: [], unavailable: {} }; }
          }
          _renderOoMapDim();
        },
        // rAF-coalesce slider drags so a fast sweep is at most one re-render per frame.
        onFocus: v => { _ooMapFocusSlider = v; if (_ooMapFocusRAF) cancelAnimationFrame(_ooMapFocusRAF); _ooMapFocusRAF = requestAnimationFrame(() => _renderOoMapDim()); },
        onSignal: (s, visible) => _ooMapSignalDetail(s, visible, windowY),
        // Dynamic non-overlapping country labels (THEME-2), opt-in.
        labelsOn: _ooMapLabelsOn,
        onLabels: () => { _ooMapLabelsOn = !_ooMapLabelsOn; _renderOoMapDim(); },
        // In-browser OSM offline-region overlay (THEME-2): parse a DOWNLOADED
        // .osm.pbf locally (zero network) and draw its geometry. Opt-in.
        osmOn: _ooMapOsmOn, osmGeo: _ooMapOsmGeo,
        // #51: real OSM admin (country) boundaries AUGMENT the choropleth geometry
        // by ISO code (a microstate the coarse 110m map drops now gets a true shape).
        osmAreas: _ooMapOsmOn && _ooMapOsmGeo ? _ooMapOsmGeo.areas : null,
        onOsm: () => _ooMapToggleOsm(),
        // Click a country → its coverage breakdown (THEME-2 "click-country → list").
        onCountry: iso => _ooMapCountryDetail(rowBy[(iso || "").toLowerCase()], dim),
        valueLabel: fmtV,
      });
    }
    // Click-a-country detail (THEME-2): the per-country coverage breakdown across
    // every measured dimension (sources · articles · keyword mentions · mean tone),
    // straight from the map-coverage row (counts only, no score). The mean-tone line
    // carries the VADER English-only caveat + its n. A button opens the Sources tab
    // so the user can explore that country's sources.
    function _ooMapCountryDetail(row, dim) {
      const host = $("oo-coverage-detail"); if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      if (!row) { host.innerHTML = `<div class="panel" style="padding:10px 12px;background:var(--panel2)"><span class="muted">${esc(t("No coverage recorded for this country yet."))}</span></div>`; return; }
      const iso = (row.country || "").toLowerCase();
      const name = ooRegionName(iso, row.name || row.country);
      const line = (label, v, extra) => (v != null && isFinite(v))
        ? `<div style="display:flex;justify-content:space-between;gap:12px"><span class="muted">${esc(label)}</span><span>${esc(fmtNum(v))}${extra ? " " + esc(extra) : ""}</span></div>` : "";
      const tone = (row.sentiment != null && isFinite(row.sentiment))
        ? `<div style="display:flex;justify-content:space-between;gap:12px"><span class="muted">${esc(t("Mean tone"))}</span><span>${row.sentiment >= 0 ? "+" : ""}${esc(fmtNum(row.sentiment, 2))} · ${esc(t("n="))}${row.sentiment_n || 0}</span></div>` : "";
      host.innerHTML = `<div class="panel" style="padding:10px 12px;background:var(--panel2)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <strong>${esc(name)}</strong>${row.continent ? ` <span class="pill">${esc(t(row.continent))}</span>` : ""}
        </div>
        <div style="margin-top:6px;font-size:13px;display:flex;flex-direction:column;gap:2px">
          ${line(t("Sources"), row.sources)}
          ${line(t("Articles"), row.articles)}
          ${line(t("Keyword mentions"), row.keywords)}
          ${tone}
        </div>
        ${tone ? `<div class="card-caveat" style="margin-top:5px">${esc(t("Mean tone uses the English-only VADER lexicon; non-English articles are not scored."))}</div>` : ""}
        <div class="row" style="margin-top:7px;gap:8px">
          <button class="tiny secondary" onclick="showTab('sources')">${esc(t("Explore sources"))}</button>
        </div>
      </div>`;
      host.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    // Signal click-to-detail (slice 5a.2 — ported faithfully from the temporal map's
    // showTmapDetail so retiring #oo-tmap loses nothing): the event's kind/title,
    // confirmed/geocode honesty, date·place·country·coords·source, note, reference
    // link, "find coverage in your corpus", and the co-occurrence "near in space &
    // time" seed (the same honest never-a-cause framing). English to match the
    // retired panel (no regression); keyable later.
    let _ooMapSigSet = [], _ooMapSigWin = 25;
    // "Near in space & time" co-occurrence is a TIGHT, FIXED window (field test
    // 2026-06-19 #14: it used the slider's focus window — ~span/12, i.e. ~166 years on
    // an antiquity→now span — so it linked events DECADES apart, a misleading
    // "co-occurrence"). Cap the time delta hard, independent of the slider: two events
    // within a couple of years AND close in space is a meaningful (still non-causal) seed.
    const _OOMAP_NEAR_YEARS = 2;
    function _ooMapSignalAt(i) { const s = _ooMapSigSet[i]; if (s) _ooMapSignalDetail(s, _ooMapSigSet, _ooMapSigWin); }
    function _ooMapNearby(s, visible, win) {
      const w = Math.min(win || _OOMAP_NEAR_YEARS, _OOMAP_NEAR_YEARS);  // never wider than the cap
      const out = [];
      (visible || []).forEach((o, idx) => {
        if (o === s) return;
        const dt = Math.abs(o.t - s.t), dlon = Math.abs(o.lon - s.lon), dlat = Math.abs(o.lat - s.lat);
        if (dt <= w && dlon <= TMAP_NEAR_DEG && dlat <= TMAP_NEAR_DEG)
          out.push({ idx, o, score: dt / (w || 1) + Math.hypot(dlon, dlat) / TMAP_NEAR_DEG });
      });
      return out.sort((a, b) => a.score - b.score).slice(0, 6);
    }
    function _ooMapSignalDetail(s, visible, win) {
      const host = $("oo-coverage-detail"); if (!host || !s) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      _ooMapSigSet = visible || []; _ooMapSigWin = win || 25;
      const url = s.url ? safeUrl(s.url) : null;
      // Item 2 (field-feedback A6, ruled): for a hazard, the composed search
      // combines TYPE + PLACE (two real, provider-asserted facts) rather than the
      // generic title/place text every other signal kind uses -- a more specific
      // corpus search than "Find coverage" alone would give.
      const cov = (s.kind === "hazard")
        ? [s.hazard_type, s.place].filter(Boolean).join(" ").trim()
        : (s.place || s.title || "").replace(/\s*\([^)]*\)\s*$/, "").trim();
      const geo = s.geocode === "country" ? `<span class="pill warn" title="country-level stand-in point, not the exact spot">≈ country</span>`
                : s.geocode === "city" ? `<span class="pill" title="placed at a known city">city</span>` : "";
      const conf = s.source === "corpus-mention" ? `<span class="pill warn" title="a date extracted from article text">mentioned · extracted</span>`
                 : s.confirmed ? `<span class="pill ok">confirmed</span>` : `<span class="pill warn">unconfirmed / scheduled</span>`;
      // Item 2: the INTERNAL article/reader link, once the hazard has been
      // ingested as a corpus Article (article_id is null until then -- never
      // fabricated).
      const localLink = (s.kind === "hazard" && s.article_id != null)
        ? `<a href="/api/articles/${s.article_id}/view" target="_blank" rel="noopener" class="tiny secondary" style="display:inline-block;padding:4px 9px;border-radius:6px" title="${esc(t("The local, offline copy of this hazard event."))}">${esc(t("Open the local article"))}</a>`
        : "";
      host.innerHTML = `<div class="panel" style="padding:10px 12px;background:var(--panel2)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="width:11px;height:11px;border-radius:50%;background:${kindColor(s.kind)};display:inline-block"></span>
          <strong>${esc(s.title)}</strong>
          <span class="pill">${esc(s.kind === "hazard" ? hazardTypeLabel(s.hazard_type) : kindLabel(s.kind))}</span> ${conf} ${geo}
        </div>
        <div class="muted" style="margin-top:5px;font-size:13px">
          ${esc(fmtDate(s))}${s.place ? ` · ${esc(s.place)}` : ""}${s.country ? ` (${esc(String(s.country).toUpperCase())})` : ""}
          · ${(+s.lat).toFixed(2)}, ${(+s.lon).toFixed(2)} · <span title="data source">${esc(s.source)}</span>
          ${s.magnitude != null ? ` · <b>M${esc(fmtNum(s.magnitude, 1))}</b>` : ""}
        </div>
        ${s.note ? `<div class="hint" style="margin-top:5px">${esc(s.note)}</div>` : ""}
        <div class="row" style="margin-top:7px;gap:8px">
          ${url ? extLink(url, "Official / reference source ↗", "tiny secondary", "align-self:center") : ""}
          ${localLink}
          ${cov ? `<button class="tiny secondary" onclick="tmapFindCoverage(${esc(JSON.stringify(cov))})">Find coverage in your corpus</button>` : ""}
        </div>
        ${(() => {
          const near = _ooMapNearby(s, _ooMapSigSet, _ooMapSigWin);
          if (!near.length) return "";
          const items = near.map(n => `<button class="tiny secondary" style="margin:2px 3px 0 0"
            onclick="_ooMapSignalAt(${n.idx})" title="${esc(fmtDate(n.o))}${n.o.place ? " · " + esc(n.o.place) : ""}">
            <span style="width:8px;height:8px;border-radius:50%;background:${kindColor(n.o.kind)};display:inline-block;margin-right:4px"></span>
            ${esc((n.o.title || "").slice(0, 38))} <span class="muted">${n.o.year != null ? esc(String(n.o.year)) : ""}</span></button>`).join("");
          return `<div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px">
            <div style="font-size:12px"><strong>Near in space &amp; time</strong>
              <span class="warn" title="These signals are merely close in place and time within your current window.">— co-occurrence, not a connection or cause. You judge.</span></div>
            <div style="margin-top:4px">${items}</div></div>`;
        })()}
      </div>`;
      host.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    // Item 3 (field-feedback A6, ruled): deep-link from the Home Alerts strip to
    // the World map, "centred on the event" -- switches to the map, selects the
    // Stories lens (the SAME lens the in-map strip already drives -- no second
    // map/engine), waits for the signal set to load, then opens the matching
    // hazard's OWN detail panel directly (a more robust "centring" than blindly
    // computing a slider position from outside the render function would be).
    async function openWorldMapAt(lat, lon, isoTime, articleId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      showTab("timemap");
      await new Promise(r => setTimeout(r, 60));
      if (_ooMapLensTabs) _ooMapLensTabs.select("stories");
      else await selectOoMapLens("stories");
      for (let i = 0; i < 20 && _ooMapSignals == null; i++) await new Promise(r => setTimeout(r, 100));
      const sig = Array.isArray(_ooMapSignals) ? _ooMapSignals : [];
      let match = (articleId != null)
        ? sig.find(s => s.kind === "hazard" && s.article_id === articleId)
        : null;
      if (!match && lat != null && lon != null) {
        const near = sig.filter(s => s.kind === "hazard")
          .map(s => ({ s, d: Math.hypot((s.lat || 0) - lat, (s.lon || 0) - lon) }))
          .sort((a, b) => a.d - b.d)[0];
        if (near && near.d < 0.5) match = near.s;
      }
      // The default "Major only" lens must never hide the very event the user
      // clicked through to: a deep-linked below-floor event clears the filter so
      // the point is actually on the map beside its detail panel.
      if (match && _ooMapHazMajorOnly && !_hazardSignalIsMajor(match)) {
        _ooMapHazMajorOnly = false;
        _renderOoMapLensBar();
        if (_ooMapPayload) _renderOoMapDim();
      }
      if (match) _ooMapSignalDetail(match, sig, 25);
      else toast(t("This event is outside the map's current signal set."), "err");
    }
    // The Home strip's overflow line ("N more, below the M6 display floor →"):
    // open the World map on the hazard layer with the major-only lens CLEARED,
    // because the whole point of that line is to reach the events the floor did
    // not show first. Full recall is one click away, exactly as the strip says.
    async function openWorldMapHazards() {
      showTab("timemap");
      await new Promise(r => setTimeout(r, 60));
      if (_ooMapLensTabs) _ooMapLensTabs.select("stories");
      else await selectOoMapLens("stories");
      for (let i = 0; i < 20 && _ooMapSignals == null; i++) await new Promise(r => setTimeout(r, 100));
      _ooMapHazMajorOnly = false;
      _ooMapHazType = null;
      _ooMapStoryKind = "hazard";
      _renderOoMapLensBar();
      if (_ooMapPayload) _renderOoMapDim();
    }
    // Toggle the in-browser OSM offline-region overlay (THEME-2). On first enable
    // it finds a DOWNLOADED region, fetches a bounded byte PREFIX of its local
    // .osm.pbf (zero network — a file already on disk), parses it with OOPBF, and
    // resolves way refs to coordinates. Honest: a preview, capped, never fabricated.
    async function _ooMapToggleOsm() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      if (_ooMapOsmOn) { _ooMapOsmOn = false; _renderOoMapDim(); return; }
      if (typeof OOPBF === "undefined" || !OOPBF.parse) { toast(t("The offline-map reader is unavailable."), "err"); return; }
      if (_ooMapOsmGeo) { _ooMapOsmOn = true; _renderOoMapDim(); return; }   // already parsed; just show
      if (_ooMapOsmLoading) return;
      _ooMapOsmLoading = true;
      try {
        const dl = await api("/api/geo/downloads");
        const done = (dl.downloads || []).filter(d => d.status === "done" && d.code);
        if (!done.length) { toast(t("No map region downloaded yet — get one in Settings → OpenStreetMap."), "err"); return; }
        const code = done[0].code;
        toast(t("Reading the offline map…"));
        // BINARY fetch (the bounded prefix). Loopback file read — no network egress.
        const res = await fetch(`/api/geo/regions/${encodeURIComponent(code)}/preview?max_bytes=8388608`);
        if (!res.ok) { toast(t("Could not read the downloaded region."), "err"); return; }
        const ab = await res.arrayBuffer();
        // Parse with tags + relations so we can also assemble admin (country)
        // boundaries (THEME-2 #51) — a higher block cap reaches the relations
        // section (they trail nodes/ways in a .pbf), maxNodes still bounds memory.
        const geo = await OOPBF.parse(ab, { maxBlocks: 48, maxNodes: 200000, withTags: true, withRelations: true });
        // Resolve way refs -> coordinates using the decoded node set (partial in a
        // bounded preview — drop a way we can't resolve, never invent a point).
        const byId = new Map(); for (const n of geo.nodes) byId.set(n.id, n);
        const lines = [];
        for (const w of geo.ways) {
          const cs = []; for (const id of w.refs) { const nd = byId.get(id); if (nd) cs.push(nd); }
          if (cs.length >= 2) lines.push(cs);
        }
        // Country (admin_level=2) boundary polygons, keyed by ISO 3166-1 alpha-2 so
        // they MERGE into the choropleth by code — replaces the coarse 110m shape /
        // centroid point for whatever country the region covers. Honest: only rings
        // we actually closed are emitted (assembleAdminAreas), never a fake border.
        const areas = (OOPBF.assembleAdminAreas ? OOPBF.assembleAdminAreas(geo) : []) || [];
        const osmAreas = {};
        for (const a of areas) { if (a && a.iso2 && a.rings && a.rings.length) osmAreas[a.iso2] = { name: a.name, rings: a.rings, source: a.source }; }
        _ooMapOsmGeo = { region: code, points: geo.nodes, lines, truncated: geo.truncated, blocks: geo.blocks,
          areas: osmAreas, areaCount: Object.keys(osmAreas).length };
        _ooMapOsmOn = true;
        _renderOoMapDim();
      } catch (e) {
        toast(t("Could not read the downloaded region.") + " " + (e && e.message ? e.message : ""), "err");
      } finally { _ooMapOsmLoading = false; }
    }

    // B2 (F1): when the map-coverage rollup serves the payload (OO_COLUMNAR_MAP_SERVE),
    // it attaches a `basis` {source, as_of, note} disclosure so the reader knows the
    // counts are as-of the last rollup build (new sources/articles appear after the next
    // rebuild). Render it via the shared basisChip (the disc form → "cached · as of …",
    // the note in the #oo-tip hover). Renders NOTHING when basis is absent (the live
    // path) — never a fabricated staleness. A DISCLOSURE, never a score.
    function _renderMapBasis() {
      const el = $("oo-coverage-basis"); if (!el) return;
      const b = _ooMapPayload && _ooMapPayload.basis;
      el.innerHTML = b ? basisChip(null, b) : "";
    }
    async function loadOoMapCoverage() {
      const host = $("oo-coverage-map"); if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        _ooMapPayload = await api("/api/insights/map-coverage");
        _renderMapBasis();   // rollup staleness disclosure, when present (else nothing)
        if (!(_ooMapPayload.by_country || []).length) {
          host.innerHTML = `<div class="muted">${esc(t("No located sources yet — add sources with a country, or collect some articles."))}</div>`;
          return;
        }
        _renderOoMapLensDesc();
        // Fast first paint (the coverage base for the current lens), THEN wire the
        // lens strip — its {initial}/select re-applies the active lens (loading the
        // Stories/Places/Server data lazily and re-rendering). ooSubtabs returns null
        // if the nav is absent, so the map still renders without the strip.
        await _renderOoMapDim();
        if (!_ooMapLensTabs) _ooMapLensTabs = ooSubtabs($("oomap-lenses"), selectOoMapLens, {initial: _ooMapLens});
        else _ooMapLensTabs.select(_ooMapLens);
      } catch (e) {
        host.innerHTML = `<div class="err">${esc(t("Could not load coverage:") + " " + e.message)}</div>`;
      }
    }

    async function loadMap() {
      const days = $("map-days").value, kind = $("map-kind").value;
      try {
        const d = await api(`/api/insights/map?days=${days}&kind=${encodeURIComponent(kind)}`);
        const rowsFor = (areas, label) => areas.length
          ? "<tr><th>" + label + "</th><th>Top keywords</th></tr>" + areas.map(a =>
              `<tr><td><strong>${esc(a.code||a.name)}</strong>${a.country&&a.name?` <span class="muted">${esc(a.country)}</span>`:""}</td><td>` +
              a.top.map(t => `<span class="pill" style="cursor:pointer" onclick='pickTerm(${esc(JSON.stringify(t.term))})'>${esc(t.term)} ${t.mentions}</span>`).join(" ") +
              `</td></tr>`).join("")
          : `<tr><td class="muted">No data — index the corpus (sources need a country/city).</td></tr>`;
        $("map-svg").innerHTML = buildMapSvg(d.cities || []);
        MAP_VB = {x: 0, y: 0, w: MAP_W, h: MAP_H}; wireMapDrag();
        $("map-countries").innerHTML = rowsFor(d.countries, "Country");
        $("map-cities").innerHTML = rowsFor(d.cities, "City");
      } catch (e) { toast(_failMsg("Map failed: {error}", e), "err"); }
    }

    // -- World map (ooMap): choropleth + space-time signals + a time slider -- //
    // Reuses the equirectangular projection (lon2x/lat2y, MAP_W/MAP_H) with its
    // own viewBox so it pans/zooms independently of the Insights map.
    const TMAP_KINDS = {
      disaster:{c:"#e5484d", l:"Disaster"}, conflict:{c:"#d6731f", l:"Conflict"},
      milestone:{c:"#7aa2f7", l:"Milestone"}, civic:{c:"#3fb950", l:"Civic"},
      space:{c:"#bf7af0", l:"Space"}, science:{c:"#1fb8c4", l:"Science"},
      climate:{c:"#2da44e", l:"Climate"}, sport:{c:"#e3b341", l:"Sport"},
      economic:{c:"#c9a227", l:"Economic"}, political:{c:"#8b949e", l:"Political"},
      technology:{c:"#58a6ff", l:"Technology"}, hazard:{c:"#f85149", l:"Hazard"},
      article:{c:"#a371f7", l:"Article"},
    };
    const kindColor = k => (TMAP_KINDS[k] || {c:"var(--muted)"}).c;
    // Translated label for a signal/story KIND (field-test Item 6): the TMAP_KINDS
    // labels are a bounded, meaningful vocabulary (Conflict · Climate · Civic …) keyed
    // ×12, so the story lens and the signals legend read in the active UI language.
    function kindLabel(k) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (x => x);
      return t((TMAP_KINDS[k] || {}).l || k);
    }

    let TMAP = {signals: [], range: null, caveat: ""};
    let TMAP_FOCUS = null;                       // fractional year in focus
    let TMAP_OFF = new Set();                     // kinds toggled off
    let TMAP_VB = {x:0, y:0, w:MAP_W, h:MAP_H};
    let _tmapVisible = [], _tmapPlay = null, TMAP_OUTLINE = null;
    // Mention layer: PLACES the corpus's articles mention (When/Where/Who, T12),
    // from /api/insights/where. Geographic only (no per-mention date), so it is a
    // static overlay independent of the time slider. OFF by default (the temporal
    // map's own signals stay the primary view; the user opts in). _tmapWhere holds
    // the endpoint payload verbatim so the method+caveat travel with the data.
    let _tmapMentionsOn = false, _tmapWhere = null;
    let _tmapDrag = false, _tmapDragSX = 0, _tmapDragSY = 0, _tmapMouseupWired = false, _tmapPrefsLoaded = false;

    // Remember the user's layers/window across sessions (local only, like agenda subs).
    const TMAP_PREFS = "oo.timemap.prefs";
    function tmapSavePrefs() {
      try { localStorage.setItem(TMAP_PREFS, JSON.stringify({
        articles: !!($("tmap-articles") && $("tmap-articles").checked),
        mentions: !!($("tmap-mentions") && $("tmap-mentions").checked),
        hazards: !!($("tmap-hazards") && $("tmap-hazards").checked),
        window: $("tmap-window") ? $("tmap-window").value : "25",
      })); } catch { /* storage may be disabled — preferences just won't persist */ }
    }
    function tmapRestorePrefs() {
      let p; try { p = JSON.parse(localStorage.getItem(TMAP_PREFS) || "null"); } catch { p = null; }
      if (!p) return;
      if ($("tmap-articles")) $("tmap-articles").checked = !!p.articles;
      if ($("tmap-mentions")) $("tmap-mentions").checked = !!p.mentions;
      if ($("tmap-hazards")) $("tmap-hazards").checked = !!p.hazards;
      if ($("tmap-window") && p.window != null) $("tmap-window").value = String(p.window);
    }
    function onTmapWindowChange() { tmapSavePrefs(); renderTimemap(); }
    const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

    function fmtYear(t) {                          // fractional year -> "Sep 2001"
      if (t == null) return "—";
      const y = Math.floor(t), doy = Math.round((t - y) * 365);
      const d = new Date(2001, 0, 1); d.setDate(doy + 1);
      return `${MON[d.getMonth()]} ${y < 0 ? "" : ""}${y}`;
    }
    function fmtDate(s) {                          // a signal's ISO date -> "Oct 24, 79"
      const m = /^(\-?\d+)-(\d{2})-(\d{2})/.exec(s.date || "");
      if (!m) return s.date || "";
      return `${MON[+m[2]-1]} ${+m[3]}, ${+m[1]}`;
    }

    function applyTmapVB() {
      const svg = document.getElementById("oo-tmap");
      if (svg) svg.setAttribute("viewBox", `${TMAP_VB.x} ${TMAP_VB.y} ${TMAP_VB.w} ${TMAP_VB.h}`);
    }
    function wireTmapWheel() {                     // Google-Maps-style wheel zoom
      const svg = document.getElementById("oo-tmap");
      if (!svg || svg._wheelWired) return;
      svg._wheelWired = true;
      svg.addEventListener("wheel", (e) => {
        e.preventDefault();
        const m = svg.getScreenCTM().inverse(); const p = svg.createSVGPoint();
        p.x = e.clientX; p.y = e.clientY; const q = p.matrixTransform(m);
        const f = Math.exp(e.deltaY * 0.0015);
        const w = Math.min(MAP_W, Math.max(MAP_W * 0.03, TMAP_VB.w * f));
        const sc = w / TMAP_VB.w;
        TMAP_VB.x = q.x - (q.x - TMAP_VB.x) * sc;
        TMAP_VB.y = q.y - (q.y - TMAP_VB.y) * sc;
        TMAP_VB.w = w; TMAP_VB.h *= sc;
        applyTmapVB(); renderTimemap();
      }, {passive: false});
    }
    function zoomTmap(f) {
      const cx = TMAP_VB.x + TMAP_VB.w/2, cy = TMAP_VB.y + TMAP_VB.h/2;
      TMAP_VB.w = Math.min(MAP_W, Math.max(30, TMAP_VB.w * f));
      TMAP_VB.h = Math.min(MAP_H, Math.max(15, TMAP_VB.h * f));
      TMAP_VB.x = cx - TMAP_VB.w/2; TMAP_VB.y = cy - TMAP_VB.h/2;
      applyTmapVB(); renderTimemap();             // re-render to toggle labels (semantic zoom)
    }
    function resetTmap() { TMAP_VB = {x:0, y:0, w:MAP_W, h:MAP_H}; applyTmapVB(); renderTimemap(); }

    function wireTmapDrag() {
      const svg = document.getElementById("oo-tmap");
      if (!svg) return;
      // svg-bound listeners die with the element when the next render replaces it; the
      // window-level mouseup is attached exactly ONCE (drag state is module-level) so it
      // can't accumulate across the many re-renders that 'play' triggers.
      svg.addEventListener("mousedown", e => {
        _tmapDrag = true; _tmapDragSX = e.clientX; _tmapDragSY = e.clientY; svg.style.cursor = "grabbing"; });
      svg.addEventListener("mousemove", e => {
        if (!_tmapDrag) return;
        const r = svg.getBoundingClientRect();
        TMAP_VB.x -= (e.clientX - _tmapDragSX) * TMAP_VB.w / r.width;
        TMAP_VB.y -= (e.clientY - _tmapDragSY) * TMAP_VB.h / r.height;
        _tmapDragSX = e.clientX; _tmapDragSY = e.clientY; applyTmapVB();
      });
      if (!_tmapMouseupWired) {
        _tmapMouseupWired = true;
        window.addEventListener("mouseup", () => {
          _tmapDrag = false;
          const s = document.getElementById("oo-tmap"); if (s) s.style.cursor = "grab";
        });
      }
    }

    let TMAP_SPAN_OVERRIDE = null;                 // [a,b] fractional years (user-set)
    function dateToT(iso) {                        // YYYY-MM-DD -> fractional year
      const d = new Date(iso + "T00:00:00Z");
      if (isNaN(d)) return null;
      const y = d.getUTCFullYear(), start = Date.UTC(y, 0, 1);
      return y + (d.getTime() - start) / (Date.UTC(y + 1, 0, 1) - start);
    }
    function tToDate(t) {                          // fractional year -> YYYY-MM-DD
      const y = Math.floor(t), start = Date.UTC(y, 0, 1);
      const ms = start + (t - y) * (Date.UTC(y + 1, 0, 1) - start);
      return new Date(ms).toISOString().slice(0, 10);
    }
    function onTmapSpanChange() {                  // re-map the slider onto a period
      const a = $("tmap-span-a").value, b = $("tmap-span-b").value;
      TMAP_SPAN_OVERRIDE = (a && b && a < b) ? [dateToT(a), dateToT(b)] : null;
      $("tmap-slider").value = 1000; onTmapSlide(); buildTmapStrip();
    }
    function onTmapDate() {                        // precise manual focus
      const t = dateToT($("tmap-date").value);
      if (t == null) return;
      $("tmap-slider").value = tToSlider(t); onTmapSlide();
    }
    function tmapExpand() {
      $("tmap-wrap").classList.toggle("mm-big");
      $("tmap-expand").textContent = $("tmap-wrap").classList.contains("mm-big") ? "🗗" : "⛶";
      renderTimemap();
    }
    function tmapSpan() {                          // [min,max] fractional years, padded
      if (TMAP_SPAN_OVERRIDE) return TMAP_SPAN_OVERRIDE;
      const r = TMAP.range || {};
      if (r.min == null) return [2000, 2030];
      const pad = Math.max(1, (r.max - r.min) * 0.02);
      return [r.min - pad, r.max + pad];
    }
    function sliderToT(v) { const [a, b] = tmapSpan(); return a + (v/1000) * (b - a); }
    function tToSlider(t) { const [a, b] = tmapSpan(); return b > a ? Math.round((t-a)/(b-a)*1000) : 1000; }

    function onTmapSlide() {
      TMAP_FOCUS = sliderToT(+$("tmap-slider").value);
      $("tmap-focus-label").textContent = fmtYear(TMAP_FOCUS);
      if (TMAP_FOCUS > 1583 && TMAP_FOCUS < 9999) $("tmap-date").value = tToDate(TMAP_FOCUS);
      renderTimemap();
    }

    function toggleTmapKind(k) {
      if (TMAP_OFF.has(k)) TMAP_OFF.delete(k); else TMAP_OFF.add(k);
      buildTmapLegend(); renderTimemap();
    }
    function buildTmapLegend() {
      const counts = (TMAP.range && TMAP.range.by_kind) || {};
      const present = Object.keys(TMAP_KINDS).filter(k => counts[k]);
      $("tmap-legend").innerHTML = present.map(k => {
        const off = TMAP_OFF.has(k);
        return `<button class="tiny" onclick="toggleTmapKind('${k}')" title="show/hide"
          style="border-color:${kindColor(k)};opacity:${off?0.4:1};display:inline-flex;align-items:center;gap:5px">
          <span style="width:9px;height:9px;border-radius:50%;background:${kindColor(k)};display:inline-block"></span>
          ${esc(TMAP_KINDS[k].l)} <span class="muted">${counts[k]}</span></button>`;
      }).join("") || `<span class="muted">No signals to show.</span>`;
      buildTmapMentionLegend();                    // append the mention-layer caveat line (never overwrites the kinds)
    }

    // ----- Mention layer: places the corpus's articles MENTION (T12) -------- //
    // Reuses the temporal map's equirectangular projection (lon2x/lat2y) and its
    // render loop — no second projection. Fed by GET /api/insights/where verbatim,
    // so the endpoint's method + "Deduced from text, never confirmed." caveat travel
    // with the data. Marker AREA scales with the article SPREAD (honest: r∝√spread),
    // never a fabricated score. Places with null lat/lon are NOT plotted; their count
    // is surfaced. OFF by default (the map's own signals stay primary; the user opts in).
    let _tmapWhereMapped = [];                      // the plotted subset (for click indexing)

    async function toggleTmapMentions() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      _tmapMentionsOn = !_tmapMentionsOn;
      const btn = $("tmap-mentions-toggle");
      if (btn) {                                     // FILL=state cue, like the kind chips
        btn.setAttribute("aria-pressed", _tmapMentionsOn ? "true" : "false");
        btn.style.borderColor = _tmapMentionsOn ? "var(--accent)" : "";
        btn.style.color = _tmapMentionsOn ? "var(--accent)" : "";
      }
      if (_tmapMentionsOn && _tmapWhere == null) {   // lazy fetch, only when first switched on
        if (btn) btn.disabled = true;
        try {
          // Both city + country (kind omitted = both); bounded by the endpoint (limit ≤ 500).
          _tmapWhere = await api("/api/insights/where?limit=500");
        } catch (e) {
          _tmapWhere = null; _tmapMentionsOn = false;
          if (btn) { btn.classList.remove("active"); btn.setAttribute("aria-pressed", "false"); }
          toast(t("Could not load mentioned places: ") + e.message, "err");
        } finally { if (btn) btn.disabled = false; }
      }
      buildTmapLegend(); renderTimemap();
    }

    function buildTmapMentionLegend() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const el = $("tmap-legend"); if (!el) return;
      if (!_tmapMentionsOn) return;
      const w = _tmapWhere;
      const placed = w ? (w.placed || 0) : 0;
      const unmapped = w ? Math.max(0, (w.count || 0) - placed) : 0;
      // The "deduced, never confirmed" caveat is VISIBLE on the layer (informed consent),
      // with the endpoint's long-form method in the hover bubble (invariant #17 layering).
      const caveat = (w && w.caveat) || "Deduced from text, never confirmed.";
      let line;
      if (!w) {
        line = `<span class="muted">${esc(t("Loading mentioned places…"))}</span>`;
      } else if (!placed) {
        line = `<span class="muted">${esc(t("No mapped mentions in your corpus yet."))}</span>`;
      } else {
        line = `<span style="display:inline-flex;align-items:center;gap:5px">
            <span style="width:9px;height:9px;border-radius:50%;background:var(--accent);opacity:0.55;display:inline-block"></span>
            <strong>${placed}</strong> ${esc(t("mentioned places"))}</span>
          <span class="warn" title="${esc(w.method || caveat)}">— ${esc(t(caveat))}</span>`
          + (unmapped ? ` <span class="muted" title="${esc(t("These places have no known coordinate, so they are not drawn on the map."))}">· ${unmapped} ${esc(t("places not mapped (no coordinates)"))}</span>` : "");
      }
      el.insertAdjacentHTML("beforeend",
        `<div style="flex-basis:100%;margin-top:4px;font-size:12px">${line}</div>`);
    }

    function buildTmapMentionLayer() {
      _tmapWhereMapped = [];
      if (!_tmapMentionsOn || !_tmapWhere || !Array.isArray(_tmapWhere.places)) return "";
      // Plot EVERY returned place with a coordinate (the endpoint already bounds the set).
      _tmapWhereMapped = _tmapWhere.places.filter(p => p.lat != null && p.lon != null);
      if (!_tmapWhereMapped.length) return "";
      const labels = TMAP_VB.w < MAP_W * 0.55;       // same semantic-zoom rule as the signals
      const maxArts = Math.max(1, ..._tmapWhereMapped.map(p => +p.articles || 0));
      const markers = _tmapWhereMapped.map((p, i) => {
        const x = lon2x(p.lon).toFixed(1), y = lat2y(p.lat).toFixed(1);
        // AREA ∝ article spread ⇒ radius ∝ √spread (honest; no composite score).
        const r = (1.6 + 4.0 * Math.sqrt((+p.articles || 0) / maxArts)).toFixed(1);
        const lab = labels ? `<text x="${x}" y="${(+y - +r - 1).toFixed(1)}" fill="var(--fg)"
          font-size="3.2" text-anchor="middle" opacity="0.8">${esc((p.name || "").slice(0, 40))}</text>` : "";
        return `<g style="cursor:pointer" onclick="showTmapWhereDetail(${i})">
          <circle cx="${x}" cy="${y}" r="${(+r + 3).toFixed(1)}" fill="transparent" stroke="none"></circle>
          <circle cx="${x}" cy="${y}" r="${r}" fill="var(--accent)" fill-opacity="0.45"
            stroke="var(--accent)" stroke-width="0.5"><title>${esc(p.name || "")}${p.country ? " (" + esc(p.country.toUpperCase()) + ")" : ""} — ${(+p.articles || 0)} ${esc("articles")}, ${(+p.mentions || 0)} ${esc("mentions")}</title></circle>${lab}</g>`;
      }).join("");
      return `<g class="tmap-mentions">${markers}</g>`;
    }

    function showTmapWhereDetail(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const p = _tmapWhereMapped[i]; if (!p) return;
      const caveat = (_tmapWhere && _tmapWhere.caveat) || "Deduced from text, never confirmed.";
      const method = (_tmapWhere && _tmapWhere.method) || "";
      const cov = (p.name || "").trim();
      $("tmap-detail").innerHTML = `<div class="panel" style="padding:10px 12px;background:var(--panel2)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="width:11px;height:11px;border-radius:50%;background:var(--accent);opacity:0.55;display:inline-block"></span>
          <strong>${esc(p.name || "")}</strong>
          ${p.country ? `<span class="pill">${esc(p.country.toUpperCase())}</span>` : ""}
          <span class="pill">${esc(p.kind === "country" ? t("country") : t("city"))}</span>
          <span class="pill warn" title="${esc(t("A place name extracted from article text, placed at a gazetteer coordinate."))}">${esc(t("mentioned · deduced"))}</span>
        </div>
        <div class="muted" style="margin-top:5px;font-size:13px">
          <strong>${(+p.articles || 0)}</strong> ${esc(t("articles mention it"))}
          · <strong>${(+p.mentions || 0)}</strong> ${esc(t("total mentions"))}
          · ${(+p.lat).toFixed(2)}, ${(+p.lon).toFixed(2)}
        </div>
        <div class="hint" style="margin-top:5px" title="${esc(method)}">${esc(t(caveat))}</div>
        <div class="row" style="margin-top:7px;gap:8px">
          ${cov ? `<button class="tiny secondary" onclick="tmapFindCoverage(${esc(JSON.stringify(cov))})">${esc(t("Find coverage in your corpus"))}</button>` : ""}
        </div>
      </div>`;
    }

    function stopTmapPlay() {                       // also called by showTab when leaving the tab
      if (_tmapPlay) { clearInterval(_tmapPlay); _tmapPlay = null; }
      const btn = $("tmap-play"); if (btn) btn.textContent = "▶ play";
    }
    function toggleTmapPlay() {
      if (_tmapPlay) { stopTmapPlay(); return; }
      const btn = $("tmap-play"); if (btn) btn.textContent = "❚❚ pause";
      _tmapPlay = setInterval(() => {
        const speed = Number($("tmap-speed").value) || 1;   // user-tweakable sweep speed
        const s = $("tmap-slider"); let v = +s.value + 6 * speed;
        if (v >= 1000) { v = 1000; stopTmapPlay(); }
        s.value = v; onTmapSlide();
      }, 120);
    }

    function buildTmapStrip() {                    // density-over-time orientation strip
      const [a, b] = tmapSpan(), W = 1000, H = 22, N = 80;
      const bins = new Array(N).fill(0);
      TMAP.signals.forEach(s => {
        if (TMAP_OFF.has(s.kind)) return;
        const i = Math.min(N-1, Math.max(0, Math.floor((s.t - a)/(b - a) * N)));
        bins[i]++;
      });
      const max = Math.max(1, ...bins);
      const bars = bins.map((c, i) => c ? `<rect x="${(i/N*W).toFixed(1)}" y="${(H-2 - (H-4)*Math.sqrt(c/max)).toFixed(1)}"
        width="${(W/N-1).toFixed(1)}" height="${((H-2)-(H-2 - (H-4)*Math.sqrt(c/max))).toFixed(1)}"
        fill="var(--accent)" fill-opacity="0.6"/>` : "").join("");
      const cx = TMAP_FOCUS == null ? W : (TMAP_FOCUS - a)/(b - a) * W;
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="none" onclick="stripClick(event)"
        style="height:22px;background:var(--panel2);border:1px solid var(--border);border-radius:5px;cursor:crosshair">
        ${bars}<line x1="${cx.toFixed(1)}" y1="0" x2="${cx.toFixed(1)}" y2="${H}" stroke="var(--fg)" stroke-width="2"/></svg>`;
    }
    function stripClick(ev) {
      const svg = ev.currentTarget, r = svg.getBoundingClientRect();
      const v = Math.round((ev.clientX - r.left)/r.width * 1000);
      $("tmap-slider").value = Math.min(1000, Math.max(0, v)); onTmapSlide();
    }

    // Real coastlines, only if the offline outline asset has been generated
    // (scripts/build_world_outline.py). Never fabricated — absent -> graticule only.
    function buildTmapCoast() {
      if (!TMAP_OUTLINE || !TMAP_OUTLINE.rings) return "";
      const paths = TMAP_OUTLINE.rings.map(ring => {
        let d = "", prevLon = null;
        ring.forEach(([lon, lat]) => {
          const cmd = (prevLon == null || Math.abs(lon - prevLon) > 180) ? "M" : "L";  // break across the dateline
          d += `${cmd}${lon2x(lon).toFixed(1)} ${lat2y(lat).toFixed(1)}`;
          prevLon = lon;
        });
        return `<path d="${d}Z" fill="var(--panel3)" fill-opacity="0.5" stroke="var(--border)" stroke-width="0.3"/>`;
      }).join("");
      return paths;
    }

    function buildTmapSvg() {
      const win = +$("tmap-window").value, focus = TMAP_FOCUS;
      const labels = TMAP_VB.w < MAP_W * 0.55;     // semantic zoom: labels only when zoomed in
      const coast = buildTmapCoast();
      let grid = "";
      for (let lon = -180; lon <= 180; lon += 30)
        grid += `<line x1="${lon2x(lon)}" y1="0" x2="${lon2x(lon)}" y2="${MAP_H}" stroke="var(--border)" stroke-width="0.3"/>`;
      for (let lat = -90; lat <= 90; lat += 30)
        grid += `<line x1="0" y1="${lat2y(lat)}" x2="${MAP_W}" y2="${lat2y(lat)}" stroke="var(--border)" stroke-width="0.3"/>`;

      _tmapVisible = TMAP.signals.filter(s =>
        !TMAP_OFF.has(s.kind) && (win === 0 || focus == null || Math.abs(s.t - focus) <= win));
      const dots = _tmapVisible.map((s, i) => {
        const x = lon2x(s.lon).toFixed(1), y = lat2y(s.lat).toFixed(1);
        const dist = focus == null ? 0 : Math.abs(s.t - focus);
        const span = win || (tmapSpan()[1] - tmapSpan()[0]) || 1;
        const op = Math.max(0.15, 1 - (dist/span) * 0.8);
        const future = focus != null && s.t > focus + 0.001;
        const mag = +s.magnitude || 0;
        const r = (mag ? 1.8 + mag*0.7 : (s.confirmed ? 3 : 2.4)).toFixed(1);
        const col = kindColor(s.kind);
        const ring = future || !s.confirmed
          // fill="transparent" (not "none"): the whole disc stays a hit target —
          // hollow rings were clickable only on their 1px edge (live test 2026-06-11).
          ? `fill="transparent" stroke="${col}" stroke-width="1.1" stroke-dasharray="${future?'2 1.5':''}"`
          : `fill="${col}" fill-opacity="0.82" stroke="var(--bg)" stroke-width="0.4"`;
        const lab = labels ? `<text x="${x}" y="${(+y - +r - 1).toFixed(1)}" fill="var(--fg)"
          font-size="3.4" text-anchor="middle" opacity="${op.toFixed(2)}">${esc((s.title||"").slice(0,42))}</text>` : "";
        return `<g opacity="${op.toFixed(2)}" style="cursor:pointer" onclick="showTmapDetail(${i})">
          <circle cx="${x}" cy="${y}" r="${(+r + 3.5).toFixed(1)}" fill="transparent" stroke="none"></circle>
          <circle cx="${x}" cy="${y}" r="${r}" ${ring}><title>${esc(s.title)} — ${esc(fmtDate(s))}</title></circle>${lab}</g>`;
      }).join("");

      const mentions = buildTmapMentionLayer();    // static place-mention overlay (sets _tmapWhereMapped)

      // With no curated signals AND the mention layer off, there is nothing to map.
      // But once the user opts into mentions, keep the map so the overlay can render.
      if (!TMAP.signals.length && !mentions)
        return `<div class="muted">No signals with both a place and a date yet. Curated anchors ship by default;
          index a geocoded corpus, enable live hazards, or install the events agenda to add more.</div>`;
      return `<svg id="oo-tmap" viewBox="0 0 ${MAP_W} ${MAP_H}" width="100%"
        style="max-width:${MAP_W}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px;cursor:grab">
        ${coast}${grid}${dots}${mentions}</svg>`;
    }

    // The honest seed of "convergence": other signals close in BOTH place and time.
    // It is co-occurrence only — never a claim of connection or cause. The reader judges.
    const TMAP_NEAR_DEG = 15;                      // ~1500 km at the equator
    function tmapNearby(s) {
      const win = +$("tmap-window").value || 25;   // reuse the chosen time window (else ±25y)
      const out = [];
      _tmapVisible.forEach((o, idx) => {
        if (o === s) return;
        const dt = Math.abs(o.t - s.t);
        const dlon = Math.abs(o.lon - s.lon), dlat = Math.abs(o.lat - s.lat);
        if (dt <= win && dlon <= TMAP_NEAR_DEG && dlat <= TMAP_NEAR_DEG)
          out.push({idx, o, score: dt/(win||1) + Math.hypot(dlon, dlat)/TMAP_NEAR_DEG});
      });
      return out.sort((a, b) => a.score - b.score).slice(0, 6);
    }

    // Close the space-time loop: jump to a corpus search for this place/subject.
    function tmapFindCoverage(q) {
      showTab("search");
      const i = $("q"); if (i) i.value = q;
      if (typeof doSearch === "function") doSearch();
    }

    function showTmapDetail(i) {
      const s = _tmapVisible[i]; if (!s) return;
      const url = s.url ? safeUrl(s.url) : null;
      const cov = (s.place || s.title || "").replace(/\s*\([^)]*\)\s*$/, "").trim();
      const geo = s.geocode === "country" ? `<span class="pill warn" title="country-level stand-in point, not the exact spot">≈ country</span>`
                : s.geocode === "city" ? `<span class="pill" title="placed at a known city">city</span>` : "";
      const conf = s.source === "corpus-mention" ? `<span class="pill warn" title="a date extracted from article text">mentioned · extracted</span>`
                 : s.confirmed ? `<span class="pill ok">confirmed</span>` : `<span class="pill warn">unconfirmed / scheduled</span>`;
      $("tmap-detail").innerHTML = `<div class="panel" style="padding:10px 12px;background:var(--panel2)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="width:11px;height:11px;border-radius:50%;background:${kindColor(s.kind)};display:inline-block"></span>
          <strong>${esc(s.title)}</strong>
          <span class="pill">${esc(TMAP_KINDS[s.kind]?.l || s.kind)}</span> ${conf} ${geo}
        </div>
        <div class="muted" style="margin-top:5px;font-size:13px">
          ${esc(fmtDate(s))}${s.place?` · ${esc(s.place)}`:""}${s.country?` (${esc(s.country.toUpperCase())})`:""}
          · ${(+s.lat).toFixed(2)}, ${(+s.lon).toFixed(2)} · <span title="data source">${esc(s.source)}</span>
        </div>
        ${s.note?`<div class="hint" style="margin-top:5px">${esc(s.note)}</div>`:""}
        <div class="row" style="margin-top:7px;gap:8px">
          ${url?extLink(url, "Official / reference source ↗", "tiny secondary", "align-self:center"):""}
          ${cov?`<button class="tiny secondary" onclick="tmapFindCoverage(${esc(JSON.stringify(cov))})">Find coverage in your corpus</button>`:""}
        </div>
        ${(() => {
          const near = tmapNearby(s);
          if (!near.length) return "";
          const items = near.map(n => `<button class="tiny secondary" style="margin:2px 3px 0 0"
            onclick="showTmapDetail(${n.idx})" title="${esc(fmtDate(n.o))}${n.o.place?' · '+esc(n.o.place):''}">
            <span style="width:8px;height:8px;border-radius:50%;background:${kindColor(n.o.kind)};display:inline-block;margin-right:4px"></span>
            ${esc((n.o.title||'').slice(0,38))} <span class="muted">${n.o.year}</span></button>`).join("");
          return `<div style="margin-top:8px;border-top:1px solid var(--border);padding-top:6px">
            <div style="font-size:12px"><strong>Near in space &amp; time</strong>
              <span class="warn" title="These signals are merely close in place and time within your current window.">— co-occurrence, not a connection or cause. You judge.</span></div>
            <div style="margin-top:4px">${items}</div></div>`;
        })()}
      </div>`;
    }

    function renderTimemap() {
      $("tmap-strip").innerHTML = buildTmapStrip();
      const svg = buildTmapSvg();                  // sets _tmapVisible
      const note = (TMAP.signals.length && !_tmapVisible.length)
        ? `<div class="hint" style="margin-top:6px">No signals fall in this time window — widen the <b>Window</b> or move the slider.</div>` : "";
      $("tmap-svg").innerHTML = svg + note;
      applyTmapVB(); wireTmapDrag(); wireTmapWheel();
    }

    // RETIRED (slice 5b): the standalone temporal map's UI panel was removed and
    // the Map tab now routes to loadOoMapCoverage (the unified ooMap absorbs the
    // choropleth + signals layer + time slider + click-detail). These temporal-only
    // functions (loadTimemap / renderTimemap / buildTmap* / showTmapDetail /
    // tmapNearby / the onTmap* + zoom/reset/play/mentions handlers / wireTmap* /
    // tmap*Prefs / the TMAP state) are now UNREACHABLE dead code — they null-guard on
    // the removed #tmap-* elements. Left in place pending a browser-verified deletion
    // cleanup; the SHARED helpers kindColor / TMAP_KINDS / fmtYear / fmtDate / dateToT
    // / TMAP_NEAR_DEG / tmapFindCoverage STAY (ooMap reuses them).
    async function loadTimemap() {
      loadOoMapCoverage();                         // the ooMap choropleth (independent of the temporal layer)
      if (!_tmapPrefsLoaded) { _tmapPrefsLoaded = true; tmapRestorePrefs(); }  // restore once, before reading controls
      const hz = $("tmap-hazards") && $("tmap-hazards").checked;
      const arts = $("tmap-articles") && $("tmap-articles").checked;
      const ment = $("tmap-mentions") && $("tmap-mentions").checked;
      tmapSavePrefs();
      $("tmap-status").textContent = "Loading…";
      if (TMAP_OUTLINE == null) {                 // best-effort, once: real coastlines if the asset exists
        try { const o = await fetch("/static/world_outline.json"); TMAP_OUTLINE = o.ok ? await o.json() : false; }
        catch { TMAP_OUTLINE = false; }            // absent -> graticule fallback, no error
      }
      try {
        const d = await api(`/api/timemap?limit=4000${hz?"&hazards=true":""}${arts?"&articles=true":""}${ment?"&mentions=true":""}`);
        TMAP = {signals: d.signals || [], range: d.range || null, caveat: d.caveat || ""};
        const r = TMAP.range || {};
        $("tmap-status").innerHTML = `${TMAP.signals.length} signals · ${r.min!=null?Math.floor(r.min):"?"}–${r.max!=null?Math.ceil(r.max):"?"}`
          + ((d.failures && d.failures.length) ? ` · <span class="warn" title="${esc(d.failures.join('; '))}">${d.failures.length} source(s) unavailable</span>` : "");
        // Fallback so the honest framing never silently disappears (audit 0.0.9).
        $("tmap-caveat").textContent = TMAP.caveat ||
          "Signals are placed where their source/extracted location says; co-occurrence in space and time is not causation.";
        if (TMAP_FOCUS == null || TMAP_FOCUS < tmapSpan()[0] || TMAP_FOCUS > tmapSpan()[1]) {
          $("tmap-slider").value = 1000; TMAP_FOCUS = sliderToT(1000);   // start "now-ish" (latest)
        }
        $("tmap-focus-label").textContent = fmtYear(TMAP_FOCUS);
        buildTmapLegend(); renderTimemap();
      } catch (e) {
        $("tmap-status").innerHTML = `<span class="err">Could not load: ${esc(e.message)}</span>`;
      }
    }

    // -- Wikipedia change-tracking ------------------------------------------ //
    let _wikiLangsLoaded = false;
    async function loadWikiLanguages() {
      if (_wikiLangsLoaded) return;
      try {
        const d = await api("/api/wiki/languages");
        const sel = $("wiki-lang"); if (!sel) return;
        const cur = sel.value || "en";
        sel.innerHTML = "";
        // ONE flat list (invariant #1, amended 2026-06-16: no continent optgroups);
        // the native name (autonym) leads as the identifier (invariant #15).
        (d.languages || []).forEach(l => {
          const o = document.createElement("option");
          o.value = l.code; o.textContent = `${l.autonym} — ${l.name} (${l.code})`;
          sel.appendChild(o);
        });
        sel.value = cur; if (!sel.value) sel.value = "en";
        _wikiLangsLoaded = true;
      } catch (e) { /* keep the en default */ }
    }

    async function loadWiki() {
      loadWikiLanguages();
      try { renderWikiStatus(await api("/api/wiki/status")); }
      catch (e) { if (!_wikiStatusBuilt) $("wiki-status").textContent = "Status unavailable: " + e.message; }
      loadWikiPages(); loadWikiChanges();
    }

    async function loadWikiDumps() {
      // Populate #dumpread-wiki (the readable editions) BEFORE the dump-FTS status renders:
      // _renderDumpIndexStatus reads those options for the "Edition to index" select, so a
      // race (index status resolving first) would otherwise leave that select empty on first
      // open until the panel is re-opened.
      await loadReadableDumps();
      loadDumpIndexStatus();  // + the full-text index status (indexed editions, build state)
      try {
        const d = await api("/api/wiki/dumps");
        const t = $("dump-table");
        if (!d.downloads.length) { t.innerHTML = `<tr><td class="muted">No offline downloads.</td></tr>`; return; }
        t.innerHTML = "<tr><th>Edition</th><th>Progress</th><th>Status</th><th></th></tr>" +
          d.downloads.map(e => `<tr>
            <td><strong>${esc(e.wiki)}</strong> <span class="muted">${esc(e.kind)}</span></td>
            <td>${humanBytes(e.downloaded_bytes)}${e.total_bytes?` / ${humanBytes(e.total_bytes)} (${e.percent}%)`:""}</td>
            <td><span class="pill ${e.status==='done'?'ok':e.status==='error'?'err':e.status==='downloading'?'':'warn'}">${esc(e.status)}</span>${e.error?` <span class="muted">${esc(e.error)}</span>`:""}</td>
            <td style="white-space:nowrap">
              ${e.status==='downloading'?`<button class="tiny secondary" onclick="pauseDump(${esc(JSON.stringify(e.key))})">Pause</button>`:
                (e.status!=='done'?`<button class="tiny secondary" onclick="startDump(${esc(JSON.stringify(e.wiki))})">Resume</button>`:"")}
              <button class="tiny danger" onclick="deleteDump(${esc(JSON.stringify(e.key))})">Delete</button>
            </td></tr>`).join("");
      } catch (e) { /* dumps optional */ }
    }

    function dumpSelected() {                      // multi-select (maintainer 2026-06-11)
      return [...$("dump-lang").selectedOptions].map(o => o.value).filter(Boolean);
    }
    async function probeDump() {
      const w = dumpSelected()[0] || "en";
      $("dump-estimate").textContent = "Checking size…";
      try {
        const d = await api(`/api/wiki/dumps/probe?wiki=${encodeURIComponent(w)}`);
        $("dump-estimate").textContent = d.size_bytes ? `≈ ${humanBytes(d.size_bytes)} for ${d.wiki}` : "size unknown";
      } catch (e) { $("dump-estimate").textContent = "size check failed"; }
    }

    // Audit finding 2026-07-17 (L5): a shared, clear-before-set poll timer -- mirrors
    // the established _llmPullStartPoll/_volStartPoll/_fbStartPoll pattern. Without
    // this, starting several dump downloads in quick succession (the multi-edition
    // picker loop just below calls startDump once per edition, sequentially awaited
    // but each spawning its OWN fire-and-forget poller) stacked one independent 3s
    // poller per start -- a polling-storm repeat of the 2026-06-27/07-01 item-F5 family.
    let _dumpPollTimer = null;
    function _dumpStartPoll() {
      if (_dumpPollTimer) clearInterval(_dumpPollTimer);
      let n = 0;
      _dumpPollTimer = setInterval(() => {
        loadWikiDumps();
        if (++n > 40) { clearInterval(_dumpPollTimer); _dumpPollTimer = null; }
      }, 3000);
    }
    async function startDump(wiki) {
      // Several selected editions download sequentially (one polite queue).
      const picks = wiki ? [wiki] : dumpSelected();
      if (picks.length > 1) {
        for (const code of picks) await startDump(code);
        return;
      }
      const w = picks[0] || "en";
      if (!wiki && !confirm(`Download the ${w} current-text dump? This can be very large (tens of GB for big editions).`)) return;
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Download a Wikipedia dump"))) return;
      try { await api("/api/wiki/dumps/start", {method:"POST", body: JSON.stringify({wiki: w})});
        toast("Download started."); loadWikiDumps();
        _dumpStartPoll();  // refresh progress a few times
      } catch (e) { toast(_failMsg("Start failed: {error}", e), "err"); }
    }
    async function pauseDump(key) {
      try { await api("/api/wiki/dumps/pause?key="+encodeURIComponent(key), {method:"POST"}); loadWikiDumps(); }
      catch (e) { toast(_failMsg("Pause failed: {error}", e), "err"); }
    }
    async function deleteDump(key) {
      if (!confirm("Delete this download and its file?")) return;
      try { await api("/api/wiki/dumps?key="+encodeURIComponent(key), {method:"DELETE"}); loadWikiDumps(); }
      catch (e) { toast(_failMsg("Delete failed: {error}", e), "err"); }
    }

    // -- Offline map: OSM region downloads (Group M) ------------------------- //
    // Mirrors the Wikipedia dump UI: a zero-network catalogue picker (size = a
    // DATED estimate, exact size read on download) + a resumable download-job
    // table. Starting a download is a NETWORK action, so it passes the ONE consent
    // popup (ensureOnline, invariant #14) and is refused while airplane mode is on
    // (the backend's guarded factory enforces the kill switch too).
    // ONE merged list (maintainer 2026-06-21): every region with its LIVE download
    // state — not-downloaded · queued · downloading (% + bar) · paused · downloaded ✓ —
    // joined from the catalogue + the downloads manager, so the two old separate lists
    // (catalogue + a jobs table) are assembled into one. Clicking a button gives instant
    // feedback. "Whole planet" downloads only the continents you DON'T already have.
    let _osmRegions = [], _osmDownloads = [];
    async function loadOsmMap() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const list = $("osm-region-list"); if (!list) return;
      try {
        const [rg, dl] = await Promise.all([
          api("/api/geo/regions"),
          api("/api/geo/downloads").catch(() => ({ downloads: [] })),
        ]);
        _osmRegions = rg.regions || [];
        _osmDownloads = dl.downloads || [];
        const note = $("osm-size-note"), asof = $("osm-size-asof");
        if (note && asof && rg.size_estimate_as_of) { asof.textContent = rg.size_estimate_as_of; note.hidden = false; }
        _renderOsmList();
      } catch (e) { list.innerHTML = `<div class="muted">${esc(t("Could not load regions."))}</div>`; }
      const tbl = $("osm-dl-table"); if (tbl) tbl.innerHTML = "";   // merged into the list above
    }
    // Legacy callers (start/pause/delete pollers) refresh the merged list.
    function loadOsmDownloads() { return loadOsmMap(); }

    function _osmDlByCode() { const m = {}; for (const d of _osmDownloads) m[d.code] = d; return m; }
    function _osmContinents() { return _osmRegions.filter((r) => r.code !== "planet"); }

    function _renderOsmList() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const list = $("osm-region-list"); if (!list) return;
      const byCode = _osmDlByCode();
      const continents = _osmContinents();
      const doneCodes = new Set(continents.filter((r) => (byCode[r.code] || {}).status === "done").map((r) => r.code));
      const rows = _osmRegions.map((r) => {
        const d = byCode[r.code], isPlanet = r.code === "planet";
        const meta = `<span class="muted">· ~${humanBytes(r.size_estimate_bytes)} · ${esc(r.continent)}</span>`;
        let stateHtml = "", actions = "";
        if (isPlanet) {
          const missing = continents.filter((c) => !doneCodes.has(c.code));
          if (!missing.length) stateHtml = `<span class="pill ok">${esc(t("All continents downloaded"))} ✓</span>`;
          else {
            stateHtml = `<span class="muted">${doneCodes.size}/${continents.length} ${esc(t("continents"))}</span>`;
            actions = `<button class="tiny danger" onclick="startPlanetDownload(this)">${esc(t("Download missing continents"))}</button>`;
          }
        } else if (!d) {
          actions = `<button class="tiny danger" onclick="startOsmDownload(${esc(JSON.stringify(r.code))}, this)">${esc(t("Download"))}</button>`;
        } else if (d.status === "downloading") {
          const pct = (d.percent != null) ? d.percent : (d.total_bytes ? Math.floor(100 * d.downloaded_bytes / d.total_bytes) : 0);
          stateHtml = `<span class="pill">${esc(t("Downloading"))} ${pct}%</span>`
            + `<progress max="100" value="${pct}" style="width:110px;vertical-align:middle"></progress>`
            + `<span class="muted" style="font-size:12px">${humanBytes(d.downloaded_bytes)}${d.total_bytes ? ` / ${humanBytes(d.total_bytes)}` : ""}</span>`;
          actions = `<button class="tiny secondary" onclick="pauseOsm(${esc(JSON.stringify(d.key))})">${esc(t("Pause"))}</button>`;
        } else if (d.status === "queued") {
          const qpos = d.queue_position;
          const queued = _osmDownloads.filter((x) => x.status === "queued" && x.queue_position != null)
            .sort((a, b) => a.queue_position - b.queue_position).map((x) => x.key);
          const qi = queued.indexOf(d.key);
          stateHtml = `<span class="pill warn">${esc(t("Queued"))}${qpos ? ` #${qpos}` : ""}</span>`;
          if (qi > 0) actions += `<button class="tiny secondary" onclick="osmMove(${esc(JSON.stringify(d.key))}, -1)" title="${esc(t("Move earlier in the queue"))}">↑</button> `;
          if (qi >= 0 && qi < queued.length - 1) actions += `<button class="tiny secondary" onclick="osmMove(${esc(JSON.stringify(d.key))}, 1)" title="${esc(t("Move later in the queue"))}">↓</button> `;
          actions += `<button class="tiny secondary" onclick="deleteOsm(${esc(JSON.stringify(d.key))})">${esc(t("Cancel"))}</button>`;
        } else if (d.status === "done") {
          stateHtml = `<span class="pill ok">${esc(t("Downloaded"))} ✓ <span class="muted">${humanBytes(d.downloaded_bytes || d.total_bytes || r.size_estimate_bytes)}</span></span>`;
          actions = `<button class="tiny danger" onclick="deleteOsm(${esc(JSON.stringify(d.key))})">${esc(t("Delete"))}</button>`;
        } else {   // paused | error
          stateHtml = `<span class="pill ${d.status === "error" ? "err" : "warn"}">${esc(t(d.status))}</span>${d.error ? ` <span class="muted">${esc(d.error)}</span>` : ""}`;
          actions = `<button class="tiny secondary" onclick="resumeOsm(${esc(JSON.stringify(d.code))}, this)">${esc(t("Resume"))}</button>`
            + ` <button class="tiny danger" onclick="deleteOsm(${esc(JSON.stringify(d.key))})">${esc(t("Delete"))}</button>`;
        }
        return `<div class="osm-region-row">
          <span class="osm-region-name"><strong>${esc(r.name)}</strong> ${meta}${isPlanet ? ` <span class="muted">— ${esc(t("downloads each continent you don't have yet"))}</span>` : ""}</span>
          <span style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">${stateHtml} ${actions}</span>
        </div>`;
      }).join("");
      list.innerHTML = rows || `<div class="muted">${esc(t("No regions."))}</div>`;
    }

    // Audit finding 2026-07-17 (L5): a shared, clear-before-set poll timer -- mirrors
    // the established _llmPullStartPoll/_volStartPoll/_fbStartPoll pattern. Without
    // this, clicking Download on several regions in quick succession (a real user
    // action the merged region-list UI invites -- each click calls startOsmDownload,
    // which calls _osmPoll) stacked one independent 3s poller per click -- a
    // polling-storm repeat of the 2026-06-27/07-01 item-F5 family.
    let _osmPollTimer = null;
    function _osmPoll() {
      if (_osmPollTimer) clearInterval(_osmPollTimer);
      loadOsmMap();
      let n = 0;
      _osmPollTimer = setInterval(() => {
        loadOsmMap();
        if (++n > 40) { clearInterval(_osmPollTimer); _osmPollTimer = null; }
      }, 3000);
    }
    async function startOsmDownload(code, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const c = code || "";
      if (!c) return;
      if (btn) { btn.disabled = true; btn.textContent = t("Starting…"); }   // instant feedback
      // No extra "are you sure" confirm (field test 2026-06-19 #15): the size is shown in
      // the row; the ONE network-consent popup (ensureOnline) is the only gate that matters.
      if (!await ensureOnline(t("Download an offline map region"))) { loadOsmMap(); return; }
      try {
        await api("/api/geo/downloads/start", { method: "POST", body: JSON.stringify({ code: c }) });
        toast(t("Download started.")); _osmPoll();
      } catch (e) { toast(_failMsg("Start failed: {error}", e), "err"); loadOsmMap(); }
    }
    function resumeOsm(code, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (btn) { btn.disabled = true; btn.textContent = t("Resuming…"); }
      return startOsmDownload(code);
    }
    // "Whole planet" = download every continent you don't already hold (skips the
    // downloaded ones — maintainer 2026-06-21: never re-fetch parts you already have).
    // The continent extracts together cover the planet, so this is the same coverage
    // WITHOUT re-downloading (a single monolithic planet file cannot skip parts).
    async function startPlanetDownload(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (btn) { btn.disabled = true; btn.textContent = t("Starting…"); }
      if (!await ensureOnline(t("Download the offline world map"))) { loadOsmMap(); return; }
      const byCode = _osmDlByCode();
      const busy = (c) => { const s = (byCode[c.code] || {}).status; return s === "done" || s === "downloading" || s === "queued"; };
      const continents = _osmContinents();
      const todo = continents.filter((c) => !busy(c)), skip = continents.filter(busy);
      if (!todo.length) { toast(t("All continents are already downloaded or in progress.")); loadOsmMap(); return; }
      let started = 0;
      for (const c of todo) {
        try { await api("/api/geo/downloads/start", { method: "POST", body: JSON.stringify({ code: c.code }) }); started++; }
        catch (e) { /* one region failing must not abort the rest */ }
      }
      toast(`${t("Queued")} ${started} ${t("regions")}${skip.length ? ` · ${skip.length} ${t("already present")}` : ""}`);
      _osmPoll();
    }
    // Reorder a QUEUED region download (same prioritisation control as the task
    // manager's dump/OSM reorder). Optimistic: renumber the cached queue + repaint
    // immediately, THEN persist via the geo reorder endpoint, THEN reconcile.
    async function osmMove(key, dir) {
      const queued = _osmDownloads.filter((x) => x.status === "queued" && x.queue_position != null)
        .sort((a, b) => a.queue_position - b.queue_position);
      const i = queued.findIndex((x) => x.key === key);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= queued.length) return;
      [queued[i], queued[j]] = [queued[j], queued[i]];
      queued.forEach((x, k) => { x.queue_position = k + 1; });   // optimistic renumber
      _renderOsmList();
      try {
        await api("/api/geo/downloads/reorder", { method: "POST", body: JSON.stringify({ keys: queued.map((x) => x.key) }) });
      } catch (e) { /* reconcile from backend truth */ }
      loadOsmMap();
    }
    async function pauseOsm(key) {
      try { await api("/api/geo/downloads/pause?key=" + encodeURIComponent(key), { method: "POST" }); loadOsmMap(); }
      catch (e) { toast(_failMsg("Pause failed: {error}", e), "err"); }
    }
    async function deleteOsm(key) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!confirm(t("Delete this download and its file?"))) return;
      try { await api("/api/geo/downloads?key=" + encodeURIComponent(key), { method: "DELETE" }); loadOsmMap(); }
      catch (e) { toast(_failMsg("Delete failed: {error}", e), "err"); }
    }

    // -- Official statistics producers (Group N): the curated directory + the --- //
    //    one-click "add producers to my sources" action. A producer with a known  //
    //    news section registers ENABLED and is crawled from there; one without    //
    //    registers disabled, because its home URL is a dataset portal (ruling 9). //
    //    Descriptive only: NO figures, NO score, NO verdict label (ruling #50 —   //
    //    a producer is a STANCED source, stated as a caveat; the user judges).    //
    //    home URLs open the LOCAL link-preview first (extLink, invariant #6/#6e). //
    async function loadStatAgencies() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("stat-agencies"); if (!box) return;
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const d = await api("/api/stats/agencies");
        const ags = d.agencies || [];
        const cov = $("stat-coverage");
        if (cov) {
          // Honest coverage line: how many continents have at least one national producer.
          const n = (d.continents_covered || []).length;
          cov.textContent = t("Continents covered: {n}").replace("{n}", n)
            + " · " + (ags.length) + " " + t("producers");
        }
        if (!ags.length) { box.innerHTML = `<div class="muted">${esc(t("No producers listed."))}</div>`; return; }
        // The API already orders international-first, then by region, then name —
        // render in that order (no client re-sort needed). Scope is labelled, not raw.
        const scope = (s) => s === "international" ? t("International")
          : s === "national" ? t("National") : (s || "");
        const rows = ags.map(a => `<tr>
            <td><strong>${esc(a.name)}</strong>${a.acronym ? ` <span class="muted">(${esc(a.acronym)})</span>` : ""}</td>
            <td>${esc(scope(a.scope))}</td>
            <td>${a.country ? esc(String(a.country).toUpperCase()) : "<span class=\"muted\">—</span>"}</td>
            <td>${esc(a.region || "")}</td>
            <td>${a.home_url ? extLink(a.home_url, a.home_url) : ""}</td>
          </tr>`).join("");
        box.innerHTML = `<table>
          <tr><th>${esc(t("Name"))}</th><th>${esc(t("Scope"))}</th><th>${esc(t("Country"))}</th>`
          + `<th>${esc(t("Region"))}</th><th>${esc(t("Official site"))}</th></tr>${rows}</table>`;
        // The API caveat travels with the data, visible by default (informed consent).
        if (d.caveat) box.innerHTML += `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>`;
      } catch (e) {
        box.innerHTML = `<div class="muted">${esc(t("Could not load the statistics directory."))}</div>`;
      }
    }
    async function ingestStatSources() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const msg = $("stat-ingest-msg"), btn = $("stat-ingest-btn");
      if (!confirm(t("Add every official-statistics producer to your sources? Those with a known news section are enabled and collected; the rest stay disabled until that address is researched."))) return;
      if (btn) btn.disabled = true;
      if (msg) msg.textContent = t("Registering…");
      try {
        // LOCAL DB write — the endpoint opens ZERO external sockets, so this works in
        // airplane mode and never needs the network-consent gate (no ensureOnline).
        const d = await api("/api/stats/sources/ingest", { method: "POST" });
        const n = (x) => (x || 0).toLocaleString();
        if (msg) {
          // The enabled / awaiting split is the point of the news_url field: it says
          // exactly how many producers still need a researched news section before
          // they can be collected. Shown whenever anything was created.
          const split = d.created
            ? ` · ${n(d.enabled)} ${esc(t("enabled"))} · ${n(d.awaiting_news_url)} ${esc(t("awaiting a news section URL"))}`
            : "";
          msg.innerHTML = `<b>${n(d.created)}</b> ${esc(t("created"))} · ${n(d.skipped_existing)} ${esc(t("already present"))}`
            + split
            + (d.skipped_no_domain ? ` · ${n(d.skipped_no_domain)} ${esc(t("skipped (no domain)"))}` : "")
            + (d.caveat ? `<div class="muted" style="margin-top:5px">${esc(d.caveat)}</div>` : "");
        }
        toast(t("Statistics producers registered."), "ok");
      } catch (e) {
        if (msg) msg.innerHTML = `<span class="note err">${esc(t("Could not register the producers."))}: ${esc(e.message)}</span>`;
        else toast(t("Could not register the producers."), "err");
      } finally { if (btn) btn.disabled = false; }
    }

    // -- Official figures (Group N): consented fetch · vintaged store · triangulation.
    // English-only strings here (matching the keyword-explorer / diagnostics Settings
    // sub-features) so i18n stays 100% with zero new keys; the BACKEND enforces the
    // honesty contract (no score, gaps as null, side-by-side never averaged).
    function _statfigFmt(v) { return v === null || v === undefined ? "—" : Number(v).toLocaleString(); }
    async function fetchStatFigure() {
      const src = $("statfig-source").value;
      const series = ($("statfig-series").value || "").trim();
      const country = ($("statfig-country").value || "").trim() || "all";
      const msg = $("statfig-msg"), btn = $("statfig-fetch");
      if (!series) { if (msg) msg.textContent = "Enter an indicator or dataset id first."; return; }
      // The fetch egresses over the configured transport -> the ONE consent popup.
      if (typeof ensureOnline === "function" && !await ensureOnline("Fetch official statistics figures")) return;
      const body = src === "worldbank"
        ? { source: "worldbank", indicator: series, country }
        : { source: "eurostat", dataset: series };
      if (btn) btn.disabled = true;
      if (msg) msg.textContent = "Fetching…";
      try {
        const d = await api("/api/stats/figures/fetch", { method: "POST", body: JSON.stringify(body) });
        if (msg) msg.innerHTML = `<b>${(d.fetched || 0).toLocaleString()}</b> fetched · `
          + `${(d.stored || 0).toLocaleString()} stored · ${(d.duplicate || 0).toLocaleString()} already had this vintage · `
          + `${(d.gaps || 0).toLocaleString()} published gaps`
          + (d.caveat ? `<div class="muted" style="margin-top:5px">${esc(d.caveat)}</div>` : "");
        $("statfig-view-series").value = series;
        loadStatFigures();
      } catch (e) {
        // Honest verdicts: 409 = airplane mode refusal, 502 = transport/endpoint failure.
        if (msg) msg.innerHTML = `<span class="note err">Fetch failed: ${esc(e.message)}</span>`;
      } finally { if (btn) btn.disabled = false; }
    }
    async function loadStatFigures() {
      const box = $("statfig-table"); if (!box) return;
      const series = ($("statfig-view-series").value || "").trim();
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const qs = series ? "?series_id=" + encodeURIComponent(series) : "";
        const d = await api("/api/stats/figures" + qs);
        const figs = d.figures || [];
        if (!figs.length) { box.innerHTML = `<div class="muted">No stored figures yet — fetch some above.</div>`; return; }
        const rows = figs.map(f => `<tr>
            <td>${esc(f.agency)}</td><td>${esc(f.series_id)}</td><td>${esc(f.ref_area)}</td>
            <td>${esc(f.time_period)}</td><td style="text-align:right">${_statfigFmt(f.value)}</td>
            <td>${esc(f.unit || "")}</td><td>${esc(f.adjustment || "")}</td><td>${esc(f.base_year || "")}</td>
          </tr>`).join("");
        box.innerHTML = `<div class="hint">${(d.shown||figs.length)} of ${(d.count||figs.length).toLocaleString()} shown · latest vintage</div>
          <table><tr><th>Agency</th><th>Series</th><th>Area</th><th>Period</th><th style="text-align:right">Value</th>`
          + `<th>Unit</th><th>SA/NSA</th><th>Base yr</th></tr>${rows}</table>`
          + (d.caveat ? `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load figures: ${esc(e.message)}</div>`; }
    }
    async function triangulateStatSeries() {
      const box = $("statfig-tri"); if (!box) return;
      const series = ($("statfig-view-series").value || "").trim();
      if (!series) { box.innerHTML = `<div class="muted">Enter a series id above to triangulate.</div>`; return; }
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const d = await api("/api/stats/triangulate?series_id=" + encodeURIComponent(series));
        const cells = d.cells || [];
        if (!cells.length) { box.innerHTML = `<div class="muted">No producers stored for "${esc(series)}" yet.</div>`; return; }
        const cellHtml = cells.map(c => {
          const cols = c.producers.map(p => `${esc(p.agency)}: <b>${_statfigFmt(p.value)}</b>${p.unit ? " " + esc(p.unit) : ""}`).join(" &nbsp;·&nbsp; ");
          const cmp = c.comparability || {};
          const flag = cmp.comparable
            ? `<span class="pill ok">comparable</span>`
            : `<span class="pill warn">not comparable — differs on ${esc((cmp.differs_on||[]).join(", "))}</span>`;
          return `<tr><td>${esc(c.ref_area)}</td><td>${esc(c.time_period)}</td><td>${c.n_producers}</td><td>${cols}</td><td>${flag}</td></tr>`;
        }).join("");
        box.innerHTML = `<table><tr><th>Area</th><th>Period</th><th>#</th><th>Producers (side by side)</th><th>Comparability</th></tr>${cellHtml}</table>`
          + (d.caveat ? `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not triangulate: ${esc(e.message)}</div>`; }
    }
    // -- Revision anomalies (the reliable-memory check): History must not be silently
    //    rewritten. Retrospective, names the shape not the intent, no score. English-only.
    async function loadRevisionAnomalies() {
      const box = $("statfig-revisions"); if (!box) return;
      const series = ($("statfig-view-series").value || "").trim();
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const qs = series ? "?series_id=" + encodeURIComponent(series) : "";
        const d = await api("/api/stats/revision-anomalies" + qs);
        const items = d.anomalies || [];
        if (!items.length) {
          box.innerHTML = `<div class="muted">No revision anomalies. A figure needs several prior revisions before an outlier can be judged, and only a recent revision unusually large for its own history is flagged.</div>`;
          return;
        }
        const rows = items.map(a => {
          const rel = (a.rel_change != null) ? ` <span class="muted">(${(a.rel_change * 100).toFixed(1)}%)</span>` : "";
          return `<tr>
            <td>${esc(a.agency)}</td><td>${esc(a.series_id)}</td><td>${esc(a.ref_area)}</td><td>${esc(a.time_period)}</td>
            <td style="text-align:right">${_statfigFmt(a.from_value)} → ${_statfigFmt(a.to_value)}</td>
            <td style="text-align:right">${_statfigFmt(a.abs_change)}${rel}</td>
            <td style="text-align:right">${(a.robust_z).toFixed(1)}</td>
            <td style="text-align:right">${a.n_prior_revisions}</td>
            <td>${esc(a.revised_at)}</td></tr>`;
        }).join("");
        box.innerHTML = `<div class="hint">${items.length} flagged · robust z ≥ ${esc(String(d.z_min))} · ≥ ${esc(String(d.min_prior_revisions))} prior revisions</div>`
          + `<table><tr><th>Agency</th><th>Series</th><th>Area</th><th>Period</th>`
          + `<th style="text-align:right">From → to</th><th style="text-align:right">Change</th>`
          + `<th style="text-align:right">Robust z</th><th style="text-align:right">Priors</th><th>Revised at</th></tr>${rows}</table>`
          + (d.method ? `<div class="hint" style="margin-top:8px">${esc(d.method)}</div>` : "")
          + (d.caveat ? `<div class="hint" style="margin-top:6px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not check revision anomalies: ${esc(e.message)}</div>`; }
    }
    // -- Honest stat chart: draws /api/stats/figures/series via ooViz.statChartGeometry.
    //    A comparability segment (unit/base-year/SA-NSA change) is its OWN path — never
    //    joined; a gap is a break, never interpolated. role=img + a .sr-only data table.
    function _fmtYearTick(v) { return Number.isInteger(v) ? String(v) : v.toFixed(1); }
    async function renderStatChart() {
      const box = $("statfig-chart"); if (!box) return;
      const series = ($("statfig-view-series").value || "").trim();
      const area = ($("statfig-view-area").value || "").trim();
      if (!series || !area) { box.innerHTML = `<div class="muted">Enter a series id and an area (e.g. FR) to chart it over time.</div>`; return; }
      if (typeof ooViz === "undefined") { box.innerHTML = `<div class="muted">Chart toolkit unavailable.</div>`; return; }
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const d = await api("/api/stats/figures/series?series_id=" + encodeURIComponent(series) + "&ref_area=" + encodeURIComponent(area));
        const segs = d.segments || [];
        const total = segs.reduce((acc, s) => acc + ((s.points || []).length), 0);
        if (!total) { box.innerHTML = `<div class="muted">No figures stored for "${esc(series)}" / "${esc(area)}". Fetch some above first.</div>`; return; }
        const W = 640, H = 240;
        const g = ooViz.statChartGeometry(d, { width: W, height: H });
        const yLines = g.yTicks.map(t =>
          `<line x1="${g.pad.l}" y1="${t.y.toFixed(1)}" x2="${W - g.pad.r}" y2="${t.y.toFixed(1)}" stroke="var(--muted)" stroke-width="1" opacity="0.28"/>`
          + `<text x="${g.pad.l - 6}" y="${(t.y + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)">${esc(_statfigFmt(t.value))}</text>`).join("");
        const xLabels = g.xTicks.map(t =>
          `<text x="${t.x.toFixed(1)}" y="${H - g.pad.b + 14}" text-anchor="middle" font-size="10" fill="var(--muted)">${esc(_fmtYearTick(t.value))}</text>`).join("");
        const paths = g.paths.map(p => `<path d="${esc(p.d)}" fill="none" stroke="var(--accent)" stroke-width="1.75"/>`).join("");
        const unit = (segs[0] && segs[0].unit) ? segs[0].unit : "";
        const breaks = g.nSegments > 1 ? ` · ${g.nSegments} segments (comparability breaks not joined)` : "";
        const aria = `${esc(series)} for ${esc(area)}: ${total} points, ${_fmtYearTick(g.timeDomain[0])} to ${_fmtYearTick(g.timeDomain[1])}${unit ? ", " + esc(unit) : ""}`;
        const trows = segs.flatMap(s => (s.points || []).map(p =>
          `<tr><td>${esc(p.period)}</td><td>${p.value == null ? "—" : esc(_statfigFmt(p.value))}</td><td>${esc(s.unit || "")}</td></tr>`)).join("");
        box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${aria}" style="max-width:${W}px;height:auto">${yLines}${xLabels}${paths}</svg>`
          + `<div class="hint">${total} points · ${esc(area)}${unit ? " · " + esc(unit) : ""}${breaks}</div>`
          + `<table class="sr-only"><caption>Stored values</caption><tr><th>Period</th><th>Value</th><th>Unit</th></tr>${trows}</table>`
          + (d.caveat ? `<div class="hint" style="margin-top:6px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not chart: ${esc(e.message)}</div>`; }
    }
    // -- Stat choropleth (§5B Phase C): colour a world map by one indicator, through the
    // ONE ooMap component + the node-tested ooViz.choroplethData honesty gate. English-only
    // (matches the chart panel). The cells carry iso2 (backend bridge), so no frontend ISO
    // map is needed. Browser-unverified per fork-3.
    async function renderStatMap() {
      const host = $("statfig-map"); if (!host) return;
      const meta = $("statfig-map-meta");
      const series = ($("statfig-view-series").value || "").trim();
      const agency = (($("statfig-map-agency") || {}).value || "").trim();
      const isLevel = !!($("statfig-map-level") && $("statfig-map-level").checked);
      if (!series) { host.innerHTML = `<div class="muted">Enter a series id above, then Map by country.</div>`; if (meta) meta.textContent = ""; return; }
      if (typeof ooViz === "undefined") { host.innerHTML = `<div class="muted">Map toolkit unavailable.</div>`; return; }
      host.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const q = "/api/stats/map?series_id=" + encodeURIComponent(series) + (agency ? "&agency=" + encodeURIComponent(agency) : "");
        const d = await api(q);
        const cells = d.cells || [];
        if (!cells.length) { host.innerHTML = `<div class="muted">No stored figures for "${esc(series)}". Fetch some above first.</div>`; if (meta) meta.textContent = ""; return; }
        const iso2By = {}; cells.forEach(c => { iso2By[c.ref_area] = c.iso2; });
        // The node-tested comparability gate: only areas on the modal basis are colour-eligible.
        const cd = ooViz.choroplethData(cells.map(c => ({
          ref_area: c.ref_area, value: c.value, unit: c.unit, base_year: c.base_year,
          adjustment: c.adjustment, time_period: c.time_period,
        })), { kind: isLevel ? "level" : "normalized" });
        const multi = d.multi_producer ? "  Several producers report this series — pin a producer above; the map never averages them." : "";
        if (cd.mode === "symbols") {
          // A LEVEL: we do NOT fake a level choropleth (a big country would look like 'more'
          // just for being big). Honest refusal + the comparable values as a ranked list.
          const ranked = cd.cells.filter(c => c.comparable && typeof c.value === "number")
            .sort((a, b) => b.value - a.value).slice(0, 30)
            .map(c => `<tr><td>${esc(ooRegionName(iso2By[c.area] || "", c.area))}</td><td style="text-align:right">${esc(fmtNum(c.value))}</td></tr>`).join("");
          host.innerHTML = `<div class="note">${esc(cd.refusalReason || "")}</div>`
            + (ranked ? `<table style="margin-top:6px"><tr><th>Area</th><th style="text-align:right">Value</th></tr>${ranked}</table>` : "");
          if (meta) meta.textContent = cd.caveat + multi;
          return;
        }
        const values = {}, names = {};
        cd.cells.forEach(c => {
          if (!c.comparable) return;            // incomparable basis / no value → no-data hatch
          const iso2 = iso2By[c.area];
          if (!iso2) return;                    // a non-country aggregate (WLD/EUU) → dropped honestly
          values[iso2] = c.value;
          names[iso2] = (typeof ooRegionName === "function") ? ooRegionName(iso2, iso2.toUpperCase()) : iso2;
        });
        const unit = (cd.basis && cd.basis.unit) || "";
        const nMapped = Object.keys(values).length;
        if (!nMapped) { host.innerHTML = `<div class="muted">No comparable, mappable figures for this series. ${esc(cd.caveat)}</div>`; if (meta) meta.textContent = ""; return; }
        await ooMap(host, {
          values, names, unit,
          valueLabel: (iso, v) => `${fmtNum(v)}${unit ? " " + unit : ""}`,
          aria: `${series} — ${nMapped} countries with comparable data`,
          method: d.method || "",
          caveat: cd.caveat + multi,
        });
        if (meta) meta.textContent = `${cd.comparableCount} comparable · ${cd.incomparableCount} on a different basis (no-data) · ${cd.noValueCount} no value`;
      } catch (e) { host.innerHTML = `<div class="muted">Could not map: ${esc(e && e.message || e)}</div>`; }
    }
    // -- Tracked figures (ruling #12): scheduled vintage auto-refresh. English-only.
    async function loadStatSubs() {
      const box = $("statfig-subs"); if (!box) return;
      try {
        const d = await api("/api/stats/subscriptions");
        const subs = d.subscriptions || [];
        if (!subs.length) { box.innerHTML = `<div class="muted">Nothing tracked yet — fetch a figure above to start tracking it.</div>`; return; }
        const rows = subs.map(s => {
          const what = s.indicator ? esc(s.indicator) + (s.country ? " · " + esc(String(s.country).toUpperCase()) : "")
                                   : esc(s.dataset || "");
          const last = s.last_fetched_at ? fmtDateTime(s.last_fetched_at) : "never";
          return `<tr>
            <td>${esc(s.source)}</td><td>${what}</td>
            <td>every ${s.interval_days}d</td>
            <td><span class="pill ${s.enabled ? 'ok' : ''}">${s.enabled ? 'on' : 'off'}</span></td>
            <td>${esc(last)}${s.last_status ? ` <span class="muted">(${esc(s.last_status)})</span>` : ""}</td>
            <td><button class="secondary" onclick="toggleStatSub(${s.id}, ${!s.enabled})">${s.enabled ? 'Disable' : 'Enable'}</button>
                <button class="secondary" onclick="deleteStatSub(${s.id})">Remove</button></td>
          </tr>`;
        }).join("");
        box.innerHTML = `<table><tr><th>Source</th><th>Series</th><th>Interval</th><th>State</th><th>Last refresh</th><th></th></tr>${rows}</table>`
          + (d.caveat ? `<div class="hint" style="margin-top:6px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load tracked figures: ${esc(e.message)}</div>`; }
    }
    async function toggleStatSub(id, enabled) {
      try { await api("/api/stats/subscriptions/" + id, { method: "PATCH", body: JSON.stringify({ enabled }) }); loadStatSubs(); }
      catch (e) { toast("Could not update: " + e.message, "err"); }
    }
    async function deleteStatSub(id) {
      if (!confirm("Stop tracking this figure for auto-refresh? (Stored vintages are kept.)")) return;
      try { await api("/api/stats/subscriptions/" + id, { method: "DELETE" }); loadStatSubs(); }
      catch (e) { toast("Could not remove: " + e.message, "err"); }
    }
    async function refreshStatSubs() {
      try {
        const d = await api("/api/stats/subscriptions/refresh", { method: "POST" });
        toast(d.skipped_offline ? "Offline — nothing refreshed (go online first)."
                                : `Refreshed ${d.refreshed || 0}, stored ${d.stored || 0} new vintage(s).`,
              d.errors ? "err" : "ok");
        loadStatSubs(); loadStatFigures();
      } catch (e) { toast(_failMsg("Refresh failed: {error}", e), "err"); }
    }

    // -- Read a page from a downloaded dump (T14: local, zero network) ------- //
    async function loadReadableDumps() {
      const sel = $("dumpread-wiki"); if (!sel) return;
      try {
        const d = await api("/api/wiki/dumps/readable");
        const cur = sel.value;
        sel.innerHTML = (d.wikis || []).map(w => `<option value="${esc(w)}">${esc(w)}</option>`).join("")
          || `<option value="">—</option>`;
        if (cur && [...sel.options].some(o => o.value === cur)) sel.value = cur;
      } catch (e) { /* reader box is optional */ }
    }
    // Substring TITLE search over a downloaded edition's multistream index (local,
    // zero network, bounded). Honest scope: titles only — page bodies are not
    // full-text-searched (decompressing every block per query is out of scope).
    async function dumpSearchTitles() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const wiki = $("dumpread-wiki").value.trim();
      const q = $("dumpread-title").value.trim();
      const out = $("dumpread-out");
      if (!wiki) { out.innerHTML = `<div class="note err">${esc(t("No readable dump yet — download a multistream dump above; its index rides along automatically."))}</div>`; return; }
      if (!q) { out.innerHTML = `<div class="note err">${esc(t("Enter a page title."))}</div>`; return; }
      out.textContent = t("Loading…");
      try {
        const d = await api(`/api/wiki/dumps/search?wiki=${encodeURIComponent(wiki)}&q=${encodeURIComponent(q)}`);
        const items = d.items || [];
        if (!items.length) {
          out.innerHTML = `<div class="note">${esc(t("No matching titles in this dump's index."))} <span class="muted">(${d.scanned} ${t("index lines scanned")}${d.capped ? ", " + esc(t("scan capped")) : ""})</span></div>`;
          return;
        }
        const rows = items.map(it =>
          `<li><a href="#" onclick="$('dumpread-title').value=${esc(JSON.stringify(it.title))};dumpReadPage();return false">${esc(it.title)}</a></li>`).join("");
        out.innerHTML = `<div class="card"><div class="muted small">${esc(t("Title matches in your downloaded dump — click one to read its wikitext. Bodies are not full-text-searched."))} <span class="muted">(${d.scanned} ${t("index lines scanned")}${d.capped ? ", " + esc(t("scan capped")) : ""})</span></div><ul>${rows}</ul></div>`;
      } catch (e) { out.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    async function dumpReadPage() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const wiki = $("dumpread-wiki").value.trim();
      const title = $("dumpread-title").value.trim();
      const out = $("dumpread-out");
      if (!wiki) { out.innerHTML = `<div class="note err">${esc(t("No readable dump yet — download a multistream dump above; its index rides along automatically."))}</div>`; return; }
      if (!title) { out.innerHTML = `<div class="note err">${esc(t("Enter a page title."))}</div>`; return; }
      out.textContent = t("Loading…");
      try {
        const d = await api(`/api/wiki/dumps/page?wiki=${encodeURIComponent(wiki)}&title=${encodeURIComponent(title)}`);
        if (!d.found) {
          let msg;
          if (d.reason === "title-not-in-index") {
            msg = `${t("This title is not in the dump's index.")} <span class="muted">(${d.index_lines_scanned} ${t("index lines scanned")}, ${d.scan_seconds}s)</span>`;
          } else if (d.reason === "no-multistream-dump" || d.reason === "no-index") {
            msg = esc(t("No readable dump for this edition: the multistream file or its index is missing."))
              + (d.legacy_file_present ? " " + esc(t("An older single-stream file exists but cannot be random-accessed — re-download to enable reading.")) : "");
          } else {
            msg = esc(d.reason || "unreadable");
          }
          out.innerHTML = `<div class="note err">${msg}</div>`;
          return;
        }
        const meta = [
          d.match === "case-insensitive" ? t("Found via case-insensitive match.") : "",
          d.rev_timestamp ? `${t("dump revision of")} ${esc(d.rev_timestamp.slice(0,10))}` : "",
          `${d.index_lines_scanned} ${t("index lines scanned")} · ${d.scan_seconds}s`
        ].filter(Boolean).join(" · ");
        out.innerHTML = `<div class="card">
          <h4>${esc(d.title)} <span class="muted" style="font-weight:normal">(${esc(d.wiki)})</span></h4>
          <div class="muted small" title="${esc(d.method || "")}">${meta}</div>
          <div class="muted small">${esc(t("Raw wikitext (unrendered), extracted locally from your downloaded dump — no network call."))}</div>
          <pre style="max-height:420px;overflow:auto;white-space:pre-wrap;margin-top:6px">${esc(d.wikitext)}</pre>
        </div>`;
      } catch (e) { out.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }

    // -- Full-text search over downloaded dump BODIES (local, zero network) --- //
    // Unlike "Read a page" (titles only), this searches page CONTENT that a prior
    // index build swept. The index is a disposable side-file beside the dumps
    // (rebuildable, excluded from backups). An edition must be indexed first; a hit
    // opens in the local dump reader above (a snapshot as of the dump date). Reuses
    // GET /api/wiki/dumps/fts-search + /api/wiki/dumps/index (status/build/cancel/clear).
    let _dumpFtsPoll = null;
    async function loadDumpIndexStatus() {
      const box = $("dumpfts-index"); if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/wiki/dumps/index");
        _renderDumpIndexStatus(d);
        // Keep polling while a build runs so progress + the indexed list update on
        // their own; stop as soon as it settles (one interval at a time).
        if (d.build && d.build.state === "running") {
          if (!_dumpFtsPoll) _dumpFtsPoll = setInterval(loadDumpIndexStatus, 2500);
        } else if (_dumpFtsPoll) { clearInterval(_dumpFtsPoll); _dumpFtsPoll = null; }
      } catch (e) { box.textContent = t("Full-text index status unavailable."); }
    }
    function _renderDumpIndexStatus(d) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("dumpfts-index"); if (!box) return;
      const eds = d.editions || [];
      // Build-edition select = editions with a downloaded multistream dump (the
      // readable set loadReadableDumps() already populated in #dumpread-wiki).
      const bsel = $("dumpfts-build-wiki");
      if (bsel) {
        const rsel = $("dumpread-wiki");
        const readable = rsel ? [...rsel.options].map(o => o.value).filter(Boolean) : [];
        const cur = bsel.value;
        bsel.innerHTML = readable.length
          ? readable.map(w => `<option value="${esc(w)}">${esc(w)}</option>`).join("")
          : `<option value="">—</option>`;
        if (cur && readable.includes(cur)) bsel.value = cur;
      }
      // Search-edition filter = indexed editions + an "all indexed" option.
      const wsel = $("dumpfts-wiki");
      if (wsel) {
        const cur = wsel.value;
        wsel.innerHTML = `<option value="">${esc(t("all indexed"))}</option>`
          + eds.map(e => `<option value="${esc(e.wiki)}">${esc(e.wiki)}</option>`).join("");
        if (cur && eds.some(e => e.wiki === cur)) wsel.value = cur;
      }
      const b = d.build || {};
      let buildLine = "";
      if (b.state === "running") buildLine = `<span class="pill">${esc(t("indexing"))} ${esc(b.wiki || "")} · ${esc(String(b.pages || 0))} ${esc(t("pages"))}</span>`;
      else if (b.state === "error") buildLine = `<span class="pill err">${esc(t("index build failed"))}${b.error ? ": " + esc(b.error) : ""}</span>`;
      else if (b.state === "cancelled") buildLine = `<span class="pill warn">${esc(t("index build cancelled"))}</span>`;
      const coverage = eds.length
        ? eds.map(e => `${esc(e.wiki)} (${esc(String(e.pages))} ${esc(t("pages"))})`).join(" · ")
        : esc(t("No editions indexed yet — pick one above and Build index."));
      box.innerHTML = `${buildLine ? buildLine + " " : ""}<span>${coverage}</span>`;
    }
    async function dumpFtsBuild() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const wiki = (($("dumpfts-build-wiki") || {}).value || "").trim();
      if (!wiki) { toast(t("Pick a downloaded edition to index."), "err"); return; }
      try {
        await api("/api/wiki/dumps/index", {method:"POST", body: JSON.stringify({wiki})});
        toast(t("Building the full-text index…"));
        loadDumpIndexStatus();
      } catch (e) { toast(e.message, "err"); }   // 409 already running / 404 no dump — surfaced honestly
    }
    async function dumpFtsCancel() {
      try { await api("/api/wiki/dumps/index/cancel", {method:"POST"}); loadDumpIndexStatus(); }
      catch (e) { toast(e.message, "err"); }
    }
    async function dumpFtsClear() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const wiki = (($("dumpfts-wiki") || {}).value || "").trim();   // "" = all editions
      const which = wiki || t("all editions");
      if (!confirm(t("Clear the full-text index for {w}? It is rebuildable from the local dump.").replace("{w}", which))) return;
      try {
        await api("/api/wiki/dumps/index" + (wiki ? "?wiki=" + encodeURIComponent(wiki) : ""), {method:"DELETE"});
        toast(t("Index cleared.")); loadDumpIndexStatus();
        const out = $("dumpfts-out"); if (out) out.innerHTML = "";
      } catch (e) { toast(e.message, "err"); }
    }
    async function dumpFtsSearch() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const q = (($("dumpfts-q") || {}).value || "").trim();
      const wiki = (($("dumpfts-wiki") || {}).value || "").trim();
      const out = $("dumpfts-out"); if (!out) return;
      if (!q) { out.innerHTML = `<div class="note err">${esc(t("Enter a full-text query."))}</div>`; return; }
      out.textContent = t("Loading…");
      try {
        const url = "/api/wiki/dumps/fts-search?q=" + encodeURIComponent(q)
          + (wiki ? "&wiki=" + encodeURIComponent(wiki) : "") + "&limit=30";
        const d = await api(url);
        const items = d.items || [];
        if (!items.length) {
          const msg = d.reason === "no-index"
            ? t("No full-text index yet — pick a downloaded edition above and Build index first.")
            : d.reason === "search-error"
              ? t("The query could not be parsed — try plain words or AND/OR/NOT.")
              : t("No matches in your indexed dump bodies.");
          out.innerHTML = `<div class="note">${esc(msg)}</div>`;
          return;
        }
        const rows = items.map(it => {
          const link = `<a href="#" onclick="dumpFtsOpen(${esc(JSON.stringify(it.wiki))},${esc(JSON.stringify(it.title))});return false">${esc(it.title)}</a>`;
          const snip = it.snippet ? `<div class="muted small">${esc(it.snippet)}</div>` : "";
          return `<li>${link} <span class="muted">(${esc(it.wiki)})</span>${snip}</li>`;
        }).join("");
        out.innerHTML = `<div class="card"><div class="muted small">${esc(d.note || "")}</div><ul>${rows}</ul></div>`;
      } catch (e) { out.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    // Open a full-text hit in the LOCAL dump reader above (invariant #6: local first) —
    // set the reader's edition + title and render its wikitext inline, then scroll to it.
    function dumpFtsOpen(wiki, title) {
      const sel = $("dumpread-wiki");
      if (sel && ![...sel.options].some(o => o.value === wiki)) {
        const o = document.createElement("option"); o.value = wiki; o.textContent = wiki; sel.appendChild(o);
      }
      if (sel) sel.value = wiki;
      const ti = $("dumpread-title"); if (ti) ti.value = title;
      dumpReadPage();
      const box = $("dumpread-out"); if (box && box.scrollIntoView) box.scrollIntoView({behavior:"smooth", block:"nearest"});
    }

    async function loadWikiPages() {
      try {
        const d = await api("/api/wiki/pages");
        const t = $("wiki-pages");
        t.innerHTML = "<tr><th>Edition</th><th>Title</th><th>Watchlist</th><th>Checked</th><th>Edits</th><th>Flagged</th><th></th></tr>" +
          (d.pages.length ? d.pages.map(p => `<tr>
            <td><strong>${esc(p.wiki)}</strong></td>
            <td>${esc(p.title)}${p.missing
                ? ' <span class="pill err" title="The wiki reports no page with this exact title — check the spelling, or paste the article URL.">page not found</span>'
                : ""}${(p.wiki_categories || []).slice(0, 3).map(c =>
                  ` <span class="pill" style="font-size:10px">${esc(c)}</span>`).join("")}</td>
            <td class="muted">${esc(p.category||"")}</td>
            <td class="muted" style="font-size:12px">${p.last_checked_at?esc(p.last_checked_at.slice(0,16).replace("T"," ")):"never"}</td>
            <td>${p.revisions}</td><td class="muted">${p.flagged}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="openWikiTC(${p.id}, ${esc(JSON.stringify(p.title))}, ${esc(JSON.stringify(p.wiki))})" title="See this page's tracked revision history — the stored edits, newest first, with each diff.">Tracked changes</button>
              <button class="tiny secondary" onclick="trackWikiPage(${p.id})">Track</button>
              <button class="tiny danger" onclick="deleteWikiPage(${p.id}, ${esc(JSON.stringify(p.title))})">Delete</button>
            </td></tr>`).join("")
            : `<tr><td colspan="7" class="muted">No watched pages yet. Add one above.</td></tr>`);
      } catch (e) { toast("Wiki pages: " + e.message, "err"); }
    }

    async function addWikiPage() {
      const body = { wiki: $("wiki-lang").value.trim() || "en", title: $("wiki-title").value.trim(),
                     category: $("wiki-cat").value.trim() || null };
      if (!body.title) { toast("Enter an article title.", "err"); return; }
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Add a watched Wikipedia page (fetches its current revision)"))) return;
      try { await api("/api/wiki/pages", {method:"POST", body: JSON.stringify(body)});
        toast("Page added to watchlist."); $("wiki-title").value=""; loadWikiPages(); loadWiki(); }
      catch (e) { toast(_failMsg("Add failed: {error}", e), "err"); }
    }

    async function deleteWikiPage(id, title) {
      if (!confirm(`Stop watching "${title}"? Its stored revisions are removed.`)) return;
      try { await api("/api/wiki/pages/"+id, {method:"DELETE"}); toast("Removed."); loadWiki(); }
      catch (e) { toast(_failMsg("Delete failed: {error}", e), "err"); }
    }

    const _ores = () => $("wiki-ores").checked ? "true" : "false";

    async function trackWikiPage(id) {
      toast("Fetching revisions… (ethical: UA + maxlag + rate-limited)");
      try {
        const r = await api(`/api/wiki/pages/${id}/track?ores=${_ores()}`, {method:"POST"});
        toast(r.baseline ? "Baseline captured." : `Stored ${r.new} new edit(s), ${r.flagged} flagged.`);
        loadWiki();
      } catch (e) { toast(_failMsg("Track failed: {error}", e), "err"); }
    }

    async function trackWikiNow() {
      $("wiki-progress").textContent = "Tracking watched pages…";
      try {
        const r = await api(`/api/wiki/track-now?ores=${_ores()}`, {method:"POST"});
        $("wiki-progress").textContent = `${r.pages} page(s): ${r.new_revisions} new edit(s), ${r.flagged} flagged.`;
        toast("Tracking complete."); loadWiki();
      } catch (e) { $("wiki-progress").textContent=""; toast(_failMsg("Track now failed: {error}", e), "err"); }
    }

    async function loadWikiChanges() {
      const flagged = $("wiki-flagged-only").checked ? "true" : "false";
      const w = $("wiki-filter-lang").value.trim();
      try {
        const d = await api(`/api/wiki/changes?flagged_only=${flagged}&limit=80` + (w?"&wiki="+encodeURIComponent(w):""));
        const t = $("wiki-changes");
        t.innerHTML = "<tr><th>When</th><th>Edition · Page</th><th>Editor</th><th>Δ bytes</th><th>Reasons</th><th>ORES</th><th></th></tr>" +
          (d.changes.length ? d.changes.map(c => `<tr>
            <td class="muted" style="font-size:12px">${c.timestamp?esc(c.timestamp.slice(0,16).replace("T"," ")):"—"}</td>
            <td><strong>${esc(c.wiki)}</strong> · ${esc(c.title)}</td>
            <td class="muted">${esc(c.editor||"—")}${c.editor_anon?' <span class="pill warn">anon</span>':''}</td>
            <td class="${(c.delta_bytes||0)<0?'':''}" style="color:${(c.delta_bytes||0)<0?'var(--err)':'var(--ok)'}">${c.delta_bytes==null?'—':(c.delta_bytes>0?'+':'')+c.delta_bytes}</td>
            <td>${(c.flag_reasons||[]).map(r=>`<span class="pill warn">${esc(r)}</span>`).join(" ")}</td>
            <td class="muted">${c.ores_damaging!=null?'dmg '+c.ores_damaging.toFixed(2):'—'}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="viewWikiDiff(${c.id})">Diff</button>
              <a class="tiny" href="${esc(c.diff_url)}" target="_blank" rel="noopener">live</a></td></tr>`).join("")
            : `<tr><td colspan="7" class="muted">No changes yet. Add pages and press “Track now”.</td></tr>`);
      } catch (e) { toast("Wiki changes: " + e.message, "err"); }
    }

    async function viewWikiDiff(id) {
      const el = $("wiki-diff");
      el.innerHTML = '<div class="muted">Loading diff…</div>';
      try {
        const d = await api("/api/wiki/revisions/"+id);
        const lines = (d.diff||"(no stored diff)").split("\n").map(l => {
          const cls = l.startsWith("+") ? "ok" : l.startsWith("-") ? "err" : "muted";
          return `<div style="color:var(--${cls});white-space:pre-wrap;font-size:13px">${esc(l)}</div>`;
        }).join("");
        el.innerHTML = `<div class="note" style="max-width:none">
          <div class="muted" style="font-size:12px;margin-bottom:6px">${esc(d.wiki)} · ${esc(d.title)} · rev ${d.revid}
            · <a href="${esc(d.diff_url)}" target="_blank" rel="noopener">view on Wikipedia</a></div>${lines}</div>`;
      } catch (e) { el.innerHTML=""; toast("Diff: " + e.message, "err"); }
    }

    // --- Wikipedia tracked-changes view (wave 5) --------------------------- //
    // The per-page tracked revision history the "tracked-changes tab" ruling asks
    // for (Wikipedia-as-a-living-source). Reads GET /api/wiki/pages/{id}/revisions —
    // the STORED tracked slice (newest first): each revision's compact +added/-removed
    // diff captured at track time (truncated per side, NOT a live re-diff), the
    // editor/comment metadata, and a "full text stored" marker for revisions whose
    // exact text is on this machine. Honest window (showing N of M) + a VISIBLE caveat
    // mirroring the endpoint method; the flagged-only toggle reuses the endpoint param.
    // Counts only, no score; all strings flow through the i18n engine.
    let _wikiTc = { id: null, title: "", wiki: "" };
    function openWikiTC(id, title, wiki) {
      _wikiTc = { id: id, title: title || "", wiki: wiki || "" };
      const ttl = $("wiki-tc-title");
      if (ttl) ttl.textContent = (_wikiTc.wiki ? _wikiTc.wiki + " · " : "") + _wikiTc.title;
      const fo = $("wiki-tc-flagged"); if (fo) fo.checked = false;
      const dlg = $("wiki-tc");
      if (dlg && typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
      loadWikiTC();
    }

    function _wikiRevRow(r, t) {
      const ts = r.timestamp ? esc(r.timestamp.slice(0, 16).replace("T", " ")) : "—";
      const editor = esc(r.editor || "—");
      const pills = [];
      if (r.editor_anon) pills.push(`<span class="pill warn">${esc(t("anon"))}</span>`);
      if (r.minor) pills.push(`<span class="pill">${esc(t("minor"))}</span>`);
      if (r.bot) pills.push(`<span class="pill">${esc(t("bot"))}</span>`);
      if (r.has_full_text) pills.push(`<span class="pill ok" title="${esc(t("The exact text of this revision is stored on this machine."))}">${esc(t("full text stored"))}</span>`);
      const pill = pills.length ? " " + pills.join(" ") : "";
      const delta = (r.delta_bytes == null) ? "" :
        `<span style="color:${r.delta_bytes < 0 ? 'var(--err)' : 'var(--ok)'}">${r.delta_bytes > 0 ? '+' : ''}${r.delta_bytes}</span>`;
      const reasons = (r.flag_reasons || []).filter(Boolean)
        .map(x => `<span class="pill warn">${esc(x)}</span>`).join(" ");
      const comment = r.comment ? `<div class="muted" style="font-size:12px;margin-top:2px">${esc(r.comment)}</div>` : "";
      const raw = (r.diff || "").trim();
      // Each diff line is the stored +added / -removed summary (same format the
      // changes-feed diff uses); context/other lines render muted. Never a live re-diff.
      const diff = raw
        ? raw.split("\n").map(l => {
            const cls = l.charAt(0) === "+" ? "ok" : l.charAt(0) === "-" ? "err" : "muted";
            return `<div style="color:var(--${cls});white-space:pre-wrap;font-size:12px">${esc(l)}</div>`;
          }).join("")
        : `<div class="muted" style="font-size:12px">${esc(t("No stored diff (no parent, or tracked without diffs)."))}</div>`;
      return `<div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="display:flex;align-items:baseline;justify-content:space-between;gap:8px;flex-wrap:wrap">
          <div><span class="muted" style="font-size:12px">${ts}</span> · <strong>${editor}</strong>${pill}</div>
          <div>${delta}</div></div>
        ${reasons ? `<div style="margin-top:3px">${reasons}</div>` : ""}
        ${comment}
        <div style="margin-top:6px">${diff}</div></div>`;
    }

    async function loadWikiTC() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const body = $("wiki-tc-body"), meth = $("wiki-tc-method");
      if (!body || _wikiTc.id == null) return;
      const flaggedEl = $("wiki-tc-flagged");
      const flagged = (flaggedEl && flaggedEl.checked) ? "true" : "false";
      body.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      if (meth) meth.textContent = "";
      try {
        const d = await api(`/api/wiki/pages/${_wikiTc.id}/revisions?limit=50&flagged_only=${flagged}&include_diff=true`);
        const revs = d.revisions || [];
        if (!revs.length) {
          // Honest empty state (flagged-aware), never a blank pane.
          body.innerHTML = `<div class="muted">${esc(t(flagged === "true"
            ? "No flagged tracked revisions stored for this page yet."
            : "No tracked revisions stored for this page yet."))}</div>`;
        } else {
          // Honest window: showing `count` of `total` — the endpoint discloses it is a slice.
          const cap = `<div class="muted" style="margin-bottom:8px">${esc(t("Showing"))} ${d.count} / ${d.total} ${esc(t("tracked revisions"))}</div>`;
          body.innerHTML = cap + revs.map(r => _wikiRevRow(r, t)).join("");
        }
        // VISIBLE caveat (keyed ×12) mirroring the endpoint's method — never hidden.
        if (meth) meth.textContent = t("The tracked slice of edits stored on this machine, newest first — not necessarily every historical revision. Each diff is the compact added / removed summary captured when the edit was tracked (truncated per side), not a live re-diff. Counts only, no score.");
      } catch (e) {
        // Additive surface — degrade quietly, never throw.
        body.innerHTML = `<div class="muted">${esc(t("Could not load") + ": " + e.message)}</div>`;
      }
    }

    // --- Search-tab time-range control (ooTimeScope reuse) ----------------- //
    // There is no lightweight corpus-span endpoint exposed to the chrome, so the
    // absolute bounds default to [today-5y, today] (a sensible bounded range).
    // The SELECTED window defaults to the WHOLE span (min..max) so a fresh search
    // excludes nothing; searchTimeScopeParams only forwards a bound the user has
    // narrowed off min/max. Built once on first Search-tab open (idempotent).
