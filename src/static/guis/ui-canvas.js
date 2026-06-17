/*
 * Open Omniscience — "Canvas" interface (Alpine.js). GPL-3.0-or-later.
 *
 * A spatial, zoomable workspace on Home: every section is a node on a pannable
 * board you can drag, zoom (wheel) and click to open. Investigations are
 * relational; a flat list/tab tree hides that. Canvas externalises the map.
 * It REUSES the core — nodes are read from the live nav and open via
 * window.showTab; the section content itself is the unchanged app.
 *
 * Alpine is vendored locally (MIT, zero network) and drives only this board.
 */
(function () {
  "use strict";
  if (!window.OOGUIs) return;

  function buildNodes() {
    var btns = Array.prototype.slice.call(document.querySelectorAll(".nav-item[data-tab]"));
    var n = btns.length || 1;
    var R = Math.max(210, n * 27);
    return btns.map(function (b, i) {
      var ang = (i / n) * 2 * Math.PI - Math.PI / 2;
      var span = b.querySelector("span");
      var label = (span ? span.textContent : (b.textContent || "")).trim();
      return { tab: b.dataset.tab, label: label,
        x: Math.round(Math.cos(ang) * R), y: Math.round(Math.sin(ang) * R) };
    });
  }

  function component() {
    return {
      scale: 1, ox: 0, oy: 0,
      panning: false, psx: 0, psy: 0,
      drag: null, moved: false,
      nodes: [],
      setup: function () {
        this.nodes = buildNodes();
        var r = this.$root.getBoundingClientRect();
        this.ox = r.width / 2; this.oy = Math.max(150, r.height / 2);
      },
      worldStyle: function () {
        return "transform: translate(" + this.ox + "px," + this.oy + "px) scale(" + this.scale + ")";
      },
      onWheel: function (e) {
        var r = this.$root.getBoundingClientRect();
        var mx = e.clientX - r.left, my = e.clientY - r.top;
        var f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
        var ns = Math.min(2.6, Math.max(0.4, this.scale * f));
        var wx = (mx - this.ox) / this.scale, wy = (my - this.oy) / this.scale;
        this.ox = mx - wx * ns; this.oy = my - wy * ns; this.scale = ns;
      },
      startPan: function (e) {
        if (e.target.closest && e.target.closest(".canvas-node")) return;
        this.panning = true; this.psx = e.clientX - this.ox; this.psy = e.clientY - this.oy;
        try { this.$root.setPointerCapture(e.pointerId); } catch (_) {}
      },
      startDrag: function (node, e) {
        var r = this.$root.getBoundingClientRect();
        this.drag = { node: node,
          dx: (e.clientX - r.left - this.ox) / this.scale - node.x,
          dy: (e.clientY - r.top - this.oy) / this.scale - node.y };
        this.moved = false;
        try { this.$root.setPointerCapture(e.pointerId); } catch (_) {}
      },
      onMove: function (e) {
        if (this.drag) {
          var r = this.$root.getBoundingClientRect();
          this.drag.node.x = Math.round((e.clientX - r.left - this.ox) / this.scale - this.drag.dx);
          this.drag.node.y = Math.round((e.clientY - r.top - this.oy) / this.scale - this.drag.dy);
          this.moved = true; return;
        }
        if (this.panning) { this.ox = e.clientX - this.psx; this.oy = e.clientY - this.psy; }
      },
      end: function () { this.panning = false; this.drag = null; },
      open: function (node) {
        if (this.moved) { this.moved = false; return; }
        if (window.showTab && node && node.tab) showTab(node.tab);
      },
      reset: function () {
        this.scale = 1; var r = this.$root.getBoundingClientRect();
        this.ox = r.width / 2; this.oy = Math.max(150, r.height / 2);
        this.nodes = buildNodes();
      }
    };
  }

  function build() {
    var home = document.getElementById("tab-home");
    if (!home || document.getElementById("canvas-board")) return;
    var sec = document.createElement("section");
    sec.className = "panel canvas-board";
    sec.id = "canvas-board";
    sec.setAttribute("x-data", "oocanvas");
    sec.setAttribute("x-init", "setup()");
    sec.setAttribute("@wheel.prevent", "onWheel($event)");
    sec.setAttribute("@pointerdown", "startPan($event)");
    sec.setAttribute("@pointermove", "onMove($event)");
    sec.setAttribute("@pointerup", "end()");
    sec.setAttribute("@pointercancel", "end()");
    sec.innerHTML =
      '<div class="canvas-toolbar">' +
        '<span class="canvas-hint hint">Drag to pan · scroll to zoom · drag a node to move it · click to open</span>' +
        '<button type="button" class="secondary tiny canvas-reset" @click="reset()">Reset view</button>' +
      '</div>' +
      '<div class="canvas-grid" aria-hidden="true"></div>' +
      '<div class="canvas-world" :style="worldStyle()">' +
        '<div class="canvas-hub" aria-hidden="true"></div>' +
        '<template x-for="n in nodes" :key="n.tab">' +
          '<button class="canvas-node" type="button" :style="`left:${n.x}px; top:${n.y}px`" ' +
            '@pointerdown.stop="startDrag(n, $event)" @click="open(n)" x-text="n.label"></button>' +
        '</template>' +
      '</div>';
    home.insertBefore(sec, home.firstChild);
  }

  OOGUIs.whenReady(function () {
    build();
    document.addEventListener("alpine:init", function () {
      if (window.Alpine) window.Alpine.data("oocanvas", component);
    });
    OOGUIs.loadAlpine();
  });
})();
