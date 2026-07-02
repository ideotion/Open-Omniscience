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

  // Clicking any keyword opens its analysis in a NEW SPA tab, landing on the
  // Keywords subtab seeded with the term (the SPA boot hydrates ?analyze=&tab=).
  // The KEYWORD is the identifier; keywords are corpora (ledger 2026-07-01).
  function analysisUrl(term) {
    return "/?analyze=" + encodeURIComponent(term) + "&tab=keywords";
  }
  function kwLink(term, inner, cls) {
    // A real anchor (middle-/ctrl-click + "open in new tab" work natively); it
    // simply navigates to the SPA — no handler, degrades gracefully.
    return '<a class="' + cls + '" href="' + esc(analysisUrl(term))
      + '" target="_blank" rel="noopener" title="Analyse “' + esc(term)
      + '” across your corpus ↗">' + inner + "</a>";
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
          a.title = "Analyse “" + s.term + "” across your corpus ↗";
          a.textContent = s.surface;
          frag.appendChild(a);
        });
        tn.parentNode.replaceChild(frag, tn);
      });
      body.setAttribute("data-kw-marked", "1");
    } catch (_e) { /* the read pane must never break over a nicety */ }
  }

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
    var render = key === "keywords" ? renderKeywords : key === "sentiment" ? renderSentiment : renderMindmap;
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
    _kwPromise = fetch("/api/insights/corpus-keywords?limit=60&article_ids=" + encodeURIComponent(aid),
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
      return "<li>" + kwLink(t.term, esc(t.term), "r-kw")
        + '<span class="r-kn">' + num(m) + " mention" + (m === 1 ? "" : "s") + "</span></li>";
    }).join("");
    pane.innerHTML =
      '<h2 class="r-h2">Keywords in this article</h2>'
      + '<p class="r-muted">Click any keyword to analyse it across your corpus ↗</p>'
      + '<ol class="r-kwlist">' + rows + "</ol>"
      + '<p class="r-method">' + esc(d.method || "") + "</p>"
      + '<p class="r-caveat">' + esc(d.caveat || "") + "</p>";
  }

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
    html += '<p class="r-caveat">Generated by a local model — fluent, but capable of being '
      + "wrong; verify against the article. Stored locally with its model and date; never "
      + "analysed for keywords.</p>";
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
    var body = key === "summary" ? {} : { target_language: target || "English" };
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
})();
