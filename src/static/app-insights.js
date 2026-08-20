/* app-insights.js — Insights

   Families, the concept browse, super-groups, the keyword explorer, cited sources,
   convergences and watches, plus the trend windowing they share.

   PART OF THE UI ENGINE. src/static/app.js was decomposed into ordered modules
   (structural debt S-3; docs/design/APPJS_DECOMPOSITION_2026-08-20.md). They share
   ONE global scope -- there is no module system here, and 413 globals are named by
   inline on*= handlers that can resolve against nothing else -- and they load in the
   order index.html lists them, with app-boot.js last.

   The split was a pure CONTIGUOUS slice, verified at the split commit by
   concatenating the modules in load order and reproducing the pre-split file byte
   for byte. That check is spent now (these files are edited normally), but the rule
   it rested on still holds: DO NOT reorder a declaration across a module boundary.
   Function declarations would survive it, because they hoist; a const or let would
   not, and the failure is a TDZ error at load rather than anything a reader would
   spot in review. Add new code inside the module it belongs to.
*/
    function _trendBucketMs(key) {
      const wk = /^(\d{4})-W(\d{2})$/.exec(key);   // ISO week -> its Monday (UTC)
      if (wk) {
        const jan4 = Date.UTC(+wk[1], 0, 4);
        const dow = (new Date(jan4).getUTCDay() + 6) % 7;
        return jan4 - dow * 864e5 + (+wk[2] - 1) * 7 * 864e5;
      }
      if (/^\d{4}-\d{2}$/.test(key)) return Date.parse(key + "-01");
      return Date.parse(key);
    }
    function _trendBucketIso(key) {
      const ms = _trendBucketMs(key);
      return isFinite(ms) ? new Date(ms).toISOString().slice(0, 10) : null;
    }
    // Span (oldest -> newest bucket) as ISO dates, to bound the ooTimeScope.
    function _trendSpan(points) {
      let min = null, max = null;
      for (const p of (points || [])) {
        const iso = _trendBucketIso(p.date);
        if (!iso) continue;
        if (min === null || iso < min) min = iso;
        if (max === null || iso > max) max = iso;
      }
      return {min, max};
    }
    // Keep only buckets whose start falls in [from,to] (ISO YYYY-MM-DD); the
    // points keep their original resolution — no downsampling, ever.
    function _windowTrendPoints(points, from, to) {
      if (!from && !to) return points || [];
      const fromMs = from ? Date.parse(from) : -Infinity;
      const toMs = to ? Date.parse(to) : Infinity;
      return (points || []).filter(p => {
        const ms = _trendBucketMs(p.date);
        return isFinite(ms) && ms >= fromMs && ms <= toMs;
      });
    }
    // Default window = the last 1 year anchored to the data's MAX (never "now"),
    // or the whole span if it covers less than a year — mirrors mktDefaultWindow.
    function _trendDefaultWindow(span) {
      if (!span.min || !span.max) return {from: span.min, to: span.max};
      const maxD = new Date(span.max + "T00:00:00Z");
      const yearAgo = new Date(maxD); yearAgo.setUTCFullYear(maxD.getUTCFullYear() - 1);
      const from = yearAgo.toISOString().slice(0, 10);
      return {from: from > span.min ? from : span.min, to: span.max};
    }
    // Build (or rebuild) an ooTimeScope over a trend point series in `box`.
    // `redraw(windowedPoints)` re-renders the chart from the CLIENT-FILTERED
    // full-resolution points (invariant #16 — never downsampled/thinned; the
    // existing ooChart renderer is handed the windowed points unchanged).
    // ooTimeScope itself degrades loudly ("not enough data for a time range")
    // when the span is unusable. Returns the initial {from,to} so the caller's
    // first paint matches the control.
    function _buildTrendScope(box, points, redraw) {
      if (!box) return {from: null, to: null};
      const span = _trendSpan(points);
      if (!span.min || !span.max || span.min === span.max) {
        ooTimeScope(box, {});           // honest "not enough data" message
        return {from: null, to: null};  // caller paints the full (tiny) series
      }
      const def = _trendDefaultWindow(span);
      ooTimeScope(box, {
        min: span.min, max: span.max, from: def.from, to: def.to,
        onChange: ({from, to}) => redraw(_windowTrendPoints(points, from, to)),
      });
      return def;
    }

    let _insSubtabs = null, _setSubtabs = null, _corpusSubtabs = null;

    // -- Insights (keyword & entity analytics) ------------------------------ //
    const _insLoaded = new Set();

    function showInsightCat(cat) {
      // Button/ARIA state is owned by the ooSubtabs component (universal grammar);
      // this callback only switches the panel + lazy-loads the section once.
      document.querySelectorAll("#tab-insights .ins-view").forEach(v =>
        v.style.display = (v.id === "ins-" + cat) ? "" : "none");
      if (!_insLoaded.has(cat)) {
        _insLoaded.add(cat);
        if (cat === "trends") loadTrends();
        if (cat === "map") loadMap();
        if (cat === "sources") loadCitedSources();
        if (cat === "families") loadFamilies();
        if (cat === "supergroups") loadSuperGroups();
        if (cat === "convergence") loadConvergences();
        if (cat === "watches") loadWatches();
        if (cat === "lunar") loadLunar();
      }
    }

    // -- Corpus landscape: super-families by semantic kind (the "zoom out") --- //
    const _KIND_GROUPS = [
      {key: "person",   label: "People",  match: k => k === "person"},
      {key: "org",      label: "Orgs",    match: k => k === "org"},
      {key: "location", label: "Places",  match: k => k === "location"},
      {key: "entity",   label: "Other entities", match: k => !["person", "org", "location", "term"].includes(k)},
      {key: "term",     label: "Themes",  match: k => k === "term"},
    ];
    let _landscapeLoaded = false;
    async function loadLandscape(force) {
      if (_landscapeLoaded && !force) return;
      // insights-landscape-headers-hardcoded (P1): _KIND_GROUPS' labels
      // (People/Orgs/Places/Other entities/Themes) were injected with no t()
      // wrapper anywhere below, so they stayed hardcoded English regardless of
      // the active UI language.
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("ins-landscape");
      box.innerHTML = '<div class="muted" style="margin-top:8px">Loading…</div>';
      try {
        const d = await api("/api/insights/top?group=true&limit=200" + tgtLangParam());
        _landscapeLoaded = true;
        const fams = d.terms || [];
        if (!fams.length) { box.innerHTML = '<div class="muted" style="margin-top:8px">No families yet — index the corpus.</div>'; return; }
        const cols = _KIND_GROUPS.map(g => {
          const items = fams.filter(f => g.match(f.kind)).slice(0, 16);
          if (!items.length) return "";
          const max = Math.max(...items.map(f => f.mentions), 1);
          const chips = items.map(f => {
            const scale = 0.82 + 0.5 * (f.mentions / max);     // size by prominence
            const fam = f.variants > 1;
            return `<button class="ls-chip" style="font-size:${(11.5*scale).toFixed(1)}px"
              title="${fam ? `family of ${f.variants}: ${esc((f.members||[]).map(m=>m.term).join(', '))} · ` : ""}${f.mentions} mentions — click to zoom in"
              onclick="pickTerm(${esc(JSON.stringify(f.term))})">${esc(f.term)}${kwTransHtml(f)}${fam ? `<span class="muted"> ·${f.variants}</span>` : ""}</button>`;
          }).join("");
          return `<div class="ls-col"><div class="ls-h">${esc(t(g.label))} <span class="muted">${items.length}</span></div><div class="ls-chips">${chips}</div></div>`;
        }).join("");
        box.innerHTML = `<div class="ls-grid">${cols}</div>`;
      } catch (e) { box.innerHTML = `<div class="muted" style="margin-top:8px">Could not load: ${esc(e.message)}</div>`; }
    }

    // -- Keyword families: Insights DATA VIEW (read-only; invariant #8 content-first) -- //
    // 2026-07-18 field fix: curation (merge/split/overrides) relocated to Settings ->
    // Keywords (loadFamilyCuration below) -- this view shows the grouped data only, no
    // plumbing (checkboxes/Merge/✕ chips). Nothing lost: every control still exists there.
    function _famMemberList(f) {
      return (f.members || []).map(m => esc(m.term)).join(", ");
    }

    async function loadFamilies() {
      const list = $("fam-list");
      list.innerHTML = '<div class="muted">Loading…</div>';
      const kind = $("fam-kind").value;
      try {
        // 2026-07-18 field fix (§0 row 1): the kind filter is applied SERVER-SIDE, before
        // the limit -- `kind` here is always "entity" or "non_term" (never blank), so the
        // response already contains only non-term rows. NO client-side re-filter: a
        // filter-after-limit trim is exactly the bug this replaces (it silently starved
        // the entity view down to whatever stray rows survived a term-dominated top-N).
        const top = await api(`/api/insights/top?group=true&limit=80&kind=${encodeURIComponent(kind)}` + tgtLangParam());
        const fams = top.terms || [];
        list.innerHTML = fams.length ? fams.map(f => `<div class="fam-row">
            <div class="fam-body"><div><b>${esc(f.term)}</b>${kwTransHtml(f)} <span class="pill">${esc(f.kind)}</span>
              ${f.manual ? '<span class="pill ok">manual</span>' : ""}
              ${f.ring_id ? `<button class="pill lvl-group" title="${esc(lvlTitle("group"))}" onclick="openConceptMap(${esc(JSON.stringify(f.ring_id))})">group</button>` : ""}
              <span class="muted">· ${f.mentions} mentions</span></div>
              <div class="fam-chips muted">${_famMemberList(f)}</div></div></div>`
          ).join("") : '<div class="muted">No entity families yet — index the corpus first.</div>';
      } catch (e) { list.innerHTML = `<div class="muted">Could not load families: ${esc(e.message)}</div>`; }
    }

    // -- Settings -> Keywords: entity family CURATION (merge/split; relocated 2026-07-18) -- //
    // Only rows where a DECISION exists are shown: multi-member (variants>1), a group merge
    // (ring_id), or a family carrying a manual override -- never thousands of single-member
    // rows with nothing to do (§0 row 6).
    async function loadFamilyCuration() {
      const list = $("famc-list");
      if (!list) return;
      list.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const [top, ov] = await Promise.all([
          api(`/api/insights/top?group=true&limit=200&kind=non_term` + tgtLangParam()),
          api("/api/insights/family/overrides"),
        ]);
        const overridden = new Set((ov.families || []).flatMap(f => f.members || []));
        const fams = (top.terms || []).filter(f =>
          f.variants > 1 || f.ring_id || f.manual ||
          (f.members || []).some(m => overridden.has(m.normalized)));
        list.innerHTML = fams.length ? fams.map(f => {
          const norms = JSON.stringify((f.members || []).map(m => m.normalized));
          const single = (f.members || []).length <= 1;
          const chips = (f.members || []).map(m =>
            `<button class="fam-chip" data-norm="${esc(m.normalized)}" data-kind="${esc(f.kind)}"
               data-single="${single ? "1" : "0"}"
               onclick="familySplit(this)"
               title="${single ? "nothing to split -- this family has only one member" : "split this form out"}"
               >${esc(m.term)}${single ? "" : " ✕"}</button>`).join("");
          // S3 (2026-07-18 default-on brief, conservative + browser-unverified per fork-3/Q6a):
          // a family collapsed in part by lemmatization (families.py conflated_by=["lemma"])
          // carries a small, honest marker -- reversible via the split control above, never a score.
          const lemmaTag = (f.conflated_by || []).includes("lemma")
            ? '<span class="pill" title="This grouping merges a form via lemmatization (e.g. study/studied). Split any member out above if a merge looks wrong.">conflated by lemma</span>'
            : "";
          return `<div class="fam-row">
            <input type="checkbox" class="fam-pick" data-norms="${esc(norms)}" data-kind="${esc(f.kind)}" data-label="${esc(f.term)}" aria-label="${esc(f.term)}">
            <div class="fam-body"><div><b>${esc(f.term)}</b>${kwTransHtml(f)} <span class="pill">${esc(f.kind)}</span>
              ${f.manual ? '<span class="pill ok">manual</span>' : ""}
              ${f.ring_id ? `<button class="pill lvl-group" title="${esc(lvlTitle("group"))}" onclick="openConceptMap(${esc(JSON.stringify(f.ring_id))})">group</button>` : ""}
              ${lemmaTag}
              <span class="muted">· ${f.mentions} mentions</span></div>
              <div class="fam-chips">${chips}</div></div></div>`;
        }).join("") : '<div class="muted">No families with a decision to review — grouping is fully automatic so far.</div>';
        renderFamOverrides(ov);
      } catch (e) { list.innerHTML = `<div class="muted">Could not load families: ${esc(e.message)}</div>`; }
    }

    function renderFamOverrides(ov) {
      const box = $("fam-overrides");
      if (!box) return;
      if (!ov.families || !ov.families.length) { box.innerHTML = ""; return; }
      box.innerHTML = `<h2 style="font-size:13px;margin:0 0 6px">Your manual overrides</h2>` +
        ov.families.map(f => `<div class="fam-ov">
          <span>${f.split ? "split" : "merge"}: <b>${esc(f.label || f.family_key)}</b>
            <span class="muted">${esc((f.members || []).join(", "))}</span></span>
          <button class="ghost tiny" data-members="${esc(JSON.stringify(f.members || []))}" onclick="familyResetGroup(this)">reset</button>
        </div>`).join("");
    }

    async function familySplit(btn) {
      if (btn.dataset.single === "1") {
        toast("Nothing to split — this family has only one member.");
        return;  // guarded no-op (§0 row 7): a single-member family has no meaningful split
      }
      try {
        await api("/api/insights/family/split", {method: "POST",
          body: JSON.stringify({normalized: btn.dataset.norm, kind: btn.dataset.kind})});
        toast("Split out."); loadFamilyCuration();
      } catch (e) { toast(_failMsg("Split failed: {error}", e), "err"); }
    }

    async function familyMerge() {
      const picks = [...document.querySelectorAll(".fam-pick:checked")];
      if (picks.length < 2) { toast("Tick at least two families to merge.", "err"); return; }
      const norms = picks.flatMap(p => JSON.parse(p.dataset.norms));
      const label = prompt("Name for the merged family:", picks[0].dataset.label || "");
      if (label === null) return;
      try {
        const r = await api("/api/insights/family/merge", {method: "POST",
          body: JSON.stringify({normalized: norms, label: label.trim() || undefined, kind: picks[0].dataset.kind})});
        const st = $("famc-status"); if (st) st.textContent = `Merged ${r.merged.length} forms into “${r.label}”.`;
        toast("Merged."); loadFamilyCuration();
      } catch (e) { toast(_failMsg("Merge failed: {error}", e), "err"); }
    }

    async function familyResetGroup(btn) {
      const members = JSON.parse(btn.dataset.members);
      try {
        for (const n of members) await api("/api/insights/family/override?normalized=" + encodeURIComponent(n), {method: "DELETE"});
        toast("Override cleared."); loadFamilyCuration();
      } catch (e) { toast(_failMsg("Reset failed: {error}", e), "err"); }
    }

    // -- Super-groups: groups of families ----------------------------------- //
    // Item #8 (an ooViz technique on a real surface): an honest DUMBBELL of a ring's
    // per-country distinct-ARTICLE spread vs total MENTIONS — the gap is amplification
    // (how many mentions per article), NEVER a fabricated curve. Counts only; built with the
    // ooViz.linearScale + niceTicks primitives (like renderStatMap templates choroplethData).
    // Every country in the payload is drawn, capped at _DUMBBELL_MAX with the drop DISCLOSED
    // (no silent truncation — the honesty rule).
    const _DUMBBELL_MAX = 15;
    function ringDumbbellSvg(rows, names, ringId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      if (typeof ooViz === "undefined" || !ooViz.linearScale || !ooViz.niceTicks) return "";
      const data = (rows || []).filter(r => r.country && ((r.mentions || 0) || (r.articles || 0)))
        .sort((a, b) => (b.mentions || 0) - (a.mentions || 0));
      if (!data.length) return "";
      const shown = data.slice(0, _DUMBBELL_MAX), dropped = data.length - shown.length;
      const maxV = Math.max(1, ...shown.map(r => Math.max(r.mentions || 0, r.articles || 0)));
      const padL = 96, padR = 44, padT = 8, rowH = 22, W = 340;
      const H = padT * 2 + shown.length * rowH + 22;
      const x = ooViz.linearScale(0, maxV, padL, W - padR);
      const grid = ooViz.niceTicks(0, maxV, 4).map(v => {
        const gx = x(v).toFixed(1);
        return `<line x1="${gx}" y1="${padT}" x2="${gx}" y2="${(padT + shown.length * rowH).toFixed(1)}" stroke="var(--border-soft)" stroke-width="1"/>`
          + `<text x="${gx}" y="${(padT + shown.length * rowH + 14).toFixed(1)}" text-anchor="middle" font-size="9" fill="var(--muted)">${esc(String(v))}</text>`;
      }).join("");
      // §D: every bar drills into the exact corpus (group's keyword ids ∩ that
      // country -> article ids), when ringId is supplied.
      const bars = shown.map((r, i) => {
        const cy = (padT + i * rowH + rowH / 2).toFixed(1);
        const xa = x(r.articles || 0), xm = x(r.mentions || 0);
        const lo = Math.min(xa, xm).toFixed(1), hi = Math.max(xa, xm).toFixed(1);
        const nm = esc((names && names[r.country]) || String(r.country).toUpperCase());
        const clickable = ringId
          ? ` style="cursor:pointer" onclick="_conceptDrillCountry('${esc(ringId)}','${esc(r.country)}')"` : "";
        return `<g${clickable}><title>${nm}</title>`
          + `<text x="${padL - 6}" y="${(+cy + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--fg)">${nm}</text>`
          + `<line x1="${lo}" y1="${cy}" x2="${hi}" y2="${cy}" stroke="var(--muted)" stroke-width="2" opacity="0.5"/>`
          + `<circle cx="${xa.toFixed(1)}" cy="${cy}" r="4" fill="var(--accent)"><title>${nm}: ${r.articles} ${esc(t("articles"))}</title></circle>`
          + `<circle cx="${xm.toFixed(1)}" cy="${cy}" r="4" fill="var(--muted)"><title>${nm}: ${r.mentions} ${esc(t("mentions"))}</title></circle></g>`;
      }).join("");
      const legend = `<div class="hint" style="margin-top:2px"><span style="color:var(--accent)">●</span> ${esc(t("articles"))} · <span style="color:var(--muted)">●</span> ${esc(t("mentions"))}`
        + (dropped ? ` · <span class="muted">${esc(t("+ {n} more (not shown)").replace("{n}", dropped))}</span>` : "") + `</div>`;
      return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(t("Per-country articles vs mentions"))}" style="max-width:${W}px;height:auto">${grid}${bars}</svg>${legend}`;
    }
    // Cross-language ring -> per-language mention breakdown, indexed from /top?group=true
    // (best-effort: only rings that fall in the fetched top-N carry a language breakdown).
    let _ringLangIndex = {};

    // -- Concept-map §D: the two-tier circled browse ------------------------------
    // Replaces the flat 540-item <select> with super-group chips (⦾⦾) -> click one
    // -> its member group (ring) chips (⦾) below, an "Ungrouped concepts" bucket so
    // no ring is ever unreachable, and a type-ahead filter. State kept module-level
    // so a refresh (loadSuperGroups) or a deep link (openConceptMap) can re-render
    // without re-fetching.
    let _conceptSupergroups = [], _conceptRings = [];
    let _conceptActiveBucket = null;   // a super-group id, "_ungrouped_", or null
    let _conceptSelectedRing = null;   // the currently-mapped group (ring) id, or null
    let _conceptFilterQ = "";
    let _conceptPendingRing = null;    // openConceptMap's deep-link target, applied once data loads

    function _conceptRingToSupers() {
      // ring_id -> [{id, name}] -- a ring MAY belong to several super-groups; it is
      // shown under every one (plural membership, never silently picking one).
      const idx = {};
      _conceptSupergroups.forEach((sg) => (sg.members || []).forEach((m) => {
        if (!m.ring_id) return;
        (idx[m.ring_id] = idx[m.ring_id] || []).push({ id: sg.id, name: sg.name });
      }));
      return idx;
    }

    function _conceptMatches(label) {
      if (!_conceptFilterQ) return true;
      return (label || "").toLowerCase().includes(_conceptFilterQ);
    }

    function renderConceptBrowse() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const supersHost = $("sg-concept-supers"), groupsHost = $("sg-concept-groups"),
        crumbHost = $("sg-concept-crumb");
      if (!supersHost || !groupsHost) return;
      const ringToSupers = _conceptRingToSupers();
      const groupedRingIds = new Set(Object.keys(ringToSupers));
      const ungrouped = _conceptRings.filter((r) => !groupedRingIds.has(r.id));

      // Tier 1: every super-group, plus a synthetic "Ungrouped concepts" bucket
      // (only when at least one ring has no super-group parent).
      const superChips = _conceptSupergroups
        .filter((sg) => _conceptMatches(sg.name))
        .map((sg) => `<button class="chip lvl-super${_conceptActiveBucket === sg.id ? " active" : ""}"
           onclick="selectConceptBucket(${sg.id})" title="${esc(lvlTitle("super"))}">⦾⦾ ${esc(sg.name)}</button>`)
        .join(" ");
      const ungroupedChip = ungrouped.length && _conceptMatches(t("Ungrouped concepts"))
        ? `<button class="chip${_conceptActiveBucket === "_ungrouped_" ? " active" : ""}"
             onclick="selectConceptBucket('_ungrouped_')">${esc(t("Ungrouped concepts"))} <span class="muted">${ungrouped.length}</span></button>`
        : "";
      supersHost.innerHTML = (superChips || ungroupedChip)
        ? superChips + (ungroupedChip ? " " + ungroupedChip : "")
        : `<div class="muted">${esc(t("No super-groups yet."))}</div>`;

      // Tier 2: the active bucket's group (ring) chips.
      let members = [];
      if (_conceptActiveBucket === "_ungrouped_") members = ungrouped;
      else if (_conceptActiveBucket) {
        const sg = _conceptSupergroups.find((s) => s.id === _conceptActiveBucket);
        const ringIds = new Set((sg && sg.members || []).filter((m) => m.ring_id).map((m) => m.ring_id));
        members = _conceptRings.filter((r) => ringIds.has(r.id));
      }
      groupsHost.innerHTML = members.length
        ? members.filter((r) => _conceptMatches(r.id) || _conceptMatches((r.languages || []).join("/")))
            .map((r) => `<button class="chip lvl-group${_conceptActiveBucket && r.id === _conceptSelectedRing ? " active" : ""}"
               onclick="selectConceptGroup('${esc(r.id)}')" title="${esc(lvlTitle("group"))}">⦾ ${esc(r.id)}
               <span class="muted">(${esc((r.languages || []).join("/"))})</span></button>`).join(" ")
        : (_conceptActiveBucket ? `<div class="muted">${esc(t("No groups in this bucket."))}</div>` : "");

      // The clickable path breadcrumb (reuses the shared component from §B).
      const crumbSegs = [];
      if (_conceptActiveBucket && _conceptActiveBucket !== "_ungrouped_") {
        const sg = _conceptSupergroups.find((s) => s.id === _conceptActiveBucket);
        if (sg) crumbSegs.push({ level: "super", label: sg.name, onClick: () => selectConceptBucket(sg.id) });
      } else if (_conceptActiveBucket === "_ungrouped_") {
        crumbSegs.push({ level: "keyword", label: t("Ungrouped concepts"), onClick: () => selectConceptBucket("_ungrouped_") });
      }
      if (_conceptSelectedRing) crumbSegs.push({ level: "group", label: _conceptSelectedRing, onClick: () => selectConceptGroup(_conceptSelectedRing) });
      if (crumbHost) crumbHost.innerHTML = lvlBreadcrumb(crumbSegs);
    }

    function selectConceptBucket(id) {
      _conceptActiveBucket = id;
      _conceptSelectedRing = null;
      renderConceptBrowse();
    }
    function selectConceptGroup(ringId) {
      _conceptSelectedRing = ringId;
      renderConceptBrowse();
      showRingMap(ringId);
    }
    function filterConceptBrowse(qstr) {
      _conceptFilterQ = (qstr || "").trim().toLowerCase();
      renderConceptBrowse();
    }
    // The deep link every ⦾ group chip in the app can call: jump to Insights ->
    // Groups, land on the right bucket (the ring's FIRST super-group, else the
    // Ungrouped bucket), and open its map -- mirrors openSupergroup's deferred
    // scroll-to-target pattern for when the data hasn't loaded yet.
    function openConceptMap(ringId) {
      _conceptPendingRing = ringId;
      showTab("insights");
      if (_insSubtabs) _insSubtabs.select("supergroups"); else showInsightCat("supergroups");
      if (_insLoaded.has("supergroups")) _conceptApplyPending();
    }
    function _conceptApplyPending() {
      if (!_conceptPendingRing) return;
      const ringId = _conceptPendingRing; _conceptPendingRing = null;
      const ringToSupers = _conceptRingToSupers();
      const parents = ringToSupers[ringId];
      selectConceptBucket(parents && parents.length ? parents[0].id : "_ungrouped_");
      selectConceptGroup(ringId);
      const el = $("sg-ringmap"); if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    // Item #4: render a cross-language ring's coverage on the ooMap component — where the
    // concept is covered (by the producing source's country) + its per-language split.
    // Counts only, no score; unknown country is shown honestly, never mapped or guessed.
    async function showRingMap(ringId) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const host = $("sg-ringmap"), detail = $("sg-ringmap-detail");
      if (!host) return;
      if (!ringId) { host.innerHTML = ""; if (detail) detail.innerHTML = ""; return; }
      host.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      if (detail) detail.innerHTML = "";
      try {
        const d = await api("/api/insights/ring-countries?ring_id=" + encodeURIComponent(ringId));
        if (!d.found) { host.innerHTML = `<div class="muted">${esc(t("No cross-country coverage for this concept yet."))}</div>`; return; }
        const values = {}, names = {}; let unloc = null;
        (d.countries || []).forEach(c => {
          if (!c.country) { unloc = c; return; }            // unlocated bucket — never mapped
          values[c.country] = c.articles;                  // distinct-article spread per country
          names[c.country] = (typeof ooRegionName === "function") ? ooRegionName(c.country, String(c.country).toUpperCase()) : String(c.country).toUpperCase();
        });
        const label = d.label || ringId;
        if (!Object.keys(values).length) {
          host.innerHTML = `<div class="muted">${esc(t("No located sources for this concept yet."))}</div>`;
        } else {
          host.innerHTML = "";
          // §D: every country polygon drills into the exact corpus (this group's
          // keyword ids ∩ that source country -> article ids) via openAnalysisForIds.
          await ooMap(host, {
            values, names, unit: t("articles"),
            valueLabel: (iso, v) => `${v} ${t("articles")}`,
            aria: `${label} — ${Object.keys(values).length} ${t("countries")}`,
            method: d.method || "", caveat: d.caveat || "",
            onCountry: (iso) => _conceptDrillCountry(ringId, iso),
          });
        }
        // Detail: the per-language mention split (from /top?group=true) + unlocated + a table.
        const lb = _ringLangIndex[ringId];
        const langBd = (lb && Object.keys(lb).length)
          ? `<div class="hint" style="margin-top:4px"><b>${esc(t("By language"))}:</b> `
            + Object.entries(lb).sort((a, b) => b[1] - a[1]).map(([lg, n]) =>
                `${esc(lg === "?" ? t("unknown") : lg)} <span class="muted">${n}</span>`).join(" · ")
            + ` <span class="muted">— ${esc(t("mentions per language"))}</span></div>`
          : "";
        const langs = (d.languages || []).length
          ? `<div class="hint"><b>${esc(t("Languages"))}:</b> ${esc((d.languages || []).join(" · "))}</div>` : "";
        // §D: the "not mapped" bucket is CLICKABLE too -- often the largest bucket,
        // and it must be investigable, never a dead end.
        const unlocNote = unloc
          ? `<button class="secondary" style="display:block;width:100%;text-align:left;margin-top:6px" onclick="_conceptDrillCountry('${esc(ringId)}', null)">`
            + `${esc(t("Not mapped (source country unknown)"))}: ${unloc.articles} ${esc(t("articles"))} · ${unloc.mentions} ${esc(t("mentions"))}</button>` : "";
        const rows = (d.countries || []).filter(c => c.country)
          .map(c => `<tr style="cursor:pointer" onclick="_conceptDrillCountry('${esc(ringId)}','${esc(c.country)}')">`
            + `<td>${esc(names[c.country] || c.country)}</td><td style="text-align:right">${c.articles}</td><td style="text-align:right">${c.mentions}</td></tr>`).join("");
        const tbl = rows
          ? `<table style="margin-top:8px"><thead><tr><th>${esc(t("Country"))}</th><th style="text-align:right">${esc(t("Articles"))}</th><th style="text-align:right">${esc(t("Mentions"))}</th></tr></thead><tbody>${rows}</tbody></table>` : "";
        // Item #8: an honest per-country dumbbell (articles vs mentions) above the table.
        const dumb = ringDumbbellSvg((d.countries || []).filter(c => c.country), names, ringId);
        if (detail) detail.innerHTML = langs + langBd + unlocNote + dumb + tbl;
      } catch (e) { host.innerHTML = `<div class="muted">${esc(e && e.message || e)}</div>`; }
    }
    // §D: the shared country-cell drill -- exact article ids behind (ring, country),
    // via the /ring-country-articles endpoint (same keyword resolution as the
    // summary table, so the drilled set can never disagree with the number beside
    // it), opened as a fresh corpus. country===null resolves the "not mapped"
    // bucket, never a silent drop.
    async function _conceptDrillCountry(ringId, country) {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        const d = await api("/api/insights/ring-country-articles?ring_id=" + encodeURIComponent(ringId)
          + (country ? "&country=" + encodeURIComponent(country) : ""));
        if (!d.article_ids || !d.article_ids.length) { toast(t("No articles found for this cell.")); return; }
        const place = country
          ? ((typeof ooRegionName === "function") ? ooRegionName(country, String(country).toUpperCase()) : String(country).toUpperCase())
          : t("not mapped");
        openAnalysisForIds(d.article_ids, `${ringId} · ${place}`);
      } catch (e) { toast(t("Drill failed: ") + (e && e.message || e), "err"); }
    }
    async function loadSuperGroups() {
      const box = $("sg-list");
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        // series_top: only the top-mentioned groups get a windowed rate + sparkline
        // (S1.5, bounded — never all ~77 groups on every load).
        const [sgs, top, rings] = await Promise.all([
          api("/api/insights/supergroups?series_top=12&window_days=7&target_lang=" + encodeURIComponent(uiLangCode())),
          api("/api/insights/top?group=true&limit=200" + tgtLangParam()),
          api("/api/insights/rings"),
        ]);
        // (S5: the add-family/add-ring datalists moved to the Settings curation
        // panel — this data view no longer populates them.)
        // Item #4: index the per-language mention breakdown carried by grouped ring rows,
        // and fill the ring-map picker (kept selection across a refresh).
        _ringLangIndex = {};
        (top.terms || []).forEach(f => { if (f.ring_id && f.language_breakdown) _ringLangIndex[f.ring_id] = f.language_breakdown; });
        // §D: the two-tier circled browse replaces the flat 540-item dropdown --
        // super-group chips (⦾⦾) -> click one -> its group (ring) chips (⦾) below,
        // plus an "Ungrouped concepts" bucket so a ring with no super-group parent
        // stays reachable (never silently dropped from the picker).
        _conceptSupergroups = sgs.supergroups || [];
        _conceptRings = rings.rings || [];
        renderConceptBrowse();
        box.innerHTML = sgs.supergroups.length ? sgs.supergroups.map(sgCard).join("")
          : '<div class="muted">No super-groups yet. Create one above, then add families or groups to it.</div>';
        const bc = $("sg-basis"); if (bc) bc.innerHTML = basisChip(sgs.counts);
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
      _sgScrollToTarget();  // S3: land on the deep-linked group after it renders
      _conceptApplyPending();  // §D: land on the deep-linked concept-map ring, if any
    }

    // S3 (keyword -> super-group navigation): jump from anywhere (the Keywords-subtab
    // chip, a future card) to the Groups surface, scrolled to the exact group. Deep
    // link via a pending target so it works whether Groups was already loaded (an
    // instant scroll) or is loading now (loadSuperGroups scrolls when it finishes).
    let _sgScrollTo = null;
    function openSupergroup(sgId) {
      _sgScrollTo = sgId;
      showTab("insights");
      if (_insSubtabs) _insSubtabs.select("supergroups"); else showInsightCat("supergroups");
      if (_insLoaded.has("supergroups")) _sgScrollToTarget();
    }
    function _sgScrollToTarget() {
      if (_sgScrollTo == null) return;
      const id = _sgScrollTo; _sgScrollTo = null;
      const el = document.getElementById("sg-card-" + id);
      if (el && el.scrollIntoView) el.scrollIntoView({behavior: "smooth", block: "center"});
    }

    // S5 (curation relocated to Settings -> Keywords, §0 row 9): sgCard is now the
    // READ-ONLY DATA VIEW (Insights -> Groups) -- stats, dominance, trend, members
    // with provenance, but no create/add/remove/delete. sgCurationCard (below) is
    // the interactive counterpart rendered ONLY in Settings.
    function sgCard(g) {
      // Row 7 (display noise): zero-mention members collapse behind a count instead
      // of rendering a flat wall of empty chips.
      const shown = g.members.filter(m => m.mentions > 0);
      const zeroCount = g.members.length - shown.length;
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const chips = shown.length ? shown.map(m => {
        const isRing = !!m.ring_id;
        const inner = isRing
          ? `⊕ ${esc(m.ring_id)}${kwTransHtml(m)} <span class="muted">group·${(m.ring_members || []).length}</span>`
          : esc(m.normalized);
        // Row 2 (cross-group overlap): a member also counted in other groups gets
        // that stated in its hover, never silently summed as if exclusive.
        const alsoIn = (m.also_in && m.also_in.length)
          ? ` — also in: ${m.also_in.join(", ")}` : "";
        // §B circle grammar: a ring/group member gets the box-shadow ring + the
        // translated level hover appended (colour reinforces, the hover carries it).
        const levelTip = isRing ? " — " + lvlTitle("group") : "";
        const tip = esc(t("Open this keyword's own analysis window") + alsoIn + levelTip);
        // A data chip navigates (its own analysis window) rather than mutating the
        // group -- curation actions live in Settings now.
        // §D: a separate map deep-link (never hijacking the chip's own openCorpus
        // action) -- "every ⦾ group chip in the app deep-links to this map".
        const mapLink = isRing
          ? ` <button class="ghost tiny" title="${esc(t("Open on the cross-country concept map"))}"
               onclick="openConceptMap(${esc(JSON.stringify(m.ring_id))})">🗺</button>` : "";
        return `<button class="chip${isRing ? " lvl-group" : ""}" onclick="openCorpus(${esc(JSON.stringify(m.normalized))})"
           title="${tip}">${inner} <span class="muted">${m.mentions}</span>${alsoIn ? " *" : ""}</button>${mapLink}`;
      }).join("")
        : '<span class="muted">No members yet.</span>';
      const zeroChip = zeroCount > 0
        ? `<span class="muted" title="${esc(g.members.filter(m => m.mentions === 0).map(m => m.normalized).join(", "))}">+${zeroCount} with no mentions yet</span>`
        : "";
      // Row 1 (dominance): the mandatory "which member accounts for the total"
      // disclosure — a group total without it misleads by construction.
      const domLine = g.dominance
        ? `<div class="hint muted" style="margin-top:2px">Dominated by <b>${esc(g.dominance.member)}</b> (${Math.round(g.dominance.share * 100)}% of this total)</div>`
        : "";
      // S1.5: a windowed rate + sparkline, present only on the top series_top groups
      // (bounded — never all groups); both summed over the SAME deduped id set the
      // headline total uses, so the chart can never disagree with the number beside it.
      const rateLine = g.rate
        ? `<div class="hint muted" style="margin-top:2px">${esc(growthFallback(g.rate, {window: true})
            || `↑${g.rate.growth}× (${g.rate.recent} recent · ${g.rate.prior} prior, ${g.rate.window_days}d vs ${g.rate.baseline_days}d)`)}</div>`
        : "";
      const spark = (g.series && g.series.length)
        ? `<div style="margin-top:6px">${dashChartSvg(g.series.map(p => ({observed_on: p.date, price: p.count})), "")}</div>`
        : "";
      return `<div class="sg-card" id="sg-card-${g.id}">
        <div class="sg-head"><b class="lvl-super" title="${esc(lvlTitle("super"))}">${esc(g.name)}</b>
          <span class="muted">· ${g.count} member${g.count === 1 ? "" : "s"} · ${g.mentions} mentions</span></div>
        ${domLine}${rateLine}${spark}
        <div class="fam-chips" style="margin-top:6px">${chips}${zeroChip ? " " + zeroChip : ""}</div></div>`;
    }

    async function createSuperGroup() {
      // S5 (curation relocated to Settings): the create input lives at Settings ->
      // Keywords now; Insights -> Groups keeps only the read-only data view.
      const name = $("sgc-name").value.trim();
      if (!name) { toast("Name the super-group.", "err"); return; }
      try {
        await api("/api/insights/supergroups", {method: "POST", body: JSON.stringify({name})});
        $("sgc-name").value = ""; toast("Super-group created."); loadSupergroupCuration();
        if (_insLoaded.has("supergroups")) loadSuperGroups();  // keep the data view in sync
      } catch (e) { toast(_failMsg("Create failed: {error}", e), "err"); }
    }

    // -- Super-group CURATION (Settings -> Keywords; the interactive counterpart of
    // the read-only sgCard data view in Insights -> Groups) ------------------------
    async function loadSupergroupCuration() {
      const box = $("sgc-list");
      if (!box) return;
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const [sgs, top, rings] = await Promise.all([
          api("/api/insights/supergroups"),  // no series_top -- curation needs no rate/sparkline
          api("/api/insights/top?group=true&limit=200" + tgtLangParam()),
          api("/api/insights/rings"),
        ]);
        $("sg-family-options").innerHTML = (top.terms || []).map(f =>
          `<option value="${esc(f.normalized)}">${esc(f.term)} (${f.mentions})</option>`).join("");
        $("sg-ring-options").innerHTML = (rings.rings || []).map(r =>
          `<option value="${esc(r.id)}">${esc(r.id)} — ${esc((r.languages || []).join("/"))}</option>`).join("");
        box.innerHTML = sgs.supergroups.length ? sgs.supergroups.map(sgCurationCard).join("")
          : '<div class="muted">No super-groups yet. Create one above, then add families or groups to it.</div>';
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    function sgCurationCard(g) {
      const chips = g.members.length ? g.members.map(m => {
        const isRing = !!m.ring_id;
        const inner = isRing
          ? `⊕ ${esc(m.ring_id)}${kwTransHtml(m)} <span class="muted">group·${(m.ring_members || []).length}</span>`
          : esc(m.normalized);
        // §B circle grammar: the group ring + its translated level hover, appended
        // to the existing member-list tip (never replacing it).
        const baseTip = isRing ? esc((m.ring_members || []).join(" · ")) : "remove from this group";
        const tip = isRing ? baseTip + " — " + esc(lvlTitle("group")) : baseTip;
        // §D: a separate map deep-link (never hijacking the chip's own remove
        // action) -- "every ⦾ group chip in the app deep-links to this map".
        const mapLink = isRing
          ? ` <button class="ghost tiny" title="Open on the cross-country concept map"
               onclick="openConceptMap(${esc(JSON.stringify(m.ring_id))})">🗺</button>` : "";
        return `<button class="fam-chip${isRing ? " lvl-group" : ""}" data-sg="${g.id}" data-norm="${esc(m.normalized)}" onclick="sgRemoveMember(this)"
           title="${tip}">${inner} <span class="muted">${m.mentions}</span> ✕</button>${mapLink}`;
      }).join("")
        : '<span class="muted">No members yet — add a family or a group below.</span>';
      return `<div class="sg-card">
        <div class="sg-head"><b class="lvl-super" title="${esc(lvlTitle("super"))}">${esc(g.name)}</b>
          <span class="muted">· ${g.count} member${g.count === 1 ? "" : "s"}</span>
          <button class="ghost tiny" style="margin-left:auto" data-sg="${g.id}" data-name="${esc(g.name)}"
            onclick="deleteSuperGroup(this)">delete</button></div>
        <div class="fam-chips" style="margin-top:6px">${chips}</div>
        <div class="row" style="margin-top:8px">
          <div style="flex:2"><input class="sg-fam-in" list="sg-family-options" placeholder="add a family…"
            data-sg="${g.id}" onkeydown="if(event.key==='Enter')sgAddMember(this)"></div>
          <div style="flex:0 0 auto;align-self:end"><button class="secondary"
            onclick="sgAddMember(this.closest('.row').querySelector('.sg-fam-in'))">Add family</button></div>
          <div style="flex:2"><input class="sg-ring-in" list="sg-ring-options" placeholder="add a group (one concept, many languages)…"
            data-sg="${g.id}" onkeydown="if(event.key==='Enter')sgAddRing(this)"></div>
          <div style="flex:0 0 auto;align-self:end"><button class="secondary"
            onclick="sgAddRing(this.closest('.row').querySelector('.sg-ring-in'))">Add group</button></div>
        </div></div>`;
    }

    async function sgAddMember(input) {
      const sg = input.dataset.sg, norm = input.value.trim();
      if (!norm) return;
      try {
        await api(`/api/insights/supergroups/${sg}/members`, {method: "POST", body: JSON.stringify({normalized: [norm]})});
        toast("Added."); loadSupergroupCuration();
        if (_insLoaded.has("supergroups")) loadSuperGroups();
      } catch (e) { toast(_failMsg("Add failed: {error}", e), "err"); }
    }

    async function sgAddRing(input) {
      const sg = input.dataset.sg, ring = input.value.trim();
      if (!ring) return;
      try {
        await api(`/api/insights/supergroups/${sg}/members`, {method: "POST", body: JSON.stringify({rings: [ring]})});
        toast("Group added."); loadSupergroupCuration();
        if (_insLoaded.has("supergroups")) loadSuperGroups();
      } catch (e) { toast(_failMsg("Add group failed: {error}", e), "err"); }
    }

    async function sgRemoveMember(btn) {
      try {
        await api(`/api/insights/supergroups/${btn.dataset.sg}/members?normalized=` + encodeURIComponent(btn.dataset.norm), {method: "DELETE"});
        loadSupergroupCuration();
        if (_insLoaded.has("supergroups")) loadSuperGroups();
      } catch (e) { toast(_failMsg("Remove failed: {error}", e), "err"); }
    }

    async function deleteSuperGroup(btn) {
      if (!confirm(`Delete super-group "${btn.dataset.name}"? (keyword data is untouched)`)) return;
      try {
        await api(`/api/insights/supergroups/${btn.dataset.sg}`, {method: "DELETE"});
        toast("Deleted."); loadSupergroupCuration();
        if (_insLoaded.has("supergroups")) loadSuperGroups();
      } catch (e) { toast(_failMsg("Delete failed: {error}", e), "err"); }
    }

    // -- Keyword explorer (Item AC: explore by tag, hide, apply baseline tags) ---- //
    let _kxAutoBackfilled = false;
    async function loadKeywordExplorer() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("kx-facets");
      if (!box) return;
      box.innerHTML = '<div class="muted">' + esc(t("Loading…")) + '</div>';
      $("kx-keywords").innerHTML = "";
      try {
        const f = await api("/api/insights/keyword-tags/facets");
        // §3.H: tagging at ingest is forward-only, so a pre-existing corpus shows no
        // tags until a backfill runs. Auto-apply the baseline tags ONCE (silent, local,
        // idempotent — the auto-index #21 pattern) when the explorer opens empty. The
        // backfill is now a ~1-min background job (returns {started, job}), so we POLL
        // it to completion BEFORE re-rendering — the old code re-rendered the instant it
        // STARTED (still empty) and the one-shot guard never retried.
        const empty = (f.axes || ["type", "topic"]).every(ax => !((f.facets && f.facets[ax]) || []).length);
        if (empty && !_kxAutoBackfilled) {
          _kxAutoBackfilled = true;
          box.innerHTML = '<div class="muted">' + esc(t("Applying baseline tags in the background…")) + '</div>';
          try {
            await api("/api/insights/keyword-tags/backfill?limit=0", {method: "POST"});
            await pollJobStatus("/api/insights/keyword-tags/backfill/status");
          } catch (e) {}
          return loadKeywordExplorer();  // re-render with the freshly applied tags (guard prevents a loop)
        }
        box.innerHTML = (f.axes || ["type", "topic"]).map(ax => {
          const tags = (f.facets && f.facets[ax]) || [];
          const chips = tags.length ? tags.map(t =>
            `<button class="fam-chip" data-ax="${esc(ax)}" data-tag="${esc(t.tag)}" onclick="kxShowTag(this)">${esc(t.tag)} <span class="muted">${t.keywords}</span></button>`).join("")
            : '<span class="muted">none yet — click “Apply baseline tags” above</span>';
          return `<div style="margin-bottom:8px"><b>${esc(ax)}</b><div class="fam-chips" style="margin-top:4px">${chips}</div></div>`;
        }).join("");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    async function kxShowTag(btn) {
      const ax = btn.dataset.ax, tag = btn.dataset.tag;
      const box = $("kx-keywords");
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        const r = await api(`/api/insights/keyword-tags/keywords?axis=${encodeURIComponent(ax)}&tag=${encodeURIComponent(tag)}&limit=200`);
        box.innerHTML = `<div class="muted" style="margin:6px 0">${r.total} keyword(s) tagged ${esc(ax)}=${esc(tag)}</div>` +
          (r.keywords || []).map(k =>
            `<div style="display:flex;gap:8px;align-items:center;padding:3px 0;border-bottom:1px solid var(--line)">
               <span style="flex:1">${esc(k.term)} <span class="muted">${esc(k.language || "?")} · ${k.articles}a/${k.mentions}m · ${esc(k.source)}</span></span>
               <button class="ghost tiny" data-norm="${esc(k.normalized)}" onclick="kxHide(this)">Hide</button>
             </div>`).join("");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    async function kxHide(btn) {
      try {
        await api("/api/insights/exclude", {method: "POST", body: JSON.stringify({term: btn.dataset.norm})});
        btn.textContent = "hidden"; btn.disabled = true;
      } catch (e) { toast(_failMsg("Hide failed: {error}", e), "err"); }
    }

    async function kxBackfill() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      try {
        toast(t("Applying baseline tags in the background…"));
        // The backfill scans the whole keyword table (~1 min) in a background job
        // (returns {started, job}); poll to completion for the REAL numbers instead of
        // "Tagged undefined keyword(s) (undefined tags)." from the start-state.
        await api("/api/insights/keyword-tags/backfill?limit=0", {method: "POST"});
        const st = await pollJobStatus("/api/insights/keyword-tags/backfill/status");
        if (st.state === "error") { toast(t("Backfill failed:") + " " + (st.error || ""), "err"); return; }
        if (_jobStillRunning(st)) {
          // Stopped watching, not finished — never report the start-state's zeros.
          toast(t("Still running in the background — check the task manager for the result."));
          return;
        }
        const res = st.result || {};
        toast(t("Applied baseline tags:") + " " + (res.tagged_keywords || 0) + " " + t("keywords") + " · " + (res.tags_added || 0) + " " + t("tags"));
        loadKeywordExplorer();
      } catch (e) { toast(t("Backfill failed:") + " " + e.message, "err"); }
    }

    // -- Most-cited sources (corpus-wide co-citation) ----------------------- //
    async function loadCitedSources() {
      const box = $("cs-list");
      const by = $("cs-by").value;
      const win = $("cs-window").value.trim();
      const min = Math.max(1, parseInt($("cs-min").value, 10) || 2);
      box.innerHTML = '<div class="muted">Loading…</div>';
      try {
        let url = `/api/links/top-cited?by=${by}&min_citations=${min}&limit=60`;
        if (win) url += `&window_days=${encodeURIComponent(win)}`;
        const d = await api(url);
        if (!d.items.length) {
          box.innerHTML = `<div class="muted">No source cited by ≥${min} article(s) yet. Ingest more, or lower the threshold. (Links are indexed from article text on ingest.)</div>`;
          return;
        }
        const max = Math.max(...d.items.map(i => i.citations), 1);
        box.innerHTML = d.items.map(it => {
          const label = by === "domain" ? it.domain : (it.link_text || it.domain || it.sample_url || it.normalized_url);
          const key = by === "domain" ? `domain=${encodeURIComponent(it.domain)}` : `url=${encodeURIComponent(it.normalized_url)}`;
          const sub = by === "domain" ? "" : `<div class="cs-url muted">${esc(it.sample_url || it.normalized_url)}</div>`;
          return `<div class="cs-row"><div class="cs-head" data-key="${esc(key)}" onclick="expandCitedSource(this)">
            <div class="cs-bar" style="width:${(it.citations/max*100).toFixed(1)}%"></div>
            <div class="cs-main"><span class="cs-label">${esc(label || "—")}</span>${sub}</div>
            <span class="cs-count">${it.citations}</span></div>
            <div class="cs-arts"></div></div>`;
        }).join("");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load: ${esc(e.message)}</div>`; }
    }

    // Auto-integrate in-article SECONDARY sources: register domains cited by >= N
    // DISTINCT sources as new DISABLED "cited" sources (metadata only — never scraped
    // until the user enables them). Previews via dry_run, then confirms before creating.
    async function promoteCitedSources() {
      const out = $("cs-promote-result");
      try {
        if (out) out.textContent = "Scanning citations…";
        const preview = await api("/api/sources/promote-cited?dry_run=true", {method: "POST"});
        const cands = preview.candidates || [];
        const gate = preview.min_source_citers;
        if (!cands.length) {
          if (out) out.textContent = `No new domain is cited by ≥${gate} distinct sources yet.`;
          return;
        }
        const sample = cands.slice(0, 8).map(c => `${c.domain} (${c.source_citers} sources)`).join("\n");
        const more = cands.length > 8 ? `\n…and ${cands.length - 8} more` : "";
        if (!confirm(`Register ${cands.length} frequently-cited domain(s) as new DISABLED “cited” sources?\n\n${sample}${more}\n\nMetadata only — they are never fetched until you enable them.`)) {
          if (out) out.textContent = "Cancelled.";
          return;
        }
        const res = await api("/api/sources/promote-cited", {method: "POST"});
        const n = (res.created || []).length;
        if (out) out.textContent = `Added ${n} disabled “cited” source(s) — find them in Settings → Sources.`;
        toast(`Registered ${n} cited source(s) — disabled; review them in Sources.`);
      } catch (e) { if (out) out.textContent = "Could not register: " + e.message; }
    }

    async function expandCitedSource(head) {
      const tgt = head.parentElement.querySelector(".cs-arts");
      const key = head.dataset.key;
      if (head.classList.contains("open")) { head.classList.remove("open"); tgt.innerHTML = ""; return; }
      head.classList.add("open");
      tgt.innerHTML = '<div class="muted" style="padding:6px 0">Assembling citing articles…</div>';
      try {
        const d = await api(`/api/links/articles-by-link?${key}&limit=200`);
        if (!d.articles.length) { tgt.innerHTML = '<div class="muted" style="padding:6px 0">No stored articles.</div>'; return; }
        tgt.innerHTML = `<div class="cs-arts-h muted">${d.count} article(s) cite this${d.count>d.articles.length?` (showing ${d.articles.length})`:""}:</div>` +
          d.articles.map(a => `<div class="cs-art">
            <a href="/api/articles/${a.id}/view" target="_blank" rel="noopener" title="offline stored copy">${esc(a.title || a.url)}</a>
            <span class="muted"> — ${esc(a.source || "")}${a.published_at?" · "+esc(a.published_at.slice(0,10)):""}</span>
            ${a.url?` · ${extLink(a.url, "source ↗", "muted")}`:""}</div>`).join("");
      } catch (e) { tgt.innerHTML = `<div class="muted" style="padding:6px 0">Could not load: ${esc(e.message)}</div>`; }
    }

    // Convergence (read-only, additive): clusters of articles converging on the
    // same PLACE within a time window on the MENTIONED event date. Independence is
    // measured by DISTINCT SOURCES, never article count; shared-origin links flag
    // possible false-triangulation (sources echoing one citation). The method +
    // caveat come FROM the API and are shown VISIBLE by default (informed consent —
    // co-occurrence is never causation). No score: only the counts the API returns.
    async function loadConvergences() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("cv-list"), meth = $("cv-method");
      const wEl = $("cv-window");
      const w = wEl ? (Math.max(1, parseInt(wEl.value, 10) || 7)) : 7;
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      if (meth) meth.textContent = "";
      try {
        const d = await api("/api/insights/convergences?window_days=" + w + "&limit=20");
        const clusters = d.clusters || [];
        if (!clusters.length) {
          // Honest empty state: state the gate (≥min_articles AND ≥min_sources).
          box.innerHTML = `<div class="muted">` + esc(
            t("No convergences yet. A cluster needs at least {a} articles AND at least {s} sources sharing a place within the window.")
              .replace("{a}", String(d.min_articles)).replace("{s}", String(d.min_sources))) + `</div>`;
          if (meth && d.caveat) meth.textContent = d.caveat;
          return;
        }
        const rows = clusters.map(c => {
          const place = esc(c.place || "—") + (c.place_country ? ` <span class="muted">(${esc(c.place_country)})</span>` : "");
          const win = esc((c.window_start || "").slice(0, 10)) + " → " + esc((c.window_end || "").slice(0, 10));
          const srcNames = (c.source_names || []).map(esc).join(", ");
          const srcShown = srcNames.length > 160 ? srcNames.slice(0, 160) + "…" : srcNames;
          // Title is clickable -> the exact converging article set (function exists).
          const head = `<div class="cs-main"><span class="cs-label" style="cursor:pointer;text-decoration:underline"
              onclick="openAnalysisForIds(${esc(JSON.stringify(c.article_ids || []))}, ${esc(JSON.stringify(c.place || ""))})">${place}</span>
            <div class="cs-url muted">${win}</div></div>`;
          const counts = `<span class="muted">${c.n_articles} ${esc(t("articles"))} · ${c.distinct_sources} ${esc(t("sources"))}</span>`;
          const srcLine = srcShown ? `<div class="muted" style="font-size:11px;margin-top:2px">${srcShown}</div>` : "";
          // VISIBLE shared-origin warning when sources may echo one citation.
          const warn = (c.shared_origin_links > 0)
            ? `<div class="hint" style="color:var(--caveat);margin-top:2px">${esc(
                t("⚠ {n} shared-origin links — sources may echo one citation, not independent confirmation.")
                  .replace("{n}", String(c.shared_origin_links)))}</div>`
            : "";
          return `<div class="cs-row" style="display:block;padding:8px 0;border-bottom:1px solid var(--border)">
            <div style="display:flex;align-items:baseline;justify-content:space-between;gap:8px">${head}${counts}</div>
            ${srcLine}${warn}</div>`;
        }).join("");
        const total = d.clusters_total != null ? d.clusters_total : clusters.length;
        const more = (total > clusters.length)
          ? `<div class="muted" style="margin-top:8px">${esc(
              t("Showing {n} of {t} clusters.").replace("{n}", String(clusters.length)).replace("{t}", String(total)))}</div>`
          : "";
        box.innerHTML = rows + more;
        // Method + caveat VISIBLE by default (never behind a toggle).
        if (meth) {
          const parts = [];
          if (d.method) parts.push(d.method);
          if (d.caveat) parts.push(d.caveat);
          meth.textContent = parts.join(" — ");
        }
      } catch (e) {
        // Additive panel — degrade quietly, never throw.
        box.innerHTML = `<div class="muted">${esc(t("Could not load") + ": " + e.message)}</div>`;
      }
    }

    // -- Lunar correlation (wave 5): first-class surface for the read-only
    // /api/insights/lunar-correlation screen (was a raw-JSON diagnostics button).
    // Screens the top keywords' daily coverage against the moon's illuminated
    // fraction, Benjamini-Hochberg FDR-corrected. The method + "correlation is not
    // causation" caveat live in the panel intro (VISIBLE by default); the common,
    // honest outcome (nothing survives) is stated, never hidden. The survivor flag
    // is the FDR verdict, NOT a ranking — counts + statistics only, no score.
    async function loadLunar() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const box = $("lunar-list"); if (!box) return;
      const limEl = $("lunar-limit"), fdrEl = $("lunar-fdr");
      const lim = Math.min(200, Math.max(1, parseInt(limEl ? limEl.value : "40", 10) || 40));
      let q = parseFloat(fdrEl ? fdrEl.value : "0.05");
      if (!(q > 0 && q <= 1)) q = 0.05;
      box.innerHTML = `<div class="muted">${esc(t("Screening the corpus… a permutation test runs per keyword, so this can take a few seconds."))}</div>`;
      try {
        const d = await api(`/api/insights/lunar-correlation?limit=${lim}&fdr_q=${q}`);
        const results = d.results || [];
        // Honest summary — counts only (tested · skipped · survivors).
        const summary = `<div class="muted" style="margin-bottom:8px">${d.tested || 0} ${esc(t("tested"))} · ${d.skipped || 0} ${esc(t("skipped"))} · <strong>${d.survivors || 0}</strong> ${esc(t("survivors"))}</div>`;
        if (!results.length) {
          // tested==0 -> too few active days; state it, never a blank pane.
          box.innerHTML = summary + `<div class="muted">${esc(t("No series had enough active days to test."))}</div>`;
          return;
        }
        // Never hide an empty result: when nothing survives, say so prominently.
        const noneNote = (d.survivors === 0)
          ? `<div class="card-caveat" style="margin-bottom:8px">${esc(t("No series survived the multiple-testing correction — the honest, expected result."))}</div>`
          : "";
        const header = `<tr>
          <th>${esc(t("Term"))}</th><th style="text-align:right">r</th>
          <th style="text-align:right">${esc(t("p-value"))}</th><th style="text-align:right">n</th>
          <th style="text-align:right">${esc(t("active days"))}</th>
          <th style="text-align:right">${esc(t("q-value"))}</th><th>${esc(t("survived"))}</th></tr>`;
        const rows = results.map(r => {
          // The survivor flag is the FDR verdict, never a ranking.
          const surv = r.survives
            ? `<span class="pill ok">${esc(t("survived"))}</span>`
            : `<span class="muted">—</span>`;
          const qv = (r.q_value == null) ? "—" : (+r.q_value).toFixed(4);
          const num = (v, dp) => (v == null || isNaN(+v)) ? "—" : (+v).toFixed(dp);
          return `<tr>
            <td>${esc(r.term)}</td>
            <td style="text-align:right">${num(r.r, 3)}</td>
            <td style="text-align:right">${num(r.p_value, 4)}</td>
            <td style="text-align:right" class="muted">${r.n}</td>
            <td style="text-align:right" class="muted">${r.active_days}</td>
            <td style="text-align:right">${qv}</td>
            <td>${surv}</td></tr>`;
        }).join("");
        box.innerHTML = summary + noneNote + `<div style="overflow:auto"><table>${header}${rows}</table></div>`;
      } catch (e) {
        // Additive panel — degrade quietly, never throw.
        box.innerHTML = `<div class="muted">${esc(t("Could not load") + ": " + e.message)}</div>`;
      }
    }

    async function lunarTestTerm() {
      const t = (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s);
      const out = $("lunar-single"); if (!out) return;
      const termEl = $("lunar-term");
      const term = (termEl ? termEl.value : "").trim();
      if (!term) { out.textContent = ""; return; }
      out.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const d = await api("/api/insights/lunar-correlation?term=" + encodeURIComponent(term));
        const r = d.result;
        if (!r) {
          // Honest skip: too few active days to test this one keyword.
          out.innerHTML = `<div class="muted">${esc(t("Too few active days to test this keyword honestly."))}</div>`;
          return;
        }
        const stat = `<strong>${esc(r.term)}</strong> · r ${(+r.r).toFixed(3)} · ${esc(t("p-value"))} ${(+r.p_value).toFixed(4)} · n ${r.n} · ${r.active_days} ${esc(t("active days"))}`;
        // The single-test note (keyed, VISIBLE): one test is not a screen.
        out.innerHTML = `<div>${stat}</div>
          <div class="card-caveat" style="margin-top:4px">${esc(t("A single test, not corrected for multiple comparisons — screen many keywords for an honest, FDR-corrected result."))}</div>`;
      } catch (e) {
        out.innerHTML = `<div class="muted">${esc(t("Could not load") + ": " + e.message)}</div>`;
      }
    }

    // -- Watches (ruling #3): saved local conditions that fire a Lead card. English
    // strings here (matching the keyword-explorer/stats sub-features) so i18n stays
    // 100% with zero new keys; the engine + honesty live in the (tested) backend.
    async function loadWatches() {
      const box = $("wt-list"); if (!box) return;
      box.innerHTML = `<div class="muted">Loading…</div>`;
      try {
        const d = await api("/api/watches");
        const ws = d.watches || [];
        if (!ws.length) { box.innerHTML = `<div class="muted">No watches yet — add one above. The engine runs after every collection pass.</div>`; return; }
        box.innerHTML = ws.map(w => {
          const last = w.last_matched_at ? fmtDateTime(w.last_matched_at) : "never";
          const hist = (w.history || []).map(h =>
            `<li>${esc(fmtDateTime(h.matched_at))}: <b>${h.n_articles}</b> articles (${h.new_articles} new)`
            + (h.article_ids && h.article_ids.length ? ` · <a href="#" onclick="openAnalysisForIds(${JSON.stringify(h.article_ids)}, ${JSON.stringify('Watch: ' + w.name)});return false">open set ↗</a>` : "")
            + `</li>`).join("");
          return `<div class="card" style="padding:10px;margin-bottom:8px">
            <div class="row" style="align-items:center;justify-content:space-between;gap:8px">
              <div><b>${esc(w.name)}</b> <span class="muted">— “${esc(w.query)}”</span>
                <span class="pill ${w.enabled ? 'ok' : ''}">${w.enabled ? 'on' : 'off'}</span></div>
              <div style="flex:0 0 auto">
                <button class="secondary" onclick="toggleWatch(${w.id}, ${!w.enabled})">${w.enabled ? 'Disable' : 'Enable'}</button>
                <button class="secondary" onclick="editWatch(${w.id})">Edit</button>
                <button class="secondary" onclick="deleteWatch(${w.id})">Delete</button>
              </div>
            </div>
            <div class="hint" style="margin-top:4px">≥ ${w.threshold} articles within ${w.window_days} day(s) · last fired: ${esc(last)}</div>
            ${hist ? `<ul class="hint" style="margin:6px 0 0 16px">${hist}</ul>` : ""}
          </div>`;
        }).join("") + (d.caveat ? `<div class="hint" style="margin-top:8px">${esc(d.caveat)}</div>` : "");
      } catch (e) { box.innerHTML = `<div class="muted">Could not load watches: ${esc(e.message)}</div>`; }
    }
    async function createWatch() {
      const name = ($("wt-name").value || "").trim();
      const query = ($("wt-query").value || "").trim();
      const threshold = parseInt($("wt-threshold").value || "3", 10);
      const window_days = parseInt($("wt-window").value || "7", 10);
      const msg = $("wt-msg");
      if (!query) { if (msg) msg.textContent = "Enter a condition (search query) first."; return; }
      try {
        await api("/api/watches", { method: "POST", body: JSON.stringify({ name, query, threshold, window_days }) });
        $("wt-name").value = ""; $("wt-query").value = "";
        if (msg) msg.textContent = "Watch added. It runs after every collection pass, or use “Check now”.";
        loadWatches();
      } catch (e) { if (msg) msg.innerHTML = `<span class="note err">Could not add: ${esc(e.message)}</span>`; }
    }
    async function toggleWatch(id, enabled) {
      try { await api("/api/watches/" + id, { method: "PATCH", body: JSON.stringify({ enabled }) }); loadWatches(); }
      catch (e) { toast("Could not update watch: " + e.message, "err"); }
    }
    async function editWatch(id) {
      // Minimal inline edit via prompts (the panel is browser-unverified; keep it simple).
      const q = prompt("New condition (search query) — leave blank to keep:");
      const th = prompt("Min articles to fire (leave blank to keep):");
      const wd = prompt("Window in days (leave blank to keep):");
      const body = {};
      if (q && q.trim()) body.query = q.trim();
      if (th && th.trim()) body.threshold = parseInt(th, 10);
      if (wd && wd.trim()) body.window_days = parseInt(wd, 10);
      if (!Object.keys(body).length) return;
      try { await api("/api/watches/" + id, { method: "PATCH", body: JSON.stringify(body) }); loadWatches(); }
      catch (e) { toast("Could not edit watch: " + e.message, "err"); }
    }
    async function deleteWatch(id) {
      if (!confirm("Delete this watch and its history?")) return;
      try { await api("/api/watches/" + id, { method: "DELETE" }); loadWatches(); }
      catch (e) { toast("Could not delete watch: " + e.message, "err"); }
    }
    async function evaluateWatches() {
      const msg = $("wt-msg");
      if (msg) msg.textContent = "Checking…";
      try {
        const d = await api("/api/watches/evaluate", { method: "POST" });
        if (msg) msg.textContent = d.count ? `${d.count} watch(es) fired — see Home, or the history below.` : "No watches fired (no new matching articles).";
        loadWatches();
      } catch (e) { if (msg) msg.innerHTML = `<span class="note err">Check failed: ${esc(e.message)}</span>`; }
    }

    let _insStatusBuilt = false;
    async function loadInsights() {
      try {
        const s = await api("/api/insights/status");
        if (!_insStatusBuilt) {
          _insStatusBuilt = true;
          $("ins-status").innerHTML =
            `<span class="pill" id="ins-pill"><span id="ins-n-indexed" data-v="0">0</span>/` +
            `<span id="ins-n-total" data-v="0">0</span> articles indexed</span> · ` +
            `<span id="ins-n-keywords" data-v="0">0</span> keywords ` +
            `(<span id="ins-n-entities" data-v="0">0</span> entities) · ` +
            `<span id="ins-n-mentions" data-v="0">0</span> mentions ` +
            `<span id="ins-remaining" class="muted"></span>`;
        }
        animateCount($("ins-n-indexed"), s.indexed_articles);
        animateCount($("ins-n-total"), s.total_articles);
        animateCount($("ins-n-keywords"), s.keywords);
        animateCount($("ins-n-entities"), s.entities);
        animateCount($("ins-n-mentions"), s.mentions);
        $("ins-pill").className = "pill " + (s.remaining === 0 ? "ok" : "warn");
        $("ins-remaining").innerHTML = s.remaining ? `· <strong>${s.remaining.toLocaleString()}</strong> to index` : "";
        if (s.remaining > 0 && !_indexing) autoIndexInsights();  // background top-up; no button (§6)
      } catch (e) { if (!_insStatusBuilt) $("ins-status").textContent = "Status unavailable: " + e.message; }
      loadLandscape();
    }

    // Insights indexing follows ingest automatically (the index_article hook
    // runs at ingest); this SILENT background top-up clears any legacy backlog of
    // not-yet-indexed articles when Insights is viewed — no button, the user
    // never thinks about it (UI_SHELL_REDESIGN §6). Best-effort + bounded; the
    // visible "N to index" count ticks down to 0 on its own.
    let _indexing = false;
    let _autoIndexCooldownUntil = 0;      // throttles the 6 s status poll's re-kick
    let _autoIndexLastRemaining = -1;     // detects a genuinely stuck backlog
