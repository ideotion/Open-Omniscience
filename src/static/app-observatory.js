/* app-observatory.js — the Observatory (the corpus as a night sky)

   Design of record: docs/design/OBSERVATORY_DESIGN.md (maintainer-ruled 2026-07-18,
   superseding Q5a). This module is the WIRING; the geometry and the two refusals
   live in src/static/oosky.js, which is pure and node-testable.

   PART OF THE UI ENGINE. The modules share ONE global scope -- there is no module
   system here -- and they load in the order index.html lists them, boot last. Add
   new code inside the module it belongs to, and never reorder a declaration across
   a module boundary (a const/let would hit a TDZ error at load).

   THE SURFACE'S OWN HONESTY OBLIGATIONS, all of them visible by default:

   * The RANKED TABLE is rendered, in full, beside the sky -- not behind a toggle.
     It is the canonical access path (invariant #8); the sky is a redundant lens
     over it. Both orders come from ooSky.rankedGalaxies, so they cannot drift.
   * WHICH RADIAL SCALE IS IN FORCE is printed under the canvas, because ooSky
     chooses log or linear from the data and a reader is owed the one that is
     actually drawn (the recorded logY defect put a "equal ratios are equal
     distances" hint above a chart that had drawn linear).
   * "N galaxies plotted · N not observed yet · M keywords in the nebula" is the
     anti-capping disclosure, on the surface itself, naming every population the
     picture does not draw.
   * The TREND lens colours a galaxy only when `growth_is_ratio` is true. When it
     is false, `growth` is the RECENT COUNT rather than a multiple -- the flag
     exists precisely so a consumer can tell a real ratio from the sentinel -- so
     those galaxies render UNMEASURED and are never painted red. A cooling colour
     derived from a count would be a fabricated decline.
*/

    // The trend lens's bands, stated on the surface rather than left implicit.
    // A ratio inside [_OBS_COOL, _OBS_WARM] is "steady": without a dead band the
    // lens paints noise as weather on a corpus whose windows hold single digits.
    const _OBS_COOL = 0.8;
    const _OBS_WARM = 1.25;

    // Languages get a categorical colour slot. FIVE are coloured and the rest
    // share one "other" slot, disclosed with its n -- the same cardinality guard
    // the design applies to arms, for the same reason: the theme-derived --fig-N
    // set has six slots, and silently wrapping a seventh language onto slot 1
    // would make two languages indistinguishable with nothing saying so.
    const _OBS_LANG_SLOTS = 5;

    const _obs = {
      payload: null, layout: null, measure: "distinct_sources", lens: "language",
      view: {w: 0, h: 0, ox: 0, oy: 0, scale: 1, hover: null, focus: null},
      langSlots: {}, otherLangs: [], raf: 0, wired: false, err: null,
    };

    // The four switchable radial measures. Keys are the payload's own
    // `measures` fields -- never a blend, never a computed "importance".
    function _obsMeasures() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return [
        {key: "distinct_sources", label: t("Sources")},
        {key: "mentions", label: t("Mentions")},
        {key: "distinct_languages", label: t("Languages")},
        {key: "distinct_keywords", label: t("Keywords")},
      ];
    }
    function _obsMeasureLabel(key) {
      const m = _obsMeasures().find((x) => x.key === key);
      return m ? m.label : key;
    }

    async function loadObservatory() {
      const host = $("sky-stage");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const status = $("sky-status");
      if (status) status.textContent = t("Loading…");
      try {
        _obs.payload = await api("/api/insights/observatory");
        _obs.err = null;
      } catch (e) {
        _obs.err = e && e.message ? e.message : String(e);
        _obs.payload = null;
      }
      _obsWire();
      _obsRender();
    }

    // One-time listener wiring. Kept idempotent (`_obs.wired`) because the tab
    // loader runs once per page load but a language or theme switch re-renders.
    function _obsWire() {
      if (_obs.wired) return;
      _obs.wired = true;
      const cv = $("sky-canvas");
      const mSel = $("sky-measure");
      const lSel = $("sky-lens");
      if (mSel) mSel.addEventListener("change", () => { _obs.measure = mSel.value; _obsRender(); });
      if (lSel) lSel.addEventListener("change", () => { _obs.lens = lSel.value; _obsRender(); });
      if (cv) {
        cv.addEventListener("mousemove", _obsMove);
        cv.addEventListener("mouseleave", () => { _obs.view.hover = null; _obsPaint(); _obsReadout(); });
        cv.addEventListener("click", _obsClick);
        cv.addEventListener("wheel", _obsWheel, {passive: false});
        cv.addEventListener("mousedown", _obsDragStart);
        cv.addEventListener("keydown", _obsKey);
        cv.addEventListener("dblclick", () => {
          _obs.view.ox = 0; _obs.view.oy = 0; _obs.view.scale = 1; _obsPaint();
        });
      }
      const reset = $("sky-reset");
      if (reset) reset.addEventListener("click", () => {
        _obs.view.ox = 0; _obs.view.oy = 0; _obs.view.scale = 1; _obsPaint();
      });
      // The LANGUAGE-switch re-render lives in app-boot.js's ONE canonical
      // oo:langchange listener, beside the map, the briefing and the Composition
      // figures -- not here. A second listener would be a second enumerator of
      // "what must re-render on a language switch", and the one place that already
      // answers that question is the place to answer it. (It also displaced the
      // first-occurrence needle two existing guards use to find THE listener, which
      // is how the duplicate was caught.)
      window.addEventListener("resize", () => _obsPaint());
    }

    // ----- colour ------------------------------------------------------------ //

    /**
     * The galaxy's dominant language = the one with the most mentions. Ties break
     * on the code so the sky is deterministic. Returns null when the galaxy has
     * no language breakdown at all, which renders as the unmeasured colour and
     * says so in the table -- never as an arbitrary first entry.
     */
    function _obsTopLang(g) {
      const langs = g.languages || {};
      let best = null, bestN = -1;
      for (const code of Object.keys(langs).sort()) {
        const n = langs[code] || 0;
        if (n > bestN) { bestN = n; best = code; }
      }
      return best;
    }

    /** Assign the top-N languages a colour slot; the rest share the "other" slot. */
    function _obsAssignLangSlots(galaxies) {
      const tally = {};
      for (const g of galaxies) {
        const c = _obsTopLang(g);
        if (c) tally[c] = (tally[c] || 0) + 1;
      }
      const ordered = Object.keys(tally).sort((a, b) => tally[b] - tally[a] || (a < b ? -1 : 1));
      _obs.langSlots = {};
      _obs.otherLangs = [];
      ordered.forEach((code, i) => {
        if (i < _OBS_LANG_SLOTS) _obs.langSlots[code] = i + 1;   // --fig-1..--fig-5
        else _obs.otherLangs.push(code);
      });
    }

    function _obsTheme() {
      const V = window.ooViz;
      const css = (n, fb) => (V && V.readCssVar ? V.readCssVar(n) : "") || fb;
      const fig = [];
      for (let i = 1; i <= 6; i++) fig.push(css("--fig-" + i, "#888"));
      const muted = css("--muted", "#888");
      const th = {
        bg: css("--panel2", "#14181f"),
        fg: css("--fg", "#e8ebf0"),
        muted: muted,
        border: css("--border", "#28303d"),
        edge: css("--fig-6", muted),
        warm: css("--fig-1", "#5b9dd9"),   // rising  — measured increase
        cool: css("--fig-4", "#c0392b"),   // cooling — measured decrease
        tickFont: "11px " + (css("--ff", "system-ui") || "system-ui"),
        fig: fig,
      };
      th.colorOf = (g) => _obsColorOf(g, th);
      return th;
    }

    function _obsColorOf(g, th) {
      if (_obs.lens === "trend") {
        const r = g.rate || {};
        // The sentinel guard: growth is only a multiple when growth_is_ratio is
        // true. Otherwise it is the recent COUNT, and colouring it would invent a
        // trend from a number that is not one.
        if (!r.growth_is_ratio) return th.muted;
        if (r.growth >= _OBS_WARM) return th.warm;
        if (r.growth <= _OBS_COOL) return th.cool;
        return th.fg;                       // steady stays neutral (cross-time guard)
      }
      const code = _obsTopLang(g);
      if (!code) return th.muted;
      const slot = _obs.langSlots[code];
      return slot ? th.fig[slot - 1] : th.fig[5];
    }

    // ----- render ------------------------------------------------------------ //

    /**
     * The plotted radius, derived from the canvas box rather than fixed, because
     * everything outside the value scale has to fit too: the "not observed yet"
     * ring, the nebula band and the wedge LABELS sit at 1.05, 1.13 and 1.22 of it.
     * A fixed radius drew the labels off-canvas on a narrow viewport, which turns
     * a labelled categorical axis into an unlabelled one with nothing to show for
     * it. The label ring is the binding constraint, so solve for that.
     */
    function _obsOuterFor(w, h) {
      const half = Math.min(w, h) / 2;
      return Math.max(80, Math.floor((half - 16) / 1.22));
    }

    function _obsRender() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const status = $("sky-status");
      if (_obs.err) {
        if (status) status.textContent = t("Could not load this figure.");
        return;
      }
      if (!_obs.payload) return;
      if (status) status.textContent = "";
      const mSel = $("sky-measure");
      if (mSel && !mSel.options.length) {
        for (const m of _obsMeasures()) {
          const o = document.createElement("option");
          o.value = m.key; o.textContent = m.label;
          mSel.appendChild(o);
        }
        mSel.value = _obs.measure;
      }
      _obsAssignLangSlots(_obs.payload.galaxies || []);
      _obs.layout = window.ooSky.skyLayout(_obs.payload, {
        measure: _obs.measure, rInner: 46, rOuter: _obs.rOuter || 240,
      });
      _obs.view.focus = null;
      _obs.view.hover = null;
      _obsPaint();
      _obsLegend();
      _obsDisclosure();
      _obsTable();
      _obsReadout();
      _obsAria();
    }

    /** rAF-coalesced repaint. Static when idle — there is no animation loop. */
    function _obsPaint() {
      if (_obs.raf) return;
      _obs.raf = requestAnimationFrame(() => {
        _obs.raf = 0;
        _obsPaintNow();
      });
    }
    function _obsPaintNow() {
      const cv = $("sky-canvas");
      if (!cv || !_obs.layout || !window.ooViz) return;
      const box = cv.parentElement ? cv.parentElement.getBoundingClientRect() : null;
      const w = Math.max(320, Math.round((box ? box.width : 720)));
      const h = Math.max(320, Math.min(640, Math.round(w * 0.62)));
      const ctx = window.ooViz.setupCanvas(cv, w, h);
      _obs.view.w = w;
      _obs.view.h = h;
      // Re-lay-out when the box changes the plotted radius. The layout owns every
      // coordinate, so painting a layout built for a different radius would put
      // the marks and their own orbit gridlines on different scales.
      const want = _obsOuterFor(w, h);
      if (want !== _obs.rOuter) {
        _obs.rOuter = want;
        if (_obs.payload) {
          _obs.layout = window.ooSky.skyLayout(_obs.payload, {
            measure: _obs.measure, rInner: Math.max(24, Math.round(want * 0.19)), rOuter: want,
          });
        }
      }
      if (!_obs.layout) return;
      window.ooSky.drawSky(ctx, _obs.layout, _obsTheme(), _obs.view);
    }

    function _obsLegend() {
      const host = $("sky-legend");
      if (!host || !_obs.layout) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
      const th = _obsTheme();
      const L = _obs.layout;
      let html = "";

      // Size legend. Area encodes mentions, and area is the channel a reader
      // under-estimates, so REAL reference values are the condition of using it.
      const stars = L.referenceStars || [];
      if (stars.length) {
        html += `<div class="sky-leg"><span class="sky-leg-h">${esc(t("Reference stars"))}</span>` +
          stars.map((s) =>
            `<span class="sky-ref"><svg width="${Math.ceil(s.r * 2) + 4}" height="26" aria-hidden="true">` +
            `<circle cx="${(Math.ceil(s.r * 2) + 4) / 2}" cy="13" r="${s.r}" fill="${esc(th.fg)}"></circle></svg>` +
            `<span>${esc(fmtNum(s.value))}</span></span>`
          ).join("") + `</div>`;
        if (L.sizeFloorValue) {
          // The size channel's own cap, named rather than left to flatten the
          // bottom of the distribution silently.
          html += `<div class="hint muted">${esc(tf(
            "Star size saturates below {n} mentions — smaller galaxies are drawn at the same minimum size.",
            {n: fmtNum(L.sizeFloorValue)}
          ))}</div>`;
        }
      }

      // Colour legend. Colour is never the only signal — every galaxy also
      // carries its name, its radial position and its row in the table below.
      if (_obs.lens === "trend") {
        html += `<div class="sky-leg"><span class="sky-leg-h">${esc(t("Trend"))}</span>` +
          `<span class="sky-ref"><i class="sky-sw" style="background:${esc(th.warm)}"></i>${esc(t("Rising"))}</span>` +
          `<span class="sky-ref"><i class="sky-sw" style="background:${esc(th.fg)}"></i>${esc(t("Steady"))}</span>` +
          `<span class="sky-ref"><i class="sky-sw" style="background:${esc(th.cool)}"></i>${esc(t("Cooling"))}</span>` +
          `<span class="sky-ref"><i class="sky-sw" style="background:${esc(th.muted)}"></i>${esc(t("Not comparable"))}</span>` +
          `</div>`;
      } else {
        const codes = Object.keys(_obs.langSlots);
        html += `<div class="sky-leg"><span class="sky-leg-h">${esc(t("Language"))}</span>` +
          codes.map((c) =>
            `<span class="sky-ref"><i class="sky-sw" style="background:${esc(th.fig[_obs.langSlots[c] - 1])}"></i>` +
            `${esc(ooLangName(c, c))}</span>`
          ).join("") +
          (_obs.otherLangs.length
            ? `<span class="sky-ref"><i class="sky-sw" style="background:${esc(th.fig[5])}"></i>` +
              `${esc(tf("Other languages ({n})", {n: fmtNum(_obs.otherLangs.length)}))}</span>`
            : "") +
          `</div>`;
      }
      host.innerHTML = html;
    }

    /**
     * The scale note + the anti-capping population lines. Both are statements the
     * picture cannot make for itself, so they are printed, never hovered.
     */
    function _obsDisclosure() {
      const host = $("sky-disclosure");
      if (!host || !_obs.layout) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
      const L = _obs.layout;
      const S = L.scale;
      const label = _obsMeasureLabel(_obs.measure);
      let scaleNote;
      if (S.mode === "log") {
        scaleNote = tf(
          "Distance from centre: {measure}, logarithmic — equal ratios are equal distances. Centre is the largest. Orbit rings are labelled.",
          {measure: label}
        );
      } else if (S.mode === "linear") {
        // Say WHY the log mode is not on offer. A control that stays enabled
        // while the renderer draws something else puts two statements on screen.
        scaleNote = tf(
          "Distance from centre: {measure}, linear from zero — the largest value here is {hi}, under one full decade, so a logarithmic radius would spread a fraction of a decade across the whole sky. Centre is the largest.",
          {measure: label, hi: fmtNum(S.hi)}
        );
      } else {
        scaleNote = tf(
          "No galaxy has a {measure} count above zero yet, so there is no scale to draw.",
          {measure: label}
        );
      }
      const neb = L.nebula || {};
      const lines = [
        `<div class="hint">${esc(scaleNote)}</div>`,
        `<div class="hint">${esc(tf(
          "Plotted: {plotted} galaxies · not observed in this corpus yet: {unplaced} · keywords in the nebula, outside every curated galaxy: {nebula} of {total}.",
          {
            plotted: fmtNum(L.galaxies.length),
            unplaced: fmtNum(L.unplaced.length),
            nebula: fmtNum(neb.nebula_keywords || 0),
            total: fmtNum(neb.total_keywords || 0),
          }
        ))}</div>`,
      ];
      if (L.edges.length) {
        lines.push(`<div class="hint">${esc(tf(
          "Constellation lines: {n} drawn from a shared member keyword — a measured overlap, never nearness on screen.",
          {n: fmtNum(L.edges.length)}
        ))}</div>`);
      }
      host.innerHTML = lines.join("");
    }

    /**
     * The ranked table. Rendered in FULL — every galaxy, plotted or not — because
     * a displayed figure is never secretly a cap. It is the canonical view and
     * the screen-reader path at once, so it is a real table and not a caption.
     */
    function _obsTable() {
      const host = $("sky-table");
      if (!host || !_obs.layout) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const rows = window.ooSky.rankedGalaxies(_obs.layout);
      const head =
        `<tr><th>${esc(t("Rank"))}</th><th>${esc(t("Galaxy"))}</th><th>${esc(t("Domain"))}</th>` +
        `<th>${esc(_obsMeasureLabel(_obs.measure))}</th><th>${esc(t("Mentions"))}</th>` +
        `<th>${esc(t("Language"))}</th><th>${esc(t("Trend"))}</th></tr>`;
      const body = rows.map((g, i) => {
        const placed = g.radius !== undefined;
        const code = _obsTopLang(g);
        return `<tr><td>${placed ? i + 1 : "—"}</td>` +
          `<td><button type="button" class="ghost tiny" data-obs-open="${esc(g.name)}">${esc(g.name)}</button></td>` +
          `<td>${esc(g.domain || "")}</td>` +
          `<td>${placed ? esc(fmtNum(g.value)) : `<span class="muted">${esc(t("Not observed in this corpus yet"))}</span>`}</td>` +
          `<td>${esc(fmtNum(g.mentions || 0))}</td>` +
          `<td>${code ? esc(ooLangName(code, code)) : `<span class="muted">${esc(t("No data yet"))}</span>`}</td>` +
          `<td>${esc(_obsTrendText(g))}</td></tr>`;
      }).join("");
      host.innerHTML = `<table class="sky-tbl"><thead>${head}</thead><tbody>${body}</tbody></table>`;
      host.querySelectorAll("[data-obs-open]").forEach((b) =>
        b.addEventListener("click", () => openAnalysisFor(b.dataset.obsOpen, {source: "observatory"})));
    }

    /**
     * The trend cell. When `growth_is_ratio` is false the payload's `growth` is
     * the recent COUNT standing in for a ratio, so the cell says the comparison
     * could not be made rather than printing a number that looks like a multiple.
     */
    function _obsTrendText(g) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
      const r = g.rate || {};
      if (!r.growth_is_ratio) return t("Not comparable — no earlier window to compare with");
      return tf("{x}× vs the previous window", {x: fmtNum(r.growth, 2)});
    }

    // ----- interaction ------------------------------------------------------- //

    function _obsPos(ev) {
      const cv = $("sky-canvas");
      const r = cv.getBoundingClientRect();
      return {x: ev.clientX - r.left, y: ev.clientY - r.top};
    }
    function _obsMove(ev) {
      if (!_obs.layout) return;
      const p = _obsPos(ev);
      const hit = window.ooSky.hitTest(_obs.layout, _obs.view, p.x, p.y);
      if (hit !== _obs.view.hover) {
        _obs.view.hover = hit;
        _obsPaint();
        _obsReadout();
      }
    }
    function _obsClick(ev) {
      if (!_obs.layout) return;
      const p = _obsPos(ev);
      const hit = window.ooSky.hitTest(_obs.layout, _obs.view, p.x, p.y);
      if (hit) openAnalysisFor(hit.name, {source: "observatory"});
    }
    function _obsWheel(ev) {
      ev.preventDefault();
      const k = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
      _obs.view.scale = window.ooViz.clamp(_obs.view.scale * k, 0.4, 6);
      _obsPaint();
    }
    function _obsDragStart(ev) {
      const start = {x: ev.clientX, y: ev.clientY, ox: _obs.view.ox, oy: _obs.view.oy};
      const move = (e) => {
        _obs.view.ox = start.ox + (e.clientX - start.x);
        _obs.view.oy = start.oy + (e.clientY - start.y);
        _obsPaint();
      };
      const up = () => {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    }

    /**
     * Keyboard traversal walks the RANKED order, not the pixels — so a keyboard
     * user reads the sky in the same order the table presents it and never
     * depends on pointer geometry (accessibility rule A5).
     */
    function _obsKey(ev) {
      if (!_obs.layout) return;
      const list = _obs.layout.galaxies.slice().sort((a, b) =>
        b.value - a.value || (a.name < b.name ? -1 : 1));
      if (!list.length) return;
      const cur = list.indexOf(_obs.view.focus);
      let next = cur;
      if (ev.key === "ArrowRight" || ev.key === "ArrowDown") next = Math.min(list.length - 1, cur + 1);
      else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") next = Math.max(0, cur - 1);
      else if (ev.key === "Home") next = 0;
      else if (ev.key === "End") next = list.length - 1;
      else if (ev.key === "Enter" || ev.key === " ") {
        if (_obs.view.focus) { ev.preventDefault(); openAnalysisFor(_obs.view.focus.name, {source: "observatory"}); }
        return;
      } else return;
      ev.preventDefault();
      _obs.view.focus = list[next < 0 ? 0 : next];
      _obsPaint();
      _obsReadout();
    }

    /** The hover/focus readout — one region serving both pointer and keyboard. */
    function _obsReadout() {
      const host = $("sky-readout");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
      const g = _obs.view.hover || _obs.view.focus;
      if (!g) {
        host.innerHTML = `<span class="muted">${esc(t("Point at a galaxy, or use the arrow keys, to see its numbers."))}</span>`;
        return;
      }
      const code = _obsTopLang(g);
      const parts = [
        `<strong>${esc(g.name)}</strong>`,
        `<span class="muted">${esc(g.domain || "")}</span>`,
        esc(tf("{measure}: {v}", {measure: _obsMeasureLabel(_obs.measure), v: fmtNum(g.value)})),
      ];
      // Mentions is ALSO the size channel, so it is always worth stating -- but
      // when it is the radial measure too the line above already said it, and the
      // first cut printed "Mentions: 263 - Mentions: 263". The duplicate was
      // invisible in the source and obvious in the rendered readout.
      if (_obs.measure !== "mentions") {
        parts.push(esc(tf("Mentions: {n}", {n: fmtNum(g.mentions || 0)})));
      }
      if (code) parts.push(esc(tf("Main language: {lang}", {lang: ooLangName(code, code)})));
      parts.push(esc(_obsTrendText(g)));
      // Dominance rides every galaxy in the S1 stats core: a headline total can be
      // one member's, and that is disclosed here rather than only in the payload.
      if (g.dominance && g.dominance.member) {
        parts.push(esc(tf("Dominated by one member: {member} holds {pct}% of the mentions.",
          {member: g.dominance.member, pct: fmtNum((g.dominance.share || 0) * 100, 1)})));
      }
      const edges = (_obs.layout.edges || []).filter((e) => e.a === g || e.b === g);
      if (edges.length) {
        const shared = edges.map((e) => (e.a === g ? e.b.name : e.a.name) + " (" + e.shared.join(", ") + ")");
        parts.push(esc(tf("Shares a member keyword with: {names}", {names: shared.join("; ")})));
      }
      host.innerHTML = parts.join(" · ");
    }

    /** The canvas's text equivalent — the takeaway, not the words "bar chart". */
    function _obsAria() {
      const cv = $("sky-canvas");
      if (!cv || !_obs.layout) return;
      const tf = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
      const L = _obs.layout;
      const top = window.ooSky.rankedGalaxies(L)[0];
      cv.setAttribute("aria-label", tf(
        "The corpus as a sky: {plotted} galaxies plotted by {measure}, {unplaced} not observed yet. The largest is {top}. The ranked table below carries every value.",
        {
          plotted: fmtNum(L.galaxies.length),
          measure: _obsMeasureLabel(_obs.measure),
          unplaced: fmtNum(L.unplaced.length),
          top: top ? top.name : "—",
        }
      ));
    }
