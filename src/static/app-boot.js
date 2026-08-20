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
      try { if (_ooMapPayload && typeof _renderOoMapDim === "function") _renderOoMapDim(); } catch (_e) {}
      // World-map lens desc + story chips are rendered at render time (kindLabel/t), so
      // re-render them too so the whole map surface tracks the new locale (field-test Item 6).
      try { if (typeof _renderOoMapLensDesc === "function") _renderOoMapLensDesc(); } catch (_e) {}
      try { if (typeof _renderOoMapLensBar === "function") _renderOoMapLensBar(); } catch (_e) {}
      try { if (typeof _renderMapBasis === "function") _renderMapBasis(); } catch (_e) {}
      try {
        const tbl = $("src-table");
        if (tbl && tbl.querySelector("tr") && typeof loadSources === "function") loadSources();
      } catch (_e) {}
      // home-lead-title-frozen-locale (P1): renderBriefing() (Home Leads + the
      // corpus-tier badge it renders internally via renderCorpusTier) builds
      // OOI18N.tf()-templated titles that were never re-rendered on a language
      // switch, so any Lead card title stayed frozen in whatever locale was active
      // when it last rendered. Re-fetch+re-render only if the briefing has actually
      // loaded at least once (_lastBriefGen is set the first time renderBriefing
      // runs); the endpoint is server-cached (~30s) and dismissal is server-tracked,
      // so re-fetching never resurrects a dismissed card.
      try { if (_lastBriefGen !== null && typeof loadBriefing === "function") loadBriefing(); } catch (_e) {}
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
      // Re-translate the airplane button's JS-managed (data-i18n-dyn) title.
      try { if (_netOnline !== null && typeof _paintNetwork === "function") _paintNetwork(_netOnline); } catch (_e) {}
      // Re-render the AI prompt editor (remark 13): its labels are auto-translated by the
      // DOM walker, but re-running loadLlmPrompts refreshes the JS-built bits + the
      // effective-prompt placeholders if the panel is open.
      try { if ($("set-models") && $("set-models").offsetParent !== null && typeof loadLlmPrompts === "function") loadLlmPrompts(); } catch (_e) {}
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
    loadHealth(); loadLlmHealth(); loadSources(); checkEmptyCorpus(); loadRateMode();
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
      tip.setAttribute("role", "tooltip"); document.body.appendChild(tip);
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
      function show(el, x, y) {
        const text = el.getAttribute("title") || el.dataset.ooTip || "";
        if (!text.trim()) return;
        el.dataset.ooTip = text; el.removeAttribute("title");  // suppress the native double bubble
        cur = el; tip.textContent = text;
        tip.style.left = Math.min(x + 12, window.innerWidth - 346) + "px";
        tip.style.top = Math.min(y + 14, window.innerHeight - tip.offsetHeight - 12) + "px";
        tip.classList.add("show");
      }
      function hide() {
        if (cur && cur.dataset.ooTip != null) { cur.setAttribute("title", cur.dataset.ooTip); }
        cur = null; tip.classList.remove("show");
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
      const cache = new Map();   // term -> formatted line ; null = in-flight
      let hovered = null;
      function fmt(d) {
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        if (!d || !d.resolved) return t("Not in your corpus yet — no stats.");
        const bits = [`${d.mentions} ${t("mentions")} · ${d.articles} ${t("articles")}`];
        const tr = d.trend || {};
        if (tr.recent || tr.prior) {
          const fb = growthFallback(tr, {window: true});
          bits.push(fb ? `${t("trend")}: ${fb}`
                       : `${t("trend")} ${tr.growth}× (${tr.window_days}d ${t("vs")} ${tr.baseline_days}d)`);
        }
        const co = (d.cooccurrences || []).slice(0, 4).map((c) => c.term).filter(Boolean);
        if (co.length) bits.push(`${t("with")}: ${co.join(", ")}`);
        const head = d.resolved.term || d.term || "";
        return `${head} — ${bits.join(" · ")}${d.caveat ? " · " + d.caveat : ""}`;
      }
      function applyTo(el, text, persist) {
        // persist=true writes the #oo-tip convention (dataset.ooTip + title) so the next
        // hover shows it instantly; persist=false updates ONLY the currently-open bubble
        // (used for the transient "Loading…" state, so an abandoned+failed fetch can never
        // strand "Loading…" as the element's permanent tooltip — the runtime-review fix).
        if (persist) {
          el.dataset.ooTip = text;                                 // #oo-tip reads this
          if (el.getAttribute("title") != null) el.setAttribute("title", text);
        }
        const tip = document.getElementById("oo-tip");
        if (tip && tip.classList.contains("show") && hovered === el) tip.textContent = text;
      }
      async function load(el, term) {
        const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        if (cache.has(term)) { const v = cache.get(term); if (v) applyTo(el, v, true); return; }
        cache.set(term, null);                              // in-flight guard (no dup fetch)
        applyTo(el, t("Loading keyword stats…"), false);    // live bubble only — never persisted
        try {
          const d = await api("/api/insights/keyword-stats?term=" + encodeURIComponent(term));
          const text = fmt(d);
          cache.set(term, text);
          applyTo(el, text, true);
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
        hovered = el;
        const term = el.getAttribute("data-kwstat");
        if (term) load(el, term);
      }
      document.addEventListener("mouseover", onHover, true);
      document.addEventListener("focusin", onHover, true);
    })();

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
        showTab("analyze", false);
        if (corpus) {
          const ids = corpus.split(",").map(Number).filter((n) => Number.isFinite(n) && n > 0);
          if (ids.length) openAnalysisForIds(ids, sp.get("label") || "");
        } else if (analyze) {
          openAnalysisFor(analyze);
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