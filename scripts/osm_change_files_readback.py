#!/usr/bin/env python3
"""Read the OSM daily change-file cost back from a returned Field data file (row 263, 0.6 gate row B).

Usage:
    python3 scripts/osm_change_files_readback.py oo-field-YYYYMMDD-HHMM-<instance>-osm-change-files.json [--json]

The file is what the Field data button saved from ``/api/osm/change-files``: the Diagnostics zip's own ``osm-change-files.json`` member
(``src/osm/diagnostics.py:diagnostics_member``). A file the button cut into numbered pieces (``...-part-001-of-002.json``) can be given
as any one of its pieces: the set is joined in memory, and a missing piece is named rather than guessed at. The member taken out of a
Diagnostics zip is read the same way, and so is the zip itself (only that one member is read from it).

Prints, per country the daily files have touched: where its objects stand, how many change files were applied and what they cost
(bytes fetched, seconds to fetch and to apply: n files measured, the total, the mean per file and the largest), its gaps by kind
(a re-baseline or a hand re-cut) and the newest runs; then the countries no file has touched, by code, what the member cut to fit its
budget, the machine kind and the street view's frame budget state. A figure the file does not have is printed with its reason, never
as 0. Counts, country codes, sequence numbers and dates only: nothing else in the file is printed. No verdict, no score.

Stdlib only; reads the file it is given and writes nothing; no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
#: The member's name inside a Diagnostics zip (src/api/diagnostics_slots.py).
MEMBER = "osm-change-files.json"
#: The largest member read out of a zip. The slot's budget is 20,000 bytes; anything far past it is not the member.
_MAX_MEMBER_BYTES = 2_000_000
_COST_KEYS = (("bytes_fetched", "bytes fetched", ""), ("fetch_seconds", "fetch", " s"), ("apply_seconds", "apply", " s"))


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


def _from_zip(path: Path) -> bytes:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n == MEMBER or n.endswith("/" + MEMBER)]
        if not names:
            raise ValueError(f"{path.name}: a zip without {MEMBER} (a Diagnostics zip from a build before the OSM member?)")
        info = zf.getinfo(names[0])
        if info.file_size > _MAX_MEMBER_BYTES:
            raise ValueError(f"{path.name}: {MEMBER} is {info.file_size:,} bytes, far past the member's budget; not read")
        return zf.read(info)


def load(path: Path) -> dict[str, Any]:
    """The member in ``path`` (a piece of a set is joined first). ValueError says what is wrong with the file."""
    if zipfile.is_zipfile(path):
        data = _from_zip(path)
    elif _pieces().piece_of(path) is not None:
        _name, data = _pieces().join_set(path)
    else:
        data = path.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: not a JSON file ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: not a change-files reading (a JSON object was expected)")
    return doc


def _int(value: Any) -> int | None:
    """A count, or None for anything that is not one (a bool, a string, a missing key): never coerced into a 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _code(value: Any) -> str:
    """A country code as the member writes it (three capital letters); anything else is not printed."""
    return value if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha() and value.isupper() else "?"


def _when(iso: Any) -> str | None:
    """An ISO time cut to the minute, or None for anything that is not one (free text is never printed)."""
    if not isinstance(iso, str) or len(iso) < 10 or not iso[:4].isdigit() or iso[4] != "-":
        return None
    out = iso[:16].replace("T", " ")
    return out + " UTC" if len(out) > 10 else out


def _n(value: Any, unit: str = "") -> str:
    v = _num(value)
    if v is None:
        return "—"
    if isinstance(v, int):
        return f"{v:,}{unit}"
    return f"{v:,.3f}".rstrip("0").rstrip(".") + unit


#: The shape of the member's reasons: the code's own fixed words (letters and plain punctuation, no digit, slash or @). A reason
#: outside it (a hand-edited or foreign file) is not printed, so nothing but the member's words can reach the read-back (R734/R736).
_FIXED_WORDS = re.compile(r"[A-Za-z_ ,;:'()\-.]{1,240}")


def _reason(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value:
        return fallback
    return value if _FIXED_WORDS.fullmatch(value) else "a reason not in the member's fixed words (not printed)"


def cost_lines(row: dict[str, Any]) -> list[str]:
    """The country's measured cost, or its reason. ``n`` below ``diffs_recorded`` is said: some files did not measure that figure."""
    cost = row.get("cost")
    if not isinstance(cost, dict):
        return [f"  cost: not measured: {_reason(row.get('cost_reason'), 'no reason given in this file')}"]
    recorded = _int(row.get("diffs_recorded"))
    unmeasured = _dict(cost.get("unmeasured"))
    out = []
    for key, label, unit in _COST_KEYS:
        st = cost.get(key)
        if not isinstance(st, dict) or _int(st.get("n")) is None:
            out.append(f"  {label}: not measured: {_reason(unmeasured.get(key), 'absent from this file')}")
            continue
        n, total, top = _int(st.get("n")), _num(st.get("total")), _num(st.get("max"))
        mean = round(total / n, 3) if n and total is not None else None
        line = f"  {label}: {_n(n)} files measured, total {_n(total, unit)}, mean per file {_n(mean, unit)}, largest {_n(top, unit)}"
        if recorded is not None and n is not None and n < recorded:
            line += f" ({_n(recorded - n)} of {_n(recorded)} files did not measure it)"
        out.append(line)
    return out


def country_lines(row: dict[str, Any]) -> list[str]:
    code = _code(row.get("alpha3"))
    status = row.get("status") if isinstance(row.get("status"), str) and row.get("status", "").isidentifier() else "?"
    pos = _dict(row.get("position"))
    seq, ts = _int(pos.get("sequence")), _when(pos.get("timestamp"))
    src = pos.get("from") if pos.get("from") in ("change file", "extract") else None
    if seq is None:
        where = f"position not recorded: {_reason(pos.get('reason'), 'no reason given in this file')}"
    else:
        where = f"position {seq} from the {src or 'unnamed source'}" + (f", {ts}" if ts else f" (no time: {_reason(pos.get('reason'), 'none recorded')})")
    recorded = _int(row.get("diffs_recorded"))
    files = (f"{_n(recorded)} change files applied" if recorded is not None
             else f"change files: not recorded: {_reason(row.get('cost_reason'), 'absent from this file')}")
    last = _when(row.get("last_applied_at"))
    lines = [f"{code} ({status}): {where} · {files}" + (f" · last applied {last}" if last else "")]
    lines += cost_lines(row)
    gaps = _int(row.get("gaps_total"))
    if gaps is None:
        lines.append(f"  gaps: not recorded: {_reason(row.get('gaps_reason'), 'absent from this file')}")
    else:
        lines.append(f"  gaps: {_n(gaps)} (re-baselines {_n(row.get('rebaselines'))}, hand re-cuts {_n(row.get('hand_recuts_seen'))})"
                     + (f", {_n(row.get('gaps_not_shown'))} not shown" if _int(row.get("gaps_not_shown")) else ""))
    runs = [r for r in _list(row.get("runs")) if isinstance(r, dict)]
    for r in runs:
        lines.append(f"  file {_n(_int(r.get('sequence')))} of {_when(r.get('diff_timestamp')) or 'an unrecorded date'}: "
                     f"{_n(r.get('bytes_fetched'))} bytes, fetch {_n(r.get('fetch_seconds'), ' s')}, apply {_n(r.get('apply_seconds'), ' s')}")
    hidden = _int(row.get("runs_not_shown"))
    if hidden:
        lines.append(f"  {_n(hidden)} older files not shown (they are in the cost above)")
    return lines


def report(doc: dict[str, Any]) -> list[str]:
    """The read-back, one line per fact. An absent lane or a cut member says why instead of printing figures it does not have."""
    if "error" in doc and "countries" not in doc:
        return [f"the member could not be built: {_reason(doc.get('reason'), 'no reason given')}"]
    if doc.get("lane") == "absent":
        return [f"the OSM lane was not read: {_reason(doc.get('reason'), 'no reason given')}"]
    if doc.get("over_budget") is True:
        need = _int(doc.get("needs_at_least_bytes"))
        return [f"the member was omitted: {_reason(doc.get('omitted'), 'over its budget')}"
                + (f" (needs at least {_n(need)} bytes)" if need is not None else "")]
    rows = [r for r in _list(doc.get("countries")) if isinstance(r, dict)]
    lines = [f"{len(rows)} countries with change files or gaps"]
    for r in rows:
        lines += country_lines(r)
    without = [_code(c) for c in _list(doc.get("countries_without_updates"))]
    lines.append("countries no change file has touched: " + (", ".join(without) if without else "none"))
    cut = _dict(doc.get("dropped_to_fit"))
    dropped = [(k, _int(v)) for k, v in (("runs", cut.get("runs")), ("gaps", cut.get("gaps")),
                                         ("countries", doc.get("countries_not_shown")),
                                         ("untouched countries", doc.get("countries_without_updates_not_shown")))]
    shown = [f"{label} {_n(v)}" for label, v in dropped if v]
    lines.append("cut to fit the member's budget: " + (", ".join(shown) if shown else "nothing"))
    m = _dict(doc.get("measured_on"))
    if m:
        lines.append(f"measured on: {m.get('os') if isinstance(m.get('os'), str) and m.get('os', '').isalnum() else '—'}, "
                     f"{m.get('arch') if isinstance(m.get('arch'), str) and m.get('arch', '').replace('_', '').isalnum() else '—'}, "
                     f"{_n(_int(m.get('cpus')))} CPUs")
    sv = doc.get("street_view")
    if isinstance(sv, dict):
        state = sv.get("state") if sv.get("state") in ("measured", "not measured", "unreadable") else "?"
        when = _when(sv.get("measured_at"))
        lines.append(f"street view frame budget: {state}" + (f", {when}" if when else "")
                     + (f": {_reason(sv.get('reason'), 'no reason given')}" if state != "measured" else ""))
    else:
        lines.append("street view frame budget: absent from this file")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--json", action="store_true", help="print the member itself, as read")
    args = ap.parse_args(argv)
    try:
        doc = load(args.file)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"cannot read {args.file.name}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2, ensure_ascii=False) if args.json else "\n".join(report(doc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
