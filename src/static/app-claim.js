/* app-claim.js — the Claim Workspace, slice 1 (gate row K of RELEASE_0.5_GATE.md, brief S05-11 S1)

   The reader pastes a CLAIM and the app walks it through the local corpus in visible
   steps (the design of record: FUTURE_DEVELOPMENTS.md A1, the action plan's A-2):
     ① related articles, ② grouped by independence, ③ who said what, when,
     ④ consented corroboration (slice 2, shown as not built), ⑤ what's missing,
     ⑥ the signed export (slice 2, shown as not built).

   A TRAIL, NEVER A VERDICT. Every step prints its method sentence on the page, not in a
   hover: the method IS the lesson. A path with nothing joining it is "no shared origin
   found", which is absence of evidence and is said so; nothing is scored, and no model
   writes any of it.

   ONE ENTRY POINT, OPENED BY AN EXPLICIT COMMAND (Q608 = a: Enter in the omnibar opens the
   analysis window, so the workspace is the omnibar's second row, never its first), plus the
   Search tab's "Check as a claim" button and the palette's page list. The tab is kept off
   the sidebar, like the analysis window.

   The renderers are pure (payload, t, tf) -> HTML so tests/claim_workspace_node_test.js
   drives them in node; only claimRun/_claimWire touch the DOM or the (loopback) network.
*/
    let _claimLast = null;      // the last payload, so a language switch redraws without a fetch
    let _claimWired = false;
    let _claimSeq = 0;

    const _CLAIM_JOIN_LABELS = {
      same_source: (t) => t("Same source"),
      near_identical: (t) => t("Near-identical text"),
      shared_link: (t) => t("Cite the same page"),
      same_wire: (t) => t("Attribute the same news wire"),
    };

    function _claimT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _claimTf() {
      if (window.OOI18N && OOI18N.tf) return OOI18N.tf;
      return (s, vars) => String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));
    }

    // The article's reference in this trail: its position in step ①'s list. The same
    // number is used in every step, so "#3" in a path is "#3" in the timeline.
    function claimRef(pos) { return "#" + pos; }

    function _claimStep(num, title, method, body, extraCls) {
      return `<section class="claim-step${extraCls ? " " + extraCls : ""}">`
        + `<h3><span class="claim-num" aria-hidden="true">${num}</span> ${esc(title)}</h3>`
        + (method ? `<p class="claim-method">${esc(method)}</p>` : "")
        + body + `</section>`;
    }

    function _claimFacts(facts) {
      return `<div class="living-facts">` + facts.map((f) =>
        `<div class="living-fact"><div class="muted">${esc(f[0])}</div>`
        + `<div class="living-fact-v">${esc(String(f[1]))}</div></div>`).join("") + `</div>`;
    }

    function _claimArticleLink(a, t) {
      const title = a.title || t("(untitled)");
      return `<a href="/api/articles/${encodeURIComponent(a.id)}/view" target="_blank" rel="noopener">${esc(title)}</a>`;
    }

    function claimRelatedHtml(ws, t, tf) {
      const r = ws.related || {};
      const q = ws.query || {};
      let body = "";
      if (!q.text) {
        body += `<p class="hint">${esc(t("The claim has no words the index can search for. Type the words to search for in the box above."))}</p>`;
        return _claimStep("①", t("Related articles in your corpus"), null, body);
      }
      body += `<p class="claim-query"><span class="muted">${esc(q.derived ? t("Words searched, taken from the claim:") : t("Words searched, as you typed them:"))}</span> <code>${esc(q.text)}</code></p>`;
      if (ws.cross_language && typeof _omniCrossNote === "function") {
        const note = _omniCrossNote(ws.cross_language);
        if (note) body += `<p class="hint">${esc(note.replace(/^ · /, ""))}</p>`;
      }
      body += _claimFacts([
        [t("Articles matched"), r.at_index_cap ? tf("at least {n}", {n: r.total}) : r.total],
        [t("Read for this trail"), r.shown],
      ]);
      if (r.total > r.shown) {
        body += `<p class="hint">${esc(tf("The trail reads the {shown} best matches, in the index's relevance order. The other matches are not read; the Search tab lists them all.", {shown: r.shown}))}</p>`;
      }
      if (!(r.articles || []).length) {
        return _claimStep("①", t("Related articles in your corpus"),
          t("Full-text search over your corpus, with the Search tab's grammar and its cross-language expansion. With no words of your own, the claim's content words are joined with OR, so an article carrying more of them ranks higher. The list is a relevance ranking, not a sample."),
          body);
      }
      body += `<ol class="claim-list">` + r.articles.map((a) =>
        `<li value="${esc(a.position)}">${_claimArticleLink(a, t)}`
        + ` <span class="muted">${esc(a.source || "")}${a.published_at ? " · " + esc(String(a.published_at).slice(0, 10)) : ""}</span>`
        + (a.language ? " " + ooLangCell(a.language, {cls: "claim-pill"}) : "")
        + `</li>`).join("") + `</ol>`;
      return _claimStep("①", t("Related articles in your corpus"),
        t("Full-text search over your corpus, with the Search tab's grammar and its cross-language expansion. With no words of your own, the claim's content words are joined with OR, so an article carrying more of them ranks higher. The list is a relevance ranking, not a sample."),
        body);
    }

    function claimIndependenceHtml(ws, t, tf) {
      const ind = ws.independence || {};
      const posOf = {};
      ((ws.related || {}).articles || []).forEach((a) => { posOf[a.id] = a.position; });
      // In step ①'s order, so "#2 #3 #4" reads as the list it points back at.
      const refs = (ids) => ids.map((id) => posOf[id]).sort((a, b) => (a == null) - (b == null) || a - b)
        .map((pos) => claimRef(pos != null ? pos : "?")).join(" ");
      const method = t("Articles are joined into one path when they come from the same source, share near-identical text, cite the same outbound page, or attribute the same news wire. Echoes of one origin are one path, however many outlets carry them.");
      if (!ind.n_articles) {
        return _claimStep("②", t("Grouped by independence"), method,
          `<p class="hint">${esc(t("No related article, so there is nothing to group."))}</p>`);
      }
      let body = _claimFacts([
        [t("Paths"), ind.n_paths],
        [t("Paths joining several articles"), ind.n_joined_paths],
        [t("Articles with no shared origin found"), ind.n_unjoined],
        [t("Sources"), ind.n_sources],
      ]);
      body += `<p class="card-caveat">${esc(t("No shared origin found is absence of evidence, never proof of independence: two articles can share an origin that neither states. The wire attribution is read from the text and can be wrong."))}</p>`;
      const joined = (ind.paths || []).filter((p) => !p.unjoined);
      joined.forEach((p) => {
        body += `<div class="claim-path"><div class="claim-path-head"><b>${esc(tf("Path {n}", {n: p.path}))}</b>`
          + ` <span class="muted">${esc(ooLabelText(t("Articles"), String(p.n_articles)))} · ${esc(ooLabelText(t("Sources"), String(p.n_sources)))}</span>`
          + ` <span class="claim-refs">${esc(refs(p.article_ids))}</span></div>`
          + `<ul class="claim-joins">` + (p.joins || []).map((j) =>
            `<li><span class="claim-join-kind">${esc(_CLAIM_JOIN_LABELS[j.kind] ? _CLAIM_JOIN_LABELS[j.kind](t) : j.kind)}</span>`
            + (j.detail ? ` <span class="claim-join-detail">${esc(j.detail)}</span>` : "")
            + ` <span class="claim-refs">${esc(refs(j.article_ids))}</span></li>`).join("")
          + `</ul></div>`;
      });
      const lone = (ind.paths || []).filter((p) => p.unjoined);
      if (lone.length) {
        body += `<div class="claim-path"><div class="claim-path-head"><b>${esc(t("No shared origin found"))}</b>`
          + ` <span class="claim-refs">${esc(refs(lone.map((p) => p.article_ids[0])))}</span></div>`
          + `<p class="hint">${esc(t("Each of these is a path of its own because nothing we can measure joins it to another one."))}</p></div>`;
      }
      return _claimStep("②", t("Grouped by independence"), method, body);
    }

    function claimTimelineHtml(ws, t, tf) {
      const rows = ws.timeline || [];
      const method = t("The trail in publication order, with the sentence of each article that carries the most of the claim's words. The earliest article is the first one your corpus holds, not necessarily where the claim began.");
      if (!rows.length) {
        return _claimStep("③", t("Who said what, when"), method,
          `<p class="hint">${esc(t("No related article, so there is no timeline."))}</p>`);
      }
      const posOf = {};
      ((ws.related || {}).articles || []).forEach((a) => { posOf[a.id] = a.position; });
      let body = `<div class="claim-table-wrap"><table class="claim-timeline"><thead><tr>`
        + `<th>${esc(t("Date"))}</th><th>${esc(t("Source"))}</th><th>${esc(t("Path"))}</th><th>${esc(t("What it said"))}</th></tr></thead><tbody>`;
      rows.forEach((r) => {
        const badges = [];
        if (r.first_in_corpus) badges.push(`<span class="claim-badge">${esc(t("first in your corpus"))}</span>`);
        if (r.wire) badges.push(`<span class="claim-badge">${esc(tf("attributes {wire}", {wire: r.wire}))}</span>`);
        const said = r.said
          ? `<q class="claim-said">${esc(r.said)}</q>`
          : `<span class="muted">${esc(t("No sentence carries the claim's words; the title is shown."))}</span>`;
        body += `<tr><td class="claim-date">${r.published_at ? esc(String(r.published_at).slice(0, 10)) : esc(t("undated"))}</td>`
          + `<td>${esc(r.source || "?")}${r.country ? " " + ooCountryCell(r.country, {cls: "claim-pill"}) : ""}</td>`
          + `<td>${r.path != null ? esc(String(r.path)) : ""}</td>`
          + `<td><div>${esc(claimRef(posOf[r.id] != null ? posOf[r.id] : "?"))} ${_claimArticleLink(r, t)} ${badges.join(" ")}</div>${said}</td></tr>`;
      });
      body += `</tbody></table></div>`;
      return _claimStep("③", t("Who said what, when"), method, body);
    }

    function _claimSilentHtml(label, block, cell, t) {
      if (!block) return "";
      const items = block.items || [];
      if (!block.total) {
        return `<p><b>${esc(label)}</b> <span class="muted">${esc(t("none silent: every one your corpus holds speaks in this trail"))}</span></p>`;
      }
      return `<p><b>${esc(ooLabelText(label, String(block.total)))}</b> `
        + items.map((it) => `<span class="claim-silent">${cell(it.key)} <span class="muted">(${esc(String(it.corpus_sources))})</span></span>`).join(" ")
        + (block.total > items.length ? ` <span class="muted">…</span>` : "") + `</p>`;
    }

    const _CLAIM_DISCRIMINATORS = {
      no_related: (tf, v) => tf("No article in your corpus matches these words. Try other words for the claim, or collect sources that cover its subject, its region and its language.", v),
      one_path: (tf, v) => tf("Every article here joins into one path. A report that does not share its origin would be a second path.", v),
      no_primary_record: (tf, v) => tf("The trail holds no primary record, such as official statistics or a law text. The record a figure or a rule comes from would tell the claim apart better than more reporting.", v),
      one_language: (tf, v) => tf("The trail is in one language. Reporting in another language would show whether the claim travels beyond one press.", v),
      short_window: (tf, v) => tf("The trail's dated articles all fall within two days. Later reporting would show whether the claim held up or was corrected.", v),
      undated: (tf, v) => tf("Articles without a publication date: {n}. They sit at the end of the timeline.", v),
      figure_source: (tf, v) => tf("The claim states figures ({figures}). The dataset or document they come from would tell the claim apart better than reports repeating them.", v),
    };

    function claimMissingHtml(ws, t, tf) {
      const m = ws.missing || {};
      const method = t("What your corpus holds that this trail is silent on, counted over the sources your corpus has articles from, and the kinds of evidence that would tell the claim apart. Silence here is silence in your corpus, not in the world.");
      let body = `<h4>${esc(t("Silent in this trail"))}</h4>`;
      body += `<p class="hint">${esc(t("In brackets: how many of your corpus's sources that one covers."))}</p>`;
      body += _claimSilentHtml(t("Countries"), m.countries, (k) => ooCountryCell(k), t);
      body += _claimSilentHtml(t("Languages"), m.languages, (k) => ooLangCell(k), t);
      body += _claimSilentHtml(t("Source types"), m.source_types, (k) => esc(t(k)), t);
      const disc = m.would_discriminate || [];
      body += `<h4>${esc(t("What would tell the claim apart"))}</h4>`;
      if (!disc.length) {
        body += `<p class="hint">${esc(t("Nothing this workspace measures points at a gap. That is not a confirmation: it measures a few things only."))}</p>`;
      } else {
        body += `<ul class="claim-disc">` + disc.map((d) => {
          const frame = _CLAIM_DISCRIMINATORS[d.code];
          if (!frame) return "";
          const f = d.fact || {};
          const vars = {days: f.days, n: f.n, figures: ooListJoin(f.figures || [])};
          return `<li>${esc(frame(tf, vars))}</li>`;
        }).join("") + `</ul>`;
      }
      return _claimStep("⑤", t("What's missing"), method, body);
    }

    function claimNotBuiltHtml(num, title, what, t) {
      return _claimStep(num, title, null,
        `<p class="hint">${esc(t("Not built yet."))} ${esc(what)}</p>`, "claim-later");
    }

    // The whole trail, in step order. ④ and ⑥ are shown where they belong and say they
    // are not built, so the pipeline reads as the design draws it and nothing is implied.
    function claimWorkspaceHtml(ws, t, tf) {
      return claimRelatedHtml(ws, t, tf)
        + claimIndependenceHtml(ws, t, tf)
        + claimTimelineHtml(ws, t, tf)
        + claimNotBuiltHtml("④", t("Corroboration offers"),
          t("Each offer will ask your consent before anything leaves your machine, and name the host it would ask."), t)
        + claimMissingHtml(ws, t, tf)
        + claimNotBuiltHtml("⑥", t("Export the trail, signed"),
          t("The trail will be exportable as a signed evidence bundle."), t);
    }

    function repaintClaimFromCache() {
      const box = $("claim-body");
      if (!box || !_claimLast) return;
      box.innerHTML = claimWorkspaceHtml(_claimLast, _claimT(), _claimTf());
    }

    async function claimRun() {
      const t = _claimT();
      const claim = ($("claim-text").value || "").trim();
      const query = ($("claim-query").value || "").trim();
      const status = $("claim-status");
      if (!claim) { status.textContent = t("Type or paste a claim first."); return; }
      const seq = ++_claimSeq;
      status.textContent = t("Walking the trail through your corpus…");
      const p = new URLSearchParams({claim});
      if (query) p.set("query", query);
      try { p.set("ui_lang", OOI18N.current()); } catch (_e) { /* no engine: no narrowing */ }
      try {
        const ws = await api("/api/claims/workspace?" + p.toString());
        if (seq !== _claimSeq) return;   // a newer run superseded this one
        _claimLast = ws;
        status.textContent = "";
        repaintClaimFromCache();
      } catch (e) {
        if (seq !== _claimSeq) return;
        status.textContent = t("The trail could not be walked:") + " " + ((e && e.message) || String(e));
      }
    }

    function _claimWire() {
      if (_claimWired) return;
      _claimWired = true;
      const run = $("claim-run");
      if (run) run.addEventListener("click", () => claimRun());
      const txt = $("claim-text");
      // Ctrl/⌘-Enter walks the trail from the text box; a bare Enter is a new line.
      if (txt) txt.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); claimRun(); }
      });
      const q = $("claim-query");
      if (q) q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); claimRun(); } });
    }

    // Open the workspace on a claim (the omnibar row, the Search tab's button). An empty
    // text only opens it; a claim walks the trail straight away. The words box is cleared,
    // so a new claim never runs with the previous claim's words.
    function openClaimWorkspace(text) {
      showTab("claim");
      _claimWire();
      const claim = String(text || "").trim();
      if (!claim) { setTimeout(() => { const el = $("claim-text"); if (el) el.focus(); }, 30); return; }
      $("claim-text").value = claim;
      $("claim-query").value = "";
      claimRun();
    }

    // The Search tab's button: the search box's text as the claim.
    (function _claimSearchButton() {
      const wire = () => {
        const b = $("claim-from-search");
        if (b) b.addEventListener("click", () => openClaimWorkspace(($("q") && $("q").value) || ""));
      };
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
      else wire();
    })();
