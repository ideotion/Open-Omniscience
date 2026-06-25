/*
 * Open Omniscience — ooViz: zero-dependency primitives for honest, accessible,
 * no-library charts. GPL-3.0-or-later. (Adopted from the MIT-licensed research
 * primitive set docs/research/dataviz/honest-charts.js — same author, Ideotion;
 * the chart-decision framework is its companion.)
 *
 * No D3, no charting libraries, no network, no DOM required for the math.
 * Deterministic by construction: nothing here calls Math.random (seeded jitter
 * uses mulberry32). The honesty rules live in the SHAPE of the output:
 *   - isMissing flags a true GAP, never zero (rule H2);
 *   - pathWithGaps BREAKS the line at a gap, never bridging it;
 *   - statSeriesPaths renders a StatFigure chart-series (the src/stats/series.py
 *     to_chart_series output) as ONE subpath PER comparability segment — a unit /
 *     base-year / SA-NSA break is NEVER joined — each broken at its own gaps;
 *   - sqrtAreaScale sizes a symbol by AREA (the only honest way, rule R4).
 *
 * Dual node/browser: attaches root.ooViz AND module.exports (so the node test in
 * tests/ooviz_node_test.js can require it). The live chart wiring (ooChart drawing
 * these paths) is the browser-deferred Phase B2 follow-on.
 */
(function (root) {
  "use strict";

  // ----- small helpers ----- //

  /** Clamp v into [lo, hi]. */
  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  /** True for values that must render as a GAP, never as zero (honesty rule H2). */
  function isMissing(v) {
    return v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));
  }

  // ----- scales ----- //

  /**
   * Linear scale mapping domain [d0,d1] to range [r0,r1]. Returns f(value) with
   * f.invert(pixel). A non-zero domain is the caller's deliberate, labelled choice.
   */
  function linearScale(d0, d1, r0, r1) {
    var span = d1 - d0 || 1; // guard zero-width domains deterministically
    var m = (r1 - r0) / span;
    var f = function (v) {
      return r0 + (v - d0) * m;
    };
    f.invert = function (p) {
      return d0 + (p - r0) / m;
    };
    f.domain = [d0, d1];
    f.range = [r0, r1];
    return f;
  }

  /**
   * Area-honest size scale for proportional symbols. AREA ∝ value, so radius ∝
   * sqrt(value) — the only honest way to size a circle by a quantity (framework R4).
   * radius(maxValue) === maxRadius; radius(0) === 0.
   */
  function sqrtAreaScale(maxValue, maxRadius) {
    var denom = maxValue > 0 ? maxValue : 1;
    return function (v) {
      return v <= 0 ? 0 : maxRadius * Math.sqrt(v / denom);
    };
  }

  // ----- nice 1-2-5 ticks (deterministic, float-clean) ----- //

  function niceTicks(min, max, target) {
    if (target === undefined) target = 6;
    if (max < min) {
      var tmp = min;
      min = max;
      max = tmp;
    }
    var span = max - min || 1;
    var raw = span / Math.max(1, target);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    var decimals = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
    var start = Math.ceil(min / step - 1e-9) * step;
    var ticks = [];
    for (var t = start; t <= max + step * 1e-9; t += step) {
      ticks.push(Number(t.toFixed(decimals)));
    }
    return ticks;
  }

  // ----- deterministic PRNG (seeded jitter/layout) - honesty rule H5 ----- //

  /** Seedable PRNG. Same seed => identical sequence => identical pixels. */
  function mulberry32(seed) {
    var s = seed | 0;
    return function () {
      s = (s + 0x6d2b79f5) | 0;
      var t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ----- line paths that BREAK at gaps (never interpolate) - rule H2 ----- //

  /**
   * Build an SVG path "d" from points where a missing point (null/undefined/NaN
   * value, see isMissing) starts a new subpath. The line is never drawn across a
   * gap. sx/sy are scale functions; each point is {x, y} (y may be missing).
   */
  function pathWithGaps(points, sx, sy) {
    var d = "";
    var pen = false;
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      if (p == null || isMissing(p.y) || isMissing(p.x)) {
        pen = false; // break: do not bridge the gap
        continue;
      }
      d += (pen ? "L" : "M") + sx(p.x) + " " + sy(p.y) + " ";
      pen = true;
    }
    return d.trim();
  }

  /**
   * Render a StatFigure chart-series (the to_chart_series output:
   * {segments:[{unit, base_year, adjustment, points:[{period, t, value}]}]}) as an
   * array of honest subpaths — ONE per comparability segment. A unit / base-year /
   * seasonal-adjustment break starts a new, SEPARATE path (never joined across the
   * break); WITHIN a segment a value=null is a gap that breaks the line. sx maps
   * the decimal-year t → px, sy maps the value → px. Each entry carries the
   * segment's comparability metadata + its point count so the renderer can mark
   * the break and label the unit. NEVER interpolates and NEVER bridges a break.
   */
  function statSeriesPaths(series, sx, sy) {
    var segments = (series && series.segments) || [];
    var out = [];
    for (var i = 0; i < segments.length; i++) {
      var seg = segments[i];
      var srcPoints = seg.points || [];
      var pts = [];
      for (var j = 0; j < srcPoints.length; j++) {
        pts.push({ x: srcPoints[j].t, y: srcPoints[j].value });
      }
      out.push({
        d: pathWithGaps(pts, sx, sy),
        unit: seg.unit !== undefined ? seg.unit : null,
        base_year: seg.base_year !== undefined ? seg.base_year : null,
        adjustment: seg.adjustment !== undefined ? seg.adjustment : null,
        n: srcPoints.length,
      });
    }
    return out;
  }

  /**
   * Compute the full geometry of a stat time-series chart from a to_chart_series result.
   * PURE (no DOM): returns pixel-space paths (one per comparability segment, gaps broken via
   * statSeriesPaths) + axis ticks + the data domains, so the caller only templates SVG.
   *
   * The VALUE domain is [min,max] of the PLOTTABLE (non-gap) values — a level series is a
   * deliberate, labelled non-zero domain (the framework allows it for lines). The TIME domain
   * spans ALL points (gaps included), so a gap leaves a visible hole and never shifts the
   * axis. An empty series => empty paths over a unit box (the caller shows "no data").
   */
  function statChartGeometry(series, opts) {
    opts = opts || {};
    var width = opts.width || 640;
    var height = opts.height || 240;
    var pad = opts.pad || { l: 52, r: 12, t: 12, b: 28 };
    var segments = (series && series.segments) || [];
    var ts = [];
    var vs = [];
    for (var i = 0; i < segments.length; i++) {
      var pts = segments[i].points || [];
      for (var j = 0; j < pts.length; j++) {
        if (typeof pts[j].t === "number") ts.push(pts[j].t);
        if (!isMissing(pts[j].value)) vs.push(pts[j].value);
      }
    }
    var t0 = ts.length ? Math.min.apply(null, ts) : 0;
    var t1 = ts.length ? Math.max.apply(null, ts) : 1;
    var v0 = vs.length ? Math.min.apply(null, vs) : 0;
    var v1 = vs.length ? Math.max.apply(null, vs) : 1;
    var sx = linearScale(t0, t1, pad.l, width - pad.r);
    var sy = linearScale(v0, v1, height - pad.b, pad.t); // inverted: larger value => higher
    var paths = statSeriesPaths(series, sx, sy);
    var xTicks = niceTicks(t0, t1, 6).map(function (v) {
      return { value: v, x: sx(v) };
    });
    var yTicks = niceTicks(v0, v1, 5).map(function (v) {
      return { value: v, y: sy(v) };
    });
    var nPoints = 0;
    for (var k = 0; k < segments.length; k++) nPoints += (segments[k].points || []).length;
    return {
      width: width,
      height: height,
      pad: pad,
      paths: paths,
      xTicks: xTicks,
      yTicks: yTicks,
      timeDomain: [t0, t1],
      valueDomain: [v0, v1],
      nPoints: nPoints,
      nSegments: segments.length,
    };
  }

  // ----- binning (overplotting fix that is also the honesty fix) ----- //

  /**
   * 1D histogram counts over a fixed domain split into `count` equal bins.
   * Returns an array of length `count`. Missing values are ignored (not zeroed).
   */
  function binCounts1D(values, opts) {
    var min = opts.min;
    var max = opts.max;
    var count = opts.count;
    var width = (max - min) / count || 1;
    var bins = new Array(count).fill(0);
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (isMissing(v)) continue;
      var idx = clamp(Math.floor((v - min) / width), 0, count - 1);
      bins[idx] += 1;
    }
    return bins;
  }

  /**
   * 2D histogram counts (for hexbin/heatmap density). Returns grid[iy][ix].
   * extent = {xmin, xmax, ymin, ymax}.
   */
  function bin2D(points, nx, ny, extent) {
    var xmin = extent.xmin;
    var xmax = extent.xmax;
    var ymin = extent.ymin;
    var ymax = extent.ymax;
    var wx = xmax - xmin || 1;
    var wy = ymax - ymin || 1;
    var grid = [];
    for (var r = 0; r < ny; r++) grid.push(new Array(nx).fill(0));
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      if (p == null || isMissing(p.x) || isMissing(p.y)) continue;
      var ix = clamp(Math.floor(((p.x - xmin) / wx) * nx), 0, nx - 1);
      var iy = clamp(Math.floor(((p.y - ymin) / wy) * ny), 0, ny - 1);
      grid[iy][ix] += 1;
    }
    return grid;
  }

  // ----- distribution summary (box plots) - honest only when n is shown ----- //

  /**
   * Five-number summary using R-7 (linear interpolation) quantiles, plus n.
   * Always returns n so the caller can refuse to draw a box over a tiny sample.
   */
  function fiveNumberSummary(values) {
    var a = values
      .filter(function (v) {
        return !isMissing(v);
      })
      .slice()
      .sort(function (x, y) {
        return x - y;
      });
    var n = a.length;
    if (n === 0) return { min: NaN, q1: NaN, median: NaN, q3: NaN, max: NaN, n: 0 };
    var q = function (p) {
      var pos = p * (n - 1);
      var lo = Math.floor(pos);
      var frac = pos - lo;
      return lo + 1 < n ? a[lo] + frac * (a[lo + 1] - a[lo]) : a[lo];
    };
    return { min: a[0], q1: q(0.25), median: q(0.5), q3: q(0.75), max: a[n - 1], n: n };
  }

  // ----- browser-only helpers (guarded so the module imports in Node) ----- //

  /**
   * Size a <canvas> for crisp high-DPI rendering and return its 2D context
   * pre-transformed to CSS pixels. Pair with role="img" + a hidden data table.
   */
  function setupCanvas(canvas, cssW, cssH) {
    var dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return ctx;
  }

  /**
   * Read a CSS custom property (theme token) as a trimmed string, so Canvas can
   * use the same colours as themed SVG/CSS and be redrawn on theme change. No
   * hardcoded colours anywhere (accessibility rule A3).
   */
  function readCssVar(name, el) {
    if (typeof window === "undefined") return "";
    var target = el || document.documentElement;
    return getComputedStyle(target).getPropertyValue(name).trim();
  }

  var API = {
    clamp: clamp,
    isMissing: isMissing,
    linearScale: linearScale,
    sqrtAreaScale: sqrtAreaScale,
    niceTicks: niceTicks,
    mulberry32: mulberry32,
    pathWithGaps: pathWithGaps,
    statSeriesPaths: statSeriesPaths,
    statChartGeometry: statChartGeometry,
    binCounts1D: binCounts1D,
    bin2D: bin2D,
    fiveNumberSummary: fiveNumberSummary,
    setupCanvas: setupCanvas,
    readCssVar: readCssVar,
  };
  root.ooViz = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API; // node test
})(typeof self !== "undefined" ? self : typeof globalThis !== "undefined" ? globalThis : this);
