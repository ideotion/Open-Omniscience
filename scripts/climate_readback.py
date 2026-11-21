#!/usr/bin/env python3
"""Read the climate fetch record back from a returned Field data file (row 265, 0.6 gate row A).

Usage:
    python3 scripts/climate_readback.py oo-field-YYYYMMDD-HHMM-<instance>-climate-fetches.json [--json]

The file is what the Field data button saved from ``/api/climate/fetch-record``: per dataset, read from each unit's own fetch
record, how many units were fetched, how many last failed and why (a fixed token each), the newest dates and summed counts.
No unit is named (a GHCN station is a count), and no address or path. A file the button cut into numbered pieces can be given as any one of
its pieces: the set is joined in memory, and a missing piece is named rather than guessed at.

Prints one line per dataset the app offers (GISTEMP, NSIDC, ONI, USGS, OWID, GHCN): not fetched yet, or how many units were
fetched (and how many are not fetched yet), what the last fetches stored, and the units whose latest attempt failed, with their
reasons. A figure the record does not hold is printed as "not recorded", never as 0. Counts, dates and tokens only.

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
SCHEMA = "oo-field-climate-fetches-1"

#: The words for each reason token (src/stats/climate.py:FAILURE_REASONS). An unknown token is printed as itself.
REASON_WORDS = {
    "kill_switch": "refused by airplane mode (the kill switch), no request sent",
    "robots": "the host's robots.txt disallows it",
    "robots_unreadable": "the host's robots.txt could not be read, so the fetch was refused",
    "redirect_refused": "the fetcher refused the address or a redirect (off the dataset's site, or not public)",
    "transport_stopped": "stopped because the network mode (protected mode or proxy) changed during the fetch",
    "too_large": "the answer was larger than the table allows",
    "http_403": "the host answered 403 (forbidden)",
    "http_404": "the host answered 404 (not found)",
    "http_429": "the host answered 429 (too many requests)",
    "http_4xx": "the host answered another 4xx status",
    "http_5xx": "the host answered a 5xx status (server error)",
    "timeout": "the host did not answer in time",
    "connect": "no connection could be made",
    "unreadable_answer": "an answer came, but not the documented table",
    "other": "another error (not recognised)",
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
    """The record in ``path`` (a piece of a set is joined first). ValueError says what is wrong with the file."""
    if _pieces().piece_of(path) is not None:
        _name, data = _pieces().join_set(path)
    else:
        data = path.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: not a JSON file ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: not a climate fetch record (a JSON object was expected)")
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"{path.name}: schema {doc.get('schema')!r}, expected {SCHEMA!r}")
    return doc


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _n(value: Any) -> str:
    v = _int(value)
    return f"{v:,}" if v is not None else "not recorded"


def _when(iso: Any) -> str:
    return str(iso)[:16].replace("T", " ") + " UTC" if isinstance(iso, str) and iso else "at an unrecorded time"


def reason_words(token: Any) -> str:
    return REASON_WORDS.get(str(token), f"reason {token!r} (unknown to this script)")


def _units(n: int, kind: str) -> str:
    return f"{n} {kind}" + ("" if n == 1 else "s")


def dataset_line(name: str, d: Any) -> str:
    d = _dict(d)
    head = f"{name} ({d.get('host') or 'host not recorded'})"
    if not d:
        return f"{head}: not in this file"
    kind = "station" if d.get("unit_kind") == "station" else "unit"
    fetched, failed = _int(d.get("units_fetched")) or 0, _int(d.get("units_last_failed")) or 0
    if d.get("state") == "not_fetched_yet" or (not fetched and not failed):
        return f"{head}: not fetched yet"
    parts: list[str] = []
    offered, not_yet = _int(d.get("units_offered")), _int(d.get("units_not_fetched_yet"))
    if fetched:
        if offered is not None:
            parts.append(f"{fetched} of {_units(offered, kind)} fetched, {not_yet if not_yet is not None else '?'} not fetched yet")
        else:
            parts.append(f"{_units(fetched, kind)} fetched")
        parts.append(f"last fetch {_when(d.get('last_fetched_at'))}")
        if _int(d.get("figures")) == 0:
            parts.append("the source gave no figures")
        else:
            parts.append(f"{_n(d.get('figures'))} figures in the last fetches, {_n(d.get('new'))} new, {_n(d.get('revised'))} revised")
        parts.append(f"{_n(d.get('stored_rows'))} values stored")
    else:
        parts.append("not fetched yet" + (f" (0 of {_units(offered, kind)})" if offered is not None else ""))
    if failed:
        reasons = _dict(d.get("reasons"))
        why = "; ".join(f"{reason_words(k)} ({_n(v)})" for k, v in sorted(reasons.items())) or "no reason recorded"
        parts.append(f"latest attempt failed for {_units(failed, kind)}, last {_when(d.get('last_failed_at'))}: {why}")
    return f"{head}: " + " · ".join(parts)


def report(doc: dict[str, Any]) -> list[str]:
    lines = [f"read at {_when(doc.get('read_at'))}"]
    if doc.get("measured") is not True:
        return lines + [f"the climate fetch records were not read: {doc.get('reason') or 'no reason given'}"]
    listed = [str(x) for x in doc.get("datasets_listed") or [] if isinstance(x, str)]
    per = _dict(doc.get("datasets"))
    lines.append(f"{len(listed)} datasets offered")
    lines += [dataset_line(name, per.get(name)) for name in listed]
    tried = [n for n in listed if _dict(per.get(n)).get("state") in ("fetched", "failed")]
    fetched = [n for n in listed if _dict(per.get(n)).get("state") == "fetched"]
    lines.append(f"totals: {len(fetched)} fetched, {len(tried) - len(fetched)} only failed, {len(listed) - len(tried)} not fetched yet")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--json", action="store_true", help="print the record itself, as read")
    args = ap.parse_args(argv)
    try:
        doc = load(args.file)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.file.name}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2, ensure_ascii=False) if args.json else "\n".join(report(doc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
