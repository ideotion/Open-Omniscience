/*
 * Open Omniscience — ooSky: the Observatory's deterministic polar renderer.
 * GPL-3.0-or-later.
 *
 * Design of record: docs/design/OBSERVATORY_DESIGN.md (maintainer-ruled 2026-07-18).
 * The corpus as a night sky: universe = the corpus, galaxy CLUSTER = a scaffold
 * domain (the `domain:` field in configs/keyword_supergroups.yml), GALAXY = a
 * super-group. Hand-rolled canvas 2D — no WebGL, no Three.js, no library, no
 * network (the ruling, reaffirmed 2026-07-13).
 *
 * THE HONESTY SPINE, which is what makes the metaphor reportable rather than
 * decorative. Every visual channel carries ONE measured quantity with a stated
 * method, or is declared aesthetic:
 *
 *   ANGLE    = category only (the domain wedge). Within a wedge the residual
 *              angular position is a STABLE HASH (ooViz.mulberry32, honesty rule
 *              H5 — never Math.random), disclosed on the surface as meaningless,
 *              exactly like alphabetical order.
 *   RADIUS   = ONE chosen measure, never an "importance" blend, monotone with
 *              centre = max, with LABELLED orbit gridlines (invariant #16).
 *   SIZE     = mentions, via ooViz.sqrtAreaScale so AREA is proportional to the
 *              value (framework rule R4), with a reference-star legend. Area is
 *              a rank-4 channel, so it is SECONDARY here by construction: the
 *              radial position and the sr-only table are what carry the reading.
 *   COLOUR   = the galaxy's dominant language (an identity channel, rule R3), or
 *              the windowed-trend lens. NEVER the only signal — every mark also
 *              carries its label, its radial position and its table row (A2).
 *   EDGES    = drawn from a MEASURED shared membership (cross_group_overlap),
 *              never implied by proximity.
 *
 * TWO REFUSALS ARE LOAD-BEARING, both reached by the real data rather than by
 * theory (measured 2026-09-07 on a 440-article corpus through the real
 * index_article):
 *
 *   (1) `radialScale` REFUSES the log mode below one full decade. The recorded
 *       ooChart `logY` lesson is that `log10(max(v, 1e-9))` reads as defensive
 *       coding and instead fabricates an axis: it spanned −9..0.78 and printed
 *       gridlines no count can take. Here `distinct_sources` tops out at SEVEN
 *       across all 77 galaxies, so a log radius would spread two thirds of a
 *       decade across the whole sky and label orbits that mean nothing. The mode
 *       is chosen from the data, the fallback is the axis the data deserves
 *       (zero-based, integer orbits), and the surface SAYS which is in force.
 *   (2) A galaxy whose measure is ZERO is not placed on the scale at all. It
 *       goes to a distinct, labelled outer band ("not observed in this corpus
 *       yet"), drawn hollow. 52 of 77 galaxies sit there on a young corpus, so
 *       this is the common case and not an edge case: log10(0) is −Infinity and
 *       a clamp would plant a fabricated observation on the outermost orbit.
 *       That is honesty rule H2 — a gap renders as a gap, in a treatment drawn
 *       from outside the value scale.
 *
 * PURE / IMPURE SPLIT: everything above `drawSky` is pure geometry over plain
 * numbers — no DOM, no canvas, no colour — so tests/oosky_node_test.js can pin
 * the refusals and the determinism without a browser. Only `drawSky` and
 * `hitTest` touch a rendering context.
 *
 * Dual node/browser like ooviz.js: attaches root.ooSky AND module.exports.
 */
(function (root) {
  "use strict";

  var V =
    root.ooViz ||
    (typeof module !== "undefined" && module.exports && typeof require === "function"
      ? require("./ooviz.js")
      : null);

  // The log radius is offered only when the positive data spans at least this
  // many times the count floor of 1 — i.e. one full decade. Below it, a log axis
  // spreads a fraction of a decade across the whole sky and labels orbits the
  // data cannot occupy (the recorded ooChart logY defect, one geometry over).
  var LOG_MIN_SPAN = 10;

  // Inside each domain wedge, leave this fraction of the wedge clear at both
  // edges so a hashed position never lands ambiguously on a sector boundary.
  var WEDGE_MARGIN = 0.12;

  // The rings OUTSIDE the value scale, as multiples of rOuter. They were 1.02 and
  // 1.06 in the first cut, which put the hollow "not observed yet" marks INSIDE
  // the nebula band -- two different facts (52 unplaced galaxies, 2,286 nebula
  // keywords) rendered on top of each other, which a screenshot showed at once and
  // no assertion would have. Separated, and the nebula moved outward and thinned,
  // because a band that carries no quantity must not be the loudest mark on screen.
  var R_UNPLACED = 1.05;
  var R_NEBULA = 1.13;
  var R_DOMAIN_LABEL = 1.22;

  // The smallest radius a star is drawn at. Below it a mark is invisible, so the
  // area channel SATURATES here: every value whose sqrt-area radius falls under
  // MIN_STAR renders identically. That is a real limit of the channel, and it is
  // disclosed twice rather than hidden — `skyLayout` reports the value at which
  // it bites (`sizeFloorValue`) and the size legend clamps to the SAME constant,
  // so a reference star is never drawn smaller than any real star can be. A
  // legend whose smallest sample is 0.8px while nothing on the canvas is under
  // 1.5px would be teaching a scale the sky does not use.
  var MIN_STAR = 1.5;

  // ----- deterministic hashing (honesty rule H5) ----- //

  /**
   * FNV-1a 32-bit over a string. Deterministic across runs, platforms and
   * sessions, which is what makes "same corpus => same sky" true: the user
   * builds spatial memory and a NEW bright star in a familiar region becomes
   * information rather than noise (design §6).
   */
  function hash32(s) {
    var h = 0x811c9dc5;
    s = String(s === null || s === undefined ? "" : s);
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h >>> 0;
  }

  /** A stable [0,1) for a name, via the seeded PRNG ooViz already ships. */
  function stableUnit(name) {
    return V.mulberry32(hash32(name))();
  }

  // ----- the radial scale (measure -> distance from centre) ----- //

  /**
   * Build the radial scale for ONE measure over the galaxies' values.
   *
   * Returns `{mode, lo, hi, ticks, r(value), rInner, rOuter, positives, zeros}`.
   * `mode` is one of:
   *   "log"    — the positive values span >= LOG_MIN_SPAN, so equal ratios are
   *              equal distances and the decade orbits are real.
   *   "linear" — they do not. Zero-based with integer orbit ticks, which is the
   *              axis a bounded count deserves.
   *   "none"   — NOTHING has a positive value. There is no scale to draw and the
   *              caller must render the honest empty state; `r` is null so a
   *              caller that ignores the mode cannot accidentally plot anyway.
   *
   * `r(v)` is defined only for v > 0 and returns null otherwise — a zero is a
   * real observation ("this galaxy has no source yet") but it is not a point on
   * this scale, and the caller places it in the labelled outer band instead.
   * MONOTONE CENTRE = MAX: the biggest measure sits at rInner, so "bright things
   * near the middle" reads the way a galaxy does.
   */
  function radialScale(values, opts) {
    opts = opts || {};
    var rInner = opts.rInner === undefined ? 40 : opts.rInner;
    var rOuter = opts.rOuter === undefined ? 300 : opts.rOuter;
    var vals = [];
    for (var i = 0; i < (values || []).length; i++) {
      var v = values[i];
      if (!V.isMissing(v) && typeof v === "number" && isFinite(v)) vals.push(v);
    }
    var positives = vals.filter(function (v) {
      return v > 0;
    });
    var zeros = vals.length - positives.length;
    if (!positives.length) {
      return {
        mode: "none", lo: null, hi: null, ticks: [], r: null,
        rInner: rInner, rOuter: rOuter, positives: 0, zeros: zeros,
      };
    }
    var hi = Math.max.apply(null, positives);
    // The floor is 1, not the observed minimum: these are COUNTS, and one is the
    // smallest thing that can be observed. Anchoring to the observed minimum
    // would make the scale jump every time the smallest galaxy gained a mention.
    var lo = 1;
    var mode = hi >= LOG_MIN_SPAN ? "log" : "linear";
    var ticks = [];
    var r;
    if (mode === "log") {
      var lhi = Math.log10(hi);
      for (var d = 0; Math.pow(10, d) <= hi; d++) ticks.push(Math.pow(10, d));
      if (ticks[ticks.length - 1] !== hi) ticks.push(hi);
      r = function (v) {
        if (V.isMissing(v) || !(v > 0)) return null;
        var t = Math.log10(v) / lhi; // lhi > 0 because hi >= 10
        return rOuter - V.clamp(t, 0, 1) * (rOuter - rInner);
      };
    } else {
      // Zero-based (a length/position scale over counts anchors at zero, Part
      // 1.4), integer orbits only — a count cannot take 2.5.
      // t > 0 only: `r()` is undefined at zero by design (a zero is a real
      // observation but not a point on this scale), so a 0 tick would advertise
      // an orbit that can never be drawn and can never hold a galaxy.
      ticks = V.niceTicks(0, hi, 4).filter(function (t) {
        return t > 0 && Math.abs(t - Math.round(t)) < 1e-9;
      });
      if (!ticks.length || ticks[ticks.length - 1] < hi) ticks.push(hi);
      r = function (v) {
        if (V.isMissing(v) || !(v > 0)) return null;
        var t = hi > 0 ? v / hi : 0;
        return rOuter - V.clamp(t, 0, 1) * (rOuter - rInner);
      };
      lo = 0;
    }
    return {
      mode: mode, lo: lo, hi: hi, ticks: ticks, r: r,
      rInner: rInner, rOuter: rOuter,
      positives: positives.length, zeros: zeros,
    };
  }

  // ----- reference stars (the size legend the area channel owes) ----- //

  /**
   * Three reference magnitudes for the size legend. Area encodes mentions, and
   * area is systematically under-read (framework 5.6), so a legend with REAL
   * reference values is the condition under which the channel is allowed at all.
   * Values are chosen from the data's own decades so the legend never advertises
   * a magnitude this corpus cannot exhibit.
   */
  function referenceStars(maxMentions, sizeFn) {
    var out = [];
    if (!(maxMentions > 0)) return out;
    var top = Math.pow(10, Math.floor(Math.log10(maxMentions)));
    var candidates = [top, top / 10, top / 100].filter(function (v) {
      return v >= 1;
    });
    if (candidates.length < 3 && maxMentions !== top) candidates.unshift(maxMentions);
    var seen = {};
    for (var i = 0; i < candidates.length && out.length < 3; i++) {
      var v = Math.round(candidates[i]);
      if (v < 1 || seen[v]) continue;
      seen[v] = 1;
      // The SAME clamp the canvas applies. `saturated` marks a sample the size
      // channel can no longer separate, so the legend can say which of its own
      // reference stars are drawn at the floor rather than at their true area.
      var raw = sizeFn(v);
      out.push({ value: v, r: Math.max(MIN_STAR, raw), saturated: raw < MIN_STAR });
    }
    return out.sort(function (a, b) {
      return b.value - a.value;
    });
  }

  /**
   * The mention count below which the size channel saturates at MIN_STAR — i.e.
   * the value under which two different galaxies are drawn the same size. Null
   * when the floor never bites. This is the anti-capping disclosure applied to a
   * VISUAL channel: the limit is named on the surface instead of quietly
   * flattening the bottom of the distribution.
   */
  function sizeFloorValue(maxMentions, maxStar) {
    if (!(maxMentions > 0) || !(maxStar > 0)) return null;
    // sqrtAreaScale: r = maxStar * sqrt(v / maxMentions); solve r = MIN_STAR.
    var v = maxMentions * Math.pow(MIN_STAR / maxStar, 2);
    var cut = Math.ceil(v);
    return cut > 1 ? cut : null;
  }

  // ----- the layout ----- //

  /**
   * Turn an /api/insights/observatory payload into placed marks. PURE: plain
   * numbers in, plain numbers out, no DOM and no colour — the caller maps a
   * language to a theme token, so the same layout survives all 17 themes.
   *
   * `opts.measure` names the radial measure (a key of `galaxy.measures`);
   * `opts.rInner`/`opts.rOuter` bound the plotted annulus. Galaxies whose
   * measure is 0 come back in `unplaced` with a reason — never a coordinate.
   */
  function skyLayout(payload, opts) {
    opts = opts || {};
    var measure = opts.measure || "distinct_sources";
    var rInner = opts.rInner === undefined ? 40 : opts.rInner;
    var rOuter = opts.rOuter === undefined ? 300 : opts.rOuter;
    var galaxies = (payload && payload.galaxies) || [];

    // Domain wedges at FIXED compass positions, ordered by NAME (design §11's
    // proposal: a stable map of the heavens). Ordering by size would move every
    // wedge whenever the corpus grew, and "change is signal" needs the frame to
    // hold still. The domain list comes from the payload's own clusters so a
    // user-created group's "Uncategorized" bucket gets a wedge like any other.
    var domainNames = {};
    for (var i = 0; i < galaxies.length; i++) domainNames[galaxies[i].domain || ""] = 1;
    var clusters = (payload && payload.clusters) || [];
    for (var c = 0; c < clusters.length; c++) domainNames[clusters[c].domain || ""] = 1;
    var domains = Object.keys(domainNames).sort();
    var wedge = domains.length ? (Math.PI * 2) / domains.length : Math.PI * 2;
    var wedgeOf = {};
    var domainArcs = domains.map(function (d, ix) {
      var a0 = -Math.PI / 2 + ix * wedge; // start at 12 o'clock, clockwise
      wedgeOf[d] = ix;
      return { domain: d, a0: a0, a1: a0 + wedge, mid: a0 + wedge / 2, index: ix };
    });

    var scale = radialScale(
      galaxies.map(function (g) {
        return (g.measures || {})[measure];
      }),
      { rInner: rInner, rOuter: rOuter }
    );

    var maxMentions = 0;
    for (var m = 0; m < galaxies.length; m++) {
      var mv = (galaxies[m].measures || {}).mentions || 0;
      if (mv > maxMentions) maxMentions = mv;
    }
    // Area proportional to the value (R4). maxR is deliberately modest: a star
    // that swallows its neighbours would turn the size channel into occlusion.
    var maxStar = opts.maxStar === undefined ? 13 : opts.maxStar;
    var sizeFn = V.sqrtAreaScale(maxMentions, maxStar);

    var placed = [];
    var unplaced = [];
    for (var k = 0; k < galaxies.length; k++) {
      var g = galaxies[k];
      var value = (g.measures || {})[measure];
      var mentions = (g.measures || {}).mentions || 0;
      var arc = domainArcs[wedgeOf[g.domain || ""]] || domainArcs[0];
      var rr = scale.r ? scale.r(value) : null;
      if (rr === null) {
        // A real observation that this scale cannot express. It keeps its ANGLE
        // (its domain is known) and is told apart by the band, not by a
        // fabricated radius.
        unplaced.push({
          id: g.id, name: g.name, domain: g.domain, value: value === undefined ? null : value,
          mentions: mentions, angle: _angleIn(arc, g.name, wedge),
          reason: value === 0 ? "zero" : "missing",
        });
        continue;
      }
      var a = _angleIn(arc, g.name, wedge);
      placed.push({
        id: g.id,
        name: g.name,
        domain: g.domain,
        angle: a,
        radius: rr,
        x: Math.cos(a) * rr,
        y: Math.sin(a) * rr,
        value: value,
        mentions: mentions,
        star: sizeFn(mentions),
        languages: g.languages || {},
        dominance: g.dominance || null,
        rate: g.rate || null,
        overlap: g.cross_group_overlap || {},
      });
    }
    // Draw order: faint first, bright last, so a big star is never hidden under
    // a small one. Deterministic tiebreak on name so the z-order is stable too.
    placed.sort(function (p, q) {
      return p.star - q.star || (p.name < q.name ? -1 : p.name > q.name ? 1 : 0);
    });

    return {
      measure: measure,
      domains: domainArcs,
      galaxies: placed,
      unplaced: unplaced,
      scale: scale,
      sizeFn: sizeFn,
      maxMentions: maxMentions,
      referenceStars: referenceStars(maxMentions, sizeFn),
      sizeFloorValue: sizeFloorValue(maxMentions, maxStar),
      minStar: MIN_STAR,
      edges: _edges(placed),
      nebula: (payload && payload.nebula) || null,
      rInner: rInner,
      rOuter: rOuter,
    };
  }

  /** Stable-hash angle inside one wedge, clear of both boundaries. */
  function _angleIn(arc, name, wedge) {
    var span = wedge * (1 - 2 * WEDGE_MARGIN);
    return arc.a0 + wedge * WEDGE_MARGIN + stableUnit(name) * span;
  }

  /**
   * Constellation edges from MEASURED shared membership. `cross_group_overlap`
   * maps a member key to the OTHER super-groups that also carry it, so an edge
   * is a fact about the data ("these two galaxies both contain `logic`") and
   * never an inference from how close two marks happen to sit. Each edge
   * carries its shared members so the readout can show n and name them.
   */
  function _edges(placed) {
    var byName = {};
    for (var i = 0; i < placed.length; i++) byName[placed[i].name] = placed[i];
    var seen = {};
    var out = [];
    for (var j = 0; j < placed.length; j++) {
      var g = placed[j];
      var ov = g.overlap || {};
      var members = Object.keys(ov);
      for (var m = 0; m < members.length; m++) {
        var others = ov[members[m]] || [];
        for (var o = 0; o < others.length; o++) {
          var other = byName[others[o]];
          if (!other) continue; // the partner is unplaced — no edge to draw
          var key = g.name < other.name ? g.name + "␟" + other.name : other.name + "␟" + g.name;
          if (!seen[key]) seen[key] = { a: g, b: other, shared: [] };
          if (seen[key].shared.indexOf(members[m]) < 0) seen[key].shared.push(members[m]);
        }
      }
    }
    var keys = Object.keys(seen).sort();
    for (var k = 0; k < keys.length; k++) {
      var e = seen[keys[k]];
      e.shared.sort();
      out.push({ a: e.a, b: e.b, shared: e.shared, n: e.shared.length });
    }
    return out;
  }

  /**
   * The galaxies in the canonical ranked order the sr-only table and the
   * keyboard traversal both use — measure descending, then name. The tabular
   * view is the canonical access path (invariant #8); the sky is a redundant
   * lens over it, so the two must agree by construction and this is the one
   * function that decides the order.
   */
  function rankedGalaxies(layout) {
    var rows = (layout.galaxies || []).slice();
    rows.sort(function (a, b) {
      return b.value - a.value || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    var tail = (layout.unplaced || []).slice().sort(function (a, b) {
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
    return rows.concat(tail);
  }

  // ----- drawing (browser only) ----- //

  /**
   * Paint one frame. `theme` carries already-resolved colour strings (the caller
   * reads them from CSS custom properties via ooViz.readCssVar and re-calls this
   * on a theme change, accessibility rule A3 — no hardcoded colour reaches here).
   * `view` is {cx, cy, scale, ox, oy} — pan and zoom are NAVIGATION only.
   *
   * Depth is three parallax layers (grid, edges, stars) offset at different
   * rates, and marks are SCREEN-SPACE sized: a star's radius never multiplies by
   * the view scale, so travelling toward the sky can never change how big a
   * magnitude looks (the reject-list rationale that 3D foreshortening fabricates
   * area). Static when idle — this is called on interaction, never on a loop.
   */
  function drawSky(ctx, layout, theme, view) {
    var w = view.w;
    var h = view.h;
    var cx = w / 2 + view.ox;
    var cy = h / 2 + view.oy;
    var z = view.scale;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = theme.bg;
    ctx.fillRect(0, 0, w, h);

    // -- layer 0: the nebula band. Its WIDTH is not a measurement and the legend
    //    says so; what is measured is the count printed beside it.
    if (layout.nebula && layout.nebula.nebula_keywords > 0) {
      var nr = layout.rOuter * z * R_NEBULA;
      ctx.save();
      ctx.globalAlpha = 0.1;
      ctx.strokeStyle = theme.muted;
      ctx.lineWidth = Math.max(4, layout.rOuter * z * 0.045);
      ctx.beginPath();
      ctx.arc(cx, cy, nr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }

    // -- layer 1 (slowest parallax): domain wedges + labelled orbit gridlines.
    var p1 = 0.94;
    var g1x = w / 2 + view.ox * p1;
    var g1y = h / 2 + view.oy * p1;
    ctx.save();
    ctx.strokeStyle = theme.border;
    ctx.lineWidth = 1;
    for (var d = 0; d < layout.domains.length; d++) {
      var arc = layout.domains[d];
      ctx.beginPath();
      ctx.moveTo(g1x, g1y);
      ctx.lineTo(
        g1x + Math.cos(arc.a0) * layout.rOuter * z,
        g1y + Math.sin(arc.a0) * layout.rOuter * z
      );
      ctx.stroke();
    }
    // THE WEDGE LABELS. Angle is the categorical axis, and an unlabelled
    // categorical axis is not an axis -- a reader could see twelve sectors and
    // have no way to learn which domain any of them was. Horizontal text rather
    // than text rotated onto the spoke: rotated labels are unreadable on the left
    // half unless flipped, and flipping makes the reading direction depend on
    // where a domain happens to sit. Alignment follows the side so a label always
    // grows away from the sky rather than across it.
    ctx.font = theme.tickFont;
    ctx.fillStyle = theme.muted;
    ctx.textBaseline = "middle";
    var lr = layout.rOuter * z * R_DOMAIN_LABEL;
    for (var dl = 0; dl < layout.domains.length; dl++) {
      var da = layout.domains[dl];
      var lx = g1x + Math.cos(da.mid) * lr;
      var ly = g1y + Math.sin(da.mid) * lr;
      var cosm = Math.cos(da.mid);
      ctx.textAlign = cosm > 0.25 ? "left" : cosm < -0.25 ? "right" : "center";
      ctx.fillText(da.domain, lx, ly);
    }
    ctx.textAlign = "center";
    // Orbit gridlines. Every one is LABELLED with the value it stands for —
    // an unlabelled ring would be decoration pretending to be a scale (#16).
    if (layout.scale.r) {
      ctx.font = theme.tickFont;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (var t = 0; t < layout.scale.ticks.length; t++) {
        var tv = layout.scale.ticks[t];
        var tr = layout.scale.r(tv) * z;
        if (!(tr > 0)) continue;
        ctx.beginPath();
        ctx.setLineDash([2, 4]);
        ctx.strokeStyle = theme.border;
        ctx.arc(g1x, g1y, tr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = theme.bg;
        var lbl = String(tv);
        var tw = ctx.measureText(lbl).width + 6;
        ctx.fillRect(g1x - tw / 2, g1y - tr - 7, tw, 14);
        ctx.fillStyle = theme.muted;
        ctx.fillText(lbl, g1x, g1y - tr);
      }
    }
    ctx.restore();

    // -- layer 2 (mid parallax): constellation edges, drawn from measured
    //    shared membership. Never proximity.
    var p2 = 0.97;
    var g2x = w / 2 + view.ox * p2;
    var g2y = h / 2 + view.oy * p2;
    ctx.save();
    ctx.strokeStyle = theme.edge;
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1;
    for (var e = 0; e < layout.edges.length; e++) {
      var ed = layout.edges[e];
      ctx.beginPath();
      ctx.moveTo(g2x + ed.a.x * z, g2y + ed.a.y * z);
      ctx.lineTo(g2x + ed.b.x * z, g2y + ed.b.y * z);
      ctx.stroke();
    }
    ctx.restore();

    // -- layer 3 (front): the galaxies themselves.
    for (var i = 0; i < layout.galaxies.length; i++) {
      var g = layout.galaxies[i];
      var x = cx + g.x * z;
      var y = cy + g.y * z;
      // SCREEN-SPACE radius: deliberately not multiplied by z.
      var r = Math.max(MIN_STAR, g.star);
      ctx.beginPath();
      ctx.fillStyle = theme.colorOf(g);
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
      if (g === view.focus || g === view.hover) {
        ctx.beginPath();
        ctx.strokeStyle = theme.fg;
        ctx.lineWidth = 2;
        ctx.arc(x, y, r + 4, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    // -- the "not observed yet" band: hollow marks OUTSIDE the value scale, so
    //    an absence can never be misread as the smallest measurement.
    if (layout.unplaced.length) {
      var ur = layout.rOuter * z * R_UNPLACED;
      ctx.save();
      ctx.strokeStyle = theme.muted;
      ctx.globalAlpha = 0.75;
      ctx.lineWidth = 1;
      for (var u = 0; u < layout.unplaced.length; u++) {
        var up = layout.unplaced[u];
        ctx.beginPath();
        ctx.arc(cx + Math.cos(up.angle) * ur, cy + Math.sin(up.angle) * ur, 2.5, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  /**
   * Nearest galaxy to a canvas point, or null past `maxDist`. Canvas has no DOM,
   * so hit-testing is manual (the framework's own note on the Canvas trade-off);
   * the KEYBOARD path does not go through here — it walks `rankedGalaxies`, so a
   * keyboard user never depends on pointer geometry.
   */
  function hitTest(layout, view, px, py, maxDist) {
    var cx = view.w / 2 + view.ox;
    var cy = view.h / 2 + view.oy;
    var z = view.scale;
    var best = null;
    var bestD = maxDist === undefined ? 18 : maxDist;
    for (var i = 0; i < layout.galaxies.length; i++) {
      var g = layout.galaxies[i];
      var dx = cx + g.x * z - px;
      var dy = cy + g.y * z - py;
      var dist = Math.sqrt(dx * dx + dy * dy) - Math.max(MIN_STAR, g.star);
      if (dist < bestD) {
        bestD = dist;
        best = g;
      }
    }
    return best;
  }

  var API = {
    LOG_MIN_SPAN: LOG_MIN_SPAN,
    WEDGE_MARGIN: WEDGE_MARGIN,
    MIN_STAR: MIN_STAR,
    sizeFloorValue: sizeFloorValue,
    hash32: hash32,
    stableUnit: stableUnit,
    radialScale: radialScale,
    referenceStars: referenceStars,
    skyLayout: skyLayout,
    rankedGalaxies: rankedGalaxies,
    drawSky: drawSky,
    hitTest: hitTest,
  };
  root.ooSky = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API; // node test
})(typeof self !== "undefined" ? self : typeof globalThis !== "undefined" ? globalThis : this);
