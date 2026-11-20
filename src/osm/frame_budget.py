"""The street view's frame budget: what one frame costs at the published caps, and on which machine (S07-02 S3, street half).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The street view (#2134) draws the roads of a view itself, on a Canvas 2D, from this computer's osm.db. The server sends at most
``POINTS_PER_VIEW`` roads and ``VERTICES_PER_VIEW`` vertices (Q822 = a); what a frame of that costs in a browser was never written
down anywhere. ``scripts/osm_street_frame_budget.py`` measures it: it builds a SYNTHETIC street grid exactly at the caps
(:func:`synthetic_grid`), draws it frame after frame in Chromium with the app's own drawing function, and reports the milliseconds per
frame (p50, p95, max, n) and the machine. ``--record`` keeps the result here, and the OSM diagnostics member's ``street_view`` slot reads
it back (:func:`member_slot`).

A machine that has not run it reads ``not measured`` with its reason, never ``0``: an unmeasured frame is not a free one. No bar is set
here (Q1017 = a): the figures are reported, not judged.

The record holds counts, milliseconds, the canvas size, the browser's version, the kind of machine and the label the operator gave the
run (``sandbox``, ``reference VM``): no path, no host name, no place.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

#: The record's file, beside the KPI instruments' records in ``<data>/diagnostics``.
RECORD_NAME = "osm-street-frame-budget.json"
SCHEMA = "osm-street-frame-budget/1"
#: The longest operator label kept; a label is a name for the machine, not a note.
LABEL_MAX = 40
#: What the member says when nothing has been measured here.
NOT_MEASURED_REASON = (
    "no street-view frame budget has been recorded on this machine; the osm_street_frame_budget.py script measures one with --record"
)
METHOD = (
    "A synthetic street grid exactly at the published caps ({roads} roads, {vertices} vertices, most of them minor streets, the major roads longer with a straight run, every road "
    "named) is drawn {frames} times in Chromium with the app's own street drawing function, panned one pixel per frame. draw_ms is the "
    "time of one full redraw (clear, every class stroked, the labels placed) ending with a one-pixel read that makes the canvas finish "
    "the frame; frame_ms is the time between two animation frames while one redraw runs in each, with no read-back (as in the app), "
    "so it includes the browser's own painting and is never below the display's frame interval. The first {warmup} frames are not counted."
)
CAVEAT = (
    "A synthetic grid, not a real city: a real view at the caps has the same numbers of roads and vertices but other lengths, crossings "
    "and names. A headless browser draws without the display a person uses, often in software; draw_ms's read-back can also move a canvas the GPU drew to the CPU, which frame_ms avoids. The figure is this machine's, under the "
    "label it was given."
)

#: How many stretches of the grid a major road (tertiary and above) runs.
MAJOR_SPANS = 8
#: The street classes' share of the roads in the synthetic grid, by the index of ``view.STREET_CLASSES`` (motorway first). Most of a
#: city's ways are minor streets and service roads; the few major ones are the long ones. A design choice, stated in the method.
CLASS_SHARE = (0.005, 0.005, 0.02, 0.03, 0.06, 0.48, 0.25, 0.14, 0.01)


def _clean(value: Any, limit: int) -> str:
    """Letters, digits, spaces and ``-_()+`` only (anything else becomes ``-``), at most ``limit`` characters.

    The label names a KIND of machine ("sandbox", "reference VM"), never a host. No slash, colon or dot survives, so no path, URL,
    dotted address or host name does; and a run of three or more digit groups (an address whose dots became dashes) is dropped too.
    """
    text = "".join(ch if (ch.isalnum() or ch in " -_()+") else "-" for ch in str(value or ""))
    return _ADDRESSY.sub("-", text)[:limit].strip()


_ADDRESSY = re.compile(r"\d+(?:-+\d+){2,}")
#: The only browser string shown: what the script writes.
_BROWSER = re.compile(r"Chromium \d+(?:\.\d+){0,3} \(headless\)")
#: An os or arch name as Python's platform module gives one.
_PLATFORM = re.compile(r"[A-Za-z0-9_]{1,20}")


def clean_label(value: Any) -> str:
    """The operator's label for the machine, cleaned (:func:`_clean`) to at most :data:`LABEL_MAX` characters."""
    return _clean(value, LABEL_MAX) or "unlabelled"


def _quantile(sorted_vals: list[float], q: float) -> float:
    """The nearest-rank quantile of an already sorted, non-empty list."""
    i = max(0, min(len(sorted_vals) - 1, math.ceil(q * len(sorted_vals)) - 1))
    return sorted_vals[i]


def summarise(samples: list[float]) -> dict[str, Any] | None:
    """``n``, p50, p95 and the max of the measured milliseconds; None when nothing was measured (never a zero)."""
    vals = sorted(float(v) for v in samples if v is not None and math.isfinite(float(v)) and float(v) >= 0)
    if not vals:
        return None
    return {"n": len(vals), "p50": round(_quantile(vals, 0.5), 2), "p95": round(_quantile(vals, 0.95), 2), "max": round(vals[-1], 2)}


def synthetic_grid(roads: int, vertices: int, width: float, height: float) -> list[dict[str, Any]]:
    """``roads`` roads holding ``vertices`` vertices in all, in screen pixels over ``width`` x ``height``, as the street view receives them.

    Each road is ``{"k": class, "name": ..., "c": [[x, y], ...]}``: a stretch of a horizontal or vertical street of the grid, with its
    vertices spread along it and a small deterministic wobble; a major road runs :data:`MAJOR_SPANS` stretches, its bends near the start
    and a long straight after them, so the labels have somewhere to go (no randomness: the same caps give the same grid, so two runs differ only by
    the machine). The classes follow :data:`CLASS_SHARE`; the vertices are dealt out so the total is exactly ``vertices``.
    """
    if roads < 1 or vertices < 2 * roads:
        raise ValueError("a road needs at least two vertices")
    counts = [int(round(roads * s)) for s in CLASS_SHARE]
    counts[5] += roads - sum(counts)  # whatever rounding left goes to the minor streets, the commonest class
    classes = [k for k, n in enumerate(counts) for _ in range(n)]
    # The classes are spread over the grid by a fixed multiplicative hash, so a major road is not always in one corner.
    spread = sorted(range(roads), key=lambda i: (i * 2654435761) % 2**32)
    per = [vertices // roads + (1 if i < vertices % roads else 0) for i in range(roads)]
    lines = max(1, int(math.sqrt(roads / 2)))
    segs = math.ceil(roads / (2 * lines))
    out: list[dict[str, Any]] = []
    for i in range(roads):
        vert = i % 2 == 1
        line, seg = (i // 2) % lines, (i // 2) // lines
        across, along_len = (width, height) if vert else (height, width)
        at = (line + 0.5) / lines * across
        span = along_len / segs
        k = classes[spread[i]]
        nv = per[i]
        # A major road (tertiary and above) runs MAJOR_SPANS stretches of the grid with a long straight middle, as a thinned arterial
        # does, so the label path is exercised; a minor one wobbles along its own stretch.
        length = span * (MAJOR_SPANS if k <= 4 else 1)
        pts = []
        for j in range(nv):
            frac = j / (nv - 1)
            if k <= 4 and 0 < j < nv - 1:
                frac = 0.1 * j / (nv - 2)  # the bends near the start; the last segment is the straight
            along = min(along_len, seg * span + length * frac)
            wob = 1.5 * math.sin(0.7 * j + 0.3 * line)
            pts.append([round(at + wob, 2), round(along, 2)] if vert else [round(along, 2), round(at + wob, 2)])
        out.append({"k": k, "name": f"Street {line + 1}-{seg + 1}{'N' if vert else 'E'}", "c": pts})
    return out


def _path(create: bool = False):
    """Where the record lives; only a write creates the folder, so reading an install that never measured leaves no trace."""
    from src.paths import data_dir

    d = data_dir() / "diagnostics"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d / RECORD_NAME


def record(result: dict[str, Any]) -> dict[str, Any] | None:
    """Keep a measured run as this machine's street-view frame budget. Best-effort: a failed write records nothing."""
    from datetime import UTC, datetime

    keep = {k: result.get(k) for k in ("label", "caps", "canvas", "frames", "warmup", "draw_ms", "frame_ms", "browser", "machine")}
    keep["label"] = clean_label(keep.get("label"))
    rec = {"schema": SCHEMA, "measured_at": datetime.now(UTC).replace(microsecond=0).isoformat(), **keep}
    try:
        from src.safety.file_lock import atomic_replace

        atomic_replace(_path(create=True), json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - a measurement's record never breaks the measurement
        return None
    return rec


def _num(v: Any) -> float | int | None:
    """A JSON number, or None. An int is taken as it is (``math.isfinite`` would raise on one too large for a float)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return v if isinstance(v, float) and math.isfinite(v) else None


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


#: A time as :func:`record` writes it; anything else in that field is not shown.
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\+00:00|Z)?")


def _stat(v: Any) -> dict[str, Any] | None:
    if not isinstance(v, dict):
        return None
    out = {k: _num(v.get(k)) for k in ("n", "p50", "p95", "max")}
    return out if all(x is not None for x in out.values()) else None


def member_slot() -> dict[str, Any]:
    """The ``street_view`` part of the OSM diagnostics member: the recorded frame budget, or ``not measured`` with its reason.

    Only the fields this module writes are read back, each checked for its kind: a hand-edited or foreign file shows what it got right and
    names the rest unreadable, never passes free text through. Small by construction (under 1 KB) inside R421's 20,000 B slot.
    """
    try:
        p = _path()
        if not p.exists():
            return {"state": "not measured", "reason": NOT_MEASURED_REASON}
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - the member never raises
        return {"state": "unreadable", "reason": "the recorded frame budget could not be read; measure again to replace it"}
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return {"state": "unreadable", "reason": "the recorded frame budget is not in this build's format; measure again to replace it"}
    draw, frame = _stat(raw.get("draw_ms")), _stat(raw.get("frame_ms"))
    caps, canvas, machine = (_dict(raw.get(k)) for k in ("caps", "canvas", "machine"))
    browser, when = raw.get("browser"), raw.get("measured_at")
    out: dict[str, Any] = {
        "state": "measured" if draw or frame else "unreadable",
        "measured_at": when if isinstance(when, str) and _ISO.fullmatch(when) else None,
        "label": clean_label(raw.get("label")),
        "caps": {k: _num(caps.get(k)) for k in ("roads", "vertices", "labels")},
        "canvas": {k: _num(canvas.get(k)) for k in ("w", "h", "dpr")},
        "draw_ms": draw,
        "frame_ms": frame,
        "browser": browser if isinstance(browser, str) and _BROWSER.fullmatch(browser) else None,
        "machine": {
            "os": machine["os"] if isinstance(machine.get("os"), str) and _PLATFORM.fullmatch(machine["os"]) else None,
            "arch": machine["arch"] if isinstance(machine.get("arch"), str) and _PLATFORM.fullmatch(machine["arch"]) else None,
            "cpus": _num(machine.get("cpus")),
            "memory_gb": _num(machine.get("memory_gb")),
        },
        "method": "the osm_street_frame_budget.py script; its method and caveat are printed with every run",
    }
    if out["state"] == "unreadable":
        out["reason"] = "the record holds no readable timing; measure again to replace it"
    else:
        for name, val in (("draw_ms", draw), ("frame_ms", frame)):
            if val is None:
                out.setdefault("unmeasured", {})[name] = "this run did not record it"
    return out
