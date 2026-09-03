/* app-home.js — Home, Leads, draft, source integrity

   The Home surface (stats strip, latest, channels, recent, trending, alerts), the
   briefing with its Lead cards and carousel, the link preview, the research draft,
   and the source-integrity / annotation surfaces the cards reach into.

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
    const HOME_STAT_LABELS = {
      articles: "Articles", sources: "Sources",
      keywords: "Keywords", commodity_prices: "Commodity prices",
      article_links: "Article links", mentioned_dates: "Mentioned dates",
    };
    function homeStatLabel(k) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return t(HOME_STAT_LABELS[k] || k.replace(/_/g, " "));
    }
    // S3.4 (d): a served-stale payload states its REAL age. The counts now come
    // from a background-refreshed cache (S3.2), so on a busy server they can be a
    // minute or two old -- and a number that is quietly old is worse than one that
    // says how old it is. Below the threshold nothing is added: stamping every
    // render with an age would turn a normal reading into a warning.
    const _STALE_NOTE_S = 90;
    function homeStatsAgeNote(payload, t) {
      const age = payload && payload.cache_age_s;
      if (!(typeof age === "number" && age >= _STALE_NOTE_S)) return "";
      // The time comes from the payload's own as_of, never from the browser clock
      // minus an age -- two clocks would disagree and the payload's is the one
      // that describes the measurement.
      let stamp = "";
      try {
        const d = new Date(payload.as_of);
        if (!isNaN(d.getTime())) {
          stamp = d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
        }
      } catch (e) { stamp = ""; }
      if (!stamp) return "";
      return t("as of {time} (server busy)").replace("{time}", stamp);
    }
    function renderHomeStats(counts, payload) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("home-stats"); if (!el) return;
      const entries = Object.entries(counts || {});
      const allZero = entries.length > 0 && entries.every(([, v]) => !v);
      const note = homeStatsAgeNote(payload, t);
      el.innerHTML = (entries.length && !allZero)
        ? entries.map(([k, v]) =>
            `<span class="s"><b>${(v || 0).toLocaleString()}</b> <span>${esc(homeStatLabel(k))}</span></span>`).join("")
          + (note ? `<span class="s muted">${esc(note)}</span>` : "")
        : `<div class="muted">${esc(t("Your library is empty — head to Collect to gather your first material."))}</div>`;
    }
    function renderHomeStatus(running) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("home-status"); if (!el) return;
      const priv = t("Your corpus stays on this machine — no cloud, no telemetry; fetching follows your Network mode.");
      el.innerHTML =
        `${esc(t("Automatic collection"))}: <span class="pill ${running ? "ok" : ""}">${esc(t(running ? "running" : "stopped"))}</span> ` +
        `· <span class="muted">${esc(priv)}</span>`;
    }
    // ======================= FEED (rulings 8-13, 40-41) =======================
    // The corpus as a reading surface. Everything by default, in an order nothing chose
    // for you, cards carrying their own top keywords and expanding in place.
    //
    // SEEN/UNSEEN IS TWO NUMBERS, NOT A READING LOG. The shuffled order is a permutation,
    // so "everything I have scrolled past" is exactly "every key below where I am" -- the
    // seed plus a watermark. Both live here, in localStorage, and neither the server nor
    // the corpus nor a backup ever holds a record of which articles were read. A reading
    // history is a surveillance artifact for the people this app is for; the cheapest way
    // not to leak one is not to have one.
    const _FEED_SEED_KEY = "oo.feed.seed";
    const _FEED_MARK_KEY = "oo.feed.mark";     // the cursor reached, per order
    const _FEED_ORDER_KEY = "oo.feed.order";
    let _feedBusy = false, _feedDone = false, _feedHeld = null;
    // Bumped by every restart (reshuffle, start-from-the-top, order switch). A page
    // that was already in flight when one of those happened belongs to the ORDER the
    // reader just left, so it is discarded on arrival rather than appended.
    let _feedGen = 0;

    function _feedSeed() {
      // Persisted per session (ruling 8): a seed drawn fresh on every load would reshuffle
      // under the reader's feet and show the same articles again. A LARGE random value --
      // the endpoint spreads it anyway, but there is no reason to hand it a small one.
      let s = 0;
      try { s = parseInt(localStorage.getItem(_FEED_SEED_KEY) || "0", 10) || 0; } catch (e) { s = 0; }
      if (!s) {
        s = Math.floor(Math.random() * 2147483646) + 1;
        try { localStorage.setItem(_FEED_SEED_KEY, String(s)); } catch (e) { /* private mode: a fresh order each load */ }
      }
      return s;
    }
    function _feedOrder() {
      try { return localStorage.getItem(_FEED_ORDER_KEY) === "recent" ? "recent" : "shuffled"; }
      catch (e) { return "shuffled"; }
    }
    function _feedMark(order) {
      try { return localStorage.getItem(_FEED_MARK_KEY + "." + order) || ""; } catch (e) { return ""; }
    }
    function _feedSetMark(order, cursor) {
      try {
        if (cursor) localStorage.setItem(_FEED_MARK_KEY + "." + order, cursor);
        else localStorage.removeItem(_FEED_MARK_KEY + "." + order);
      } catch (e) { /* nothing to remember is a worse feed, never a broken one */ }
    }
    // Ruling 41: BOTH resets, because they are different asks. Reshuffle = a new order,
    // from the top. Clear seen = the same order, from the top. Neither touches an article.
    function feedReshuffle() {
      try { localStorage.removeItem(_FEED_SEED_KEY); } catch (e) { /* ignore */ }
      _feedSetMark("shuffled", ""); _feedSetMark("recent", "");
      if ($("feed-list")) { _feedRestart(); }
    }
    function feedClearSeen() {
      _feedSetMark("shuffled", ""); _feedSetMark("recent", "");
      if ($("feed-list")) { _feedRestart(); }
    }
    function _feedSetOrder(order) {
      try { localStorage.setItem(_FEED_ORDER_KEY, order); } catch (e) { /* ignore */ }
      _feedRestart();
    }
    function _feedRestart() {
      // The bump must come FIRST: it is what lets loadFeed run while a page is still in
      // flight without the two of them racing to append.
      _feedGen++; _feedBusy = false;
      _feedDone = false; _feedHeld = null;
      const list = $("feed-list"); if (list) list.innerHTML = "";
      loadFeed(true);
    }

    function _feedControls() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("feed-controls"); if (!host) return;
      const order = _feedOrder();
      const btn = (v, label, tip) =>
        `<button class="tiny${order === v ? "" : " ghost"}" aria-pressed="${order === v}" `
        + `onclick="_feedSetOrder('${v}')" title="${esc(tip)}">${esc(label)}</button>`;
      host.innerHTML =
        `<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:6px">`
        + `<span class="muted" style="font-size:.85em">${esc(t("Order"))}:</span>`
        + btn("shuffled", t("Shuffled"), t("A fixed order chosen by a seed — it uses each article's id and that seed and nothing else."))
        + btn("recent", t("Newest first"), t("By publication date, newest first."))
        + `<button class="tiny ghost" style="margin-inline-start:8px" onclick="feedReshuffle()" `
        + `title="${esc(t("Draw a new order and start again from the top."))}">${esc(t("Reshuffle"))}</button>`
        + `<button class="tiny ghost" onclick="feedClearSeen()" `
        + `title="${esc(t("Keep this order and start again from the top."))}">${esc(t("Start from the top"))}</button>`
        + `</div>`;
    }

    function _feedCard(a) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const kws = (a.keywords || []).map(k =>
        `<button type="button" class="an-facet" onclick="openAnalysisFor(${esc(JSON.stringify(k.term))})" `
        + `title="${esc(t("Mentions in this article — open this keyword's corpus."))}">`
        + `${esc(k.term)} <span class="muted">${k.count}</span></button>`).join(" ");
      const when = (a.published_at || "").slice(0, 10);
      const lang = a.language || a.detected_language || "";
      // Ruling 12: expanding is a class toggle over text ALREADY in the payload -- a feed
      // that fetches on every "read more" stutters, and a reader who opened one card has
      // not asked to wait.
      const more = (a.excerpt_full || "").length > (a.excerpt || "").length;
      return `<article class="feed-card" data-aid="${a.id}">`
        + `<h3 class="feed-t"><a href="${esc(a.reader_url)}" target="_blank" rel="noopener">`
        + `${esc(a.title) || '<span class="muted">(untitled)</span>'}</a></h3>`
        + `<div class="feed-meta muted">${esc(a.source || "")}`
        + (when ? ` · ${esc(when)}` : "")
        + (lang ? ` · ${esc(String(lang).toUpperCase())}` : "")
        + (a.provenance ? ` · ${esc(t(a.provenance))}` : "")
        + `</div>`
        + (kws ? `<div class="feed-kw">${kws}</div>` : "")
        + `<p class="feed-x" data-short="${esc(a.excerpt || "")}" data-full="${esc(a.excerpt_full || "")}">`
        + `${esc(a.excerpt || "")}${more ? "…" : ""}</p>`
        + (more
            ? `<button class="tiny ghost" onclick="_feedExpand(this)">${esc(t("Read more"))}</button> `
            : "")
        + (a.truncated
            ? `<span class="muted" style="font-size:.85em">${esc(t("This is the opening of the article — open it to read the rest."))}</span>`
            : "")
        + `</article>`;
    }
    function _feedExpand(btn) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const card = btn.closest(".feed-card"); if (!card) return;
      const p = card.querySelector(".feed-x"); if (!p) return;
      const open = p.dataset.open === "1";
      p.textContent = open ? p.dataset.short + "…" : p.dataset.full;
      p.dataset.open = open ? "" : "1";
      btn.textContent = t(open ? "Read more" : "Show less");
    }

    async function loadFeed(reset) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const list = $("feed-list"); if (!list || _feedBusy || (_feedDone && !reset)) return;
      _feedBusy = true;
      const gen = _feedGen;
      _feedControls();
      const order = _feedOrder();
      const more = $("feed-more");
      if (more) more.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const p = new URLSearchParams({ order, limit: "20" });
        if (order === "shuffled") p.set("seed", String(_feedSeed()));
        const mark = reset ? "" : _feedMark(order);
        if (mark) p.set("after", mark);
        const d = await api("/api/feed?" + p.toString());
        // A RESTART HAPPENED WHILE THIS WAS IN FLIGHT. Appending now would put rows from
        // the order the reader left into the order they chose, and -- worse -- write this
        // page's cursor over the cleared mark, so the next scroll would send the NEW seed
        // with a cursor from the OLD permutation and silently skip everything between
        // them. Skipping is the one thing a keyset walk over a bijection is supposed to
        // make impossible, so this page is dropped instead.
        if (gen !== _feedGen) return;
        if (d.held_back) _feedHeld = d.held_back;
        list.insertAdjacentHTML("beforeend", (d.results || []).map(_feedCard).join(""));
        _feedSetMark(order, d.next_cursor || "");
        _feedDone = !d.has_more || !d.next_cursor;
        _feedNote(d);
        if (more) {
          more.innerHTML = _feedDone
            ? `<div class="muted" style="margin:10px 0">${esc(t("That is the end of this pass."))}</div>`
            : `<button class="tiny" onclick="loadFeed(false)">${esc(t("Load more"))}</button>`;
        }
      } catch (e) {
        // Same reason as the discard above: a page the reader has already navigated away
        // from must not report ITS failure over the walk that replaced it.
        if (gen === _feedGen && more) {
          more.innerHTML = `<div class="note err">${esc((e && e.message) || t("The feed could not load."))}</div>`;
        }
      } finally {
        // Only the CURRENT walk may release the flag: a discarded page returning late
        // would otherwise clear the busy flag of the walk that replaced it.
        if (gen === _feedGen) _feedBusy = false;
      }
    }

    // The note above the list. It carries the method + the caveat the endpoint sends (both
    // orders miss articles that arrive mid-scroll, in opposite directions) and, when the
    // feed is shorter than the corpus, WHY -- an empty column with no explanation reads as
    // "you have collected nothing", which on a corpus whose qualification pass has not run
    // is simply false.
    function _feedNote(d) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("feed-note"); if (!el) return;
      let h = `<span class="muted">${esc(d.method || "")}</span>`;
      if (d.caveat) h += `<div class="card-caveat">${esc(d.caveat)}</div>`;
      const held = _feedHeld;
      if (held && (held.quarantined || held.source_not_qualified)) {
        const bits = [];
        if (held.source_not_qualified) {
          bits.push(t("{n} held back: their source has not been qualified yet")
            .replace("{n}", held.source_not_qualified.toLocaleString()));
        }
        if (held.quarantined) {
          bits.push(t("{n} held back as quarantined")
            .replace("{n}", held.quarantined.toLocaleString()));
        }
        h += `<div class="card-caveat">${esc(bits.join(" · "))}</div>`;
      }
      el.innerHTML = h;
    }

    // Infinite scroll, ONE observer on the sentinel -- no scroll handler, no polling, and
    // it only ever fires while the Feed tab is the visible one.
    let _feedObs = null;
    function _wireFeed() {
      _feedControls();
      const list = $("feed-list");
      if (list && !list.children.length) loadFeed(true);
      const more = $("feed-more");
      if (more && !_feedObs && window.IntersectionObserver) {
        _feedObs = new IntersectionObserver((entries) => {
          if (entries.some(e => e.isIntersecting)) loadFeed(false);
        }, { rootMargin: "400px" });
        _feedObs.observe(more);
      }
    }

    async function loadHome() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try { const s = await api("/api/database/stats"); renderHomeStats(s.counts, s); }
      catch (e) { $("home-stats").innerHTML = `<div class="muted">${esc(t("Stats unavailable."))}</div>`; }
      try { const sc = await api("/api/scheduler/status"); renderHomeStatus(sc.running); }
      catch (e) { renderHomeStatus(false); }
      loadBriefing();
      loadHomeAlerts();
      loadHomeTrends();
      // Each panel decides its OWN visibility (it hides when it has nothing), and the
      // subtab list is built from the panels that actually have something to show. So
      // the sync runs from HERE, once each loader has settled, rather than inside the
      // loaders: their fail-safe hide statements are pinned verbatim by
      // test_ui_channel_facet / test_ui_home_latest / test_ui_home_recent, and those
      // guards protect a real honesty property (a panel with no data must hide) that
      // this change has no business touching.
      const pRecent = loadHomeRecent();
      const pLatest = loadHomeLatest();
      const pChannels = loadHomeChannels();
      Promise.allSettled([pRecent, pLatest, pChannels]).then(_syncHomeSubtabs);
      refreshDraftCount();
    }
    // Home "Latest in your corpus" (wave 4 I / GET /api/insights/latest): a recency LENS
    // with transparent substance FILTERS — newest first by COLLECTION time (un-spoofable,
    // never the publisher's claimed date), gated by the min-words AND min-cited-sources
    // thresholds the user sets AND sees, near-identical wire reprints collapsed. Each row
    // shows its REAL word count + cited-source count + channel — counts, NEVER a score.
    // The facet <select>s (content type + tag) are populated once from the endpoint's
    // window-wide options (independent of the active gates) and preserve the selection.
    // Hidden until the corpus has recent articles so Home is never blank-and-silent (the
    // Briefing still renders); when it HAS articles but none pass the gates it shows the
    // panel with an honest "loosen the gates" message so the controls stay reachable.
    async function loadHomeLatest() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const panel = $("home-latest-panel"), box = $("home-latest");
      if (!panel || !box) return;
      const mw = Math.max(0, parseInt(($("latest-minwords") || {}).value, 10) || 0);
      const ms = Math.max(0, parseInt(($("latest-minsources") || {}).value, 10) || 0);
      const ct = (($("latest-channel") || {}).value || "").trim();
      const tg = (($("latest-tag") || {}).value || "").trim();
      const collapse = ($("latest-collapse") ? $("latest-collapse").checked : true) ? "1" : "0";
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const p = new URLSearchParams({
          limit: "12", min_words: String(mw), min_sources: String(ms),
          collapse, facets: "1",
        });
        if (ct) p.set("content_type", ct);
        if (tg) p.set("tag", tg);
        const d = await api("/api/insights/latest?" + p.toString());
        const arts = d.articles || [];
        const types = d.available_content_types || {};
        const tags = d.available_tags || [];
        // No recent articles in the corpus at all (not just "none pass the gates") ->
        // hide the panel entirely so Home is never blank-and-silent.
        if (!arts.length && !Object.keys(types).length && !tags.length) {
          panel.hidden = true; return;
        }
        panel.hidden = false;
        _fillLatestFacet($("latest-channel"), t("All channels"),
          Object.keys(types).map(k => ({v: k, label: k, n: types[k]})));
        _fillLatestFacet($("latest-tag"), t("All tags"),
          tags.map(x => ({v: x.tag, label: x.tag, n: x.articles})));
        if (!arts.length) {
          box.innerHTML = `<div class="muted">${esc(t("No recent articles pass these gates yet — loosen the gates or collect more."))}</div>`;
          return;
        }
        box.innerHTML = arts.map(a => {
          const src = (a.source || {});
          const date = String(a.created_at || "").slice(0, 10);
          const meta = [esc(src.name || src.domain || ""), esc(date)].filter(Boolean).join(" · ");
          // REAL substance figures (counts, never a score): word count (flagged when the
          // language is unsegmented, where word_count is meaningless) + cited sources.
          const wc = (a.word_count != null && !a.unsegmented)
            ? `${esc(String(a.word_count))} ${esc(t("words"))}` : "";
          const cs = `${esc(String(a.cited_sources || 0))} ${esc(t("cited sources"))}`;
          const chan = src.source_type ? `<span class="pill">${esc(src.source_type)}</span>` : "";
          const facts = [wc, cs].filter(Boolean).join(" · ");
          // Spread honesty (anti-false-triangulation): count DISTINCT OTHER outlets that
          // ran the same story (the backend's deduped `also_reported_by`, which excludes
          // the survivor's own outlet re-posting) — NEVER the raw duplicates_collapsed,
          // which would overstate independent confirmation. Absent when no OTHER outlet.
          const others = (a.also_reported_by || []).length;
          const also = others > 0
            ? ` <span class="muted">— ${esc(t("also reported by {n} more").replace("{n}", String(others)))}</span>` : "";
          return `<div class="home-recent-row"><a href="${esc(a.url || ("/api/articles/" + a.id + "/view"))}" target="_blank" rel="noopener" title="${esc(t("offline stored copy"))}">${esc(a.title || t("(untitled)"))}</a>`
            + (meta ? ` <span class="muted">— ${meta}</span>` : "")
            + `<div class="muted small" style="margin-top:2px">${chan} ${facts}${also}</div></div>`;
        }).join("")
          + `<div class="hint muted" style="font-size:11px;margin-top:6px">${esc(d.caveat || "")}</div>`;
      } catch (e) { panel.hidden = true; box.innerHTML = ""; }
    }
    // Populate a Latest facet <select> once (preserving the current selection), an "all"
    // default first then each option with its article count. Idempotent: repopulates so a
    // growing corpus surfaces new channels/tags, but keeps what the user picked.
    function _fillLatestFacet(sel, allLabel, opts) {
      if (!sel) return;
      const cur = sel.value;
      const parts = [`<option value="">${esc(allLabel)}</option>`];
      opts.forEach(o => { if (o.v) parts.push(`<option value="${esc(o.v)}">${esc(o.label)} (${esc(String(o.n))})</option>`); });
      sel.innerHTML = parts.join("");
      if (cur && opts.some(o => o.v === cur)) sel.value = cur;
    }
    // Home "By channel" (wave 4 I / GET /api/insights/source-types): the content-provenance
    // facet — article counts per ASSERTED content channel (news/newsletter/wiki/statistics/
    // law/market/discovery/untyped), a descriptive fact known by construction, NEVER a
    // quality score. Clicking a channel opens the analysis window over EXACTLY that
    // channel's articles: /api/articles?source_type= resolves the id set, which every
    // analysis subtab honours (openAnalysisForIds), so the whole corpus narrows honestly
    // by channel using only endpoints that already exist. Hidden when the corpus has no
    // channels (Home is never blank-and-silent).
    async function loadHomeChannels() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const panel = $("home-channels-panel"), box = $("home-channels");
      if (!panel || !box) return;
      try {
        const d = await api("/api/insights/source-types");
        const facets = (d.facets || []).filter(f => (f.articles || 0) > 0);
        if (!facets.length) { panel.hidden = true; box.innerHTML = ""; return; }
        panel.hidden = false;
        // A bare count cannot answer "is this channel most of my corpus or a rounding
        // error?", so each chip carries its SHARE and the denominator is stated once
        // above them. Article.source_id is NOT NULL and the facet excludes quarantined
        // articles exactly as the browse path does, so the facets really do sum to the
        // corpus this share is a share OF -- an unstated denominator is the usual way a
        // percentage lies. Shares are shown BESIDE the counts, never instead: the raw
        // number is what the reader checks the percentage against.
        //
        // Deliberately NOT a waffle, and not a second bar view either. The project's own
        // chart framework prescribes sorted bars for part-to-whole and never mentions a
        // waffle at all; `_ooShareBars` already implements that form -- but its rows are
        // not clickable, and these chips open the channel's corpus (openChannelCorpus).
        // Replacing them would trade a working tool for a prettier read of the same
        // numbers, so the shares come to the chips instead.
        const total = facets.reduce((s, f) => s + (f.articles || 0), 0);
        const pct = (n) => (total > 0 ? (n / total * 100) : 0);
        // Below 0.5% a rounded share reads as "0%", which looks like nothing rather than
        // like a little; "<1%" says small without claiming a precision the rounding lost.
        const share = (n) => (pct(n) >= 0.5 ? Math.round(pct(n)) + "%" : "<1%");
        const totalLine = (window.OOI18N && OOI18N.tf)
          ? OOI18N.tf("{n} articles across {k} channels", {n: fmtNum(total), k: facets.length})
          : `${fmtNum(total)} articles across ${facets.length} channels`;
        box.innerHTML = `<div class="hint muted" style="margin-bottom:4px">${esc(totalLine)}</div>`
          + `<div style="display:flex;gap:6px;flex-wrap:wrap">` + facets.map(f =>
          `<button class="chip" onclick="openChannelCorpus(${esc(JSON.stringify(f.source_type))})" title="${esc(t("An asserted content channel (newsletter, web article, wiki, statistic, law, market, discovery), never a quality score. Click a channel to explore its corpus."))}">${esc(f.source_type)} <span class="muted">${esc(String(f.articles))} · ${esc(share(f.articles))}</span></button>`).join("")
          + `</div>`;
      } catch (e) { panel.hidden = true; box.innerHTML = ""; }
    }
    // Open the analysis window over exactly one content channel's articles. Resolves the
    // channel to an explicit id set through /api/articles?source_type= (the endpoint that
    // supports the filter) then hands it to openAnalysisForIds, so ALL analysis subtabs
    // (keywords / WWW / mindmap / …) narrow to the channel — not just the article list.
    async function openChannelCorpus(st) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/articles?source_type=" + encodeURIComponent(st) + "&limit=1000");
        const ids = (d.results || []).map(a => a.id).filter(Boolean);
        if (!ids.length) { toast(t("No articles for this channel yet.")); return; }
        openAnalysisForIds(ids, t("Channel: {c}").replace("{c}", st));
      } catch (e) { toast((e && e.message) || String(e), "err"); }
    }
    // Home "Most recent by tag" (item #36 / Home helicopter view): a recency LENS onto the
    // corpus, never a reweighting — newest-first by the article's PUBLISHED date among sources
    // carrying a chosen source tag. REDUNDANT by design (every title deep-links to the offline
    // stored reader, invariant #6). Reuses /api/sources/facets (the tag list) + /api/articles
    // (tags + sort_by=date). Hidden until it has a tag + articles so Home is never blank-and-
    // silent (the Briefing still renders below).
    async function loadHomeRecent() {
      const panel = $("home-recent-panel"), sel = $("home-recent-tag");
      if (!panel || !sel) return;
      try {
        const f = await api("/api/sources/facets");
        const tags = (f.tags || []).filter(x => x && x.key).slice(0, 20);
        if (!tags.length) { panel.hidden = true; return; }
        const cur = sel.value;
        sel.innerHTML = tags.map(x => `<option value="${esc(x.key)}">${esc(x.key)} (${x.n})</option>`).join("");
        sel.value = (cur && tags.some(x => x.key === cur)) ? cur : tags[0].key;
        await loadHomeRecentList(sel.value);
      } catch (e) { panel.hidden = true; }
    }
    async function loadHomeRecentList(tag) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const panel = $("home-recent-panel"), box = $("home-recent");
      if (!panel || !box) return;
      if (!tag) { panel.hidden = true; return; }
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const q = "/api/articles?tags=" + encodeURIComponent(tag) + "&sort_by=date&sort_dir=desc&limit=8";
        const d = await api(q);
        const rows = d.results || [];
        if (!rows.length) { box.innerHTML = `<div class="muted">${esc(t("No articles for this tag yet."))}</div>`; panel.hidden = false; return; }
        box.innerHTML = rows.map(a => {
          const meta = [esc(a.source || ""), esc(String(a.published_at || "").slice(0, 10))].filter(Boolean).join(" · ");
          return `<div class="home-recent-row"><a href="/api/articles/${a.id}/view" target="_blank" rel="noopener" title="${esc(t("offline stored copy"))}">${esc(a.title || t("(untitled)"))}</a>`
            + (meta ? ` <span class="muted">— ${meta}</span>` : "") + `</div>`;
        }).join("");
        panel.hidden = false;
      } catch (e) {
        // home-recent-panel-hidden-on-error (P1): both SUCCESS paths above clear
        // `hidden`, but this catch branch set an honest error message into the
        // panel's own box while leaving the panel itself hidden -- the message was
        // written but never shown. The panel must render its error the same way it
        // renders any other outcome.
        box.innerHTML = `<div class="muted">${esc(e && e.message || e)}</div>`;
        panel.hidden = false;
      }
    }
    // Home "Trending now" glance (UI rethink, Home → helicopter view). Compact +
    // REDUNDANT by design: the past-week RISING keywords (the disclosed window-vs-
    // baseline RATE — never a score), each a chip that deep-links to its own
    // analysis window; a small honest sparkline rides along (dashChartSvg: line
    // when dense, Item-Y bars when sparse). The panel HIDES when nothing is
    // trending yet (Home is never blank-and-silent — the Briefing still renders);
    // "More in Insights →" deep-links to the canonical Trends view. Reuses
    // /api/insights/trending-windows + dashChartSvg; no new backend, no new poll.
    let _homeTrendTerms = [], _homeTrendCaveat = "";   // stash for enlargeHomeTrend(i)
    async function loadHomeTrends() {
      const panel = $("home-trends-panel"), box = $("home-trends");
      if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/insights/trending-windows?limit=4&series_top=4" + tgtLangParam());
        const wk = (d.windows || []).find(w => w.label === "7d") || (d.windows || [])[0];
        const terms = (wk && wk.terms) || [];
        if (!terms.length) { if (panel) panel.hidden = true; box.innerHTML = ""; return; }
        if (panel) panel.hidden = false;
        _homeTrendTerms = terms;              // stash so enlargeHomeTrend(i) needs no refetch
        _homeTrendCaveat = d.caveat || "";
        const cards = terms.map((x, i) => {
          const spark = Array.isArray(x.series)
            ? dashChartSvg(x.series.map(p => ({observed_on: p.date, price: p.count})), "")
            : "";
          // Click-to-enlarge into the interactive ooChart (invariant #16), matching
          // the Insights Trends UX — the daily series is already in the payload.
          const enlarge = Array.isArray(x.series)
            ? `<button class="ghost tiny" style="margin-inline-start:auto" onclick="enlargeHomeTrend(${i})" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>`
            : "";
          return `<div style="flex:1;min-width:180px;padding:6px;border:1px solid var(--border);border-radius:8px">
            <div style="display:flex;align-items:baseline;gap:6px">
              <a href="#" onclick='openAnalysisFor(${esc(JSON.stringify(x.term))});return false' title="${esc(t("Open this keyword's own analysis window"))}">${esc(x.term)}</a>${kwTransHtml(x)}
              <span class="muted" style="font-size:12px">${esc(growthFallback(x) || `↑${x.growth}× · ${x.recent}`)}</span>${enlarge}
            </div>${spark}</div>`;
        }).join("");
        box.innerHTML = `<div style="display:flex;gap:8px;flex-wrap:wrap">${cards}</div>`
          + `<div class="hint muted" style="font-size:11px;margin-top:6px">${esc(d.caveat || "")}</div>`;
        _renderOverviewTrends();   // the compact row folded into Overview (ruling 7a)
        _syncHomeSubtabs();
      } catch (e) {
        if (panel) panel.hidden = true; box.innerHTML = "";
        _renderOverviewTrends(); _syncHomeSubtabs();
      }
    }
    // Enlarge a Home "Trending now" sparkline into the interactive ooChart (invariant
    // #16). The daily series is already in the stashed payload — no extra fetch.
    // Global (reached from the inline onclick, matching the card's local convention).
    function enlargeHomeTrend(i) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const x = _homeTrendTerms[i];
      if (!x || !Array.isArray(x.series)) return;   // defensive: nothing to enlarge
      chartEnlarge(x.term, [{label: x.term, unit: t("mentions"),
        points: x.series.map(p => ({t: p.date, v: p.count}))}], _homeTrendCaveat || "");
    }
    // Home severity alert strip (info / watch / urgent) — GET /api/signals/alerts, LOCAL,
    // no network (reads the cached hazard snapshot; a producer NEVER fetches). Compact +
    // honest: 'urgent' is ONLY a provider-declared RED hazard (we never promote a magnitude
    // band); every alert states its provider + the snapshot's staleness ("silence is not
    // safety"); the method + caveat are VISIBLE (invariant #23). Watch/convergence article
    // sets open the exact corpus (openAnalysisForIds); a hazard URL is external so it goes
    // through extLink (the confirm popup, invariant #7). The panel HIDES when there is
    // nothing (Home is never blank-and-silent — the Briefing still renders below).
    async function loadHomeAlerts() {
      const panel = $("home-alerts-panel"), box = $("home-alerts");
      if (!box) return;
      try {
        const d = await api("/api/signals/alerts");
        // S3.1: a scan still running is NOT "no alerts". It reports building:true
        // and OMITS every measured field, so this branch must come before the
        // total check -- `!d.total` on an absent total would hide the panel and
        // a computing corpus would look like a quiet one.
        if (d && d.building) {
          if (panel) panel.hidden = false;
          const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
          box.innerHTML = `<div class="muted">${esc(t("Checking for alerts…"))}</div>`;
          return;
        }
        if (!d || !d.total) { if (panel) panel.hidden = true; box.innerHTML = ""; return; }
        if (panel) panel.hidden = false;
        _renderHomeAlerts(d);
      } catch (e) { if (panel) panel.hidden = true; box.innerHTML = ""; }
    }
    // Item 3 (field-feedback A6, ruled): a distinct glyph per hazard TYPE (never a
    // score/severity encoding -- purely a scannability aid), "⚠" for an unlisted type.
    const HAZARD_GLYPH = {
      earthquake: "◉", cyclone: "🌀", flood: "≈", volcano: "🌋",
      drought: "☀", wildfire: "🔥", tsunami: "〰",
    };
    // The hazard TYPE IN WORDS. A glyph alone is not deducible by someone seeing
    // it for the first time — the maintainer's report (2026-08-01, ruling 4) was
    // that opening an earthquake's detail never says it IS an earthquake. Every
    // hazard render states the type in words, translated; an unlisted type falls
    // back to the provider's own raw string rather than inventing a name.
    const HAZARD_TYPE_KEYS = {
      earthquake: "Earthquake", cyclone: "Cyclone", flood: "Flood", volcano: "Volcano",
      drought: "Drought", wildfire: "Wildfire", tsunami: "Tsunami",
    };
    function hazardTypeLabel(type) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const raw = String(type || "").trim().toLowerCase();
      if (!raw) return t("Hazard");
      return HAZARD_TYPE_KEYS[raw] ? t(HAZARD_TYPE_KEYS[raw]) : String(type);
    }
    // The provider's magnitude, always labelled as the BAND it is. "M6.8 · strong"
    // is a measurement of size, never a statement about consequences — which is
    // exactly why a magnitude is never promoted into an urgency tier.
    function hazardMagLabel(h) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (h.magnitude == null) return "";
      const band = h.band ? ` <span class="muted">· ${esc(t(h.band))}</span>` : "";
      return `<b>M${esc(fmtNum(h.magnitude, 1))}</b>${band} · `;
    }
    // The compact hazard strip item: type glyph, real magnitude (never fabricated),
    // place, RELATIVE date (the stored "time" field, finally rendered -- it used to
    // be fetched and dropped), and TWO deep links: the World map (centred on the
    // event) and the internal article (once ingested; absent until then, never a
    // broken link). The tier dot is the existing per-tier pill above the list.
    function _hazardStripItem(h) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const glyph = HAZARD_GLYPH[h.type] || "⚠";
      const kind = `<span class="haz-kind">${esc(hazardTypeLabel(h.type))}</span> · `;
      const mag = hazardMagLabel(h);
      const place = esc(h.place || h.title || h.type || "");
      const when = h.time ? esc(fmtAgo(h.time)) : "";
      // A grouped entry is ONE event two providers both reported — a deduction
      // from coordinates and time, labelled as such, never presented as a
      // provider statement. Both providers are named.
      const provs = (h.providers && h.providers.length) ? h.providers : (h.source ? [h.source] : []);
      const prov = provs.length
        ? ` <span class="muted">${esc(t("via {p}").replace("{p}", provs.join(" + ")))}</span>`
        : "";
      const grouped = h.grouped
        ? ` <span class="pill tiny" title="${esc(t("Same hazard type, within 0.5° and 2 hours — a deduced grouping of two providers' reports of one event, never a merge of the stored records."))}">${esc(t("grouped"))}</span>`
        : "";
      const mapBtn = (typeof h.lat === "number" && typeof h.lon === "number")
        ? ` <button class="ghost tiny" onclick="openWorldMapAt(${h.lat}, ${h.lon}, ${esc(JSON.stringify(h.time || null))}, ${h.article_id != null ? h.article_id : "null"})" title="${esc(t("Open on the World map"))}">🗺</button>`
        : "";
      const artLink = (h.article_id != null)
        ? ` <a href="/api/articles/${h.article_id}/view" target="_blank" rel="noopener" class="ghost tiny" title="${esc(t("Open the local article"))}">📄</a>`
        : "";
      const srcLink = (h.url && /^https?:\/\//i.test(h.url)) ? " " + extLink(h.url, t("source ↗")) : "";
      return `<li class="alert-hazard-item${h.major ? " haz-major" : ""}">${glyph} ${kind}${mag}${place}`
        + `${when ? ` <span class="muted">· ${when}</span>` : ""}${prov}${grouped}${mapBtn}${artLink}${srcLink}</li>`;
    }
    function _renderHomeAlerts(d) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("home-alerts"); if (!box) return;
      const TIER_LABEL = { urgent: t("Urgent"), watch: t("Watch"), info: t("Info") };
      const TIER_CLASS = { urgent: "err", watch: "warn", info: "" };
      // The DISPLAY floor (2026-08-01 rulings 1-2). The backend already ordered
      // each tier by the provider's own facts and marked which entries clear the
      // floor; the strip shows those first, capped, and collapses the rest into
      // ONE line that opens the World map. Nothing is removed: every hazard is
      // still in this payload, on the map, and behind "Open corpus" — which is
      // what makes a floor honest rather than a silent exclusion.
      const cap = Math.max(1, Number(d.strip_cap) || 5);
      const blocks = ["urgent", "watch", "info"].map(tier => {
        const T = (d.tiers || {})[tier];
        if (!T || !T.count) return "";
        const items = [];
        const hz = T.hazards || [];
        const major = hz.filter(h => h.major);
        const shown = major.length ? major.slice(0, cap) : hz.slice(0, cap);
        const hidden = hz.length - shown.length;
        shown.forEach(h => items.push(_hazardStripItem(h)));
        if (hidden > 0) {
          const note = major.length
            ? t("{n} more, below the M{m} display floor — open the World map")
            : t("{n} more — open the World map");
          items.push(`<li class="alert-more"><button class="ghost tiny" onclick="openWorldMapHazards()">`
            + esc(note.replace("{n}", String(hidden))
                     .replace("{m}", fmtNum(d.major_min_magnitude != null ? d.major_min_magnitude : 6, 1)))
            + ` →</button></li>`);
        }
        (T.watches || []).forEach(w => {
          const nm = esc(w.name || w.query || "");
          const n = (w.n_articles != null) ? ` <span class="muted">${esc(String(w.n_articles))} ${esc(t("articles"))}</span>` : "";
          items.push(`<li>${nm}${n}</li>`);
        });
        (T.convergences || []).forEach(c => {
          const pl = [c.place || "", c.place_country || ""].filter(Boolean).map(esc).join(", ");
          const meta = ` <span class="muted">${esc(String(c.distinct_sources || 0))} ${esc(t("sources"))} · ${esc(String(c.n_articles || 0))} ${esc(t("articles"))}</span>`;
          items.push(`<li>${pl}${meta}</li>`);
        });
        const open = (Array.isArray(T.article_ids) && T.article_ids.length)
          ? ` <button class="ghost tiny" onclick="openAnalysisForIds(${esc(JSON.stringify(T.article_ids))}, ${esc(JSON.stringify(TIER_LABEL[tier]))})">${esc(t("Open corpus"))} ↗</button>`
          : "";
        return `<div class="alert-tier"><span class="pill ${TIER_CLASS[tier]}">${esc(TIER_LABEL[tier])} · ${esc(String(T.count))}</span>${open}<ul>${items.join("")}</ul></div>`;
      }).join("");
      // Hazard-snapshot staleness (silence is not safety): state the age + stale flag, or
      // that there is no local snapshot at all.
      let stale;
      if (d.hazards_available) {
        const age = (d.hazards_age_hours != null) ? " (" + esc(t("{h}h old").replace("{h}", Math.round(d.hazards_age_hours))) + ")" : "";
        const asof = d.hazards_as_of ? esc(String(d.hazards_as_of).slice(0, 16).replace("T", " ")) : "—";
        stale = `<span class="hint">${esc(t("Hazard snapshot"))}: ${asof}${age}${d.hazards_stale ? " · " + esc(t("stale")) : ""}</span>`;
      } else {
        stale = `<span class="hint">${esc(t("No local hazard snapshot — silence is not safety."))}</span>`;
      }
      // Caveat VISIBLE by default (#23); the method rides the #oo-tip hover (the "how").
      const caveat = d.caveat ? `<div class="card-caveat" title="${esc(d.method || "")}">${esc(d.caveat)}</div>` : "";
      box.innerHTML = `<div class="phead"><h2>${esc(t("Alerts"))}</h2><span class="sp"></span>${stale}</div>`
        + blocks + caveat;
    }
    // Live Home (the at-a-glance strip + briefing self-update; no Refresh button).
    // Only runs while Home is the active, visible tab (the LIVE registry). Cheap:
    // stats are server-cached ~30 s; the briefing feed re-renders ONLY when its
    // generated_at actually changes, so the user's card triage is never reset.
    async function refreshHomeLive() {
      // Awaited end-to-end so the LIVE single-flight guard covers the WHOLE Home chain
      // (under 429 backpressure a poll can outlast its 15 s interval; without this the
      // trailing trends/alerts would race the next tick).
      try { const s = await api("/api/database/stats", {polled: true}); renderHomeStats(s.counts, s); } catch (e) {}
      try { const sc = await api("/api/scheduler/status", {polled: true}); renderHomeStatus(sc.running); } catch (e) {}
      try {
        const data = await api("/api/briefing", {polled: true});
        if (data.generated_at !== _lastBriefGen) renderBriefing(data);
      } catch (e) {}
      try { await loadHomeTrends(); } catch (e) {}
      try { await loadHomeAlerts(); } catch (e) {}
    }

    // -- The Home briefing (triage cards) ----------------------------------- //
    // Cards are produced server-side from real analytics; this layer only renders
    // them and lets the user triage (dismiss / add to draft). It never computes a
    // verdict. The full method + caveat for every figure is one toggle away.
    let _briefCards = {};   // id -> card (so "Add to draft" has the full card)
    let _lastBriefGen = null;  // last rendered briefing generated_at (live-refresh guard)

    async function loadBriefing(force) {
      const feed = $("briefing-feed");
      try {
        const data = await api("/api/briefing" + (force ? "?force=true" : ""));
        renderBriefing(data);
      } catch (e) {
        feed.innerHTML = '<div class="muted">Briefing unavailable right now.</div>';
      }
    }

    async function refreshBriefing() {
      const btn = $("brief-refresh-btn");
      if (btn) { btn.disabled = true; btn.textContent = "Refreshing…"; }
      try { const data = await api("/api/briefing/refresh", {method:"POST"}); renderBriefing(data); toast("Briefing refreshed."); }
      catch (e) { toast("Could not refresh briefing: " + e.message, "err"); }
      finally { if (btn) { btn.disabled = false; btn.textContent = "Refresh"; } }
    }

    // -- Corpus maturity tier (descriptive STAGE, never a score) ------------ //
    // Calibrates how much weight the evidence cards deserve. The visible surface
    // keeps the stage word + the REAL "N articles · M days" present; an EARLY
    // corpus also shows the short "thin evidence" caveat inline. The long plain-
    // language explanation AND the exact thresholds live in the #oo-tip hover
    // (informed-consent layering, invariant #17). Numbers come from the backend;
    // the JS only formats — no second corpus-age definition lives here.
    function renderCorpusTier(ct) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const el = $("home-tier"); if (!el) return;
      if (!ct || !ct.tier) { el.hidden = true; el.innerHTML = ""; el.removeAttribute("title"); return; }
      const tier = ct.tier;
      const arts = (ct.articles || 0).toLocaleString();
      const days = (ct.age_days || 0).toLocaleString();
      const th = ct.thresholds || {};
      // The stage word (one of three constant labels — each keyed ×12).
      const stageLabel = t(tier === "early" ? "Early corpus"
        : tier === "established" ? "Established corpus" : "Developing corpus");
      // The real numbers, always shown beside the stage (constant unit labels keyed).
      const nums = `${arts} ${t("articles")} · ${days} ${t("days")}`;
      // What the stage MEANS (plain language) + the exact thresholds — the hover
      // long form. Built from keyed sentence fragments + the real numbers so the
      // bubble is translated ×12 by construction (i18n.t on each fragment).
      const meaning = t(tier === "early"
          ? "Early stage: the Leads rest on thin evidence — read them as first hints, not established patterns."
          : tier === "established"
          ? "Established stage: enough breadth and time for patterns to be more than a first hint — still descriptive, never a verdict."
          : "Developing stage: patterns are forming but the corpus is not yet broad or old enough to lean on heavily.");
      const rule = t("Stages are descriptive, from real corpus facts — never a score.") + " " +
        t("Thresholds: early is below {a} articles or {d} days; established is at least {b} articles and {e} days; developing is in between.")
          .replace("{a}", th.young_articles ?? 200)
          .replace("{d}", th.min_span_days ?? 14)
          .replace("{b}", th.established_articles ?? 1000)
          .replace("{e}", th.established_days ?? 90);
      el.className = "corpus-tier tier-" + tier;
      // The #oo-tip hover re-reads this live-translated title (invariant #17).
      el.title = stageLabel + " — " + meaning + " " + rule;
      const caveat = (tier === "early")
        ? `<span class="tier-caveat">${esc(t("thin evidence — read with care"))}</span>` : "";
      el.innerHTML =
        `<span class="tier-badge">${esc(stageLabel)}</span>` +
        `<span class="tier-nums">${esc(nums)}</span>` + caveat;
      el.hidden = false;
    }

    function renderBriefing(data) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      _briefCards = {};
      renderCorpusTier(data.corpus_tier);
      _lastBriefGen = data.generated_at || null;
      const feed = $("briefing-feed");
      const gen = $("brief-generated");
      if (gen) gen.textContent = data.generated_at ? (t("updated") + " " + fmtDateTime(data.generated_at)) : "";
      // Recompute now runs OFF the request thread (field test 2026-06-24: Home froze on
      // "Loading the briefing…" at 60K). While a background refresh runs we show a real
      // progress bar and re-poll until cards land; if we already have (stale) cards we
      // keep showing them under a slim "updating…" banner so Home is never blank.
      const refreshing = !!(data.refreshing || data.building);
      if (refreshing) _scheduleBriefRepoll(); else _cancelBriefRepoll();
      const banner = refreshing ? briefProgressHtml(data, t) : "";
      if (!data.buckets || !data.buckets.length) {
        if (refreshing) { feed.innerHTML = banner; return; }
        feed.innerHTML = `<div class="card">
          <h4>No Leads yet — that's expected on a young corpus</h4>
          <p class="sum">Leads are computed from YOUR collected material; an empty feed means the
          signals haven't accumulated, never that the engine is gone. As the corpus grows you'll see:
          <b>Rising now</b> (terms accelerating vs their own baseline), <b>Overtold/Undertold</b>,
          <b>framing splits</b>, <b>promises due</b> (a mentioned future date arrives),
          <b>edit-war bursts</b> on tracked Wikipedia pages, <b>regions gone quiet</b>,
          and <b>source candidates</b> from offline discovery.</p>
          <p class="muted" style="margin-top:6px">Collection and Leads update automatically in the
          background while you're online — there's nothing to start by hand.</p></div>`;
        return;
      }
      // Family-type colors: see famHue -- keyed on the family's STABLE name, so a
      // family keeps its colour as the set of non-empty families changes. Applied as
      // the card left-accent (--fam) so the feed stays scannable in "All", and echoed
      // as a dot in the family subtab. "All cards" is the default lens (a single
      // prioritised feed); the families are a lens, never a wall (§5).
      // The server's OWN family label, remembered per stable bucket key so a card's
      // provenance can carry it (ruling 16) without app.js keeping a second copy of
      // BUCKET_LABELS that could drift from the Python one.
      data.buckets.forEach(b => { if (b && b.bucket) _famLabels[b.bucket] = b.label || ""; });
      const html = data.buckets.map((b, bi) => {
        b.cards.forEach(c => { _briefCards[c.id] = c; });
        const cards = b.cards.map(cardHtml).join("");
        return `<div class="brief-bucket" data-fam="${bi}" style="--fam:${famHue(b.bucket)}">`
          + `<h3>${esc(b.label)} <span class="ct">· ${b.cards.length}</span></h3>`
          + `<div class="cards">${cards}</div></div>`;
      }).join("");
      // OVERVIEW (2026-08-01 rulings 5-8): the DEFAULT lens is the top card of each
      // family, taken from the feed's OWN already-sorted order — one ordering
      // system, not a second selector. Each card carries the visible "why this
      // card" (order_explain), which restores the transparency surface the
      // Settings restructure removed when it deleted the Leads preview. "All
      // Leads" keeps the full feed; nothing is lost, the wall is just no longer
      // the first thing you meet.
      const ovHtml = _overviewHtml(data, t);
      const famTabs = `<button class="active" data-tab="__ov">${esc(t("Overview"))}</button>`
        + `<button data-tab="__all">${esc(t("All Leads"))}</button>`
        + data.buckets.map((b, bi) =>
            `<button data-tab="${bi}"><span class="fam-dot" style="background:${famHue(b.bucket)}"></span>${esc(b.label)}</button>`).join("")
        + _homePanelTabsHtml(t);
      feed.innerHTML = banner
        + `<nav class="tabs home-fam" id="home-fam-subtabs">${famTabs}</nav>`
        + ovHtml + html;
      ooSubtabs($("home-fam-subtabs"), selectHomeFamily, {initial: _homeTabKey});
      selectHomeFamily(_homeTabKey);
      _renderOverviewTrends();
    }
    // FAMILY IDENTITY COLOUR (ruling 14, field feedback 2026-08-07).
    //
    // Was `bi => hsl((bi * 53) % 360 ...)` -- keyed on the family's POSITION in the
    // rendered list. Position is not identity: a family with no cards this pass is
    // omitted, so every family after it shifts up and changes colour. The colour
    // therefore moved for reasons that had nothing to do with the family, which makes
    // it useless as the thing it is for -- recognising a family at a glance.
    //
    // Keyed on `bucket`, the STABLE machine key ("rising", "overtold", ...), never on:
    //   * the index -- the defect above;
    //   * `label` -- that is the TRANSLATED display string, so hashing it would give a
    //     French reader different colours from an English one for the same families.
    //
    // Curated table + hash fallback, exactly like agCatHue below: the eight shipped
    // families get hand-picked hues that are pairwise separable (>= 30 degrees apart --
    // a hash alone can place two families a few degrees from each other, and "these two
    // look the same" is the whole failure being fixed), while a family added later still
    // gets a deterministic colour with no code change. Colour is decorative and
    // reinforcing: the label is always present and remains the real identifier.
    //
    // This CHANGES today's Home colours, which is the point -- ruling 14 accepts a new
    // palette in exchange for one that stops moving.
    // bucket key -> the family label the SERVER sent (filled by renderBriefing).
    const _famLabels = {};
    const FAM_HUE = {
      rising: 145, watch: 55, overtold: 25, context: 175,
      investigate: 205, undertold: 265, trust: 300, debunk: 340,
    };
    function famHue(name) {
      const key = String(name == null ? "" : name);
      let h = FAM_HUE[key];
      if (h == null) {
        // Same 31-multiplier walk as agCatHue, so the two surfaces derive an unknown
        // key's hue the same way rather than each inventing an arithmetic.
        let n = 0;
        for (let i = 0; i < key.length; i++) n = (n * 31 + key.charCodeAt(i)) >>> 0;
        h = n % 360;
      }
      return `hsl(${h} 60% 55%)`;
    }
    // The Overview lens: TOP-1 card per family, in the feed's own disclosed order.
    function _overviewHtml(data, t) {
      const tops = data.buckets.map((b, bi) => {
        const c = (b.cards || [])[0];
        if (!c) return "";
        // The card renders exactly as it does in its family (same component, same
        // actions), plus the disclosed reason it leads its family.
        const why = c.order_explain
          ? `<div class="ov-why" title="${esc(c.order_explain)}">${esc(c.order_explain)}</div>` : "";
        return `<div class="ov-item" style="--fam:${famHue(b.bucket)}">`
          + `<h4 class="ov-fam"><span class="fam-dot" style="background:${famHue(b.bucket)}"></span>${esc(b.label)}`
          + ` <a href="#" class="ov-more" onclick='selectHomeFamily(${esc(JSON.stringify(String(bi)))});return false'>`
          + `${esc(t("all {n}").replace("{n}", String((b.cards || []).length)))} →</a></h4>`
          + `<div class="cards">${cardHtml(c)}</div>${why}</div>`;
      }).join("");
      return `<div class="brief-bucket" data-fam="__ov">`
        + `<div id="ov-trending"></div>`
        + `<div class="ov-grid">${tops}</div>`
        + `<div class="card-caveat">${esc(t("One Lead per family, chosen by the same disclosed order as the full feed — independent sources, then sample magnitude, then recency. Never a score, and nothing is hidden: “All Leads” has every card."))}</div>`
        + `</div>`;
    }

    // -- S4.3: the synthesized-Leads carousel (Home dashboard) --------------------------- //
    // A rolling rotation of the TOP local-analytic Leads (never LLM — Home is zero-network).
    // PAUSABLE (WCAG 2.2: pause on hover/focus + a manual toggle); the caveat rides EVERY face
    // so a timed rotation never hides it (#23); each face DEEP-LINKS (#8) via the SAME action
    // the full card uses; ordering is the briefing's own (evidence tier + recency + spread —
    // never a hidden score). Hidden with <2 Leads so Home is never blank-and-silent.
    let _carTimer = null, _carIdx = 0, _carCards = [], _carPaused = false;

    function renderLeadsCarousel(cards) {
      const panel = $("home-carousel-panel"), host = $("home-carousel");
      if (!panel || !host) return;
      _carStop();
      _carCards = (cards || []).filter(c => c && c.title).slice(0, 8);
      if (_carCards.length < 2) { panel.hidden = true; host.innerHTML = ""; return; }
      panel.hidden = false;
      _carIdx = 0;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      host.innerHTML =
        `<div class="carousel" role="region" aria-roledescription="${esc(t("carousel"))}" aria-label="${esc(t("Leads"))}" tabindex="0">`
        + `<div class="carousel-face" id="carousel-face" aria-live="polite"></div>`
        + `<div class="carousel-ctl">`
        +   `<button class="tiny secondary" onclick="carouselStep(-1)" aria-label="${esc(t("Previous Lead"))}">‹</button>`
        +   `<button class="tiny secondary" id="carousel-pause" onclick="carouselToggle()" aria-pressed="false" aria-label="${esc(t("Pause the carousel"))}">⏸</button>`
        +   `<button class="tiny secondary" onclick="carouselStep(1)" aria-label="${esc(t("Next Lead"))}">›</button>`
        +   `<span class="carousel-dots" id="carousel-dots"></span>`
        + `</div></div>`;
      const car = host.querySelector(".carousel");
      // WCAG 2.2: the auto-rotation pauses on hover/focus, plus the explicit pause toggle.
      car.addEventListener("mouseenter", _carHold);
      car.addEventListener("mouseleave", _carRelease);
      car.addEventListener("focusin", _carHold);
      car.addEventListener("focusout", _carRelease);
      car.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") { carouselStep(-1); e.preventDefault(); }
        else if (e.key === "ArrowRight") { carouselStep(1); e.preventDefault(); }
      });
      _carPaint();
      if (!_carPaused) _carStart();
    }

    function _carPaint() {
      const face = $("carousel-face"); if (!face || !_carCards.length) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const c = _carCards[_carIdx]; if (!c) return;
      const n = _carCards.length;
      const aq = cardAnalyzeQuery(c);
      const aIds = (Array.isArray(c.article_ids) && c.article_ids.length) ? c.article_ids : null;
      const action = aIds
        ? `openCardCorpus(${esc(JSON.stringify(aIds))}, ${esc(JSON.stringify(aq))}, null, ${esc(JSON.stringify(cardProvenance(c)))})`
        : `openCardCorpusQuery(${esc(JSON.stringify(aq))}, null, ${esc(JSON.stringify(cardProvenance(c)))})`;
      // the CAVEAT rides EVERY rotated face — a timed rotation never hides it (#23 + the brief).
      const caveat = c.caveat ? `<p class="card-caveat">${esc(c.caveat)}</p>` : "";
      face.innerHTML =
        `<div class="carousel-card bk-${esc(c.bucket)}" role="group" aria-label="${esc(t("Lead"))} ${_carIdx + 1} / ${n}">`
        + `<h4>${esc(cardTitle(c))}</h4>`
        + (c.summary ? `<p class="sum">${esc(c.summary)}</p>` : "")
        + caveat
        + `<div><button class="tiny" onclick="${action}">${esc(t("Open corpus"))} ↗</button></div>`
        + `</div>`;
      const dots = $("carousel-dots");
      if (dots) dots.innerHTML = _carCards.map((_, i) =>
        `<button class="carousel-dot${i === _carIdx ? " on" : ""}" onclick="carouselGo(${i})" aria-label="${esc(t("Lead"))} ${i + 1}"${i === _carIdx ? ' aria-current="true"' : ""}></button>`).join("");
    }

    function carouselStep(d) {
      if (!_carCards.length) return;
      _carIdx = (_carIdx + d + _carCards.length) % _carCards.length;
      _carPaint();
    }
    function carouselGo(i) { _carIdx = i; _carPaint(); }
    function carouselToggle() {
      _carPaused = !_carPaused;
      const b = $("carousel-pause");
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (b) {
        b.textContent = _carPaused ? "▶" : "⏸";
        b.setAttribute("aria-pressed", _carPaused ? "true" : "false");
        b.setAttribute("aria-label", _carPaused ? t("Play the carousel") : t("Pause the carousel"));
      }
      if (_carPaused) _carStop(); else _carStart();
    }
    function _carStart() { _carStop(); if (_carPaused || _carCards.length < 2) return; _carTimer = setInterval(() => carouselStep(1), 7000); }
    function _carStop() { if (_carTimer) { clearInterval(_carTimer); _carTimer = null; } }
    function _carHold() { _carStop(); }                 // hover/focus pause (keeps the user's toggle state)
    function _carRelease() { if (!_carPaused) _carStart(); }

    // The "pleasing progress bar" for a background briefing recompute (remarks 6/7).
    // Determinate once producers report (done/total), indeterminate until then. Honest:
    // it counts ANALYSES completed, not elapsed time (producers vary in cost), and is
    // labelled as such — never a fabricated time estimate.
    function briefProgressHtml(data, t) {
      t = t || ((s) => s);
      const p = data.progress || {};
      const total = +p.total || 0, done = +p.done || 0;
      const label = data.building ? t("Building your briefing…") : t("Updating your briefing…");
      const bar = total > 0
        ? `<progress max="${total}" value="${done}" style="width:100%;height:8px"></progress>`
        : `<progress style="width:100%;height:8px"></progress>`;
      const detail = total > 0 ? `${done} / ${total} ${t("analyses")}` : "";
      return `<div class="brief-progress card" role="status" aria-live="polite" style="margin-bottom:10px">`
        + `<div style="display:flex;justify-content:space-between;gap:8px">`
        + `<span>${esc(label)}</span><span class="muted">${esc(detail)}</span></div>${bar}</div>`;
    }
    // Re-poll the briefing while a background recompute runs so the bar advances and the
    // final cards appear without a manual reload. One timer at a time; renderBriefing
    // cancels it on a non-refreshing payload. 1.5 s is responsive without hammering.
    let _briefRepoll = null;
    function _scheduleBriefRepoll() {
      if (_briefRepoll) return;
      _briefRepoll = setTimeout(() => { _briefRepoll = null; loadBriefing(); }, 1500);
    }
    function _cancelBriefRepoll() {
      if (_briefRepoll) { clearTimeout(_briefRepoll); _briefRepoll = null; }
    }
    // The standalone Home panels become SUBTABS beside the families (ruling 7a):
    // the long scroll was every block stacked at once. They keep their own DOM,
    // their own loaders and their own honest empty states — only their visibility
    // is driven from here, so nothing is lost and no listener is re-bound.
    let _homeTabKey = "__ov";
    const _HOME_PANEL_TABS = [
      {key: "__recent", id: "home-recent-panel", label: "Most recent"},
      {key: "__latest", id: "home-latest-panel", label: "Latest in your corpus"},
      {key: "__channels", id: "home-channels-panel", label: "By channel"},
    ];
    // A panel tab appears only once its panel has something to show: these panels
    // unhide themselves when loaded (and stay hidden when there is nothing), so
    // offering a tab onto an empty panel would be offering an empty room.
    function _homePanelTabsHtml(t) {
      return _HOME_PANEL_TABS.filter(p => { const el = $(p.id); return el && !el.hidden; })
        .map(p => `<button data-tab="${p.key}">${esc(t(p.label))}</button>`).join("");
    }
    function selectHomeFamily(key) {
      _homeTabKey = key;
      const panelKeys = _HOME_PANEL_TABS.map(p => p.key);
      const onPanel = panelKeys.indexOf(key) !== -1;
      document.querySelectorAll("#briefing-feed .brief-bucket").forEach(el => {
        const fam = el.dataset.fam;
        const show = onPanel ? false
          : (key === "__ov") ? (fam === "__ov")
          : (key === "__all") ? (fam !== "__ov")
          : (fam === key);
        el.style.display = show ? "" : "none";
      });
      // Clearing the inline style (rather than forcing a display) lets each panel's
      // own `hidden` still win — a panel with nothing to show stays hidden even
      // while its tab is selected, instead of rendering an empty box.
      _HOME_PANEL_TABS.forEach(p => {
        const el = $(p.id);
        if (el) el.style.display = (key === p.key) ? "" : "none";
      });
      // Trending is folded INTO Overview as a compact row, so its standalone panel
      // no longer competes for the same screen (ruling 7a).
      const tr = $("home-trends-panel");
      if (tr) tr.style.display = "none";
    }
    // Re-sync after an async panel loader unhides its panel: the subtab list is
    // built from what is actually available, so a panel that arrives late must be
    // able to claim its tab (and must not stay force-hidden by a stale inline
    // style set before it had content).
    function _syncHomeSubtabs() {
      const nav = $("home-fam-subtabs");
      if (!nav) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const want = _HOME_PANEL_TABS.filter(p => { const el = $(p.id); return el && !el.hidden; })
        .map(p => p.key).join(",");
      const have = Array.prototype.slice.call(nav.querySelectorAll("button[data-tab]"))
        .map(b => b.dataset.tab).filter(k => _HOME_PANEL_TABS.some(p => p.key === k)).join(",");
      if (want === have) { selectHomeFamily(_homeTabKey); return; }
      _HOME_PANEL_TABS.forEach(p => {
        const btn = nav.querySelector(`button[data-tab="${p.key}"]`);
        const el = $(p.id), avail = !!(el && !el.hidden);
        if (avail && !btn) {
          const b = document.createElement("button");
          b.dataset.tab = p.key; b.textContent = t(p.label);
          nav.appendChild(b);
        } else if (!avail && btn) {
          if (_homeTabKey === p.key) _homeTabKey = "__ov";
          btn.remove();
        }
      });
      ooSubtabs(nav, selectHomeFamily, {initial: _homeTabKey});
      selectHomeFamily(_homeTabKey);
    }
    // The compact Trending row inside Overview (ruling 7a). Reuses the SAME stashed
    // payload the standalone panel already fetched — no second request, no new poll.
    function _renderOverviewTrends() {
      const host = $("ov-trending");
      if (!host) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const terms = _homeTrendTerms || [];
      if (!terms.length) { host.innerHTML = ""; return; }
      const chips = terms.slice(0, 6).map(x =>
        `<a class="chip tiny" href="#" onclick='openAnalysisFor(${esc(JSON.stringify(x.term))});return false'`
        + ` title="${esc(t("Open this keyword's own analysis window"))}">${esc(x.term)}`
        + ` <span class="muted">${esc(growthFallback(x) || `↑${x.growth}× · ${x.recent}`)}</span></a>`).join("");
      host.innerHTML = `<div class="ov-trend"><span class="muted">${esc(t("Trending now"))}:</span>${chips}`
        + `<a class="ov-more" href="#" onclick="showTab('insights');return false">${esc(t("More in Insights"))} →</a></div>`
        + (_homeTrendCaveat ? `<div class="hint muted" style="font-size:11px">${esc(_homeTrendCaveat)}</div>` : "");
    }

    // The query that reproduces a card's article selection in the analysis window
    // (maintainer 2026-06-16: clicking a card opens the unified analysis interface
    // "whose corpus corresponds to the selection of articles the card identified").
    // Prefer the quoted term in the title (the original searchable surface form),
    // then the card key (the normalized term/identity), then the bare title. For
    // keyword/topic cards this is the EXACT, full selection (openAnalysisFor re-runs
    // the same FTS search); for set-based cards it is the closest honest query and
    // the analysis window states its scope.
    function cardAnalyzeQuery(c) {
      const m = (c.title || "").match(/[“"]([^”"]{2,})[”"]/);
      if (m && m[1].trim()) return m[1].trim();
      if (c.key && String(c.key).trim()) return String(c.key).trim();
      return (c.title || "").replace(/[“”"]/g, "").trim();
    }
    // S4.5: a card's DISPLAY title. When the producer emits a translatable title
    // (title_i18n = a fixed keyable template + title_vars = language-neutral data),
    // render OOI18N.tf(template, vars) — the frame translates ×12, the keyword term
    // stays data. Otherwise the English `title` (additive fallback; cards without a
    // template, or a browser without tf, are byte-identical to before).
    function cardTitle(c) {
      if (c && c.title_i18n && window.OOI18N && OOI18N.tf) return OOI18N.tf(c.title_i18n, c.title_vars || {});
      return (c && c.title) || "";
    }
    // Click a Lead card to FLIP it (front <-> back). Inner controls (buttons/links/
    // inputs) are not flip triggers. Keyboard: Enter/Space flips when focused.
    function leadFlip(card, ev) {
      if (ev && ev.target && ev.target.closest("button,a,input,label,details,summary")) return;
      card.classList.toggle("flipped");
    }
    function leadFlipKey(card, ev) {
      if ((ev.key === "Enter" || ev.key === " ") &&
          !(ev.target && ev.target.closest("button,a,input,label,details,summary"))) {
        ev.preventDefault();
        card.classList.toggle("flipped");
      }
    }
    // dblclick-opens-duplicate-analysis-tabs (P1): a fast double-click (or an
    // accidental double-tap) on a card's "Open corpus" button fired window.open()
    // twice at the identical URL before the first tab settled -- neither
    // openCardCorpus nor openAnalysisInNewTab guarded against a second call for the
    // same URL in quick succession. A single user action should be idempotent
    // against an accidental repeat activation, so both now route through one
    // shared debounce: a call for the SAME URL within 700ms of the last one is a
    // no-op (a deliberate second open of a DIFFERENT corpus a moment later still
    // works normally -- only the identical-URL-in-quick-succession case is guarded).
    let _lastCorpusOpenUrl = "", _lastCorpusOpenAt = 0;
    function _openCorpusUrlOnce(url) {
      const now = Date.now();
      if (url === _lastCorpusOpenUrl && (now - _lastCorpusOpenAt) < 700) return;
      _lastCorpusOpenUrl = url; _lastCorpusOpenAt = now;
      window.open(url, "_blank", "noopener");
    }
    // Open the card's corpus IN A NEW WINDOW (maintainer 2026-06-23) — a real browser
    // tab the SPA hydrates from the URL (boot handler below), so the analysis lives
    // outside the current view. Exact set when the card carries article_ids, else the
    // seed query (the diagnostic flags any card whose query loses its corpus).
    // ---- LEAD PROVENANCE TRANSPORT (rulings 15/16) ---------------------------- //
    //
    // Ruling 16: the WHOLE provenance travels with a card into its analysis window --
    // the card, its family, the producer, the trigger, the method and the caveat.
    // TRANSPORT, never a new measurement: every field below is read off the card the
    // reader actually clicked and carried verbatim.
    //
    // Carried through localStorage under a one-shot token, not in the URL, because the
    // analysis opens in a NEW BROWSER TAB: sessionStorage does not cross tabs, and the
    // method + caveat + trigger math are whole sentences and rows, which would make an
    // unwieldy URL and can exceed length limits. The token is single-use -- the reading
    // tab deletes the entry as soon as it has it -- and a sweep bounds what a tab that
    // never opened can leave behind, so this can never grow without limit.
    const _AN_PROV_PREFIX = "oo.an.prov.";
    const _AN_PROV_KEEP = 8;        // most recent handoffs retained by the sweep
    const _AN_PROV_MAX_AGE_MS = 36e5;   // and nothing older than an hour survives it
    // The six fields ruling 16 names, read off the card. `bucket` is the STABLE family
    // key (the label is translated at render time, and the hue is derived from the key),
    // and `type` IS the producer identity -- one producer emits one card type.
    function cardProvenance(c) {
      if (!c) return null;
      return {
        card: cardTitle(c) || c.title || "",
        bucket: c.bucket || "",
        // The family's display label, taken from the server's own briefing payload at
        // the moment the card is rendered. Carried rather than looked up on arrival:
        // the analysis opens in a NEW browser tab, which may never have loaded Home and
        // so would have no label table at all.
        family: (c.bucket && _famLabels[c.bucket]) || "",
        producer: c.type || "",
        trigger: c.trigger || null,
        method: c.method || "",
        caveat: c.caveat || "",
      };
    }
    function _anProvSweep() {
      try {
        const now = Date.now();
        const mine = [];
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          if (k && k.indexOf(_AN_PROV_PREFIX) === 0) mine.push(k);
        }
        // Newest first: the token's tail is the creation time in base 36.
        mine.sort().reverse();
        mine.forEach((k, idx) => {
          const born = parseInt(String(k.slice(_AN_PROV_PREFIX.length)).split("-")[0], 36);
          const stale = !Number.isFinite(born) || (now - born) > _AN_PROV_MAX_AGE_MS;
          if (idx >= _AN_PROV_KEEP || stale) localStorage.removeItem(k);
        });
      } catch (_e) { /* private mode / quota -- a colour-and-caption feature never blocks a click */ }
    }
    function _anProvStash(prov) {
      if (!prov) return "";
      try {
        const token = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
        localStorage.setItem(_AN_PROV_PREFIX + token, JSON.stringify(prov));
        _anProvSweep();
        return token;
      } catch (_e) { return ""; }   // no storage -> the window still opens, just without the header
    }
    function _anProvTake(token) {
      if (!token) return null;
      try {
        const raw = localStorage.getItem(_AN_PROV_PREFIX + token);
        localStorage.removeItem(_AN_PROV_PREFIX + token);   // single use
        return raw ? JSON.parse(raw) : null;
      } catch (_e) { return null; }
    }
    function openCardCorpus(ids, label, tab, prov) {
      const p = new URLSearchParams();
      p.set("corpus", (ids || []).join(","));
      if (label) p.set("label", label);
      if (tab) p.set("tab", tab);   // item #5: land the new window on the type's best subtab
      const token = _anProvStash(prov);
      if (token) p.set("prov", token);
      _openCorpusUrlOnce("/?" + p.toString());
    }
    // Open a query's analysis window in a NEW BROWSER TAB (field remark 9: search +
    // Enter should open a new tab). A fresh SPA boot hydrates ?analyze= via
    // _hydrateCardCorpus() → openAnalysisFor(), so the new tab lands on the same
    // analysis. Shared by the home-card flip and the omnibar/palette Enter.
    function openAnalysisInNewTab(q, tab, prov) {
      const p = new URLSearchParams();
      p.set("analyze", q || "");
      if (tab) p.set("tab", tab);   // optional deep-link subtab (item #5); omnibar Enter omits it
      const token = _anProvStash(prov);
      if (token) p.set("prov", token);
      _openCorpusUrlOnce("/?" + p.toString());
    }
    function openCardCorpusQuery(q, tab, prov) { openAnalysisInNewTab(q, tab, prov); }
    // Route a Lead to the most useful analysis subtab for its type (item #5): a rising
    // keyword -> its Trend; a coordination/near-dup/framing Lead -> Related; a reading-diet
    // or coverage Lead -> Sources; a space-time convergence -> When/Where/Who. Anything
    // else lands on Overview. The deep-link only applies a tab whose an-<tab> panel exists.
    const _CARD_SUBTAB = {
      rising: "trend", manufactured_emergence: "trend", price_narrative: "trend",
      echo_chamber: "related", source_laundering: "related", flooded_topic: "related",
      copypasta: "related", recycled_claim: "related", headline_body_mismatch: "related",
      framing_split: "related",
      diet_self_audit: "sources", coverage_advisor: "sources", reading_diet: "sources",
      space_time_convergence: "www", weather_corroboration: "www",
    };
    function cardSubtab(c) { return (c && _CARD_SUBTAB[c.type]) || "overview"; }
    function cardHtml(c) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const sig = c.signal || {};
      const sigLine = (sig.metric != null && sig.value != null)
        ? `<div class="sig">${esc(sig.metric)} = ${esc(sig.value)}${c.n != null ? " · n=" + c.n : ""}</div>` : "";
      const evid = (c.evidence || []).filter(e => e && (e.url || e.title)).slice(0, 3).map(e => {
        const label = esc(e.title || e.url);
        const meta = [e.source, (e.published_at || "").slice(0,10)].filter(Boolean).map(esc).join(" · ");
        // External evidence opens the LOCAL preview first (invariant #6
        // extension, maintainer-repeated first target): never a bare jump.
        const ext = e.url && /^https?:\/\//i.test(e.url);
        const link = e.article_id
          ? `<a href="/api/articles/${e.article_id}/view" target="_blank" rel="noopener" title="offline stored copy">${label}</a>`
          : (e.url
            ? (ext
              ? `<a href="${esc(safeUrl(e.url))}" onclick="event.preventDefault();openLinkPreview('${esc(safeUrl(e.url))}')" title="Opens the local preview first — what your database knows about this link">${label}</a>`
              : `<a href="${esc(safeUrl(e.url))}" target="_blank" rel="noopener noreferrer">${label}</a>`)
            : label);
        return `<span>${link}${meta ? ` <span class="muted">— ${meta}</span>` : ""}</span>`;
      }).join("");
      const evidBlock = evid ? `<div class="evid">${evid}</div>` : "";
      const dismiss = c.dismissible === false ? ""
        : `<button class="ghost tiny" onclick="dismissCard(${esc(JSON.stringify(c.id))}, ${esc(JSON.stringify(c.type || ''))})">Dismiss</button>`;
      // Echo-chamber cards carry an actor signature: offer user-guided collapse (never auto).
      let collapseBtn = "";
      if (c.type === "echo_chamber" && sig.signature) {
        collapseBtn = sig.collapse_applied
          ? `<button class="secondary tiny" onclick="cardCollapse('${esc(sig.signature)}', false)">Expand (revert)</button>`
          : `<button class="secondary tiny" onclick="cardCollapse('${esc(sig.signature)}', true)" title="Count this coordinated network as one voice (reversible, stays flagged)">Collapse to one actor</button>`;
      }
      // Weather-corroboration cards (if-this-then-SUGGEST, 2026-06-12): the
      // bounded Open-Meteo fetch happens ONLY from this button, behind the one
      // consent popup — the producer that made the card never touched the network.
      let weatherBtn = "";
      let weatherBox = "";
      if (c.type === "weather_corroboration" && sig.lat != null && sig.lon != null) {
        weatherBtn = `<button class="secondary tiny" onclick="cardWeatherFetch('${c.id}')" title="Fetches the bounded Open-Meteo slice for this place and window — only after your consent.">Fetch weather context</button>`;
        weatherBox = `<div class="wx" id="wx-${c.id}" style="margin-top:6px"></div>`;
      }
      // Investigation recipe (0.0.8 WP8/RM-20): opens /investigate in a NEW tab,
      // fully URL-parameterised (shareable, no hidden state), main UI stays put.
      let recipeBtn = "";
      if (c.recipe && c.recipe.view) {
        const qp = new URLSearchParams({view: c.recipe.view, ...(c.recipe.params || {})});
        recipeBtn = `<a class="btnlike tiny" href="/investigate?${qp.toString()}" target="_blank" rel="noopener" title="Opens a dedicated investigation view in a new tab">Open investigation ↗</a>`;
      }
      // Flip cards (maintainer 2026-06-23): the front is the lead at a glance; the
      // BACK carries the method + the exact math + the caveat + evidence + the action
      // row. The verbose "why"/math is no longer behind a per-card "?" — the flip IS
      // the detail layer (the back has room). Labels are i18n-translated; math values
      // are numbers/symbols (language-neutral).
      const _whyRows = (c.trigger && c.trigger.math || []).map(r =>
        `<tr><td>${esc(r.label)}</td><td class="why-val">${esc(r.value)}</td></tr>`).join("");
      const _whyPlain = (c.trigger && c.trigger.plain) ? `<p class="why-plain">${esc(c.trigger.plain)}</p>` : "";
      const methodBlock = c.method ? `<div class="mc"><b>${esc(t("Method"))}:</b> ${esc(c.method)}</div>` : "";
      const mathBlock = _whyRows
        ? `<details class="card-info"><summary>${esc(t("The exact math"))}</summary>
             <table class="why-math">${_whyRows}</table></details>` : "";
      // The CAVEAT is VISIBLE on the BACK — an equal side of the card, revealed by ONE
      // flip (never a hidden toggle), right beside the action that opens its corpus
      // (#23 amended 2026-06-23 / informed-consent preserved by LAYERING, not hiding).
      const caveatLine = c.caveat ? `<p class="card-caveat">${esc(c.caveat)}</p>` : "";
      // The standardized, family-themed "open corpus" button — opens the card's corpus
      // IN A NEW WINDOW (exact set when the card carries article_ids, else the seed query).
      const _aq = cardAnalyzeQuery(c);
      const _aIds = (Array.isArray(c.article_ids) && c.article_ids.length) ? c.article_ids : null;
      const _tab = cardSubtab(c);   // item #5: the most useful analysis subtab for this Lead's type
      // Ruling 16: the whole provenance travels with the card into its analysis window.
      const _prov = cardProvenance(c);
      const _openCorpus = _aIds
        ? `openCardCorpus(${esc(JSON.stringify(_aIds))}, ${esc(JSON.stringify(_aq))}, ${esc(JSON.stringify(_tab))}, ${esc(JSON.stringify(_prov))})`
        : `openCardCorpusQuery(${esc(JSON.stringify(_aq))}, ${esc(JSON.stringify(_tab))}, ${esc(JSON.stringify(_prov))})`;
      const openBtn = _aq
        ? `<button class="lead-open" onclick="${_openCorpus}" title="${esc(t("Open this Lead's corpus in a new window"))}">${esc(t("Open corpus"))} ↗</button>`
        : "";
      const chip = `<span class="chip">${esc(c.type.replace(/_/g, " "))}</span>`;
      const _title = cardTitle(c);
      // lead-card-nested-interactive (P1, axe): role="button" tabindex="0" on this
      // OUTER container, while it ALSO hosted genuinely interactive descendants
      // (the back face's buttons/links once flipped), is an invalid ARIA pattern --
      // a "button" must not contain more focusable content. leadFlip/leadFlipKey
      // already guarded against clicks/keys originating from a nested interactive
      // element (so the CLICK BEHAVIOUR was already correct), but the STRUCTURE
      // itself was wrong. Fixed by moving the interactive button role onto the
      // FRONT face specifically (it has no interactive children of its own -- chip/
      // heading/summary/sig-line/hint are all plain text), and giving the BACK
      // face's own "Back" hint its own small, explicitly-scoped button instead of
      // relying on the whole (interactive-descendant-hosting) back face being
      // itself a button. The outer container is now role="group" -- a plain
      // semantic wrapper, not an interactive element that could conflict with what
      // it contains.
      return `<div class="card bk-${esc(c.bucket)}" data-card="${c.id}" role="group" aria-label="${esc(_title)}">
        <div class="card-inner">
          <div class="card-face card-front" tabindex="0" role="button" aria-label="${esc(_title)}"
               onclick="leadFlip(this.closest('.card'),event)" onkeydown="leadFlipKey(this.closest('.card'),event)">
            ${chip}
            <h4>${esc(_title)}</h4>
            <p class="sum">${esc(c.summary)}</p>
            ${sigLine}
            <span class="lead-flip-hint">${esc(t("Details & corpus"))} ⟲</span>
          </div>
          <div class="card-face card-back">
            ${chip}
            ${caveatLine}
            ${methodBlock}
            ${(_whyPlain || mathBlock) ? `<div class="why-mathlabel">${esc(t("Why am I seeing this?"))}</div>` : ""}
            ${_whyPlain}
            ${mathBlock}
            ${evidBlock}
            ${weatherBox}
            <div class="acts">
              ${openBtn}
              ${recipeBtn}
              ${weatherBtn}
              <button class="secondary tiny" onclick="addToDraft('${c.id}')">+ Add to draft</button>
              ${collapseBtn}
              ${dismiss}
            </div>
            <button class="lead-flip-hint back" onclick="leadFlip(this.closest('.card'))">⟲ ${esc(t("Back"))}</button>
            <!-- the Back button intentionally omits ",event": leadFlip's own
                 interactive-descendant guard (ev.target.closest("button,a,...")) would
                 always match the button ITSELF (ev.target IS the button), silently
                 blocking every flip-back click. Passing no event makes the guard's
                 "ev &&" check false, so it falls straight to the toggle -- exactly what
                 a dedicated, single-purpose flip-back control should do. -->
          </div>
        </div></div>`;
    }

    // The global "Show method" toggle was retired (P2-2, 2026-06-19): each Lead's
    // method + "why" now live behind a per-card "?" affordance (cardHtml -> infoBlock).

    // Reasons offered when dismissing a Lead (the evidence-tier feedback loop). The chip
    // KEYS are stable identifiers; only the labels translate. A free-text box captures
    // anything the chips don't cover.
    function _leadDismissReasons() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return [
        ["not-relevant", t("Not relevant")],
        ["already-knew", t("Already knew this")],
        ["too-noisy", t("Too noisy / repetitive")],
        ["not-useful", t("Not useful")],
        ["disagree", t("I don't think this holds")],
      ];
    }
    // Dismissing a Lead offers an OPTIONAL reason (POST /api/signals/dismiss-reason). The
    // reason is recorded SEPARATELY from the dismissed-id set, so a failed record never
    // blocks the (unchanged) dismissal mechanic (_dismissCardNow). A chip dismisses with
    // that reason; the text box + Dismiss confirm with typed text; "Dismiss" with an empty
    // box is a valid skip (an explicit "dismissed, no reason" — nothing is sent).
    function dismissCard(id, type) {
      const el = document.querySelector(`.card[data-card="${id}"]`);
      const acts = el && el.querySelector(".acts");
      if (!acts) { _dismissCardNow(id); return; }               // no card back — just dismiss
      if (acts.querySelector(".lead-dismiss-form")) return;     // already open
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const form = document.createElement("div");
      form.className = "lead-dismiss-form";
      form.style.cssText = "margin-top:6px;width:100%";
      form.addEventListener("click", (e) => e.stopPropagation());   // never flip the card while choosing
      const label = document.createElement("div");
      label.className = "hint"; label.textContent = t("Why dismiss? (optional)");
      const chips = document.createElement("div");
      chips.className = "lead-dreasons"; chips.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;margin:4px 0";
      _leadDismissReasons().forEach(([k, lbl]) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "ghost tiny"; b.textContent = lbl;
        b.addEventListener("click", (e) => { e.stopPropagation(); _leadDismissWith(id, type, k); });
        chips.appendChild(b);
      });
      const row = document.createElement("div");
      row.className = "row"; row.style.cssText = "gap:6px";
      const inp = document.createElement("input");
      inp.className = "lead-dreason-text"; inp.type = "text";
      inp.placeholder = t("Add a reason…"); inp.style.flex = "1";
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.stopPropagation(); _leadDismissWith(id, type, inp.value.trim()); }
      });
      const go = document.createElement("button");
      go.type = "button"; go.className = "ghost tiny"; go.textContent = t("Dismiss");
      go.addEventListener("click", (e) => { e.stopPropagation(); _leadDismissWith(id, type, inp.value.trim()); });
      row.appendChild(inp); row.appendChild(go);
      form.appendChild(label); form.appendChild(chips); form.appendChild(row);
      acts.appendChild(form);
      inp.focus();
    }
    function _leadDismissWith(id, type, reason) {
      // Record the OPTIONAL reason (best-effort — never blocks the dismissal); a blank
      // reason is a valid skip and is not sent.
      if (reason) {
        api("/api/signals/dismiss-reason", {method: "POST",
          body: JSON.stringify({card_id: id, reason: reason, card_type: type || null})}).catch(() => {});
      }
      _dismissCardNow(id);
    }
    async function _dismissCardNow(id) {
      try {
        await api("/api/briefing/dismiss", {method:"POST", body: JSON.stringify({id})});
        const el = document.querySelector(`.card[data-card="${id}"]`);
        if (el) el.remove();
      } catch (e) { toast("Could not dismiss: " + e.message, "err"); }
    }

    // --- Local link preview (invariant #6 extension) ---------------------------
    // The database extraction for an outbound URL, shown BEFORE leaving the
    // machine; the outbound anchor's text IS the full address, and clicking it
    // still passes the external-link confirm (invariant #7) — layered consent.
    //
    // extLink(): the ONE way to render an outbound "source ↗" link anywhere
    // (invariant #6e — search rows, markets, law, events, insights, reader…).
    // It never jumps straight out: it opens the local preview first. Use this
    // for every external source link so none can regress to a bare jump.
    // evidence-links-contrast-and-no-underline (P1): these links rendered at
    // 2.41:1 with no underline (axe: link-in-text-block) -- color alone is
    // insufficient distinction per WCAG 1.4.1. The shared "ext-link" class
    // (app.css) adds a permanent underline, since this IS the one shared
    // chokepoint every evidence link renders through.
    function extLink(url, label, cls, style) {
      const u = safeUrl(url);
      const classes = cls ? `ext-link ${cls}` : "ext-link";
      return `<a class="${classes}"${style ? ` style="${style}"` : ""} href="${esc(u)}" rel="noopener" `
        + `onclick="event.preventDefault();openLinkPreview('${esc(u)}')" `
        + `title="Opens the local preview first — what your database knows about this link">`
        + `${esc(label)}</a>`;
    }
    async function openLinkPreview(url) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const dlg = $("link-preview"), body = $("lp-body"), out = $("lp-out");
      if (!dlg) { window.open(url, "_blank", "noopener"); return false; }
      body.textContent = t("Loading…"); out.innerHTML = "";
      dlg.showModal();
      try {
        const d = await api("/api/links/preview?url=" + encodeURIComponent(url));
        const rows = [`<div class="muted small">${esc(d.domain)}</div>`];
        if (d.local_article) {
          rows.push(`<div>${esc(t("A stored local copy exists — read it without going online:"))} <a href="${esc(d.local_article.reader_url)}" target="_blank" rel="noopener">${esc(d.local_article.title || "")}</a></div>`);
        }
        if (d.known_source) {
          rows.push(`<div>${esc(t("Known source in your catalog:"))} <b>${esc(d.known_source.name)}</b>${d.known_source.country ? ` <span class="muted">(${esc(ooRegionName(d.known_source.country, String(d.known_source.country).toUpperCase()))})</span>` : ""}</div>`);
        }
        rows.push(`<div>${esc(t("Articles in your corpus citing this URL:"))} <b>${d.cited_by_articles}</b></div>`);
        if ((d.citing_examples || []).length) {
          rows.push(`<div class="muted small">${d.citing_examples.map(x => `<a href="/api/articles/${x.article_id}/view" target="_blank" rel="noopener">${esc(x.title || ("#" + x.article_id))}</a>`).join(" · ")}</div>`);
        }
        if (d.law_document) rows.push(`<div>${esc(t("Tracked law document:"))} <b>${esc(d.law_document.title)}</b> <span class="muted">(${esc(String(d.law_document.jurisdiction || "").toUpperCase())})</span></div>`);
        if (d.wiki_page) rows.push(`<div>${esc(t("Watched Wikipedia page:"))} <b>${esc(d.wiki_page.title)}</b> <span class="muted">(${esc(d.wiki_page.wiki)})</span></div>`);
        if (d.keywords && d.keywords.length) rows.push(`<div class="muted small">${esc(t("Top keywords of the local copy:"))} ${d.keywords.map(esc).join(", ")}</div>`);
        if (!d.local_article && !d.known_source && !d.cited_by_articles) rows.push(`<div class="muted">${esc(t("No local record of this link yet."))}</div>`);
        rows.push(`<div class="muted small" style="margin-top:4px" title="${esc(d.method || "")}">${esc(t("Built from your local database only — no network call."))}</div>`);
        body.innerHTML = rows.join("");
        out.innerHTML = `<div class="muted small">${esc(t("The transparent outbound link — its text is the full address; opening it leaves this machine:"))}</div>` +
          `<a href="${esc(safeUrl(d.url))}" target="_blank" rel="noopener noreferrer" style="word-break:break-all">${esc(d.url)}</a>`;
      } catch (e) {
        body.innerHTML = `<div class="note err">${esc(e.message)}</div>`;
        out.innerHTML = `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer" style="word-break:break-all">${esc(url)}</a>`;
      }
      return false;
    }

    // --- Weather corroboration (if-this-then-SUGGEST, 2026-06-12) -------------
    // The card only OFFERS the check; this click is the consent moment. The
    // fetch is one bounded (place, window) reanalysis slice through the same
    // ethical fetch path as everything else; failures render the honest
    // transport verdict, results render per-variable (one chart per unit —
    // mixed units on one axis would be a fabricated comparison).
    async function cardWeatherFetch(id) {
      const c = _briefCards[id]; if (!c) return;
      const sig = c.signal || {};
      const box = document.getElementById("wx-" + id); if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (!await ensureOnline(t("Fetch weather context for one place and time window (Open-Meteo)"))) return;
      box.textContent = t("Loading…");
      try {
        const body = {
          lat: sig.lat, lon: sig.lon,
          start_date: sig.window_start, end_date: sig.window_end,
          variables: String(sig.variables || "").split(",").filter(Boolean),
          label: sig.rule_label || c.title
        };
        const d = await api("/api/weather/context", {method: "POST", body: JSON.stringify(body)});
        renderWeatherContext(box, d, sig);
      } catch (e) {
        box.innerHTML = `<div class="note err">${esc(e.message)}</div>`;
      }
    }

    function renderWeatherContext(box, d, sig) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      if (!d || !d.ok) {
        const verdict = d ? `${d.verdict || ""} — ${d.verdict_note || ""}` : "";
        box.innerHTML = `<div class="note err"><b>${esc(t("Weather fetch refused:"))}</b> <span>${esc(verdict)}</span></div>`;
        return;
      }
      const days = (d.daily && d.daily.time) || [];
      const vars = Object.keys(d.daily || {}).filter(k => k !== "time");
      let html = "";
      vars.forEach(k => {
        html += `<div class="muted" style="margin:4px 0 2px">${esc(k)}${d.units && d.units[k] ? " (" + esc(d.units[k]) + ")" : ""}</div><div class="wx-chart" data-var="${esc(k)}"></div>`;
      });
      const prov = d.provenance || {};
      const facts = [
        prov.fetched_at ? prov.fetched_at.slice(0, 16).replace("T", " ") + " UTC" : "",
        d.cached ? t("cached copy") : "",
        (sig && sig.geocode) ? `geocode: ${sig.geocode}` : ""
      ].filter(Boolean).join(" · ");
      html += `<div class="muted small" style="margin-top:4px"><span title="${esc(prov.requested_url || "")}">${esc(t("Open-Meteo reanalysis (CC BY 4.0): a model estimate for this place and window — corroboration, never proof."))}</span> <span>${esc(facts)}</span></div>`;
      box.innerHTML = html;
      box.querySelectorAll(".wx-chart").forEach(el => {
        const k = el.getAttribute("data-var");
        const pts = days.map((dt, i) => ({t: dt, v: (d.daily[k] || [])[i]})).filter(p => p.v != null);
        if (pts.length) {
          try { ooChart(el, [{label: k, unit: (d.units && d.units[k]) || "", points: pts}], {height: 120}); }
          catch (_e) { el.textContent = pts.map(p => `${p.t}: ${p.v}`).join("  "); }
        } else {
          el.innerHTML = `<span class="muted small">${esc(t("No values were returned for this variable and window."))}</span>`;
        }
      });
    }

    // -- The newsletter draft (card → reproducible Markdown) ---------------- //
    async function addToDraft(id) {
      const card = _briefCards[id];
      if (!card) return;
      try {
        const d = await api("/api/briefing/draft/add", {method:"POST", body: JSON.stringify({card})});
        updateDraftCount(d.items.length);
        // Clickable (maintainer-ruled 2026-06-10): the confirmation IS the way in.
        toast("Added to draft — click to open it.", "ok", () => { showTab("home"); openDraft(); });
      } catch (e) { toast("Could not add to draft: " + e.message, "err"); }
    }
    async function refreshDraftCount() {
      try { const d = await api("/api/briefing/draft"); updateDraftCount((d.items||[]).length);
        const t = $("draft-title"); if (t && d.title) t.value = d.title; }
      catch (e) { /* draft is optional */ }
    }
    function updateDraftCount(n) { const el = $("draft-count"); if (el) el.textContent = n; }

    async function openDraft() {
      $("draft-panel").hidden = false;
      await renderDraft();
      $("draft-panel").scrollIntoView({behavior:"smooth", block:"start"});
    }
    function closeDraft() { $("draft-panel").hidden = true; }

    async function renderDraft() {
      const box = $("draft-items");
      try {
        const d = await api("/api/briefing/draft");
        updateDraftCount((d.items||[]).length);
        const t = $("draft-title"); if (t) t.value = d.title || "";
        if (!d.items || !d.items.length) { box.innerHTML = '<div class="muted">No Leads pinned yet. Use “+ Add to draft” on a briefing Lead.</div>'; return; }
        box.innerHTML = d.items.map(it => {
          const c = it.card;
          return `<div class="draft-item" data-id="${c.id}">
            <div class="di-body">
              <div class="di-title">${esc(c.title)}</div>
              <div class="hint" style="margin-top:2px">${esc(c.summary || "")}</div>
              <textarea placeholder="Your note (ships in the export)…" onchange="saveDraftItemNote('${c.id}', this.value)">${esc(it.note||"")}</textarea>
            </div>
            <button class="ghost tiny" onclick="removeDraftItem('${c.id}')">Remove</button>
          </div>`;
        }).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load the draft.</div>'; }
    }
    async function removeDraftItem(id) {
      try { const d = await api("/api/briefing/draft/" + encodeURIComponent(id), {method:"DELETE"});
        updateDraftCount((d.items||[]).length); renderDraft(); } catch (e) { toast(e.message, "err"); }
    }
    async function saveDraftItemNote(id, note) {
      try { await api("/api/briefing/draft/note", {method:"PUT", body: JSON.stringify({id, note})}); }
      catch (e) { toast("Could not save note: " + e.message, "err"); }
    }
    async function saveDraftTitle() {
      try { await api("/api/briefing/draft/title", {method:"PUT", body: JSON.stringify({title: $("draft-title").value})}); }
      catch (e) { toast(e.message, "err"); }
    }
    async function clearDraft() {
      if (!confirm("Clear all pinned Leads from the draft?")) return;
      try { await api("/api/briefing/draft/clear", {method:"POST"}); updateDraftCount(0); renderDraft(); }
      catch (e) { toast(e.message, "err"); }
    }
    function exportDraft() { window.open("/api/briefing/draft/export.md", "_blank"); }
    async function copyDraft() {
      try {
        const md = await (await fetch("/api/briefing/draft/export.md")).text();
        await navigator.clipboard.writeText(md);
        toast("Draft Markdown copied to clipboard.");
      } catch (e) { toast("Could not copy: " + e.message, "err"); }
    }

    // ===================================================================== //
    //  SOURCE INTEGRITY & ANTI-AMPLIFICATION (§6) — propose → you dispose     //
    // ===================================================================== //
    async function cardCollapse(signature, apply) {
      try {
        await api("/api/integrity/collapse/" + (apply ? "apply" : "revert"),
          {method:"POST", body: JSON.stringify({signature})});
        toast(apply ? "Collapsed to one actor (reversible)." : "Expanded — raw equal view restored.");
        await refreshBriefing();            // counts that measure consensus now reflect the choice
      } catch (e) { toast("Could not update collapse: " + e.message, "err"); }
    }

    function loadIntegrity() { loadMineAnnotations(); loadAuthors(); }

    async function loadActors() {
      const box = $("actors-list");
      box.innerHTML = '<div class="muted">Scanning recent corpus for coordination…</div>';
      try {
        const d = await api("/api/integrity/actors");
        if (!d.actors || !d.actors.length) {
          box.innerHTML = '<div class="muted">No coordinated near-duplicate clusters found in the recent window.</div>'; return;
        }
        box.innerHTML = `<p class="hint">${esc(d.caveat)}</p>` + d.actors.map(a => {
          const members = a.sources.map(esc).join(", ");
          const btn = a.applied
            ? `<button class="secondary tiny" onclick="collapseAction('${esc(a.signature)}', false)">Expand (revert)</button>`
            : `<button class="secondary tiny" onclick="collapseAction('${esc(a.signature)}', true)">Apply collapse</button>`;
          const flag = a.applied ? '<span class="pill ok">collapsed</span> ' : '<span class="pill warn">annotated only</span> ';
          return `<div class="panel" style="background:var(--panel2); margin-top:8px">
            ${flag}<b>${a.size} sources</b> · ${a.shared_stories} shared story(ies)
            ${a.shared_hosts && a.shared_hosts.length ? "· host "+esc(a.shared_hosts[0]) : ""}
            ${a.median_span_hours!=null ? "· ~"+a.median_span_hours+"h span" : ""}
            <div class="hint" style="margin-top:4px">${members}</div>
            <div class="acts" style="margin-top:6px">${btn}</div></div>`;
        }).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not scan: ' + esc(e.message) + '</div>'; }
    }
    async function collapseAction(sig, apply) {
      try { await api("/api/integrity/collapse/" + (apply?"apply":"revert"), {method:"POST", body: JSON.stringify({signature: sig})});
        loadActors(); } catch (e) { toast(e.message, "err"); }
    }
    async function revertAllCollapse() {
      try { await api("/api/integrity/collapse/revert_all", {method:"POST"}); toast("All collapses reverted."); loadActors(); }
      catch (e) { toast(e.message, "err"); }
    }

    async function loadProfile() {
      const src = $("prof-source").value.trim(); if (!src) return;
      const out = $("profile-out");
      out.innerHTML = '<div class="muted">Measuring…</div>';
      try {
        const p = await api("/api/integrity/profile?source=" + encodeURIComponent(src));
        const d = p.dimensions;
        const dim = (title, body, m, c) => `<div class="panel" style="background:var(--panel2); margin-top:8px">
          <b>${esc(title)}</b><div style="margin-top:4px">${body}</div>
          <div class="hint" style="margin-top:4px"><i>Method:</i> ${esc(m)}<br><i>Caveat:</i> ${esc(c)}</div></div>`;
        const co = d.coordination, nv = d.novelty, oc = d.output_capacity, tr = d.transparency, rec = d.track_record;
        out.innerHTML =
          `<p class="hint"><b>No composite score</b> — these are independent measured dimensions you weigh yourself.</p>` +
          dim("Coordination", co.is_member ? `Member of ${co.actors.length} detected actor(s).` : "No coordination detected.", co.method, co.caveat) +
          dim("Novelty (originates vs echoes)", nv.mean_ratio==null ? "Not enough data." : `Mean novelty <b>${nv.mean_ratio}</b> over ${nv.n} articles.`, nv.method, nv.caveat) +
          dim("Output capacity", `${oc.articles} articles · ~${oc.per_day}/day (corpus median ${oc.corpus_median_per_day}/day).`, oc.method, oc.caveat) +
          dim("Transparency", `${esc(tr.country?ooRegionName(tr.country,tr.country):"?")} · ${esc(tr.language?ooLangName(tr.language):"?")} · ownership: ${(tr.ownership_tags||[]).join(", ")||"—"} · leaning: ${(tr.leaning_tags||[]).join(", ")||"—"}`, tr.method, tr.caveat) +
          dim("Track record", `${rec.total_articles} articles in your corpus.`, rec.method, rec.caveat);
      } catch (e) { out.innerHTML = '<div class="muted">' + esc(e.message) + '</div>'; }
    }

    // -- Crowdsourced annotations (web of trust) ---------------------------- //
    async function addAnnotation() {
      const target = $("anno-target").value.trim(), kind = $("anno-kind").value, value = $("anno-value").value.trim();
      if (!target || !value) { toast("Target and value are required.", "err"); return; }
      try { await api("/api/annotations/mine", {method:"POST", body: JSON.stringify({target, kind, value})});
        $("anno-value").value = ""; loadMineAnnotations(); toast("Annotation added."); }
      catch (e) { toast(e.message, "err"); }
    }
    async function loadMineAnnotations() {
      const box = $("anno-mine");
      try {
        const d = await api("/api/annotations/mine");
        if (!d.annotations || !d.annotations.length) { box.innerHTML = '<div class="muted">No annotations yet.</div>'; return; }
        box.innerHTML = d.annotations.map((a, i) =>
          `<div class="draft-item"><div class="di-body"><b>${esc(a.target)}</b> · <span class="chip">${esc(a.kind)}</span> ${esc(a.value)}
            ${a.note ? '<div class="hint">'+esc(a.note)+'</div>' : ''}</div>
            <button class="ghost tiny" onclick="removeAnnotation(${i})">Remove</button></div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load.</div>'; }
    }
    async function removeAnnotation(i) {
      try { await api("/api/annotations/mine/" + i, {method:"DELETE"}); loadMineAnnotations(); } catch (e) { toast(e.message, "err"); }
    }
    function exportAnnotations() { window.open("/api/annotations/export", "_blank"); }
    async function importAnnotations(input) {
      const file = input.files && input.files[0]; if (!file) return;
      try {
        const bundle = JSON.parse(await file.text());
        const r = await api("/api/annotations/import", {method:"POST", body: JSON.stringify({bundle})});
        toast(`Imported ${r.annotations} annotation(s) from ${r.author_name}.`);
        loadAuthors();
      } catch (e) { toast(_failMsg("Import failed: {error}", e), "err"); }
      finally { input.value = ""; }
    }
    async function loadAuthors() {
      const box = $("anno-authors");
      try {
        const d = await api("/api/annotations/authors");
        if (!d.authors || !d.authors.length) { box.innerHTML = '<div class="muted">No imported authors yet.</div>'; return; }
        box.innerHTML = d.authors.map(a =>
          `<div class="draft-item"><div class="di-body"><b>${esc(a.author_name||a.author_id.slice(0,12))}</b>
            <span class="hint">· ${a.annotations} annotation(s) · ${esc(a.author_id.slice(0,16))}…</span></div>
            <label class="switch" style="margin-top:0"><input type="checkbox" ${a.trusted?"checked":""}
              onchange="trustAuthor('${a.author_id}', this.checked)"> trust</label>
            <button class="ghost tiny" onclick="removeAuthor('${a.author_id}')">Remove</button></div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">Could not load.</div>'; }
    }
    async function trustAuthor(id, trusted) {
      try { await api("/api/annotations/authors/trust", {method:"PUT", body: JSON.stringify({author_id:id, trusted})}); }
      catch (e) { toast(e.message, "err"); }
    }
    async function removeAuthor(id) {
      try { await api("/api/annotations/authors/" + encodeURIComponent(id), {method:"DELETE"}); loadAuthors(); }
      catch (e) { toast(e.message, "err"); }
    }
    async function lookupAnnotations() {
      const target = $("anno-lookup").value.trim(); if (!target) return;
      const box = $("anno-aggregate");
      try {
        const d = await api("/api/annotations/for?target=" + encodeURIComponent(target));
        if (!d.total_assertions) { box.innerHTML = '<div class="muted">No annotations for that source (from you or trusted authors).</div>'; return; }
        box.innerHTML = `<p class="hint">${esc(d.caveat)}</p>` +
          (d.dissent_kinds.length ? `<p class="hint"><b>Dissent on:</b> ${d.dissent_kinds.map(esc).join(", ")}</p>` : "") +
          d.claims.map(c => `<div class="draft-item"><div class="di-body"><span class="chip">${esc(c.kind)}</span> <b>${esc(c.value)}</b>
            <div class="hint">asserted by: ${c.asserted_by.map(a=>esc(a.author)).join(", ")}</div></div></div>`).join("");
      } catch (e) { box.innerHTML = '<div class="muted">' + esc(e.message) + '</div>'; }
    }

    // ===================================================================== //
    //  WORLD LAW — change tracking (§5)                                       //
    // ===================================================================== //
    // -- Agenda (world events): subscribe to calendars, filter & group ------ //
