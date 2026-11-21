#!/usr/bin/env python3
"""Read the Wikipedia coverage report back from a returned Field data file (row 260, 0.6 gate row D).

Usage:
    python3 scripts/wiki_coverage_readback.py oo-field-YYYYMMDD-HHMM-<instance>-wiki-coverage.json [--json]

The file is what the Field data button saved from ``/api/wiki/lane/counters``: the lane's counters, the same figures the
Diagnostics zip carries in ``soak-window.json`` and Living sources shows. A file the button cut into numbered pieces
(``...-part-001-of-002.json``) can be given as any one of its pieces: the set is joined in memory, and a missing piece is
named rather than guessed at. A ``soak-window.json`` taken out of a Diagnostics zip is read too (its ``wiki`` block).

Prints one line per edition (the twelve first, as the report lists them): pages seen of the edition's own article count with
the total's state (row 257: read, read earlier and no longer refreshed, not read and why), the full-text range, the last event,
the gaps by reason and whether the walk finished its pass; then the totals and the located-address counters. A figure the
report does not have is printed with its reason, never as 0. Counts and dates only: no verdict, no score, no percentage.

Stdlib only; reads the file it is given and writes nothing; no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

#: What each total state means, in the words Living sources uses (src/static/app-living.js:livingTotalWhy).
_TOTAL_WORDS = {
    "read": "read",
    "stale_walk_off": "read {at}, no longer refreshed: the page walk is off",
    "not_read_walk_off": "not read: the page walk is off",
    "not_read_paused": "not read: the walk is paused ({reason})",
    "not_read_refused": "not read ({at}): the edition refused the count read ({reason})",
    "answer_unreadable": "not read: the edition's answer held no article count",
    "not_read_not_running": "not read: the walk runs only while the live stream runs",
    "not_read_yet": "not read yet",
    "unknown": "not read: the walk's switch could not be read",
}


def _pieces() -> Any:
    """``src/monitoring/field_pieces.py`` loaded by path (stdlib only), as the other read-back scripts do."""
    if "oo_field_pieces" in sys.modules:
        return sys.modules["oo_field_pieces"]
    spec = importlib.util.spec_from_file_location("oo_field_pieces", _HERE.parent / "src" / "monitoring" / "field_pieces.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load src/monitoring/field_pieces.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oo_field_pieces"] = mod
    spec.loader.exec_module(mod)
    return mod


def load(path: Path) -> dict[str, Any]:
    """The counters reading in ``path`` (a piece of a set is joined first). ValueError says what is wrong with the file."""
    if _pieces().piece_of(path) is not None:
        _name, data = _pieces().join_set(path)
    else:
        data = path.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: not a JSON file ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: not a counters reading (a JSON object was expected)")
    if "coverage" not in doc and isinstance(doc.get("wiki"), dict):
        doc = doc["wiki"]  # soak-window.json from a Diagnostics zip
    return doc


def _n(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else "—"


def _when(iso: Any) -> str:
    return str(iso)[:16].replace("T", " ") + " UTC" if isinstance(iso, str) and iso else "never"


def total_words(note: Any) -> str:
    """The total's state as words; a row from a build before row 257 (no state) says so."""
    if not isinstance(note, dict) or "state" not in note:
        return "state not recorded by this build"
    tpl = _TOTAL_WORDS.get(str(note.get("state")))
    if tpl is None:
        return f"state {note.get('state')!r} (unknown to this script)"
    return tpl.format(at=_when(note.get("at")), reason=note.get("reason") or "?")


def edition_line(row: dict[str, Any]) -> str:
    code = str(row.get("edition") or "?")
    if not row.get("has_run"):
        return f"{code}: no run yet ({row.get('reason') or 'no reason given'})"
    seen, total = row.get("pages_seen"), row.get("edition_articles")
    if not isinstance(seen, int):
        pages = "the walk has not run for this edition"
    elif isinstance(total, int):
        pages = f"{_n(seen)} of {_n(total)} pages seen"
    else:
        pages = f"{_n(seen)} pages seen, total unknown"
    parts = [pages, "total " + total_words(row.get("edition_articles_read"))]
    if row.get("walk_complete"):
        parts.append("walk pass complete")
    ft = row.get("full_text") or {}
    hot, warm = ft.get("hot_pages_with_text"), ft.get("warm_pages_with_text")
    if isinstance(hot, int) and isinstance(warm, int):
        parts.append(f"full text held for between {_n(max(hot, warm))} and {_n(hot + warm)} pages")
    elif isinstance(hot, int):
        parts.append(f"full text held for at least {_n(hot)} pages (the second tier has not run)")
    if row.get("last_event_unreadable"):
        parts.append("last event: could not be read")
    else:
        parts.append(f"last event: {_when(row.get('last_event_recorded_at'))}")
    gaps = row.get("gaps") or {}
    if isinstance(gaps.get("total"), int) and gaps["total"] > 0:
        by = ", ".join(f"{k} {_n(v)}" for k, v in sorted((gaps.get("by_reason") or {}).items()))
        parts.append(f"{_n(gaps['total'])} gaps ({by})" if by else f"{_n(gaps['total'])} gaps")
    else:
        parts.append("no gap recorded")
    return f"{code}: " + " · ".join(parts)


def located_lines(block: Any) -> list[str]:
    if not isinstance(block, dict):
        return ["located addresses: absent from this file"]
    if block.get("measured") is not True:
        return [f"located addresses: not measured ({block.get('reason') or 'no reason given'})"]
    per = block.get("per_edition") or {}
    if not per:
        return ["located addresses: no address found yet"]
    found = sum(int(v.get("found") or 0) for v in per.values() if isinstance(v, dict))
    located = sum(int(v.get("located") or 0) for v in per.values() if isinstance(v, dict))
    out = [f"located addresses: {_n(located)} of {_n(found)} found addresses located"
           + ("" if block.get("complete") else " (the scan has not read every stored page yet)")]
    for code in sorted(per):
        counts = per[code] if isinstance(per[code], dict) else {}
        out.append(f"  {code}: " + ", ".join(f"{k} {_n(v)}" for k, v in sorted(counts.items())))
    return out


def report(doc: dict[str, Any]) -> list[str]:
    """The read-back, one line per fact. An absent report says why instead of printing figures it does not have."""
    lines = [f"read at {_when(doc.get('read_at'))}"]
    if doc.get("measured") is False and "coverage" not in doc:
        return lines + [f"the Wikipedia lane was not read: {doc.get('detail') or doc.get('reason') or 'no reason given'}"]
    cov = doc.get("coverage")
    if not isinstance(cov, dict):
        return lines + ["no coverage report in this file (a build before S06-03)"]
    if cov.get("measured") is not True:
        return lines + [f"coverage not measured: {cov.get('reason') or 'no reason given'}"]
    rows = [r for r in cov.get("editions") or [] if isinstance(r, dict)]
    lines.append(f"{len(rows)} editions listed")
    lines += [edition_line(r) for r in rows]
    t = cov.get("totals") or {}
    lines.append(
        f"totals: {_n(t.get('pages_seen'))} pages seen; {_n(t.get('edition_articles'))} articles over the editions with a total; "
        f"{_n(t.get('editions_without_total'))} editions without a total; {_n(t.get('editions_with_a_run'))} editions with a run; "
        f"{_n(t.get('gaps'))} gaps"
    )
    lines += located_lines(cov.get("located"))
    unmeasured = doc.get("unmeasured")
    if isinstance(unmeasured, list) and unmeasured:
        lines.append("blocks not measured in this reading: " + ", ".join(map(str, unmeasured)))
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--json", action="store_true", help="print the coverage block itself, as read")
    args = ap.parse_args(argv)
    try:
        doc = load(args.file)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.file.name}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(doc.get("coverage"), indent=2, ensure_ascii=False))
    else:
        print("\n".join(report(doc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
