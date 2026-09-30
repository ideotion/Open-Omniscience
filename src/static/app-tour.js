/* app-tour.js — the onboarding tour (gate row K of RELEASE_0.5_GATE.md, brief S05-11 S5)

   A short walk through the surfaces the sidebar pins at the reader's interface depth (the
   Ring dial, S05-09), one step each, in the sidebar's own order. Opened by an explicit
   command only: Settings → General, the command palette, Help & docs. It never starts by
   itself, and it can be left on any step (Skip, Esc).

   IT NARROWS NOTHING (the recorded onboarding lesson, LESSONS 2026-07-12: an onboarding
   picker must default to everything; emphasis is not exclusion). It sets no filter, hides no
   tab, changes no setting and keeps no record that it ran. A depth that pins fewer tabs gets
   its own step naming every tab it does not pin, with a button that shows them. Every step
   says so on the page, not in a hover.

   THE STEPS ARE DERIVED FROM THE LIVE SIDEBAR, not listed here, so a tab added later is in
   the tour the day it is in the sidebar. What this file owns is one sentence per tab
   (tourBlurb). A tab with no sentence yet is still a step, with its name and its button; the
   test that walks the sidebar fails the day one is missing, so that is a visible gap.

   The renderers are pure (payload, t, tf) -> data/HTML so tests/tour_node_test.js drives
   them in node; only openTour, _tourShow and _tourWire touch the DOM.
*/
    let _tourWired = false;
    let _tourSteps = [];
    let _tourAt = 0;

    function _tourT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _tourTf() {
      if (window.OOI18N && OOI18N.tf) return OOI18N.tf;
      return (s, vars) => String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));
    }

    // digit grouping like the sidebar's own "Show more (N)" (fmtNum lives in another module;
    // plain when this file is run alone, as the node test does)
    function _tourNum(n) { return (typeof fmtNum === "function") ? fmtNum(n, 0) : String(n); }

    // One sentence per sidebar tab. Each says what the tab SHOWS, in the words the tab itself
    // uses, and none of them promises a conclusion: the app shows data, counts and methods.
    function tourBlurb(id, t) {
      switch (id) {
        case "home": return t("Your briefing: cards that each say why you are seeing them, how they were computed and what they cannot show. Counts and methods, never a verdict.");
        case "feed": return t("The articles collected on this machine, in an order you can reshuffle. It keeps no record of what you have read.");
        case "explore": return t("Search the corpus with a Boolean query, then analyse what it returns: keywords, when, where and who, links, sentiment and sources.");
        case "insights": return t("Analytics over the keywords and entities extracted from your corpus, each figure beside its method and its sample size.");
        case "observatory": return t("Your corpus as a night sky: one dot per keyword group, placed by domain and sized by mentions. Another way to look at the same data, never a second source.");
        case "timemap": return t("Your corpus by place: where the articles you hold come from and which places they mention, on a map.");
        case "law": return t("Countries, their governments and their laws: compare countries, group them, and read the statistics and law documents you hold.");
        case "agenda": return t("A calendar of major world events, plus dates deduced from your articles. A deduced date is labelled as such and never confirmed.");
        case "indices": return t("World stock indices from official free sources: end-of-day values, each labelled with its date and source. Not real time.");
        case "markets": return t("Commodity, energy, metal and currency series from official feeds. Every point comes straight from the downloaded file.");
        case "living": return t("Wikipedia, law and maps: when each was last checked and what changed, shown as dates and counts, never judged.");
        case "library": return t("Everything you have downloaded and everything the app has derived from it, with real counts and on-disk sizes.");
        default: return "";
      }
    }

    // tabs: [{id, label, pinned}] in sidebar order; depth: "essentials" | "standard" | "full".
    // Returns the steps: the top bar, one per pinned tab, one naming the tabs this depth does
    // not pin (only when there are some), and the depth itself. Every tab is in the tour: a
    // pinned one as a step, an unpinned one by name in the "more" step.
    function tourSteps(tabs, depth, t, tf) {
      const steps = [{
        kind: "chrome",
        title: t("The top bar"),
        body: t("The plane is airplane mode: filled means offline, and nothing leaves this machine until you turn it off and agree to what will be contacted. The language menu switches the whole interface at once. The task manager shows what is running, queued and scheduled."),
      }];
      const rest = [];
      (tabs || []).forEach((tab) => {
        if (!tab.pinned) { rest.push(tab); return; }
        steps.push({kind: "tab", tab: tab.id, title: tab.label, body: tourBlurb(tab.id, t)});
      });
      if (rest.length) {
        steps.push({
          kind: "more",
          title: tf("{n} more tabs", {n: _tourNum(rest.length)}),
          body: t("At this depth they are grouped under “Show more” in the sidebar; the tab you have open always stays listed. They are all one click away, and the command palette (Ctrl/⌘-K) reaches every one of them."),
          list: rest.map((x) => x.label),
        });
      }
      const depthName = depth === "essentials" ? t("Essentials") : depth === "standard" ? t("Standard") : t("Full");
      steps.push({
        kind: "depth",
        title: t("Your interface depth"),
        body: tf("The interface depth is {depth} now. A depth changes what is pinned in the sidebar, never what is reachable. You can change it in Settings, and take this tour again from there or from the command palette.", {depth: depthName}),
      });
      return steps;
    }

    // The button a step offers, as {label, act}; a step with nothing to open has none.
    function tourAction(step, t, tf) {
      if (step.kind === "tab") return {act: "open", label: tf("Open {tab}", {tab: step.title})};
      if (step.kind === "more") return {act: "more", label: t("Show them in the sidebar")};
      if (step.kind === "depth") return {act: "depth", label: t("Open the depth setting")};
      return null;
    }

    function tourStepHtml(step, i, n, t, tf) {
      const act = tourAction(step, t, tf);
      return `<p class="hint">${esc(tf("Step {n} of {total}", {n: _tourNum(i + 1), total: _tourNum(n)}))}</p>`
        + `<h4 class="tour-title" dir="auto">${esc(step.title)}</h4>`
        + (step.body ? `<p>${esc(step.body)}</p>` : "")
        + (step.list ? `<ul class="tour-list">${step.list.map((x) => `<li dir="auto">${esc(x)}</li>`).join("")}</ul>` : "")
        + (act ? `<p><button type="button" class="secondary" data-tour-act="${esc(act.act)}">${esc(act.label)}</button></p>` : "")
        + `<p class="card-caveat">${esc(t("The tour changes nothing: it sets no filter, hides no tab and keeps no record."))}</p>`;
    }

    // What the live sidebar pins. data-ring is set by paintNavMore ("0" pinned at every
    // depth, "1" pinned from Standard up); a depth other than Essentials pins every tab.
    function _tourTabs() {
      const depth = (typeof uiDepth === "function") ? uiDepth() : "full";
      const out = [];
      document.querySelectorAll("#navGroups .nav-item[data-tab]").forEach((b) => {
        const span = b.querySelector("span:not(.badge)");
        out.push({
          id: b.getAttribute("data-tab"),
          label: ((span && span.textContent) || b.getAttribute("data-tab")).trim(),
          // what the sidebar's own "Show more (N)" counts: the OPEN tab stays listed at every
          // depth (invariant #2), and the step says so, so its count is the sidebar's
          pinned: depth !== "essentials" || b.getAttribute("data-ring") === "0",
        });
      });
      return {tabs: out, depth};
    }

    function _tourShow() {
      const t = _tourT(), tf = _tourTf();
      const body = $("tour-body"), next = $("tour-next"), back = $("tour-back");
      if (!body) return;
      const step = _tourSteps[_tourAt];
      body.innerHTML = tourStepHtml(step, _tourAt, _tourSteps.length, t, tf);
      if (back) back.disabled = _tourAt === 0;
      if (next) next.textContent = _tourAt === _tourSteps.length - 1 ? t("Finish") : t("Next");
    }

    function _tourClose() { const d = $("tour"); if (d && d.open) d.close(); }

    function _tourRedraw() {
      const d = $("tour");
      if (!d || !d.open) return;
      const live = _tourTabs();
      const cur = _tourSteps[_tourAt];
      _tourSteps = tourSteps(live.tabs, live.depth, _tourT(), _tourTf());
      const keep = _tourSteps.findIndex((s) => s.kind === cur.kind && s.tab === cur.tab);
      _tourAt = keep >= 0 ? keep : Math.min(_tourAt, _tourSteps.length - 1);
      _tourShow();
    }

    function _tourWire() {
      if (_tourWired) return;
      _tourWired = true;
      const on = (id, fn) => { const el = $(id); if (el) el.addEventListener("click", fn); };
      on("tour-skip", _tourClose);
      on("tour-back", () => { if (_tourAt > 0) { _tourAt--; _tourShow(); } });
      on("tour-next", () => {
        if (_tourAt >= _tourSteps.length - 1) { _tourClose(); return; }
        _tourAt++; _tourShow();
      });
      const body = $("tour-body");
      if (body) body.addEventListener("click", (e) => {
        const b = e.target.closest && e.target.closest("[data-tour-act]");
        if (!b) return;
        const step = _tourSteps[_tourAt], act = b.getAttribute("data-tour-act");
        _tourClose();
        if (act === "open" && step.tab) showTab(step.tab);
        else if (act === "more") { _navMoreOpen = true; paintNavMore(); }
        else if (act === "depth") { showTab("settings"); (_setSubtabs || {select: showSetCat}).select("general"); }
      });
      document.addEventListener("oo:langchange", () => setTimeout(_tourRedraw, 0));
    }

    // The one entry point: Settings → General, the palette, Help & docs.
    function openTour() {
      const d = $("tour");
      if (!d) return;
      _tourWire();
      const live = _tourTabs();
      _tourSteps = tourSteps(live.tabs, live.depth, _tourT(), _tourTf());
      _tourAt = 0;
      _tourShow();
      if (!d.open) d.showModal();
    }
