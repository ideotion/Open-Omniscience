/* Open Omniscience — the declarative event binding that replaced inline handlers.

   WHY (Q1127 = a, 0.5 gate row I): an inline handler (an on-click attribute) is script the browser
   runs from an attribute, so the CSP had to keep script-src 'unsafe-inline' — which also
   lets any injected markup run script. The handlers are now written as
       data-on-click="showTab('settings')"
   and ONE delegated listener per event type (here) runs them. Nothing is evaluated: the
   attribute is PARSED by the small grammar below, and it can only call a function whose
   name is in OO_ACTIONS, with DATA for arguments. That is the point — a generic evaluator
   of attribute strings would be an inline handler under another name (a "script gadget"),
   and dropping 'unsafe-inline' beside one would be security theatre.

   THE GRAMMAR (one attribute value):
     seq   := stmt (";" stmt)* ";"?
     stmt  := "return false"                  -> preventDefault(), as in an inline handler
            | call
     call  := NAME "(" [arg ("," arg)*] ")"   NAME must be in OO_ACTIONS
     arg   := string ('…' or "…", JS escapes) | number | true | false | null | undefined
            | [ … ] | { key: arg, … }         (JSON-ish, keys bare or quoted)
            | this | this.PROP                the element carrying the attribute
            | event | event.PROP             the event
            | call                            a nested allowed call, e.g. anParams()
   A keydown/keyup/keypress binding may carry data-on-key="Enter Space Escape": it then
   runs only for those keys ("Space" is " ").

   PHASE: one CAPTURE listener per event type on the root element, walking the event's path
   from the target outward and running each element's binding, stopping where a binding
   called event.stopPropagation() — the order and the stop an inline handler had. An
   event that does not bubble (focus, blur, load, error, toggle, close, mouseenter…) runs
   only the target's own binding, as its inline handler did. A binding that throws is
   logged and does not stop the next one, like an inline handler's error. */
(function () {
  "use strict";

  const EVENTS = [
    "click", "dblclick", "contextmenu", "change", "input", "submit", "reset", "search",
    "keydown", "keyup", "keypress", "focus", "blur", "focusin", "focusout",
    "mouseover", "mouseout", "mouseenter", "mouseleave", "mousedown", "mouseup", "wheel",
    "scroll", "load", "error", "toggle", "close", "cancel",
    "dragstart", "dragover", "dragenter", "dragleave", "drop", "dragend",
    "pointerdown", "pointerup", "touchstart", "touchend",
  ];

  // Parsed bindings are cached by their source text; a binding string is small and the
  // set of distinct ones is bounded by the markup, so the cache cannot grow without end.
  const _cache = new Map();

  function parse(src) {
    let i = 0;
    const n = src.length;
    const err = (msg) => { throw new SyntaxError(`data-on: ${msg} at ${i} in ${JSON.stringify(src)}`); };
    const ws = () => { while (i < n && /\s/.test(src[i])) i++; };
    const ident = () => {
      const m = /^[A-Za-z_$][\w$]*/.exec(src.slice(i));
      if (!m) err("expected a name");
      i += m[0].length;
      return m[0];
    };
    const expect = (c) => { ws(); if (src[i] !== c) err(`expected ${c}`); i++; };
    function str(q) {
      i++;
      let out = "";
      while (i < n && src[i] !== q) {
        if (src[i] === "\\") {
          i++;
          const c = src[i++];
          if (c === "u") { out += String.fromCharCode(parseInt(src.substr(i, 4), 16)); i += 4; }
          else out += ({n: "\n", t: "\t", r: "\r", b: "\b", f: "\f", v: "\v", 0: "\0"})[c] ?? c;
        } else out += src[i++];
      }
      if (src[i] !== q) err("unterminated string");
      i++;
      return {k: "lit", v: out};
    }
    function arg() {
      ws();
      const c = src[i];
      if (c === "'" || c === '"') return str(c);
      if (c === "[") {
        i++; const items = []; ws();
        if (src[i] === "]") { i++; return {k: "arr", v: items}; }
        for (;;) { items.push(arg()); ws(); if (src[i] === ",") { i++; continue; } expect("]"); return {k: "arr", v: items}; }
      }
      if (c === "{") {
        i++; const props = []; ws();
        if (src[i] === "}") { i++; return {k: "obj", v: props}; }
        for (;;) {
          ws();
          const key = (src[i] === "'" || src[i] === '"') ? str(src[i]).v : ident();
          expect(":");
          props.push([key, arg()]); ws();
          if (src[i] === ",") { i++; continue; }
          expect("}"); return {k: "obj", v: props};
        }
      }
      const num = /^-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/.exec(src.slice(i));
      if (num) { i += num[0].length; return {k: "lit", v: Number(num[0])}; }
      const name = ident();
      if (name === "true") return {k: "lit", v: true};
      if (name === "false") return {k: "lit", v: false};
      if (name === "null") return {k: "lit", v: null};
      if (name === "undefined") return {k: "lit", v: undefined};
      if (name === "NaN") return {k: "lit", v: NaN};
      if (name === "this" || name === "event") {
        const path = [];
        while (src[i] === ".") { i++; path.push(ident()); }
        if (path.some((p) => p === "constructor" || p === "__proto__" || p === "prototype")) err("forbidden property");
        return {k: name, v: path};
      }
      ws();
      if (src[i] === "(") return call(name);
      err(`unknown value ${name}`);
    }
    function call(name) {
      if (!Object.prototype.hasOwnProperty.call(ACTIONS, name)) err(`${name} is not in OO_ACTIONS`);
      expect("(");
      const args = [];
      ws();
      if (src[i] === ")") { i++; return {k: "call", name, args}; }
      for (;;) { args.push(arg()); ws(); if (src[i] === ",") { i++; continue; } expect(")"); return {k: "call", name, args}; }
    }
    const stmts = [];
    for (;;) {
      ws();
      if (i >= n) break;
      if (src.startsWith("return false", i)) { i += 12; stmts.push({k: "retfalse"}); }
      else stmts.push(call(ident()));
      ws();
      if (i >= n) break;
      if (src[i] === ";") { i++; continue; }
      err("expected ;");
    }
    return stmts;
  }

  function evalArg(a, el, ev) {
    switch (a.k) {
      case "lit": return a.v;
      case "arr": return a.v.map((x) => evalArg(x, el, ev));
      case "obj": { const o = {}; for (const [k, v] of a.v) o[k] = evalArg(v, el, ev); return o; }
      case "this": return a.v.reduce((o, p) => (o == null ? o : o[p]), el);
      case "event": return a.v.reduce((o, p) => (o == null ? o : o[p]), ev);
      case "call": return run(a, el, ev);
    }
    return undefined;
  }

  function run(c, el, ev) {
    const fn = ACTIONS[c.name];
    const f = typeof fn === "function" ? fn : window[c.name];
    if (typeof f !== "function") {
      console.warn(`data-on: ${c.name} is not defined yet`);
      return undefined;
    }
    return f.apply(el, c.args.map((a) => evalArg(a, el, ev)));
  }

  function bindingFor(el, type) {
    const src = el.getAttribute("data-on-" + type);
    if (src == null) return null;
    let stmts = _cache.get(src);
    if (!stmts) { stmts = parse(src); _cache.set(src, stmts); }
    return stmts;
  }

  const KEY_ALIAS = {Space: " "};

  // The event as the binding's function sees it: the real event, except that
  // currentTarget is the element carrying the binding -- what it was for an inline
  // handler (the delegated listener's own currentTarget is the document). Methods are
  // bound to the real event, so preventDefault/stopPropagation act on it.
  function asSeenBy(ev, el) {
    return new Proxy(ev, {
      get(t, p) {
        if (p === "currentTarget") return el;
        const v = Reflect.get(t, p, t);
        return typeof v === "function" ? v.bind(t) : v;
      },
    });
  }

  function fire(el, type, realEv) {
    const ev = asSeenBy(realEv, el);
    let stmts;
    try { stmts = bindingFor(el, type); } catch (e) { console.error(e); return; }
    if (!stmts) return;
    if (type === "keydown" || type === "keyup" || type === "keypress") {
      const keys = el.getAttribute("data-on-key");
      if (keys && !keys.split(/\s+/).map((k) => KEY_ALIAS[k] || k).includes(ev.key)) return;
    }
    for (const s of stmts) {
      if (s.k === "retfalse") { ev.preventDefault(); continue; }
      // A call's return value is ignored, as an inline handler's expression statement's
      // was; only an explicit "return false" cancels the default.
      try { run(s, el, ev); } catch (e) { console.error(e); }
    }
  }

  function onEvent(ev) {
    const type = ev.type;
    const target = ev.target;
    if (!target || target.nodeType !== 1) {
      // window/document-level load/error etc. carry no binding
      if (!(target && target.nodeType === 9)) return;
    }
    if (!ev.bubbles) {
      if (target.nodeType === 1 && target.hasAttribute("data-on-" + type)) fire(target, type, ev);
      return;
    }
    const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
    for (const node of path) {
      if (!node || node.nodeType !== 1) continue;
      if (node.hasAttribute("data-on-" + type)) {
        fire(node, type, ev);
        if (ev.cancelBubble) break;
      }
    }
  }

  // The allowlist: every function a data-on-* binding may call, by name. It is resolved
  // against window at call time, so a module that loads after this file is fine; a name
  // that is not here is refused at parse time and logged, never evaluated. Kept sorted;
  // tests/test_inline_handler_ratchet.py asserts every name used in markup is listed and
  // every listed name is used.
  const ACTIONS = Object.create(null);
  const OO_ACTIONS = [
    "_anActivate", "_anArtGo", "_anClearSense", "_anCloseTab", "_anFormCounts", "_anPickSense",
    "_anSetCap", "_anSetExpand", "_anSetGroupByLang", "_anSetProvenance", "_anSortBy",
    "_anSortChanged", "_anToggleArtFacetChip", "_anToggleKwSort", "_conceptDrillCountry",
    "_feedExpand", "_feedSetOrder", "_libSetWindow", "_lvlCrumbFire", "_ooMapSignalAt",
    "_srcTrailToggleClass", "_synthCopy", "_synthCount", "_synthExport", "_synthRenderSelect",
    "_synthRun", "_synthSelectAll", "_uxImBackground", "_uxImRun", "_uxImScan", "_uxImStop",
    "_uxImVerify", "_uxPauseResume", "_uxRun", "addAnnotation", "addMarketRule", "addSource",
    "addToDraft", "addWikiPage", "agExcludeBulk", "agExcludeClear", "agNavShift", "agNavToday",
    "agOpenMonth", "agOpenMonthYear", "agOpenYear", "agPickDate", "agSetCat", "agShowDay",
    "agToggleExclude", "aiRunPrompt", "aiRunPromptStart", "aiStartNow", "altAct", "altDiscardBatch", "altMore", "anApplyArticlesFilter",
    "anFillTentative", "anMMset", "anMMsetScale", "anMMtoggleBig", "anParams", "anRelUpdateSel", "anSelectLens", "anTrendPick", "anTrendSetMode",
    "anchorRoot", "appShutdown", "applySrcFilters", "batchSelectAll", "batchToggle",
    "branchByFacet", "branchFromOrigin", "branchFromRelated", "branchSelectedRelated",
    "bulkJobCancel", "bulkJobClearDone", "bulkLlm", "bulkLlmRun", "bulkLlmStop", "bulkPanelHide",
    "bulletinDelete", "bulletinDownloadBundle", "bulletinGenerate", "bulletinLanguageReport",
    "bulletinNarrate", "bulletinOpen", "bulletinOpenFile", "bulletinPublish", "bulletinReview",
    "bulletinToggleSection", "bulletinToggleStory", "cancelP0Validation", "cancelPull",
    "candidateAct", "cardCollapse", "cardResetTunable", "cardSetEnabled", "cardWeatherFetch",
    "carouselGo", "carouselStep", "carouselToggle", "chartSymbol", "cleanupKeywords", "clearDraft",
    "clearIdxCompare", "clearSrcFilters", "closeDraft", "closePalette", "collapseAction",
    "collectToggle", "conjCombine", "conjContrast", "conjOpenCombined", "conjScope",
    "conjSearchNear", "copyDraft", "copyLlmPrompt", "createSuperGroup", "createWatch",
    "custodyGapCheck", "custodyGapRecord", "deleteDump", "deleteMarketRule", "deleteOsm",
    "deleteSource", "deleteStatSub", "deleteSuperGroup", "deleteWatch", "deleteWikiPage",
    "disableUnmanagedLanguages", "discoverSources", "discoverWorld", "dismissCard",
    "dismissRetiredMode", "doSearch", "downloadBackupFirst", "downloadDiagnosticsVolumes",
    "downloadKeywordParts",
    "dumpFtsBuild", "dumpFtsCancel", "dumpFtsClear", "dumpFtsOpen", "dumpFtsSearch", "dumpReadPage",
    "dumpReadView", "dumpSearchTitles", "editWatch", "encryptCorpus", "enlargeHomeTrend",
    "enlargeLibMetric", "enlargeLibQualification", "enlargeTrend", "enrichSourceTypes",
    "enrichSources", "evaluateWatches", "excludeKeyword", "expandCitedSource", "exploreTerm",
    "exportAnnotations", "exportCustody", "exportDraft", "exportEvidence", "exportMethods",
    "exportResults", "familyMerge", "familyResetGroup", "familySplit", "feedAction",
    "feedClearSeen", "feedReshuffle", "fetchStatFigure", "filterConceptBrowse", "filterDoc",
    "folderImportAction", "goldBuilderGrade", "goldBuilderKey", "goldBuilderLoad",
    "goldBuilderSave", "govLoadStandard", "govShowLaw", "govToggleAllAggregates",
    "importAnnotations", "importCustomFeed", "importFeed", "importIcsFile", "importIcsUrl",
    "importNewsletters", "importPdfFolder", "importPdfs", "importSources", "indexDetail",
    "ingestBatch", "ingestSource", "ingestStatSources", "ingestUrl", "installDefaultModel",
    "installOneModel", "installVllm", "jobCancel", "jobMove", "jobResume", "kbReset", "kxAddTag",
    "kxBackfill", "kxHide", "kxRemoveTag", "kxShowTag", "kxToggleTags", "launchOllama",
    "lawAddDocument", "lawSeed", "lawSetWatched", "lawSummarize", "lawTrack", "leadFlipFrom",
    "leadFlipKeyFrom", "livingShowDiff", "loadActors", "loadAlternates", "loadBuiltinStoplist", "loadChronology",
    "loadCitedSources", "loadConvergences", "loadFamilies", "loadFamilyCuration", "loadFeed",
    "loadGovAggregate", "loadGovCountry", "loadGovMap", "loadHomeLatest", "loadHomeRecentList",
    "loadIndicesData", "loadKeywordExplorer", "loadLaw", "loadLawChanges", "loadLemmaPreview",
    "loadLivingStream", "loadLunar", "loadMap", "loadMarketData", "loadPatternsGate", "loadProfile",
    "loadRevisionAnomalies", "loadRingGaps", "loadSessionForensics", "loadStatFigures",
    "loadSuperGroups", "loadSupergroupCuration", "loadTagCoverage", "loadTrends", "loadWikiChanges",
    "loadWikiTC", "lookupAnnotations", "lunarSyncDirection", "lunarTestTerm", "mbAnchorGrade",
    "mbAnchorKey", "mbAnchorKind", "mbAnchorsLoad", "mbAnchorsSave", "mbBuildBatch", "mbRun",
    "migrateOllamaStore", "mmExpand", "mmLevel", "mmReload", "mmView", "mmWindowChange",
    "onAiActivityToggle", "onFetchModeChange", "onUninstallMode", "ooFolderPicker",
    "ooFolderPickerUse", "ooMapCloseDetail", "openAnalysisFor", "openAnalysisForIds", "openCardCorpus",
    "openCardCorpusQuery", "openChannelCorpus", "openConceptMap", "openConjunctionLensChannel",
    "openCorpus", "openDoc",
    "openDraft", "openGuide", "openIdxComparison", "openInsightsTrends", "openLinkPreview",
    "openOsmObjectCard", "openPalette", "openPlaceCard", "openSettingsAgenda", "openSettingsOsm", "openSourcesForKeyword", "openSupergroup",
    "openTaskManager", "openTour", "openUnifiedExport", "openUnifiedImport", "openWikiTC", "openWorldMapAt",
    "openWorldMapHazards", "osmCountAdmin1", "osmHistoryDownload", "osmHistoryReadSize", "osmMove", "osmPickAdd", "osmPickAddCode", "osmPickRemove", "overlayAdopt", "overlayExport", "overlayMerge",
    "overlayRevert", "palKey", "panicWipe", "partsSaveNext", "partsSaveRest", "pauseDump", "pauseOsm", "pickLang",
    "pickTerm", "prepareOllamaInstall", "previewTargets", "promoteCitedSources", "pullMailbox",
    "pullModelFromBox", "qualSaveScope", "qualSaveToggle", "qualifyAssist", "qualifyBulkCancel",
    "qualifyBulkStart", "recheckOllama", "refreshDumpSizes", "refreshStatSubs", "releaseRunCancel",
    "releaseRunCollect", "releaseRunResume", "releaseRunStart", "releaseRunStatus",
    "reloadBatchPicker", "removeAnnotation", "removeAuthor", "removeDraftItem",
    "removeImportedNewsletters", "removeModel", "removeUserCalendar", "renderAgenda",
    "renderCoverageTable", "renderFeedDir", "renderGovCompare", "renderGovGroup", "renderGovMap",
    "renderPalette", "renderStatChart", "renderStatMap", "renderStorageFootprint",
    "renderWikiLanguages", "resetCustomPromptForm", "resetLlmPrompt", "resetMap", "resetUi",
    "resumeOsm", "retryFailedFeeds", "revertAllCollapse", "ringLoadStart", "runAiCheck",
    "runAiSetup", "runAllDiagnostics", "runFixity", "runIrEval", "runMarketRule",
    "runOllamaInstall", "runP0Validation", "runPerceptionEvalLive", "runSeriesCorpus",
    "saveAiSweepMembership", "saveCardSettings", "saveCustody", "saveCustomPrompt",
    "saveDiscoveryExternal", "saveDraftItemNote", "saveDraftTitle", "saveFetchMode",
    "saveImportCheckpointK", "saveKeywordFilter", "saveLaneBudget", "saveLlmBehaviour",
    "saveScheduler", "saveSettings", "schedSpeedLabel", "schedulerRunNow", "schedulerStart",
    "schedulerStop", "secureErase", "seedDefaults", "selectConceptBucket", "selectConceptGroup",
    "selectHomeFamily", "setAccent", "setActiveModel", "setAiBackend", "setAllowImpracticalHw",
    "setDensity", "setFace", "setRerunGuide", "setSidebar", "setSrcSort", "setTheme",
    "setTrendLens", "sgAddMember", "sgAddMemberFrom", "sgAddRing", "sgAddRingFrom",
    "sgRemoveMember", "showGovLens", "showTab", "srcFilterTag", "srcJumpToDomain", "srcMselChanged",
    "srcPage", "startDump", "startFolderImport", "startOsmDownload", "startPlanetDownload",
    "stopVllm", "storageGuardResume", "summarize", "synthesizeResults", "tmapFindCoverage", "toggleAiCoordinator",
    "toggleCalSub", "toggleIdxCompare", "toggleIndexTag", "toggleKeywordTriage", "toggleLangMenu",
    "toggleMktConfig", "toggleNetwork", "togglePerceptionExtract", "toggleRateMode",
    "toggleSidebar", "toggleSourceTags", "toggleSourceTrail", "toggleStatSub", "toggleVitals",
    "toggleWatch", "trackWikiNow", "trackWikiPage", "translateArticle", "triangulateStatSeries",
    "trustAuthor", "unattendedLog", "unattendedStart", "unattendedStop", "undoNewsletterAttach",
    "uninstallAi", "uninstallApp", "updateSourceEnabled", "updateSourcePriority", "vacuumNow",
    "verifyChain", "viewChain", "viewKeywordGrowth", "viewWikiDiff", "vitalsKey", "wikiLaneClick",
    "windowsLocksReport", "zoomMap",
  ];
  for (const name of OO_ACTIONS) ACTIONS[name] = null;

  // Small helpers for what inline handlers used to say in-line.
  const HELPERS = {
    ooPrevent(ev) { if (ev) ev.preventDefault(); },
    ooStop(ev) { if (ev) ev.stopPropagation(); },
    ooPreventStop(ev) { if (ev) { ev.preventDefault(); ev.stopPropagation(); } },
    ooCloseDialog(id) { const d = document.getElementById(id); if (d && d.close) d.close(); },
    ooClickId(id) { const e = document.getElementById(id); if (e) e.click(); },
    ooSetValue(id, v) { const e = document.getElementById(id); if (e) e.value = v; },
    ooClearValue(el) { if (el) el.value = ""; },
    ooBodyClass(cls, force) { document.body.classList.toggle(cls, force); },
    // A same-origin download in a new tab. Only a path on this app is accepted, so a
    // binding cannot be turned into an outbound link (those go through invariant #7's
    // confirm, via a real <a href>).
    ooOpenUrl(path) {
      if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) return;
      window.open(path, "_blank");
    },
  };
  for (const [k, f] of Object.entries(HELPERS)) ACTIONS[k] = f;

  // On the ROOT ELEMENT's capture phase, not the document's: the app registers its own
  // document-level capture listeners (the language menu's outside-click closer, the
  // external-link guard), and those ran BEFORE an inline handler, which sat on the element
  // itself. Listening one level further in keeps that order -- the Chromium walk caught the
  // language menu closing itself the moment it opened when this sat on document.
  const root = document.documentElement;
  for (const type of EVENTS) root.addEventListener(type, onEvent, true);

  window.ooOn = {parse, EVENTS, ACTIONS, OO_ACTIONS};
})();
