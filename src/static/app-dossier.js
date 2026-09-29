/* app-dossier.js — the dossier seed (gate row K of RELEASE_0.5_GATE.md, brief S05-11 S4)

   One Wikidata item, and every rail this machine can join to it: the corpus articles that
   name it (split into news and web, Wikipedia and law by their source's channel), the
   Wikipedia lane's pages, the Places and the OpenStreetMap lane's objects carrying it. A
   SEED: the page lists the rails it joins and NAMES the ones it does not, with why, so it
   never reads as the whole picture. The ≥ 6 rails bar is 0.8's.

   The corpus passport (the action plan's A-1) sits under the title, one line, visible by
   default: n articles · sources · countries · languages · date span, with the articles
   missing a country, a language or a date counted on the same line rather than dropped.

   Opened from the place card and from a Who chip whose name resolves to one Wikidata item.
   Counts and lists only: no verdict, no score, no model. Every read is local (the server
   makes no network call to build it), so it needs no online consent.

   dossierHtml(d, t, tf) is pure so a test can drive it; openDossier and _dossierWire touch
   the DOM. No inline handlers: one delegated listener on the body serves every redraw.
*/
    let _dossierLast = null;    // the last payload, so a language switch re-reads it
    let _dossierSeq = 0;
    let _dossierWired = false;

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
        agenda: () => t("Agenda"),
        law_versions: () => t("Tracked law texts"),
      };
      return L[key] ? L[key]() : String(key || "");
    }

    // Why a rail is not joined. The server sends a code with English words; the words shown
    // are keyed here, and a code this list does not know shows the server's words.
    function _dossierNotJoinedReason(r, t) {
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
      const codes = (list) => (list || []).map((c) => c.code + " " + c.articles).join(", ");
      const hover = [t(p.method || ""),
        p.country_codes && p.country_codes.length ? t("Countries") + ": " + codes(p.country_codes) : "",
        p.language_codes && p.language_codes.length ? t("Languages") + ": " + codes(p.language_codes) : ""]
        .filter(Boolean).join(" — ");
      return `<div class="dossier-passport small" title="${esc(hover)}">`
        + `<span>${esc(parts.join(" · "))}</span>`
        + (span ? ` · <span class="dossier-date" dir="ltr">${esc(span)}</span>` : "")
        + (gaps.length ? ` <span class="muted">(${esc(gaps.join(" · "))})</span>` : "")
        + `</div>`;
    }

    function _dossierRailRow(r, d, t, tf) {
      const name = _dossierRailName(r.key, t);
      let what = "";
      if (r.key === "news") {
        const ch = Object.keys(r.by_channel || {});
        what = esc(tf("{n} articles", {n: r.articles || 0}))
          + (ch.length > 1 ? ` <span class="muted small">${esc(ch.map((c) => _dossierChannel(c, t) + " " + r.by_channel[c]).join(" · "))}</span>` : "");
      } else if (r.key === "law") {
        what = esc(tf("{n} articles", {n: r.articles || 0}));
      } else if (r.key === "wikipedia") {
        const lane = r.lane || {};
        what = esc(tf("{n} corpus articles", {n: r.articles || 0}));
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
            + ` <span class="muted small">${esc([p.kind, p.country ? ooCountryCode(p.country) : ""].filter(Boolean).join(" · "))}`
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
      }
      return `<tr><th scope="row">${esc(name)}</th><td>${what}</td></tr>`;
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
      html += `<div class="vsect">${esc(t("How articles join this item"))}</div><ul class="dossier-list">`
        + routeRow("entities", t("A person or organisation they mention"))
        + routeRow("keywords", t("A keyword that is a name of this item"))
        + routeRow("places", t("A place they mention"))
        + `</ul>`;
      html += `<div class="vsect">${esc(t("Joined on this page"))}</div><table class="data dossier-rails"><tbody>`
        + (d.rails || []).map((r) => _dossierRailRow(r, d, t, tf)).join("") + `</tbody></table>`;
      html += `<div class="vsect">${esc(t("Not joined yet"))}</div><ul class="dossier-list">`
        + (d.not_joined || []).map((r) =>
          `<li><strong>${esc(_dossierRailName(r.key, t))}</strong> <span class="muted">${esc(_dossierNotJoinedReason(r, t))}</span></li>`).join("")
        + `</ul>`;
      const n = (d.passport || {}).articles || 0;
      if (n) {
        const k = (d.article_ids || []).length;
        html += `<div style="margin-top:8px"><button type="button" class="secondary dossier-open">`
          + `${esc(tf("Open these {n} articles in the analysis window", {n: k}))}</button>`
          + (d.article_ids_bounded ? ` <span class="muted small">${esc(tf("the first {shown} of {n}", {shown: k, n}))}</span>` : "")
          + `</div>`;
      }
      html += `<p class="muted small" style="margin-top:8px">${esc(t(d.method || ""))}</p>`;
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
      $("dossier-body").innerHTML = dossierHtml(d, t, tf);
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
