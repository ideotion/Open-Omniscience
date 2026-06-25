// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Ideotion
//
// honest-charts.js
// Zero-dependency primitives for honest, accessible, no-library charts.
// No D3, no charting libraries, no network, no DOM required for the math.
// Deterministic by construction: nothing here calls Math.random.
//
// Companion to "Honest, Accessible Chart-Type Decision Framework".
// Browser usage:  <script type="module"> import { linearScale } from './honest-charts.js'
// Node usage:     import { linearScale } from './honest-charts.js'

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

/** Clamp v into [lo, hi]. */
export function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

/** True for values that must render as a GAP, never as zero (honesty rule H2). */
export function isMissing(v) {
  return v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));
}

// ---------------------------------------------------------------------------
// Scales (replace d3.scaleLinear etc.)
// ---------------------------------------------------------------------------

/**
 * Linear scale mapping domain [d0,d1] to range [r0,r1].
 * Returns f(value) with f.invert(pixel). Position encoding: a non-zero domain
 * is allowed for dots/lines, but is the caller's deliberate, labelled choice.
 */
export function linearScale(d0, d1, r0, r1) {
  const span = d1 - d0 || 1; // guard zero-width domains deterministically
  const m = (r1 - r0) / span;
  const f = (v) => r0 + (v - d0) * m;
  f.invert = (p) => d0 + (p - r0) / m;
  f.domain = [d0, d1];
  f.range = [r0, r1];
  return f;
}

/**
 * Area-honest size scale for proportional symbols (bubbles, symbol maps).
 * AREA is proportional to value, so radius is proportional to sqrt(value).
 * This is the only honest way to size a circle by a quantity (framework R4).
 * radius(maxValue) === maxRadius; radius(0) === 0.
 */
export function sqrtAreaScale(maxValue, maxRadius) {
  const denom = maxValue > 0 ? maxValue : 1;
  return (v) => (v <= 0 ? 0 : maxRadius * Math.sqrt(v / denom));
}

// ---------------------------------------------------------------------------
// Nice 1-2-5 ticks (replace d3 ticks); deterministic and float-clean
// ---------------------------------------------------------------------------

/**
 * Generate "nice" tick values across [min,max] near `target` count,
 * using a 1/2/5 * 10^k step. Output is rounded to the step's precision so
 * values are clean (0, 0.2, 0.4, ... not 0.6000000000000001).
 */
export function niceTicks(min, max, target = 6) {
  if (max < min) [min, max] = [max, min];
  const span = max - min || 1;
  const raw = span / Math.max(1, target);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const decimals = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
  const start = Math.ceil(min / step - 1e-9) * step;
  const ticks = [];
  for (let t = start; t <= max + step * 1e-9; t += step) {
    ticks.push(Number(t.toFixed(decimals)));
  }
  return ticks;
}

// ---------------------------------------------------------------------------
// Deterministic PRNG (seeded jitter / layout) - satisfies honesty rule H5
// ---------------------------------------------------------------------------

/** Seedable PRNG. Same seed => identical sequence => identical pixels. */
export function mulberry32(seed) {
  let s = seed | 0;
  return function () {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------------------
// Line paths that BREAK at gaps (never interpolate) - satisfies rule H2
// ---------------------------------------------------------------------------

/**
 * Build an SVG path "d" from points where a missing point (null/undefined/NaN
 * value, see isMissing) starts a new subpath. The line is never drawn across
 * a gap. `sx`/`sy` are scale functions; each point is {x, y} (y may be missing).
 */
export function pathWithGaps(points, sx, sy) {
  let d = "";
  let pen = false;
  for (const p of points) {
    if (p == null || isMissing(p.y) || isMissing(p.x)) {
      pen = false; // break: do not bridge the gap
      continue;
    }
    d += (pen ? "L" : "M") + sx(p.x) + " " + sy(p.y) + " ";
    pen = true;
  }
  return d.trim();
}

// ---------------------------------------------------------------------------
// Binning (overplotting fix that is also the honesty fix) - frameworks 4.8/4.9
// ---------------------------------------------------------------------------

/**
 * 1D histogram counts over a fixed domain split into `count` equal bins.
 * Returns an array of length `count`. Missing values are ignored (not zeroed).
 */
export function binCounts1D(values, { min, max, count }) {
  const width = (max - min) / count || 1;
  const bins = new Array(count).fill(0);
  for (const v of values) {
    if (isMissing(v)) continue;
    const idx = clamp(Math.floor((v - min) / width), 0, count - 1);
    bins[idx] += 1;
  }
  return bins;
}

/**
 * 2D histogram counts (for hexbin/heatmap density). Returns grid[iy][ix].
 * extent = {xmin, xmax, ymin, ymax}. Reduces ~10k points to nx*ny cells so
 * SVG stays cheap and density is shown honestly instead of overplotting.
 */
export function bin2D(points, nx, ny, extent) {
  const { xmin, xmax, ymin, ymax } = extent;
  const wx = (xmax - xmin) || 1;
  const wy = (ymax - ymin) || 1;
  const grid = Array.from({ length: ny }, () => new Array(nx).fill(0));
  for (const p of points) {
    if (p == null || isMissing(p.x) || isMissing(p.y)) continue;
    const ix = clamp(Math.floor(((p.x - xmin) / wx) * nx), 0, nx - 1);
    const iy = clamp(Math.floor(((p.y - ymin) / wy) * ny), 0, ny - 1);
    grid[iy][ix] += 1;
  }
  return grid;
}

// ---------------------------------------------------------------------------
// Distribution summary (box plots) - honest only when n is shown - framework 4.10
// ---------------------------------------------------------------------------

/**
 * Five-number summary using R-7 (linear interpolation) quantiles, plus n.
 * Always returns n so the caller can refuse to draw a box over tiny samples.
 */
export function fiveNumberSummary(values) {
  const a = values.filter((v) => !isMissing(v)).slice().sort((x, y) => x - y);
  const n = a.length;
  if (n === 0) return { min: NaN, q1: NaN, median: NaN, q3: NaN, max: NaN, n: 0 };
  const q = (p) => {
    const pos = p * (n - 1);
    const lo = Math.floor(pos);
    const frac = pos - lo;
    return lo + 1 < n ? a[lo] + frac * (a[lo + 1] - a[lo]) : a[lo];
  };
  return { min: a[0], q1: q(0.25), median: q(0.5), q3: q(0.75), max: a[n - 1], n };
}

// ---------------------------------------------------------------------------
// Browser-only helpers (no-op friendly; guarded so the module imports in Node)
// ---------------------------------------------------------------------------

/**
 * Size a <canvas> for crisp rendering on high-DPI screens and return its 2D
 * context pre-transformed to CSS pixels. Pair the canvas with role="img" +
 * a hidden data table for accessibility (the canvas has no DOM marks).
 */
export function setupCanvas(canvas, cssW, cssH) {
  const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  canvas.style.width = cssW + "px";
  canvas.style.height = cssH + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

/**
 * Read a CSS custom property (theme token) as a trimmed string, so Canvas can
 * use the same colours as themed SVG/CSS and be redrawn on theme change.
 * No hardcoded colours anywhere (accessibility rule A3).
 */
export function readCssVar(name, el) {
  if (typeof window === "undefined") return "";
  const target = el || document.documentElement;
  return getComputedStyle(target).getPropertyValue(name).trim();
}
