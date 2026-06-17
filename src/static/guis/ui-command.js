/*
 * Open Omniscience — "Command" interface (Alpine.js). GPL-3.0-or-later.
 *
 * Keyboard/command-first shell. Builds an always-present command launcher on
 * Home: a fuzzy-filtered list of every section + key action, navigable with the
 * arrow keys, runnable with Enter — so a power user reaches any feature without
 * hunting through thirteen tabs. It REUSES the core: commands are read from the
 * live nav (window.showTab) and the existing search/palette, so nothing here
 * duplicates logic or bypasses a consent step.
 *
 * Alpine is vendored locally (MIT, zero network). It only manages this one
 * x-data subtree; the rest of the app is untouched.
 */
(function () {
  "use strict";
  if (!window.OOGUIs) return;

  // Commands, derived from the REAL nav (no hardcoded list to drift) + a few
  // high-value actions that call existing globals.
  function buildItems() {
    var items = [];
    document.querySelectorAll(".nav-item[data-tab]").forEach(function (b) {
      var tab = b.dataset.tab;
      var label = (b.querySelector("span") ? b.querySelector("span").textContent : b.textContent || "").trim();
      if (!tab || !label) return;
      items.push({ id: "tab:" + tab, label: label, sub: "Section",
        run: function () { if (window.showTab) showTab(tab); } });
    });
    items.push({ id: "act:search", label: "Search the corpus", sub: "Action",
      run: function () { if (window.showTab) showTab("search"); setTimeout(function () { var q = document.getElementById("q"); if (q) q.focus(); }, 60); } });
    items.push({ id: "act:palette", label: "Open the command palette", sub: "Action",
      run: function () { if (window.openPalette) openPalette(); } });
    items.push({ id: "act:collect", label: "Collect now (one pass)", sub: "Action",
      run: function () { if (window.showTab) showTab("ingest"); if (window.schedulerRunNow) setTimeout(schedulerRunNow, 80); } });
    items.push({ id: "act:settings", label: "Open Settings", sub: "Action",
      run: function () { if (window.showTab) showTab("settings"); } });
    return items;
  }

  // Subsequence fuzzy match: every char of the query appears in order. Substring
  // hits score highest, then earliest/contiguous subsequence.
  function score(q, label) {
    if (!q) return 1;
    var s = label.toLowerCase(), needle = q.toLowerCase();
    var idx = s.indexOf(needle);
    if (idx >= 0) return 1000 - idx;
    var si = 0, hits = 0, last = -1, contig = 0;
    for (var qi = 0; qi < needle.length; qi++) {
      var f = s.indexOf(needle[qi], si);
      if (f < 0) return -1;
      if (f === last + 1) contig++;
      last = f; si = f + 1; hits++;
    }
    return hits * 4 + contig * 6 - last;
  }

  function component() {
    return {
      q: "",
      sel: 0,
      items: [],
      setup: function () { this.items = buildItems(); },
      filtered: function () {
        var q = this.q.trim();
        return this.items
          .map(function (it) { return { it: it, sc: score(q, it.label) }; })
          .filter(function (x) { return x.sc >= 0; })
          .sort(function (a, b) { return b.sc - a.sc; })
          .map(function (x) { return x.it; });
      },
      move: function (d) {
        var n = this.filtered().length; if (!n) return;
        this.sel = (this.sel + d + n) % n;
      },
      enter: function () {
        var f = this.filtered();
        if (f.length) { this.run(f[this.sel] || f[0]); return; }
        // No command matched -> treat the text as a corpus search.
        var q = this.q.trim(); if (!q) return;
        if (window.showTab) showTab("search");
        setTimeout(function () {
          var qi = document.getElementById("q");
          if (qi) { qi.value = q; if (window.doSearch) doSearch(); }
        }, 60);
      },
      run: function (item) { if (item && item.run) item.run(); }
    };
  }

  function build() {
    var home = document.getElementById("tab-home");
    if (!home || document.getElementById("cmd-launch")) return;
    var sec = document.createElement("section");
    sec.className = "panel cmd-launch";
    sec.id = "cmd-launch";
    sec.setAttribute("x-data", "oocmd");
    sec.setAttribute("x-init", "setup()");
    sec.innerHTML =
      '<div class="cmd-bar">' +
        '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input class="cmd-input" type="text" autocomplete="off" spellcheck="false" ' +
          'placeholder="Type a command, or search the corpus…" ' +
          'x-model="q" @input="sel = 0" @keydown.arrow-down.prevent="move(1)" @keydown.arrow-up.prevent="move(-1)" ' +
          '@keydown.enter.prevent="enter()">' +
        '<kbd class="cmd-kbd">↑↓ · ↵</kbd>' +
      '</div>' +
      '<div class="cmd-grid">' +
        '<template x-for="(item, idx) in filtered()" :key="item.id">' +
          '<button class="cmd-tile" type="button" @click="run(item)" @mouseenter="sel = idx" :class="{ sel: idx === sel }">' +
            '<span class="cmd-label" x-text="item.label"></span>' +
            '<span class="cmd-sub" x-text="item.sub"></span>' +
          '</button>' +
        '</template>' +
      '</div>' +
      '<p class="cmd-hint hint">Every section and action is one keystroke away. Press ' +
        '<kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>K</kbd> anywhere for the full federated palette.</p>';
    home.insertBefore(sec, home.firstChild);
  }

  OOGUIs.whenReady(function () {
    build();
    document.addEventListener("alpine:init", function () {
      if (window.Alpine) window.Alpine.data("oocmd", component);
    });
    OOGUIs.loadAlpine();
  });
})();
