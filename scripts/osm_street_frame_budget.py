#!/usr/bin/env python3
"""Measure the street view's frame budget at the published caps, in Chromium (S07-02 S3, street half; row 187 item 5).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The street view draws at most ``POINTS_PER_VIEW`` roads holding at most ``VERTICES_PER_VIEW`` vertices (``src/osm/view.py``, Q822 = a).
This builds a synthetic street grid exactly at those caps (``src.osm.frame_budget.synthetic_grid``), loads the app's OWN street drawing
function out of ``src/static/app-map.js`` into a blank Chromium page (no app server, no data, no network), and draws the grid frame after
frame, reporting the milliseconds per frame (p50, p95, max, n) and the machine. The method and the caveat are
``src.osm.frame_budget.METHOD`` / ``CAVEAT``, printed with the figures.

    python scripts/osm_street_frame_budget.py --label "reference VM"                 # prints the report
    python scripts/osm_street_frame_budget.py --label "reference VM" --record        # and keeps it for the diagnostics bundle

``--record`` writes the result into this install's data folder, where the OSM diagnostics member's ``street_view`` slot reads it; without
it nothing is written. Run it with the app stopped or idle, since the machine is the thing being measured. Needs the Python Playwright client (the
``[uiwalk]`` extra) and a Chromium: Playwright's own under ``PLAYWRIGHT_BROWSERS_PATH``, or one named with ``--chromium``. Exit 0 measured, 2 refused (no browser,
or the drawing function was not found in the UI source).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.osm import frame_budget as fb  # noqa: E402
from src.osm import view as osm_view  # noqa: E402

APP_MAP = ROOT / "src" / "static" / "app-map.js"


def _function_source(src: str, name: str) -> str:
    """The text of ``function name(...) {...}`` in ``src``, by bracket matching (the node tests' ``fnSource``)."""
    at = src.find("function " + name + "(")
    if at < 0:
        raise LookupError(name)
    i, depth = src.index("(", at), 0
    while i < len(src):
        depth += {"(": 1, ")": -1}.get(src[i], 0)
        i += 1
        if depth == 0:
            break
    j, depth = src.index("{", i), 0
    while j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
        if depth == 0:
            break
    return src[at:j]


def drawing_source() -> str:
    """The street style table, the label cap, the label-width cache and ``_ooOsmDrawStreets``, exactly as the app ships them."""
    src = APP_MAP.read_text(encoding="utf-8")
    start = src.find("const _OO_OSM_STREET_STYLE")
    end = src.find("function _ooOsmDrawStreets(")
    if start < 0 or end < start:
        raise LookupError("_OO_OSM_STREET_STYLE")
    return src[start:end] + _function_source(src, "_ooOsmDrawStreets")


# The page: one canvas, the app's colours as fixed values (a theme's own are read from CSS in the app), and a measuring loop. Each frame
# pans the grid by a pixel, maps every road to the screen as the app's draw() does (a multiply and an add per vertex), redraws it whole,
# and, in the timed loop, reads one pixel back so the canvas has really finished the frame before the clock stops. The animation-frame
# loop reads nothing back, as the app's draw() reads nothing back.
_PAGE_JS = r"""
(async ({ roads, frames, warmup, w, h }) => {
  const cv = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  cv.style.width = w + "px"; cv.style.height = h + "px";
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  document.body.style.margin = "0"; document.body.appendChild(cv);
  const ctx = cv.getContext("2d");
  const pal = { "--bg": "#101418", "--fg": "#e6e6e6", "--muted": "#8a94a0", "--accent": "#4aa3ff", "--caveat": "#eab44e" };
  const color = (v) => pal[v] || "#888";
  const sz = { w, h };
  const one = (i, readBack) => {
    const t0 = performance.now();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const dx = -(i % 40);
    const placed = _ooOsmDrawStreets(ctx, roads, (r) => r.c.map(([x, y]) => [x + dx, y]), color, sz);
    if (readBack) ctx.getImageData(0, 0, 1, 1);
    return [performance.now() - t0, placed];
  };
  const draw = [], frame = [];
  let labels = 0;
  for (let i = 0; i < warmup + frames; i++) { const [ms, p] = one(i, true); labels = p; if (i >= warmup) draw.push(ms); }
  await new Promise((done) => {
    let i = 0, last = null;
    const tick = (now) => {
      if (last !== null && i > warmup) frame.push(now - last);
      last = now; one(i, false); i++;
      if (i <= warmup + frames) requestAnimationFrame(tick); else done();
    };
    requestAnimationFrame(tick);
  });
  return { draw, frame, labels, dpr };
})
"""


def _memory_gb() -> float | None:
    try:
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        return round(pages * size / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return None


def measure(*, label: str, frames: int, warmup: int, width: int, height: int, dpr: float, chromium: str | None) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("the Playwright client is not installed (the [uiwalk] extra)") from exc
    roads = fb.synthetic_grid(osm_view.POINTS_PER_VIEW, osm_view.VERTICES_PER_VIEW, width, height)
    code = drawing_source()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=dpr)
            page.set_content("<!doctype html><meta charset=utf-8><body></body>")
            page.add_script_tag(content=code + "\nwindow._ooOsmDrawStreets = _ooOsmDrawStreets;"
                                "\nwindow._OO_OSM_STREET_LABELS = _OO_OSM_STREET_LABELS;")
            got = page.evaluate(_PAGE_JS, {"roads": roads, "frames": frames, "warmup": warmup, "w": width, "h": height})
            labels_cap = page.evaluate("window._OO_OSM_STREET_LABELS")
            version = f"Chromium {browser.version} (headless)"
        finally:
            browser.close()
    return {
        "label": label[: fb.LABEL_MAX],
        "caps": {"roads": len(roads), "vertices": sum(len(r["c"]) for r in roads), "labels": labels_cap,
                 "labels_placed": got["labels"]},
        "canvas": {"w": width, "h": height, "dpr": got["dpr"]},
        "frames": frames,
        "warmup": warmup,
        "draw_ms": fb.summarise(got["draw"]),
        "frame_ms": fb.summarise(got["frame"]),
        "browser": version,
        "machine": {"os": platform.system() or None, "arch": platform.machine() or None, "cpus": os.cpu_count(),
                    "memory_gb": _memory_gb()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--label", required=True, help='what this machine is, in a few words ("sandbox", "reference VM")')
    ap.add_argument("--frames", type=int, default=120, help="frames counted (default 120)")
    ap.add_argument("--warmup", type=int, default=10, help="frames drawn first and not counted (default 10)")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--dpr", type=float, default=1.0, help="device pixel ratio (default 1)")
    ap.add_argument("--chromium", help="a Chromium executable, when Playwright's own is not installed")
    ap.add_argument("--record", action="store_true", help="keep the result for this install's diagnostics bundle")
    a = ap.parse_args(argv)
    if a.frames < 1 or a.warmup < 0:
        ap.error("--frames must be at least 1 and --warmup at least 0")
    try:
        res = measure(label=a.label, frames=a.frames, warmup=a.warmup, width=a.width, height=a.height, dpr=a.dpr,
                      chromium=a.chromium)
    except (RuntimeError, LookupError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - a browser that cannot start is a refusal, named by its class
        print(f"refused: the browser could not run the measurement ({type(exc).__name__})", file=sys.stderr)
        return 2
    caps = res["caps"]
    res["method"] = fb.METHOD.format(roads=caps["roads"], vertices=caps["vertices"], frames=a.frames, warmup=a.warmup)
    res["caveat"] = fb.CAVEAT
    if a.record:
        res["recorded"] = fb.record(res) is not None
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
