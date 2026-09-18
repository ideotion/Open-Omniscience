/* app-analysis.js — the analysis window

   The analysis window end to end: its tab strip and facets, the price, trend,
   related, mindmap and articles subtabs, plus search, synthesis and the bulk-LLM
   queue that run from it.

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
    let _searchTimeScope = null;
    let _searchTsBounds = {min: null, max: null};
    function buildSearchTimeScope() {
      const box = $("search-timescope");
      if (!box || _searchTimeScope) return;
      const today = new Date();
      const max = today.toISOString().slice(0, 10);
      const lo = new Date(today); lo.setUTCFullYear(today.getUTCFullYear() - 5);
      const min = lo.toISOString().slice(0, 10);
      _searchTsBounds = {min, max};
      // Default window = the full span; re-run the search live on change (matches
      // how the omnibar/other live filters behave — the user sees results update).
      _searchTimeScope = ooTimeScope(box, {
        min, max, from: min, to: max,
        onChange: () => { if (_loaded.has("search")) doSearch(); },
      });
    }

    // The Search-tab date filter is the SAME ooTimeScope control used app-wide
    // (Markets/Insights/corpus window) — periods are first-class. The control's
    // from/to feed the UNCHANGED backend params start_date / end_date (YYYY-MM-DD,
    // accepted by /api/articles + /api/articles/export). A bound is sent ONLY when
    // the user has narrowed it off the absolute min/max — so a plain search never
    // silently excludes articles outside the default window.
    function searchTimeScopeParams(p) {
      if (!_searchTimeScope) return;
      const sel = _searchTimeScope.get();   // {from,to} ISO, or {null,null} on unusable span
      if (sel && sel.from && sel.from > _searchTsBounds.min) p.set("start_date", sel.from);
      if (sel && sel.to && sel.to < _searchTsBounds.max) p.set("end_date", sel.to);
    }
    function searchParams() {
      const p = new URLSearchParams();
      const q = $("q").value.trim(); if (q) p.set("query", q);
      const src = $("f-source").value.trim(); if (src) p.set("source", src);
      const lang = $("f-lang").value.trim(); if (lang) p.set("language", lang);
      searchTimeScopeParams(p);
      return p;
    }
    // The SAME params, built from the analysis window's own Advanced inputs — so the
    // window's exports describe exactly the article set it is analysing (the Search-tab
    // capabilities are absorbed here, toward the one-search-entry goal).
    // Populate the Advanced-search language <select> once: "Any language" + the 12 UI
    // languages as flag + native name (maintainer 2026-06-20). Built in JS so the autonym
    // labels stay native (invariant #15) and out of the static-HTML dropdown i18n gate.
    function _anFillLangSelect() {
      const sel = $("an-adv-lang");
      if (!sel || sel.tagName !== "SELECT" || sel.options.length) return;   // once
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const opts = ['<option value="">' + esc(t("Any language")) + "</option>"];
      for (const [code, flag, name] of LANGS_12)
        opts.push('<option value="' + code + '">' + flag + " " + esc(name) + "</option>");
      sel.innerHTML = opts.join("");
    }
    function anQuery() { return ($("an-adv-query").value || "").trim(); }
    // The EXACT article set behind a clicked card (maintainer-ruled 2026-06-16). When
    // set, the analysis window's corpus IS precisely these articles — every subtab
    // passes article_ids, and the backend's _resolve_corpus prefers them over a
    // search. null = the normal omnibar/Advanced search path.
    let _anIds = null;
    let _anCommodity = null;   // {symbol,name,unit} when seeded by a commodity click (Price subtab)
    let _anLastParams = null;  // last analysis params — for the lazily-rendered Trend subtab
    let _anSubtabs = null;     // ooSubtabs handle for the analysis window (to fall back off Price)
    let _anBootTab = null;     // ?tab= deep-link target, applied once _anSubtabs exists
    let _anFacets = {who: [], where: [], when: []};  // When/Where/Who clickable facet drill (P5.1b)
    function anParams() {
      const p = new URLSearchParams();
      if (_anIds && _anIds.length) { p.set("article_ids", _anIds.join(",")); return p; }
      const q = anQuery(); if (q) p.set("query", q);
      const src = $("an-adv-source").value.trim(); if (src) p.set("source", src);
      const lang = $("an-adv-lang").value.trim(); if (lang) p.set("language", lang);
      if ($("an-adv-from").value) p.set("start_date", $("an-adv-from").value);
      if ($("an-adv-to").value) p.set("end_date", $("an-adv-to").value);
      // Metadata sort (brief §2.D) — honest ordering, never a score. Only the
      // Articles list (/api/articles) reads these; insights endpoints ignore them.
      const sb = $("an-adv-sort") && $("an-adv-sort").value;
      if (sb) { p.set("sort_by", sb); p.set("sort_dir", ($("an-adv-dir") && $("an-adv-dir").value) || "desc"); }
      return p;
    }
    // === THEME-3 (2026-06-19): analysis-window-per-query ====================== //
    // Each search / Lead / keyword spawns a NAMED, closeable, persisted TAB over the
    // ONE #an render area. A SEED captures what to show; activating a tab applies its
    // seed + re-renders. Replaces the singleton #an AND the retired #corpus-win modal
    // (ruling: "retire both — one analysis surface"). Per-card landing = generic: a
    // spawned tab lands on the OVERVIEW screen showing the card's EXACT corpus (Q1).
    let _anTabs = [];          // [{id,key,label,kind,query,ids,commodity,src,lang,from,to}]
    let _anActiveId = null;
    let _anTabSeq = 1;
    let _anHydrated = false;    // restored tabs load lazily the first time Analysis is opened
    const _AN_TABS_KEY = "oo.an.tabs.v1";
    const _AN_TAB_CAP = 10;    // soft cap (a multi-document workspace, not unbounded)

    function _anSaveTabs() {
      try {
        // Persist only the lightweight SEEDS (never the rendered data).
        const slim = _anTabs.map(tb => ({
          id: tb.id, key: tb.key, label: tb.label, kind: tb.kind, query: tb.query || "",
          ids: tb.kind === "ids" ? (tb.ids || []).slice(0, 5000) : null,
          commodity: tb.commodity || null, src: tb.src || "", lang: tb.lang || "",
          from: tb.from || "", to: tb.to || "",
          // Ruling 16: the Lead's provenance is part of the seed, so a reload does not
          // silently drop the header and leave the analysis looking self-originated.
          prov: tb.prov || null,
          // Q504: the cross-language lens is part of the seed too. Without it a reader
          // who narrowed a tab to the words they typed got the widened search back on
          // the next reload, with nothing to say the view had changed under them.
          lens: tb.lens || null,
        }));
        localStorage.setItem(_AN_TABS_KEY, JSON.stringify({tabs: slim, active: _anActiveId}));
      } catch (_e) { /* private mode — tabs just won't persist */ }
    }
    function _anRenderStrip() {
      const strip = $("an-tabstrip"); if (!strip) return;
      if (!_anTabs.length) { strip.innerHTML = ""; strip.style.display = "none"; return; }
      strip.style.display = "";
      strip.innerHTML = _anTabs.map(tb => {
        const on = tb.id === _anActiveId;
        const lbl = (tb.label || tb.query || "set").slice(0, 28);
        // a11y-analysis-nested-interactive (measured 2026-09-09, axe-core serious,
        // n=1): the wrapper <span> carried role="tab" AND held two <button>s, so an
        // interactive widget contained two more — the tab's accessible name was
        // assembled from both buttons' text and neither control was coherently
        // reachable.
        // The ARIA tabs pattern cannot express a CLOSABLE tab: `tablist` requires
        // its children to be `tab`, `tab` is a widget role, and the close control
        // has to live inside the tab visually. Moving role="tab" onto the label
        // button and marking the wrapper role="presentation" was tried FIRST and
        // MEASURED: it removed nested-interactive and immediately raised
        // aria-required-children (1) instead, because axe does not promote a
        // presentational wrapper's descendants into the tablist's owned set. So the
        // strip is described as what it actually is — a LIST of open analyses, each
        // with an open control and a close control — which is valid, carries the
        // same structure to a screen reader, and leaves no widget nested in a
        // widget. `aria-current` marks the active entry in place of aria-selected.
        // (This is NOT one of invariant #18's ooSubtabs surfaces: the window's own
        // subtabs are #an-subtabs and keep the tablist grammar unchanged.)
        return `<span class="an-tab${on ? " active" : ""}" role="listitem">`
          + `<button class="an-tab-label"${on ? ' aria-current="true"' : ""} onclick="_anActivate(${esc(JSON.stringify(tb.id))})" title="${esc(tb.label || tb.query || "")}">${esc(lbl)}</button>`
          + `<button class="an-tab-x" onclick="_anCloseTab(${esc(JSON.stringify(tb.id))})" title="Close this analysis tab" aria-label="Close">✕</button></span>`;
      }).join("");
    }
    function _anApplySeed(tb) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      _anIds = (tb.kind === "ids" && Array.isArray(tb.ids)) ? tb.ids.slice(0, 5000) : null;
      _anCommodity = tb.commodity || null;
      // The lens belongs to the TAB: switching between two analyses must not carry one
      // reader's narrowing onto the other's corpus.
      _anApplyLensSeed(tb.lens);
      _anWriteLensToUrl();
      _anFillLangSelect();   // ensure the language <select> is built before seeding it
      $("an-adv-query").value = tb.query || "";
      $("an-adv-source").value = tb.src || "";
      $("an-adv-lang").value = tb.lang || "";
      $("an-adv-from").value = tb.from || "";
      $("an-adv-to").value = tb.to || "";
      $("an-query").textContent = tb.label ? `“${tb.label}”` : (tb.query ? `“${tb.query}”` : t("(the selected article set)"));
      $("an-adv-note").textContent = (tb.kind === "ids") ? t("Showing the exact article set behind this Lead.") : "";
      _anRenderProvenance(tb.prov || null);
      loadAnalysis(anParams());
      if (_anSubtabs) _anSubtabs.select("overview"); else anSelectTab("overview");   // generic landing (Q1)
    }
    // The PERSISTENT provenance header (ruling 15). Sits above the subtabs, so it stays
    // on screen whichever subtab the reader is on -- an analysis opened from a Lead
    // should never lose track of which Lead, and on what basis, it came from.
    //
    // Every field is the CARD'S OWN, carried verbatim (ruling 16). Nothing here is
    // recomputed, so the header can never disagree with the card that produced it.
    // A missing field is simply omitted: an analysis opened from a search has no card
    // provenance at all and the whole header stays hidden, because attributing a search
    // to a producer that never ran would be a fabricated attribution.
    function _anRenderProvenance(prov) {
      const host = $("an-prov"); if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!prov || !(prov.card || prov.producer || prov.method || prov.caveat)) {
        host.hidden = true; host.innerHTML = ""; host.style.removeProperty("--fam");
        return;
      }
      // The family colour comes from the same famHue as Home, keyed on the same stable
      // bucket name, so a Lead and its analysis are recognisably the same family.
      if (prov.bucket) host.style.setProperty("--fam", famHue(prov.bucket));
      else host.style.removeProperty("--fam");
      const famLabel = prov.family || prov.bucket || "";
      const bits = [];
      if (famLabel) {
        bits.push(`<span class="an-prov-fam"><span class="fam-dot"`
          + `${prov.bucket ? ` style="background:${famHue(prov.bucket)}"` : ""}></span>`
          + `${esc(t(famLabel))}</span>`);
      }
      if (prov.producer) {
        // The producer identity, shown as the card TYPE the reader already saw on the
        // card's own chip -- same vocabulary on both surfaces.
        bits.push(`<span class="chip">${esc(String(prov.producer).replace(/_/g, " "))}</span>`);
      }
      // The trigger's plain sentence is ONE constant per card type (keyable), and each
      // math row is a constant label + a language-neutral value -- so both translate.
      const mathRows = ((prov.trigger && prov.trigger.math) || []).map(r =>
        `<tr><td>${esc(t(r.label))}</td><td class="why-val">${esc(r.value)}</td></tr>`).join("");
      const why = (prov.trigger && prov.trigger.plain)
        ? `<p class="why-plain">${esc(t(prov.trigger.plain))}</p>` : "";
      const math = mathRows
        ? `<details class="card-info"><summary>${esc(t("The exact math"))}</summary>`
          + `<table class="why-math">${mathRows}</table></details>` : "";
      // The CAVEAT is visible by default here, exactly as on the card's back face --
      // never behind the details toggle (invariant #23).
      const caveat = prov.caveat ? `<p class="card-caveat">${esc(t(prov.caveat))}</p>` : "";
      const method = prov.method
        ? `<div class="mc"><b>${esc(t("Method"))}:</b> ${esc(t(prov.method))}</div>` : "";
      host.innerHTML = `<div class="an-prov-top">`
        + `<span class="an-prov-from">${esc(t("From this Lead"))}:</span> `
        + `<b class="an-prov-card">${esc(prov.card || "")}</b> ${bits.join(" ")}</div>`
        + caveat + method
        + ((why || math) ? `<div class="why-mathlabel">${esc(t("Why am I seeing this?"))}</div>` : "")
        + why + math;
      host.hidden = false;
    }
    function _anActivate(id) {
      const tb = _anTabs.find(x => x.id === id); if (!tb) return;
      _anActiveId = id; _anHydrated = true;
      showTab("analyze");
      _anRenderStrip();
      _anApplySeed(tb);
      _anSaveTabs();
    }
    function _anCloseTab(id) {
      const i = _anTabs.findIndex(x => x.id === id); if (i < 0) return;
      _anTabs.splice(i, 1);
      if (_anActiveId === id) {
        const next = _anTabs[i] || _anTabs[i - 1] || null;
        _anActiveId = next ? next.id : null;
        _anRenderStrip();
        if (next) _anApplySeed(next); else _anShowEmpty();
      } else { _anRenderStrip(); }
      _anSaveTabs();
    }
    function _anShowEmpty() {
      // No tabs: the surface is a launcher (the empty singleton #an is retired).
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      _anIds = null; _anCommodity = null; $("an-query").textContent = "";
      _anRenderProvenance(null);
      const ov = $("an-overview");
      if (ov) ov.innerHTML = `<div class="muted">${esc(t("Search above, or open a Lead or keyword, to start an analysis. Each opens its own tab here."))}</div>`;
      if (_anSubtabs) _anSubtabs.select("overview"); else anSelectTab("overview");
    }
    // Spawn (or focus) a tab for a seed; dedupe by key so the SAME query/set reuses
    // its tab while DIFFERENT searches coexist as parallel tabs (the workspace).
    function _anSpawn(seed) {
      const key = seed.kind === "ids"
        ? ("ids:" + (seed.label || (seed.ids || []).slice(0, 4).join(",")))
        : ("q:" + (seed.query || "").toLowerCase() + "|" + (seed.src || "") + "|" + (seed.lang || ""));
      let tb = _anTabs.find(x => x.key === key);
      if (!tb) {
        tb = Object.assign({id: "t" + (_anTabSeq++) + Date.now().toString(36), key}, seed);
        _anTabs.push(tb);
        if (_anTabs.length > _AN_TAB_CAP) {
          const drop = _anTabs.find(x => x.id !== tb.id);   // evict the oldest non-new tab
          if (drop) _anTabs = _anTabs.filter(x => x.id !== drop.id);
        }
      } else { Object.assign(tb, seed, {id: tb.id, key}); }
      _anActivate(tb.id);
    }
    // Open the analysis window over an EXACT article set (echo / convergence / a card's
    // precise selection). The corpus is exactly these ids, not a re-run search.
    function openAnalysisForIds(ids, label, prov, lens) {
      _anSpawn({kind: "ids", ids: Array.isArray(ids) ? ids.slice(0, 5000) : [], label: label || "",
                query: "", prov: prov || null, lens: lens || null});
    }
    // Open the analysis window seeded with a query (omnibar Enter, keyword/card click).
    // A commodity click carries {commodity:{symbol,name,unit}} for the Price subtab.
    function openAnalysisFor(query, opts) {
      const q = (query || "").trim();
      _anSpawn({kind: "query", query: q, label: q, commodity: (opts && opts.commodity) || null,
                prov: (opts && opts.prov) || null, lens: (opts && opts.lens) || null});
    }
    // Retired #corpus-win modal -> a keyword now spawns its own analysis tab (one
    // surface). All openCorpus call sites get the spawn behaviour for free.
    function openCorpus(term) { openAnalysisFor(term); }
    function _anRestoreTabs() {
      try {
        const raw = JSON.parse(localStorage.getItem(_AN_TABS_KEY) || "null");
        if (raw && Array.isArray(raw.tabs) && raw.tabs.length) {
          _anTabs = raw.tabs;
          _anActiveId = raw.active && _anTabs.some(t => t.id === raw.active) ? raw.active : _anTabs[0].id;
          _anRenderStrip();   // show the strip; the active tab loads lazily when Analysis opens
        }
      } catch (_e) { /* corrupt state — start clean */ }
    }
    function openAnalysis() {
      // The search "Analyze" path -> spawn a tab seeded from the current search.
      const qtxt = $("q").value.trim();
      const _ts = _searchTimeScope && _searchTimeScope.get();
      _anSpawn({
        kind: "query", query: qtxt, label: qtxt || "(filtered)",
        src: ($("f-source").value || "").trim(), lang: ($("f-lang").value || "").trim(),
        from: (_ts && _ts.from && _ts.from > _searchTsBounds.min) ? _ts.from : "",
        to: (_ts && _ts.to && _ts.to < _searchTsBounds.max) ? _ts.to : "",
      });
    }
    // Advanced tab: refine the ACTIVE tab in-place (updates its seed, never spawns a
    // new tab). loadAnalysis re-runs EVERY subtab from the params.
    // The active filters/sort, summarised — so the corpus SCOPE is always visible in
    // the analysis window (§2.D; the filters are analysis-scoped, so the honest place
    // for the indicator is here, not a misleading app-wide chip).
    function _anFilterSummary() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const parts = [];
      const src = ($("an-adv-source").value || "").trim(); if (src) parts.push(t("source") + ": " + src);
      const lang = ($("an-adv-lang").value || "").trim(); if (lang) parts.push(t("language") + ": " + lang);
      const from = $("an-adv-from").value, to = $("an-adv-to").value;
      if (from || to) parts.push((from || "…") + " → " + (to || "…"));
      const sb = $("an-adv-sort") && $("an-adv-sort").value;
      if (sb) parts.push(t("sorted") + ": " + sb + " " + (($("an-adv-dir") && $("an-adv-dir").value) === "asc" ? "↑" : "↓"));
      return parts;
    }
    function anRunAdvanced() {
      _anIds = null;   // refining via Advanced search replaces any fixed article set
      _anCommodity = null;   // a refined search is no longer the commodity overlay
      const tt = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const q = $("an-adv-query").value.trim();
      const src = $("an-adv-source").value.trim(), lang = $("an-adv-lang").value.trim();
      const from = $("an-adv-from").value, to = $("an-adv-to").value;
      const tb = _anTabs.find(x => x.id === _anActiveId);
      if (tb) {
        Object.assign(tb, {kind: "query", query: q, label: q || "(filtered)", ids: null,
          commodity: null, src, lang, from, to,
          key: "q:" + q.toLowerCase() + "|" + src + "|" + lang});
        _anRenderStrip(); _anSaveTabs();
      }
      $("an-query").textContent = q ? `“${q}”` : "(all articles matching your filters)";
      const fs = _anFilterSummary();
      $("an-adv-note").innerHTML = fs.length
        ? `<span class="pill">${esc(tt("Filtered"))}</span> ${fs.map(esc).join(" · ")}`
        : tt("Analysis updated — see the other tabs.");
      loadAnalysis(anParams());
    }
    function anSelectTab(key) {
      document.querySelectorAll("#tab-analyze .an-panel").forEach(el =>
        el.style.display = (el.id === "an-" + key) ? "" : "none");
      // A LAZY TAB SELECTED WHILE AN ANALYSIS IS LOADING WAITS FOR ITS PARAMS. Before
      // this, selecting Trend inside that window called `renderAnTrend(null)`, which
      // falls back to the typed term with NO lens -- so the tab fetched, charted and
      // cached the LITERAL word while the list beside it counted the concept, which is
      // the exact split Q501 exists to close. Measured in Chromium as `hi` issuing the
      // trend request twice, once bare and once with the locale.
      // Nothing is lost by waiting: `loadAnalysis` renders whichever lazy panel is
      // visible the moment it has the lensed params, and it nulls this on entry so a
      // second run cannot serve the PREVIOUS corpus' chart in the meantime.
      if (!_anLastParams) return;
      if (key === "overview") renderAnOverview(_anLastParams);  // headline tile per lens
      if (key === "trend") renderAnTrend(_anLastParams);   // lazy: only fetch when the Trend tab is shown
      if (key === "related") renderAnRelated(_anLastParams);   // lazy: coordination/related computed on show
      if (key === "competitive") renderAnCompetitive(_anLastParams);   // lazy: source-competitive on show
    }
    // The OVERVIEW screen (THEME-3): an honest headline tile per lens (counts only, no
    // synthesis), each deep-linking to its subtab. Bounded summary fetches; degrades
    // gracefully (shows whatever resolves). The card's EXACT corpus is the scope (Q1).
    let _anOverviewKey = null;
    async function renderAnOverview(p) {
      const host = $("an-overview"); if (!host || !p) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const key = p.toString();
      if (_anOverviewKey === key && host.dataset.done === "1") return;  // already shown for this set
      _anOverviewKey = key; host.dataset.done = "";
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      // Honest slow-load notice (field test 2026-06-24, remark 8: a keyword's analysis
      // hung on a bare "Loading…" at 60K). After a few seconds we say it's a large-corpus
      // aggregation and how to speed it up (narrow the window) — never a fake spinner and
      // never a hard abort that would discard the in-flight result.
      const slow = setTimeout(() => {
        if (host.dataset.done !== "1") {
          host.innerHTML = `<div class="muted">${esc(t("Loading…"))} `
            + `<span class="bp-detail">${esc(t("still computing over your full corpus — narrow the time window to speed this up"))}</span></div>`;
        }
      }, 6000);
      const qs = p.toString();
      const grab = (path) => api(path + "?" + qs).then(d => d).catch(() => null);
      const [kw, www, src, sent] = await Promise.all([
        grab("/api/insights/corpus-keywords"), grab("/api/insights/corpus-www"),
        grab("/api/insights/corpus-sources"), grab("/api/insights/corpus-sentiment"),
      ]);
      clearTimeout(slow);
      const topKw = kw && kw.terms && kw.terms.length ? kw.terms[0] : null;
      const topPlace = www && www.where && www.where.length ? www.where[0] : null;
      const topWho = www && www.who && www.who.length ? www.who[0] : null;
      const topSrc = src && src.sources && src.sources.length ? src.sources[0] : null;
      const tone = sent && (sent.summary || sent.mean != null) ? sent : null;
      const tile = (lens, headline, sub) =>
        `<button class="an-ov-tile" onclick="_anSubtabs && _anSubtabs.select(${esc(JSON.stringify(lens))})">`
        + `<div class="an-ov-h">${esc(headline)}</div>`
        + (sub ? `<div class="an-ov-s muted">${esc(sub)}</div>` : "")
        + `<div class="an-ov-go muted">${esc(t("Open"))} →</div></button>`;
      const tiles = [];
      tiles.push(tile("keywords", t("Keywords"), topKw ? `${topKw.term} · ${kw.terms.length}+ ${t("Keywords").toLowerCase()}` : t("No keywords yet")));
      tiles.push(tile("www", t("When/Where/Who"), [topPlace ? topPlace.name : null, topWho ? (topWho.name || topWho.term) : null].filter(Boolean).join(" · ") || t("Nothing extracted yet")));
      tiles.push(tile("sources", t("Sources"), topSrc ? `${topSrc.name || topSrc.domain}` : t("No sources yet")));
      tiles.push(tile("sentiment", t("Sentiment"), tone ? (tone.summary || "") : t("English-only (VADER) — see the tab")));
      tiles.push(tile("trend", t("Trend"), t("How coverage moved over time")));
      tiles.push(tile("mindmap", t("Mindmap"), t("Keyword associations")));
      tiles.push(tile("links", t("Links"), t("Shared outbound origins")));
      tiles.push(tile("related", t("Related"), t("Near-duplicate clusters")));
      tiles.push(tile("articles", t("Articles"), t("The matched articles")));
      host.innerHTML = `<div class="hint" style="margin-bottom:8px">${esc(t("A headline from each lens — counts only, never a verdict. Open any to dig in."))}</div>`
        + `<div class="an-ov-grid">${tiles.join("")}</div>`;
      host.dataset.done = "1";
    }

    // --- Commodity price × coverage overlay (Markets item, Group G) --------- //
    // Shown ONLY when the analysis window was seeded by a commodity click (the
    // card title ⊞ / Analyse ↗ pass {commodity:{symbol,name,unit}}). The Price
    // subtab overlays the commodity PRICE curve with the corpus COVERAGE (article
    // volume) timeline on a SHARED time axis — "what and when to deduce why and
    // how". The non-causation principle still governs the design; the repeated
    // on-graph "never causation" caveat was removed (maintainer 2026-06-17).
    // Reuses existing endpoints (no new backend).
    function _toggleAnPrice() {
      const on = !!(_anCommodity && _anCommodity.symbol);
      const btn = $("an-price-tab");
      if (btn) btn.style.display = on ? "" : "none";
      if (on) { renderAnPrice(); return; }
      // Hidden now: if the Price tab was the active one, fall back to Keywords.
      const panel = $("an-price");
      if (panel) {
        if (panel.style.display !== "none" && _anSubtabs) _anSubtabs.select("keywords");
        panel.innerHTML = "";
      }
    }
    async function renderAnPrice() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("an-price"); if (!el || !_anCommodity) return;
      const c = _anCommodity;
      el.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      const term = anQuery() || c.name || c.symbol;
      try {
        // Price (the commodity's own series) + corpus coverage (this term's article
        // volume over time). Either may be absent — degrade loudly, never fake.
        const [pd, td] = await Promise.all([
          api(`/api/commodities/${encodeURIComponent(c.symbol)}/prices`).catch(() => null),
          api(`/api/insights/trend?bucket=week&term=${encodeURIComponent(term)}`).catch(() => null),
        ]);
        const prices = (pd && pd.prices) || [];
        const vol = (td && td.resolved) ? (td.points || []) : [];
        const unit = c.unit || (prices[0] ? `${prices[0].currency}/${prices[0].unit}` : "");
        const head = `<div class="hint"><b>${esc(t("Price × coverage"))}</b> — ${esc(c.name || c.symbol)}</div>`;
        const note = vol.length
          ? `<div class="hint muted" style="font-size:11px;margin-top:4px">${esc(t("Articles"))}: ${td.total} · ${vol.length}×</div>`
          : `<div class="muted" style="font-size:12px;margin:6px 0">${esc(t("No corpus coverage to overlay yet."))}</div>`;
        el.innerHTML = head + commodityOverlaySvg(prices, vol, unit) + note;
      } catch (e) { el.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    // A self-contained, deterministic dual-axis SVG (does NOT touch ooChart). The
    // PRICE reads its OWN left axis (line + real sample dots so the true n is
    // honest), the COVERAGE its OWN right axis (bars, 0-based) — each on its own
    // LABELLED scale, so magnitudes are never conflated (no fabricated shared
    // baseline). Shared time X so spikes line up. Empty/sparse degrade honestly.
    function commodityOverlaySvg(prices, vol, priceUnit) {
      const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const P = (prices || []).map(p => ({t: Date.parse(p.observed_on), v: +p.price}))
        .filter(p => isFinite(p.t) && isFinite(p.v)).sort((a, b) => a.t - b.t);
      const V = (vol || []).map(p => ({t: Date.parse(p.date), v: +p.count}))
        .filter(p => isFinite(p.t) && isFinite(p.v)).sort((a, b) => a.t - b.t);
      if (!P.length && !V.length) return `<div class="muted">${esc(t9("no data points yet"))}</div>`;
      const W = 660, H = 230, padL = 54, padR = 50, padT = 16, padB = 28;
      const allT = P.concat(V).map(p => p.t);
      const tMin = Math.min(...allT), tMax = Math.max(...allT), tSpan = (tMax - tMin) || 1;
      const X = ms => padL + (W - padL - padR) * (ms - tMin) / tSpan;
      const pv = P.map(p => p.v);
      const pMin = P.length ? Math.min(...pv) : 0, pMax = P.length ? Math.max(...pv) : 1;
      const pSpan = (pMax - pMin) || 1;
      const vMax = V.length ? Math.max(...V.map(p => p.v), 1) : 1;
      const Yp = v => padT + (H - padT - padB) * (1 - (v - pMin) / pSpan);
      const Yv = v => padT + (H - padT - padB) * (1 - v / vMax);
      const baseY = H - padB;
      const fmt = (typeof fmtNum === "function") ? fmtNum : (x => String(x));
      // Coverage bars (RIGHT axis) drawn first so the price line sits on top.
      const slot = (W - padL - padR) / Math.max(V.length, 1);
      const bw = Math.max(2, Math.min(slot * 0.6, 16));
      const bars = V.map(p => {
        const cx = X(p.t), by = Yv(p.v), x0 = Math.max(padL, cx - bw / 2);
        return `<rect x="${x0.toFixed(1)}" y="${by.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0, baseY - by).toFixed(1)}" fill="var(--muted)" fill-opacity="0.30"></rect>`;
      }).join("");
      // Price series (LEFT axis). RC08.6 / register L5 (2026-09-15) brings this
      // renderer under the SAME sparse rule the rest of the app already uses:
      // `_SPARSE_BAR_MAX` (app-markets.js, shared) -- under 10 real points a BAR
      // graph, at 10 or more the full-resolution line. It used to draw a polyline
      // from TWO points, which is the curve-faked-through-a-handful-of-points that
      // invariant #16 forbids. The invariant is unchanged; only this renderer was
      // still outside it.
      //
      // Price is a LEVEL series, so the bars anchor to the window MIN that the left
      // axis already LABELS -- never a fabricated zero, which for a price would
      // exaggerate every difference. A 2px cap marks each bar's true value so a
      // point sitting flush on the min, an all-equal window, or a single point
      // stays VISIBLE rather than drawing as a zero-height bar.
      //
      // The coverage bars beside them are on the RIGHT axis, drawn first, muted and
      // wider; these are accent-coloured and narrower, so a reader cannot take the
      // pair for one stacked total (the misreading the toolkit's own grouped-bar
      // note records).
      const priceBars = P.length < _SPARSE_BAR_MAX;
      const pslot = (W - padL - padR) / Math.max(P.length, 1);
      const pbw = Math.max(2, Math.min(pslot * 0.35, 9));
      const line = (!priceBars && P.length >= 2)
        ? `<polyline fill="none" stroke="var(--accent)" stroke-width="1.6" points="${P.map(p => `${X(p.t).toFixed(1)},${Yp(p.v).toFixed(1)}`).join(" ")}"></polyline>` : "";
      const pbarsSvg = priceBars ? P.map(p => {
        const cx = X(p.t), py = Yp(p.v), x0 = Math.max(padL, cx - pbw / 2);
        return `<rect x="${x0.toFixed(1)}" y="${py.toFixed(1)}" width="${pbw.toFixed(1)}" height="${Math.max(0, baseY - py).toFixed(1)}" fill="var(--accent)" fill-opacity="0.55"></rect>`
          + `<rect x="${x0.toFixed(1)}" y="${(py - 1).toFixed(1)}" width="${pbw.toFixed(1)}" height="2" fill="var(--accent)"></rect>`;
      }).join("") : "";
      // In LINE mode the dots keep the true n honest; in BAR mode each bar IS a
      // sample, so a dot on top of its own cap would claim nothing extra.
      const dots = priceBars ? "" : P.map(p => `<circle cx="${X(p.t).toFixed(1)}" cy="${Yp(p.v).toFixed(1)}" r="1.5" fill="var(--accent)"></circle>`).join("");
      const leftAxis = P.length ? [pMin, pMin + pSpan / 2, pMax].map(v =>
        `<text x="${(padL - 5).toFixed(1)}" y="${(Yp(v) + 3).toFixed(1)}" text-anchor="end" font-size="8.5" fill="var(--accent)">${fmt(v)}</text>`).join("") : "";
      const rightAxis = V.length ? [0, vMax].map(v =>
        `<text x="${(W - padR + 5).toFixed(1)}" y="${(Yv(v) + 3).toFixed(1)}" text-anchor="start" font-size="8.5" fill="var(--muted)">${fmt(v)}</text>`).join("") : "";
      const dts = [tMin, (tMin + tMax) / 2, tMax].map((ms, i) =>
        `<text x="${X(ms).toFixed(1)}" y="${(H - 6).toFixed(1)}" text-anchor="${i === 0 ? "start" : i === 2 ? "end" : "middle"}" font-size="8.5" fill="var(--muted)">${new Date(ms).toISOString().slice(0, 7)}</text>`).join("");
      const aria = `${t9("Price × coverage")}: ${P.length} price, ${V.length} coverage`;
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px" role="img" aria-label="${esc(aria)}">`
        + (P.length ? `<text x="${padL}" y="11" font-size="8.5" fill="var(--accent)">${esc(t9("Price"))} ${esc(priceUnit || "")}</text>` : "")
        + (V.length ? `<text x="${W - padR}" y="11" text-anchor="end" font-size="8.5" fill="var(--muted)">${esc(t9("Articles"))}</text>` : "")
        + bars + pbarsSvg + line + dots + leftAxis + rightAxis + dts + `</svg>`;
    }

    // --- Combined time-aligned TREND overlay (Analysis window; maintainer-ruled
    // 2026-06-17). ONE chart for a keyword + its related keywords/tags (all article
    // COUNTS = a shared unit, so an honest shared axis), with an INDEXED mode (each
    // series rebased to 100 at the window start) that ALSO overlays commodity PRICE
    // series of a DIFFERENT unit WITHOUT conflating magnitudes — plus the precise
    // dual-axis price×coverage panel. The shared axis is TIME. Counts only / no
    // score; the design respects co-occurrence ≠ causation, but the on-graph caveat
    // text was removed (maintainer 2026-06-17). Lazy: rendered on tab-show, cached.
    const _anTrend = { key: null, term: null, counts: [], suggested: [], picked: {}, mode: "counts",
                       byLang: null, concept: null, articles: null };
    function commoditiesForTerm(term, related) {
      // Reverse of the COMMODITY_QUERY seed: suggest a commodity when its family
      // word appears in the analyzed term or its related terms (e.g. a "Middle East"
      // corpus whose associations include "oil" -> WTI/BRENT). Deterministic
      // whole-word match; never fabricates a link.
      const hay = (" " + (term || "") + " " + (related || []).join(" ") + " ").toLowerCase();
      const out = [];
      for (const sym of Object.keys(COMMODITY_QUERY)) {
        const words = COMMODITY_QUERY[sym].toLowerCase().split(/\s+/).filter(w => w.length > 2);
        if (words.some(w => hay.includes(" " + w) || hay.includes(w + " "))) out.push(sym);
      }
      return out.slice(0, 8);
    }
    // The Trend tab builds its URLs from a TERM, not from the params object, so the lens
    // `loadAnalysis` applied does not travel with them on its own. This lifts it back off
    // those params as a suffix. Without it the Trend tab charts the literal term while
    // the Articles list beside it counts the concept -- the exact disagreement Q501
    // exists to remove, one tab further along than the one that was fixed first.
    function _anLensSuffix(p) {
      if (!p || !p.get) return "";
      const out = new URLSearchParams();
      ["expand", "literal_cap", "ui_lang"].forEach((k) => {
        const v = p.get(k); if (v != null) out.set(k, v);
      });
      // A pin is `term:ring_id`, so one aimed at the typed term simply does not apply to
      // a related keyword -- the server reports it rather than silently widening.
      (p.getAll ? p.getAll("sense") : []).forEach((v) => out.append("sense", v));
      const qs = out.toString();
      return qs ? "&" + qs : "";
    }
    async function renderAnTrend(p) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("an-trend"); if (!host) return;
      const term = (p && p.get && p.get("query")) || anQuery() || "";
      const lens = _anLensSuffix(p);
      // Cached on the term AND THE LENS. Keyed on the term alone, a reader who narrowed
      // to the words they typed would be handed the widened chart straight from the
      // cache -- which reads as the toggle being broken rather than as a stale cache.
      const key = term + "\u0000" + lens;
      if (_anTrend.key === key && _anTrend.counts.length) { drawAnTrend(); return; }
      if (!term) { host.innerHTML = `<div class="muted">${esc(t("Open the analysis from a keyword or a search to see its combined trend."))}</div>`; return; }
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      _anTrend.key = key; _anTrend.term = term; _anTrend.counts = []; _anTrend.suggested = []; _anTrend.picked = {}; _anTrend.mode = "counts";
      try {
        const [main, assoc] = await Promise.all([
          api("/api/insights/trend?bucket=week&term=" + encodeURIComponent(term) + lens).catch(() => null),
          api("/api/insights/associations?term=" + encodeURIComponent(term) + "&limit=8" + lens).catch(() => null),
        ]);
        const series = [];
        if (main && main.resolved && (main.points || []).length)
          series.push({ label: term, unit: t("articles"), color: "var(--accent)", points: main.points.map(pt => ({ t: pt.date, v: pt.count })) });
        // Related keywords are corpora too: overlay each one's own coverage series.
        const rel = ((assoc && assoc.nodes) || []).map(n => n.label || n.id)
          .filter(x => x && x.toLowerCase() !== term.toLowerCase()).slice(0, 4);
        const palette = ["var(--ok)", "var(--warn)", "#6ea8fe", "#c084fc"];
        const relTrends = await Promise.all(rel.map(rt =>
          api("/api/insights/trend?bucket=week&term=" + encodeURIComponent(rt) + lens).catch(() => null)));
        relTrends.forEach((rd, i) => {
          if (rd && rd.resolved && (rd.points || []).length)
            series.push({ label: rel[i], unit: t("articles"), color: palette[i % palette.length], points: rd.points.map(pt => ({ t: pt.date, v: pt.count })) });
        });
        _anTrend.counts = series;
        // Q502/Q417: the per-language halves the aggregate already publishes. Captured
        // rather than re-fetched -- the stacked view and the hover must describe the
        // SAME resolution as the line above them, and a second call under a different
        // lens is how two views of one term come to disagree.
        _anTrend.byLang = (main && main.by_language) || null;
        _anTrend.concept = (main && main.concept) || null;
        _anTrend.articles = (main && main.articles != null) ? main.articles : null;
        _anTrend.suggested = commoditiesForTerm(term, rel);
        if (_anCommodity && _anCommodity.symbol && _anTrend.suggested.indexOf(_anCommodity.symbol) < 0)
          _anTrend.suggested.unshift(_anCommodity.symbol);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      drawAnTrend();
    }
    function anTrendSetMode(m) { _anTrend.mode = m; drawAnTrend(); }
    async function anTrendPick(sym) {
      if (!sym) return;
      if (_anTrend.picked[sym]) { delete _anTrend.picked[sym]; drawAnTrend(); return; }
      try {
        const pd = await api("/api/commodities/" + encodeURIComponent(sym) + "/prices").catch(() => null);
        const prices = (pd && pd.prices) || [];
        _anTrend.picked[sym] = { prices, unit: prices[0] ? (prices[0].currency + "/" + prices[0].unit) : "" };
      } catch (e) { _anTrend.picked[sym] = { prices: [], unit: "" }; }
      if (_anTrend.mode === "counts") _anTrend.mode = "indexed";   // a price cannot share the counts axis
      drawAnTrend();
    }
    function drawAnTrend() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("an-trend"); if (!host) return;
      const counts = _anTrend.counts || [];
      if (!counts.length) { host.innerHTML = `<div class="muted">${esc(t("No coverage to chart for this term yet."))}</div>`; return; }
      const picks = Object.keys(_anTrend.picked);
      const indexed = _anTrend.mode === "indexed";
      // Counts always; commodity PRICE series only in indexed mode (different unit).
      const list = counts.slice();
      if (indexed) for (const sym of picks) {
        const c = _anTrend.picked[sym];
        const pts = (c.prices || []).map(p => ({ t: p.observed_on, v: +p.price })).filter(p => isFinite(p.v));
        if (pts.length) list.push({ label: sym, unit: c.unit || t("price"), color: "var(--err)", points: pts });
      }
      const seg = (m, lbl) => `<button class="ghost tiny${_anTrend.mode === m ? " on" : ""}" onclick="anTrendSetMode('${m}')">${esc(lbl)}</button>`;
      // Q502's view, offered only when the concept is actually carried in more than one
      // language: a one-band stack is an area chart wearing a stack's clothes and asks
      // the reader to look for parts that are not there.
      const langKeys = Object.keys(_anTrend.byLang || {}).filter(
        (k) => ((_anTrend.byLang[k] || {}).points || []).length);
      const byLangOffered = langKeys.length > 1;
      // A MODE THE VIEW NO LONGER OFFERS FALLS BACK, rather than leaving the row with no
      // button lit beside a chart drawn in a mode the reader cannot see named. The mode
      // is reset per analysis run, so this only bites when the same corpus comes back
      // carrying one language -- but a control row that lights nothing reads as broken.
      if (_anTrend.mode === "bylang" && !byLangOffered) _anTrend.mode = "counts";
      const modeRow = `<div class="row" style="gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:6px">`
        + `<span class="muted" style="font-size:11px">${esc(t("View"))}:</span>` + seg("counts", t("Counts")) + seg("indexed", t("Indexed"))
        + (byLangOffered ? seg("bylang", t("By language")) : "") + `</div>`;
      const chip = (sym) => `<button class="chip${_anTrend.picked[sym] ? " on" : ""}" onclick="anTrendPick('${sym}')"`
        + `${_anTrend.picked[sym] ? ' style="border-color:var(--accent)"' : ''}>${esc(sym)}</button>`;
      const suggRow = `<div class="row" style="gap:5px;align-items:center;flex-wrap:wrap;margin-bottom:6px">`
        + `<span class="muted" style="font-size:11px">${esc(t("Overlay a commodity"))}:</span>`
        + _anTrend.suggested.map(chip).join(" ")
        + ` <select onchange="anTrendPick(this.value);this.value=''" style="width:auto;font-size:12px">`
        + `<option value="">${esc(t("more…"))}</option>`
        + Object.keys(COMMODITY_QUERY).map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("")
        + `</select></div>`;
      const caveat = indexed
        ? t("Indexed to 100 at the window start — relative movement, not absolute levels. Hover shows the real value.")
        : t("Article counts on a shared time axis.");
      if (_anTrend.mode === "bylang" && byLangOffered) return _drawAnTrendByLang(host, modeRow, langKeys);
      host.innerHTML = modeRow + suggRow + `<div id="an-trend-chart"></div>`
        + `<p class="card-caveat" style="margin-top:6px">${esc(caveat)}</p>`
        + (_anTrend.mode === "counts" && picks.length ? `<p class="hint muted" style="margin:4px 0 0">${esc(t("Switch to Indexed to overlay commodity prices honestly (different units)."))}</p>` : "")
        + `<div id="an-trend-dual" style="margin-top:10px"></div>`;
      ooChart($("an-trend-chart"), list, { height: 240, indexed: indexed, zeroBase: !indexed });
      // Precise dual-axis (2 series): the first picked commodity's price × this
      // term's coverage, each on its OWN real-unit scale (the shipped overlay).
      const dual = $("an-trend-dual");
      if (picks.length && counts.length) {
        const c = _anTrend.picked[picks[0]];
        const cov = (counts[0].points || []).map(p => ({ date: p.t, count: p.v }));
        dual.innerHTML = `<div class="hint"><b>${esc(t("Dual-axis"))}</b> — ${esc(picks[0])} · ${esc(t("Price × coverage"))} `
          + `<span class="muted">${esc(t("each on its own real-unit scale"))}</span></div>` + commodityOverlaySvg(c.prices, cov, c.unit);
      } else dual.innerHTML = "";
    }

    // Q502 = a — "stacked per language with a legend", through the ONE chart toolkit
    // (invariant #16), and the sentence that keeps the stack honest.
    //
    // A STACK ASSERTS PART-TO-WHOLE, AND THESE PARTS DO NOT SUM TO THIS WHOLE. An
    // article carrying two languages' forms of the concept is counted in BOTH bands and
    // ONCE in the article total, so the stack's height is a sum of per-language mention
    // counts and NOT the distinct article count. Drawn without saying so, the picture
    // makes a claim the data cannot support -- so the distinct total is printed beside
    // it, labelled, and the caveat names the overlap rather than leaving a reader to
    // discover it by adding the bands up.
    //
    // The "absent bucket = zero" declaration `stacked` requires is TRUE here and is why
    // this caller may pass it: these are mention counts over a complete weekly grid, so
    // a week a language does not appear in is a week it was not mentioned. A published
    // NULL would be different, and `_stackSeries` refuses that case outright.
    function _drawAnTrendByLang(host, modeRow, langKeys) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s2, v) =>
        String(s2).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? v[k] : m));
      const ordered = langKeys.slice().sort((a, b) => {
        const na = ((_anTrend.byLang[a] || {}).articles) || 0;
        const nb = ((_anTrend.byLang[b] || {}).articles) || 0;
        return nb - na || String(a).localeCompare(String(b));
      });
      const series = ordered.map((lg) => ({
        label: ooLangCode(lg),
        unit: t("mentions"),
        points: (((_anTrend.byLang[lg] || {}).points) || [])
          .map((pt) => ({ t: pt.date, v: pt.count })),
      }));
      const totals = ordered.map((lg) =>
        `${ooLangCell(lg)} ${esc(String(((_anTrend.byLang[lg] || {}).articles) || 0))}`).join(" · ");
      host.innerHTML = modeRow + `<div id="an-trend-chart"></div>`
        + `<div class="hint" style="margin-top:6px">${totals}`
        + (_anTrend.articles != null
            ? ` <span class="muted">· ${esc(tf("{n} articles in total, counted once each",
                { n: _anTrend.articles }))}</span>` : "")
        + `</div>`
        + `<p class="card-caveat" style="margin-top:6px">`
        // ONE LINE, however long: a concatenated literal is invisible to every instrument
        // that harvests translation calls by READING THE SOURCE -- the i18n report and
        // the guards that check a rendered string has twelve entries both see the pieces
        // and neither sees the sentence. The same blind spot cost a module-level constant
        // its translations earlier in this slice; splitting a caveat across `+` is that
        // trap with a different shape.
        //
        // AND THE INSTRUMENT DOES NOT STRIP COMMENTS: the first draft of this note quoted
        // the call shape it describes, and `--max-unkeyed-t-calls` harvested the quote as
        // a real call and demanded a key for the ellipsis inside it. A comment about a
        // source-reading guard is source the guard reads.
        + esc(t("Bands are mention counts per language and they overlap: an article carrying two languages' forms of the concept is counted in both, so the stack's height is not the article total beside it."))
        + `</p><div id="an-trend-refusal" class="hint muted"></div>`;
      ooChart($("an-trend-chart"), series, { height: 240, stacked: true, zeroBase: true });
      // A REFUSAL IS REPORTED, never silently swallowed: without this the reader sees an
      // ordinary multi-line chart under a control labelled "By language" and has no way
      // to learn that the stack was declined or why.
      const host2 = $("an-trend-chart");
      const why = host2 && host2.dataset ? host2.dataset.stackRefusal : null;
      const box = $("an-trend-refusal");
      if (box && why) {
        // Each refusal is a KEYED sentence of its own rather than an interpolated code:
        // "gap" and "indexed" are reasons a reader has to be able to act on, and a raw
        // token in eleven locales is not one.
        const said = {
          gap: t("One of these series has a published gap, and a gap is not a zero."),
          indexed: t("Indexed values cannot be added, so they are not stacked."),
          log: t("Heights on a logarithmic axis do not add, so they are not stacked."),
          "one-series": t("Only one language is present, so there is nothing to stack."),
          empty: t("No points in this window."),
        }[why];
        box.textContent = t("These series could not be stacked, so they are drawn as lines.")
          + (said ? " " + said : "");
      } else if (box) {
        box.textContent = "";
      }
    }

    // --- Related & coordination (Analysis window; maintainer-ruled 2026-06-17):
    // make the coordination "scan" AMBIENT in analysis (not a manual tab) AND let the
    // user BRANCH related articles into a NEW corpus for associated research. Computed
    // automatically when the Related subtab opens (lazy, cached per corpus). Surfaces
    // near-identical clusters as "N near-identical copies across M sources = one voice"
    // — independence by DISTINCT SOURCES, structural only, NO score; the non-collusion +
    // absence-is-not-absence caveat is visible. Each cluster branches via
    // openAnalysisForIds (the exact-set spawn) = a fresh corpus = associated research.
    const _anRelated = { key: null };
    const _anCompetitive = { key: null };   // batch F item 4: Source-competitive ported into #an
    let _anRelatedClusters = [];
    let _anRelatedLinks = [];
    async function renderAnRelated(p) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("an-related"); if (!host) return;
      const key = (p && p.toString && p.toString()) || "";
      if (_anRelated.key === key && host.dataset.done === "1") return;   // cached on this corpus
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      _anRelated.key = key; host.dataset.done = "";
      const qs = p ? p.toString() : "";
      try {
        // Two independence-honest "related" lenses over the corpus: near-identical
        // copies (text) AND shared outbound origins (citation). Both reuse existing
        // endpoints; each cluster/origin BRANCHES into a fresh corpus.
        const [cd, ld] = await Promise.all([
          api("/api/insights/corpus-coordination?" + qs).catch(() => null),
          api("/api/links/corpus?" + qs).catch(() => null),
        ]);
        _anRelatedClusters = (cd && cd.clusters) || [];
        _anRelatedLinks = (ld && ld.items) || [];
        let html = `<div class="row" style="gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">`
          + `<button class="secondary tiny" onclick="branchSelectedRelated()">${esc(t("Branch selected into a new corpus →"))}</button>`
          + ` <span id="an-rel-selcount" class="muted" style="font-size:11px"></span></div>`
          + `<div class="hint"><b>${_anRelatedClusters.length}</b> ${esc(t("Near-identical clusters"))}`
          + ` <span class="muted">· ${esc((cd && cd.method) || "")}</span></div>`;
        if (!_anRelatedClusters.length) {
          html += `<div class="muted" style="margin:6px 0 2px">`
            + `${esc(t("No near-identical clusters detected in this corpus — not proof there is no coordination, only that none was found at this threshold."))}</div>`;
        } else {
          html += _anRelatedClusters.map((c, i) => {
            const voice = c.single_source
              ? t("{n} near-identical copies from one source = one voice").replace("{n}", c.size)
              : t("{n} near-identical copies across {m} sources = effectively one voice").replace("{n}", c.size).replace("{m}", c.distinct_sources);
            const ex = (c.members || []).slice(0, 6).map((m) =>
              `<li><a href="/api/articles/${m.id}/view" target="_blank" rel="noopener">${esc(m.title || t("(untitled)"))}</a>`
              + ` <span class="muted">· ${esc(m.source || "")}</span></li>`).join("");
            const more = c.size > 6 ? `<li class="muted">+${c.size - 6} ${esc(t("more"))}</li>` : "";
            return `<div class="card" style="padding:10px;margin-top:8px">`
              + `<div class="row" style="justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">`
              + `<span style="display:flex;align-items:center;gap:6px"><input type="checkbox" class="an-rel-pick" data-kind="c" data-idx="${i}" onchange="anRelUpdateSel()" aria-label="${esc(t("Select for branching"))}"><b>${esc(voice)}</b></span>`
              + `<button class="secondary tiny" onclick="branchFromRelated(${i})" title="${esc(t("Open these articles as a new analysis corpus"))}">${esc(t("Branch into a new corpus →"))}</button></div>`
              + `<details style="margin-top:6px"><summary class="muted" style="cursor:pointer">${esc(t("Show all"))}</summary>`
              + `<ul style="margin:6px 0 0">${ex}${more}</ul></details></div>`;
          }).join("") + `<p class="card-caveat" style="margin-top:8px">${esc((cd && cd.caveat) || "")}</p>`;
        }
        // --- Shared origins: articles citing the SAME outbound page (one origin,
        // not independent confirmation — the anti-false-triangulation lens). ---
        html += `<div class="hint" style="margin-top:16px"><b>${_anRelatedLinks.length}</b> ${esc(t("Shared origins"))}`
          + ` <span class="muted">· ${esc(t("articles in this corpus citing the same outbound page"))}</span></div>`;
        if (!_anRelatedLinks.length) {
          html += `<div class="muted" style="margin:6px 0 2px">${esc(t("No outbound page is cited by 2+ articles in this corpus yet."))}</div>`;
        } else {
          html += _anRelatedLinks.map((it, i) => {
            const label = it.domain || it.link_text || it.normalized_url;
            return `<div class="card" style="padding:10px;margin-top:8px">`
              + `<div class="row" style="justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">`
              + `<span style="display:flex;align-items:center;gap:6px"><input type="checkbox" class="an-rel-pick" data-kind="o" data-idx="${i}" onchange="anRelUpdateSel()" aria-label="${esc(t("Select for branching"))}">`
              + `<span>${extLink(it.sample_url || it.normalized_url, esc(label), "", "")} `
              + `<span class="muted">· ${it.citations}× ${esc(t("cited"))}</span></span></span>`
              + `<button class="secondary tiny" onclick="branchFromOrigin(${i})" title="${esc(t("Open every article citing this origin as a new corpus"))}">${esc(t("Branch into a new corpus →"))}</button></div></div>`;
          }).join("")
            + `<p class="card-caveat" style="margin-top:8px">${esc((ld && ld.caveat) || t("Several articles citing the same page are not independent confirmation — one origin, several echoes."))}</p>`;
        }
        host.innerHTML = html;
        host.dataset.done = "1";
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    function branchFromRelated(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const c = _anRelatedClusters[i];
      if (!c || !c.article_ids || !c.article_ids.length) return;
      openAnalysisForIds(c.article_ids, t("Near-identical cluster") + " · " + c.size);
    }
    // Facet DRILL (P5.1b): narrow the current corpus to the articles that MENTION a
    // who/where/when value, then spawn a refined analysis window over them — the drill
    // that makes a facet co-equal with the text query. Re-uses anParams() so it intersects
    // whatever corpus is active (an exact id set OR the search + Advanced filters).
    async function branchByFacet(group, idx) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const it = _anFacets && _anFacets[group] && _anFacets[group][idx];
      if (!it) return;
      const p = anParams();
      p.set("facet", it.facet);
      p.set("value", it.value);
      try {
        const d = await api("/api/insights/corpus-facet-articles?" + p.toString());
        const ids = d.article_ids || [];
        if (!ids.length) {
          if (typeof toast === "function") toast(t("No articles mention this in the current corpus."));
          return;
        }
        openAnalysisForIds(ids, it.label + " · " + ids.length);
      } catch (e) { if (typeof toast === "function") toast(e.message); }
    }
    // Branch every article that cites one shared outbound origin into a fresh corpus
    // (the "sources' sources" trail). Fetches the citing-article ids on click.
    async function branchFromOrigin(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const it = _anRelatedLinks[i]; if (!it) return;
      try {
        const d = await api("/api/links/articles-by-link?url=" + encodeURIComponent(it.normalized_url || it.sample_url));
        const ids = (d.articles || []).map((a) => a.id);
        if (!ids.length) { if (typeof toast === "function") toast(t("No articles cite this origin.")); return; }
        openAnalysisForIds(ids, (it.domain || t("Shared origin")) + " · " + ids.length);
      } catch (e) { if (typeof toast === "function") toast(e.message); }
    }
    // Multi-select branch: union the SELECTED clusters' + origins' article sets into
    // ONE fresh corpus (associated research over a hand-picked combination).
    function anRelUpdateSel() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const n = document.querySelectorAll("#an-related .an-rel-pick:checked").length;
      const el = $("an-rel-selcount");
      if (el) el.textContent = n ? t("{n} selected").replace("{n}", n) : "";
    }
    async function branchSelectedRelated() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const picks = Array.from(document.querySelectorAll("#an-related .an-rel-pick:checked"));
      if (!picks.length) { if (typeof toast === "function") toast(t("Select one or more rows to branch.")); return; }
      const ids = new Set();
      const originIdx = [];
      for (const cb of picks) {
        if (cb.dataset.kind === "c") {
          const c = _anRelatedClusters[+cb.dataset.idx];
          (c && c.article_ids || []).forEach((id) => ids.add(id));
        } else { originIdx.push(+cb.dataset.idx); }
      }
      try {
        const lists = await Promise.all(originIdx.map((i) => {
          const it = _anRelatedLinks[i];
          return it ? api("/api/links/articles-by-link?url=" + encodeURIComponent(it.normalized_url || it.sample_url)).catch(() => null) : null;
        }));
        for (const d of lists) (d && d.articles || []).forEach((a) => ids.add(a.id));
      } catch (e) { /* origins are best-effort; cluster ids still branch */ }
      const arr = Array.from(ids);
      if (!arr.length) { if (typeof toast === "function") toast(t("No articles in the selected rows.")); return; }
      openAnalysisForIds(arr, t("Selected related") + " · " + arr.length);
    }

    // Self-contained radial mind-map for the analysis window. Distinct from the
    // Insights renderGraph() (which owns _mm* state + a force/zoom canvas): this
    // draws ONE static, deterministic SVG into the container it is handed — no
    // shared globals, no animation loop. Maintainer mind-map rules: centre →
    // arms → ALWAYS outward; first-ring neighbours on a circle; edges centre→
    // neighbour only (radial, no cross-tangle); never interpolate fake structure.
    // Consumes the /api/insights/graph shape: nodes {id,label,size,center}, edges
    // {a,b,weight}, plus level/method/caveat. Font size scales with node size.
    // In-map controls (mind-map rules): a Cloud SECOND view, a text-size control and
    // ⛶ Enlarge. State is kept so the controls re-render from the same graph.
    const _anMM = { graph: null, cloud: false, concept: false, arms: null, scale: 100, big: false };
    function anMMset(patch) { Object.assign(_anMM, patch); if (_anMM.graph) renderAnMindmap(_anMM.graph); }
    // Q512: THE RING AT THE CENTRE, ONE ARM PER LANGUAGE, ASSOCIATIONS OFF THE ARMS.
    // A third view beside Map and Cloud rather than a replacement for Map: they answer
    // different questions (Map = "what does this term sit with?", Concept = "where does
    // this concept live?"), and the mind-map rules say the cloud is a SECOND view, which
    // is a rule about not replacing the map with something else.
    //
    // PURE (payload + geometry -> svg) so the geometry that the mind-map rules constrain
    // can be driven in node: centre -> arm -> association, ALWAYS outward, every edge
    // radial, nothing crossing. An association sits inside its OWN arm's angular sector,
    // so which arm it hangs off is read off the picture rather than from a legend.
    function _anConceptTreeSvg(d, geo) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const { cx, cy, R, scale } = geo;
      const arms = (d && d.arms) || [];
      if (!arms.length) return "";
      const edges = [];
      const nodes = [];
      const line = (x1, y1, x2, y2, w) =>
        `<line stroke="var(--border)" stroke-width="${w}" x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}"`
        + ` x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"></line>`;
      const label = (x, y, text, size, weight, col, title) =>
        `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})">`
        + (title ? `<title>${esc(title)}</title>` : "")
        + `<text text-anchor="middle" dominant-baseline="central" font-size="${size.toFixed(1)}"`
        + ` font-weight="${weight}" fill="${col}">${esc(text)}</text></g>`;
      const step = (2 * Math.PI) / arms.length;
      arms.forEach((a, i) => {
        const ang = i * step - Math.PI / 2;
        const ax = cx + R * Math.cos(ang), ay = cy + R * Math.sin(ang);
        edges.push(line(cx, cy, ax, ay, 1.6));
        const forms = (a.forms || []).join(", ");
        // The hover carries the layered detail (invariant #17): the form(s) this arm is,
        // and -- when several languages share one spelling -- which other arms are the
        // same word, so three arms of one article do not read as three languages of
        // coverage.
        const shared = (a.form_shared_with || []).length
          ? " — " + t("the same word in") + " "
            + a.form_shared_with.map((x) => ooLangCode(x)).join(", ") : "";
        // Q302 INSIDE AN SVG. `ooLangCell` renders an HTML `<span title=…>`, which an
        // SVG `<text>` cannot hold -- so the ruling is expressed in the markup this
        // surface actually emits: the CODE (`ooLangCode`) is what is drawn, and the
        // localised NAME (`ooLangDisplayName`) joins the `<title>` the node already
        // carries. Same rule, same two facts, a different element.
        const lname = ooLangDisplayName(a.language, "");
        nodes.push(label(ax, ay, `${ooLangCode(a.language)} ${a.articles}`, 13 * scale, 600,
                         "var(--ok)", `${lname ? lname + " — " : ""}${forms}${shared}`));
        const assoc = (a.associations || []);
        // The arm's OWN angular sector, so an association can never drift under a
        // neighbouring language. One arm -> its whole circle; the fan never exceeds the
        // sector, so two arms' associations cannot interleave.
        const fan = Math.min(step * 0.72, Math.PI / 3);
        assoc.forEach((x, j) => {
          const f = assoc.length === 1 ? 0 : (j / (assoc.length - 1) - 0.5) * fan;
          const bang = ang + f, br = R * 1.72;
          const bx = cx + br * Math.cos(bang), by = cy + br * Math.sin(bang);
          edges.push(line(ax, ay, bx, by, 1));
          nodes.push(label(bx, by, x.term, 9.5 * scale, 400, "var(--accent)",
                           `${x.term} · ${x.articles}`));
        });
      });
      const c = (d.center || {});
      nodes.push(label(cx, cy, c.label || "", 17 * scale, 700, "var(--fg)",
                       `${c.ring_id || ""} · ${c.articles || 0}`));
      return edges.join("") + nodes.join("");
    }
    function renderAnMindmap(graph, hostEl) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = hostEl || $("an-mindmap");
      if (!host) return;
      if (graph) _anMM.graph = graph;
      const g = _anMM.graph || {};
      const all = (g.nodes || []);
      const controls = `<div class="row" style="gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap">`
        + `<button class="ghost tiny${(!_anMM.cloud && !_anMM.concept) ? " on" : ""}" onclick="anMMset({cloud:false,concept:false})">Map</button>`
        + `<button class="ghost tiny${_anMM.cloud ? " on" : ""}" onclick="anMMset({cloud:true,concept:false})">Cloud</button>`
        // Offered only when the term IS in a ring the corpus carries more than one form
        // of: a Concept view over a single language is a straight line drawn as though
        // it were a structure.
        + ((_anMM.arms && _anMM.arms.expanded)
            ? `<button class="ghost tiny${_anMM.concept ? " on" : ""}" onclick="anMMset({cloud:false,concept:true})">`
              + `${esc(t("Concept"))}</button>`
            : "")
        + `<label class="hint" style="display:flex;align-items:center;gap:4px">${esc(t("Text size"))}`
        + ` <input type="range" min="60" max="180" value="${_anMM.scale}" oninput="anMMset({scale:+this.value})" style="width:90px"></label>`
        + `<button class="ghost tiny" onclick="anMMset({big:!_anMM.big})" title="${esc(t("Enlarge the mindmap"))}">⛶</button></div>`;
      // The Concept view reads a DIFFERENT payload, so it must not be gated on the
      // association graph having content: a corpus can carry a concept in six languages
      // and still have no keyword co-occurring often enough to draw an association map.
      // Gated below the "no associations" line, the view offered by the button above
      // would have been unreachable in exactly the young corpus it is most useful on.
      const _concept = (_anMM.concept && _anMM.arms && _anMM.arms.expanded) ? _anMM.arms : null;
      if (all.length < 2 && !_concept) {
        host.innerHTML = controls + `<div class="muted">${esc(t("No strong associations yet."))}</div>`;
        return;
      }
      const center = all.find((n) => n.center) || all[0] || {id: "", label: "", size: 1};
      const neighbours = all.filter((n) => n.id !== center.id)
        .sort((a, b) => (b.size || 1) - (a.size || 1)).slice(0, 24);
      const scale = (_anMM.scale || 100) / 100, big = _anMM.big;
      const W = big ? 1100 : 680, H = big ? 720 : 460, cx = W / 2, cy = H / 2;
      const R = Math.min(W, H) * 0.36;
      const maxSize = Math.max(center.size || 1, ...neighbours.map((n) => n.size || 1), 1);
      const fsOf = (n) => ((n.id === center.id ? 17 : 9 + 9 * Math.sqrt((n.size || 1) / maxSize)) * scale);
      let edges = "";
      if (_concept) {
        const d = _concept;
        const tree = _anConceptTreeSvg(d, {cx, cy, R: R * 0.62, scale});
        // THE PICTURE NAMES WHAT IT OMITS. A ring language the corpus carries nothing in
        // gets no arm, because an empty arm asserts the concept exists there and is
        // merely quiet -- a different fact. Naming them keeps the omission visible
        // instead of cropping the sky to what happens to be in it.
        // The not-observed line is ordinary HTML, so it uses the ordinary renderer:
        // `ooLangCell` already escapes, which is why the forms beside it are escaped
        // here and the whole string is not escaped again around it.
        const missing = (d.not_observed || []).map((n) =>
          `${ooLangCell(n.language)}: ${esc((n.forms || []).join(", "))}`);
        const omitted = missing.length
          ? `<div class="hint muted" style="margin-top:4px">`
            + `${esc(t("Not observed in this corpus:"))} ${missing.join(" · ")}</div>`
          : "";
        host.innerHTML = controls
          + `<svg viewBox="0 0 ${W} ${H}" width="100%" style="background:var(--panel2);`
          + `border:1px solid var(--border);border-radius:8px">${tree}</svg>`
          + omitted
          + `<div class="hint muted" style="margin-top:6px">`
          + `${esc(t("The concept at the centre, one arm per language, associations off the arms."))} `
          + `${esc(d.method ? t(d.method) : "")} <b>${esc(d.caveat ? t(d.caveat) : "")}</b></div>`;
        return;
      }
      if (_anMM.cloud) {
        // Word cloud SECOND view: golden-angle spiral by size, no edges.
        [center, ...neighbours].sort((a, b) => (b.size || 1) - (a.size || 1)).forEach((n, i) => {
          const ang = i * 2.39996, r = 15 * Math.sqrt(i);
          n._x = cx + r * Math.cos(ang) * 1.5; n._y = cy + r * Math.sin(ang);
        });
      } else {
        // Radial tree: centre → arms → ALWAYS outward (deterministic, no cross-tangle).
        center._x = cx; center._y = cy;
        neighbours.forEach((n, i) => {
          const ang = (i / neighbours.length) * 2 * Math.PI - Math.PI / 2;
          n._x = cx + R * Math.cos(ang); n._y = cy + R * Math.sin(ang);
        });
        edges = neighbours.map((n) =>
          `<line stroke="var(--border)" stroke-width="1.4" x1="${cx}" y1="${cy}"`
          + ` x2="${n._x.toFixed(1)}" y2="${n._y.toFixed(1)}"></line>`).join("");
      }
      const drawNode = (n) => {
        const col = n.id === center.id ? "var(--ok)" : "var(--accent)";
        const fam = (n.members || []).length > 1;
        const title = fam ? `<title>${esc((n.members || []).join(", "))}</title>` : "";
        return `<g transform="translate(${n._x.toFixed(1)},${n._y.toFixed(1)})">${title}`
          + `<text text-anchor="middle" dominant-baseline="central" font-size="${fsOf(n).toFixed(1)}"`
          + ` font-weight="${n.id === center.id ? 700 : 500}" fill="${col}">${esc(n.label || n.id)}</text></g>`;
      };
      const nodesSvg = drawNode(center) + neighbours.map(drawNode).join("");
      const desc = _anMM.cloud
        ? t("Word cloud: keywords sized by shared-article volume; no links.")
        : t("Radial map: the seed keyword at the centre, its strongest relatives outward.");
      host.innerHTML = controls
        + `<svg viewBox="0 0 ${W} ${H}" width="100%" style="background:var(--panel2);`
        + `border:1px solid var(--border);border-radius:8px">${edges}${nodesSvg}</svg>`
        + `<div class="hint muted" style="margin-top:6px">${esc(desc)} `
        + `<b>${esc(t("Font size = shared-article volume."))}</b> ${esc(g.method || "")} ${esc(g.caveat || "")}</div>`;
    }
    // Inline near-dup annotation (maintainer-ruled: "1 voice" inline in lists, PR 3):
    // badge article-row links that are near-identical COPIES (= effectively one voice,
    // not independent corroboration) so echo is never mistaken for confirmation.
    // NON-BLOCKING (the list renders first) + reuses corpus-coordination; reuses the
    // Related subtab's cache when present so it adds no extra fetch in the common path.
    // Best-effort: any failure leaves the list exactly as rendered. Reusable across any
    // host whose article links are /api/articles/{id}/view.
    async function annotateArticleDups(params, host) {
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const key = params ? params.toString() : "";
      try {
        let clusters;
        if (_anRelated && _anRelated.key === key && _anRelatedClusters && _anRelatedClusters.length) {
          clusters = _anRelatedClusters;            // reuse the Related cache (no extra fetch)
        } else {
          const d = await api("/api/insights/corpus-coordination?" + key).catch(() => null);
          clusters = (d && d.clusters) || [];
        }
        if (!clusters.length) return;
        const sizeById = {};
        for (const c of clusters) for (const id of (c.article_ids || [])) sizeById[id] = c.size;
        let flagged = 0;
        const badges = [];
        host.querySelectorAll("a[href]").forEach((a) => {
          const m = (a.getAttribute("href") || "").match(/\/api\/articles\/(\d+)\/view/);
          if (!m || a.dataset.dupBadged) return;
          const sz = sizeById[+m[1]];
          if (!sz) return;
          a.dataset.dupBadged = "1";
          const b = document.createElement("span");
          b.className = "pill"; b.style.marginInlineStart = "6px"; b.style.cursor = "default";
          b.textContent = "≈" + sz;
          b.title = t(_AN_DUP_PILL).replace("{n}", sz);
          a.after(b);
          badges.push({ el: b, size: sz });
          flagged++;
        });
        let note = null;
        if (flagged) {
          note = document.createElement("div");
          note.className = "card-caveat"; note.style.marginTop = "6px";
          note.textContent = t(_AN_DUP_NOTE).replace("{n}", flagged);
          host.appendChild(note);
        }
        // Retained so a language switch can repaint these IN PLACE. Both strings are
        // composed (a keyed frame plus a measured count), which is a text node the i18n
        // DOM walker can never match against its English key -- so without this the
        // CAVEAT stays in the boot language even though every locale already carries a
        // translation for it. Measured in the Chromium walk (S04-14 session 2): in `ar`
        // it kept reading "21 of these are near-identical copies …" in English.
        _anDupBadges = { note, flagged, badges };
      } catch (e) { /* annotation is best-effort, never breaks the list */ }
    }
    // The Articles subtab is PAGINATED (maintainer 2026-06-20): a 1000-result search is
    // browsable page by page with Prev/Next + "Page X of Y" controls BOTH above and below
    // the list. /api/articles already supports limit+offset; `total` drives the page count.
    // _anArtParams remembers the active corpus so paging re-fetches the same selection.
    const _AN_ART_PAGE = 50;
    let _anArtParams = null, _anArtPage = 0;
    function _anArtPager(total, pages) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const TF = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((tpl, v) => tpl.replace(/\{(\w+)\}/g, (_m, k) => v[k]));
      // See the note on the same change in app-settings.js: toLocaleString() reads the
      // BROWSER locale, which the language switcher never touches, so it prints an
      // English separator inside a translated sentence. fmtNum is the ruled one.
      const _anNum = (n) => (typeof fmtNum === "function") ? fmtNum(n, 0) : String(n);
      if (pages <= 1) return "";
      const cur = _anArtPage;
      // ONE FRAME per sentence, not five pieces welded to two numbers. The old form put
      // the word "of" through t() on its own -- two characters, where --audit-chrome
      // floors at three -- so the audit could not see it at all, and it had no en.json
      // key either: every locale rendered "Page 1 of 5" with an English "of" wedged
      // between two translated words. A gate that cannot see a string is not evidence
      // the string is fine. (Written out rather than pasted as a call: both i18n scans
      // read RAW SOURCE, so a literal in a comment is counted as a live UI string.)
      const lbl = esc(TF("Page {n} of {total}", {n: cur + 1, total: pages}))
        + ' <span class="muted">(' + esc(TF("{n} Articles", {n: _anNum(total)})) + ")</span>";
      return '<div class="an-pager" style="display:flex;align-items:center;gap:10px;margin:8px 0;flex-wrap:wrap">'
        + '<button class="tiny ghost" ' + (cur <= 0 ? "disabled" : "") + ' onclick="_anArtGo(' + (cur - 1) + ')">' + esc(t("← Previous")) + "</button>"
        + "<span>" + lbl + "</span>"
        + '<button class="tiny ghost" ' + (cur >= pages - 1 ? "disabled" : "") + ' onclick="_anArtGo(' + (cur + 1) + ')">' + esc(t("Next →")) + "</button></div>";
    }
    function _anArtGo(page) {
      if (!_anArtParams) return;
      _anLoadArticles(_anArtParams, page);
      var a = $("an-articles"); if (a && a.scrollIntoView) a.scrollIntoView({ block: "start", behavior: "smooth" });
    }
    // Tone chip (stored sentiment, VADER English-only — a signal, never a verdict) +
    // a "deduced" language hint (the §2.6 secondary/detected language, shown only when
    // the source left the article untagged). Null-safe: renders nothing when absent.
    // The STORED tone, on its own. Split out of _anToneChip so a surface that already
    // shows the language (the feed card) can render the tone without the deduced-language
    // half repeating what is two segments to its left -- and so there stays exactly ONE
    // implementation of how a tone is drawn and captioned, rather than a second one
    // growing on the next surface that wants it.
    //
    // The caveat travels WITH the value on every surface: VADER is an English lexicon, so
    // a score on non-English coverage is unreliable, and the hover says "a signal, not a
    // verdict" wherever the chip appears. Absent label -> nothing drawn: an article that
    // was never scored (a core install has no VADER, and non-English returns None by
    // design) shows no tone rather than a neutral-looking zero.
    function _toneChip(a) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!a || !a.sentiment_label) return "";
      const c = a.sentiment_label === "positive" ? "var(--ok)"
        : (a.sentiment_label === "negative" ? "var(--err)" : "var(--muted)");
      const sc = (a.sentiment_score != null) ? " " + Number(a.sentiment_score).toFixed(2) : "";
      return ` <span style="color:${c};font-size:.85em" title="${esc(t("Tone (VADER, English-only) — a signal, not a verdict."))}">${esc(t(a.sentiment_label))}${esc(sc)}</span>`;
    }
    function _anToneChip(a) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      let out = _toneChip(a);
      if (a && a.detected_language && !a.language) {
        out += ` <span class="muted" style="font-size:.85em" title="${esc(t("Language deduced offline — the source did not tag it."))}">${esc(t("deduced"))}: ${ooLangCell(a.detected_language)}</span>`;
      }
      return out;
    }
    // Articles-subtab lenses (LOCAL to this list — they never touch the params the
    // other subtabs use): a content-provenance toggle (all/wikipedia/web/newsletter/
    // statistics — a descriptive ingestion-channel filter, NEVER a quality score) and a
    // keyword-count sort. The ×N badge + the count sort appear only when the corpus
    // resolves to a single searched keyword (the keyword-click case).
    let _anProvenance = "";    // "" = all resources
    let _anKwSort = false;     // order the list by the searched keyword's per-article count
    let _anKwForCount = "";    // the keyword whose counts are shown (from the API), or ""
    // Corpus source/language filter (2026-07-20 ruling, item 3): facet controls live
    // IN the Articles subtab (not buried in Advanced), populated from what the CURRENT
    // corpus actually contains (a facet list, never free text). Selecting chips only
    // stages the choice; "Apply filter" (anApplyArticlesFilter) commits it.
    let _anArtFacetSel = { source: "", language: "" };
    let _anArtFacetData = { sources: [], languages: [] };
    function _anSetProvenance(v) {
      _anProvenance = v || "";
      // Wikipedia view orders by keyword count when a count is available (the ruling).
      if (_anProvenance === "wikipedia" && _anKwForCount) _anKwSort = true;
      if (_anArtParams) _anLoadArticles(_anArtParams, 0);
    }
    function _anToggleKwSort() {
      _anKwSort = !_anKwSort;
      // ONE visible sort at a time. The searched-keyword count and the column sort
      // answer different questions and the request can only carry one, so turning this
      // on clears the header/select choice rather than silently overriding it -- two
      // controls that disagree while one quietly wins is the shape this move was
      // supposed to remove, not relocate.
      if (_anKwSort) { const sb = $("an-adv-sort"); if (sb) sb.value = ""; }
      if (_anArtParams) _anLoadArticles(_anArtParams, 0);
    }
    // The sort controls now live in the Articles subtab (ruling 20) and are read LIVE by
    // _anLoadArticles, so changing one re-orders the LIST without re-running the whole
    // analysis -- the other subtabs do not read sort at all, and re-fetching six of them
    // to change a column order would be work nobody asked for.
    function _anSortChanged() {
      _anKwSort = false;                       // the select/headers win once touched
      if (_anArtParams) _anLoadArticles(_anArtParams, 0);
    }
    // A column header IS the sort control (ruling 21): clicking cycles this column
    // ascending/descending, and the arrow in the header says which way, so the header
    // and the select can never show different answers -- they are the same two fields.
    function _anSortBy(field) {
      const sb = $("an-adv-sort"), dr = $("an-adv-dir");
      if (!sb || !dr) return;
      if (sb.value === field) dr.value = (dr.value === "asc") ? "desc" : "asc";
      else { sb.value = field; dr.value = (field === "title" || field === "language" || field === "source") ? "asc" : "desc"; }
      _anSortChanged();
    }
    function _anArtControls(d) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // "Wikipedia" is a proper noun (kept untranslated); the rest go through t().
      const buckets = [["", t("All")], ["wikipedia", "Wikipedia"], ["web", t("Web articles")],
        ["newsletter", t("Newsletters")], ["statistics", t("Statistics")], ["cited", t("Cited sources")]];
      let h = '<div class="an-prov" style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin:2px 0 6px">'
        + `<span class="muted" style="font-size:.85em">${esc(t("Show"))}:</span>`;
      for (const [v, lbl] of buckets) {
        const on = (_anProvenance || "") === v;
        h += `<button class="tiny${on ? "" : " ghost"}" aria-pressed="${on}" onclick="_anSetProvenance('${v}')">${esc(lbl)}</button>`;
      }
      if (d && d.keyword_for_count) {
        const on = _anKwSort;
        h += `<button class="tiny${on ? "" : " ghost"}" style="margin-inline-start:8px" aria-pressed="${on}" `
          + `onclick="_anToggleKwSort()" title="${esc(t("Order articles by how often the searched keyword appears in each."))}">`
          + `↕ “${esc(d.keyword_for_count)}” ${esc(t("count"))}</button>`;
      }
      return h + "</div>";
    }
    // Sources + languages PRESENT in the current corpus, with counts -- a facet LIST
    // of what the corpus actually contains (2026-07-20 ruling, item 3), never free
    // text. Fetched once per fresh corpus (from loadAnalysis); chip selection alone
    // never refetches or re-filters -- only "Apply filter" commits it.
    async function _anLoadArtFacets(p) {
      try {
        const d = await api("/api/insights/corpus-source-language-facets?" + p.toString());
        _anArtFacetData = { sources: d.sources || [], languages: d.languages || [] };
      } catch (e) { _anArtFacetData = { sources: [], languages: [] }; }
      _anRenderArtFacetChips();
    }
    function _anToggleArtFacetChip(kind, value) {
      _anArtFacetSel[kind] = (_anArtFacetSel[kind] === value) ? "" : value;
      _anRenderArtFacetChips();
    }
    function _anRenderArtFacetChips() {
      const host = $("an-art-facets"); if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const srcChips = (_anArtFacetData.sources || []).slice(0, 20).map(s => {
        // Selection/drill key is source_id (never name) -- Source.name carries no
        // uniqueness constraint, so two chips can legitimately share a display name;
        // only the id disambiguates them (2026-07-20 ruling review fix).
        const on = _anArtFacetSel.source === String(s.source_id);
        return `<button type="button" class="an-facet" aria-pressed="${on}" `
          + `onclick="_anToggleArtFacetChip('source', ${esc(JSON.stringify(String(s.source_id)))})">${esc(s.name)} `
          + `<span class="muted">${s.n}</span></button>`;
      }).join(" ");
      const langChips = (_anArtFacetData.languages || []).slice(0, 20).map(l => {
        const on = _anArtFacetSel.language === l.language;
        return `<button type="button" class="an-facet" aria-pressed="${on}" `
          + `onclick="_anToggleArtFacetChip('language', ${esc(JSON.stringify(l.language))})">${ooLangCell(l.language)} `
          + `<span class="muted">${l.n}</span></button>`;
      }).join(" ");
      if (!srcChips && !langChips) { host.innerHTML = ""; return; }
      host.innerHTML = `<div style="margin:4px 0 8px">`
        + (srcChips ? `<div style="margin-bottom:4px"><span class="muted" style="font-size:.85em">${esc(t("source"))}:</span> ${srcChips}</div>` : "")
        + (langChips ? `<div><span class="muted" style="font-size:.85em">${esc(t("language"))}:</span> ${langChips}</div>` : "")
        + `<button class="tiny" style="margin-top:4px" onclick="anApplyArticlesFilter()">${esc(t("Apply filter"))}</button>`
        + `</div>`;
    }
    // The drill -- ids ∩ facet -> the narrowed set, in corpus order (never a clear).
    async function _anFacetDrillIds(ids, facet, value) {
      if (!ids.length) return ids;
      const p = new URLSearchParams();
      p.set("article_ids", ids.join(","));
      p.set("facet", facet);
      p.set("value", value);
      try {
        const d = await api("/api/insights/corpus-facet-articles?" + p.toString());
        return d.article_ids || [];
      } catch (e) { return ids; }   // a failed drill never silently empties the corpus
    }
    // Commit the staged facet selection. For an id-seeded corpus (a card's exact
    // article set) this INTERSECTS via the drill grammar -- ids ∩ source ∩ language --
    // rather than clearing the seeded set (the 2026-07-20 ruling's own wording); for a
    // query-seeded corpus it mirrors into the existing Advanced fields and reuses the
    // already-correct refine path.
    async function anApplyArticlesFilter() {
      const selSrc = _anArtFacetSel.source, selLang = _anArtFacetSel.language;
      if (!selSrc && !selLang) return;
      // selSrc is a source_id (the drill key -- see the chip's onclick); an-adv-source
      // is a NAME field (an-adv-source / _resolve_corpus's own "source" param semantics,
      // unchanged), so mirror the chip's matching source NAME into it, not the id.
      // Each field is only touched when its own facet was actually selected -- never
      // blank the other dimension's pre-existing Advanced value.
      if (selSrc) {
        const srcRow = (_anArtFacetData.sources || []).find(r => String(r.source_id) === selSrc);
        $("an-adv-source").value = srcRow ? srcRow.name : "";
      }
      if (selLang) $("an-adv-lang").value = selLang;
      if (_anIds && _anIds.length) {
        let ids = _anIds.slice();
        if (selSrc) ids = await _anFacetDrillIds(ids, "source", selSrc);
        if (selLang) ids = await _anFacetDrillIds(ids, "language", selLang);
        _anIds = ids;
        const tb = _anTabs.find(x => x.id === _anActiveId);
        if (tb) { tb.ids = ids.slice(); tb.kind = "ids"; _anRenderStrip(); _anSaveTabs(); }
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        const fs = _anFilterSummary();
        $("an-adv-note").innerHTML = fs.length
          ? `<span class="pill">${esc(t("Filtered"))}</span> ${fs.map(esc).join(" · ")}`
          : "";
        loadAnalysis(anParams());
      } else {
        anRunAdvanced();   // a query-seeded corpus already refines correctly
      }
    }
    // /api/articles names an explicit id set `ids`; the analysis params name it
    // `article_ids`, which is what the INSIGHTS endpoints accept. FastAPI silently DROPS
    // an unrecognised query key, so sending `article_ids` to /api/articles did not error
    // -- the id set simply never arrived and the query fell into its browse-by-recency
    // branch, returning the WHOLE corpus. The tab labelled "the matched articles" showed
    // 180 unrelated articles for a 3-article selection, and the CSV/JSON export wrote all
    // of them. Verified against the running app: `article_ids=82,5,164` -> total 180,
    // `ids=82,5,164` -> total 3.
    //
    // It failed OPEN, with plausible data, which is why it survived: every insights
    // subtab beside it was correct, so the counts agreed and only the article LIST lied.
    // Pre-existing and not specific to the brush -- it hit every id-seeded corpus,
    // including every Home card that seeds an exact set (the 2026-06-16 exact-set
    // ruling) and every "Branch into a new corpus".
    //
    // ONE translation, used by every /api/articles caller, so the next one cannot forget.
    // synthesizeResults already carried this fix inline; it now shares this.
    // R1 (2026-09-05): cross-language expansion is ON by default (the ruling) and the
    // reader can narrow to exactly what they typed. The flag lives here rather than in the
    // captured params because it is a LENS on the current corpus, like the sort — flipping
    // it must not re-run the whole analysis.
    let _anExpand = true;
    // {normalized term: ring id} -- the reader's answers to the several-senses refusal
    // (R2a: the reader picks the sense). Keyed on the NORMALIZED term the payload
    // publishes, so the key the UI sends is the key the ring index is built on.
    let _anSenses = {};
    // Q503's NOTE: the reader may switch the 40-form fan-out cap OFF. ON by default, as
    // the ruling asks. A THIRD lens value beside the two above, because "search every
    // language" and "search every FORM of every language" are different questions.
    let _anCap = true;
    // Grouped or interleaved (Q508's note). Interleaved by date is the ruled default;
    // the group-by is the note's addition, and it is a VIEW over the same rows -- it
    // never changes which articles matched.
    let _anGroupByLang = false;
    // The last payload the expansion rail was drawn from — see `_anRepaintXLang`.
    let _anLastCross = null;
    // The two near-duplicate strings, named ONCE so the render and the repaint below
    // cannot drift into being two different keys (which is how a repaint silently stops
    // matching what it is meant to repaint).
    const _AN_DUP_PILL = "One of {n} near-identical copies = effectively one voice. Open Related to inspect the cluster.";
    const _AN_DUP_NOTE = "{n} of these are near-identical copies — fewer independent voices than the count suggests (see Related).";
    // The last near-duplicate annotation drawn — see `_anRepaintDupNote`.
    let _anDupBadges = null;
    // Registered in app-boot's ONE `oo:langchange` listener, for the same reason as
    // `_anRepaintXLang` below. Repaints only text, from values it already holds: no
    // fetch, no re-annotation, and a node that has since been replaced is skipped
    // (`isConnected`) rather than resurrected.
    function _anRepaintDupNote() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!_anDupBadges) return;
      (_anDupBadges.badges || []).forEach(({ el, size }) => {
        if (el && el.isConnected) el.title = t(_AN_DUP_PILL).replace("{n}", size);
      });
      const note = _anDupBadges.note;
      if (note && note.isConnected && _anDupBadges.flagged) {
        note.textContent = t(_AN_DUP_NOTE).replace("{n}", _anDupBadges.flagged);
      }
    }
    // Registered in app-boot's ONE `oo:langchange` listener (never a second listener:
    // a second enumerator is a second thing to forget). Redraws the rail IN PLACE from
    // the retained payload — no fetch, and nothing else on the page moves.
    function _anRepaintXLang() {
      const host = $("an-xlang");
      if (!host || !_anLastCross) return;
      const html = _crossLangNotice(_anLastCross.cross, _anLastCross.narrowed, _anLastCross.capOff);
      if (!html) { host.outerHTML = ""; return; }
      const tmp = document.createElement("div");
      tmp.innerHTML = html;
      const next = tmp.firstElementChild;
      if (next) host.replaceWith(next);
    }

    // ONE lens, applied to EVERY request the analysis window makes -- the Articles list
    // AND each tab's own endpoint. Before this, `_articleQuery` carried the lens and the
    // insights fetches built their URLs straight from the captured params, so flipping
    // the toggle changed the Articles tab and nothing else: the two halves of one window
    // answered about different concepts while looking like one view. Q501's whole point
    // is that they cannot.
    function _anApplyLens(q) {
      // IDEMPOTENT. `loadAnalysis` applies the lens once to the params every tab reads,
      // and `_articleQuery` applies it again to its own copy -- so `sense`, which is
      // APPENDED rather than set, has to be cleared first or a second pass doubles every
      // pin and the server sees each choice twice.
      q.delete("expand"); q.delete("literal_cap"); q.delete("ui_lang"); q.delete("sense");
      // An id-seeded corpus is an exact set with no term to widen, so sending the lens
      // would offer a choice that does not exist.
      if (!q.get("query")) return q;
      if (!_anExpand) q.set("expand", "false");
      if (!_anCap) q.set("literal_cap", "false");
      const lang = (window.OOI18N && OOI18N.current) ? OOI18N.current() : "";
      if (lang) q.set("ui_lang", lang);
      // Repeatable, one per chosen term. Sending a sense with expansion off would be
      // meaningless (nothing is expanded), so it rides inside the same guard.
      if (_anExpand) {
        Object.keys(_anSenses).forEach((k) => q.append("sense", k + ":" + _anSenses[k]));
      }
      return q;
    }
    function _articleQuery(p) {
      const q = new URLSearchParams(p);
      const seeded = q.get("article_ids");
      if (seeded) { q.set("ids", seeded); q.delete("article_ids"); }
      return _anApplyLens(q);
    }
    // The lens as a SEED value: persisted with the tab and round-tripped through the URL
    // (Q504). `senses` is a small {term: ring_id} map and `expand`/`cap` are booleans, so
    // all three inline in a query string -- no need for the localStorage-token shape the
    // provenance payload uses, and a link a reader sends someone else then opens the same
    // search rather than the default one.
    function _anLensSeed() {
      return {expand: _anExpand, cap: _anCap, senses: Object.assign({}, _anSenses)};
    }
    function _anApplyLensSeed(seed) {
      const L = seed || {};
      // `!== false` rather than truthiness: a seed written before this shipped carries
      // NEITHER key, and an absent lens means the DEFAULT (both on), not "off".
      _anExpand = L.expand !== false;
      _anCap = L.cap !== false;
      _anSenses = (L.senses && typeof L.senses === "object") ? Object.assign({}, L.senses) : {};
    }
    // Q504: the lens lives in the URL as well as in the tab, so a reload, a Back and a
    // shared link all reproduce the search rather than the default. Written with
    // replaceState -- flipping a lens is not a navigation, and pushing one would make
    // Back undo a toggle instead of leaving the tab.
    function _anWriteLensToUrl() {
      try {
        const sp = new URLSearchParams(location.search);
        if (_anExpand) sp.delete("expand"); else sp.set("expand", "0");
        if (_anCap) sp.delete("cap"); else sp.set("cap", "0");
        sp.delete("sense");
        // The pins are written EVEN WITH EXPANSION OFF, and that is not the same rule as
        // `_anApplyLens`'s. The URL is STATE, the request is an ACTION: a pin is
        // meaningless to send when nothing is being expanded, but it is still the sense
        // this reader chose, and `_anLensSeed` (the tab's own persistence) keeps it
        // unconditionally. Gating it here too would leave the two persistence paths
        // disagreeing -- a reload would restore the pin and a shared link would not.
        Object.keys(_anSenses).forEach((k) => sp.append("sense", k + ":" + _anSenses[k]));
        const qs = sp.toString();
        history.replaceState(null, "", (qs ? "?" + qs : location.pathname) + location.hash);
      } catch (_e) { /* a hostile history state must never break a toggle */ }
    }
    // The other direction, and PURE (a query string -> a lens seed, or null when the URL
    // carries no lens at all). It deliberately does NOT assign the globals: a deep link's
    // lens has to become the SEED of the tab the link opens, not a setting applied beside
    // it -- otherwise `_anApplySeed` would immediately overwrite it with the new tab's
    // (absent) lens and `_anWriteLensToUrl` would erase it from the URL in the same
    // breath, which is exactly what the first version of this did.
    function _anParseLens(search) {
      const sp = new URLSearchParams(search || "");
      if (!sp.has("expand") && !sp.has("cap") && !sp.has("sense")) return null;
      const senses = {};
      // A pin is validated SERVER-side against the rings the term already belongs to
      // (a stale or hand-edited one is reported, never applied), so the only thing to
      // do here is refuse a malformed pair rather than guess at it.
      sp.getAll("sense").forEach((raw) => {
        const i = String(raw).lastIndexOf(":");
        if (i <= 0) return;
        const term = String(raw).slice(0, i).trim().toLowerCase();
        const ring = String(raw).slice(i + 1).trim();
        if (term && ring) senses[term] = ring;
      });
      return {expand: sp.get("expand") !== "0", cap: sp.get("cap") !== "0", senses};
    }
    function _anReadLensFromUrl() {
      try { return _anParseLens(location.search); } catch (_e) { return null; }
    }

    // The R1 honesty rail, rendered by default: expansion changed WHICH articles matched,
    // so the surface says so, names the concept and its per-language members, and offers
    // one click back to the literal term. PURE (payload -> html) so it can be driven in
    // node without a browser — the render is the disclosure, so it is worth testing.
    function _crossLangNotice(cross, narrowed, capOff) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (narrowed) {
        return `<div class="hint" id="an-xlang">${esc(t("Showing only the words you typed."))} `
          + `<button type="button" class="linkish" onclick="_anSetExpand(true)">`
          + `${esc(t("Search the concept in every language"))}</button></div>`;
      }
      if (!cross) {
        // The cap is a lens the READER set, so its state is known here even when the
        // payload has nothing to disclose -- and a reader who turned the limit off and
        // then searched a term that touches no ring would otherwise have no way back to
        // the default, with nothing on screen to say the lens was still on.
        if (capOff) {
          return `<div class="hint" id="an-xlang">${esc(t("Searching every form of the concept."))} `
            + `<button type="button" class="linkish" onclick="_anSetCap(true)">`
            + `${esc(t("Limit the search to the most-mentioned forms"))}</button></div>`;
        }
        return "";
      }
      // A sentence carrying a VALUE cannot be keyed as a whole (the term and the concept
      // vary), so the FRAME is a keyable {placeholder} template and the data is
      // interpolated after translation — OOI18N.tf, the composite-string discipline.
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s2, v) =>
        String(s2).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? v[k] : m));
      const langsOf = (term) => Object.entries(term.by_language || {})
        .map(([lg, words]) => `${esc(lg)}: ${esc((words || []).join(", "))}`)
        .join(" · ");
      // A pin that named a ring the term does not belong to. The search still ran, so the
      // only dishonest thing available is silence: the reader would be looking at results
      // for a concept they did not choose, believing they had chosen it.
      const missNote = (term) => (term.pinned_ring && !term.pin_applied)
        ? ` <span class="muted">${esc(t("The sense you chose is not one this word belongs to, so it was ignored."))}</span>`
        : "";
      const parts = [];
      for (const term of (cross.terms || [])) {
        if (term.pin_applied) {
          // R2a, answered: the reader picked this sense, so the sentence says so rather
          // than "also matched", which would read as something the app decided.
          parts.push(`<div>${esc(tf("{term}: searching the concept “{concept}”, which you chose",
            { term: term.term, concept: term.concept }))} — <span class="muted">${langsOf(term)}</span>`
            + ` <button type="button" class="linkish" onclick="_anClearSense(${esc(JSON.stringify(term.normalized))})">`
            + `${esc(t("Show all senses"))}</button></div>`);
        } else if (term.expanded) {
          parts.push(`<div>${esc(tf("{term} also matched as the concept “{concept}”",
            { term: term.term, concept: term.concept }))} — <span class="muted">${langsOf(term)}</span>`
            + missNote(term) + `</div>`);
        } else if (term.declined === "several-senses") {
          // The refusal is honest and, on its own, a dead end: it names the concepts and
          // leaves the reader nowhere to go. Each one is a button (R2a). The concept
          // LABEL is data -- an English identifier derived from the ring id -- so it is
          // interpolated, never keyed; only the frame around it translates.
          const picks = (term.senses || []).map((s2) =>
            `<button type="button" class="linkish"`
            + ` onclick="_anPickSense(${esc(JSON.stringify(term.normalized))}, ${esc(JSON.stringify(s2.ring_id))})">`
            + `“${esc(s2.concept)}”</button>`).join(" · ");
          parts.push(`<div>${esc(tf("{term} denotes several concepts, so it was not expanded",
            { term: term.term }))}. <span class="muted">${esc(t("Search one of them:"))}</span> ${picks}`
            + missNote(term) + `</div>`);
        } else if (term.pinned_ring) {
          // No expansion and no refusal, but a pin was sent: the term touches no ring at
          // all. Nothing else in this loop would render, so the rejected choice would
          // vanish entirely.
          parts.push(`<div>${esc(term.term)}${missNote(term)}</div>`);
        }
      }
      if (!parts.length && !capOff) return "";
      const back = cross.expanded
        ? ` <button type="button" class="linkish" onclick="_anSetExpand(false)">`
          + `${esc(t("Show only the words I typed"))}</button>`
        : "";
      // Q503's NOTE, both ways round. The payload says `capped` only when a cap actually
      // BIT -- so the sentence that offers to lift it comes from the payload, and the one
      // that offers to restore it comes from the reader's own lens, because with the cap
      // off there is nothing for the server to report. The two are never both drawn.
      let cap = "";
      if (cross.capped) {
        cap = `<div class="muted">${esc(cross.cap_caveat ? t(cross.cap_caveat) : "")} `
          + `<button type="button" class="linkish" onclick="_anSetCap(false)">`
          + `${esc(t("Search every form"))}</button></div>`;
      } else if (capOff) {
        cap = `<div class="muted">${esc(t("Searching every form of the concept."))} `
          + `<button type="button" class="linkish" onclick="_anSetCap(true)">`
          + `${esc(t("Limit the search to the most-mentioned forms"))}</button></div>`;
      }
      // Q509: how many articles each FORM matches. LAZY -- it is N counts over the corpus,
      // so it is a click, never part of the search. One trigger per expanded term, because
      // the endpoint answers about one term; `_anFormCounts` writes into the slot below it.
      const counts = (cross.terms || []).filter((x) => x.expanded).map((x) =>
        `<div class="muted" style="margin-top:4px">`
        + `<button type="button" class="linkish"`
        + ` onclick="_anFormCounts(${esc(JSON.stringify(x.term))}, ${esc(JSON.stringify(x.normalized || x.term))})"`
        + ` title="${esc(t("Counts the articles each form of the concept matches. It runs no new search on this list."))}">`
        + `${esc(t("Count each form"))}</button>`
        + `<span id="an-xforms-${esc(_anSlug(x.normalized || x.term))}"></span></div>`).join("");
      // The caveat is SERVER prose, so it goes through `t()` exactly as the Lead's own
      // caveat does in `_anRenderProvenance`. Without it the rail reads in English on a
      // page whose every other string is translated -- measured in ar/zh/ja/hi.
      const cav = cross.caveat ? t(cross.caveat) : "";
      return `<div class="hint" id="an-xlang" title="${esc(cav)}">`
        + parts.join("") + counts + cap
        + `<div class="muted">${esc(cav)}${back}</div></div>`;
    }
    // A DOM-id-safe slug for a term that may be Arabic, Japanese or hyphenated. Not a
    // hash: the id has to be reproducible from the same term on the next render, and
    // collisions only matter within one notice (a handful of terms).
    function _anSlug(s) {
      return String(s == null ? "" : s).replace(/[^a-zA-Z0-9_-]/g, (c) =>
        "u" + c.codePointAt(0).toString(36));
    }
    // PURE (payload -> html), so the sentence that carries the numbers is testable without
    // a browser. THREE things it may never do, each one a way this readout could lie:
    //   * present the per-form figures as parts of a whole -- they OVERLAP (an article
    //     carrying two forms is counted under each), so the payload's caveat travels with
    //     them and the total is labelled as the distinct count;
    //   * print a 0 for a form the server could not count -- that is a different fact, and
    //     the payload marks it `unmeasured` for exactly this reason;
    //   * let the measured list read as the whole concept when the cap bit -- so
    //     "N of M forms" is stated whenever those two numbers differ.
    function _anFormCountsHtml(d) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s2, v) =>
        String(s2).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? v[k] : m));
      if (!d || !Array.isArray(d.forms) || !d.forms.length) {
        return ` <span class="muted">${esc(t("No forms to count."))}</span>`;
      }
      // The app-wide shared formatter (the units/precision ruling), guarded the same way
      // the price chart above guards it -- these are integer article counts, so 0 decimals.
      const n = (x) => (typeof fmtNum === "function" ? fmtNum(x, 0) : String(x));
      const chips = d.forms.map((f) => (f.articles == null)
        ? `<span class="muted" title="${esc(f.unmeasured ? t(f.unmeasured) : t("This form could not be counted."))}">`
          + `${esc(f.form)} —</span>`
        : `<span>${esc(f.form)} <b>${esc(n(f.articles))}</b></span>`).join(" · ");
      let out = ` ${chips}`;
      if (d.total != null) {
        out += ` <span>· ${esc(tf("{n} articles in total, counted once each",
          { n: n(d.total) }))}</span>`;
      }
      if (d.total_forms != null && d.measured_forms != null && d.total_forms !== d.measured_forms) {
        out += ` <span class="muted">· ${esc(tf("{n} of {total} forms counted",
          { n: n(d.measured_forms), total: n(d.total_forms) }))}</span>`;
      }
      if (d.caveat) out += ` <span class="muted">${esc(t(d.caveat))}</span>`;
      return out;
    }
    async function _anFormCounts(term, key) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const q = new URLSearchParams({ term: String(term || "") });
      const lang = (window.OOI18N && OOI18N.current) ? OOI18N.current() : "";
      if (lang) q.set("ui_lang", lang);
      if (!_anCap) q.set("literal_cap", "false");
      // The counts must describe the SAME resolution the list ran, so the sense pins ride
      // along: without them a pinned term would be counted across every sense it has.
      Object.keys(_anSenses).forEach((k) => q.append("sense", k + ":" + _anSenses[k]));
      const slot = $("an-xforms-" + _anSlug(key == null ? term : key));
      if (slot) slot.innerHTML = ` <span class="muted">${esc(t("Counting…"))}</span>`;
      try {
        const d = await api("/api/insights/concept-forms?" + q.toString());
        if (slot) slot.innerHTML = _anFormCountsHtml(d);
      } catch (_e) {
        // A failed count says so. Blanking the trigger would read as "there is nothing
        // to count", which is a different answer from "it could not be counted".
        if (slot) slot.innerHTML = ` <span class="muted">${esc(t("The forms could not be counted."))}</span>`;
      }
    }
    // THE LENS NOW RE-RUNS THE WHOLE WINDOW, and the comment above `_anExpand` used to
    // say the opposite for a good reason that has since expired: the flag was a lens on
    // the ARTICLES LIST alone, so re-running the analysis would have been wasted work.
    // It now decides which articles EVERY tab describes, so re-running only the list
    // would leave the Keywords, mind map, When/Where/Who, Links, Sentiment and Sources
    // tabs answering about the previous lens with nothing on screen to say so.
    function _anRerunForLens() {
      _anSaveLensOnTab();
      _anWriteLensToUrl();
      if (_anLastParams) loadAnalysis(_anLastParams);
      else if (_anArtParams) _anLoadArticles(_anArtParams, 0);
    }
    function _anSaveLensOnTab() {
      const tb = _anTabs.find((x) => x.id === _anActiveId);
      if (tb) { tb.lens = _anLensSeed(); _anSaveTabs(); }
    }
    function _anSetExpand(on) {
      _anExpand = !!on;
      _anRerunForLens();
    }
    // Q503's NOTE: the reader turns the 40-form fan-out cap off (and back on).
    function _anSetCap(on) {
      _anCap = !!on;
      _anRerunForLens();
    }
    // Q508's NOTE: group the SAME rows by language, or leave them interleaved by date
    // (the ruled default). A VIEW, so it re-renders the list and never re-runs a search.
    function _anSetGroupByLang(on) {
      _anGroupByLang = !!on;
      if (_anArtParams) _anLoadArticles(_anArtParams, _anArtPage || 0);
    }
    // R2a: the reader picks the sense, and the pick survives paging and re-sorting
    // because it lives in the query the list rebuilds from, not in the rendered notice.
    function _anPickSense(term, ringId) {
      if (!term || !ringId) return;
      _anSenses[term] = ringId;
      _anRerunForLens();
    }
    function _anClearSense(term) {
      if (!term) return;
      delete _anSenses[term];
      _anRerunForLens();
    }

    // A sortable column header. `field` is the /api/articles sort_by value; the arrow
    // reflects the LIVE control state, so the header row is a readout of the sort as
    // well as the way to change it.
    function _anTh(field, label) {
      const sb = $("an-adv-sort"), dr = $("an-adv-dir");
      const on = sb && sb.value === field;
      const arrow = on ? ((dr && dr.value === "asc") ? " ↑" : " ↓") : "";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return `<th><button type="button" class="an-th" aria-pressed="${!!on}" `
        + `onclick="_anSortBy('${field}')" title="${esc(t("Sort by this column"))}">`
        + `${esc(label)}${arrow}</button></th>`;
    }
    // Q508: a language chip on EVERY row. PURE (article -> html) so it can be driven in
    // node. Three states, kept apart because they are three different facts:
    //   * the source ASSERTED a language -> show it plainly;
    //   * the source asserted nothing and the app DEDUCED one -> show it marked as
    //     deduced, with the caveat in the hover (the app's own reading, never the
    //     publisher's claim);
    //   * neither -> an em dash, never a guess and never a blank cell that reads as "en".
    function _anLangCell(a) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // `ooLangCell` and nothing else, unguarded, exactly as every other surface calls
      // it: Q302 says the CODE is what is displayed and the localised name is the hover,
      // and a local fallback that printed the raw value would be a second, quieter answer
      // to that question sitting beside the one the ruling names.
      if (a && a.language) return ooLangCell(a.language);
      if (a && a.detected_language) {
        return `<span class="muted" title="${esc(t("Language deduced offline — the source did not tag it."))}">`
          + `${ooLangCell(a.detected_language)} <span class="muted">${esc(t("deduced"))}</span></span>`;
      }
      return '<span class="muted">—</span>';
    }
    // The ruled DEFAULT is interleaved by date; this is the note's addition. It groups the
    // SAME rows that are already on screen -- it issues no request and changes no total,
    // so a reader flipping it can never end up looking at a different set.
    function _anGroupByLangControl() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // A SEGMENTED PAIR with stable labels, the same grammar the Trend tab's view
      // switch already uses -- not one button whose label flips. A flipping label has to
      // name the action ("Interleave by date") while `aria-pressed` describes the state,
      // so a screen reader announces "Interleave by date, pressed" about a view the
      // reader is not in. Two labelled options, each pressed or not, say the same thing
      // to both readers.
      const seg = (on, mode, label) => `<button type="button" class="ghost tiny${on ? " on" : ""}"`
        + ` aria-pressed="${on ? "true" : "false"}" onclick="_anSetGroupByLang(${mode})"`
        + ` title="${esc(t("Groups the articles already listed. It runs no new search and changes no count."))}">`
        + `${esc(label)}</button>`;
      return `<div class="row" style="gap:6px;align-items:center;margin-top:6px">`
        + `<span class="muted" style="font-size:11px">${esc(t("View"))}:</span>`
        + seg(!_anGroupByLang, "false", t("Interleave by date"))
        + seg(_anGroupByLang, "true", t("Group by language"))
        + `</div>`;
    }
    // Groups the rendered rows under one heading per language, in DESCENDING row count so
    // the reader meets the languages this corpus actually carries first, with ties broken
    // alphabetically so two runs over one corpus produce the same order.
    function _anGroupRowsByLanguage(items, rowHtml) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const buckets = new Map();
      items.forEach((a, i) => {
        // An article whose language is neither asserted nor deduced gets its OWN bucket
        // rather than being filed under a plausible one -- the grouped view must not
        // invent a language the row itself refuses to claim.
        const key = (a && a.language) || (a && a.detected_language) || "";
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(rowHtml[i]);
      });
      const order = [...buckets.keys()].sort((x, y) => {
        const d = buckets.get(y).length - buckets.get(x).length;
        return d !== 0 ? d : String(x).localeCompare(String(y));
      });
      return order.map((k) => {
        const n = buckets.get(k).length;
        const label = k ? ooLangCell(k) : `<span class="muted">${esc(t("Language not recorded"))}</span>`;
        return `<tr class="an-lang-group"><td colspan="5"><b>${label}</b>`
          + ` <span class="muted">${esc(t("{n} articles").replace("{n}", n))}</span></td></tr>`
          + buckets.get(k).join("");
      }).join("");
    }

    async function _anLoadArticles(p, page) {
      // The list renders into an-art-list, INSIDE an-articles -- the sort bar above it
      // is static markup and must survive a re-render (it is what triggered this one).
      const arts = $("an-art-list") || $("an-articles"); if (!arts) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      _anArtParams = p; _anArtPage = Math.max(0, page | 0);
      arts.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const q = _articleQuery(p);
        q.set("limit", String(_AN_ART_PAGE));
        q.set("offset", String(_anArtPage * _AN_ART_PAGE));
        if (_anProvenance) q.set("provenance", _anProvenance);
        // Read the sort from the controls rather than from the captured params: `p` was
        // snapshotted when the corpus loaded, so a params-only read would order by
        // whatever was chosen THEN and silently ignore the header just clicked.
        const _sb = $("an-adv-sort") && $("an-adv-sort").value;
        if (_sb) { q.set("sort_by", _sb); q.set("sort_dir", ($("an-adv-dir") && $("an-adv-dir").value) || "desc"); }
        else { q.delete("sort_by"); q.delete("sort_dir"); }
        if (_anKwSort) { q.set("sort_by", "keyword_count"); q.set("sort_dir", "desc"); }
        const d = await api("/api/articles?" + q.toString());
        _anKwForCount = d.keyword_for_count || "";
        if (!_anKwForCount) _anKwSort = false;   // no keyword resolved -> no count sort
        const kwc = _anKwForCount;
        const total = d.total || 0, pages = Math.max(1, Math.ceil(total / _AN_ART_PAGE));
        if (_anArtPage > pages - 1) return _anLoadArticles(p, pages - 1);   // clamp after a narrower filter
        const rowHtml = (d.results || []).map((a) => {
          // Small, discrete per-article keyword count beside the title (counts only).
          const badge = (kwc && a.keyword_count != null)
            ? ` <span class="muted" style="font-size:.82em" title="${esc(t("Mentions of") + " “" + kwc + "” " + t("in this article"))}">×${a.keyword_count}</span>`
            : "";
          // The article's OWN top keyword (ruling 23/38/39), precomputed at index time.
          // A tie is SHOWN as a tie: several keywords share that count and the one named
          // is the lowest-id among them, so calling it "the" top keyword would assert a
          // ranking the count never made. An article the re-index has not reached yet has
          // no value at all -- rendered as an em dash, never as a 0, which would read as
          // "measured, and it has no keywords".
          let top = '<span class="muted">—</span>';
          if (a.top_keyword) {
            const tied = (a.top_keyword_tied_n || 1) > 1;
            const tip = tied
              ? t("{n} keywords are tied at this count in this article — this is one of them, not a winner.").replace("{n}", a.top_keyword_tied_n)
              : t("This article's most-mentioned keyword, counted when it was indexed.");
            top = `<span title="${esc(tip)}">${esc(a.top_keyword)}`
              + ` <span class="muted">×${a.top_keyword_count}</span>`
              + (tied ? ` <span class="muted">${esc(t("tied"))}</span>` : "")
              + `</span>`;
          }
          return `<tr data-aid="${a.id}"><td><a href="/api/articles/${a.id}/view" target="_blank" rel="noopener">`
          + `${esc(a.title) || '<span class="muted">(untitled)</span>'}</a>${badge}</td>`
          // `_toneChip`, not `_anToneChip`: the Language column below now carries the
          // deduced-language half, and the split exists precisely so a surface that
          // already shows the language renders the tone without repeating it.
          + `<td>${esc(a.source || "")}${_toneChip(a)}</td>`
          + `<td>${_anLangCell(a)}</td>`
          + `<td class="muted">${esc((a.published_at || "").slice(0, 10))}</td>`
          + `<td>${top}</td></tr>`;
        });
        const rows = _anGroupByLang ? _anGroupRowsByLanguage(d.results || [], rowHtml) : rowHtml.join("");
        const pager = _anArtPager(total, pages);
        // RULING 22: the "source ↗" column and the per-row Summarize / Translate buttons
        // are gone -- the reader carries both (its "Original source:" line shows the FULL
        // url, and its Summary / Translation tabs run the same local model on the same
        // article), so this is an absorption, not a removal. Nothing was lost: the bulk
        // Summarize all / Translate all actions are untouched in the export bar below.
        // Retained so a LANGUAGE SWITCH can redraw the rail without re-running the
        // search: the rail's text is derived at render time (a tf() frame plus server
        // prose through t()), so the i18n DOM walker cannot reach it and it would
        // otherwise stay frozen in whichever locale painted it first -- the recorded
        // frozen-locale class, of which this would have been the next member.
        _anLastCross = {cross: d.cross_language || null,
                        narrowed: !_anExpand && !!q.get("query"),
                        capOff: !_anCap && !!q.get("query")};
        arts.innerHTML = _anArtControls(d)
          + _crossLangNotice(d.cross_language, !_anExpand && !!q.get("query"), !_anCap && !!q.get("query"))
          + `<div id="an-art-facets"></div>`
          // `an-art-total` is the ONE number a reader takes away from this list, and it
          // had no anchor: a walk trying to read it had to guess which `.hint` on the
          // surface it was, and the expansion rail above carries that class too.
          + `<div class="hint" id="an-art-total"><b>${total.toLocaleString()}</b> ${esc(t("Articles"))} <span class="muted">· ${esc(t("Open an article to read it, see its original source, and summarize or translate it."))}</span></div>`
          + pager
          + _anGroupByLangControl()
          + `<table style="margin-top:6px"><tr>`
          + _anTh("title", t("Title")) + _anTh("source", t("Source"))
          + _anTh("language", t("Language"))
          + _anTh("date", t("Published")) + _anTh("top_keyword", t("Top keyword"))
          + `</tr>${rows}</table>`
          + pager;
        annotateArticleDups(p, arts);   // inline "1 voice" near-dup badges (non-blocking, PR 3)
        _anRenderArtFacetChips();   // redraw from already-fetched facet data (sync, no network)
      } catch (e) {
        // Same honest, rate-limit-aware message as the Search tab (search-lockout
        // fix) -- this subtab hits the SAME /api/articles endpoint, including from a
        // boot-time deep link (?corpus=/?analyze=, app-boot.js._hydrateCardCorpus),
        // so a refusal here deserves the same disclosure, not a bare exception string.
        arts.innerHTML = `<div class="note err">${esc(_articleFailureMessage(e))}</div>`;
      }
    }
    // The catalogue cell of the analysis window's Sources table, as a PURE function of
    // one row -- extracted so it can be executed in a test rather than only grepped.
    //
    // REGION AND TAGS COMPLETE THE COLUMN (2026-09-09, second pass). The first pass at
    // this gap named "country / region / language / type / tags" as what the retired
    // #corpus-win modal showed, and then shipped three of the five. Both missing fields
    // were already on the row -- corpus_sources selects Source.region and Source.tags
    // beside the rest -- so the loss was in the renderer alone. A half-closed gap is the
    // harder kind to notice the second time, which is why this is now executable: a
    // source-text guard for "tags are rendered" passes against code that reads s.tags
    // and discards it.
    //
    // TWO-CLASS HONESTY: every field here is catalogue/source-ASSERTED (set from the
    // catalogue, a ccTLD, or the operator), never deduced from the article text. A
    // source the catalogue holds nothing for reads as an em dash, never as an empty
    // claim.
    function _anSourceCatalogHtml(s) {
      s = s || {};
      const facts = [
        s.country ? (typeof ooRegionName === "function"
          ? ooRegionName(s.country) : s.country) : null,
        s.region || null,
        s.language ? (typeof ooLangName === "function"
          ? ooLangName(s.language) : s.language) : null,
        s.source_type || null,
      ].filter(Boolean).join(" \u00b7 ");
      const tags = (s.tags && s.tags.length)
        ? s.tags.map((x) => `<span class="pill" style="font-size:11px">${esc(x)}</span>`).join(" ")
        : "";
      if (!facts && !tags) return "\u2014";
      return (facts ? esc(facts) : "")
        + (tags ? `<div style="margin-top:3px">${tags}</div>` : "");
    }
    async function loadAnalysis(p) {
      // ...and the lazy subtabs hold until this run has params of its own (see
      // `anSelectTab`). Nulled BEFORE the await below, so the window in which a click
      // could reach the previous corpus' params does not exist.
      _anLastParams = null;
      // THE BOOT RACE, measured in Chromium (2026-09-17): walking straight to an analysis
      // deep link in `hi` rendered the expansion rail's frame in ENGLISH while ar, zh and
      // ja came out translated — the analysis fetch simply beat the locale fetch, and
      // which locale loses is a matter of file size and timing. `OOI18N.ready` is the
      // promise this project added for exactly this, and it is a promise rather than an
      // event so that asking late still works.
      //
      // IT WAITS FIRST, BEFORE ANYTHING READS THE LOCALE. The wait originally sat a few
      // lines lower, which fixed the frame text it was written for and left the two
      // readers ABOVE it unguarded: `t` captured the fallback, and -- the one that
      // reaches the server -- `_anApplyLens` read `OOI18N.current()` too early and built
      // the params for EVERY tab with no `ui_lang`. The second Chromium walk caught it as
      // `hi` issuing the trend request TWICE (once bare, once with the locale) where the
      // other four locales issued it once: the reader's first chart described a
      // resolution computed without their language, and a repaint quietly replaced it.
      try { if (window.OOI18N && OOI18N.ready) await OOI18N.ready; } catch (_e) { /* never block a render */ }
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // Q501/Q516: apply the lens ONCE, here, to the params EVERY tab below reads -- the
      // keywords chips, the mind map's graph, When/Where/Who, Links, Sentiment, Sources
      // and the lazy Trend/Related/Competitive renderers that read `_anLastParams`.
      // Before this the lens travelled only through `_articleQuery`, so flipping the
      // toggle changed the Articles tab and left every other tab describing a different
      // concept while looking like one view.
      p = _anApplyLens(new URLSearchParams(p));
      const kw = $("an-keywords"), arts = $("an-art-list") || $("an-articles");
      kw.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      arts.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      _anProvenance = ""; _anKwSort = false; _anKwForCount = "";   // fresh corpus -> reset the Articles-list lenses
      _anArtFacetSel = { source: "", language: "" };   // fresh corpus -> reset the staged facet selection too
      _anLastParams = p; _anTrend.key = null; _anRelated.key = null; _anCompetitive.key = null;   // a new analysis run -> the lazy subtabs refetch on next show
      if ($("an-trend") && $("an-trend").style.display !== "none") setTimeout(() => renderAnTrend(p), 0);
      if ($("an-related") && $("an-related").style.display !== "none") setTimeout(() => renderAnRelated(p), 0);
      if ($("an-competitive") && $("an-competitive").style.display !== "none") setTimeout(() => renderAnCompetitive(p), 0);
      _toggleAnPrice();   // commodity overlay: show + render the Price subtab, or hide it
      try {
        const d = await api("/api/insights/corpus-keywords?" + p.toString() + tgtLangParam());
        _anKwData = d; _anKwHost = kw;   // stash for the tentative-fill action
        anRenderKwChips();
        loadAnContext(p);   // S4.4: term-in-context concordance under the chips (progressive)
      } catch (e) { kw.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Mindmap: a deterministic radial keyword-association graph seeded on the
      // TOP keyword of the matched set (KEYWORDS ARE CORPORA). Self-contained
      // renderer — never touches the Insights mind-map state. Window params pass
      // through (the /graph endpoint accepts start/end/days, like _mmWindowQS).
      const mm = $("an-mindmap");
      mm.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const dk = await api("/api/insights/corpus-keywords?" + p.toString());
        const top = (dk.terms && dk.terms.length) ? dk.terms[0].term : null;
        if (!top) {
          mm.innerHTML = `<div class="muted">${esc(t("No strong associations yet."))}</div>`;
        } else {
          // an-mindmap-wrong-corpus-scope (P1): clone the analysis window's OWN scope
          // (article_ids, or query/source/language/date-range) instead of a fresh,
          // scope-less params object — else the mindmap silently reverted to a
          // corpus-wide keyword graph for every seeded/searched analysis.
          const gp = new URLSearchParams(p);
          gp.set("level", "keyword"); gp.set("term", top); gp.set("hops", "2");
          // Q512: the Concept view's own payload, fetched beside the graph and keyed on
          // the TYPED term rather than on the corpus's top keyword -- "the ring" means
          // the ring of the word the reader searched, not of whatever happens to be
          // most frequent in the result set. Best-effort: the map still draws without it,
          // and the Concept button simply does not appear.
          const _ct = (p.get && p.get("query")) || top;
          const cq = new URLSearchParams({ term: String(_ct) });
          ["ui_lang", "literal_cap"].forEach((k) => {
            const v = p.get(k); if (v != null) cq.set(k, v);
          });
          (p.getAll ? p.getAll("sense") : []).forEach((v) => cq.append("sense", v));
          const [g, cm] = await Promise.all([
            api("/api/insights/graph?" + gp.toString()),
            api("/api/insights/concept-map?" + cq.toString()).catch(() => null),
          ]);
          _anMM.arms = cm;
          renderAnMindmap(g, mm);
        }
      } catch (e) { mm.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      _anLoadArticles(p, 0);   // paginated Articles list — Prev/Next + "Page X of Y", above + below
      _anLoadArtFacets(p);   // sources/languages present in this corpus, with counts (item 3 facet controls)
      // When/Where/Who deduced across the matched articles, as CLICKABLE FACETS:
      // clicking a value narrows the corpus to the articles that mention it (the drill
      // that makes a facet co-equal with the text query). Counts only, never confirmed.
      try {
        const d = await api("/api/insights/corpus-www?" + p.toString());
        _anFacets = {
          who: ((d.who && d.who.entities) || []).map((e) => ({
            facet: "entity", value: e.name, label: e.name,
            sub: e.class || "", n: e.articles})),
          where: ((d.where && d.where.places) || []).map((pl) => ({
            facet: "place", value: pl.name, label: pl.name,
            sub: pl.country ? ooCountryCode(pl.country) : "", n: pl.articles})),
          when: ((d.when && d.when.years) || []).map((yr) => ({
            facet: "when", value: String(yr.year), label: String(yr.year),
            sub: "", n: yr.articles})),
        };
        const chips = (group) => {
          const items = _anFacets[group];
          if (!items.length) return `<span class="muted">—</span>`;
          return items.map((it, i) =>
            `<button type="button" class="chip an-facet" onclick="branchByFacet('${group}',${i})" `
            + `title="${esc(t("Narrow the corpus to articles that mention this") + " — " + it.value)}">`
            + `${esc(it.label)}${it.sub ? ` <span class="muted">(${esc(it.sub)})</span>` : ""}`
            + ` <span class="muted">· ${it.n}</span></button>`).join(" ");
        };
        const col = (title, group) =>
          `<div style="min-width:200px;flex:1"><div class="vsect">${esc(title)}</div>`
          + `<div class="an-facet-row" style="display:flex;flex-wrap:wrap;gap:6px;margin:4px 0">`
          + `${chips(group)}</div></div>`;
        $("an-www").innerHTML =
          `<div class="hint muted">${esc(d.caveat || "")} `
          + `${esc(t("Click a value to narrow the corpus to articles that mention it."))}</div>`
          + `<div style="display:flex;gap:28px;flex-wrap:wrap;margin-top:8px">`
          + col(t("Who"), "who") + col(t("Where"), "where") + col(t("When"), "when") + `</div>`;
      } catch (e) { $("an-www").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Links: outbound URLs SHARED by 2+ of the matched articles (shared-origin
      // structure; convergence is corroboration only when paths are independent).
      try {
        const d = await api("/api/links/corpus?" + p.toString());
        // THE INDEPENDENCE READOUT, per row. The retired #corpus-win modal showed a
        // distinct-SOURCE count beside the distinct-ARTICLE count and said, for each
        // link, which of the two situations it was in; this view showed the article
        // count alone under one blanket caveat, which reads the same for five articles
        // from one outlet as for five from five. That is the difference between echo
        // and corroboration, so it is stated per link, in the reader's language, from
        // the endpoint's machine-readable verdict rather than from server prose.
        const indep = (it) => it.independence === "distinct_sources"
          ? `<span class="pill" title="${esc(t("Every citing article comes from a different outlet, so the citations are as many paths as they appear to be. They may still share an upstream origin this view cannot see."))}">${esc(t("distinct outlets"))}</span>`
          : `<span class="pill warn" title="${esc(t("The citing articles do not come from as many outlets as there are citations — one outlet cites this page more than once, or only one outlet does. Their agreement is one path, not independent confirmation."))}">${esc(t("one path"))}</span>`;
        const rows = (d.items || []).map((it) =>
          `<tr><td>${extLink(it.sample_url || it.normalized_url, esc(it.domain || it.link_text || it.normalized_url), "", "")}</td>`
          + `<td style="text-align:right;font-variant-numeric:tabular-nums">${it.citations}</td>`
          + `<td style="text-align:right;font-variant-numeric:tabular-nums">${it.citing_sources}</td>`
          + `<td>${indep(it)}</td></tr>`).join("");
        $("an-links").innerHTML = `<div class="hint muted">${esc(d.caveat || "")}</div>`
          + (rows
            ? `<table class="data" style="margin-top:8px"><thead><tr><th>${esc(t("Link"))}</th>`
              + `<th style="text-align:right" title="${esc(t("How many distinct matched articles cite this link — an exact count, never a score."))}">${esc(t("Cited by"))}</th>`
              + `<th style="text-align:right" title="${esc(t("How many distinct sources those citing articles come from. This is the ceiling on how many independent paths the citations could represent."))}">${esc(t("Citing sources"))}</th>`
              + `<th title="${esc(t("Whether the citations come from as many outlets as there are citations. Structure only — never a credibility judgement."))}">${esc(t("Independence"))}</th></tr></thead><tbody>${rows}</tbody></table>`
            : `<div class="muted" style="margin-top:8px">${esc(t("No links shared by 2+ matched articles."))}</div>`);
      } catch (e) { $("an-links").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Sentiment: distribution of the STORED per-article VADER tone over the set,
      // with the English-lexicon limitation disclosed (non-English scores unreliable).
      try {
        const d = await api("/api/insights/corpus-sentiment?" + p.toString());
        const cav = `<div class="hint muted">${esc(d.caveat || "")}</div>`;
        if (!d.n_scored) {
          $("an-sentiment").innerHTML = cav
            + `<div class="muted" style="margin-top:8px">${esc(t("No tone scores in this set."))}</div>`;
        } else {
          const lab = d.labels || {};
          const LK = { positive: "Positive", neutral: "Neutral", negative: "Negative" };
          const keys = ["positive", "neutral", "negative"].filter((k) => k in lab)
            .concat(Object.keys(lab).filter((k) => !(k in LK)));
          const rows = keys.map((k) => {
            const pct = Math.round((100 * lab[k]) / d.n_scored);
            return `<div style="display:flex;justify-content:space-between;max-width:320px">`
              + `<span>${esc(LK[k] ? t(LK[k]) : k)}</span><span class="muted">${lab[k]} · ${pct}%</span></div>`;
          }).join("");
          const engPct = Math.round((100 * d.english_scored) / d.n_scored);
          $("an-sentiment").innerHTML = cav + `<div style="margin-top:8px">${rows}</div>`
            + `<div class="muted" style="margin-top:8px">${esc(t("Mean tone"))}: ${d.mean_score}`
            + ` · n=${d.n_scored}/${d.n_articles} · ${esc(t("English-scored (reliable)"))}: ${d.english_scored} (${engPct}%)</div>`;
        }
      } catch (e) { $("an-sentiment").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
      // Sources: how each source covers the matched set -- volume, mean tone, span,
      // and the catalogue facts the source ASSERTS about itself.
      // Coverage, never credibility; no ranking (ordered by volume only).
      //
      // THE CATALOGUE COLUMN CLOSES AN ABSORPTION GAP (2026-09-09). index.html's
      // retirement note says every subtab of the retired #corpus-win modal is
      // "covered by the ONE #an window (a strict superset)". For Sources it was
      // not: the modal's version showed each source's country / region / language
      // / type / tags, and this one showed name, volume, tone and span only. So a
      // capability the consolidation promised to keep was quietly dropped.
      // It costs no extra request -- corpus_sources() already joins Source and
      // groups by Source.id, so the fields ride on the row it had already read.
      // TWO-CLASS HONESTY, unchanged from the modal: every field here is
      // catalog/source-ASSERTED (set from the catalogue, a ccTLD, or the
      // operator), never deduced from the text, and a source the catalogue holds
      // nothing for reads as an em dash rather than as an empty claim.
      try {
        const d = await api("/api/insights/corpus-sources?" + p.toString());
        const rows = (d.sources || []).map((s) => {
          const span = (s.first && s.last) ? `${String(s.first).slice(0, 10)} – ${String(s.last).slice(0, 10)}` : "—";
          const tone = (s.mean_tone === null || s.mean_tone === undefined) ? "—" : s.mean_tone;
          return `<tr><td>${esc(s.name || s.domain || "")}</td>`
            + `<td style="text-align:right;font-variant-numeric:tabular-nums">${s.articles}</td>`
            + `<td style="text-align:right;font-variant-numeric:tabular-nums">${tone}</td>`
            + `<td class="muted">${esc(span)}</td>`
            + `<td class="muted">${_anSourceCatalogHtml(s)}</td></tr>`;
        }).join("");
        $("an-sources").innerHTML = `<div class="hint muted">${esc(d.caveat || "")}</div>`
          + (rows
            ? `<table class="data" style="margin-top:8px"><thead><tr><th>${esc(t("Source"))}</th>`
              + `<th style="text-align:right">${esc(t("Articles"))}</th>`
              + `<th style="text-align:right">${esc(t("Mean tone"))}</th><th>${esc(t("Span"))}</th>`
              + `<th title="${esc(t("Stated by the source catalog (asserted, not deduced from text)."))}">${esc(t("Catalog"))}</th></tr></thead>`
              + `<tbody>${rows}</tbody></table>`
            : `<div class="muted" style="margin-top:8px">${esc(t("No sources in this set."))}</div>`);
      } catch (e) { $("an-sources").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }

    // Source-competitive subtab — ported from the retired #corpus-win modal into the
    // #an flagship (batch F item 4, the ONE capability the modal had that #an lacked;
    // absorption so the two-window consolidation loses nothing). How each source
    // APPROACHES this corpus, side by side: VOLUME (exact article count) + TONE (VADER
    // mean/label) + TIMING (first→last span) from /api/insights/corpus-sources (scoped
    // to the #an corpus, article_ids OR query, via _resolve_corpus) + distinctive
    // EMPHASIS terms from /api/framing (query-only, so shown when a query defines the
    // corpus and honestly absent for an article-set corpus — never wrong data). Rows
    // are ordered by volume ONLY — a DESCRIPTIVE comparison of divergence, never a
    // ranking, a winner or a composite score. Tone carries the VADER English-only
    // disclosure. n=1 ⇒ "nothing to compare". Lazy (rendered on show), cached per
    // corpus. Reuses EXISTING endpoints — no new backend.
    async function renderAnCompetitive(p) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("an-competitive"); if (!host) return;
      p = p || _anLastParams;
      if (!p) { host.innerHTML = `<div class="muted">${esc(t("Open the analysis from a keyword or a search first."))}</div>`; return; }
      const key = p.toString();
      if (_anCompetitive.key === key) return;   // already rendered for this corpus
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      const query = p.get("query");   // framing is query-only; absent for an article-set corpus
      let cs, fr;
      try {
        [cs, fr] = await Promise.all([
          api("/api/insights/corpus-sources?" + p.toString() + "&limit=200"),
          query ? api("/api/framing?query=" + encodeURIComponent(query)).catch(() => null) : Promise.resolve(null),
        ]);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const rows = (cs && cs.sources) || [];
      if (!rows.length) { host.innerHTML = `<div class="muted">${esc(t("No sources for this corpus yet."))}</div>`; _anCompetitive.key = key; return; }
      if (rows.length === 1) { host.innerHTML = `<div class="muted">${esc(t("Only one source in this corpus — nothing to compare."))}</div>`; _anCompetitive.key = key; return; }
      const byName = {}; ((fr && fr.framing) || []).forEach(f => { if (f.source) byName[f.source] = f; });
      const fmt = (n) => (n || 0).toLocaleString();
      const firsts = rows.map(r => r.first).filter(Boolean).sort();
      const lasts = rows.map(r => r.last).filter(Boolean).sort();
      const corpusFirst = firsts[0] || null, corpusLast = lasts[lasts.length - 1] || null;
      const day = (s) => (s || "").slice(0, 10);
      const tonePill = (label, val) => {
        if (val == null) return `<span class="muted">—</span>`;
        const cls = label === "positive" ? "ok" : label === "negative" ? "err" : "";
        const lab = label === "positive" ? t("Positive") : label === "negative" ? t("Negative")
          : label === "neutral" ? t("Neutral") : (label || "");
        return `<span class="pill ${cls}">${esc(lab)} ${val.toFixed(2)}</span>`;
      };
      const chips = (arr) => (arr || []).slice(0, 6).filter(Boolean)
        .map(x => `<span class="pill" style="font-size:11px">${esc(x)}</span>`).join(" ");
      const notRanking = t("Descriptive comparison — how these sources DIFFER, never a ranking or a credibility judgement. Rows are ordered by volume only (most-covering first); there is no winner and no composite score.");
      const emphasisNA = query ? (fr ? t("No distinctive terms.") : t("Needs the [analysis] extra."))
        : t("Distinctive terms need a keyword/search corpus (not an article set).");
      const body = rows.map(r => {
        const f = byName[r.name] || {};
        const emphasis = (f.top_terms && f.top_terms.length) ? chips(f.top_terms)
          : `<span class="muted" style="font-size:12px">${esc(emphasisNA)}</span>`;
        // real value, never invented -- and never the WRONG denominator: see the sibling
        // renderer above. A framing row that honestly reports no tone renders the em-dash
        // rather than borrowing corpus-sources' whole-set mean.
        const hasFraming = Object.prototype.hasOwnProperty.call(byName, r.name);
        const toneVal = (f.avg_tone != null) ? f.avg_tone : (hasFraming ? null : r.mean_tone);
        const toneLbl = f.tone_label || null;
        const span = (r.first && r.last) ? `${esc(day(r.first))} → ${esc(day(r.last))}` : `<span class="muted">—</span>`;
        return `<tr style="border-bottom:1px solid var(--line)">
          <td style="padding:5px 8px"><b style="font-size:13px">${esc(r.name || r.domain || "—")}</b>${r.domain ? `<div class="muted" style="font-size:11px">${esc(r.domain)}</div>` : ""}</td>
          <td style="text-align:right;padding:5px 8px">${fmt(r.articles)}</td>
          <td style="padding:5px 8px">${tonePill(toneLbl, toneVal)}</td>
          <td style="padding:5px 8px;white-space:nowrap;font-size:12px">${span}</td>
          <td style="padding:5px 8px">${emphasis}</td>
        </tr>`;
      }).join("");
      host.innerHTML =
        `<div class="hint" title="${esc(t("How each source APPROACHES this concept, side by side: volume (exact article count), tone (VADER mean + label), timing (first→last publication span) and the outlet's distinctive emphasised terms. A microscope on divergence, not a verdict — no source is ranked above another, no quality is judged, no composite score is computed."))}">${esc(notRanking)}</div>` +
        `<table style="width:100%;border-collapse:collapse;font-size:13px">
           <thead><tr style="border-bottom:1px solid var(--line)">
             <th style="text-align:start;padding:5px 8px">${esc(t("Source"))}</th>
             <th style="text-align:right;padding:5px 8px" title="${esc(t("How many articles in this corpus come from this source — an exact count, never a score."))}">${esc(t("Volume"))}</th>
             <th style="text-align:start;padding:5px 8px" title="${esc(t("Mean VADER tone for this source's coverage, with the label. VADER is an ENGLISH-lexicon method — tone for non-English coverage is unreliable or absent. A real value, never a verdict."))}">${esc(t("Tone"))} <span class="muted" style="font-weight:normal">${esc(t("(VADER tone)"))}</span></th>
             <th style="text-align:start;padding:5px 8px" title="${esc(t("The first → last publication date for this source's coverage in the corpus — real dates, never a score."))}">${esc(t("Timing"))}</th>
             <th style="text-align:start;padding:5px 8px" title="${esc(t("This outlet's most distinctive terms when covering the concept (from framing). Descriptive emphasis, not a judgement."))}">${esc(t("Emphasis"))}</th>
           </tr></thead>
           <tbody>${body}</tbody>
         </table>` +
        `<div class="hint" style="margin-top:6px">${esc(t("n ="))} ${fmt(cs.n_articles)} ${esc(t("articles"))}` +
          `${(corpusFirst && corpusLast) ? ` · ${esc(day(corpusFirst))} → ${esc(day(corpusLast))}` : ""}` +
          `${cs.capped ? ` · ${esc(t("(scoped to the top matched articles)"))}` : ""}. ` +
          `${esc(cs.caveat || "")} ${esc((fr && fr.caveat) || "")}</div>`;
      _anCompetitive.key = key;   // cache AFTER a successful render (retry on error)
    }

    // === Search-lockout fix (audit P0 finding 3) ============================= //
    // GET /api/articles is rate-limited to 100/hour and this is the app's densest,
    // most iterative surface (135 controls, 5 inputs, boolean query grammar, five
    // time-range presets) -- built for exactly the refinement pattern that burns the
    // budget. Before this fix a refusal here rendered as an EMPTY search: the results
    // table and the "N result(s)" line were left untouched (blank, on a first search,
    // or simply stale) and the only signal was a toast that auto-dismisses in a few
    // seconds -- leaving a state indistinguishable from a real zero-result query, and
    // one that stays indistinguishable forever if the tab is left open or reloaded
    // after the toast is gone. Fail closed, never open: a failed search must say so,
    // and keep saying so, exactly where a real result would have appeared. Shared by
    // every /api/articles-driven surface in this file (the Search tab here, and the
    // analysis window's Articles subtab below) so the message is the same wherever
    // this exact backend call can be refused.
    function _searchRetryAfterSeconds(e) {
      // An optional Retry-After hint, IF a caller has attached one to the thrown
      // error. This file does not own app-core.js's api() (a sibling fix does) and
      // cannot pin its exact contract, so every plausible shape is tried and absence
      // is honest silence -- never a fabricated wait (CLAUDE.md: never invent a
      // countdown you do not have; if you only know "later", say only that).
      if (!e) return null;
      const detail = e.detail;
      const cands = [e.retryAfter, e.retry_after, e.retryAfterSeconds,
        (detail && typeof detail === "object") ? detail.retry_after : null,
        (detail && typeof detail === "object") ? detail.retryAfter : null];
      for (const c of cands) {
        const n = Number(c);
        if (isFinite(n) && n >= 0) return n;
      }
      return null;
    }
    function _isRateLimited(e) { return !!(e && e.status === 429); }
    // ONE translatable message for a failed article search, wherever it renders. An
    // EXACT known wait (a real server Retry-After) is stated as a clock time, computed
    // once at render time -- never a live-ticking countdown, and never a guess when no
    // Retry-After is present (then the message says only "later").
    function _articleFailureMessage(e) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf
        : ((s, v) => s.replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)));
      if (_isRateLimited(e)) {
        const secs = _searchRetryAfterSeconds(e);
        if (secs != null && secs > 0) {
          const when = new Date(Date.now() + secs * 1000);
          return tf(t("Search has hit its rate limit — try again after {time}."), { time: when.toLocaleTimeString() });
        }
        return t("Search has hit its rate limit. Try again later.");
      }
      return tf(t("Search failed: {error}"), { error: (e && e.message) || String(e) });
    }
    async function doSearch() {
      // Through _articleQuery like every other /api/articles caller. The Search tab never
      // carries an id-seeded corpus, so this is a no-op here -- but making the rule
      // uniform means there is no exception to remember, which is what let the analysis
      // tab drift in the first place.
      const p = _articleQuery(searchParams()); p.set("limit", String(DEFAULT_LIMIT));
      try {
        const data = await api("/api/articles?" + p.toString());
        $("search-meta").textContent = `${data.total} result(s)` + (data.total > data.results.length ?
          ` (showing ${data.results.length})` : "");
        const t = $("results");
        t.innerHTML = "<tr><th>Title</th><th>Source</th><th>Published</th><th>Lang</th><th></th></tr>" +
          (data.results.length ? data.results.map(a =>
            `<tr><td><div>${esc(a.title) || '<span class="muted">(untitled)</span>'}</div>
                 <div class="muted" style="font-size:12px">${esc((a.content||"").slice(0,160))}…</div></td>
             <td>${esc(a.source)}${_anToneChip(a)}</td><td class="muted">${esc((a.published_at||"").slice(0,10))}</td>
             <td>${ooLangCell(a.language)}</td>
             <td><a href="/api/articles/${a.id}/view" target="_blank" rel="noopener" title="offline stored copy">open</a>
                 ${a.url ? `· ${extLink(a.url, "source ↗", "muted")}` : ""}
                 <button class="secondary tiny" style="margin-top:4px"
                   onclick="summarize(${a.id}, this)">Summarize</button>
                 <button class="secondary tiny" style="margin-top:4px"
                   onclick="translateArticle(${a.id}, this)">Translate</button>
                 <div class="summary muted" style="font-size:12px;margin-top:4px"></div></td></tr>`
          ).join("") : `<tr><td colspan="5" class="muted">No matches.</td></tr>`);
        annotateArticleDups(p, t);   // inline "1 voice" near-dup badges (non-blocking, reuses the helper)
      } catch (e) {
        // PERSISTENT, honest failure state -- rendered into the exact two spots a
        // successful search fills, so it survives exactly as long as a real result
        // would (unlike the toast below, which is a transient echo of the same fact,
        // kept for the reader who is looking at the toast tray when it happens).
        const msg = _articleFailureMessage(e);
        const meta = $("search-meta"); if (meta) meta.textContent = msg;
        const t = $("results");
        if (t) t.innerHTML = "<tr><th>Title</th><th>Source</th><th>Published</th><th>Lang</th><th></th></tr>"
          + `<tr><td colspan="5" class="note err">${esc(msg)}</td></tr>`;
        toast(_failMsg("Search failed: {error}", e), "err");
      }
    }

    function exportResults(fmt, p) {
      // Through _articleQuery, so an id-seeded corpus exports THAT corpus. Without it the
      // export dropped the selection and wrote every article the reader holds -- a
      // "download the matched articles" button that quietly handed over the whole corpus.
      const params = _articleQuery(p || searchParams());
      params.set("format", fmt);
      window.open("/api/articles/export?" + params.toString(), "_blank");
    }

    // --- Synthesis window (maintainer 2026-06-21) ----------------------------- //
    // "Synthesize results" opens a roomy, article-style WINDOW. Step 1 makes the member
    // selection TRANSPARENT (which articles, of how many, by search relevance) and lets
    // the user pick exactly which to include — no silent "top 20" truncation. Step 2
    // shows the synthesis + caveat + provenance + the FULL corpus of synthesized
    // articles WITH metadata, plus export (.md / standalone page) + copy. The synthesis
    // is written in the UI language (the backend appends a native-language directive +
    // a robust "synthesize ALL excerpts" prompt so a weak model no longer bails).
    const _SYNTH_MAX = 20;        // mirrors the backend bound (small-CPU-model context)
    let _synthData = null;        // last result, for export/copy
    let _synthCandidates = null;  // {params, total, results} for the selection step
    const _synthT = () => ((window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s));

    function _synthCandidateParams(arg) {
      // arg: a URLSearchParams (analysis window) | a query string | null (search tab).
      if (arg instanceof URLSearchParams) return arg;
      if (arg != null) { const p = new URLSearchParams(); const q = (arg || "").trim(); if (q) p.set("query", q); return p; }
      return searchParams();   // search tab: respect query + active filters
    }
    async function synthesizeResults(btn, arg) {
      const t = _synthT();
      const p = _synthCandidateParams(arg);
      const hasSel = p.get("query") || p.get("source") || p.get("language")
        || p.get("start_date") || p.get("end_date") || p.get("article_ids");
      if (!hasSel) { toast(t("Run a search first."), "err"); return; }
      const dlg = $("synth-window"); if (!dlg) return;
      $("synth-win-actions").innerHTML = "";
      $("synth-win-title").textContent = t("Synthesis");
      $("synth-win-body").innerHTML = `<p class="muted">${esc(t("Loading articles…"))}</p>`;
      if (!dlg.open) dlg.showModal();
      // Fetch a candidate pool a bit larger than the synthesis bound so the user has a
      // real choice; /api/articles uses `ids` for an explicit set, else the query.
      const cp = _articleQuery(p);
      cp.set("limit", "60");
      try {
        const data = await api("/api/articles?" + cp.toString());
        _synthCandidates = { total: data.total, results: data.results || [] };
        _synthRenderSelect();
      } catch (e) { $("synth-win-body").innerHTML = `<p class="card-caveat">${esc(t("Could not load articles."))} ${esc(e.message)}</p>`; }
    }

    function _synthRenderSelect() {
      const TF = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((tpl, v) => tpl.replace(/\{(\w+)\}/g, (_m, k) => v[k]));
      const t = _synthT();
      const c = _synthCandidates; if (!c) return;
      const rows = c.results;
      $("synth-win-actions").innerHTML = "";
      $("synth-win-title").textContent = t("Synthesis");
      if (!rows.length) { $("synth-win-body").innerHTML = `<p class="muted">${esc(t("No matching articles to synthesize."))}</p>`; return; }
      const preset = Math.min(_SYNTH_MAX, rows.length);
      const list = rows.map((a, i) => `
        <label style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid var(--line);align-items:flex-start">
          <input type="checkbox" class="synth-cb" value="${a.id}" ${i < preset ? "checked" : ""} onchange="_synthCount()">
          <span style="flex:1">
            <span style="font-weight:600">${esc(a.title) || '<span class="muted">(untitled)</span>'}</span>
            <span class="muted" style="display:block;font-size:12px">${esc(a.source || "")} · ${esc((a.published_at || "").slice(0, 10)) || t("undated")} · ${a.language ? ooLangCell(a.language) : "?"}
              · <a href="/api/articles/${a.id}/view" target="_blank" rel="noopener">${esc(t("open"))}</a></span>
          </span>
        </label>`).join("");
      $("synth-win-body").innerHTML = `
        <div class="hint" style="margin-bottom:10px">${esc(t("A synthesis reads a bounded set of articles with a local model and writes what they agree on, where they disagree, and what they leave open — citing each source by number. It is reading assistance, never a verdict."))}</div>
        <div class="card" style="margin-bottom:12px">
          <div>${esc(t("Matched"))}: <b>${c.total}</b>${c.total > rows.length ? ` <span class="muted">(${esc(TF("showing the top {n} by search relevance", {n: rows.length}))})</span>` : ""}</div>
          <div class="muted" style="font-size:12px;margin-top:4px">${esc(TF("Pick up to {n} articles. The most relevant are pre-selected — refine your search to change the pool. (A small local model can only synthesize a bounded set well.)", {n: _SYNTH_MAX}))}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
          <span id="synth-count" class="chip"></span>
          <button class="ghost tiny" onclick="_synthSelectAll(true)">${esc(TF("Select first {n}", {n: _SYNTH_MAX}))}</button>
          <button class="ghost tiny" onclick="_synthSelectAll(false)">${esc(t("Clear"))}</button>
          <span style="margin-inline-start:auto"></span>
          <button class="primary" id="synth-run-btn" onclick="_synthRun()">${esc(t("Run synthesis"))}</button>
        </div>
        <div>${list}</div>`;
      _synthCount();
    }

    function _synthSelectAll(on) {
      const cbs = Array.from(document.querySelectorAll("#synth-win-body .synth-cb"));
      let n = 0;
      for (const cb of cbs) { cb.checked = on && n < _SYNTH_MAX; if (cb.checked) n++; }
      _synthCount();
    }
    function _synthCount() {
      const t = _synthT();
      const n = document.querySelectorAll("#synth-win-body .synth-cb:checked").length;
      const el = $("synth-count"); if (el) el.textContent = `${t("Selected")}: ${n} / ${_SYNTH_MAX}`;
      const btn = $("synth-run-btn");
      if (btn) { btn.disabled = (n < 1 || n > _SYNTH_MAX); btn.title = n > _SYNTH_MAX ? t("Too many — uncheck some.") : ""; }
    }

    async function _synthRun() {
      const t = _synthT();
      const ids = Array.from(document.querySelectorAll("#synth-win-body .synth-cb:checked"))
        .map((cb) => Number(cb.value)).filter((n) => n);
      if (!ids.length) { toast(t("Select at least one article."), "err"); return; }
      if (ids.length > _SYNTH_MAX) { toast(t("Too many — uncheck some."), "err"); return; }
      const btn = $("synth-run-btn"); if (btn) { btn.disabled = true; btn.textContent = t("Synthesizing…"); }
      const code = (window.OOI18N && OOI18N.current && OOI18N.current()) || "en";
      try {
        const r = await api("/api/llm/synthesize", { method: "POST",
          body: JSON.stringify({ article_ids: ids, output_language: _uiLangName(), ui_lang: code }) });
        _synthData = r;
        _synthRenderResult();
      } catch (e) {
        toast(t("Synthesis failed: ") + e.message, "err");
        if (btn) { btn.disabled = false; btn.textContent = t("Run synthesis"); }
      }
    }

    function _synthRenderResult() {
      const TF = (window.OOI18N && OOI18N.tf)
        ? OOI18N.tf : ((tpl, v) => tpl.replace(/\{(\w+)\}/g, (_m, k) => v[k]));
      const t = _synthT();
      const r = _synthData; if (!r) return;
      $("synth-win-actions").innerHTML = `
        <button class="ghost tiny" onclick="_synthCopy()" title="${esc(t("Copy the synthesis text"))}">${esc(t("Copy"))}</button>
        <button class="ghost tiny" onclick="_synthExport('md')">${esc(t("Export .md"))}</button>
        <button class="ghost tiny" onclick="_synthExport('html')">${esc(t("Open as a page ↗"))}</button>`;
      const members = (r.members || []).map((m) => `
        <li style="padding:6px 0;border-bottom:1px solid var(--line)">
          <span style="font-weight:600">[${m.n}] ${esc(m.title) || '<span class="muted">(untitled)</span>'}</span>
          <div class="muted" style="font-size:12px">${esc(m.source || "")} · ${esc((m.published_at || "").slice(0, 10)) || t("undated")} · ${m.language ? ooLangCell(m.language) : "?"}
            · <a href="/api/articles/${m.id}/view" target="_blank" rel="noopener">${esc(t("open"))}</a>${m.url ? " · " + extLink(m.url, t("source ↗"), "muted") : ""}</div>
        </li>`).join("");
      $("synth-win-body").innerHTML = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
          <span class="chip">${esc(t("synthesis"))} · ${esc(r.model || "")}</span>
          <span class="chip">${esc(TF("{n} articles", {n: r.member_count}))}</span>
          ${r.truncated ? `<span class="chip" title="${esc(t("Only the bounded set was synthesized."))}">${esc(TF("top {n} of {total}", {n: r.max_articles, total: r.total_matched}))}</span>` : ""}
        </div>
        <div style="white-space:pre-wrap;line-height:1.55">${esc(r.result || "")}</div>
        <div class="card-caveat" style="margin-top:10px">${esc(r.caveat || "")}</div>
        <h3 style="margin:16px 0 6px;font-size:14px">${esc(t("Synthesized corpus"))} (${(r.members || []).length})</h3>
        <ul style="list-style:none;padding:0;margin:0">${members}</ul>
        <div style="margin-top:12px"><button class="secondary tiny" onclick="_synthRenderSelect()">${esc(t("← Change selection"))}</button></div>`;
    }

    function _synthAsMarkdown() {
      const t = _synthT(); const r = _synthData; if (!r) return "";
      const out = [`# ${t("Synthesis")}`, "",
        `*${t("Local model")}: ${r.model || "?"} · ${r.member_count} ${t("articles")} · ${new Date().toISOString().slice(0, 10)}*`,
        "", (r.result || ""), "", `> ${r.caveat || ""}`, "", `## ${t("Synthesized corpus")}`];
      for (const m of (r.members || []))
        out.push(`${m.n}. ${m.title || "(untitled)"} — ${m.source || ""}${m.published_at ? " (" + m.published_at.slice(0, 10) + ")" : ""}${m.language ? " [" + ooLangCode(m.language) + "]" : ""}${m.url ? " " + m.url : ""}`);
      return out.join("\n");
    }
    function _synthAsHtml() {
      const t = _synthT(); const r = _synthData; if (!r) return "";
      const rows = (r.members || []).map((m) =>
        `<li><b>[${m.n}] ${esc(m.title || "(untitled)")}</b><br><small>${esc(m.source || "")} · ${esc((m.published_at || "").slice(0, 10))} · ${esc(ooLangCode(m.language || ""))}${m.url ? " · " + esc(m.url) : ""}</small></li>`).join("");
      return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(t("Synthesis"))}</title>`
        + `<style>body{font:16px/1.6 system-ui,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;color:#1a1a1a}`
        + `.meta{color:#666;font-size:13px}blockquote{color:#555;border-left:3px solid #ddd;padding-left:12px}`
        + `pre{white-space:pre-wrap;font:inherit}ul{padding-left:18px}li{margin:6px 0}</style></head><body>`
        + `<h1>${esc(t("Synthesis"))}</h1>`
        + `<p class="meta">${esc(t("Local model"))}: ${esc(r.model || "?")} · ${r.member_count} ${esc(t("articles"))} · ${new Date().toISOString().slice(0, 10)}</p>`
        + `<pre>${esc(r.result || "")}</pre>`
        + `<blockquote>${esc(r.caveat || "")}</blockquote>`
        + `<h2>${esc(t("Synthesized corpus"))}</h2><ul>${rows}</ul></body></html>`;
    }
    function _synthDownload(name, mime, text) {
      const blob = new Blob([text], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    function _synthExport(fmt) {
      const t = _synthT(); if (!_synthData) return;
      if (fmt === "md") { _synthDownload("synthesis.md", "text/markdown", _synthAsMarkdown()); return; }
      const html = _synthAsHtml();
      const w = window.open("", "_blank");
      if (w && w.document) { w.document.open(); w.document.write(html); w.document.close(); }
      else { _synthDownload("synthesis.html", "text/html", html); toast(t("Saved synthesis.html"), "ok"); }
    }
    function _synthCopy() {
      const t = _synthT(); if (!_synthData) return;
      const txt = _synthData.result || "";
      if (navigator.clipboard && navigator.clipboard.writeText)
        navigator.clipboard.writeText(txt).then(() => toast(t("Copied."), "ok"), () => toast(t("Copy failed."), "err"));
    }

    // --- Bulk summarize / translate over the matched set (local model) --------- //
    // Unlike Synthesize (ONE combined output), this runs the local model over EACH
    // matched article and stores a per-article result — kept forever, never replacing
    // a prior one (the reader shows the latest + folds the rest). Honest streaming
    // progress (invariant #20). Ollama is loopback (no egress), but airplane mode
    // still refuses it — surfaced loudly. These rows are NEVER keyword-indexed.
    let _bulkAbort = null;
    // The current UI language as an ENGLISH name the model reliably understands
    // ("French", not "Français") — the v2 language pin: summaries/synthesis come back
    // in the user's language. Translate carries its own explicit target instead.
    const _LANG_EN = {en:"English",fr:"French",de:"German",es:"Spanish",pt:"Portuguese",
      ru:"Russian",ar:"Arabic",zh:"Chinese",ja:"Japanese",hi:"Hindi",bn:"Bengali",id:"Indonesian"};
    function _uiLangCode() {
      return (window.OOI18N && OOI18N.current && OOI18N.current()) || "en";
    }
    function _uiLangName() {
      return _LANG_EN[_uiLangCode()] || "English";
    }
    function _bulkParams(ctx) { return ctx === "an" ? anParams() : searchParams(); }
    // --- Bulk summarize / translate QUEUE (maintainer 2026-06-21) -------------- //
    // Several batch runs can be QUEUED: start a long translation, keep searching, and
    // queue more from new results — they run ONE AT A TIME (a single local CPU model
    // can't do them well in parallel). Each job SNAPSHOTS its selection at enqueue, so
    // it targets the right articles even after you change the search. The active run also
    // appears in the task manager; this client-side queue manages the pending ones. The
    // queue lives in a persistent sibling (.bulk-queue) so it survives the config panel
    // being hidden or the custom-extractor panel reusing the same mount.
    let _bulkQueue = [];        // jobs, see _bulkSelLabel for the shape
    let _bulkActive = null;     // the running job (one at a time)
    let _bulkJobAbort = null;   // its AbortController (separate from _bulkAbort = extractor)
    let _bulkJobSeq = 1;

    function _bulkSelLabel(op, body) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const verb = op === "translate" ? t("Translate") : t("Summarize");
      let what;
      if (body.article_ids) what = body.article_ids.length + " " + t("selected");
      else if (body.query) what = '"' + body.query + '"';
      else what = t("filtered set");
      const into = op === "translate" && body.target_language ? " → " + body.target_language : "";
      return verb + " " + what + into;
    }

    function bulkLlm(op, ctx) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const mount = $(ctx === "an" ? "bulk-llm-an" : "bulk-llm-search");
      if (!mount) return;
      const p = _bulkParams(ctx);
      const hasSel = p.get("article_ids") || p.get("query") || p.get("source")
        || p.get("language") || p.get("start_date") || p.get("end_date");
      if (!hasSel) { toast(t("Run a search first."), "err"); return; }
      const isTr = op === "translate";
      const heading = isTr ? t("Translate all matched articles") : t("Summarize all matched articles");
      const tgt = isTr
        ? `<label class="muted" style="margin-inline-end:4px" for="bulk-tgt-${ctx}">${esc(t("Into"))}</label>`
          + `<input id="bulk-tgt-${ctx}" value="${esc(_uiLangName())}" style="max-width:150px">`
        : "";
      mount.style.display = "";
      mount.innerHTML = `<div class="card">
        <div style="font-weight:600;margin-bottom:4px">${esc(heading)}</div>
        <div class="hint" style="margin-bottom:8px">${esc(t("Runs a local model over each article — this can take a while. Each result is stored with its model and date; nothing leaves your machine, and keyword analysis is never affected. You can queue several runs; they process one at a time."))}</div>
        <div class="row" style="gap:12px;align-items:center;flex-wrap:wrap">
          ${tgt}
          <label style="display:flex;align-items:center;gap:5px"><input type="checkbox" id="bulk-skip-${ctx}" checked> ${esc(t("Skip articles already done"))}</label>
          <button class="primary" id="bulk-start-${ctx}" onclick="bulkLlmRun('${op}','${ctx}')">${esc(t("Add to queue"))}</button>
          <button class="ghost tiny" onclick="bulkPanelHide('${ctx}')">${esc(t("Hide"))}</button>
        </div>
      </div>`;
      _bulkRenderQueue();
    }
    // Hides the CONFIG panel only — queued/running jobs persist (the maintainer keeps
    // searching while a translation runs). Never cancels work.
    function bulkPanelHide(ctx) {
      const mount = $(ctx === "an" ? "bulk-llm-an" : "bulk-llm-search");
      if (mount) mount.style.display = "none";
    }
    // Back-compat: the custom-extractor panel's Cancel still aborts its own run + hides.
    function bulkLlmStop(ctx) {
      if (_bulkAbort) { try { _bulkAbort.abort(); } catch (e) { /* already done */ } _bulkAbort = null; }
      const mount = $(ctx === "an" ? "bulk-llm-an" : "bulk-llm-search");
      if (mount) mount.style.display = "none";
    }

    // Enqueue a bulk run (snapshot the current selection) and pump the queue.
    function bulkLlmRun(op, ctx) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const p = _bulkParams(ctx);
      const skipEl = $("bulk-skip-" + ctx);
      const body = { op, skip_existing: !!(skipEl && skipEl.checked) };
      const ids = p.get("article_ids");
      if (ids) { body.article_ids = ids.split(",").map(Number).filter((n) => n); }
      else {
        if (p.get("query")) body.query = p.get("query");
        if (p.get("source")) body.source = p.get("source");
        if (p.get("language")) body.language = p.get("language");
        if (p.get("start_date")) body.start_date = p.get("start_date");
        if (p.get("end_date")) body.end_date = p.get("end_date");
      }
      const hasSel = body.article_ids || body.query || body.source || body.language || body.start_date || body.end_date;
      if (!hasSel) { toast(t("Run a search first."), "err"); return; }
      // `ui_lang` goes on BOTH ops now (ruling 14, 2026-07-31): it no longer only
      // pins the OUTPUT language of a summary, it also selects which language the
      // built-in prompt BODY is written in — which a translation run needs too.
      if (op === "translate") { const e = $("bulk-tgt-" + ctx); body.target_language = (e && e.value.trim()) || _uiLangName(); }
      else { body.output_language = _uiLangName(); }
      body.ui_lang = _uiLangCode();
      const job = { id: _bulkJobSeq++, op, body, label: _bulkSelLabel(op, body),
        status: "queued", total: 0, done: 0, storedN: 0, skippedN: 0, failedN: 0, todo: null, skip: 0, err: "" };
      _bulkQueue.push(job);
      const ahead = _bulkQueue.filter((j) => j.status === "queued").length - 1;
      toast(_bulkActive ? `${t("Queued")} (${ahead} ${t("ahead")})` : t("Started."), "ok");
      _bulkRenderQueue();
      _bulkPump();
    }

    async function _bulkPump() {
      if (_bulkActive) return;                       // one model run at a time
      const job = _bulkQueue.find((j) => j.status === "queued");
      if (!job) return;
      _bulkActive = job; job.status = "running";
      _bulkRenderQueue();
      // `aiWorking` paints the pill busy NOW. The server would report this run too
      // (its generate() calls cross the counted seam), but only at the next poll —
      // and for work the reader just asked for, "within fifteen seconds" is not
      // feedback. The server signal still covers the case this cannot see: the run
      // continuing after the tab is closed.
      try { await aiWorking(() => _bulkRunJob(job)); }
      finally {
        _bulkActive = null; _bulkJobAbort = null;
        loadLlmHealth();                             // a fresh signal of whether Ollama is up
        _bulkRenderQueue();
        _bulkPump();                                 // next in line
      }
    }

    async function _bulkRunJob(job) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      _bulkJobAbort = ("AbortController" in window) ? new AbortController() : null;
      try {
        const resp = await fetch("/api/llm/bulk", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(job.body), signal: _bulkJobAbort ? _bulkJobAbort.signal : undefined,
        });
        if (!resp.ok || !resp.body) {
          let detail = "HTTP " + resp.status;
          try { const j = await resp.json(); if (j.detail) detail = j.detail; } catch (e) { /* keep status */ }
          job.status = "error"; job.err = detail; _bulkRenderQueue(); return;
        }
        const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
        for (;;) {
          const { done: fin, value } = await reader.read();
          if (fin) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split("\n"); buf = lines.pop();
          for (const line of lines) {
            if (!line.trim()) continue;
            let o; try { o = JSON.parse(line); } catch (e) { continue; }
            if (o.event === "start") {
              job.total = o.total;
              job.todo = (o.to_process != null) ? o.to_process : o.total;
              job.skip = Math.max(0, job.total - job.todo);
            } else if (o.event === "item") {
              job.done++;
              if (o.status === "stored") job.storedN++;
              else if (o.status === "skipped") job.skippedN++;
              else if (o.status === "failed") job.failedN++;
            } else if (o.event === "done") {
              if (o.aborted) { job.status = "error"; job.err = o.reason || t("Stopped"); }
              else job.status = "done";
            }
            _bulkRenderQueue();
          }
        }
        if (job.status === "running") job.status = "done";  // stream ended cleanly
      } catch (e) {
        if (e && e.name === "AbortError") { job.status = "cancelled"; }
        else { job.status = "error"; job.err = (e && e.message) || "error"; }
      } finally {
        _bulkRenderQueue();
      }
    }

    function bulkJobCancel(id) {
      const job = _bulkQueue.find((j) => j.id === id);
      if (!job) return;
      if (job.status === "running") { if (_bulkJobAbort) { try { _bulkJobAbort.abort(); } catch (e) { /* already */ } } }
      else if (job.status === "queued") { job.status = "cancelled"; }
      _bulkRenderQueue();
    }
    function bulkJobClearDone() {
      _bulkQueue = _bulkQueue.filter((j) => j.status === "queued" || j.status === "running");
      _bulkRenderQueue();
    }

    function _bulkJobLine(job) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const tally = `(${job.storedN} ${t("stored")} · ${job.skippedN} ${t("skipped")} · ${job.failedN} ${t("failed")})`;
      let state = "";
      if (job.status === "queued") state = `<span class="chip">${esc(t("Queued"))}</span>`;
      else if (job.status === "running") {
        const head = job.total ? `${job.done}/${job.total}` : t("starting…");
        state = `<span class="chip" style="background:var(--accent);color:#fff">${esc(t("Running"))} ${esc(head)}</span> <span class="muted">${esc(tally)}</span>`;
      } else if (job.status === "done") state = `<b>${esc(t("Done."))}</b> <span class="muted">${esc(tally)}</span>`;
      else if (job.status === "cancelled") state = `<span class="muted">${esc(t("Cancelled."))}</span>`;
      else if (job.status === "error") state = `<span class="note err">${esc(t("Stopped:"))} ${esc(job.err)}</span> <span class="muted">${esc(tally)}</span>`;
      const cancel = (job.status === "queued" || job.status === "running")
        ? `<button class="ghost tiny" onclick="bulkJobCancel(${job.id})" style="margin-inline-start:auto">${esc(t("Cancel"))}</button>` : "";
      return `<div class="row" style="gap:8px;align-items:center;padding:4px 0;border-bottom:1px solid var(--line);flex-wrap:wrap">
        <span style="font-weight:600">${esc(job.label)}</span> ${state} ${cancel}</div>`;
    }
    function _bulkRenderQueue() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const conts = document.querySelectorAll(".bulk-queue");
      if (!conts.length) return;
      let html = "";
      if (_bulkQueue.length) {
        const anyDone = _bulkQueue.some((j) => j.status === "done" || j.status === "cancelled" || j.status === "error");
        html = `<div class="card"><div style="font-weight:600;margin-bottom:4px">${esc(t("Translation & summary queue"))}</div>`
          + _bulkQueue.map(_bulkJobLine).join("")
          + (anyDone ? `<div style="margin-top:6px"><button class="ghost tiny" onclick="bulkJobClearDone()">${esc(t("Clear finished"))}</button></div>` : "")
          + `</div>`;
      }
      conts.forEach((c) => { c.innerHTML = html; });
    }

    // --- Run a user-defined custom extractor over the analysis OR search selection (the
    // on-demand path for the #386 managed list). ``ctx`` is "an" or "search" (mirrors
    // bulkLlm): same selection (_bulkParams), same NDJSON stream + abort (_bulkAbort /
    // bulkLlmStop), ctx-scoped element ids so both surfaces can be open at once. Results
    // store as ai_keyword rows of the prompt's kind — AI-derived, labelled unreliable,
    // NEVER the trusted keyword index (the backend writes ai_keyword, not KeywordMention). //
    async function aiRunPrompt(ctx) {
      ctx = ctx || "an";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const mount = $(ctx === "an" ? "bulk-llm-an" : "bulk-llm-search"); if (!mount) return;
      const p = _bulkParams(ctx);
      const hasSel = p.get("article_ids") || p.get("query") || p.get("source")
        || p.get("language") || p.get("start_date") || p.get("end_date");
      if (!hasSel) { toast(t("Run a search first."), "err"); return; }
      let prompts = [];
      try { const d = await api("/api/ai/prompts"); prompts = (d && d.prompts) || []; }
      catch (e) { toast(t("Could not load your extractors."), "err"); return; }
      const usable = prompts.filter((x) => x.enabled);
      mount.style.display = "";
      // E-S5 (2026-08-01): the BUILT-IN AI-keyword extractor had an endpoint and no
      // caller anywhere in the UI, so a user with no custom prompt could not reach it
      // at all — the custom-prompt path absorbs the MECHANISM but not this prompt.
      // Listing it here gives it a caller rather than retiring a capability nothing
      // else provides.
      const opts = `<option value="builtin">${esc(t("Built-in: AI keywords"))} · ai-keyword</option>`
        + usable.map((x) =>
          `<option value="${x.id}">${esc(x.label)} · ${esc(x.output_kind)}</option>`).join("");
      mount.innerHTML = `<div class="card">
        <div style="font-weight:600;margin-bottom:4px">${esc(t("Run a custom extractor"))}</div>
        <div class="hint" style="margin-bottom:8px">${esc(t("Runs your prompt with the local model over each matched article. Results are stored as AI-derived metadata of that type, labelled unreliable — the trusted keyword index is never affected; nothing leaves your machine."))}</div>
        <div class="row" style="gap:12px;align-items:center;flex-wrap:wrap">
          <select id="ai-run-pick-${ctx}">${opts}</select>
          <label style="display:flex;align-items:center;gap:5px"><input type="checkbox" id="ai-run-skip-${ctx}" checked> ${esc(t("Skip articles already done"))}</label>
          <button class="primary" id="ai-run-start-${ctx}" onclick="aiRunPromptStart('${ctx}')">${esc(t("Start"))}</button>
          <button class="ghost tiny" onclick="bulkLlmStop('${ctx}')">${esc(t("Cancel"))}</button>
        </div>
        <div id="ai-run-prog-${ctx}" class="hint" style="margin-top:8px"></div>
      </div>`;
    }
    async function aiRunPromptStart(ctx) {
      ctx = ctx || "an";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const pick = $("ai-run-pick-" + ctx), prog = $("ai-run-prog-" + ctx), startBtn = $("ai-run-start-" + ctx);
      const id = pick && pick.value;
      if (!id) return;
      const p = _bulkParams(ctx);
      const skipEl = $("ai-run-skip-" + ctx);
      const body = { skip_existing: !!(skipEl && skipEl.checked) };
      const ids = p.get("article_ids");
      if (ids) { body.article_ids = ids.split(",").map(Number).filter((n) => n); }
      else {
        if (p.get("query")) body.query = p.get("query");
        if (p.get("source")) body.source = p.get("source");
        if (p.get("language")) body.language = p.get("language");
        if (p.get("start_date")) body.start_date = p.get("start_date");
        if (p.get("end_date")) body.end_date = p.get("end_date");
      }
      if (startBtn) startBtn.disabled = true;
      if (prog) prog.textContent = t("Starting…");
      _bulkAbort = ("AbortController" in window) ? new AbortController() : null;
      let done = 0, total = 0;
      try {
        const url = (id === "builtin")
          ? "/api/ai/keywords/extract" : `/api/ai/prompts/${id}/run`;
        const resp = await fetch(url, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body), signal: _bulkAbort ? _bulkAbort.signal : undefined,
        });
        if (!resp.ok || !resp.body) {
          let detail = "HTTP " + resp.status;
          try { const j = await resp.json(); if (j.detail) detail = j.detail; } catch (e) { /* keep status */ }
          if (prog) prog.innerHTML = `<span class="note err">${esc(detail)}</span>`;
          if (startBtn) startBtn.disabled = false; return;
        }
        const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
        for (;;) {
          const { done: fin, value } = await reader.read();
          if (fin) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split("\n"); buf = lines.pop();
          for (const line of lines) {
            if (!line.trim()) continue;
            let o; try { o = JSON.parse(line); } catch (e) { continue; }
            if (o.event === "start") {
              total = o.total;
              if (prog) prog.textContent = t("Processing") + " 0/" + total + "…";
            } else if (o.event === "item") {
              done++;
              if (prog) prog.textContent = t("Processing") + " " + done + "/" + total + "…";
            } else if (o.event === "done") {
              if (o.aborted) {
                if (prog) prog.innerHTML = `<span class="note err">${esc(t("Stopped:"))} ${esc(o.reason || "")}</span>`;
              } else if (prog) {
                const tally = `${o.terms || 0} ${t("items")} · ${o.stored || 0} ${t("stored")} · `
                  + `${o.skipped || 0} ${t("skipped")} · ${o.failed || 0} ${t("failed")}`;
                prog.innerHTML = `<b>${esc(t("Done."))}</b> ${esc(tally)} `
                  + `<span class="muted">${esc(t("Open an article to see its AI-derived metadata."))}</span>`;
              }
            }
          }
        }
      } catch (e) {
        if (e && e.name === "AbortError") { if (prog) prog.textContent = t("Cancelled."); }
        else if (prog) prog.innerHTML = `<span class="note err">${esc(e.message)}</span>`;
      } finally {
        if (startBtn) startBtn.disabled = false; _bulkAbort = null;
        loadLlmHealth();
      }
    }

