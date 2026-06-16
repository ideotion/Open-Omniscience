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

  function lazyLoad(key, pane) {
    if (!aid) {
      pane.innerHTML = '<p class="r-muted">No article id — cannot load this view.</p>';
      return;
    }
    pane.innerHTML = '<p class="r-muted">Loading…</p>';
    var url = key === "keywords"
      ? "/api/insights/corpus-keywords?limit=40&article_ids=" + encodeURIComponent(aid)
      : "/api/insights/corpus-sentiment?article_ids=" + encodeURIComponent(aid);
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { (key === "keywords" ? renderKeywords : renderSentiment)(pane, d); })
      .catch(function (e) {
        pane.innerHTML = '<p class="r-muted">Could not load this view (' + esc(e.message) + ").</p>";
      });
  }

  function renderKeywords(pane, d) {
    var terms = (d && d.terms) || [];
    if (!terms.length) {
      pane.innerHTML = '<p class="r-muted">No keywords extracted from this article yet.</p>';
      return;
    }
    var rows = terms.map(function (t) {
      var m = t.mentions || 0;
      return '<li><span class="r-kw">' + esc(t.term) + '</span>'
        + '<span class="r-kn">' + num(m) + " mention" + (m === 1 ? "" : "s") + "</span></li>";
    }).join("");
    pane.innerHTML =
      '<h2 class="r-h2">Keywords in this article</h2>'
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
})();
