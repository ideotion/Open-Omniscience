/* app-patterns.js — the full lists behind the pattern Leads, corpus-wide Who, and the undo
   controls that had no button (Lane M's route sweep, ruling R685).

   EIGHT LISTS, ONE DIALOG. Eight Home Lead types each show only their top few cases as cards;
   the server already computed the whole list (copied wording, a source giving one topic far
   more space than its own past, a headline the body barely covers, a term that arrived wide
   with no dated event, near-identical text that came back after a long gap, many sources
   citing one origin, one story dated differently, the order a topic reached each source).
   A card's back opens its list; Insights > Patterns opens any of the eight.

   R685, the wording rule: an item says WHAT WAS MEASURED ("12 sources (30 articles) cite one
   origin: example.org"), never what it proves, and never with words like "fake" or
   "manipulated" — a list names real sources. The pattern's name carries the label; the
   caveat qualifies it. Each list's count line says how many items it holds and when the
   server computed them, and the "How this was measured" button right beside it reveals the
   translated caveat, the method and the thresholds. The caveat also rides the button's
   hover (#oo-tip), the same layering as the back of a Lead card (#23). The button is a real
   <button> with aria-expanded, so it works by keyboard, touch and screen reader.

   UNDO THAT WAS MISSING. A dismissed Lead could never come back, and a keyword hidden from
   the explorer could never be shown again. Now: the dismiss toast is an Undo
   (POST /api/briefing/restore), the Briefing header offers "Show N dismissed cards"
   (POST /api/briefing/dismissed/clear), and a hidden keyword gets an Undo beside it
   (POST /api/insights/include). Those three POSTs answer a person's click only
   (event.isTrusted), like the task manager's controls (R673).

   The renderers are pure (payload, t, tf) -> HTML so tests/pattern_lists_node_test.js runs
   them as real code; only the open/load functions touch the DOM or the network.
*/

    // The eight lists: the Lead type, the route, and which array of the payload holds the items.
    const OO_PATTERNS = [
      {type: "copypasta", path: "/api/insights/copypasta", key: "items"},
      {type: "flooded_topic", path: "/api/insights/flooded-topics", key: "items"},
      {type: "headline_body_mismatch", path: "/api/insights/headline-body-mismatch", key: "items"},
      {type: "manufactured_emergence", path: "/api/insights/manufactured-emergence", key: "items"},
      {type: "recycled_claim", path: "/api/insights/recycled-claims", key: "clusters"},
      {type: "source_laundering", path: "/api/insights/source-laundering", key: "clusters"},
      {type: "disputed_chronology", path: "/api/signals/disputed-chronology", key: "items"},
      {type: "story_propagation", path: "/api/signals/story-propagation", key: "items"},
    ];
    // The most items one list asks for (every route caps its own `limit`; 100 is the highest
    // any of the six insights routes accepts, and the two signals routes return what they find).
    const OO_PATTERN_LIMIT = 100;
    const _patternCache = {};   // type -> last payload, so a language switch redraws without a fetch
    let _patternOpen = null;    // the type the dialog shows

    function _patT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _patTf() {
      return (window.OOI18N && OOI18N.tf) ? OOI18N.tf
        : ((s, v) => String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)));
    }
    function _patEsc(s) {
      return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
        ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));
    }
    function _patNum(v) {
      return (typeof fmtNum === "function") ? fmtNum(v, 0) : String(v);
    }
    function _patShort(s, n) {
      const x = String(s == null ? "" : s);
      return x.length > n ? x.slice(0, n - 1) + "…" : x;
    }
    function _patPct(share) {
      const v = Number(share);
      return isFinite(v) ? String(Math.round(v * 1000) / 10) : "?";
    }
    function patternByType(type) {
      for (const p of OO_PATTERNS) if (p.type === type) return p;
      return null;
    }

    // The pattern's name: the Lead chip's own label, so the list and the card agree.
    function patternLabel(type, t) {
      switch (type) {
        case "copypasta": return t("Copied wording");
        case "flooded_topic": return t("Flooded topic");
        case "headline_body_mismatch": return t("Headline vs body");
        case "manufactured_emergence": return t("Sudden emergence");
        case "recycled_claim": return t("Recycled claim");
        case "source_laundering": return t("Source laundering");
        case "disputed_chronology": return t("Disputed chronology");
        case "story_propagation": return t("Story propagation");
        default: return String(type || "");
      }
    }

    // ONE line per item, saying what was measured. Each frame is a literal tf() so the i18n
    // gates see it; the values are data (names, phrases, dates) and are escaped by the caller.
    function patternItemText(type, it, t, tf) {
      const srcCount = (it && it.distinct_sources != null) ? it.distinct_sources : (Array.isArray(it && it.sources) ? it.sources.length : 0);
      switch (type) {
        case "copypasta":
          return tf("The same {words}-word phrase in {sources} sources ({n} articles): “{phrase}”",
            {words: it.n_words, sources: srcCount, n: it.n_articles, phrase: _patShort(it.phrase, 120)});
        case "flooded_topic":
          return tf("{source}: {now}% of its recent articles were about “{keyword}” ({recent} of {total}), against {base}% before",
            {source: it.source, now: _patPct(it.share_now), keyword: it.term, recent: it.recent_articles,
             total: it.recent_total, base: _patPct(it.baseline_share)});
        case "headline_body_mismatch":
          return tf("“{title}”: the headline's words are rare in the article body (divergence {div})",
            {title: _patShort(it.title || t("(untitled)"), 120), div: it.lexical_div});
        case "manufactured_emergence":
          return tf("“{keyword}”: in {n} articles from {sources} sources within days, with almost no earlier mention and no dated event cited",
            {keyword: it.term, n: it.recent_articles, sources: it.recent_sources});
        case "recycled_claim":
          return tf("“{title}”: near-identical text seen {first}, then again {resurfaced}, {days} days later ({sources} sources)",
            {title: _patShort(it.recent_title || it.original_title || t("(untitled)"), 120), first: it.first_seen,
             resurfaced: it.resurfaced, days: it.gap_days, sources: srcCount});
        case "source_laundering":
          return tf("{sources} sources ({n} articles) cite the same origin: {origin}",
            {sources: srcCount, n: it.n_articles, origin: it.origin_domain || it.origin});
        case "disputed_chronology":
          return tf("{sources} sources tell a near-identical story with {dates} different event dates, {days} days apart",
            {sources: srcCount, dates: it.distinct_dates, days: it.span_days});
        case "story_propagation":
          return tf("“{keyword}”: reached {sources} sources over {days} days, first in {source} on {date}",
            {keyword: it.term, sources: srcCount, days: it.span_days, source: it.first_source, date: it.first_seen});
        default:
          return "";
      }
    }

    // The article ids an item opens: a list of them, or the one article a headline item is.
    function patternItemIds(it) {
      if (it && Array.isArray(it.article_ids) && it.article_ids.length) return it.article_ids.slice(0, 5000);
      if (it && it.article_id != null) return [it.article_id];
      return [];
    }

    // The thresholds the server applied, each in words. Only the keys a payload carries are
    // shown; an unknown key is left out rather than printed raw.
    function patternThresholds(p, t, tf) {
      const rows = [];
      const has = (k) => p && p[k] != null && p[k] !== "";
      if (has("min_sources")) rows.push(tf("At least {n} distinct sources", {n: p.min_sources}));
      if (has("min_articles")) rows.push(tf("At least {n} articles", {n: p.min_articles}));
      if (has("recent_days")) rows.push(tf("Recent window: {n} days", {n: p.recent_days}));
      if (has("prior_days")) rows.push(tf("Compared with the {n} days before", {n: p.prior_days}));
      if (has("baseline_days")) rows.push(tf("Compared with the {n} days before", {n: p.baseline_days}));
      if (has("lookback_days")) rows.push(tf("Looked back {n} days", {n: p.lookback_days}));
      if (has("min_gap_days")) rows.push(tf("A gap of at least {n} days", {n: p.min_gap_days}));
      if (has("k")) rows.push(tf("Phrases of at least {n} words", {n: p.k}));
      if (has("d_min")) rows.push(tf("Headline–body divergence of at least {n}", {n: p.d_min}));
      if (has("z_min")) rows.push(tf("A share jump of at least {n} standard deviations", {n: p.z_min}));
      if (has("min_share")) rows.push(tf("At least {n}% of the source's recent articles", {n: _patPct(p.min_share)}));
      if (has("min_recent_count")) rows.push(tf("At least {n} recent articles", {n: p.min_recent_count}));
      if (has("tolerance_days")) rows.push(tf("Dates within {n} days count as the same", {n: p.tolerance_days}));
      if (has("min_span_days")) rows.push(tf("Spread over at least {n} days", {n: p.min_span_days}));
      return rows;
    }

    // A sentence the server wrote, shown translated when the locale has it, else as sent in
    // its own left-to-right span behind a visible label (R289's treatment).
    function _patServerText(text, t) {
      const s = String(text || "");
      if (!s) return "";
      const tr = t(s);
      const lang = (window.OOI18N && OOI18N.current) ? OOI18N.current() : "en";
      if (tr !== s || lang === "en") return _patEsc(tr);
      const label = _patEsc(t("Server text, in English"));
      const val = `<span lang="en" dir="ltr">${_patEsc(s)}</span>`;
      return (typeof ooLabelHtml === "function") ? ooLabelHtml(label, val) : `${label}: ${val}`;
    }

    // The count line and its "How this was measured" control, shared by the eight lists and Who.
    // `id` names the region the button opens, so aria-controls points at it.
    function patternHeadHtml(p, shown, id, t, tf) {
      const when = p && p.computed_at
        ? ((typeof fmtDateTime === "function") ? fmtDateTime(p.computed_at) : String(p.computed_at)) : "";
      const count = when
        ? tf("{n} found, computed {when}", {n: _patNum(shown), when: when})
        : tf("{n} found", {n: _patNum(shown)});
      const caveat = p && p.caveat ? t(p.caveat) : "";
      const thresholds = patternThresholds(p, t, tf);
      const capped = shown >= OO_PATTERN_LIMIT
        ? `<p class="hint">${_patEsc(tf("Showing the first {n}.", {n: _patNum(OO_PATTERN_LIMIT)}))}</p>` : "";
      return `<div class="row pat-head" style="gap:8px;align-items:center;flex-wrap:wrap">
          <span class="pat-count">${_patEsc(count)}</span>
          <button type="button" class="ghost tiny pat-how" aria-expanded="false" aria-controls="${_patEsc(id)}"
                  title="${_patEsc(caveat)}">${_patEsc(t("How this was measured"))}</button>
        </div>
        <div class="pat-how-body" id="${_patEsc(id)}" role="region" aria-label="${_patEsc(t("How this was measured"))}" hidden>
          ${caveat ? `<p class="card-caveat">${_patEsc(caveat)}</p>` : ""}
          ${p && p.method ? `<p class="hint">${_patServerText(p.method, t)}</p>` : ""}
          ${thresholds.length ? `<ul class="hint pat-thresholds">${thresholds.map((r) => `<li>${_patEsc(r)}</li>`).join("")}</ul>` : ""}
        </div>${capped}`;
    }

    // One list, as HTML. Pure: the payload in, markup out.
    function patternListHtml(type, payload, t, tf) {
      const def = patternByType(type);
      const items = (payload && def && Array.isArray(payload[def.key])) ? payload[def.key] : [];
      const head = patternHeadHtml(payload, items.length, "pat-how-" + type, t, tf);
      if (!items.length) {
        return head + `<p class="muted">${_patEsc(t("Nothing matches these thresholds in your corpus yet."))}</p>`;
      }
      const rows = items.map((it, i) => {
        const ids = patternItemIds(it);
        const open = ids.length
          ? ` <button type="button" class="ghost tiny pat-open" data-pat-item="${i}">${_patEsc(tf("Open {n} articles", {n: _patNum(ids.length)}))}</button>`
          : "";
        return `<li class="pat-item"><span>${_patEsc(patternItemText(type, it, t, tf))}</span>${open}</li>`;
      }).join("");
      return head + `<ol class="pat-list">${rows}</ol>`;
    }

    // Wire the controls inside a list host: the "How this was measured" toggles and each item's
    // "Open N articles". Listeners, not data-on-click, so no name joins oo-on.js's allow-list.
    function _patWire(host, type, payload) {
      host.querySelectorAll(".pat-how").forEach((b) => {
        b.addEventListener("click", () => {
          const region = document.getElementById(b.getAttribute("aria-controls"));
          if (!region) return;
          const open = region.hidden;
          region.hidden = !open;
          b.setAttribute("aria-expanded", open ? "true" : "false");
        });
      });
      if (!type) return;
      const def = patternByType(type);
      const items = (payload && def && Array.isArray(payload[def.key])) ? payload[def.key] : [];
      host.querySelectorAll(".pat-open").forEach((b) => {
        b.addEventListener("click", () => {
          const it = items[Number(b.dataset.patItem)];
          if (!it) return;
          const t = _patT(), tf = _patTf();
          const label = patternLabel(type, t) + " — " + _patShort(patternItemText(type, it, t, tf), 80);
          const dlg = document.getElementById("pattern-list");
          if (dlg && dlg.open && dlg.close) dlg.close();
          if (typeof openAnalysisForIds === "function") openAnalysisForIds(patternItemIds(it), label);
        });
      });
    }

    async function _patFetch(type, force) {
      if (!force && _patternCache[type]) return _patternCache[type];
      const def = patternByType(type);
      if (!def) return null;
      const sep = def.path.indexOf("?") >= 0 ? "&" : "?";
      const url = def.path.startsWith("/api/insights/") ? def.path + sep + "limit=" + OO_PATTERN_LIMIT : def.path;
      const payload = await api(url);
      _patternCache[type] = payload;
      return payload;
    }

    function _patPaintDialog() {
      const type = _patternOpen;
      const host = document.getElementById("pl-body");
      const head = document.getElementById("pl-title");
      if (!type || !host) return;
      const t = _patT(), tf = _patTf();
      if (head) head.textContent = patternLabel(type, t);
      const payload = _patternCache[type];
      if (!payload) return;
      host.innerHTML = patternListHtml(type, payload, t, tf);
      _patWire(host, type, payload);
    }

    // Open one list in the shared dialog (from a Lead's back, or from Insights > Patterns).
    async function openPatternList(type) {
      const dlg = document.getElementById("pattern-list");
      const host = document.getElementById("pl-body");
      if (!dlg || !host || !patternByType(type)) return;
      const t = _patT();
      _patternOpen = type;
      const head = document.getElementById("pl-title");
      if (head) head.textContent = patternLabel(type, t);
      host.innerHTML = `<p class="muted">${_patEsc(t("Loading…"))}</p>`;
      if (!dlg.open && dlg.showModal) dlg.showModal();
      try {
        await _patFetch(type, true);
        if (_patternOpen === type) _patPaintDialog();
      } catch (e) {
        if (_patternOpen === type) {
          host.innerHTML = `<p class="err-line">${_patEsc((typeof _failMsg === "function") ? _failMsg("Could not load the list: {error}", e) : t("Could not load the list."))}</p>`;
        }
      }
    }

    // The button a Lead card's back carries when its type has a full list. HTML, because the
    // card is built as a string; the click is caught by the one delegated listener below.
    function ooPatternListButton(c) {
      if (!c || !patternByType(c.type)) return "";
      const t = _patT();
      return `<button type="button" class="secondary tiny" data-pattern-list="${_patEsc(c.type)}"
        title="${_patEsc(t("Every case the server found, not only the ones shown as cards"))}">${_patEsc(t("See the full list"))}</button>`;
    }

    // -- Insights > Patterns: the eight lists, each with its count, one click from its dialog --
    function patternsOverviewHtml(counts, t, tf) {
      return `<ul class="pat-overview">${OO_PATTERNS.map((p) => {
        const c = counts[p.type];
        const n = (c === undefined) ? t("Loading…") : (c === null ? t("could not be read") : tf("{n} found", {n: _patNum(c)}));
        return `<li class="row" style="gap:8px;align-items:center">
            <b>${_patEsc(patternLabel(p.type, t))}</b><span class="muted">${_patEsc(n)}</span><span class="sp"></span>
            <button type="button" class="ghost tiny" data-pattern-list="${_patEsc(p.type)}">${_patEsc(t("Open the list"))}</button>
          </li>`;
      }).join("")}</ul>`;
    }
    const _patCounts = {};
    function _patPaintOverview() {
      const host = document.getElementById("ins-patterns-body");
      if (!host) return;
      host.innerHTML = patternsOverviewHtml(_patCounts, _patT(), _patTf());
    }
    async function loadPatternsOverview() {
      OO_PATTERNS.forEach((p) => { delete _patCounts[p.type]; });
      _patPaintOverview();
      // One at a time: each is a whole-corpus scan behind the server's heavy-read guard, and
      // eight at once would only meet its busy answer.
      for (const p of OO_PATTERNS) {
        try {
          const payload = await _patFetch(p.type, true);
          const arr = payload && Array.isArray(payload[p.key]) ? payload[p.key] : [];
          _patCounts[p.type] = arr.length;
        } catch (e) { _patCounts[p.type] = null; }
        _patPaintOverview();
      }
    }

    // -- Insights > Who: people and organisations across the whole corpus, with counts --------
    let _whoCache = null;
    function whoListHtml(payload, t, tf) {
      const ents = (payload && Array.isArray(payload.entities)) ? payload.entities : [];
      const head = patternHeadHtml(payload, ents.length, "pat-how-who", t, tf);
      if (!ents.length) return head + `<p class="muted">${_patEsc(t("No people or organisations found yet."))}</p>`;
      const rows = ents.map((e, i) => {
        const kind = e["class"] === "person" ? t("person") : (e["class"] === "organization" ? t("organisation") : String(e["class"] || ""));
        return `<li class="pat-item"><button type="button" class="ghost tiny who-open" data-who="${i}">${_patEsc(e.name)}</button>
          <span class="muted">${_patEsc(tf("{kind} · {n} articles · {m} mentions", {kind: kind, n: _patNum(e.articles), m: _patNum(e.mentions)}))}</span></li>`;
      }).join("");
      return head + `<ol class="pat-list">${rows}</ol>`;
    }
    function _whoPaint() {
      const host = document.getElementById("ins-who-body");
      if (!host || !_whoCache) return;
      host.innerHTML = whoListHtml(_whoCache, _patT(), _patTf());
      _patWire(host, null, null);
      const ents = Array.isArray(_whoCache.entities) ? _whoCache.entities : [];
      host.querySelectorAll(".who-open").forEach((b) => {
        b.addEventListener("click", () => {
          const e = ents[Number(b.dataset.who)];
          if (e && typeof openAnalysisFor === "function") openAnalysisFor(e.name);
        });
      });
    }
    async function loadWho() {
      const host = document.getElementById("ins-who-body");
      if (!host) return;
      const sel = document.getElementById("who-class");
      const cls = sel ? sel.value : "";
      host.innerHTML = `<p class="muted">${_patEsc(_patT()("Loading…"))}</p>`;
      try {
        _whoCache = await api("/api/insights/who?limit=200" + (cls ? "&entity_class=" + encodeURIComponent(cls) : ""));
        _whoPaint();
      } catch (e) {
        host.innerHTML = `<p class="err-line">${_patEsc((typeof _failMsg === "function") ? _failMsg("Could not load the list: {error}", e) : _patT()("Could not load the list."))}</p>`;
      }
    }

    // -- Undo controls -------------------------------------------------------------------------
    // A dismissed Lead comes back: the dismiss toast is the undo for one card.
    async function ooRestoreCard(id) {
      try {
        await api("/api/briefing/restore", {method: "POST", body: JSON.stringify({id: id})});
        if (typeof loadBriefing === "function") loadBriefing();
        toast(_patT()("The card is back."));
      } catch (e) { toast(_failMsg("Could not bring the card back: {error}", e), "err"); }
    }
    function ooCardDismissedToast(id) {
      toast(_patT()("Card dismissed. Click to undo."), "ok", () => { ooRestoreCard(id); });
    }
    // Every dismissed Lead comes back at once, from the Briefing header.
    function briefDismissedHtml(n, t, tf) {
      const k = Number(n) || 0;
      if (k <= 0) return "";
      return `<button type="button" class="ghost tiny" id="brief-dismissed-show"
        title="${_patEsc(t("Cards you dismissed stay hidden until you bring them back"))}">${_patEsc(tf("Show {n} dismissed cards", {n: _patNum(k)}))}</button>`;
    }
    function ooPaintBriefDismissed(n) {
      const host = document.getElementById("brief-dismissed");
      if (!host) return;
      host.innerHTML = briefDismissedHtml(n, _patT(), _patTf());
      const b = document.getElementById("brief-dismissed-show");
      if (!b) return;
      b.addEventListener("click", async (ev) => {
        if (!ev.isTrusted) return;
        try {
          await api("/api/briefing/dismissed/clear", {method: "POST"});
          host.innerHTML = "";
          if (typeof loadBriefing === "function") loadBriefing();
        } catch (e) { toast(_failMsg("Could not bring the cards back: {error}", e), "err"); }
      });
    }
    // A keyword hidden from the explorer can be shown again, from the button that hid it.
    function ooKeywordUndoButton(term, hiddenBtn) {
      const t = _patT();
      const undo = document.createElement("button");
      undo.type = "button"; undo.className = "ghost tiny kx-undo";
      undo.textContent = t("Undo");
      undo.title = t("Show this keyword in the listings again");
      undo.addEventListener("click", async (ev) => {
        if (!ev.isTrusted) return;
        try {
          await api("/api/insights/include", {method: "POST", body: JSON.stringify({term: term})});
          if (hiddenBtn) { hiddenBtn.textContent = t("Hide"); hiddenBtn.disabled = false; }
          undo.remove();
        } catch (e) { toast(_failMsg("Could not show the keyword again: {error}", e), "err"); }
      });
      return undo;
    }

    // One delegated listener for every "See the full list" / "Open the list" button, wherever the
    // markup was built (a Lead's back is a string; the overview is repainted).
    document.addEventListener("click", (ev) => {
      const b = ev.target && ev.target.closest ? ev.target.closest("[data-pattern-list]") : null;
      if (!b) return;
      ev.stopPropagation();   // a button on a Lead's back never flips the card
      openPatternList(b.getAttribute("data-pattern-list"));
    });
    // Insights > Who: changing "Show" reads the list again for that kind of name.
    document.addEventListener("change", (ev) => {
      if (ev.target && ev.target.id === "who-class") loadWho();
    });
    // A language switch redraws what is on screen from what was fetched; nothing is re-read.
    document.addEventListener("oo:langchange", () => {
      try { _patPaintDialog(); } catch (_e) { /* the dialog is not built */ }
      try { if (Object.keys(_patCounts).length) _patPaintOverview(); } catch (_e) { /* not opened */ }
      try { _whoPaint(); } catch (_e) { /* not opened */ }
    });

    if (typeof module !== "undefined" && module.exports) {
      module.exports = {OO_PATTERNS, patternLabel, patternItemText, patternItemIds, patternThresholds,
        patternHeadHtml, patternListHtml, patternsOverviewHtml, whoListHtml, briefDismissedHtml};
    }
