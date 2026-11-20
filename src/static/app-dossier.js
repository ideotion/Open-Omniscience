/* app-dossier.js — the dossier seed (gate row K of RELEASE_0.5_GATE.md, brief S05-11 S4)

   One Wikidata item, and every rail this machine can join to it: the corpus articles that
   name it (split into news and web, Wikipedia and law by their source's channel), the
   Wikipedia lane's pages, the Places and the OpenStreetMap lane's objects carrying it. A
   SEED: the page lists the rails it joins and NAMES the ones it does not, with why, so it
   never reads as the whole picture. The ≥ 6 rails bar is 0.8's.

   The corpus passport (the action plan's A-1) sits under the title, one line, visible by
   default: n articles · sources · countries · languages · date span, with the articles
   missing a country, a language or a date counted on the same line rather than dropped.

   Opened from the place card, from a Who chip whose name resolves to one Wikidata item, and
   (row 178) from a keyword with a QID, an Explore search naming one item and a Lead card.
   Counts and lists only: no verdict, no score, no model. Every read is local (the server
   makes no network call to build it), so it needs no online consent.

   dossierHtml(d, t, tf) is pure so a test can drive it; openDossier and _dossierWire touch
   the DOM. No inline handlers: one delegated listener on the body serves every redraw.
*/
    let _dossierLast = null;    // the last payload, so a language switch re-reads it
    let _dossierSeq = 0;
    let _dossierWired = false;
    let _dossierTab = "overview";  // the open subtab, kept across a language switch's repaint

    function _dossierT() { return (window.OOI18N && OOI18N.t) ? OOI18N.t : ((s) => s); }
    function _dossierTf() {
      if (window.OOI18N && OOI18N.tf) return OOI18N.tf;
      return (s, vars) => String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));
    }

    // The provenance classes, keyed. A class this list does not know is data, shown as stored.
    function _dossierChannel(code, t) {
      const L = {
        web: () => t("Press and web"),
        newsletter: () => t("Newsletters"),
        statistics: () => t("Official statistics"),
        cited: () => t("Sources found through citations"),
        hazard: () => t("Hazard alerts"),
      };
      return L[code] ? L[code]() : String(code || "");
    }

    function _dossierRailName(key, t) {
      const L = {
        news: () => t("News and web"),
        wikipedia: () => t("Wikipedia"),
        law: () => t("Law"),
        places: () => t("Places"),
        map: () => t("Map (OpenStreetMap)"),
        markets: () => t("Markets"),
        stats: () => t("Statistics"),
        climate: () => t("Climate"),
        agenda: () => t("Agenda"),
        elections: () => t("Elections"),
        law_versions: () => t("Tracked law texts"),
      };
      return L[key] ? L[key]() : String(key || "");
    }

    // Why a rail is not joined. The server sends a code with English words; the words shown
    // are keyed here, and a code this list does not know shows the server's words.
    function _dossierNotJoinedReason(r, t) {
      // A country rail's absence is keyed by its code: the same rail is absent for two reasons.
      const C = {
        "not-a-country": () => t("Joined only for a country: no Place on this machine of kind country carries this item."),
        "country-unconfirmed": () => t("A Place of kind country carries this item, but none of its names names the country its code says, so no country is picked."),
        "several-countries": () => t("The Places of kind country carrying this item name more than one country, so none is picked."),
      };
      if (r.code && C[r.code]) return C[r.code]();
      const L = {
        markets: () => t("Market series are keyed by ticker symbol, not by a Wikidata item."),
        agenda: () => t("Calendar events carry no Wikidata item."),
        law_versions: () => t("Tracked law texts are keyed by their legal identifier; they join here only through the corpus articles they were ingested as."),
      };
      return L[r.key] ? L[r.key]() : String(r.reason || "");
    }

    function _dossierLaneAbsence(reason, which, t) {
      if (reason === "lane-unreadable") return t("The lane's file could not be read on this machine.");
      return which === "osm"
        ? t("The OpenStreetMap lane has not run on this machine.")
        : t("The Wikipedia lane has not run on this machine.");
    }

    // A-1: one line, data-dense, no prose. The gaps ride the SAME line when there are any.
    function passportLine(p, t, tf) {
      if (!p) return "";
      const num = (n) => (typeof fmtNum === "function" ? fmtNum(Number(n || 0)) : String(n || 0));
      const parts = [
        tf("{n} articles", {n: num(p.articles)}),
        tf("{n} sources", {n: num(p.sources)}),
        tf("{n} countries", {n: num(p.countries)}),
        tf("{n} languages", {n: num(p.languages)}),
      ];
      // The span is its own isolated left-to-right run: in an RTL line the bidi algorithm
      // would otherwise reorder an ISO date's parts around its hyphens.
      const span = (p.first && p.last) ? (p.first === p.last ? p.first : p.first + " – " + p.last) : "";
      if (!span && p.articles) parts.push(t("no dated article"));
      const gaps = [];
      if (p.no_country) gaps.push(tf("{n} without a country", {n: num(p.no_country)}));
      if (p.no_language) gaps.push(tf("{n} without a language", {n: num(p.no_language)}));
      if (p.undated && p.first) gaps.push(tf("{n} undated", {n: num(p.undated)}));
      const codes = (list, form) => (list || []).map((c) => (form ? form(c.code) : c.code) + " " + c.articles).join(", ");
      const hover = [t(p.method || ""),
        p.country_codes && p.country_codes.length ? t("Countries") + ": " + codes(p.country_codes, ooCountryCode) : "",
        p.language_codes && p.language_codes.length ? t("Languages") + ": " + codes(p.language_codes) : ""]
        .filter(Boolean).join(" — ");
      return `<div class="dossier-passport small" title="${esc(hover)}">`
        + `<span>${esc(parts.join(" · "))}</span>`
        + (span ? ` · <span class="dossier-date" dir="ltr">${esc(span)}</span>` : "")
        + (gaps.length ? ` <span class="muted">(${esc(gaps.join(" · "))})</span>` : "")
        + `</div>`;
    }

    // Where each rail's rows come from, VISIBLE at the top of its panel (row 178, PR 5: the planner's
    // "each rail's provenance and caveat stay visible by default"). Keyed; an unknown rail says nothing.
    function _dossierRailSource(key, t) {
      const L = {
        news: () => t("From the corpus articles that name this item, split by their source's channel."),
        wikipedia: () => t("From the corpus articles on Wikipedia sources, and the pages the Wikipedia lane holds for this item."),
        law: () => t("From the corpus articles on legal sources that name this item."),
        places: () => t("From the Places on this machine that carry this item."),
        map: () => t("From the OpenStreetMap lane's objects tagged with this item."),
        stats: () => t("From the statistics series stored for this country: names, periods and dates, never a value."),
        climate: () => t("From the climate series stored for this country, each with its publisher's licence."),
        agenda: () => t("From the agenda catalogue's events for this country."),
        elections: () => t("From the agenda catalogue's elections for this country; each date keeps its confidence."),
      };
      return L[key] ? L[key]() : t("From this machine's own store for this rail.");
    }

    // How many rows a joined rail found here, in its own unit, or null for a gap (S3: a gap is a gap).
    function _dossierRailCount(r, t, tf) {
      if (r.key === "news" || r.key === "law") return r.articles ? tf("{n} articles", {n: r.articles}) : null;
      if (r.key === "wikipedia") {
        const pages = ((r.lane || {}).pages || []).length;
        if (!r.articles && !pages) return null;
        return tf("{n} corpus articles", {n: r.articles || 0}) + (pages ? " · " + tf("{n} pages", {n: pages}) : "");
      }
      if (r.key === "map") {
        const k = ((r.lane || {}).objects || []).length;
        return k ? tf("{n} objects", {n: k}) : null;
      }
      return r.count ? tf("{n} rows", {n: r.count}) : null;
    }

    // One rail's rows, as the body of its panel.
    // Row 200 (S08-01 S2): a corpus rail lists its newest joined articles, each opening the local
    // reader first (invariant #6), with its source, its date and how it joined. The join is named,
    // never weighed; the rail's count stays the whole count and the rest is said to be there.
    function _dossierItemsHtml(r, t, tf) {
      const JOIN = {entities: "a person or organisation named", keywords: "a keyword", places: "a place named"};
      const items = r.items || [];
      if (!items.length) return "";
      const total = r.articles || items.length;
      return `<ul class="dossier-list dossier-items">` + items.map((a) => {
        const how = (a.joined_by || []).filter((k) => JOIN[k]).map((k) => t(JOIN[k])).join(" · ");
        return `<li><a href="/api/articles/${Number(a.id)}/view" target="_blank" rel="noopener" dir="auto"`
          + ` title="${esc(t("offline stored copy"))}">${esc(a.title || t("(untitled)"))}</a>`
          + ` <span class="muted small"><span dir="ltr">${esc(a.domain || "")}</span> · `
          + `<span dir="ltr">${esc(a.published_at || t("undated"))}</span></span>`
          + (how ? `<div class="muted small">${esc(tf("joined through: {how}", {how}))}</div>` : "")
          + `</li>`;
      }).join("") + `</ul>`
        + (total > items.length ? `<div class="muted small">${esc(tf("{shown} of {n} shown", {shown: items.length, n: total}))}`
          + ` · ${esc(t("Open them all in the analysis window with the button below."))}</div>` : "");
    }

    function _dossierRailBody(r, d, t, tf) {
      let what = "";
      if (r.key === "news") {
        const ch = Object.keys(r.by_channel || {});
        what = esc(tf("{n} articles", {n: r.articles || 0}))
          + (ch.length > 1 ? ` <span class="muted small">${esc(ch.map((c) => _dossierChannel(c, t) + " " + r.by_channel[c]).join(" · "))}</span>` : "")
          + _dossierItemsHtml(r, t, tf);
      } else if (r.key === "law") {
        what = esc(tf("{n} articles", {n: r.articles || 0})) + _dossierItemsHtml(r, t, tf);
      } else if (r.key === "wikipedia") {
        const lane = r.lane || {};
        what = esc(tf("{n} corpus articles", {n: r.articles || 0})) + _dossierItemsHtml(r, t, tf);
        if (!lane.available) {
          what += `<div class="muted small">${esc(_dossierLaneAbsence(lane.reason, "wiki", t))}</div>`;
        } else if (!(lane.pages || []).length) {
          what += `<div class="muted small">${esc(t("No page the Wikipedia lane holds carries this item."))}</div>`;
        } else {
          what += `<ul class="dossier-list">` + lane.pages.map((p) =>
            `<li dir="auto">${esc(p.title || p.external_id)} <span class="muted small">${esc(p.edition || "")}`
            + `${p.followed ? "" : " · " + esc(t("listed by the walk"))}</span></li>`).join("") + `</ul>`;
        }
      } else if (r.key === "places") {
        const ps = r.places || [];
        if (!ps.length) {
          what = `<span class="muted">${esc(t("No Place on this machine carries this item."))}</span>`;
        } else {
          what = `<ul class="dossier-list">` + ps.map((p) =>
            `<li><button type="button" class="linkish dossier-place" data-place-id="${esc(p.id)}" title="${esc(t("Open the place card"))}">`
            + `<span dir="auto">${esc(p.name)}</span></button>`
            + ` <span class="muted small">${esc([ooPlaceKind(p.kind).text, p.country ? ooCountryCode(p.country) : ""].filter(Boolean).join(" · "))}`
            + ` · ${esc(tf("Mentioned in {n} articles", {n: p.articles || 0}))}</span></li>`).join("") + `</ul>`
            + (r.count > ps.length ? `<div class="muted small">${esc(tf("{shown} of {n} shown", {shown: ps.length, n: r.count}))}</div>` : "");
        }
      } else if (r.key === "map") {
        const lane = r.lane || {};
        if (!lane.available) {
          what = `<span class="muted">${esc(_dossierLaneAbsence(lane.reason, "osm", t))}</span>`;
        } else if (!(lane.objects || []).length) {
          what = `<span class="muted">${esc(t("No object the OpenStreetMap lane holds is tagged with this item."))}</span>`;
        } else {
          what = `<ul class="dossier-list">` + lane.objects.map((o) =>
            `<li><span dir="auto">${esc(o.name || o.osm)}</span> <span class="muted small">${esc([o.osm, o.country_alpha3].filter(Boolean).join(" · "))}</span></li>`).join("") + `</ul>`;
        }
      } else if (r.key === "stats" || r.key === "climate") {
        // Series, periods and dates: no value, since a value needs its unit and vintage beside it.
        const ss = r.series || [];
        if (!ss.length) {
          what = `<span class="muted">${esc(r.key === "stats"
            ? t("No statistics series stored for this country on this machine.")
            : t("No climate series stored for this country on this machine."))}</span>`;
        } else {
          what = `<ul class="dossier-list">` + ss.map((x) => {
            const span = x.first === x.last ? x.first : x.first + " – " + x.last;
            const lic = (r.licences || {})[x.agency];
            return `<li><span dir="ltr">${esc(x.series_id)}</span> <span class="muted small">${esc(x.agency)} · ${esc(x.ref_area)}`
              + ` · ${esc(tf("{n} periods", {n: x.periods || 0}))} · <span dir="ltr">${esc(span || "")}</span></span>`
              + (lic ? `<div class="muted small">${esc(lic)}</div>` : "") + `</li>`;
          }).join("") + `</ul>`
            + (r.count > ss.length ? `<div class="muted small">${esc(tf("{shown} of {n} shown", {shown: ss.length, n: r.count}))}</div>` : "");
        }
      } else if (r.key === "agenda" || r.key === "elections") {
        const es = r.events || [];
        if (!es.length) {
          what = `<span class="muted">${esc(r.key === "agenda"
            ? t("The agenda lists no event for this country.")
            : t("The agenda lists no election for this country."))}</span>`;
        } else {
          what = `<ul class="dossier-list">` + es.map((e) => {
            // An election's year (and month, where the catalogue states one) is its date; for any
            // other event until_year is the year it STOPS, never shown as its date.
            const pad = (m) => (m ? "-" + String(m).padStart(2, "0") : "");
            const when = e.next_occurrence
              || (e.projection && e.projection.year ? String(e.projection.year) + pad(e.projection.month) : "")
              || (e.calendar === "elections" && e.until_year ? String(e.until_year) + pad(e.month) : "");
            // The date's caveat is VISIBLE beside it (the informed-consent rule), never a hover only.
            return `<li><span dir="auto">${esc(e.title || "")}</span>`
              + (when ? ` <span class="muted small" dir="ltr">${esc(when)}</span>` : "")
              + (e.confirmed === false && !e.date_caveat ? ` <span class="muted small">${esc(t("not confirmed"))}</span>` : "")
              + (e.date_caveat ? `<div class="card-caveat small">${esc(t(e.date_caveat))}</div>` : "") + `</li>`;
          }).join("") + `</ul>`
            + (r.count > es.length ? `<div class="muted small">${esc(tf("{shown} of {n} shown", {shown: es.length, n: r.count}))}</div>` : "");
        }
      }
      return what;
    }

    // THE RAILS AS SUBTABS (row 178, PR 5; invariant #18): one <nav class="tabs"> of data-tab buttons
    // driven by ooSubtabs, Overview first, then the rails in the server's order (the planner kept it).
    // A rail without rows keeps its tab and says so on it: a gap is a gap, never hidden.
    function _dossierTabsHtml(d, t) {
      const withRows = new Set(((d.availability || {}).rails_with_rows) || []);
      const btn = (key, label, gap, active) => `<button type="button" data-tab="${esc(key)}"`
        + (active ? ` class="active"` : "")
        + (gap ? ` title="${esc(t("No rows on this machine for this item"))}"` : "") + `>${esc(label)}`
        + (gap ? ` <span class="muted small">${esc(t("none here"))}</span>` : "") + `</button>`;
      return `<nav class="tabs dossier-tabs" id="dossier-tabs">`
        + btn("overview", t("Overview"), false, true)
        + (d.rails || []).map((r) => btn(r.key, _dossierRailName(r.key, t), !withRows.has(r.key), false)).join("")
        + `</nav>`;
    }

    function _dossierRailPanel(r, d, t, tf) {
      const src = _dossierRailSource(r.key, t);
      return `<div class="dossier-panel" data-panel="${esc(r.key)}" hidden>`
        + `<div class="vsect">${esc(_dossierRailName(r.key, t))}</div>`
        + (src ? `<p class="muted small dossier-source">${esc(src)}</p>` : "")
        + _dossierRailBody(r, d, t, tf) + `</div>`;
    }

    function dossierHtml(d, t, tf) {
      if (!d) return "";
      const item = d.item || {};
      let html = passportLine(d.passport, t, tf);
      if (item.description) {
        html += `<p class="dossier-desc" dir="auto">${esc(item.description)} <span class="muted small">— ${esc(t("Wikidata"))}</span></p>`;
      } else {
        html += `<p class="muted dossier-desc">${esc(item.status === "missing"
          ? t("Wikidata has no item with this id.")
          : t("No label or description on this machine yet: fetch the Wikidata items in Settings → Advanced."))}</p>`;
      }
      // How articles join: three routes, each with its own count and what it matched on.
      const routes = d.routes || {};
      const routeRow = (key, label) => {
        const r = routes[key] || {articles: 0, matched_on: []};
        const on = (r.matched_on || []).slice(0, 8).join(", ");
        return `<li>${esc(label)}: ${esc(tf("{n} articles", {n: r.articles || 0}))}`
          + (on ? ` <span class="muted small" dir="auto">(${esc(on)})</span>` : "") + `</li>`;
      };
      html += _dossierTabsHtml(d, t);
      let overview = `<div class="vsect">${esc(t("How articles join this item"))}</div><ul class="dossier-list">`
        + routeRow("entities", t("A person or organisation they mention"))
        + routeRow("keywords", t("A keyword that is a name of this item"))
        + routeRow("places", t("A place they mention"))
        + `</ul>`;
      // S3: how many joined rails had rows here. A rail without rows is a gap, not a zero.
      const av = d.availability;
      if (av) {
        overview += `<div class="muted small dossier-availability" title="${esc(t("A rail without rows has nothing on this machine for this item; that does not mean nothing exists."))}">`
          + `${esc(tf("{n} of {total} joined rails have rows on this machine", {n: av.with_rows, total: av.joined}))}</div>`;
      }
      // Every rail's count on the first screen (review of PR 5): the tabs hold the rows, this holds the summary.
      // Whether a rail had rows is the server's own answer (availability), the same one the tabs use.
      const hasRows = new Set(((d.availability || {}).rails_with_rows) || []);
      overview += `<ul class="dossier-list dossier-summary">` + (d.rails || []).map((r) => {
        const c = hasRows.has(r.key) ? (_dossierRailCount(r, t, tf) || "") : null;
        return `<li><strong>${esc(_dossierRailName(r.key, t))}</strong> <span class="${c === null ? "muted" : ""}">${esc(c === null ? t("none here") : c)}</span></li>`;
      }).join("") + `</ul>`;
      overview += `<div class="vsect">${esc(t("Not joined yet"))}</div><ul class="dossier-list">`
        + (d.not_joined || []).map((r) =>
          `<li><strong>${esc(_dossierRailName(r.key, t))}</strong> <span class="muted">${esc(_dossierNotJoinedReason(r, t))}</span></li>`).join("")
        + `</ul>`;
      html += `<div class="dossier-panel" data-panel="overview">${overview}</div>`
        + (d.rails || []).map((r) => _dossierRailPanel(r, d, t, tf)).join("");
      // Below the panels, whatever subtab is open: the actions, the method and the caveat.
      const n = (d.passport || {}).articles || 0;
      if (n) {
        const k = (d.article_ids || []).length;
        html += `<div style="margin-top:8px"><button type="button" class="secondary dossier-open">`
          + `${esc(tf("Open these {n} articles in the analysis window", {n: k}))}</button>`
          + (d.article_ids_bounded ? ` <span class="muted small">${esc(tf("the first {shown} of {n}", {shown: k, n}))}</span>` : "")
          + `</div>`;
      }
      // S08-01 S2: the dossier as a signed evidence bundle, through the same review as every
      // other export (what the file holds, plaintext, the key) before anything is written.
      html += `<div style="margin-top:8px"><button type="button" class="secondary dossier-evidence">`
        + `${esc(t("Export signed evidence"))}</button></div>`;
      html += `<p class="muted small" style="margin-top:8px">${esc(t(d.method || ""))}`
        + (d.method_country ? " " + esc(t(d.method_country)) : "") + `</p>`;
      // The caveat is VISIBLE, never behind a hover (the informed-consent rule).
      html += `<p class="card-caveat">${esc(t(d.caveat || ""))}</p>`;
      return html;
    }

    function _dossierPaint() {
      const d = _dossierLast;
      if (!d) return;
      const t = _dossierT(), tf = _dossierTf();
      const item = d.item || {};
      $("dossier-title").textContent = item.label || d.qid;
      $("dossier-qid").textContent = d.qid;
      const body = $("dossier-body");
      body.innerHTML = dossierHtml(d, t, tf);
      // Invariant #18: ONE subtab component. Without it every panel stays visible, never none.
      const panels = Array.prototype.slice.call(body.querySelectorAll(".dossier-panel"));
      const show = (key) => {
        _dossierTab = key;
        panels.forEach((p) => { p.hidden = p.getAttribute("data-panel") !== key; });
      };
      const nav = $("dossier-tabs");
      const tabs = (nav && typeof ooSubtabs === "function") ? ooSubtabs(nav, show) : null;
      if (!tabs) { panels.forEach((p) => { p.hidden = false; }); return; }
      if (!tabs.select(_dossierTab)) tabs.select("overview");
    }

    function _dossierWire() {
      if (_dossierWired) return;
      const dlg = $("dossier");
      if (!dlg) return;
      _dossierWired = true;
      $("dossier-close").addEventListener("click", () => dlg.close());
      $("dossier-body").addEventListener("click", (ev) => {
        const tgt = ev.target && ev.target.closest ? ev.target : null;
        if (!tgt) return;
        const place = tgt.closest(".dossier-place");
        if (place) {
          dlg.close();
          if (typeof openPlaceCard === "function") openPlaceCard(place.getAttribute("data-place-id"));
          return;
        }
        if (tgt.closest(".dossier-evidence") && _dossierLast && typeof openEvidenceReview === "function") {
          const d = _dossierLast;
          const label = (d.item || {}).label;
          dlg.close();
          openEvidenceReview({dossier_qid: d.qid, lang: d.lang || "en",
                              case_name: label && label !== d.qid ? label + " · " + d.qid : d.qid});
          return;
        }
        const cand = tgt.closest(".dossier-candidate");
        if (cand) {
          openDossier(cand.getAttribute("data-qid"));
          return;
        }
        if (tgt.closest(".dossier-open") && _dossierLast) {
          const d = _dossierLast;
          dlg.close();
          if (typeof openAnalysisForIds === "function") {
            openAnalysisForIds(d.article_ids || [], ((d.item || {}).label || d.qid) + " · " + d.qid);
          }
        }
      });
    }

    async function openDossier(qid) {
      const dlg = $("dossier");
      if (!dlg || !qid) return;
      _dossierWire();
      const t = _dossierT();
      const seq = ++_dossierSeq;
      if (!_dossierLast || _dossierLast.qid !== qid) _dossierTab = "overview";
      $("dossier-title").textContent = qid;
      $("dossier-qid").textContent = qid;
      $("dossier-body").innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      if (!dlg.open) dlg.showModal();
      const lang = (typeof uiLangCode === "function") ? String(uiLangCode()).split("-")[0].toLowerCase() : "en";
      try {
        const d = await api("/api/entities/dossier?" + new URLSearchParams({qid, lang}).toString());
        if (seq !== _dossierSeq) return;
        _dossierLast = d;
        _dossierPaint();
      } catch (e) {
        if (seq !== _dossierSeq) return;
        $("dossier-body").innerHTML = `<div class="note err">${esc(t("Could not open the dossier:") + " " + e.message)}</div>`;
      }
    }

    // A language switch re-reads it: the item's label depends on the language.
    function repaintDossierFromCache() {
      const dlg = $("dossier");
      if (!dlg || !dlg.open || !_dossierLast) return;
      openDossier(_dossierLast.qid);
    }

    // ---- The entry points (S08-01 S2, row 178): a keyword, an Explore search, a Lead ---- //
    // WHERE THE BUTTON LIVES (the brief leaves it to the PR): beside the thing that names the item,
    // never a main tab. A keyword that already resolved to one QID carries a "Dossier" button next
    // to its QID; an Explore search whose words name exactly one item gets one line in the result
    // count; a Lead card's back face gets a button among its actions, resolved when pressed. All
    // three open the one #dossier dialog, and every read is local (the ring table, no network).

    function _dossierQidOk(qid) { return typeof qid === "string" && /^Q[1-9][0-9]*$/.test(qid); }

    // The button for an item already known. A keyword chip is clickable itself, so the click stops.
    function dossierButtonHtml(qid) {
      if (!_dossierQidOk(qid)) return "";
      const t = _dossierT();
      return ` <button type="button" class="secondary tiny dossier-launch" data-i18n-dyn`
        + ` title="${esc(t("Open the dossier of this item: every rail this machine joins to it"))}"`
        + ` data-on-click='ooStop(event);openDossier(${esc(JSON.stringify(qid))})'>${esc(t("Dossier"))}</button>`;
    }

    // The words of a search or a Lead, as one name the ring table may know. Boolean syntax, field
    // filters and wildcards are not a name, so they are not asked.
    function _dossierTermOf(text) {
      let s = String(text || "").trim();
      const m = s.match(/^["“](.+)["”]$/);
      if (m) s = m[1].trim();
      if (!s || s.length > 120) return "";
      if (/[()*:"“”]/.test(s) || /\b(AND|OR|NOT)\b/.test(s)) return "";
      return s;
    }

    // {qid} when the term names exactly one item, {candidates} when it names several, {} when none.
    async function _dossierResolve(term) {
      // A target language, because the ladder lists the candidates of a shared name only then.
      const lang = (typeof uiLangCode === "function") ? String(uiLangCode()).split("-")[0].toLowerCase() : "en";
      const r = await api("/api/entities/resolve?" + new URLSearchParams({term, target_lang: lang || "en"}).toString());
      if (r && _dossierQidOk(r.qid)) return {qid: r.qid};
      const c = ((r && r.candidate_qids) || []).filter(_dossierQidOk);
      return c.length ? {candidates: c} : {};
    }

    // A Lead: resolved when pressed, so a Home page of cards costs no lookup. A term that names no
    // item, or several, says so in the dialog; several are listed, each opening its own dossier.
    async function openDossierForTerm(text) {
      const dlg = $("dossier");
      if (!dlg) return;
      _dossierWire();
      const t = _dossierT(), tf = _dossierTf();
      const term = _dossierTermOf(text) || String(text || "").trim();
      const seq = ++_dossierSeq;
      _dossierLast = null;
      $("dossier-title").textContent = term;
      $("dossier-qid").textContent = "";
      $("dossier-body").innerHTML = `<div class="muted">${esc(t("Loading…"))}</div>`;
      if (!dlg.open) dlg.showModal();
      try {
        const r = _dossierTermOf(text) ? await _dossierResolve(term) : {};
        if (seq !== _dossierSeq) return;
        if (r.qid) { openDossier(r.qid); return; }
        if (r.candidates) {
          $("dossier-body").innerHTML = `<p>${esc(tf("“{term}” names several Wikidata items on this machine. Pick one:", {term}))}</p>`
            + `<p>${r.candidates.map((q) => `<button type="button" class="secondary tiny dossier-candidate" data-qid="${esc(q)}">${esc(q)}</button>`).join(" ")}</p>`;
          return;
        }
        $("dossier-body").innerHTML = `<p class="muted">${esc(tf("No single Wikidata item is known for “{term}” on this machine, so there is no dossier to open.", {term}))}</p>`;
      } catch (e) {
        if (seq !== _dossierSeq) return;
        $("dossier-body").innerHTML = `<div class="note err">${esc(t("Could not open the dossier:") + " " + e.message)}</div>`;
      }
    }

    // An Explore search: one line in the result count when the words name exactly one item. Quiet
    // otherwise (a search that names no item is not a failure). isCurrent() drops a stale answer.
    async function dossierSearchHint(text, host, isCurrent) {
      const term = _dossierTermOf(text);
      if (!term || !host) return;
      let r;
      try { r = await _dossierResolve(term); } catch (e) { return; }
      if (!r.qid || (isCurrent && !isCurrent())) return;
      const t = _dossierT();
      const span = document.createElement("span");
      span.className = "dossier-hint";
      span.innerHTML = ` · ${esc(t("Wikidata item"))} <span dir="ltr">${esc(r.qid)}</span>` + dossierButtonHtml(r.qid);
      host.appendChild(span);
    }
