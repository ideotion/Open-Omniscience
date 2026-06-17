/*
 * Open Omniscience — Settings -> GUIs: the alternative-interfaces gallery.
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 *
 * Renders the picker that lets the user switch interface live. Selecting one
 * persists the choice (in the shared oo.ui blob, via OOGUIs.setActive) and
 * reloads so the skin applies from boot. Reset = select the default.
 *
 * All visible chrome is rendered in clean English; the i18n MutationObserver
 * translates it x12 from the strings keyed in src/static/locales/*.json. UI
 * NAMES are proper nouns and are intentionally NOT translated.
 */
(function () {
  "use strict";

  // Per-interface copy (the at-a-glance critical argument; the full rationale
  // lives in docs/product/GUI_ALTERNATIVES.md). Each string is a locale key.
  var META = {
    "": {
      tag: "The original — dense, honest, fully featured.",
      why: "The reference interface every alternative is measured against."
    },
    aurora: {
      tag: "Calm and uncluttered; depth on demand.",
      why: "Answers the original's biggest adoption risk — front-loading everything at once — by revealing method and detail progressively, while every caveat stays visible."
    },
    atlas: {
      tag: "A mission-control dashboard of live tiles.",
      why: "Turns the text-first Home into an at-a-glance command center, so there is always something to see and somewhere to dig in."
    },
    command: {
      tag: "Keyboard-first; everything a keystroke away.",
      why: "Puts the search palette at the centre of gravity, so power users reach any feature instantly instead of hunting across thirteen tabs."
    },
    field: {
      tag: "A mobile-first card stream with a bottom bar.",
      why: "Makes the desktop-dense layout genuinely usable one-handed on a phone — the device field reporters actually carry."
    },
    focus: {
      tag: "Distraction-free reading and analysis.",
      why: "Recedes the chrome so long investigative sessions stay on the content, not the controls."
    },
    terminal: {
      tag: "Maximum information density for analysts.",
      why: "For experts who want more on screen and fewer clicks — a compact, high-contrast, keyboard-friendly cockpit."
    },
    canvas: {
      tag: "A spatial, zoomable investigation board.",
      why: "Externalises the relational nature of an investigation that lists and tables flatten."
    },
    editorial: {
      tag: "Your briefing, typeset like a publication.",
      why: "Reframes the database-admin feel into a newsroom front page that resonates with the journalist the app is built for."
    }
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // A small, themeable layout mock per interface (pure CSS via .gt--<id>). The
  // pieces evoke the real layout: sidebar / top-nav / bottom-bar / palette /
  // board, so the difference is legible before switching.
  function thumb(id) {
    var key = id || "default";
    var card = '<i class="gt-c"></i>';
    var cards = card + card + card + card;
    return '' +
      '<div class="gt gt--' + esc(key) + '" aria-hidden="true">' +
        '<div class="gt-bar"></div>' +
        '<div class="gt-body">' +
          '<div class="gt-side"></div>' +
          '<div class="gt-main">' + cards + '</div>' +
        '</div>' +
        '<div class="gt-foot"></div>' +
      '</div>';
  }

  function card(g) {
    var id = g.id || "";
    var meta = META[id] || { tag: "", why: "" };
    var active = OOGUIs.activeId() === id;
    var isDefault = id === "";
    var name = isDefault ? "Open Omniscience" : g.name;
    var badge = isDefault ? "Default interface"
      : (g.engine === "alpine" ? "Alpine.js" : "No framework");
    var badgeTitle = g.engine === "alpine"
      ? "Uses Alpine.js — a tiny framework vendored locally (MIT, zero network)."
      : "";
    var btn = active
      ? '<span class="gui-active">Active</span>'
      : '<button class="gui-use" type="button" data-gui="' + esc(id) + '">' +
          (isDefault ? "Reset to the default interface" : "Use this interface") + "</button>";

    return '' +
      '<div class="gui-card' + (active ? " on" : "") + (isDefault ? " is-default" : "") + '">' +
        thumb(id) +
        '<div class="gui-meta">' +
          '<div class="gui-head">' +
            '<h4 class="gui-name">' + esc(name) + "</h4>" +
            '<span class="gui-badge"' + (badgeTitle ? ' title="' + esc(badgeTitle) + '"' : "") + ">" + esc(badge) + "</span>" +
          "</div>" +
          '<p class="gui-tag">' + esc(meta.tag) + "</p>" +
          '<p class="gui-why">' + esc(meta.why) + "</p>" +
          '<div class="gui-acts">' + btn + "</div>" +
        "</div>" +
      "</div>";
  }

  function renderGallery() {
    var host = document.getElementById("guis-gallery");
    if (!host) return;
    var all = (window.OOGUIs && OOGUIs.all) || [];
    var current = OOGUIs.activeId();
    // The default ("") card first, then the eight alternatives.
    var cards = [card({ id: "", name: "Open Omniscience", engine: "vanilla" })]
      .concat(all.map(card)).join("");

    host.innerHTML = '' +
      '<div class="gui-intro">' +
        '<p class="gui-lead">Pick an interface to try it live. Your corpus, your data and every honesty ' +
          'guarantee stay the same — only the look, layout and interaction change. Switching reloads the app to apply.</p>' +
        '<p class="card-caveat gui-ethic">Every interface shows the same data and the same caveats: caveats stay ' +
          'visible, the network-consent step is unchanged, and no interface invents a score.</p>' +
      "</div>" +
      '<div class="gui-grid">' + cards + "</div>";

    // Wire the "use" buttons (no inline handlers — CSP-friendly, like the rest
    // of the gallery framework).
    host.querySelectorAll("button.gui-use").forEach(function (b) {
      b.addEventListener("click", function () {
        OOGUIs.setActive(b.getAttribute("data-gui") || "");
      });
    });
    void current;
  }

  // Expose on the shared namespace (boot.js created it).
  if (window.OOGUIs) window.OOGUIs.renderGallery = renderGallery;
  else window.OOGUIs = { renderGallery: renderGallery };
})();
