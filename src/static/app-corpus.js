/* app-corpus.js — corpus window, mindmap, trends

   The corpus window and its subtabs, the mindmap and graph renderers, keyword
   rendering with the level grammar, the trend views (slope, small multiples) and
   the shared chart-enlarge dialog.

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
    let _corpusTerm = null, _corpusTab = "trend";
    // openCorpus is RETIRED here (THEME-3, 2026-06-19): the legacy #corpus-win keyword
    // modal is gone — a keyword now spawns its own analysis TAB (one analysis surface).
    // The replacement `function openCorpus(term){ openAnalysisFor(term); }` is defined
    // with the tab machinery below; all call sites route through it unchanged.
    // Return the relocatable mind-map kit (#mm-kit) to its Insights home anchor.
    // Called BEFORE any corpus tab overwrites #corpus-body, so the shared
    // component (its DOM + live SVG/pan-zoom handlers) is never destroyed.
    function _mmKitHome() {
      const kit = $("mm-kit"), home = $("mm-kit-home");
      if (kit && home && kit.parentNode !== home.parentNode) {
        home.parentNode.insertBefore(kit, home.nextSibling);
      }
    }
    async function corpusTab(which) {
      _corpusTab = which;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      // Button/ARIA state is owned by the ooSubtabs component.
      _mmKitHome();   // restore the shared mind-map kit before clearing the body
      const el = $("corpus-body"); el.innerHTML = `<div class="muted">…</div>`;
      try {
        if (which === "trend") {
          const tr = await api(`/api/insights/trend?term=${encodeURIComponent(_corpusTerm)}`);
          if (!tr.resolved) { el.innerHTML = `<div class="muted">${esc(t("No indexed mentions yet."))}</div>`; return; }
          $("corpus-n").textContent = `${tr.total} ${t("mentions in")} ${tr.articles} ${t("articles")}`;
          // The trend endpoint returns the FULL bucketed series (no date params),
          // so the ooTimeScope window is applied CLIENT-SIDE by FILTERING the
          // already-fetched points — never refetched, never thinned (invariant #16).
          el.innerHTML = `<div style="margin-bottom:8px"><div class="hint">${esc(t("Time range"))}</div>
            <div id="corpus-timescope"></div></div><div id="corpus-chart"></div>`;
          const allPts = tr.points || [];
          const label = tr.resolved.term;
          // DELIBERATELY NOT brushable, though it is a single-keyword article-time chart
          // and would qualify: corpusTab has NO callers -- it is the retired #corpus-win
          // modal (THEME-3, 2026-06-19). Wiring a selection here would add a capability
          // no reader can reach, and a guard asserting it would pass while proving
          // nothing. Wire it if this surface is ever revived.
          const draw = (pts) => ooChart($("corpus-chart"), [{label, unit: "mentions",
            points: pts.map(pt => ({t: pt.date, v: pt.count}))}], {height: 200, zeroBase: true});
          const def = _buildTrendScope($("corpus-timescope"), allPts, draw);
          draw(_windowTrendPoints(allPts, def.from, def.to));
        } else if (which === "articles") {
          const ctx = await api(`/api/insights/context?term=${encodeURIComponent(_corpusTerm)}&limit=25`);
          const ms = ctx.mentions || [];
          el.innerHTML = ms.length ? ms.map(m =>
            `<div class="note" style="max-width:none;margin-bottom:6px">
               <div class="muted" style="font-size:12px">${esc(m.source || "")}${m.observed_on ? " · " + esc(m.observed_on) : ""}
                 ${m.article_id ? `· <a href="/api/articles/${m.article_id}/view" target="_blank" rel="noopener">${esc(t("open"))}</a>` : ""}</div>
               <div style="font-size:13px">${esc(m.snippet || m.title || "")}</div></div>`).join("")
            : `<div class="muted">${esc(t("No indexed mentions yet."))}</div>`;
        } else if (which === "mindmap") {
          // Reuse the EXACT Insights associations mind-map (renderMindmap →
          // renderGraph): same radial renderer, same in-map controls
          // (levels / cloud / period / text-size / enlarge). We RELOCATE the
          // shared #mm-kit into this pane (no fork, no duplicate IDs), then
          // point it at THIS window's corpus term. The mind-map's own Period
          // control honours the date window (the corpus Trend's ooTimeScope is
          // a client-side filter on a different series, so we don't pretend to
          // couple them — the mind-map carries its own honest window control).
          el.innerHTML = `<div id="corpus-mm-host"></div>`;
          const kit = $("mm-kit");
          if (kit) $("corpus-mm-host").appendChild(kit);
          await renderMindmap(_corpusTerm);
        } else if (which === "links") {
          const d = await api(`/api/links/shared?term=${encodeURIComponent(_corpusTerm)}`);
          const rows = d.shared || [];
          el.innerHTML =
            `<div class="hint">${esc(t("Shared outbound links among the member articles — a shared origin means agreement is ONE path, not independent confirmation."))}</div>` +
            (rows.length ? rows.map(r =>
              `<div class="note" style="max-width:none;margin-bottom:6px">
                 <div style="font-size:12.5px;word-break:break-all"><b>${r.cited_by_articles}×</b> ${esc(r.url)}</div>
                 <div class="muted" style="font-size:12px">${esc(t("citing sources:"))} ${r.citing_sources} — ${esc(r.note)}</div>
               </div>`).join("")
             : `<div class="muted">${esc(t("No outbound link is shared by more than one member article."))}</div>`);
        } else if (which === "sentiment") {
          // Reuse the EXACT Insights framing renderer (loadFraming → /api/framing)
          // by CALLING it into a fresh host — no DOM relocation, Insights untouched.
          // The endpoint is keyed on the FTS query, so we point it at _corpusTerm.
          // Its d.caveat carries the English-only VADER disclosure (audit B1),
          // rendered VISIBLY by loadFraming (the same keyed disclosure the
          // Insights framing surface shows). /api/framing takes no date params,
          // so this is honest full-corpus — we do NOT fake a time-scope window.
          el.innerHTML = `<h2 style="margin:2px 0 6px;font-size:13px">${esc(t("How outlets frame this"))} <span class="muted">${esc(t("(VADER tone)"))}</span></h2>
            <div id="corpus-sentiment-host"></div>`;
          await loadFraming(_corpusTerm, "corpus-sentiment-host");
        } else if (which === "keywords") {
          // Reuse the EXACT Insights associations data (/api/insights/associations,
          // the SAME endpoint q.associations that powers the mind-map graph) by
          // rendering it as a ranked TABLE into a fresh host — the Sentiment
          // pattern (function-call into a host, no DOM relocation). The Mindmap
          // sub-tab shows the SAME relatives as a radial GRAPH (how they relate,
          // visually); this answers "which terms define this corpus, with numbers".
          // /api/insights/associations exposes no date params, so this is honest
          // full-corpus — we do NOT fake a time-scope window (cf. Sentiment).
          el.innerHTML = `<div id="corpus-keywords-host"><div class="muted">${esc(t("…"))}</div></div>`;
          await renderCorpusKeywords(_corpusTerm, "corpus-keywords-host");
        } else if (which === "sources") {
          // SOURCE-DESCRIPTION sub-tab: WHICH sources feed this corpus, with the
          // catalog metadata they assert — descriptive provenance, NOT the
          // competitive/angle analysis (a later, corpus-only tab) and NOT tone
          // (Sentiment owns that). Reuses /api/insights/corpus-sources for the
          // corpus's DISTINCT sources + their REAL per-corpus article count, then
          // enriches client-side from the bulk /api/sources catalog (no new
          // backend, no fork). The function-call-into-a-fresh-host pattern
          // (Sentiment/Keywords), never DOM relocation. No time-scope here:
          // /api/insights/corpus-sources does honest full-corpus over the matched
          // articles (it exposes date params but we don't fake a window control).
          el.innerHTML = `<div id="corpus-sources-host"><div class="muted">${esc(t("…"))}</div></div>`;
          await renderCorpusSources(_corpusTerm, "corpus-sources-host");
        } else if (which === "competitive") {
          // SOURCE-COMPETITIVE sub-tab (corpus-only, the flagship's LAST design
          // facet): how each source APPROACHES this concept, side by side —
          // VOLUME (exact article count), TONE (VADER mean + label), TIMING
          // (first→last span), EMPHASIS (each outlet's distinctive terms). It is
          // a DESCRIPTIVE comparison of DIVERGENCE, never a ranking, a winner or
          // a credibility verdict — no composite score. Built by JOINING two
          // EXISTING endpoints per source (no new backend, no fork): volume +
          // timing + mean tone from /api/insights/corpus-sources, tone label +
          // emphasised terms from /api/framing. n=1 ⇒ "nothing to compare". The
          // function-call-into-a-fresh-host pattern (Sentiment/Sources). No
          // time-scope: neither endpoint takes date params — honest full-corpus.
          el.innerHTML = `<div id="corpus-competitive-host"><div class="muted">${esc(t("…"))}</div></div>`;
          await renderCorpusCompetitive(_corpusTerm, "corpus-competitive-host");
        }
      } catch (e) { el.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }

    // Source-description sub-tab: the distinct sources behind this corpus, each
    // with its REAL per-corpus article count (from /api/insights/corpus-sources,
    // the same data the source-coverage view uses) PLUS the catalog metadata the
    // source ASSERTS — domain, country, region, language, tags (from the bulk
    // /api/sources list, merged by domain). Two-class honesty: every metadata
    // field here is catalog/source-ASSERTED (set from the catalog, ccTLD or the
    // operator), NEVER text-deduced — stated as such; we never fabricate a
    // "description" the model does not store (Source has no free-text bio), so a
    // source with no catalog facts on file reads "no catalog metadata on file".
    // No score, no ranking — descriptive provenance, not credibility.
    async function renderCorpusSources(term, hostId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = document.getElementById(hostId);
      if (!host) return;
      let cs, cat;
      try {
        // corpus-sources keys on the FTS query (like Sentiment's framing call),
        // so we point it at this window's term to get THIS corpus's sources.
        [cs, cat] = await Promise.all([
          api(`/api/insights/corpus-sources?query=${encodeURIComponent(term)}&limit=200`),
          api(`/api/sources/?limit=1000`).catch(() => []),
        ]);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const rows = (cs && cs.sources) || [];
      if (!rows.length) {
        host.innerHTML = `<div class="muted">${esc(t("No sources for this corpus yet."))}</div>`;
        return;
      }
      // Index the catalog metadata by domain (+ name fallback) for client-side merge.
      const byDom = {}, byName = {};
      (Array.isArray(cat) ? cat : []).forEach(s => {
        if (s.domain) byDom[s.domain.toLowerCase()] = s;
        if (s.name) byName[s.name] = s;
      });
      const fmt = (n) => (n || 0).toLocaleString();
      const chips = (arr) => (arr || []).filter(Boolean)
        .map(x => `<span class="pill" style="font-size:11px">${esc(x)}</span>`).join(" ");
      const cards = rows.map(r => {
        const meta = byDom[(r.domain || "").toLowerCase()] || byName[r.name] || {};
        const facts = [];
        if (meta.country) facts.push(`${esc(t("Country"))}: ${esc(ooRegionName(meta.country, meta.country.toUpperCase()))}`);
        if (meta.region) facts.push(`${esc(t("Region"))}: ${esc(meta.region)}`);
        if (meta.language) facts.push(`${esc(t("Language"))}: ${esc(ooLangName(meta.language, meta.language))}`);
        if (meta.source_type) facts.push(`${esc(t("Type"))}: ${esc(meta.source_type)}`);
        const tags = (meta.tags && meta.tags.length) ? chips(meta.tags) : "";
        const hasMeta = facts.length || tags;
        // Source name → the EXISTING integrity source-profile view (reuse), keyed
        // by the source name/domain it already accepts. No invented destination.
        const nameLink = `<a href="#" class="csrc-prof" data-src="${esc(r.domain || r.name)}"
            title="${esc(t("Open this source's profile (measured dimensions, no composite score)."))}">${esc(r.name || r.domain || "—")}</a>`;
        return `<div class="note" style="max-width:none;margin-bottom:8px">
          <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
            <b style="font-size:13px">${nameLink}</b>
            <span class="muted" style="font-size:12px">${esc(r.domain || "")}</span>
            <span style="margin-inline-start:auto;font-size:12px">${fmt(r.articles)} ${esc(t("articles"))}</span>
          </div>
          ${facts.length ? `<div class="muted" style="font-size:12px;margin-top:3px">${facts.join(" · ")}</div>` : ""}
          ${tags ? `<div style="margin-top:4px">${tags}</div>` : ""}
          ${hasMeta ? "" : `<div class="muted" style="font-size:12px;margin-top:3px">${esc(t("No catalog metadata on file."))}</div>`}
        </div>`;
      }).join("");
      host.innerHTML =
        `<div class="hint">${esc(t("The distinct sources behind this corpus, with their per-corpus article count. Country, region, language and tags are stated by the source catalog (asserted, not deduced from text); article counts are exact. No score, no ranking — coverage, not credibility."))}</div>` +
        cards +
        `<div class="hint" style="margin-top:6px">${esc(t("n ="))} ${fmt(cs.n_articles)} ${esc(t("articles"))}${cs.capped ? ` · ${esc(t("(scoped to the top matched articles)"))}` : ""}. ${esc(cs.caveat || "")}</div>`;
      // Source name → the existing source-profile view (reuse loadProfile).
      host.querySelectorAll(".csrc-prof").forEach(a =>
        a.addEventListener("click", (e) => {
          e.preventDefault();
          const inp = $("prof-source");
          if (inp) { inp.value = a.dataset.src; showTab("integrity"); loadProfile(); }
        }));
    }

    // Source-competitive sub-tab (corpus-only, the flagship's LAST design facet):
    // how each source APPROACHES this concept, side by side. It JOINS two EXISTING
    // endpoints per source (no new backend, no fork):
    //   • VOLUME + TIMING + mean tone  ← /api/insights/corpus-sources
    //     (sources[]: name, domain, articles, mean_tone, first, last)
    //   • TONE label + EMPHASISED terms ← /api/framing
    //     (framing[]: source, tone_label, avg_tone, article_count, top_terms[])
    // Every column is a REAL value — exact article counts, real publication dates,
    // the source's own VADER mean/label, that outlet's distinctive terms. There is
    // NO composite score, NO "leader", NO ranking-as-quality: rows are ordered by
    // VOLUME only (the most-covering source first — an ordering, not a verdict).
    // It is a DESCRIPTIVE comparison of DIVERGENCE. n=1 ⇒ "nothing to compare"
    // (the ledger's "n=1 has no competition"). Tone carries the VADER English-only
    // disclosure (audit B1), reused from the framing/Sentiment surface, VISIBLE.
    // Neither endpoint takes date params, so this is honest full-corpus — we do
    // NOT fake a time-scope window (cf. Sentiment/Keywords/Sources).
    async function renderCorpusCompetitive(term, hostId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = document.getElementById(hostId);
      if (!host) return;
      let cs, fr;
      try {
        // Both endpoints key on the FTS query (like Sentiment/Sources), so we point
        // them at THIS window's term. Framing needs the [analysis] extra; if it is
        // absent we still show volume/timing and say tone/emphasis is unavailable.
        [cs, fr] = await Promise.all([
          api(`/api/insights/corpus-sources?query=${encodeURIComponent(term)}&limit=200`),
          api(`/api/framing?query=${encodeURIComponent(term)}`).catch(() => null),
        ]);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const rows = (cs && cs.sources) || [];
      if (!rows.length) {
        host.innerHTML = `<div class="muted">${esc(t("No sources for this corpus yet."))}</div>`;
        return;
      }
      if (rows.length === 1) {
        // The ledger's "n=1 has no competition" — honest single-source state.
        host.innerHTML =
          `<div class="muted">${esc(t("Only one source in this corpus — nothing to compare."))}</div>`;
        return;
      }
      // Index framing per source (by name; tone label + emphasised terms live there).
      const byName = {};
      ((fr && fr.framing) || []).forEach(f => { if (f.source) byName[f.source] = f; });
      const fmt = (n) => (n || 0).toLocaleString();
      // Relative timing readout vs the WHOLE corpus span (real dates, never a score):
      // the corpus's earliest/latest publication across these sources.
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
      // The "not a ranking / not credibility" disclosure — VISIBLE, with the long
      // form in the #oo-tip hover (informed-consent layering). Plus the VADER
      // English-only disclosure carried by the framing/corpus-sources caveat.
      const notRanking = t("Descriptive comparison — how these sources DIFFER, never a ranking or a credibility judgement. Rows are ordered by volume only (most-covering first); there is no winner and no composite score.");
      const body = rows.map(r => {
        const f = byName[r.name] || {};
        const emphasis = (f.top_terms && f.top_terms.length) ? chips(f.top_terms)
          : `<span class="muted" style="font-size:12px">${fr ? esc(t("No distinctive terms.")) : esc(t("Needs the [analysis] extra."))}</span>`;
        // Tone: prefer the framing label+avg; fall back to the corpus-sources mean
        // (same VADER number) ONLY when framing has no row for this outlet at all.
        // AMENDED 2026-07-29: framing can now honestly report avg_tone:null ("none of
        // this outlet's sampled pieces were in a language the lexicon reads"). Falling
        // through to r.mean_tone there would print a number computed over a DIFFERENT,
        // uncapped article set, with no label — the denominator mismatch the same
        // change added tone_articles/tone_unmeasured to prevent. An outlet framing
        // declared unmeasurable renders the honest em-dash.
        const hasFraming = Object.prototype.hasOwnProperty.call(byName, r.name);
        const toneVal = (f.avg_tone != null) ? f.avg_tone : (hasFraming ? null : r.mean_tone);
        const toneLbl = f.tone_label || null;
        const span = (r.first && r.last)
          ? `${esc(day(r.first))} → ${esc(day(r.last))}`
          : `<span class="muted">—</span>`;
        return `<tr style="border-bottom:1px solid var(--line)">
          <td style="padding:5px 8px"><b style="font-size:13px">${esc(r.name || r.domain || "—")}</b>
            ${r.domain ? `<div class="muted" style="font-size:11px">${esc(r.domain)}</div>` : ""}</td>
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
             <th style="text-align:right;padding:5px 8px"
                 title="${esc(t("How many articles in this corpus come from this source — an exact count, never a score."))}">${esc(t("Volume"))}</th>
             <th style="text-align:start;padding:5px 8px"
                 title="${esc(t("Mean VADER tone for this source's coverage, with the label. VADER is an ENGLISH-lexicon method — tone for non-English coverage is unreliable or absent. A real value, never a verdict."))}">${esc(t("Tone"))} <span class="muted" style="font-weight:normal">${esc(t("(VADER tone)"))}</span></th>
             <th style="text-align:start;padding:5px 8px"
                 title="${esc(t("The first → last publication date for this source's coverage in the corpus — real dates, never a score."))}">${esc(t("Timing"))}</th>
             <th style="text-align:start;padding:5px 8px"
                 title="${esc(t("This outlet's most distinctive terms when covering the concept (from framing). Descriptive emphasis, not a judgement."))}">${esc(t("Emphasis"))}</th>
           </tr></thead>
           <tbody>${body}</tbody>
         </table>` +
        `<div class="hint" style="margin-top:6px">${esc(t("n ="))} ${fmt(cs.n_articles)} ${esc(t("articles"))}` +
          `${(corpusFirst && corpusLast) ? ` · ${esc(day(corpusFirst))} → ${esc(day(corpusLast))}` : ""}` +
          `${cs.capped ? ` · ${esc(t("(scoped to the top matched articles)"))}` : ""}. ` +
          `${esc(cs.caveat || "")} ${esc((fr && fr.caveat) || "")}</div>`;
    }

    // Keyword-analysis sub-tab: a ranked TABLE of the corpus's co-occurring
    // keywords with REAL per-keyword numbers from /api/insights/associations
    // (the same data the mind-map plots). No composite score — each column is a
    // raw value; PMI carries the endpoint's own method + caveat. A row click
    // opens that keyword as its own corpus (the existing openCorpus entry).
    let _ckwSort = "pmi";
    async function renderCorpusKeywords(term, hostId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
      const host = document.getElementById(hostId);
      if (!host) return;
      let d;
      try {
        d = await api(`/api/insights/associations?term=${encodeURIComponent(term)}&limit=100`);
      } catch (e) { host.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
      const pairs = (d.pairs || []).slice();
      if (!pairs.length) {
        host.innerHTML = `<div class="muted">${esc(t("No keywords indexed for this corpus yet."))}</div>`;
        return;
      }
      const sorters = {
        pmi: (a, b) => (b.pmi - a.pmi) || (b.cooccur - a.cooccur),
        cooccur: (a, b) => (b.cooccur - a.cooccur) || (b.pmi - a.pmi),
        n_b: (a, b) => (b.n_b - a.n_b) || (b.cooccur - a.cooccur),
      };
      pairs.sort(sorters[_ckwSort] || sorters.pmi);
      const nA = d.n_articles_with_term || 0;
      const fmt = (n) => (n || 0).toLocaleString();
      // Headers carry honest method/caveat in the #oo-tip hover (translated title).
      const th = (key, label, title) =>
        `<th data-sort="${key}" role="button" tabindex="0" style="cursor:pointer;text-align:right;padding:4px 8px;white-space:nowrap"
            title="${esc(title)}">${esc(label)}${_ckwSort === key ? " ▾" : ""}</th>`;
      host.innerHTML =
        `<div class="hint">${esc(t("Keywords that co-occur with this corpus, ranked. Real per-keyword counts — no composite score."))} ${esc(d.method || "")} ${esc(d.caveat || "")}</div>` +
        `<table style="width:100%;border-collapse:collapse;font-size:13px">
           <thead><tr style="border-bottom:1px solid var(--line)">
             <th style="text-align:start;padding:4px 8px">${esc(t("Keyword"))}</th>
             ${th("cooccur", t("In this corpus"), t("Distinct articles in this corpus that mention BOTH the corpus term and this keyword. A real count, never a score."))}
             ${th("n_b", t("Total articles"), t("Distinct articles across the whole corpus that mention this keyword. A real count, never a score."))}
             ${th("pmi", t("Association"), t("Pointwise mutual information with the corpus term — association strength, not causation. PMI on small samples is noisy; read it beside the counts."))}
           </tr></thead>
           <tbody>${pairs.map(p => {
             const members = (p.members && p.members.length > 1) ? p.members.join(", ") : "";
             const titleAttr = members ? ` title="${esc(t("Entity family:"))} ${esc(members)}"` : "";
             return `<tr class="ckw-row" data-term="${esc(p.normalized || p.term)}" style="cursor:pointer;border-bottom:1px solid var(--line)">
               <td style="padding:4px 8px"><span${titleAttr}>${esc(p.term)}</span>${p.kind ? ` <span class="muted" style="font-size:11px">${esc(p.kind)}</span>` : ""}</td>
               <td style="text-align:right;padding:4px 8px">${fmt(p.cooccur)}</td>
               <td style="text-align:right;padding:4px 8px">${fmt(p.n_b)}</td>
               <td style="text-align:right;padding:4px 8px">${(p.pmi != null ? p.pmi.toFixed(2) : "—")}</td>
             </tr>`;
           }).join("")}</tbody>
         </table>` +
        `<div class="hint" style="margin-top:6px">${esc(t("n ="))} ${fmt(nA)} ${esc(t("articles mention the corpus term."))} ${d.grouped ? esc(t("Surface variants are merged into entity families.")) : ""} ${esc(t("Click a row to open that keyword as its own corpus."))}</div>`;
      // Row click → that keyword's corpus window (reuse the existing entry).
      host.querySelectorAll(".ckw-row").forEach(tr =>
        tr.addEventListener("click", () => openCorpus(tr.dataset.term)));
      // Header click/Enter → re-sort (honest defaults first; PMI by default).
      host.querySelectorAll("th[data-sort]").forEach(h => {
        const go = () => { _ckwSort = h.dataset.sort; renderCorpusKeywords(term, hostId); };
        h.addEventListener("click", go);
        h.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      });
    }

    function pickTerm(t) { $("ins-term").value = t; (_insSubtabs || {select: showInsightCat}).select("explore"); exploreTerm(); }

    function trendSvg(points) {
      if (!points.length) return '<div class="muted">No mentions over time yet — index the corpus first.</div>';
      const w = 680, h = 140, pad = 30, ys = points.map(p => p.count), maxY = Math.max(...ys, 1);
      const X = i => pad + (w - 2*pad) * (points.length < 2 ? 0.5 : i/(points.length-1));
      const Y = v => h - pad - (h - 2*pad) * (v / maxY);
      const line = points.map((p, i) => `${X(i).toFixed(1)},${Y(p.count).toFixed(1)}`).join(" ");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" style="max-width:${w}px;background:var(--panel2);border:1px solid var(--border);border-radius:8px">
        <polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${line}"></polyline>
        <text x="${pad}" y="14" fill="var(--muted)" font-size="11">${maxY}</text>
        <text x="${pad}" y="${h-8}" fill="var(--muted)" font-size="11">${esc(points[0].date)}</text>
        <text x="${w-pad}" y="${h-8}" fill="var(--muted)" font-size="11" text-anchor="end">${esc(points[points.length-1].date)}</text>
      </svg>`;
    }

    // Interactive, force-directed mind-map: drag to pan, scroll to zoom, drag a node
    // to pin it, click a node to recenter (re-query). Vanilla — a tiny spring layout
    // over an SVG viewBox, no dependencies. Respects prefers-reduced-motion (settles
    // synchronously, no animation). _mmRAF holds the running animation handle.
    let _mmRAF = null, _mmLevel = "keyword", _mmTerm = null, _mmViewMode = "map", _mmGraph = null;
    function _mmWindowQS() {
      const w = $("mm-window").value;
      if (w === "custom") {
        const a = $("mm-start").value, b = $("mm-end").value;
        return (a ? `&start=${a}` : "") + (b ? `&end=${b}` : "");
      }
      return w ? `&days=${w}` : "";
    }
    function mmWindowChange() {
      $("mm-custom").style.display = $("mm-window").value === "custom" ? "" : "none";
      mmReload();
    }
    function mmView(v) {
      _mmViewMode = v;
      document.querySelectorAll("#mm-views button").forEach(b =>
        b.classList.toggle("active", b.dataset.view === v));
      if (_mmGraph) renderGraph(_mmGraph);
    }
    function mmExpand() {
      const host = $("ins-mindmap");
      host.classList.toggle("mm-big");
      $("mm-expand").textContent = host.classList.contains("mm-big") ? "⛶ Reduce" : "⛶ Enlarge";
      if (_mmGraph) renderGraph(_mmGraph);
    }
    function mmReload() {
      if (_mmLevel === "keyword" && !_mmTerm) { if (_mmGraph) renderGraph(_mmGraph); return; }
      mmLevel(_mmLevel);
    }
    async function mmLevel(level) {
      _mmLevel = level;
      document.querySelectorAll("#mm-levels button").forEach(b =>
        b.classList.toggle("active", b.dataset.level === level));
      const host = $("ins-mindmap");
      if (level === "keyword") {
        if (!_mmTerm) { host.innerHTML = '<div class="muted">Pick a keyword above to see its relatives (two hops).</div>'; return; }
        host.innerHTML = '<div class="muted">Loading…</div>';
        try {
          const g = await api(`/api/insights/graph?level=keyword&term=${encodeURIComponent(_mmTerm)}&hops=2${_mmWindowQS()}`);
          renderGraph(g);
        } catch (e) { host.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
        return;
      }
      host.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const g = await api(`/api/insights/graph?level=${level}${_mmWindowQS()}`);
        renderGraph(g);
      } catch (e) { host.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
    }
    // Adapter: the keyword view comes from the layered endpoint (2 hops + window).
    async function renderMindmap(center, _pairs) {
      _mmTerm = center; _mmLevel = "keyword";
      document.querySelectorAll("#mm-levels button").forEach(b =>
        b.classList.toggle("active", b.dataset.level === "keyword"));
      try {
        const g = await api(`/api/insights/graph?level=keyword&term=${encodeURIComponent(center)}&hops=2${_mmWindowQS()}`);
        renderGraph(g);
      } catch (e) { $("ins-mindmap").innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
    }
    function mmLegend(g) {
      const sw = (c) => `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${c};vertical-align:-1px"></span>`;
      const items = [];
      const kinds = new Set(g.nodes.map(n => n.center ? "center" : (n.hop === 2 ? "hop2" : n.kind)));
      if (kinds.has("center")) items.push(`${sw("var(--ok)")} <span>seed term</span>`);
      if (kinds.has("keyword")) items.push(`${sw("var(--accent)")} <span>relative</span>`);
      if (kinds.has("hop2")) items.push(`${sw("var(--muted)")} <span>relative of a relative</span>`);
      if (kinds.has("family")) items.push(`${sw("var(--warn)")} <span>family</span>`);
      if (kinds.has("supergroup")) items.push(`${sw("var(--ok)")} <span>super-group</span>`);
      return items.join(" &nbsp;·&nbsp; ");
    }
    function renderGraph(g) {
      _mmGraph = g;
      if (_mmRAF) { cancelAnimationFrame(_mmRAF); _mmRAF = null; }
      const host = $("ins-mindmap");
      if (!g.nodes || g.nodes.length < 2) { host.innerHTML = '<div class="muted">No strong associations yet.</div>'; return; }
      const big = host.classList.contains("mm-big");
      const W = big ? 1200 : 680, H = big ? 760 : 460;
      const scale = (Number($("mm-size").value) || 100) / 100;
      const maxSize = Math.max(...g.nodes.map(n => n.size || 1), 1);
      const fsOf = (n) => ((n.center ? 17 : 9 + 9 * Math.sqrt((n.size || 1) / maxSize)) * scale);

      // ---- layout: mind-map rules (center → arms → ALWAYS outward) -------- //
      const nodes = g.nodes.slice(0, 60).map(n => ({...n, fs: fsOf(n)}));
      const byId = {}; nodes.forEach(n => byId[n.id] = n);
      let treeEdges = [];
      if (_mmViewMode === "cloud") {
        // Word cloud: weight-ordered spiral from the centre, no edges.
        const sorted = [...nodes].sort((a, b) => (b.size || 1) - (a.size || 1));
        sorted.forEach((n, i) => {
          const ang = i * 2.39996, r = 16 * Math.sqrt(i);   // golden-angle spiral
          n.x = W / 2 + r * Math.cos(ang) * 1.6;
          n.y = H / 2 + r * Math.sin(ang);
        });
      } else if (g.level === "keyword") {
        const center = nodes.find(n => n.center) || nodes[0];
        center.x = W / 2; center.y = H / 2;
        const arms = nodes.filter(n => !n.center && n.hop !== 2);
        const leaves = nodes.filter(n => n.hop === 2);
        const parentOf = {};
        for (const e of g.edges) {
          if (byId[e.b] && byId[e.b].hop === 2 && byId[e.a] && !byId[e.a].center) {
            if (!(e.b in parentOf) || e.weight > parentOf[e.b].w) parentOf[e.b] = {p: e.a, w: e.weight};
          }
        }
        const R1 = Math.min(W, H) * 0.30, R2 = Math.min(W, H) * 0.46;
        arms.forEach((n, i) => {
          n.ang = (i / arms.length) * 2 * Math.PI - Math.PI / 2;
          n.x = W / 2 + R1 * Math.cos(n.ang); n.y = H / 2 + R1 * Math.sin(n.ang);
          treeEdges.push({a: center, b: n, w: 2});
        });
        const kids = {};
        leaves.forEach(n => {
          const p = byId[(parentOf[n.id] || {}).p] || arms[0];
          (kids[p.id] = kids[p.id] || []).push(n);
          n._p = p;
        });
        for (const pid in kids) {
          const p = byId[pid], ks = kids[pid];
          const span = (2 * Math.PI / Math.max(arms.length, 1)) * 0.8;
          ks.forEach((n, j) => {
            const a = p.ang + span * ((j + 1) / (ks.length + 1) - 0.5);
            n.x = W / 2 + R2 * Math.cos(a); n.y = H / 2 + R2 * Math.sin(a);
            treeEdges.push({a: p, b: n, w: 1});
          });
        }
      } else {
        // family / super-group: concentric rings by weight rank (outward =
        // lighter), each node linked only to its single strongest neighbour.
        const sorted = [...nodes].sort((a, b) => (b.size || 1) - (a.size || 1));
        sorted.forEach((n, i) => {
          if (i === 0) { n.x = W / 2; n.y = H / 2; return; }
          const ring = i <= 8 ? 1 : i <= 24 ? 2 : 3;
          const start = ring === 1 ? 0 : ring === 2 ? 8 : 24;
          const count = ring === 1 ? Math.min(8, sorted.length - 1) : ring === 2 ? Math.min(16, sorted.length - 9) : sorted.length - 25;
          const ang = ((i - start) / Math.max(count, 1)) * 2 * Math.PI - Math.PI / 2 + ring * 0.3;
          const R = Math.min(W, H) * (0.16 + 0.15 * ring);
          n.x = W / 2 + R * Math.cos(ang) * 1.25; n.y = H / 2 + R * Math.sin(ang);
        });
        const best = {};
        for (const e of g.edges) {
          if (!byId[e.a] || !byId[e.b]) continue;
          if (!(e.a in best) || e.weight > best[e.a].w) best[e.a] = {o: e.b, w: e.weight};
          if (!(e.b in best) || e.weight > best[e.b].w) best[e.b] = {o: e.a, w: e.weight};
        }
        const seen = new Set();
        for (const id in best) {
          const key = [id, best[id].o].sort().join("|");
          if (!seen.has(key)) { seen.add(key); treeEdges.push({a: byId[id], b: byId[best[id].o], w: best[id].w}); }
        }
      }

      host.innerHTML =
        `<div class="hint" id="mm-legend">${mmLegend(g)}</div>` +
        `<svg id="mm-svg" viewBox="0 0 ${W} ${H}" width="100%" style="background:var(--panel2);border:1px solid var(--border);border-radius:8px;touch-action:none;cursor:grab"><g id="mm-view"></g></svg>` +
        `<div class="hint">Drag to pan · scroll to zoom (far out goes up a level) · click a word to dive in. <b>Font size = shared-article volume.</b> ${_mmViewMode === "map" ? "Branches grow outward from the centre; each leaf hangs off its strongest relative." : "Cloud view: weight-ordered, no links."} ${esc(g.method || "")} ${esc(g.caveat || "")}</div>`;
      const svg = $("mm-svg"), view = $("mm-view");
      const maxW = Math.max(...treeEdges.map(e => e.w || 1), 1);
      view.innerHTML =
        treeEdges.map(e => `<line stroke="var(--border)" stroke-width="${(0.8 + 2.2 * (e.w || 1) / maxW).toFixed(1)}"
            x1="${e.a.x.toFixed(1)}" y1="${e.a.y.toFixed(1)}" x2="${e.b.x.toFixed(1)}" y2="${e.b.y.toFixed(1)}"></line>`).join("") +
        nodes.map((n, i) => {
          const col = n.center ? "var(--ok)"
            : n.kind === "supergroup" ? "var(--ok)"
            : n.kind === "family" ? "var(--warn)"
            : n.hop === 2 ? "var(--muted)" : "var(--accent)";
          const fam = (n.members || []).length > 1;
          const title = fam ? `<title>${esc((n.members || []).join(", "))}</title>` : "";
          return `<g class="mm-node" data-i="${i}" style="cursor:pointer" transform="translate(${n.x.toFixed(1)},${n.y.toFixed(1)})">${title}` +
            `<text text-anchor="middle" dominant-baseline="central" font-size="${n.fs.toFixed(1)}" font-weight="${n.center ? 700 : 500}" fill="${col}">${esc(n.label)}</text></g>`;
        }).join("");

      // -- pan / zoom (level-up on far zoom-out) + click-to-dive ------------- //
      let vb = {x: 0, y: 0, w: W, h: H};
      const applyVB = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
      const ptVB = (e) => { const m2 = svg.getScreenCTM().inverse(); const p = svg.createSVGPoint();
        p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(m2); };
      svg.addEventListener("wheel", (e) => { e.preventDefault(); const p = ptVB(e);
        const sc = Math.min(3, Math.max(0.34, vb.w * Math.exp(e.deltaY * 0.0015) / W)) * W / vb.w;
        vb.x = p.x - (p.x - vb.x) * sc; vb.y = p.y - (p.y - vb.y) * sc; vb.w *= sc; vb.h *= sc; applyVB();
        if (vb.w / W >= 2.7) {
          if (_mmLevel === "keyword") mmLevel("family");
          else if (_mmLevel === "family") mmLevel("supergroup");
        }
      }, {passive: false});
      let drag = null;
      svg.addEventListener("pointerdown", (e) => {
        const gEl = e.target.closest && e.target.closest(".mm-node");
        if (gEl) drag = {type: "node", i: +gEl.dataset.i, sx: e.clientX, sy: e.clientY, moved: false};
        else { const r = svg.getBoundingClientRect();
          drag = {type: "pan", x0: vb.x, y0: vb.y, cx: e.clientX, cy: e.clientY, sx: vb.w / r.width, sy: vb.h / r.height}; }
        svg.setPointerCapture(e.pointerId);
      });
      svg.addEventListener("pointermove", (e) => { if (!drag) return;
        if (drag.type === "node") { if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > 4) drag.moved = true; }
        else { vb.x = drag.x0 - (e.clientX - drag.cx) * drag.sx; vb.y = drag.y0 - (e.clientY - drag.cy) * drag.sy; applyVB(); }
      });
      svg.addEventListener("pointerup", (e) => {
        if (drag && drag.type === "node" && !drag.moved) {
          const n = nodes[drag.i];
          if (!n.center) {
            if (n.kind === "supergroup") mmLevel("family");
            else { $("ins-term").value = n.label; pickTerm(n.label); }
          }
        }
        drag = null; try { svg.releasePointerCapture(e.pointerId); } catch (_e) {}
      });
    }

    async function exploreTerm() {
      const term = $("ins-term").value.trim();
      if (!term) { toast("Enter a keyword or entity.", "err"); return; }
      $("ins-trend").innerHTML = '<div class="muted">Loading…</div>';
      $("ins-mindmap").innerHTML = ""; $("ins-context").innerHTML = ""; $("ins-framing").innerHTML = "";
      try {
        const [tr, assoc, ctx] = await Promise.all([
          api("/api/insights/trend?bucket=week&term=" + encodeURIComponent(term)),
          api("/api/insights/associations?term=" + encodeURIComponent(term)),
          api("/api/insights/context?term=" + encodeURIComponent(term)),
        ]);
        if (!tr.resolved) { $("ins-trend").innerHTML = `<div class="note err">No indexed mentions of “${esc(term)}”. Index the corpus, or try another term.</div>`; return; }
        const r = tr.resolved;
        const t8 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
        $("ins-trend").innerHTML =
          `<div style="margin-bottom:6px">Resolved to <strong>${esc(r.term)}</strong> ` +
          `<span class="pill">${esc(r.kind)}</span> · ${tr.total} mentions in ${tr.articles} articles ` +
          `<button class="tiny secondary" onclick="openCorpus(${esc(JSON.stringify(r.term))})" title="Open this keyword as a corpus window: trend, member articles, and shared outbound links (the sources' sources).">⊞ Corpus</button></div>` +
          `<div style="margin-bottom:8px"><div class="hint">${esc(t8("Time range"))}</div>` +
          `<div id="ins-trend-scope"></div></div>` +
          `<div id="ins-trend-oo"></div>`;
        // FULL bucketed series fetched once; the ooTimeScope window FILTERS it
        // client-side (invariant #16 — never thinned; ooChart unchanged).
        const allPts = tr.points || [];
        const insDraw = (pts) => ooChart($("ins-trend-oo"), [{label: r.term, unit: "mentions",
          points: pts.map(pt => ({t: pt.date, v: pt.count}))}],
          {height: 180, zeroBase: true, lineMin: 8, bucket: "week",
           onSelectRange: _brushToCorpus(r.term, "week")});
        const insDef = _buildTrendScope($("ins-trend-scope"), allPts, insDraw);
        insDraw(_windowTrendPoints(allPts, insDef.from, insDef.to));
        renderMindmap(r.term, assoc.pairs);
        loadFraming(r.term);
        $("ins-context").innerHTML = (ctx.mentions || []).length
          ? ctx.mentions.map(m => `<div class="note" style="max-width:none;margin-bottom:6px">
               <div style="font-size:12px" class="muted">${esc(m.source||"")}${m.country?" · "+esc(ooRegionName(m.country, m.country)):""}${m.city?" · "+esc(m.city):""}${m.observed_on?" · "+esc(m.observed_on):""}
                 ${m.article_id?`· <a href="/api/articles/${m.article_id}/view" target="_blank" rel="noopener" title="offline stored copy">open</a>`:""}${m.url?`· ${extLink(m.url, "source ↗", "muted")}`:""}</div>
               <div>${esc(m.snippet)}</div></div>`).join("")
          : '<div class="muted">No context snippets.</div>';
      } catch (e) { $("ins-trend").innerHTML = ""; toast(_failMsg("Explore failed: {error}", e), "err"); }
    }

    // ── The growth sentinel ────────────────────────────────────────────────────
    // `queries._growth_of` reports the recent COUNT in `growth` when the prior rate
    // scaled to the window comes to less than one mention: there is no denominator
    // worth dividing by, so the count is substituted. That substitution is a SENTINEL,
    // not a measurement, and printed as "↑N×" it is a fabricated magnitude — a field
    // bulletin rendered 5,701 mentions against a prior of 4 as "×5701.0", and 19 of its
    // 20 rows were the same sentinel. The bulletin renderer was fixed then; these six
    // chrome sites were not, and this is the shared reader they go through now.
    //
    // Deliberately mirrors `src/bulletin/render.py::_is_ratio`, down to the wording of
    // the sentences below, so the same quantity reads the same way in the document and
    // in the chrome. THREE states, because two would force a guess: `null` means the
    // payload does not say and cannot be asked, and a row that cannot prove it is a
    // ratio does not get to claim one. Payloads predating the flag still carry
    // `expected`, which is what the flag is computed FROM, so they are read rather than
    // guessed at.
    function growthIsRatio(row) {
      if (!row) return null;
      const flag = row.growth_is_ratio;
      if (flag !== undefined && flag !== null) return !!flag;
      const exp = row.expected;
      if (exp === undefined || exp === null) return null;
      const n = Number(exp);
      return Number.isFinite(n) ? n >= 1 : null;
    }
    // The honest phrase for a row whose `growth` is NOT a measured ratio, or null when
    // it is — in which case the caller keeps its own existing "↑N×" rendering unchanged.
    // Splitting it this way is deliberate: only the branch that was WRONG changes, so a
    // measured ratio still renders byte-for-byte as it does today on all six surfaces,
    // and no ratio-branch string moves through a translation table it was never in.
    //
    // The three sentences are the bulletin's, verbatim, and their translations were
    // lifted from `configs/bulletin_i18n/` rather than re-drafted — same claim, same
    // words, whichever surface the reader is on.
    function growthFallback(row, opts) {
      opts = opts || {};
      const isRatio = growthIsRatio(row);
      if (isRatio === true && row && row.growth != null) return null;

      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const TF = (s, v) => (window.OOI18N && OOI18N.tf) ? OOI18N.tf(s, v)
        : String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
      const recent = (row && row.recent != null) ? row.recent : 0;
      const prior = (row && row.prior != null) ? row.prior : null;

      // Nothing computed, or the row cannot prove it is a ratio: say the count and stop,
      // rather than print "×undefined" or claim a multiple the row cannot support.
      if (!row || row.growth == null || isRatio === null) {
        return TF("{n} mentions", {n: fmtNum(recent)});
      }
      // The sentinel. Say the two counts it stands between and name the reason; the one
      // thing not to do is dress the count as a multiple.
      if (prior === 0 || prior == null) {
        return TF("{n} mentions — new in this period, nothing prior to compare", {n: fmtNum(recent)});
      }
      const win = (opts.window && row.baseline_days != null)
        ? TF("prior {days} days", {days: row.baseline_days}) : T("prior period");
      return TF("{n} mentions, against {prior} in the {window} — too thin a baseline to divide by",
                {n: fmtNum(recent), prior: fmtNum(prior), window: win});
    }

    // The current UI language as a target for verified keyword translations.
    function uiLangCode() { return (window.OOI18N && OOI18N.current && OOI18N.current()) || "en"; }
    function tgtLangParam() { return "&target_lang=" + encodeURIComponent(uiLangCode()); }
    // A foreign keyword's VERIFIED translation into the UI language (Wikidata-sourced
    // cross-language ring) — shown beside the original so the reader is never blinded
    // to a foreign-language keyword, only given its translation (the language-aware
    // engine). `row` is the keyword row; `t` here is the outer i18n function.
    function kwTransHtml(row) {
      if (!row || !row.translation) return "";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      // S4.2: the verified cross-language concept; the per-language COMPOSITION
      // (de-US-centring in action — a concept's coverage ACROSS languages) rides the #oo-tip
      // LAYERED hover on demand (invariant #17), never crowding the visible trend/Home row.
      // language_breakdown = {langCode: count} on the merged ring row (queries.py); absent on a
      // single-language keyword -> just the base title (defensive).
      let title = t("Verified translation (cross-language concept).");
      const lb = row.language_breakdown;
      if (lb && typeof lb === "object") {
        const parts = Object.keys(lb)
          .map((k) => [k, +lb[k] || 0])
          .filter((p) => p[1] > 0)
          .sort((a, b) => b[1] - a[1])
          .map((p) => `${p[0]} ${p[1]}`);
        if (parts.length) title += " — " + t("Across languages:") + " " + parts.join(" · ");
      }
      return ` <span class="kw-trans" title="${esc(title)}">→ ${esc(row.translation)}</span>`;
    }
    // The TENTATIVE LLM translation (Phase 4 fallback): shown ONLY when no verified
    // ring translation exists, with a distinct ≈ marker + an "unreliable" hover — never
    // presented as fact.
    function kwTentativeHtml(row) {
      if (!row || row.translation || !row.tentative) return "";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      return ` <span class="kw-trans kw-tentative" title="${esc(t("AI-generated tentative translation — unreliable, not verified."))}">≈ ${esc(row.tentative)}</span>`;
    }

    // -- Circle-grammar level marking (GROUPS amendment §B) -------------------------
    // The uniform convention app-wide: plain chip = keyword, ONE ring = a group
    // (a cross-language concept), TWO rings = a super-group. `lvlClass`/`lvlTitle`
    // are the shared primitives every chip-rendering call site attaches; `.lvl-group`
    // /`.lvl-super` (app.css) draw the box-shadow rings themselves, so applying a
    // class never shifts layout. Colour is reinforcing-only (WCAG 1.4.1) -- the
    // translated title here (rendered by the existing #oo-tip hover convention,
    // invariant #17) plus the ring COUNT are what actually carry the level.
    function lvlClass(level) {
      return level === "super" ? "lvl-super" : (level === "group" ? "lvl-group" : "");
    }
    function lvlTitle(level) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (level === "super") return t("A super-group: several groups gathered under one theme.");
      if (level === "group") return t("A group: one concept counted across every language it appears in.");
      return "";
    }
    // The reusable path breadcrumb -- renders wherever any level appears, e.g.
    // "⦾⦾ Climate change ▸ ⦾ temperature ▸ температура (ru)". `segments` is
    // [{level:'super'|'group'|'keyword', label, onClick}]; every segment is its own
    // clickable button (plural super-group membership renders several ⦾⦾ segments,
    // never silently picking one). `onClick` receives no args -- callers close over
    // whatever id they need (mirrors the openSupergroup/openCorpus call convention).
    let _lvlCrumbHandlers = [];
    function lvlBreadcrumb(segments) {
      if (!segments || !segments.length) return "";
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const glyph = (lvl) => lvl === "super" ? "⦾⦾" : (lvl === "group" ? "⦾" : "");
      const idx0 = _lvlCrumbHandlers.length;
      _lvlCrumbHandlers.push(...segments.map((s) => s.onClick || null));
      const parts = segments.map((s, i) => {
        const g = glyph(s.level);
        const title = esc(lvlTitle(s.level) || t("Open this corpus"));
        const handlerIdx = idx0 + i;
        const clickable = _lvlCrumbHandlers[handlerIdx] ? ` onclick="_lvlCrumbFire(${handlerIdx})"` : "";
        return `<button class="seg" type="button" title="${title}"${clickable}>${g ? g + " " : ""}${esc(s.label)}</button>`;
      });
      return `<span class="lvl-crumb">` + parts.join(`<span class="sep">▸</span>`) + `</span>`;
    }
    function _lvlCrumbFire(i) { const fn = _lvlCrumbHandlers[i]; if (typeof fn === "function") fn(); }
    // Analysis-window Keywords subtab render + the Phase-4 tentative-fill action.
    let _anKwData = null, _anKwHost = null;
    function _anKwNeedsTentative(tm) {
      return !tm.translation && !tm.tentative && (tm.language || "").toLowerCase() !== uiLangCode();
    }
    let _anConjLast = null;   // S13: the last /corpus-algebra result, for the Open-as-corpus action

    // S13 Conjunction Lens — an N-keyword set-algebra picker hosted in the analysis window's
    // Keywords subtab. It calls the live /api/insights/corpus-algebra (∩ all / ∪ any / ∖ first-
    // only), shows the set EXPRESSION as the corpus label + each term's exact n + the combined n,
    // and opens the exact result set as its own corpus via openAnalysisForIds. Counts only, never
    // a score; the bounded flag + method/caveat are surfaced. Browser-unverified per fork-3.
    function anConjunctionHtml() {
      return `<div style="margin-bottom:10px;padding:8px;border:1px solid var(--line);border-radius:6px">`
        + `<div class="hint" style="margin-top:0"><b>Combine keywords</b> — set algebra over N keywords. `
        + `The set expression is the corpus label; counts only, never a score.</div>`
        + `<div class="row" style="flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px">`
        + `<input id="an-conj-terms" placeholder="keyword, keyword, keyword…" style="flex:1;min-width:180px" `
        + `onkeydown="if(event.key==='Enter')anCombine('intersection')">`
        + `<button class="secondary" onclick="anCombine('intersection')" title="articles mentioning ALL terms">∩ All</button>`
        + `<button class="secondary" onclick="anCombine('union')" title="articles mentioning ANY term">∪ Any</button>`
        + `<button class="secondary" onclick="anCombine('difference')" title="the first term and none of the rest">∖ First-only</button>`
        + `</div><div id="an-conj-result" style="margin-top:8px"></div></div>`;
    }
    function _anConjSep(op) { return op === "difference" ? " ∖ " : (op === "union" ? " ∪ " : " ∩ "); }
    function anCombineHtml(d) {
      const terms = (d && d.terms) || [];
      if (!terms.length) return `<div class="muted">${esc((d && d.method) || "No resolvable keyword given.")}</div>`;
      const expr = terms.map((x) => esc(x.normalized || x.term)).join(_anConjSep(d.op));
      const perTerm = terms.map((x) =>
        `<span class="chip" title="exact corpus-wide article count for this term">${esc(x.term)} <span class="muted">${esc(String(x.n))}</span></span>`).join(" ");
      const bounded = d.result_bounded
        ? `<div class="card-caveat" title="the set scan reached its cap">Result bounded — a true SUBSET of the answer (it may miss members), never a fabricated one.</div>` : "";
      const open = (d.n_combined > 0)
        ? `<button class="secondary" onclick="anOpenCombined()">Open ${esc(String(d.n_combined))} article(s) as a corpus →</button>`
        : `<div class="muted">Empty set — no articles match this combination.</div>`;
      return `<div class="hint" style="margin-top:0"><b>${esc(expr)}</b> · <b>${esc(String(d.n_combined))}</b> article(s)</div>`
        + `<div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px">${perTerm}</div>`
        + `<div style="margin-top:6px">${open}</div>${bounded}`
        + `<div class="card-caveat" title="${esc(d.method || "")}">${esc(d.caveat || "")}</div>`;
    }
    async function anCombine(op) {
      const inp = $("an-conj-terms"), out = $("an-conj-result");
      if (!inp || !out) return;
      const terms = (inp.value || "").split(",").map((s) => s.trim()).filter(Boolean);
      if (!terms.length) { out.innerHTML = `<div class="muted">Enter at least one keyword to combine.</div>`; return; }
      out.innerHTML = `<div class="muted">Combining…</div>`;
      try {
        const d = await api("/api/insights/corpus-algebra?terms=" + encodeURIComponent(terms.join(","))
          + "&op=" + encodeURIComponent(op));
        _anConjLast = d;
        out.innerHTML = anCombineHtml(d);
      } catch (e) { out.innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
    }
    function anOpenCombined() {
      const d = _anConjLast;
      if (!d || !d.article_ids || !d.article_ids.length) return;
      const expr = ((d.terms) || []).map((x) => x.normalized || x.term).join(_anConjSep(d.op));
      openAnalysisForIds(d.article_ids, expr);   // the exact-set precedent — a fresh corpus tab
    }
    function anRenderKwChips() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const d = _anKwData, kw = _anKwHost;
      if (!kw) return;
      if (!d || !d.terms || !d.terms.length) {
        // The Combine picker works over the WHOLE-corpus keyword index, so it stays useful even
        // when this window's matched set has no indexed keywords.
        kw.innerHTML = anConjunctionHtml()
          + `<div class="muted">${esc(t("No keywords indexed across the matched articles yet."))}</div>`;
        return;
      }
      // S3 (keyword -> super-group navigation): a "part of ⊕ <group>" chip per group
      // the keyword belongs to (never picks one — plural membership renders every
      // hit), linking straight to the group's own trend + members view.
      // §B circle grammar: this chip jumps to a SUPER-group (openSupergroup), so it
      // carries the double-ring .lvl-super marking + the translated level hover
      // appended to the existing action hover (never replacing it).
      const sgChips = (term) => (term.supergroups || []).map((g) =>
        `<button class="chip tiny lvl-super" onclick="openSupergroup(${g.id})"`
        + ` title="${esc(t("Open this group's own trend + members") + " — " + lvlTitle("super"))}">⊕ ${esc(g.name)}</button>`).join(" ");
      const chips = d.terms.map((term) =>
        `<button class="chip" data-kwstat="${esc(term.term)}" onclick="openCorpus(${esc(JSON.stringify(term.term))})"`
        + ` title="${esc(t("Open this keyword's own analysis window"))}">${esc(term.term)}${kwTransHtml(term)}${kwTentativeHtml(term)}`
        + ` <span class="muted">${term.articles}</span></button>${sgChips(term)}`).join(" ");
      // Audit-07 B1 disclosure: our extractor does NOT segment CJK, so those keywords
      // are unreliable; surface it when CJK terms are present.
      const cjk = d.terms.some((tm) => /[぀-ヿ㐀-䶿一-鿿가-힯]/.test(tm.term));
      const cjkNote = cjk ? ` · <span class="note err" title="${esc(t("Keyword extraction splits on spaces and punctuation; it does NOT segment Chinese, Japanese or Korean, so the CJK keyword aggregates shown here are unreliable."))}">${esc(t("CJK not segmented — unreliable"))}</span>` : "";
      // Offer the tentative LLM fallback only when some keyword has NO verified
      // translation into the reader's language (Phase 4; explicit action, never auto).
      const btn = d.terms.some(_anKwNeedsTentative)
        ? ` <button class="ghost tiny" onclick="anFillTentative()" title="${esc(t("AI-generated tentative translation — unreliable, not verified."))}">✦ ${esc(t("Translate the rest (AI, tentative)"))}</button>`
        : "";
      kw.innerHTML = anConjunctionHtml()
        + `<div class="hint"><b>${d.terms.length}</b> ${esc(t("Keywords"))}`
        + ` · <span class="muted">${esc(d.caveat || "")}</span>${cjkNote}${btn}</div>`
        + `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px">${chips}</div>`
        + anContextHtml();
    }
    // S4.4: term-in-context CONCORDANCE — ported from the retired Insights search bar
    // (exploreTerm's #ins-context) into the #an Keywords subtab, so the omnibar→#an window
    // absorbs the LAST Insights-bar capability (trend + associations + mindmap already live in
    // #an). Keyed on the analysis QUERY term; SKIPPED honestly for an article-id corpus that has
    // no single term. Snippets/counts only, never a score. Rides on _anKwData so the tentative-
    // translate re-render (anFillTentative → anRenderKwChips) keeps the snippets shown.
    function anContextHtml() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const ctx = _anKwData && _anKwData._context;
      if (!ctx) return "";   // no single-term corpus, or not fetched yet — render nothing
      const ms = ctx.mentions || [];
      const body = ms.length
        ? ms.map((m) => `<div class="note" style="max-width:none;margin-bottom:6px">`
            + `<div style="font-size:12px" class="muted">${esc(m.source || "")}`
            + `${m.country ? " · " + esc(ooRegionName(m.country, m.country)) : ""}`
            + `${m.city ? " · " + esc(m.city) : ""}${m.observed_on ? " · " + esc(m.observed_on) : ""}`
            + `${m.article_id ? ` · <a href="/api/articles/${m.article_id}/view" target="_blank" rel="noopener" title="${esc(t("offline stored copy"))}">${esc(t("open"))}</a>` : ""}`
            + `${m.url ? " · " + extLink(m.url, t("source ↗"), "muted") : ""}</div>`
            + `<div>${esc(m.snippet || "")}</div></div>`).join("")
        : `<div class="muted">${esc(t("No context snippets."))}</div>`;
      return `<h3 style="margin:16px 0 6px;font-size:13px">${esc(t("In context"))}`
        + `${ctx.term ? ` <span class="muted">— ${esc(ctx.term)}</span>` : ""}</h3>` + body;
    }
    async function loadAnContext(p) {
      if (!_anKwData) return;
      const term = (p && p.get && p.get("query")) || anQuery() || "";
      if (!term) { _anKwData._context = null; return; }   // article-id corpus: no single term to concord
      try {
        const ctx = await api("/api/insights/context?term=" + encodeURIComponent(term) + "&limit=12");
        _anKwData._context = { term: (ctx.resolved && ctx.resolved.term) || term, mentions: ctx.mentions || [] };
      } catch (_e) { _anKwData._context = null; }   // best-effort; never break the Keywords subtab
      anRenderKwChips();
    }
    async function anFillTentative() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const d = _anKwData; if (!d || !d.terms) return;
      const items = d.terms.filter(_anKwNeedsTentative).map(tm => ({term: tm.term, language: tm.language}));
      if (!items.length) return;
      try {
        const r = await api("/api/ai/translate-keywords",
          {method: "POST", body: JSON.stringify({terms: items, target_lang: uiLangCode()})});
        if (!r.available) {
          toast(t("Local AI is offline — start Ollama (and turn airplane mode off) for tentative translations."), "err");
          return;
        }
        const tx = r.translations || {};
        let n = 0;
        d.terms.forEach(tm => { if (tx[tm.term]) { tm.tentative = tx[tm.term]; n++; } });
        anRenderKwChips();
        if (!n) toast(t("No tentative translations were produced."));
      } catch (e) { toast(_failMsg("Translate failed: {error}", e), "err"); }
    }
    function termListHtml(terms, extra) {
      if (!terms.length) return '<div class="muted">Nothing yet — index the corpus.</div>';
      return terms.map(t => `<div style="padding:4px 0;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:6px">
        <button class="tiny danger" title="exclude this keyword" style="margin:0;padding:0 6px"
          onclick='excludeKeyword(${esc(JSON.stringify(t.term))})'>✕</button>
        <a href="#" data-kwstat="${esc(t.term)}" title="${esc(t.term)}" onclick='pickTerm(${esc(JSON.stringify(t.term))});return false'>${esc(t.term)}</a>${kwTransHtml(t)}
        <span class="pill">${esc(t.kind)}</span> <span class="muted">${extra(t)}</span></div>`).join("");
    }
    // Trends as clickable horizontal BAR graphs (field test 2026-06-19 #25): keywords
    // top→down, bar length ∝ the REAL measured value (mentions count / rising rate —
    // never a composite score), the value shown beside it; clicking a bar opens the
    // unified analysis window (trend over time + worldwide spread). The bar is a
    // visual of the count/rate, not a verdict — the number stays explicit.
    // `valueOf` may return null for a row that HAS no magnitude on this scale — a rising
    // row whose `growth` is the no-baseline sentinel is a count, not a rate, and drawing
    // it on the rate scale is what made every real ratio invisible (a 5,701-mention
    // sentinel beside a ×3.6 ratio). Such a row keeps its place and its honest label and
    // gets an EMPTY track: no fill at all, rather than the 2% stub, which would read as a
    // very small rate instead of no rate. The scale is then taken over the rows that
    // genuinely share it.
    function termBarsHtml(terms, valueOf, labelOf) {
      const T = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!terms.length) return '<div class="muted">' + esc(T("Nothing yet — index the corpus.")) + "</div>";
      const scaled = terms.map(t => valueOf(t)).map(v => (v == null ? null : Number(v)))
        .map(v => (v != null && Number.isFinite(v)) ? v : null);
      const max = Math.max(1, ...scaled.filter(v => v != null));
      return '<div class="term-bars">' + terms.map((t, i) => {
        const v = scaled[i];
        const fill = v == null ? ""
          : `<span class="tb-fill" style="width:${Math.max(2, Math.round((v / max) * 100))}%"></span>`;
        return `<div class="tb-row">
          <button class="tiny danger tb-x" title="exclude this keyword" onclick='excludeKeyword(${esc(JSON.stringify(t.term))})'>✕</button>
          <a class="tb-label" href="#" data-kwstat="${esc(t.term)}" title="${esc(t.term)} — open in analysis (trend + worldwide spread)"
             onclick='openAnalysisFor(${esc(JSON.stringify(t.term))});return false'>${esc(t.term)}</a>
          <span class="tb-bar" aria-hidden="true">${fill}</span>
          <span class="tb-val muted">${esc(labelOf(t))}</span>
        </div>`;
      }).join("") + "</div>";
    }

    async function excludeKeyword(term) {
      try {
        await api("/api/insights/exclude", {method: "POST", body: JSON.stringify({term})});
        toast(`Excluded “${term}”. Manage exclusions in Settings.`);
        loadTrends(); if ($("ins-term").value.trim()) exploreTerm();
      } catch (e) { toast(_failMsg("Exclude failed: {error}", e), "err"); }
    }

    // Honesty-envelope disclosure (informed-consent-by-layering): the maintained-counter
    // aggregates carry {value, basis:exact|estimated, as_of, method, n}; the rollup-served
    // paths add a cache disclosure {source, as_of, note}. Render a small VISIBLE chip so the
    // reader knows whether a number is an exact live count or an estimate, and as of when;
    // the method / n / rollup note ride the #oo-tip hover (the translated title). It is a
    // DISCLOSURE, never a score (no numeric grade), so the no-score rule holds.
    function _basisWhen(iso) { return iso ? String(iso).slice(0, 10) : ""; }
    function basisChip(counts, disc) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!counts && !disc) return "";
      let label = "", est = false;
      const titleParts = [];
      if (counts && counts.basis) {
        est = counts.basis === "estimated";
        const w = _basisWhen(counts.as_of);
        label = t(est ? "estimated" : "exact") + (w ? " · " + t("as of") + " " + w : "");
        if (counts.method) titleParts.push(counts.method);
        if (counts.n != null) titleParts.push("n = " + counts.n);
      }
      if (disc) {
        if (!label) { const w = _basisWhen(disc.as_of); label = t("cached") + (w ? " · " + t("as of") + " " + w : ""); }
        if (disc.note) titleParts.push(disc.note);
      }
      if (!label) return "";
      const title = titleParts.join(" · ");
      return `<span class="basis-chip${est ? " est" : ""}"${title ? ` title="${esc(title)}"` : ""}>${esc(label)}</span>`;
    }
    async function loadTrends() {
      const wd = $("trd-window").value, bd = $("trd-base").value, kind = $("trd-kind").value, cc = $("trd-country").value.trim();
      const qp = (extra) => `kind=${encodeURIComponent(kind)}${cc?"&country="+encodeURIComponent(cc):""}${tgtLangParam()}${extra||""}`;
      try {
        const [rising, top] = await Promise.all([
          api(`/api/insights/trending?window_days=${wd}&baseline_days=${bd}&${qp()}`),
          api(`/api/insights/top?days=${wd}&${qp()}`),
        ]);
        // #25: clickable horizontal bar graphs (rising by growth rate, top by mentions).
        // A row whose growth is the no-baseline sentinel is off the rate scale (null) and
        // says so in words, rather than drawing a count as the longest bar on the chart.
        $("trd-rising").innerHTML = termBarsHtml(rising.terms,
          t => (growthIsRatio(t) === true ? t.growth : null),
          t => growthFallback(t) || `↑${t.growth}× (${t.recent} recent · ${t.prior} prior)`);
        $("trd-top").innerHTML = termBarsHtml(top.terms, t => t.mentions,
          t => `${t.mentions} mentions · ${t.articles} articles`);
        $("trd-method").textContent = rising.method ? "Rising = " + rising.method : "";
        const bc = $("trd-basis"); if (bc) bc.innerHTML = basisChip(top.counts, top.basis || rising.basis);
      } catch (e) { toast(_failMsg("Trends failed: {error}", e), "err"); }
      loadTrendWindows();
    }

    // The three preset windows side by side (24h · week · month) — the ruled
    // Trends redesign (2026-06-16). Reads /api/insights/trending-windows (no
    // controls; fixed presets); each column reuses termListHtml. Honest n + the
    // early-corpus caveat travel from the API. Additive to the single-window view.
    let _trendWindowsData = null;  // last /trending-windows payload (the enlarge dialog reads its series)
    async function loadTrendWindows() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("trd-windows"); if (!box) return;
      const LABELS = {"24h": t("Past 24h"), "7d": t("Past week"), "30d": t("Past month")};
      try {
        // EVERY shown trending term carries a daily series (series_top == limit) so
        // each renders a small honest time-series sparkline (dashChartSvg: line when
        // dense, Item-Y bars when sparse — never an interpolated curve) instead of a
        // raw table row — the field ask: see the top trending keywords AS small graphs
        // over time (e.g. the past-week column). Kept to 6/window: glanceable + bounds
        // the per-term day-bucket queries at scale.
        const d = await api("/api/insights/trending-windows?limit=6&series_top=6" + tgtLangParam());
        _trendWindowsData = d;  // stash so enlargeTrend(wi,ti) needs no extra fetch
        box.innerHTML = (d.windows || []).map((w, wi) => {
          const head = `<h2 style="font-size:13px">${esc(LABELS[w.label] || w.label)} <span class="muted">· n=${w.count}</span></h2>`;
          const terms = w.terms || [];
          if (!terms.length) {
            return `<div style="flex:1;min-width:240px">${head}<div class="muted">${esc(t("No rising keywords in this window yet."))}</div></div>`;
          }
          // Map over ALL terms (index ti preserved so enlargeTrend can index back
          // into _trendWindowsData), rendering a sparkline only for those carrying
          // a series; the rest fall through to the plain list below.
          const spark = terms.map((x, ti) => {
            if (!Array.isArray(x.series)) return "";
            // {date,count} -> dashChartSvg's {observed_on,price}; it handles the empty
            // + sparse cases honestly (no fabricated points).
            const pts = x.series.map(p => ({observed_on: p.date, price: p.count}));
            return `<div style="padding:6px 0;border-bottom:1px solid var(--border)">
              <div style="display:flex;align-items:baseline;gap:6px">
                <a href="#" onclick='pickTerm(${esc(JSON.stringify(x.term))});return false'>${esc(x.term)}</a>
                <span class="muted" style="font-size:12px">${esc(growthFallback(x) || `↑${x.growth}× · ${x.recent} recent`)}</span>
                <button class="ghost tiny" style="margin-inline-start:auto" onclick="enlargeTrend(${wi},${ti})" title="${esc(t("Enlarge the chart"))}" aria-label="${esc(t("Enlarge the chart"))}">⛶</button>
              </div>${dashChartSvg(pts, "")}</div>`;
          }).join("");
          const rest = terms.filter(x => !Array.isArray(x.series));
          const restList = rest.length
            ? termListHtml(rest, t2 => growthFallback(t2) || `↑${t2.growth}× · ${t2.recent} recent`)
            : "";
          return `<div style="flex:1;min-width:240px">${head}${spark}${restList}</div>`;
        }).join("") || `<div class="muted">${esc(t("No rising keywords in this window yet."))}</div>`;
        const note = $("trd-windows-note"); if (note) note.textContent = d.caveat || "";
        // If a non-default lens (slope / small multiples) is active, re-render it with
        // the fresh payload (visibility was already set by setTrendLens).
        if (_trdLens === "slope") renderTrendSlope();
        else if (_trdLens === "multiples") renderTrendMultiples();
      } catch (e) { /* additive panel — leave the single-window view intact on error */ }
    }

    // Click-to-enlarge a Trends sparkline into the interactive ooChart (invariant
    // #16: full-resolution, wheel-zoom / drag-pan / hover-readout / legend; Item-Y
    // bars when n<10). The daily series is already in the trending-windows payload
    // (_trendWindowsData) — no extra fetch. Global: reached from an inline onclick.
    function enlargeTrend(wi, ti) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const d = _trendWindowsData;
      const w = d && d.windows && d.windows[wi];
      const x = w && (w.terms || [])[ti];
      if (!x || !Array.isArray(x.series)) return;   // defensive: nothing to enlarge
      const LABELS = {"24h": t("Past 24h"), "7d": t("Past week"), "30d": t("Past month")};
      const title = x.term + " — " + (LABELS[w.label] || w.label);
      const points = x.series.map(p => ({t: p.date, v: p.count}));
      chartEnlarge(title, [{label: x.term, unit: t("mentions"), points}], d.caveat || "");
    }

    // -- ooViz honest lenses over the trending-windows payload (batch F item 2) ---- //
    // A Tufte SLOPE chart + a shared-scale SMALL-MULTIPLES grid, both built from the
    // ooViz primitives (slopeGeometry / gridLayout) over the SAME _trendWindowsData
    // already fetched by loadTrendWindows — no extra request. Additive: the default
    // "Windows" lens is unchanged (the Desk lesson). Honest by construction (invariant
    // #16): shared scales, n shown, bars when sparse, a GAP never zero-filled, no
    // interpolated curve, counts only / no score, caveats visible.
    let _trdLens = "windows";

    // Slope of per-day mention RATE across the preset windows (24h · week · month).
    // RATE = count ÷ window length, so the three nested windows are on a comparable
    // magnitude (a raw count would trivially grow with span). A term missing from a
    // window's rising set is absence, NOT zero — so its line BREAKS there (a gap).
    function _slopeFromTrendWindows(d) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const windows = (d && d.windows) || [];
      const DAYS = {"24h": 1, "7d": 7, "30d": 30};
      const LAB = {"24h": t("Past 24h"), "7d": t("Past week"), "30d": t("Past month")};
      const order = ["24h", "7d", "30d"].filter(lab => windows.some(w => w.label === lab));
      if (order.length < 2) return null;
      const byTerm = {};
      windows.forEach(w => {
        if (!(w.label in DAYS)) return;
        (w.terms || []).forEach(x => {
          if (!byTerm[x.term]) byTerm[x.term] = {term: x.term, x, rates: {}};
          byTerm[x.term].rates[w.label] = (x.recent || 0) / DAYS[w.label];
        });
      });
      const rank = tm => tm.rates[order[0]] != null ? tm.rates[order[0]] : (tm.rates[order[order.length - 1]] || 0);
      const terms = Object.values(byTerm).sort((a, b) => rank(b) - rank(a));
      return {
        stages: order.map(lab => LAB[lab] || lab),
        series: terms.map(tm => ({
          label: tm.term,
          values: order.map(lab => lab in tm.rates ? +tm.rates[lab].toFixed(2) : null),
        })),
      };
    }

    // Render a slope chart from series aligned to ordered stages. Colour encodes
    // DIRECTION (rising=--ok / falling=--err / flat=--muted — the same honest
    // convention as dashChartSvg); each line is direct-labelled at its endpoint (no
    // colour legend needed) and deep-links to that term's analysis window. Capped
    // with the drop DISCLOSED (never silent). Built on ooViz.slopeGeometry.
    const _SLOPE_MAX = 10;
    function slopeChartSvg(spec) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ooViz === "undefined" || !ooViz.slopeGeometry) return "";
      const stages = spec.stages || [];
      let series = (spec.series || []).filter(s => (s.values || []).some(v => v != null && isFinite(v)));
      if (!series.length || stages.length < 2) return `<div class="muted">${esc(t("Not enough data to compare yet."))}</div>`;
      const dropped = Math.max(0, series.length - _SLOPE_MAX);
      series = series.slice(0, _SLOPE_MAX);
      const W = 360, H = Math.max(190, 46 + series.length * 13), pad = {l: 8, r: 104, t: 16, b: 24};
      const g = ooViz.slopeGeometry(series, {stages, width: W, height: H, pad});
      const grid = g.yTicks.map(tk =>
        `<line x1="${pad.l}" x2="${(W - pad.r).toFixed(1)}" y1="${tk.y.toFixed(1)}" y2="${tk.y.toFixed(1)}" stroke="var(--border)" stroke-dasharray="2 4" stroke-width="0.6"/>`
        + `<text x="${pad.l}" y="${(tk.y - 1.5).toFixed(1)}" font-size="8" fill="var(--muted)">${fmtNum(tk.value)}</text>`).join("");
      const xlab = g.stages.map((st, ix) =>
        `<line x1="${st.x.toFixed(1)}" x2="${st.x.toFixed(1)}" y1="${pad.t}" y2="${(H - pad.b).toFixed(1)}" stroke="var(--border-soft)" stroke-width="1"/>`
        + `<text x="${st.x.toFixed(1)}" y="${(H - pad.b + 12).toFixed(1)}" text-anchor="${ix === 0 ? "start" : ix === g.stages.length - 1 ? "end" : "middle"}" font-size="9" fill="var(--muted)">${esc(st.label)}</text>`).join("");
      const lines = g.series.map(se => {
        const finite = se.points.filter(p => !p.missing);
        if (!finite.length) return "";
        const first = finite[0].value, last = finite[finite.length - 1].value;
        const col = last > first ? "var(--ok)" : last < first ? "var(--err)" : "var(--muted)";
        let segs = "";
        for (let i = 0; i < se.points.length - 1; i++) {
          const a = se.points[i], b = se.points[i + 1];
          if (a.missing || b.missing) continue;   // break at gaps, never bridge
          segs += `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${col}" stroke-width="1.6" opacity="0.85"/>`;
        }
        const dots = finite.map(p => `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.6" fill="${col}"><title>${esc(se.label)}: ${fmtNum(p.value)}</title></circle>`).join("");
        const lp = finite[finite.length - 1];
        const lbl = `<text x="${(lp.x + 5).toFixed(1)}" y="${(lp.y + 3).toFixed(1)}" font-size="9" fill="var(--fg)" style="cursor:pointer" onclick='openAnalysisFor(${esc(JSON.stringify(se.label))});return false'>${esc(se.label)}</text>`;
        return segs + dots + lbl;
      }).join("");
      const legend = `<div class="hint" style="margin-top:2px"><span style="color:var(--ok)">▲</span> ${esc(t("rising"))} · <span style="color:var(--err)">▼</span> ${esc(t("falling"))}`
        + (dropped ? ` · <span class="muted">${esc(t("+ {n} more (not shown)").replace("{n}", dropped))}</span>` : "") + `</div>`;
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(spec.aria || t("Slope chart"))}" style="max-width:${W}px;height:auto">${grid}${xlab}${lines}</svg>${legend}`
        + (spec.caveat ? `<div class="card-caveat" style="margin-top:3px">${esc(spec.caveat)}</div>` : "");
    }

    // Shared-scale SMALL-MULTIPLES grid: N mini time-series panels on ONE common
    // vertical scale (0..sharedMax) so panels are directly comparable — the whole
    // point of small multiples. Each panel renders honestly (line when dense, bars
    // when sparse per invariant #16, n shown) and never interpolates a curve; counts
    // anchor at their true zero. Panels deep-link to their analysis window. Column
    // count from ooViz.gridLayout.
    function smallMultiplesSvg(panels, opts) {
      opts = opts || {};
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ooViz === "undefined" || !ooViz.gridLayout) return "";
      const all = panels || [];
      const live = all.filter(p => (p.points || []).some(pt => !_missing(pt && pt.count)));
      // Panels with nothing to plot were dropped SILENTLY, so a grid of 4 out of 9
      // read as "these are the nine". Its sibling slopeChartSvg already discloses
      // what it left out; this now does too.
      const emptied = all.length - live.length;
      if (!live.length) return `<div class="muted">${esc(t("No series to show yet."))}</div>`;
      let maxV = 0;
      // _missing rather than isFinite, for ONE predicate across the function --
      // NOT because the old scan was wrong. isFinite(null) is true, but the guard
      // was `isFinite(pt.count) && pt.count > maxV`, and `null > maxV` coerces to
      // `0 > maxV`, which cannot raise a scale that starts at 0. The shared max was
      // never corrupted; an earlier draft of this comment claimed it was, which an
      // adversarial pass correctly refuted. The real damage was downstream, where
      // Y(null) lands on the baseline.
      live.forEach(p => p.points.forEach(pt => {
        if (!_missing(pt.count) && pt.count > maxV) maxV = pt.count;
      }));
      maxV = Math.max(1, maxV);
      const lay = ooViz.gridLayout(live.length, {maxCols: opts.maxCols || 4});
      const w = 200, h = 84, padL = 6, padR = 6, padT = 8, padB = 16;
      const cell = (p) => {
        const pts = p.points, n = pts.length;
        // TWO counts, deliberately. Geometry spans every SLOT so a hole keeps its
        // width instead of closing up; the sparse threshold and the displayed n
        // count only REAL observations, because "n=30" over a series with 25 gaps
        // claims evidence that was never collected.
        const nReal = pts.filter(pt => !_missing(pt.count)).length;
        const lineMode = nReal >= _SPARSE_BAR_MAX;
        const plotW = w - padL - padR;
        const X = i => padL + plotW * (n < 2 ? 0.5 : i / (n - 1));
        const Y = v => padT + (h - padT - padB) * (1 - v / maxV);   // SHARED 0..maxV
        const baseY = Y(0);
        // Direction is read from the first and last REAL observations. `null >= x`
        // coerces to 0, so a gap at either end used to decide the colour.
        const real = pts.filter(pt => !_missing(pt.count));
        const up = real.length ? real[real.length - 1].count >= real[0].count : true;
        // A corpus count is NEUTRAL: fewer articles in a language is not "bad", so
        // it must not be painted in market up=green/down=red. Same rule and same
        // opt-in as dashChartSvg's; the trending caller keeps the directional colour.
        const col = opts.neutral ? "var(--accent)" : (up ? "var(--ok)" : "var(--err)");
        const slot = plotW / Math.max(n, 1), bw = Math.max(2, Math.min(slot * 0.6, 14));
        const body = lineMode
          // A HOLE IS DRAWN AS A HOLE. This renderer was missed by the honest-gaps
          // pass that fixed dashChartSvg and ooChart: one unbroken <polyline> over
          // every point bridged any gap, and Y(null) evaluates to the zero baseline,
          // so a period with no data was published as a measured zero. Index axis,
          // so a run breaks only on a missing VALUE (there is no cadence to compare).
          ? _seriesRuns(pts, {value: pt => pt.count}).map(run =>
              run.length === 1
                // A single surviving point between two holes has no line to draw;
                // a dot keeps it visible instead of vanishing.
                ? `<circle cx="${X(run[0]).toFixed(1)}" cy="${Y(pts[run[0]].count).toFixed(1)}" r="1.6" fill="${col}"/>`
                : `<polyline fill="none" stroke="${col}" stroke-width="1.4" points="${run.map(i => `${X(i).toFixed(1)},${Y(pts[i].count).toFixed(1)}`).join(" ")}"/>`
            ).join("")
          : pts.map((pt, i) => {
              if (_missing(pt.count)) return "";   // no bar for a gap, never a zero-height one
              const cx = X(i), by = Y(pt.count), x0 = Math.max(padL, cx - bw / 2);
              const bwc = Math.max(1, Math.min(w - padR, cx + bw / 2) - x0).toFixed(1);
              const hgt = Math.max(0, baseY - by);
              // A MEASURED ZERO IS NOT NOTHING. Without this cap a real 0 renders as
              // height="0.0" -- pixel-identical to the gap that emits no rect at all,
              // so the distinction the line above insists on would be invisible in the
              // only mode this renderer actually reaches. Same 2px value-cap
              // dashChartSvg uses to keep a flush-minimum bar visible; it marks the
              // true value and never invents height.
              return `<rect x="${x0.toFixed(1)}" y="${by.toFixed(1)}" width="${bwc}" height="${hgt.toFixed(1)}" fill="${col}" opacity="0.72"/>`
                + (hgt < 2 ? `<rect x="${x0.toFixed(1)}" y="${(by - 1).toFixed(1)}" width="${bwc}" height="2" fill="${col}"/>` : "");
            }).join("");
        const gr = `<line x1="${padL}" x2="${w - padR}" y1="${Y(maxV).toFixed(1)}" y2="${Y(maxV).toFixed(1)}" stroke="var(--border)" stroke-dasharray="2 3" stroke-width="0.5"/>`
          + `<line x1="${padL}" x2="${w - padR}" y1="${baseY.toFixed(1)}" y2="${baseY.toFixed(1)}" stroke="var(--border)" stroke-width="0.5"/>`;
        const svg = `<svg viewBox="0 0 ${w} ${h}" width="100%" role="img" aria-label="${esc((p.label || "") + " — n=" + nReal + (nReal < n ? " (" + (n - nReal) + " gaps)" : ""))}" style="display:block">${gr}${body}</svg>`;
        const oc = p.term != null ? `onclick='openAnalysisFor(${esc(JSON.stringify(p.term))});return false'` : "";
        const head = `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:4px">`
          + `<a href="#" ${oc} title="${esc(t("Open this keyword's own analysis window"))}" style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.label || "")}</a>`
          + `<span class="muted" style="font-size:10px"${nReal < n ? ` title="${esc(t("Periods with no data are drawn as gaps, never as zero."))}"` : ""}>n=${nReal}${nReal < n ? " · " + (n - nReal) + "\u00a0◦" : ""}</span></div>`;
        return `<div style="border:1px solid var(--border);border-radius:6px;padding:5px">${head}${svg}</div>`;
      };
      // Asserted ONLY when a gap is actually present. The single shipped caller
      // (renderTrendMultiples) feeds _window_daily_series, which OMITS zero-count
      // days rather than publishing them as null, so no hole ever reaches this
      // renderer from it -- and a caveat that advertises gap handling on data that
      // cannot contain a gap is a fabricated assurance, the exact class of claim
      // this function was just fixed to stop making. The handling below is real and
      // tested; it is simply not exercised by today's caller, so it is not claimed.
      const anyGap = live.some(p => p.points.some(pt => _missing(pt && pt.count)));
      const cav = `<div class="card-caveat" style="margin-top:5px">${esc(opts.caveat || t("All panels share one vertical scale so they are comparable — a line when dense, bars when sparse (n shown), never an interpolated curve; counts only, no score."))}`
        + `${anyGap ? " " + esc(t("Periods with no data are drawn as gaps, never as zero.")) : ""}`
        + ` ${esc(t("Shared max:"))} ${esc(fmtNum(maxV))}`
        + `${emptied ? " · " + esc(t("Panels with no data, not shown: {n}").replace("{n}", emptied)) : ""}</div>`;
      return `<div style="display:grid;grid-template-columns:repeat(${lay.cols},minmax(0,1fr));gap:8px">${live.map(cell).join("")}</div>${cav}`;
    }

    function renderTrendSlope() {
      const box = $("trd-slope"); if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!_trendWindowsData) { box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`; return; }
      const spec = _slopeFromTrendWindows(_trendWindowsData);
      if (!spec) { box.innerHTML = `<div class="muted">${esc(t("Not enough windows to compare yet."))}</div>`; return; }
      box.innerHTML = `<h2 style="font-size:13px">${esc(t("Mention rate across windows"))}</h2>`
        + slopeChartSvg({
            stages: spec.stages, series: spec.series,
            aria: t("Mentions per day across the preset windows, one line per rising term"),
            caveat: t("Mentions per day in each window (count ÷ window length); the windows are nested. A term missing from a window's rising set shows as a gap, never zero. Counts only, no score."),
          });
    }
    function renderTrendMultiples() {
      const box = $("trd-multiples"); if (!box) return;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (!_trendWindowsData) { box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`; return; }
      const windows = _trendWindowsData.windows || [];
      const wk = windows.find(w => w.label === "7d") || windows[0];
      const terms = ((wk && wk.terms) || []).filter(x => Array.isArray(x.series));
      if (!terms.length) { box.innerHTML = `<div class="muted">${esc(t("No rising keywords with a series yet."))}</div>`; return; }
      const LAB = {"24h": t("Past 24h"), "7d": t("Past week"), "30d": t("Past month")};
      const panels = terms.map(x => ({label: x.term, term: x.term, points: x.series.map(p => ({date: p.date, count: p.count}))}));
      box.innerHTML = `<h2 style="font-size:13px">${esc(t("Small multiples"))} — ${esc(LAB[wk.label] || wk.label)}</h2>` + smallMultiplesSvg(panels, {});
    }
    // Switch the Trends chart lens (Windows / Rate slope / Small multiples). All three
    // read the SAME _trendWindowsData (already fetched); no extra request. Global —
    // reached from the inline onclick, matching the Trends subtab's local convention.
    function setTrendLens(which) {
      _trdLens = (which === "slope" || which === "multiples") ? which : "windows";
      const winOn = _trdLens === "windows";
      const set = (id, on) => { const e = $(id); if (e) e.style.display = on ? "" : "none"; };
      set("trd-windows", winOn); set("trd-windows-note", winOn);
      set("trd-slope", _trdLens === "slope"); set("trd-multiples", _trdLens === "multiples");
      document.querySelectorAll("#trd-lens [data-trdlens]").forEach(b => {
        const on = b.dataset.trdlens === _trdLens;
        b.setAttribute("aria-pressed", on ? "true" : "false");
        b.style.borderColor = on ? "var(--accent)" : "";
        b.style.color = on ? "var(--accent)" : "";
      });
      if (_trdLens === "slope") renderTrendSlope();
      else if (_trdLens === "multiples") renderTrendMultiples();
    }

    // Reusable interactive-chart enlarge dialog (Item 1, Group E). Renders the
    // given ooChart series into the modal <dialog> (native showModal traps focus,
    // OO-D13-001). The caveat shows VISIBLE by default (informed consent). ooChart
    // is drawn AFTER showModal so the dialog has layout width for the canvas.
    function chartEnlarge(title, seriesList, caveat, opts) {
      opts = opts || {};
      const dlg = $("chart-enlarge"); if (!dlg) return;
      const ttl = $("chart-enlarge-title"); if (ttl) ttl.textContent = title || "";
      const note = $("chart-enlarge-note");
      if (note) { note.textContent = caveat || ""; note.style.display = caveat ? "" : "none"; }
      const body = $("chart-enlarge-body"); if (!body) return;
      body.innerHTML = "";
      if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
      if (opts.scales) {
        // Scale controls (maintainer markets revamp Slice 3: "change the graph
        // scales"): Absolute (raw values) ↔ Indexed (rebase each series to 100 at
        // the window start, so different-magnitude series co-move WITHOUT
        // conflating magnitudes) ↔ Log (log10 y-axis). Re-renders the SAME ooChart
        // with the proven opts.indexed / opts.logY (the hover always shows the REAL
        // value). One shared #chart-enlarge dialog — no new modal DOM.
        const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((x) => x);
        const SCALES = [["absolute", "Absolute"], ["indexed", "Indexed (=100)"], ["log", "Log"]];
        let mode = "absolute";
        // Offering a mode the chart will refuse puts two statements on screen at once: the
        // hint claiming "Log scale (base 10) — equal ratios are equal distances" above a
        // chart that drew a linear axis and says so underneath. ooChart's refusal is the
        // load-bearing guard (it cannot be bypassed); this stops the contradiction from
        // being reachable, and states the reason on the control itself rather than only
        // after the reader has clicked it.
        const logPossible = seriesList.every(
          s => (s.points || []).every(p => p.v != null && +p.v > 0));
        const ctl = document.createElement("div");
        ctl.className = "mkt-scalerow";
        ctl.innerHTML = `<span class="muted" style="font-size:12px;margin-right:2px">${esc(t9("Scale"))}:</span>`
          + SCALES.map(([k, lbl]) => {
              const off = k === "log" && !logPossible;
              return `<button type="button" class="chip${k === mode ? " on" : ""}" data-scale="${k}"`
                + (off ? ` disabled title="${esc(t9("A log axis cannot place a zero, and this data has some."))}"` : "")
                + `>${esc(t9(lbl))}</button>`;
            }).join("");
        const hint = document.createElement("div");
        hint.className = "hint muted"; hint.style.cssText = "font-size:11.5px;margin:2px 0 4px";
        const host = document.createElement("div");
        body.appendChild(ctl); body.appendChild(hint); body.appendChild(host);
        const HINTS = {
          absolute: t9("Raw values on a shared time axis — series of very different magnitudes may flatten."),
          indexed: t9("Each series rebased to 100 at the window start — relative moves, not absolute levels."),
          log: t9("Log scale (base 10) — equal ratios are equal distances; the hover shows the real value."),
        };
        const render = () => {
          hint.textContent = HINTS[mode] || "";
          // mkt-002-stale-caveat-scale-toggle (P1): the note was set once above from
          // the caller's `caveat`, and for the Commodities family view that caveat IS
          // a per-mode statement ("Indexed to 100 at the window start…"), so it never
          // refreshed on a scale-toggle click and ended up contradicting the accurate
          // hint just above it. The fix mirrored HINTS into the note — which cured the
          // contradiction and silently DISCARDED every caller's caveat, because
          // HINTS[mode] is non-empty for all three modes and `|| caveat` was therefore
          // dead code. Two mode-INDEPENDENT caveats were lost that way: the
          // qualification tile's "counts only, never a quality score / awaiting a
          // verdict does not mean untried" and the index comparison's provenance line.
          // Found by opening the modal in a browser and reading its last line.
          //
          // So the two statements now live in the two slots they belong to: the mode
          // text in `hint`, which tracks the mode, and the caller's caveat in `note`,
          // which does not depend on it. A caller whose caveat is a MODE statement must
          // pass none — HINTS already says it (the Commodities caller does exactly that
          // and keeps its inline .card-caveat for the un-enlarged view).
          if (note) { note.textContent = caveat || ""; note.style.display = caveat ? "" : "none"; }
          ooChart(host, seriesList, {height: 360, maxWidth: 880, indexed: mode === "indexed", logY: mode === "log"});
        };
        ctl.addEventListener("click", (e) => {
          const b = e.target.closest("[data-scale]"); if (!b || b.disabled) return;
          mode = b.dataset.scale;
          ctl.querySelectorAll("[data-scale]").forEach(x => x.classList.toggle("on", x.dataset.scale === mode));
          render();
        });
        render();
        _chartEnlargeExtra(body, opts);
        return;
      }
      ooChart(body, seriesList, {height: 360, maxWidth: 880});
      _chartEnlargeExtra(body, opts);
    }
    // Optional extra content appended below the enlarged chart (P2-10: the
    // per-symbol price detail routes here and adds its "Correlate with news"
    // control). opts.extra is an HTML string; opts.onReady(body) wires it up.
    function _chartEnlargeExtra(body, opts) {
      if (opts && opts.extra) {
        const wrap = document.createElement("div");
        wrap.innerHTML = opts.extra;
        body.appendChild(wrap);
      }
      if (opts && typeof opts.onReady === "function") opts.onReady(body);
    }

    // World map: equirectangular projection, viewBox-based zoom/pan (no deps).
