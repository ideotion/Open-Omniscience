/* app-shell.js — navigation shell, look, keys, palette

   Tab navigation (TAB_LOADERS, showTab, the relocated subtab strip), UI preferences
   (themes, accents, density, typeface), keybindings, the Settings category switch and
   its Advanced foldouts, the drawer, and the command palette / omnibar.

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
    const NAV = [
      {id:"home",     label:"Home",               grp:"Investigate"},
      {id:"search",   label:"Search",             grp:"Investigate"},
      {id:"insights", label:"Insights",           grp:"Investigate"},
      {id:"timemap",  label:"World map",          grp:"Investigate"},
      {id:"wiki",     label:"Wikipedia",          grp:"Investigate"},
      {id:"law",      label:"Governments",        grp:"Investigate"},
      {id:"agenda",   label:"Agenda",             grp:"Investigate"},
      {id:"indices",  label:"Indices",            grp:"Investigate"},
      {id:"markets",  label:"Commodities",        grp:"Investigate"},
      {id:"ingest",   label:"Collect",            grp:"Collect"},
      {id:"sources",  label:"Sources",            grp:"Collect"},
      {id:"library",  label:"Library",            grp:"Collect"},
      {id:"custody",  label:"Evidence & custody", grp:"Trust"},
      {id:"integrity",label:"Source integrity",   grp:"Trust"},
      // Settings is NOT a menu item (maintainer-ruled 2026-06-10: the top-bar
      // gear button is the single entry; a duplicate menu row was confusing).
      // Help is ALSO not a sidebar item (maintainer-ruled 2026-06-15: the top-bar
      // "?" icon is sufficient). Both stay registered/LOCKED so deep-links, the
      // command palette and the top-bar buttons keep working.
      {id:"help",     label:"Help & docs",        grp:"System"},
    ];
    // Always-available tools can't be hidden, so the user can never lock themselves out.
    const LOCKED = new Set(["home","settings","help"]);

    // -- Tab navigation ----------------------------------------------------- //
    // Every entry is an ARROW, never a bare function reference. A bare reference is
    // evaluated when this object literal is BUILT, so it depends on the loader having
    // been hoisted -- which holds only while the whole UI engine is one script. The
    // arrow defers the lookup to the click, so load order stops mattering. This is the
    // shape _ADV_LOADERS, _LIB_VIEW_LOADERS, LIVE and this table's own `library:` entry
    // already use; the twelve bare references here were the only construct in the file
    // that reached forward across the module split (measured: 12 forward refs, all here,
    // and zero TDZ references anywhere -- docs/design/APPJS_DECOMPOSITION_2026-08-20.md).
    const TAB_LOADERS = {
      home: () => loadHome(),
      feed: () => { _wireFeed(); },   // rulings 13/40: the corpus as a reading surface
      search: () => buildSearchTimeScope(),   // mount the ooTimeScope date-range control once
      indices: () => loadIndices(),
      markets: () => loadMarkets(),
      insights: () => loadInsights(),
      timemap: () => loadOoMapCoverage(),   // slice 5b: the Map tab is now the unified ooMap (the temporal map was folded in + retired)
      law: () => loadGovernments(),   // Governments tab (Countries · Map · Law subtabs)
      agenda: () => loadAgenda(),
      library: () => { _wireLibraryViews(); },  // per-view lazy loaders (2026-08-01 ruling 9); stats ride the live poller (startLive)
      custody: () => loadCustody(),
      integrity: () => loadIntegrity(),
      settings: () => loadSettings(),
      help: () => loadDocs(),
    };
    const _loaded = new Set();

    // Facet subtabs live JUST UNDER the status bar (maintainer 2026-06-20): each tab's
    // ooSubtabs nav is relocated into #subtab-strip the first time the tab is shown —
    // moving the DOM node preserves its listeners + active state — then only the active
    // tab's nav is displayed. Tabs without facet subtabs hide the strip.
    const _SUBTAB_NAV = {
      analyze: "an-subtabs", insights: "ins-subtabs", settings: "set-subtabs",
      agenda: "agenda-views", indices: "indices-cats", markets: "commodities-cats",
      law: "gov-subtabs",   // Governments: Countries · Map · Law
      timemap: "oomap-lenses",   // World map: Coverage · Stories · Places · Server IPs (field-test Item 6)
      library: "library-views",  // Library: Overview · Activity · Tracked · Database & storage · World coverage
    };
    function _relocateSubtabs(name) {
      const strip = $("subtab-strip"); if (!strip) return;
      const id = _SUBTAB_NAV[name];
      if (id) { const nav = $(id); if (nav && nav.parentNode !== strip) strip.appendChild(nav); }
      let any = false;
      Array.prototype.forEach.call(strip.children, (ch) => {
        const on = !!id && ch.id === id;
        ch.style.display = on ? "" : "none";
        if (on) any = true;
      });
      strip.hidden = !any;
    }
    function showTab(name, push = true) {
      if (name === "database") name = "library";  // legacy #database deep-links
      if (name === "ingest") {  // Collect moved into Settings → Advanced → Collection
        showTab("settings", push);
        _openAdvanced("collect");
        return;
      }
      if (name === "sources") {  // Sources moved into Settings → Advanced → Sources
        showTab("settings", push);
        _openAdvanced("sources");
        return;
      }
      if (name === "wiki") {  // Wikipedia moved into Settings → Wikipedia (content-first §6)
        showTab("settings", push);
        try { _setSubtabs.select("wikipedia"); } catch (e) { showSetCat("wikipedia"); }
        return;
      }
      if (!document.getElementById("tab-" + name)) name = "home";
      document.querySelectorAll(".nav-item[data-tab]").forEach(b => {
        const on = b.dataset.tab === name;
        b.classList.toggle("active", on);
        if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
      });
      document.querySelectorAll(".tab-page").forEach(p =>
        p.classList.toggle("active", p.id === "tab-" + name));
      _relocateSubtabs(name);   // move this tab's facet subtabs into the top strip (under the status bar)
      // S3.1 (c): a tab's own loader and its live poller overlap for home,
      // insights and library -- `insights` is literally the SAME function in
      // both maps -- so the first open of those tabs issued every request twice
      // (Home: stats, scheduler status, briefing, trends and alerts, the last
      // being the 23.7 s convergence scan). The loader runs once per page load;
      // the live poller ticks immediately on EVERY showTab. When the loader has
      // just run, its leading tick is the duplicate, so skip that one -- the
      // interval is untouched, so live data is never delayed by more than the
      // loader it would have duplicated.
      let justLoaded = false;
      if (TAB_LOADERS[name] && !_loaded.has(name)) {
        _loaded.add(name);
        TAB_LOADERS[name]();
        justLoaded = true;
      }
      // THEME-3: opening Analysis hydrates the restored active tab the first time (the
      // strip is restored at boot; the active tab's data loads lazily here), or shows
      // the launcher empty state when there are no tabs.
      if (name === "analyze" && !_anHydrated) {
        _anHydrated = true;
        _anFillLangSelect();   // populate the Advanced language <select> (flags + names)
        const tb = _anActiveId ? _anTabs.find(x => x.id === _anActiveId) : null;
        if (tb) { _anRenderStrip(); _anApplySeed(tb); }
        else if (!_anTabs.length) _anShowEmpty();
      }
      if (name !== "timemap" && typeof stopTmapPlay === "function") stopTmapPlay();  // don't animate a hidden tab
      startLive(name, {loaderJustRan: justLoaded});      // live status for the active tab
      document.body.classList.remove("nav-open");       // close mobile drawer
      closePalette();
      const m = document.querySelector("main"); if (m) m.scrollTop = 0;
      window.scrollTo(0, 0);
      // Each user tab-switch PUSHES a history entry so the browser Back button
      // moves between visited tabs (it used to replaceState, leaving no entries —
      // so Back escaped the app, landing on /unlock). popstate re-renders without
      // re-pushing; the initial load (below) replaces, so /home isn't a dead Back.
      if (location.hash !== "#" + name) {
        if (push) history.pushState(null, "", "#" + name);
        else history.replaceState(null, "", "#" + name);
      }
    }
    document.querySelectorAll(".nav-item[data-tab]").forEach(b =>
      b.addEventListener("click", () => showTab(b.dataset.tab)));
    // Back/Forward navigates the tab history (render only — the URL already moved).
    window.addEventListener("popstate", () =>
      showTab((location.hash || "#home").slice(1), false));
    // imp-ghost-modal-after-back (P1): no popstate listener anywhere closed an open
    // <dialog> -- browser Back while e.g. #ux-export was open left the tab underneath
    // repainted while the dialog's native modal top-layer backdrop stayed active,
    // blocking every click with no visual cue (only Escape recovered). Close EVERY
    // open dialog on Back/Forward via the one shared native mechanism -- this covers
    // all of them (#ux-import/#ux-export/#chart-enlarge/#synth-window/#link-preview/
    // #wiki-tc/#folder-picker/#net-consent/#guide-wizard/#corpus-win), not just one.
    //
    // A BARE .close() is not enough: per the <dialog> spec it fires only "close",
    // never "cancel" -- and #net-consent's ensureOnline() Promise only ever resolves
    // via its ok/cancel click handlers OR dlg.oncancel (the same for #guide-wizard's
    // closeGuide bookkeeping, wired to "cancel"). A bare .close() would silently
    // ORPHAN that Promise forever (every ensureOnline() caller hangs with no error),
    // and leave the guide marked not-done. Dispatch a synthetic "cancel" first (the
    // same signal Escape sends) so each dialog's own resolve/cleanup path runs --
    // resolving #net-consent as `false` ("stay offline"), the same safe default as
    // Esc -- THEN force-close (a no-op if the cancel handler already closed it).
    window.addEventListener("popstate", () =>
      document.querySelectorAll("dialog[open]").forEach((d) => {
        d.dispatchEvent(new Event("cancel", {cancelable: true}));
        d.close();
      }));

    // -- Appearance / customization (local-only, never transmitted) --------- //
    const UI_KEY = "oo.ui";
    const UI_DEFAULTS = {theme:"ink", accent:"", density:"comfortable", face:"", sidebar:"expanded"};
    const THEMES = [
      {id:"ink",name:"Ink",c:"#5b9dd9"}, {id:"slate",name:"Slate",c:"#7aa2f7"},
      {id:"midnight",name:"Midnight",c:"#8b7dff"}, {id:"arctic",name:"Arctic",c:"#88c0d0"},
      {id:"cyber",name:"Cyber",c:"#22d3ee"}, {id:"forest",name:"Forest",c:"#6fbf73"},
      {id:"aubergine",name:"Aubergine",c:"#c084fc"}, {id:"garnet",name:"Garnet",c:"#d96c7f"},
      {id:"solar",name:"Solar",c:"#b58900"}, {id:"sepia",name:"Sepia",c:"#d8a657"},
      {id:"terminal",name:"Terminal",c:"#36d97a"}, {id:"contrast",name:"Contrast",c:"#ffd400"},
      {id:"light",name:"Light",c:"#2f6fb3"}, {id:"mist",name:"Mist",c:"#5e81ac"},
      {id:"dawn",name:"Dawn",c:"#b4637a"}, {id:"mint",name:"Mint",c:"#2e7d5b"},
      {id:"paper",name:"Paper",c:"#9a6a2f"}, {id:"system",name:"System",c:"#8c95a6"},
    ];
    const ACCENTS = ["", "#5b9dd9", "#7aa2f7", "#8b7dff", "#36d97a", "#e0698f", "#d9a441", "#e8743b", "#2bb3a3"];
    // Bundled OFL typefaces (/static/fonts). "" = the theme's own font; a pick
    // overrides every theme. Variable fonts carry the full weight range
    // (Inter/Outfit go down to Thin 100 — the maintainer's modern-thin ask).
    const FACES = [
      {id:"", name:"Theme default", ff:""},
      {id:"cantarell", name:"Cantarell", ff:'"Cantarell", system-ui, sans-serif'},
      {id:"inter", name:"Inter", ff:'"Inter", system-ui, sans-serif'},
      {id:"outfit", name:"Outfit", ff:'"Outfit", system-ui, sans-serif'},
      {id:"manrope", name:"Manrope", ff:'"Manrope", system-ui, sans-serif'},
      {id:"serif", name:"Source Serif", ff:'"Source Serif 4", Georgia, serif'},
      {id:"mono", name:"JetBrains Mono", ff:'"JetBrains Mono", ui-monospace, monospace'},
    ];

    function getUi() { try { return {...UI_DEFAULTS, ...JSON.parse(localStorage.getItem(UI_KEY) || "{}")}; }
      catch { return {...UI_DEFAULTS}; } }
    function saveUi(ui) { localStorage.setItem(UI_KEY, JSON.stringify(ui)); }

    function applyThemeAttr(theme) {
      const eff = theme === "system" ? (_media && _media.matches ? "light" : "")
                : theme === "ink" ? "" : theme;
      const r = document.documentElement;
      if (eff) r.setAttribute("data-theme", eff); else r.removeAttribute("data-theme");
    }
    function applyUi(ui) {
      const r = document.documentElement;
      applyThemeAttr(ui.theme);
      if (ui.accent) r.style.setProperty("--accent", ui.accent); else r.style.removeProperty("--accent");
      const face = FACES.find(f => f.id === (ui.face || ""));
      if (face && face.ff) r.style.setProperty("--ff", face.ff); else r.style.removeProperty("--ff");
      if (ui.density === "compact") r.setAttribute("data-density", "compact"); else r.removeAttribute("data-density");
      if (ui.sidebar === "collapsed") r.setAttribute("data-sidebar", "collapsed"); else r.removeAttribute("data-sidebar");
      // The sidebar-visibility feature was removed (#17, 2026-06-22): the flat nav is
      // always complete (every tab also reachable via the palette), so no nav-item is
      // ever hidden here. A legacy ui.hidden in stored prefs is simply ignored.
    }
    function setTheme(t)   { const u = getUi(); u.theme = t;   saveUi(u); applyUi(u); buildDrawer(); syncThemeSelect(); }
    function setAccent(a)  { const u = getUi(); u.accent = a;  saveUi(u); applyUi(u); buildDrawer(); }
    function setDensity(d) { const u = getUi(); u.density = d; saveUi(u); applyUi(u); buildDrawer(); }
    function setFace(f)    { const u = getUi(); u.face = f;    saveUi(u); applyUi(u); buildDrawer(); }
    function setSidebar(s) { const u = getUi(); u.sidebar = s; saveUi(u); applyUi(u); buildDrawer(); }
    function toggleSidebar(){ setSidebar(getUi().sidebar === "collapsed" ? "expanded" : "collapsed"); }
    function resetUi() { localStorage.removeItem(UI_KEY); applyUi(getUi()); buildDrawer(); syncThemeSelect();
      toast("Appearance reset to defaults."); }
    // theme-select-lossy-overwrite (P1): the Settings -> General panel's #set-theme
    // select is a lossy 3-way dark/light/system BUCKET of the full 17/18-theme value
    // (Settings -> Graphics is the authoritative picker). _lastSyncedThemeBucket
    // remembers which bucket syncThemeSelect() just assigned, so saveSettings() can
    // tell "the user left this alone" (skip re-applying the bucket default) apart
    // from "the user actually picked a different bucket here" (honor it).
    let _lastSyncedThemeBucket = null;
    function syncThemeSelect() { const t = getUi().theme; const sel = $("set-theme");
      const lightish = ["light", "paper", "mist", "dawn", "mint"];
      const bucket = (t === "system" ? "system" : lightish.includes(t) ? "light" : "dark");
      if (sel) sel.value = bucket;
      _lastSyncedThemeBucket = bucket; }

    // Appearance now lives in Settings → Appearance (the old drawer is gone).
    // openDrawer() is kept as the single "take me to appearance" entry point so the
    // command palette and any deep link still work; closeDrawer() is a safe no-op.
    function openDrawer()  { showTab("settings"); (_setSubtabs || {select: showSetCat}).select("graphics"); }
    function closeDrawer() { /* drawer removed — appearance is a Settings section */ }

    // -- Keyboard shortcuts (local-only, rebindable; UI-shell §4) ----------- //
    // The global shortcuts are stored on THIS DEVICE (localStorage), never transmitted.
    // The command palette (Ctrl/⌘-K) is bound by default; the rest are opt-in (default
    // unset) so a fresh install never hijacks a keystroke. One dispatcher reads the
    // bindings, so a rebind takes effect immediately without reloading.
    const KEYS_KEY = "oo.keys";
    const KB_DEFAULTS = { palette: "Mod+K", home: "", settings: "", airplane: "", help: "" };
    function getKeys() { try { return {...KB_DEFAULTS, ...JSON.parse(localStorage.getItem(KEYS_KEY) || "{}")}; }
      catch { return {...KB_DEFAULTS}; } }
    function saveKeys(k) { localStorage.setItem(KEYS_KEY, JSON.stringify(k)); }
    // Normalize a keydown into a canonical combo string ("Mod+K", "Alt+Shift+H"). Ctrl and
    // Cmd both fold to "Mod" (cross-platform). Returns "" while only a modifier is held.
    function _kbCombo(e) {
      const k = e.key;
      if (!k || ["Control", "Shift", "Alt", "Meta", "OS", "Dead"].includes(k)) return "";
      const parts = [];
      if (e.ctrlKey || e.metaKey) parts.push("Mod");
      if (e.altKey) parts.push("Alt");
      if (e.shiftKey) parts.push("Shift");
      parts.push(k.length === 1 ? k.toUpperCase() : k);
      return parts.join("+");
    }
    function _kbShow(c) { return c ? c.replace("Mod", "Ctrl/⌘") : ""; }
    function _kbInField(el) {
      const tag = el && el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el && el.isContentEditable);
    }
    function _kbActions() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return [
        { id: "palette",  label: t("Open the command palette"), always: true, run: () => openPalette() },
        { id: "home",     label: t("Go to Home"),               run: () => showTab("home") },
        { id: "settings", label: t("Open Settings"),            run: () => showTab("settings") },
        { id: "airplane", label: t("Toggle airplane mode"),     run: () => { if (typeof toggleNetwork === "function") toggleNetwork(); } },
        { id: "help",     label: t("Open Help"),                run: () => showTab("help") },
      ];
    }
    // The single global keydown dispatcher: Escape closes overlays; a bound combo runs its
    // action. A plain-key binding never fires while typing in a field; the palette (Mod-combo)
    // always may. Ctrl/⌘-K keeps its default behaviour unless the user rebinds it.
    function _kbDispatch(e) {
      if (e.key === "Escape") { closePalette(); closeDrawer(); document.body.classList.remove("nav-open"); return; }
      if (_kbRecording) return;   // a rebind capture is in progress
      const combo = _kbCombo(e); if (!combo) return;
      const binds = getKeys(), field = _kbInField(e.target);
      for (const a of _kbActions()) {
        if (binds[a.id] !== combo) continue;
        if (field && !a.always) continue;
        e.preventDefault(); a.run(); return;
      }
    }
    // Settings → Shortcuts: list the shortcuts + rebind the global ones (the recorder
    // captures the next keystroke). Reference rows document the fixed contextual keys.
    let _kbRecording = null;
    function loadShortcuts() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("kb-panel"); if (!host) return;
      const binds = getKeys();
      const rows = _kbActions().map(a => {
        const cur = binds[a.id];
        const chip = cur
          ? `<span class="kb-chip">${esc(_kbShow(cur))}</span>`
          : `<span class="muted">${esc(t("Not set"))}</span>`;
        return `<tr><td>${esc(a.label)}</td><td>${chip}</td>
          <td style="white-space:nowrap">
            <button class="secondary tiny" data-kb-change="${esc(a.id)}">${esc(t("Change"))}</button>
            <button class="secondary tiny" data-kb-clear="${esc(a.id)}"${cur ? "" : " disabled"}>${esc(t("Clear"))}</button>
          </td></tr>`;
      }).join("");
      const ref = [
        [t("Close overlays and dialogs"), "Esc"],
        [t("Move within lists and subtabs"), "← → ↑ ↓"],
        [t("Submit search / run the selection"), "Enter"],
      ].map(([lbl, k]) => `<tr><td>${esc(lbl)}</td><td><span class="kb-chip">${esc(k)}</span></td><td class="muted">${esc(t("Fixed"))}</td></tr>`).join("");
      host.innerHTML =
        `<table><thead><tr><th>${esc(t("Action"))}</th><th>${esc(t("Shortcut"))}</th><th></th></tr></thead><tbody>${rows}</tbody></table>
         <div style="margin:8px 0"><button class="secondary tiny" onclick="kbReset()">${esc(t("Reset to defaults"))}</button></div>
         <h3 style="margin-top:14px;font-size:14px">${esc(t("Fixed shortcuts"))}</h3>
         <p class="hint muted">${esc(t("These contextual keys are always available and are not rebindable."))}</p>
         <table><tbody>${ref}</tbody></table>`;
      host.querySelectorAll("[data-kb-change]").forEach(b =>
        b.addEventListener("click", () => kbRecord(b.getAttribute("data-kb-change"), b)));
      host.querySelectorAll("[data-kb-clear]").forEach(b =>
        b.addEventListener("click", () => kbClear(b.getAttribute("data-kb-clear"))));
    }
    function kbRecord(id, btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (_kbRecording) return;
      _kbRecording = id; btn.textContent = t("Press a key…"); btn.classList.add("kb-rec");
      function done() { document.removeEventListener("keydown", onKey, true); _kbRecording = null; }
      function onKey(e) {
        e.preventDefault(); e.stopPropagation();
        if (e.key === "Escape") { done(); loadShortcuts(); return; }   // cancel the capture
        const combo = _kbCombo(e); if (!combo) return;                 // wait for a real key
        const binds = getKeys();
        Object.keys(binds).forEach(k => { if (k !== id && binds[k] === combo) binds[k] = ""; });  // no dup
        binds[id] = combo; saveKeys(binds); done(); loadShortcuts();
      }
      document.addEventListener("keydown", onKey, true);   // capture: beats the global dispatcher
    }
    function kbClear(id) { const b = getKeys(); b[id] = ""; saveKeys(b); loadShortcuts(); }
    function kbReset() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      saveKeys({...KB_DEFAULTS}); loadShortcuts(); toast(t("Shortcuts reset to defaults."));
    }

    // Settings sections (Appearance · General · Wikipedia · Data · Safety).
    function showSetCat(cat) {
      // Button/ARIA state is owned by the ooSubtabs component; this callback
      // switches the panel + does the section's one-time setup.
      document.querySelectorAll("#tab-settings .set-view").forEach(v =>
        v.style.display = (v.id === "set-" + cat) ? "" : "none");
      if (cat !== "advanced") stopSchedRatePoll();  // the scheduler panel moved into Advanced
      // Graphics = Appearance + the alternative-interfaces gallery, fused (remark 11).
      if (cat === "graphics") {
        buildDrawer();                                                    // (re)paint theme/accent state
        if (window.OOGUIs && OOGUIs.renderGallery) OOGUIs.renderGallery();  // the GUIs gallery
      }

      if (cat === "agenda" && !AG.cals.length) loadAgenda();  // calendars/directory live here now
      // loadLlmPrompts/loadCustomPrompts are NOT here any more: their panels moved to
      // Advanced → AI and load when that section is expanded (2026-08-09).
      if (cat === "models") { loadOllamaInstall(); loadLlmModels(); loadLlmHealth(); _llmPullStartPoll(); loadLangDetectCount(); loadAiBackendPanel(); loadVllmStatusPanel(); loadAiSetup(); loadAiHero(); loadAiStore(); loadModelCatalog(); syncKeywordTriageToggle(); syncSourceTagsToggle(); syncPerceptionExtractToggle(); loadPerceptionGate(); syncAiCoordinator(); }  // LLM-management subtab (Q6) — also offer the binary installer + re-check the pill + show any in-progress pull + the dual-backend panel (B1/B2/B4) + the B5 progressive-sweep toggles + the B6 perception-extract toggle/gate
      if (cat === "advanced") _advWire();             // Collection / Sources / Keywords, lazily per section
      if (cat === "general") loadShortcuts();         // the shortcuts panel moved into General (2026-07-31)
      if (cat === "cards") loadCardCatalog();     // the Leads catalogue (PR-7): lazy, one loopback read
      if (cat === "wikipedia") loadWiki();            // moved Wikipedia tracking onShow (dumps load via loadSettings)
      if (cat === "offlinemap") loadOsmMap();         // OSM offline-map region downloads (Group M)
      // The newsletter/PDF import panels moved into Data & backup (2026-07-31). Both
      // calls are cheap and loopback-only -- a count query and a job-status poll -- so
      // they load with the subtab rather than needing the Advanced lazy treatment.
      if (cat === "data") { loadNewsletterRemoveCount(); _folderImportStartPoll(); }
    }

    // ADVANCED subtab (2026-07-31 Settings review): Collection, Sources and Keywords moved
    // into folded <details> sections. Their loaders run when a SECTION IS EXPANDED, never
    // when the subtab is selected -- folded must not mean fetched. That distinction is not
    // cosmetic here: the source catalog can hold ~46k rows, and loading all three eagerly
    // would make opening Advanced the most expensive click in Settings.
    const _ADV_LOADERS = {
      collect:  () => { loadScheduler(); },
      // The system prompts and the operator's own extractors (maintainer 2026-08-09:
      // "move the entire Behaviour & prompts section to an AI section in the advanced
      // subtab"). They are a developer surface -- four full prompt textareas and a CRUD
      // form -- and having them under the AI tab made the page a console for a reader
      // who only wanted to switch AI on. Nothing is lost: both panels moved WHOLE, and
      // they load on expand rather than with the subtab.
      // The three progressive-sweep panels live in THIS section too, and their syncs were
      // left behind on the AI subtab when the markup moved -- so opening the section that
      // contains them never asked whether a run existed, and the download links (rendered
      // by the sync) could not appear where the panels actually are. Field report
      // 2026-08-13: "can't find your keyword triage button". A moved panel takes its
      // loader with it.
      ai:       () => {
        loadLlmPrompts(); loadCustomPrompts();
        syncKeywordTriageToggle(); syncSourceTagsToggle(); syncPerceptionExtractToggle();
      },
      sources:  () => { loadSrcFacets(); loadManagedSources(); loadCandidates(); },
      // SAFETY, folded in from its retired subtab (rulings 26/42). Its loaders came WITH
      // it: on the subtab they ran on select, and here they run on EXPAND -- folded must
      // not mean fetched. loadAtRestState is a loopback read of the store's encryption
      // state; it is cheap, but running it because someone opened Advanced to change a
      // scheduler knob is still work nobody asked for.
      safety:   () => { loadAtRestState(); },
      // UNINSTALL & WIPE, its own section (ruling 26). onUninstallMode paints the preview
      // of what the CURRENT mode would delete -- it must run before the panel is read, or
      // the reader sees an empty preview beside an irreversible button.
      uninstall: () => { onUninstallMode(); },
      // Both quality gates + the scope toggles + the bulk catch-up (absorbed from the
      // Sources section, which now points here — never two homes for one control).
      qualification: () => { loadQualificationGates(); loadQualifyBulk(); },
      // The official-statistics producer DIRECTORY is source management, so it lives here;
      // the FIGURES surface moved to Governments → Statistics (2026-07-31).
      stats:    () => { loadStatAgencies(); },
      // loadKeywordFilter moved off loadSettings with its panel, so it loads here too.
      keywords: () => { loadKeywordExplorer(); loadFamilyCuration(); loadSupergroupCuration(); loadKeywordFilter(); },
      // The ~500-feed calendar catalogue: plumbing, so it moved out of the Agenda
      // subtab (invariant #8). It no longer loads with the agenda — only on expand.
      calendars: () => { loadFeedDir(); },   // loadFeedDir renders the user calendars too
      // The Bulletin (§16): last section, folded, and its availability check +
      // edition list run on EXPAND like the rest. Both are loopback.
      bulletin: () => { loadBulletin(); },
    };
    // Deep-link into one Advanced section. The old showTab("ingest") / showTab("sources")
    // redirects pointed at subtabs that no longer exist, so every palette entry and
    // "Collect now" button that used them would have landed on nothing. They now select
    // Advanced and OPEN the right section -- which also fires its toggle listener, so the
    // section loads exactly as if the user had opened it by hand.
    function _openAdvanced(section) {
      try { _setSubtabs.select("advanced"); } catch (e) { showSetCat("advanced"); }
      _advWire();
      const d = document.querySelector(`#set-advanced details.adv-sec[data-adv="${section}"]`);
      if (d && !d.open) d.open = true;
      if (d) d.scrollIntoView({block: "start"});
    }
    function _advWire() {
      document.querySelectorAll("#set-advanced details.adv-sec").forEach(d => {
        if (d.dataset.advWired === "1") return;
        d.dataset.advWired = "1";
        d.addEventListener("toggle", () => {
          if (!d.open || d.dataset.advLoaded === "1") return;
          d.dataset.advLoaded = "1";                       // load once, keep the data on re-collapse
          const load = _ADV_LOADERS[d.dataset.adv];
          if (!load) return;
          // One section failing must not take the others down with it.
          try { load(); } catch (e) { console.error("advanced section failed to load", d.dataset.adv, e); }
        });
      });
    }

    function buildDrawer() {
      const ui = getUi();
      $("dr-themes").innerHTML = THEMES.map(t =>
        `<button class="theme-card ${t.id === ui.theme ? "sel" : ""}" onclick="setTheme('${t.id}')">
           <span class="tdot" style="background:${t.c}"></span>${esc(t.name)}</button>`).join("");
      $("dr-accents").innerHTML = ACCENTS.map(a =>
        `<button class="sw ${a === ui.accent ? "sel" : ""}" title="${a || "Theme default"}"
           onclick="setAccent('${a}')" style="background:${a || "linear-gradient(135deg,var(--muted),var(--accent))"}"></button>`).join("");
      $("dr-density").innerHTML = ["comfortable", "compact"].map(d =>
        `<button class="${d === ui.density ? "sel" : ""}" onclick="setDensity('${d}')">${d[0].toUpperCase() + d.slice(1)}</button>`).join("");
      $("dr-faces").innerHTML = FACES.map(f =>
        `<button class="${f.id === (ui.face || "") ? "sel" : ""}" onclick="setFace('${f.id}')"
           style="${f.ff ? "font-family:" + esc(f.ff) : ""}">${esc(f.name)}</button>`).join("");
      $("dr-sidebar").innerHTML = [["expanded", "Expanded"], ["collapsed", "Collapsed"]].map(([v, l]) =>
        `<button class="${v === ui.sidebar ? "sel" : ""}" onclick="setSidebar('${v}')">${l}</button>`).join("");
      // (The "Tools shown in the sidebar" checklist was removed — #17, 2026-06-22.)
    }

    // -- Command palette = the OMNIBAR (Ctrl/⌘-K; T13 slice 1) -------------- //
    // Static commands (pages/actions/docs) match instantly; from 2 typed
    // characters the palette ALSO federates over the indexed data surfaces
    // (articles via FTS5, keywords, sources, wiki pages, law documents) —
    // debounced and sequence-guarded, never scan-on-type: the endpoint is
    // index-backed and discloses the true totals behind the first three.
    let _palItems = [], _palFiltered = [], _palSel = 0;
    let _omniLive = null, _omniTimer = null, _omniSeq = 0;
    function palCommands() {
      const pages = NAV.map(n => ({grp:"Pages", label:n.label, sub:n.grp, run:() => showTab(n.id)}));
      const actions = [
        {grp:"Actions", label:"Run a search", sub:"Search", run:() => { showTab("search"); setTimeout(() => $("q").focus(), 50); }},
        {grp:"Actions", label:"Collect now (one scraper pass)", sub:"Collect", run:() => { showTab("ingest"); schedulerRunNow(); }},
        {grp:"Actions", label:"Track Wikipedia now", sub:"Wikipedia", run:() => { showTab("wiki"); trackWikiNow(); }},
        {grp:"Actions", label:"Export / Back up…", sub:"Data & backup", run:() => { showTab("settings"); openUnifiedExport(); }},
        {grp:"Actions", label:"Open the User Manual", sub:"Help", run:() => { showTab("help"); openDoc("user-manual"); }},
        {grp:"Actions", label:"Open Settings", sub:"System", run:() => showTab("settings")},
        {grp:"Actions", label:"Customize appearance", sub:"Theme", run:() => openDrawer()},
        {grp:"Actions", label:"API reference (Swagger)", sub:"System", run:() => window.open("/docs", "_blank")},
      ];
      const docs = (_docList || []).map(d => ({grp:"Documentation", label:d.title, sub:"Doc",
        run:() => { showTab("help"); openDoc(d.slug); }}));
      return [...pages, ...actions, ...docs];
    }
    function openPalette() {
      _palItems = palCommands();
      _omniLive = null;
      _palPrevFocus = document.activeElement;  // a11y: restore focus on close (OO-D13-001)
      $("palOverlay").classList.add("open"); $("palette").classList.add("open");
      const i = $("pal-input"); i.value = ""; renderPalette(); setTimeout(() => i.focus(), 30);
    }
    function closePalette() {
      $("palOverlay").classList.remove("open"); $("palette").classList.remove("open");
      if (_palPrevFocus && _palPrevFocus.focus) {
        try { _palPrevFocus.focus(); } catch (_) { /* opener gone */ }
        _palPrevFocus = null;
      }
    }
    // The live half of the omnibar: items built from /api/search/omni results.
    // Each carries a run() like any static command, so keyboard navigation and
    // Enter work unchanged. Group headers disclose the TRUE total behind the
    // first three (the display bound never hides the magnitude).
    function _omniItems(q) {
      if (!_omniLive || _omniLive.q !== q) return [];
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const head = (label, g) => label + (g.total > (g.items || []).length ? ` · ${g.total} ${t("matches in total")}` : "");
      const out = [];
      (_omniLive.groups || []).forEach(g => {
        const items = g.items || [];
        if (!items.length) return;
        if (g.kind === "articles") {
          const grp = head(t("Articles"), g);
          items.forEach(it => out.push({grp, label: it.title || ("#" + it.article_id),
            sub: (it.published_at || "").slice(0, 10) || t("article"),
            run: () => window.open(it.url, "_blank")}));
        } else if (g.kind === "keywords") {
          const grp = head(t("Keywords"), g);
          items.forEach(it => {
            // S3: keyword -> super-group navigation. Plural membership renders every
            // group name (never picks one); the palette row's single action still
            // opens the keyword's own corpus window — the group VIEW is one more
            // click away via the Keywords-subtab chip (richer HTML there).
            const sgNote = (it.supergroups && it.supergroups.length)
              ? " · " + t("part of") + " ⊕ " + it.supergroups.map(g2 => g2.name).join(", ")
              : "";
            out.push({grp,
              label: it.term + (it.frequency ? ` (${it.frequency})` : ""),
              sub: t("opens its corpus window") + sgNote,
              run: () => openCorpus(it.normalized_term)});
          });
        } else if (g.kind === "sources") {
          const grp = head(t("Sources"), g);
          items.forEach(it => out.push({grp, label: it.name, sub: it.domain || "",
            run: () => showTab("sources")}));
        } else if (g.kind === "wiki") {
          const grp = head(t("Wikipedia"), g);
          // A content hit carries a reader url (open the LOCAL article); a watched-page
          // title hit (no url) jumps to the Wikipedia settings/tracker.
          items.forEach(it => out.push({grp, label: it.title, sub: it.wiki || "",
            run: it.url ? (() => window.open(it.url, "_blank")) : (() => showTab("wiki"))}));
        } else if (g.kind === "law") {
          const grp = head(t("World law"), g);
          items.forEach(it => out.push({grp, label: it.title,
            sub: (it.jurisdiction || "").toUpperCase(),
            run: () => showTab("law")}));
        }
      });
      return out;
    }
    function _omniFetch(q) {
      clearTimeout(_omniTimer);
      _omniTimer = setTimeout(async () => {
        const seq = ++_omniSeq;
        try {
          const d = await api("/api/search/omni?q=" + encodeURIComponent(q));
          if (seq !== _omniSeq) return;  // a newer keystroke superseded this reply
          _omniLive = d;
          if ($("palette").classList.contains("open") && $("pal-input").value.trim() === q) renderPalette();
        } catch (_e) { /* static commands still work; the server logs the why */ }
      }, 160);
    }
    function renderPalette() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const raw = $("pal-input").value.trim();
      const q = raw.toLowerCase();
      const statics = _palItems.filter(it => !q ||
        it.label.toLowerCase().includes(q) || (it.sub || "").toLowerCase().includes(q));
      let live = [];
      if (raw.length >= 2) {
        live = _omniItems(raw);
        if (!_omniLive || _omniLive.q !== raw) _omniFetch(raw);
        // Ruled: Enter -> the corpus/analysis window (default), now opening in a NEW
        // BROWSER TAB (field remark 9). The in-SPA spawn (openAnalysisFor) stays the
        // default for clicking a specific result + every card/commodity entry; the
        // Boolean Search tab is still one item away (nothing lost).
        live.unshift({grp: t("Search"), label: `${t("Run the full Boolean search for")} “${raw}”`,
          sub: "", run: () => { showTab("search"); setTimeout(() => { $("q").value = raw; doSearch(); }, 60); }});
        live.unshift({grp: t("Search"), label: `${t("Analysis")}: “${raw}”`,
          sub: "↵ ↗", run: () => openAnalysisInNewTab(raw)});
      }
      _palFiltered = [...statics, ...live];
      _palSel = 0;
      let html = "", lastGrp = null;
      _palFiltered.forEach((it, i) => {
        if (it.grp !== lastGrp) { html += `<div class="pal-group">${esc(it.grp)}</div>`; lastGrp = it.grp; }
        html += `<div class="pal-item ${i === 0 ? "sel" : ""}" data-i="${i}" onclick="palRun(${i})">
          ${esc(it.label)}<span class="pal-sub">${esc(it.sub || "")}</span></div>`;
      });
      $("pal-list").innerHTML = html || `<div class="pal-group">No matches</div>`;
    }
    function palMove(d) {
      if (!_palFiltered.length) return;
      _palSel = (_palSel + d + _palFiltered.length) % _palFiltered.length;
      document.querySelectorAll(".pal-item").forEach(el =>
        el.classList.toggle("sel", +el.dataset.i === _palSel));
      const cur = document.querySelector(".pal-item.sel"); if (cur) cur.scrollIntoView({block:"nearest"});
    }
    function palRun(i) { const it = _palFiltered[i]; if (it) { closePalette(); it.run(); } }
    function palKey(e) {
      if (e.key === "ArrowDown") { e.preventDefault(); palMove(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); palMove(-1); }
      else if (e.key === "Enter") { e.preventDefault(); palRun(_palSel); }
      else if (e.key === "Escape") { closePalette(); }
      else if (e.key === "Tab") { _trapTab($("palette"), e); }  // a11y trap (OO-D13-001)
    }

    // -- Home dashboard ----------------------------------------------------- //
    // Locale-aware date/time in the APP language (not the browser locale), full
    // month name. Shared formatter (parallels the smart units formatter); the
    // i18n DOM walker cannot reach JS-built date strings, so format them here.
    function fmtDateTime(ts) {
      const d = new Date(ts); if (isNaN(d)) return "";
      try {
        return new Intl.DateTimeFormat(OOI18N.current(),
          { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(d);
      } catch (e) { return d.toLocaleString(); }
    }
    // Human, translated labels for the at-a-glance stat keys. The server keys are
    // raw snake_case identifiers (the Database tab + cache rely on them), so the
    // Home strip maps them to translated labels in the UI layer; an unknown key
    // falls back to a prettified form so a new server key never shows raw.
