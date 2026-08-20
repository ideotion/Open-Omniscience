/* app-markets.js — Markets, Indices, and the chart toolkit

   The Indices and Commodities boards with their feeds and rules — AND the shared
   chart toolkit (dashChartSvg, ooChart, ooSubtabs, ooTimeScope).

   The toolkit lives here because it is INTERLEAVED with the Markets board that grew
   up around it, not because charts belong to markets: measured, its pieces sit at
   ~11216-11900, ~12298 and ~12894 with market code between them. Extracting them
   would mean reordering declarations, which forfeits byte-parity. Regrouping is a
   separate, separately browser-verified change.

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
    let MKT_SERIES = [];
    const MKT_PRICES = {};            // symbol -> [{observed_on, price, currency, unit}]
    let _mktConfigLoaded = false;

    // -- Indices board (world stock-exchange indices) ----------------------- //
    async function loadIndices() { loadIndicesBoard(); }

    let _idxCards = [];              // last-loaded index board cards
    let _idxCat = "__all";           // current continent facet ("__all" or a continent)
    let _idxTags = new Set();         // active tag facets (AND-filter, none = no tag filter)
    let _idxCatTabs = null;           // the continent ooSubtabs handle
    const _idxCompare = new Map();    // symbol -> {name, currency, unit} selected for the overlay (Slice 3)
    let _idxView = "families";        // "cards" | "families" — families-first (P2-10 twin parity); the cards code path stays reachable but the UI has no toggle
    let _idxScope = {from: null, to: null};  // families-view time window
    let _idxTimeScope = null;          // the ooTimeScope handle (families view)
    let _idxSeriesLoaded = false;      // full per-symbol series fetched (lazy, for families)
    // Continent display order (data-driven: only those actually present render).
    const IDX_CONTINENTS = ["Africa", "Asia", "Europe", "North America", "South America", "Oceania", "Global"];

    async function loadIndicesBoard() {
      const el = $("idx-board");
      el.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const b = await api("/api/markets/board?category=index");
        $("idx-note").textContent = b.note || "";
        _idxCards = b.cards || [];
        renderIndicesBoard();
      } catch (e) { el.innerHTML = `<div class="muted">Could not load indices: ${esc(e.message)}</div>`; }
    }

    function _idxContinent(c) { return c.continent || "Other"; }

    // Group the index cards by CONTINENT into vsect sections (the primary
    // category axis — the direct analog of the commodities board's category
    // grouping, so the two boards stay near-identical, invariant #18 + the
    // twin-board ruling), build the continent subtabs + the secondary tag-chip
    // facet, then apply the active filters.
    function renderIndicesBoard() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("idx-board");
      if (!_idxCards.length) { el.innerHTML = '<div class="muted">No index catalog found.</div>'; }
      const byCont = {};
      for (const c of _idxCards) (byCont[_idxContinent(c)] || (byCont[_idxContinent(c)] = [])).push(c);
      // Present continents in the declared order, then any unexpected ones, then "Other".
      const ordered = IDX_CONTINENTS.filter(k => byCont[k]);
      const extra = Object.keys(byCont).filter(k => k !== "Other" && !IDX_CONTINENTS.includes(k)).sort();
      const present = [...ordered, ...extra, ...(byCont["Other"] ? ["Other"] : [])];
      // Board CONTENT depends on the view (Slice 6 — twin parity): FAMILIES = one
      // multi-series graph per continent (windowed by the time-scope), CARDS = the
      // per-index spark cards (default; unchanged — no regression).
      if (_idxView === "families") {
        // Families is now the DEFAULT view (P2-10), so the full per-symbol series
        // must be lazy-loaded on first render too (the spark data is truncated).
        if (_idxCards.length && !_idxSeriesLoaded) { loadIdxFullSeries().then(renderIndicesBoard); return; }
        if (!_idxTimeScope) buildIdxTimeScope();   // build once, after the series load
        renderIdxFamilies();
      } else if (_idxCards.length) {
        el.innerHTML = present.map(cont =>
          `<div class="idx-cat" data-cat="${esc(cont)}" style="display:contents">` +
          `<div class="vsect" style="grid-column:1/-1">${esc(t(cont))}</div>` +
          byCont[cont].map(idxCard).join("") + `</div>`
        ).join("");
      } else {
        el.innerHTML = '<div class="muted">No index catalog found.</div>';
      }
      const tsRow = $("idx-timescope-row");
      if (tsRow) tsRow.style.display = (_idxView === "families") ? "" : "none";
      _renderIdxViewToggle(t);
      // Continent SUB-TABS (universal subtab grammar, invariant #18): "All"
      // default lens + one tab per present continent. Skip the nav when only
      // one continent is present (a lone tab adds nothing — Home does the same).
      const catNav = $("indices-cats");
      if (catNav) {
        if (present.length > 1) {
          catNav.style.display = "";
          catNav.innerHTML = `<button class="active" data-tab="__all">${esc(t("All"))}</button>`
            + present.map(cont => `<button data-tab="${esc(cont)}">${esc(t(cont))}</button>`).join("");
          _idxCatTabs = ooSubtabs(catNav, selectIndexCat, {initial: _idxCat && present.includes(_idxCat) ? _idxCat : "__all"});
        } else { catNav.style.display = "none"; catNav.innerHTML = ""; _idxCatTabs = null; _idxCat = "__all"; }
      }
      // Secondary TAG facet: distinct tags as toggle chips (AND-filter). Off by
      // default; clicking narrows within the chosen continent. Honest empty
      // states are handled by applyIndexFilters (hides emptied sections).
      const tagRow = $("indices-tags");
      if (tagRow) {
        const tags = [...new Set(_idxCards.flatMap(c => c.tags || []))].sort();
        // Drop any stale active tag no longer present in the data.
        _idxTags = new Set([..._idxTags].filter(x => tags.includes(x)));
        tagRow.innerHTML = tags.length > 1
          ? `<span class="muted" style="font-size:12px;margin-right:4px">${esc(t("Tags"))}:</span>`
            + tags.map(tag =>
                `<button type="button" class="chip${_idxTags.has(tag) ? " on" : ""}" data-tag="${esc(tag)}"
                   onclick="toggleIndexTag(${esc(JSON.stringify(tag))})">${esc(tag)}</button>`).join("")
          : "";
      }
      if (_idxView !== "families") applyIndexFilters();   // cards-view filtering only
      renderIdxCompareBar();
    }
    // The Cards/Families view toggle (Slice 6) — mirrors the commodities toggle so
    // the two boards stay near-identical; default Cards (no regression).
    function _renderIdxViewToggle(t) {
      // Families-first (P2-10 twin parity): the toggle is DROPPED, mirroring the
      // commodities board. Keep the slot empty; the cards path stays reachable.
      const tog = $("idx-viewtoggle"); if (!tog) return;
      tog.innerHTML = ""; tog.style.display = "none";
    }

    function selectIndexCat(key) {
      _idxCat = key;
      // In FAMILIES view the continent subtab re-renders the family graphs (the
      // card-level applyIndexFilters is meaningless there); otherwise it filters
      // the cards. Re-rendering (not hiding) keeps the ooChart widths correct.
      if (_idxView === "families") renderIdxFamilies();
      else applyIndexFilters();
    }
    function toggleIndexTag(tag) {
      if (_idxTags.has(tag)) _idxTags.delete(tag); else _idxTags.add(tag);
      document.querySelectorAll("#indices-tags .chip").forEach(b =>
        b.classList.toggle("on", _idxTags.has(b.dataset.tag)));
      // Families view filters the family MEMBERS by tag (re-render); cards view
      // hides individual cards.
      if (_idxView === "families") renderIdxFamilies();
      else applyIndexFilters();
    }

    // -- Multi-series compare overlay (Slice 3) ----------------------------- //
    // The user accumulates several indices, then opens ONE ooChart overlay of
    // their real price series with Absolute/Indexed/Log scale controls — "the
    // possibility to aggregate several curves onto the same graph" (maintainer
    // 2026-06-17). No fabricated data: each curve is the symbol's stored series
    // fetched from /api/commodities/{symbol}/prices.
    function toggleIdxCompare(symbol, name, currency, unit) {
      if (_idxCompare.has(symbol)) _idxCompare.delete(symbol);
      else _idxCompare.set(symbol, {name: name || symbol, currency: currency || "", unit: unit || ""});
      renderIndicesBoard();   // reflect the comparing state on the cards + the bar
    }
    function clearIdxCompare() { _idxCompare.clear(); renderIndicesBoard(); }
    function renderIdxCompareBar() {
      const bar = $("idx-compare-bar"); if (!bar) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const n = _idxCompare.size;
      if (n < 1) { bar.style.display = "none"; bar.innerHTML = ""; return; }
      bar.style.display = "";
      const names = [..._idxCompare.values()].map(v => esc(v.name)).join(" · ");
      // Need at least 2 series for a meaningful overlay; with 1 selected, invite a second.
      const ready = n >= 2;
      bar.innerHTML =
        `<span class="muted" style="font-size:12px">${esc(t("Comparing"))}: <b>${names}</b></span>`
        + `<button type="button" class="tiny${ready ? "" : " secondary"}"${ready ? "" : " disabled"}
             title="${esc(t("Overlay the selected series on one graph"))}"
             onclick="openIdxComparison()">${esc(t("Compare"))} (${n}) ↗</button>`
        + `<button type="button" class="tiny secondary" onclick="clearIdxCompare()">${esc(t("Clear"))}</button>`
        + (ready ? "" : ` <span class="hint muted" style="font-size:11px">${esc(t("Pick at least two."))}</span>`);
    }
    async function openIdxComparison() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_idxCompare.size < 2) return;
      const entries = [..._idxCompare.entries()];
      // Fetch every selected symbol's FULL stored series (cached by fetchPrices).
      const seriesList = [];
      for (const [symbol, meta] of entries) {
        const pts = await fetchPrices(symbol);
        if (!pts || !pts.length) continue;
        seriesList.push({
          label: meta.name || symbol,
          unit: meta.unit ? `${meta.currency || ""}/${meta.unit}`.replace(/^\//, "") : (meta.currency || ""),
          points: pts.map(p => ({t: p.observed_on, v: p.price})),
        });
      }
      if (seriesList.length < 2) { toast(t("Not enough stored data to compare these yet."), "err"); return; }
      chartEnlarge(t("Index comparison"), seriesList,
        t("End-of-day values from official sources on a shared time axis."), {scales: true});
    }

    // -- Indices FAMILIES view (Slice 6 — twin-board parity) ---------------- //
    // Bring the commodities board's family-stacked graphs + time-range control to
    // the Indices board so the two boards are near-identical (maintainer: "very
    // similar … nearly identical, only the data they show is different"). One
    // multi-series ooChart per CONTINENT, windowed by an ooTimeScope, reusing the
    // SAME renderFamilyGraphs + windowPricesRange + dashChartSvg helpers. Cards
    // view is untouched (sparks) — no regression.
    function setIdxView(v) {
      _idxView = v;
      const row = $("idx-timescope-row"); if (row) row.style.display = (v === "families") ? "" : "none";
      if (v === "families" && !_idxSeriesLoaded) { loadIdxFullSeries().then(renderIndicesBoard); return; }
      renderIndicesBoard();
    }
    async function loadIdxFullSeries() {
      // Lazily fetch every index's FULL stored series (cached by fetchPrices), so
      // the families view + time-scope window real data — not the truncated spark.
      await Promise.all((_idxCards || []).map(c => fetchPrices(c.symbol)));
      _idxSeriesLoaded = true;
    }
    function idxDataSpan() {
      let min = null, max = null;
      for (const c of (_idxCards || [])) {
        for (const p of (MKT_PRICES[c.symbol] || [])) {
          const d = p.observed_on; if (!d) continue;
          if (min === null || d < min) min = d;
          if (max === null || d > max) max = d;
        }
      }
      return {min, max};
    }
    function buildIdxTimeScope() {
      const box = $("idx-timescope"); if (!box) return;
      const span = idxDataSpan();
      if (!span.min || !span.max) { _idxTimeScope = ooTimeScope(box, {}); return; }
      const def = mktDefaultWindow(span);   // reuse: last year of data, anchored to max
      _idxScope = {from: def.from, to: def.to};
      _idxTimeScope = ooTimeScope(box, {
        min: span.min, max: span.max, from: def.from, to: def.to,
        onChange: ({from, to}) => { _idxScope = {from, to}; renderIdxFamilies(); },
      });
    }
    // Build one family per VISIBLE continent (respecting the continent subtab +
    // tag chips), each member windowed to the active range.
    function idxFamilies() {
      const tags = [..._idxTags];
      const cards = (_idxCards || []).filter(c => {
        if (_idxCat !== "__all" && (c.continent || "Other") !== _idxCat) return false;
        if (tags.length && !tags.every(x => (c.tags || []).includes(x))) return false;
        return true;
      });
      const _ser = (c) => {
        const pts = windowPricesRange(MKT_PRICES[c.symbol] || [], _idxScope.from, _idxScope.to);
        return {label: c.name || c.symbol, unit: c.currency || "", symbol: c.symbol,
                points: pts.map(p => ({t: p.observed_on, v: p.price}))};
      };
      // A SPECIFIC continent subtab (not the general "All" lens) shows each index
      // INDIVIDUALLY — one graph per index — instead of merging the continent into
      // one combined family graph (maintainer-ruled). "All" keeps the combined
      // per-continent overview (dense helicopter view).
      if (_idxCat !== "__all") {
        return cards.map(c => ({key: c.symbol, label: c.name || c.symbol, series: [_ser(c)]}));
      }
      const byCont = {};
      for (const c of cards) (byCont[c.continent || "Other"] || (byCont[c.continent || "Other"] = [])).push(c);
      const order = [...IDX_CONTINENTS, "Other"];
      const present = Object.keys(byCont).sort((a, b) => order.indexOf(a) - order.indexOf(b));
      return present.map(cont => ({key: cont, label: cont, series: byCont[cont].map(_ser)}));
    }
    function renderIdxFamilies() {
      const el = $("idx-board"); if (!el) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Twin parity (P2-10): indices member chips mirror commodities — Analyse ↗
      // (the index's corpus coverage) + the price detail in the fullscreen overlay.
      renderFamilyGraphs(el, idxFamilies(), {
        memberActions: [
          {glyph: "⊞", title: t("Open this in the analysis window"),
           fn: (s) => openAnalysisFor(s.label)},
          {glyph: "📈", title: t("Price detail"),
           fn: (s) => chartSymbol(s.symbol, s.unit)},
        ],
      });
    }

    // Apply BOTH facets: the continent subtab hides whole sections; the tag
    // chips hide individual cards (AND across active tags); a section whose
    // cards are all tag-hidden is itself hidden so no empty header shows.
    function applyIndexFilters() {
      const tags = [..._idxTags];
      document.querySelectorAll("#idx-board .idx-card").forEach(card => {
        const ct = (card.dataset.tags || "").split("|").filter(Boolean);
        card.style.display = tags.every(x => ct.includes(x)) ? "" : "none";
      });
      document.querySelectorAll("#idx-board .idx-cat").forEach(sec => {
        const visMatch = _idxCat === "__all" || sec.dataset.cat === _idxCat;
        const anyCard = [...sec.querySelectorAll(".idx-card")].some(c => c.style.display !== "none");
        sec.style.display = (visMatch && anyCard) ? "contents" : "none";
      });
    }

    function _num(n) { return n == null ? "—" : Number(n).toLocaleString(undefined, {maximumFractionDigits: 2}); }

    function idxSpark(pts, chg) {
      if (!pts || pts.length < 2) return '<div class="idx-spark-empty muted">no series yet</div>';
      const w = 280, h = 42, n = pts.length, vals = pts.map(p => p[1]);
      const min = Math.min(...vals), max = Math.max(...vals), rng = (max - min) || 1;
      const x = i => (i / (n - 1)) * w, y = v => h - ((v - min) / rng) * (h - 6) - 3;
      const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
      const col = chg == null ? "var(--muted)" : (chg >= 0 ? "var(--ok)" : "var(--err)");
      return `<svg class="idx-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;
    }

    function idxCard(c) {
      const t2 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const has = !!c.latest;
      const chg = c.change_pct;
      const cls = chg == null ? "flat" : (chg >= 0 ? "up" : "down");
      const chgTxt = chg == null ? "" : `${chg >= 0 ? "▲" : "▼"} ${Math.abs(chg).toFixed(2)}%`;
      // With stored data the card opens the SAME interactive ooChart detail the
      // commodity board uses (invariant #16: full-resolution series fetched from
      // /api/commodities/{symbol}/prices, never the truncated spark). Empty
      // catalog entries stay inert until a first import.
      const open = has
        ? ` style="cursor:pointer" title="open detailed chart"
            onclick="indexDetail(${esc(JSON.stringify(c.symbol))}, ${esc(JSON.stringify(c.name || c.symbol))}, ${esc(JSON.stringify(c.currency || ""))})"`
        : "";
      // The GRAPH is a first-class entry into the analysis WINDOW (ledger
      // MARKETS item 4): an "Analyse ↗" affordance opens the index's corpus
      // coverage via openAnalysisFor (the same universal opener — no duplicate).
      // The card body keeps its indexDetail price chart (the Desk lesson: never
      // silently lose a tool); stopPropagation in the footer keeps the two paths
      // distinct. No symbol→family seed exists for indices, so the term is the
      // index's REAL name — never a fabricated family. The price × article
      // timeline OVERLAY is remaining; this slice opens the window on the name.
      const idxQ = c.name || c.symbol;
      // Carry the facet values so the continent subtab + tag chips can filter
      // without a re-fetch (data-tags is '|'-joined for a simple includes test).
      const facets = ` data-continent="${esc(c.continent || "Other")}" data-tags="${esc((c.tags || []).join("|"))}"`;
      // Slice 3: a compare toggle adds this index to the multi-series overlay
      // (only meaningful with a stored series — gated on `has`). The card body's
      // indexDetail click is preserved (stopPropagation keeps the two distinct).
      const cmp = _idxCompare.has(c.symbol);
      const cmpBtn = has
        ? ` · <button class="tiny${cmp ? "" : " secondary"}" type="button"
              title="${esc(t2(cmp ? "Remove from the comparison overlay" : "Add to the comparison overlay"))}"
              onclick="event.stopPropagation(); toggleIdxCompare(${esc(JSON.stringify(c.symbol))}, ${esc(JSON.stringify(c.name || c.symbol))}, ${esc(JSON.stringify(c.currency || ""))}, ${esc(JSON.stringify(c.unit || ""))})">${cmp ? "✓ " + esc(t2("Comparing")) : "＋ " + esc(t2("Compare"))}</button>`
        : "";
      return `<div class="idx-card${cmp ? " comparing" : ""}" data-symbol="${esc(c.symbol)}"${facets}${open}>
        <div class="idx-top">
          <div class="idx-id"><div class="idx-name">${esc(c.name)}</div>
            <div class="idx-mkt muted">${esc(c.market || "")}</div></div>
          <div class="idx-quote"><div class="idx-num">${_num(has ? c.latest.price : null)}</div>
            <div class="idx-chg ${cls}">${chgTxt}</div></div>
        </div>
        ${idxSpark(c.spark, chg)}
        ${has && c.spark && c.spark.length >= 2
          ? `<div class="idx-range hint muted"><span>${esc(c.spark[0][0])}</span><span>${esc(c.spark[c.spark.length - 1][0])}</span></div>`
          : ""}
        <div class="idx-foot muted" onclick="event.stopPropagation()">${has ? `as of ${esc(c.latest.observed_on)}` : "no data yet — click Load"}
          · ${esc(c.currency || "")} · ${extLink(c.url, "source")}
          · <button class="tiny secondary" type="button"
              title="${esc(t2("Open this in the analysis window — its corpus coverage"))}"
              onclick="openAnalysisFor(${esc(JSON.stringify(idxQ))})">${esc(t2("Analyse"))} ↗</button>${cmpBtn}</div>
      </div>`;
    }

    // Per-feed TRANSPORT-AWARE verdicts (ruled 2026-06-12): "refused over Tor"
    // is not "robots disallows" is not "dead series". Failures are listed with
    // their honest note, and ONLY honestly-retryable ones get the Retry button.
    function _renderFeedVerdicts(elId, r, category) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $(elId); if (!el) return;
      const fails = (r.results || []).filter(x => x.status !== "imported");
      if (!fails.length) { el.innerHTML = ""; return; }
      const rows = fails.map(x =>
        `<div><span class="pill warn">${esc(x.verdict || x.status)}</span> <b>${esc(x.symbol || x.key)}</b>` +
        ` <span class="muted">— ${esc(x.verdict_note || x.detail || "")}</span></div>`).join("");
      const retry = (r.retryable_failed_keys || []);
      const btn = retry.length
        ? `<button class="secondary tiny" style="margin-top:4px" onclick="retryFailedFeeds('${esc(category||"")}', '${esc(retry.join(","))}', '${esc(elId)}')">` +
          esc(t("Retry failed feeds")) + ` (${retry.length})</button>`
        : "";
      el.innerHTML = rows + btn;
    }
    async function retryFailedFeeds(category, keys, elId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ensureOnline === "function" &&
          !await ensureOnline(t("Fetch market and index data from the official feeds"))) return;
      const el = $(elId); if (el) el.textContent = t("Retrying failed feeds…");
      try {
        const q = category ? `?category=${encodeURIComponent(category)}&keys=` : "?keys=";
        const r = await api(`/api/markets/feeds/import-all${q}${encodeURIComponent(keys)}`, {method: "POST"});
        toast(`${t("Retry finished:")} ${r.points_imported} ${t("new point(s);")} ${r.failed} ${t("still failing.")}`);
        _renderFeedVerdicts(elId, r, category);
      } catch (e) { if (el) el.textContent = e.message; }
    }
    async function loadIndicesData(btn) {
      btn.disabled = true;
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Fetch market and index data from the official feeds"))) { btn.disabled = false; return; }
      const st = $("idx-status");
      st.textContent = "Importing index feeds (official end-of-day CSVs; may take a moment)…";
      try {
        const r = await api("/api/markets/feeds/import-all?category=index", {method: "POST"});
        st.textContent = `Imported ${r.points_imported} point(s) across ${r.feeds} feed(s)${r.failed ? `, ${r.failed} failed` : ""}.`;
        _renderFeedVerdicts("idx-verdicts", r, "index");
        // Degrade loudly (maintainer hit "only Dow + S&P arrive"): name each
        // failing feed and the exact refusal, instead of a silent count.
        const bad = (r.results || []).filter(x => x.status !== "imported");
        $("idx-note").innerHTML = bad.length
          ? `<b>Feeds that did not deliver:</b> ` + bad.map(x =>
              `${esc(x.key || x.symbol)} <span class="muted">(${esc(x.detail || x.status)})</span>`).join(" · ")
          : "";
        await loadIndicesBoard();
        toast("Indices updated.");
      } catch (e) { st.textContent = ""; toast(_failMsg("Load failed: {error}", e), "err"); }
      finally { btn.disabled = false; }
    }

    async function loadMarkets() { loadDashboard(); loadMineralsSupply(); }

    // S5.1: the USGS Mineral Commodity Summaries SUPPLY surface — production / reserves /
    // net-import-reliance for minerals (rare earths) that have NO free spot-price source.
    // Supply data, NEVER prices (stated in the caveat). Reads /api/stats/minerals-supply;
    // honest empty state (available:false → the operator-fetch reason) so an empty board
    // reads as "not fetched yet", never "no supply". Counts only, no score.
    async function loadMineralsSupply() {
      const host = $("mkt-minerals-supply"); if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let d;
      try { d = await api("/api/stats/minerals-supply"); }
      catch { host.innerHTML = ""; return; }   // best-effort; never break the board
      const head = `<h2 style="font-size:14px;margin:0 0 4px">${esc(t("Minerals supply"))} `
        + `<span class="muted" style="font-weight:400">${esc(t("(USGS — supply data, not prices)"))}</span></h2>`
        + `<div class="hint muted" style="margin-bottom:8px">${esc(d.caveat || "")}</div>`;
      if (!d.available) {
        host.innerHTML = head
          + `<div class="muted">${esc(d.reason || t("No USGS supply figures stored yet."))}</div>`;
        return;
      }
      const blocks = (d.commodities || []).map((c) => {
        const measures = Object.keys(c.measures || {}).sort().map((m) => {
          const rows = (c.measures[m] || []).slice(0, 12).map((r) =>
            `<tr><td>${esc(r.ref_area)}</td>`
            + `<td class="muted">${esc(r.time_period)}</td>`
            + `<td style="text-align:right;font-variant-numeric:tabular-nums">${r.value === null || r.value === undefined ? "—" : (typeof fmtNum === "function" ? fmtNum(r.value) : r.value)}</td>`
            + `<td class="muted">${esc(r.unit || "")}</td></tr>`).join("");
          return `<div class="vsect" style="margin-top:6px">${esc(m.replace(/_/g, " "))}</div>`
            + `<table class="data"><thead><tr><th>${esc(t("Area"))}</th><th>${esc(t("Year"))}</th>`
            + `<th style="text-align:right">${esc(t("Value"))}</th><th>${esc(t("Unit"))}</th></tr></thead>`
            + `<tbody>${rows}</tbody></table>`;
        }).join("");
        return `<div class="an-panel" style="margin-top:10px"><h3 style="font-size:13px;margin:0 0 2px">${esc(c.commodity.replace(/-/g, " "))}</h3>${measures}</div>`;
      }).join("");
      host.innerHTML = head + blocks;
    }

    async function fetchPrices(symbol) {
      if (MKT_PRICES[symbol]) return MKT_PRICES[symbol];
      try { const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/prices`); MKT_PRICES[symbol] = d.prices || []; }
      catch { MKT_PRICES[symbol] = []; }
      return MKT_PRICES[symbol];
    }

    async function loadDashboard() {
      const status = $("mkt-dash-status");
      try {
        const d = await api("/api/markets/series");
        MKT_SERIES = d.series || [];
        if (!MKT_SERIES.length) {
          $("mkt-dashboard").innerHTML = `<div class="muted">No market data yet. Click “Load / refresh market data” to import official price feeds (EUR/USD, crude oil, metals, gold).</div>`;
          status.textContent = ""; return;
        }
        status.textContent = `${MKT_SERIES.length} series`;
        await Promise.all(MKT_SERIES.map(s => fetchPrices(s.symbol)));
        // (Re)build the time-range control from the freshly loaded data span,
        // defaulting the window to the last year (or all if <1y). It calls
        // renderDashboard() on every change; render once now for the default.
        buildMktTimeScope();
        renderDashboard();
      } catch (e) { status.textContent = "Could not load series: " + e.message; }
    }

    // The commodities board is windowed by ABSOLUTE dates [from,to] (the
    // ooTimeScope control), not a trailing `days` count. Within the window the
    // FULL-RESOLUTION series is kept (invariant #16) — never thinned; sparse
    // windows render as honest dots downstream (dashChartSvg).
    let _mktScope = {from: null, to: null};   // current window (ISO YYYY-MM-DD)
    let _mktTimeScope = null;                  // the ooTimeScope handle
    function windowPricesRange(points, from, to) {
      if (!points.length) return points;
      if (!from && !to) return points;
      return points.filter(p =>
        (!from || p.observed_on >= from) && (!to || p.observed_on <= to));
    }
    // The data span across ALL loaded commodity series (oldest → newest point),
    // used to bound the control. Indices are excluded (not commodities).
    function mktDataSpan() {
      let min = null, max = null;
      for (const s of MKT_SERIES) {
        if (s.category === "index") continue;
        const pts = MKT_PRICES[s.symbol] || [];
        for (const p of pts) {
          const d = p.observed_on;
          if (!d) continue;
          if (min === null || d < min) min = d;
          if (max === null || d > max) max = d;
        }
      }
      return {min, max};
    }
    // Default window = the last 1 year of the data (or the whole span if the
    // data covers less than a year). Anchored to the data's max, never "now".
    function mktDefaultWindow(span) {
      if (!span.min || !span.max) return {from: span.min, to: span.max};
      const maxD = new Date(span.max + "T00:00:00Z");
      const yearAgo = new Date(maxD); yearAgo.setUTCFullYear(maxD.getUTCFullYear() - 1);
      const from = yearAgo.toISOString().slice(0, 10);
      return {from: from > span.min ? from : span.min, to: span.max};
    }
    function buildMktTimeScope() {
      const box = $("mkt-timescope");
      if (!box) return;
      const span = mktDataSpan();
      if (!span.min || !span.max) { _mktTimeScope = ooTimeScope(box, {}); return; }
      const def = mktDefaultWindow(span);
      _mktScope = {from: def.from, to: def.to};
      _mktTimeScope = ooTimeScope(box, {
        min: span.min, max: span.max, from: def.from, to: def.to,
        onChange: ({from, to}) => { _mktScope = {from, to}; renderDashboard(); },
      });
    }

    // Smart number formatting (maintainer-ruled, app-wide): significant digits
    // scaled to the magnitude — never a raw float tail like 3654.015384615385.
    // Thin-space thousands grouping (locale-neutral, SI style).
    function fmtNum(v, maxDec) {
      if (v == null || !isFinite(v)) return "—";
      const a = Math.abs(v);
      const dec = maxDec != null ? maxDec : (a >= 1000 ? 1 : a >= 100 ? 1 : a >= 1 ? 2 : 3);
      const s = v.toFixed(dec).replace(/\.?0+$/, m => m.includes(".") ? "" : m);
      const [int, frac] = s.split(".");
      const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
      return frac ? `${grouped}.${frac}` : grouped;
    }

    // Detailed per-card chart (maintainer-ruled, invariant #16): the FULL series
    // within the visible window — never downsampled, never silently widened to
    // the whole history. Labelled axes + DISCRETE horizontal gridlines so a
    // crossing reads off in X and Y. Honest sparsity: a connecting line ONLY
    // when the window is dense enough (lineMin=8); fewer points render as
    // discrete dots with n + the early-corpus caveat — never a curve faked
    // through a handful of points.
    // Item Y (ruled 2026-06-15, amends invariant #16): app-wide, n<10 datapoints
    // render as a BAR graph (not dots), n>=10 as the full-resolution line. Shared by
    // BOTH chart renderers (dashChartSvg + ooChart).
    const _SPARSE_BAR_MAX = 10;

    // --- categorical series identity: three channels, not one ------------- //
    // A multi-series chart used to be told apart by COLOUR ALONE (a 4-entry cycle
    // indexed i % 4, a solid stroke, a solid legend swatch). Measured: the worst
    // mutual contrast between two of the six theme-derived series colours is
    // 1.00:1 — luminance-identical — so on a greyscale print, to a colour-blind
    // reader, or at i == 4 where the cycle wrapped series 5 onto series 1, the
    // series were not distinguishable at all. app.css states the rule the code was
    // breaking: "Colour is never the only signal."
    //
    // So a series carries THREE redundant channels: the --fig-N colour, a dash
    // pattern, and a marker shape. Any one of them alone identifies the series;
    // colour is now the decorative one. Six slots (not four) so a sixth series is
    // still its own thing rather than a duplicate of the first — and the wrap at
    // slot 7 is disclosed by _figStyle rather than silent.
    //
    // Dash arrays are in CSS px and are the SAME numbers for canvas
    // (ctx.setLineDash) and SVG (stroke-dasharray), so ooChart and the legend
    // swatch cannot drift apart.
    // The patterns are chosen so no two share a FAMILY, not merely a number. A first
    // cut used [2,3] for slot 3 and [1,3] for slot 6 — both read as "the dotted one",
    // since a 1px difference in dot length is not perceptible — and [11,3,2,3] against
    // [4,3,1,3], both "dash-dot". Each is now a different rhythm: solid / long dash /
    // fine dot / dash-dot / long-dash-double-dot / wide-spaced square dot.
    //
    // Marker shapes avoid pairs that are the same shape rotated: a diamond IS a
    // rotated square, and at a few pixels across, anti-aliasing makes them a coin
    // flip. Circle / square / triangle / plus / cross / chevron differ in vertex
    // count and stroke direction, which survives being small.
    const _FIG_STYLES = [
      {color: "var(--fig-1)", dash: [],                  marker: "circle"},
      {color: "var(--fig-2)", dash: [10, 5],             marker: "square"},
      {color: "var(--fig-3)", dash: [1.5, 3.5],          marker: "triangle"},
      {color: "var(--fig-4)", dash: [9, 4, 2, 4],        marker: "plus"},
      {color: "var(--fig-5)", dash: [13, 4, 2, 4, 2, 4], marker: "cross"},
      // dot-DASH: the same two mark lengths as slot 4 in the opposite ORDER, which
      // reads differently. [3, 7] was tried here and rejected by the rhythm guard —
      // against slot 3's [1.5, 3.5] it is the same uniform-dotted family at half the
      // frequency, and scaling a pattern up does not make it a different pattern.
      {color: "var(--fig-6)", dash: [2, 4, 9, 4],        marker: "chevron"},
    ];
    // The style for series index i. Beyond six series the channels re-use, which
    // is a real limit and is reported (`wrapped`) rather than hidden: a caller with
    // seven series is told its 7th looks like its 1st.
    function _figStyle(i) {
      const n = _FIG_STYLES.length;
      return Object.assign({}, _FIG_STYLES[((i % n) + n) % n], {wrapped: i >= n});
    }
    // One marker path, drawn identically on canvas and in SVG so the legend glyph
    // and the plotted point are the same shape. r is the half-size in px.
    function _figMarkerPath(shape, x, y, r) {
      switch (shape) {
        case "square":   return [[x - r, y - r], [x + r, y - r], [x + r, y + r], [x - r, y + r]];
        case "triangle": return [[x, y - r * 1.2], [x + r * 1.1, y + r * 0.8], [x - r * 1.1, y + r * 0.8]];
        // A downward chevron: an OPEN outline, so it never reads as a filled blob the
        // way a small square or triangle can. (A diamond was dropped — it is a
        // rotated square, and at ~6px the two are indistinguishable.)
        case "chevron":  return [[[x - r * 1.2, y - r * 0.6], [x, y + r * 0.8]],
                                 [[x, y + r * 0.8], [x + r * 1.2, y - r * 0.6]]];
        // cross/plus are strokes, not fills — returned as segment pairs
        case "cross":    return [[[x - r, y - r], [x + r, y + r]], [[x - r, y + r], [x + r, y - r]]];
        case "plus":     return [[[x - r * 1.25, y], [x + r * 1.25, y]], [[x, y - r * 1.25], [x, y + r * 1.25]]];
        default:         return null;                      // circle: drawn as an arc
      }
    }
    // The shapes drawn as STROKES rather than fills. Kept in one place so the canvas
    // and SVG paths cannot disagree about which is which.
    const _FIG_STROKE_MARKERS = new Set(["cross", "plus", "chevron"]);
    // Draw one marker on a 2D canvas context (fill for closed shapes, stroke for
    // the two open ones, arc for circle).
    function _figMarkerCanvas(ctx, shape, x, y, r) {
      const p = _figMarkerPath(shape, x, y, r);
      if (!p) { ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); return; }
      if (_FIG_STROKE_MARKERS.has(shape)) {
        const w = ctx.lineWidth, d = ctx.getLineDash();
        ctx.setLineDash([]); ctx.lineWidth = Math.max(1.4, r * 0.7);
        ctx.beginPath();
        for (const [[ax, ay], [bx, by]] of p) { ctx.moveTo(ax, ay); ctx.lineTo(bx, by); }
        ctx.stroke(); ctx.lineWidth = w; ctx.setLineDash(d);
        return;
      }
      ctx.beginPath();
      p.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
      ctx.closePath(); ctx.fill();
    }
    // The legend/key glyph as inline SVG: the series' own dash pattern on a short
    // rule with its marker centred, so the legend states all three channels. Vector,
    // so it survives greyscale printing and a browser zoom.
    function _figGlyph(st) {
      // The marker sits at the FAR END, not the middle. Centred at x=15 on a 30px
      // swatch, it covered exactly the stretch where a dash-dot cycle shows its
      // distinguishing detail — slot 4's [8,4,2,4] rendered as two long solid runs
      // with the whole pattern hidden behind the glyph, so its key showed no pattern
      // at all. The swatch is also wider now (38px) so a long cycle completes at
      // least once inside it: a key that cannot show the pattern cannot teach it.
      const c = st.color, mx = 33, mk = _figMarkerPath(st.marker, mx, 7, 3.4);
      let m;
      if (!mk) m = `<circle cx="${mx}" cy="7" r="3.4" fill="${c}"/>`;
      else if (_FIG_STROKE_MARKERS.has(st.marker))
        m = mk.map(([[ax, ay], [bx, by]]) =>
          `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="${c}" stroke-width="2"` +
          ` stroke-linecap="round"/>`).join("");
      else m = `<polygon points="${mk.map(([px, py]) => px + "," + py).join(" ")}" fill="${c}"/>`;
      return `<svg width="38" height="14" viewBox="0 0 38 14" aria-hidden="true" focusable="false"` +
        ` style="vertical-align:middle;flex:none">` +
        `<line x1="0" y1="7" x2="28" y2="7" stroke="${c}" stroke-width="2"` +
        (st.dash.length ? ` stroke-dasharray="${st.dash.join(" ")}"` : "") + `/>${m}</svg>`;
    }
    // One shared "no data here" hatch, so absence is a TEXTURE (a shape cue) and
    // never a colour or a zero. Both shipped hatches (#oomap-nodata, #rhythm-none)
    // hand-rolled their own <defs> and stroked with var(--border), which measures
    // 1.20:1 against --panel on garnet — the absence cue was itself near-invisible.
    // --fig-gap clears 3:1 on all 17 themes (worst 3.44:1, paper).
    const FIG_GAP_ID = "fig-nodata";
    function figGapDefs(id) {
      const pid = id || FIG_GAP_ID;
      return `<defs><pattern id="${pid}" width="6" height="6" patternUnits="userSpaceOnUse"` +
        ` patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6"` +
        ` stroke="var(--fig-gap)" stroke-width="1.25"></line></pattern></defs>`;
    }
    function figGapFill(id) { return `url(#${id || FIG_GAP_ID})`; }

    // --- F2: the one method / caveat / n panel ----------------------------- //
    // "Every displayed figure carries its method, its caveat and its n" is a
    // structural invariant on the backend — Card.method and Card.caveat are
    // non-defaulted required fields, Envelope refuses an empty method or a
    // fabricated as_of — but on the frontend it was 41 hand-built `.card-caveat`
    // sites and no component at all. Every new figure therefore re-implemented the
    // honesty furniture, which is exactly how a figure ends up shipping without it.
    //
    // Takes the Envelope shape as it is serialized (envelope.py:106-114):
    //   {method, caveat, n, basis, as_of}
    // and renders it VISIBLY, never behind a toggle (informed consent by layering:
    // the long form belongs in an #oo-tip title, not behind a checkbox).
    //
    // `basis` is a DISCLOSURE, not a score: "exact" = verified against the
    // canonical store at as_of, "estimated" = a maintained value that may have
    // drifted since. It is printed in words, never as a badge that could be read
    // as a grade.
    function figMeta(env) {
      if (!env) return "";
      const parts = [];
      // `t` is not a module-level global in app.js — every function aliases it, and
      // a function that forgets throws "t is not defined" at runtime. (Aliasing it
      // as t9 = (s) => t(s) would have slipped past the invariant guard, which looks
      // for a literal t("…"), and still broken at runtime. Bind it directly.)
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // The method sentence gets its OWN element. The i18n walker matches a text node
      // against the key map EXACTLY, so `Method: <sentence>` as one text node is not a
      // key and never translates — which a browser screenshot in Arabic showed as
      // English method lines under translated Arabic caveats. Two elements, two exact
      // matches: the label "Method" and the sentence itself.
      if (env.method) {
        parts.push(`<span class="fig-method">${esc(t9("Method"))}:</span> ` +
          `<span class="fig-method">${esc(env.method)}</span>`);
      }
      // n === 0 is a real measurement ("nothing matched") and must print; only an
      // absent n is omitted. `n == null` catches undefined too, and nothing else.
      if (env.n != null) {
        parts.push(`<span class="fig-n">${esc(OOI18N && OOI18N.tf
          ? OOI18N.tf("n = {n}", {n: fmtNum(env.n)}) : "n = " + fmtNum(env.n))}</span>`);
      }
      if (env.basis) {
        // Each basis value is translated through its OWN FIXED key, so the disclosure
        // is readable in every locale. An unrecognised value is printed verbatim
        // rather than silently normalised into one of the known ones — a wrong basis
        // claim is worse than an untranslated one.
        const lab = env.basis === "exact" ? t9("verified against the corpus")
          : env.basis === "estimated" ? t9("from a maintained counter — may have drifted")
          : env.basis === "live" ? t9("counted live just now")
          : env.basis;
        const asOf = env.as_of ? ` (${esc(_figAsOf(env.as_of))})` : "";
        parts.push(`<span class="fig-basis">${esc(lab)}${asOf}</span>`);
      }
      let html = parts.length ? `<div class="fig-meta"><span class="fig-method">` +
        parts.join(` <span class="muted">·</span> `) + `</span></div>` : "";
      if (env.caveat) {
        html += `<div class="fig-meta"><span class="fig-caveat">${esc(env.caveat)}</span></div>`;
      }
      return html;
    }
    // as_of is an ISO timestamp the backend guarantees is real (envelope.py refuses
    // an empty one). Render it as a plain date-time; a value that will not parse is
    // shown verbatim rather than replaced by a guess.
    function _figAsOf(iso) {
      const d = new Date(iso);
      return isFinite(+d) ? d.toLocaleString() : String(iso);
    }

    // --- F3: absence is not zero ------------------------------------------ //
    // An honest empty state: a sentence where the figure would be. Never a blank
    // box (which reads as broken) and never an axis drawn through no data (which
    // reads as a measured zero — the fabricated-spike trap an all-zero histogram
    // from an n == 0 report walks straight into).
    function figEmpty(msg, env) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return `<div class="fig-empty">${esc(msg || t("Nothing to show yet."))}</div>` +
        (env ? figMeta(env) : "");
    }
    // The legend row naming the hatch in words, so the texture is not the only
    // statement that a cell was never measured.
    function figGapKey(msg) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return `<div class="fig-gap-key"><span class="fig-gap-swatch"></span>` +
        `<span>${esc(msg || t("Hatched = not measured, which is not a zero."))}</span></div>`;
    }

    // --- chart accessibility (audit PR G) -------------------------------- //
    // <svg>/<canvas> charts are opaque to screen readers. Give each a role="img"
    // + a translated aria-label SUMMARY, and a visually-hidden data table so the
    // actual series is readable. Aria text is built from t9() fragments (a dynamic
    // attribute value is never matched by the i18n engine's exact-key lookup, so it
    // must be pre-translated here).
    function _chartAria(label, n, a, b, lo, hi) {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return t9("Chart, {label}: {n} points, {a} to {b}, {lo} to {hi}")
        .replace("{label}", label || t9("Value")).replace("{n}", String(n))
        .replace("{a}", String(a)).replace("{b}", String(b))
        .replace("{lo}", String(lo)).replace("{hi}", String(hi));
    }
    function _chartSrTable(rows, label) {
      // rows: [{date, value}]; capped so a dense series can't bloat the DOM (the
      // aria-label already states the true n; a truncated table ends with an
      // ellipsis row). Visually hidden (.sr-only) — no visual change.
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const CAP = 500;
      const body = rows.slice(0, CAP).map(
        r => `<tr><td>${esc(String(r.date))}</td><td>${esc(String(r.value))}</td></tr>`).join("");
      const more = rows.length > CAP ? '<tr><td colspan="2">…</td></tr>' : "";
      const cap = label ? `${t9("Chart data")} — ${esc(String(label))}` : esc(t9("Chart data"));
      return `<table class="sr-only"><caption>${cap}</caption>`
        + `<thead><tr><th>${esc(t9("Date"))}</th><th>${esc(t9("Value"))}</th></tr></thead>`
        + `<tbody>${body}${more}</tbody></table>`;
    }

    // --- honest axes (2026-08-01 field impressions, ruling 10) ------------ //
    // A tick must be a value the axis ACTUALLY spans, in the data's own units.
    // Two fabrications this replaces, both born of the `(max - min) || 1` span
    // fallback: (a) a FLAT series invented a span, so a constant 23 drew ticks
    // at 23 / "23.50" / 23 with the min+max labels OVERLAPPING at the plot
    // bottom (dashChartSvg) and 23 / 23.33 / 23.67 / 24 — a top tick no data
    // reaches — in ooChart; (b) a COUNT axis drew FRACTIONAL ticks ("23.5 law
    // documents"). Rules: flat -> exactly ONE tick at the real value; an
    // all-integer series -> integer ticks only; the first and last tick are
    // always the REAL extremes, so rounding can never invent a value outside
    // the data's own range.
    function _allInteger(vals) {
      return vals.length > 0 && vals.every(v => Number.isInteger(v));
    }
    function honestTicks(minV, maxV, want, integerOnly) {
      if (!isFinite(minV) || !isFinite(maxV)) return [];
      if (maxV <= minV) return [minV];              // FLAT: one honest tick, never a fabricated span
      const n = Math.max(2, want | 0);
      const eps = (maxV - minV) * 1e-9;
      const out = [];
      for (let g = 0; g < n; g++) {
        const raw = minV + (maxV - minV) * g / (n - 1);
        // endpoints stay the REAL extremes; interior ticks snap to integers on a count axis
        const v = (g === 0) ? minV : (g === n - 1) ? maxV : (integerOnly ? Math.round(raw) : raw);
        if (v < minV - eps || v > maxV + eps) continue;
        if (!out.some(o => Math.abs(o - v) <= eps)) out.push(v);
      }
      return out.sort((a, b) => a - b);
    }
    // X-label granularity derived from the ACTUAL plotted span. The old code
    // hard-sliced every label to YYYY-MM and de-duplicated INDEXES rather than
    // TEXT, so two hourly snapshots inside one month both printed "2026-07"
    // (maintainer-reported). Returns a formatter; callers then drop duplicate
    // label TEXT, so a window that genuinely sits inside one hour honestly
    // shows one label instead of the same one repeated.
    // A single point (or several stamped at one instant) has a span of EXACTLY zero,
    // which carries no granularity at all -- so the granularity comes from the
    // timestamp's own precision instead of from a span that cannot speak. Without
    // this, a one-point annual series fell into the <=2-days arm and "2022-01-01"
    // was sliced to "01-01": a year printed as a month and a day (field feedback
    // 2026-08-07, item 8, the Physicians card). An hourly pair one hour apart has a
    // span of 0.04 days, not 0, so it keeps the hourly label -- this arm is only
    // reached when there is genuinely no interval to read.
    function _pointLabelFmt(s) {
      const str = String(s);
      const hasTime = /T\d\d:/.test(str) && !/T00:00/.test(str);
      if (hasTime) return str.slice(5, 13).replace("T", " ");   // MM-DD HH
      if (/^\d{4}-01-01/.test(str)) return str.slice(0, 4);     // YYYY -- an annual figure
      return str.slice(0, 10);                                  // YYYY-MM-DD
    }
    // An AXIS label has ~40px of room, so a magnitude that does not fit must be
    // compacted rather than printed in full and clipped: a GDP gridline read
    // "51167643745037.1" (field feedback 2026-08-07, item 8). Only values at or
    // above a million change -- a count axis, a price axis and a percentage axis
    // are byte-identical to before, because those are the axes where the exact
    // grouped figure is both readable and the thing the reader wants. The hover
    // and the value line still carry the precise number; this is the tick only.
    function _axisNum(v) {
      return (isFinite(v) && Math.abs(v) >= 1e6) ? _govCompact(v) : fmtNum(v);
    }
    function _timeLabelFmt(firstIso, lastIso) {
      const a = Date.parse(String(firstIso)), b = Date.parse(String(lastIso));
      const days = (isFinite(a) && isFinite(b)) ? Math.abs(b - a) / 864e5 : NaN;
      if (isFinite(days) && days === 0) return _pointLabelFmt;
      if (isFinite(days) && days <= 2)
        return (s) => String(s).slice(5, 13).replace("T", " ");   // MM-DD HH
      if (isFinite(days) && days <= 92)
        return (s) => String(s).slice(0, 10);                     // YYYY-MM-DD
      return (s) => String(s).slice(0, 7);                        // YYYY-MM
    }
    // The same rule for an epoch-ms axis (ooChart): granularity from the span
    // being labelled, so an hourly window stops printing the same day repeatedly.
    function _msLabel(ms, spanMs) {
      const iso = new Date(ms).toISOString();
      const days = spanMs / 864e5;
      if (isFinite(days) && days <= 2) return iso.slice(5, 16).replace("T", " ");  // MM-DD HH:MM
      if (isFinite(days) && days <= 92) return iso.slice(0, 10);                   // YYYY-MM-DD
      return iso.slice(0, 7);                                                      // YYYY-MM
    }
    // -- Honest gaps in the ONE chart toolkit (invariant #16) ---------------- //
    // A hole in a time series must render as a HOLE. Both renderers here used to
    // draw straight through one: dashChartSvg emitted a SINGLE <polyline> over
    // every point, and ooChart dropped non-finite values and then lineTo'd from
    // the point before the hole to the point after it. On a real time axis that
    // is a fabricated measurement -- a smooth line across hours nothing was
    // recorded -- and it is the one thing the project's own committed chart
    // framework rejects outright ("Render gaps as gaps; mark 'no data'
    // distinctly. Verdict: REJECT", docs/research/dataviz/chart_decision_framework.md).
    // ooviz.js has shipped pathWithGaps + statSeriesPaths for exactly this since
    // they were written, and neither had ever been wired to anything.
    //
    // Three live data families reach these renderers with real holes:
    //   - Library metric history: snapshot rows exist only for hours that were
    //     recorded, so any time the app was off is a genuine gap (app.js:8279);
    //   - official-statistics indicators, where a published gap is a real null the
    //     call site FILTERS OUT before drawing (app.js:4732);
    //   - commodity prices on a shared time axis, where market closures are holes
    //     (app.js:10532).
    //
    // WHAT COUNTS AS A GAP is an editorial choice, so it is a stated one. A run
    // breaks at a missing value always, and -- only when the x-axis is a REAL time
    // axis -- at a hole wider than _GAP_FACTOR x the series' OWN median cadence.
    // Keying off the series' own cadence rather than a fixed duration is what lets
    // one rule serve hourly counters and annual indicators alike. The factor is
    // deliberately generous so ordinary jitter never breaks a line; a cadence is
    // only trusted from >= 3 intervals, and below that nothing is ever split (a
    // fabricated gap is exactly as dishonest as a fabricated line).
    //
    // BLAST RADIUS, deliberately bounded: on an INDEX axis the spacing claims
    // observation order, not elapsed time, so bridging consecutive observations
    // fabricates nothing and index-mode output stays byte-identical. Only a
    // missing value breaks there.
    // A JS TRAP that makes the naive check exactly backwards: isFinite(null) is
    // TRUE and +null is 0, so a published gap coerces to a real, plotted ZERO --
    // a fabricated measurement, which is worse than the bridged line this fix is
    // about. ooViz.isMissing has encoded the right rule since it was written
    // ("must render as a GAP, never as zero") and had no caller; it does now, with
    // an inline fallback so a stale service-worker copy of ooviz.js degrades to the
    // same semantics rather than silently reverting to zeros.
    const _missing = (v) => (typeof ooViz !== "undefined" && ooViz.isMissing)
      ? ooViz.isMissing(v) || !isFinite(v)
      : (v === null || v === undefined || !isFinite(v));
    const _GAP_FACTOR = 3;
    function _seriesRuns(points, opts) {
      opts = opts || {};
      const factor = opts.gapFactor || _GAP_FACTOR;
      const ok = (p) => p != null && !_missing(opts.value ? opts.value(p) : p.v);
      const at = (p) => (opts.time ? opts.time(p) : p.t);
      let cadence = 0;
      if (opts.timed) {
        const deltas = [];
        for (let i = 1; i < points.length; i++) {
          const a = at(points[i - 1]), b = at(points[i]);
          if (ok(points[i - 1]) && ok(points[i]) && isFinite(a) && isFinite(b) && b > a) deltas.push(b - a);
        }
        // A cadence guessed from one or two intervals is not a cadence. Below the
        // floor the series is left whole rather than split on a number we cannot
        // stand behind.
        if (deltas.length >= 3) {
          deltas.sort((x, y) => x - y);
          cadence = deltas[Math.floor(deltas.length / 2)];
        }
      }
      const runs = [];
      let cur = null;
      for (let i = 0; i < points.length; i++) {
        if (!ok(points[i])) { cur = null; continue; }          // a missing value is always a hole
        // A caller that had to DROP a missing value (ooChart, so the scales and the
        // sparse-bar threshold keep counting real observations only) marks the
        // survivor after it. Without this the hole would have to be inferred from
        // its width, and one dropped point is far too narrow to trip the cadence
        // rule -- so the line would quietly close over it again.
        if (points[i].gapBefore) cur = null;
        if (cur && cadence > 0) {
          const d = at(points[i]) - at(points[cur[cur.length - 1]]);
          if (isFinite(d) && d > factor * cadence) cur = null;  // a hole wider than the cadence
        }
        if (!cur) { cur = []; runs.push(cur); }
        cur.push(i);
      }
      return runs;
    }
    function dashChartSvg(points, unit, opts) {
      opts = opts || {};
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!points.length) {
        return `<div class="muted" style="padding:18px 0;font-size:12px">${esc(t9("not enough points in this window"))}</div>`;
      }
      const w = 300, h = 120, padL = 44, padR = 8, padT = 8, padB = 18;
      const n = points.length, lineMode = n >= _SPARSE_BAR_MAX;
      const ys = points.map(p => p.price);
      const dataMin = Math.min(...ys), dataMax = Math.max(...ys);
      // opts.zeroBase (Item Y, count series): the axis starts at a true ZERO, so a
      // count difference is read against zero and never against a window-min that
      // exaggerates it. Price LEVEL callers keep the window-min baseline (a
      // fabricated zero would be the dishonest direction there).
      const baseMin = opts.zeroBase ? Math.min(0, dataMin) : dataMin;
      // A FLAT series is centred in the plot instead of fabricating a span: the
      // old `(max-min)||1` fallback pinned a constant series to the very bottom
      // AND invented the ticks above it.
      const flat = dataMax <= baseMin;
      const minY = flat ? baseMin - 0.5 : baseMin, maxY = flat ? dataMax + 0.5 : dataMax;
      const span = (maxY - minY) || 1;
      const plotW = w - padL - padR;
      // Shared time axis (Slice 4 — maintainer "graph timescales should be coherent
      // between all sources"): when opts.t0/t1 (ISO dates) are given, every point is
      // placed at its TRUE calendar position on that ONE window, so a March point
      // sits at the same x on EVERY card of the board (coherent timescales, honest
      // gaps). Without it, the index-based mapping is byte-for-byte identical to
      // before (Home sparklines, trend windows — additive, no regression).
      const _ms = (d) => Date.parse(String(d).length <= 7 ? String(d) + "-01T00:00:00Z" : String(d) + "T00:00:00Z");
      const sa = opts.t0 ? _ms(opts.t0) : NaN, sb = opts.t1 ? _ms(opts.t1) : NaN;
      const shared = isFinite(sa) && isFinite(sb) && sb > sa;
      const X = i => padL + plotW * (n < 2 ? 0.5 : i/(n-1));
      const Xp = (p, i) => {
        if (!shared) return X(i);
        const m = _ms(p.observed_on);
        if (!isFinite(m)) return X(i);
        return Math.max(padL, Math.min(w - padR, padL + plotW * ((m - sa) / (sb - sa))));
      };
      const Y = v => padT + (h - padT - padB) * (1 - (v - minY)/span);
      const up = points[n-1].price >= points[0].price;
      // opts.neutral: a NEUTRAL metric (a corpus count) must not be painted in
      // market up=green/down=red semantics — fewer keywords is not "bad". Price
      // and market callers keep the directional colour.
      const col = opts.neutral ? 'var(--accent)' : (up ? 'var(--ok)' : 'var(--err)');
      // Discrete horizontal gridlines, each labelled — values from honestTicks
      // (flat -> one tick at the real value; integer data -> integer ticks).
      const grid = honestTicks(baseMin, dataMax, 3, _allInteger(ys) && Number.isInteger(baseMin)).map(v =>
        `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${w-padR}" y2="${Y(v).toFixed(1)}"
           stroke="var(--border)" stroke-dasharray="2 4" stroke-width="0.6"></line>
         <text x="${padL-4}" y="${(Y(v)+3).toFixed(1)}" text-anchor="end" font-size="8.5"
           fill="var(--muted)">${_axisNum(v)}</text>`).join("");
      // X ticks: in SHARED mode the ticks are the WINDOW endpoints (start/mid/end of
      // the plot at fixed positions) so every card reads the SAME coherent time
      // legend; otherwise first / middle / last point dates (YYYY-MM, de-duplicated).
      // Granularity follows the plotted span (hour / day / month) and duplicate
      // label TEXT is dropped — the old code sliced every label to YYYY-MM and
      // de-duplicated INDEXES, so two hourly snapshots in one month both printed
      // "2026-07" (maintainer-reported).
      const xfmt = shared
        ? _timeLabelFmt(opts.t0, opts.t1)
        : _timeLabelFmt(points[0].observed_on, points[n-1].observed_on);
      const xcand = shared
        ? [[padL, "start", opts.t0], [padL + plotW / 2, "middle", new Date((sa + sb) / 2).toISOString()],
           [w - padR, "end", opts.t1]]
        : [...new Set([0, Math.floor((n-1)/2), n-1])].map(i =>
            [X(i), i === 0 ? "start" : i === n-1 ? "end" : "middle", points[i].observed_on]);
      const xseen = new Set();
      const xticks = xcand.map(([x, anc, lab]) => {
        const text = xfmt(lab);
        if (xseen.has(text)) return "";               // dedupe on TEXT, not index
        xseen.add(text);
        return `<text x="${x.toFixed(1)}" y="${h-5}" text-anchor="${anc}"
               font-size="8.5" fill="var(--muted)">${esc(text)}</text>`;
      }).join("");
      // The series itself: a line when dense (n>=10), otherwise honest BARS (Item Y).
      // Bars anchor to the window-MIN — which the gridlines above already LABEL — so a
      // price-LEVEL difference stays visible and honest (NEVER a fabricated zero
      // baseline). A 2px cap is drawn at the true value so a flush min / equal / single
      // point stays visible (the cap marks the value, never an invented height).
      const baseY = Y(minY);
      const slot = (w - padL - padR) / Math.max(n, 1);
      const bw = Math.max(3, Math.min(slot * 0.62, 22));
      // ONE polyline PER RUN, never one across the whole series: a hole in the data
      // leaves a hole in the line. `shared` is the real-time-axis mode, so a time
      // gap only counts there (see _seriesRuns). A single-point run still gets a
      // dot, or a measurement surrounded by holes would vanish entirely.
      const _runs = _seriesRuns(points, {
        timed: shared, value: (p) => p.price, time: (p) => _ms(p.observed_on),
      });
      const _gapped = _runs.length > 1;
      const body = lineMode
        ? _runs.map(run => (run.length > 1
            ? `<polyline fill="none" stroke="${col}" stroke-width="1.6" points="${
                run.map(i => `${Xp(points[i], i).toFixed(1)},${Y(points[i].price).toFixed(1)}`).join(" ")}"></polyline>`
            : `<circle cx="${Xp(points[run[0]], run[0]).toFixed(1)}" cy="${Y(points[run[0]].price).toFixed(1)}" r="2" fill="${col}"></circle>`
          )).join("")
          + `<circle cx="${Xp(points[n-1], n-1).toFixed(1)}" cy="${Y(points[n-1].price).toFixed(1)}" r="2.4" fill="${col}"></circle>`
        : points.map((p, i) => {
            const cx = Xp(p, i), by = Y(p.price);
            const x0 = Math.max(padL, cx - bw / 2), x1 = Math.min(w - padR, cx + bw / 2);
            const bwc = Math.max(1, x1 - x0).toFixed(1);
            return `<rect x="${x0.toFixed(1)}" y="${by.toFixed(1)}" width="${bwc}" height="${Math.max(0, baseY - by).toFixed(1)}" fill="${col}" opacity="0.72"></rect>`
                 + `<rect x="${x0.toFixed(1)}" y="${(by - 0.5).toFixed(1)}" width="${bwc}" height="2" fill="${col}"></rect>`;
          }).join("");
      // Item Y: the sparse "dots shown / no curve interpolated" caveat is removed
      // app-wide; only the datapoint count is kept — but it now carries its UNIT
      // (opts.nUnit), because a bare "n=2" beside a value of 23 read as "23 or 2
      // documents?" (maintainer-reported). n counts DATAPOINTS, never entities.
      const nText = opts.nUnit
        ? ((window.OOI18N && OOI18N.tf) ? OOI18N.tf("n={n} {unit}", {n: n, unit: opts.nUnit})
                                        : `n=${n} ${opts.nUnit}`)
        : `n=${n}`;
      // A break is only meaningful if the reader is told what it means, so the note
      // appears exactly when one was actually drawn — never as standing boilerplate.
      const gapNote = _gapped
        ? `<div class="hint muted" style="margin-top:1px">${esc(t9("The line breaks where nothing was recorded — a gap is not a zero."))}</div>`
        : "";
      const caveat = (lineMode ? "" :
        `<div class="hint muted" style="margin-top:1px">${esc(nText)}</div>`) + gapNote;
      // The legend reads the SHARED window when coherent (so every card states the
      // same span), else this series' own first→last dates.
      const range = shared ? `${xfmt(opts.t0)} → ${xfmt(opts.t1)}`
        : (n >= 2 ? `${xfmt(points[0].observed_on)} → ${xfmt(points[n-1].observed_on)}`
                  : xfmt(points[0].observed_on));
      // a11y: a translated summary + a visually-hidden data table (audit PR G).
      // The stated lo/hi are the REAL data extremes, never the padded plot bounds.
      const aria = _chartAria(unit || "", n, xfmt(points[0].observed_on),
        xfmt(points[n - 1].observed_on), fmtNum(dataMin), fmtNum(dataMax));
      const srTable = _chartSrTable(
        points.map(p => ({date: p.observed_on, value: fmtNum(p.price)})), unit || "");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" style="display:block" role="img" aria-label="${esc(aria)}">
        ${grid}
        ${body}${xticks}</svg>${srTable}
        <div class="hint" style="display:flex;justify-content:space-between;margin-top:2px">
          <span><span style="display:inline-block;width:14px;height:0;border-top:2px solid ${col};vertical-align:middle"></span>
            ${esc(unit || "")}</span><span>${range}</span></div>${caveat}`;
    }

    // -- Family-stacked graphs (Slice 5) ------------------------------------ //
    // "In the 'all' subtab … stacking all curves into family graphs … as much
    // data but with fewer graphs" (maintainer 2026-06-17). One multi-series
    // ooChart per group (category / continent) replaces N small cards. INDEXED by
    // default so different-magnitude members of a family (gold vs copper, a 5000-pt
    // index vs a 130 OECD index) co-move honestly on one axis — the hover always
    // shows the REAL value, and a VISIBLE caveat states "relative, not absolute".
    // Each group is wrapped with data-cat so the SAME continent/category subtabs
    // filter the family graphs too. Reuses the ONE ooChart toolkit (invariant #16).
    // groups: [{key, label, series:[{label, unit, points:[{t,v}]}]}]; shared [t0,t1].
    function renderFamilyGraphs(host, groups, opts) {
      opts = opts || {};
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const live = groups.filter(g => g.series.some(s => (s.points || []).length));
      if (!live.length) { host.innerHTML = `<div class="muted">${esc(t("No data in this window yet."))}</div>`; return; }
      const cavText = t("Indexed to 100 at the window start — relative moves, not absolute levels; the hover shows the real value.");
      // Per-member action buttons (P2-10): families-first dropped the cards grid,
      // so the per-commodity tools (Analyse ↗ + price-detail+Correlate) migrate
      // INTO the family view as member chips — nothing lost (the Desk lesson). Each
      // action is {glyph,title,fn(series)}; the delegated handler resolves the live
      // series so no closure is stored in the DOM.
      const acts = Array.isArray(opts.memberActions) ? opts.memberActions : [];
      host.innerHTML = live.map((g, i) => {
        const liveSer = g.series.filter(s => (s.points || []).length);
        const members = acts.length
          ? `<div class="fam-members" style="grid-column:1/-1">`
            + liveSer.map((s, si) =>
                `<span class="fam-member"><span class="fam-mlabel">${esc(s.label)}</span>`
                + acts.map((a, ai) =>
                    `<button type="button" class="fam-mbtn" data-fam="${i}" data-si="${si}" data-act="${ai}"
                       title="${esc(a.title || "")}">${esc(a.glyph || "↗")}</button>`).join("")
                + `</span>`).join("")
            + `</div>`
          : "";
        return `<div class="fam-block mkt-cat" data-cat="${esc(g.key)}">
           <div class="vsect fam-head" style="grid-column:1/-1">
             <span>${esc(t(g.label))} <span class="muted">· ${liveSer.length} ${esc(t("series"))}</span></span>
             <button type="button" class="fam-enlarge" data-fam="${i}"
               title="${esc(t("Open this graph fullscreen with scale controls"))}">⛶</button>
           </div>
           <div class="fam-chart" style="grid-column:1/-1"></div>
           ${members}
         </div>`;
      }).join("") + `<div class="card-caveat">${esc(cavText)}</div>`;
      // Stash the live data for the delegated handlers (re-read live on every click,
      // so a board re-render never serves a stale closure — the ooSubtabs lesson).
      host._famGroups = live;
      host._famCaveat = cavText;
      host._famActions = acts;
      // ooChart renders imperatively into a live element, so instantiate after the
      // containers exist (in group order — the hosts match `live` 1:1).
      host.querySelectorAll(".fam-chart").forEach((el, i) => {
        const g = live[i]; if (!g) return;
        ooChart(el, g.series.filter(s => (s.points || []).length),
          {height: 200, indexed: opts.indexed !== false, logY: !!opts.logY});
      });
      if (!host._famWired) {
        host._famWired = true;
        host.addEventListener("click", (e) => {
          const eb = e.target.closest(".fam-enlarge");
          if (eb) {
            const g = host._famGroups[+eb.dataset.fam]; if (!g) return;
            // The ONE shared fullscreen graph overlay (P2-10) — the family's
            // multi-series on #chart-enlarge with the Absolute/Indexed/Log scales.
            // No caveat passed: this view's caveat is the per-mode "Indexed to 100 at
            // the window start…" statement, which the modal's own HINTS says for every
            // mode and keeps correct when the mode changes. Passing it here is what
            // made the note go stale on a scale toggle in the first place; the inline
            // .card-caveat still carries it for the un-enlarged family view.
            chartEnlarge(t(g.label), g.series.filter(s => (s.points || []).length), "", {scales: true});
            return;
          }
          const mb = e.target.closest(".fam-mbtn");
          if (mb) {
            const g = host._famGroups[+mb.dataset.fam]; if (!g) return;
            const ser = g.series.filter(s => (s.points || []).length)[+mb.dataset.si];
            const act = host._famActions[+mb.dataset.act];
            if (ser && act && typeof act.fn === "function") act.fn(ser);
          }
        });
      }
    }

    // Category display order + labels for the grouped Commodities board.
    const MKT_CATS = [
      ["energy", "Energy"], ["strategic", "Strategic & nuclear"], ["metals", "Base metals"],
      ["precious", "Precious metals"], ["construction", "Construction materials"],
      ["agriculture", "Agriculture & cereals"], ["fx", "Currencies"], ["custom", "Custom"],
    ];
    // Curated commodity SYMBOL → corpus search query (the "symbol→family seed
    // table", maintainer-ruled). Maps a price-feed symbol to the best plain
    // search term for that commodity's coverage in the corpus. Only symbols
    // whose raw code/name is a poor query are listed; everything unmapped falls
    // back to the series display name (s.name) — never an invented commodity.
    const COMMODITY_QUERY = {
      WTI: "oil", BRENT: "oil", NATGAS: "natural gas", NATGAS_EU: "natural gas",
      LNG_ASIA: "liquefied natural gas", COAL: "coal", URANIUM: "uranium",
      COPPER: "copper", ALUMINUM: "aluminium", NICKEL: "nickel", ZINC: "zinc",
      IRON_ORE: "iron ore", TIN: "tin", LEAD: "lead",
      GOLD: "gold", SILVER: "silver",
      CORN: "maize corn", WHEAT: "wheat", RICE: "rice", SOYBEANS: "soybeans",
      SUGAR: "sugar", COFFEE: "coffee", COCOA: "cocoa", COTTON: "cotton",
      RUBBER: "rubber", LOGS: "timber logs", SAWNWOOD: "sawnwood timber",
      EURUSD: "euro dollar exchange rate",
    };
    let _mktCatTabs = null;        // the commodities category ooSubtabs handle
    let _mktCat = "__all";          // the currently-selected category (persists across re-renders)
    let _mktView = "families";      // "cards" | "families" — families-first (P2-10); the cards code path stays reachable (Desk lesson) but the UI has no toggle
    function selectCommodityCat(key) {
      // Button/ARIA state is owned by the ooSubtabs component (universal
      // grammar, invariant #18); this callback only filters which category
      // section is visible. "__all" (the default lens) shows everything. The
      // family blocks carry the same .mkt-cat/data-cat, so this filters BOTH
      // the cards view and the families view.
      const changed = key !== _mktCat;
      _mktCat = key;  // remember it so a board re-render (auto-refresh / view toggle) keeps it
      // FAMILIES view: a specific category shows each commodity individually (one
      // graph per commodity), so the group set itself changes — RE-RENDER (the
      // exploded groups are built in commodityFamilies), never a CSS hide. Guard
      // on `changed` so the ooSubtabs init fire (which passes the current _mktCat)
      // never re-enters renderDashboard → _renderCommodityCatTabs → ooSubtabs.
      if (_mktView === "families") { if (changed) renderDashboard(); return; }
      document.querySelectorAll("#mkt-dashboard .mkt-cat").forEach(el => {
        el.style.display = (key === "__all" || el.dataset.cat === key) ? "" : "none";
      });
    }
    function setMktView(v) { _mktView = v; renderDashboard(); }
    // Build one family per present category: its member series windowed to the
    // shared range, ready for renderFamilyGraphs (Slice 5).
    function commodityFamilies(present, seriesFor, from, to) {
      const _ser = (s) => {
        const pts = windowPricesRange(MKT_PRICES[s.symbol] || [], from, to);
        const last = pts.length ? pts[pts.length - 1] : null;
        const unit = last ? `${last.currency}/${last.unit}` : "";
        return {
          label: s.name || s.symbol,
          unit,
          points: pts.map(p => ({t: p.observed_on, v: p.price})),
          // Carry the identity so the family member chips can open the corpus
          // analysis window (the curated family seed) AND the price detail.
          symbol: s.symbol,
          query: COMMODITY_QUERY[s.symbol] || s.name || s.symbol,
          commodity: {symbol: s.symbol, name: s.name, unit},
        };
      };
      // A SPECIFIC category subtab (not the general "All" lens) shows each
      // commodity INDIVIDUALLY — one graph per commodity — instead of merging the
      // category into one combined family graph (maintainer-ruled). "All" keeps
      // the combined per-category overview (dense helicopter view).
      if (_mktCat !== "__all") {
        const sel = present.find(([k]) => (k === "__other" ? "__other" : k) === _mktCat);
        if (sel) return seriesFor(sel[0]).map(s => ({key: s.symbol, label: s.name || s.symbol, series: [_ser(s)]}));
      }
      return present.map(([k, label]) => ({
        key: k === "__other" ? "__other" : k,
        label,
        series: seriesFor(k).map(_ser),
      }));
    }
    function renderDashboard() {
      if (!MKT_SERIES.length) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Window by ABSOLUTE dates [from,to] from the ooTimeScope control (no
      // longer a trailing `days` count).
      const from = _mktScope.from, to = _mktScope.to;
      // SHARED time axis (Slice 4): every card on the board is drawn against the
      // SAME [t0,t1] window so the timescales are coherent across all sources (a
      // monthly World-Bank series and a daily FRED series align on one calendar
      // axis). Falls back to the full data span when no window is set.
      const _span = mktDataSpan();
      const axT0 = from || _span.min, axT1 = to || _span.max;
      // Indices are NOT commodities (maintainer-ruled): they live in the
      // Indices tab; the board shows everything else, grouped by category.
      // The category comes straight from the series data (s.category), not a
      // guessed symbol map — never misfile an index as a commodity.
      const series = MKT_SERIES.filter(s => s.category !== "index");
      const byCat = {};
      for (const s of series) (byCat[s.category] || (byCat[s.category] = [])).push(s);
      // Category list is DATA-DRIVEN: only the categories actually present
      // among the loaded commodities (never an empty tab), in the declared
      // MKT_CATS display order; any unmapped category falls under "Other".
      const present = MKT_CATS.filter(([k]) => byCat[k]);
      const mappedKeys = new Set(MKT_CATS.map(([k]) => k));
      const otherCats = Object.keys(byCat).filter(k => !mappedKeys.has(k));
      if (otherCats.length) present.push(["__other", "Other"]);
      const sectionKey = ([k]) => k === "__other" ? "__other" : k;
      const seriesFor = k => k === "__other"
        ? otherCats.reduce((acc, c) => acc.concat(byCat[c]), []) : byCat[k];
      // FAMILIES view (Slice 5): one multi-series graph per category instead of N
      // cards — "as much data but with fewer graphs". Default stays Cards (the
      // existing per-card grid below), so there is no regression.
      if (_mktView === "families") {
        // Families-first (P2-10): the per-commodity tools the cards grid carried
        // migrate INTO each family graph as member chips — Analyse ↗ (the corpus
        // value) + the price detail (chartSymbol → the fullscreen overlay, which
        // preserves "Correlate with news"). Nothing is lost (the Desk lesson).
        renderFamilyGraphs($("mkt-dashboard"), commodityFamilies(present, seriesFor, from, to), {
          memberActions: [
            {glyph: "⊞", title: t("Open this in the analysis window — its corpus coverage"),
             fn: (s) => openAnalysisFor(s.query, {commodity: s.commodity})},
            {glyph: "📈", title: t("Price detail + correlate with news"),
             fn: (s) => chartSymbol(s.symbol, (s.commodity && s.commodity.unit) || "")},
          ],
        });
        _renderMktViewToggle(t);
        _renderCommodityCatTabs(present, sectionKey, t);
        return;
      }
      $("mkt-dashboard").innerHTML = present.map(([k, label]) =>
        `<div class="mkt-cat" data-cat="${esc(sectionKey([k]))}" style="display:contents">` +
        `<div class="vsect" style="grid-column:1/-1">${esc(t(label))}</div>` +
        seriesFor(k).map(s => {
          const all = MKT_PRICES[s.symbol] || [];
          // RESPECT the window (invariant #16): never silently expand a narrow
          // window to the full history, never downsample within it. A sparse
          // window renders as honest dots (handled in dashChartSvg), so the
          // smallest scale no longer dumps the entire series — it shows exactly
          // the FULL-RESOLUTION points that fall in [from,to].
          const pts = windowPricesRange(all, from, to);
          const last = pts.length ? pts[pts.length-1] : (all.length ? all[all.length-1] : null);
          const first = pts.length ? pts[0] : null;
          let change = "";
          if (first && last && first.price) {
            const pct = (last.price - first.price) / first.price * 100;
            change = `<span class="pill ${pct>=0?'ok':'err'}">${pct>=0?'+':''}${pct.toFixed(1)}%</span>`;
          }
          const lv = last ? `${fmtNum(last.price)} <span class="muted">${esc(last.currency)}/${esc(last.unit)}</span>` : '—';
          // The TITLE is its own clickable affordance: it investigates the
          // commodity's coverage in the corpus via the analysis window
          // (openAnalysisFor — the universal corpora object). stopPropagation
          // keeps the card's own chartSymbol click (the price detail) intact;
          // the query comes from the curated COMMODITY_QUERY seed map, else the
          // series display name. The caveat is the maintainer's binding rule:
          // this surfaces co-occurrence in the corpus, NEVER causation.
          const q = COMMODITY_QUERY[s.symbol] || s.name || s.symbol;
          // Carry the commodity identity so the analysis window's Price subtab can
          // overlay this commodity's price curve with the term's corpus coverage.
          const cOpts = esc(JSON.stringify({commodity: {symbol: s.symbol, name: s.name, unit: last ? `${last.currency}/${last.unit}` : ""}}));
          // The GRAPH is a first-class entry into the analysis WINDOW (ledger
          // MARKETS item 4): a clear "Analyse ↗" affordance UNDER the chart opens
          // the commodity's keyword-family corpus via openAnalysisFor (the same
          // opener the title ⊞ already uses — NOT a duplicate opener). The card
          // body keeps its chartSymbol price detail + correlation (the Desk
          // lesson: never silently lose a tool); stopPropagation keeps the two
          // paths distinct. The term is the curated COMMODITY_QUERY family seed,
          // else the real series name/symbol — never a fabricated family. The
          // window's Price subtab OVERLAYS the price curve with the term's corpus
          // coverage timeline (the commodity identity rides along in cOpts, below).
          return `<div class="stat" style="cursor:pointer" title="open detail + correlation"
              onclick="chartSymbol(${esc(JSON.stringify(s.symbol))}, ${esc(JSON.stringify(last?last.unit:''))})">
            <div style="display:flex;justify-content:space-between;align-items:baseline">
              <button type="button" title="${esc(s.name || s.symbol)}"
                style="background:none;border:none;padding:0;margin:0;font:inherit;font-weight:700;color:var(--accent);cursor:pointer;text-decoration:none"
                onclick="event.stopPropagation(); openAnalysisFor(${esc(JSON.stringify(q))}, ${cOpts})">${esc(s.symbol)} ⊞</button> ${change}</div>
            <div class="muted" style="font-size:12px;margin:2px 0 6px">${lv}</div>
            ${dashChartSvg(pts, last ? `${last.currency}/${last.unit}` : "", {t0: axT0, t1: axT1})}
            <div style="margin-top:4px"><button class="tiny secondary" type="button"
                title="${esc(t("Open this in the analysis window — its corpus coverage"))}"
                onclick="event.stopPropagation(); openAnalysisFor(${esc(JSON.stringify(q))}, ${cOpts})">${esc(t("Analyse"))} ↗</button></div></div>`;
        }).join("") + `</div>`
      ).join("");
      _renderMktViewToggle(t);
      _renderCommodityCatTabs(present, sectionKey, t);
    }
    // The Cards/Families view toggle (Slice 5) — only meaningful with >1 category;
    // default Cards (no regression). Reuses the chip grammar.
    function _renderMktViewToggle(t) {
      // Families-first (P2-10): the Cards/Families toggle is DROPPED — families is
      // the one board view, with the per-commodity tools migrated into it. The
      // cards code path stays reachable programmatically (Desk lesson), but there
      // is no UI switch, so this just keeps the slot empty.
      const tog = $("mkt-viewtoggle");
      if (tog) { tog.innerHTML = ""; tog.style.display = "none"; }
    }
    // Category SUB-TABS (universal subtab grammar, invariant #18): the nav from the
    // categories actually present, with an "All" default lens (like Home families).
    // Skip the nav entirely when only one category is present. Shared by BOTH the
    // cards view and the families view (the .mkt-cat data-cat filter works in both).
    function _renderCommodityCatTabs(present, sectionKey, t) {
      const catNav = $("commodities-cats");
      if (!catNav) return;
      if (present.length > 1) {
        catNav.style.display = "";
        // Preserve the operator's selected category across re-renders (auto-refresh,
        // cards/families toggle, time-scope change) — only fall back to "All" when the
        // previously-selected category is no longer present (#31).
        const valid = ["__all"].concat(present.map(([k]) => sectionKey([k])));
        const initial = valid.indexOf(_mktCat) >= 0 ? _mktCat : "__all";
        catNav.innerHTML =
          `<button${initial === "__all" ? ' class="active"' : ""} data-tab="__all">${esc(t("All"))}</button>`
          + present.map(([k, label]) => {
              const key = sectionKey([k]);
              return `<button${initial === key ? ' class="active"' : ""} data-tab="${esc(key)}">${esc(t(label))}</button>`;
            }).join("");
        _mktCatTabs = ooSubtabs(catNav, selectCommodityCat, {initial});
      } else {
        catNav.style.display = "none";
        catNav.innerHTML = "";
        _mktCatTabs = null;
        selectCommodityCat("__all");
      }
    }

    async function loadMarketData(btn) {
      btn.disabled = true;
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Fetch market and index data from the official feeds"))) { btn.disabled = false; return; }
      const status = $("mkt-dash-status");
      status.textContent = "Importing official feeds… (downloads CSVs, may take a moment)";
      try {
        const r = await api("/api/markets/feeds/import-all", {method: "POST"});
        status.textContent = `Imported ${r.points_imported} point(s) across ${r.feeds} feeds${r.failed?`, ${r.failed} failed`:""}.`;
        _renderFeedVerdicts("mkt-verdicts", r, "");
        for (const k in MKT_PRICES) delete MKT_PRICES[k];
        await loadDashboard();
        if (_mktConfigLoaded) loadFeeds();
        toast("Market data loaded.");
      } catch (e) { status.textContent = ""; toast(_failMsg("Load failed: {error}", e), "err"); }
      finally { btn.disabled = false; }
    }

    function toggleMktConfig() {
      const el = $("mkt-config"), open = el.style.display === "none";
      el.style.display = open ? "" : "none";
      $("mkt-config-caret").textContent = open ? "▾" : "▸";
      if (open && !_mktConfigLoaded) { _mktConfigLoaded = true; loadMarketConfig(); }
    }

    async function loadMarketConfig() {
      try {
        const sources = await api("/api/sources");
        $("mkt-source").innerHTML = sources.map(s =>
          `<option value="${s.id}">${esc(s.name)} (${esc(s.domain)})</option>`).join("")
          || '<option value="">(no sources — add one first)</option>';
      } catch (e) { /* leave as-is */ }
      loadFeeds(); loadRules();
    }

    async function loadRules() {
      try {
        const d = await api("/api/markets/rules");
        const t = $("mkt-rules");
        t.innerHTML = "<tr><th>Symbol</th><th>Category</th><th>Source</th><th>Last status</th><th></th></tr>" +
          (d.rules.length ? d.rules.map(r => `<tr>
            <td><strong>${esc(r.symbol)}</strong></td><td class="muted">${esc(r.category)}</td>
            <td class="muted">${esc(r.source_name||"")}</td>
            <td class="muted" style="font-size:12px;max-width:240px">${esc(r.last_status||"never run")}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="runMarketRule(${r.id})" title="Fetch once and apply the rule">Test</button>
              <button class="tiny secondary" onclick="chartSymbol(${esc(JSON.stringify(r.symbol))}, ${esc(JSON.stringify(r.unit||''))})">Chart</button>
              <button class="tiny danger" onclick="deleteMarketRule(${r.id})">Delete</button></td></tr>`).join("")
            : `<tr><td colspan="5" class="muted">No extraction rules. Feeds cover most needs; add a rule below to scrape a price off a specific page.</td></tr>`);
      } catch (e) { /* rules optional */ }
    }

    // -- Official CSV feeds ------------------------------------------------- //
    async function loadFeeds() {
      try {
        const d = await api("/api/markets/feeds");
        const t = $("feed-table");
        if (!d.feeds.length) { t.innerHTML = `<tr><td class="muted">No feeds configured.</td></tr>`; return; }
        t.innerHTML = "<tr><th>Series</th><th>Symbol</th><th>Unit</th><th>Stored</th><th></th></tr>" +
          d.feeds.map(f => `<tr>
            <td>${esc(f.name)}<div class="muted" style="font-size:12px">${esc(f.market||"")}</div></td>
            <td><strong>${esc(f.symbol)}</strong></td>
            <td class="muted">${esc(f.currency)}/${esc(f.unit)}</td>
            <td class="muted">${f.points}</td>
            <td style="white-space:nowrap">
              <button class="tiny secondary" onclick="importFeed(${esc(JSON.stringify(f.key))})">Import</button>
              <button class="tiny secondary" onclick="chartSymbol(${esc(JSON.stringify(f.symbol))}, ${esc(JSON.stringify(f.unit))})">Chart</button>
            </td></tr>`).join("");
      } catch (e) { /* feeds optional */ }
    }

    async function importFeed(key) {
      if (!await ensureOnline(((window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x))("Fetch market and index data from the official feeds"))) return;
      toast("Importing feed… (downloads a CSV, may take a moment)");
      try {
        const r = await api(`/api/markets/feeds/${encodeURIComponent(key)}/import`, {method: "POST"});
        toast(`Imported ${r.imported} new point(s) for ${r.symbol} (${r.skipped_existing} already had).`);
        delete MKT_PRICES[r.symbol]; loadFeeds(); loadDashboard();
      } catch (e) { toast(_failMsg("Import failed: {error}", e), "err"); }
    }

    async function importCustomFeed() {
      const body = {
        url: $("feed-url").value.trim(),
        symbol: $("feed-symbol").value.trim(),
        unit: $("feed-unit").value.trim() || "t",
        currency: $("feed-currency").value.trim() || "USD",
        market: $("feed-market").value.trim() || null,
        date_column: $("feed-datecol").value.trim() || null,
        value_column: $("feed-valcol").value.trim() || null,
      };
      if (!body.url || !body.symbol) { toast("URL and symbol are required.", "err"); return; }
      $("feed-result").textContent = "Downloading and importing…";
      try {
        const r = await api("/api/markets/feeds/import-url", {method: "POST", body: JSON.stringify(body)});
        $("feed-result").innerHTML = `<span class="pill ok">imported</span> ${r.imported} new point(s) for ` +
          `${esc(r.symbol)} (${r.skipped_existing} already present, ${r.received} in feed).`;
        toast("Feed imported."); delete MKT_PRICES[body.symbol]; loadFeeds(); loadDashboard();
      } catch (e) { $("feed-result").textContent = ""; toast(_failMsg("Import failed: {error}", e), "err"); }
    }

    async function addMarketRule() {
      const body = {
        source_id: Number($("mkt-source").value),
        symbol: $("mkt-symbol").value.trim(),
        label: $("mkt-label").value.trim() || null,
        url: $("mkt-url").value.trim(),
        selector: $("mkt-selector").value.trim(),
        attribute: $("mkt-attr").value.trim() || null,
        value_regex: $("mkt-regex").value.trim() || null,
        currency: $("mkt-currency").value.trim() || "USD",
        unit: $("mkt-unit").value.trim() || "kg",
        market: $("mkt-market").value.trim() || null,
        category: "commodity",
      };
      if (!body.source_id || !body.symbol || !body.url || !body.selector) {
        toast("Source, symbol, URL and selector are required.", "err"); return;
      }
      try {
        await api("/api/markets/rules", {method: "POST", body: JSON.stringify(body)});
        toast("Rule added.");
        ["mkt-symbol","mkt-label","mkt-url","mkt-selector","mkt-attr","mkt-regex","mkt-market"]
          .forEach(id => $(id).value = "");
        loadRules();
      } catch (e) { toast(_failMsg("Add failed: {error}", e), "err"); }
    }

    async function runMarketRule(id) {
      toast("Fetching and applying rule…");
      try {
        const o = await api(`/api/markets/rules/${id}/run`, {method: "POST"});
        if (o.status === "stored_price")
          toast(`Stored ${o.value} for ${o.symbol} (${o.observed_on}).`);
        else if (o.status === "duplicate_price")
          toast(`Already had a point for ${o.symbol} today (${o.value}).`, "warn");
        else
          toast(`${o.status}: ${o.reason || ""}`, "err");
        delete MKT_PRICES[o.symbol]; loadRules(); loadDashboard();
      } catch (e) { toast(_failMsg("Run failed: {error}", e), "err"); }
    }

    async function deleteMarketRule(id) {
      if (!confirm("Delete this rule? Stored price history is kept.")) return;
      try { await api(`/api/markets/rules/${id}`, {method: "DELETE"}); toast("Rule deleted."); loadRules(); }
      catch (e) { toast(_failMsg("Delete failed: {error}", e), "err"); }
    }

    // ===== THE chart toolkit (maintainer-ruled: ONE component for every =====
    // chart surface). Honesty rules built in: the FULL series renders within
    // the visible window -- never downsampled, never thinned; SPARSE series
    // render as honest POINTS with n shown and an early-corpus caveat (a line
    // only when density supports it; no interpolation faking a curve).
    // Interactions: wheel = time zoom (cursor-anchored), drag = pan,
    // hover = crosshair readout, click = pin exact X/Y, dblclick = reset,
    // legend chips toggle series.
    // Turn a brushed span on a single-keyword trend chart into an analysis corpus.
    //
    // Only for charts whose x-axis IS article time. The range is resolved SERVER-side
    // against KeywordMention.observed_on -- the column the chart is drawn from -- and not
    // through the published_at date filter, which means a different thing: an article
    // whose publish date could not be extracted is plotted on the chart and invisible to
    // that filter, so the filter route would return fewer articles than the bars the
    // reader just selected (pinned in tests/test_chart_time_vs_filter_time.py).
    //
    // Both numbers are reported because they are different quantities: a bar's height is
    // a MENTION total, the selection is a set of ARTICLES, and one article mentioning a
    // term three times raises the bar by three and the set by one.
    function _brushToCorpus(term, bucket) {
      return async (from, to, ctl) => {
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        const tf = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_m, k) => v[k]));
        try {
          // The chart's OWN bucket travels with the span: a brush over a weekly chart can
          // only honestly select whole weeks, so the server widens the range to bucket
          // edges. Without it a bar sitting inside the band could contribute none of its
          // height and the reported total would disagree with the bars just selected --
          // measured 65 drawn against 50 reported before this.
          const r = await api(`/api/insights/trend-articles?term=${encodeURIComponent(term)}`
            + `&start=${encodeURIComponent(from)}&end=${encodeURIComponent(to)}`
            + `&bucket=${encodeURIComponent(bucket || "day")}`);
          const ids = (r && r.article_ids) || [];
          if (!ids.length) {
            // An honest empty, never a silent no-op: the span really held nothing that
            // can be opened, and saying so is the difference between "no articles" and
            // "the button is broken".
            toast(tf("No articles in {from} → {to}.", {from, to}), "err");
            if (ctl && ctl.clear) ctl.clear();
            return;
          }
          // The term is named so the toast is self-contained: "3 articles \u00b7 50
          // mentions" alone does not say WHAT was counted, and the reader would have to
          // notice the search chip elsewhere on the page to recover it.
          // r.start/r.end are the EFFECTIVE span after bucket expansion. Showing the raw
          // drag instead would report a period that was not the one queried.
          const eff = {from: r.start || from, to: r.end || to};
          let note = tf("{term} \u00b7 {articles} articles \u00b7 {mentions} mentions \u00b7 {from} \u2192 {to}",
                        {term, articles: r.articles, mentions: r.mentions,
                         from: eff.from, to: eff.to});
          if (r.quarantined_excluded) {
            note += " · " + tf("{n} quarantined, not included",
                                   {n: r.quarantined_excluded});
          }
          if (r.capped) note += " · " + t("showing the first 5000");
          toast(note);
          openAnalysisForIds(ids, tf("{term}: {from} → {to}", {term, from, to}));
          if (ctl && ctl.clear) ctl.clear();
        } catch (e) {
          // api() already threw an Error whose message _apiErrorMessage composed, so the
          // message is used directly. Passing the Error BACK through _apiErrorMessage
          // would read e.detail (undefined) and then res.status on a string, rendering
          // the "undefined undefined" that helper exists to prevent.
          toast((e && e.message) || t("Could not open that period"), "err");
        }
      };
    }

    // Composite lookup for chart chrome: the KEY is a fixed template so it is keyable
    // x12, the VALUES are data interpolated after translation (the OOI18N.tf discipline).
    function _figTf(tpl, vars) {
      if (window.OOI18N && OOI18N.tf) return OOI18N.tf(tpl, vars);
      return tpl.replace(/\{(\w+)\}/g, (_m, k) => vars[k]);
    }

    function ooChart(el, seriesList, opts = {}) {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      el.innerHTML = "";
      // The canvas is sized in FIXED px, so it must never be wider than its host:
      // a 320 px hard floor (and a 680 px fallback when the element was not laid
      // out yet) made the chart overflow a narrower tile, with no overflow rule
      // anywhere in the tile/row/panel chain to clip it (maintainer-reported
      // "graphs do not fit their boxes"). Measure the real container; when it is
      // not laid out yet (hidden tab), re-render ONCE when it gains a width
      // instead of guessing a size that will overflow.
      const avail = el.clientWidth || (el.parentElement ? el.parentElement.clientWidth : 0);
      if (!avail) {
        if (typeof ResizeObserver === "function" && !el._ooChartPending) {
          el._ooChartPending = true;
          const ro = new ResizeObserver(() => {
            if (!el.clientWidth) return;
            ro.disconnect(); el._ooChartPending = false;
            ooChart(el, seriesList, opts);
          });
          ro.observe(el);
        }
        return;
      }
      const W = Math.max(120, Math.min(avail, opts.maxWidth || 900));
      const H = opts.height || 220, padL = 52, padR = 10, padT = 10, padB = 24;
      const wrap = document.createElement("div");
      const cv = document.createElement("canvas");
      const dpr = window.devicePixelRatio || 1;
      cv.width = W * dpr; cv.height = H * dpr;
      cv.style.cssText = `width:${W}px;height:${H}px;display:block;background:var(--panel2);border:1px solid var(--border);border-radius:8px;cursor:crosshair;touch-action:none`;
      const legend = document.createElement("div");
      legend.style.cssText = "display:flex;gap:10px;flex-wrap:wrap;font-size:12px;margin-top:4px;align-items:center";
      const readout = document.createElement("div");
      readout.className = "hint"; readout.style.minHeight = "18px";
      wrap.appendChild(cv); wrap.appendChild(legend); wrap.appendChild(readout); el.appendChild(wrap);

      const toMs = (x) => {
        if (typeof x === "number") return x;
        const wk = /^(\d{4})-W(\d{2})$/.exec(x);   // ISO week -> its Monday
        if (wk) {
          const jan4 = Date.UTC(+wk[1], 0, 4);
          const dow = (new Date(jan4).getUTCDay() + 6) % 7;
          return jan4 - dow * 864e5 + (+wk[2] - 1) * 7 * 864e5;
        }
        if (/^\d{4}-\d{2}$/.test(x)) return Date.parse(x + "-01");
        return Date.parse(x);
      };
      const all = seriesList.map((s, i) => ({
        label: s.label || `#${i + 1}`, unit: s.unit || "",
        // Three redundant channels per series (see _FIG_STYLES): colour, dash
        // pattern, marker shape. A caller-supplied s.color still wins — a surface
        // that deliberately means something by its colour keeps saying it — but it
        // gets the dash and marker too, so it is identifiable without the hue.
        style: _figStyle(i),
        color: s.color || _figStyle(i).color,
        // `+p.v` alone made a MISSING value a plotted ZERO: +null is 0 and
        // isFinite(0) is true, so a published gap survived the filter as a real
        // measurement of nothing. No caller passes nulls today -- /api/stats/
        // chart-series is built to preserve them ("A GAP IS A GAP",
        // src/stats/series.py:17) and has no frontend consumer yet -- so this is a
        // trap closed before it bites rather than a live defect. A missing value is
        // now dropped AND marked, so the line breaks there instead of being drawn
        // through a point that was never measured.
        pts: (() => {
          const out = [];
          let hole = false;
          for (const p of (s.points || [])) {
            const t = toMs(p.t);
            if (_missing(p.v) || !isFinite(t)) { hole = true; continue; }
            out.push({t, v: +p.v, gapBefore: hole});
            hole = false;
          }
          return out.sort((a, b) => a.t - b.t);
        })(),
        hidden: false,
      })).filter(s => s.pts.length);
      if (!all.length) { el.innerHTML = `<div class="muted">${esc(t9("no data points yet"))}</div>`; return; }
      const tMin = Math.min(...all.map(s => s.pts[0].t)), tMax = Math.max(...all.map(s => s.pts[s.pts.length - 1].t));
      const span0 = Math.max(tMax - tMin, 1);
      let t0 = tMin, t1 = tMax, pinned = null, pinnedS = null;
      const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
      const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n) || "#888";
      const fmtV = (v) => (typeof fmtNum === "function") ? fmtNum(v) : String(v);
      const fmtT = (ms) => _msLabel(ms, Math.max(tMax - tMin, 1));
      // a11y (audit PR G): the canvas is opaque to screen readers — give it a
      // role + translated summary, and a visually-hidden per-series data table.
      const allV = all.flatMap(s => s.pts.map(p => p.v));
      cv.setAttribute("role", "img");
      cv.setAttribute("aria-label", _chartAria(
        all.map(s => s.label).join(", "), allV.length, fmtT(tMin), fmtT(tMax),
        fmtV(Math.min(...allV)), fmtV(Math.max(...allV))));
      const srWrap = document.createElement("div");
      srWrap.className = "sr-only";
      srWrap.innerHTML = all.map(
        s => _chartSrTable(s.pts.map(p => ({date: fmtT(p.t), value: fmtV(p.v)})), s.label)).join("");
      wrap.appendChild(srWrap);
      const plotW = W - padL - padR, plotH = H - padT - padB;
      const Xof = (ms) => padL + plotW * ((ms - t0) / Math.max(t1 - t0, 1));
      // The inverse, for turning a pointer position back into a moment. Clamped to the
      // plot so a drag that leaves the canvas selects the visible edge rather than a
      // time outside the window the reader can see.
      const msAt = (clientX) => {
        const r = cv.getBoundingClientRect();
        const f = Math.max(0, Math.min(1, ((clientX - r.left) - padL) / plotW));
        return t0 + (t1 - t0) * f;
      };
      // BRUSH-TO-SELECT (plan F4). Opt-in per chart via opts.onSelectRange, and the
      // opt-in is a correctness rule, not a convenience: only a chart whose x-axis IS
      // article time can honestly answer "which articles are under this span". A
      // commodity price chart's axis is price time and an official-statistics chart's is
      // the observation period — brushing either and calling the result "the articles
      // behind this" would be a category error, so those callers pass nothing and get no
      // affordance at all. With opts.onSelectRange absent every line below is inert and
      // this component behaves exactly as before.
      // The calendar day a moment falls on, in LOCAL time. Shared by the live readout
      // and the emitted span so the two AGREE BY CONSTRUCTION: fmtT picks its
      // granularity from the whole axis span, so on a multi-month chart it renders
      // "2026-05" while the brush selects 2026-05-10 -- the reader was shown a month and
      // given a span starting mid-month, with no way to tell before releasing. Local,
      // not UTC, because toISOString() on a local midnight lands on the previous day.
      const dayOf = (ms) => {
        const d = new Date(ms);
        return new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
      };
      // Bucket edges, so the live readout previews the span the SERVER will use. Without
      // this the preview showed the raw drag (2026-05-10 -> 06-26) and the result reported
      // the widened weeks (05-04 -> 06-28): two different spans for one gesture, which is
      // the same preview-vs-action divergence the shared day formatter already fixed once.
      const _snap = (ms, end) => {
        const d = new Date(ms);
        const b = opts.bucket || "day";
        if (b === "week") {
          const dow = (d.getDay() + 6) % 7;              // Monday-based, matching ISO weeks
          d.setDate(d.getDate() - dow + (end ? 6 : 0));
        } else if (b === "month") {
          if (end) { d.setMonth(d.getMonth() + 1, 0); } else { d.setDate(1); }
        }
        return d.getTime();
      };
      const canBrush = typeof opts.onSelectRange === "function";
      let brushMode = false, bFrom = null, bTo = null;
      // The affordance sits INSIDE the chart, the same convention ooMap's zoom and layer
      // controls follow: a reader should not have to know a modifier exists. A <button>
      // with a real listener, never an inline onclick, so this stays off the
      // 'unsafe-inline' script-src debt; aria-pressed carries the state for a reader who
      // cannot see the accent, and the translated title inherits the #oo-tip hover.
      let brushBtn = null;
      if (canBrush) {
        const bar = document.createElement("div");
        bar.style.cssText = "display:flex;gap:6px;align-items:center;margin-top:4px";
        brushBtn = document.createElement("button");
        brushBtn.type = "button";
        brushBtn.className = "chip";
        brushBtn.textContent = t9("Select a period");
        brushBtn.title = t9("Drag across the chart to open the articles in that period. Hold Shift to drag without switching mode.");
        brushBtn.setAttribute("aria-pressed", "false");
        brushBtn.addEventListener("click", () => {
          brushMode = !brushMode;
          brushBtn.setAttribute("aria-pressed", brushMode ? "true" : "false");
          brushBtn.classList.toggle("on", brushMode);
          cv.style.cursor = brushMode ? "ew-resize" : "crosshair";
          if (!brushMode) { bFrom = bTo = null; }
          draw();
        });
        bar.appendChild(brushBtn);
        // After the LEGEND but before the readout. Between canvas and legend (the first
        // placement) wedged a control between the chart and the caption describing it;
        // appended at the end it would land after the .sr-only table.
        wrap.insertBefore(bar, readout);
      }
      // Indexed mode (opts.indexed, maintainer-ruled 2026-06-17): each series is
      // rebased to 100 at its first value in the VISIBLE window, so series of
      // DIFFERENT units (e.g. article coverage + a commodity price) co-move on ONE
      // shared axis WITHOUT conflating magnitudes — an honest RELATIVE view (the
      // hover still shows the REAL value/unit). _base is set per draw on the
      // persistent series so visible() copies and the hover inherit it. When
      // opts.indexed is off, pv() is the identity, so every existing chart is
      // byte-for-byte unchanged.
      const pv = (s, p) => (opts.indexed && s._base) ? (p.v / s._base * 100) : p.v;
      // Log-Y mode (opts.logY, maintainer-ruled 2026-06-17 markets revamp): the
      // y-axis maps log10(value) so series spanning orders of magnitude (a 5000-pt
      // index next to a 130 OECD index) read together; labels + hover still show
      // the REAL value (vtInv back-transforms the gridline value). Identity when
      // off, so every existing chart is byte-for-byte unchanged (the same additive
      // contract as opts.indexed). zeroBase is ignored under logY (log(0) is -∞).
      const LOGEPS = 1e-9;
      // log10(0) is -Infinity, so a series containing a zero has NO honest position on a
      // log axis -- and the clamp to LOGEPS invented one. Measured on the source
      // qualification tile (four integer series in 0..6, zeros at the start): the axis
      // spanned log-space -9..0.78, so the real differences occupied about 5% of the plot
      // height, honestTicks labelled log-space ticks back through vtInv and printed
      // "0.003" and TWO "0" gridlines -- none of them values a count can take -- and every
      // true zero was drawn as a plotted point sitting on the floor with a line through it.
      // A fabricated axis, found by rendering the modal and reading its ticks.
      //
      // It never showed before because logY shipped for the markets boards, where an index
      // value is never 0. So the mode is REFUSED when the data cannot support it: fall back
      // to linear (zero-based, integer ticks -- the honest axis for counts) and SAY so,
      // rather than drawing a decade range the data never occupied. Judged over the WHOLE
      // series, not the visible window, so the axis cannot silently flip while zooming.
      const logOk = !!opts.logY
        && all.every(s => (s.pts || []).every(p => !_missing(p.v) && +p.v > 0));
      const logRefused = !!opts.logY && !logOk;
      const vt = (v) => logOk ? Math.log10(Math.max(v, LOGEPS)) : v;   // value -> axis space
      const vtInv = (d) => logOk ? Math.pow(10, d) : d;                // axis space -> value (labels)
      if (logRefused) {
        const warn = document.createElement("div");
        warn.className = "hint muted";
        warn.style.cssText = "font-size:11px";
        warn.textContent = t9("Linear scale: a log axis cannot place a zero, and this data has some.");
        wrap.insertBefore(warn, readout);
      }

      function visible() {
        return all.filter(s => !s.hidden).map(s => ({...s, vis: s.pts.filter(p => p.t >= t0 && p.t <= t1)}));
      }
      function draw() {
        ctx.clearRect(0, 0, W, H);
        if (opts.indexed) for (const s of all) {        // rebase each series to 100 at its first visible value
          const vis = s.pts.filter(p => p.t >= t0 && p.t <= t1);
          const fnz = vis.find(p => p.v !== 0);
          s._base = fnz ? fnz.v : (vis.length ? (vis[0].v || 1) : 1);
        }
        const vs = visible();
        const ys = vs.flatMap(s => s.vis.map(p => vt(pv(s, p))));
        if (!ys.length) { readout.textContent = t9("no points in this window — zoom out (double-click)"); return; }
        const dataLo = (opts.zeroBase && !logOk) ? Math.min(0, ...ys) : Math.min(...ys);
        const dataHi = Math.max(...ys);
        // A FLAT series is centred instead of fabricating a span: the old
        // `(yMax-yMin)||1` fallback drew 23 / 23.33 / 23.67 / 24 for a constant
        // 23 — three ticks the data never reaches (2026-08-01 ruling 10).
        const flatY = dataHi <= dataLo;
        const yMin = flatY ? dataLo - 0.5 : dataLo, yMax = flatY ? dataHi + 0.5 : dataHi;
        const ySpan = (yMax - yMin) || 1;
        const Yof = (v) => padT + plotH * (1 - (v - yMin) / ySpan);
        ctx.font = "10px sans-serif"; ctx.fillStyle = cssVar("--muted"); ctx.strokeStyle = cssVar("--border");
        // Ticks in the data's own units: integer-only for a count axis (never a
        // fractional count), exactly one tick for a flat series. Under logY the
        // axis space is log10, so integer snapping applies to the LABEL values,
        // not the axis positions — hence the vtInv round-trip stays as-is.
        const tickInt = !logOk && !opts.indexed && _allInteger(ys);
        for (const v of honestTicks(dataLo, dataHi, 4, tickInt)) {
          const y = Yof(v);
          ctx.setLineDash([2, 4]); ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
          ctx.setLineDash([]); ctx.textAlign = "right"; ctx.fillText(fmtV(vtInv(v)), padL - 4, y + 3);
        }
        const nTicks = Math.max(2, Math.min(6, Math.floor(plotW / 110)));
        ctx.textAlign = "center";
        // Granularity follows the VISIBLE window (zooming into a day stops
        // printing the same date six times), and duplicate label TEXT is dropped.
        const winFmt = (ms) => _msLabel(ms, Math.max(t1 - t0, 1));
        const seenT = new Set();
        for (let g = 0; g <= nTicks; g++) {
          const ms = t0 + (t1 - t0) * g / nTicks;
          const lab = winFmt(ms);
          if (seenT.has(lab)) continue;
          seenT.add(lab);
          ctx.fillText(lab, Math.min(Math.max(Xof(ms), padL + 28), W - padR - 28), H - 8);
        }
        for (const s of vs) {
          if (!s.vis.length) continue;
          const n = s.vis.length, pxPer = plotW / Math.max(n - 1, 1);
          const barMode = n < _SPARSE_BAR_MAX;              // Item Y: n<10 -> bars, n>=10 -> line
          const st = s.style || _figStyle(0);
          ctx.strokeStyle = s.color.startsWith("var(") ? cssVar(s.color.slice(4, -1)) : s.color;
          ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 1.8;
          if (barMode) {
            // Bars anchor to the plot baseline Yof(yMin): true ZERO for zeroBase
            // (count) series, else the window-MIN which the gridlines LABEL (price
            // levels) — never a fabricated zero. A 2px cap marks the value so a
            // flush/equal/single point stays visible.
            //
            // GROUPED, not overlaid, when more than one series is in bar mode. Every
            // series used to draw its bar centred on the same x from the same
            // baseline, so the bars sat ON TOP of each other and the tallest one read
            // as a STACK with the others as its segments — a part-to-whole statement
            // nobody computed. (Adding a dashed outline per series made that
            // misreading worse, not better: the outlines look like segment
            // boundaries.) Each series now gets its own sub-slot within the time
            // position, the group centred on the true x, which is the ordinary
            // grouped-bar convention for comparing series at one time slot.
            //
            // A SINGLE series is byte-identical to before: one slot, centred on its
            // true x, no offset. So no existing single-series chart moves.
            const baseY = Yof(yMin);
            const nS = vs.length, slot = Math.max(2, Math.min(plotW / (n * 1.5), 26));
            const bw = nS > 1 ? Math.max(2, slot / nS) : slot;
            const si = vs.indexOf(s);
            for (const p of s.vis) {
              const cx = Xof(p.t);
              // Clamp the GROUP, then offset within it — never the other way round.
              // The first and last points sit exactly on the plot edges, so half a
              // slot always fell outside; clipping is bad for one bar (the HEIGHT,
              // which is the value, still reads correctly) and much worse for a group,
              // where the outermost series can be cut away entirely and a reader who
              // sees no bar concludes nothing was measured.
              //
              // The first fix clamped each series' OWN x0 independently, which
              // reproduced that failure by another route: at the first slot, series 0
              // and series 1 both clamped to exactly padL, drew on top of each other,
              // and the later one hid the earlier — an invisible measurement, and not
              // even hatched. Clamping the group's left edge keeps every sub-slot
              // distinct by construction. Found by screenshotting the bars and
              // counting pixels per group, not by reading the code.
              const g0 = nS > 1
                ? Math.max(padL, Math.min(cx - slot / 2, W - padR - slot))
                : cx - slot / 2;
              // A 1px inset so two adjacent bars have a real background gap between
              // them rather than a shared anti-aliased edge.
              const inset = nS > 1 ? 1 : 0;
              const x0 = g0 + si * bw;
              const y = Yof(vt(pv(s, p)));
              const bwv = Math.max(1, bw - inset);
              ctx.globalAlpha = 0.72; ctx.fillRect(x0, y, bwv, Math.max(0, baseY - y));
              ctx.globalAlpha = 1;    ctx.fillRect(x0, y - 1, bwv, 2);
              // The series' own marker above its bar, so identity survives greyscale
              // here too — the fill colour alone cannot carry it (worst mutual
              // separation between two series colours is 1.00:1).
              if (nS > 1) _figMarkerCanvas(ctx, st.marker, x0 + bwv / 2, y - 6, 3.2);
            }
          } else {
            // One subpath PER RUN: the pen lifts across a hole instead of drawing a
            // measurement nobody took. ooChart always has a REAL time axis, so a
            // cadence gap counts here; the visible window is what is split, so
            // zooming into a quiet stretch still shows it as quiet, not as a line.
            ctx.setLineDash(st.dash);
            ctx.beginPath();
            for (const run of _seriesRuns(s.vis, {timed: true})) {
              run.forEach((ix, i) => {
                const p = s.vis[ix], x = Xof(p.t), y = Yof(vt(pv(s, p)));
                i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
              });
            }
            ctx.stroke();
            ctx.setLineDash([]);
            // The honest dot on a roomy line, now carrying the series' own SHAPE — so
            // identity survives greyscale, a colour-blind reader, and a dash pattern
            // whose gap happens to land where you are looking.
            //
            // EVERY visible point still gets its mark, exactly as before. Spacing the
            // glyphs out would have been the tidier drawing and is wrong twice: it
            // thins what the chart states (invariant #16 — the full series renders
            // within the visible window, and test_ui_invariants catches the `%
            // every` that expresses it), and a reader who has learned that a dot
            // means "measured here" would read the unmarked points as unmeasured.
            if (pxPer > 9) {
              for (const p of s.vis) {
                _figMarkerCanvas(ctx, st.marker, Xof(p.t), Yof(vt(pv(s, p))), 3.2);
              }
            }
          }
        }
        // The brush band. Drawn AFTER the series so the selection reads as an overlay
        // on the data rather than as a layer the data sits on, and with an explicit
        // edge on each side because a translucent fill alone is ambiguous about where
        // the span actually stops.
        if (bFrom != null && bTo != null) {
          const xa = Math.min(Xof(bFrom), Xof(bTo)), xb = Math.max(Xof(bFrom), Xof(bTo));
          // --accent, NOT --fig-gap. The first draft used the gap token and that was a
          // semantic error: --fig-gap means ABSENCE ("no data was recorded here"), so
          // painting a SELECTION with it gives one colour two opposite meanings, and a
          // reader who has learned the grey means missing would read a selection as a
          // hole. Selection is an active user state, which this app expresses with the
          // accent -- the same accent the pressed toggle uses.
          ctx.fillStyle = cssVar("--accent");
          ctx.globalAlpha = 0.15;
          ctx.fillRect(xa, padT, Math.max(1, xb - xa), plotH);
          ctx.globalAlpha = 1;
          ctx.strokeStyle = cssVar("--accent");
          ctx.beginPath();
          ctx.moveTo(xa, padT); ctx.lineTo(xa, H - padB);
          ctx.moveTo(xb, padT); ctx.lineTo(xb, H - padB);
          ctx.stroke();
        }
        if (pinned) {
          const x = Xof(pinned.t), y = Yof(vt(opts.indexed && pinnedS ? pv(pinnedS, pinned) : pinned.v));
          ctx.strokeStyle = cssVar("--muted"); ctx.setLineDash([3, 3]);
          ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke(); ctx.setLineDash([]);
          ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.stroke();
        }
        // The legend glyph shows all three channels (colour + dash + marker), so the
        // key itself is readable in greyscale. It is a <button>, not a clickable
        // <span> with an inline onclick, so it keeps this component off the
        // 'unsafe-inline' script-src debt instead of adding to it, and the toggle
        // becomes keyboard-reachable with its pressed state announced.
        //
        // Careful: the loop below used to only ASSIGN elm._oo, and the inline
        // `onclick="this._oo&&this._oo()"` was what invoked it \u2014 so that property was
        // not a listener and dropping the inline attribute alone would have left the
        // toggle dead. It is now a real addEventListener; _oo stays because
        // ooChart re-renders the legend on every draw and the property is the
        // per-element closure the listener calls.
        legend.innerHTML = vs.map((s) => {
          const i = all.indexOf(all.find(a => a.label === s.label));
          const st = s.style || _figStyle(Math.max(i, 0));
          return `<button type="button" class="fig-leg" data-oo-leg="${i}"` +
            ` aria-pressed="${s.hidden ? "false" : "true"}"${s.hidden ? ' style="opacity:.4"' : ""}>` +
            _figGlyph(Object.assign({}, st, {color: s.color})) +
            `${esc(s.label)} <span class="muted" title="${esc(t9("n counts the datapoints plotted here, not articles."))}">n=${s.vis.length}${s.unit ? " \u00b7 " + esc(s.unit) : ""}</span></button>`;
        }).join("");
        legend.querySelectorAll("[data-oo-leg]").forEach(elm => {
          elm._oo = () => { all[+elm.dataset.ooLeg].hidden = !all[+elm.dataset.ooLeg].hidden; draw(); };
          elm.addEventListener("click", elm._oo);
        });
      }
      function nearest(ev) {
        const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left;
        const ms = t0 + (t1 - t0) * (mx - padL) / plotW;
        let best = null;
        for (const s of visible()) for (const p of s.vis) {
          const d = Math.abs(p.t - ms);
          if (!best || d < best.d) best = {d, p, s};
        }
        return best;
      }
      cv.addEventListener("wheel", (ev) => {
        ev.preventDefault();
        const r = cv.getBoundingClientRect();
        const anchor = t0 + (t1 - t0) * ((ev.clientX - r.left) - padL) / plotW;
        const f = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
        t0 = Math.max(tMin, anchor - (anchor - t0) * f);
        t1 = Math.min(tMax, anchor + (t1 - anchor) * f);
        if (t1 - t0 < 3600e3) { const c = (t0 + t1) / 2; t0 = c - 1800e3; t1 = c + 1800e3; }
        draw();
      }, {passive: false});
      let dragX = null, dragT = null;
      // A drag is a PAN by default and a BRUSH when the chart offers selection and the
      // reader asks for it -- either by pressing the toolbar toggle or by holding Shift.
      // Both exist deliberately: a modifier alone is undiscoverable (nothing on screen
      // says it is there), while a mode toggle alone makes a one-off selection cost two
      // round trips. Neither path changes what a CLICK does, so click-to-pin still works
      // in brush mode, and a brush shorter than the click threshold is treated as the
      // click it almost certainly was rather than as an empty selection.
      const brushing = (ev) => canBrush && (brushMode || ev.shiftKey);
      cv.addEventListener("pointerdown", (ev) => {
        cv.setPointerCapture(ev.pointerId);
        if (brushing(ev)) {
          bFrom = msAt(ev.clientX); bTo = bFrom;
          dragX = ev.clientX; dragT = null;   // dragT null is what marks this a brush
          draw(); return;
        }
        dragX = ev.clientX; dragT = [t0, t1];
      });
      cv.addEventListener("pointermove", (ev) => {
        if (dragX != null && dragT == null && bFrom != null) {
          bTo = msAt(ev.clientX);
          const lo = Math.min(bFrom, bTo), hi = Math.max(bFrom, bTo);
          let inside = 0, tot = 0;
          for (const sr of visible()) for (const pt of sr.vis) {
            tot++; if (pt.t >= lo && pt.t <= hi) inside++;
          }
          readout.textContent = _figTf("Selected {from} \u2192 {to} \u00b7 {n} of {total} points",
            {from: dayOf(_snap(lo, false)), to: dayOf(_snap(hi, true)),
             n: inside, total: tot});
          draw(); return;
        }
        if (dragX != null && dragT) {
          const dt = (dragX - ev.clientX) / plotW * (dragT[1] - dragT[0]);
          const span = dragT[1] - dragT[0];
          t0 = Math.max(tMin, Math.min(dragT[0] + dt, tMax - span));
          t1 = t0 + span; draw(); return;
        }
        const b = nearest(ev);
        if (b) {
          const ix = opts.indexed && b.s._base ? ` \u00b7 idx ${Math.round(pv(b.s, b.p))}` : "";
          readout.textContent = `${b.s.label}: ${fmtV(b.p.v)}${b.s.unit ? " " + b.s.unit : ""}${ix} \u00b7 ${fmtT(b.p.t)}`;
        }
      });
      cv.addEventListener("pointerup", (ev) => {
        const wasBrush = dragX != null && dragT == null && bFrom != null;
        const moved = dragX != null && Math.abs(ev.clientX - dragX) >= 4;
        if (wasBrush && moved) {
          dragX = null;
          opts.onSelectRange(dayOf(Math.min(bFrom, bTo)), dayOf(Math.max(bFrom, bTo)),
                             {clear: () => { bFrom = bTo = null; draw(); }});
          return;
        }
        if (wasBrush) { bFrom = bTo = null; }   // too short to be a span: it was a click
        if (dragX != null && !moved) {
          const b = nearest(ev);
          pinned = b ? b.p : null; pinnedS = b ? b.s : null;
          if (b) readout.innerHTML = `<b>${esc(b.s.label)}: ${fmtV(b.p.v)}${b.s.unit ? " " + esc(b.s.unit) : ""} \u00b7 ${fmtT(b.p.t)}</b> <span class="muted">${esc(t9("(pinned — click empty space or re-click to move)"))}</span>`;
          draw();
        }
        dragX = null;
      });
      cv.addEventListener("dblclick", () => { t0 = tMin; t1 = tMax; pinned = null; pinnedS = null; draw(); });
      draw();
      return {redraw: draw};
    }

    function sparkSvg(points) {
      if (!points.length) return '<div class="muted">No price points stored yet — use “Test” to fetch one.</div>';
      const w = 680, h = 180, pad = 34;
      const ys = points.map(p => p.price);
      const minY = Math.min(...ys), maxY = Math.max(...ys), spanY = (maxY - minY) || 1;
      const X = i => pad + (w - 2*pad) * (points.length < 2 ? 0.5 : i/(points.length-1));
      const Y = v => h - pad - (h - 2*pad) * ((v - minY)/spanY);
      const line = points.map((p,i) => `${X(i).toFixed(1)},${Y(p.price).toFixed(1)}`).join(" ");
      const dots = points.map((p,i) =>
        `<circle cx="${X(i).toFixed(1)}" cy="${Y(p.price).toFixed(1)}" r="2.5" fill="var(--accent)"></circle>`).join("");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" style="max-width:${w}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px">
        <polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${line}"></polyline>${dots}
        <text x="${pad}" y="16" fill="var(--muted)" font-size="11">${maxY}</text>
        <text x="${pad}" y="${h-8}" fill="var(--muted)" font-size="11">${minY}</text>
        <text x="${w-pad}" y="${h-8}" fill="var(--muted)" font-size="11" text-anchor="end">${esc(points[points.length-1].observed_on)}</text>
        <text x="${pad}" y="${h-8}" fill="var(--muted)" font-size="11" dx="40">${esc(points[0].observed_on)}</text>
      </svg>`;
    }

    async function chartSymbol(symbol, unit) {
      // P2-10: the single-symbol price detail opens in the ONE shared fullscreen
      // overlay (#chart-enlarge → ooChart) instead of the cramped bottom #mkt-chart
      // strip, and PRESERVES "Correlate with news" (appended below the chart via the
      // chartEnlarge extra/onReady hook; the correlation renders into that element).
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/prices`);
        const series = [{label: symbol, unit: unit || (d.prices[0] && d.prices[0].unit) || "",
          points: d.prices.map(p => ({t: p.observed_on, v: p.price}))}];
        chartEnlarge(`${symbol} — ${d.count} ${t9("point(s)")}`, series, "", {
          scales: true,
          extra: `<div style="margin-top:10px">`
            + `<button class="tiny secondary" id="ce-correlate" type="button"`
            + ` title="${esc(t9("Correlate price change vs news volume"))}">${esc(t9("Correlate with news"))}</button>`
            + `<div id="mkt-corr" class="hint" style="margin-top:8px"></div></div>`,
          onReady: (body) => {
            const b = body.querySelector("#ce-correlate");
            if (b) b.addEventListener("click", () => correlateSymbolInto(symbol, body.querySelector("#mkt-corr")));
          },
        });
      } catch (e) {
        const el = $("mkt-chart");
        if (el) el.innerHTML = `<div class="note err">Chart unavailable: ${esc(e.message)} ` +
          `<span class="muted">(commodity analysis endpoints require the [analysis] extra)</span></div>`;
      }
    }

    // Indices detail — the SAME interactive ooChart the commodity board uses
    // (invariant #16). Indices are stored as CommodityPrice rows, so the full,
    // un-thinned series comes from /api/commodities/{symbol}/prices (never the
    // truncated board spark). Mirrors chartSymbol; renders into #idx-chart.
    async function indexDetail(symbol, name, currency) {
      const el = $("idx-chart"); if (!el) return;
      el.innerHTML = `<div class="muted">Loading ${esc(name || symbol)}…</div>`;
      try {
        const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/prices`);
        el.innerHTML = `<h2 style="margin:0 0 8px;font-size:14px;color:var(--muted)">${esc(name || symbol)} — ${d.count} point(s)</h2>` +
          `<div id="idx-chart-oo"></div>`;
        ooChart($("idx-chart-oo"), [{label: name || symbol,
          unit: currency || (d.prices[0] && d.prices[0].currency) || "",
          points: d.prices.map(p => ({t: p.observed_on, v: p.price}))}], {height: 230});
        el.scrollIntoView({behavior: "smooth", block: "nearest"});
      } catch (e) {
        el.innerHTML = `<div class="note err">Chart unavailable: ${esc(e.message)}</div>`;
      }
    }

    // Correlate the symbol's daily price change against article volume for the
    // current search query (if any), rendering into a CALLER-supplied element.
    // Honest output: real coefficient/p-value/n. (P2-10 routes this into the
    // fullscreen overlay; the legacy bottom-strip caller is kept below.)
    async function correlateSymbolInto(symbol, el) {
      if (!el) return;
      const qInput = $("q");
      const q = qInput ? qInput.value.trim() : "";
      el.innerHTML = `<div class="muted">Correlating ${esc(symbol)} with news…</div>`;
      try {
        const d = await api(`/api/commodities/${encodeURIComponent(symbol)}/correlation` +
          (q ? "?query=" + encodeURIComponent(q) : ""));
        let body;
        if (d.insufficient_data) {
          body = `<span class="pill warn">insufficient data</span> only ${d.n} overlapping day(s) — need more price + article history.`;
        } else {
          const sig = d.significant ? '<span class="pill ok">significant</span>' : '<span class="pill">not significant</span>';
          body = `<div>method <strong>${esc(d.method)}</strong>, n=${d.n}, ` +
            `coefficient <strong>${d.coefficient.toFixed(3)}</strong>, p=${d.p_value.toExponential(2)} ${sig}</div>`;
        }
        el.innerHTML =
          `<div style="margin:0 0 6px;font-size:13px;color:var(--muted)">${esc(symbol)} vs news${q?` — “${esc(q)}”`:""}</div>` +
          body + `<div class="hint" style="margin-top:6px">${esc(d.caveat || "")}</div>`;
      } catch (e) {
        el.innerHTML = `<div class="note err">Correlation unavailable: ${esc(e.message)}</div>`;
      }
    }
    // Legacy bottom-strip caller (kept for any code path still using #mkt-chart).
    function correlateSymbol(symbol) { correlateSymbolInto(symbol, $("mkt-chart")); }

    // ===== Universal subtab component (keystone, maintainer-ruled 2026-06-13) ==
    // ONE navigation grammar everywhere: a <nav class="tabs"> of buttons each
    // carrying data-tab="KEY". Click OR arrow-keys/Home/End select; the component
    // owns the visible state (.active + role=tab/aria-selected + roving tabindex),
    // labels are plain DOM text (auto-translated ×12), and titled buttons get the
    // hover-bubble convention for free. onSelect(key) does the per-surface panel
    // switch. Returns { select, paint } for programmatic switching (e.g. opening a
    // modal on a given tab). Reused by Insights, Settings and the corpus window.
    function ooSubtabs(nav, onSelect, opts) {
      if (!nav) return null;
      opts = opts || {};
      // Query buttons LIVE on every operation, never capture once: surfaces like the
      // Markets category tabs REBUILD this nav's buttons on a re-render and call
      // ooSubtabs again, but the click/keydown listeners are wired once (_ooWired), so
      // a captured array goes stale and paints DETACHED buttons — leaving the
      // HTML-marked "All" visually active after a switch (field test 2026-06-19 #31).
      const buttons = () => Array.prototype.slice.call(nav.querySelectorAll("[data-tab]"));
      if (!buttons().length) return null;
      nav.setAttribute("role", "tablist");
      buttons().forEach(b => { b.setAttribute("role", "tab"); if (!b.getAttribute("type")) b.type = "button"; });
      function paint(key) {            // visuals + a11y only — never fires onSelect
        let hit = null;
        buttons().forEach(b => {
          const on = b.dataset.tab === key;
          b.classList.toggle("active", on);
          b.setAttribute("aria-selected", on ? "true" : "false");
          b.tabIndex = on ? 0 : -1;
          if (on) hit = b;
        });
        return hit;
      }
      function select(key, focus) {    // the canonical switch: paint + callback
        const b = paint(key);
        if (!b) return false;
        if (focus) b.focus();
        if (typeof onSelect === "function") onSelect(key);
        return true;
      }
      if (!nav._ooWired) {
        nav._ooWired = true;
        nav.addEventListener("click", e => {
          const b = e.target.closest("[data-tab]");
          if (b && nav.contains(b)) select(b.dataset.tab);
        });
        nav.addEventListener("keydown", e => {
          const btns = buttons();
          const i = btns.indexOf(document.activeElement);
          if (i < 0) return;
          let j = i;
          if (e.key === "ArrowRight" || e.key === "ArrowDown") j = (i + 1) % btns.length;
          else if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = (i - 1 + btns.length) % btns.length;
          else if (e.key === "Home") j = 0;
          else if (e.key === "End") j = btns.length - 1;
          else return;
          e.preventDefault();
          select(btns[j].dataset.tab, true);
        });
      }
      // Initial state: sync ARIA/roving-tabindex to the HTML-marked active button
      // WITHOUT firing onSelect (each surface already renders its default panel),
      // unless opts.initial explicitly asks to switch+fire.
      if (opts.initial !== undefined) select(opts.initial);
      else {
        const bs = buttons();
        paint((bs.filter(b => b.classList.contains("active"))[0] || bs[0]).dataset.tab);
      }
      return { select: select, paint: paint };
    }

    // ooTimeScope — ONE reusable time-range control (maintainer UX: "dates +
    // a visual range bar", NOT 5 buttons). Renders into `container`:
    //   (a) From / To <input type=date> fields,
    //   (b) a horizontal track with the selected span + two draggable handles,
    //   (c) quick presets (1M·6M·1Y·5Y·All) as one-click SHORTCUTS.
    // The three stay in sync; onChange({from,to}) fires (ISO YYYY-MM-DD) on any
    // change. Exposes { set(from,to), get() }. Pure DOM + CSS, no deps,
    // deterministic. Drag math mirrors the temporal-map slider helpers
    // (value↔pixel over [min,max], here in days since epoch). Wired to Markets
    // now; reusable later (Insights / agenda / corpus windows).
    const _TS_DAY = 86400000;
    function _tsParse(iso) {                       // ISO date -> integer days since epoch (UTC)
      if (!iso) return null;
      const t = Date.parse(iso + "T00:00:00Z");
      return isFinite(t) ? Math.round(t / _TS_DAY) : null;
    }
    function _tsIso(days) {                        // integer days since epoch -> ISO date
      return new Date(days * _TS_DAY).toISOString().slice(0, 10);
    }
    // Quick-preset spans in CALENDAR units, anchored to the data's max date.
    // "All" = the full [min,max] span. Labels are keyed for ×12 translation.
    const _TS_PRESETS = [
      ["1M", d => { const x = new Date(d * _TS_DAY); x.setUTCMonth(x.getUTCMonth() - 1); return Math.round(x.getTime() / _TS_DAY); }],
      ["6M", d => { const x = new Date(d * _TS_DAY); x.setUTCMonth(x.getUTCMonth() - 6); return Math.round(x.getTime() / _TS_DAY); }],
      ["1Y", d => { const x = new Date(d * _TS_DAY); x.setUTCFullYear(x.getUTCFullYear() - 1); return Math.round(x.getTime() / _TS_DAY); }],
      ["5Y", d => { const x = new Date(d * _TS_DAY); x.setUTCFullYear(x.getUTCFullYear() - 5); return Math.round(x.getTime() / _TS_DAY); }],
      ["All", () => null],   // sentinel: clamp to min
    ];
    function ooTimeScope(container, opts) {
      if (!container) return null;
      opts = opts || {};
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s => s);
      const min = _tsParse(opts.min), max = _tsParse(opts.max);
      // Degrade loudly if the span is unusable (no/identical bounds).
      if (min == null || max == null || max <= min) {
        container.innerHTML = `<span class="hint muted">${esc(t("not enough data for a time range"))}</span>`;
        return { set: () => {}, get: () => ({from: opts.from || null, to: opts.to || null}) };
      }
      let from = _tsParse(opts.from); let to = _tsParse(opts.to);
      if (from == null) from = min; if (to == null) to = max;
      const clamp = v => Math.max(min, Math.min(max, v));
      from = clamp(from); to = clamp(to);
      if (from > to) { const s = from; from = to; to = s; }

      container.classList.add("ts");
      container.innerHTML =
        `<div class="ts-dates">
           <label>${esc(t("From"))} <input type="date" class="ts-from"></label>
           <label>${esc(t("To"))} <input type="date" class="ts-to"></label>
         </div>
         <div class="ts-bar" tabindex="-1">
           <div class="ts-track"></div><div class="ts-sel"></div>
           <div class="ts-handle ts-h-from" role="slider" tabindex="0"
                aria-label="${esc(t("From"))}"></div>
           <div class="ts-handle ts-h-to" role="slider" tabindex="0"
                aria-label="${esc(t("To"))}"></div>
         </div>
         <div class="ts-presets">` +
        _TS_PRESETS.map(([k]) =>
          `<button type="button" data-preset="${esc(k)}">${esc(t(k))}</button>`).join("") +
        `</div>`;

      const inFrom = container.querySelector(".ts-from");
      const inTo   = container.querySelector(".ts-to");
      const bar    = container.querySelector(".ts-bar");
      const sel    = container.querySelector(".ts-sel");
      const hFrom  = container.querySelector(".ts-h-from");
      const hTo    = container.querySelector(".ts-h-to");
      // date inputs carry the absolute bounds so the native picker is bounded.
      const minIso = _tsIso(min), maxIso = _tsIso(max);
      [inFrom, inTo].forEach(el => { el.min = minIso; el.max = maxIso; });

      function frac(v) { return (v - min) / (max - min); }     // value -> 0..1
      function paint() {
        inFrom.value = _tsIso(from); inTo.value = _tsIso(to);
        const a = frac(from) * 100, b = frac(to) * 100;
        sel.style.left = a + "%"; sel.style.width = (b - a) + "%";
        hFrom.style.left = a + "%"; hTo.style.left = b + "%";
        [[hFrom, from], [hTo, to]].forEach(([h, v]) => {
          h.setAttribute("aria-valuemin", minIso);
          h.setAttribute("aria-valuemax", maxIso);
          h.setAttribute("aria-valuenow", _tsIso(v));
        });
      }
      function fire() {
        if (typeof opts.onChange === "function") opts.onChange({from: _tsIso(from), to: _tsIso(to)});
      }
      function setRange(a, b, notify) {
        a = clamp(a); b = clamp(b);
        if (a > b) { const s = a; a = b; b = s; }
        const changed = a !== from || b !== to;
        from = a; to = b; paint();
        if (notify && changed) fire();
      }
      // x pixel within the bar -> value in [min,max] (mirrors sliderToT).
      function pxToVal(clientX) {
        const r = bar.getBoundingClientRect();
        const f = r.width ? Math.max(0, Math.min(1, (clientX - r.left) / r.width)) : 0;
        return Math.round(min + f * (max - min));
      }

      // -- pointer drag (mouse + touch via Pointer Events) ------------------ //
      let dragging = null;   // "from" | "to" | null
      function onDown(which, e) {
        dragging = which; e.preventDefault();
        (which === "from" ? hFrom : hTo).focus();
        try { e.target.setPointerCapture(e.pointerId); } catch (_) {}
      }
      function onMove(e) {
        if (!dragging) return;
        const v = pxToVal(e.clientX);
        if (dragging === "from") setRange(v, to, true); else setRange(from, v, true);
      }
      function onUp() { dragging = null; }
      hFrom.addEventListener("pointerdown", e => onDown("from", e));
      hTo.addEventListener("pointerdown", e => onDown("to", e));
      bar.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      // Click on the track (not a handle) moves the NEARER handle there.
      bar.addEventListener("pointerdown", e => {
        if (e.target.classList.contains("ts-handle")) return;
        const v = pxToVal(e.clientX);
        if (Math.abs(v - from) <= Math.abs(v - to)) setRange(v, to, true);
        else setRange(from, v, true);
      });

      // -- keyboard on handles (a11y plus) ---------------------------------- //
      function onKey(which, e) {
        let step = 0;
        if (e.key === "ArrowLeft" || e.key === "ArrowDown") step = -1;
        else if (e.key === "ArrowRight" || e.key === "ArrowUp") step = 1;
        else if (e.key === "PageDown") step = -30;
        else if (e.key === "PageUp") step = 30;
        else if (e.key === "Home") { which === "from" ? setRange(min, to, true) : setRange(from, from, true); e.preventDefault(); return; }
        else if (e.key === "End") { which === "from" ? setRange(to, to, true) : setRange(from, max, true); e.preventDefault(); return; }
        else return;
        e.preventDefault();
        if (which === "from") setRange(from + step, to, true); else setRange(from, to + step, true);
      }
      hFrom.addEventListener("keydown", e => onKey("from", e));
      hTo.addEventListener("keydown", e => onKey("to", e));

      // -- date inputs ------------------------------------------------------ //
      inFrom.addEventListener("change", () => { const v = _tsParse(inFrom.value); if (v != null) setRange(v, to, true); else paint(); });
      inTo.addEventListener("change",   () => { const v = _tsParse(inTo.value);   if (v != null) setRange(from, v, true); else paint(); });

      // -- presets (one-click shortcuts; from = max - span, to = max) ------- //
      container.querySelector(".ts-presets").addEventListener("click", e => {
        const b = e.target.closest("[data-preset]");
        if (!b) return;
        const def = _TS_PRESETS.find(([k]) => k === b.dataset.preset);
        if (!def) return;
        const startFn = def[1];
        const start = startFn(max);                 // null sentinel => "All"
        setRange(start == null ? min : start, max, true);
      });

      paint();
      return {
        set: (a, b) => setRange(_tsParse(a) ?? from, _tsParse(b) ?? to, false),
        get: () => ({from: _tsIso(from), to: _tsIso(to)}),
      };
    }

    // ---- ooTimeScope reuse for keyword-trend surfaces (Insights Explore +
    // the corpus window). The /api/insights/trend endpoint returns the FULL
    // bucketed series (no date params), so the window is applied CLIENT-SIDE by
    // FILTERING the already-fetched points — never refetched, never thinned
    // (invariant #16: the full-resolution series within the window is kept and
    // handed to the existing ooChart renderer UNCHANGED). The bucket key may be
    // YYYY-MM-DD (day), YYYY-MM (month) or YYYY-Www (ISO week); _trendBucketMs
    // mirrors ooChart's own toMs so the filter agrees with the renderer. ------ //
