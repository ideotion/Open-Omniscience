/* Reader analysis tabs (Tier 1, PR1) — self-contained, no dependencies.
 *
 * The offline article reader (/api/articles/{id}/view) is a standalone server-
 * rendered page that does NOT load the SPA bundle, so this is its own small
 * module. It wires the sub-tab bar (Read · Keywords · Sentiment · Related · Links)
 * and LAZILY fetches the two new analysis tabs from the article_ids-aware insights
 * endpoints (the article = a "corpus of 1"). Reading/Related/Links are already
 * server-rendered into their panes; only Keywords + Sentiment fetch on first open.
 *
 * Honesty by construction: counts only (never a score), method + caveat shown
 * inline, the VADER English-only disclosure is VISIBLE by default, honest empty +
 * error states, and the network only fires when the user opens a lazy tab.
 */
(function () {
  "use strict";

  var wrap = document.querySelector(".wrap");
  var aid = wrap ? wrap.getAttribute("data-article-id") : null;
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".rtab"));
  var loaded = {}; // lazy panes already fetched (fetch once)

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }
  function num(n) { return (n == null ? 0 : n).toLocaleString(); }

  // The page loads i18n.js (deferred, ahead of this file), so its t()/tf() are the SPA's
  // own. Each is guarded: a reader must still read if the engine did not load.
  function T(s) { return (window.OOI18N && window.OOI18N.t) ? window.OOI18N.t(s) : s; }
  function TF(s, v) {
    if (window.OOI18N && window.OOI18N.tf) return window.OOI18N.tf(s, v);
    return String(s).replace(/\{(\w+)\}/g, function (m, k) { return (v && v[k] != null) ? String(v[k]) : m; });
  }
  function uiLang() {
    try {
      return (window.OOI18N && window.OOI18N.current && window.OOI18N.current())
        || localStorage.getItem("oo.lang") || "en";
    } catch (e) { return "en"; }
  }

  // --- THE KEYWORD LABEL, PORTED (M7) --------------------------------------------
  // The SPA draws every keyword through ONE helper, `kwLabelParts` in app-corpus.js: the
  // translation where a verified ring allows, a small "translated from French" / "in
  // French" tag otherwise, the original and the languages in the hover. This page does
  // not load the SPA bundle, so the Keywords tab showed the bare stored word -- a French
  // keyword stayed French in the English reader while the analysis window beside it
  // translated it. This is the smallest FAITHFUL port of those rules, not a new grammar:
  // same tiers, same fields, same keyed frames, the language names from CLDR through the
  // browser (the SPA's `ooLangName` reads the same source). Keep the two in step.
  // THE SECOND OWNER of the Intl language-name constructor (test_alpha3_display_surfaces):
  // this page cannot load app-map.js's `ooLangName`. Same derivation, small: the bare base
  // (`en-US` -> `en`, the house key rule), and a CLDR answer that merely ECHOES the code is
  // not a name -- it prints the code as the SPA's last resort does, never passes as one.
  var _langDN = {};
  function langName(code) {
    var src = String(code == null ? "" : code).trim();
    var base = src.toLowerCase().replace(/_/g, "-").split("-")[0];
    if (!base) return src;
    var ui = uiLang();
    try {
      if (!_langDN[ui]) _langDN[ui] = new Intl.DisplayNames([ui], { type: "language" });
      var name = _langDN[ui].of(base);
      return (name && name.toLowerCase() !== base) ? name : base;
    } catch (e) { return base; }
  }
  function langList(codes) {
    var names = (codes || []).map(langName).filter(Boolean);
    if (names.length < 2) return names[0] || "";
    try { return new Intl.ListFormat(uiLang(), { type: "conjunction" }).format(names); }
    catch (e) { return names.join(", "); }
  }
  function countsLine(counts) {
    if (!counts || typeof counts !== "object") return "";
    return Object.keys(counts).map(function (k) { return [k, +counts[k] || 0]; })
      .filter(function (x) { return x[1] > 0; })
      .sort(function (a, b) { return b[1] - a[1] || String(a[0]).localeCompare(String(b[0])); })
      .map(function (x) { return (x[0] === "?" ? T("Language not recorded") : langName(x[0])) + " " + x[1]; })
      .join(" · ");
  }
  function rdLabel(row) {
    var original = row.term || row.normalized || "";
    var tier = row.translation_tier || (row.translation ? "verified" : "untranslated");
    var ml = row.mention_languages;
    var langs = (ml && typeof ml === "object")
      ? Object.keys(ml).filter(function (k) { return k !== "?" && (+ml[k] || 0) > 0; })
        .sort(function (a, b) { return (+ml[b] || 0) - (+ml[a] || 0) || a.localeCompare(b); })
      : [];
    if (!langs.length && row.translation_source_lang) langs = [row.translation_source_lang];
    var ui = String(uiLang()).split("-")[0].toLowerCase();
    var inUi = !!ml && langs.some(function (c) { return String(c).split("-")[0].toLowerCase() === ui; });
    if (inUi && (tier === "verified" || tier === "tentative")) tier = "untranslated";
    var names = langList(langs);
    var shown = (tier === "verified" || tier === "tentative") && row.translation ? row.translation : original;
    var tag = "", cls = "";
    if (tier === "verified" && names) tag = TF("translated from {language}", { language: names });
    else if (tier === "tentative" && names) { tag = "≈ " + TF("translated from {language}", { language: names }); cls = " r-kw-tentative"; }
    else if (tier === "untranslated" && !inUi && row.translation_declined === "several-senses") tag = T("Several senses");
    else if (tier === "untranslated" && names && !(inUi && langs.length === 1)) tag = TF("in {language}", { language: names });
    var hover = [];
    if (tier === "verified") hover.push(T("Verified translation (cross-language concept)."));
    else if (tier === "tentative") hover.push(T("AI-generated tentative translation — unreliable, not verified."));
    else if (tier === "untranslated") hover.push(T("Not translated — shown in its own language."));
    if (shown !== original && original) hover.push(T("Original") + ": " + original);
    var split = countsLine(ml);
    if (split) hover.push(T("Mentions by language:") + " " + split);
    else if (names) hover.push(T("Language") + ": " + names);
    var across = countsLine(row.language_breakdown);
    if (across) hover.push(T("Across languages:") + " " + across);
    if (row.translation_qid) hover.push("Wikidata: " + row.translation_qid);
    return { shown: shown, tag: tag, cls: cls, hover: hover.join(" — ") };
  }
  // `data-i18n-dyn`: the walker must never translate a keyword (a corpus holding the
  // word "sources" is one collision away from a fabricated term).
  function rdLabelHtml(row) {
    var p = rdLabel(row);
    var html = '<span class="r-kw-term" data-i18n-dyn>' + esc(p.shown) + "</span>";
    if (p.tag) {
      html += ' <span class="r-kw-tag' + p.cls + '" data-i18n-dyn title="' + esc(p.hover) + '">'
        + esc(p.tag) + "</span>";
    }
    return html;
  }

  // Clicking any keyword opens its analysis in a NEW SPA tab, landing on the
  // Keywords subtab seeded with the term (the SPA boot hydrates ?analyze=&tab=).
  // The KEYWORD is the identifier; keywords are corpora (ledger 2026-07-01).
  function analysisUrl(term) {
    return "/?analyze=" + encodeURIComponent(term) + "&tab=keywords";
  }
  function kwLink(term, inner, cls) {
    // A real anchor (middle-/ctrl-click + "open in new tab" work natively); it
    // simply navigates to the SPA — no handler, degrades gracefully. data-kwstat lets
    // the hover enrich its title with the keyword's real corpus stats (lazy, cached).
    return '<a class="' + cls + '" data-kwstat="' + esc(term) + '" href="' + esc(analysisUrl(term))
      // The title is a STATIC sentence, not one composed around the term: the i18n
      // walker matches an attribute by EXACT value, so a title carrying the keyword
      // could never match a key and rendered English in eleven locales. The term is
      // already the link's own text and rides in data-kwstat, so naming it twice
      // bought nothing and cost the translation.
      + '" target="_blank" rel="noopener" title="Analyse this keyword across your corpus ↗">'
      + inner + "</a>";
  }

  // --- In-article keyword marking (pure core; unit-verified) -----------------
  // We mark ONLY the article's TRUSTED indexed keyword terms — never a naive
  // scan of arbitrary words (honesty: an inline mark is a link to a REAL entry
  // in the corpus keyword index, not an invented keyword).
  function isCJK(s) { return /[぀-ヿ㐀-鿿豈-﫿가-힣]/.test(s); }
  function buildMatcher(terms) {
    var seen = {}, canon = {}, parts = [];
    (terms || []).map(String)
      .filter(function (t) { return t && t.trim().length >= 2; })
      .sort(function (a, b) { return b.length - a.length; })  // longest first: phrases win
      .forEach(function (t) {
        var low = t.toLowerCase();
        if (seen[low]) return;
        seen[low] = 1; canon[low] = t;
        var e = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        // Word-boundaried for scripts that HAVE boundaries; a bare substring for
        // CJK/Hangul (no spaces) — so "election" never marks inside "reelection"
        // while "中国" still marks inside a run of ideographs.
        parts.push(isCJK(t) ? e : "(?<![\\p{L}\\p{N}_])" + e + "(?![\\p{L}\\p{N}_])");
      });
    if (!parts.length) return null;
    try {
      return { re: new RegExp("(?:" + parts.join("|") + ")", "giu"), canon: canon };
    } catch (_e) {
      return null;  // an engine without lookbehind/\p{}: skip marking, never break the read pane
    }
  }
  // Split one text-node string into {text} and {surface,term} segments (the term
  // is the canonical indexed keyword the surface form maps to).
  function segmentText(text, m) {
    if (!m || !text) return [{ text: text }];
    var out = [], last = 0, match;
    m.re.lastIndex = 0;
    while ((match = m.re.exec(text)) !== null) {
      if (match.index > last) out.push({ text: text.slice(last, match.index) });
      var surf = match[0];
      out.push({ surface: surf, term: m.canon[surf.toLowerCase()] || surf });
      last = match.index + surf.length;
      if (match.index === m.re.lastIndex) m.re.lastIndex++;  // zero-width guard
    }
    if (last < text.length) out.push({ text: text.slice(last) });
    return out;
  }
  // Wrap indexed-keyword occurrences inside the Read pane's <article> body with
  // linking anchors. Guarded end-to-end: any failure leaves the body untouched.
  function markArticleBody(terms) {
    try {
      var body = document.querySelector("#rp-read article");
      if (!body || body.getAttribute("data-kw-marked")) return;
      var m = buildMatcher(terms);
      if (!m) return;
      var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null);
      var texts = [], node;
      while ((node = walker.nextNode())) {
        if (node.parentNode && node.parentNode.closest && node.parentNode.closest("a")) continue;
        if (node.nodeValue && node.nodeValue.trim()) texts.push(node);
      }
      texts.forEach(function (tn) {
        var segs = segmentText(tn.nodeValue, m);
        if (segs.length === 1 && segs[0].text != null) return;  // nothing matched here
        var frag = document.createDocumentFragment();
        segs.forEach(function (s) {
          if (s.text != null) { frag.appendChild(document.createTextNode(s.text)); return; }
          var a = document.createElement("a");
          a.className = "r-kw-mark";
          a.href = analysisUrl(s.term);
          a.target = "_blank"; a.rel = "noopener";
          a.title = "Analyse this keyword across your corpus ↗";   // static: see makeKwLink
          a.setAttribute("data-kwstat", s.term);   // hover enriches the title with real stats
          a.textContent = s.surface;
          frag.appendChild(a);
        });
        tn.parentNode.replaceChild(frag, tn);
      });
      body.setAttribute("data-kw-marked", "1");
    } catch (_e) { /* the read pane must never break over a nicety */ }
  }

  // In-reader keyword hover-stats (wave 4 I): on first hover of a keyword (an in-article
  // mark or a Keywords-tab link), lazily enrich its native title with the keyword's REAL
  // corpus stats — mentions, distinct-article spread, the windowed trend RATE, and the
  // top co-occurrences (GET /api/insights/keyword-stats). Counts only, the endpoint's
  // caveat rides along, NO score. Loopback-only (airplane-safe), cached per term, fully
  // guarded — a failure leaves the existing "Analyse …" title untouched. The standalone
  // reader has no #oo-tip bubble, so it uses the native title (its existing hover).
  var _kwStatCache = {};
  // The same line the SPA's keyword bubble composes (app-boot.js ooKwStatInit), through
  // the same keys -- and the CAVEAT through t(), which it was not: a fixed server sentence
  // appended verbatim read English inside every translated reader (K-reader; keyed since N7).
  function kwStatLine(d) {
    if (!d || !d.resolved) return T("Not in your corpus yet — no stats.");
    var bits = [num(d.mentions) + " " + T(d.mentions === 1 ? "mention" : "mentions")
      + " · " + num(d.articles) + " " + T(d.articles === 1 ? "article" : "articles")];
    var tr = d.trend || {};
    if (tr.recent || tr.prior) {
      bits.push(T("trend") + " " + tr.growth + "× (" + tr.window_days + "d " + T("vs") + " " + tr.baseline_days + "d)");
    }
    var co = (d.cooccurrences || []).slice(0, 4).map(function (c) { return c.term; }).filter(Boolean);
    if (co.length) bits.push(T("with") + ": " + co.join(", "));
    return bits.join(" · ") + (d.caveat ? " · " + T(d.caveat) : "");
  }
  // THE CACHE HOLDS THE PAYLOAD, NOT THE SENTENCE (K-cache/K-reader). It used to hold the
  // formatted line and PREPEND it to the title once per element, so after a language
  // switch every keyword already hovered kept the old language's line for the life of
  // the page. The title is now rebuilt on each hover from the payload and the one static
  // sentence both link kinds carry, in the language on screen at that moment -- which
  // also means a second hover never stacks a second line on the first.
  var _KW_TITLE = "Analyse this keyword across your corpus ↗";
  function _kwStatTitle(el, d) { el.title = kwStatLine(d) + "\n" + T(_KW_TITLE); }
  function enrichKwStat(el) {
    var term = el.getAttribute("data-kwstat");
    if (!term) return;
    var d = _kwStatCache[term];
    if (d) { _kwStatTitle(el, d); return; }
    if (d === null) return;                      // in flight: one request per term
    _kwStatCache[term] = null;
    fetch("/api/insights/keyword-stats?term=" + encodeURIComponent(term), { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { _kwStatCache[term] = d || {}; _kwStatTitle(el, _kwStatCache[term]); })
      .catch(function () { delete _kwStatCache[term]; });   // allow a later retry
  }
  document.addEventListener("mouseover", function (e) {
    var el = e.target && e.target.closest ? e.target.closest("[data-kwstat]") : null;
    if (el) enrichKwStat(el);
  }, true);

  function show(key) {
    tabs.forEach(function (b) {
      var on = b.getAttribute("data-rtab") === key;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.setAttribute("tabindex", on ? "0" : "-1");
    });
    Array.prototype.forEach.call(document.querySelectorAll(".rpane"), function (p) {
      p.hidden = p.id !== "rp-" + key;
    });
    var pane = document.getElementById("rp-" + key);
    if (pane && pane.getAttribute("data-lazy") && !loaded[key]) {
      loaded[key] = true;
      lazyLoad(key, pane);
    }
  }

  // Lazy panes: endpoint (article_ids-aware, the article = a "corpus of 1") + renderer.
  var ENDPOINTS = {
    keywords: "/api/insights/corpus-keywords?limit=40&article_ids=",
    sentiment: "/api/insights/corpus-sentiment?article_ids=",
    mindmap: "/api/insights/graph?article_ids=",
    // subjectivity is per-article (article_id, singular) — a DEDUCED rule-based lens, not a corpus roll-up.
    subjectivity: "/api/insights/subjectivity?article_id=",
  };

  function lazyLoad(key, pane) {
    if (!aid) {
      pane.innerHTML = '<p class="r-muted">No article id — cannot load this view.</p>';
      return;
    }
    // Summary / Translation read the stored LLM results (their own shape: latest +
    // folded history + a generate-now control) rather than an insights endpoint.
    if (key === "summary" || key === "translation") { loadAnalyses(key, pane); return; }
    // Keywords may already be in flight / cached from the eager in-article
    // marking pass (one fetch serves both — no double request).
    if (key === "keywords" && _kwPromise) {
      pane.innerHTML = '<p class="r-muted">Loading…</p>';
      _kwPromise.then(function (d) { renderKeywords(pane, d); })
        .catch(function (e) { pane.innerHTML = '<p class="r-muted">Could not load this view (' + esc(e.message) + ").</p>"; });
      return;
    }
    var base = ENDPOINTS[key];
    if (!base) return;
    pane.innerHTML = '<p class="r-muted">Loading…</p>';
    var render = key === "keywords" ? renderKeywords
      : key === "sentiment" ? renderSentiment
      : key === "subjectivity" ? renderSubjectivity
      : renderMindmap;
    fetch(base + encodeURIComponent(aid), { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { render(pane, d); })
      .catch(function (e) {
        pane.innerHTML = '<p class="r-muted">Could not load this view (' + esc(e.message) + ").</p>";
      });
  }

  // One eager, loopback-only fetch of the article's indexed keywords, used to
  // (a) mark them inline in the Read body and (b) prime the Keywords tab so
  // opening it never refetches. Loopback ⇒ airplane-safe; fully guarded ⇒ a
  // failure leaves the reader exactly as before.
  var _kwPromise = null;
  function primeKeywords() {
    if (!aid) return;
    // In the reader's language, so the Keywords tab can draw each label the way the SPA
    // does (M7); the terms the body marking reads are the stored words either way.
    _kwPromise = fetch("/api/insights/corpus-keywords?limit=60&article_ids=" + encodeURIComponent(aid)
      + "&target_lang=" + encodeURIComponent(uiLang()),
      { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
    _kwPromise.then(function (d) {
      var terms = (d && d.terms || []).map(function (t) { return t.term; });
      if (terms.length) markArticleBody(terms);
    }).catch(function () { /* marking is a nicety — never surface an error here */ });
  }

  function renderKeywords(pane, d) {
    var terms = (d && d.terms) || [];
    if (!terms.length) {
      pane.innerHTML = '<p class="r-muted">No keywords extracted from this article yet.</p>';
      return;
    }
    var rows = terms.map(function (t) {
      var m = t.mentions || 0;
      // Each keyword is CLICKABLE — it opens its full analysis in a new tab.
      return "<li>" + kwLink(t.term, rdLabelHtml(t), "r-kw")
        + '<span class="r-kn">' + num(m) + " " + esc(T(m === 1 ? "mention" : "mentions")) + "</span></li>";
    }).join("");
    pane.innerHTML =
      '<h2 class="r-h2">Keywords in this article</h2>'
      + '<p class="r-muted">Click any keyword to analyse it across your corpus ↗</p>'
      + '<ol class="r-kwlist">' + rows + "</ol>"
      // Both are FIXED server sentences, keyed like the SPA's: the caveat carries a count,
      // so the server also sends it as a frame + vars (M14) and the English stays the
      // fallback for an older payload (K-reader).
      + '<p class="r-method">' + esc(T(d.method || "")) + "</p>"
      + '<p class="r-caveat">' + esc(d.caveat_i18n ? TF(d.caveat_i18n, d.caveat_vars || {}) : (d.caveat || "")) + "</p>"
      + '<div id="r-ailens"></div>';
    loadAiLens();
  }

  // --- The AI-derived lens, BESIDE the trusted keywords (never inside them) ---------
  //
  // WIRING TWO DEAD ENDS (PRH-07). `AiKeyword.evidence` had zero writers and
  // `POST /api/ai/keywords/confirm` had no frontend consumer; `GET /api/ai/articles/
  // {id}/keywords` had none either. All three were built so a caller could use them,
  // and no caller ever did -- while the analysis window's own success message already
  // told the operator "Open an article to see its AI-derived metadata", which the
  // reader did not show. This is that caller.
  //
  // THE TWO CLASSES STAY TWO, which is the whole ruling. The trusted rule-based index
  // renders ABOVE; this renders below it under its own heading, and nothing here is
  // ever merged into that list: a confirmed row STAYS AI-derived, and confirming is
  // curation WITHIN the lens, never promotion out of it.
  //
  // ABSENT RENDERS NOTHING. A zeroed panel would read as "the model found nothing here"
  // when the truth is usually "no extraction has been run over this article" -- two
  // different facts, and only one of them is about the article.
  var _aiLensLoaded = false;
  function loadAiLens() {
    if (!aid || _aiLensLoaded) return;
    _aiLensLoaded = true;
    fetch("/api/ai/articles/" + encodeURIComponent(aid) + "/keywords",
      { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && (d.keywords || []).length) renderAiLens(d); })
      .catch(function () { /* the lens is additive: a failure leaves the pane as it was */ });
  }

  function renderAiLens(d) {
    var host = document.getElementById("r-ailens");
    if (!host) return;
    var rows = (d.keywords || []).map(function (k) {
      // THREE states, never two. `evidence` is where the term occurs in your stored
      // copy. `evidence_absent` means the copy WAS searched and the term is not in it --
      // the informative case, said in words rather than left blank, because a missing
      // line reads as "nothing to show" and this is a finding (inferred, translated, or
      // invented). NEITHER key means the stored copy has no text, so nothing could be
      // searched -- and claiming "not found" there would assert a search nobody ran.
      var ev;
      if (k.evidence) {
        ev = '<div class="r-aiev">' + esc(k.evidence) + "</div>";
      } else if (k.evidence_absent) {
        ev = '<div class="r-aiev r-aigap">Not found in your stored copy of this article</div>';
      } else {
        ev = '<div class="r-aiev r-aigap">Your stored copy has no text to search</div>';
      }
      var label = k.confirmed ? "Confirmed" : "Confirm";
      return '<li><span class="r-aikind">' + esc(k.kind) + "</span> "
        + "<b>" + esc(k.term) + "</b> "
        + '<button class="r-aibtn" data-aikw="' + esc(String(k.id)) + '"'
        + (k.confirmed ? ' data-on="1"' : "") + ">" + label + "</button>"
        + ev + "</li>";
    }).join("");
    host.innerHTML =
      '<h2 class="r-h2">AI-derived — unreliable</h2>'
      // ONE literal, not two joined at a line break. This file has no t() binding at
      // all -- it relies entirely on i18n.js's DOM walker, which matches a WHOLE text
      // node against its key -- so a caveat split across a `+` was two nodes and could
      // never match one. It is a caveat, and caveats ship x12 by the informed-consent
      // non-negotiable, so being unkeyable was the defect rather than a formatting nit.
      + '<p class="r-caveat">Generated by a local model from the article text — unverified candidates, never confirmed and never part of the trusted keyword index.</p>'
      + '<ol class="r-kwlist r-ailist">' + rows + "</ol>";
  }

  // Curate the lens in place. Delegated (no inline onclick, no per-row handler), and
  // the button re-reads its own state from the response rather than assuming the POST
  // did what was asked -- the row stays AI-derived either way.
  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest(".r-aibtn") : null;
    if (!btn) return;
    var id = parseInt(btn.getAttribute("data-aikw"), 10);
    if (!id) return;
    var want = btn.getAttribute("data-on") !== "1";
    btn.disabled = true;
    fetch("/api/ai/keywords/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ id: id, confirmed: want }),
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        if (j.confirmed) { btn.setAttribute("data-on", "1"); btn.textContent = "Confirmed"; }
        else { btn.removeAttribute("data-on"); btn.textContent = "Confirm"; }
      })
      .catch(function () { /* leave the button as it was; nothing was changed */ })
      .then(function () { btn.disabled = false; });
  });

  function renderSentiment(pane, d) {
    var caveat = '<p class="r-caveat">' + esc((d && d.caveat) || "") + "</p>";
    if (!d || !d.n_scored) {
      pane.innerHTML = '<p class="r-muted">No tone score is stored for this article.</p>' + caveat;
      return;
    }
    var labels = d.labels || {};
    var chips = Object.keys(labels).map(function (k) {
      return '<span class="r-chip">' + esc(k) + " · " + num(labels[k]) + "</span>";
    }).join(" ");
    // english_scored is 0 for a non-English article ⇒ VADER tone is unreliable; say so.
    var english = d.english_scored
      ? ""
      : '<p class="r-warn">This article is not detected as English — VADER tone is unreliable here.</p>';
    pane.innerHTML =
      '<h2 class="r-h2">Tone</h2>'
      + '<p class="r-score">Valence score: <b>' + esc(d.mean_score) + "</b> "
      + '<span class="r-muted">(−1 negative … +1 positive)</span></p>'
      + (chips ? "<p>" + chips + "</p>" : "")
      + english
      + '<p class="r-method">' + esc(d.method || "") + "</p>"
      + caveat;
  }

  // The loaded-language / subjectivity lens (S5.2): DEDUCED, rule-based (never AI, never asserted),
  // per-language. Shows the loaded-term density (n_loaded / n_tokens, both shown) + the matched terms,
  // or an HONEST GAP when the article's language has no lexicon / is a script mismatch — never a
  // fabricated 0. Conservative render: a term list + density, NOT an inline highlight over the body
  // (char-offset spans over rendered HTML drift; a highlight surface is a later browser-verified slice).
  function renderSubjectivity(pane, d) {
    var method = '<p class="r-method">' + esc((d && d.method) || "") + "</p>";
    var caveat = '<p class="r-caveat">' + esc((d && d.caveat) || "") + "</p>";
    if (!d || d.available === false) {
      var reason = (d && d.reason) || "not available";
      pane.innerHTML = '<h2 class="r-h2">Loaded language</h2>'
        + '<p class="r-muted">Not measured for this article — ' + esc(reason) + ".</p>"
        + method + caveat;
      return;
    }
    var terms = d.terms || [];
    var chips = terms.map(function (t) { return '<span class="r-chip">' + esc(t) + "</span>"; }).join(" ");
    pane.innerHTML =
      '<h2 class="r-h2">Loaded language</h2>'
      + '<p class="r-muted">Deduced from the text (rule-based, never AI) — a prompt to read closely, never a verdict.</p>'
      + '<p class="r-score">Loaded-term density: <b>' + esc(d.density) + "</b> "
      + '<span class="r-muted">(' + num(d.n_loaded || 0) + " of " + num(d.n_tokens || 0) + " words)</span></p>"
      + (chips
          ? '<p class="r-muted">Loaded terms found:</p><p>' + chips + "</p>"
          : '<p class="r-muted">No loaded terms found — a real measurement, not a gap.</p>')
      + method + caveat;
  }

  // A deterministic RADIAL keyword map (centre → arms → always OUTWARD — the
  // mind-map rule, no cross-tangle). Self-contained SVG; node area ∝ mention
  // count; counts only, never a score. Data: /api/insights/graph?article_ids=.
  function renderMindmap(pane, d) {
    var nodes = (d && d.nodes) || [];
    var method = '<p class="r-method">' + esc((d && d.method) || "") + "</p>";
    var caveat = '<p class="r-caveat">' + esc((d && d.caveat) || "") + "</p>";
    if (!nodes.length) {
      pane.innerHTML = '<h2 class="r-h2">Mindmap</h2>'
        + '<p class="r-muted">Not enough keywords indexed to draw a map yet.</p>' + method + caveat;
      return;
    }
    var center = null, arms = [];
    nodes.forEach(function (n) { if (n.center) center = n; else arms.push(n); });
    if (!center) { center = nodes[0]; arms = nodes.slice(1); }
    var MAX_ARMS = 14;
    var more = arms.length > MAX_ARMS ? arms.length - MAX_ARMS : 0;
    arms = arms.slice(0, MAX_ARMS);

    var W = 720, H = 460, cx = W / 2, cy = H / 2, R = 150;
    var maxSize = 1;
    arms.concat([center]).forEach(function (n) { if ((n.size || 1) > maxSize) maxSize = n.size || 1; });
    function radius(sz) { return Math.max(7, Math.min(22, 7 + Math.sqrt((sz || 1) / maxSize) * 15)); }

    var edges = "", circles = "", labels = "";
    var m = arms.length || 1;
    arms.forEach(function (n, i) {
      var ang = (-90 + i * (360 / m)) * Math.PI / 180;
      var co = Math.cos(ang), si = Math.sin(ang);
      var x = cx + R * co, y = cy + R * si, r = radius(n.size);
      edges += '<line class="r-mm-edge" x1="' + cx + '" y1="' + cy + '" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '"></line>';
      circles += '<circle class="r-mm-node" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + r.toFixed(1) + '"></circle>';
      var anchor = co > 0.3 ? "start" : co < -0.3 ? "end" : "middle";
      var lx = x + co * (r + 5), ly = y + si * (r + 5) + 4;
      labels += '<text class="r-mm-label" x="' + lx.toFixed(1) + '" y="' + ly.toFixed(1) + '" text-anchor="' + anchor + '">'
        + esc(n.label) + ' <tspan class="r-mm-n">· ' + num(n.mentions || n.size || 0) + "</tspan></text>";
    });
    var cr = Math.max(radius(center.size), 14);
    circles += '<circle class="r-mm-node center" cx="' + cx + '" cy="' + cy + '" r="' + cr.toFixed(1) + '"></circle>';
    labels += '<text class="r-mm-label center" x="' + cx + '" y="' + (cy + cr + 15).toFixed(1) + '" text-anchor="middle">' + esc(center.label) + "</text>";

    var svg = '<svg class="r-mm" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Keyword mindmap for this article">'
      + edges + circles + labels + "</svg>";
    var moreNote = more ? '<p class="r-muted">+ ' + num(more) + " more keyword" + (more === 1 ? "" : "s") + " not shown.</p>" : "";
    pane.innerHTML = '<h2 class="r-h2">Mindmap</h2>' + svg + moreNote + method + caveat;
  }

  // --- Summary / Translation tabs --------------------------------------------
  // Show the LATEST stored result prominently and FOLD the rest (we keep every
  // past summary/translation — a new one never replaces an old one). Each carries
  // its provenance (model, target language, date). A generate-now control runs the
  // LOCAL model and re-loads the list. Honesty: the caveat is always visible; the
  // result is never analysed for keywords (stated). Nothing leaves the machine
  // (Ollama is loopback) — but airplane mode refuses it, surfaced loudly.
  var TARGETS = ["English", "French", "Spanish", "German", "Portuguese", "Italian",
    "Dutch", "Arabic", "Russian", "Chinese", "Japanese", "Hindi", "Bengali", "Indonesian"];

  function loadAnalyses(key, pane) {
    pane.innerHTML = '<p class="r-muted">Loading…</p>';
    fetch("/api/llm/articles/" + encodeURIComponent(aid) + "/analyses?kind=" + key,
      { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { renderAnalyses(key, pane, d); })
      .catch(function (e) {
        pane.innerHTML = '<p class="r-muted">Could not load this view (' + esc(e.message) + ").</p>";
      });
  }

  function itemHtml(an, key) {
    var when = (an.created_at || "").slice(0, 16).replace("T", " ");
    var tgt = (key === "translation" && an.target_language) ? " → " + esc(an.target_language) : "";
    // The exact prompt used is recorded with each result (provenance) — folded away.
    var prompt = an.prompt_text
      ? '<details class="r-an-prompt"><summary>prompt used'
        + (an.prompt_version ? " (" + esc(an.prompt_version) + ")" : "")
        + '</summary><div class="r-an-promptbody">' + esc(an.prompt_text) + "</div></details>"
      : "";
    return '<div class="r-an-meta">' + esc(an.model || "(model unknown)") + tgt
      + (when ? " · " + esc(when) : "") + "</div>"
      + '<div class="r-an-body">' + esc(an.result) + "</div>" + prompt;
  }

  function controlHtml(key) {
    var status = '<span class="r-gen-status r-muted"></span>';
    if (key === "translation") {
      var opts = TARGETS.map(function (l) {
        return '<option value="' + esc(l) + '">' + esc(l) + "</option>";
      }).join("");
      return '<div class="r-gen"><label class="r-muted" for="r-tgt">Into</label>'
        + ' <select id="r-tgt" class="r-sel">' + opts + "</select>"
        + ' <button type="button" class="r-genbtn">Translate now</button> ' + status + "</div>";
    }
    return '<div class="r-gen"><button type="button" class="r-genbtn">Summarize now</button> '
      + status + "</div>";
  }

  function renderAnalyses(key, pane, d) {
    var list = (d && d.analyses) || [];
    var heading = key === "summary" ? "Summary" : "Translation";
    var word = key === "summary" ? "summary" : "translation";
    var html = '<h2 class="r-h2">' + heading + "</h2>" + controlHtml(key);
    if (!list.length) {
      html += '<p class="r-muted">No ' + word + " stored yet — generate one with your local model above.</p>";
    } else {
      html += '<div class="r-an latest">' + itemHtml(list[0], key) + "</div>";
      if (list.length > 1) {
        var prev = list.slice(1).map(function (an) {
          return '<div class="r-an">' + itemHtml(an, key) + "</div>";
        }).join("");
        var n = list.length - 1;
        html += '<details class="r-an-prev"><summary>' + n + " earlier "
          + word + (n === 1 ? "" : "s") + " (kept, never replaced)</summary>" + prev + "</details>";
      }
    }
    // ONE literal, for the reason given at the sibling caveat above: the DOM walker
    // keys whole text nodes, so a caveat split across two `+` joins was unkeyable.
    html += '<p class="r-caveat">Generated by a local model — fluent, but capable of being wrong; verify against the article. Stored locally with its model and date; never analysed for keywords.</p>';
    pane.innerHTML = html;
    var btn = pane.querySelector(".r-genbtn");
    if (btn) btn.addEventListener("click", function () {
      var sel = pane.querySelector("#r-tgt");
      runGenerate(key, sel ? sel.value : null, pane, btn);
    });
  }

  function runGenerate(key, target, pane, btn) {
    var status = pane.querySelector(".r-gen-status");
    btn.disabled = true;
    if (status) { status.className = "r-gen-status r-muted"; status.textContent = "Working locally…"; }
    var url = "/api/llm/articles/" + encodeURIComponent(aid)
      + (key === "summary" ? "/summarize" : "/translate");
    // The UI language code, read the same way i18n.js does (the reader loads it,
    // so window.OOI18N is normally there; the localStorage read is the fallback for
    // the case where it is not). Ruling 14 (2026-07-31): this selects which language
    // the built-in prompt BODY is written in, so a French reader asking for a
    // summary does not get English work back. Unset = the English body, unchanged.
    var uiLang = "en";
    try {
      uiLang = (window.OOI18N && window.OOI18N.current && window.OOI18N.current())
        || localStorage.getItem("oo.lang") || "en";
    } catch (e) { /* a storage-denied browser still gets the English default */ }
    var body = key === "summary" ? { ui_lang: uiLang }
                                 : { target_language: target || "English", ui_lang: uiLang };
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, j: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          var detail = (res.j && res.j.detail) ? res.j.detail : ("HTTP " + res.status);
          if (status) { status.className = "r-gen-status r-warn"; status.textContent = detail; }
          btn.disabled = false;
          return;
        }
        // Re-load so the new result shows as the latest (older ones fold below).
        loadAnalyses(key, pane);
      })
      .catch(function (e) {
        if (status) { status.className = "r-gen-status r-warn"; status.textContent = e.message; }
        btn.disabled = false;
      });
  }

  // Tab interaction: click + roving-tabindex keyboard nav (mirrors the SPA's
  // ooSubtabs grammar — ←/→/↑/↓ move, Home/End jump).
  function focusTab(i) {
    var n = tabs.length;
    var t = tabs[((i % n) + n) % n];
    t.focus();
    show(t.getAttribute("data-rtab"));
  }
  tabs.forEach(function (b, i) {
    b.addEventListener("click", function () { show(b.getAttribute("data-rtab")); });
    b.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); focusTab(i + 1); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); focusTab(i - 1); }
      else if (e.key === "Home") { e.preventDefault(); focusTab(0); }
      else if (e.key === "End") { e.preventDefault(); focusTab(tabs.length - 1); }
    });
  });

  // Mark the article's real indexed keywords inline in the Read body + prime the
  // Keywords tab (one loopback fetch serves both).
  primeKeywords();

  // A language switch re-asks for the keywords in the new language and redraws the tab
  // if it was open: the labels carry translations INTO the old one. (This page has no
  // switcher of its own; the listener costs nothing and keeps the port's contract.)
  document.addEventListener("oo:langchange", function () {
    primeKeywords();
    var pane = document.getElementById("rp-keywords");
    if (loaded.keywords && pane && _kwPromise) {
      _kwPromise.then(function (d) { renderKeywords(pane, d); }).catch(function () {});
    }
  });
})();
