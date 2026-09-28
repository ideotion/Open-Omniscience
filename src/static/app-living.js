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

    // The allpages walk (Q701 = c; S05-06): what it is doing, and each edition's pages seen
    // of the edition's OWN article count. "N of M", never a bar or a percentage: the edition
    // counts a slightly different set than the walk lists (redirects, pages without links),
    // so the ratio can pass 100% and a bar would draw that as a finished job that is not.
    const _LIVING_WALK_STATE = {
      off: "Off", walking: "Walking", paused: "Paused", waiting: "Waiting",
      complete: "Complete", not_started: "Not started yet", not_running: "Not running now",
    };
    const _LIVING_WALK_WHY = {
      network_off: "Airplane mode is on.",
      transport_unavailable: "Protected mode has no usable proxy, and the walk never goes direct.",
      storage_budget_spent: "The lane's storage budget is spent.",
      connection_failed: "The connection or the proxy did not answer.",
      service_busy: "The wiki asked clients to slow down.",
      request_refused: "The wiki refused the request.",
      malformed_response: "The answer could not be read.",
    };
    const _LIVING_TRANSPORT = {
      direct: "direct connection", proxy: "your proxy", pool: "your proxy pool",
    };

    function _livingCount(n) {
      return typeof fmtNum === "function" ? fmtNum(Number(n) || 0, 0) : String(Number(n) || 0);
    }

    function livingWalkGroup(src, t, tf) {
      const w = src.walk || {};
      const stateKey = w.enabled === false ? "off" : (w.state || "not_running");
      const word = _LIVING_WALK_STATE[stateKey] ? t(_LIVING_WALK_STATE[stateKey]) : String(stateKey);
      // The reader's own separator (ooLabelText): a welded ": " reads wrong in a locale
      // whose colon is full-width (2026-09-27 re-walk O-5).
      const value = w.reason && _LIVING_WALK_WHY[w.reason]
        ? ooLabelText(word, t(_LIVING_WALK_WHY[w.reason])) : word;
      // "State", never the group's own title again (the repeated-title defect the
      // 2026-09-25 Chromium walk found on "Pages you track").
      const facts = [{
        label: t("State"), value,
        hover: w.enabled === false
          ? t("The walk lists every article title in the editions you follow, 50 per request, one request at a time. It is off: switch it on in Settings → Wikipedia.")
          : t("The walk lists every article title in the editions you follow, 50 per request, one request at a time, and stores titles, sizes and Wikidata ids, never text. It runs only while the live stream runs."),
      }];
      if (w.measured !== true) return { title: t("Page walk"), facts };
      facts.push(
        { label: t("Pages seen"), value: _livingCount(w.pages_seen),
          hover: t("Distinct article pages the walk has listed in its current pass, across every edition.") },
        { label: t("Requests answered"), value: _livingCount(w.requests),
          hover: t("Answers the walk read in full, across every edition. A refused request is not counted here: it is recorded on its edition, with its reason.") },
        { label: t("Answers weighed"), value: humanBytes(w.response_bytes || 0),
          hover: t("The size of the JSON the wiki sent back, as it was read.") },
      );
      for (const e of (w.editions || [])) {
        // Q302 / Q306: the 639-2/T code is what shows, the name in the UI language is the
        // hover -- the same rule the stream's own rows follow through ooLangCell.
        const code = (typeof ooLangCode === "function" ? ooLangCode(e.edition) : "") || String(e.edition);
        const name = typeof ooLangName === "function" ? ooLangName(e.edition, "") : "";
        let value = typeof e.edition_articles === "number"
          ? tf("{n} of {m}", { n: _livingCount(e.pages_seen), m: _livingCount(e.edition_articles) })
          : tf("{n} of an unknown total", { n: _livingCount(e.pages_seen) });
        if (e.completed_at) value += " · " + t("pass complete");
        else if (e.consecutive_failures > 0) value += " · " + t("waiting");
        const refusal = e.consecutive_failures > 0 && _LIVING_WALK_WHY[e.last_error]
          ? " " + t(_LIVING_WALK_WHY[e.last_error]) + " " + t("It is asked again after a pause that doubles each time, up to an hour.")
          : "";
        const explain = t("Pages the walk listed in this edition, of the edition's own article count. The edition counts its articles its own way, so the first number can pass the second.");
        facts.push({ label: code, value,
          hover: (name && name !== code ? ooLabelText(name, explain) : explain) + refusal });
      }
      const rates = (w.throughput && w.throughput.by_transport) || {};
      for (const k of Object.keys(rates)) {
        const r = rates[k] || {};
        if (!r.hours) continue;
        const via = _LIVING_TRANSPORT[k] ? t(_LIVING_TRANSPORT[k]) : String(k);
        facts.push({ label: tf("Measured rate, {transport}", { transport: via }),
          value: tf("{n} pages an hour", { n: _livingCount(Math.round(r.pages / r.hours)) }),
          hover: t("Pages listed per hour, over the hours in the last 7 days with at least one walk request on this transport. An hour the walk ran for only part of counts whole, so this reads low, never high.") });
      }
      return { title: t("Page walk"), facts };
    }

    // Q707's WARM tier (S05-06's S1): the newest text of every OTHER page the stream reports
    // changed, latest + previous (Q710). Counts only. The share of the budget it leaves to
    // the followed pages is a proposed default, and the hover says so.
    const _LIVING_WARM_STATE = {
      off: "Off", fetching: "Fetching", paused: "Paused", waiting: "Waiting", caught_up: "Caught up",
      not_started: "Not started yet", not_running: "Not running now",
    };
    const _LIVING_WARM_WHY = {
      network_off: "Airplane mode is on.",
      transport_unavailable: "Protected mode has no usable proxy, and the lane never goes direct.",
      storage_budget_spent: "The lane's storage budget is spent.",
      warm_share_spent: "Changed pages have used their share of the storage budget; the rest is kept for the pages you follow.",
      connection_failed: "The connection or the proxy did not answer.",
      service_busy: "The wiki asked clients to slow down.",
      request_refused: "The wiki refused the request.",
      malformed_response: "The answer could not be read.",
    };

    function livingWarmGroup(src, t, tf) {
      const w = src.warm || {};
      const stateKey = w.enabled === false ? "off" : (w.state || "not_running");
      const word = _LIVING_WARM_STATE[stateKey] ? t(_LIVING_WARM_STATE[stateKey]) : String(stateKey);
      const value = w.reason && _LIVING_WARM_WHY[w.reason]
        ? ooLabelText(word, t(_LIVING_WARM_WHY[w.reason])) : word;
      const facts = [{
        label: t("State"), value,
        hover: w.enabled === false
          ? t("The lane can fetch the newest text of every other page the stream reports changed, 50 pages a request. That fetching is off: switch it on in Settings → Wikipedia.")
          : t("The lane fetches the newest text of every other page the stream reports changed, 50 pages a request, the longest-waiting first, and keeps each page's latest and previous text. It runs only while the live stream runs."),
      }];
      if (w.measured !== true) return { title: t("Other changed pages"), facts };
      facts.push(
        { label: t("Pages with text"), value: _livingCount(w.pages_with_text),
          hover: t("Pages holding a stored text: the latest this machine fetched and the one before it. A page deleted later keeps its text.") },
        { label: t("Waiting for text"), value: _livingCount(w.due),
          hover: t("Changed pages whose newest text has not been fetched yet, across every edition.") },
        { label: t("Texts fetched"), value: _livingCount(w.texts_fetched),
          hover: t("Every text stored. A page fetched three times counts three.") },
        { label: t("Now followed"), value: _livingCount(w.promoted),
          hover: t("Pages that became pages you follow after they changed. Every version of them is kept from then on, and the texts fetched before stay.") },
        { label: t("Requests answered"), value: _livingCount(w.requests),
          hover: t("Answers read in full, across every edition. A refused request is not counted here.") },
        { label: t("Answers weighed"), value: humanBytes(w.response_bytes || 0),
          hover: t("The size of the JSON the wiki sent back, as it was read.") },
      );
      if (typeof w.share === "number") {
        facts.push({ label: t("Stops at"), value: tf("{pct}% of the budget", { pct: Math.round(w.share * 100) }),
          hover: t("These texts stop when the lane file holds this share of its storage budget, and the rest is kept for the pages you follow. The share is a proposed default, not a ruling.") });
      }
      const waiting = w.waiting || {};
      for (const e of (w.editions || [])) {
        const code = (typeof ooLangCode === "function" ? ooLangCode(e.edition) : "") || String(e.edition);
        const name = typeof ooLangName === "function" ? ooLangName(e.edition, "") : "";
        let row = tf("{n} with text · {m} to fetch", { n: _livingCount(e.pages_with_text), m: _livingCount(e.due) });
        const token = waiting[e.edition];
        if (token) row += " · " + t("waiting");
        const refusal = token && _LIVING_WARM_WHY[token]
          ? " " + t(_LIVING_WARM_WHY[token]) + " " + t("It is asked again after a pause that doubles each time, up to an hour.")
          : "";
        const explain = t("Pages holding a text in this edition, and changed pages still waiting for theirs.");
        facts.push({ label: code, value: row,
          hover: (name && name !== code ? ooLabelText(name, explain) : explain) + refusal });
      }
      return { title: t("Other changed pages"), facts };
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
      // Q707's order: the followed pages (the stream), the other changed pages, the tail.
      return [
        { title: t("Live stream"), facts: stream },
        livingWarmGroup(src, t, tf),
        livingWalkGroup(src, t, tf),
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
            + ` <button class="tiny secondary" data-diff-rev="${Number(c.revision_id)}" data-on-click="livingShowDiff(${Number(c.revision_id)}, this)">${esc(t("Show diff"))}</button>`;
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
      else if (kind === "law") { loadLivingLaw(); loadLawEvolution(); }
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

    // A switch Living sources shows was saved elsewhere (Settings → Wikipedia): a view already
    // drawn re-reads its overview, so it never keeps the state from before the change. A view
    // never opened is left alone -- it reads everything when it opens.
    function livingRefreshIfShown() {
      if (_livingOverview) loadLivingOverview();
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
        ? pages.map((p) => `<button class="tiny secondary living-page" data-on-click="openWikiTC(${Number(p.id)}, ${esc(JSON.stringify(String(p.title || "")))}, ${esc(JSON.stringify(String(p.wiki || "")))})"`
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

    // The evolution surface (row G) loads beside the change stream, not inside it: the
    // stream is one fetch with its own failure line, and each panel below has its own.
    function loadLawEvolution() {
      _wireLawEvolution();
      loadLawWeek();
      loadLivingLawDocs();
      loadLawAmendMap();
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

    // ---- 0.5 row G: the law evolution surface (brief S05-07) ------------------------ //
    // Every block reads what this machine stored; none of them fetches from the web, so
    // none passes the network consent gate (invariant #14 gates egress, not local reads).
    // Each keeps its last payload so a language switch redraws without a request, and
    // each prints its method and caveat VISIBLY (informed consent), never on hover only.
    let _lawWeekLast = null, _lawDocsLast = null, _lawPitLast = null, _lawTopicLast = null, _lawMapLast = null;
    let _lawReader = null, _wikiReader = null, _lawTc = null;

    // The one dating vocabulary, worded once for every surface (src/law/versions.py).
    function lawDatingWords(dating, t) {
      if (dating === "official") return t("as the document states it");
      if (dating === "observed") return t("dated by observation — this instance saw the text on this day; the source stated no date of its own");
      return t("recorded before this app tracked how the date was determined");
    }
    function lawSpan(h, tf) {
      return h.valid_to
        ? tf("from {from} until {until}", { from: h.valid_from || "—", until: h.valid_to })
        : tf("from {from} (the newest held)", { from: h.valid_from || "—" });
    }
    function lawMethodHtml(d, t) {
      return (d.caveat ? `<p class="card-caveat">${esc(t(d.caveat))}</p>` : "")
        + (d.method ? `<p class="hint">${esc(t(d.method))}</p>` : "");
    }

    function _wireLawEvolution() {
      const pit = $("law-pit-form");
      if (pit && !pit._wired) {
        pit._wired = true;
        pit.addEventListener("submit", (e) => { e.preventDefault(); lawPitSearch(); });
      }
      const topic = $("law-topic-form");
      if (topic && !topic._wired) {
        topic._wired = true;
        topic.addEventListener("submit", (e) => { e.preventDefault(); lawTopicCompare(); });
      }
      const docs = $("living-law-docs");
      if (docs && !docs._wired) {
        docs._wired = true;
        docs.addEventListener("click", (e) => {
          const b = e.target.closest && e.target.closest("[data-law-doc]");
          if (b) openLawVersions(Number(b.getAttribute("data-law-doc")));
        });
      }
    }

    // -- analytic 5: what changed this week in the laws I follow --
    function renderLawWeek() {
      const t = _livingT(), tf = _livingTf();
      const box = $("living-law-week"), d = _lawWeekLast;
      if (!box || !d) return;
      const rows = (d.items || []).map((i) => `<div class="living-row">`
        + `<a href="${esc(i.reader_url)}" target="_blank" rel="noopener">${esc(i.title || "?")}</a>`
        + ` <span class="muted">${ooCountryCell(i.jurisdiction)}${i.language ? " · " + ooLangCell(i.language) : ""}</span>`
        + ` · ${esc(tf("{n} new versions captured", { n: fmtNum(i.changes, 0) }))}`
        + ` · <span class="muted">${esc(livingWhen(i.newest, t))}</span></div>`).join("");
      box.innerHTML = (rows || `<div class="muted">${esc(tf("Nothing you follow changed in the last {n} days.", { n: d.window_days }))}</div>`)
        + `<p class="hint">${esc(tf("{n} documents followed · {from} to {to}", { n: fmtNum(d.followed_documents, 0), from: d.window_from, to: d.window_to }))}</p>`
        + lawMethodHtml(d, t);
    }
    async function loadLawWeek() {
      const box = $("living-law-week");
      if (!box) return;
      try { _lawWeekLast = await api("/api/law/this-week?days=7"); renderLawWeek(); }
      catch (e) { _lawWeekLast = null; box.innerHTML = _livingFailHtml(e.message, _livingT()); }
    }

    // -- point-in-time search (Q916) --
    function renderLawPit() {
      const t = _livingT(), tf = _livingTf();
      const box = $("law-pit-results"), d = _lawPitLast;
      if (!box || !d) return;
      if (d.status === "no-lane") { box.innerHTML = `<div class="muted">${esc(t(d.reason))}</div>`; return; }
      const cov = d.coverage || {};
      const head = `<p class="hint">${esc(d.on
        ? tf("{n} versions in force on {day} contain these words, in {docs} documents.", { n: fmtNum(d.matched || 0, 0), day: d.on, docs: fmtNum(d.documents || 0, 0) })
        : tf("{n} stored versions contain these words, in {docs} documents.", { n: fmtNum(d.matched || 0, 0), docs: fmtNum(d.documents || 0, 0) }))}</p>`;
      const covLine = cov.versions_total != null
        ? `<p class="hint">${esc(tf("Searched {searched} of {total} stored versions; {missing} cannot be searched (no stored text, or no version key); {pending} are still being indexed.", {
            searched: fmtNum(cov.versions_searchable || 0, 0), total: fmtNum(cov.versions_total || 0, 0),
            missing: fmtNum(cov.versions_without_text || 0, 0), pending: fmtNum(cov.versions_pending || 0, 0) }))}</p>`
        : "";
      const hits = (d.hits || []).map((h) => {
        const others = (h.other_languages || []).map((o) => o.id != null
          ? `<a href="/api/law/documents/${Number(o.id)}/view" target="_blank" rel="noopener">${ooLangCell(o.language)}</a>`
          : `<span class="muted">${ooLangCell(o.language)}</span>`).join(" ");
        return `<div class="living-row" data-i18n-dyn>`
          + `<a href="${esc(h.reader_url)}" target="_blank" rel="noopener">${esc(h.title || "?")}</a>`
          + ` <span class="muted">${ooCountryCell(h.jurisdiction)}${h.language ? " · " + ooLangCell(h.language) : ""}</span>`
          + `<div>${esc(lawSpan(h, tf))} <span class="muted">(${esc(lawDatingWords(h.dating, t))})</span>`
          + (h.current ? ` · ${esc(t("the newest held version"))}` : "") + `</div>`
          + `<div class="muted" style="unicode-bidi:plaintext">${esc(h.snippet || "")}</div>`
          + (others ? `<div>${esc(t("Also tracked in"))} ${others}</div>` : "")
          + `</div>`;
      }).join("");
      box.innerHTML = head + covLine + (hits || `<div class="muted">${esc(t("No held version contains these words on that day."))}</div>`)
        + (d.truncated ? `<p class="hint">${esc(t("More versions matched than are shown; narrow the words."))}</p>` : "")
        + lawMethodHtml(d, t);
    }
    async function lawPitSearch() {
      const t = _livingT();
      const box = $("law-pit-results"), q = ($("law-pit-q") || {}).value || "", on = ($("law-pit-on") || {}).value || "";
      if (!box) return;
      if (!q.trim()) { box.innerHTML = `<div class="muted">${esc(t("Type the words to find."))}</div>`; return; }
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try {
        _lawPitLast = await api(`/api/law/versions/search?q=${encodeURIComponent(q)}` + (on ? `&on=${encodeURIComponent(on)}` : ""));
        renderLawPit();
      } catch (e) { _lawPitLast = null; box.innerHTML = _livingFailHtml(e.message, t); }
    }

    // -- the documents list and the ONE version reader (Q918 + note) --
    function renderLivingLawDocs() {
      const t = _livingT();
      const box = $("living-law-docs"), d = _lawDocsLast;
      if (!box || !d) return;
      const docs = d.documents || [];
      box.innerHTML = docs.length
        ? docs.map((x) => `<button type="button" class="tiny secondary living-page" data-law-doc="${Number(x.id)}"`
            + ` title="${esc(t("Compare this document's stored versions side by side."))}">`
            + `${ooCountryCell(x.jurisdiction)} · ${esc(x.title || "?")} <span class="muted">${esc(String(x.revisions || 0))}</span></button>`).join(" ")
        : `<div class="muted">${esc(t("No legal documents tracked yet."))}</div>`;
    }
    async function loadLivingLawDocs() {
      const box = $("living-law-docs");
      if (!box) return;
      try { _lawDocsLast = await api("/api/law/documents"); renderLivingLawDocs(); }
      catch (e) { _lawDocsLast = null; box.innerHTML = _livingFailHtml(e.message, _livingT()); }
    }
    function openLawVersions(id) {
      const host = $("law-tc-versions");
      if (!host || typeof ooVersionReader !== "function") return;
      const doc = ((_lawDocsLast && _lawDocsLast.documents) || []).find((x) => x.id === id);
      _lawTc = { id, title: doc ? doc.title : "" };
      const ttl = $("law-tc-title");
      if (ttl) ttl.textContent = doc ? `${ooCountryCode(doc.jurisdiction)} · ${doc.title}` : "";
      const base = `/api/law/documents/${Number(id)}`;
      if (_lawReader) _lawReader.load(base);
      else _lawReader = ooVersionReader(host, base, { onLanguage: (other) => openLawVersions(other) });
      const sec = $("law-tc");
      if (sec && typeof sec.scrollIntoView === "function") sec.scrollIntoView({ block: "start" });
    }
    // The Wikipedia panel's tracked page gets the SAME reader (called by openWikiTC).
    function livingMountWikiVersions(pageId) {
      const host = $("wiki-tc-versions");
      if (!host || typeof ooVersionReader !== "function" || pageId == null) return;
      const base = `/api/wiki/pages/${Number(pageId)}`;
      if (_wikiReader) _wikiReader.load(base);
      else _wikiReader = ooVersionReader(host, base, {});
    }

    // -- analytic 3: a topic across jurisdictions --
    function renderLawTopic() {
      const t = _livingT();
      const box = $("law-topic-results"), d = _lawTopicLast;
      if (!box || !d) return;
      if (d.status === "no-lane") { box.innerHTML = `<div class="muted">${esc(t(d.reason))}</div>`; return; }
      const rows = (d.rows || []).map((r) => `<tr><td>${ooCountryCell(r.jurisdiction)}</td>`
        + `<td>${esc(fmtNum(r.versions_matching, 0))}</td><td>${esc(fmtNum(r.documents_matching, 0))}</td>`
        + `<td>${esc(fmtNum(r.documents_current_matching, 0))}</td><td>${esc(fmtNum(r.tracked_documents, 0))}</td></tr>`).join("");
      box.innerHTML = (rows
        ? `<table class="living-table"><thead><tr><th>${esc(t("Jurisdiction"))}</th><th>${esc(t("Versions containing it"))}</th>`
          + `<th>${esc(t("Documents containing it"))}</th><th>${esc(t("In the newest held version"))}</th><th>${esc(t("Documents tracked"))}</th></tr></thead><tbody>${rows}</tbody></table>`
        : `<div class="muted">${esc(t("No tracked law contains these words."))}</div>`) + lawMethodHtml(d, t);
    }
    async function lawTopicCompare() {
      const t = _livingT();
      const box = $("law-topic-results"), q = ($("law-topic-q") || {}).value || "";
      if (!box) return;
      if (!q.trim()) { box.innerHTML = `<div class="muted">${esc(t("Type the words to find."))}</div>`; return; }
      box.innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      try { _lawTopicLast = await api(`/api/law/topics?q=${encodeURIComponent(q)}`); renderLawTopic(); }
      catch (e) { _lawTopicLast = null; box.innerHTML = _livingFailHtml(e.message, t); }
    }

    // -- analytic 4: amendment activity on the equal-area map, with its vintage --
    async function renderLawAmendMap() {
      const t = _livingT(), tf = _livingTf();
      const d = _lawMapLast, host = $("law-amend-map");
      if (!d || !host) return;
      const vint = $("law-amend-vintage");
      if (vint) {
        vint.textContent = d.newest_capture
          ? tf("Amendments captured from {from} to {to}. The newest capture counted: {newest}.", { from: d.window_from, to: d.window_to, newest: d.newest_capture.slice(0, 10) })
          : tf("No amendment was captured from {from} to {to}.", { from: d.window_from, to: d.window_to });
      }
      const off = $("law-amend-off");
      if (off) {
        off.innerHTML = (d.not_on_the_map || []).length
          ? `<p class="hint">${esc(ooLabelText(t("Not on the map (not a country)"), d.not_on_the_map.map((r) =>
              tf("{j}: {n} amendments, {docs} documents tracked", { j: ooCountryCode(r.jurisdiction), n: fmtNum(r.amendments, 0), docs: fmtNum(r.tracked_documents, 0) })).join(" · ")))}</p>`
          : "";
      }
      if (typeof ooMap !== "function") return;
      const names = {};
      Object.keys(d.values || {}).forEach((iso) => { names[iso] = typeof ooRegionName === "function" ? ooRegionName(iso) : iso; });
      await ooMap(host, {
        values: d.values || {}, names,
        label: t("Amendments captured"),
        valueLabel: (iso, v) => tf("{n} amendments captured · {docs} documents tracked", { n: fmtNum(v, 0), docs: fmtNum((d.tracked_documents || {})[iso] || 0, 0) }),
        caveat: t(d.caveat),
      });
      host.insertAdjacentHTML("beforeend", `<p class="hint">${esc(t(d.method))}</p>`);
    }
    async function loadLawAmendMap() {
      const host = $("law-amend-map");
      if (!host) return;
      try { _lawMapLast = await api("/api/law/amendment-map?days=365"); await renderLawAmendMap(); }
      catch (e) { _lawMapLast = null; host.innerHTML = _livingFailHtml(e.message, _livingT()); }
    }

    function repaintLawEvolutionFromCache() {
      renderLawWeek(); renderLivingLawDocs(); renderLawPit(); renderLawTopic();
      const tc = $("law-tc-title");
      if (tc && _lawTc && !_lawTc.title) tc.textContent = "";
      void renderLawAmendMap();
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
      if (typeof repaintLawEvolutionFromCache === "function") repaintLawEvolutionFromCache();
    }

    // --- One held Wikipedia version, read before it is added (R52) --------------------
    // The Wikipedia lane's search finds texts the corpus does not hold: a changed page's
    // latest and previous text (WARM) and the earlier versions of the pages the stream
    // follows. A hit opens THAT version here, and «Add to corpus» adds it as one article,
    // one click per version: the lane's texts never become articles by themselves (Q719).
    // The renderers are pure (payload, t, tf) -> HTML, driven in node
    // (tests/lane_version_node_test.js); openLaneVersion and laneVersionAdd alone touch
    // the DOM, and their network is loopback.
    const _LANE_WHICH = {
      latest: "latest text held",
      previous: "previous text held",
      earlier: "earlier version",
      newest: "newest version",
    };
    // A token outside the four is shown as the server sent it, never mapped onto the
    // nearest known word (the rule Living's change kinds follow).
    function laneWhichText(which, t) {
      return _LANE_WHICH[which] ? t(_LANE_WHICH[which]) : String(which || "");
    }

    // A held version as "edition · which text · date": the one line a palette row and a
    // Search tab row both carry, so the two cannot describe one hit two ways.
    function laneHitSub(it, t) {
      return [it.edition || "", laneWhichText(it.which, t), (it.revised_at || "").slice(0, 10)]
        .filter(Boolean).join(" · ");
    }

    // The command palette's rows for the lane's hits: beside the corpus hits, marked as
    // Wikipedia, each opening THAT version. `run` only opens the dialog below.
    function laneOmniRows(lane, t) {
      const items = (lane && lane.available && Array.isArray(lane.items)) ? lane.items : [];
      return items.map((it) => ({
        label: it.title || ("#" + it.page_id),
        sub: laneHitSub(it, t),
        run: () => openLaneVersion(it.source, it.owner_id, it.revid),
      }));
    }

    function laneVersionMetaHtml(d, t, tf) {
      return esc([
        d.edition || "",
        laneWhichText(d.which, t),
        d.revised_at ? livingWhen(d.revised_at, t) : "",
        tf("revision {revid}", {revid: d.revid}),
      ].filter(Boolean).join(" · "));
    }

    // Visible by default, never behind a toggle: where this text lives, and what adding it
    // does. The newest version of a followed page is already the corpus article.
    function laneVersionNotesHtml(d, t) {
      const notes = [d.newest_followed
        ? t("This is the newest version of a page the stream follows. Your corpus already holds it as an article.")
        : t("Held on this machine by the Wikipedia lane, not in your corpus. Adding it creates one article for this exact version.")];
      if (d.deleted) notes.push(t("The page has been deleted on Wikipedia since. Its text stays here."));
      return notes.map((n) => `<div class="hint">${esc(n)}</div>`).join("");
    }

    // Invariant #6: the outbound link's visible text IS the full address, and the
    // capture-phase guard (#7) still confirms before it opens.
    function laneVersionOutHtml(d, t) {
      if (!d.url) return "";
      return `<div class="muted small">${esc(t("The transparent outbound link — its text is the full address; opening it leaves this machine:"))}</div>`
        + `<a href="${esc(safeUrl(d.url))}" target="_blank" rel="noopener noreferrer" dir="ltr" style="word-break:break-all">${esc(d.url)}</a>`;
    }

    // What «Add to corpus» did. Every outcome that names an article links to it in the
    // local reader, so "already there" is one click from the article it means.
    function laneAddedHtml(r, t) {
      const said = {
        created: "Added to your corpus as its own article.",
        exists: "This version is already in your corpus.",
        same_text: "Your corpus already holds an article with exactly these words.",
        "skipped-empty-after-strip": "Nothing to add: no text is left once the wiki markup is removed.",
      }[r && r.status];
      const words = said ? t(said) : String((r && r.status) || "");
      const link = (r && r.article_id != null)
        ? ` <a href="/api/articles/${encodeURIComponent(r.article_id)}/view" target="_blank" rel="noopener">${esc(t("Open it in the reader"))}</a>`
        : "";
      return `<div class="note${r && r.status === "created" ? " ok" : ""}">${esc(words)}${link}</div>`;
    }

    // The routes' named refusals, in words; anything else is the server's own message.
    function laneFailText(e, t) {
      const said = {
        "not-held": "This version is no longer held on this machine.",
        "no-title": "The lane holds no title for this page, and an article needs one.",
        "lane-unreadable": "The Wikipedia lane could not be read just now.",
        "lane-never-run": "The Wikipedia lane has not run on this machine yet.",
      }[e && e.detail];
      return said ? t(said) : String((e && e.message) || e || "");
    }

    let _laneVersionLast = null;   // what the dialog drew: {d, added, failed, busy}
    let _laneVersionSeq = 0;       // a later open supersedes an earlier one still loading
    let _laneVersionWired = false;
    function _laneVersionWire() {
      if (_laneVersionWired || !$("lane-version")) return;
      _laneVersionWired = true;
      $("lv-close").addEventListener("click", () => $("lane-version").close());
      $("lv-add").addEventListener("click", () => laneVersionAdd());
    }

    function renderLaneVersion() {
      const s = _laneVersionLast;
      if (!s || !$("lane-version")) return;
      const t = _livingT(), tf = _livingTf(), d = s.d;
      $("lv-title").textContent = d.title || ("#" + d.page_id);
      $("lv-meta").innerHTML = laneVersionMetaHtml(d, t, tf);
      $("lv-notes").innerHTML = laneVersionNotesHtml(d, t);
      $("lv-text").textContent = d.text || "";
      $("lv-out").innerHTML = laneVersionOutHtml(d, t);
      $("lv-result").innerHTML = s.added ? laneAddedHtml(s.added, t)
        : (s.failed ? `<div class="note err">${esc(laneFailText(s.failed, t))}</div>` : "");
      $("lv-add").disabled = Boolean(s.added || s.busy);
    }

    async function openLaneVersion(source, ownerId, revid) {
      const dlg = $("lane-version");
      if (!dlg) return;
      _laneVersionWire();
      const t = _livingT(), seq = ++_laneVersionSeq;
      _laneVersionLast = null;
      $("lv-title").textContent = "";
      $("lv-meta").textContent = t("Loading…");
      ["lv-notes", "lv-out", "lv-result"].forEach((id) => { $(id).innerHTML = ""; });
      $("lv-text").textContent = "";
      $("lv-add").disabled = true;
      if (!dlg.open) dlg.showModal();
      const q = new URLSearchParams({source: String(source), owner_id: String(ownerId), revid: String(revid)});
      try {
        const d = await api("/api/wiki/lane/version?" + q.toString());
        if (seq !== _laneVersionSeq) return;
        _laneVersionLast = {d, added: null, failed: null, busy: false};
        renderLaneVersion();
      } catch (e) {
        if (seq !== _laneVersionSeq) return;
        $("lv-meta").innerHTML = `<div class="note err">${esc(laneFailText(e, t))}</div>`;
      }
    }

    // ONE version, on one click: the route adds it only when the lane still holds it, and
    // answers "already there" rather than storing a second copy.
    async function laneVersionAdd() {
      const s = _laneVersionLast;
      if (!s || s.added || s.busy) return;
      s.busy = true; s.failed = null;
      renderLaneVersion();
      try {
        s.added = await api("/api/wiki/lane/add-to-corpus", {method: "POST",
          body: JSON.stringify({source: s.d.source, owner_id: s.d.owner_id, revid: s.d.revid})});
        _laneSearchNoteAdded(s.d, s.added);
      } catch (e) {
        s.failed = e;
      } finally {
        s.busy = false;
        if (_laneVersionLast === s) renderLaneVersion();
      }
    }

    // A language switch (app-boot.js) redraws the open dialog from what it holds, never a
    // fetch: its lines are composed with t()/tf(), out of the i18n walker's reach.
    function repaintLaneVersionFromCache() {
      const dlg = $("lane-version");
      if (dlg && dlg.open && _laneVersionLast) renderLaneVersion();
    }

    // --- The Search tab's Wikipedia section (R52) -------------------------------------
    // The one search box's other half. The Search tab searches the lane's held texts with
    // the same words and lists them BESIDE the corpus's results, marked as Wikipedia and
    // never ranked into them: two BM25 scores from two indexes are not one scale. What was
    // searched is said with every answer, above its hits, so an empty list never reads as
    // «Wikipedia does not say this» (R52's owed line). The corpus's filters -- the source,
    // language and time boxes, and the query's source:, author:, url:, tag: and title:= --
    // describe ARTICLES and never reach these texts; whenever one is set the section says
    // so rather than letting a filtered corpus list sit beside an unfiltered one unmarked.
    // Pure renderers first, driven in node like the ones above.

    // A snippet arrives as PARTS (lane_search.snippet), each carrying its own text, so no
    // offset is counted by a browser that counts characters differently from the server.
    function laneSnippetHtml(parts) {
      if (!Array.isArray(parts)) return "";
      return parts.map((p) => ((p && p.hit) ? `<mark>${esc(p.text)}</mark>` : esc((p && p.text) || ""))).join("");
    }

    // "en 10, fr 2": each edition with its pages, in the reader's own list punctuation.
    function _laneEditionsText(rows) {
      return ooListJoin((rows || []).map((r) => _ltrIsolate(r.edition) + " " + r.pages));
    }

    // What the search looked through: the texts THIS machine holds, per edition, and what
    // it could not look at yet. Counted from the route's `coverage`, never from the hits.
    function laneCoverageHtml(c, t) {
      if (!c) return "";
      const changed = c.changed_pages || {}, stream = c.stream_pages || {};
      const lines = [];
      if (changed.pages) {
        lines.push(ooLabelText(t("Other changed pages, by their latest and previous texts"),
          `${changed.pages} (${_laneEditionsText(changed.editions)})`));
      }
      if (stream.pages) {
        lines.push(ooLabelText(t("Pages the stream has followed, by their older versions"),
          `${stream.pages} (${_laneEditionsText(stream.editions)})`));
      }
      if (!lines.length) lines.push(t("The Wikipedia lane holds no text yet."));
      if (c.pending) lines.push(ooLabelText(t("Texts waiting to be indexed, not searched yet"), c.pending));
      if (c.failed) lines.push(ooLabelText(t("Texts set aside because they could not be read"), c.failed));
      if (c.warm_enabled === false) lines.push(t("Fetching other changed pages is off. Texts already fetched are kept."));
      return `<div class="hint">${esc(t("Searched only the texts the Wikipedia lane holds on this machine, not Wikipedia itself:"))}</div>`
        + `<ul class="hint lane-cov">${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
    }

    function _laneKey(it) { return `${it.source}:${it.owner_id}:${it.revid}`; }

    // One hit. Its title opens THAT version to read first; «Add to corpus» adds it, one
    // version per click. `st` is the section's state: what was added, failed, is in flight.
    function laneHitHtml(it, st, t) {
      const key = _laneKey(it);
      const added = (st && st.added) ? st.added[key] : null;
      const failed = (st && st.failed) ? st.failed[key] : null;
      const busy = Boolean(st && st.busy && st.busy[key]);
      const at = `data-source="${esc(it.source)}" data-owner="${esc(it.owner_id)}" data-revid="${esc(it.revid)}"`;
      const snip = laneSnippetHtml(it.snippet);
      const out = added ? laneAddedHtml(added, t)
        : (failed ? `<div class="note err">${esc(laneFailText(failed, t))}</div>` : "");
      return `<li class="living-row">`
        + `<div class="living-row-head"><button type="button" class="linkish" data-lane-open ${at}`
        + ` title="${esc(t("Read this version before adding it"))}">${esc(it.title || ("#" + it.page_id))}</button>`
        + `<span class="muted small">${esc(laneHitSub(it, t))}</span>`
        + `<button type="button" class="secondary tiny lane-add" data-lane-add ${at}${(added || busy) ? " disabled" : ""}>`
        + `${esc(t("Add to corpus"))}</button></div>`
        + (snip ? `<div class="small lane-snip" dir="auto">${snip}</div>` : "")
        + out + `</li>`;
    }

    // The whole section from its state. "" hides it: no words to search for, or the app
    // is locked and the corpus's search already says so.
    function laneSearchHtml(st, t, tf) {
      if (!st) return "";
      const head = `<h3>${esc(t("Wikipedia texts held on this machine"))}</h3>`;
      if (st.loading) return head + `<div class="hint">${esc(t("Loading…"))}</div>`;
      if (st.error) return head + `<div class="note err">${esc(laneFailText(st.error, t))}</div>`;
      const d = st.d;
      if (!d) return "";
      if (!d.available) {
        if (d.reason === "locked") return "";
        const said = {
          sqlite_too_old: "This system's SQLite is too old for the search index of these texts: it needs version 3.43 or newer.",
          index_not_built: "The search index of these texts is built the next time the Wikipedia lane runs.",
        }[d.reason];
        return head + `<div class="hint">${esc(said ? t(said) : laneFailText({detail: d.reason, message: d.reason}, t))}</div>`;
      }
      if (d.error === "query_invalid") {
        return head + `<div class="hint">${esc(t("These texts were not searched: their index could not read this query."))}</div>`;
      }
      if (d.total == null) return "";
      const items = Array.isArray(d.items) ? d.items : [];
      const count = d.total > items.length
        ? tf("{n} result(s) (showing {shown})", {n: d.total, shown: items.length})
        : tf("{n} result(s)", {n: d.total});
      const filtered = st.filtered || (Array.isArray(d.fields_not_applied) && d.fields_not_applied.length);
      const list = items.length
        ? `<ul class="lane-hits">${items.map((it) => laneHitHtml(it, st, t)).join("")}</ul>`
        : `<div class="muted">${esc(t("None of the texts the Wikipedia lane holds contains these words."))}</div>`;
      return head
        + `<div class="hint">${esc(count)}</div>`
        + laneCoverageHtml(d.coverage, t)
        + (filtered ? `<div class="hint">${esc(t("Your filters apply to the corpus only: these Wikipedia texts were searched by the words alone."))}</div>` : "")
        + list
        + `<div class="card-caveat">${esc(t("Older versions are found by the lines a later edit removed. A search whose words sit partly in kept lines and partly in removed ones finds neither version."))}</div>`;
    }

    let _laneSearchLast = null;   // what the section shows: {q, d, filtered, added, failed, busy}
    let _laneSearchSeq = 0;       // a later search supersedes an earlier one still loading
    let _laneSearchWired = false;
    function _laneSearchWire() {
      const host = $("search-lane");
      if (_laneSearchWired || !host) return;
      _laneSearchWired = true;
      // ONE delegated listener: the rows are redrawn on every answer and language switch.
      host.addEventListener("click", (ev) => {
        const b = ev.target.closest("button[data-source]");
        if (!b || !host.contains(b) || b.disabled) return;
        const source = b.dataset.source, ownerId = Number(b.dataset.owner), revid = Number(b.dataset.revid);
        if (b.hasAttribute("data-lane-add")) laneSearchAdd(source, ownerId, revid);
        else openLaneVersion(source, ownerId, revid);
      });
    }

    function renderLaneSearch() {
      const host = $("search-lane");
      if (!host) return;
      const html = laneSearchHtml(_laneSearchLast, _livingT(), _livingTf());
      host.innerHTML = html;
      host.hidden = !html;
    }

    // doSearch hands over the Search tab's words and whether a corpus-only filter is set,
    // and never awaits this: the corpus's list never waits for the lane's.
    async function searchLaneHits(q, filtered) {
      if (!$("search-lane")) return;
      _laneSearchWire();
      const seq = ++_laneSearchSeq;
      const words = String(q || "").trim();
      _laneSearchLast = words ? {q: words, loading: true, filtered: Boolean(filtered)} : null;
      renderLaneSearch();
      if (!words) return;
      let st;
      try {
        const d = await api("/api/wiki/lane/search?" + new URLSearchParams({q: words}).toString());
        st = {q: words, d, filtered: Boolean(filtered), added: {}, failed: {}, busy: {}};
      } catch (e) {
        st = {q: words, error: e, filtered: Boolean(filtered)};
      }
      if (seq !== _laneSearchSeq) return;
      _laneSearchLast = st;
      renderLaneSearch();
    }

    // ONE version per click, named by the row's own attributes: the version that row shows.
    async function laneSearchAdd(source, ownerId, revid) {
      const s = _laneSearchLast;
      if (!s || !s.added) return;
      const key = `${source}:${ownerId}:${revid}`;
      if (s.added[key] || s.busy[key]) return;
      s.busy[key] = true;
      delete s.failed[key];
      renderLaneSearch();
      try {
        s.added[key] = await api("/api/wiki/lane/add-to-corpus", {method: "POST",
          body: JSON.stringify({source, owner_id: ownerId, revid})});
      } catch (e) {
        s.failed[key] = e;
      } finally {
        delete s.busy[key];
        if (_laneSearchLast === s) renderLaneSearch();
      }
    }

    // An add made in the version window shows on that version's row here too.
    function _laneSearchNoteAdded(d, r) {
      const s = _laneSearchLast;
      if (!s || !s.added || !d || !r) return;
      const key = _laneKey(d);
      if (((s.d && s.d.items) || []).some((it) => _laneKey(it) === key)) {
        s.added[key] = r;
        renderLaneSearch();
      }
    }

    // A language switch (app-boot.js) redraws the section from what it holds, never a fetch.
    function repaintLaneSearchFromCache() {
      if (_laneSearchLast) renderLaneSearch();
    }
