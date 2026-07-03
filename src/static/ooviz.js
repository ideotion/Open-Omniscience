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

  // ----- choropleth / proportional symbols (the "normalized-only" ruling) ----- //

  /** Normalise a comparability dimension (null/undefined/"" => "", trimmed). */
  function _norm(v) {
    return v === null || v === undefined ? "" : String(v).trim();
  }
  /** Human display of a comparability value ("" => an em-dash placeholder). */
  function _show(v) {
    var s = _norm(v);
    return s === "" ? "—" : s;
  }

  /**
   * Parse a stat period label to a decimal year for "latest per area" selection.
   * Mirrors src/stats/series.py _parse_period: annual / semester / quarter / month /
   * week / day. Unparseable => NaN (the caller falls back to a raw-string compare, so a
   * weird label is never silently mis-ordered into "latest").
   */
  function periodToYear(period) {
    if (period === null || period === undefined) return NaN;
    var s = String(period).trim();
    var m;
    if (/^\d{4}$/.test(s)) return parseInt(s, 10);
    if ((m = /^(\d{4})[-_ ]?Q([1-4])$/i.exec(s))) return parseInt(m[1], 10) + (parseInt(m[2], 10) - 1) / 4;
    if ((m = /^(\d{4})[-_ ]?S([1-2])$/i.exec(s))) return parseInt(m[1], 10) + (parseInt(m[2], 10) - 1) / 2;
    if ((m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)))
      return parseInt(m[1], 10) + (parseInt(m[2], 10) - 1) / 12 + (parseInt(m[3], 10) - 1) / 365;
    if ((m = /^(\d{4})[-_ ]?W(\d{1,2})$/i.exec(s))) return parseInt(m[1], 10) + (parseInt(m[2], 10) - 1) / 52;
    if ((m = /^(\d{4})[-_ ]?M?(\d{1,2})$/i.exec(s))) {
      var mo = parseInt(m[2], 10);
      if (mo >= 1 && mo <= 12) return parseInt(m[1], 10) + (mo - 1) / 12;
    }
    return NaN;
  }

  /**
   * Build the honest data layer for a per-area map of ONE official-statistics
   * indicator. `rows` are StatFigure-shaped: {ref_area, value, unit, base_year,
   * adjustment, time_period}. The two honesty rules of the §5B "normalized-only"
   * ruling live in the SHAPE of the output:
   *
   *   (1) COMPARABILITY GATE — only areas sharing the MODAL (unit, base year,
   *       seasonal adjustment) basis are coloured/sized; an area on a different
   *       basis is comparable:false with a reason, so the renderer shows it as
   *       no-data (NEVER recoloured to fit one scale). A missing value is also
   *       no-data, with its own reason. The value DOMAIN spans comparable values
   *       only (a stray incomparable figure can't stretch the colour scale).
   *
   *   (2) LEVEL vs NORMALIZED — opts.kind==="level" (a count/total like population
   *       or GDP) REFUSES the choropleth (mode "symbols"): colouring a level makes
   *       a big country look "more" just for being big. The caller draws
   *       area-proportional symbols instead (see symbolRadii). opts.kind defaults
   *       to "normalized" (rate/ratio/%/per-capita) => mode "choropleth".
   *
   * One cell PER area: when opts.period is given, only that period; otherwise the
   * LATEST period each area has (periodToYear, raw-string tiebreak). Vintage dedup
   * is the caller's job (hand us one value per area+period). PURE, no DOM, no score.
   */
  function choroplethData(rows, opts) {
    opts = opts || {};
    rows = rows || [];
    var kind = opts.kind === "level" ? "level" : "normalized";
    var wantPeriod = opts.period !== undefined && opts.period !== null ? String(opts.period) : null;

    // One row per area: filter to the requested period, or keep each area's latest.
    var byArea = {};
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var area = _norm(r.ref_area);
      if (area === "") continue;
      if (wantPeriod !== null && _norm(r.time_period) !== wantPeriod) continue;
      var prev = byArea[area];
      if (!prev) {
        byArea[area] = r;
        continue;
      }
      var ry = periodToYear(r.time_period);
      var py = periodToYear(prev.time_period);
      var rk = Number.isNaN(ry) ? -Infinity : ry;
      var pk = Number.isNaN(py) ? -Infinity : py;
      if (rk > pk || (rk === pk && String(r.time_period) > String(prev.time_period))) byArea[area] = r;
    }

    // Modal comparability basis over areas that actually carry a value.
    var counts = {};
    var triples = {};
    var areas = Object.keys(byArea);
    for (var a = 0; a < areas.length; a++) {
      var row = byArea[areas[a]];
      if (isMissing(row.value)) continue;
      var key = _norm(row.unit) + "␟" + _norm(row.base_year) + "␟" + _norm(row.adjustment);
      counts[key] = (counts[key] || 0) + 1;
      if (!triples[key]) triples[key] = { unit: row.unit, base_year: row.base_year, adjustment: row.adjustment };
    }
    var basisKey = null;
    var best = -1;
    var keys = Object.keys(counts);
    for (var c = 0; c < keys.length; c++) {
      if (counts[keys[c]] > best) {
        best = counts[keys[c]];
        basisKey = keys[c];
      }
    }
    var basis = basisKey !== null ? triples[basisKey] : null;

    function basisReason(row) {
      if (_norm(row.unit) !== _norm(basis.unit))
        return "unit '" + _show(row.unit) + "' differs from '" + _show(basis.unit) + "'";
      if (_norm(row.base_year) !== _norm(basis.base_year))
        return "base year " + _show(row.base_year) + " differs from " + _show(basis.base_year);
      if (_norm(row.adjustment) !== _norm(basis.adjustment))
        return "adjustment '" + _show(row.adjustment) + "' differs from '" + _show(basis.adjustment) + "'";
      return "differs from the comparable basis";
    }

    var cells = [];
    var comparableCount = 0;
    var incomparableCount = 0;
    var noValueCount = 0;
    var vmin = Infinity;
    var vmax = -Infinity;
    for (var k = 0; k < areas.length; k++) {
      var rr = byArea[areas[k]];
      var cell = { area: areas[k], value: rr.value, period: rr.time_period, comparable: false, reason: null };
      if (isMissing(rr.value)) {
        cell.reason = "no value for this period";
        noValueCount += 1;
      } else if (basis !== null && _norm(rr.unit) === _norm(basis.unit) && _norm(rr.base_year) === _norm(basis.base_year) && _norm(rr.adjustment) === _norm(basis.adjustment)) {
        cell.comparable = true;
        comparableCount += 1;
        if (rr.value < vmin) vmin = rr.value;
        if (rr.value > vmax) vmax = rr.value;
      } else {
        cell.reason = basisReason(rr);
        incomparableCount += 1;
      }
      cells.push(cell);
    }
    cells.sort(function (x, y) {
      return x.area < y.area ? -1 : x.area > y.area ? 1 : 0;
    });

    var domain = comparableCount > 0 ? [vmin, vmax] : null;
    var caveat =
      kind === "level"
        ? "A level (count or total) is shown as area-proportional symbols, not colour — a choropleth would make a large area look like 'more' just for being big. Symbol area is proportional to the value."
        : "Coloured by comparable values only — areas on a different unit, base year or seasonal adjustment show as no-data (never recoloured to one scale), as do areas with no value for this period.";

    return {
      mode: kind === "level" ? "symbols" : "choropleth",
      refusedChoropleth: kind === "level",
      refusalReason:
        kind === "level"
          ? "A level is not comparable across areas of different size; it is shown as proportional symbols."
          : null,
      basis: basis,
      cells: cells,
      comparableCount: comparableCount,
      incomparableCount: incomparableCount,
      noValueCount: noValueCount,
      domain: domain,
      caveat: caveat,
    };
  }

  /**
   * Area-honest proportional-symbol radii for the cells of a LEVEL indicator
   * (choroplethData mode "symbols"). Radius via sqrtAreaScale over the maximum
   * COMPARABLE, non-negative value, so AREA ∝ value (rule R4). A missing /
   * incomparable / negative value is shown:false with a reason (never a fake dot).
   */
  function symbolRadii(cells, maxRadius) {
    cells = cells || [];
    maxRadius = maxRadius || 20;
    var max = 0;
    for (var i = 0; i < cells.length; i++) {
      var c = cells[i];
      if (c.comparable && !isMissing(c.value) && c.value > max) max = c.value;
    }
    var scale = sqrtAreaScale(max, maxRadius);
    return cells.map(function (c) {
      if (!c.comparable || isMissing(c.value))
        return { area: c.area, value: c.value, r: 0, shown: false, reason: c.reason || "no comparable value" };
      if (c.value < 0)
        return { area: c.area, value: c.value, r: 0, shown: false, reason: "negative value — not a proportional symbol" };
      return { area: c.area, value: c.value, r: scale(c.value), shown: true, reason: null };
    });
  }

  // ----- slope chart geometry (Tufte slope / bump; honest by SHARED scale) ----- //

  /**
   * Pure geometry for a SLOPE chart: several series, each carrying one value per
   * ordered STAGE, connected by straight segments across the stages. The honesty
   * lives in the SHAPE of the output:
   *   - ONE shared value scale over every finite value across every series, so two
   *     series are directly comparable (a slope means the same thing everywhere);
   *   - a missing value (isMissing) is a GAP: its point carries y:null + missing:true
   *     so the renderer BREAKS the line there and NEVER bridges/zero-fills it (a
   *     stage a term simply isn't in is absence, not a measured zero);
   *   - straight segments between ADJACENT measured stage values — never an
   *     interpolated curve through unmeasured points.
   *
   * series: [{label, values:[v|null, ...]}] aligned to opts.stages (the x labels).
   * Returns pixel-space positions; the caller only templates the SVG. PURE, no DOM.
   */
  function slopeGeometry(series, opts) {
    opts = opts || {};
    series = series || [];
    var width = opts.width || 320;
    var height = opts.height || 220;
    var pad = opts.pad || { l: 8, r: 8, t: 14, b: 22 };
    var stages = opts.stages || [];
    var nStages = stages.length;
    var vs = [];
    for (var i = 0; i < series.length; i++) {
      var vals = series[i].values || [];
      for (var j = 0; j < vals.length; j++) if (!isMissing(vals[j])) vs.push(vals[j]);
    }
    var v0 = vs.length ? Math.min.apply(null, vs) : 0;
    var v1 = vs.length ? Math.max.apply(null, vs) : 1;
    var stageX = [];
    for (var s = 0; s < nStages; s++) {
      stageX.push(nStages < 2 ? pad.l + (width - pad.l - pad.r) / 2
        : pad.l + (width - pad.l - pad.r) * (s / (nStages - 1)));
    }
    var sy = linearScale(v0, v1, height - pad.b, pad.t); // inverted: larger value => higher
    var outSeries = series.map(function (se) {
      var vals = se.values || [];
      var pts = [];
      for (var k = 0; k < nStages; k++) {
        var v = vals[k];
        var miss = isMissing(v);
        pts.push({ stage: k, x: stageX[k], value: miss ? null : v, missing: miss, y: miss ? null : sy(v) });
      }
      return { label: se.label, points: pts };
    });
    var yTicks = niceTicks(v0, v1, 4).map(function (v) { return { value: v, y: sy(v) }; });
    return {
      width: width, height: height, pad: pad,
      stages: stages.map(function (lb, ix) { return { label: lb, x: stageX[ix] }; }),
      series: outSeries, yTicks: yTicks, valueDomain: [v0, v1], nSeries: series.length, nStages: nStages,
    };
  }

  /**
   * Deterministic small-multiples GRID layout: N panels into a responsive column
   * grid. cols defaults to a near-square (ceil(sqrt(n))) bounded by opts.maxCols,
   * so the caller can render each cell at a shared scale (the small-multiples
   * honesty win — comparable panels). PURE: returns {cols, rows, count, cells}.
   */
  function gridLayout(n, opts) {
    opts = opts || {};
    n = Math.max(0, n | 0);
    var maxCols = opts.maxCols || 4;
    var cols = opts.cols ? Math.max(1, opts.cols | 0) : Math.max(1, Math.min(maxCols, Math.ceil(Math.sqrt(n)) || 1));
    var rows = Math.max(1, Math.ceil(n / cols));
    var cells = [];
    for (var i = 0; i < n; i++) cells.push({ i: i, col: i % cols, row: Math.floor(i / cols) });
    return { cols: cols, rows: rows, count: n, cells: cells };
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
    slopeGeometry: slopeGeometry,
    gridLayout: gridLayout,
    periodToYear: periodToYear,
    choroplethData: choroplethData,
    symbolRadii: symbolRadii,
    binCounts1D: binCounts1D,
    bin2D: bin2D,
    fiveNumberSummary: fiveNumberSummary,
    setupCanvas: setupCanvas,
    readCssVar: readCssVar,
  };
  root.ooViz = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API; // node test
})(typeof self !== "undefined" ? self : typeof globalThis !== "undefined" ? globalThis : this);
