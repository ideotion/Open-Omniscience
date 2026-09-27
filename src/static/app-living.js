/* app-living.js — the Living sources view (Q1016; gate row O, S04-08's S6)

   One view for the sources that keep changing after they are collected: Wikipedia,
   law and maps. Each has its coverage, its freshness, its storage, and a timeline of
   changes whose stored diff opens in place. It replaces the tracked-changes dialog
   (#wiki-tc): that view's own renderer (loadWikiTC / _wikiRevRow, app-map.js) now
   draws into this tab, so a watched page's history is read beside the others rather
   than over them.

   COUNTS AND DATES, NEVER A VERDICT. Freshness is the newest and the oldest check,
   never "stale": how recent is recent enough depends on the story, and no threshold
   was ruled. A change the stream only COUNTED reads as counted, never as a change
   with nothing in it. Every figure carries its method in the hover (#oo-tip).

   The renderers below are pure (payload, t, tf) -> HTML so they can be driven in
   node (tests/living_sources_node_test.js) and reused as a Home family if the
   placement moves there; only the load* functions touch the DOM or the network,
   and the network is loopback.
*/
    let _livingSubtabs = null;
    let _livingView = "wiki";
    let _livingOverview = null;
    let _livingStreamOffset = 0;
    const _LIVING_KINDS = ["wiki", "law", "osm"];
    const _LIVING_STREAM_PAGE = 50;

    // A stored UTC instant, said as UTC. Every timestamp this view shows is UTC on the
    // wire; printing its digits without the zone would read as the operator's own time.
    function livingWhen(iso, t) {
      if (!iso) return t("never");
      return _ltrIsolate(String(iso).slice(0, 16).replace("T", " ")) + " UTC";
    }

    function livingSigned(n) {
      if (typeof n !== "number") return "";
      return _ltrIsolate((n > 0 ? "+" : "") + n);
    }

    // One figure: a label, a value and the method behind it. `html` marks a value that
    // is already markup (the storage cells reused from Settings -> Storage).
    function livingFactHtml(f) {
      const val = f.html ? f.value : esc(f.value);
      return `<div class="living-fact"${f.hover ? ` title="${esc(f.hover)}"` : ""}>`
        + `<div class="muted">${esc(f.label)}</div><div class="living-fact-v">${val}</div></div>`;
    }

    function livingGroupsHtml(groups) {
      return groups.map((g) =>
        `<h3 class="lib-sub">${esc(g.title)}</h3>`
        + `<div class="living-facts">${g.facts.map(livingFactHtml).join("")}</div>`).join("");
    }

    function _livingUnmeasured(block, t) {
      const why = block && block.reason === "lane-never-run"
        ? t("Not run yet") : t("Could not be read");
      const hover = block && block.reason === "lane-never-run"
        ? t("This lane has no database file yet: it has never run.")
        : t("This part could not be read just now. The other figures on this page are unaffected.");
      return [{ label: t("State"), value: why, hover }];
    }

    // The same two cells Settings -> Storage draws, so the two surfaces cannot come to
    // disagree -- minus the budget's edit box: this tab shows data, and the setting
    // stays in Settings (invariant #8).
    function livingStorageGroup(storage, t) {
      const facts = [];
      if (!storage) {
        facts.push({ label: t("On disk"), value: t("Could not be read"),
          hover: t("The storage report could not be read just now.") });
      } else {
        facts.push({ label: t("On disk"), value: _storageSizeHtml(storage), html: true });
        const budget = Object.assign({}, storage.budget || {}, { setting: null });
        facts.push({ label: t("Budget"), value: _storageBudgetHtml(Object.assign({}, storage, { budget })) || "—",
          html: true, hover: t("Budgets are set in Settings → Data & backup.") });
      }
      return { title: t("Storage"), facts };
    }

    function livingWikiGroups(src, t, tf) {
      const s = src.stream || {};
      const stream = s.measured !== true ? _livingUnmeasured(s, t) : [
        { label: t("Pages followed"), value: String(s.pages),
          hover: t("Pages the live stream follows, in its own lane file.") },
        { label: t("Changes reported, last 30 days"), value: String(s.changes),
          hover: t("Changes the stream reported for the pages it follows, counted by when this machine recorded them.") },
        { label: t("Text stored for"), value: tf("{n} of {m}", { n: s.changes_with_text, m: s.changes }),
          hover: t("Under a budget the stream stores the text of some changes and counts the rest. A counted change has no diff.") },
        { label: t("Changes on pages you do not follow"), value: String(s.changes_not_followed),
          hover: t("Changes the stream reported for pages outside your list, counted but not stored.") },
        { label: t("Last change recorded"), value: livingWhen(s.last_change_at, t),
          hover: t("The newest change the stream recorded, on any page, followed or not.") },
        { label: t("Complete through"), value: s.contiguous_through ? livingWhen(s.contiguous_through, t) : t("Not declared yet"),
          hover: t("The earliest point every feed was read without a break. Changes before it are all here; after it, some may be missing.") },
        { label: t("Open gaps"), value: String(s.open_gaps),
          hover: t("Stretches of the feed the stream knows it missed and has not filled.") },
      ];
      const k = src.tracked || {};
      const tracked = k.measured !== true ? _livingUnmeasured(k, t) : [
        { label: t("Pages"), value: String(k.pages),
          hover: t("The pages you added in Settings → Wikipedia.") },
        { label: t("Never checked"), value: String(k.never_checked) },
        { label: t("Newest check"), value: livingWhen(k.newest_check_at, t) },
        { label: t("Oldest check"), value: livingWhen(k.oldest_check_at, t),
          hover: t("The page checked longest ago. Freshness is shown as dates, never judged.") },
        { label: t("Revisions stored, last 30 days"), value: String(k.changes),
          hover: t("Counted by when this machine stored them, not by the edit's own date.") },
        { label: t("Flagged"), value: String(k.flagged),
          hover: t("Revisions a heuristic flagged, such as a large removal. A flag is a reason to look, not a finding.") },
      ];
      return [
        { title: t("Live stream"), facts: stream },
        { title: t("Pages you track"), facts: tracked },
        livingStorageGroup(src.storage, t),
      ];
    }

    function livingLawGroups(src, t) {
      const k = src.tracker || {};
      const facts = k.measured !== true ? _livingUnmeasured(k, t) : [
        { label: t("Documents"), value: String(k.documents) },
        { label: t("Jurisdictions"), value: String(k.jurisdictions) },
        { label: t("Never checked"), value: String(k.never_checked) },
        { label: t("Newest check"), value: livingWhen(k.newest_check_at, t) },
        { label: t("Oldest check"), value: livingWhen(k.oldest_check_at, t),
          hover: t("The document checked longest ago. Freshness is shown as dates, never judged.") },
        { label: t("Changes, last 30 days"), value: String(k.changes),
          hover: t("Revisions whose text changed, counted by when this machine observed them. A re-check with no change is not counted.") },
        { label: t("Flagged"), value: String(k.flagged),
          hover: t("Changes a heuristic flagged. A flag is a reason to look, not a finding.") },
      ];
      return [{ title: t("Law tracker"), facts }, livingStorageGroup(src.storage, t)];
    }

    function livingMapGroups(src, t) {
      const m = src.maps || {};
      let facts;
      if (m.measured !== true) {
        facts = _livingUnmeasured(m, t);
      } else {
        const st = m.by_state || {};
        facts = [
          { label: t("Regions"), value: String(m.regions) },
          { label: t("Downloaded"), value: String(st.done || 0) },
          { label: t("In progress"), value: String((st.downloading || 0) + (st.queued || 0)) },
          { label: t("Paused"), value: String(st.paused || 0) },
          { label: t("Failed"), value: String(st.error || 0) },
          { label: t("On disk"), value: humanBytes(m.bytes_on_disk || 0),
            hover: t("The bytes the map files hold on this machine, partial downloads included.") },
          { label: t("Date of the map data"), value: t("Not recorded"),
            hover: t("A map extract carries the date of its data in its own header, which the app does not read yet. The date the file was written here is a different fact, so it is not shown in its place.") },
        ];
      }
      return [{ title: t("Map regions"), facts }, livingStorageGroup(src.storage, t)];
    }

    function livingGroupsFor(src, t, tf) {
      if (!src) return [];
      if (src.kind === "wiki") return livingWikiGroups(src, t, tf);
      if (src.kind === "law") return livingLawGroups(src, t);
      if (src.kind === "osm") return livingMapGroups(src, t);
      return [];
    }

    // A stored diff, line by line: added and removed lines coloured, everything else
    // (the unified headers and context) muted. Never a live re-diff -- the text drawn is
    // what was stored when the change arrived.
    function livingDiffHtml(text) {
      return String(text || "").split("\n").map((l) => {
        const head = l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@");
        const cls = head ? "muted" : l.charAt(0) === "+" ? "ok" : l.charAt(0) === "-" ? "err" : "muted";
        return `<div class="living-diff-l" style="color:var(--${cls})">${esc(l)}</div>`;
      }).join("");
    }

    // One opened stream diff, from the revision payload: the stored lines, the truncation
    // note when the server cut it, and what the diff is (and is not) measured against.
    function livingDiffBoxHtml(d, t, tf) {
      let html = `<div class="living-diff">${livingDiffHtml(d.diff_text)}</div>`;
      if (d.truncated) {
        html += `<div class="muted small">${esc(tf("Showing the first {n} characters of {m}.", { n: (d.diff_text || "").length, m: d.diff_chars }))}</div>`;
      }
      return html + `<div class="muted small">${esc(t("The diff stored when this change arrived, against the lane's previous stored text: not a live re-diff, and not necessarily the source's previous revision."))}</div>`;
    }

    // The four kinds the lane knows, each to the NOUN it is shown as ("delete" is keyed
    // elsewhere as a button's verb, which reads wrong on a label in several languages).
    const _LIVING_CHANGE_KINDS = { edit: "edit", create: "create", delete: "deletion", move: "move" };

    function livingStreamRowsHtml(changes, t, tf) {
      if (!changes || !changes.length) {
        return `<div class="muted">${esc(t("No changes recorded for the pages the stream follows yet."))}</div>`;
      }
      return changes.map((c) => {
        const kind = Object.prototype.hasOwnProperty.call(_LIVING_CHANGE_KINDS, c.change_kind)
          ? `<span class="pill">${esc(t(_LIVING_CHANGE_KINDS[c.change_kind]))}</span>`
          : `<span class="pill" title="${esc(t("The source's own word for this change, shown as it was sent."))}">${esc(c.change_kind || "?")}</span>`;
        let what;
        if (!c.text_stored) {
          what = `<span title="${esc(t("Under a budget the stream stores the text of some changes and counts the rest. A counted change has no diff."))}">${esc(t("Counted only: its text was not stored."))}</span>`;
        } else if (c.diff_method === "unified") {
          what = esc(tf("Lines added: {added}, removed: {removed}", { added: c.diff_added, removed: c.diff_removed }))
            + ` <button class="tiny secondary" data-diff-rev="${Number(c.revision_id)}" onclick="livingShowDiff(${Number(c.revision_id)}, this)">${esc(t("Show diff"))}</button>`;
        } else if (c.diff_method === "no-previous-text") {
          what = esc(t("Text stored; there was no earlier stored text to compare it with."));
        } else if (c.diff_method === "too-large") {
          what = esc(t("Text stored; too large to compare line by line."));
        } else {
          what = esc(t("Text stored."));
        }
        const delta = typeof c.byte_delta === "number"
          ? ` <span class="living-delta" title="${esc(t("Change in size, in bytes, as the source reported it."))}">${esc(livingSigned(c.byte_delta))}</span>` : "";
        return `<div class="living-row"><div class="living-row-head">`
          + `<span class="muted">${esc(livingWhen(c.recorded_at, t))}</span> · <b>${esc(c.title || c.external_id || "?")}</b>`
          // Q302: the language CODE (639-2/T) on screen, its name in the hover.
          + (c.language ? ` ${ooLangCell(c.language, { cls: "pill" })}` : "") + ` ${kind}${delta}</div>`
          + `<div class="muted small">${what}</div>`
          + (c.text_stored ? `<div id="living-diff-${Number(c.revision_id)}"></div>` : "")
          + `</div>`;
      }).join("");
    }

    function livingLawRowsHtml(changes, t) {
      if (!changes || !changes.length) {
        return `<div class="muted">${esc(t("No changes recorded for the documents the law tracker follows yet."))}</div>`;
      }
      return changes.map((c) => {
        const reasons = (c.flag_reasons || []).filter(Boolean)
          .map((x) => `<span class="pill warn">${esc(x)}</span>`).join(" ");
        const diff = (c.diff || "").trim()
          // The change's id travels on the fold, so a repaint (a language switch) can
          // re-open exactly the diffs the reader had open (2026-09-27 re-walk O-3).
          ? `<details data-change-id="${esc(String(c.id == null ? "" : c.id))}"><summary>${esc(t("Stored diff"))}</summary><div class="living-diff">${livingDiffHtml(c.diff)}</div></details>`
          : `<div class="muted small">${esc(t("No stored diff (no parent, or tracked without diffs)."))}</div>`;
        return `<div class="living-row"><div class="living-row-head">`
          + `<span class="muted">${esc(livingWhen(c.observed_at, t))}</span> · `
          // Q302: the alpha-3 code on screen, the country's name in the hover (as the Law tab).
          + `${ooCountryCell(c.jurisdiction, { cls: "pill" })} <b>${esc(c.title || "?")}</b>`
          + (typeof c.delta_bytes === "number" ? ` <span class="living-delta">${esc(livingSigned(c.delta_bytes))}</span>` : "")
          + (reasons ? ` ${reasons}` : "")
          // The local stored copy first (invariant #6); the official source is one more
          // click from there, through the reader's own confirmed link.
          + (c.document_id != null ? ` · <a href="/api/law/documents/${Number(c.document_id)}/view" target="_blank" rel="noopener"`
            + ` title="${esc(t("offline stored copy + history"))}">${esc(t("Read locally"))}</a>` : "")
          + `</div>${diff}</div>`;
      }).join("");
    }

    const _LIVING_MAP_STATE = {
      done: "Downloaded", downloading: "Downloading", queued: "Queued", paused: "Paused", error: "Failed",
    };

    function livingMapRowsHtml(downloads, t) {
      if (!downloads || !downloads.length) {
        return `<div class="muted">${esc(t("No map regions downloaded yet. Regions are downloaded from Settings → OpenStreetMap."))}</div>`;
      }
      const rows = downloads.map((d) => {
        const state = _LIVING_MAP_STATE[d.status] ? t(_LIVING_MAP_STATE[d.status]) : String(d.status || "?");
        const size = d.total_bytes
          ? `${humanBytes(d.downloaded_bytes || 0)} / ${humanBytes(d.total_bytes)}`
          : humanBytes(d.downloaded_bytes || 0);
        // The same cause line the task manager draws, from the same function, fed the
        // task manager's word for a failure (the manager itself writes "error").
        const why = typeof _jobWhy === "function"
          ? _jobWhy({ kind: "osm-map", state: d.status === "error" ? "failed" : d.status,
            paused_by: d.paused_by, error: d.error }, t) : "";
        return `<tr><td>${esc(t(d.name || d.key || "?"))}</td><td>${esc(state)}${why}</td><td>${esc(size)}</td></tr>`;
      }).join("");
      return `<table><thead><tr><th>${esc(t("Region"))}</th><th>${esc(t("State"))}</th>`
        + `<th>${esc(t("On disk"))}</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    // ---- wiring (DOM + loopback reads only) ----------------------------------------- //

    // The last payload each panel drew, so a language switch repaints the panel from
    // what it already holds -- no request, and nothing the reader opened is closed. The
    // switch used to re-run showLivingView, which re-fetched and rebuilt every list and
    // so collapsed an open stream diff and every open law diff (2026-09-27 re-walk O-3).
    let _livingStreamLast = null;   // {measured, reason, changes: [every row loaded], total}
    let _livingPagesLast = null;
    let _livingLawLast = null;
    let _livingMapsLast = null;
    const _livingDiffs = new Map();  // revision id -> the payload of a diff opened

    function _livingT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _livingTf() {
      return (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]));
    }
    // "Could not load: <reason>" with the reader's own separator (ooLabelText), never a
    // welded ": " -- the zh and ja colon is full-width, the fr one takes a space.
    function _livingFailHtml(msg, t) {
      return `<div class="muted">${esc(ooLabelText(t("Could not load"), msg))}</div>`;
    }

    async function loadLiving() {
      const nav = $("living-subtabs");
      // A re-open keeps the source the operator was reading; only the first open starts
      // on Wikipedia.
      if (nav && !_livingSubtabs) _livingSubtabs = ooSubtabs(nav, showLivingView, { initial: _livingView });
      else if (_livingSubtabs) _livingSubtabs.select(_livingView);
    }

    function showLivingView(kind) {
      if (_LIVING_KINDS.indexOf(kind) < 0) kind = "wiki";
      _livingView = kind;
      _LIVING_KINDS.forEach((v) => { const el = $("living-" + v); if (el) el.style.display = (v === kind) ? "" : "none"; });
      loadLivingOverview();
      if (kind === "wiki") { _livingStreamOffset = 0; loadLivingStream(); loadLivingPages(); }
      else if (kind === "law") loadLivingLaw();
      else if (kind === "osm") loadLivingMaps();
    }

    function renderLivingOverview() {
      const t = _livingT(), tf = _livingTf();
      const d = _livingOverview;
      if (!d) return;
      (d.sources || []).forEach((src) => {
        const el = $("living-" + src.kind + "-facts");
        if (el) el.innerHTML = livingGroupsHtml(livingGroupsFor(src, t, tf));
      });
      const st = $("living-status");
      if (st) {
        st.textContent = tf("Read {when}. Counts cover the last {days} days.", { when: livingWhen(d.read_at, t), days: d.window_days });
        st.title = t("Counts of what this machine recorded, read now. Nothing is sent anywhere.");
      }
    }

    async function loadLivingOverview() {
      const t = _livingT();
      try {
        _livingOverview = await api("/api/living/overview");
        renderLivingOverview();
      } catch (e) {
        const st = $("living-status");
        if (st) st.textContent = ooLabelText(t("Could not load"), e.message);
      }
    }

    // The whole stream as loaded so far (every "Show older changes" page included).
    function renderLivingStream() {
      const t = _livingT(), tf = _livingTf();
      const box = $("living-stream"), btn = $("living-stream-more"), cap = $("living-stream-cap");
      const d = _livingStreamLast;
      if (!box || !d) return;
      if (d.measured !== true) {
        box.innerHTML = `<div class="muted">${esc(d.reason === "lane-never-run"
          ? t("The live stream has not run yet, so there is no timeline. Turn it on with the W button in the top bar.")
          : t("The live stream's file could not be read just now."))}</div>`;
        if (btn) btn.hidden = true;
        if (cap) cap.textContent = "";
        return;
      }
      box.innerHTML = livingStreamRowsHtml(d.changes, t, tf);
      _livingStreamCap();
    }
    function _livingStreamCap() {
      const tf = _livingTf();
      const btn = $("living-stream-more"), cap = $("living-stream-cap");
      const d = _livingStreamLast;
      if (!d || d.measured !== true) return;
      // The window is stated, never implied: N of M, and a button while more exist.
      if (cap) cap.textContent = d.total ? tf("Showing {n} of {m} changes, newest first.", { n: _livingStreamOffset, m: d.total }) : "";
      if (btn) btn.hidden = _livingStreamOffset >= d.total;
    }

    async function loadLivingStream(more) {
      const t = _livingT(), tf = _livingTf();
      const box = $("living-stream");
      if (!box) return;
      if (!more) {
        _livingStreamOffset = 0;
        _livingStreamLast = null;
        box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      }
      try {
        const d = await api(`/api/wiki/lane/changes?limit=${_LIVING_STREAM_PAGE}&offset=${_livingStreamOffset}`);
        if (d.measured !== true) {
          _livingStreamLast = { measured: d.measured, reason: d.reason, changes: [], total: 0 };
          renderLivingStream();
          return;
        }
        const changes = d.changes || [];
        if (more && _livingStreamLast) {
          // Appended, not redrawn: a diff opened higher up stays open.
          _livingStreamLast.changes = _livingStreamLast.changes.concat(changes);
          _livingStreamLast.total = d.total;
          if (changes.length) box.insertAdjacentHTML("beforeend", livingStreamRowsHtml(changes, t, tf));
        } else {
          _livingStreamLast = { measured: true, reason: null, changes: changes.slice(), total: d.total };
          box.innerHTML = livingStreamRowsHtml(changes, t, tf);
        }
        _livingStreamOffset += d.count;
        _livingStreamCap();
      } catch (e) {
        box.innerHTML = _livingFailHtml(e.message, t);
      }
    }

    async function livingShowDiff(revisionId, btn) {
      const t = _livingT(), tf = _livingTf();
      const box = $("living-diff-" + revisionId);
      if (!box) return;
      if (box.innerHTML) { box.innerHTML = ""; if (btn) btn.textContent = t("Show diff"); return; }
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        const d = await api(`/api/wiki/lane/revisions/${Number(revisionId)}`);
        _livingDiffs.set(Number(revisionId), d);
        box.innerHTML = livingDiffBoxHtml(d, t, tf);
        if (btn) btn.textContent = t("Hide diff");
      } catch (e) {
        box.innerHTML = _livingFailHtml(e.message, t);
      }
    }

    function renderLivingPages() {
      const t = _livingT();
      const box = $("living-pages"), d = _livingPagesLast;
      if (!box || !d) return;
      const pages = (d.pages || []).filter((p) => p.watched !== false);
      box.innerHTML = pages.length
        ? pages.map((p) => `<button class="tiny secondary living-page" onclick="openWikiTC(${Number(p.id)}, ${esc(JSON.stringify(String(p.title || "")))}, ${esc(JSON.stringify(String(p.wiki || "")))})"`
            + ` title="${esc(t("See this page's tracked revision history — the stored edits, newest first, with each diff."))}">`
            + `${esc(p.wiki ? p.wiki + " · " : "")}${esc(p.title || "?")} <span class="muted">${esc(String(p.revisions || 0))}</span></button>`).join(" ")
        : `<div class="muted">${esc(t("No pages tracked yet. Add them in Settings → Wikipedia."))}</div>`;
    }

    async function loadLivingPages() {
      const box = $("living-pages");
      if (!box) return;
      try {
        _livingPagesLast = await api("/api/wiki/pages");
        renderLivingPages();
      } catch (e) {
        _livingPagesLast = null;
        box.innerHTML = _livingFailHtml(e.message, _livingT());
      }
    }

    function renderLivingLaw() {
      const t = _livingT();
      const box = $("living-law-changes"), d = _livingLawLast;
      if (!box || !d) return;
      // The tracker's own caveat, visible (informed consent): a mirror, not the law.
      box.innerHTML = (d.caveat ? `<p class="card-caveat">${esc(t(d.caveat))}</p>` : "")
        + livingLawRowsHtml(d.changes, t);
    }

    async function loadLivingLaw() {
      const t = _livingT();
      const box = $("living-law-changes");
      if (!box) return;
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        _livingLawLast = await api("/api/law/changes?limit=50");
        renderLivingLaw();
      } catch (e) {
        _livingLawLast = null;
        box.innerHTML = _livingFailHtml(e.message, t);
      }
    }

    function renderLivingMaps() {
      const box = $("living-osm-regions"), d = _livingMapsLast;
      if (!box || !d) return;
      box.innerHTML = livingMapRowsHtml(d.downloads, _livingT());
    }

    async function loadLivingMaps() {
      const box = $("living-osm-regions");
      if (!box) return;
      try {
        _livingMapsLast = await api("/api/geo/downloads");
        renderLivingMaps();
      } catch (e) {
        _livingMapsLast = null;
        box.innerHTML = _livingFailHtml(e.message, _livingT());
      }
    }

    // A language switch (app-boot.js): every panel redraws from the payload it last drew
    // and re-opens what the reader had open -- the stream diffs (from the payloads they
    // were opened with) and the law folds (by change id). NEVER a fetch: a diff whose
    // payload is not held (still loading, or failed) is left closed rather than re-asked.
    function repaintLivingFromCache() {
      const t = _livingT(), tf = _livingTf();
      renderLivingOverview();
      const stream = $("living-stream");
      if (stream && _livingStreamLast) {
        const open = [];
        stream.querySelectorAll('[id^="living-diff-"]').forEach((box) => {
          const id = Number(box.id.slice("living-diff-".length));
          if (box.innerHTML && _livingDiffs.has(id)) open.push(id);
        });
        renderLivingStream();
        open.forEach((id) => {
          const box = $("living-diff-" + id);
          if (!box) return;
          box.innerHTML = livingDiffBoxHtml(_livingDiffs.get(id), t, tf);
          const btn = stream.querySelector(`button[data-diff-rev="${id}"]`);
          if (btn) btn.textContent = t("Hide diff");
        });
      }
      renderLivingPages();
      const law = $("living-law-changes");
      if (law && _livingLawLast) {
        const open = new Set([...law.querySelectorAll("details[data-change-id][open]")]
          .map((el) => el.getAttribute("data-change-id")));
        renderLivingLaw();
        law.querySelectorAll("details[data-change-id]").forEach((el) => {
          if (open.has(el.getAttribute("data-change-id"))) el.open = true;
        });
      }
      renderLivingMaps();
    }
