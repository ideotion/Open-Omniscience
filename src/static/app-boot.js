/* app-boot.js — the boot block — runs last

   Load-time wiring only: the event listeners, the saved-look application, the first
   render, and the ooSubtabs constructions. It assumes every definition above already
   exists, so it MUST stay the last module index.html loads.

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
    $("cust-ots").addEventListener("change", () =>
      $("cust-ots-warn").style.display = $("cust-ots").checked ? "block" : "none");

    $("q").addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

    // Apply the saved look immediately (before any network) so there is no flash.
    applyUi(getUi()); buildDrawer();

    // Re-check the local LLM when the tab regains focus — covers starting/stopping
    // Ollama in another window without a constant poll (event-driven, cheap loopback).
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && _netOnline !== false) loadLlmHealth();
    });

    // Live language switch (field test 2026-06-19 #16): CLDR-derived names (country /
    // continent on the world map, the sources country column) are localized at RENDER
    // time, so the i18n DOM walker (which matches English source strings) cannot
    // re-derive them. Re-render those dynamic-name surfaces in the new locale. The map
    // re-renders from its CACHE (no fetch); the sources table re-renders only if it has
    // already been loaded.
    document.addEventListener("oo:langchange", () => {
      // S04-06: the keyword labels opt OUT of the i18n walker (`data-i18n-dyn`, so a
      // keyword that happens to match a chrome key is never translated as if it were
      // chrome), which means nothing repaints them on a switch -- the frozen-locale
      // class. Registered in THIS listener rather than a new one: a second listener is a
      // second enumerator, and the two guards that inspect this event already walk every
      // handler for exactly that reason.
      try { if (typeof ooKwRepaintOnLangChange === "function") ooKwRepaintOnLangChange(); } catch (_e) {}
      // S04-09: the Wikipedia wizard's share line and the lane summary are built at
      // render time from tf() frames plus measured numbers, which is the same
      // frozen-locale class -- nothing in the walker can repaint a sentence it never
      // saw in English. Registered in THIS listener for the reason stated above.
      try { if (typeof _wizShare === "function") _wizShare(); } catch (_e) {}
      // The rest of the Home at-a-glance strip -- its counts and their labels, the "as
      // of" stamp and the automatic-collection line -- is built with t() inside the same
      // [data-i18n-dyn] subtree, so it is the same frozen-locale class: measured staying
      // English after a switch to fr or ar until the next 15 s poll (2026-09-26
      // click-through U5). Repaints from the LAST READING (app-home.js), never fetches,
      // and never over the read-failure line, which has its own branch further down.
      try { if (typeof repaintHomeGlance === "function") repaintHomeGlance(); } catch (_e) {}
      // The Home strip's own Wikipedia figure is built from a tf() frame AND carries
      // `data-i18n-dyn`, so BOTH repaint paths skip it -- the walker because the node
      // opts out, and this listener because it was not listed. Measured by the Chromium
      // walk: the figure rendered English in ar, zh and de while every other string on
      // the strip was translated. Repaints from the CACHED reading, so a language
      // switch costs no request.
      try { if (typeof renderHomeWikiFigure === "function") renderHomeWikiFigure(true); } catch (_e) {}
      try { if (typeof loadWikiLaneSummary === "function") loadWikiLaneSummary(); } catch (_e) {}
      // S04-07: the analysis window's cross-language rail is the same frozen-locale
      // class -- its sentences are built at render time from a tf() frame plus server
      // prose, so the walker cannot reach them. It redraws from the payload it already
      // has and NEVER fetches, so a switch cannot re-run a search behind the reader.
      try { if (typeof _anRepaintXLang === "function") _anRepaintXLang(); } catch (_e) {}
      // S04-14 (Q1124): the Patterns-lens gate panel is built at render time from
      // t() calls plus measured numbers, so the walker cannot repaint its composed
      // lines -- the same frozen-locale class. Measured in the Chromium walk: the
      // "Corpus size" line stayed English in fr while the pills beside it translated.
      // Repaints from the CACHED payload, so a switch costs no request.
      try { if (typeof _renderPatternsGate === "function") _renderPatternsGate(); } catch (_e) {}
      // Settings → Advanced → Quality gates is the same class (click-through S3): its
      // headline, scope sentence, admission rows, floor notes and backlog line are t()
      // and tf() frames welded to measured numbers at render time, so after a switch
      // they stayed in the old locale while the static text around them translated.
      // Re-read ONLY a section that was already expanded (its loader is guarded by
      // `advLoaded`), over loopback -- a switch never fetches for a fold nobody opened.
      // The last merge report redraws from the payload it kept, with no request at all.
      try {
        const qd = document.querySelector('#set-advanced details.adv-sec[data-adv="qualification"]');
        if (qd && qd.dataset.advLoaded === "1" && typeof loadQualificationGates === "function") {
          loadQualificationGates();
          if (typeof loadQualifyBulk === "function") loadQualifyBulk();
          if (typeof _renderOverlayMerge === "function") _renderOverlayMerge();
        }
      } catch (_e) {}
      // S04-14 (session 2): Home's "By channel" total line is built from a tf() frame
      // plus measured counts, so it is the same frozen-locale class -- the walker cannot
      // match a composed sentence against its English key. Measured in the Chromium walk:
      // booting `en` then switching to `ar` left "24 articles across 1 channels" in
      // English beside chips that translated, while booting straight into `ar` rendered
      // it correctly. Repaints from the CACHED payload, so a switch costs no request.
      try { if (typeof _renderHomeChannels === "function") _renderHomeChannels(); } catch (_e) {}
      // S04-14 (session 2): the analysis window's near-duplicate CAVEAT and its "≈N"
      // pill hovers are a keyed frame plus a measured count, so they are the same
      // frozen-locale class. A caveat that holds a translation in all twelve locales and
      // still shows English after a switch is the informed-consent non-negotiable
      // failing quietly. Repaints text only, from retained values -- no fetch.
      try { if (typeof _anRepaintDupNote === "function") _anRepaintDupNote(); } catch (_e) {}
      // S04-09: the Wikipedia toggle's hover is built at paint time from t() calls,
      // so it is the frozen-locale class too -- the button carries `data-i18n-dyn`
      // (its title is ALREADY translated, and letting the walker cache that as "the
      // original English" is the poisoning half of the same bug), which means nothing
      // else repaints it. Repaints from the state it already holds and NEVER fetches,
      // so a language switch cannot ask the backend anything behind the reader.
      try {
        if (typeof _paintWikiLane === "function" && typeof _wikiLaneState !== "undefined"
            && _wikiLaneState) _paintWikiLane(_wikiLaneState, _wikiLaneActive);
      } catch (_e) {}
      // The airplane coachmark is positioned in pixels from the plane, and a switch
      // into or out of Arabic mirrors the top bar without resizing the window, so the
      // coach stayed at its old spot -- 1,019 px from the plane, over the sidebar
      // (delegated click-through, rows N and T). Re-place it now and once the walker's
      // reflow has settled. _placeCoach returns at once when the coach is not showing.
      try {
        if (typeof _placeCoach === "function") { _placeCoach(); setTimeout(_placeCoach, 220); }
      } catch (_e) {}
      try { if (_ooMapPayload && typeof _renderOoMapDim === "function") _renderOoMapDim(); } catch (_e) {}
      // World-map lens desc + story chips are rendered at render time (kindLabel/t), so
      // re-render them too so the whole map surface tracks the new locale (field-test Item 6).
      try { if (typeof _renderOoMapLensDesc === "function") _renderOoMapLensDesc(); } catch (_e) {}
      try { if (typeof _renderOoMapLensBar === "function") _renderOoMapLensBar(); } catch (_e) {}
      try { if (typeof _renderMapBasis === "function") _renderMapBasis(); } catch (_e) {}
      try {
        // `loadManagedSources` is the TABLE; `loadSources` -- what this called -- only
        // refills the ingest <select> since the sources split, so the country/language
        // hovers in the table kept the old locale. The facet checklist labels
        // ("Name (CODE)", localised at render) are re-read too; a re-fill keeps its ticks.
        const tbl = $("src-table");
        if (tbl && tbl.querySelector("tr") && typeof loadManagedSources === "function") {
          loadManagedSources();
          if (typeof loadSrcFacets === "function") loadSrcFacets();
          // Its "…languages we can't analyse yet" line is a tf() frame now: same class.
          if (typeof loadUnmanagedLanguages === "function") loadUnmanagedLanguages();
        }
      } catch (_e) {}
      // World coverage is the same frozen-locale class, and it needed BOTH halves --
      // which is why the first fix looked like a fix and was not. Its two repaint
      // guards fingerprint the payload, so they now carry the locale too (otherwise
      // this call returns early on unchanged data and changes nothing); and nothing
      // re-ran it on a switch, so walking en -> fr -> ar -> zh left all 218 country
      // hovers reading whichever locale painted them first. Measured in Chromium:
      // after a switch the table was stale, and a forced `loadCoverage()` was correct.
      // Guarded on the table already having rows, exactly like `src-table` above: a
      // language switch must never FETCH for a panel the reader has not opened.
      try {
        const cov = $("coverage-table");
        if (cov && cov.querySelector("tr") && typeof loadCoverage === "function") loadCoverage();
      } catch (_e) {}
      // Governments → Law is the same class: its jurisdiction cells bake the localised
      // name into their hover at render time, so after a switch GBR still hovered
      // "United Kingdom" in fr/ar/zh until a reload (2026-09-26 click-through, L15).
      // Re-read ONLY a panel already painted -- the same guard as the two above -- and
      // over loopback, so a switch never fetches for a tab the reader has not opened.
      // The documents table is the guard for BOTH: `loadLaw` fills the two together,
      // and `#law-changes` starts life holding a "Loading…" line, so its own children
      // would read as "painted" before the tab was ever opened.
      try {
        const lawDocs = $("law-docs");
        if (lawDocs && lawDocs.querySelector("tr") && typeof loadLawDocs === "function") {
          loadLawDocs();
          if (typeof loadLawChanges === "function") loadLawChanges();
        }
      } catch (_e) {}
      // Markets → Minerals supply: its area cells hover the country name, or "World —
      // published aggregate", baked at render time (L9). Same guard: only a table
      // already painted is re-read, over loopback.
      try {
        const mins = $("mkt-minerals-supply");
        if (mins && mins.querySelector("table") && typeof loadMineralsSupply === "function") loadMineralsSupply();
      } catch (_e) {}
      // Settings -> Statistics: the figures and revision-anomalies tables draw their
      // count lines and headers in the reader's language (B18 R7/R8). Redrawn from the
      // payload each last drew -- never a fetch, and nothing for a table never opened.
      try { if (typeof repaintStatTablesFromCache === "function") repaintStatTablesFromCache(); } catch (_e) {}
      // home-lead-title-frozen-locale (P1): renderBriefing() (Home Leads + the
      // corpus-tier badge it renders internally via renderCorpusTier) builds
      // OOI18N.tf()-templated titles that were never re-rendered on a language
      // switch, so any Lead card title stayed frozen in whatever locale was active
      // when it last rendered. Re-fetch+re-render only if the briefing has actually
      // loaded at least once (_lastBriefGen is set the first time renderBriefing
      // runs); the endpoint is server-cached (~30s) and dismissal is server-tracked,
      // so re-fetching never resurrects a dismissed card.
      try { if (_lastBriefGen !== null && typeof loadBriefing === "function") loadBriefing(); } catch (_e) {}
      // The stat strip's read-failure line lives inside a [data-i18n-dyn] subtree,
      // so the DOM walker will never revisit it -- see renderHomeStatsFailure() in
      // app-home.js. Re-derive it here, and ONLY when it is actually the thing on
      // screen, so a language switch never repaints over real stats.
      try {
        if (typeof homeStatsIsShowingFailure === "function" && homeStatsIsShowingFailure()
            && typeof renderHomeStatsFailure === "function") renderHomeStatsFailure();
      } catch (_e) {}
      // The Composition figures are the same frozen-locale bug class as the Lead
      // titles above, and for the same reason: a Library view renders ONCE
      // (_libViewLoaded is a Set) and its labels are built at render time with t()
      // and OOI18N.tf(). The DOM walker can re-translate an exact-key text node, but
      // an already-INTERPOLATED tf() string ("top 3 sources hold 77.8% of articles")
      // is no longer a key and stays in whatever locale first rendered it. Caught by
      // screenshotting the panel in Arabic. Only re-renders if it has ever loaded.
      try {
        if (_libViewLoaded.has("composition") && typeof renderCompositionFigures === "function") {
          renderCompositionFigures();
        }
      } catch (_e) {}
      // Library -> Database & storage: the tiles own their labels (data-i18n-dyn, so a
      // label painted in French is never cached as the English), which means the walker
      // cannot relabel them either. Relabel from the last payload -- no fetch, and
      // nothing at all until the tiles were ever drawn (2026-09-26 click-through S6).
      try { if (typeof _paintDbStatLabels === "function") _paintDbStatLabels(); } catch (_e) {}
      // ...and the #db-file line under them plus every Storage footprint panel already
      // drawn (Library and the task manager's System tab): same class, same cure -- from
      // the last payloads, never a fetch and never a new disk walk.
      try { if (typeof repaintDbStorageFromCache === "function") repaintDbStorageFromCache(); } catch (_e) {}
      // Agenda -> Bulletin is the same class (the 2026-09-27 cross-batch finding
      // K-repaint): its Review, editions list, gate and status lines are composed at
      // render time, so a switch left all of them in the old language. `_bulRepaint`
      // redraws them from the payloads and status keys they last drew -- no fetch, and
      // nothing at all for a panel never opened.
      try { if (typeof _bulRepaint === "function") _bulRepaint(); } catch (_e) {}
      // Settings → Data & backup → Storage and the Library overview's tiles: every size
      // is written with its unit translated at render, inside a tf() frame or beside an
      // interpolated count, so the walker cannot repaint them and they kept the old
      // locale while the view stayed open (click-through B14, Z2). Both redraw from the
      // payload they last drew -- never a fetch -- and only once they were ever drawn.
      try { if (typeof repaintLaneStorageFromCache === "function") repaintLaneStorageFromCache(); } catch (_e) {}
      try { if (typeof repaintLibraryOverviewFromCache === "function") repaintLibraryOverviewFromCache(); } catch (_e) {}
      // Governments -> Groups: the aggregate cards are keyed frames drawn at render (Z4).
      try { if (typeof repaintGovGroupFromCache === "function") repaintGovGroupFromCache(); } catch (_e) {}
      // Governments' other views (Countries, Compare, the aggregate lens, the group picker,
      // the map line) and the Insights header: t()'d at render, redrawn from cache (W16/W17).
      try { if (typeof repaintGovViewsFromCache === "function") repaintGovViewsFromCache(); } catch (_e) {}
      try { if (typeof repaintInsightsStatusFromCache === "function") repaintInsightsStatusFromCache(); } catch (_e) {}
      // The Observatory is the same class again, and worse: its canvas has no DOM
      // for the i18n walker to reach at all, so EVERY label it paints (the orbit
      // ticks, the domain wedge names) plus its tf()-built disclosures would stay
      // in the first-rendered locale forever. Re-render only if it has payload,
      // i.e. only if the tab was ever opened -- this never triggers a fetch.
      try {
        if (typeof _obs !== "undefined" && _obs.payload && typeof _obsRender === "function") {
          _obsRender();
        }
      } catch (_e) {}
      // Living sources builds every figure and row with t()/tf() at render time, so a
      // switch re-reads the panel on screen (loopback only) -- and only if the tab was
      // ever opened, which is when _livingOverview holds a payload.
      try {
        if (typeof _livingOverview !== "undefined" && _livingOverview && typeof showLivingView === "function") {
          showLivingView(_livingView);
          if (_livingView === "wiki" && _wikiTc && _wikiTc.id != null) loadWikiTC();
        }
      } catch (_e) {}
      // The Activity view is the same class again, and it recurred the moment a new
      // interpolated string was added there: the qualification tile's composition note
      // ("Of 3 awaiting a verdict, 1 have never been attempted…") is built with
      // OOI18N.tf(), so once interpolated it is not a key and the walker cannot touch it.
      // Caught by screenshotting the tile in French, where every neighbouring label had
      // translated and this one sentence had not. Any future render-once surface that
      // interpolates must register here too.
      try {
        if (_libViewLoaded.has("activity") && typeof renderLibraryActivityGraphs === "function") {
          renderLibraryActivityGraphs();
        }
      } catch (_e) {}
      // The 2026-09-26 click-through (N5, U9) found three more members of the class, each
      // built at render time from t()/tf() and so out of the walker's reach: the Insights
      // watch rows, the analysis Price overlay's in-SVG axis label, and the Agenda grids
      // (weekday names from Intl in the page's language, and the moon hovers). Each redraws
      // from what it already holds -- the watch payload, the price series, the loaded
      // agenda -- and only when it was ever drawn, so a switch never fetches for them.
      try { if (typeof _renderWatches === "function") _renderWatches(); } catch (_e) {}
      try { if (typeof _anRepaintPrice === "function") _anRepaintPrice(); } catch (_e) {}
      try {
        if (typeof AG !== "undefined" && AG.cals && AG.cals.length && typeof renderAgenda === "function") {
          renderAgenda();
        }
      } catch (_e) {}
      // Re-translate the airplane button's JS-managed (data-i18n-dyn) title.
      try { if (_netOnline !== null && typeof _paintNetwork === "function") _paintNetwork(_netOnline); } catch (_e) {}
      // Re-render the AI prompt editor (remark 13): its labels are auto-translated by the
      // DOM walker, but re-running loadLlmPrompts refreshes the JS-built bits + the
      // effective-prompt placeholders if the panel is open.
      try { if ($("set-models") && $("set-models").offsetParent !== null && typeof loadLlmPrompts === "function") loadLlmPrompts(); } catch (_e) {}
      // The newsletter attach panel (Q1151) is built at render time from t()-resolved
      // strings and a server-sent caveat, so nothing in it is reachable by the DOM walker.
      // Re-render only when it is already on screen -- loadNewsletterAttach hides itself on
      // an empty corpus, and re-fetching for a hidden panel would be a poll.
      try {
        const nl = $("nl-attach");
        if (nl && nl.style.display !== "none" && typeof loadNewsletterAttach === "function") {
          loadNewsletterAttach();
        }
      } catch (_e) {}
      // The task manager's System panel (click-through B16, V9) draws its labels with t()
      // at render; redrawn from the last two samples it holds, so a switch never fetches.
      try { if (typeof repaintVitalsFromCache === "function") repaintVitalsFromCache(); } catch (_e) {}
    });

    // Global shortcuts: dispatched from the user's (rebindable) bindings — Ctrl/⌘-K opens
    // the palette by default; Escape closes overlays. See _kbDispatch / Settings → Shortcuts.
    document.addEventListener("keydown", _kbDispatch);

    // Initial load: always-on essentials; per-tab data loads lazily on first view.
    // Settings is loaded eagerly so the default result limit + theme seed apply
    // app-wide (mark it loaded so opening the tab doesn't refetch).
    _loaded.add("settings");
    loadSettings().then(doSearch);
    if (_media) _media.addEventListener("change", () => {
      if (getUi().theme === "system") applyThemeAttr("system");
    });
    // loadSources() is NOT here any more (2026-09-09): it fetched the whole source
    // catalogue -- 714,399 bytes, 98.8% of all boot API bytes on the live fixture --
    // to populate one <select> inside a folded Settings section. It now loads with
    // that section, via _ADV_LOADERS.collect, like every other Advanced panel.
    loadHealth(); loadLlmHealth(); checkEmptyCorpus(); loadRateMode(); loadWikiLane();
    // A window lives in the SERVER process, so it outlives a page reload. Discover
    // it at boot or the operator could have an open window with no visible sign of
    // it and no way to close it -- the exact failure mode the bar exists to prevent.
    initEgressWindow();
    // Keep the background-activity chip live app-wide (e.g. a scheduled scrape that
    // the user didn't trigger from the current tab). Adaptive: fast while a scrape
    // is active, backing off when idle; paused while the tab is hidden (audit PR G).
    _adaptivePoll(_pollActivity);
    // Dismiss the vitals popover on Escape or an outside click.
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && _vitalsOpen) toggleVitals(); });

    // -- Easter egg (opt-in, documented, harmless) -------------------------- //
    // Type the Konami code (↑↑↓↓←→←→ B A) to surface a random attributed journalism
    // quote / sourced fun fact. Only fires on the deliberate sequence, never during a
    // task, and never in evidence/exports — personality without intrusion.
    (function () {
      const seq = ["ArrowUp","ArrowUp","ArrowDown","ArrowDown","ArrowLeft","ArrowRight","ArrowLeft","ArrowRight","b","a"];
      let pos = 0, alt = false;
      document.addEventListener("keydown", (e) => {
        const t = e.target && e.target.tagName;
        if (t === "INPUT" || t === "TEXTAREA" || (e.target && e.target.isContentEditable)) return;
        pos = (e.key.toLowerCase() === seq[pos].toLowerCase()) ? pos + 1 : 0;
        if (pos !== seq.length) return;
        pos = 0; alt = !alt;
        api("/api/personality/random?kind=" + (alt ? "fact" : "quote")).then(r => {
          const it = r.item; if (!it) return;
          const msg = it.kind === "fact"
            ? `${it.text}${it.source ? `  — ${it.source}` : ""}`
            : `"${it.text}"  — ${it.author || "Unknown"}${it.attribution === "disputed" ? " (attribution disputed)" : ""}`;
          toast(msg, "ok");
        }).catch(() => {});
      });
    })();
    document.addEventListener("click", (e) => {
      if (!_vitalsOpen) return;
      const pop = $("vitals-pop"), chip = $("activity");
      if (pop && !pop.contains(e.target) && chip && !chip.contains(e.target)) toggleVitals();
    });
    ensureDocList();   // so the command palette can offer docs before Help is opened
    // -- External-link guard (maintainer ruling 2026-06-10): the app ALWAYS --- //
    // asks before opening an external link. Capture-phase + delegated, so it
    // covers every anchor — static or rendered later. Loopback links are exempt.
    // ---- the hover-for-information enhancer (one delegated listener; the ----
    // bubble re-reads the live translated title, so language switches apply.
    (function ooTipInit() {
      const tip = document.createElement("div"); tip.id = "oo-tip";
      tip.setAttribute("role", "tooltip");
      // Idle the bubble sits EMPTY at opacity:0 — still in the accessibility tree, so a
      // role=tooltip with no accessible name is exposed on every page (axe serious
      // aria-tooltip-name, found by the 2026-08-20 a11y walk on 3 surfaces — one
      // element, one fix). Hidden-from-AT while idle; show()/hide() toggle it, so when
      // visible its textContent IS its accessible name.
      tip.setAttribute("aria-hidden", "true");
      document.body.appendChild(tip);
      const mark = (root) => {
        (root.querySelectorAll ? root.querySelectorAll("[title]") : []).forEach((el) => {
          if ((el.getAttribute("title") || "").trim()) el.classList.add("oo-tip-target");
        });
      };
      mark(document);
      new MutationObserver((muts) => muts.forEach((m) => m.addedNodes.forEach((n) => {
        if (n.nodeType === 1) { if (n.hasAttribute && n.hasAttribute("title")) mark({querySelectorAll: () => [n]}); mark(n); }
      }))).observe(document.body, {childList: true, subtree: true});
      let cur = null, hideT = null;
      // A title set on an element AFTER it was rendered (a toggle repainting its own
      // hover on click) is marked like any other, and when that element's bubble is the
      // one open, the bubble takes the new text at once, instead of naming the state
      // before the click until the pointer leaves (row P's stale W hover).
      new MutationObserver((muts) => muts.forEach((m) => {
        const el = m.target, v = el.getAttribute && el.getAttribute("title");
        if (!v || !v.trim()) return;
        el.classList.add("oo-tip-target");
        if (el === cur) { el.dataset.ooTip = v; el.removeAttribute("title"); tip.textContent = v; }
      })).observe(document.body, {attributes: true, attributeFilter: ["title"], subtree: true});
      function show(el, x, y) {
        const text = el.getAttribute("title") || el.dataset.ooTip || "";
        if (!text.trim()) return;
        el.dataset.ooTip = text; el.removeAttribute("title");  // suppress the native double bubble
        // A MODAL DIALOG IS IN THE BROWSER'S TOP LAYER, which paints above every z-index
        // in the document, so a bubble left on <body> is drawn UNDER any showModal()
        // dialog: the consent popup's per-lane hosts (Q1002) were unreadable behind a
        // green is_visible() check (docs/audit/delegated-clickthrough-2026-09-26, P1).
        // Host the bubble in the open dialog that holds the element; position:fixed
        // still resolves to the viewport, because no dialog here sets a transform.
        const host = (el.closest && el.closest("dialog[open]")) || document.body;
        if (tip.parentNode !== host) host.appendChild(tip);
        cur = el; tip.textContent = text;
        tip.style.left = Math.min(x + 12, window.innerWidth - 346) + "px";
        tip.style.top = Math.min(y + 14, window.innerHeight - tip.offsetHeight - 12) + "px";
        tip.removeAttribute("aria-hidden");
        tip.classList.add("show");
      }
      function hide() {
        // A control REPAINTED while its bubble was open (the top-bar toggles set a new
        // title on click) already carries its new title: keep it, and never write the
        // text captured before the click back over it (the stale-hover defect, row P).
        if (cur && cur.hasAttribute("title")) { cur.dataset.ooTip = cur.getAttribute("title"); }
        else if (cur && cur.dataset.ooTip != null) { cur.setAttribute("title", cur.dataset.ooTip); }
        cur = null; tip.classList.remove("show");
        tip.setAttribute("aria-hidden", "true");
      }
      document.addEventListener("mouseover", (e) => {
        const el = e.target.closest && e.target.closest(".oo-tip-target");
        clearTimeout(hideT);
        if (el && el !== cur) { hide(); show(el, e.clientX, e.clientY); }
        else if (!el) hideT = setTimeout(hide, 80);
      }, true);
      document.addEventListener("focusin", (e) => {
        const el = e.target.closest && e.target.closest(".oo-tip-target");
        if (el) { const r = el.getBoundingClientRect(); hide(); show(el, r.left, r.bottom); }
      }, true);
      document.addEventListener("focusout", () => hide(), true);
      let pressT = null;  // touch: long-press opens the same bubble (title never did)
      document.addEventListener("touchstart", (e) => {
        const el = e.target.closest && e.target.closest(".oo-tip-target");
        if (!el) { hide(); return; }
        const t = e.touches[0];
        pressT = setTimeout(() => show(el, t.clientX, t.clientY), 450);
      }, {passive: true});
      document.addEventListener("touchend", () => { clearTimeout(pressT); hideT = setTimeout(hide, 2600); }, {passive: true});
    })();

    // Keyword hover-stats (wave 4 I / GET /api/insights/keyword-stats): hovering any
    // keyword surface marked data-kwstat surfaces its REAL stats — total mentions,
    // distinct-article spread, the windowed recent-vs-prior trend RATE, and the top
    // co-occurring keywords — through the ONE #oo-tip bubble (invariant #17). Counts
    // only, the endpoint's method/caveat ride along, NO score. Lazy + cached per term
    // (no fetch storm on a list of chips); the fetch is loopback-only so it is airplane-
    // safe. The bubble renders plain textContent, so the stats are one honest
    // " · "-separated line. It writes the element's title/ooTip (the #oo-tip convention)
    // and, when that element's bubble is already open, updates it live (hint -> loading
    // -> stats) without touching the ooTip internals.
    (function ooKwStatInit() {
      const cache = new Map();   // term -> keyword-stats payload ; null = in-flight
      let hovered = null;
      function fmt(d) {
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        // NAME THE TERM even when there are no stats to show. The reader's hover title
        // is a STATIC sentence -- it has to be, because the i18n walker matches an
        // attribute by exact value and a title carrying the keyword could never match
        // a key -- so this line is the only place the keyword's own name reaches the
        // bubble. Dropping it here left an unindexed keyword generic BEFORE and AFTER
        // hover. Built in the same shape as the resolved branch twenty lines below
        // (name, em dash, the line), so the two readings of this bubble agree.
        if (!d || !d.resolved) {
          const unresolved = (d && d.term) || "";
          const none = t("Not in your corpus yet — no stats.");
          return unresolved ? `${unresolved} — ${none}` : none;
        }
        // "1 articles" read as a slip (N14): the singular keys exist, so a count of one
        // takes them. (No CLDR plural rules here; this fixes the one form every locale
        // has, and leaves the rest of the counting grammar where it was.)
        const bits = [`${d.mentions} ${d.mentions === 1 ? t("mention") : t("mentions")}`
          + ` · ${d.articles} ${d.articles === 1 ? t("article") : t("articles")}`];
        const tr = d.trend || {};
        if (tr.recent || tr.prior) {
          const fb = growthFallback(tr, {window: true});
          bits.push(fb ? `${t("trend")}: ${fb}`
                       : `${t("trend")} ${tr.growth}× (${tr.window_days}d ${t("vs")} ${tr.baseline_days}d)`);
        }
        // THE MEASURED NUMBERS, not just the names. keyword-stats returns each
        // co-occurrence with its shared-article count AND its PMI, and this line used
        // to map straight to c.term and drop both -- so the one surface in the #an
        // window that carries an association strength was fetching it and throwing it
        // away. Shown beside the term, because a co-occurrence with no count and no
        // strength cannot be read: it says "these appear together" without saying how
        // often or how much more than chance. PMI stays paired with the raw count on
        // purpose (it is noisy on small samples, exactly as the endpoint's caveat says).
        const co = (d.cooccurrences || []).slice(0, 4).filter((c) => c && c.term).map((c) => {
          const n = (c.cooccur != null) ? ` (${c.cooccur} ${t("articles")}` : "";
          const pmi = (n && c.pmi != null) ? `, ${t("Association")} ${c.pmi.toFixed(1)}` : "";
          return `${c.term}${n}${pmi}${n ? ")" : ""}`;
        });
        if (co.length) bits.push(`${t("with")}: ${co.join(", ")}`);
        const head = d.resolved.term || d.term || "";
        // The caveat is a FIXED server sentence, so it is keyed and goes through t() --
        // appended verbatim it read in English inside every translated bubble (N7, M14).
        return `${head} — ${bits.join(" · ")}${d.caveat ? " · " + t(d.caveat) : ""}`;
      }
      function applyTo(el, text, persist) {
        // THIS HANDLER OVERWRITES THE TITLE, so anything the RENDERER put there is gone
        // the moment the reader hovers. `data-oo-tip-extra` is how a row keeps a fact of
        // its own: read here and appended to the composed line, so it survives the
        // overwrite and reaches the bubble the reader actually reads rather than only
        // the native tooltip that the overwrite replaces.
        //
        // Found by measuring (Q417, 2026-09-17): the per-language breakdown was put in
        // the title of a `data-kwstat` row, which is true in the DOM at render time and
        // false after one hover, forever. The Chromium walk read the bubble back and saw
        // the stats line where the breakdown should have been.
        //
        // Appended per ELEMENT rather than folded into `fmt`, because the stats line is
        // cached per TERM and this is a fact about the row.
        //
        // The rest as before: persist=true writes the #oo-tip convention (dataset.ooTip +
        // title) so the next hover shows it instantly; persist=false updates ONLY the
        // currently-open bubble (used for the transient "Loading…" state, so an
        // abandoned+failed fetch can never strand "Loading…" as the element's permanent
        // tooltip — the runtime-review fix).
        const extra = (el.dataset && el.dataset.ooTipExtra) || "";
        const full = extra ? text + " \u2014 " + extra : text;
        if (persist) {
          el.dataset.ooTip = full;                                 // #oo-tip reads this
          if (el.getAttribute("title") != null) el.setAttribute("title", full);
        }
        const tip = document.getElementById("oo-tip");
        if (tip && tip.classList.contains("show") && hovered === el) tip.textContent = full;
      }
      async function load(el, term) {
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        // The PAYLOAD is cached, not the formatted line: the line is words in the active
        // language, and a line cached in English was served unchanged after a switch.
        if (cache.has(term)) { const v = cache.get(term); if (v) applyTo(el, fmt(v), true); return; }
        cache.set(term, null);                              // in-flight guard (no dup fetch)
        applyTo(el, t("Loading keyword stats…"), false);    // live bubble only — never persisted
        try {
          const d = await api("/api/insights/keyword-stats?term=" + encodeURIComponent(term));
          cache.set(term, d || {});
          applyTo(el, fmt(d), true);
        } catch (_e) {
          cache.delete(term);                               // allow a later retry
          // if still hovering, revert the transient "Loading…" back to the element's own hint
          const tip = document.getElementById("oo-tip");
          if (tip && tip.classList.contains("show") && hovered === el) tip.textContent = el.dataset.ooTip || "";
        }
      }
      function onHover(e) {
        const el = e.target && e.target.closest ? e.target.closest("[data-kwstat]") : null;
        if (!el) { hovered = null; return; }
        // A hover target of its OWN inside the keyword row -- the tier tag, its QID --
        // keeps the bubble ooTipInit just opened for it. Without this the stats line
        // overwrote it at once, so Q418's hover (original, language, QID) was unreachable
        // on every data-kwstat chip (M2). Its text also rides the row's
        // data-oo-tip-extra, which is how a keyboard reader gets it.
        const inner = e.target.closest(".oo-tip-target");
        if (inner && inner !== el && el.contains(inner)) { hovered = null; return; }
        hovered = el;
        const term = el.getAttribute("data-kwstat");
        if (term) load(el, term);
      }
      document.addEventListener("mouseover", onHover, true);
      document.addEventListener("focusin", onHover, true);
    })();

    // Q412's sense picker (M4): ONE delegated listener for every [data-kwpin] button on
    // every keyword surface. CAPTURE phase and stopped here, so a picker drawn inside a
    // clickable row (a keyword link) never also fires that row's own action.
    document.addEventListener("click", (e) => {
      const b = e.target && e.target.closest ? e.target.closest("[data-kwpin]") : null;
      if (!b || typeof kwPickSense !== "function") return;
      e.preventDefault(); e.stopPropagation();
      kwPickSense(b);
    }, true);

    document.addEventListener("click", function _externalLinkGuard(e) {
      const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      if (!a || !/^https?:/i.test(a.href)) return;
      let host = "";
      try { host = new URL(a.href).hostname; } catch { return; }
      if (host === "127.0.0.1" || host === "localhost" || host === location.hostname) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!confirm(t("Open this external link in your browser?") + "\n\n" + a.href + "\n\n" +
                   t("This leaves the app and contacts an outside server.")))
        { e.preventDefault(); e.stopImmediatePropagation(); }
    }, true);
    // Honour a deep-link like /#sources on first load; otherwise land on Home.
    // showTab itself maps legacy aliases (#database -> #library) and falls back.
    showTab((location.hash || "#home").slice(1), false);  // initial render: replace, don't push

    // THEME-3: restore the spawned analysis-tab strip (data loads lazily) -- this MUST
    // run BEFORE _hydrateCardCorpus() below (analysis-boot-race-destroys-tab-workspace,
    // P1): _hydrateCardCorpus()'s ?corpus=/?analyze= spawn calls _anSpawn() ->
    // _anActivate() -> _anSaveTabs(), which OVERWRITES the persisted 'oo.an.tabs.v1'
    // localStorage key with only the just-spawned tab. Restoring the PREVIOUSLY
    // persisted tabs FIRST means the deep-linked seed gets ADDED to that restored set
    // (via _anSpawn's own dedup-by-key check, which reuses a matching tab in place
    // rather than duplicating it) instead of clobbering it -- so opening the omnibar
    // in successive new browser tabs actually accumulates a multi-tab workspace via
    // its real, documented entry point, instead of every fresh tab always showing
    // exactly the one query it was seeded with.
    _anRestoreTabs();

    // Deep-link a Lead's corpus opened "in a new window" (maintainer 2026-06-23): a
    // card's back button does window.open("/?corpus=1,2,3&label=…"); this fresh SPA
    // tab hydrates the analysis over that exact set (or ?analyze=<seed> for a query
    // card). Runs once at boot; the params are left in the URL only for this hydration.
    (function _hydrateCardCorpus() {
      try {
        const sp = new URLSearchParams(location.search);
        const corpus = sp.get("corpus"), analyze = sp.get("analyze");
        if (!corpus && !analyze) return;
        // The deep link IS the tab to show: mark Analysis hydrated BEFORE opening it, so
        // showTab does not first load the RESTORED active tab as well. Loading both raced
        // two runs into the same panels and wrote the restored tab's sense into this
        // tab's URL (the 2026-09-26 delegated click-through, row N: P1 + the sense-pin
        // leak). Only when a spawn will follow: a ?corpus= with no usable id falls back
        // to the restored tab, exactly as before.
        const ids = corpus ? corpus.split(",").map(Number).filter((n) => Number.isFinite(n) && n > 0) : [];
        if (analyze || ids.length) _anHydrated = true;
        // Q504: the cross-language lens travels in the link, so a shared "?analyze=climat
        // &expand=0" opens the search the sender was actually looking at rather than the
        // default one. It rides as part of the SEED, not as a setting applied beside it:
        // the spawned tab's own _anApplySeed would otherwise overwrite it a moment later
        // and rewrite the URL without it. Read BEFORE showTab: when showTab hydrates the
        // restored tab it writes THAT tab's lens into this URL, and a read after it took
        // another tab's sense as this link's own (row N, N2).
        const lens = _anReadLensFromUrl();
        showTab("analyze", false);
        // Ruling 16: the Lead's provenance travels with the deep link (a one-shot
        // localStorage token, taken and deleted here) so the new window can show WHICH
        // Lead it came from and on what basis. Absent -> no header, never an invented one.
        const prov = _anProvTake(sp.get("prov"));
        if (corpus) {
          if (ids.length) openAnalysisForIds(ids, sp.get("label") || "", prov, lens);
        } else if (analyze) {
          openAnalysisFor(analyze, (prov || lens) ? {prov, lens} : undefined);
        }
        // Deep-link a specific analysis subtab (?tab=keywords from an in-article
        // keyword click). _anSubtabs is wired just AFTER this IIFE, so stash the
        // request; it is applied once the subtab component exists (below).
        const tab = sp.get("tab");
        if (tab && document.getElementById("an-" + tab)) _anBootTab = tab;
      } catch (e) { /* a malformed deep link must never break boot */ }
    })();


    // Wire the universal subtab grammar on every multi-section surface (one
    // component, three surfaces). No opts.initial: each surface keeps its
    // HTML-default panel; the component just adopts ARIA + keyboard + click.
    _insSubtabs = ooSubtabs($("ins-subtabs"), showInsightCat);
    _setSubtabs = ooSubtabs($("set-subtabs"), showSetCat);
    _corpusSubtabs = ooSubtabs($("corpus-subtabs"), corpusTab);
    // Closing the corpus window returns the shared mind-map kit to Insights
    // (so the Insights Explore mind-map is never left empty after a relocation).
    $("corpus-win").addEventListener("close", _mmKitHome);
    ooSubtabs($("tm-subtabs"), tmSelectTab);  // the task-manager window (Tasks / System)
    _anSubtabs = ooSubtabs($("an-subtabs"), anSelectTab);  // the analysis window subtabs
    // A ?tab= deep link (in-article keyword click → the Keywords subtab): apply
    // it now that the subtab component exists (it was stashed during hydration).
    if (_anBootTab && document.getElementById("an-" + _anBootTab)) {
      _anSubtabs.select(_anBootTab); _anBootTab = null;
    }

    // Deep-link the tracked-changes view for ONE wiki page (S2/S4): the article
    // reader offers "tracked changes on this machine" and navigates to
    // "/?wikitc=<page_id>". The reader is a STANDALONE page served by
    // /api/articles/{id}/view, so without this the history the ruling asks to sit
    // beside a wiki article would be reachable only by going looking for it.
    //
    // The view is the Wikipedia panel of Living sources now (Q1016, S04-08's S6), and
    // openWikiTC goes there itself, selecting the subtab through the tab's own
    // component (invariant #18) so .active / aria-selected stay in step.
    //
    // The reader only ever emits this link for a page whose WikiPage row exists, so
    // the id is real by construction; a stale or hand-edited one opens the view and
    // the view's own honest empty state answers it -- no fabricated history, and a
    // malformed link never breaks boot.
    (function _hydrateWikiTrackedChanges() {
      try {
        const id = Number(new URLSearchParams(location.search).get("wikitc"));
        if (!Number.isFinite(id) || id <= 0) return;
        if (typeof openWikiTC !== "function") return;
        // openWikiTC goes to Living sources -> Wikipedia itself, through the tab's
        // subtab component; the view left Settings with the dialog (Q1016).
        openWikiTC(id, "", "");
      } catch (e) { /* a malformed deep link must never break boot */ }
    })();

    // The standalone task manager (/tasks) hands a download's Resume over here when it is
    // offline: a resume re-opens a fetch, and the ONE consent popup (invariant #14) lives
    // in this app, not on that page. "/?resume=<job id>" runs the SAME jobResume the
    // in-app window's button runs, so the popup asks first, with its own reason, and
    // nothing is sent if the operator stays offline. Only the two download kinds are
    // accepted (a local job needs no hand-off; anything else is dropped, never posted),
    // and the parameter leaves the URL at once, so a reload never asks again. After the
    // locale is ready, so the popup's reason is in the operator's language.
    (function _hydrateResumeHandoff() {
      try {
        const sp = new URLSearchParams(location.search);
        const id = sp.get("resume");
        if (!id) return;
        sp.delete("resume");
        const qs = sp.toString();
        history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
        if (!/^(dump|osm):./.test(id) || typeof jobResume !== "function") return;
        Promise.resolve(window.OOI18N && OOI18N.ready).then(() => jobResume(id), () => jobResume(id));
      } catch (e) { /* a malformed deep link must never break boot */ }
    })();

    // Q725's wizard, reached BOTH ways the ruling asks for. The Settings button is
    // the door an operator can go back through at any time; "/?wikiwizard=1" is the
    // hand-off unlock.html makes for a FRESH corpus only, so an operator who has
    // already answered is never asked again on launch.
    //
    // The deep link deliberately does NOT check ``wizard_done``: a returning operator
    // never arrives with this parameter (unlock.html only adds it after a create),
    // and refusing to open a screen the operator explicitly navigated to would be the
    // app second-guessing a link they followed.
    (function _wireWikiWizard() {
      const open = $("wiki-wizard-open");
      if (open) open.addEventListener("click", () => openWikiWizard());
      const save = $("wiki-wizard-save");
      if (save) save.addEventListener("click", () => saveWikiWizard());
      const cancel = $("wiki-wizard-cancel");
      if (cancel) cancel.addEventListener("click", () => {
        const dlg = $("wiki-wizard");
        // "Not now" LEAVES THE SETTINGS ALONE, including wizard_done. An operator who
        // dismissed the screen has not been through it, and recording that they had
        // would make the defaults look like a choice they made.
        if (dlg) { try { dlg.close(); } catch (_e) { dlg.removeAttribute("open"); } }
      });
      const all = $("wiki-wizard-all");
      if (all) all.addEventListener("click", () => _wizSelectAll(true));
      const none = $("wiki-wizard-none");
      if (none) none.addEventListener("click", () => _wizSelectAll(false));
      const budget = $("wiki-wizard-budget");
      if (budget) budget.addEventListener("input", () => _wizShare());
      try {
        if (new URLSearchParams(location.search).get("wikiwizard") === "1"
            && typeof openWikiWizard === "function") {
          openWikiWizard();
        }
      } catch (e) { /* a malformed deep link must never break boot */ }
    })();

    // The keyword fold (Q416 = a): Settings → Advanced. Bound here rather than inline.
    (function _wireKeywordFold() {
      const btn = $("kw-fold-btn");
      if (btn) btn.addEventListener("click", () => foldKeywords(btn));
      const rep = $("kw-fold-report");
      if (rep) rep.addEventListener("click", () => window.open("/api/insights/keyword-fold-job/report", "_blank"));
    })();

    // The search re-index (S04-07 S8): Settings → Advanced. Bound here rather than inline.
    (function _wireSearchReindex() {
      const btn = $("fts-reindex-btn");
      if (btn) btn.addEventListener("click", () => reindexSearch(btn));
      const rep = $("fts-reindex-report");
      if (rep) rep.addEventListener("click", () => window.open("/api/search/index-job/report", "_blank"));
    })();

    // Click the EMPTY space of the sidebar (not a nav item / button / link) to
    // collapse / expand it (remark 15) — the same toggle as the #sb-collapse /
    // #sb-expand buttons, so the whole rail is a discoverable target.
    (function _wireSidebarEmptyClickToggle() {
      const sb = $("sidebar");
      if (!sb) return;
      sb.addEventListener("click", (e) => {
        if (e.target.closest(".nav-item, button, a, input, label, select, textarea")) return;
        toggleSidebar();
      });
    })();