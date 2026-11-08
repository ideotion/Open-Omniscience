"""The operator's dated population table: the fallback weight for a population-weighted mean.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Slice S06-04 §S6 (ruling Q1153 = a). ``aggregate.py`` weights a mean by population when the
stored population series (``SP.POP.TOTL``) holds a figure for every member. A member the
stored series misses used to turn the whole weighted mean into a named refusal. This module
lets an operator supply ONE dated table that fills exactly those gaps, so the weighted figure
exists again AND says where each weight came from.

THE TABLE IS NOT SHIPPED. ``configs/population_table.json`` is an operator drop-in, absent by
default (the registry entry ``population-table`` reads "not built yet" until it exists), because
a population vintage is somebody's published data with its own terms and its own date, and this
repository must not make up either. Shape::

    {"source": "UN World Population Prospects 2024, medium variant",
     "as_of": "2024-07-11",
     "rows": {"FR": 66548530, "DE": 84552242}}

WHAT IT REFUSES (each returns a status and a reason, never an exception and never a partial table):

* **No file** → ``absent``. Not an error: nothing is filled and the refusal stands.
* **A file that cannot be read or parsed** → ``unreadable`` / ``malformed``.
* **No ``source`` or no usable ``as_of``** → ``undated``. A weight whose source and date cannot be
  stated on the figure is not offered at all: the slice's disclosure is the whole point.
* **A row that is not a two-letter code with a finite number above zero** → ``malformed``, naming
  the row. One bad row refuses the table, because a table with some rows silently dropped would
  weight a mean over a membership nobody can see.
* **The same country twice** (after case folding) → ``malformed``.

A member the table does not name stays a stated gap: ``fill_gaps`` never invents a weight.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_PATH", "fill_gaps", "load_population_table"]

#: Where the operator drops the table (relative to the repository root, like every other config).
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "configs" / "population_table.json"

_AS_OF = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
_CODE = re.compile(r"^[A-Za-z]{2}$")


def _real_date(text: str) -> bool:
    """``YYYY-MM`` or ``YYYY-MM-DD`` naming a day that exists (2024-99-99 matches the shape and is not a date)."""
    try:
        date.fromisoformat(text if len(text) == 10 else text + "-01")
    except ValueError:
        return False
    return True


def _refuse(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason, "weights": {}, "source": None, "as_of": None}


def load_population_table(path: str | Path | None = None) -> dict[str, Any]:
    """Read the operator's table. Never raises.

    Returns ``{"status", "reason", "weights", "source", "as_of"}``; ``weights`` maps the stored
    (lower-case alpha-2) country code to a population and is empty unless ``status == "ok"``.
    """
    p = Path(path) if path is not None else DEFAULT_PATH
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _refuse("absent", "no population table has been placed (an operator step)")
    except (OSError, UnicodeDecodeError) as exc:
        return _refuse("unreadable", f"the population table could not be read ({type(exc).__name__})")
    try:
        doc = json.loads(raw)
    except ValueError:
        return _refuse("malformed", "the population table is not valid JSON")
    if not isinstance(doc, dict):
        return _refuse("malformed", "the population table is not a JSON object")

    source = doc.get("source")
    as_of = doc.get("as_of")
    if not isinstance(source, str) or not source.strip():
        return _refuse("undated", "the population table names no source")
    if not isinstance(as_of, str) or not _AS_OF.match(as_of.strip()) or not _real_date(as_of.strip()):
        return _refuse("undated", "the population table carries no usable as_of date (YYYY-MM or YYYY-MM-DD)")

    rows = doc.get("rows")
    if not isinstance(rows, dict) or not rows:
        return _refuse("malformed", "the population table has no rows")
    weights: dict[str, float] = {}
    for code, value in rows.items():
        if not isinstance(code, str) or not _CODE.match(code):
            return _refuse("malformed", f"row {str(code)[:12]!r} is not a two-letter country code")
        try:
            number = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        except OverflowError:  # a JSON integer beyond float range
            number = None
        if number is None or not math.isfinite(number) or number <= 0:
            return _refuse("malformed", f"row {code!r} is not a finite population above zero")
        key = code.lower()
        if key in weights:
            return _refuse("malformed", f"country {code!r} appears twice")
        weights[key] = number
    return {"status": "ok", "reason": None, "weights": weights, "source": source.strip(), "as_of": as_of.strip()}


def fill_gaps(
    stored: Mapping[str, float | None],
    areas: list[str],
    table: Mapping[str, Any],
) -> tuple[dict[str, float | None], list[str]]:
    """The stored weights, with a member the stored series misses taken from the table.

    Returns ``(weights, from_table)``: ``weights`` has one entry per area (``None`` for a member
    NEITHER holds: a stated gap, never a guess) and ``from_table`` names the members whose weight
    came from the table, sorted. A stored figure always wins; the table only fills holes. Nothing
    is filled unless the table loaded ``ok``.
    """
    usable = table.get("weights") if table.get("status") == "ok" else None
    out: dict[str, float | None] = {}
    taken: list[str] = []
    for a in areas:
        got = stored.get(a)
        if got is None and usable and usable.get(a) is not None:
            out[a] = float(usable[a])
            taken.append(a)
        else:
            out[a] = got
    return out, sorted(taken)
